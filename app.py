import os
import io
import json
import logging
import re
from pathlib import Path

import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _looks_like_speech_key(value: str) -> bool:
    # 支援傳統 32 位十六進位 key 與新版較長的英數 key。
    if re.fullmatch(r"[0-9a-fA-F]{32}", value):
        return True
    return bool(re.fullmatch(r"[A-Za-z0-9]{40,128}", value))


def get_speech_config() -> speechsdk.SpeechConfig:
    # Allow both AZURE_* and legacy SPEECH_* variable names.
    speech_key = (os.getenv("AZURE_SPEECH_KEY") or os.getenv("SPEECH_KEY") or "").strip()
    speech_region = (os.getenv("AZURE_SPEECH_REGION") or os.getenv("SPEECH_REGION") or "eastasia").strip()
    speech_endpoint = (os.getenv("AZURE_SPEECH_ENDPOINT") or os.getenv("SPEECH_ENDPOINT") or "").strip()

    if not speech_key:
        raise ValueError("請設定 AZURE_SPEECH_KEY（或 SPEECH_KEY）")

    if not _looks_like_speech_key(speech_key):
        raise ValueError(
            "AZURE_SPEECH_KEY 格式看起來不正確。請填入 Azure Speech 資源的 Key1/Key2。"
        )

    if speech_endpoint and not speech_endpoint.startswith(("https://", "wss://")):
        raise ValueError("AZURE_SPEECH_ENDPOINT 格式錯誤，必須以 https:// 或 wss:// 開頭")

    if not speech_endpoint and not speech_region:
        raise ValueError("請設定 AZURE_SPEECH_REGION（或 SPEECH_REGION）")

    if speech_endpoint:
        config = speechsdk.SpeechConfig(endpoint=speech_endpoint, subscription=speech_key)
    else:
        config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
    return config


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/voices")
def list_voices():
    """列出可用語音，可用 ?locale=zh-TW 篩選語系"""
    locale_filter = request.args.get("locale", "")
    try:
        config = get_speech_config()
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=None)
        result = synthesizer.get_voices_async(locale_filter).get()

        if result.reason != speechsdk.ResultReason.VoicesListRetrieved:
            if result.reason == speechsdk.ResultReason.Canceled:
                msg = (getattr(result, "error_details", "") or "語音服務請求被取消").strip()
                return jsonify({"error": f"無法取得語音清單：{msg}"}), 500
            return jsonify({"error": f"無法取得語音清單，原因：{result.reason}"}), 500

        voices = [
            {
                "name": v.name,
                "short_name": v.short_name,
                "locale": v.locale,
                "gender": v.gender.name,
                "voice_type": v.voice_type.name,
            }
            for v in result.voices
        ]
        return jsonify(voices)
    except Exception as e:
        logger.exception("取得語音清單失敗")
        return jsonify({"error": str(e)}), 500


@app.route("/api/synthesize", methods=["POST"])
def synthesize():
    """將文字或 SSML 合成語音，回傳 audio/wav"""
    data = request.get_json(force=True)
    mode = data.get("mode", "text")      # "text" or "ssml"
    content = data.get("content", "").strip()
    voice = data.get("voice", "zh-TW-HsiaoChenNeural")
    rate = data.get("rate", "0%")        # e.g. "+10%", "-20%"
    pitch = data.get("pitch", "0%")      # e.g. "+5Hz"

    if not content:
        return jsonify({"error": "內容不能為空"}), 400

    try:
        config = get_speech_config()
        config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Riff16Khz16BitMonoPcm
        )

        stream = speechsdk.audio.PullAudioOutputStream()
        audio_config = speechsdk.audio.AudioOutputConfig(stream=stream)
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=config, audio_config=audio_config
        )

        if mode == "ssml":
            result = synthesizer.speak_ssml_async(content).get()
        else:
            # 將純文字包成 SSML 以支援語速/音調設定
            ssml = (
                f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-TW">'
                f'<voice name="{voice}">'
                f'<prosody rate="{rate}" pitch="{pitch}">'
                f'{content}'
                f'</prosody>'
                f'</voice>'
                f'</speak>'
            )
            result = synthesizer.speak_ssml_async(ssml).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            audio_data = result.audio_data
            return send_file(
                io.BytesIO(audio_data),
                mimetype="audio/wav",
                as_attachment=False,
                download_name="speech.wav",
            )

        if result.reason == speechsdk.ResultReason.Canceled:
            detail = speechsdk.SpeechSynthesisCancellationDetails(result)
            logger.error("合成取消：%s / %s", detail.reason, detail.error_details)
            return jsonify({"error": detail.error_details}), 500

        return jsonify({"error": "未知錯誤"}), 500

    except Exception as e:
        logger.exception("合成語音失敗")
        return jsonify({"error": str(e)}), 500


# ── Breeze-ASR 台語離線辨識 ──────────────────────────────────────────────

@app.route("/asr")
def asr_page():
    return render_template("asr.html")


@app.route("/api/transcribe", methods=["POST"])
def transcribe():
    """接收音訊檔（multipart/form-data 的 "audio" 欄位），回傳辨識結果。"""
    if "audio" not in request.files:
        return jsonify({"error": "請上傳音訊檔（欄位名稱：audio）"}), 400

    audio_file = request.files["audio"]
    filename = audio_file.filename or "audio.webm"
    audio_bytes = audio_file.read()

    if not audio_bytes:
        return jsonify({"error": "音訊檔案為空"}), 400

    try:
        from asr_breeze import transcribe as _transcribe
        text = _transcribe(audio_bytes, filename)
        return jsonify({"text": text})
    except Exception as e:
        logger.exception("語音辨識失敗")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)

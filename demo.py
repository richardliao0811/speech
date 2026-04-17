
'''
  For more samples please visit https://github.com/Azure-Samples/cognitive-services-speech-sdk
'''

import os
import azure.cognitiveservices.speech as speechsdk

# Creates an instance of a speech config with specified subscription key and service region.
# Never store secrets directly in source control. Use environment variables instead.
speech_key = os.environ.get("AZURE_SPEECH_KEY")
service_region = os.environ.get("AZURE_SPEECH_REGION", "eastus2")

if not speech_key:
    raise ValueError("AZURE_SPEECH_KEY environment variable is required")

speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)
# Note: the voice setting will not overwrite the voice element in input SSML.
# speech_config.speech_synthesis_voice_name = "en-US-BrandonMultilingualNeural"
speech_config.speech_synthesis_voice_name = "en-GB-MaisieNeural"

text = "Hi, this is Brandon Multilingual"

# use the default speaker as audio output.
speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config)

result = speech_synthesizer.speak_text_async(text).get()
# Check result
if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
    print("Speech synthesized for text [{}]".format(text))
elif result.reason == speechsdk.ResultReason.Canceled:
    cancellation_details = result.cancellation_details
    print("Speech synthesis canceled: {}".format(cancellation_details.reason))
    if cancellation_details.reason == speechsdk.CancellationReason.Error:
        print("Error details: {}".format(cancellation_details.error_details))
                
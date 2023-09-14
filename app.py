import time
from flask import Flask, render_template, request, redirect
import speech_recognition as sr
from datetime import datetime
from decouple import config
import os

import azure.cognitiveservices.speech as speechsdk
import openai

# This should not change unless you switch to a new version of the Speech REST API.
SPEECH_TRANSCRIPTION_PATH = "/speechtotext/v3.0/transcriptions"

# These should not change unless you switch to a new version of the Cognitive Language REST API.
SENTIMENT_ANALYSIS_PATH = "/language/:analyze-text"
SENTIMENT_ANALYSIS_QUERY = "?api-version=2022-05-01"
CONVERSATION_ANALYSIS_PATH = "/language/analyze-conversations/jobs"
CONVERSATION_ANALYSIS_QUERY = "?api-version=2022-05-15-preview"
CONVERSATION_SUMMARY_MODEL_VERSION = "2022-05-15-preview"

openai.api_type = "azure"
openai.api_version = "2023-03-15-preview"
COMPLETIONS_MODEL = "davinci"

openai.api_key = config('OPENAI_API_KEY')
openai.api_base = config('OPENAI_API_BASE')
subscription = config('SPEECH_KEY')
region = config('SPEECH_REGION')

# How long to wait while polling batch transcription and conversation analysis status.
WAIT_SECONDS = 10


# def AudioFileAdjust(fname, states=''):
#     '''
#     check audio file format and if not appropriate create new buffer audio for use
#     '''
#     if states == 'remove':
#         os.remove(fname)
#     else:
#         # if the file format not useful for Azure, first need to change -> fr: 16000 must be
#         audio_file = au.ReadAudioFile(fname)
#         if audio_file.frame_rate != int(16000):
#             # print('[Commend] changing the FrameRate')
#             audio_file_e = au.SetFramerate(audio_file, int(16000))
#             # change fine name for use
#             # without wav firstly and add additional
#             fname2 = fname.split(".")[0] + "_Conv_2" + ".wav"
#             au.ExportAudioFile(audio_file_e, fname2)
#             # print('new file name: ', fname)
#             fname = fname2
#     return fname

transcriptions = []

conversations = []

def conversation_transcriber_recognition_canceled_cb(evt: speechsdk.SessionEventArgs):
    print('Canceled event')


def conversation_transcriber_session_stopped_cb(evt: speechsdk.SessionEventArgs):
    print('SessionStopped event')

def conversation_transcriber_transcribed_cb(evt: speechsdk.SpeechRecognitionEventArgs):
    print('TRANSCRIBED:')
    if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
        print('\tText={}'.format(evt.result.text))
        print('\tSpeaker ID={}'.format(evt.result.speaker_id))
        conversations.append(
            {'text': evt.result.text, 'speaker_id': evt.result.speaker_id})
    elif evt.result.reason == speechsdk.ResultReason.NoMatch:
        print('\tNOMATCH: Speech could not be TRANSCRIBED: {}'.format(
            evt.result.no_match_details))


def conversation_transcriber_session_started_cb(evt: speechsdk.SessionEventArgs):
    print('SessionStarted event')


def transcribtion_transcribed_cb(evt: speechsdk.SpeechRecognitionEventArgs):

    if evt.result.reason == speechsdk.ResultReason.RecognizingSpeech:
        print('..recognizing...')
        # print('\tText={}'.format(evt.result.text))
    elif evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
        print('RECOGNIZED::')
        print('\tText={}'.format(evt.result.text))
        transcriptions.append(
            {'text': evt.result.text})
    elif evt.result.reason == speechsdk.ResultReason.NoMatch:
        print('\tNOMATCH: Speech could not be TRANSCRIBED: {}'.format(
            evt.result.no_match_details))


def recognize_from_file(conversation_transcriber):

    transcribing_stop = False

    def stop_cb(evt: speechsdk.SessionEventArgs):
        # """callback that signals to stop continuous recognition upon receiving an event `evt`"""
        print('CLOSING on {}'.format(evt))
        nonlocal transcribing_stop
        transcribing_stop = True

    # Connect callbacks to the events fired by the conversation transcriber
    conversation_transcriber.transcribed.connect(
        conversation_transcriber_transcribed_cb)
    conversation_transcriber.session_started.connect(
        conversation_transcriber_session_started_cb)
    conversation_transcriber.session_stopped.connect(
        conversation_transcriber_session_stopped_cb)
    conversation_transcriber.canceled.connect(
        conversation_transcriber_recognition_canceled_cb)
    # stop transcribing on either session stopped or canceled events
    conversation_transcriber.session_stopped.connect(stop_cb)
    conversation_transcriber.canceled.connect(stop_cb)

    conversation_transcriber.start_transcribing_async()

    # Waits for completion.
    while not transcribing_stop:
        time.sleep(.5)

    conversation_transcriber.stop_transcribing_async()


app = Flask(__name__)


@app.route("/", methods=["GET", "POST"])
def index():
    transcript = ""
    use_azure = True
    if request.method == "POST":
        print("FORM DATA RECEIVED")

        if "file" not in request.files:
            return redirect(request.url)

        file = request.files["file"]
        if file.filename == "":
            return redirect(request.url)

        if file:

            transcriptions.clear()
            conversations.clear()
            if use_azure:

                # Ensure the uploads directory exists
                os.makedirs('uploads', exist_ok=True)

                # Save the file to a location on your server
                filename = os.path.join('uploads', file.filename)
                file.save(filename)

                # Now you can use this filename with AudioConfig
                audio_config = speechsdk.AudioConfig(filename=filename)

                speech_config = speechsdk.SpeechConfig(
                    subscription=subscription, region=region)

                auto_detect_source_language_config = \
                    speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
                        languages=["fi-FI", "sv-SE", "en-US"])

                # Creates a speech recognizer using a file as audio input, also specify the speech language
                language_identifier = speechsdk.SpeechRecognizer(
                    speech_config=speech_config, audio_config=audio_config,
                    auto_detect_source_language_config=auto_detect_source_language_config)

                # Creates an audio stream format. For an example we are using MP3 compressed file here
                # compressed_format = speechsdk.audio.AudioStreamFormat(
                #     compressed_stream_format=speechsdk.AudioStreamContainerFormat.MP3)
                # callback = BinaryFileReaderCallback(
                #     filename=weatherfilenamemp3)
                # stream = speechsdk.audio.PullAudioInputStream(
                #     stream_format=compressed_format, pull_stream_callback=callback)
                # audio_config = speechsdk.audio.AudioConfig(stream=stream)

                # Detect language first
                result = language_identifier.recognize_once_async().get()
                auto_detect_source_language_result = speechsdk.AutoDetectSourceLanguageResult(
                    result)
                detected_language = auto_detect_source_language_result.language
                print(detected_language)

                transcript = f"Detected language: {detected_language}\n"

                speech_config.speech_recognition_language = detected_language
                # Creates a speech recognizer using a file as audio input, also specify the speech language
                speech_recognizer = speechsdk.SpeechRecognizer(
                    speech_config=speech_config, audio_config=audio_config)

                use_conversation_transcriber = True

                result = None
                # Transcribe the audio

                use_speech_transcriber = True

                if use_speech_transcriber:

                    try:
                        done = False

                        def stop_cb(evt: speechsdk.SessionEventArgs):
                            """callback that signals to stop continuous recognition upon receiving an event `evt`"""
                            print('CLOSING on {}'.format(evt))
                            nonlocal done
                            done = True

                        # Connect callbacks to the events fired by the speech recognizer
                        speech_recognizer.recognizing.connect(
                            transcribtion_transcribed_cb)
                        #    lambda evt: print('RECOGNIZING: {}'.format(evt)))
                        speech_recognizer.recognized.connect(
                            transcribtion_transcribed_cb)
                        #     lambda evt: print('RECOGNIZED: {}'.format(evt)))
                        speech_recognizer.session_started.connect(
                            lambda evt: print('SESSION STARTED: {}'.format(evt)))
                        speech_recognizer.session_stopped.connect(
                            lambda evt: print('SESSION STOPPED {}'.format(evt)))
                        speech_recognizer.canceled.connect(
                            lambda evt: print('CANCELED {}'.format(evt)))
                        # stop continuous recognition on either session stopped or canceled events
                        speech_recognizer.session_stopped.connect(stop_cb)
                        speech_recognizer.canceled.connect(stop_cb)

                        # Start continuous speech recognition
                        speech_recognizer.start_continuous_recognition()

                        while not done:
                            time.sleep(.5)

                        speech_recognizer.stop_continuous_recognition()

                        # result_future = speech_recognizer.start_continuous_recognition_async()
                        # print('recognition is running....')
                        # Other tasks can be performed here...

                        # Retrieve the recognition result. This blocks until recognition is complete.
                        # result = result_future.get()

                        if result:
                            transcript = transcript + result.text + \
                                f"\n\n(spoken in {detected_language})"
                        else:
                            transcript = transcript + "\nDetected speech:\n"
                            transcript = transcript + \
                                "\n".join([t['text'] for t in transcriptions])

                    except Exception as err:
                        print(
                            "Encountered exception in start_continuous_recognition:  {}".format(err))

                if use_conversation_transcriber:
                    try:
                        conversation_transcriber = speechsdk.transcription.ConversationTranscriber(
                            speech_config=speech_config, audio_config=audio_config)
                        recognize_from_file(conversation_transcriber)
                    except Exception as err:
                        print("Encountered exception. {}".format(err))

                # Combine all transcriptions into a single transcript
                conversation = " ".join(
                    [f"\n{t['speaker_id']}: {t['text']}" for t in conversations])

                transcript = transcript + \
                    f"\n\nDetected conversation:{conversation}"
            else:
                recognizer = sr.Recognizer()
                audioFile = sr.AudioFile(file)
                with audioFile as source:
                    data = recognizer.record(source)
                transcript = recognizer.recognize_google(
                    data, key=None, language="fi-FI")

            # Get current date and time
            now = datetime.now()

            # Format as string in the format YYYYMMDD_HH
            date_time_str = now.strftime("%Y%m%d_%H")

            # Use this string to create a filename
            filename = f"transcriptions_{date_time_str}.log"

            # Write the transcription to a file
            with open(filename, 'a', encoding='utf-8') as f:
                f.write(f"New transcpit at {now}\n")
                f.write(str(transcript))
                f.write("\n")

    res = render_template('index.html', transcript=transcript)
    
    return res


if __name__ == "__main__":
    app.run(debug=True, threaded=True)

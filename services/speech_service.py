"""
Speech-to-Text Service
Wraps the SpeechRecognition library to capture microphone input and return text.
The active engine is controlled by SPEECH_ENGINE in config.py.

When SPEECH_ENGINE = "azure":
  - AZURE_SPEECH_KEY is set  → Azure Speech SDK with the API key + AZURE_SPEECH_REGION.
  - AZURE_SPEECH_KEY is blank → keyless Entra auth (DefaultAzureCredential) using
    AZURE_SPEECH_REGION as the target region.
"""

import speech_recognition as sr
import os

from config import SPEECH_ENGINE, AZURE_SPEECH_KEY, AZURE_SPEECH_REGION, SPEECH_ENDPOINT, LLM_TENANT_ID

_KEY_PLACEHOLDER      = "YOUR_AZURE_SPEECH_KEY_HERE"
_REGION_PLACEHOLDERS  = frozenset({"YOUR_AZURE_REGION_HERE", ""})
_ENDPOINT_PLACEHOLDER = "YOUR_SPEECH_ENDPOINT_HERE"


class SpeechService:
    """Captures audio from the default microphone and transcribes it to text."""

    def __init__(self):
        self.recognizer = sr.Recognizer()
        # Slightly more aggressive energy threshold for typical office environments
        self.recognizer.dynamic_energy_threshold = True
        self._microphone_available = False
        self._continuous_recognizer = None
        self._init_microphone()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_microphone(self) -> None:
        """Test whether a microphone is available and calibrate noise level."""
        try:
            with sr.Microphone() as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            self._microphone_available = True
        except (OSError, AttributeError):
            self._microphone_available = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """True when a working microphone was detected at startup."""
        return self._microphone_available

    def listen(self, timeout: int = 10, phrase_time_limit: int = 30) -> str:
        """
        Block until speech is detected or *timeout* seconds elapse, then
        transcribe and return the spoken text.

        Raises:
            RuntimeError:          No microphone is available.
            sr.WaitTimeoutError:   No speech detected within *timeout* seconds.
            sr.UnknownValueError:  Speech was detected but could not be understood.
            sr.RequestError:       Recognition service returned an error.
        """
        if not self._microphone_available:
            raise RuntimeError(
                "No microphone detected. Check your audio device and try again."
            )

        with sr.Microphone() as source:
            audio = self.recognizer.listen(
                source,
                timeout=timeout,
                phrase_time_limit=phrase_time_limit,
            )

        return self._transcribe(audio)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _transcribe(self, audio: sr.AudioData) -> str:
        """Send *audio* to the configured recognition engine and return text."""
        engine = SPEECH_ENGINE.lower()

        if engine == "google":
            return self.recognizer.recognize_google(audio)

        elif engine == "azure":
            return self._transcribe_azure(audio)

        elif engine == "whisper":
            # Uses the local Whisper model bundled with speech_recognition
            return self.recognizer.recognize_whisper(audio, model="base")

        else:
            raise ValueError(
                f"Unknown SPEECH_ENGINE '{SPEECH_ENGINE}'. "
                "Valid values: 'google', 'azure', 'whisper'."
            )

    def _make_speech_config(self):
        """Build and return a SpeechConfig using whichever auth path is configured."""
        import azure.cognitiveservices.speech as speechsdk

        use_key      = bool(AZURE_SPEECH_KEY) and AZURE_SPEECH_KEY != _KEY_PLACEHOLDER
        has_endpoint = bool(SPEECH_ENDPOINT)  and SPEECH_ENDPOINT  != _ENDPOINT_PLACEHOLDER

        if use_key and has_endpoint:
            # Foundry / custom-domain: subscription + endpoint (no region).
            return speechsdk.SpeechConfig(
                subscription=AZURE_SPEECH_KEY,
                endpoint=SPEECH_ENDPOINT,
            )
        if use_key:
            if AZURE_SPEECH_REGION in _REGION_PLACEHOLDERS:
                raise RuntimeError("AZURE_SPEECH_REGION is not configured in config.py.")
            return speechsdk.SpeechConfig(
                subscription=AZURE_SPEECH_KEY,
                region=AZURE_SPEECH_REGION,
            )
        if has_endpoint:
            # Keyless with custom endpoint: pass the https:// URL directly.
            cfg = speechsdk.SpeechConfig(endpoint=SPEECH_ENDPOINT)
            cfg.authorization_token = self._get_speech_token()
            return cfg
        if AZURE_SPEECH_REGION not in _REGION_PLACEHOLDERS:
            # Keyless fallback: standard regional endpoint.
            return speechsdk.SpeechConfig(
                auth_token=self._get_speech_token(),
                region=AZURE_SPEECH_REGION,
            )
        raise RuntimeError("Configure SPEECH_ENDPOINT or AZURE_SPEECH_KEY in config.py.")

    def _transcribe_azure(self, audio: sr.AudioData) -> str:
        """Transcribe using the Azure Speech SDK.

        Supports API key auth (AZURE_SPEECH_KEY set) and keyless Entra auth
        (AZURE_SPEECH_KEY blank — uses DefaultAzureCredential with AZURE_SPEECH_REGION).
        """
        import azure.cognitiveservices.speech as speechsdk

        speech_config = self._make_speech_config()

        # Convert the captured audio to 16 kHz / 16-bit mono PCM and stream to the SDK.
        raw_pcm = audio.get_raw_data(convert_rate=16000, convert_width=2)
        fmt = speechsdk.audio.AudioStreamFormat(
            samples_per_second=16000, bits_per_sample=16, channels=1
        )
        stream = speechsdk.audio.PushAudioInputStream(stream_format=fmt)
        stream.write(raw_pcm)
        stream.close()

        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=speechsdk.audio.AudioConfig(stream=stream),
        )
        result = recognizer.recognize_once()

        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            return result.text
        if result.reason == speechsdk.ResultReason.NoMatch:
            raise sr.UnknownValueError()
        details = result.cancellation_details
        raise sr.RequestError(
            f"Azure speech recognition canceled ({details.reason}): {details.error_details}"
        )

    def _get_speech_token(self) -> str:
        """Obtain an Azure AD Bearer token for the Speech SDK authorization_token property."""
        from azure.identity import DefaultAzureCredential

        if LLM_TENANT_ID:
            os.environ.setdefault("AZURE_TENANT_ID", LLM_TENANT_ID)
        return DefaultAzureCredential().get_token(
            "https://cognitiveservices.azure.com/.default"
        ).token

    def start_continuous(self, on_recognizing, on_recognized, on_error) -> None:
        """Start continuous recognition, calling callbacks as speech arrives.

        Args:
            on_recognizing: called with partial text while the user is still speaking.
            on_recognized:  called with the final text for each completed utterance.
            on_error:       called with an error message string if recognition fails.
        """
        if not self._microphone_available:
            raise RuntimeError("No microphone detected.")
        if SPEECH_ENGINE.lower() != "azure":
            raise RuntimeError("Continuous recognition requires SPEECH_ENGINE = 'azure'.")
        import azure.cognitiveservices.speech as speechsdk

        speech_config = self._make_speech_config()
        audio_config  = speechsdk.audio.AudioConfig(use_default_microphone=True)
        rec = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)

        rec.recognizing.connect(lambda e: on_recognizing(e.result.text))
        rec.recognized.connect(
            lambda e: on_recognized(e.result.text)
            if e.result.reason == speechsdk.ResultReason.RecognizedSpeech else None
        )
        rec.canceled.connect(
            lambda e: on_error(
                f"Azure speech recognition canceled ({e.result.reason}): "
                f"{e.result.cancellation_details.error_details}"
            )
        )
        self._continuous_recognizer = rec
        rec.start_continuous_recognition_async()

    def stop_continuous(self) -> None:
        """Stop the continuous recogniser started by :meth:`start_continuous`."""
        if self._continuous_recognizer is not None:
            self._continuous_recognizer.stop_continuous_recognition_async().get()
            self._continuous_recognizer = None

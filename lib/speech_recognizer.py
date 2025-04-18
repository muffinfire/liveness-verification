# speech_recognizer.py

import threading
import time
import logging
import tempfile
from config import Config
from pocketsphinx import Decoder
import os

class SpeechRecognizer:
    """Handles real-time speech recognition for challenge verification using PocketSphinx on streamed audio."""

    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.last_speech = ""
        self.speech_lock = threading.Lock()
        self.last_speech_time = 0
        self.target_word = ""
        self.decoder = None # Initialize decoder to None

        # Create a temporary keyword file
        keywords = config.SPEECH_KEYWORDS
        
        try:
            # Ensure the temp file has a recognizable suffix if needed, though usually not required
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".kws") as tmp_f:
                self.keyword_file = tmp_f.name
                for word, threshold in keywords.items():
                    tmp_f.write(f"{word} /{threshold}/\n")
            self.logger.info(f"Keyword file created: {self.keyword_file}")
        except Exception as e:
            self.logger.error(f"Failed to create keyword file: {e}")
            self.keyword_file = None
            return # Stop initialization if keyword file fails

        # Initialize the PocketSphinx decoder
        try:
            model_path = 'models/en-us/'
            config_ps = Decoder.default_config()

            # Set necessary paths
            config_ps.set_string('-hmm', model_path)
            config_ps.set_string('-dict', os.path.join(model_path, 'cmudict-en-us.dict'))

            # Explicitly disable language model by setting it to None
            config_ps.set_string('-lm', None)

            # Enable keyword spotting
            config_ps.set_string('-kws', self.keyword_file)

            # Set sample rate
            config_ps.set_float('-samprate', config.SPEECH_SAMPLING_RATE)

            # Suppress PocketSphinx logs (optional)
            config_ps.set_string('-logfn', 'logs/speech_recognizer.log')

            # Initialize the decoder
            self.decoder = Decoder(config_ps)
            self.decoder.start_utt()
            self.logger.info("PocketSphinx decoder initialized successfully for keyword spotting.")

        except RuntimeError as e:
            self.logger.error(f"Failed to initialize PocketSphinx Decoder: {e}")
            self.decoder = None # Ensure decoder is None if init fails
        except Exception as e: # Catch other potential errors
            self.logger.error(f"An unexpected error occurred during PocketSphinx initialization: {e}")
            self.decoder = None

    def set_target_word(self, word: str) -> None:
        self.target_word = word.lower().strip()
        self.logger.info(f"Target word set to: {self.target_word}")
    
    def get_last_speech(self) -> str:
        with self.speech_lock:
            return self.last_speech
    
    def get_last_speech_time(self) -> float:
        with self.speech_lock:
            return self.last_speech_time
    
    def process_audio_chunk(self, audio_chunk: bytes) -> None:
        self.logger.debug(f"Processing audio chunk, size: {len(audio_chunk)}")

        # Add check: Do not process if decoder failed to initialize
        if self.decoder is None:
            self.logger.warning("Decoder not initialized, skipping audio processing.")
            return

        try:
            self.decoder.process_raw(audio_chunk, no_search=False, full_utt=False)
            hypothesis = self.decoder.hyp()
            if hypothesis is not None:
                detected_text = hypothesis.hypstr.lower().strip()
                now = time.time()
                recognized_keyword = None
                self.logger.info(f"Detected text: {detected_text}")

                # Check target word first
                if self.target_word and self.target_word in detected_text:
                     recognized_keyword = self.target_word
                     self.logger.info(f"Target word recognized: {recognized_keyword}")

                # Otherwise, check general keywords
                else:
                    for k in self.config.SPEECH_KEYWORDS:
                        if k in detected_text:
                            if k != "noise": # Treat noise differently or ignore based on goal
                                recognized_keyword = k
                                self.logger.info(f"Recognized keyword: {k} (full: '{detected_text}')")
                            else:
                                self.logger.info("Detected 'noise', ignoring.")
                            break # Stop after first match

                # Update state if a valid keyword was recognized
                if recognized_keyword and recognized_keyword != "noise":
                    with self.speech_lock:
                        self.last_speech = recognized_keyword
                        self.last_speech_time = now
                    # Reset utterance after successful detection
                    self.decoder.end_utt()
                    self.decoder.start_utt()

        except Exception as e:
            self.logger.error(f"Error processing audio chunk: {e}")
            # Consider restarting utterance on error?
            # try:
            #     self.decoder.end_utt()
            #     self.decoder.start_utt()
            # except Exception as restart_e:
            #     self.logger.error(f"Failed to restart utterance after error: {restart_e}")


    def reset(self) -> None:
        # Add check: Only reset if decoder exists
        if self.decoder is not None:
            try:
                with self.speech_lock:
                    self.last_speech = ""
                    self.last_speech_time = 0
                # Restart the utterance to clear internal state.
                self.decoder.end_utt()
                self.decoder.start_utt()
                self.logger.info("Speech recognizer reset.")
            except Exception as e:
                 self.logger.error(f"Error resetting PocketSphinx utterance: {e}")
        else:
            # Also reset local state even if decoder is None
             with self.speech_lock:
                self.last_speech = ""
                self.last_speech_time = 0
             self.logger.warning("Attempted to reset SpeechRecognizer, but decoder was not initialized.")

    # Consider adding a cleanup method if needed to delete the temp file
    # def cleanup(self):
    #     if self.keyword_file and os.path.exists(self.keyword_file):
    #         try:
    #             os.remove(self.keyword_file)
    #             self.logger.info(f"Removed temporary keyword file: {self.keyword_file}")
    #         except OSError as e:
    #             self.logger.error(f"Error removing temporary keyword file {self.keyword_file}: {e}")

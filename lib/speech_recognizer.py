# speech_recognizer.py
# This file is used to handle real-time speech recognition for challenge verification using PocketSphinx on streamed audio.

import threading
import time
import logging
import tempfile
from lib.config import Config
from pocketsphinx import Decoder
import os

# SpeechRecognizer class for real-time speech recognition using PocketSphinx
class SpeechRecognizer:

    # Initialise the SpeechRecognizer with the given configuration
    def __init__(self, config: Config):
        self.config = config # Store the configuration object for settings access
        self.logger = logging.getLogger(__name__) # Create logger instance for this module
        self.last_speech = "" # Last spoken word
        self.speech_lock = threading.Lock() # Lock for thread-safe access to last speech (Used to prevent race conditions)
        self.last_speech_time = 0 # Time of last speech
        self.target_word = "" # Target word to recognize
        self.decoder = None # Initialise decoder to None

        # Create a temporary keyword file (Used to store the keywords and their thresholds)
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
            return # Stop initialisation if keyword file fails

        # Initialise the PocketSphinx decoder
        try:
            model_path = 'models/en-us/' # Path to the PocketSphinx model
            config_ps = Decoder.default_config() # Create a default configuration for the decoder

            # Set necessary paths
            config_ps.set_string('-hmm', model_path) # Set the path to the PocketSphinx model
            config_ps.set_string('-dict', os.path.join(model_path, 'cmudict-en-us.dict')) # Set the path to the PocketSphinx dictionary

            # Explicitly disable language model by setting it to None
            config_ps.set_string('-lm', None) # Set the language model to None

            # Enable keyword spotting
            config_ps.set_string('-kws', self.keyword_file) # Set the keyword file

            # Set sample rate
            config_ps.set_float('-samprate', config.SPEECH_SAMPLING_RATE) # Set the sample rate (Default is 16000 but 48000 is default in Chrome)

            # Suppress PocketSphinx logs (optional)
            config_ps.set_string('-logfn', 'speech_recognizer.log')

            # Initialise the decoder
            self.decoder = Decoder(config_ps) # Initialise the decoder with the configuration
            self.decoder.start_utt() # Start the utterance (Used to clear internal state. Utterance is the process of recognising speech)
            self.logger.info("PocketSphinx decoder initialised successfully for keyword spotting.")

        except RuntimeError as e:
            self.logger.error(f"Failed to initialise PocketSphinx Decoder: {e}")
            self.decoder = None # Ensure decoder is None if init fails
        except Exception as e: # Catch other potential errors
            self.logger.error(f"An unexpected error occurred during PocketSphinx initialisation: {e}")
            self.decoder = None

    # Set the target word to recognize
    def set_target_word(self, word: str) -> None:
        self.target_word = word.lower().strip() # Set the target word
        self.logger.info(f"Target word set to: {self.target_word}")
    
    # Get the last spoken word
    def get_last_speech(self) -> str:
        with self.speech_lock:
            return self.last_speech
    
    # Get the time of the last spoken word
    def get_last_speech_time(self) -> float:
        with self.speech_lock:
            return self.last_speech_time
    
    # Process an audio chunk for speech recognition
    def process_audio_chunk(self, audio_chunk: bytes) -> None:
        self.logger.debug(f"Processing audio chunk, size: {len(audio_chunk)}")

        # Add check: Do not process if decoder failed to initialise
        if self.decoder is None:
            self.logger.warning("Decoder not initialised, skipping audio processing.")
            return

        try:
            self.decoder.process_raw(audio_chunk, no_search=False, full_utt=False) # Process the audio chunk (no_search=False, full_utt=False) false because we want to recognise the word
            hypothesis = self.decoder.hyp() # Get the hypothesis (The hypothesis is the recognised word)
            if hypothesis is not None:
                detected_text = hypothesis.hypstr.lower().strip() # Get the detected text (The detected text is the recognised word)
                now = time.time()
                recognized_keyword = None
                self.logger.info(f"Detected text: {detected_text}")

                # Check target word first (The target word is the word we want to recognise)
                if self.target_word and self.target_word in detected_text:
                    recognized_keyword = self.target_word  # Set the recognised keyword to the target word 
                    self.logger.info(f"Target word recognized: {recognized_keyword}")

                # Otherwise, check general keywords (The general keywords are the words we want to recognise)
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

    # Reset the speech recognizer
    def reset(self) -> None:
        # Add check: Only reset if decoder exists
        if self.decoder is not None:
            try:
                with self.speech_lock:
                    self.last_speech = "" # Reset the last spoken word
                    self.last_speech_time = 0 # Reset the time of the last spoken word
                # Restart the utterance to clear internal state.
                self.decoder.end_utt() # End the utterance
                self.decoder.start_utt() # Start the utterance
                self.logger.info("Speech recognizer reset.")
            except Exception as e:
                 self.logger.error(f"Error resetting PocketSphinx utterance: {e}")
        else:
            # Also reset local state even if decoder is None
             with self.speech_lock:
                self.last_speech = ""
                self.last_speech_time = 0
             self.logger.warning("Attempted to reset SpeechRecognizer, but decoder was not initialised.")
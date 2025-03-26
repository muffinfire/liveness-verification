"""Speech recognition module for challenge verification using PocketSphinx."""

import speech_recognition as sr
import threading
import time
import logging
import tempfile
from config import Config
from pocketsphinx import LiveSpeech

class SpeechRecognizer:
    """Handles real-time speech recognition for challenge verification using PocketSphinx."""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        self.last_speech = ""
        self.speech_lock = threading.Lock()
        self.last_speech_time = 0
        self.running = False
        self.speech_thread = None
        self.speech_ready = False
        self.target_word = ""  # default target word is empty
        
        try:
            self.logger.info("Initializing PocketSphinx...")
            keywords = config.SPEECH_KEYWORDS
            self.keyword_file = tempfile.NamedTemporaryFile(mode='w', delete=False).name
            with open(self.keyword_file, "w") as f:
                for kw in keywords:
                    f.write(kw + "\n")
            
            self.logger.info(f"Keyword file: {self.keyword_file}")
            
            self.microphone = sr.Microphone()
            with self.microphone as source:
                self.logger.info("Calibrating microphone for ambient noise (0.5s)...")
                sr.Recognizer().adjust_for_ambient_noise(source, duration=0.5)
            
            self.speech = LiveSpeech(
                verbose=False,
                sampling_rate=config.SPEECH_SAMPLING_RATE,
                buffer_size=config.SPEECH_BUFFER_SIZE,
                no_search=False,
                full_utt=False,
                kws=self.keyword_file
            )
            self.speech_ready = True
            self.logger.info("PocketSphinx ready.")
        except ImportError:
            self.logger.error("Could not import pocketsphinx. Please install via pip")
            self.speech_ready = False
        except Exception as e:
            self.logger.error(f"Error initializing pocketsphinx: {e}")
            self.speech_ready = False

    def set_target_word(self, word: str) -> None:
        self.target_word = word.lower().strip()
        self.logger.info(f"Target word set to: {self.target_word}")
    
    def listen_for_speech(self) -> None:
        if not self.speech_ready:
            self.logger.warning("Speech recognition not available")
            return
        
        self.logger.info("Speech recognition thread started")
        self.running = True
        last_detected_word = None
        last_time = 0
        
        try:
            for phrase in self.speech:
                if not self.running:
                    break
                text = str(phrase).lower()
                now = time.time()
                
                # If a target word is set, check if it appears in the phrase.
                if self.target_word and self.target_word in text:
                    with self.speech_lock:
                        self.last_speech = self.target_word
                        self.last_speech_time = now
                    self.logger.info(f"Target word recognized: {self.target_word}")
                    continue

                # Otherwise, process recognized keywords.
                possible_keywords = ["blue", "red", "sky", "ground", "hello", "noise"]
                first_word = None
                for k in possible_keywords:
                    if k in text:
                        first_word = k
                        break
                if first_word:
                    if first_word == "noise":
                        with self.speech_lock:
                            self.last_speech = ""
                            self.last_speech_time = now
                        last_detected_word = first_word
                        last_time = now
                        self.logger.debug("Detected 'noise' => ignoring")
                    else:
                        # Avoid spamming if the same word repeats in <1s
                        if (first_word != last_detected_word) or ((now - last_time) > 1.0):
                            with self.speech_lock:
                                self.last_speech = first_word
                                self.last_speech_time = now
                            self.logger.info(f"Recognized: {first_word} (full: '{text}')")
                            last_detected_word = first_word
                            last_time = now
                else:
                    self.logger.debug(f"No recognized keyword in '{text}'")
        except Exception as e:
            self.logger.error(f"Error in speech recognition: {e}")
        finally:
            self.running = False
            self.logger.info("Speech recognition thread ended")
    
    def start_listening(self) -> None:
        if not self.speech_ready:
            self.logger.warning("Speech not available")
            return
        if not self.running and (self.speech_thread is None or not self.speech_thread.is_alive()):
            self.speech_thread = threading.Thread(target=self.listen_for_speech, daemon=True)
            self.speech_thread.start()
    
    def stop(self) -> None:
        self.running = False
        if self.speech_thread and self.speech_thread.is_alive():
            self.logger.info("Stopping speech thread...")
            self.speech_thread.join(timeout=1.0)
    
    def get_last_speech(self) -> str:
        with self.speech_lock:
            return self.last_speech
    
    def get_last_speech_time(self) -> float:
        with self.speech_lock:
            return self.last_speech_time
    
    def reset(self) -> None:
        with self.speech_lock:
            self.last_speech = ""
            self.last_speech_time = 0

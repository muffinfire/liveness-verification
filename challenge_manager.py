"""Challenge management module for liveness verification."""

import time
import random
import logging
from typing import Optional, Tuple

from config import Config

class ChallengeManager:
    """Manages challenge issuance and verification."""

    def __init__(self, config: Config, speech_recognizer=None, blink_detector=None):
        self.config = config
        self.speech_recognizer = speech_recognizer
        self.blink_detector = blink_detector
        self.logger = logging.getLogger(__name__)

        self.current_challenge = None
        self.challenge_completed = False
        self.challenge_start_time = None
        self.challenge_timeout = config.CHALLENGE_TIMEOUT
        self.available_challenges = config.CHALLENGES
        self.verification_result = None

        # Speech tracking
        self.last_speech_time = None
        self.used_speech_time = None
        self.last_speech_word = None

    def issue_new_challenge(self) -> str:
        # Generate a random challenge by combining an action and a speech keyword
        action = random.choice(self.config.ACTIONS)
        
        # Get keys from SPEECH_KEYWORDS dictionary
        speech_keywords = list(self.config.SPEECH_KEYWORDS.keys())
        
        # Filter out 'noise' which is not a real keyword for challenges
        for unwanted in ('noise', 'verify'):
            if unwanted in speech_keywords:
                speech_keywords.remove(unwanted)
        
        word = random.choice(speech_keywords)

        # Combine action and word to form a challenge
        self.current_challenge = f"{action} and say {word}"
        
        self.challenge_start_time = time.time()
        self.challenge_completed = False
        self.verification_result = None
        self.last_speech_time = None
        self.used_speech_time = None
        self.last_speech_word = None

        if self.speech_recognizer:
            self.speech_recognizer.reset()
            self.speech_recognizer.set_target_word(word)

        if self.blink_detector:
            self.blink_detector.reset()
            self.logger.debug("Blink counter reset for new challenge")

        self.logger.info(f"New challenge issued: {self.current_challenge}")
        return self.current_challenge

    def verify_challenge(self, head_pose: str, blink_counter: int, last_speech: str) -> bool:
        if self.current_challenge is None:
            return False

        current_time = time.time()
        self.logger.debug(f"Verifying - Head: {head_pose}, Blinks: {blink_counter}, Speech: '{last_speech}'")

        # Timeout check
        if current_time - self.challenge_start_time > self.challenge_timeout:
            self.verification_result = "FAIL"
            self.current_challenge = None
            if self.speech_recognizer:
                self.speech_recognizer.reset()
            self.logger.info("Challenge timed out")
            return True

        c = self.current_challenge.lower()
        target_word = c.split("say ")[-1]

        # Handle duress word
        if last_speech.lower() == "verify":
            self.challenge_completed = True
            self.verification_result = "FAIL"
            self.current_challenge = None
            if self.speech_recognizer:
                self.speech_recognizer.reset()
            self.logger.info("Challenge exited due to duress 'verify'")
            return True

        # ACTION DETECTION
        action_is_happening = False
        if "turn left" in c and head_pose == "left":
            action_is_happening = True
            self.logger.debug("LEFT action is happening")
        elif "turn right" in c and head_pose == "right":
            action_is_happening = True
            self.logger.debug("RIGHT action is happening")
        elif "look up" in c and head_pose == "up":
            action_is_happening = True
            self.logger.debug("UP action is happening")
        elif "look down" in c and head_pose == "down":
            action_is_happening = True
            self.logger.debug("DOWN action is happening")
        elif "blink twice" in c and blink_counter >= 3:
            action_is_happening = True
            self.logger.debug(f"BLINK action is happening (Counter: {blink_counter})")

        # SPEECH LOCK-IN LOGIC
        word_is_happening = False

        # Lock the speech time only once (on first valid detection)
        if (
            last_speech and
            last_speech.lower() == target_word and
            self.last_speech_time is None
        ):
            self.last_speech_time = current_time
            self.last_speech_word = last_speech.lower()
            self.logger.debug(f"Registered speech for word '{last_speech}' at {current_time}")

        # Now check if word is still valid within the time window
        if (
            self.last_speech_word == target_word and
            self.last_speech_time and
            abs(current_time - self.last_speech_time) <= self.config.ACTION_SPEECH_WINDOW and
            self.used_speech_time != self.last_speech_time  # prevent reuse
        ):
            word_is_happening = True
            self.logger.debug(f"WORD '{target_word}' detected within time window (diff: {abs(current_time - self.last_speech_time):.2f}s)")
        elif self.last_speech_time:
            self.logger.debug(f"Speech too old: {current_time - self.last_speech_time:.2f}s")

        # FINAL VERIFICATION
        if action_is_happening and word_is_happening:
            self.challenge_completed = True
            self.verification_result = "PASS"
            self.used_speech_time = self.last_speech_time
            self.current_challenge = None
            if self.speech_recognizer:
                self.speech_recognizer.reset()
            self.logger.debug(f"Challenge PASSED! {self.current_challenge}")   
            self.logger.info(f"Action: {action_is_happening} and speech: {word_is_happening}")
            return True

        return False


    def get_challenge_status(self, head_pose: str, blink_counter: int, last_speech: str) -> Tuple[Optional[str], bool, bool, Optional[str]]:
        if not self.current_challenge:
            return (None, False, False, self.verification_result)

        c = self.current_challenge.lower()
        action = (
            ("turn left" in c and head_pose == "left") or
            ("turn right" in c and head_pose == "right") or
            ("look up" in c and head_pose == "up") or
            ("look down" in c and head_pose == "down") or
            ("blink twice" in c and blink_counter >= 2)
        )

        word = c.split("say ")[-1] if "say " in c else ""
        
        # Check if word was spoken within the required time window (1.5 seconds)
        word_in_time_window = False
        if self.last_speech_word == word and self.last_speech_time:
            time_diff = time.time() - self.last_speech_time
            word_in_time_window = time_diff <= self.config.ACTION_SPEECH_WINDOW
            
        # Word status is true only if the word matches AND is within time window
        word_status = last_speech.lower() == word and word_in_time_window
        
        return (self.current_challenge, action, word_status, self.verification_result)

    def get_challenge_time_remaining(self) -> float:
        if self.current_challenge is None or self.challenge_start_time is None:
            return 0
        elapsed = time.time() - self.challenge_start_time
        return max(0, self.challenge_timeout - elapsed)

    def update(self, head_pose: str, blink_counter: int, last_speech: str) -> None:
        if self.current_challenge:
            self.verify_challenge(head_pose, blink_counter, last_speech)

    def reset(self) -> None:
        self.current_challenge = None
        self.challenge_completed = False
        self.challenge_start_time = None
        self.verification_result = None
        self.last_speech_time = None
        self.used_speech_time = None
        self.last_speech_word = None
        self.logger.info("ChallengeManager reset")
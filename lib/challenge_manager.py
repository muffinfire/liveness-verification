"""Challenge management module for liveness verification."""

import time
import random
import logging
from typing import Optional, Tuple

from lib.config import Config

class ChallengeManager:
    """Handles the lifecycle of challenges, including generation, verification, and tracking."""

    def __init__(self, config: Config, speech_recognizer=None, blink_detector=None):
        # Store config and input modules for interaction
        self.config = config
        self.speech_recognizer = speech_recognizer
        self.blink_detector = blink_detector

        # Set up logger
        self.logger = logging.getLogger(__name__)

        # Internal state tracking
        self.current_challenge = None                      # The current active challenge (e.g. "turn left and say fish")
        self.challenge_completed = False                   # True if current challenge has been passed
        self.challenge_start_time = None                   # Timestamp when current challenge was issued
        self.challenge_timeout = config.CHALLENGE_TIMEOUT  # Max time allowed for the challenge
        self.available_actions = config.ACTIONS            # List of possible actions (head/blink)
        self.available_keywords = list(config.SPEECH_KEYWORDS.keys())  # List of allowed speech keywords
        self.verification_result = None                    # "PASS", "FAIL", or None

        # Speech detection tracking
        self.last_speech_time = None                       # When the last valid keyword was spoken
        self.used_speech_time = None                       # Placeholder, not currently used
        self.last_speech_word = None                       # What word was last spoken

    def issue_new_challenge(self) -> str:
        # Randomly choose a challenge (action + keyword)
        action = random.choice(self.available_actions)

        # Exclude special-case words like 'verify' and 'noise'
        valid_keywords = [word for word in self.available_keywords if word != 'verify' and word != 'noise']
        keyword = random.choice(valid_keywords)

        # Compose full challenge phrase
        self.current_challenge = f"{action} and say {keyword}"
        self.challenge_start_time = time.time()

        # Reset all state flags and speech tracking
        self.challenge_completed = False
        self.verification_result = None
        self.last_speech_time = None
        self.used_speech_time = None
        self.last_speech_word = None

        # Reset and configure speech recognizer with target keyword
        if self.speech_recognizer:
            self.speech_recognizer.reset()
            word = self.current_challenge.lower().split("say ")[-1]
            self.speech_recognizer.set_target_word(word)

        # Reset blink detector state if present
        if self.blink_detector:
            self.blink_detector.reset()
            self.logger.debug("Blink counter reset for new challenge")

        self.logger.info(f"New challenge issued: {self.current_challenge}")
        return self.current_challenge

    def verify_challenge(self, head_pose: str, blink_counter: int, last_speech: str) -> bool:
        # Bail if no challenge is active
        if self.current_challenge is None:
            return False

        current_time = time.time()
        self.logger.debug(f"Verifying - Head: {head_pose}, Blinks: {blink_counter}, Speech: '{last_speech}'")

        # Handle timeout: too much time has passed since issuing challenge
        if current_time - self.challenge_start_time > self.challenge_timeout:
            self.verification_result = "FAIL"
            self.current_challenge = None
            if self.speech_recognizer:
                self.speech_recognizer.reset()
            self.logger.info("Challenge timed out")
            return True

        # Extract the target keyword from the challenge string
        c = self.current_challenge.lower()
        target_word = c.split("say ")[-1]

        # Special-case handling for duress keyword "verify"
        if last_speech.lower() == "verify":
            self.challenge_completed = True
            self.verification_result = "FAIL"
            self.current_challenge = None
            if self.speech_recognizer:
                self.speech_recognizer.reset()
            self.logger.info("Challenge exited due to duress 'verify'")
            return True

        # Check whether the required physical action is happening right now
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
        elif "blink twice" in c and blink_counter >= self.config.BLINK_COUNTER_THRESHOLD:
            action_is_happening = True
            self.logger.debug(f"BLINK action is happening (Counter: {blink_counter})")

        word_is_happening = False

        # If a previously spoken keyword has expired, clear it
        if (
            self.last_speech_word == target_word and
            self.last_speech_time is not None and
            (current_time - self.last_speech_time) > self.config.ACTION_SPEECH_WINDOW
        ):
            self.logger.debug(f"Speech for '{self.last_speech_word}' expired (diff: {current_time - self.last_speech_time:.2f}s)")
            self.last_speech_time = None
            self.last_speech_word = None

        # Register new speech if it's valid and not a recent duplicate
        if (
            last_speech and last_speech.lower() == target_word and
            (self.last_speech_word != target_word or
             self.last_speech_time is None or
             (current_time - self.last_speech_time) > self.config.ACTION_SPEECH_WINDOW)
        ):
            self.last_speech_time = current_time
            self.last_speech_word = target_word
            self.logger.debug(f"Registered NEW speech for word '{last_speech}' at {current_time}")

            # Immediately reset recognizer so it doesn't keep spamming duplicates
            if self.speech_recognizer:
                self.speech_recognizer.reset()
                self.logger.debug("Speech recognizer reset after word registration")

            self.logger.debug(f"Last speech time: {self.last_speech_time}")
            self.logger.debug(f"Current time: {current_time}")
            self.logger.debug(f"Time difference: {current_time - self.last_speech_time}")
        else:
            self.logger.debug(f"Ignored duplicate speech '{last_speech}' (still inside window)")

        # Check if the stored keyword is still valid within the speech window
        if (
            self.last_speech_word == target_word and
            self.last_speech_time is not None and
            (current_time - self.last_speech_time) <= self.config.ACTION_SPEECH_WINDOW
        ):
            word_is_happening = True
            self.logger.debug(f"WORD '{target_word}' detected within time window (diff: {current_time - self.last_speech_time:.2f}s)")
        elif self.last_speech_time:
            self.logger.debug(f"Speech too old: {current_time - self.last_speech_time:.2f}s")

        # FINAL VERIFICATION CHECK
        if action_is_happening and word_is_happening and blink_counter >= self.config.BLINK_COUNTER_THRESHOLD:
            self.challenge_completed = True
            self.verification_result = "PASS"
            self.current_challenge = None
            if self.speech_recognizer:
                self.speech_recognizer.reset()
            self.logger.debug(f"Challenge PASSED! {self.current_challenge}")   
            self.logger.info(f"Action: {action_is_happening} and speech: {word_is_happening}")
            return True

        return False

    def get_challenge_status(self, head_pose: str, blink_counter: int, last_speech: str) -> Tuple[Optional[str], bool, bool, Optional[str]]:
        # Returns current challenge, whether action is happening, whether speech is valid, and result if any
        if not self.current_challenge:
            return (None, False, False, self.verification_result)

        c = self.current_challenge.lower()
        action = (
            ("turn left" in c and head_pose == "left") or
            ("turn right" in c and head_pose == "right") or
            ("look up" in c and head_pose == "up") or
            ("look down" in c and head_pose == "down") or
            ("blink twice" in c and blink_counter >= self.config.BLINK_COUNTER_THRESHOLD)
        )

        word = c.split("say ")[-1] if "say " in c else ""

        # Check if word is still within valid speech window
        word_in_time_window = False
        if self.last_speech_word == word and self.last_speech_time:
            time_diff = time.time() - self.last_speech_time
            word_in_time_window = time_diff <= self.config.ACTION_SPEECH_WINDOW

        word_status = word_in_time_window

        return (self.current_challenge, action, word_status, self.verification_result)

    def get_challenge_time_remaining(self) -> float:
        # Returns how many seconds are left before the current challenge times out
        if self.current_challenge is None or self.challenge_start_time is None:
            return 0
        elapsed = time.time() - self.challenge_start_time
        return max(0, self.challenge_timeout - elapsed)

    def update(self, head_pose: str, blink_counter: int, last_speech: str) -> None:
        # Trigger verification on each update loop/frame
        if self.current_challenge:
            self.verify_challenge(head_pose, blink_counter, last_speech)

    def reset(self) -> None:
        # Fully reset challenge state
        self.current_challenge = None
        self.challenge_completed = False
        self.challenge_start_time = None
        self.verification_result = None
        self.last_speech_time = None
        self.used_speech_time = None
        self.last_speech_word = None
        self.logger.info("ChallengeManager reset")

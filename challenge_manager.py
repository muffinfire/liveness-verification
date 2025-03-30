"""Challenge management module for liveness verification."""

import time
import random
import logging
from typing import Optional, Tuple

from config import Config

class ChallengeManager:
    """Manages challenge issuance and verification."""
    
    def __init__(self, config: Config, speech_recognizer=None, blink_detector=None):
        # Initialize with configuration and optional detectors
        self.config = config
        self.speech_recognizer = speech_recognizer  # Speech recognition component
        self.blink_detector = blink_detector       # Blink detection component
        self.logger = logging.getLogger(__name__)  # Logger for debugging
        
        # Challenge state variables
        self.current_challenge = None             # Current active challenge
        self.challenge_completed = False          # Completion status
        self.challenge_start_time = None          # Timestamp of challenge start
        self.challenge_timeout = config.CHALLENGE_TIMEOUT  # Timeout duration from config
        self.available_challenges = config.CHALLENGES      # List of possible challenges
        self.verification_result = None           # Result of verification (PASS/FAIL)
        self.last_speech_time = None              # Timestamp of last detected speech
    
    def issue_new_challenge(self) -> str:
        # Select and initialize a new random challenge
        self.current_challenge = random.choice(self.available_challenges)
        self.challenge_start_time = time.time()
        self.challenge_completed = False
        self.verification_result = None
        self.last_speech_time = None
        
        # Reset and configure speech recognizer if present
        if self.speech_recognizer:
            self.speech_recognizer.reset()
            word = self.current_challenge.lower().split("say ")[-1]
            self.speech_recognizer.set_target_word(word)
        
        # Reset blink detector if present
        if self.blink_detector:
            self.blink_detector.reset()
            self.logger.debug("Blink counter reset for new challenge")
        
        self.logger.info(f"New challenge issued: {self.current_challenge}")
        return self.current_challenge
    
    def verify_challenge(self, head_pose: str, blink_counter: int, last_speech: str) -> bool:
        # Check if there's an active challenge
        if self.current_challenge is None:
            return False
        
        # Log verification inputs for debugging
        self.logger.debug(f"Verifying - Head: {head_pose}, Blinks: {blink_counter}, Speech: '{last_speech}'")
        
        # Check for timeout
        elapsed = time.time() - self.challenge_start_time
        if elapsed > self.challenge_timeout:
            self.verification_result = "FAIL"
            self.current_challenge = None
            if self.speech_recognizer:
                self.speech_recognizer.reset()
            self.logger.info("Challenge timed out")
            return True
        
        c = self.current_challenge.lower()
        current_time = time.time()
        
        # Update last speech timestamp if speech detected
        if last_speech and last_speech.strip():
            self.last_speech_time = current_time
        
        action_is_happening = False
        # Check for head movement challenges
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
        # Check for blink challenge
        elif "blink twice" in c and blink_counter >= 2:
            action_is_happening = True
            self.logger.debug(f"BLINK action is happening (Counter: {blink_counter})")
        
        # Check for speech challenge
        word = c.split("say ")[-1]
        word_is_happening = last_speech.lower() == word
        if word_is_happening:
            self.logger.debug(f"WORD '{word}' detected")
        
        # Verify if both action and speech occur simultaneously
        if action_is_happening and word_is_happening:
            self.challenge_completed = True
            self.verification_result = "PASS"
            self.current_challenge = None
            if self.speech_recognizer:
                self.speech_recognizer.reset()
            self.logger.info("Challenge PASSED! Action and speech concurrent")
            return True
        # Verify if action occurs within 1 second of speech
        elif action_is_happening and self.last_speech_time:
            diff = current_time - self.last_speech_time
            if diff <= 1.0:
                self.challenge_completed = True
                self.verification_result = "PASS"
                self.current_challenge = None
                if self.speech_recognizer:
                    self.speech_recognizer.reset()
                self.logger.info(f"Challenge PASSED! Action with recent speech (diff: {diff:.2f}s)")
                return True
        
        return False
    
    def get_challenge_status(self, head_pose: str, blink_counter: int, last_speech: str) -> Tuple[Optional[str], bool, bool, Optional[str]]:
        # Return current challenge status if no active challenge
        if not self.current_challenge:
            return (None, False, False, self.verification_result)
        
        c = self.current_challenge.lower()
        # Check if required action is being performed
        action = (
            ("turn left" in c and head_pose == "left") or
            ("turn right" in c and head_pose == "right") or
            ("look up" in c and head_pose == "up") or
            ("look down" in c and head_pose == "down") or
            ("blink twice" in c and blink_counter >= 2)
        )
        # Check if required word is spoken
        word = c.split("say ")[-1] if "say " in c else ""
        word_status = last_speech.lower() == word
        return (self.current_challenge, action, word_status, self.verification_result)
    
    def get_challenge_time_remaining(self) -> float:
        # Calculate and return remaining time for active challenge
        if self.current_challenge is None or self.challenge_start_time is None:
            return 0
        elapsed = time.time() - self.challenge_start_time
        return max(0, self.challenge_timeout - elapsed)
    
    def update(self, head_pose: str, blink_counter: int, last_speech: str) -> None:
        # Update challenge verification if there's an active challenge
        if self.current_challenge:
            self.verify_challenge(head_pose, blink_counter, last_speech)
    
    def reset(self) -> None:
        # Reset all challenge-related state variables
        self.current_challenge = None
        self.challenge_completed = False
        self.challenge_start_time = None
        self.verification_result = None
        self.last_speech_time = None
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
        self.challenge_action_completed = False
        self.challenge_word_completed = False
        self.verification_result = None
        self.action_completion_time = None
        self.word_completion_time = None
    
    def issue_new_challenge(self) -> str:
        self.current_challenge = random.choice(self.available_challenges)
        self.challenge_start_time = time.time()
        self.challenge_completed = False
        self.challenge_action_completed = False
        self.challenge_word_completed = False
        self.verification_result = None
        self.action_completion_time = None
        self.word_completion_time = None
        
        if self.speech_recognizer:
            self.speech_recognizer.reset()
        if self.blink_detector:
            self.blink_detector.reset()
            self.logger.debug("Blink counter reset for new challenge")
        
        self.logger.info(f"New challenge issued: {self.current_challenge}")
        return self.current_challenge
    
    def verify_challenge(self, head_pose: str, blink_counter: int, last_speech: str) -> bool:
        if self.current_challenge is None:
            return False
        
        self.logger.debug(f"Verifying - Head: {head_pose}, Blinks: {blink_counter}, Speech: '{last_speech}'")
        
        elapsed = time.time() - self.challenge_start_time
        if elapsed > self.challenge_timeout:
            self.verification_result = "FAIL"
            self.current_challenge = None
            if self.speech_recognizer:
                self.speech_recognizer.reset()
            self.logger.info("Challenge timed out")
            return True
        
        c = self.current_challenge.lower()
        
        # Action check
        if not self.challenge_action_completed:
            if "turn left" in c and head_pose=="left":
                self.challenge_action_completed=True
                self.action_completion_time=time.time()
                self.logger.debug("LEFT ACTION COMPLETED!")
            elif "turn right" in c and head_pose=="right":
                self.challenge_action_completed=True
                self.action_completion_time=time.time()
                self.logger.debug("RIGHT ACTION COMPLETED!")
            elif "look up" in c and head_pose=="up":
                self.challenge_action_completed=True
                self.action_completion_time=time.time()
                self.logger.debug("UP ACTION COMPLETED!")
            elif "look down" in c and head_pose=="down":
                self.challenge_action_completed=True
                self.action_completion_time=time.time()
                self.logger.debug("DOWN ACTION COMPLETED!")
            elif "blink twice" in c and blink_counter>=2:
                self.challenge_action_completed=True
                self.action_completion_time=time.time()
                self.logger.debug(f"BLINK ACTION COMPLETED! Counter: {blink_counter}")
            elif "nod your head" in c:
                # if you detect nod
                pass
            elif "shake your head" in c:
                # if you detect shake
                pass
        
        # Word check
        if not self.challenge_word_completed:
            if "say blue" in c and "blue" in last_speech:
                self.challenge_word_completed=True
                self.word_completion_time=time.time()
                self.logger.debug("BLUE WORD COMPLETED!")
            elif "say red" in c and "red" in last_speech:
                self.challenge_word_completed=True
                self.word_completion_time=time.time()
                self.logger.debug("RED WORD COMPLETED!")
            elif "say sky" in c and "sky" in last_speech:
                self.challenge_word_completed=True
                self.word_completion_time=time.time()
                self.logger.debug("SKY WORD COMPLETED!")
            elif "say ground" in c and "ground" in last_speech:
                self.challenge_word_completed=True
                self.word_completion_time=time.time()
                self.logger.debug("GROUND WORD COMPLETED!")
            elif "say hello" in c and "hello" in last_speech:
                self.challenge_word_completed=True
                self.word_completion_time=time.time()
                self.logger.debug("HELLO WORD COMPLETED!")
        
        # Check concurrency
        if self.challenge_action_completed and self.challenge_word_completed:
            diff = abs((self.action_completion_time or 0) - (self.word_completion_time or 0))
            self.logger.debug(f"Time diff between action & speech: {diff:.2f}s (max {self.config.ACTION_SPEECH_WINDOW:.2f}s)")
            if diff <= self.config.ACTION_SPEECH_WINDOW:
                self.challenge_completed = True
                self.verification_result = "PASS"
                self.current_challenge = None
                if self.speech_recognizer:
                    self.speech_recognizer.reset()
                self.logger.info("Challenge PASSED!")
                return True
            else:
                self.logger.debug(f"Action & speech not concurrent (diff: {diff:.2f}s)")
        
        return False
    
    def get_challenge_status(self) -> Tuple[Optional[str],bool,bool,Optional[str]]:
        return (
            self.current_challenge,
            self.challenge_action_completed,
            self.challenge_word_completed,
            self.verification_result
        )
    
    def get_challenge_time_remaining(self) -> float:
        if self.current_challenge is None or self.challenge_start_time is None:
            return 0
        elapsed = time.time() - self.challenge_start_time
        return max(0, self.challenge_timeout - elapsed)

"""Main liveness detection module integrating all components."""

import cv2
import numpy as np
import time
import logging
from typing import Tuple, Optional

from config import Config
from face_detector import FaceDetector
from blink_detector import BlinkDetector
from speech_recognizer import SpeechRecognizer
from challenge_manager import ChallengeManager
from action_detector import ActionDetector

class LivenessDetector:
    """Main class for liveness detection integrating all components."""
    
    def __init__(self, config: Config):
        """Initialize the liveness detector with configuration."""
        self.config = config
        
        # Configure logging
        logging_level = logging.DEBUG if config.DEBUG else logging.INFO
        logging.basicConfig(
            level=logging_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # Initialize components
        self.face_detector = FaceDetector(config)
        self.blink_detector = BlinkDetector(config)
        self.action_detector = ActionDetector(config)
        self.speech_recognizer = SpeechRecognizer(config)
        
        # Pass speech_recognizer and blink_detector to challenge_manager for reset coordination
        self.challenge_manager = ChallengeManager(
            config, 
            speech_recognizer=self.speech_recognizer,
            blink_detector=self.blink_detector
        )
        
        # Status variables
        self.consecutive_live_frames = 0
        self.consecutive_fake_frames = 0
        self.status = "Analyzing..."
        self.liveness_score = 0.0
        
        # Start with a challenge immediately
        self.challenge_manager.issue_new_challenge()
        self.speech_recognizer.start_listening()
        
        # Set target word from challenge
        challenge_text, _, _, _ = self.challenge_manager.get_challenge_status()
        if challenge_text:
            target_word = challenge_text.split()[-1]
            self.speech_recognizer.set_target_word(target_word)
    
    def detect_liveness(self, frame: np.ndarray) -> Tuple[np.ndarray, bool]:
        """
        Process a frame for liveness detection (the old function).
        
        Returns: (processed_frame, exit_flag).
        This is still used in some older code, apparently.
        """
        # Make a copy of the frame for display
        display_frame = frame.copy()
        
        # Detect face
        face_roi, face_rect = self.face_detector.detect_face(frame)
        
        # If no face detected, show a message
        if face_roi is None:
            cv2.putText(display_frame, "No face detected", (50, 50), 
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            return display_frame, False
        
        # Detect movement
        self.face_detector.detect_movement(face_rect)
        
        # Detect head pose using action detector
        head_pose = self.action_detector.detect_head_pose(display_frame, face_rect)
        
        # Detect blinks
        self.blink_detector.detect_blinks(display_frame, face_rect, face_roi)
        
        # Get last speech
        last_speech = self.speech_recognizer.get_last_speech()
        
        # Verify current challenge or issue new one
        challenge_text, action_completed, word_completed, verification_result = \
            self.challenge_manager.get_challenge_status()
        
        if challenge_text is not None:
            # Verify challenge
            self.challenge_manager.verify_challenge(
                head_pose, self.blink_detector.blink_counter, last_speech
            )
            
            # Display challenge status
            cv2.putText(display_frame, f"Challenge: {challenge_text}", (10, 30), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            time_remaining = self.challenge_manager.get_challenge_time_remaining()
            cv2.putText(display_frame, f"Time: {time_remaining:.1f}s", (10, 60), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            # Display action and word status
            action_status = "✓" if action_completed else "✗"
            word_status = "✓" if word_completed else "✗"
            cv2.putText(display_frame, f"Action: {action_status}", (10, 90), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(display_frame, f"Word: {word_status}", (10, 120), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            # Check verification result
            if verification_result == "PASS":
                cv2.putText(display_frame, "VERIFICATION PASSED", (50, 200), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                return display_frame, True
            elif verification_result == "FAIL":
                cv2.putText(display_frame, "VERIFICATION FAILED", (50, 200), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                return display_frame, True
        else:
            # Issue a new challenge if none is active
            self.challenge_manager.issue_new_challenge()
        
        # Draw face information
        self.face_detector.draw_face_info(display_frame, face_rect, self.status, self.liveness_score)
        
        # Display speech recognition status
        cv2.putText(display_frame, f"Speech: {last_speech}", (10, display_frame.shape[0]-20), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        return display_frame, False
    
    def reset(self) -> None:
        """Reset all components."""
        self.blink_detector.reset()
        self.speech_recognizer.reset()
        self.challenge_manager.issue_new_challenge()
        self.consecutive_live_frames = 0
        self.consecutive_fake_frames = 0
        self.status = "Analyzing..."
        self.liveness_score = 0.0
    
    def start_challenge(self):
        """Start a new challenge."""
        self.challenge_manager.start_new_challenge()
        challenge_text, _, _, _ = self.challenge_manager.get_challenge_status()
        if challenge_text:
            target_word = challenge_text.split()[-1]
            self.speech_recognizer.set_target_word(target_word)
    
    def process_frame(self, frame):
        """
        Process a frame (newer approach). Return a dictionary with:
           display_frame, debug_frame, verification_result, exit_flag,
           challenge_text, action_completed, word_completed, time_remaining
        """
        print(f"Processing frame with shape: {frame.shape if frame is not None else 'None'}")
        if frame is None or frame.size == 0:
            print("Error: Frame is None or empty in process_frame")
            return {
                'display_frame': None,
                'debug_frame': None,
                'verification_result': 'PENDING',
                'exit_flag': False,
                'challenge_text': None,
                'action_completed': False,
                'word_completed': False,
                'time_remaining': 0
            }
        
        # 1) Make two copies
        display_frame = frame.copy()
        debug_frame = frame.copy()
        
        # 2) Face detection on the debug_frame so bounding boxes show up
        face_roi, face_rect = self.face_detector.detect_face(debug_frame)
        
        if face_roi is None:
            cv2.putText(display_frame, "No face detected", (30, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            cv2.putText(debug_frame, "No face detected", (30, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            print("No face detected, skipping further processing")
            return {
                'display_frame': display_frame,
                'debug_frame': debug_frame,
                'verification_result': 'PENDING',
                'exit_flag': False,
                'challenge_text': None,
                'action_completed': False,
                'word_completed': False,
                'time_remaining': 0
            }
        
        # 3) Movement + head pose
        self.face_detector.detect_movement(face_rect)
        head_pose = self.action_detector.detect_head_pose(debug_frame, face_rect)
        
        # 4) Blink detection
        self.blink_detector.detect_blinks(debug_frame, face_rect, face_roi)
        
        # 5) Speech
        last_speech = self.speech_recognizer.get_last_speech()
        
        # 6) Challenge
        challenge_text, action_completed, word_completed, verification_result = \
            self.challenge_manager.get_challenge_status()
        
        exit_flag = False
        final_result = 'PENDING'
        
        if challenge_text:
            self.challenge_manager.verify_challenge(
                head_pose, self.blink_detector.blink_counter, last_speech
            )
            
            # Get updated status after verification
            challenge_text, action_completed, word_completed, verification_result = \
                self.challenge_manager.get_challenge_status()
            
            time_left = self.challenge_manager.get_challenge_time_remaining()
            print(f"Challenge: {challenge_text}, Time left: {time_left:.1f}s, Action: {action_completed}, Word: {word_completed}")
            
            # Draw detailed info on debug_frame
            cv2.putText(debug_frame, f"Challenge: {challenge_text}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(debug_frame, f"Time: {time_left:.1f}s", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            act_status = "✓" if action_completed else "✗"
            wrd_status = "✓" if word_completed else "✗"
            cv2.putText(debug_frame, f"Action: {act_status}", (10, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(debug_frame, f"Word: {wrd_status}", (10, 120),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            if verification_result == "PASS":
                cv2.putText(debug_frame, "VERIFICATION PASSED", (50, 200),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                final_result = 'PASS'
                exit_flag = True
            elif verification_result == "FAIL":
                cv2.putText(debug_frame, "VERIFICATION FAILED", (50, 200),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                final_result = 'FAIL'
                exit_flag = True
        else:
            # If no challenge is active, issue a new one
            self.challenge_manager.issue_new_challenge()
            challenge_text, action_completed, word_completed, verification_result = \
                self.challenge_manager.get_challenge_status()
            time_left = self.challenge_manager.get_challenge_time_remaining()
            print(f"New challenge issued: {challenge_text}, Time left: {time_left:.1f}s")
        
        # Minimal info on display_frame
        self.face_detector.draw_face_info(display_frame, face_rect, self.status, self.liveness_score)
        cv2.putText(display_frame, f"Speech: {last_speech}",
                    (10, display_frame.shape[0] - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        return {
            'display_frame': display_frame,
            'debug_frame': debug_frame,
            'verification_result': final_result,
            'exit_flag': exit_flag,
            'challenge_text': challenge_text,
            'action_completed': action_completed,
            'word_completed': word_completed,
            'time_remaining': time_left
        }
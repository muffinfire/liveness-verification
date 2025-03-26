"""Main liveness detection module integrating all components."""

import cv2
import numpy as np
import time
import logging
from typing import Tuple, Optional
import dlib

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
        
        # If not in debug mode, set logging level to WARNING to suppress INFO logs
        if not config.DEBUG:
            for handler in logging.root.handlers:
                handler.setLevel(logging.WARNING)
        
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
        face_detection_result = self.face_detector.detect_face(frame)
        
        # Handle the case where detect_face returns either (face_roi, face_rect) or just face_rect
        if isinstance(face_detection_result, tuple) and len(face_detection_result) == 2 and isinstance(face_detection_result[1], tuple):
            # It returned (face_roi, face_rect)
            face_roi, face_rect = face_detection_result
        else:
            # It returned just face_rect
            face_rect = face_detection_result
            # Extract face ROI manually if face_rect exists
            if face_rect is not None:
                x, y, w, h = face_rect
                face_roi = frame[y:y+h, x:x+w]
            else:
                face_roi = None
        
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
        self.blink_detector.detect_blinks(frame, face_rect, face_roi)
        
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
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
            time_remaining = self.challenge_manager.get_challenge_time_remaining()
            cv2.putText(display_frame, f"Time: {time_remaining:.1f}s", (10, 60), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
            # Display action and word status
            action_status = "✓" if action_completed else "✗"
            word_status = "✓" if word_completed else "✗"
            cv2.putText(display_frame, f"Action: {action_status}", (10, 90), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(display_frame, f"Word: {word_status}", (10, 120), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
            # Check verification result
            if verification_result == "PASS":
                cv2.putText(display_frame, "VERIFICATION PASSED", (50, 200), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                return display_frame, True
            elif verification_result == "FAIL":
                cv2.putText(display_frame, "VERIFICATION FAILED", (50, 200), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                return display_frame, True
        else:
            # Issue a new challenge if none is active
            self.challenge_manager.issue_new_challenge()
        
        # Draw face information
        self.face_detector.draw_face_info(display_frame, face_rect, self.status, self.liveness_score)
        
        # Display speech recognition status
        cv2.putText(display_frame, f"Speech: {last_speech}", (10, display_frame.shape[0]-20), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
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
        Process a frame for liveness detection.
        
        Returns: Dictionary with processed frame data.
        """
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
        debug_frame = frame.copy()  # Always create debug frame
        
        # 2) Face detection
        face_roi, face_rect = self.face_detector.detect_face(display_frame)
        
        if face_roi is None:
            cv2.putText(display_frame, "No face detected", (30, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            cv2.putText(debug_frame, "No face detected", (30, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        
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
        
        # 3) Blink detection - use regular detect_blinks to avoid breaking functionality
        blink_count = self.blink_detector.detect_blinks(frame, face_rect, face_roi)
        
        # Draw eye polygons on debug frame if needed
        if self.config.SHOW_DEBUG_FRAME:
            # Get facial landmarks for visualization
            gray_roi = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
            x, y, w, h = face_rect
            dlib_rect = dlib.rectangle(x, y, x + w, y + h)
            landmarks = self.blink_detector.dlib_predictor(gray_roi, dlib_rect)
            
            # Draw eye contours
            left_eye = np.array([(landmarks.part(i).x, landmarks.part(i).y) for i in range(36, 42)])
            right_eye = np.array([(landmarks.part(i).x, landmarks.part(i).y) for i in range(42, 48)])
            
            cv2.polylines(debug_frame, [left_eye], True, (0, 255, 0), 1)
            cv2.polylines(debug_frame, [right_eye], True, (0, 255, 0), 1)
            
            # Calculate and display EAR values
            left_ear = self.blink_detector.calculate_ear(left_eye)
            right_ear = self.blink_detector.calculate_ear(right_eye)
            
            left_center = np.mean(left_eye, axis=0).astype(int)
            right_center = np.mean(right_eye, axis=0).astype(int)
            
            cv2.putText(debug_frame, f"L: {left_ear:.2f}", 
                        (left_center[0] - 20, left_center[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            cv2.putText(debug_frame, f"R: {right_ear:.2f}", 
                        (right_center[0] - 20, right_center[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        
        # 4) Action detection
        action_detected = self.action_detector.detect_action(face_roi, face_rect)
        
        # 5) Speech recognition
        last_speech = self.speech_recognizer.get_last_speech()
        
        # 6) Update challenge manager
        self.challenge_manager.update(blink_count, action_detected, last_speech)
        
        # 7) Get challenge status
        challenge_text, action_completed, word_completed, verification_result = \
            self.challenge_manager.get_challenge_status()
        
        time_left = self.challenge_manager.get_challenge_time_remaining()
        
        # 8) Prepare result
        final_result = 'PENDING'
        exit_flag = False
        
        if verification_result != "PENDING":
            # Add debug info to debug frame
            cv2.putText(debug_frame, f"Action: {action_detected}", (10, 120),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(debug_frame, f"Speech: {last_speech}", (10, 150),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(debug_frame, f"Blinks: {self.blink_detector.blink_counter}", (10, 180),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
            if verification_result == "PASS":
                cv2.putText(debug_frame, "VERIFICATION PASSED", (50, 220),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 1)
                final_result = 'PASS'
                exit_flag = True
            elif verification_result == "FAIL":
                cv2.putText(debug_frame, "VERIFICATION FAILED", (50, 220),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                final_result = 'FAIL'
                exit_flag = True
        else:
            # If no challenge is active, issue a new one
            if not challenge_text:
                self.challenge_manager.issue_new_challenge()
                challenge_text, action_completed, word_completed, verification_result = \
                    self.challenge_manager.get_challenge_status()
                time_left = self.challenge_manager.get_challenge_time_remaining()
                print(f"New challenge issued: {challenge_text}, Time left: {time_left:.1f}s")
        
        # Minimal info on display_frame
        self.face_detector.draw_face_info(display_frame, face_rect, self.status, self.liveness_score)
        cv2.putText(display_frame, f"Speech: {last_speech}",
                    (10, display_frame.shape[0] - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        # Always add debug info to debug frame
        cv2.putText(debug_frame, f"Challenge: {challenge_text}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(debug_frame, f"Action completed: {action_completed}", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(debug_frame, f"Word completed: {word_completed}", (10, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(debug_frame, f"Time left: {time_left:.1f}s", (10, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(debug_frame, f"Blinks: {self.blink_detector.blink_counter}", (10, 150),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        # Update liveness score based on challenge progress
        if action_completed:
            self.liveness_score += 0.5
        if word_completed:
            self.liveness_score += 0.5
        # Cap score at 1.0
        self.liveness_score = min(1.0, self.liveness_score)
        
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
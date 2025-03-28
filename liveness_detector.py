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
        logging_level = logging.DEBUG if config.DEBUG else logging.INFO
        logging.basicConfig(
            level=logging_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        if not config.DEBUG:
            for handler in logging.root.handlers:
                handler.setLevel(logging.WARNING)
        
        self.face_detector = FaceDetector(config)
        self.blink_detector = BlinkDetector(config)
        self.action_detector = ActionDetector(config)
        self.speech_recognizer = SpeechRecognizer(config)
        
        self.challenge_manager = ChallengeManager(
            config,
            speech_recognizer=self.speech_recognizer,
            blink_detector=self.blink_detector
        )
        
        self.consecutive_live_frames = 0
        self.consecutive_fake_frames = 0
        self.status = "Waiting for verification..."
        self.liveness_score = 0.0
        self.duress_detected = False
        
        self.start_challenge()
        self.logger.debug("LivenessDetector initialized")
    
    def detect_liveness(self, frame: np.ndarray) -> Tuple[np.ndarray, bool]:
        """Process a frame for liveness detection (older method)."""
        display_frame = frame.copy()
        
        face_roi, face_rect = self.face_detector.detect_face(frame)
        
        if face_roi is None:
            cv2.putText(display_frame, "No face detected", (50, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            return display_frame, False
        
        self.face_detector.detect_movement(face_rect)
        head_pose = self.action_detector.detect_head_pose(display_frame, face_rect)
        self.blink_detector.detect_blinks(frame, face_rect, face_roi)
        last_speech = self.speech_recognizer.get_last_speech()
        
        self.challenge_manager.update(head_pose, self.blink_detector.blink_counter, last_speech)
        
        challenge_text, action_completed, word_completed, verification_result = \
            self.challenge_manager.get_challenge_status()
        
        if challenge_text is not None:
            self.challenge_manager.verify_challenge(
                head_pose, self.blink_detector.blink_counter, last_speech
            )
            
            cv2.putText(display_frame, f"Challenge: {challenge_text}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            time_remaining = self.challenge_manager.get_challenge_time_remaining()
            cv2.putText(display_frame, f"Time: {time_remaining:.1f}s", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            action_status = "✓" if action_completed else "✗"
            word_status = "✓" if word_completed else "✗"
            cv2.putText(display_frame, f"Action: {action_status}", (10, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(display_frame, f"Word: {word_status}", (10, 120),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
            if verification_result == "PASS":
                cv2.putText(display_frame, "VERIFICATION PASSED", (50, 200),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                return display_frame, True
            elif verification_result == "FAIL":
                cv2.putText(display_frame, "VERIFICATION FAILED", (50, 200),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                return display_frame, True
        else:
            self.start_challenge()
        
        self.face_detector.draw_face_info(display_frame, face_rect, self.status, self.liveness_score)
        cv2.putText(display_frame, f"Speech: {last_speech}", (10, display_frame.shape[0]-20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        return display_frame, False

    def reset(self) -> None:
        """Reset all components to initial state."""
        self.blink_detector.reset()
        self.speech_recognizer.reset()
        self.challenge_manager.reset()
        self.consecutive_live_frames = 0
        self.consecutive_fake_frames = 0
        self.status = "Waiting for verification..."
        self.liveness_score = 0.0
        self.duress_detected = False
        self.start_challenge()
        self.logger.debug("LivenessDetector reset")

    def start_challenge(self):
        """Start a new challenge."""
        self.challenge_manager.issue_new_challenge()
        self.speech_recognizer.start_listening()
        challenge_text, _, _, _ = self.challenge_manager.get_challenge_status()
        if challenge_text:
            target_word = challenge_text.split()[-1]
            self.speech_recognizer.set_target_word(target_word)
        self.logger.debug(f"New challenge started: {challenge_text}")
    
    def process_frame(self, frame):
        """Process a frame for liveness detection (newer approach)."""
        self.logger.debug("Processing frame in LivenessDetector")
        if frame is None or frame.size == 0:
            self.logger.error("Frame is None or empty in process_frame")
            return {
                'display_frame': None,
                'debug_frame': None,
                'verification_result': 'PENDING',
                'exit_flag': False,
                'challenge_text': None,
                'action_completed': False,
                'word_completed': False,
                'time_remaining': 0,
                'duress_detected': False
            }
        
        display_frame = frame.copy()
        debug_frame = frame.copy() if self.config.SHOW_DEBUG_FRAME else None
        
        face_roi, face_rect = self.face_detector.detect_face(display_frame)
        
        head_pose = None
        if face_roi is None:
            self.logger.debug("No face detected")
            cv2.putText(display_frame, "No face detected", (30, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            if debug_frame is not None:
                cv2.putText(debug_frame, "No face detected", (30, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        else:
            self.logger.debug(f"Face detected at {face_rect}")
            self.blink_detector.detect_blinks(frame, face_rect, face_roi)
            self.logger.debug(f"Blink count: {self.blink_detector.blink_counter}")
            
            if self.config.SHOW_DEBUG_FRAME:
                self.logger.debug("Generating debug frame with landmarks")
                gray_roi = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
                x, y, w, h = face_rect
                dlib_rect = dlib.rectangle(0, 0, w, h)
                landmarks = self.blink_detector.dlib_predictor(gray_roi, dlib_rect)
                
                left_eye = [(landmarks.part(i).x + x, landmarks.part(i).y + y) for i in range(36, 42)]
                right_eye = [(landmarks.part(i).x + x, landmarks.part(i).y + y) for i in range(42, 48)]
                
                cv2.polylines(debug_frame, [np.array(left_eye)], True, (0, 255, 0), 1)
                cv2.polylines(debug_frame, [np.array(right_eye)], True, (0, 255, 0), 1)
                
                left_ear = self.blink_detector.calculate_ear(np.array(left_eye) - np.array([x, y]))
                right_ear = self.blink_detector.calculate_ear(np.array(right_eye) - np.array([x, y]))
                
                left_center = np.mean(np.array(left_eye), axis=0).astype(int)
                right_center = np.mean(np.array(right_eye), axis=0).astype(int)
                cv2.putText(debug_frame, f"L: {left_ear:.2f}", 
                            (left_center[0] - 20, left_center[1] - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                cv2.putText(debug_frame, f"R: {right_ear:.2f}", 
                            (right_center[0] - 20, right_center[1] - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                self.logger.debug(f"Debug frame generated: EAR L={left_ear:.2f}, R={right_ear:.2f}")
        
        head_pose = self.action_detector.detect_head_pose(display_frame, face_rect)
        self.logger.debug(f"Head pose: {head_pose}")
        last_speech = self.speech_recognizer.get_last_speech()
        
        if last_speech.lower() == "verify":
            self.duress_detected = True
            self.logger.info("Duress detected: 'verify' spoken")
        
        self.challenge_manager.update(head_pose, self.blink_detector.blink_counter, last_speech)
        
        challenge_text, action_completed, word_completed, verification_result = \
            self.challenge_manager.get_challenge_status()
        time_left = self.challenge_manager.get_challenge_time_remaining()
        self.logger.debug(f"Challenge status: text={challenge_text}, action={action_completed}, "
                         f"word={word_completed}, result={verification_result}, time={time_left:.1f}s")
        
        if word_completed and challenge_text:
            target_action = challenge_text.split()[1].lower()
            action_completed = (head_pose == target_action)
            self.logger.debug(f"Word spoken, verifying action: expected={target_action}, detected={head_pose}")
            self.challenge_manager.action_completed = action_completed
        
        final_result = 'PENDING'
        exit_flag = False
        
        if verification_result != "PENDING":
            last_speech = self.speech_recognizer.get_last_speech()
            if debug_frame is not None:
                cv2.putText(debug_frame, f"Speech: {last_speech}", (10, 150),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                cv2.putText(debug_frame, f"Blinks: {self.blink_detector.blink_counter}", (10, 180),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
            if self.duress_detected:
                self.status = "UNDER DURESS DETECTED"
                cv2.putText(debug_frame if debug_frame is not None else display_frame,
                            "DURESS DETECTED", (20, display_frame.shape[0]-20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (239, 234, 79), 2)
                final_result = 'FAIL'
                exit_flag = True
            elif verification_result == "PASS":
                self.status = "VERIFICATION PASSED"
                cv2.putText(debug_frame if debug_frame is not None else display_frame,
                            "VERIFICATION PASSED", (20, display_frame.shape[0]-20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                final_result = 'PASS'
                exit_flag = True
            elif verification_result == "FAIL":
                self.status = "VERIFICATION FAILED"
                cv2.putText(debug_frame if debug_frame is not None else display_frame,
                            "VERIFICATION FAILED", (20, display_frame.shape[0]-20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                final_result = 'FAIL'
                exit_flag = True
            self.logger.debug(f"Verification result: {final_result}")
        else:
            if not challenge_text:
                self.start_challenge()
                challenge_text, action_completed, word_completed, verification_result = \
                    self.challenge_manager.get_challenge_status()
                time_left = self.challenge_manager.get_challenge_time_remaining()
                self.logger.debug("Issued new challenge due to none active")
        
        # Draw face info on both frames
        self.face_detector.draw_face_info(display_frame, face_rect, self.status, self.liveness_score)
        cv2.putText(display_frame, f"Speech: {self.speech_recognizer.get_last_speech()}",
                    (10, display_frame.shape[0] - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        if self.config.SHOW_DEBUG_FRAME and debug_frame is not None:
            self.face_detector.draw_face_info(debug_frame, face_rect, self.status, self.liveness_score)
        
        cv2.putText(display_frame, f"Head Pose: {head_pose if head_pose else 'None'}", (10, 210),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(display_frame, f"Challenge: {challenge_text}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(display_frame, f"Action completed: {action_completed}", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(display_frame, f"Word completed: {word_completed}", (10, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(display_frame, f"Time left: {time_left:.1f}s", (10, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        if debug_frame is not None:
            cv2.putText(debug_frame, f"Head Pose: {head_pose if head_pose else 'None'}", (10, 210),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(debug_frame, f"Challenge: {challenge_text}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(debug_frame, f"Action completed: {action_completed}", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(debug_frame, f"Word completed: {word_completed}", (10, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(debug_frame, f"Time left: {time_left:.1f}s", (10, 120),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        if action_completed and word_completed:
            self.liveness_score = 1.0
        else:
            self.liveness_score = 0.0
        
        self.logger.debug("Frame processing completed")
        return {
            'display_frame': display_frame,
            'debug_frame': debug_frame,
            'verification_result': final_result,
            'exit_flag': exit_flag,
            'challenge_text': challenge_text,
            'action_completed': action_completed,
            'word_completed': word_completed,
            'time_remaining': time_left,
            'duress_detected': self.duress_detected
        }

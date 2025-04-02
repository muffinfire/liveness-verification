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
        self.config = config  # Store the configuration object for settings access
        # Set logging level based on debug mode from config
        logging_level = logging.DEBUG if config.DEBUG else logging.INFO
        logging.basicConfig(
            level=logging_level,  # Define verbosity of logs
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'  # Log format with timestamp, name, level, and message
        )
        self.logger = logging.getLogger(__name__)  # Create logger instance for this module
        
        # Reduce log verbosity in non-debug mode to warnings only
        if not config.DEBUG:
            for handler in logging.root.handlers:
                handler.setLevel(logging.WARNING)
        
        logging_level = logging.WARNING

        # Initialize component detectors with the provided config
        self.face_detector = FaceDetector(config)  # Detects faces in frames
        self.blink_detector = BlinkDetector(config)  # Tracks eye blinks
        self.action_detector = ActionDetector(config)  # Detects head movements
        self.speech_recognizer = SpeechRecognizer(config)  # Recognizes spoken words
        
        # Set up challenge manager with dependencies for liveness tasks
        self.challenge_manager = ChallengeManager(
            config,
            speech_recognizer=self.speech_recognizer,
            blink_detector=self.blink_detector
        )
        
        # Initialize counters and state variables
        self.consecutive_live_frames = 0  # Tracks consecutive frames indicating liveness
        self.consecutive_fake_frames = 0  # Tracks consecutive frames indicating no liveness
        self.status = "Waiting for verification..."  # Current status message
        self.liveness_score = 0.0  # Score indicating liveness confidence
        self.duress_detected = False  # Flag for detecting forced verification attempts
        
        # Initialize detection state for consistent challenge updates
        self.head_pose = "center"  # Default head pose for initial state
        self.blink_count = 0  # Default blink count for initial state
        self.last_speech = ""  # Default last spoken word for initial state
        
        self.start_challenge()  # Begin the first liveness challenge
        self.logger.debug("LivenessDetector initialized")  # Log initialization completion
    
    def detect_liveness(self, frame: np.ndarray) -> Tuple[np.ndarray, bool]:
        """Process a frame for liveness detection (older method)."""
        display_frame = frame.copy()  # Create a copy of the frame for display
        
        # Detect face and its region of interest (ROI)
        face_roi, face_rect = self.face_detector.detect_face(frame)
        
        # Handle case where no face is detected
        if face_roi is None:
            cv2.putText(display_frame, "No face detected", (50, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)  # Display error text
            return display_frame, False  # Return frame and indicate no exit
        
        # Analyze face movement and head pose
        self.face_detector.detect_movement(face_rect)
        head_pose = self.action_detector.detect_head_pose(display_frame, face_rect) or "center"  # Fallback to "center" if None
        self.blink_detector.detect_blinks(frame, face_rect, face_roi)  # Check for blinks
        last_speech = self.speech_recognizer.get_last_speech()  # Get latest spoken word
        
        # Update challenge status with detected features
        self.challenge_manager.update(head_pose, self.blink_detector.blink_counter, last_speech)
        
        # Retrieve current challenge details with detection state
        challenge_text, action_completed, word_completed, verification_result = \
            self.challenge_manager.get_challenge_status(head_pose, self.blink_detector.blink_counter, last_speech)
        
        # Process active challenge
        if challenge_text is not None:
            self.challenge_manager.verify_challenge(
                head_pose, self.blink_detector.blink_counter, last_speech
            )  # Verify if challenge conditions are met
            
            # Display challenge instructions and status on frame
            cv2.putText(display_frame, f"Challenge: {challenge_text}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            time_remaining = self.challenge_manager.get_challenge_time_remaining()
            cv2.putText(display_frame, f"Time: {time_remaining:.1f}s", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            action_status = "✓" if action_completed else "✗"  # Action completion indicator
            word_status = "✓" if word_completed else "✗"  # Word spoken indicator
            cv2.putText(display_frame, f"Action: {action_status}", (10, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(display_frame, f"Word: {word_status}", (10, 120),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
            # Handle verification outcomes
            if verification_result == "PASS":
                cv2.putText(display_frame, "VERIFICATION PASSED", (50, 200),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)  # Success message
                return display_frame, True  # Exit with success
            elif verification_result == "FAIL":
                cv2.putText(display_frame, "VERIFICATION FAILED", (50, 200),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)  # Failure message
                return display_frame, True  # Exit with failure
        else:
            self.start_challenge()  # Start a new challenge if none is active
        
        # Draw face information and last spoken word on frame
        self.face_detector.draw_face_info(display_frame, face_rect, self.status, self.liveness_score)
        cv2.putText(display_frame, f"Speech: {last_speech}", (10, display_frame.shape[0]-20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        return display_frame, False  # Return frame and indicate processing continues

    def reset(self) -> None:
        """Reset all components to initial state."""
        self.blink_detector.reset()  # Clear blink detection state
        self.speech_recognizer.reset()  # Clear speech recognition state
        self.challenge_manager.reset()  # Clear challenge state
        self.consecutive_live_frames = 0  # Reset live frame counter
        self.consecutive_fake_frames = 0  # Reset fake frame counter
        self.status = "Waiting for verification..."  # Reset status message
        self.liveness_score = 0.0  # Reset liveness score
        self.duress_detected = False  # Reset duress flag
        self.head_pose = "center"  # Reset head pose to default
        self.blink_count = 0  # Reset blink count to default
        self.last_speech = ""  # Reset last speech to default
        self.start_challenge()  # Begin a new challenge
        self.logger.debug("LivenessDetector reset")  # Log reset action

    def start_challenge(self):
        """Start a new challenge."""
        self.challenge_manager.issue_new_challenge()  # Generate a new challenge

        # Pass current state to get_challenge_status to avoid missing argument errors
        challenge_text, _, _, _ = self.challenge_manager.get_challenge_status(
            self.head_pose, self.blink_count, self.last_speech
        )
        if challenge_text:
            target_word = challenge_text.split()[-1]  # Extract the target word from challenge
            self.speech_recognizer.set_target_word(target_word)  # Set word to listen for
        self.logger.debug(f"New challenge started: {challenge_text}")  # Log new challenge
    
    def process_frame(self, frame):
        """Process a frame for liveness detection (newer approach)."""
        self.logger.debug("Processing frame in LivenessDetector")  # Log frame processing start
        # Handle invalid frame input
        if frame is None or frame.size == 0:
            self.logger.error("Frame is None or empty in process_frame")  # Log error
            return {
                'display_frame': None,  # No display frame available
                'debug_frame': None,  # No debug frame available
                'verification_result': 'PENDING',  # Default result
                'exit_flag': False,  # Continue processing
                'challenge_text': None,  # No challenge text
                'action_completed': False,  # Action not completed
                'word_completed': False,  # Word not spoken
                'time_remaining': 0,  # No time remaining
                'duress_detected': False  # No duress detected
            }
        
        # Create copies of the frame for display and optional debug output
        display_frame = frame.copy()
        debug_frame = frame.copy() if self.config.SHOW_DEBUG_FRAME else None
        
        # Detect face and ROI
        face_roi, face_rect = self.face_detector.detect_face(display_frame)
        
        # Process face detection results
        if face_roi is None:
            self.logger.debug("No face detected")  # Log no face found
            cv2.putText(display_frame, "No face detected", (30, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)  # Display error text
            if debug_frame is not None:
                cv2.putText(debug_frame, "No face detected", (30, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)  # Debug frame text
            self.head_pose = "center"  # Reset head pose when no face
            self.blink_count = 0  # Reset blink count when no face
        else:
            self.logger.debug(f"Face detected at {face_rect}")  # Log face detection
            self.blink_detector.detect_blinks(frame, face_rect, face_roi)  # Detect blinks
            self.blink_count = self.blink_detector.blink_counter  # Update blink count
            self.logger.debug(f"Blink count: {self.blink_count}")  # Log blink count
            
            # Generate debug frame with eye landmarks if enabled
            if self.config.SHOW_DEBUG_FRAME and debug_frame is not None:
                self.logger.debug("Generating debug frame with landmarks")  # Log debug frame creation
                gray_roi = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)  # Convert ROI to grayscale
                x, y, w, h = face_rect  # Unpack face rectangle
                dlib_rect = dlib.rectangle(0, 0, w, h)  # Create dlib rectangle for landmarks
                landmarks = self.blink_detector.dlib_predictor(gray_roi, dlib_rect)  # Get facial landmarks
                
                # Extract eye landmark coordinates
                left_eye = [(landmarks.part(i).x + x, landmarks.part(i).y + y) for i in range(36, 42)]
                right_eye = [(landmarks.part(i).x + x, landmarks.part(i).y + y) for i in range(42, 48)]
                
                # Draw eye outlines on debug frame
                cv2.polylines(debug_frame, [np.array(left_eye)], True, (0, 255, 0), 1)
                cv2.polylines(debug_frame, [np.array(right_eye)], True, (0, 255, 0), 1)
                
                # Calculate Eye Aspect Ratio (EAR) for each eye
                left_ear = self.blink_detector.calculate_ear(np.array(left_eye) - np.array([x, y]))
                right_ear = self.blink_detector.calculate_ear(np.array(right_eye) - np.array([x, y]))
                
                # Display EAR values near eyes
                left_center = np.mean(np.array(left_eye), axis=0).astype(int)
                right_center = np.mean(np.array(right_eye), axis=0).astype(int)
                cv2.putText(debug_frame, f"L: {left_ear:.2f}", 
                            (left_center[0] - 20, left_center[1] - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                cv2.putText(debug_frame, f"R: {right_ear:.2f}", 
                            (right_center[0] - 20, right_center[1] - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                self.logger.debug(f"Debug frame generated: EAR L={left_ear:.2f}, R={right_ear:.2f}")  # Log EAR values
        
        # Detect head pose and last spoken word
        self.head_pose = self.action_detector.detect_head_pose(display_frame, face_rect) or "center"  # Update head pose, fallback to "center"
        self.logger.debug(f"Head pose: {self.head_pose}")  # Log detected pose
        self.last_speech = self.speech_recognizer.get_last_speech()  # Update last speech
        self.logger.debug(f"Last speech: {self.last_speech}")  # Log last speech
        
        # Check for duress keyword and set flag (actual handling moved to ChallengeManager)
        if self.last_speech.lower() == "verify":
            self.duress_detected = True
            self.logger.info("Duress detected: 'verify' spoken")  # Log duress detection
        
        # Update challenge manager with current detections
        self.challenge_manager.update(self.head_pose, self.blink_count, self.last_speech)
        
        # Get current challenge status with updated detection state
        challenge_text, action_completed, word_completed, verification_result = \
            self.challenge_manager.get_challenge_status(self.head_pose, self.blink_count, self.last_speech)
        time_left = self.challenge_manager.get_challenge_time_remaining()
        self.logger.debug(f"Challenge status: text={challenge_text}, action={action_completed}, "
                         f"word={word_completed}, result={verification_result}, time={time_left:.1f}s")  # Log status
        
        final_result = 'PENDING'  # Default verification result
        exit_flag = False  # Default flag to continue processing
        
        # Process final verification outcome
        if verification_result in ["PASS", "FAIL"]:
            if debug_frame is not None:
                # Display speech and blink info on debug frame
                cv2.putText(debug_frame, f"Speech: {self.last_speech}", (10, 150),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                cv2.putText(debug_frame, f"Blinks: {self.blink_count}", (10, 180),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
            # Handle duress detection
            if self.duress_detected:
                self.status = "UNDER DURESS DETECTED"
                cv2.putText(debug_frame if debug_frame is not None else display_frame,
                            "DURESS DETECTED", (20, display_frame.shape[0]-20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (239, 234, 79), 2)  # Yellow text for duress
                final_result = 'FAIL'
                exit_flag = True
            # Handle successful verification
            elif verification_result == "PASS":
                self.status = "VERIFICATION PASSED"
                cv2.putText(debug_frame if debug_frame is not None else display_frame,
                            "VERIFICATION PASSED", (20, display_frame.shape[0]-20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)  # Green text for pass
                final_result = 'PASS'
                exit_flag = True
            # Handle failed verification (including timeout)
            elif verification_result == "FAIL":
                self.status = "VERIFICATION FAILED"
                cv2.putText(debug_frame if debug_frame is not None else display_frame,
                            "VERIFICATION FAILED", (20, display_frame.shape[0]-20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)  # Red text for fail
                final_result = 'FAIL'
                exit_flag = True
            self.logger.debug(f"Verification result: {final_result}")  # Log result
        else:
            # Start a new challenge if none is active
            if not challenge_text:
                self.start_challenge()
                challenge_text, action_completed, word_completed, verification_result = \
                    self.challenge_manager.get_challenge_status(self.head_pose, self.blink_count, self.last_speech)
                time_left = self.challenge_manager.get_challenge_time_remaining()
                self.logger.debug("Issued new challenge due to none active")  # Log new challenge
        
        # Draw face info on both frames
        self.face_detector.draw_face_info(display_frame, face_rect, self.status, self.liveness_score)
        cv2.putText(display_frame, f"Speech: {self.last_speech}",
                    (10, display_frame.shape[0] - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)  # Display last speech
        if self.config.SHOW_DEBUG_FRAME and debug_frame is not None:
            self.face_detector.draw_face_info(debug_frame, face_rect, self.status, self.liveness_score)
        
        # Overlay additional info on both frames
        cv2.putText(display_frame, f"Head Pose: {self.head_pose if self.head_pose else 'None'}", (10, 210),
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
            cv2.putText(debug_frame, f"Head Pose: {self.head_pose if self.head_pose else 'None'}", (10, 210),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(debug_frame, f"Challenge: {challenge_text}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(debug_frame, f"Action completed: {action_completed}", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(debug_frame, f"Word completed: {word_completed}", (10, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(debug_frame, f"Time left: {time_left:.1f}s", (10, 120),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        # Update liveness score based on challenge completion
        if action_completed and word_completed:
            self.liveness_score = 1.0
        else:
            self.liveness_score = 0.0
        
        self.logger.debug("Frame processing completed")  # Log completion
        # Return comprehensive result dictionary
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
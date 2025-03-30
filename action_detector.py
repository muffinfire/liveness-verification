"""Action detection module for liveness verification."""

import cv2
import numpy as np
import logging
import dlib
from typing import List, Tuple, Dict, Any, Optional
from collections import deque

class ActionDetector:
    """Detects specific actions for liveness verification."""
    
    def __init__(self, config):
        self.config = config  # Store configuration object
        self.logger = logging.getLogger(__name__)  # Create logger for this module
        
        self.dlib_detector = dlib.get_frontal_face_detector()  # Initialize dlib face detector
        try:
            # Load dlib's facial landmark predictor
            self.dlib_predictor = dlib.shape_predictor("shape_predictor_68_face_landmarks.dat")
            self.using_dlib = True  # Flag indicating successful dlib initialization
            self.logger.info("Using dlib for facial landmark detection in ActionDetector")  # Log success
        except Exception as e:
            self.logger.error(f"Could not load dlib shape predictor: {e}")  # Log failure
            self.using_dlib = False
            raise ValueError("Dlib shape predictor is required for action detection")  # Raise error if failed
        
        # Initialize action tracking variables
        self.current_action = None  # Current action to detect
        self.action_completed = False  # Flag for action completion
        self.action_start_time = None  # Timestamp when action detection started
        
        # Queue to store face angles for smoothing
        self.face_angles = deque(maxlen=config.FACE_POSITION_HISTORY_LENGTH)
        self.head_pose = "center"  # Default head pose
        self.last_debug_time = 0.0  # Last time a debug message was logged
    
    def set_action(self, action: str) -> None:
        """Set the action to detect."""
        self.current_action = action  # Assign new action
        self.action_completed = False  # Reset completion flag
        self.action_start_time = None  # Clear start time
        self.logger.debug(f"Action set to: {action}")  # Log action setting
    
    def detect_head_pose(self, frame: np.ndarray, face_rect: Tuple[int, int, int, int]) -> str:
        """
        Detect head pose (left, right, up, down, center) using facial landmarks.
        """
        if face_rect is None:
            return self.head_pose  # Return last known pose if no face detected
        
        x, y, w, h = face_rect  # Unpack face rectangle coordinates
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)  # Convert frame to grayscale
        dlib_rect = dlib.rectangle(x, y, x + w, y + h)  # Create dlib rectangle
        landmarks = self.dlib_predictor(gray, dlib_rect)  # Detect facial landmarks

        # Extract key landmark points
        nose = np.array([landmarks.part(30).x, landmarks.part(30).y])  # Nose tip
        left_eye = np.array([landmarks.part(36).x, landmarks.part(36).y])  # Left eye corner
        right_eye = np.array([landmarks.part(45).x, landmarks.part(45).y])  # Right eye corner

        # Calculate horizontal ratio (Right/Left instead of Left/Right)
        left_dist = np.linalg.norm(nose - left_eye)  # Distance from nose to left eye
        right_dist = np.linalg.norm(nose - right_eye)  # Distance from nose to right eye
        horizontal_ratio = right_dist / left_dist if left_dist != 0 else 1.0  # Compute ratio

        # Calculate vertical offset for up/down detection
        face_center_y = (y + y + h) / 2  # Vertical center of face
        nose_offset = nose[1] - face_center_y  # Nose position relative to center

        # Add current measurements to history for smoothing
        self.face_angles.append((horizontal_ratio, nose_offset))
        
        # Process pose when enough history is accumulated
        if len(self.face_angles) >= self.config.FACE_POSITION_HISTORY_LENGTH:
            angles_list = list(self.face_angles)  # Convert deque to list
            avg_ratio = sum(a[0] for a in angles_list) / len(angles_list)  # Average horizontal ratio
            avg_offset = sum(a[1] for a in angles_list) / len(angles_list)  # Average vertical offset
            
            # Define symmetric thresholds from config
            HORIZONTAL_THRESHOLD = self.config.HEAD_POSE_THRESHOLD_HORIZONTAL
            CENTER_MIN = 1.0 - HORIZONTAL_THRESHOLD  # Minimum ratio for center
            CENTER_MAX = 1.0 + HORIZONTAL_THRESHOLD  # Maximum ratio for center
            UP_THRESHOLD = -self.config.HEAD_POSE_THRESHOLD_UP  # Negative for upward movement
            DOWN_THRESHOLD = self.config.HEAD_POSE_THRESHOLD_DOWN  # Positive for downward movement
            
            old_pose = self.head_pose  # Store previous pose for comparison
            
            # Determine head pose based on averaged values
            if avg_ratio > CENTER_MAX:
                self.head_pose = "right"
            elif avg_ratio < CENTER_MIN:
                self.head_pose = "left"
            elif avg_offset < UP_THRESHOLD:
                self.head_pose = "up"
            elif avg_offset > DOWN_THRESHOLD:
                self.head_pose = "down"
            else:
                self.head_pose = "center"
            
            # Log pose change if it differs and rate-limited (1-second interval)
            now = float(cv2.getTickCount()) / cv2.getTickFrequency()
            if self.head_pose != old_pose and now - self.last_debug_time > 1.0:
                self.logger.debug(f"{self.head_pose.upper()} detected! Ratio: {avg_ratio:.2f}, Offset: {avg_offset:.1f}")
                self.last_debug_time = now
            
            # Add debug visualization to frame
            cv2.circle(frame, tuple(nose), 2, (0, 255, 0), -1)  # Mark nose
            cv2.circle(frame, tuple(left_eye), 2, (0, 255, 0), -1)  # Mark left eye
            cv2.circle(frame, tuple(right_eye), 2, (0, 255, 0), -1)  # Mark right eye
            cv2.line(frame, tuple(nose), tuple(left_eye), (255, 0, 0), 1)  # Line to left eye
            cv2.line(frame, tuple(nose), tuple(right_eye), (255, 0, 0), 1)  # Line to right eye
            direction_x = int(x + w/2 + (avg_ratio - 1) * 50)  # Horizontal direction indicator
            direction_y = int(face_center_y + avg_offset)  # Vertical direction indicator
            cv2.line(frame, (int(x + w/2), int(face_center_y)), (direction_x, direction_y), (0, 255, 255), 2)  # Direction line
        
        return self.head_pose  # Return detected pose
    
    def detect_action(self, frame: np.ndarray, face_rect: Tuple[int, int, int, int]) -> bool:
        """Detect if the specified action is performed."""
        if self.current_action is None or face_rect is None:
            return False  # No action to detect or no face
        
        current_pose = self.detect_head_pose(frame, face_rect)  # Get current head pose
        self.action_completed = (current_pose.lower() == self.current_action.lower())  # Check if pose matches action
        return self.action_completed  # Return completion status
    
    def is_action_completed(self):
        """Check if the current action has been completed."""
        return self.action_completed  # Return current completion state
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
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        self.dlib_detector = dlib.get_frontal_face_detector()
        try:
            self.dlib_predictor = dlib.shape_predictor("shape_predictor_68_face_landmarks.dat")
            self.using_dlib = True
            self.logger.info("Using dlib for facial landmark detection in ActionDetector")
        except Exception as e:
            self.logger.error(f"Could not load dlib shape predictor: {e}")
            self.using_dlib = False
            raise ValueError("Dlib shape predictor is required for action detection")
        
        self.current_action = None
        self.action_completed = False
        self.action_start_time = None
        
        self.face_angles = deque(maxlen=config.FACE_POSITION_HISTORY_LENGTH)
        self.head_pose = "center"
        self.last_debug_time = 0.0
    
    def set_action(self, action: str) -> None:
        self.current_action = action
        self.action_completed = False
        self.action_start_time = None
        self.logger.debug(f"Action set to: {action}")
    
    def detect_head_pose(self, frame: np.ndarray, face_rect: Tuple[int, int, int, int]) -> str:
        """
        Detect head pose (left, right, up, down, center) using facial landmarks.
        """
        if face_rect is None:
            return self.head_pose
        
        x, y, w, h = face_rect
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        dlib_rect = dlib.rectangle(x, y, x + w, y + h)
        landmarks = self.dlib_predictor(gray, dlib_rect)

        # Extract key landmarks
        nose = np.array([landmarks.part(30).x, landmarks.part(30).y])
        left_eye = np.array([landmarks.part(36).x, landmarks.part(36).y])
        right_eye = np.array([landmarks.part(42).x, landmarks.part(42).y])

        # Horizontal ratio (Right/Left instead of Left/Right)
        left_dist = np.linalg.norm(nose - left_eye)
        right_dist = np.linalg.norm(nose - right_eye)
        horizontal_ratio = right_dist / left_dist if left_dist != 0 else 1.0  # Swapped

        # Vertical offset (Up/Down)
        face_center_y = (y + y + h) / 2
        nose_offset = nose[1] - face_center_y

        # Smoothing
        self.face_angles.append((horizontal_ratio, nose_offset))
        
        if len(self.face_angles) >= self.config.FACE_POSITION_HISTORY_LENGTH:
            angles_list = list(self.face_angles)
            avg_ratio = sum(a[0] for a in angles_list) / len(angles_list)
            avg_offset = sum(a[1] for a in angles_list) / len(angles_list)
            
            # Symmetric thresholds
            HORIZONTAL_THRESHOLD = self.config.HEAD_POSE_THRESHOLD_HORIZONTAL
            CENTER_MIN = 1.0 - HORIZONTAL_THRESHOLD
            CENTER_MAX = 1.0 + HORIZONTAL_THRESHOLD
            UP_THRESHOLD = -self.config.HEAD_POSE_THRESHOLD_UP
            DOWN_THRESHOLD = self.config.HEAD_POSE_THRESHOLD_DOWN
            
            old_pose = self.head_pose
            
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
            
            now = float(cv2.getTickCount()) / cv2.getTickFrequency()
            if self.head_pose != old_pose and now - self.last_debug_time > 1.0:
                self.logger.debug(f"{self.head_pose.upper()} detected! Ratio: {avg_ratio:.2f}, Offset: {avg_offset:.1f}")
                self.last_debug_time = now
            
            # Debug visualization
            cv2.circle(frame, tuple(nose), 2, (0, 255, 0), -1)
            cv2.circle(frame, tuple(left_eye), 2, (0, 255, 0), -1)
            cv2.circle(frame, tuple(right_eye), 2, (0, 255, 0), -1)
            cv2.line(frame, tuple(nose), tuple(left_eye), (255, 0, 0), 1)
            cv2.line(frame, tuple(nose), tuple(right_eye), (255, 0, 0), 1)
            direction_x = int(x + w/2 + (avg_ratio - 1) * 50)
            direction_y = int(face_center_y + avg_offset)
            cv2.line(frame, (int(x + w/2), int(face_center_y)), (direction_x, direction_y), (0, 255, 255), 2)
        
        return self.head_pose
    
    def detect_action(self, frame: np.ndarray, face_rect: Tuple[int, int, int, int]) -> bool:
        if self.current_action is None or face_rect is None:
            return False
        
        current_pose = self.detect_head_pose(frame, face_rect)
        self.action_completed = (current_pose.lower() == self.current_action.lower())
        return self.action_completed
    
    def is_action_completed(self):
        return self.action_completed
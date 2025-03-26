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
        """Initialize the action detector with configuration."""
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Load dlib face detector and shape predictor
        self.dlib_detector = dlib.get_frontal_face_detector()
        try:
            self.dlib_predictor = dlib.shape_predictor("shape_predictor_68_face_landmarks.dat")
            self.using_dlib = True
            self.logger.info("Using dlib for facial landmark detection in ActionDetector")
        except Exception as e:
            self.logger.error(f"Could not load dlib shape predictor: {e}")
            self.using_dlib = False
            raise ValueError("Dlib shape predictor is required for action detection")
        
        # Action detection variables
        self.current_action = None
        self.action_completed = False
        self.action_start_time = None
        
        # Head pose tracking
        self.face_positions = deque(maxlen=config.FACE_POSITION_HISTORY_LENGTH)
        self.face_angles = deque(maxlen=config.FACE_POSITION_HISTORY_LENGTH)
        self.head_pose = "center"  # center, left, right, up, down
    
    def set_action(self, action: str) -> None:
        """
        Set the current action to detect.
        
        Args:
            action: Action name ("left", "right", "up", "down")
        """
        self.current_action = action
        self.action_completed = False
        self.action_start_time = None
        self.logger.debug(f"Action set to: {action}")
    
    def detect_head_pose(self, frame: np.ndarray, face_rect: Tuple[int, int, int, int]) -> str:
        """
        Detect head pose (left, right, up, down, center).
        
        Args:
            frame: Input video frame
            face_rect: Face rectangle (x, y, w, h)
            
        Returns:
            Head pose as string: "left", "right", "up", "down", or "center"
        """
        if face_rect is None:
            return self.head_pose
            
        x, y, w, h = face_rect
        
        face_center_x = x + w/2
        frame_center_x = frame.shape[1] / 2
        face_center_y = y + h/2
        frame_center_y = frame.shape[0] / 2
        
        x_offset = face_center_x - frame_center_x
        y_offset = face_center_y - frame_center_y
        
        x_offset_normalized = x_offset / (frame.shape[1] / 2)
        y_offset_normalized = y_offset / (frame.shape[0] / 2)
        
        self.face_angles.append((x_offset_normalized, y_offset_normalized))
        
        if len(self.face_angles) >= 5:
            angles_list = list(self.face_angles)
            avg_x_offset = sum(a[0] for a in angles_list) / len(angles_list)
            avg_y_offset = sum(a[1] for a in angles_list) / len(angles_list)
            
            x_threshold = self.config.HEAD_POSE_THRESHOLD_X
            y_threshold_up = self.config.HEAD_POSE_THRESHOLD_Y_UP
            y_threshold_down = self.config.HEAD_POSE_THRESHOLD_Y_DOWN
            
            self.logger.debug(f"Head position - X offset: {avg_x_offset:.2f}, Y offset: {avg_y_offset:.2f}")
            
            old_pose = self.head_pose
            if avg_x_offset < -x_threshold:
                self.head_pose = "right"
                if old_pose != "right":
                    self.logger.debug("RIGHT detected!")
            elif avg_x_offset > x_threshold:
                self.head_pose = "left"
                if old_pose != "left":
                    self.logger.debug("LEFT detected!")
            elif avg_y_offset < -y_threshold_up:
                self.head_pose = "up"
                if old_pose != "up":
                    self.logger.debug("UP detected!")
            elif avg_y_offset > y_threshold_down:
                self.head_pose = "down"
                if old_pose != "down":
                    self.logger.debug("DOWN detected!")
            else:
                self.head_pose = "center"
                if old_pose != "center":
                    self.logger.debug("CENTER detected!")
            
            # Draw direction indicator for debugging
            center_x = int(frame.shape[1] / 2)
            center_y = int(frame.shape[0] / 2)
            direction_x = int(center_x + avg_x_offset * 100)
            direction_y = int(center_y + avg_y_offset * 100)
            cv2.line(frame, (center_x, center_y), (direction_x, direction_y), (0, 255, 255), 2)
        
        return self.head_pose
    
    def detect_action(self, frame: np.ndarray, face_rect: Tuple[int, int, int, int]) -> bool:
        """
        Detect the specified action.
        
        Args:
            frame: Input video frame
            face_rect: Face rectangle (x, y, w, h)
            
        Returns:
            True if action is detected, False otherwise
        """
        if self.current_action is None or face_rect is None:
            return False
            
        current_pose = self.detect_head_pose(frame, face_rect)
        self.action_completed = current_pose.lower() == self.current_action.lower()
        
        return self.action_completed
    
    def is_action_completed(self):
        """Check if the current action is completed."""
        return self.action_completed 
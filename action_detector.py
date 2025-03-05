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
        self.landmark_history = []  # Store recent landmarks for tracking movement
        self.max_history = 30  # Maximum number of frames to keep in history
        
        # Head pose tracking
        self.face_positions = deque(maxlen=30)
        self.face_angles = deque(maxlen=30)
        self.head_pose = "center"  # center, left, right, up, down
        
        # Thresholds for different actions
        self.nod_threshold = 0.15  # Vertical movement threshold for nodding
        self.shake_threshold = 0.15  # Horizontal movement threshold for shaking
        self.tilt_threshold = 0.15  # Rotation threshold for tilting
    
    def set_action(self, action: str) -> None:
        """
        Set the current action to detect.
        
        Args:
            action: Action name ("nod", "shake", "tilt")
        """
        self.current_action = action
        self.action_completed = False
        self.action_start_time = None
        self.landmark_history = []
        self.logger.debug(f"Action set to: {action}")
    
    def get_landmarks(self, frame: np.ndarray, face_rect: Tuple[int, int, int, int]) -> Optional[np.ndarray]:
        """
        Get facial landmarks using dlib.
        
        Args:
            frame: Input video frame
            face_rect: Face rectangle (x, y, w, h)
            
        Returns:
            Array of facial landmarks or None if detection fails
        """
        if not self.using_dlib:
            return None
            
        x, y, w, h = face_rect
        
        # Convert to dlib rectangle
        rect = dlib.rectangle(x, y, x+w, y+h)
        
        # Get facial landmarks
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        landmarks = self.dlib_predictor(gray, rect)
        
        # Convert to numpy array
        points = np.zeros((68, 2), dtype=np.float32)
        for i in range(68):
            points[i] = (landmarks.part(i).x, landmarks.part(i).y)
            
        return points
    
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
            
        try:
            landmarks = self.get_landmarks(frame, face_rect)
        except Exception as e:
            self.logger.error(f"Error extracting landmarks: {e}")
            return False
        
        if landmarks is not None:
            self.landmark_history.append(landmarks)
            if len(self.landmark_history) > self.max_history:
                self.landmark_history.pop(0)
        
        # Detect the specified action
        if self.current_action.lower() == "nod":
            self.action_completed = self.detect_nod(landmarks)
        elif self.current_action.lower() == "shake":
            self.action_completed = self.detect_shake(landmarks)
        elif self.current_action.lower() == "tilt":
            self.action_completed = self.detect_tilt(landmarks)
        elif self.current_action.lower() in ["left", "right", "up", "down"]:
            current_pose = self.detect_head_pose(frame, face_rect)
            self.action_completed = current_pose.lower() == self.current_action.lower()
        else:
            self.logger.warning(f"Unknown action: {self.current_action}")
        
        return self.action_completed
    
    def detect_nod(self, landmarks: np.ndarray) -> bool:
        """
        Detect head nodding (up and down movement).
        
        Args:
            landmarks: Current facial landmarks
            
        Returns:
            True if nodding is detected, False otherwise
        """
        if landmarks is None or len(self.landmark_history) < 5:
            return False
            
        # Use nose tip (point 30) for tracking vertical movement
        nose_y_positions = [lm[30][1] for lm in self.landmark_history[-10:]]
        
        # Calculate vertical movement
        min_y = min(nose_y_positions)
        max_y = max(nose_y_positions)
        movement_range = max_y - min_y
        
        # Check if movement exceeds threshold
        frame_height = 480  # Assuming standard frame height
        normalized_movement = movement_range / frame_height
        
        # Check for direction changes (at least 2 for a nod)
        direction_changes = 0
        for i in range(1, len(nose_y_positions) - 1):
            if (nose_y_positions[i-1] < nose_y_positions[i] and 
                nose_y_positions[i] > nose_y_positions[i+1]) or \
               (nose_y_positions[i-1] > nose_y_positions[i] and 
                nose_y_positions[i] < nose_y_positions[i+1]):
                direction_changes += 1
        
        if normalized_movement > self.nod_threshold and direction_changes >= 2:
            self.logger.debug(f"Nod detected! Movement: {normalized_movement:.2f}, Changes: {direction_changes}")
            return True
            
        return False
    
    def detect_shake(self, landmarks: np.ndarray) -> bool:
        """
        Detect head shaking (left and right movement).
        
        Args:
            landmarks: Current facial landmarks
            
        Returns:
            True if shaking is detected, False otherwise
        """
        if landmarks is None or len(self.landmark_history) < 5:
            return False
            
        # Use nose tip (point 30) for tracking horizontal movement
        nose_x_positions = [lm[30][0] for lm in self.landmark_history[-10:]]
        
        # Calculate horizontal movement
        min_x = min(nose_x_positions)
        max_x = max(nose_x_positions)
        movement_range = max_x - min_x
        
        # Check if movement exceeds threshold
        frame_width = 640  # Assuming standard frame width
        normalized_movement = movement_range / frame_width
        
        # Check for direction changes (at least 2 for a shake)
        direction_changes = 0
        for i in range(1, len(nose_x_positions) - 1):
            if (nose_x_positions[i-1] < nose_x_positions[i] and 
                nose_x_positions[i] > nose_x_positions[i+1]) or \
               (nose_x_positions[i-1] > nose_x_positions[i] and 
                nose_x_positions[i] < nose_x_positions[i+1]):
                direction_changes += 1
        
        if normalized_movement > self.shake_threshold and direction_changes >= 2:
            self.logger.debug(f"Shake detected! Movement: {normalized_movement:.2f}, Changes: {direction_changes}")
            return True
            
        return False
    
    def detect_tilt(self, landmarks: np.ndarray) -> bool:
        """
        Detect head tilting (rotation).
        
        Args:
            landmarks: Current facial landmarks
            
        Returns:
            True if tilting is detected, False otherwise
        """
        if landmarks is None or len(self.landmark_history) < 5:
            return False
            
        # Use eyes to detect tilt (angle between eyes)
        left_eye = landmarks[36:42].mean(axis=0)
        right_eye = landmarks[42:48].mean(axis=0)
        
        # Calculate angle
        dx = right_eye[0] - left_eye[0]
        dy = right_eye[1] - left_eye[1]
        angle = np.degrees(np.arctan2(dy, dx))
        
        # Check if tilt exceeds threshold
        if abs(angle) > self.tilt_threshold:
            self.logger.debug(f"Tilt detected! Angle: {angle:.2f}")
            return True
            
        return False
    
    def is_action_completed(self):
        """Check if the current action is completed."""
        return self.action_completed 
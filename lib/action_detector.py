"""Action detection module for liveness verification.

This module is responsible for detecting specific head movements and actions
required for liveness verification challenges. It uses facial landmarks to
determine head pose and track movements with optimized processing for
better performance over the internet.
"""

import cv2
import numpy as np
import logging
import dlib
import time
from typing import List, Tuple, Dict, Any, Optional
from collections import deque

class ActionDetector:
    """Detects specific actions for liveness verification.
    
    This class analyzes facial landmarks to determine head pose and detect
    specific actions like looking left, right, up, or down. It includes
    optimizations for efficient processing over network connections.
    
    Attributes:
        config: Configuration settings
        dlib_detector: Face detector from dlib
        dlib_predictor: Facial landmark predictor from dlib
        current_action: The action currently being verified
        action_completed: Whether the current action has been completed
        face_angles: Queue of recent face angle measurements for smoothing
        head_pose: Current detected head pose
        processing_mode: Current processing mode (normal or action_detection)
        landmark_cache: Cache of facial landmarks to avoid redundant processing
    """
    
    def __init__(self, config):
        """Initialize the action detector with configuration settings.
        
        Args:
            config: Configuration object containing settings
        """
        self.config = config  # Store configuration object
        self.logger = logging.getLogger(__name__)  # Create logger for this module
        
        self.dlib_detector = dlib.get_frontal_face_detector()  # Initialize dlib face detector
        try:
            # Load dlib's facial landmark predictor
            self.dlib_predictor = dlib.shape_predictor("bin/shape_predictor_68_face_landmarks.dat")
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
        
        # Frame sampling strategy variables
        self.frame_count = 0  # Counter for frame sampling
        self.last_processed_frame_time = 0.0  # Timestamp of last processed frame
        self.processing_mode = "normal"  # Current processing mode
        self.last_landmarks = None  # Store last detected landmarks for interpolation
        self.last_pose_change_time = 0.0  # Time of last pose change
        
        # Adaptive sampling rates based on detection needs
        self.sampling_rates = {
            "normal": 3,           # Process 1 in 3 frames in normal mode
            "action_detection": 2  # Process 1 in 2 frames during action detection
        }
        
        # Cache for landmark calculations to avoid redundant processing
        self.landmark_cache = {}
        self.cache_ttl = 0.5  # Cache time-to-live in seconds
        self.last_cache_cleanup = time.time()
        
        # Network optimization variables
        self.network_quality = "medium"  # Current network quality assessment
        self.last_network_update = time.time()  # Last time network quality was updated
    
    def set_action(self, action: str) -> None:
        """Set the action to detect.
        
        Args:
            action: The action to detect (e.g., "turn left", "look up")
        """
        self.current_action = action  # Assign new action
        self.action_completed = False  # Reset completion flag
        self.action_start_time = None  # Clear start time
        self.processing_mode = "action_detection"  # Switch to action detection mode
        self.logger.info(f"Action set to: {action}")  # Log action setting
    
    def should_process_frame(self) -> bool:
        """Determine if the current frame should be processed based on sampling strategy.
        
        Returns:
            Boolean indicating whether to process the current frame
        """
        self.frame_count += 1
        
        # Check if we're in a critical detection phase
        now = time.time()
        if now - self.last_pose_change_time < 1.0:
            return True  # Process every frame shortly after a pose change
        
        # Sample frames based on current mode and network quality
        base_sampling_rate = self.sampling_rates.get(self.processing_mode, 2)
        
        # Adjust sampling rate based on network quality
        if self.network_quality == "low":
            # Reduce sampling rate further for low network quality
            sampling_rate = base_sampling_rate + 1
        elif self.network_quality == "high":
            # Increase sampling rate for high network quality
            sampling_rate = max(1, base_sampling_rate - 1)
        else:
            # Use base sampling rate for medium network quality
            sampling_rate = base_sampling_rate
            
        return self.frame_count % sampling_rate == 0
    
    def cleanup_cache(self) -> None:
        """Clean up expired entries in the landmark cache."""
        now = time.time()
        if now - self.last_cache_cleanup < 5.0:  # Only clean up every 5 seconds
            return
            
        expired_keys = []
        for key, (timestamp, _) in self.landmark_cache.items():
            if now - timestamp > self.cache_ttl:
                expired_keys.append(key)
                
        for key in expired_keys:
            del self.landmark_cache[key]
            
        self.last_cache_cleanup = now
    
    def set_network_quality(self, quality: str) -> None:
        """Update the network quality assessment.
        
        Args:
            quality: Network quality level ("high", "medium", or "low")
        """
        if quality in ["high", "medium", "low"] and quality != self.network_quality:
            self.network_quality = quality
            self.logger.debug(f"Network quality set to: {quality}")
            self.last_network_update = time.time()
    
    def detect_head_pose(self, frame: np.ndarray, face_rect: Tuple[int, int, int, int]) -> str:
        """Detect head pose (left, right, up, down, center) using facial landmarks.
        
        This method is optimized with frame sampling and caching to reduce
        processing load and bandwidth usage.
        
        Args:
            frame: Video frame to process
            face_rect: Rectangle coordinates of detected face (x, y, w, h)
            
        Returns:
            String indicating detected head pose
        """
        if face_rect is None:
            return self.head_pose  # Return last known pose if no face detected
        
        # Check if we should process this frame based on sampling strategy
        if not self.should_process_frame():
            return self.head_pose  # Return last known pose if skipping this frame
        
        x, y, w, h = face_rect  # Unpack face rectangle coordinates
        
        # Generate cache key based on face position
        cache_key = f"{x}_{y}_{w}_{h}"
        now = time.time()
        
        # Check if we have cached landmarks for this face position
        if cache_key in self.landmark_cache and now - self.landmark_cache[cache_key][0] < self.cache_ttl:
            # Use cached landmarks
            landmarks = self.landmark_cache[cache_key][1]
            self.logger.debug("Using cached landmarks for head pose detection")
        else:
            # Process new landmarks
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)  # Convert frame to grayscale
            dlib_rect = dlib.rectangle(x, y, x + w, y + h)  # Create dlib rectangle
            landmarks = self.dlib_predictor(gray, dlib_rect)  # Detect facial landmarks
            
            # Cache the landmarks
            self.landmark_cache[cache_key] = (now, landmarks)
            self.last_landmarks = landmarks  # Store for future reference
            
            # Clean up cache periodically
            self.cleanup_cache()

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
            UP_THRESHOLD = self.config.HEAD_POSE_THRESHOLD_UP  # Negative for upward movement
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
            
            # If pose changed, update processing mode and timestamp
            if self.head_pose != old_pose:
                self.last_pose_change_time = now
                self.processing_mode = "action_detection"  # Increase sampling rate after pose change
                
                # Log pose change if it differs and rate-limited (1-second interval)
                if now - self.last_debug_time > 1.0:
                    self.logger.debug(f"{self.head_pose.upper()} detected! Ratio: {avg_ratio:.2f}, Offset: {avg_offset:.1f}")
                    self.last_debug_time = now
            elif now - self.last_pose_change_time > 2.0 and self.processing_mode == "action_detection":
                # Return to normal mode if pose has been stable for 2 seconds
                self.processing_mode = "normal"
            
            # Add debug visualization to frame (only when needed)
            if self.config.SHOW_DEBUG_FRAME:
                cv2.circle(frame, tuple(nose), 2, (0, 255, 0), -1)  # Mark nose
                cv2.circle(frame, tuple(left_eye), 2, (0, 255, 0), -1)  # Mark left eye
                cv2.circle(frame, tuple(right_eye), 2, (0, 255, 0), -1)  # Mark right eye
                cv2.line(frame, tuple(nose), tuple(left_eye), (255, 0, 0), 1)  # Line to left eye
                cv2.line(frame, tuple(nose), tuple(right_eye), (255, 0, 0), 1)  # Line to right eye
                direction_x = int(x + w/2 + (avg_ratio - 1) * 50)  # Horizontal direction indicator
                direction_y = int(face_center_y + avg_offset)  # Vertical direction indicator
                cv2.line(frame, (int(x + w/2), int(face_center_y)), (direction_x, direction_y), (0, 255, 255), 2)  # Direction line
        
        self.last_processed_frame_time = now
        return self.head_pose  # Return detected pose
    
    def detect_action(self, frame: np.ndarray, face_rect: Tuple[int, int, int, int]) -> bool:
        """Detect if the specified action is performed.
        
        Args:
            frame: Video frame to process
            face_rect: Rectangle coordinates of detected face (x, y, w, h)
            
        Returns:
            Boolean indicating whether the action is completed
        """
        if self.current_action is None or face_rect is None:
            return False  # No action to detect or no face
        
        # Switch to action detection mode when actively checking for an action
        self.processing_mode = "action_detection"
        
        current_pose = self.detect_head_pose(frame, face_rect)  # Get current head pose
        
        # Check if pose matches action (handle special case for "blink twice")
        if self.current_action.lower() == "blink twice":
            # This is handled by the blink detector, not here
            return self.action_completed
        else:
            # For directional actions, check if pose matches
            action_pose = self.current_action.lower().replace("turn ", "").replace("look ", "")
            self.action_completed = (current_pose.lower() == action_pose)
        
        # If action is completed, we can return to normal processing mode
        if self.action_completed:
            self.processing_mode = "normal"
            
        return self.action_completed  # Return completion status
    
    def is_action_completed(self) -> bool:
        """Check if the current action has been completed.
        
        Returns:
            Boolean indicating whether the action is completed
        """
        return self.action_completed
    
    def get_state(self) -> Dict[str, Any]:
        """Get current state information for external components.
        
        Returns:
            Dictionary containing current state information
        """
        return {
            'head_pose': self.head_pose,
            'action_completed': self.action_completed,
            'processing_mode': self.processing_mode,
            'current_action': self.current_action,
            'network_quality': self.network_quality
        }
    
    def set_processing_mode(self, mode: str) -> None:
        """Set the processing mode externally (e.g., from challenge manager).
        
        Args:
            mode: Processing mode to set ("normal" or "action_detection")
        """
        if mode in self.sampling_rates:
            self.processing_mode = mode
            self.logger.debug(f"Processing mode set to: {mode}")

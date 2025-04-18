"""Face detection and head pose estimation module.

This module is responsible for detecting faces in video frames and estimating
head pose for liveness verification. It includes optimizations for efficient
processing over network connections with adaptive sampling and caching.
"""

import cv2
import numpy as np
from collections import deque
import logging
import time
from typing import Tuple, Optional, Dict, Any, List
from config import Config
from lib.utils.frame_utils import save_frame
class FaceDetector:
    """Handles face detection and head pose estimation.
    
    This class detects faces in video frames and estimates head pose using
    facial landmarks. It includes optimizations for efficient processing
    over network connections, including targeted search, progressive detection
    parameters, and result caching.
    
    Attributes:
        config: Configuration settings
        face_detector: OpenCV cascade classifier for face detection
        face_positions: Queue of recent face positions for tracking
        face_angles: Queue of recent face angles for head pose estimation
        head_pose: Current detected head pose
        processing_mode: Current processing mode (normal or detection)
        last_face_rect: Last detected face rectangle for targeted search
        face_cache: Cache of face detection results to avoid redundant processing
    """
    
    def __init__(self, config: Config):
        """Initialize the face detector with configuration settings.
        
        Args:
            config: Configuration object containing settings
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.frame_count = 0
        
        # Load cascade
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        self.logger.info(f"Attempting to load cascade from: {cascade_path}")
        self.face_detector = cv2.CascadeClassifier(cascade_path)
        if self.face_detector.empty():
            self.logger.error("Failed to load face detector cascade")
            raise ValueError("Failed to load face detector cascade")
        self.logger.info("Face detector cascade loaded successfully")
        
        # Initialize tracking variables
        self.face_positions = deque(maxlen=30)
        self.face_angles = deque(maxlen=30)
        self.head_pose = "center"
        self.movement_detected = False
        
        # Rate-limit debug logs
        self.last_debug_time = 0.0
        
        # Frame sampling strategy variables
        self.frame_count = 0
        self.last_processed_frame_time = 0.0
        self.processing_mode = "normal"  # Can be "normal" or "detection"
        
        # Adaptive sampling rates based on detection needs
        self.sampling_rates = {
            "normal": 3,       # Process 1 in 3 frames in normal mode
            "detection": 2     # Process 1 in 2 frames during active detection
        }
        
        # Face detection optimization
        self.last_face_rect = None
        self.face_detection_confidence = 0.0
        self.detection_scale_factors = [1.1, 1.05, 1.03]  # Progressive scale factors
        self.detection_min_neighbors = [5, 3, 2]  # Progressive min neighbors
        self.detection_min_sizes = [(30, 30), (25, 25), (20, 20)]  # Progressive min sizes
        
        # Cache for face detection results
        self.face_cache = {}
        self.cache_ttl = 0.5  # Cache time-to-live in seconds
        self.last_cache_cleanup = time.time()
        
        # Network optimization variables
        self.network_quality = "medium"  # Current network quality assessment
        self.last_network_update = time.time()  # Last time network quality was updated
    
    def should_process_frame(self) -> bool:
        """Determine if the current frame should be processed based on sampling strategy.
        
        Returns:
            Boolean indicating whether to process the current frame
        """
        self.frame_count += 1
        
        # Check if we're in a critical detection phase
        now = time.time()
        if self.last_face_rect is None or now - self.last_processed_frame_time > 1.0:
            return True  # Process frame if no face detected recently or it's been a while
            
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
        """Clean up expired entries in the face cache."""
        now = time.time()
        if now - self.last_cache_cleanup < 5.0:  # Only clean up every 5 seconds
            return
            
        expired_keys = []
        for key, (timestamp, _) in self.face_cache.items():
            if now - timestamp > self.cache_ttl:
                expired_keys.append(key)
                
        for key in expired_keys:
            del self.face_cache[key]
            
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
            
            # Adjust cache TTL based on network quality
            if quality == "low":
                self.cache_ttl = 0.8  # Longer cache lifetime for low quality networks
            elif quality == "high":
                self.cache_ttl = 0.3  # Shorter cache lifetime for high quality networks
            else:
                self.cache_ttl = 0.5  # Default cache lifetime for medium quality
    
    def detect_face(self, frame: np.ndarray) -> Tuple[Optional[np.ndarray], Optional[Tuple[int,int,int,int]]]:
        """Detect face in frame with optimized processing.
        
        This method uses a targeted search approach, looking first around the last
        known face position before scanning the entire frame. It also employs
        progressive detection parameters and result caching for efficiency.
        
        Args:
            frame: Video frame to process
            
        Returns:
            Tuple containing face ROI and face rectangle (x, y, width, height)
        """
        now = time.time()
        frame_interval = self.config.SAVE_FRAMES_INTERVAL

        self.frame_count += 1
        if self.config.SAVE_FRAMES and self.frame_count % frame_interval == 0:
            save_frame(frame, out_dir=self.config.SAVE_FRAMES_DIR, prefix="face_debug_IN", logger=self.logger, frame_count=self.frame_count)
        
        # Check if we should process this frame based on sampling strategy
        if not self.should_process_frame() and self.last_face_rect is not None:
            # Return last known face if we're skipping this frame
            x, y, w, h = self.last_face_rect
            if 0 <= x < frame.shape[1] and 0 <= y < frame.shape[0]:
                w = min(w, frame.shape[1] - x)
                h = min(h, frame.shape[0] - y)
                if w > 0 and h > 0:
                    face_roi = frame[y:y+h, x:x+w]
                    return face_roi, self.last_face_rect
            return None, None
        
        if frame is None or frame.size == 0:
            self.logger.error("Received empty or None frame")
            return None, None
        
        # Generate cache key based on frame content (simple hash)
        # Only use a portion of the frame for faster hashing
        center_x, center_y = frame.shape[1] // 2, frame.shape[0] // 2
        sample_size = min(100, min(frame.shape[0], frame.shape[1]) // 2)
        sample_x = max(0, center_x - sample_size // 2)
        sample_y = max(0, center_y - sample_size // 2)
        sample = frame[sample_y:sample_y+sample_size, sample_x:sample_x+sample_size]
        frame_hash = hash(sample.tobytes()) % 10000000
        cache_key = f"face_{frame_hash}"
        
        # Check if we have cached results for this frame
        if cache_key in self.face_cache and now - self.face_cache[cache_key][0] < self.cache_ttl:
            face_roi, face_rect = self.face_cache[cache_key][1]
            if face_rect is not None:
                self.last_face_rect = face_rect
            return face_roi, face_rect
        
        # Convert to grayscale for face detection
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # If we have a previous face location, first try a targeted search
        faces = []
        if self.last_face_rect is not None:
            x, y, w, h = self.last_face_rect
            # Add padding around last known position
            padding = int(max(w, h) * 0.2)
            search_x = max(0, x - padding)
            search_y = max(0, y - padding)
            search_w = min(frame.shape[1] - search_x, w + 2*padding)
            search_h = min(frame.shape[0] - search_y, h + 2*padding)
            
            if search_w > 0 and search_h > 0:
                search_roi = gray[search_y:search_y+search_h, search_x:search_x+search_w]
                local_faces = self.face_detector.detectMultiScale(search_roi, 1.05, 3)
                
                # Adjust coordinates back to full frame
                if len(local_faces) > 0:
                    for (fx, fy, fw, fh) in local_faces:
                        faces.append((fx + search_x, fy + search_y, fw, fh))
        
        # If targeted search failed, try full frame with progressive parameters
        if len(faces) == 0:
            # Adjust detection parameters based on network quality
            if self.network_quality == "low":
                # Use more aggressive parameters for low quality networks
                scale_factors = [1.2, 1.1, 1.05]
                min_neighbors_values = [6, 4, 3]
                min_sizes = [(40, 40), (30, 30), (25, 25)]
            elif self.network_quality == "high":
                # Use more precise parameters for high quality networks
                scale_factors = [1.05, 1.03, 1.01]
                min_neighbors_values = [4, 3, 2]
                min_sizes = [(25, 25), (20, 20), (15, 15)]
            else:
                # Use default parameters for medium quality networks
                scale_factors = self.detection_scale_factors
                min_neighbors_values = self.detection_min_neighbors
                min_sizes = self.detection_min_sizes
            
            # Try detection with progressive parameters
            for scale, neighbors, min_size in zip(scale_factors, 
                                                min_neighbors_values,
                                                min_sizes):
                faces = self.face_detector.detectMultiScale(gray, scale, neighbors, minSize=min_size)
                if len(faces) > 0:
                    break
        
        # Fallback logic: If no face is detected, use the last known position
        if len(faces) == 0 and len(self.face_positions) > 0:
            last_x, last_y = self.face_positions[-1]
            est_size = 150  # Estimated size for fallback
            x = int(last_x - est_size // 2)
            y = int(last_y - est_size // 2)
            w = est_size
            h = est_size
            
            if 0 <= x < frame.shape[1] and 0 <= y < frame.shape[0]:
                w = min(w, frame.shape[1] - x)
                h = min(h, frame.shape[0] - y)
                if w > 0 and h > 0:
                    face_roi = frame[y:y+h, x:x+w]
                    face_rect = (x, y, w, h)
                    self.last_face_rect = face_rect
                    self.face_detection_confidence = 0.3  # Lower confidence for estimated position
                    
                    # Cache the result
                    self.face_cache[cache_key] = (now, (face_roi, face_rect))
                    self.cleanup_cache()
                    
                    if now - self.last_debug_time > 1.0:
                        self.logger.debug("Using estimated face position fallback")
                        self.last_debug_time = now
                    
                    self.last_processed_frame_time = now
                    return face_roi, face_rect
            
            # No face detected and fallback failed
            self.face_cache[cache_key] = (now, (None, None))
            self.face_detection_confidence = 0.0
            
            if now - self.last_debug_time > 1.0:
                self.logger.debug("No face detected in frame")
                self.last_debug_time = now
                
            self.last_processed_frame_time = now
            return None, None
        
        if len(faces) == 0:
            # No face detected
            self.face_cache[cache_key] = (now, (None, None))
            self.face_detection_confidence = 0.0
            
            if now - self.last_debug_time > 1.0:
                self.logger.debug("No face detected in frame")
                self.last_debug_time = now
                
            self.last_processed_frame_time = now
            return None, None
        
        # Select the largest face if multiple faces are detected
        face_rect = max(faces, key=lambda rect: rect[2] * rect[3])
        x, y, w, h = face_rect
        
        # Ensure face rectangle is within frame boundaries
        x = max(0, x)
        y = max(0, y)
        w = min(w, frame.shape[1] - x)
        h = min(h, frame.shape[0] - y)
        
        if w <= 0 or h <= 0:
            self.face_cache[cache_key] = (now, (None, None))
            self.face_detection_confidence = 0.0
            
            if now - self.last_debug_time > 1.0:
                self.logger.debug("Detected face ROI invalid")
                self.last_debug_time = now
                
            self.last_processed_frame_time = now
            return None, None
        
        # Extract face ROI
        face_roi = frame[y:y+h, x:x+w]
        face_rect = (x, y, w, h)
        self.last_face_rect = face_rect
        self.face_detection_confidence = 0.9  # High confidence for direct detection
        
        # Cache the result
        self.face_cache[cache_key] = (now, (face_roi, face_rect))
        self.cleanup_cache()
        
        if now - self.last_debug_time > 1.0:
            self.logger.debug(f"Face detected at: ({x}, {y}, {w}, {h})")
            self.last_debug_time = now

        # Save debug frame
        if self.config.SAVE_FRAMES and self.frame_count % frame_interval == 0:
            save_frame(frame, out_dir=self.config.SAVE_FRAMES_DIR, prefix="face_debug_OUT", logger=self.logger, frame_count=self.frame_count)
        
        self.last_processed_frame_time = now
        return face_roi, face_rect
    
    def detect_movement(self, face_rect: Tuple[int,int,int,int]) -> bool:
        """Detect if there is significant movement in face position.
        
        This method tracks face position changes over time to detect movement,
        which can be used to adjust processing modes and sampling rates.
        
        Args:
            face_rect: Rectangle coordinates of detected face (x, y, w, h)
            
        Returns:
            Boolean indicating whether significant movement is detected
        """
        if face_rect is None:
            return False
            
        x, y, w, h = face_rect
        cx = x + w/2
        cy = y + h/2
        
        self.face_positions.append((cx, cy))
        if len(self.face_positions) < 2:
            return False
        
        # Calculate movement only using the last few positions for efficiency
        positions = list(self.face_positions)[-5:] if len(self.face_positions) > 5 else list(self.face_positions)
        movement = 0
        for i in range(1, len(positions)):
            dx = positions[i][0] - positions[i-1][0]
            dy = positions[i][1] - positions[i-1][1]
            movement += np.sqrt(dx*dx + dy*dy)
        
        avg_movement = movement / (len(positions) - 1)
        
        # Adjust movement threshold based on network quality
        if self.network_quality == "low":
            threshold = 3.0  # Higher threshold for low quality networks
        elif self.network_quality == "high":
            threshold = 1.5  # Lower threshold for high quality networks
        else:
            threshold = 2.0  # Default threshold for medium quality networks
            
        self.movement_detected = avg_movement > threshold
        
        # If significant movement is detected, switch to detection mode
        if self.movement_detected:
            self.processing_mode = "detection"
        elif self.processing_mode == "detection" and not self.movement_detected:
            # Return to normal mode if no movement for a while
            self.processing_mode = "normal"
            
        return self.movement_detected
    
    def detect_head_pose(self, frame: np.ndarray,
                         face_rect: Tuple[int,int,int,int]) -> str:
        """Detect head pose (left, right, up, down, center) based on face position.
        
        This method estimates head pose by analyzing the position of the face
        within the frame, with smoothing to reduce jitter.
        
        Args:
            frame: Video frame to process
            face_rect: Rectangle coordinates of detected face (x, y, w, h)
            
        Returns:
            String indicating detected head pose
        """
        if face_rect is None:
            return self.head_pose
        
        # Check if we should process this frame based on sampling strategy
        if not self.should_process_frame():
            return self.head_pose  # Return last known pose if skipping this frame
        
        x, y, w, h = face_rect
        face_cx = x + w/2
        face_cy = y + h/2
        frame_cx = frame.shape[1]/2
        frame_cy = frame.shape[0]/2
        
        x_offset = face_cx - frame_cx
        y_offset = face_cy - frame_cy
        
        x_offset_norm = x_offset/(frame.shape[1]/2)
        y_offset_norm = y_offset/(frame.shape[0]/2)
        
        self.face_angles.append((x_offset_norm, y_offset_norm))
        
        if len(self.face_angles) >= 5:
            # Use only the last 5 angles for more responsive detection
            angles_list = list(self.face_angles)[-5:]
            avg_x = sum(a[0] for a in angles_list)/len(angles_list)
            avg_y = sum(a[1] for a in angles_list)/len(angles_list)
            
            # Adjust thresholds based on network quality
            if self.network_quality == "low":
                # Use more forgiving thresholds for low quality networks
                x_thr = self.config.HEAD_POSE_THRESHOLD_X * 1.2
                y_thr_up = self.config.HEAD_POSE_THRESHOLD_Y_UP * 1.2
                y_thr_down = self.config.HEAD_POSE_THRESHOLD_Y_DOWN * 1.2
            elif self.network_quality == "high":
                # Use more precise thresholds for high quality networks
                x_thr = self.config.HEAD_POSE_THRESHOLD_X * 0.9
                y_thr_up = self.config.HEAD_POSE_THRESHOLD_Y_UP * 0.9
                y_thr_down = self.config.HEAD_POSE_THRESHOLD_Y_DOWN * 0.9
            else:
                # Use default thresholds for medium quality networks
                x_thr = self.config.HEAD_POSE_THRESHOLD_X
                y_thr_up = self.config.HEAD_POSE_THRESHOLD_Y_UP
                y_thr_down = self.config.HEAD_POSE_THRESHOLD_Y_DOWN
            
            old_pose = self.head_pose
            if avg_x < -x_thr:
                self.head_pose = "right"
            elif avg_x > x_thr:
                self.head_pose = "left"
            elif avg_y < -y_thr_up:
                self.head_pose = "up"
            elif avg_y > y_thr_down:
                self.head_pose = "down"
            else:
                self.head_pose = "center"
            
            # If pose changed, switch to detection mode temporarily
            if old_pose != self.head_pose:
                self.processing_mode = "detection"
                
                now = time.time()
                if now - self.last_debug_time > 1.0:
                    self.logger.debug(f"{self.head_pose.upper()} detected!")
                    self.last_debug_time = now
            
            # Only draw debug visualization if needed
            if self.config.SHOW_DEBUG_FRAME:
                center_x = int(frame.shape[1]/2)
                center_y = int(frame.shape[0]/2)
                dir_x = int(center_x + avg_x*100)
                dir_y = int(center_y + avg_y*100)
                cv2.line(frame, (center_x, center_y), (dir_x, dir_y), (0, 255, 255), 2)
        
        return self.head_pose
    
    def draw_face_info(self, frame: np.ndarray,
                       face_rect: Tuple[int,int,int,int],
                       status: str,
                       score: float) -> None:
        """Draw face information on the frame.
        
        This method adds visual indicators and text to the frame for debugging
        and visualization purposes. It only draws when debug frame is enabled.
        
        Args:
            frame: Video frame to draw on
            face_rect: Rectangle coordinates of detected face (x, y, w, h)
            status: Status text to display
            score: Confidence score to display
        """
        if face_rect is None or not self.config.SHOW_DEBUG_FRAME:
            return
            
        x, y, w, h = face_rect
        
        color = (0, 0, 255)  # default red
        if status == "Live Person":
            color = (0, 255, 0)
        elif status == "Analyzing...":
            color = (0, 165, 255)
        
        cv2.rectangle(frame, (x, y), (x+w, y+h), color, 2)
        
        cv2.putText(frame, f"Status: {status}", (x, y-40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        cv2.putText(frame, f"Score: {score:.2f}", (x, y-10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        
        cv2.putText(frame, f"Head: {self.head_pose}",
                    (10, frame.shape[0]-50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        cv2.putText(frame, f"Movement: {'Yes' if self.movement_detected else 'No'}",
                    (10, frame.shape[0]-20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        # Add network quality indicator
        cv2.putText(frame, f"Network: {self.network_quality}",
                    (10, frame.shape[0]-80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    
    def get_state(self) -> Dict[str, Any]:
        """Get current state information for external components.
        
        Returns:
            Dictionary containing current state information
        """
        return {
            'head_pose': self.head_pose,
            'movement_detected': self.movement_detected,
            'face_detected': self.last_face_rect is not None,
            'detection_confidence': self.face_detection_confidence,
            'processing_mode': self.processing_mode,
            'network_quality': self.network_quality
        }
    
    def set_processing_mode(self, mode: str) -> None:
        """Set the processing mode externally.
        
        Args:
            mode: Processing mode to set ("normal" or "detection")
        """
        if mode in self.sampling_rates:
            self.processing_mode = mode
            self.logger.debug(f"Processing mode set to: {mode}")

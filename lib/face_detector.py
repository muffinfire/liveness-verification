# face_detector.py
# Face detection and head pose estimation module

import cv2
import numpy as np
from collections import deque
import logging
from typing import Tuple, Optional
import time
from lib.config import Config

# FaceDetector class for face detection and head pose estimation
class FaceDetector:

    # Initialise FaceDetector
    def __init__(self, config: Config):
        self.config = config # Store config object
        self.logger = logging.getLogger(__name__)
        
        # Load cascade classifier for face detection (as fallback if no dlib)
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        self.logger.info(f"Attempting to load cascade from: {cascade_path}")
        self.face_detector = cv2.CascadeClassifier(cascade_path)
        if self.face_detector.empty():
            self.logger.error("Failed to load face detector cascade")
            raise ValueError("Failed to load face detector cascade")
        
        # Log success
        self.logger.info("Face detector cascade loaded successfully")
        
        # Initialise face position history
        self.face_positions = deque(maxlen=30) # History of face positions
        self.face_angles = deque(maxlen=30) # History of face angles
        self.head_pose = "center" # Current head pose
        self.movement_detected = False # Whether movement has been detected
        
        # Rate-limit debug logs
        self.last_debug_time = 0.0
    
    # Detect face in frame using cascade classifier
    def detect_face(self, frame: np.ndarray) -> Tuple[Optional[np.ndarray], Optional[Tuple[int,int,int,int]]]:
        now = cv2.getTickCount() / cv2.getTickFrequency()
        
        # Check if frame is valid
        if frame is None or frame.size == 0:
            self.logger.error("Received empty or None frame")
            return None, None
        
        # Convert frame to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_detector.detectMultiScale(gray, 1.1, 5) # Detect faces in frame
        
        # If no faces are detected, try different scales
        if len(faces) == 0:
            faces = self.face_detector.detectMultiScale(gray, 1.05, 3, minSize=(30, 30))

        # If still no faces are detected, try even smaller scales
        if len(faces) == 0:
            faces = self.face_detector.detectMultiScale(gray, 1.03, 2, minSize=(20, 20))
        
        # Fallback logic: If no face is detected, use the last known position
        if len(faces) == 0 and len(self.face_positions) > 0:
            last_x, last_y = self.face_positions[-1] # Get last known face position
            est_size = 150  # Estimated size for fallback
            x = int(last_x - est_size // 2) # Calculate x coordinate of face ROI
            y = int(last_y - est_size // 2) # Calculate y coordinate of face ROI
            w = est_size # Calculate width of face ROI
            h = est_size # Calculate height of face ROI

            # Check if face ROI is within frame bounds
            if 0 <= x < frame.shape[1] and 0 <= y < frame.shape[0]:
                w = min(w, frame.shape[1] - x) # Ensure width is within frame bounds
                h = min(h, frame.shape[0] - y) # Ensure height is within frame bounds

                # If face ROI is valid, return it
                if w > 0 and h > 0:
                    face_roi = frame[y:y+h, x:x+w] # Get face ROI
                    if now - self.last_debug_time > 1.0:
                        self.logger.debug("Using estimated face position fallback")
                        self.last_debug_time = now
                    return face_roi, (x, y, w, h)
            
            return None, None
        
        # If no face is detected, log debug message
        if len(faces) == 0:
            if now - self.last_debug_time > 1.0:
                self.logger.debug("No face detected in frame")
                self.last_debug_time = now
            return None, None
        
        # Get largest face in frame
        face_rect = max(faces, key=lambda rect: rect[2] * rect[3]) # Get largest face in frame
        x, y, w, h = face_rect # Get x, y, width, height of face ROI
        x = max(0, x) # Ensure x is within frame bounds
        y = max(0, y) # Ensure y is within frame bounds
        w = min(w, frame.shape[1] - x) # Ensure width is within frame bounds
        h = min(h, frame.shape[0] - y) # Ensure height is within frame bounds

        # Check if face ROI is valid
        if w <= 0 or h <= 0:
            if now - self.last_debug_time > 1.0:
                self.logger.debug("Detected face ROI invalid")
                self.last_debug_time = now
            return None, None
        
        face_roi = frame[y:y+h, x:x+w] # Get face ROI
        
        # Log debug message
        if now - self.last_debug_time > 1.0:
            self.logger.debug(f"Face detected at: ({x}, {y}, {w}, {h})")
            self.last_debug_time = now
        
        return face_roi, (x, y, w, h)
    
    # Detect movement in face position history
    def detect_movement(self, face_rect: Tuple[int,int,int,int]) -> bool:
        if face_rect is None:
            return False
        x,y,w,h = face_rect # Get x, y, width, height of face ROI
        cx = x + w/2 # Calculate center x coordinate of face ROI
        cy = y + h/2 # Calculate center y coordinate of face ROI

        # Append face position to history
        self.face_positions.append((cx,cy))

        # If there are less than 2 face positions, return False
        if len(self.face_positions)<2:
            return False
        
        positions = list(self.face_positions) # Get list of face positions
        movement=0 # Initialise movement (distance moved)
        for i in range(1,len(positions)): # Iterate through face positions
            dx = positions[i][0]-positions[i-1][0] # Calculate x movement
            dy = positions[i][1]-positions[i-1][1] # Calculate y movement
            movement += np.sqrt(dx*dx + dy*dy) # Calculate movement
        
        avg_movement = movement / (len(positions)-1) # Calculate average movement
        self.movement_detected = avg_movement>2.0 # Set movement detected flag
        return self.movement_detected 
    
    # Detect head pose
    def detect_head_pose(self, frame: np.ndarray,
                         face_rect: Tuple[int,int,int,int]) -> str:
        if face_rect is None:
            return self.head_pose
        
        # Get face ROI coordinates
        x,y,w,h = face_rect # Get x, y, width, height of face ROI
        face_cx = x + w/2 # Calculate center x coordinate of face ROI
        face_cy = y + h/2 # Calculate center y coordinate of face ROI
        frame_cx = frame.shape[1]/2 # Calculate center x coordinate of frame
        frame_cy = frame.shape[0]/2 # Calculate center y coordinate of frame

        # Calculate x and y offsets (relative to frame center)
        x_offset = face_cx - frame_cx
        y_offset = face_cy - frame_cy

        # Normalise x and y offsets (relative to frame size)
        x_offset_norm = x_offset/(frame.shape[1]/2)
        y_offset_norm = y_offset/(frame.shape[0]/2)
        
        self.face_angles.append((x_offset_norm,y_offset_norm)) # Append face angle to history
        
        # If there are at least 5 face angles, calculate average x and y offsets
        if len(self.face_angles)>=5:
            angles_list = list(self.face_angles) # Get list of face angles
            avg_x = sum(a[0] for a in angles_list)/len(angles_list) # Calculate average x offset
            avg_y = sum(a[1] for a in angles_list)/len(angles_list) # Calculate average y offset
            
            x_thr = self.config.HEAD_POSE_THRESHOLD_X # Get x threshold
            y_thr_up = self.config.HEAD_POSE_THRESHOLD_Y_UP # Get y threshold for "up"
            y_thr_down = self.config.HEAD_POSE_THRESHOLD_Y_DOWN # Get y threshold for "down"
            
            # Update head pose based on average x and y offsets
            old_pose = self.head_pose # Get old head pose
            if avg_x < -x_thr: # If x offset is less than -x threshold
                self.head_pose="right" # Set head pose to "right"
            elif avg_x > x_thr: # If x offset is greater than x threshold
                self.head_pose="left" # Set head pose to "left"
            elif avg_y < -y_thr_up: # If y offset is less than -y threshold for "up"
                self.head_pose="up" # Set head pose to "up"
            elif avg_y > y_thr_down: # If y offset is greater than y threshold for "down"
                self.head_pose="down" # Set head pose to "down"
            else: # If x and y offsets are within thresholds
                self.head_pose="center" # Set head pose to "center"
            
            # Log debug message
            now = time.time()
            if old_pose != self.head_pose and now - self.last_debug_time > 1.0:
                self.logger.debug(f"{self.head_pose.upper()} detected!")
                self.last_debug_time = now
            
            # Draw line for debug
            center_x = int(frame.shape[1]/2) # Calculate center x coordinate of frame
            center_y = int(frame.shape[0]/2) # Calculate center y coordinate of frame
            dir_x = int(center_x + avg_x*100) # Calculate direction x coordinate
            dir_y = int(center_y + avg_y*100) # Calculate direction y coordinate
            cv2.line(frame, (center_x,center_y), (dir_x,dir_y), (0,255,255),2) # Draw line
        
        return self.head_pose
    
    # Draw face info on frame for debugging
    def draw_face_info(self, frame: np.ndarray,
                       face_rect: Tuple[int,int,int,int],
                       status: str,
                       score: float) -> None:
        if face_rect is None:
            return
        x,y,w,h = face_rect # Get x, y, width, height of face ROI
        
        color = (0,0,255) # Default color is red
        if status=="Live Person":
            color = (0,255,0) # Set color to green
        elif status=="Analyzing...":
            color = (0,165,255) # Set color to yellow
        
        # Draw debug rectangle and text on frame
        cv2.rectangle(frame, (x,y), (x+w, y+h), color,2) # Draw rectangle
        
        cv2.putText(frame, f"Status: {status}", (x,y-40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color,2) # Draw text for status
        cv2.putText(frame, f"Score: {score:.2f}", (x,y-10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color,2) # Draw text for score
        
        cv2.putText(frame, f"Head: {self.head_pose}",
                    (10, frame.shape[0]-50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255,255,255),2) # Draw text for head pose
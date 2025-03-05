"""Face detection and head pose estimation module."""

import cv2
import numpy as np
from collections import deque
import logging
from typing import Tuple, Optional

from config import Config

class FaceDetector:
    """Handles face detection and head pose estimation."""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Load cascade
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        self.logger.info(f"Attempting to load cascade from: {cascade_path}")
        self.face_detector = cv2.CascadeClassifier(cascade_path)
        if self.face_detector.empty():
            self.logger.error("Failed to load face detector cascade")
            raise ValueError("Failed to load face detector cascade")
        self.logger.info("Face detector cascade loaded successfully")
        
        self.face_positions = deque(maxlen=30)
        self.face_angles = deque(maxlen=30)
        self.head_pose = "center"
        self.movement_detected = False
    
    def detect_face(self, frame: np.ndarray) -> Tuple[Optional[np.ndarray], Optional[Tuple[int,int,int,int]]]:
        self.logger.debug(f"Detecting face in frame with shape: {frame.shape if frame is not None else 'None'}")
        if frame is None or frame.size == 0:
            self.logger.error("Received empty or None frame")
            return None, None
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_detector.detectMultiScale(gray, 1.1, 5)
        
        if len(faces) == 0:
            faces = self.face_detector.detectMultiScale(gray, 1.05, 3, minSize=(30, 30))
        if len(faces) == 0:
            faces = self.face_detector.detectMultiScale(gray, 1.03, 2, minSize=(20, 20))
        
        # Fallback logic: If no face is detected, use the last known position
        if len(faces) == 0 and len(self.face_positions) > 0:
            last_x, last_y = self.face_positions[-1]
            est_size = 150  # Estimated size for fallback
            x = int(last_x - est_size // 2)
            y = int(last_y - est_size // 2)
            w = est_size
            h = est_size
            self.logger.debug("Using estimated face position fallback")
            
            x = max(0, x)
            y = max(0, y)
            w = min(w, frame.shape[1] - x)
            h = min(h, frame.shape[0] - y)
            
            if w > 0 and h > 0:
                face_roi = frame[y:y+h, x:x+w]
                return face_roi, (x, y, w, h)
            else:
                self.logger.debug("Fallback face ROI invalid")
                return None, None
        
        if len(faces) == 0:
            self.logger.debug("No face detected in frame")
            return None, None
        
        face_rect = max(faces, key=lambda rect: rect[2] * rect[3])
        x, y, w, h = face_rect
        x = max(0, x)
        y = max(0, y)
        w = min(w, frame.shape[1] - x)
        h = min(h, frame.shape[0] - y)
        if w <= 0 or h <= 0:
            self.logger.debug("Detected face ROI invalid")
            return None, None
        
        face_roi = frame[y:y+h, x:x+w]
        self.logger.debug(f"Face detected at: ({x}, {y}, {w}, {h})")
        return face_roi, (x, y, w, h)
    
    def detect_movement(self, face_rect: Tuple[int,int,int,int]) -> bool:
        if face_rect is None:
            return False
        x,y,w,h = face_rect
        cx = x + w/2
        cy = y + h/2
        
        self.face_positions.append((cx,cy))
        if len(self.face_positions)<2:
            return False
        
        positions = list(self.face_positions)
        movement=0
        for i in range(1,len(positions)):
            dx = positions[i][0]-positions[i-1][0]
            dy = positions[i][1]-positions[i-1][1]
            movement += np.sqrt(dx*dx + dy*dy)
        
        avg_movement = movement / (len(positions)-1)
        self.movement_detected = avg_movement>2.0
        return self.movement_detected
    
    def detect_head_pose(self, frame: np.ndarray,
                         face_rect: Tuple[int,int,int,int]) -> str:
        if face_rect is None:
            return self.head_pose
        
        x,y,w,h = face_rect
        face_cx = x + w/2
        face_cy = y + h/2
        frame_cx = frame.shape[1]/2
        frame_cy = frame.shape[0]/2
        
        x_offset = face_cx - frame_cx
        y_offset = face_cy - frame_cy
        
        x_offset_norm = x_offset/(frame.shape[1]/2)
        y_offset_norm = y_offset/(frame.shape[0]/2)
        
        self.face_angles.append((x_offset_norm,y_offset_norm))
        
        if len(self.face_angles)>=5:
            angles_list = list(self.face_angles)
            avg_x = sum(a[0] for a in angles_list)/len(angles_list)
            avg_y = sum(a[1] for a in angles_list)/len(angles_list)
            
            x_thr = self.config.HEAD_POSE_THRESHOLD_X
            y_thr_up = self.config.HEAD_POSE_THRESHOLD_Y_UP
            y_thr_down = self.config.HEAD_POSE_THRESHOLD_Y_DOWN
            
            old_pose = self.head_pose
            if avg_x < -x_thr:
                self.head_pose="right"
            elif avg_x > x_thr:
                self.head_pose="left"
            elif avg_y < -y_thr_up:
                self.head_pose="up"
            elif avg_y > y_thr_down:
                self.head_pose="down"
            else:
                self.head_pose="center"
            
            if old_pose != self.head_pose:
                self.logger.debug(f"{self.head_pose.upper()} detected!")
            
            # draw line for debug
            center_x = int(frame.shape[1]/2)
            center_y = int(frame.shape[0]/2)
            dir_x = int(center_x + avg_x*100)
            dir_y = int(center_y + avg_y*100)
            cv2.line(frame, (center_x,center_y), (dir_x,dir_y), (0,255,255),2)
        
        return self.head_pose
    
    def draw_face_info(self, frame: np.ndarray,
                       face_rect: Tuple[int,int,int,int],
                       status: str,
                       score: float) -> None:
        if face_rect is None:
            return
        x,y,w,h = face_rect
        
        color = (0,0,255)  # default red
        if status=="Live Person":
            color = (0,255,0)
        elif status=="Analyzing...":
            color = (0,165,255)
        
        cv2.rectangle(frame, (x,y), (x+w, y+h), color,2)
        
        cv2.putText(frame, f"Status: {status}", (x,y-40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color,2)
        cv2.putText(frame, f"Score: {score:.2f}", (x,y-10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color,2)
        
        cv2.putText(frame, f"Head: {self.head_pose}",
                    (10, frame.shape[0]-50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255,255,255),2)
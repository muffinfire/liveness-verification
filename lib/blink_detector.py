"""Eye detection and blink analysis module."""

import cv2
import numpy as np
import time
import logging
import dlib
from typing import Tuple, Optional
from collections import deque

from lib.config import Config

class BlinkDetector:
    """Handles eye detection and blink analysis using facial landmarks."""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Load eye detectors (as fallback if no dlib)
        self.eye_detector = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')
        if self.eye_detector.empty():
            self.logger.warning("Failed to load eye detector cascade")
        
        # Load dlib face detector + shape predictor
        self.dlib_detector = dlib.get_frontal_face_detector()
        try:
            self.dlib_predictor = dlib.shape_predictor("bin/shape_predictor_68_face_landmarks.dat")
            self.using_dlib = True
            self.logger.info("Using dlib for facial landmark detection")
        except Exception as e:
            self.logger.warning(f"Could not load dlib shape predictor: {e}")
            self.logger.warning("Falling back to Haar cascade for eye detection")
            self.using_dlib = False
        
        # Blink detection variables
        self.blink_threshold = config.BLINK_THRESHOLD
        self.min_blink_frames = config.MIN_BLINK_FRAMES
        self.blink_frames = 0
        self.blink_counter = 0
        self.blink_detected = False
        self.last_blink_time = time.time()
        
        # Track EAR
        self.ear_history = deque(maxlen=30)
        self.eye_state = "open"  # can be "open", "closing", "closed", "opening"
        self.eye_state_start = time.time()

        # [CHANGED] Rate-limit debug logs to once per second
        self.last_debug_time = 0.0
    
    def calculate_ear(self, eye_points: np.ndarray) -> float:
        # Eye Aspect Ratio
        A = np.linalg.norm(eye_points[1] - eye_points[5])
        B = np.linalg.norm(eye_points[2] - eye_points[4])
        C = np.linalg.norm(eye_points[0] - eye_points[3])
        if C == 0:
            return 0
        return (A + B) / (2.0 * C)
    
    def detect_blinks_dlib(self, frame: np.ndarray,
                           face_rect: Tuple[int,int,int,int]) -> bool:
        """Detect blinks using dlib EAR. Draw lines on `frame` for debug."""
        if face_rect is None:
            return False
        
        x, y, w, h = face_rect
        rect = dlib.rectangle(x, y, x + w, y + h)
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        landmarks = self.dlib_predictor(gray, rect)
        
        left_eye = np.array([(landmarks.part(i).x, landmarks.part(i).y) for i in range(36, 42)])
        right_eye = np.array([(landmarks.part(i).x, landmarks.part(i).y) for i in range(42, 48)])
        
        left_ear = self.calculate_ear(left_eye)
        right_ear = self.calculate_ear(right_eye)
        avg_ear = (left_ear + right_ear) / 2.0
        self.ear_history.append(avg_ear)
        
        # Draw eye contours for debugging, rate-limited
        now = time.time()
        if now - self.last_debug_time > 1.0:
            for eye in [left_eye, right_eye]:
                for i in range(len(eye)):
                    pt1 = tuple(eye[i])
                    pt2 = tuple(eye[(i+1) % 6])
                    cv2.line(frame, pt1, pt2, (0,255,0), 1)
        
        # [CHANGED] Rate-limit debug logs
        if now - self.last_debug_time > 1.0:
            self.logger.debug(f"EAR: {avg_ear:.2f} (Threshold: {self.blink_threshold:.2f})")
        
        blink_detected_now = False
        
        if avg_ear < self.blink_threshold:
            self.blink_frames += 1
            if self.eye_state == "open":
                self.eye_state = "closing"
                self.eye_state_start = now
            elif (self.eye_state == "closing"
                  and (now - self.eye_state_start) > 0.1):
                self.eye_state = "closed"
                self.eye_state_start = now
        else:
            if (self.eye_state == "closed"
                and self.blink_frames >= self.min_blink_frames
                and (now - self.last_blink_time) > self.config.MIN_BLINK_INTERVAL):
                self.blink_counter += 1
                self.blink_detected = True
                blink_detected_now = True
                
                # [CHANGED] Rate-limit "BLINK DETECTED" info
                if now - self.last_debug_time > 1.0:
                    self.logger.info(f"BLINK DETECTED! Counter: {self.blink_counter}")
                
                self.last_blink_time = now
            
            self.eye_state = "open" if self.eye_state != "closed" else "opening"
            self.eye_state_start = now
            self.blink_frames = 0
        
        # Display EAR + blink count in face ROI
        face_roi = frame[y : y + h, x : x + w]
        cv2.putText(face_roi, f"EAR: {avg_ear:.2f}", (10,40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,255),1)
        cv2.putText(face_roi, f"Blinks: {self.blink_counter}", (10,20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,255),1)
        
        # Update debug timestamp if needed
        if now - self.last_debug_time > 1.0:
            self.last_debug_time = now
        
        return blink_detected_now
    
    def detect_blinks_haar(self, face_roi: np.ndarray,
                           frame: np.ndarray,
                           face_rect: Tuple[int,int,int,int]) -> bool:
        """Fallback blink detection with Haar. Extremely simplistic."""
        if face_roi.shape[0]<20 or face_roi.shape[1]<20:
            return False
        
        gray_face = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
        gray_face = cv2.equalizeHist(gray_face)
        
        eyes = self.eye_detector.detectMultiScale(gray_face, 1.1,3, minSize=(20,20))
        if len(eyes)<2:
            eyes = self.eye_detector.detectMultiScale(gray_face, 1.05,2, minSize=(15,15))
        
        x,y,w,h = face_rect
        blink_detected_now = False
        now = time.time()
        
        if len(eyes)==0:
            if (now - self.last_blink_time) > self.config.MIN_BLINK_INTERVAL:
                self.blink_counter += 1
                self.blink_detected = True
                blink_detected_now = True
                self.logger.debug(f"BLINK DETECTED! Counter: {self.blink_counter}")
                self.last_blink_time = now
        else:
            # draw eyes for debug
            if now - self.last_debug_time > 1.0:
                for (ex,ey,ew,eh) in eyes:
                    cv2.rectangle(frame, (x+ex,y+ey), (x+ex+ew, y+ey+eh), (0,255,0),1)
        
        # show blink count
        roi = frame[y : y+h, x : x+w]
        cv2.putText(roi, f"Blinks: {self.blink_counter}", (10,20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,255),1)
        
        if now - self.last_debug_time > 1.0:
            self.last_debug_time = now
        
        return blink_detected_now
    
    def detect_blinks(self,
                      frame: np.ndarray,
                      face_rect: Tuple[int,int,int,int],
                      face_roi: np.ndarray) -> bool:
        """
        Decide which method to use: dlib or Haar.
        We draw debug lines right on `frame`.
        """
        if self.using_dlib:
            return self.detect_blinks_dlib(frame, face_rect)
        else:
            return self.detect_blinks_haar(face_roi, frame, face_rect)
    
    def reset(self) -> None:
        self.blink_counter = 0
        self.blink_detected = False
        self.blink_frames = 0
        self.eye_state = "open"
        self.last_blink_time = time.time()
        self.ear_history.clear()
        self.last_debug_time = 0.0
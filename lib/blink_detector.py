# blink_detector.py
# Eye detection and blink analysis module

import cv2
import numpy as np
import time
import logging
import dlib
from typing import Tuple, Optional
from collections import deque

from lib.config import Config

# BlinkDetector class for eye detection and blink analysis using facial landmarks
class BlinkDetector:
    
    # Initialise BlinkDetector
    def __init__(self, config: Config):
        self.config = config # Store configuration object
        self.logger = logging.getLogger(__name__) # Create logger for this module
        
        # Load eye detectors (as fallback if no dlib)
        self.eye_detector = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml') # Load eye detector cascade (as fallback if no dlib)
        if self.eye_detector.empty():
            self.logger.warning("Failed to load eye detector cascade")
        
        # Load dlib face detector + shape predictor
        self.dlib_detector = dlib.get_frontal_face_detector() # Load dlib face detector (as fallback if no haar)
        try:
            self.dlib_predictor = dlib.shape_predictor("bin/shape_predictor_68_face_landmarks.dat") # Load dlib shape predictor
            self.using_dlib = True # Flag indicating successful dlib initialisation
            self.logger.info("Using dlib for facial landmark detection")
        except Exception as e:
            self.logger.warning(f"Could not load dlib shape predictor: {e}")
            self.logger.warning("Falling back to Haar cascade for eye detection")
            self.using_dlib = False # Flag indicating fallback to Haar cascade
        
        # Blink detection variables
        self.blink_threshold = config.BLINK_THRESHOLD
        self.min_blink_frames = config.MIN_BLINK_FRAMES
        self.blink_frames = 0
        self.blink_counter = 0
        self.blink_detected = False
        self.last_blink_time = time.time()
        
        # Track EAR
        self.ear_history = deque(maxlen=30) # Initialise queue to store eye aspect ratios for smoothing
        self.eye_state = "open"  # can be "open", "closing", "closed", "opening"
        self.eye_state_start = time.time() # Initialise eye state start time

        # Rate-limit debug logs to once per second
        self.last_debug_time = 0.0 # Initialise last debug time
    
    # Calculate Eye Aspect Ratio
    def calculate_ear(self, eye_points: np.ndarray) -> float:
        # Eye Aspect Ratio
        A = np.linalg.norm(eye_points[1] - eye_points[5]) # Calculate distance between eye points
        B = np.linalg.norm(eye_points[2] - eye_points[4]) # Calculate distance between eye points
        C = np.linalg.norm(eye_points[0] - eye_points[3]) # Calculate distance between eye points
        if C == 0:
            return 0 # If distance between eye points is 0, return 0
        return (A + B) / (2.0 * C) # Return Eye Aspect Ratio
    
    # Detect blinks using dlib EAR
    def detect_blinks_dlib(self, frame: np.ndarray,
                           face_rect: Tuple[int,int,int,int]) -> bool:
        if face_rect is None:
            return False # If face rectangle is None, return False
        
        x, y, w, h = face_rect # Get face rectangle coordinates
        rect = dlib.rectangle(x, y, x + w, y + h) # Create dlib rectangle
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) # Convert frame to grayscale
        landmarks = self.dlib_predictor(gray, rect) # Get facial landmarks
        
        left_eye = np.array([(landmarks.part(i).x, landmarks.part(i).y) for i in range(36, 42)]) # Get left eye landmarks
        right_eye = np.array([(landmarks.part(i).x, landmarks.part(i).y) for i in range(42, 48)]) # Get right eye landmarks
        
        left_ear = self.calculate_ear(left_eye) # Calculate left eye aspect ratio
        right_ear = self.calculate_ear(right_eye) # Calculate right eye aspect ratio
        avg_ear = (left_ear + right_ear) / 2.0 # Calculate average eye aspect ratio
        self.ear_history.append(avg_ear) # Append average eye aspect ratio to history
        
        # Draw eye contours for debugging, rate-limited to once per second
        now = time.time() # Get current time
        if now - self.last_debug_time > 1.0: # If time since last debug is greater than 1 second
            for eye in [left_eye, right_eye]: # Draw eye contours for left and right eyes
                for i in range(len(eye)): # Draw eye contours for each eye
                    pt1 = tuple(eye[i]) # Get first point
                    pt2 = tuple(eye[(i+1) % 6]) # Get second point
                    cv2.line(frame, pt1, pt2, (0,255,0), 1) # Draw line
        
        # Rate-limit debug logs to once per second
        if now - self.last_debug_time > 1.0:
            self.logger.debug(f"EAR: {avg_ear:.2f} (Threshold: {self.blink_threshold:.2f})")
        
        blink_detected_now = False # Initialise blink detected now
        
        if avg_ear < self.blink_threshold: # If average eye aspect ratio is less than blink threshold
            self.blink_frames += 1 # Increment blink frames
            if self.eye_state == "open": # If eye state is open
                self.eye_state = "closing" # Set eye state to closing
                self.eye_state_start = now # Set eye state start time
            elif (self.eye_state == "closing" # If eye state is closing
                  and (now - self.eye_state_start) > 0.1): # If time since eye state start is greater than 0.1 seconds
                self.eye_state = "closed" # Set eye state to closed
                self.eye_state_start = now # Set eye state start time
        else:
            if (self.eye_state == "closed" # If eye state is closed
                and self.blink_frames >= self.min_blink_frames # If blink frames are greater than minimum blink frames
                and (now - self.last_blink_time) > self.config.MIN_BLINK_INTERVAL): # If time since last blink is greater than minimum blink interval
                self.blink_counter += 1 # Increment blink counter
                self.blink_detected = True # Set blink detected to True
                blink_detected_now = True # Set blink detected now to True
                
                # Rate-limit "BLINK DETECTED" info to once per second
                if now - self.last_debug_time > 1.0:
                    self.logger.info(f"BLINK DETECTED! Counter: {self.blink_counter}")
                
                self.last_blink_time = now # Set last blink time to current time
            
            self.eye_state = "open" if self.eye_state != "closed" else "opening" # Set eye state to open if eye state is not closed, otherwise set to opening
            self.eye_state_start = now # Set eye state start time to current time
            self.blink_frames = 0 # Reset blink frames
        
        # Display EAR + blink count in face ROI
        face_roi = frame[y : y + h, x : x + w] # Get face ROI
        cv2.putText(face_roi, f"EAR: {avg_ear:.2f}", (10,40), # Display EAR in face ROI
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,255),1) # Display EAR in face ROI
        cv2.putText(face_roi, f"Blinks: {self.blink_counter}", (10,20), # Display blink counter in face ROI
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,255),1) # Display blink counter in face ROI
        
        # Update debug timestamp if needed
        if now - self.last_debug_time > 1.0: # If time since last debug is greater than 1 second
            self.last_debug_time = now # Set last debug time to current time
        
        return blink_detected_now
    
    def detect_blinks_haar(self, face_roi: np.ndarray,
                           frame: np.ndarray,
                           face_rect: Tuple[int,int,int,int]) -> bool:
        # Fallback blink detection with Haar. Extremely simplistic.
        if face_roi.shape[0]<20 or face_roi.shape[1]<20:
            return False # If face ROI is less than 20 pixels, return False
        
        gray_face = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY) # Convert face ROI to grayscale
        gray_face = cv2.equalizeHist(gray_face) # Equalise histogram of face ROI (This is a simple method to improve contrast)
        
        eyes = self.eye_detector.detectMultiScale(gray_face, 1.1,3, minSize=(20,20)) # Detect eyes in face ROI
        if len(eyes)<2: # If number of eyes detected is less than 2
            eyes = self.eye_detector.detectMultiScale(gray_face, 1.05,2, minSize=(15,15)) # Detect eyes in face ROI
        
        x,y,w,h = face_rect # Get face rectangle coordinates
        blink_detected_now = False # Initialise blink detected now
        now = time.time() # Get current time
        
        if len(eyes)==0: # If number of eyes detected is 0
            if (now - self.last_blink_time) > self.config.MIN_BLINK_INTERVAL: # If time since last blink is greater than minimum blink interval
                self.blink_counter += 1 # Increment blink counter
                self.blink_detected = True # Set blink detected to True
                blink_detected_now = True # Set blink detected now to True
                self.logger.debug(f"BLINK DETECTED! Counter: {self.blink_counter}") # Log blink detected
                self.last_blink_time = now # Set last blink time to current time
        else:
            # draw eyes for debug
            if now - self.last_debug_time > 1.0: # If time since last debug is greater than 1 second
                for (ex,ey,ew,eh) in eyes: # Draw eyes for debug
                    cv2.rectangle(frame, (x+ex,y+ey), (x+ex+ew, y+ey+eh), (0,255,0),1) # Draw rectangle
        
        # show blink count
        roi = frame[y : y+h, x : x+w] # Get face ROI
        cv2.putText(roi, f"Blinks: {self.blink_counter}", (10,20), # Display blink counter in face ROI
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,255),1) # Display blink counter in face ROI
        
        if now - self.last_debug_time > 1.0: # If time since last debug is greater than 1 second
            self.last_debug_time = now # Set last debug time to current time
        
        return blink_detected_now # Return blink detected now
    
    # Detect blinks (dlib or Haar)
    def detect_blinks(self,
                      frame: np.ndarray,
                      face_rect: Tuple[int,int,int,int],
                      face_roi: np.ndarray) -> bool:

        # Detect blinks using dlib or Haar
        if self.using_dlib:
            return self.detect_blinks_dlib(frame, face_rect)
        else:
            return self.detect_blinks_haar(face_roi, frame, face_rect)
    
    # Reset blink detection variables
    def reset(self) -> None:
        self.blink_counter = 0 # Reset blink counter
        self.blink_detected = False # Reset blink detected
        self.blink_frames = 0 # Reset blink frames
        self.eye_state = "open" # Reset eye state
        self.last_blink_time = time.time() # Reset last blink time
        self.ear_history.clear() # Clear eye history
        self.last_debug_time = 0.0 # Reset last debug time
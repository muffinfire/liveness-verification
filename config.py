"""Blink detection configuration for liveness detection system."""

import os
import logging

class Config:
    # Debug mode for browser
    BROWSER_DEBUG = True  # UPDATED: Set to True for testing

    # Show debug frame with eye tracking polygons, EAR values, etc.
    SHOW_DEBUG_FRAME = True  # UPDATED: Set to True for testing

    # Show partner video in QR code
    SHOW_PARTNER_VIDEO_IN_QR = True 

    # Logging modes (Debug, Info, Error)
    LOGGING_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    APP_LOGGING_LEVEL = logging.INFO
    SPEECH_RECOGNIZER_LOGGING_LEVEL = logging.INFO
    ACTION_DETECTOR_LOGGING_LEVEL = logging.INFO
    CHALLENGE_MANAGER_LOGGING_LEVEL = logging.INFO
    LIVENESS_DETECTOR_LOGGING_LEVEL = logging.INFO

    # Session timeout in seconds
    SESSION_TIMEOUT = 120
    CODE_EXPIRATION_TIME = 120
    
    # Camera settings
    CAMERA_WIDTH = 640
    CAMERA_HEIGHT = 480
    
    # Face detection parameters
    FACE_CONFIDENCE_THRESHOLD = 0.9
    FACE_NMS_THRESHOLD = 0.3
    
    # Head pose thresholds for landmark-based detection
    HEAD_POSE_THRESHOLD_HORIZONTAL = 0.4  # Symmetric deviation from 1.0 for left/right 3.5
    HEAD_POSE_THRESHOLD_UP = 15           # Pixels for "up"
    HEAD_POSE_THRESHOLD_DOWN = 30         # Pixels for "down" 35
    FACE_POSITION_HISTORY_LENGTH = 10      # Kept for responsiveness
        
    # History lengths for tracking
    LANDMARK_HISTORY_MAX = 5  # Maximum frames to keep in landmark history
    
    # Blink detection parameters - UPDATED: Adjusted for low frame rates
    BLINK_THRESHOLD = 0.32  # EAR threshold for blink detection (increased from 0.30)
    MIN_BLINK_FRAMES = 1    # Minimum consecutive frames below threshold to count as blink
    MIN_BLINK_INTERVAL = 0.2  # Minimum time between blinks (seconds) (increased from 0.1)
    
    # Challenge parameters
    CHALLENGE_TIMEOUT = 10  # seconds
    ACTION_SPEECH_WINDOW = 2  # Time allowed between action and speech (seconds)
    SPEECH_DEBOUNCE_TIME = 0.2  # Ignore repeat detections of same word within this time
    
    # Speech recognition parameters
    SPEECH_TIMEOUT = 10  # seconds
    SPEECH_PHRASE_LIMIT = 2  # seconds
    SPEECH_SAMPLING_RATE = 48000
    SPEECH_BUFFER_SIZE = 1024

    SPEECH_KEYWORDS = {
        "clock": 1e-3,
        "book": 1e-2,
        "jump": 1e-3,
        "fish": 1e-3,
        "mind": 1e-3,
        "verify": 1e-3,
        "stop": 1e-3,
        "noise": 1e-1,
    }
    ACTIONS= [
        "turn left", 
        "turn right", 
        "look up", 
        "look down", 
        "blink twice"
    ]
    
    # Liveness scoring
    MIN_CONSECUTIVE_LIVE_FRAMES = 5
    MIN_CONSECUTIVE_FAKE_FRAMES = 5

    # Available challenges
    CHALLENGES = [
        "Turn left and say clock", 
        "Turn right and say book", 
        "Look up and say jump", 
        "Look down and say fish", 
        "Blink twice and say mind"
    ]

    # [CHANGED] SSL and host/port in config
    CERTFILE = 'cert.pem'
    KEYFILE = 'key.pem'
    HOST = '0.0.0.0'
    PORT = int(os.environ.get('PORT', 8080))
    
    # Base URL for verification links
    BASE_URL = os.environ.get('BASE_URL', 'https://verify.adambaumgartner.com')

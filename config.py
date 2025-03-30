"""Configuration settings for the liveness detection system."""

import os

class Config:
    # Debug mode
    DEBUG = True
    
    # Show debug frame with eye tracking polygons, EAR values, etc.
    SHOW_DEBUG_FRAME = True

    # Session timeout in seconds
    SESSION_TIMEOUT = 120
    
    # Camera settings
    CAMERA_WIDTH = 640
    CAMERA_HEIGHT = 480
    
    # Face detection parameters
    FACE_CONFIDENCE_THRESHOLD = 0.9
    FACE_NMS_THRESHOLD = 0.3
    
    # Head pose thresholds for landmark-based detection
    HEAD_POSE_THRESHOLD_HORIZONTAL = 0.4  # Symmetric deviation from 1.0 for left/right 3.5
    HEAD_POSE_THRESHOLD_UP = 15           # Pixels for "up" (positive, negated in code) 10
    HEAD_POSE_THRESHOLD_DOWN = 40         # Pixels for "down" 35
    FACE_POSITION_HISTORY_LENGTH = 3      # Kept for responsiveness
        
    # History lengths for tracking
    LANDMARK_HISTORY_MAX = 30  # Maximum frames to keep in landmark history
    
    # Blink detection parameters
    BLINK_THRESHOLD = 0.25  # EAR threshold for blink detection
    MIN_BLINK_FRAMES = 1    # Minimum consecutive frames below threshold to count as blink
    MIN_BLINK_INTERVAL = 0.1  # Minimum time between blinks (seconds)
    
    # Challenge parameters
    CHALLENGE_TIMEOUT = 10  # seconds
    ACTION_SPEECH_WINDOW = 10.0  # seconds allowed between action and speech
    
    # Speech recognition parameters
    SPEECH_TIMEOUT = 10  # seconds
    SPEECH_PHRASE_LIMIT = 2  # seconds
    SPEECH_SAMPLING_RATE = 16000
    SPEECH_BUFFER_SIZE = 1024
    SPEECH_KEYWORDS = [
        "blue /1e-3/",
        "red /1e-3/",
        "sky /1e-3/",
        "ground /1e-3/",
        "hello /1e-3/",
        "verify /1e-3/",
        "noise /1e-1/",
    ]
    
    # Liveness scoring
    MIN_CONSECUTIVE_LIVE_FRAMES = 5
    MIN_CONSECUTIVE_FAKE_FRAMES = 5
    
    # Logging
    LOGGING_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Available challenges
    CHALLENGES = [
        "Turn left and say blue", 
        "Turn right and say red", 
        "Look up and say sky", 
        "Look down and say ground", 
        "Blink twice and say hello"
    ]

    # [CHANGED] SSL and host/port in config
    CERTFILE = 'cert.pem'
    KEYFILE = 'key.pem'
    HOST = '0.0.0.0'
    PORT = int(os.environ.get('PORT', 8080))
    BASE_URL = 'https://192.168.8.126:8080'  # Configurable base URL for QR code

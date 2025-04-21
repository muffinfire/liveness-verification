# Config.py
# Configuration settings for the liveness detection system

import os
import logging

class Config:
    # Debug options
    BROWSER_DEBUG = False # Whether to output debug information to browser console
    SHOW_DEBUG_FRAME = True # Whether to show debug frame within verification UI

    # Logging modes (Debug, Info, Error)
    LOGGING_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    APP_LOGGING_LEVEL = logging.INFO
    SPEECH_RECOGNIZER_LOGGING_LEVEL = logging.INFO
    ACTION_DETECTOR_LOGGING_LEVEL = logging.INFO
    CHALLENGE_MANAGER_LOGGING_LEVEL = logging.INFO
    LIVENESS_DETECTOR_LOGGING_LEVEL = logging.INFO

    # Session timeout in seconds
    SESSION_TIMEOUT = 120                   # Time allowed for a session to be completed (seconds)
    CODE_EXPIRATION_TIME = 600              # Time allowed for a code to be used (seconds)
    
    # Camera settings
    CAMERA_WIDTH = 640                      # Width of camera frames
    CAMERA_HEIGHT = 480                     # Height of camera frames
    
    # Head pose thresholds for landmark-based detection (closer to 0 is more sensitive)
    HEAD_POSE_THRESHOLD_HORIZONTAL = 0.4    # Symmetric deviation from 1.0 for left/right
    HEAD_POSE_THRESHOLD_UP = 4              # Pixels for "up" (negated in code)
    HEAD_POSE_THRESHOLD_DOWN = 20           # Pixels for "down" 
    FACE_POSITION_HISTORY_LENGTH = 5        # Number of frames to consider for head pose detection
    
    # Blink detection parameters
    BLINK_THRESHOLD = 0.29                  # EAR threshold for blink detection
    MIN_BLINK_FRAMES = 1                    # Minimum consecutive frames below threshold to count as blink
    MIN_BLINK_INTERVAL = 0.05               # Minimum time between blinks (seconds)
    
    # Challenge parameters
    CHALLENGE_TIMEOUT = 30                  # Time allowed for a challenge to be completed (seconds)
    ACTION_SPEECH_WINDOW = 3                # Time allowed between action and speech (seconds)
    SPEECH_DEBOUNCE_TIME = 0.1              # Ignore repeat detections of same word within this time (seconds)
    BLINK_COUNTER_THRESHOLD = 3             # Minimum number of blinks to count as a challenge completion
    
    # Speech recognition parameters
    SPEECH_TIMEOUT = 10                     # Time allowed for speech to be recognised (seconds)
    SPEECH_PHRASE_LIMIT = 2                 # Maximum number of words in a phrase (Used to limit false positives)
    SPEECH_SAMPLING_RATE = 48000            # Sampling rate for speech recognition
    # SPEECH_BUFFER_SIZE = 1024             # Buffer setting moved to app.js

    # Speech keywords and their corresponding weights (Eg: "sand" has a higher weight than "noise" meaning it's more likely to be a valid keyword)
    SPEECH_KEYWORDS = {
        "sand": 1e-3,
        "book": 1e-3,
        "jump": 1e-3,
        "fish": 1e-3,
        "mind": 1e-3,
        "verify": 1e-3,
        "noise": 1e-1,
    }

    # Available actions (Eg: "turn left", "turn right", "look up", "look down")
    ACTIONS= [
        "turn left", 
        "turn right", 
        "look up", 
        "look down"
    ]

    # SSL and host/port in config
    HOST = '0.0.0.0'
    PORT = int(os.environ.get('PORT', 8080))
    BASE_URL = 'https://verify.adambaumgartner.com'  # Configurable base URL for QR code
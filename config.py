"""Configuration settings for the liveness detection system."""

class Config:
    # Debug mode
    DEBUG = False
    
    # Face detection parameters
    FACE_CONFIDENCE_THRESHOLD = 0.9
    FACE_NMS_THRESHOLD = 0.3
    
    # Head pose thresholds (normalized)
    HEAD_POSE_THRESHOLD_X = 0.06  # 8% of half frame width
    HEAD_POSE_THRESHOLD_Y_UP = 0.08  # 8% for looking up
    HEAD_POSE_THRESHOLD_Y_DOWN = 0.10  # 10% for looking down
    
    # Blink detection parameters
    BLINK_THRESHOLD = 0.25  # EAR threshold for blink detection
    MIN_BLINK_FRAMES = 1  # Minimum consecutive frames below threshold to count as blink
    MIN_BLINK_INTERVAL = 0.1  # Minimum time between blinks (seconds)
    
    # Challenge parameters
    CHALLENGE_TIMEOUT = 10  # seconds (increased from 10)
    ACTION_SPEECH_WINDOW = 5.0  # seconds allowed between action and speech (increased from 3.0)
    
    # Speech recognition parameters
    SPEECH_TIMEOUT = 5  # seconds (reduced from 5)
    SPEECH_PHRASE_LIMIT = 2  # seconds (reduced from 3)
    
    # Liveness scoring
    MIN_CONSECUTIVE_LIVE_FRAMES = 5
    MIN_CONSECUTIVE_FAKE_FRAMES = 5
    
    # Available challenges
    CHALLENGES = [
        "Turn left and say blue", 
        "Turn right and say red", 
        "Look up and say sky", 
        "Look down and say ground", 
        "Blink twice and say hello"
    ]
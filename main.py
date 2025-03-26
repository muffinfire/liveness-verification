"""Main application for liveness detection (CLI version)."""

import cv2
import time
import argparse
import logging
from typing import Optional

from config import Config
from liveness_detector import LivenessDetector

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Liveness Detection System")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--camera", type=int, default=0, help="Camera index")
    return parser.parse_args()

def main():
    args = parse_args()
    
    config = Config()
    config.DEBUG = args.debug
    
    logging_level = logging.DEBUG if config.DEBUG else logging.INFO
    logging.basicConfig(
        level=logging_level,
        format=config.LOGGING_FORMAT
    )
    logger = logging.getLogger(__name__)
    
    logger.info(f"Opening camera {args.camera}")
    cap = cv2.VideoCapture(args.camera)
    
    if not cap.isOpened():
        logger.error("Error: Could not open camera")
        return
    
    # Set camera properties
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
    
    detector = LivenessDetector(config)
    
    while True:
        ret, frame = cap.read()
        if not ret:
            logger.error("Error: Could not read frame")
            break
        
        display_frame, exit_flag = detector.detect_liveness(frame)
        
        cv2.imshow("Liveness Detection", display_frame)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or exit_flag:
            break
        elif key == ord('r'):
            detector.reset()
    
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()


import cv2
import os
import time

def save_frame(frame, out_dir, prefix="frame", tag=None, logger=None, frame_count=None):
    os.makedirs(out_dir, exist_ok=True)
    timestamp = int(time.time() * 1000)
    filename = f"{prefix}_{tag or timestamp}_{frame_count}.jpg"
    path = os.path.join(out_dir, filename)
    success = cv2.imwrite(path, frame)

    if logger and success:
        logger.info(f"{prefix}: Saved frame {frame_count}...")
    elif logger and not success:
        logger.warning(f"{prefix}: Failed to save frame to {path}")

    return path if success else None
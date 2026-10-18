import numpy as np
import cv2 as cv
from typing import Optional, Tuple

def extractFeatures(
    prev_grayscale_frame: Optional[np.ndarray],
    curr_grayscale_frame: np.ndarray,
    currFrame: np.ndarray,
    codec: str = "jpg",
) -> Tuple[float, int, Optional[np.ndarray]]:
    """Extract (mean_frame_diff, encoded_size, encoded_bytes) from video frame.

    Supports alternate codecs: 'jpg'/'jpeg' (default), 'png', and 'raw'.
    """
    if prev_grayscale_frame is None:
        mean_frame_diff = 0.00
    else:
        # Calculating mean absolute difference between the two greyscale frames
        frame_diff = cv.absdiff(prev_grayscale_frame, curr_grayscale_frame)
        mean_frame_diff = float(frame_diff.mean())

    num_encoded_bytes = 0
    encoded_frame_bytes = None

    codec_lower = codec.lower().strip(".")
    if codec_lower in ("jpg", "jpeg"):
        encode_success, encoded_frame_bytes = cv.imencode('.jpg', currFrame)
        if encode_success:
            num_encoded_bytes = len(encoded_frame_bytes)
    elif codec_lower == "png":
        encode_success, encoded_frame_bytes = cv.imencode('.png', currFrame)
        if encode_success:
            num_encoded_bytes = len(encoded_frame_bytes)
    elif codec_lower == "raw":
        raw_bytes = currFrame.tobytes()
        encoded_frame_bytes = np.frombuffer(raw_bytes, dtype=np.uint8)
        num_encoded_bytes = len(encoded_frame_bytes)
    else:
        # Fallback to JPEG
        encode_success, encoded_frame_bytes = cv.imencode('.jpg', currFrame)
        if encode_success:
            num_encoded_bytes = len(encoded_frame_bytes)

    return (mean_frame_diff, num_encoded_bytes, encoded_frame_bytes)
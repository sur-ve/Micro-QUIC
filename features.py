import numpy as np
import cv2 as cv

def extractFeatures(prev_grayscale_frame, curr_grayscale_frame, currFrame) -> tuple[float, int, np.ndarray[int]]:
    if prev_grayscale_frame is None:
        mean_frame_diff = 0.00
    else:
        # calculating mean absolute difference between the two greyscale frames
        frame_diff = cv.absdiff(prev_grayscale_frame, curr_grayscale_frame)
        mean_frame_diff = frame_diff.mean()

    num_encoded_bytes = 0 # setting the number of encoded bytes before hand to prevent later problems
    encoded_frame_bytes = None
    # converting the current frame to encodings
    encode_success, encoded_frame_bytes = cv.imencode('.jpg', currFrame)
    # if encoding successful then record the number of bytes in the encoding, this depends on redundancy
    if encode_success:
        num_encoded_bytes = len(encoded_frame_bytes)
    else:
        pass
    return (float(mean_frame_diff), num_encoded_bytes, encoded_frame_bytes)
# Wrapper over the trained pipeline that classifies packets as critical / non-critical.

import joblib
import numpy as np

# Load the MakeFile using joblib
_PIPELINE_PATH = "criticality_model.pkl"
_pipeline = joblib.load(_PIPELINE_PATH)


def predict_criticality(features: tuple[float, int]) -> bool:
    """Takes the 2-feature vector (frame_diff, encoded_size) and returns criticality."""
    diff, size = features
    if size == 0:
        # Encode failure / empty payload — treat as critical.
        return True

    arr = np.array([[diff, size]], dtype=float)  # shaping the array to (1, 2)
    prediction = _pipeline.predict(arr) # predict the criticality of packet
    return bool(prediction[0])

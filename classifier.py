# Wrapper over the trained pipeline that classifies packets as critical / non-critical.

import os
import joblib
import numpy as np

MODEL_PATH = "criticality_model.pkl"

# Lazy-loaded pipeline — None until first call to predict_criticality() or load_pipeline().
# This allows the module to be imported safely before the model has been trained.
_pipeline = None


class ModelNotTrainedError(RuntimeError):
    """Raised when predict_criticality() is called but no trained model exists."""


def load_pipeline(path: str = MODEL_PATH) -> None:
    """Load (or reload) the trained sklearn pipeline from *path*.

    Call this explicitly after running train_classifier.py if you need
    the updated model to take effect in the same process.
    """
    global _pipeline, MODEL_PATH
    MODEL_PATH = path
    _pipeline = joblib.load(path)


def _ensure_pipeline() -> None:
    """Load the pipeline on first use (lazy initialisation)."""
    global _pipeline
    if _pipeline is None:
        if not os.path.exists(MODEL_PATH):
            raise ModelNotTrainedError(
                f"Trained model not found at '{MODEL_PATH}'. "
                "Run train_classifier.py first to generate the model."
            )
        _pipeline = joblib.load(MODEL_PATH)


def predict_criticality(features: tuple[float, int]) -> bool:
    """Takes the 2-feature vector (frame_diff, encoded_size) and returns criticality.

    Returns True if the frame is classified as critical (requires reliable delivery),
    False otherwise. Raises ModelNotTrainedError if the model .pkl does not exist.
    """
    diff, size = features
    if size == 0:
        # Encode failure / empty payload — treat as critical.
        return True

    _ensure_pipeline()
    arr = np.array([[diff, size]], dtype=float)  # shaping the array to (1, 2)
    prediction = _pipeline.predict(arr)  # predict the criticality of packet
    return bool(prediction[0])

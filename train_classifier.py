"""Train the ML criticality classifier and save the pipeline to disk.

Supports:
- Multi-video diverse training (directory or list of video files)
- Unsupervised KMeans clustering or Supervised labeled training path
- Exporting feature importances and evaluation metrics (accuracy, confusion matrix, balance)

Usage:
    python train_classifier.py [--video PATH] [--video-dir DIR] [--model OUT.pkl]
                               [--label-method {kmeans,motion-threshold,supervised}]
                               [--labels LABELS.csv] [--metrics-out METRICS.json]
"""
import argparse
import glob
import json
import os
from typing import List, Tuple, Dict, Any, Optional

import cv2 as cv
import joblib
import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from features import extractFeatures


def extract_features_from_video(
    video_path: str,
    max_frames: int = 0,
) -> List[Tuple[float, int]]:
    """Extract (mean_diff, encoded_size) pairs from a video file."""
    cap = cv.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[TRAIN] Warning: Could not open {video_path}, skipping.")
        return []

    features = []
    prev_gray = None
    frame_count = 0

    while True:
        if max_frames and frame_count >= max_frames:
            break
        ret, frame = cap.read()
        if not ret:
            break

        curr_gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        diff, size, _ = extractFeatures(prev_gray, curr_gray, frame)
        features.append((diff, size))
        prev_gray = curr_gray
        frame_count += 1

    cap.release()
    print(f"[TRAIN] Extracted {len(features)} frames from: {video_path}")
    return features


def load_supervised_labels(labels_file: str, total_frames: int) -> np.ndarray:
    """Load binary labels from CSV (one label per line or frame_idx,is_critical)."""
    labels = []
    with open(labels_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.lower().startswith("frame"):
                continue
            parts = line.split(",")
            val = parts[-1].strip().lower()
            labels.append(val in ("1", "true", "critical", "crit"))

    if len(labels) < total_frames:
        print(f"[TRAIN] Warning: Labels file has {len(labels)} entries, padding with False up to {total_frames}.")
        labels.extend([False] * (total_frames - len(labels)))
    elif len(labels) > total_frames:
        labels = labels[:total_frames]

    return np.array(labels, dtype=bool)


def train(
    video_paths: List[str],
    model_out: str,
    label_method: str = "kmeans",
    labels_file: str = "",
    motion_threshold: float = 12.0,
    max_frames_per_video: int = 0,
    metrics_out: str = "",
) -> Dict[str, Any]:
    """Train the criticality decision tree classifier across multiple videos."""
    all_features: List[Tuple[float, int]] = []

    for v_path in video_paths:
        feats = extract_features_from_video(v_path, max_frames=max_frames_per_video)
        all_features.extend(feats)

    if not all_features:
        raise SystemExit("[TRAIN] Error: No frames were extracted across all videos.")

    X = np.array(all_features, dtype=float)
    total_samples = len(X)

    # 1. Generate / obtain ground-truth target labels y
    if label_method == "supervised" and labels_file:
        print(f"[TRAIN] Using supervised labels from '{labels_file}'...")
        y = load_supervised_labels(labels_file, total_samples)
    elif label_method == "motion-threshold":
        print(f"[TRAIN] Using motion-threshold labeling (diff >= {motion_threshold})...")
        y = X[:, 0] >= motion_threshold
    else:  # kmeans pseudo-labels
        print("[TRAIN] Using unsupervised KMeans clustering (k=2)...")
        scaler_temp = StandardScaler()
        scaled_X = scaler_temp.fit_transform(X)
        kmeans = KMeans(n_clusters=2, random_state=42)
        raw_cluster = kmeans.fit_predict(scaled_X)
        # Cluster with higher mean frame diff is designated critical
        centers = kmeans.cluster_centers_
        crit_cluster = 0 if centers[0][0] > centers[1][0] else 1
        y = (raw_cluster == crit_cluster)

    crit_count = int(y.sum())
    norm_count = int((~y).sum())
    crit_ratio = (crit_count / total_samples) * 100

    print(f"[TRAIN] Dataset balance: {crit_count} critical ({crit_ratio:.1f}%), {norm_count} normal ({100 - crit_ratio:.1f}%)")

    # 2. Train / test split for metrics
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y if 0 < crit_count < total_samples else None
    )

    # 3. Fit pipeline: StandardScaler + DecisionTreeClassifier
    dt_classifier = DecisionTreeClassifier(max_depth=3, random_state=42)
    pipeline = Pipeline([
        ('scaler', StandardScaler()),
        ('classifier', dt_classifier),
    ])
    pipeline.fit(X_train, y_train)

    # 4. Compute metrics
    y_pred = pipeline.predict(X_test)
    acc = float(accuracy_score(y_test, y_pred))
    prec = float(precision_score(y_test, y_pred, zero_division=0))
    rec = float(recall_score(y_test, y_pred, zero_division=0))
    f1 = float(f1_score(y_test, y_pred, zero_division=0))
    cm = confusion_matrix(y_test, y_pred).tolist()

    feature_importances = {
        "mean_frame_diff": float(dt_classifier.feature_importances_[0]),
        "encoded_size_bytes": float(dt_classifier.feature_importances_[1]),
    }

    # 5. Fit on full dataset before saving
    pipeline.fit(X, y)
    joblib.dump(pipeline, model_out)
    print(f"[TRAIN] Trained pipeline saved to: '{model_out}'")

    # Reload classifier module
    try:
        import classifier
        classifier.load_pipeline(model_out)
        print("[TRAIN] Reloaded classifier in current process.")
    except Exception as exc:
        print(f"[TRAIN] Note: could not reload classifier: {exc}")

    metrics = {
        "total_frames": total_samples,
        "critical_frames": crit_count,
        "normal_frames": norm_count,
        "critical_percentage": crit_ratio,
        "label_method": label_method,
        "validation_metrics": {
            "accuracy": acc,
            "precision": prec,
            "recall": rec,
            "f1_score": f1,
            "confusion_matrix": cm,
        },
        "feature_importances": feature_importances,
        "model_file": model_out,
    }

    print("\n" + "=" * 60)
    print("           CRITICALITY CLASSIFIER METRICS REPORT")
    print("=" * 60)
    print(f"Total Frames:           {total_samples}")
    print(f"Critical Ratio:         {crit_count}/{total_samples} ({crit_ratio:.1f}%)")
    print(f"Accuracy:               {acc * 100:.2f}%")
    print(f"Precision / Recall:     {prec * 100:.2f}% / {rec * 100:.2f}%")
    print(f"F1 Score:               {f1:.4f}")
    print(f"Feature Importances:    diff={feature_importances['mean_frame_diff']:.3f}, size={feature_importances['encoded_size_bytes']:.3f}")
    print(f"Confusion Matrix [TN, FP; FN, TP]: {cm}")
    print("=" * 60 + "\n")

    if metrics_out:
        with open(metrics_out, "w") as f:
            json.dump(metrics, f, indent=2)
        print(f"[TRAIN] Saved metrics to: {metrics_out}")

    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train Micro-QUIC criticality classifier")
    parser.add_argument("--video", default="data/testVideo.mp4", help="Path to single training video")
    parser.add_argument("--video-dir", default="", help="Directory with multiple video files to train on")
    parser.add_argument("--videos", nargs="*", default=[], help="List of video file paths")
    parser.add_argument("--model", default="criticality_model.pkl", help="Output model path")
    parser.add_argument(
        "--label-method",
        choices=["kmeans", "motion-threshold", "supervised"],
        default="kmeans",
        help="Labeling strategy",
    )
    parser.add_argument("--labels", default="", help="CSV file for supervised labels")
    parser.add_argument("--motion-threshold", type=float, default=12.0, help="Diff threshold for motion-threshold labeling")
    parser.add_argument("--max-frames-per-video", type=int, default=0, help="Max frames per video (0 = all)")
    parser.add_argument("--metrics-out", default="", help="Save evaluation metrics to JSON file")
    args = parser.parse_args()

    # Collect video files
    video_list: List[str] = []
    if args.video_dir and os.path.isdir(args.video_dir):
        for ext in ("*.mp4", "*.avi", "*.mkv", "*.mov"):
            video_list.extend(glob.glob(os.path.join(args.video_dir, ext)))
            video_list.extend(glob.glob(os.path.join(args.video_dir, "**", ext), recursive=True))
        video_list = sorted(list(set(video_list)))
    elif args.videos:
        video_list = args.videos
    else:
        video_list = [args.video]

    print(f"[TRAIN] Training on {len(video_list)} video(s): {video_list}")
    train(
        video_paths=video_list,
        model_out=args.model,
        label_method=args.label_method,
        labels_file=args.labels,
        motion_threshold=args.motion_threshold,
        max_frames_per_video=args.max_frames_per_video,
        metrics_out=args.metrics_out,
    )
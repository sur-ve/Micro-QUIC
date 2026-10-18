"""Capture frames -> extract features -> ML criticality (via MicroQUICSocket) -> send.

Supports:
- File or live webcam/camera capture (--camera 0)
- Real-time frame pacing to source FPS (--fps 30)
- Priority drop under load (--priority-drop)
- Rate limiting / congestion pacing (--rate-limit)
- Authenticated PSK encryption (--psk)
- Multi-stream channel multiplexing (--stream-id)
- Alternate codecs (--codec jpg|png|raw)
"""
import argparse
import time
from typing import Tuple, Optional

import cv2 as cv

from channel import LossyChannel
from features import extractFeatures
from micro_quic import MicroQUICSocket


def run_video_sender(
    video_source: str | int,
    dest: Tuple[str, int],
    loss_rate: float = 0.0,
    max_frames: int = 0,
    fps: float = 30.0,
    priority_drop: bool = False,
    rate_limit_kbps: Optional[float] = None,
    psk: Optional[str] = None,
    stream_id: int = 0,
    codec: str = "jpg",
    keyframe_interval: int = 0,
):
    """Run ML-driven Micro-QUIC video sender."""
    channel = None
    if loss_rate > 0:
        proxy_port = dest[1] + 100
        print(f"[CHANNEL] Lossy proxy :{proxy_port} -> :{dest[1]} (loss={int(loss_rate * 100)}%)")
        channel = LossyChannel(listen_port=proxy_port, target_port=dest[1], loss_rate=loss_rate)
        channel.start()
        dest = (dest[0], proxy_port)

    # Initialize MicroQUICSocket with Selective Repeat sliding window, rate limiting, and PSK
    sock = MicroQUICSocket(
        timeout=0.1,
        max_retries=5,
        use_classifier=True,
        window_size=16,
        rate_limit_kbps=rate_limit_kbps,
        psk=psk,
    )

    # Open video source (file path or camera index)
    if isinstance(video_source, int) or (isinstance(video_source, str) and video_source.isdigit()):
        cam_idx = int(video_source)
        cap = cv.VideoCapture(cam_idx)
        src_label = f"Camera #{cam_idx}"
    else:
        cap = cv.VideoCapture(video_source)
        src_label = str(video_source)

    if not cap.isOpened():
        raise SystemExit(f"Could not open video source: {video_source}")

    # Determine frame rate pacing
    source_fps = cap.get(cv.CAP_PROP_FPS)
    target_fps = fps if fps > 0 else (source_fps if source_fps > 0 else 30.0)
    frame_interval = (1.0 / target_fps) if target_fps > 0 else 0.0

    prev_gray = None
    frame_id = 0
    sent_crit = 0
    sent_norm = 0
    dropped_load = 0

    last_send_duration = 0.0

    print(
        f"[SENDER] Streaming {src_label} -> {dest[0]}:{dest[1]} "
        f"[stream={stream_id}, codec={codec}, pacing={target_fps:.1f}fps, psk={'yes' if psk else 'no'}]"
    )

    while True:
        if max_frames and frame_id >= max_frames:
            break

        frame_start_time = time.time()

        ret, frame = cap.read()
        if not ret:
            break

        gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        diff, size, encoded = extractFeatures(prev_gray, gray, frame, codec=codec)
        prev_gray = gray

        if encoded is None or size == 0:
            print(f"[SENDER] frame={frame_id} encode failed, skipping")
            frame_id += 1
            continue

        payload = encoded.tobytes()

        # Check criticality via keyframe interval or ML classifier
        is_crit = False
        if keyframe_interval > 0 and (frame_id % keyframe_interval == 0):
            is_crit = True
        elif sock._classifier_fn is not None:
            try:
                is_crit = sock._classifier_fn((diff, size))
            except Exception:
                is_crit = False

        # Priority drop under load: if previous critical send experienced backlog/timeout,
        # drop non-critical frames to keep stream real-time
        if priority_drop and not is_crit and frame_interval > 0:
            if last_send_duration > 1.5 * frame_interval:
                dropped_load += 1
                print(f"[SENDER] frame={frame_id} (normal) DROPPED under load backlog")
                frame_id += 1
                continue

        send_start = time.time()
        ok = sock.send_frame(
            payload,
            dest,
            features=(diff, size),
            is_critical=is_crit,
            stream_id=stream_id,
        )
        last_send_duration = time.time() - send_start

        if is_crit:
            sent_crit += 1
            status = "ACK OK" if ok else "FAILED"
        else:
            sent_norm += 1
            status = "sent"

        print(
            f"[SENDER] frame={frame_id:<4} diff={diff:<5.2f} size={size:<6} "
            f"{'CRITICAL' if is_crit else 'normal':8} {status:<6} send_t={last_send_duration * 1000:4.1f}ms"
        )
        frame_id += 1

        # Frame pacing to target FPS
        if frame_interval > 0:
            elapsed = time.time() - frame_start_time
            sleep_time = max(0.0, frame_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    # Cleanup
    cap.release()
    sock.close()
    if channel:
        time.sleep(0.5)
        channel.stop()

    print(
        f"[SENDER] Done. frames={frame_id} critical={sent_crit} normal={sent_norm} "
        f"dropped_load={dropped_load}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ML-driven Micro-QUIC video sender")
    parser.add_argument("--video", default="data/testVideo.mp4", help="Video file path")
    parser.add_argument("--camera", "--webcam", dest="camera", type=int, default=None, help="Camera device index (e.g. 0)")
    parser.add_argument("--host", default="127.0.0.1", help="Target host")
    parser.add_argument("--port", type=int, default=50007, help="Target port")
    parser.add_argument("--loss-rate", type=float, default=0.0, help="Simulated loss rate (0.0 - 1.0)")
    parser.add_argument("--max-frames", type=int, default=0, help="Max frames (0 = all)")
    parser.add_argument("--fps", type=float, default=30.0, help="Frame pacing FPS (0 = unpaced)")
    parser.add_argument("--priority-drop", action="store_true", help="Drop non-critical frames under network load")
    parser.add_argument("--rate-limit", type=float, default=0.0, help="Transmission rate limit in kbps (0 = unlimited)")
    parser.add_argument("--psk", default="", help="Pre-shared key for encryption")
    parser.add_argument("--stream-id", type=int, default=0, help="Stream ID (0 - 7)")
    parser.add_argument("--codec", default="jpg", choices=["jpg", "jpeg", "png", "raw"], help="Video frame codec")
    parser.add_argument("--keyframe-interval", type=int, default=0, help="Force critical delivery every N frames (0 = classifier only)")
    args = parser.parse_args()

    source = args.camera if args.camera is not None else args.video
    rate_lim = args.rate_limit if args.rate_limit > 0 else None
    psk_key = args.psk if args.psk else None

    run_video_sender(
        video_source=source,
        dest=(args.host, args.port),
        loss_rate=args.loss_rate,
        max_frames=args.max_frames,
        fps=args.fps,
        priority_drop=args.priority_drop,
        rate_limit_kbps=rate_lim,
        psk=psk_key,
        stream_id=args.stream_id,
        codec=args.codec,
        keyframe_interval=args.keyframe_interval,
    )

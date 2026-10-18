"""Receive Micro-QUIC JPEG/PNG/RAW frames (reassembled), ACK critical fragments automatically.

Supports:
- Optional OpenCV GUI display or headless operation (--no-display)
- Saving stream to video file (--save OUT.avi)
- Saving individual frames to directory (--save-frames DIR)
- Multi-stream filtering (--stream-id)
- Authenticated PSK decryption (--psk)
- Live reception statistics
"""
import argparse
import os
import time
from typing import Optional

import cv2 as cv
import numpy as np

from micro_quic import MicroQUICSocket


def run_video_receiver(
    port: int,
    host: str = "127.0.0.1",
    display: bool = True,
    max_frames: int = 0,
    save_path: str = "",
    save_frames_dir: str = "",
    psk: Optional[str] = None,
    stream_id: Optional[int] = None,
    timeout: Optional[float] = None,
):
    """Receive, decode and optionally display/save a Micro-QUIC video stream."""
    sock = MicroQUICSocket(psk=psk)
    sock.bind((host, port))
    if timeout:
        sock.settimeout(timeout)
    else:
        sock.settimeout(None)
    print(f"[RECV] Listening on {host}:{port} [stream={stream_id if stream_id is not None else 'any'}, psk={'yes' if psk else 'no'}]")

    received = 0
    critical = 0
    total_bytes = 0

    video_writer: Optional[cv.VideoWriter] = None
    frames_written = 0
    first_frame_time = 0.0

    if save_frames_dir:
        os.makedirs(save_frames_dir, exist_ok=True)
        print(f"[RECV] Saving individual frames to: {save_frames_dir}/")

    try:
        while True:
            if max_frames and received >= max_frames:
                break

            result = sock.recv_packet(include_stream_id=True)
            if not result or result[0] is None:
                if timeout is not None and received > 0:
                    print(f"[RECV] Stream idle for {timeout}s after receiving frames. Exiting.")
                    break
                continue

            payload, addr, is_crit, pkt_stream_id = result

            # Stream filtering
            if stream_id is not None and pkt_stream_id != stream_id:
                continue

            total_bytes += len(payload)

            # Try decoding as image (JPEG / PNG)
            arr = np.frombuffer(payload, dtype=np.uint8)
            frame = cv.imdecode(arr, cv.IMREAD_COLOR)

            if frame is None:
                print(f"[RECV] Frame decode failed from {addr} len={len(payload)}")
                continue

            received += 1
            if is_crit:
                critical += 1

            if received == 1:
                first_frame_time = time.time()
                h, w = frame.shape[:2]
                if save_path:
                    fourcc = cv.VideoWriter_fourcc(*"MJPG")
                    video_writer = cv.VideoWriter(save_path, fourcc, 30.0, (w, h))
                    print(f"[RECV] Saving video to: {save_path} ({w}x{h})")

            tag = "CRITICAL" if is_crit else "normal"
            print(
                f"[RECV] #{received:<4} {frame.shape} {tag:8} "
                f"stream={pkt_stream_id} bytes={len(payload):<6} from {addr}"
            )

            if video_writer is not None:
                video_writer.write(frame)
                frames_written += 1

            if save_frames_dir:
                frame_path = os.path.join(save_frames_dir, f"frame_{received:06d}.jpg")
                cv.imwrite(frame_path, frame)
                frames_written += 1

            if display:
                cv.imshow("microQUIC", frame)
                if cv.waitKey(1) & 0xFF == ord("q"):
                    break

    except KeyboardInterrupt:
        print("\n[RECV] Interrupted by user.")

    elapsed = (time.time() - first_frame_time) if first_frame_time else 0.0
    goodput_kbps = (total_bytes * 8 / (elapsed * 1000)) if elapsed > 0 else 0.0

    # Cleanup
    if video_writer is not None:
        video_writer.release()
        print(f"[RECV] Saved {frames_written} frames to {save_path}")
    sock.close()
    if display:
        cv.destroyAllWindows()

    print(
        f"[RECV] Done. frames={received} critical={critical} "
        f"bytes={total_bytes} elapsed={elapsed:.1f}s goodput={goodput_kbps:.1f} kbps"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Micro-QUIC video receiver")
    parser.add_argument("--host", default="127.0.0.1", help="Bind IP address (e.g. 127.0.0.1 or 0.0.0.0)")
    parser.add_argument("--port", type=int, default=50007, help="Bind UDP port")
    parser.add_argument("--no-display", action="store_true", help="Disable OpenCV window (headless mode)")
    parser.add_argument("--max-frames", type=int, default=0, help="0 = run until Ctrl-C")
    parser.add_argument("--save", default="", metavar="OUT.avi", help="Save received stream as MJPEG .avi file")
    parser.add_argument("--save-frames", default="", metavar="DIR", help="Save individual JPEG frames to directory")
    parser.add_argument("--psk", default="", help="Pre-shared key for encryption")
    parser.add_argument("--stream-id", type=int, default=None, help="Filter specific stream ID")
    args = parser.parse_args()

    psk_key = args.psk if args.psk else None

    run_video_receiver(
        port=args.port,
        host=args.host,
        display=not args.no_display,
        max_frames=args.max_frames,
        save_path=args.save,
        save_frames_dir=args.save_frames,
        psk=psk_key,
        stream_id=args.stream_id,
    )

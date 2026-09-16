"""
Capture frames -> extract features -> ML criticality -> Micro-QUIC send (with fragmentation).
"""
import argparse
import time

import cv2 as cv

from channel import LossyChannel
from classifier import predict_criticality
from features import extractFeatures
from micro_quic import MicroQUICSocket


def run_video_sender(video_path: str, dest: tuple[str, int], loss_rate: float = 0.0, max_frames: int = 0):
    channel = None
    if loss_rate > 0: # if there is any loss
        proxy_port = dest[1] + 100 # proxy port for lossy channel 
        print(f"[CHANNEL] Lossy proxy :{proxy_port} -> :{dest[1]} (loss={int(loss_rate * 100)}%)")
        channel = LossyChannel(listen_port=proxy_port, target_port=dest[1], loss_rate=loss_rate)
        channel.start()
        dest = (dest[0], proxy_port)

    sock = MicroQUICSocket(timeout=0.1, max_retries=5) # timeout per packet is 0.1 sec and it tries 5 retransmissions per packet
    cap = cv.VideoCapture(video_path) # read video data using openCV
    if not cap.isOpened():
        raise SystemExit(f"Could not open video: {video_path}")

    prev_gray = None
    frame_id = 0 # keep track of number of frames
    sent_crit = 0 # keep track of numberr of critical and non-critical packets sent
    sent_norm = 0

    print(f"[SENDER] Streaming {video_path} -> {dest[0]}:{dest[1]}")

    while True:
        if max_frames and frame_id >= max_frames: # if max number of frames has been reached then exit else keep going
            break

        ret, frame = cap.read()
        if not ret:
            break

        gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        diff, size, encoded = extractFeatures(prev_gray, gray, frame)
        prev_gray = gray

        if encoded is None: # encoding failure
            print(f"[SENDER] frame={frame_id} encode failed, skipping")
            frame_id += 1
            continue

        is_crit = predict_criticality((diff, size)) # criticality of packet: True if critical, False if not
        payload = encoded.tobytes()
        ok = sock.send_packet(payload, dest, is_critical=is_crit) # sending packet with flag value depending on is_crit

        # recording whether packet was critical or not
        if is_crit:
            sent_crit += 1
            status = "ACK OK" if ok else "FAILED"
        else:
            sent_norm += 1
            status = "sent"

        print(
            f"[SENDER] frame={frame_id} diff={diff:.2f} size={size} "
            f"{'CRITICAL' if is_crit else 'normal':8} {status}"
        )
        frame_id += 1

    # cleanup
    cap.release()
    sock.close()
    if channel:
        time.sleep(0.5)
        channel.stop()

    print(f"[SENDER] Done. frames={frame_id} critical={sent_crit} normal={sent_norm}")


if __name__ == "__main__": # configuring arguments for CLI execution
    parser = argparse.ArgumentParser(description="ML-driven Micro-QUIC video sender")
    parser.add_argument("--video", default="data/testVideo.mp4") # video path
    parser.add_argument("--host", default="127.0.0.1") # host ip
    parser.add_argument("--port", type=int, default=50007) # host port
    parser.add_argument("--loss-rate", type=float, default=0.0) # loss rate
    parser.add_argument("--max-frames", type=int, default=0, help="0 = all frames") # maximum number of frames to be considered
    args = parser.parse_args()

    run_video_sender(args.video, (args.host, args.port), args.loss_rate, args.max_frames)

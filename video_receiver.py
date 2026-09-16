"""
Receive Micro-QUIC JPEG frames (reassembled), ACK critical fragments automatically.
"""
import argparse

import cv2 as cv
import numpy as np

from micro_quic import MicroQUICSocket


def run_video_receiver(port: int, display: bool = True, max_frames: int = 0):
    sock = MicroQUICSocket()
    sock.bind(("127.0.0.1", port))
    # Block until a packet arrives; avoid busy-spinning on timeout returns
    sock.settimeout(None)
    print(f"[RECV] Listening on 127.0.0.1:{port}")

    received = 0 # total number of received packets and critical packets
    critical = 0

    while True:
        if max_frames and received >= max_frames:
            break

        payload, addr, is_crit = sock.recv_packet() # receive video frame packet
        if payload is None: # payload not received
            continue

        arr = np.frombuffer(payload, dtype=np.uint8) 
        frame = cv.imdecode(arr, cv.IMREAD_COLOR) # convert encoded frame back to normal
        if frame is None: # frame decode error
            print(f"[RECV] bad JPEG from {addr} crit={is_crit} len={len(payload)}")
            continue

        # recording number of total and critical frames received
        received += 1 
        if is_crit:
            critical += 1

        tag = "CRITICAL" if is_crit else "normal"
        print(f"[RECV] #{received} {frame.shape} {tag} len={len(payload)} from {addr}")

        if display:
            cv.imshow("microQUIC", frame) # show the frame with title microQUIC
            if cv.waitKey(1) & 0xFF == ord("q"): # exit condition
                break

    # cleanup
    sock.close()
    if display:
        cv.destroyAllWindows()
    print(f"[RECV] Done. frames={received} critical={critical}")


if __name__ == "__main__": # argument parsing for CLI
    parser = argparse.ArgumentParser(description="Micro-QUIC video receiver")
    parser.add_argument("--port", type=int, default=50007)
    parser.add_argument("--no-display", action="store_true")
    parser.add_argument("--max-frames", type=int, default=0, help="0 = run until Ctrl-C")
    args = parser.parse_args()

    run_video_receiver(args.port, display=not args.no_display, max_frames=args.max_frames)

"""Micro-QUIC vs Standard TCP vs Standard UDP Benchmark Suite.

Simulates packet loss across all three protocols and evaluates:
- Goodput (packets/sec and KB/s)
- Total vs Critical packet delivery rates
- Latency and transfer duration
- Visual metrics dashboard comparison

Fairness model: every protocol transmits logical messages over the same
per-datagram loss channel. Messages larger than one datagram are split into
1200-byte chunks (matching Micro-QUIC's MTU-friendly MAX_PAYLOAD_SIZE),
and a message counts as received only when *all* of its chunks arrive —
this is how loss actually treats fragmented video frames on a real network
(any missing fragment kills the frame). UDP gets no free loopback
reassembly and payloads are never truncated.
"""
import argparse
import json
import math
import socket
import threading
import time
from typing import List, Dict, Any, Tuple, Union

import cv2 as cv

from channel import LossyChannel, LossyTCPChannel, tcp_send_frame, tcp_recv_frame, tcp_send_reliable
from classifier import predict_criticality
from features import extractFeatures
from micro_quic import MicroQUICSocket, MAX_PAYLOAD_SIZE

# Shared loss granularity: all protocols split oversized messages into
# datagrams of this size so every protocol pays the same multi-fragment
# cost under packet loss.
BENCH_CHUNK_SIZE = MAX_PAYLOAD_SIZE


def _extract_video_workload(
    video_path: str,
    count: int,
    full_frames: bool,
) -> Tuple[List[Tuple[bytes, bool]], str]:
    """Extract frames from a real video and classify each with the trained ML model.

    Criticality is decided *only* by ``predict_criticality`` on real decoded-frame
    features (diff, encoded size) — no ratios, keyframe intervals, or synthetic
    feature vectors.

    If ``full_frames`` is False, payloads are compact per-frame descriptors (real
    frames still drive the features/classification); if True, the actual encoded
    frame bytes are sent (real multi-fragment frame streaming).

    Criticality is bursty, so the window is extended until it includes a
    meaningful critical mix (>= 3 criticals or ~10% of the window, bounded
    +1000 frames) — a calm intro would otherwise starve the benchmark of
    critical frames ARQ is designed to protect.
    """
    cap = cv.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"Could not open video file: {video_path}")

    workload: List[Tuple[bytes, bool]] = []
    prev_gray = None
    read_frames = 0
    hard_limit = count if count > 0 else 10 ** 9  # count=0 => whole video
    extend_limit = hard_limit + 1000  # safety bound for calm-clip extension
    # Criticality is bursty (e.g. calm intros followed by sustained motion).
    # Extend until the window contains a few criticals (~10% of the window),
    # not merely the first one, so the benchmark/results reflect a sensible mix.
    crit_target = max(3, math.ceil(0.10 * count)) if count > 0 else 1
    crit_count = 0
    extended_note_shown = False

    # One continuous sequential pass: read ``count`` frames. If the ML
    # classifier hasn't reached the critical-frame target yet (calm clip
    # intro), extend reading up to +1000 more frames so the ARQ path is
    # meaningfully exercised.
    while True:
        if read_frames >= hard_limit:
            if crit_count >= crit_target or read_frames >= extend_limit:
                break
            if not extended_note_shown:
                print(
                    f"[BENCHMARK] Only {crit_count}/{len(workload)} ML-critical frames in "
                    f"first {count}; extending frame window (up to {extend_limit}, "
                    f"target {crit_target} criticals)."
                )
                extended_note_shown = True

        ret, frame = cap.read()
        if not ret:
            break
        read_frames += 1

        gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        diff, size, encoded = extractFeatures(prev_gray, gray, frame)
        prev_gray = gray

        if encoded is None or size == 0:
            continue

        is_crit = predict_criticality((diff, size))
        if is_crit:
            crit_count += 1
        payload = encoded.tobytes() if full_frames else (
            f"VFRAME_{read_frames - 1}|diff={diff:.4f}|size={size}|"
            f"len={len(encoded)}".encode()
        )
        workload.append((payload, is_crit))
    cap.release()

    if crit_count == 0:
        print(
            f"[BENCHMARK] Warning: no ML-critical frames found in '{video_path}'. "
            "Consider a higher-motion clip or retrain with train_classifier.py."
        )
    pct = crit_count / max(1, len(workload)) * 100.0
    mode = "full encoded frames" if full_frames else "compact payloads, real-frame criticality"
    desc = (
        f"Real video '{video_path}' ({mode}) "
        f"[ML Decision Tree: {crit_count}/{len(workload)} critical ({pct:.1f}%)]"
    )
    return workload, desc


def create_benchmark_workload(
    count: int = 100,
    critical_ratio: float = 0.2,
    video_path: str = "",
    use_model: bool = False,
    full_frames: bool = False,
) -> Tuple[List[Tuple[bytes, bool]], str]:
    """Generate or extract the benchmark packet workload.

    - If video_path is provided: extracts frames from the video file and evaluates
      each frame dynamically with the trained ML classifier (predict_criticality).
      By default payloads are compact per-frame descriptors (real decoded frames,
      real ML criticality) so all three protocols are compared at the same
      datagram granularity; pass full_frames=True to send the actual encoded
      frame bytes (real multi-fragment frame streaming).
    - If use_model is True without video: evaluates simulated video motion/size
      features with predict_criticality to dynamically determine criticality.
    - Otherwise: uses the configured critical_ratio (default 0.2 = 20%).
    """
    workload: List[Tuple[bytes, bool]] = []

    if video_path:
        try:
            return _extract_video_workload(video_path, count, full_frames)
        except FileNotFoundError:
            raise SystemExit(f"[BENCHMARK] Error: Could not open video file: {video_path}")

    if use_model:
        for i in range(count):
            # Simulate dynamic video motion patterns (background drift + periodic scene cuts)
            diff = 0.4 + (2.5 if (i % 7 == 0) else (0.15 * (i % 5)))
            size = 45000 + (18000 if (i % 7 == 0) else 0)
            is_crit = predict_criticality((diff, size))
            payload = f"SYNTH_FRAME_{i}".encode()
            workload.append((payload, is_crit))
        crit_count = sum(1 for _, c in workload if c)
        desc = f"Simulated frame features [ML Decision Tree: {crit_count}/{len(workload)} critical ({crit_count / max(1, len(workload)) * 100:.1f}%)]"
        return workload, desc

    # Ratio-based workload
    crit_interval = max(1, int(round(1.0 / critical_ratio))) if critical_ratio > 0 else 0
    for i in range(count):
        is_crit = (i % crit_interval == 0) if crit_interval > 0 else False
        payload = f"BENCH_PACKET_{i}".encode()
        workload.append((payload, is_crit))
    crit_count = sum(1 for _, c in workload if c)
    desc = f"Synthetic packets [Configured ratio: {critical_ratio * 100:.0f}% ({crit_count}/{len(workload)} critical)]"
    return workload, desc


def _resolve_workload(workload_or_count: Union[int, List[Tuple[bytes, bool]]]) -> List[Tuple[bytes, bool]]:
    if isinstance(workload_or_count, int):
        workload, _ = create_benchmark_workload(count=workload_or_count)
        return workload
    return workload_or_count


def run_tcp_benchmark(workload_or_count: Union[int, List[Tuple[bytes, bool]]], loss_rate: float) -> dict:
    """TCP-like reliability under the same loss model: Stop-and-Wait ARQ on every packet."""
    workload = _resolve_workload(workload_or_count)
    total_packets = len(workload)
    server_port = 55001
    proxy_port = 55002
    rto = 0.02
    max_retries = 5

    channel = LossyTCPChannel(listen_port=proxy_port, target_port=server_port, loss_rate=loss_rate)
    channel.start()

    received_count = 0
    critical_received = 0
    end_time = 0.0
    bytes_received = 0

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(('127.0.0.1', server_port))
    server_sock.listen(1)

    def server_thread():
        nonlocal received_count, critical_received, end_time, bytes_received
        conn, _ = server_sock.accept()
        seen = set()
        while True:
            data = tcp_recv_frame(conn)
            if data is None:
                break
            if data not in seen:
                seen.add(data)
                received_count += 1
                bytes_received += len(data)
                if data.startswith(b"CRITICAL"):
                    critical_received += 1
            pkt_id = data.rsplit(b"_", 1)[-1]
            try:
                tcp_send_frame(conn, b"ACK_" + pkt_id)
            except OSError:
                break
        end_time = time.time()
        conn.close()
        server_sock.close()

    t = threading.Thread(target=server_thread, daemon=True)
    t.start()
    time.sleep(0.1)

    client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_sock.connect(('127.0.0.1', proxy_port))

    start_time = time.time()
    critical_total = 0
    bytes_sent = 0

    for i, (item_payload, is_crit) in enumerate(workload):
        if is_crit:
            critical_total += 1
        prefix = b"CRITICAL_" if is_crit else b"NORMAL_"
        payload = prefix + item_payload
        bytes_sent += len(payload)
        tcp_send_reliable(
            client_sock,
            payload,
            ack_token=f"ACK_{i}".encode(),
            timeout=rto,
            max_retries=max_retries,
        )
        time.sleep(0.001)

    client_sock.close()
    t.join(timeout=5.0)
    channel.stop()

    elapsed = (end_time - start_time) if end_time > start_time else (time.time() - start_time)
    goodput_kbps = (bytes_received * 8 / (elapsed * 1000.0)) if elapsed > 0 else 0.0

    return {
        'protocol': 'Standard TCP',
        'sent': total_packets,
        'received': received_count,
        'critical_received': critical_received,
        'critical_total': critical_total,
        'bytes_sent': bytes_sent,
        'bytes_received': bytes_received,
        'goodput_kbps': goodput_kbps,
        'time_sec': elapsed,
    }


def run_udp_benchmark(workload_or_count: Union[int, List[Tuple[bytes, bool]]], loss_rate: float) -> dict:
    """Standard UDP baseline: no ACKs, drops under loss without retransmission.

    Oversized messages are split into BENCH_CHUNK_SIZE datagrams (like real
    RTP-style UDP video streaming). A message counts as received only when
    every datagram of it arrives; losing any datagram kills the message.
    """
    workload = _resolve_workload(workload_or_count)
    total_packets = len(workload)
    server_port = 55003
    proxy_port = 55004

    channel = LossyChannel(listen_port=proxy_port, target_port=server_port, loss_rate=loss_rate)
    channel.start()

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_sock.bind(('127.0.0.1', server_port))
    server_sock.settimeout(1.0)

    received_count = 0
    critical_received = 0
    bytes_received = 0

    def receiver_thread():
        nonlocal received_count, critical_received, bytes_received
        # frame_id -> {"n": total chunks, "chunks": {idx: size}, "critical": bool}
        in_flight_frames: Dict[str, Dict[str, Any]] = {}
        while True:
            try:
                data, _ = server_sock.recvfrom(65535)
            except socket.timeout:
                break

            if data.startswith(b"CRITICAL_"):
                is_crit = True
                rest = data[len(b"CRITICAL_"):]
            elif data.startswith(b"NORMAL_"):
                is_crit = False
                rest = data[len(b"NORMAL_"):]
            else:
                continue

            # Layout: FRAME_ID_NNN_JJJ_<chunk bytes>
            parts = rest.split(b"_", 3)
            if len(parts) != 4:
                continue
            fid, n_bytes, j_bytes, chunk = parts
            if n_bytes.isdigit() and j_bytes.isdigit():
                fid = fid.decode(errors="ignore")
                n, j = int(n_bytes), int(j_bytes)
                if n <= 0 or j >= n:
                    continue
                state = in_flight_frames.setdefault(
                    fid, {"n": n, "chunks": {}, "critical": is_crit}
                )
                if n != state["n"] or is_crit != state["critical"]:
                    continue
                state["chunks"][j] = len(chunk)

                if len(state["chunks"]) == state["n"]:
                    # All chunks arrived: message delivered
                    received_count += 1
                    bytes_received += sum(state["chunks"].values())
                    if state["critical"]:
                        critical_received += 1
                    in_flight_frames.pop(fid, None)

    t = threading.Thread(target=receiver_thread, daemon=True)
    t.start()

    client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    start_time = time.time()
    critical_total = 0
    bytes_sent = 0

    for i, (item_payload, is_crit) in enumerate(workload):
        prefix = b"CRITICAL_" if is_crit else b"NORMAL_"
        if is_crit:
            critical_total += 1
        bytes_sent += len(item_payload)
        chunks = [
            item_payload[j:j + BENCH_CHUNK_SIZE]
            for j in range(0, len(item_payload), BENCH_CHUNK_SIZE)
        ] or [b""]
        n = len(chunks)
        for j, chunk in enumerate(chunks):
            header = prefix + f"{i:05d}_{n:03d}_{j:03d}_".encode()
            client_sock.sendto(header + chunk, ('127.0.0.1', proxy_port))
            time.sleep(0.001)
        if n > 1:
            time.sleep(0.02)  # inter-message pacing for bursty multi-datagram frames

    time.sleep(1.2)
    end_time = time.time() - 1.2

    channel.stop()
    server_sock.close()
    client_sock.close()

    elapsed = max(0.001, end_time - start_time)
    goodput_kbps = (bytes_received * 8 / (elapsed * 1000.0)) if elapsed > 0 else 0.0

    return {
        'protocol': 'Standard UDP',
        'sent': total_packets,
        'received': received_count,
        'critical_received': critical_received,
        'critical_total': critical_total,
        'bytes_sent': bytes_sent,
        'bytes_received': bytes_received,
        'goodput_kbps': goodput_kbps,
        'time_sec': elapsed,
    }


def run_microquic_benchmark(workload_or_count: Union[int, List[Tuple[bytes, bool]]], loss_rate: float) -> dict:
    """Micro-QUIC: Selective Repeat ARQ on critical packets only."""
    workload = _resolve_workload(workload_or_count)
    total_packets = len(workload)
    server_port = 55005
    proxy_port = 55006

    channel = LossyChannel(listen_port=proxy_port, target_port=server_port, loss_rate=loss_rate)
    channel.start()

    server_quic = MicroQUICSocket()
    server_quic.bind(('127.0.0.1', server_port))
    server_quic.settimeout(1.0)

    received_count = 0
    critical_received = 0
    bytes_received = 0

    def receiver_thread():
        nonlocal received_count, critical_received, bytes_received
        while True:
            payload, addr, is_crit = server_quic.recv_packet()
            if payload is None:
                break
            received_count += 1
            bytes_received += len(payload)
            if is_crit:
                critical_received += 1

    t = threading.Thread(target=receiver_thread, daemon=True)
    t.start()

    client_quic = MicroQUICSocket(timeout=0.03, max_retries=5, window_size=16)
    start_time = time.time()
    critical_total = 0
    bytes_sent = 0

    for i, (item_payload, is_crit) in enumerate(workload):
        if is_crit:
            critical_total += 1
        bytes_sent += len(item_payload)
        client_quic.send_packet(item_payload, ('127.0.0.1', proxy_port), is_critical=is_crit)
        pacing = 0.02 if len(item_payload) > 1500 else 0.001
        time.sleep(pacing)

    wait_time = 1.5 if (workload and len(workload[0][0]) > 1500) else 1.2
    time.sleep(wait_time)
    end_time = time.time() - wait_time

    channel.stop()
    server_quic.close()
    client_quic.close()

    elapsed = max(0.001, end_time - start_time)
    goodput_kbps = (bytes_received * 8 / (elapsed * 1000.0)) if elapsed > 0 else 0.0

    return {
        'protocol': 'Micro-QUIC',
        'sent': total_packets,
        'received': received_count,
        'critical_received': critical_received,
        'critical_total': critical_total,
        'bytes_sent': bytes_sent,
        'bytes_received': bytes_received,
        'goodput_kbps': goodput_kbps,
        'time_sec': elapsed,
    }


def print_benchmark_dashboard(loss_rate: float, results: List[Dict[str, Any]], workload_desc: str = ""):
    """Render a visual ASCII metrics dashboard comparing all protocols."""
    print("\n" + "=" * 98)
    print(f"             MICRO-QUIC PERFORMANCE & RELIABILITY DASHBOARD (Loss Rate: {int(loss_rate * 100)}%)")
    if workload_desc:
        print(f"  Workload: {workload_desc}")
    print("=" * 98)
    header_fmt = "{:<16} | {:<10} | {:<10} | {:<16} | {:<10} | {:<14}"
    row_fmt = "{:<16} | {:<10} | {:<10} | {:<16} | {:<10.3f}s | {:<10.1f} kbps"

    print(header_fmt.format("Protocol", "Sent", "Received", "Critical Ratio", "Latency", "Goodput"))
    print("-" * 98)

    for r in results:
        crit_pct = (r['critical_received'] / max(1, r['critical_total'])) * 100
        crit_ratio_str = f"{r['critical_received']}/{r['critical_total']} ({crit_pct:.1f}%)"
        print(row_fmt.format(
            r['protocol'],
            r['sent'],
            r['received'],
            crit_ratio_str,
            r['time_sec'],
            r['goodput_kbps'],
        ))
    print("=" * 98)

    # Visual Bar Chart for Critical Reliability & Latency
    print("\n[VISUAL METRICS COMPARISON]")
    for r in results:
        crit_pct = (r['critical_received'] / max(1, r['critical_total'])) * 100
        bar_len = int(crit_pct / 5)  # 20 bars max
        crit_bar = "█" * bar_len + "░" * (20 - bar_len)
        print(f"  {r['protocol']:<15} Critical Delivery: [{crit_bar}] {crit_pct:5.1f}% | Latency: {r['time_sec']:.3f}s")
    print("-" * 98 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Micro-QUIC Benchmark Suite")
    parser.add_argument("--packets", type=int, default=100, help="Number of test packets per protocol")
    parser.add_argument("--loss-rate", type=float, default=0.15, help="Simulated loss rate (0.0 to 1.0)")
    parser.add_argument("--critical-ratio", type=float, default=0.2, help="Ratio of critical packets when using synthetic workload (default: 0.2)")
    parser.add_argument("--video", default="", help="Path to video file for ML-driven frame criticality benchmarking")
    parser.add_argument("--full-frames", action="store_true",
                        help="Send actual encoded frame bytes from the video (multi-fragment stream) "
                             "instead of compact per-frame payloads")
    parser.add_argument("--use-model", action="store_true", help="Use trained ML model to classify synthetic feature vectors")
    parser.add_argument("--export-json", default="", help="Export benchmark results to JSON file")
    args = parser.parse_args()

    workload, workload_desc = create_benchmark_workload(
        count=args.packets,
        critical_ratio=args.critical_ratio,
        video_path=args.video,
        use_model=args.use_model,
        full_frames=args.full_frames,
    )

    print(f"Running benchmarks with {len(workload)} packets under {int(args.loss_rate * 100)}% simulated packet loss...")
    print(f"Workload: {workload_desc}")

    res_tcp = run_tcp_benchmark(workload, args.loss_rate)
    res_udp = run_udp_benchmark(workload, args.loss_rate)
    res_mquic = run_microquic_benchmark(workload, args.loss_rate)

    results = [res_tcp, res_udp, res_mquic]
    print_benchmark_dashboard(args.loss_rate, results, workload_desc=workload_desc)

    if args.export_json:
        with open(args.export_json, "w") as f:
            json.dump({
                "loss_rate": args.loss_rate,
                "workload_description": workload_desc,
                "results": results
            }, f, indent=2)
        print(f"[BENCHMARK] Results saved to: {args.export_json}")

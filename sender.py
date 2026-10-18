"""Telemetry demo application for Micro-QUIC (sender / receiver).

Supports:
- Selective reliability ARQ for critical telemetry packets
- Simulated lossy channel proxy (--loss-rate)
- Multi-stream identification (--stream-id)
- Authenticated PSK encryption (--psk)
- Rate limiting (--rate-limit)
"""
import argparse
import time
from typing import Optional

from channel import LossyChannel
from micro_quic import MicroQUICSocket


def run_receiver(
    port: int,
    host: str = "127.0.0.1",
    psk: Optional[str] = None,
    stream_id: Optional[int] = None,
):
    """Run Micro-QUIC telemetry receiver."""
    sock = MicroQUICSocket(psk=psk)
    sock.bind((host, port))
    print(
        f"[RECEIVER] Micro-QUIC Receiver listening on {host}:{port}... "
        f"[stream={stream_id if stream_id is not None else 'any'}, psk={'yes' if psk else 'no'}]"
    )

    received_count = 0
    critical_count = 0

    try:
        while True:
            result = sock.recv_packet(include_stream_id=True)
            if not result or result[0] is None:
                continue

            payload, addr, is_crit, pkt_stream = result
            if stream_id is not None and pkt_stream != stream_id:
                continue

            received_count += 1
            tag = "[CRITICAL]" if is_crit else "[NORMAL]  "
            if is_crit:
                critical_count += 1

            text = payload.decode(errors="replace")
            print(f"[RECEIVER] Recv #{received_count:<3} {tag} stream={pkt_stream} Data: '{text}' from {addr}")
    except KeyboardInterrupt:
        print("\n[RECEIVER] Stopped.")
    finally:
        sock.close()
        print(f"[RECEIVER] Done. total={received_count} critical={critical_count}")


def run_sender(
    target_port: int,
    host: str = "127.0.0.1",
    count: int = 30,
    critical_ratio: float = 0.2,
    loss_rate: float = 0.0,
    psk: Optional[str] = None,
    stream_id: int = 0,
    rate_limit_kbps: Optional[float] = None,
):
    """Run Micro-QUIC telemetry sender."""
    proxy_port = target_port + 100

    if loss_rate > 0:
        print(f"[CHANNEL] Starting lossy proxy :{proxy_port} -> :{target_port} (Loss: {int(loss_rate * 100)}%)")
        channel = LossyChannel(listen_port=proxy_port, target_port=target_port, loss_rate=loss_rate)
        channel.start()
        dest_port = proxy_port
    else:
        dest_port = target_port
        channel = None

    sock = MicroQUICSocket(
        timeout=0.1,
        max_retries=5,
        psk=psk,
        rate_limit_kbps=rate_limit_kbps,
    )
    print(
        f"[SENDER] Sending {count} telemetry packets to {host}:{dest_port}... "
        f"[crit_ratio={critical_ratio * 100:.0f}%, stream={stream_id}, psk={'yes' if psk else 'no'}]"
    )

    sent_crit = 0
    sent_norm = 0

    try:
        for i in range(1, count + 1):
            is_crit = (i % int(1 / critical_ratio) == 0) if critical_ratio > 0 else False
            if is_crit:
                sent_crit += 1
            else:
                sent_norm += 1

            tag = "[CRITICAL]" if is_crit else "[NORMAL]  "
            msg = f"Telemetry Payload #{i}"
            print(f"[SENDER] Transmitting #{i:<3} {tag}...", end=" ")

            success = sock.send_packet(
                msg.encode(),
                (host, dest_port),
                is_critical=is_crit,
                stream_id=stream_id,
            )
            if is_crit:
                status = "ACK RECEIVED" if success else "FAILED / TIMEOUT"
                print(f"Status: {status}")
            else:
                print("Sent")

            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n[SENDER] Interrupted.")
    finally:
        sock.close()
        if channel:
            time.sleep(0.5)
            channel.stop()

    print(f"\n[SENDER] Transfer complete. Sent {sent_crit} critical & {sent_norm} normal packets.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Micro-QUIC Telemetry Sender / Receiver Demo")
    parser.add_argument("mode", choices=["sender", "receiver"], help="Mode: sender or receiver")
    parser.add_argument("--host", default="127.0.0.1", help="Target server host / IP")
    parser.add_argument("--port", type=int, default=50007, help="Target server port")
    parser.add_argument("--count", "--max-frames", dest="count", type=int, default=30, help="Number of packets to send")
    parser.add_argument("--critical-ratio", type=float, default=0.2, help="Ratio of critical packets (0.2 = 20%)")
    parser.add_argument("--loss-rate", type=float, default=0.0, help="Simulated packet loss rate (e.g. 0.15 = 15%)")
    parser.add_argument("--psk", default="", help="Pre-shared key for authenticated encryption")
    parser.add_argument("--stream-id", type=int, default=0, help="Stream ID (0-7)")
    parser.add_argument("--rate-limit", type=float, default=0.0, help="Transmission rate limit in kbps (0 = unlimited)")

    args = parser.parse_args()

    psk_key = args.psk if args.psk else None
    rate_lim = args.rate_limit if args.rate_limit > 0 else None

    if args.mode == "receiver":
        run_receiver(args.port, host=args.host, psk=psk_key, stream_id=args.stream_id)
    else:
        run_sender(
            target_port=args.port,
            host=args.host,
            count=args.count,
            critical_ratio=args.critical_ratio,
            loss_rate=args.loss_rate,
            psk=psk_key,
            stream_id=args.stream_id,
            rate_limit_kbps=rate_lim,
        )

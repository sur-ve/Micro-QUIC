import time
import argparse
from micro_quic import MicroQUICSocket
from channel import LossyChannel

def run_receiver(port: int):
    sock = MicroQUICSocket()
    sock.bind(('127.0.0.1', port))
    print(f"[RECEIVER] Micro-QUIC Receiver listening on 127.0.0.1:{port}...")
    
    received_count = 0
    critical_count = 0

    while True:
        payload, addr, is_crit = sock.recv_packet()
        if payload is None:
            continue

        received_count += 1
        tag = "[CRITICAL]" if is_crit else "[NORMAL]  "
        if is_crit:
            critical_count += 1

        print(f"[RECEIVER] Recv #{received_count} {tag} Data: {payload.decode()} from {addr}")

def run_sender(target_port: int, count: int, critical_ratio: float, loss_rate: float):
    proxy_port = target_port + 100
    
    # Start proxy channel if loss_rate > 0
    if loss_rate > 0:
        print(f"[CHANNEL] Starting lossy channel proxy on :{proxy_port} -> :{target_port} (Loss Rate: {int(loss_rate*100)}%)")
        channel = LossyChannel(listen_port=proxy_port, target_port=target_port, loss_rate=loss_rate)
        channel.start()
        dest_port = proxy_port
    else:
        dest_port = target_port
        channel = None

    sock = MicroQUICSocket(timeout=0.1, max_retries=5)
    print(f"[SENDER] Sending {count} packets to 127.0.0.1:{dest_port}...")

    sent_crit = 0
    sent_norm = 0

    for i in range(1, count + 1):
        is_crit = (i % int(1 / critical_ratio) == 0) if critical_ratio > 0 else False
        if is_crit:
            sent_crit += 1
        else:
            sent_norm += 1

        tag = "[CRITICAL]" if is_crit else "[NORMAL]  "
        msg = f"Telemetry Payload #{i}"
        print(f"[SENDER] Transmitting #{i} {tag}...")

        success = sock.send_packet(msg.encode(), ('127.0.0.1', dest_port), is_critical=is_crit)
        if is_crit:
            status = "ACK RECEIVED" if success else "FAILED / TIMEOUT"
            print(f"[SENDER]   └─> Critical #{i} Status: {status}")
        
        time.sleep(0.05)

    print(f"\n[SENDER] Transfer complete. Sent {sent_crit} critical & {sent_norm} normal packets.")

    if channel:
        time.sleep(1.0)
        channel.stop()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Micro-QUIC Sender / Receiver Demo")
    parser.add_argument("mode", choices=["sender", "receiver"], help="Mode: sender or receiver")
    parser.add_argument("--port", type=int, default=50007, help="Target server port")
    parser.add_argument("--count", type=int, default=30, help="Number of packets to send")
    parser.add_argument("--critical-ratio", type=float, default=0.2, help="Ratio of critical packets (0.2 = 20%%)")
    parser.add_argument("--loss-rate", type=float, default=0.15, help="Simulated packet loss rate (0.15 = 15%%)")

    args = parser.parse_args()

    if args.mode == "receiver":
        run_receiver(args.port)
    else:
        run_sender(args.port, args.count, args.critical_ratio, args.loss_rate)

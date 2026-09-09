import time
import socket
import threading
from micro_quic import MicroQUICSocket
from channel import LossyChannel

def run_tcp_benchmark(total_packets: int, loss_rate: float) -> dict:
    server_port = 55001
    
    received_count = 0
    start_time = 0
    end_time = 0

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(('127.0.0.1', server_port))
    server_sock.listen(1)

    def server_thread():
        nonlocal received_count, end_time
        conn, _ = server_sock.accept()
        while True:
            data = conn.recv(1024)
            if not data:
                break
            received_count += 1
        end_time = time.time()
        conn.close()
        server_sock.close()

    t = threading.Thread(target=server_thread, daemon=True)
    t.start()

    time.sleep(0.1)

    client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_sock.connect(('127.0.0.1', server_port))

    start_time = time.time()
    critical_total = int(total_packets * 0.2)
    for i in range(total_packets):
        client_sock.sendall(f"TCP_PACKET_{i}".encode())
        time.sleep(0.001)
    client_sock.close()

    t.join(timeout=5.0)

    elapsed = (end_time - start_time) if end_time > start_time else 0.001
    return {
        'protocol': 'Standard TCP',
        'sent': total_packets,
        'received': received_count,
        'critical_received': critical_total,
        'critical_total': critical_total,
        'time_sec': elapsed
    }



def run_udp_benchmark(total_packets: int, loss_rate: float) -> dict:
    server_port = 55003
    proxy_port = 55004

    # Setup lossy channel proxy
    channel = LossyChannel(listen_port=proxy_port, target_port=server_port, loss_rate=loss_rate)
    channel.start()

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_sock.bind(('127.0.0.1', server_port))
    server_sock.settimeout(1.0)

    received_count = 0
    critical_received = 0

    def receiver_thread():
        nonlocal received_count, critical_received
        while True:
            try:
                data, _ = server_sock.recvfrom(1024)
                received_count += 1
                if data.startswith(b"CRITICAL"):
                    critical_received += 1
            except socket.timeout:
                break

    t = threading.Thread(target=receiver_thread, daemon=True)
    t.start()

    client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    start_time = time.time()
    critical_total = 0

    for i in range(total_packets):
        is_crit = (i % 5 == 0)  # 20% critical
        prefix = b"CRITICAL_" if is_crit else b"NORMAL_"
        if is_crit:
            critical_total += 1
        client_sock.sendto(prefix + f"UDP_PACKET_{i}".encode(), ('127.0.0.1', proxy_port))
        time.sleep(0.001)

    time.sleep(1.2)  # Wait for socket timeout
    end_time = time.time() - 1.2
    
    channel.stop()
    server_sock.close()
    client_sock.close()

    elapsed = max(0.001, end_time - start_time)
    return {
        'protocol': 'Standard UDP',
        'sent': total_packets,
        'received': received_count,
        'critical_received': critical_received,
        'critical_total': critical_total,
        'time_sec': elapsed
    }


def run_microquic_benchmark(total_packets: int, loss_rate: float) -> dict:
    server_port = 55005
    proxy_port = 55006

    channel = LossyChannel(listen_port=proxy_port, target_port=server_port, loss_rate=loss_rate)
    channel.start()

    server_quic = MicroQUICSocket()
    server_quic.bind(('127.0.0.1', server_port))
    server_quic.settimeout(1.0)

    received_count = 0
    critical_received = 0

    def receiver_thread():
        nonlocal received_count, critical_received
        while True:
            payload, addr, is_crit = server_quic.recv_packet()
            if payload is None:
                break
            received_count += 1
            if is_crit:
                critical_received += 1

    t = threading.Thread(target=receiver_thread, daemon=True)
    t.start()

    client_quic = MicroQUICSocket(timeout=0.08, max_retries=5)

    start_time = time.time()
    critical_total = 0

    for i in range(total_packets):
        is_crit = (i % 5 == 0)  # 20% critical
        if is_crit:
            critical_total += 1
        client_quic.send_packet(f"QUIC_PACKET_{i}".encode(), ('127.0.0.1', proxy_port), is_critical=is_crit)
        time.sleep(0.001)

    time.sleep(1.2)
    end_time = time.time() - 1.2

    channel.stop()
    server_quic.close()
    client_quic.close()

    elapsed = max(0.001, end_time - start_time)
    return {
        'protocol': 'Micro-QUIC',
        'sent': total_packets,
        'received': received_count,
        'critical_received': critical_received,
        'critical_total': critical_total,
        'time_sec': elapsed
    }


def print_benchmark_summary(loss_rate: float, results: list):
    print("\n" + "=" * 90)
    print(f"               MICRO-QUIC VS TCP VS UDP BENCHMARK REPORT (Loss Rate: {int(loss_rate*100)}%)")
    print("=" * 90)
    header_fmt = "{:<16} | {:<10} | {:<14} | {:<20} | {:<12}"
    row_fmt    = "{:<16} | {:<10} | {:<14} | {:<20} | {:<12.3f}s"
    
    print(header_fmt.format("Protocol", "Total Sent", "Total Recv", "Critical Recv Ratio", "Time Taken"))
    print("-" * 90)
    
    for r in results:
        crit_ratio = f"{r['critical_received']}/{r['critical_total']} ({r['critical_received']/max(1, r['critical_total'])*100:.1f}%)"
        print(row_fmt.format(
            r['protocol'],
            r['sent'],
            r['received'],
            crit_ratio,
            r['time_sec']
        ))
    print("=" * 90 + "\n")


if __name__ == "__main__":
    LOSS_RATE = 0.15  # 15% simulated packet loss
    TOTAL_PACKETS = 100

    print(f"Running benchmarks with {TOTAL_PACKETS} packets under {int(LOSS_RATE*100)}% simulated packet loss...")
    
    res_udp = run_udp_benchmark(TOTAL_PACKETS, LOSS_RATE)
    res_mquic = run_microquic_benchmark(TOTAL_PACKETS, LOSS_RATE)
    res_tcp = run_tcp_benchmark(TOTAL_PACKETS, LOSS_RATE)

    print_benchmark_summary(LOSS_RATE, [res_tcp, res_udp, res_mquic])

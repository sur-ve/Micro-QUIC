import socket
import random
import time
import threading
from header import MicroQUICPacket, HEADER_SIZE

class LossyChannel:
    """
    Simulates a network channel between client and server with:
    - Packet loss rate (0.0 to 1.0)
    - Delay (latency in seconds)
    - Data corruption rate (0.0 to 1.0)
    - Optional ACK protection (ACKs are never dropped)
    """
    def __init__(
        self,
        listen_port: int,
        target_port: int,
        loss_rate: float = 0.1,
        delay_ms: float = 0.0,
        corruption_rate: float = 0.0,
        protect_acks: bool = True,
    ):
        self.listen_port = listen_port
        self.target_port = target_port
        self.loss_rate = loss_rate
        self.delay_sec = delay_ms / 1000.0
        self.corruption_rate = corruption_rate
        self.protect_acks = protect_acks
        self.running = False
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', self.listen_port))
        self.stats = {
            'forwarded': 0,
            'dropped': 0,
            'corrupted': 0
        }

    def _is_ack(self, data: bytes) -> bool:
        if len(data) < HEADER_SIZE:
            return False
        try:
            pkt = MicroQUICPacket.unpack(data)
            # Require a valid CRC so raw UDP payloads like b"CRITICAL_..." are not
            # treated as ACKs (their 9th byte is '_' = 0x5F, which has the ACK bit set).
            return pkt.is_valid and pkt.is_ack
        except Exception:
            return False

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self.sock.close()

    def _run(self):
        self.sock.settimeout(0.2)
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except Exception:
                break

            # Determine destination port (forwarding proxy)
            # If coming from client port -> send to target_port
            # If coming from target_port -> send back to client
            if addr[1] == self.target_port:
                dest_addr = ('127.0.0.1', self.last_client_port) if hasattr(self, 'last_client_port') else ('127.0.0.1', self.target_port)
            else:
                self.last_client_port = addr[1]
                dest_addr = ('127.0.0.1', self.target_port)

            # 1. Packet Loss Check (optionally spare ACKs so RTO isn't inflated by ACK loss)
            if random.random() < self.loss_rate:
                if not (self.protect_acks and self._is_ack(data)):
                    self.stats['dropped'] += 1
                    continue

            # 2. Corruption Check
            if random.random() < self.corruption_rate:
                self.stats['corrupted'] += 1
                # Corrupt last byte
                data = data[:-1] + b'\xFF' if len(data) > 0 else b'\xFF'

            # 3. Network Delay Simulation
            if self.delay_sec > 0:
                time.sleep(self.delay_sec)

            # Forward Packet
            self.stats['forwarded'] += 1
            self.sock.sendto(data, dest_addr)


class LossyTCPChannel:
    """
    Bidirectional TCP middlebox with the same per-frame loss rate as LossyChannel.
    Models lossy delivery; reliability (retransmit-all) is implemented by the
    TCP benchmark client, mirroring Micro-QUIC's ARQ but for every message.
    """
    def __init__(
        self,
        listen_port: int,
        target_port: int,
        loss_rate: float = 0.1,
        protect_acks: bool = True,
    ):
        self.listen_port = listen_port
        self.target_port = target_port
        self.loss_rate = loss_rate
        self.protect_acks = protect_acks
        self.running = False
        self.listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listen_sock.bind(('127.0.0.1', self.listen_port))
        self.listen_sock.listen(1)
        self.stats = {'forwarded': 0, 'dropped': 0}
        self._threads: list[threading.Thread] = []

    def start(self):
        self.running = True
        t = threading.Thread(target=self._accept_loop, daemon=True)
        t.start()
        self._threads.append(t)

    def stop(self):
        self.running = False
        try:
            self.listen_sock.close()
        except Exception:
            pass

    @staticmethod
    def _recv_exact(conn: socket.socket, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            try:
                chunk = conn.recv(n - len(buf))
            except OSError:
                return b""
            if not chunk:
                return b""
            buf += chunk
        return buf

    def _accept_loop(self):
        self.listen_sock.settimeout(0.2)
        while self.running:
            try:
                client_conn, _ = self.listen_sock.accept()
            except socket.timeout:
                continue
            except Exception:
                break
            t = threading.Thread(target=self._relay_session, args=(client_conn,), daemon=True)
            t.start()
            self._threads.append(t)

    def _should_drop(self, payload: bytes) -> bool:
        if self.protect_acks and payload.startswith(b"ACK"):
            return False
        return random.random() < self.loss_rate

    def _forward_frames(self, src: socket.socket, dst: socket.socket):
        try:
            while self.running:
                header = self._recv_exact(src, 4)
                if not header:
                    break
                length = int.from_bytes(header, "big")
                if length <= 0 or length > 1_000_000:
                    break
                payload = self._recv_exact(src, length)
                if len(payload) < length:
                    break
                if self._should_drop(payload):
                    self.stats['dropped'] += 1
                    continue
                try:
                    dst.sendall(header + payload)
                except OSError:
                    break
                self.stats['forwarded'] += 1
        except OSError:
            pass

    def _relay_session(self, client_conn: socket.socket):
        server_conn = None
        try:
            server_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_conn.connect(('127.0.0.1', self.target_port))
            # Bidirectional: data client→server and ACKs server→client, both lossy
            up = threading.Thread(
                target=self._forward_frames, args=(client_conn, server_conn), daemon=True
            )
            down = threading.Thread(
                target=self._forward_frames, args=(server_conn, client_conn), daemon=True
            )
            up.start()
            down.start()
            up.join()
            # Unblock the reverse path once the client finishes sending
            for conn in (client_conn, server_conn):
                try:
                    conn.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            down.join(timeout=1.0)
        except Exception:
            pass
        finally:
            for conn in (client_conn, server_conn):
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass


def tcp_send_frame(sock: socket.socket, payload: bytes) -> None:
    sock.sendall(len(payload).to_bytes(4, "big") + payload)


def tcp_recv_frame(sock: socket.socket) -> bytes | None:
    header = LossyTCPChannel._recv_exact(sock, 4)
    if not header:
        return None
    length = int.from_bytes(header, "big")
    if length <= 0 or length > 1_000_000:
        return None
    payload = LossyTCPChannel._recv_exact(sock, length)
    return payload if len(payload) == length else None


def tcp_send_reliable(
    sock: socket.socket,
    payload: bytes,
    ack_token: bytes,
    timeout: float = 0.005,
    max_retries: int = 5,
) -> bool:
    """Stop-and-Wait with matching ACK token — models TCP retransmit-under-loss cost."""
    for _ in range(max_retries):
        tcp_send_frame(sock, payload)
        sock.settimeout(timeout)
        try:
            ack = tcp_recv_frame(sock)
            if ack == ack_token:
                return True
            # Stale/mismatched ACK from a prior retransmit — keep waiting in this attempt
            if ack is not None:
                deadline = time.time() + timeout
                while time.time() < deadline:
                    sock.settimeout(max(0.001, deadline - time.time()))
                    try:
                        ack = tcp_recv_frame(sock)
                        if ack == ack_token:
                            return True
                    except (socket.timeout, OSError):
                        break
        except (socket.timeout, OSError):
            continue
    return False

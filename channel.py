import socket
import random
import time
import threading
from header import MicroQUICPacket

class LossyChannel:
    """
    Simulates a network channel between client and server with:
    - Packet loss rate (0.0 to 1.0)
    - Delay (latency in seconds)
    - Data corruption rate (0.0 to 1.0)
    """
    def __init__(self, listen_port: int, target_port: int, loss_rate: float = 0.1, delay_ms: float = 0.0, corruption_rate: float = 0.0):
        self.listen_port = listen_port
        self.target_port = target_port
        self.loss_rate = loss_rate
        self.delay_sec = delay_ms / 1000.0
        self.corruption_rate = corruption_rate
        self.running = False
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', self.listen_port))
        self.stats = {
            'forwarded': 0,
            'dropped': 0,
            'corrupted': 0
        }

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

            # 1. Packet Loss Check
            if random.random() < self.loss_rate:
                self.stats['dropped'] += 1
                # Drop packet
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

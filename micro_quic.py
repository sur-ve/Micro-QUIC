import socket
import time
import select
from typing import Tuple, Optional, Callable, Dict
from header import MicroQUICPacket, FLAG_CRITICAL, FLAG_ACK, FLAG_MORE_FRAGMENTS

DEFAULT_TIMEOUT = 0.1  # 100 ms retransmission timeout
DEFAULT_MAX_RETRIES = 5
MAX_PAYLOAD_SIZE = 1200  # MTU friendly size

class MicroQUICSocket:
    def __init__(self, timeout: float = DEFAULT_TIMEOUT, max_retries: int = DEFAULT_MAX_RETRIES):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.timeout = timeout
        self.max_retries = max_retries
        self.seq_num = 1
        self.expected_seq = 1
        self.received_buffers: Dict[Tuple[str, int], Dict[int, MicroQUICPacket]] = {}

    def bind(self, address: Tuple[str, int]):
        self.sock.bind(address)

    def settimeout(self, value: Optional[float]):
        self.sock.settimeout(value)

    def close(self):
        self.sock.close()

    def send_packet(self, payload: bytes, dest_addr: Tuple[str, int], is_critical: bool = False) -> bool:
        """
        Sends a single payload to target destination.
        If is_critical=True, waits for ACK and retransmits on timeout.
        """
        flags = FLAG_CRITICAL if is_critical else 0
        seq = self.seq_num
        self.seq_num += 1

        pkt = MicroQUICPacket(seq=seq, ack=0, flags=flags, payload=payload)
        packed_bytes = pkt.pack()

        if not is_critical:
            # Non-critical: Fire and forget
            self.sock.sendto(packed_bytes, dest_addr)
            return True

        # Critical: Stop-and-Wait ARQ
        attempts = 0
        self.sock.settimeout(self.timeout)

        while attempts < self.max_retries:
            attempts += 1
            self.sock.sendto(packed_bytes, dest_addr)
            
            start_time = time.time()
            while time.time() - start_time < self.timeout:
                try:
                    remaining = max(0.001, self.timeout - (time.time() - start_time))
                    self.sock.settimeout(remaining)
                    data, addr = self.sock.recvfrom(65535)
                    
                    if addr == dest_addr:
                        try:
                            recv_pkt = MicroQUICPacket.unpack(data)
                            if recv_pkt.is_valid and recv_pkt.is_ack and recv_pkt.ack == seq:
                                return True  # Successfully ACKed
                        except Exception:
                            pass
                except socket.timeout:
                    break
                except Exception:
                    break

        print(f"[MicroQUIC] Warning: Packet seq={seq} to {dest_addr} failed after {self.max_retries} retries.")
        return False

    def recv_packet(self, bufsize: int = 65535) -> Tuple[Optional[bytes], Optional[Tuple[str, int]], bool]:
        """
        Receives next packet. If critical, automatically sends ACK back to sender.
        Returns: (payload, sender_address, is_critical)
        """
        while True:
            try:
                data, addr = self.sock.recvfrom(bufsize)
                pkt = MicroQUICPacket.unpack(data)
                
                if not pkt.is_valid:
                    print(f"[MicroQUIC] Corrupted packet received from {addr}. Dropping.")
                    continue

                if pkt.is_ack:
                    # Ignore standalone ACKs in recv_packet loop
                    continue

                if pkt.is_critical:
                    # Send immediate per-packet ACK
                    ack_pkt = MicroQUICPacket(seq=0, ack=pkt.seq, flags=FLAG_ACK, payload=b'')
                    self.sock.sendto(ack_pkt.pack(), addr)

                return pkt.payload, addr, pkt.is_critical
            except socket.timeout:
                return None, None, False
            except Exception as e:
                return None, None, False

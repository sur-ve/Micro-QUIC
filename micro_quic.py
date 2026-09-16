import socket
import time
from typing import Tuple, Optional, Dict, List

from header import MicroQUICPacket, FLAG_CRITICAL, FLAG_ACK, FLAG_MORE_FRAGMENTS

DEFAULT_TIMEOUT = 0.1  # 100 ms retransmission timeout
DEFAULT_MAX_RETRIES = 5
MAX_PAYLOAD_SIZE = 1200  # MTU-friendly payload size


class MicroQUICSocket:
    def __init__(self, timeout: float = DEFAULT_TIMEOUT, max_retries: int = DEFAULT_MAX_RETRIES):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.timeout = timeout
        self.max_retries = max_retries
        self.seq_num = 1
        # Per-peer reassembly: addr -> {next_seq, parts, is_critical}
        self.received_buffers: Dict[Tuple[str, int], dict] = {}

    def bind(self, address: Tuple[str, int]):
        self.sock.bind(address)

    def settimeout(self, value: Optional[float]):
        self.sock.settimeout(value)

    def close(self):
        self.sock.close()

    def _chunk_payload(self, payload: bytes) -> List[bytes]:
        if not payload:
            return [b""]
        return [
            payload[i:i + MAX_PAYLOAD_SIZE]
            for i in range(0, len(payload), MAX_PAYLOAD_SIZE)
        ]

    def _send_one(
        self,
        payload: bytes,
        dest_addr: Tuple[str, int],
        is_critical: bool,
        more_fragments: bool,
    ) -> bool:
        """Send a single datagram-sized fragment. Critical fragments use Stop-and-Wait ARQ."""
        flags = 0
        if is_critical:
            flags |= FLAG_CRITICAL
        if more_fragments:
            flags |= FLAG_MORE_FRAGMENTS

        seq = self.seq_num
        self.seq_num += 1

        pkt = MicroQUICPacket(seq=seq, ack=0, flags=flags, payload=payload)
        packed_bytes = pkt.pack()

        if not is_critical:
            self.sock.sendto(packed_bytes, dest_addr)
            return True

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
                                return True
                        except Exception:
                            pass
                except socket.timeout:
                    break
                except Exception:
                    break

        print(f"[MicroQUIC] Warning: Packet seq={seq} to {dest_addr} failed after {self.max_retries} retries.")
        return False

    def send_packet(self, payload: bytes, dest_addr: Tuple[str, int], is_critical: bool = False) -> bool:
        """
        Sends a logical payload to the destination, fragmenting when needed.
        If is_critical=True, each fragment waits for ACK and is retransmitted on timeout.
        Returns True if all fragments were sent successfully (critical: all ACKed).
        """
        chunks = self._chunk_payload(payload)
        for i, chunk in enumerate(chunks):
            more = i < len(chunks) - 1
            ok = self._send_one(chunk, dest_addr, is_critical, more_fragments=more)
            if not ok:
                return False
        return True

    def recv_packet(self, bufsize: int = 65535) -> Tuple[Optional[bytes], Optional[Tuple[str, int]], bool]:
        """
        Receives the next complete logical message (reassembling fragments).
        Critical fragments are ACKed immediately.
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
                    continue

                if pkt.is_critical:
                    ack_pkt = MicroQUICPacket(seq=0, ack=pkt.seq, flags=FLAG_ACK, payload=b"")
                    self.sock.sendto(ack_pkt.pack(), addr)

                assembled = self._ingest_fragment(addr, pkt)
                if assembled is None:
                    continue
                payload, is_critical = assembled
                return payload, addr, is_critical

            except socket.timeout:
                return None, None, False
            except Exception:
                return None, None, False

    def _ingest_fragment(
        self, addr: Tuple[str, int], pkt: MicroQUICPacket
    ) -> Optional[Tuple[bytes, bool]]:
        """
        Feed one fragment into the reassembly buffer.
        Returns (full_payload, is_critical) when a message is complete, else None.
        """
        buf = self.received_buffers.get(addr)

        # Single-packet message (no open assembly, no more fragments)
        if not pkt.has_more_fragments and buf is None:
            return pkt.payload, pkt.is_critical

        if buf is None:
            # Start a new multi-fragment message
            self.received_buffers[addr] = {
                "next_seq": pkt.seq + 1,
                "parts": [pkt.payload],
                "is_critical": pkt.is_critical,
            }
            return None

        # Gap / out-of-order: abandon previous assembly and restart if this looks like a new start
        if pkt.seq != buf["next_seq"]:
            if pkt.has_more_fragments:
                self.received_buffers[addr] = {
                    "next_seq": pkt.seq + 1,
                    "parts": [pkt.payload],
                    "is_critical": pkt.is_critical,
                }
                return None
            del self.received_buffers[addr]
            return pkt.payload, pkt.is_critical

        buf["parts"].append(pkt.payload)
        buf["next_seq"] = pkt.seq + 1
        buf["is_critical"] = buf["is_critical"] or pkt.is_critical

        if pkt.has_more_fragments:
            return None

        payload = b"".join(buf["parts"])
        is_critical = buf["is_critical"]
        del self.received_buffers[addr]
        return payload, is_critical

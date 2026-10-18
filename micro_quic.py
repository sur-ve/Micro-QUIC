"""microQUIC engine — lightweight QUIC-inspired UDP transport with:
  - Selective Repeat Sliding Window ARQ for critical packets
  - Out-of-order fragment reassembly
  - Incomplete-frame timeout handling
  - Dynamic RTT / timeout estimation (Jacobson/Karels + Karn's algorithm)
  - Congestion / rate control and pacing
  - Multi-stream support (up to 16 concurrent logical streams)
  - Authenticated payload encryption (PSK)
  - Optional ML-based criticality classification
"""
import socket
import time
from typing import Tuple, Optional, Dict, List, Any

from header import (
    MicroQUICPacket,
    encode_flags,
    encrypt_payload,
    decrypt_payload,
    FLAG_ACK,
    FLAG_CRITICAL,
    FLAG_MORE_FRAGMENTS,
    FLAG_ENCRYPTED,
)

DEFAULT_TIMEOUT = 0.1  # 100 ms initial retransmission timeout
DEFAULT_MAX_RETRIES = 5
MAX_PAYLOAD_SIZE = 1200  # MTU-friendly payload size (IPv4 UDP max payload without fragmentation)


class RecvResult(tuple):
    """Result tuple (payload, addr, is_critical) with optional .stream_id attribute.

    Unpacks as 3 elements (payload, addr, is_critical) for 100% backward
    compatibility, while also exposing .stream_id, .payload, .addr, .is_critical.
    """

    def __new__(
        cls,
        payload: Optional[bytes],
        addr: Optional[Tuple[str, int]],
        is_critical: bool,
        stream_id: int = 0,
    ):
        obj = super().__new__(cls, (payload, addr, is_critical))
        obj.payload = payload
        obj.addr = addr
        obj.is_critical = is_critical
        obj.stream_id = stream_id
        return obj


class MicroQUICSocket:
    """UDP socket with selective reliability, sliding window ARQ, dynamic RTT,
    and optional ML criticality classification.

    Parameters
    ----------
    timeout : float
        Initial per-packet retransmission timeout (seconds) for critical packets.
    max_retries : int
        Maximum retransmission attempts for critical fragments before giving up.
    use_classifier : bool
        When True, ``send_frame()`` uses the trained ML pipeline
        (``classifier.predict_criticality``) to decide whether each
        video frame payload is critical.
    window_size : int
        Sliding window size (max unACKed critical fragments in-flight). Default 16.
    fragment_timeout : float
        Timeout (seconds) for incomplete multi-fragment message reassembly. Default 0.5s.
    rate_limit_kbps : float | None
        Optional transmission rate limit in kilobits per second.
    psk : bytes | str | None
        Optional Pre-Shared Key for authenticated AES-CTR/HMAC encryption.
    """

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        use_classifier: bool = False,
        window_size: int = 16,
        fragment_timeout: float = 1.5,
        rate_limit_kbps: Optional[float] = None,
        psk: Optional[bytes | str] = None,
    ):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 2 * 1024 * 1024)
        except Exception:
            pass

        self.initial_timeout = timeout
        self.max_retries = max_retries
        self.use_classifier = use_classifier
        self.window_size = max(1, window_size)
        self.fragment_timeout = fragment_timeout
        self.rate_limit_kbps = rate_limit_kbps
        self.psk = psk.encode() if isinstance(psk, str) else psk

        self.seq_num = 1

        # Dynamic RTT estimation (Jacobson/Karels + Karn's algorithm)
        self.srtt: Optional[float] = None
        self.rttvar: float = timeout / 2.0
        self.rto: float = timeout
        self.min_rto: float = 0.005  # 5 ms minimum RTO
        self.max_rto: float = 2.0    # 2.0 s maximum RTO

        # Out-of-order reassembly buffers: (addr, stream_id) -> buffer state
        self.received_buffers: Dict[Tuple[Tuple[str, int], int], dict] = {}

        # Lazily import classifier
        self._classifier_fn = None
        if use_classifier:
            self._load_classifier()

    # ------------------------------------------------------------------
    # Classifier integration
    # ------------------------------------------------------------------

    def _load_classifier(self) -> bool:
        """Import and cache the predict_criticality function."""
        try:
            from classifier import predict_criticality  # noqa: F401
            self._classifier_fn = predict_criticality
            return True
        except Exception as exc:
            print(f"[MicroQUIC] Classifier unavailable: {exc}")
            self._classifier_fn = None
            return False

    def reload_classifier(self) -> bool:
        """Reload the ML pipeline (e.g. after retraining)."""
        return self._load_classifier()

    # ------------------------------------------------------------------
    # Socket helpers
    # ------------------------------------------------------------------

    def bind(self, address: Tuple[str, int]):
        self.sock.bind(address)

    def settimeout(self, value: Optional[float]):
        self.sock.settimeout(value)

    def close(self):
        self.sock.close()

    # ------------------------------------------------------------------
    # Dynamic RTT & Rate Limiting
    # ------------------------------------------------------------------

    def _update_rtt(self, sample_rtt: float) -> None:
        """Update RTT and RTO estimates using Karn's algorithm & Jacobson's formula."""
        if self.srtt is None:
            self.srtt = sample_rtt
            self.rttvar = sample_rtt / 2.0
        else:
            self.rttvar = 0.75 * self.rttvar + 0.25 * abs(self.srtt - sample_rtt)
            self.srtt = 0.875 * self.srtt + 0.125 * sample_rtt
        self.rto = min(self.max_rto, max(self.min_rto, self.srtt + max(0.001, 4.0 * self.rttvar)))

    def _apply_rate_limit(self, bytes_sent: int) -> None:
        """Apply pacing/rate-limit delay if rate_limit_kbps is configured."""
        if self.rate_limit_kbps and self.rate_limit_kbps > 0:
            delay = bytes_sent / (self.rate_limit_kbps * 125.0)  # 1 kbps = 125 bytes/sec
            time.sleep(delay)

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def _chunk_payload(self, payload: bytes) -> List[bytes]:
        if not payload:
            return [b""]
        return [
            payload[i:i + MAX_PAYLOAD_SIZE]
            for i in range(0, len(payload), MAX_PAYLOAD_SIZE)
        ]

    def send_packet(
        self,
        payload: bytes,
        dest_addr: Tuple[str, int],
        is_critical: bool = False,
        stream_id: int = 0,
    ) -> bool:
        """Send a logical payload to dest_addr, fragmenting when needed.

        - If is_critical=False: fire-and-forget fragments with rate pacing.
        - If is_critical=True: Sliding Window Selective Repeat ARQ with dynamic RTT.
        """
        chunks = self._chunk_payload(payload)
        num_chunks = len(chunks)
        is_frag = (num_chunks > 1)

        if not is_critical:
            start_seq = self.seq_num
            for i, chunk in enumerate(chunks):
                more = (i < num_chunks - 1)
                body = encrypt_payload(chunk, self.psk) if self.psk else chunk
                flags = encode_flags(
                    critical=False,
                    more_fragments=more,
                    fragmented=is_frag,
                    encrypted=bool(self.psk),
                    stream_id=stream_id,
                )
                seq = self.seq_num
                self.seq_num += 1

                pkt = MicroQUICPacket(seq=seq, ack=start_seq, flags=flags, payload=body)
                packed = pkt.pack()
                self.sock.sendto(packed, dest_addr)
                self._apply_rate_limit(len(packed))
            return True

        # Critical delivery: Sliding Window Selective Repeat ARQ
        fragments_to_send: List[Tuple[int, bytes]] = []
        start_seq = self.seq_num
        for i, chunk in enumerate(chunks):
            more = (i < num_chunks - 1)
            body = encrypt_payload(chunk, self.psk) if self.psk else chunk
            flags = encode_flags(
                critical=True,
                more_fragments=more,
                fragmented=is_frag,
                encrypted=bool(self.psk),
                stream_id=stream_id,
            )
            seq = self.seq_num
            self.seq_num += 1

            pkt = MicroQUICPacket(seq=seq, ack=start_seq, flags=flags, payload=body)
            fragments_to_send.append((seq, pkt.pack()))

        in_flight: Dict[int, dict] = {}
        frag_idx = 0

        while frag_idx < len(fragments_to_send) or in_flight:
            # Send up to window_size fragments
            while frag_idx < len(fragments_to_send) and len(in_flight) < self.window_size:
                seq, packed_bytes = fragments_to_send[frag_idx]
                frag_idx += 1
                self.sock.sendto(packed_bytes, dest_addr)
                now = time.perf_counter()
                in_flight[seq] = {
                    "bytes": packed_bytes,
                    "send_time": now,
                    "retries": 0,
                }
                self._apply_rate_limit(len(packed_bytes))

            # Wait for ACKs or oldest fragment timeout
            now = time.perf_counter()
            if in_flight:
                oldest_send = min(info["send_time"] for info in in_flight.values())
                wait_time = max(0.001, self.rto - (now - oldest_send))
            else:
                wait_time = self.rto

            try:
                self.sock.settimeout(wait_time)
                data, addr = self.sock.recvfrom(65535)
                self._process_ack(data, addr, dest_addr, in_flight)

                # Batch drain any additional queued ACKs immediately
                self.sock.setblocking(False)
                try:
                    while in_flight:
                        try:
                            data, addr = self.sock.recvfrom(65535)
                            self._process_ack(data, addr, dest_addr, in_flight)
                        except (BlockingIOError, socket.error):
                            break
                finally:
                    self.sock.setblocking(True)
            except socket.timeout:
                pass
            except Exception:
                pass

            # Check timeouts for in-flight fragments (Selective Repeat)
            now = time.perf_counter()
            for seq, info in list(in_flight.items()):
                if now - info["send_time"] >= self.rto:
                    if info["retries"] < self.max_retries:
                        self.sock.sendto(info["bytes"], dest_addr)
                        info["retries"] += 1
                        info["send_time"] = now
                        self.rto = min(self.max_rto, self.rto * 1.5)  # Exponential backoff
                        self._apply_rate_limit(len(info["bytes"]))
                    else:
                        print(
                            f"[MicroQUIC] Warning: Packet seq={seq} to {dest_addr} "
                            f"failed after {self.max_retries} retries."
                        )
                        return False

        return True

    def _process_ack(
        self,
        data: bytes,
        addr: Tuple[str, int],
        dest_addr: Tuple[str, int],
        in_flight: Dict[int, dict],
    ) -> None:
        """Process an incoming ACK datagram and update RTT."""
        if addr[1] == dest_addr[1]:
            try:
                recv_pkt = MicroQUICPacket.unpack(data)
                if recv_pkt.is_valid and recv_pkt.is_ack and recv_pkt.ack in in_flight:
                    info = in_flight.pop(recv_pkt.ack)
                    if info["retries"] == 0:
                        sample_rtt = max(0.0001, time.perf_counter() - info["send_time"])
                        self._update_rtt(sample_rtt)
            except Exception:
                pass

    def send_frame(
        self,
        frame_bytes: bytes,
        dest_addr: Tuple[str, int],
        features: Optional[Tuple[float, int]] = None,
        is_critical: Optional[bool] = None,
        stream_id: int = 0,
    ) -> bool:
        """Send an encoded video frame, using ML classification to set criticality."""
        if is_critical is not None:
            crit = is_critical
        elif self.use_classifier and features is not None:
            if self._classifier_fn is None:
                self._load_classifier()
            if self._classifier_fn is not None:
                try:
                    crit = self._classifier_fn(features)
                except Exception as exc:
                    print(f"[MicroQUIC] Classifier prediction failed: {exc}. Treating as non-critical.")
                    crit = False
            else:
                crit = False
        else:
            crit = False

        return self.send_packet(frame_bytes, dest_addr, is_critical=crit, stream_id=stream_id)

    # ------------------------------------------------------------------
    # Receiving & Reassembly
    # ------------------------------------------------------------------

    def recv_packet(
        self,
        bufsize: int = 65535,
        include_stream_id: bool = False,
    ) -> Any:
        """Receive the next complete logical message (reassembling fragments).

        Critical fragments are ACKed immediately. Out-of-order fragments
        are buffered and reassembled upon arrival.

        Returns
        -------
        RecvResult or 4-tuple:
            Unpacks as ``(payload, addr, is_critical)`` by default.
            If ``include_stream_id=True``, returns ``(payload, addr, is_critical, stream_id)``.
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

                # Immediately ACK critical fragments
                if pkt.is_critical:
                    ack_flags = encode_flags(ack=True, stream_id=pkt.stream_id)
                    ack_pkt = MicroQUICPacket(seq=0, ack=pkt.seq, flags=ack_flags, payload=b"")
                    self.sock.sendto(ack_pkt.pack(), addr)

                # Decrypt payload if encrypted
                payload = pkt.payload
                if pkt.is_encrypted:
                    if not self.psk:
                        print(f"[MicroQUIC] Dropping encrypted packet from {addr}: no PSK configured.")
                        continue
                    try:
                        payload = decrypt_payload(payload, self.psk)
                    except Exception as exc:
                        print(f"[MicroQUIC] Decryption/authentication failed from {addr}: {exc}")
                        continue

                assembled = self._ingest_fragment(addr, pkt, payload)
                if assembled is None:
                    continue

                full_payload, is_critical, stream_id = assembled
                if include_stream_id:
                    return full_payload, addr, is_critical, stream_id
                return RecvResult(full_payload, addr, is_critical, stream_id=stream_id)

            except socket.timeout:
                if include_stream_id:
                    return None, None, False, 0
                return RecvResult(None, None, False, 0)
            except Exception:
                if include_stream_id:
                    return None, None, False, 0
                return RecvResult(None, None, False, 0)

    def _ingest_fragment(
        self,
        addr: Tuple[str, int],
        pkt: MicroQUICPacket,
        payload: bytes,
    ) -> Optional[Tuple[bytes, bool, int]]:
        """Feed one fragment into the reassembly buffer for (addr, stream_id).

        Returns ``(full_payload, is_critical, stream_id)`` when a message is complete, else None.
        """
        key = (addr, pkt.stream_id)
        now = time.time()

        if key not in self.received_buffers:
            self.received_buffers[key] = {
                "fragments": {},
                "first_seen_time": now,
                "last_delivered_seq": 0,
            }

        buf = self.received_buffers[key]

        # Handle sender restart (sequence number reset to 1)
        if pkt.seq <= 2 and buf["last_delivered_seq"] > 10:
            buf["fragments"].clear()
            buf["last_delivered_seq"] = 0
            buf["first_seen_time"] = now
        elif pkt.seq <= buf["last_delivered_seq"]:
            # Stale / duplicate packet that was already delivered
            return None

        # Incomplete-frame timeout check: drop stalled assembly if deadline exceeded
        if now - buf["first_seen_time"] > self.fragment_timeout and buf["fragments"]:
            # Drop stalled fragments and advance last_delivered_seq past the gap
            max_stalled = max(buf["fragments"].keys())
            buf["fragments"].clear()
            buf["last_delivered_seq"] = max_stalled
            buf["first_seen_time"] = now

        # Standalone (unfragmented) message: deliver immediately without buffering
        if not pkt.is_fragmented:
            buf["last_delivered_seq"] = max(buf["last_delivered_seq"], pkt.seq)
            buf["first_seen_time"] = now
            return payload, pkt.is_critical, pkt.stream_id

        # Buffer the incoming fragment: (payload, is_critical, has_more, start_seq)
        buf["fragments"][pkt.seq] = (payload, pkt.is_critical, pkt.has_more_fragments, pkt.ack)

        # Check if any complete message is ready in buf["fragments"]
        # Candidate message ends have has_more_fragments == False
        end_seqs = sorted(s for s, frag in buf["fragments"].items() if not frag[2])

        for s_end in end_seqs:
            frag_end = buf["fragments"][s_end]
            msg_start = frag_end[3] if len(frag_end) > 3 else 0
            if msg_start > 0:
                s_start = msg_start
                is_valid_start = True
            else:
                # Fallback to trace backwards for packets without start_seq
                curr = s_end - 1
                while curr in buf["fragments"] and buf["fragments"][curr][2]:
                    curr -= 1

                s_start = curr + 1

                # Validate that s_start is a legitimate message boundary
                is_valid_start = (
                    s_start == 1
                    or s_start - 1 == buf["last_delivered_seq"]
                    or (s_start - 1 in buf["fragments"] and not buf["fragments"][s_start - 1][2])
                )

            if is_valid_start:
                needed = list(range(s_start, s_end + 1))
                if all(s in buf["fragments"] for s in needed):
                    full_payload = b"".join(buf["fragments"][s][0] for s in needed)
                    is_critical = any(buf["fragments"][s][1] for s in needed)
                    # Purge this message and any older stale fragments
                    stale_seqs = [s_seq for s_seq in buf["fragments"] if s_seq <= s_end]
                    for s_seq in stale_seqs:
                        del buf["fragments"][s_seq]
                    buf["last_delivered_seq"] = s_end
                    buf["first_seen_time"] = now
                    return full_payload, is_critical, pkt.stream_id

        return None

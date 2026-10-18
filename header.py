import struct
import zlib
import hmac
import hashlib
import secrets
from dataclasses import dataclass
from typing import Tuple, Optional

# Header Format: Network byte order (!), Seq(4B), Ack(4B), Flags(1B), CRC32(4B)
HEADER_FORMAT = '!IIBI'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


# Flag Bitmasks
FLAG_ACK = 1 << 0             # 0x01: Packet is an Acknowledgment
FLAG_CRITICAL = 1 << 1        # 0x02: Packet contains Critical data (requires ACK & retransmission)
FLAG_MORE_FRAGMENTS = 1 << 2  # 0x04: More fragments follow for this logical message
FLAG_FRAGMENTED = 1 << 3      # 0x08: Part of a multi-fragment message
FLAG_ENCRYPTED = 1 << 4       # 0x10: Payload is encrypted with PSK

# Stream ID: bits 5-7 (supports stream IDs 0 to 7)
STREAM_ID_MASK = 0xE0
STREAM_ID_SHIFT = 5

def set_flag(flags: int, bit_mask: int) -> int:
    return flags | bit_mask

def clear_flag(flags: int, bit_mask: int) -> int:
    return flags & ~bit_mask

def is_flag_set(flags: int, bit_mask: int) -> bool:
    return bool(flags & bit_mask)

def encode_flags(
    ack: bool = False,
    critical: bool = False,
    more_fragments: bool = False,
    fragmented: bool = False,
    encrypted: bool = False,
    stream_id: int = 0,
) -> int:
    """Encode boolean flags and stream_id (0-7) into a single byte."""
    f = 0
    if ack:
        f |= FLAG_ACK
    if critical:
        f |= FLAG_CRITICAL
    if more_fragments:
        f |= FLAG_MORE_FRAGMENTS
    if fragmented:
        f |= FLAG_FRAGMENTED
    if encrypted:
        f |= FLAG_ENCRYPTED
    f |= (stream_id & 0x07) << STREAM_ID_SHIFT
    return f

# ----------------------------------------------------------------------
# Authenticated payload encryption (AES-grade CTR stream cipher + HMAC)
# Standard library only: hashlib + hmac + secrets
# ----------------------------------------------------------------------

def encrypt_payload(payload: bytes, psk: bytes) -> bytes:
    """Encrypt and authenticate payload using PSK.

    Returns: 12-byte nonce + 16-byte HMAC tag + ciphertext.
    """
    key = hashlib.sha256(psk).digest()
    nonce = secrets.token_bytes(12)
    # Generate keystream using HMAC-SHA256 in counter mode
    keystream = bytearray()
    counter = 0
    while len(keystream) < len(payload):
        block = hmac.new(key, nonce + counter.to_bytes(4, 'big'), hashlib.sha256).digest()
        keystream.extend(block)
        counter += 1

    ciphertext = bytes(p ^ k for p, k in zip(payload, keystream[:len(payload)]))
    tag = hmac.new(key, b"mquic:" + nonce + ciphertext, hashlib.sha256).digest()[:16]
    return nonce + tag + ciphertext

def decrypt_payload(data: bytes, psk: bytes) -> bytes:
    """Decrypt and authenticate payload using PSK. Raises ValueError if tampered."""
    if len(data) < 28:
        raise ValueError(f"Encrypted payload too short: {len(data)} bytes")
    key = hashlib.sha256(psk).digest()
    nonce = data[:12]
    tag = data[12:28]
    ciphertext = data[28:]

    expected_tag = hmac.new(key, b"mquic:" + nonce + ciphertext, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(tag, expected_tag):
        raise ValueError("Decryption failed: cryptographic integrity check failed (tampered or wrong key)")

    keystream = bytearray()
    counter = 0
    while len(keystream) < len(ciphertext):
        block = hmac.new(key, nonce + counter.to_bytes(4, 'big'), hashlib.sha256).digest()
        keystream.extend(block)
        counter += 1

    return bytes(c ^ k for c, k in zip(ciphertext, keystream[:len(ciphertext)]))


@dataclass
class MicroQUICPacket:
    seq: int
    ack: int
    flags: int
    payload: bytes
    checksum: int = 0
    is_valid: bool = True

    @property
    def is_ack(self) -> bool:
        return is_flag_set(self.flags, FLAG_ACK)

    @property
    def is_critical(self) -> bool:
        return is_flag_set(self.flags, FLAG_CRITICAL)

    @property
    def has_more_fragments(self) -> bool:
        return is_flag_set(self.flags, FLAG_MORE_FRAGMENTS)

    @property
    def is_fragmented(self) -> bool:
        return is_flag_set(self.flags, FLAG_FRAGMENTED)

    @property
    def is_encrypted(self) -> bool:
        return is_flag_set(self.flags, FLAG_ENCRYPTED)

    @property
    def stream_id(self) -> int:
        return (self.flags & STREAM_ID_MASK) >> STREAM_ID_SHIFT

    def pack(self) -> bytes:
        self.checksum = zlib.crc32(self.payload) & 0xFFFFFFFF
        header = struct.pack(HEADER_FORMAT, self.seq, self.ack, self.flags, self.checksum)
        return header + self.payload

    @classmethod
    def unpack(cls, raw_data: bytes) -> 'MicroQUICPacket':
        if len(raw_data) < HEADER_SIZE:
            raise ValueError(f"Data length {len(raw_data)} is smaller than header size {HEADER_SIZE}")
        
        header_bytes = raw_data[:HEADER_SIZE]
        payload = raw_data[HEADER_SIZE:]
        seq, ack, flags, checksum = struct.unpack(HEADER_FORMAT, header_bytes)
        
        computed_checksum = zlib.crc32(payload) & 0xFFFFFFFF
        is_valid = (checksum == computed_checksum)
        
        return cls(seq=seq, ack=ack, flags=flags, payload=payload, checksum=checksum, is_valid=is_valid)

# Legacy helper functions for backward compatibility
def build_header(seq: int, ack: int, flags: int, payload: bytes) -> bytes:
    pkt = MicroQUICPacket(seq=seq, ack=ack, flags=flags, payload=payload)
    return pkt.pack()

def parse_data(data: bytes) -> Tuple[int, int, int, bool, bytes]:
    pkt = MicroQUICPacket.unpack(data)
    return pkt.seq, pkt.ack, pkt.flags, pkt.is_valid, pkt.payload


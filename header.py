import struct
import zlib
from dataclasses import dataclass
from typing import Tuple

# Header Format: Network byte order (!), Seq(4B), Ack(4B), Flags(1B), CRC32(4B)
HEADER_FORMAT = '!IIBI'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

# Flag Bitmasks
FLAG_ACK = 1 << 0             # 0x01: Packet is an Acknowledgment
FLAG_CRITICAL = 1 << 1        # 0x02: Packet contains Critical data (requires ACK & retransmission)
FLAG_MORE_FRAGMENTS = 1 << 2  # 0x04: More fragments follow for this logical message

def set_flag(flags: int, bit_mask: int) -> int:
    return flags | bit_mask

def clear_flag(flags: int, bit_mask: int) -> int:
    return flags & ~bit_mask

def is_flag_set(flags: int, bit_mask: int) -> bool:
    return bool(flags & bit_mask)

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


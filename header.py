import struct
from typing import Any
import zlib

# Defining the structure of the header
format = '!IIBI'
size = struct.calcsize(format)
'''
Header Structure:
    1. Sequence Number - I(integer)
    2. Acknowledgement Number(Per packet acknowledgement) - I
    3. Flags [DATA_CRITICAL = 0, DATA_NONCRITICAL = 1, ACK = 2] - B(byte)
    4. CRC32 - I
'''

# packing data into struct
def build_header(seq: int, ack: int, flags: int, payload: bytes) -> bytes:
    checksum = zlib.crc32(payload)
    header = struct.pack(format, seq, ack, flags, checksum)
    return header + payload # returning new data packet with added header

# parses the data and seperates header from payload
def parse_data(data: bytes) -> tuple[int, int, int, bool, bytes]:
    header = data[:size]
    payload = data[size:]
    seq, ack, flags, checksum = struct.unpack(format, header)
    is_valid = checksum == zlib.crc32(payload)
    return seq, ack, flags, is_valid, payload


# flag commands
def set_flag(flags: int, bit: int) -> int:
    return flags | (1 << bit)

def clear_flag(flags: int, bit: int) -> int:
    return flags & ~(1 << bit)

def is_flag_set(flags: int, bit: int) -> int:
    return flags ^ ~(1 << bit)

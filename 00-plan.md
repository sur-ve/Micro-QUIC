# Micro-QUIC - Development Roadmap & Plan

## Project Overview
Micro-QUIC is a custom transport layer protocol built on top of UDP. It implements selective retransmission of critical data packets, eliminating TCP handshaking and cumulative ACK overhead while preserving reliability for high-priority payloads in lossy network environments.

---

## Architecture & Protocol Specifications

### 1. Packet Header Layout (13 Bytes)
- **Sequence Number**: 32-bit Integer (`4 Bytes`)
- **Acknowledgment Number**: 32-bit Integer (`4 Bytes`)
- **Flags**: 8-bit Unsigned Byte (`1 Byte`)
  - `Bit 0 (0x01)`: `ACK` flag
  - `Bit 1 (0x02)`: `CRITICAL` flag
  - `Bit 2 (0x04)`: `MORE_FRAGMENTS` flag
  - `Bits 3-7`: Reserved for future expansion
- **CRC-32 Checksum**: 32-bit Integer (`4 Bytes`)

### 2. Micro-QUIC Transmission Rules
- **Non-Critical Packets (`CRITICAL` flag = 0)**: Sent over UDP with sequence numbers and CRC verification. No ACKs requested, no retransmissions upon loss.
- **Critical Packets (`CRITICAL` flag = 1)**: Sent over UDP. Receiver must immediately reply with an ACK packet (`ACK` flag = 1, `ack_num` = `seq_num`). Sender uses Stop-and-Wait / Sliding Window with timer-based ARQ retransmission.
- **Fragmentation**: Large payloads are split into MTU-friendly chunks (`MORE_FRAGMENTS` set until final chunk).

---

## Phase-by-Phase Plan

### Phase 1: Core Protocol & Header Module (`header.py`)
- [ ] Fix bitwise flag utilities (`is_flag_set` bug in helper functions).
- [ ] Define clean flag constants (`FLAG_ACK`, `FLAG_CRITICAL`, `FLAG_MORE_FRAGMENTS`).
- [ ] Implement robust `MicroQUICPacket` data structure for header packing, parsing, validation, and error reporting.

### Phase 2: Micro-QUIC Socket & Protocol Engine (`micro_quic.py`)
- [ ] Implement `MicroQUICSocket` class abstracting UDP sockets.
- [ ] Add ARQ (Automatic Repeat Request) retransmission logic with timeout for critical packets.
- [ ] Add selective ACK generation and tracking for critical packets.
- [ ] Support payload fragmentation & packet reassembly for transfers larger than MTU.
- [ ] Implement out-of-order packet resequencing.

### Phase 3: Simulated Lossy Network Channel (`channel.py`)
- [ ] Build a network simulator proxy/channel to inject controlled packet loss, corruption, delay, and reordering.
- [ ] Configure adjustable loss rate parameters (e.g., 0% to 30% loss rate).

### Phase 4: Benchmarking Suite & TCP/UDP Comparison (`benchmark.py`)
- [ ] Implement automated performance benchmarks comparing **TCP**, **Standard UDP**, and **Micro-QUIC**.
- [ ] Measure key metrics:
  - Throughput (KB/s)
  - Packet delivery ratio for critical vs non-critical data
  - Average latency and completion time in lossy conditions
- [ ] Generate comparative summary reports and charts.

### Phase 5: High-Level Client & Server Demonstrations (`sender.py` & `receiver.py`)
- [ ] Build demo application (e.g., streaming telemetry with critical control frames or live video/audio metadata).
- [ ] CLI arguments for adjusting critical packet ratios and network parameters.

---

## Project Directory Map
```
Micro-QUIC/
├── README.md              # Project description and spec
├── 00-plan.md             # Development roadmap & execution plan
├── header.py              # Header serialization & flag utilities
├── micro_quic.py          # MicroQUIC protocol engine (Sender/Receiver classes)
├── channel.py             # Simulated lossy & delayed network channel
├── benchmark.py           # Benchmarking & performance evaluation script
├── sender.py              # Micro-QUIC demo client
├── receiver.py            # Micro-QUIC demo server
├── tcp_sender.py          # Baseline TCP sender
├── tcp_receiver.py        # Baseline TCP receiver
├── udp_sender.py          # Baseline UDP sender
└── udp_receiver.py        # Baseline UDP receiver
```

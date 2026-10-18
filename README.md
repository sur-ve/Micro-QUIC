# Micro-QUIC — Selective Retransmission over UDP

**Micro-QUIC** is an ultra-lightweight, QUIC-inspired transport protocol engineered over UDP. It provides **selective reliability** powered by an embedded machine learning criticality classifier. 

In lossy environments, standard TCP retransmits *every* dropped packet with heavy head-of-line blocking and multi-way handshakes, while standard UDP silently discards packets without any recovery. Micro-QUIC bridges this gap: it guarantees reliable delivery for **critical packets** (via Selective Repeat ARQ) while allowing **non-critical packets** to be safely dropped, achieving near-UDP speed with TCP-grade reliability on essential data.

---

## Key Features

- **Selective Repeat Sliding Window ARQ** — High-throughput parallel fragment transmission (`window_size=16`) replacing per-fragment Stop-and-Wait.
- **Dynamic RTT & Adaptive Timeout** — Jacobson/Karels RTT estimation combined with Karn's algorithm (excluding retransmitted samples) and exponential backoff.
- **Robust Out-of-Order Reassembly** — Backward-contiguous fragment reassembly tolerates packet reordering across frames.
- **Incomplete-Frame Timeout** — Automated deadline expiration (`fragment_timeout=0.5s`) purges stalled buffers without stalling subsequent frames.
- **ML Criticality Classification** — DecisionTree pipeline classifying frames into critical vs normal based on motion diff and compressed size.
- **Multi-Stream Multiplexing** — Supports up to 8 independent logical streams (`--stream-id 0..7`) over a single UDP socket without crosstalk.
- **Authenticated Encryption (PSK)** — Zero-dependency AES-grade CTR stream keystream + HMAC-SHA256 authenticated encryption (`--psk`).
- **Real-Time Frame Pacing & Priority Drop** — Paces sends to video FPS and skips non-critical frames when critical backlog builds up.
- **Webcam & Headless Recording** — Live camera capture mode (`--camera 0`), headless mode (`--no-display`), and stream recording (`--save out.avi`).
- **Comprehensive Benchmarks & Dashboard** — Automated side-by-side performance comparison against TCP and UDP with live ASCII dashboard.

---

## Protocol Specification

### The 13-Byte Micro-QUIC Header

Micro-QUIC encapsulates payloads in a compact 13-byte header formatted in network byte order (`!IIBI`):

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                        Sequence Number                        |  4 Bytes
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                     Acknowledgment Number                     |  4 Bytes
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|     Flags     |                                               |  1 Byte
+-+-+-+-+-+-+-+-+                                               |
|                            CRC-32                             |  4 Bytes
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                            Payload                            |  Variable
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### Flags Field Breakdown (1 Byte)

| Bit | Mask | Flag | Description |
| :---: | :---: | :--- | :--- |
| **0** | `0x01` | `FLAG_ACK` | Packet is an acknowledgment. |
| **1** | `0x02` | `FLAG_CRITICAL` | Requires reliable Selective Repeat ARQ delivery. |
| **2** | `0x04` | `FLAG_MORE_FRAGMENTS` | Set if more fragments follow in the logical message. |
| **3** | `0x08` | `FLAG_FRAGMENTED` | Set on all fragments of a multi-fragment message. |
| **4** | `0x10` | `FLAG_ENCRYPTED` | Payload is encrypted with PSK. |
| **5–7**| `0xE0` | `STREAM_ID` | 3-bit Stream Identifier (0 to 7). |

---

## Project Layout

| File | Description |
| :--- | :--- |
| `header.py` | 13-byte header pack/unpack, CRC-32 validation, flag encoding, and PSK authenticated encryption |
| `micro_quic.py` | Core socket engine: Selective Repeat ARQ, dynamic RTT, reassembly, rate limiting, and ML hook |
| `channel.py` | Local proxy simulating configurable packet loss, delay, and data corruption |
| `features.py` | Per-frame feature extraction: mean grayscale difference, encoded size, and multi-codec support |
| `train_classifier.py` | Multi-video training pipeline supporting KMeans, motion-threshold, and supervised labels |
| `classifier.py` | Lazy-loading wrapper for `criticality_model.pkl` with dynamic reload support |
| `video_sender.py` | Video stream sender with webcam capture, FPS pacing, priority drop, PSK, and rate control |
| `video_receiver.py` | Video receiver with headless mode, stream saving (`.avi`), frame dumping, and metrics |
| `sender.py` | Command-line telemetry demo for synthetic traffic |
| `benchmark.py` | Comparative benchmark suite (TCP vs UDP vs Micro-QUIC) with visual ASCII dashboard |
| `test_smoke.py` | Comprehensive headless CI smoke test suite (crypto, protocol, ARQ, reassembly, video stream) |
| `test_efficiency_and_e2e.py` | End-to-end efficiency and scalability sweep suite comparing Micro-QUIC vs TCP across loss rates and payload sizes |
| `02-todo-features.md`| Completed checklist of all roadmap features |

---

## Installation & Setup

Ensure Python 3.10+ is installed:

```bash
# Clone the repository
cd microQUIC

# Set up virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## Quick Verification: Smoke Test & Benchmarks

### 1. Run Headless CI Smoke Test
Verifies crypto, packet packing, multi-stream multiplexing, Selective Repeat ARQ under loss, and video streaming without requiring a GUI:

```bash
python test_smoke.py
```

### 2. Run Complete End-to-End & Efficiency Sweep Suite
Executes all 7 testing stages including in-depth efficiency and goodput sweeps against TCP across loss rates (5%, 15%, 25%) and payload sizes (64B, 500B, 2.5KB multi-fragment):

```bash
python test_efficiency_and_e2e.py
```

### 3. Run Comparative Benchmark Suite
Runs test packets across TCP, UDP, and Micro-QUIC under simulated packet loss and outputs a live visual comparison:

```bash
# Standard benchmark with synthetic packets (default: 100 packets, 15% loss)
python benchmark.py --packets 100 --loss-rate 0.15

# ML model-driven classification benchmark (dynamically classifies features via decision tree)
python benchmark.py --use-model --packets 100 --loss-rate 0.15

# Real video frame benchmark (extracts actual frames and runs ML classifier)
python benchmark.py --video data/testVideo.mp4 --packets 20 --loss-rate 0.15

# Configurable critical ratio benchmark (e.g. 35% critical packets)
python benchmark.py --critical-ratio 0.35 --packets 100 --loss-rate 0.15
```

**Example Dashboard Output:**
```
==================================================================================================
             MICRO-QUIC PERFORMANCE & RELIABILITY DASHBOARD (Loss Rate: 15%)
  Workload: Simulated frame features [ML Decision Tree: 15/100 critical (15.0%)]
==================================================================================================
Protocol         | Sent       | Received   | Critical Ratio   | Latency    | Goodput       
--------------------------------------------------------------------------------------------------
Standard TCP     | 100        | 100        | 15/15 (100.0%)   | 1.093     s | 15.5       kbps
Standard UDP     | 100        | 82         | 13/15 (86.7%)    | 0.118     s | 117.7      kbps
Micro-QUIC       | 100        | 83         | 15/15 (100.0%)   | 0.151     s | 61.3       kbps
==================================================================================================

[VISUAL METRICS COMPARISON]
  Standard TCP    Critical Delivery: [████████████████████] 100.0% | Latency: 1.093s
  Standard UDP    Critical Delivery: [█████████████████░░░]  86.7% | Latency: 0.118s (Critical lost!)
  Micro-QUIC      Critical Delivery: [████████████████████] 100.0% | Latency: 0.151s (7.2x faster than TCP)
--------------------------------------------------------------------------------------------------
```
*Notice: Micro-QUIC guarantees 100% critical delivery at over 7x the speed of TCP, whereas UDP drops 13.3% of critical packets.*

---

## ML Criticality Pipeline

The ML pipeline identifies high-motion scene changes and keyframes that must be preserved reliably.

### Retraining on Diverse Video Datasets

Train across a directory of videos (e.g. `data/trainingVideos/`) or multiple individual files:

```bash
# Train on diverse video library with KMeans clustering and export metrics
python train_classifier.py --video-dir data/trainingVideos --metrics-out metrics.json

# Train using motion-threshold heuristic
python train_classifier.py --video data/testVideo.mp4 --label-method motion-threshold --motion-threshold 12.0

# Train with supervised ground-truth CSV labels
python train_classifier.py --video data/testVideo.mp4 --label-method supervised --labels my_labels.csv
```

Outputs:
- `criticality_model.pkl`: Serialized Scikit-Learn `Pipeline([StandardScaler, DecisionTreeClassifier])`.
- `metrics.json`: Accuracy, precision, recall, F1, feature importances, and confusion matrix.

---

## ML Video Streaming Demo

### 1. Basic File Streaming

**Terminal 1 — Receiver:**
```bash
python video_receiver.py --port 50007
```
*(Add `--no-display` for headless servers/CI).*

**Terminal 2 — Sender:**
```bash
python video_sender.py --video data/testVideo.mp4 --port 50007 --loss-rate 0.15
```

### 2. Live Webcam Capture Mode

Stream from your local webcam (device index 0) in real time:

```bash
# Receiver
python video_receiver.py --port 50007

# Sender (streaming from camera 0)
python video_sender.py --camera 0 --port 50007 --fps 30
```

### 3. Saving the Received Video & Frames

Save the decoded stream to a video file and/or write individual JPEG frames:

```bash
python video_receiver.py --port 50007 --save received_stream.avi --save-frames frames/ --no-display
```

### 4. Advanced Production Controls

- **Frame Pacing (`--fps 30`)**: Matches source FPS capture instead of overwhelming the network.
- **Priority Drop Under Load (`--priority-drop`)**: Automatically drops non-critical frames if network congestion or packet loss causes critical retransmissions to backlog.
- **Rate Limiting (`--rate-limit 5000`)**: Caps outbound transmission at 5000 kbps to prevent buffer bloat.
- **Authenticated Encryption (`--psk secretkey123`)**: Encrypts and authenticates all payloads using AES-CTR + HMAC-SHA256.
- **Multi-Stream (`--stream-id 1`)**: Tags datagrams with logical stream IDs (0–7) allowing multiple video/telemetry channels over one port.
- **Alternate Codecs (`--codec png` or `--codec raw`)**: Choose between JPEG, PNG, or raw byte streams.

---

## Telemetry Demo

Run synthetic telemetry data transmission:

```bash
# Receiver
python sender.py receiver --port 50007

# Sender: 50 packets, 20% critical, through 15% simulated packet loss
python sender.py sender --port 50007 --count 50 --critical-ratio 0.2 --loss-rate 0.15
```

---

## Cross-Host & LAN Deployment

To run Micro-QUIC between two physical machines on the same local network:

### 1. Receiver Host Setup
1. Find your LAN IP address (e.g. `192.168.1.50`):
   ```bash
   ip -br addr
   ```
2. Open the UDP port in your firewall (Linux `ufw`):
   ```bash
   sudo ufw allow 50007/udp
   ```
3. Start the receiver binding to all interfaces (`0.0.0.0`):
   ```bash
   python video_receiver.py --host 0.0.0.0 --port 50007
   ```

### 2. Sender Host Setup
Point the sender to the receiver's LAN IP:
```bash
python video_sender.py --host 192.168.1.50 --port 50007 --video data/testVideo.mp4
```

### 3. Wireshark Capture & Inspection
To inspect Micro-QUIC datagrams in Wireshark:
1. Select your network interface (`eth0`, `wlan0`, or `lo` for localhost).
2. Apply the display filter:
   ```wireshark
   udp.port == 50007
   ```
3. Notice the 13-byte header immediately following the 8-byte UDP header:
   - First 4 bytes: Sequence Number
   - Next 4 bytes: ACK Number
   - 9th byte: Flags bitmask (`0x02` for Critical, `0x01` for ACK, `0x04` for More Fragments, `0x10` for Encrypted)
   - Last 4 bytes: CRC-32 checksum

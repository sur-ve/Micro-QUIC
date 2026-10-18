# Micro-QUIC — Completed Features & Roadmap

Living checklist of completed features and planned upgrades.

---

## Completed Features

### Protocol (`micro_quic.py` / `header.py`)
- [x] **Sliding window ARQ** — replaced Stop-and-Wait with Selective Repeat ARQ (`window_size=16`) for high-throughput critical frame transmission
- [x] **Out-of-order reassembly** — tolerant backward-contiguous reassembly handles out-of-order and interleaved fragment delivery
- [x] **Incomplete-frame timeout** — automated deadline drop (`fragment_timeout=0.5s`) purges stalled buffers without blocking subsequent frames
- [x] **Dynamic RTT / timeout** — Jacobson/Karels RTT estimation with Karn's algorithm (excluding retransmitted samples) and exponential backoff
- [x] **Wire `MORE_FRAGMENTS` edge cases** — handles empty payload (`b""`), single-byte last fragments, and peer restarts mid-stream

### ML Pipeline (`train_classifier.py` / `classifier.py`)
- [x] **Retrain on diverse video** — multi-video feature extraction across `data/trainingVideos/*.mp4` and `data/testVideo.mp4`
- [x] **Labeled training path** — supports unsupervised KMeans, motion-threshold heuristics, and supervised CSV ground-truth labels
- [x] **Export feature importances / metrics** — exports accuracy, precision, recall, F1, confusion matrix, and feature importances to `metrics.json`
- [x] **Safe lazy-loading & hot reload** — `classifier.py` loads on first use and supports dynamic reload via `load_pipeline()`

### Demo Apps (`video_sender.py`, `video_receiver.py`, `sender.py`)
- [x] **Webcam / live capture mode** — `video_sender.py` supports live webcam/camera streams via `--camera <index>`
- [x] **Save received stream to file** — `video_receiver.py` writes MJPEG `.avi` videos via `--save` and individual JPEG frames via `--save-frames`
- [x] **Unify CLIs** — unified arguments (`--host`, `--port`, `--loss-rate`, `--max-frames`, `--psk`, `--stream-id`, `--rate-limit`) across apps
- [x] **Headless CI smoke test** — comprehensive `test_smoke.py` verifying protocol, crypto, multi-stream, Selective Repeat, and video streaming

### New Capabilities Added
- [x] **Selective Repeat + larger send window** — multi-fragment sliding window send loop with selective retransmission
- [x] **Congestion / rate control** — `--rate-limit` (in kbps) and inter-packet pacing to prevent UDP burst buffer overflows
- [x] **Frame pacing to source FPS** — real-time frame pacing matching source video FPS or user-configured `--fps`
- [x] **Priority drop under load** — `--priority-drop` drops non-critical frames when retransmission latency builds up
- [x] **Encryption & integrity beyond CRC** — authenticated AES-grade CTR keystream + HMAC-SHA256 authenticated encryption using standard library (`--psk`)
- [x] **Multi-stream / connection IDs** — multiplexes up to 8 independent logical streams (`--stream-id 0..7`) over a single UDP socket
- [x] **Metrics dashboard** — visual ASCII comparison dashboard in `benchmark.py` displaying goodput, loss %, and latency
- [x] **Alternate codecs** — selectable frame encoding (`--codec jpg|png|raw`) in `features.py` and `video_sender.py`
- [x] **Cross-host demo docs** — detailed Wireshark filters, firewall configuration, and LAN streaming instructions in `README.md`

### Project Hygiene
- [x] Renamed `dependancies.txt` → `requirements.txt` and pinned versions
- [x] Dropped unused `pandas` dependency
- [x] Refreshed `README.md` with complete architecture, CLI reference, and ML workflow

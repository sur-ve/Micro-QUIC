# Micro-QUIC - Future Plans
---

## To Be Completed 

### Protocol (`micro_quic.py` / `header.py`)
- [ ] **Sliding window ARQ** — replace per-fragment Stop-and-Wait with Go-Back-N or Selective Repeat for higher critical-frame throughput
- [ ] **Out-of-order reassembly** — current reassembly expects contiguous `seq`; tolerate reorder within a message
- [ ] **Incomplete-frame timeout** — drop stalled fragment buffers after a deadline instead of waiting forever / until a seq gap
- [ ] **Dynamic RTT / timeout** — estimate RTT (e.g. Karn’s algorithm) instead of fixed `DEFAULT_TIMEOUT = 100ms`
- [ ] **Message-level ACK option** — ACK once per logical frame instead of every critical fragment (fewer round trips for ~80-chunk JPEGs)
- [ ] **Wire `MORE_FRAGMENTS` edge cases** — empty payload, single-byte last fragment, and peer restart mid-stream

### ML pipeline
- [ ] **Retrain on diverse video** — model is fit only on `data/testVideo.mp4`; add more scenes / resolutions
- [ ] **Labeled training path** — optional supervised labels instead of KMeans pseudo-labels only
- [ ] **Online / adaptive threshold** — adjust criticality under live loss/bandwidth feedback
- [ ] **Export feature importances / metrics** — accuracy, cluster balance, confusion vs hand labels in `train_classifier.py`

### Demo apps
- [ ] **Webcam / live capture mode** — `video_sender.py` currently file-only (`VideoCapture(path)`)
- [ ] **Save received stream to file** — write decoded frames or MJPEG/MP4 from `video_receiver.py`
- [ ] **Unify CLIs** — align flags between `sender.py` (telemetry) and `video_*.py`
- [ ] **Headless CI smoke test** — scripted N-frame send/recv with asserts (no GUI)
---

## Features To Add (new capability)

| Priority | Feature | Why |
| :--- | :--- | :--- |
| High | Selective Repeat + larger send window | Critical video is slow under Stop-and-Wait × ~79 fragments/frame |
| High | Congestion / rate control | Avoid flooding the network on non-critical fire-and-forget bursts |
| Medium | Frame pacing to source FPS | Match 30 fps capture instead of send-as-fast-as-possible |
| Medium | Priority drop under load | Skip non-critical frames when critical backlog grows |
| Medium | Encryption / integrity beyond CRC | CRC catches corruption, not attackers |
| Medium | Multi-stream / connection IDs | Multiple logical flows over one UDP port |
| Low | Metrics dashboard | Live loss %, critical ratio, goodput charts (extend `benchmark.py`) |
| Low | Cross-host demo docs | Non-localhost setup, firewall, Wireshark filters |
| Low | Alternate codecs | H.264 NAL units or raw YUV instead of JPEG-per-frame |


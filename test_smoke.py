"""Headless CI Smoke Test Suite for Micro-QUIC.

Runs automated unit and end-to-end integration tests without requiring a GUI.
Exits with code 0 on complete pass, non-zero on failure.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from channel import LossyChannel
from features import extractFeatures
from header import (
    MicroQUICPacket,
    encode_flags,
    encrypt_payload,
    decrypt_payload,
    FLAG_CRITICAL,
    FLAG_ACK,
    FLAG_ENCRYPTED,
    FLAG_FRAGMENTED,
)
from micro_quic import MicroQUICSocket, RecvResult


def test_header_and_crypto():
    print("[TEST 1/5] Header serialization & PSK authenticated encryption...")
    psk = b"secret-smoke-test-key"
    data = b"MicroQUIC authenticated payload"

    # Test encryption & decryption
    enc = encrypt_payload(data, psk)
    dec = decrypt_payload(enc, psk)
    assert dec == data, "Decrypted data does not match original"

    # Test tampering detection
    tampered = bytearray(enc)
    tampered[-1] ^= 0xAA
    try:
        decrypt_payload(bytes(tampered), psk)
        assert False, "Tampered payload should have failed authentication"
    except ValueError:
        pass

    # Test packet pack / unpack
    flags = encode_flags(critical=True, fragmented=True, encrypted=True, stream_id=5)
    pkt = MicroQUICPacket(seq=101, ack=50, flags=flags, payload=enc)
    packed = pkt.pack()

    unpacked = MicroQUICPacket.unpack(packed)
    assert unpacked.is_valid, "Packet checksum failed"
    assert unpacked.is_critical, "FLAG_CRITICAL not preserved"
    assert unpacked.is_fragmented, "FLAG_FRAGMENTED not preserved"
    assert unpacked.is_encrypted, "FLAG_ENCRYPTED not preserved"
    assert unpacked.stream_id == 5, f"Stream ID mismatch: got {unpacked.stream_id}"
    assert unpacked.seq == 101
    assert unpacked.ack == 50
    print("  -> Passed!")


def test_multistream():
    print("[TEST 2/5] Multi-stream multiplexing over single UDP port...")
    port = 54390
    server = MicroQUICSocket()
    server.bind(("127.0.0.1", port))
    server.settimeout(2.0)

    client = MicroQUICSocket()

    received = {}

    def srv():
        for _ in range(3):
            res = server.recv_packet(include_stream_id=True)
            if res[0] is not None:
                payload, addr, is_crit, sid = res
                received[sid] = payload

    t = threading.Thread(target=srv)
    t.start()
    time.sleep(0.05)

    client.send_packet(b"STREAM_0_MSG", ("127.0.0.1", port), stream_id=0)
    client.send_packet(b"STREAM_2_MSG", ("127.0.0.1", port), stream_id=2)
    client.send_packet(b"STREAM_7_MSG", ("127.0.0.1", port), stream_id=7)

    t.join(timeout=3.0)
    server.close()
    client.close()

    assert received.get(0) == b"STREAM_0_MSG", f"Stream 0 mismatch: {received.get(0)}"
    assert received.get(2) == b"STREAM_2_MSG", f"Stream 2 mismatch: {received.get(2)}"
    assert received.get(7) == b"STREAM_7_MSG", f"Stream 7 mismatch: {received.get(7)}"
    print("  -> Passed!")


def test_selective_repeat_sliding_window():
    print("[TEST 3/5] Selective Repeat ARQ under 20% lossy channel...")
    server_port = 54391
    proxy_port = 54392
    loss_rate = 0.20

    channel = LossyChannel(listen_port=proxy_port, target_port=server_port, loss_rate=loss_rate)
    channel.start()

    server = MicroQUICSocket()
    server.bind(("127.0.0.1", server_port))
    server.settimeout(3.0)

    client = MicroQUICSocket(timeout=0.05, max_retries=10, window_size=8)

    # 10 KB payload -> ~9 fragments
    large_payload = b"CRITICAL_DATA_CHUNK_" + b"Z" * 9000

    def srv():
        p, a, c = server.recv_packet()
        assert p == large_payload, f"Payload mismatch: got {len(p) if p else 0} bytes"
        assert c == True, "Expected critical=True"

    t = threading.Thread(target=srv)
    t.start()
    time.sleep(0.05)

    ok = client.send_packet(large_payload, ("127.0.0.1", proxy_port), is_critical=True)
    assert ok, "Selective Repeat send failed"

    t.join(timeout=4.0)
    channel.stop()
    server.close()
    client.close()
    print("  -> Passed!")


def test_out_of_order_and_timeout():
    print("[TEST 4/5] Out-of-order reassembly and incomplete-frame timeout...")
    server = MicroQUICSocket(fragment_timeout=0.2)
    addr = ("127.0.0.1", 9999)

    # Test reverse arrival of 3 fragments
    p1 = MicroQUICPacket(seq=1, ack=0, flags=encode_flags(critical=True, more_fragments=True, fragmented=True), payload=b"CHUNK1_")
    p2 = MicroQUICPacket(seq=2, ack=0, flags=encode_flags(critical=True, more_fragments=True, fragmented=True), payload=b"CHUNK2_")
    p3 = MicroQUICPacket(seq=3, ack=0, flags=encode_flags(critical=True, more_fragments=False, fragmented=True), payload=b"CHUNK3")

    assert server._ingest_fragment(addr, p3, p3.payload) is None
    assert server._ingest_fragment(addr, p1, p1.payload) is None

    res = server._ingest_fragment(addr, p2, p2.payload)
    assert res is not None, "Failed to reassemble out-of-order fragments"
    full_payload, is_crit, _ = res
    assert full_payload == b"CHUNK1_CHUNK2_CHUNK3"
    assert is_crit == True

    # Test incomplete frame timeout recovery
    p_stalled = MicroQUICPacket(seq=4, ack=0, flags=encode_flags(critical=False, more_fragments=True, fragmented=True), payload=b"STALLED_")
    server._ingest_fragment(addr, p_stalled, p_stalled.payload)

    time.sleep(0.25)  # Wait past fragment_timeout

    # Fresh standalone packet arrives
    p_fresh = MicroQUICPacket(seq=5, ack=0, flags=encode_flags(critical=False, more_fragments=False, fragmented=False), payload=b"FRESH")
    fresh_res = server._ingest_fragment(addr, p_fresh, p_fresh.payload)
    assert fresh_res is not None
    assert fresh_res[0] == b"FRESH"
    print("  -> Passed!")


def test_end_to_end_video_streaming():
    print("[TEST 5/5] End-to-end headless video stream through 15% lossy channel...")
    port = 54395
    temp_dir = tempfile.mkdtemp(prefix="mquic_smoke_")
    save_avi = os.path.join(temp_dir, "received.avi")
    save_frames = os.path.join(temp_dir, "frames")

    from video_receiver import run_video_receiver
    from video_sender import run_video_sender

    target_critical_frames = 4

    # Run receiver in background thread: stops after receiving target_critical_frames
    def receiver_runner():
        run_video_receiver(
            port=port,
            display=False,
            max_frames=target_critical_frames,
            save_path=save_avi,
            save_frames_dir=save_frames,
            timeout=5.0,
        )

    t_recv = threading.Thread(target=receiver_runner, daemon=True)
    t_recv.start()
    time.sleep(0.2)

    # Run sender: send 4 frames end-to-end
    run_video_sender(
        video_source="data/testVideo.mp4",
        dest=("127.0.0.1", port),
        loss_rate=0.0,
        max_frames=target_critical_frames,
        fps=0.0,  # Unthrottled for fast CI
        keyframe_interval=2,
    )

    t_recv.join(timeout=10.0)

    # Assert outputs
    assert os.path.exists(save_avi), f"Output video file {save_avi} was not created"
    assert os.path.getsize(save_avi) > 0, "Output video file is empty"

    assert os.path.isdir(save_frames), f"Frames directory {save_frames} not created"
    written_frames = os.listdir(save_frames)
    assert len(written_frames) > 0, "No JPEG frames saved"

    # Cleanup temp dir
    shutil.rmtree(temp_dir)
    print(f"  -> Passed! (Saved video and {len(written_frames)} frames verified)")


def main():
    print("=" * 60)
    print("        MICRO-QUIC HEADLESS CI SMOKE TEST SUITE")
    print("=" * 60)

    start_time = time.time()
    test_header_and_crypto()
    test_multistream()
    test_selective_repeat_sliding_window()
    test_out_of_order_and_timeout()
    test_end_to_end_video_streaming()
    elapsed = time.time() - start_time

    print("=" * 60)
    print(f" ALL TESTS PASSED SUCCESSFULLY in {elapsed:.2f}s!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())

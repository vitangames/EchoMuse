"""Passive wake-word recorder: exact PCM capture and safe storage."""

import json
import wave

import em_wake_recorder as rec


def _db(tmp_path):
    return str(tmp_path / "echomuse.db")


def _pcm(ms: int, value: bytes = b"\x01\x02") -> bytes:
    return value * int(rec.SAMPLE_RATE * ms / 1000)


def test_target_key_keeps_readable_unicode_but_rejects_paths():
    assert rec.target_key("  Василий  ") == "василий"
    assert rec.target_key("Hey, Biscuit!") == "hey_biscuit"
    assert rec.target_key("../") is None
    assert rec.target_key("") is None


def test_recorder_includes_preroll_and_finishes_at_exact_duration():
    recorder = rec.Recorder("echo1", pre_roll_ms=400)
    recorder.feed(_pcm(400, b"\x10\x00"))
    state = recorder.start(target_phrase="Василий", duration_ms=2000)
    assert state["state"] == "recording"
    assert state["captured_ms"] == 400

    capture = recorder.feed(_pcm(2000, b"\x20\x00"))
    assert capture is not None
    assert len(capture.pcm) == rec.BYTES_PER_SECOND * 2
    assert capture.pcm[:2] == b"\x10\x00"
    assert capture.pcm[-2:] == b"\x20\x00"
    assert recorder.status()["state"] == "saving"


def test_recorder_does_not_change_the_pcm_object():
    recorder = rec.Recorder("echo1")
    recorder.start(target_phrase="Василий", duration_ms=1500)
    frame = _pcm(80)
    before = bytes(frame)
    recorder.feed(frame)
    assert frame == before


def test_cancel_and_failure_return_to_a_clear_state():
    recorder = rec.Recorder("echo1")
    recorder.start(target_phrase="Василий", duration_ms=1500)
    assert recorder.cancel() is True
    assert recorder.status()["state"] == "idle"
    recorder.start(target_phrase="Василий", duration_ms=1500)
    recorder.fail("stream gone")
    assert recorder.status()["state"] == "error"
    assert recorder.status()["error"] == "stream gone"
    assert recorder.cancel() is True
    assert recorder.status()["state"] == "idle"


def test_save_writes_pcm16_wav_and_manifest(tmp_path):
    recorder = rec.Recorder("echo1", pre_roll_ms=0)
    recorder.start(
        target_phrase="Василий", duration_ms=1500, device_label="Kitchen",
        distance="3 m", environment="TV", notes="side angle",
        session_id="session-a",
    )
    capture = recorder.feed(_pcm(1500))
    assert capture is not None
    row = rec.save_capture(capture, _db(tmp_path))
    recorder.mark_saved(row)

    path = tmp_path / "wake_samples" / "василий" / "echo1" / f"{row['sample_id']}.wav"
    with wave.open(str(path), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
        assert wav.getnframes() == 24000
    manifest = tmp_path / "wake_samples" / "василий" / "manifest.jsonl"
    saved = json.loads(manifest.read_text().strip())
    assert saved["filename"] == f"echo1/{row['sample_id']}.wav"
    assert saved["distance"] == "3 m"
    assert saved["environment"] == "TV"
    assert saved["session_id"] == "session-a"
    assert len(saved["pcm_sha256"]) == 64
    assert not list(tmp_path.rglob("*.part"))


def _save_for(tmp_path, device: str, phrase: str = "Василий"):
    recorder = rec.Recorder(device, pre_roll_ms=0)
    recorder.start(target_phrase=phrase, duration_ms=1500)
    capture = recorder.feed(_pcm(1500))
    assert capture is not None
    return rec.save_capture(capture, _db(tmp_path))


def test_listing_and_resolve_are_scoped_to_target_and_device(tmp_path):
    one = _save_for(tmp_path, "echo1")
    _save_for(tmp_path, "echo2")
    _save_for(tmp_path, "echo1", "Компьютер")

    rows, total = rec.list_samples("Василий", "echo1", _db(tmp_path))
    assert total == 1
    assert rows[0]["sample_id"] == one["sample_id"]
    assert rec.find_sample("Василий", "echo1", one["sample_id"], _db(tmp_path))
    assert rec.find_sample("Василий", "echo2", one["sample_id"], _db(tmp_path)) is None
    assert rec.find_sample("Василий", "../echo1", one["sample_id"], _db(tmp_path)) is None
    assert rec.find_sample("Василий", "echo1", "../manifest", _db(tmp_path)) is None


def test_delete_removes_only_requested_sample_and_manifest_row(tmp_path):
    one = _save_for(tmp_path, "echo1")
    two = _save_for(tmp_path, "echo1")
    assert rec.delete_sample("Василий", "echo1", one["sample_id"], _db(tmp_path))
    rows, total = rec.list_samples("Василий", "echo1", _db(tmp_path))
    assert total == 1
    assert rows[0]["sample_id"] == two["sample_id"]
    assert rec.find_sample("Василий", "echo1", one["sample_id"], _db(tmp_path)) is None


def test_controller_taps_before_selecting_the_detector_queue():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "em_controller.py").read_text()
    handler = source[source.index("async def handle_data"):]
    handler = handler[:handler.index("\n# ─── Router", 1)]
    assert handler.index("wake_recorder.feed(payload)") < handler.index(
        "q = device.voice_queue if device.oww_paused.is_set() else device.mic_queue",
        handler.index("payload = raw[MIC_HEADER_LEN:]"),
    )
    assert "q.get" not in handler[
        handler.index("wake_recorder.feed(payload)"):
        handler.index("q = device.voice_queue if device.oww_paused.is_set() else device.mic_queue",
                      handler.index("payload = raw[MIC_HEADER_LEN:]"))
    ]

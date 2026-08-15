"""
em_wake_recorder.py — passive real wake-word sample capture
=============================================================

Captures a COPY of the Echo's continuous 16 kHz mono S16_LE microphone
stream.  The caller still owns and routes the original PCM frame to
openWakeWord/Assist; this module never consumes a queue and never changes the
audio pipeline.

One Recorder lives on each connected Device. ``feed`` is intentionally pure
in-memory work and returns a completed Capture when enough PCM has arrived.
The controller persists that Capture in an executor, so filesystem latency
can never stall the data-plane WebSocket or wake-word scoring.

Samples live in ``wake_samples/`` beside the controller database (and thus in
the existing persisted Docker volume):

    wake_samples/<target>/<device>/<sample-id>.wav
    wake_samples/<target>/manifest.jsonl

The manifest stores the exact device, phrase and optional collection notes.
Writes are atomic; a process crash leaves at most an ignored ``.part`` file,
never a WAV that looks complete.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import unicodedata
import uuid
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
CHANNELS = 1
BYTES_PER_SECOND = SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS

DEFAULT_DURATION_MS = 3000
MIN_DURATION_MS = 1500
MAX_DURATION_MS = 5000
PRE_ROLL_MS = 400

WAKE_SAMPLES_SUBDIR = "wake_samples"
MANIFEST_NAME = "manifest.jsonl"

_SAFE_DEVICE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_SAMPLE_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_manifest_lock = threading.Lock()


def samples_dir(db_path: str | None = None) -> Path:
    if db_path is None:
        db_path = os.environ.get("DB_PATH", "echomuse.db")
    return Path(db_path).resolve().parent / WAKE_SAMPLES_SUBDIR


def target_key(phrase: str) -> str | None:
    """A readable, path-safe Unicode key for a target phrase."""
    if not isinstance(phrase, str):
        return None
    phrase = unicodedata.normalize("NFKC", phrase).strip().casefold()
    if not phrase or len(phrase) > 120:
        return None
    key = re.sub(r"[^\w-]+", "_", phrase, flags=re.UNICODE).strip("_-")
    if not key or key in {".", ".."}:
        return None
    return key[:80]


def safe_device_id(device_id: str) -> str | None:
    return device_id if isinstance(device_id, str) and _SAFE_DEVICE_RE.fullmatch(device_id) else None


def _pcm_bytes(ms: int) -> int:
    # Always keep sample boundaries intact.
    return (int(BYTES_PER_SECOND * ms / 1000) // SAMPLE_WIDTH) * SAMPLE_WIDTH


@dataclass(frozen=True)
class Capture:
    sample_id: str
    device_id: str
    pcm: bytes
    metadata: dict[str, Any]


class Recorder:
    """Bounded in-memory recorder for one device's continuous PCM stream."""

    def __init__(self, device_id: str, pre_roll_ms: int = PRE_ROLL_MS):
        safe = safe_device_id(device_id)
        if safe is None:
            raise ValueError("unsafe device id")
        self.device_id = safe
        self._pre_roll_limit = _pcm_bytes(max(0, min(pre_roll_ms, 1000)))
        self._pre_roll = bytearray()
        self._buffer: bytearray | None = None
        self._wanted_bytes = 0
        self._metadata: dict[str, Any] | None = None
        self._sample_id: str | None = None
        self._state = "idle"
        self._error: str | None = None
        self._last_sample: dict[str, Any] | None = None

    def _remember(self, pcm: bytes) -> None:
        if not pcm or self._pre_roll_limit <= 0:
            return
        self._pre_roll.extend(pcm)
        overflow = len(self._pre_roll) - self._pre_roll_limit
        if overflow > 0:
            del self._pre_roll[:overflow]
        if len(self._pre_roll) % SAMPLE_WIDTH:
            del self._pre_roll[:len(self._pre_roll) % SAMPLE_WIDTH]

    def start(self, *, target_phrase: str, duration_ms: int = DEFAULT_DURATION_MS,
              device_label: str = "", distance: str = "",
              environment: str = "", notes: str = "",
              session_id: str = "") -> dict[str, Any]:
        if self._state in {"recording", "saving"}:
            raise RuntimeError("a recording is already in progress")
        key = target_key(target_phrase)
        if key is None:
            raise ValueError("target phrase is empty or invalid")
        duration_ms = int(duration_ms)
        if not MIN_DURATION_MS <= duration_ms <= MAX_DURATION_MS:
            raise ValueError(
                f"duration_ms must be between {MIN_DURATION_MS} and {MAX_DURATION_MS}"
            )
        sample_id = uuid.uuid4().hex
        started_at = time.time()
        self._metadata = {
            "sample_id": sample_id,
            "target_phrase": target_phrase.strip(),
            "target_key": key,
            "device_id": self.device_id,
            "device_label": str(device_label or "")[:120],
            "distance": str(distance or "")[:80],
            "environment": str(environment or "")[:160],
            "notes": str(notes or "")[:500],
            "session_id": str(session_id or "")[:80],
            "requested_duration_ms": duration_ms,
            "pre_roll_ms": int(len(self._pre_roll) / BYTES_PER_SECOND * 1000),
            "started_at": started_at,
        }
        self._sample_id = sample_id
        self._wanted_bytes = _pcm_bytes(duration_ms)
        self._buffer = bytearray(self._pre_roll[-self._wanted_bytes:])
        self._state = "recording"
        self._error = None
        return self.status()

    def feed(self, pcm: bytes) -> Capture | None:
        """Tap one PCM frame. Returns a complete capture without doing I/O."""
        if not isinstance(pcm, bytes) or not pcm:
            return None
        if len(pcm) % SAMPLE_WIDTH:
            pcm = pcm[:len(pcm) - (len(pcm) % SAMPLE_WIDTH)]
        if not pcm:
            return None

        completed = None
        if self._state == "recording" and self._buffer is not None:
            remaining = self._wanted_bytes - len(self._buffer)
            self._buffer.extend(pcm[:remaining])
            if len(self._buffer) >= self._wanted_bytes:
                completed = Capture(
                    sample_id=self._sample_id or uuid.uuid4().hex,
                    device_id=self.device_id,
                    pcm=bytes(self._buffer[:self._wanted_bytes]),
                    metadata=dict(self._metadata or {}),
                )
                self._state = "saving"
                self._buffer = None
        self._remember(pcm)
        return completed

    def mark_saved(self, sample: dict[str, Any]) -> None:
        self._last_sample = dict(sample)
        self._state = "idle"
        self._error = None
        self._metadata = None
        self._sample_id = None
        self._wanted_bytes = 0

    def fail(self, message: str) -> None:
        if self._state in {"recording", "saving"}:
            self._state = "error"
            self._error = str(message)[:300]
            self._buffer = None
            self._metadata = None
            self._sample_id = None
            self._wanted_bytes = 0

    def cancel(self) -> bool:
        active = self._state in {"recording", "saving", "error"}
        if active:
            self._state = "idle"
            self._error = None
            self._buffer = None
            self._metadata = None
            self._sample_id = None
            self._wanted_bytes = 0
        return active

    def status(self) -> dict[str, Any]:
        captured = len(self._buffer) if self._buffer is not None else 0
        requested_ms = int((self._metadata or {}).get("requested_duration_ms", 0))
        return {
            "state": self._state,
            "sample_id": self._sample_id,
            "target_phrase": (self._metadata or {}).get("target_phrase"),
            "duration_ms": requested_ms,
            "captured_ms": int(captured / BYTES_PER_SECOND * 1000),
            "progress": round(min(1.0, captured / self._wanted_bytes), 3)
                        if self._wanted_bytes else 0.0,
            "error": self._error,
            "last_sample": self._last_sample,
        }


def _manifest_path(root: Path, key: str) -> Path:
    return root / key / MANIFEST_NAME


def save_capture(capture: Capture, db_path: str | None = None) -> dict[str, Any]:
    """Persist a completed capture as WAV and append its manifest row."""
    safe = safe_device_id(capture.device_id)
    key = target_key(str(capture.metadata.get("target_phrase", "")))
    if safe is None or key is None or not _SAMPLE_ID_RE.fullmatch(capture.sample_id):
        raise ValueError("capture metadata is unsafe")
    if not capture.pcm or len(capture.pcm) % SAMPLE_WIDTH:
        raise ValueError("capture PCM is empty or not sample-aligned")

    root = samples_dir(db_path)
    target_root = root / key
    device_root = target_root / safe
    device_root.mkdir(parents=True, exist_ok=True)
    filename = f"{capture.sample_id}.wav"
    path = device_root / filename
    part = path.with_suffix(".wav.part")
    with wave.open(str(part), "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(capture.pcm)
    part.replace(path)

    now = time.time()
    row = dict(capture.metadata)
    row.update({
        "sample_id": capture.sample_id,
        "target_key": key,
        "device_id": safe,
        "filename": f"{safe}/{filename}",
        "created_at": now,
        "created_at_iso": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "sample_rate": SAMPLE_RATE,
        "channels": CHANNELS,
        "sample_width_bytes": SAMPLE_WIDTH,
        "duration_ms": int(len(capture.pcm) / BYTES_PER_SECOND * 1000),
        "pcm_sha256": hashlib.sha256(capture.pcm).hexdigest(),
    })
    manifest = _manifest_path(root, key)
    try:
        with _manifest_lock:
            manifest.parent.mkdir(parents=True, exist_ok=True)
            with manifest.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
    except Exception:
        # A WAV with no manifest row is invisible to the UI and impossible to
        # classify later. Roll it back so a failed append leaves no orphan.
        path.unlink(missing_ok=True)
        raise
    return row


def _read_manifest(phrase: str, db_path: str | None = None) -> list[dict[str, Any]]:
    key = target_key(phrase)
    if key is None:
        return []
    manifest = _manifest_path(samples_dir(db_path), key)
    if not manifest.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for raw in manifest.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def list_samples(phrase: str, device_id: str | None = None,
                 db_path: str | None = None, limit: int = 200
                 ) -> tuple[list[dict[str, Any]], int]:
    safe = safe_device_id(device_id) if device_id is not None else None
    if device_id is not None and safe is None:
        return [], 0
    rows = [row for row in _read_manifest(phrase, db_path)
            if safe is None or row.get("device_id") == safe]
    rows.sort(key=lambda row: float(row.get("created_at", 0)), reverse=True)
    total = len(rows)
    return rows[:max(0, min(int(limit), 1000))], total


def find_sample(phrase: str, device_id: str, sample_id: str,
                db_path: str | None = None
                ) -> tuple[dict[str, Any], Path] | None:
    safe = safe_device_id(device_id)
    key = target_key(phrase)
    if safe is None or key is None or not _SAMPLE_ID_RE.fullmatch(sample_id or ""):
        return None
    for row in _read_manifest(phrase, db_path):
        if row.get("device_id") == safe and row.get("sample_id") == sample_id:
            expected = f"{safe}/{sample_id}.wav"
            if row.get("filename") != expected:
                return None
            path = samples_dir(db_path) / key / safe / f"{sample_id}.wav"
            return (row, path) if path.is_file() else None
    return None


def delete_sample(phrase: str, device_id: str, sample_id: str,
                  db_path: str | None = None) -> bool:
    found = find_sample(phrase, device_id, sample_id, db_path)
    if found is None:
        return False
    _, path = found
    key = target_key(phrase)
    assert key is not None
    manifest = _manifest_path(samples_dir(db_path), key)
    with _manifest_lock:
        rows = _read_manifest(phrase, db_path)
        kept = [row for row in rows if not (
            row.get("device_id") == device_id and row.get("sample_id") == sample_id
        )]
        tmp = manifest.with_suffix(".jsonl.part")
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            for row in kept:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        tmp.replace(manifest)
        path.unlink(missing_ok=True)
    return True

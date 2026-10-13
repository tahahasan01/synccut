"""Local speech-to-text with word timings (faster-whisper on CPU)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from .config import settings

_model = None
_model_lock = threading.Lock()


class TranscriptionUnavailable(RuntimeError):
    pass


def _load():
    global _model
    with _model_lock:
        if _model is None:
            try:
                from faster_whisper import WhisperModel
            except (ImportError, OSError) as exc:
                raise TranscriptionUnavailable(
                    "Local Whisper could not load. On Windows this usually means the Microsoft "
                    "Visual C++ Redistributable is missing - install it with "
                    "`winget install Microsoft.VCRedist.2015+.x64`, then restart the API. "
                    f"({exc})"
                ) from exc
            _model = WhisperModel(settings.whisper_model, device="cpu", compute_type="int8")
        return _model


def transcribe(wav_path: Path, progress: Callable[[float, str], None]) -> dict:
    progress(0.0, f"Loading Whisper model '{settings.whisper_model}' (first run downloads it)")
    model = _load()
    segments, info = model.transcribe(str(wav_path), word_timestamps=True, vad_filter=True)
    duration = max(info.duration, 0.001)
    words: list[dict] = []
    for segment in segments:
        for word in segment.words or []:
            text = word.word.strip()
            if text:
                words.append({"w": text, "start_ms": round(word.start * 1000), "end_ms": round(word.end * 1000)})
        progress(min(segment.end / duration, 1.0), f"Transcribed {segment.end:.0f}s of {duration:.0f}s")
    return {
        "words": words,
        "text": " ".join(w["w"] for w in words),
        "language": info.language,
        "model": settings.whisper_model,
    }

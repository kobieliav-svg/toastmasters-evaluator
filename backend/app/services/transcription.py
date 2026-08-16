"""
Local, free speech-to-text using faster-whisper (CTranslate2 build of
OpenAI's Whisper). Runs entirely on your own machine/server -- no per-minute
API bills.

Model size tradeoff (set via TM_WHISPER_MODEL env var):
  tiny.en / base.en  -> fastest, good enough for English filler-word/timing
                        scoring, runs fine on CPU in real time.
  small.en / medium.en -> more accurate transcript text, needs more CPU/RAM
                        or a GPU to keep up with live audio.

For the live-Zoom-bot pipeline, audio arrives in short chunks (per RTMS
frame buffer, see services/zoom_rtms.py) and this module transcribes each
finalized speaking turn once silence/turn-end is detected -- it does not
need word-level streaming to produce the end-of-turn transcript this app
scores.
"""
import os
import wave
import contextlib
from functools import lru_cache

MODEL_SIZE = os.environ.get("TM_WHISPER_MODEL", "base.en")


@lru_cache(maxsize=1)
def _get_model():
    from faster_whisper import WhisperModel
    # int8 compute type keeps this usable on a CPU-only server/laptop.
    return WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")


def transcribe_audio_file(path: str) -> str:
    """Transcribe a finished WAV/MP3 file (e.g. one Table Topics answer or
    one full prepared speech) and return the plain-text transcript."""
    model = _get_model()
    segments, _info = model.transcribe(path, language="en", vad_filter=True)
    return " ".join(seg.text.strip() for seg in segments).strip()


def wav_duration_seconds(path: str) -> float:
    with contextlib.closing(wave.open(path, "r")) as f:
        frames = f.getnframes()
        rate = f.getframerate()
        return frames / float(rate)

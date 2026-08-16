#!/usr/bin/env python3
"""
Local Zoom-audio listener -- NO Zoom API, NO Zoom app, NO Zoom account
credits needed. This is the recommended way to run the evaluator.

How it works: run this script on the computer that is *in* the Zoom
meeting (see the README for the recommended setup -- join as an extra
silent participant, mic muted, so this machine's speaker output carries
everyone else's voice). The script listens to that computer's own audio
output (a "loopback" recording -- literally what would come out of the
speakers), automatically detects when someone starts/stops talking, and
uploads each finished turn to the dashboard's API, where it gets
transcribed (locally, for free) just long enough to count filler words,
measure pace/duration, and produce a score.

Requirements (only on the listener machine -- lightweight, no Whisper here):
    pip install -r requirements-listener.txt

Usage:
    python listen_and_score.py --api http://localhost:8000
    python listen_and_score.py --api http://localhost:8000 --session-id 3
    python listen_and_score.py --list-devices          # see input options
    python listen_and_score.py --device "BlackHole 2ch" # macOS, see README

Stop with Ctrl+C.
"""
import argparse
import datetime
import io
import sys
import tempfile
import time
import wave

import numpy as np
import requests

# Compatibility shim: the `soundcard` package (as of v0.4.3) still calls the
# old binary mode of numpy.fromstring internally, which NumPy 2.x removed
# entirely ("The binary mode of fromstring is removed, use frombuffer
# instead"). Patch it here so soundcard keeps working without pinning an
# older NumPy.
_orig_fromstring = np.fromstring


def _fromstring_compat(data, dtype=float, count=-1, sep=""):
    if sep == "":
        return np.frombuffer(data, dtype=dtype, count=count)
    return _orig_fromstring(data, dtype=dtype, count=count, sep=sep)


np.fromstring = _fromstring_compat

SAMPLE_RATE = 16000
FRAME_MS = 100                       # size of each analysis chunk
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
CALIBRATION_SECONDS = 2.0            # measure ambient noise floor at startup
SILENCE_HANGOVER_SEC = 10.0          # silence needed to end a turn (kept in
                                      # sync with app.js -- long, by request,
                                      # to avoid splitting one answer in two)
MIN_TURN_SECONDS = 3.0               # discard shorter blips (coughs, "yeah")
MAX_TURN_SECONDS = 480               # safety cap (8 min) so a stuck VAD can't buffer forever
PRE_ROLL_FRAMES = 3                  # keep a little audio from just before speech was detected


def list_devices():
    import soundcard as sc
    print("Speakers (use the default unless you have a reason not to):")
    for s in sc.all_speakers():
        print(f"  - {s.name}")
    print("\nMicrophones / recordable inputs (pick one with --device for a non-default setup, e.g. BlackHole on macOS):")
    for m in sc.all_microphones(include_loopback=True):
        print(f"  - {m.name}")


def get_recorder(device_name: str | None):
    import soundcard as sc
    if device_name:
        mic = sc.get_microphone(device_name, include_loopback=True)
        print(f"Using device: {mic.name}")
        return mic
    default_speaker = sc.default_speaker()
    mic = sc.get_microphone(default_speaker.name, include_loopback=True)
    print(f"Using loopback of default speaker: {default_speaker.name}")
    return mic


def frames_to_wav_bytes(frames: list[np.ndarray]) -> bytes:
    audio = np.concatenate(frames)
    audio_i16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_i16.tobytes())
    return buf.getvalue()


def ensure_session(api_base: str, session_id: int | None, title: str | None) -> int:
    if session_id:
        return session_id
    resp = requests.post(
        f"{api_base}/api/sessions",
        json={"title": title or f"Live listen {datetime.date.today()}", "zoom_meeting_id": ""},
        timeout=10,
    )
    resp.raise_for_status()
    sid = resp.json()["id"]
    print(f"Created session #{sid}")
    return sid


def upload_turn(api_base: str, session_id: int, speech_type: str, wav_bytes: bytes, duration_s: float):
    files = {"file": ("turn.wav", wav_bytes, "audio/wav")}
    data = {
        "session_id": session_id,
        "speech_type": speech_type,
        "project_title": "",
        "target_min_seconds": 60 if speech_type == "table_topic" else 300,
        "target_max_seconds": 120 if speech_type == "table_topic" else 420,
        "speaker_name_raw": "",
    }
    try:
        resp = requests.post(f"{api_base}/api/speeches/ingest-audio", data=data, files=files, timeout=120)
        resp.raise_for_status()
        result = resp.json()
        score = result.get("evaluation", {}).get("score_total", "?")
        fillers = result.get("filler_total", "?")
        speaker = result.get("speaker_name_raw") or "(unmatched)"
        print(f"  -> turn ({duration_s:.0f}s) uploaded: speaker={speaker} score={score} fillers={fillers}")
    except requests.RequestException as e:
        print(f"  !! upload failed: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8000", help="Base URL of the dashboard/API")
    parser.add_argument("--session-id", type=int, default=None, help="Existing session id (else a new one is created)")
    parser.add_argument("--title", default=None, help="Title for a newly-created session")
    parser.add_argument("--speech-type", default="table_topic", choices=["table_topic", "speech"])
    parser.add_argument("--device", default=None, help="Specific input device name (see --list-devices)")
    parser.add_argument("--list-devices", action="store_true")
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return

    session_id = ensure_session(args.api, args.session_id, args.title)
    mic = get_recorder(args.device)

    silence_hangover_frames = int(SILENCE_HANGOVER_SEC * 1000 / FRAME_MS)
    min_turn_frames = int(MIN_TURN_SECONDS * 1000 / FRAME_MS)
    max_turn_frames = int(MAX_TURN_SECONDS * 1000 / FRAME_MS)

    print(f"Calibrating ambient noise for {CALIBRATION_SECONDS:.0f}s -- keep the meeting quiet for a moment...")
    with mic.recorder(samplerate=SAMPLE_RATE, channels=1) as rec:
        calib_frames = int(CALIBRATION_SECONDS * 1000 / FRAME_MS)
        noise_samples = []
        for _ in range(calib_frames):
            data = rec.record(numframes=FRAME_SAMPLES)
            noise_samples.append(np.abs(data).mean())
        noise_floor = float(np.mean(noise_samples)) if noise_samples else 0.001
        threshold = max(noise_floor * 4, 0.003)
        print(f"Noise floor: {noise_floor:.5f} | speech threshold: {threshold:.5f}")
        print("Listening... (Ctrl+C to stop)\n")

        state = "idle"
        pre_roll = []
        turn_frames = []
        silence_run = 0

        try:
            while True:
                data = rec.record(numframes=FRAME_SAMPLES)
                mono = data[:, 0] if data.ndim > 1 else data
                level = float(np.abs(mono).mean())
                is_loud = level > threshold

                if state == "idle":
                    pre_roll.append(mono)
                    if len(pre_roll) > PRE_ROLL_FRAMES:
                        pre_roll.pop(0)
                    if is_loud:
                        state = "speaking"
                        turn_frames = list(pre_roll)
                        turn_frames.append(mono)
                        silence_run = 0
                        print("Speech detected, recording turn...")
                else:  # speaking
                    turn_frames.append(mono)
                    if is_loud:
                        silence_run = 0
                    else:
                        silence_run += 1

                    turn_too_long = len(turn_frames) >= max_turn_frames
                    turn_ended = silence_run >= silence_hangover_frames or turn_too_long

                    if turn_ended:
                        duration_s = len(turn_frames) * FRAME_MS / 1000
                        if len(turn_frames) >= min_turn_frames:
                            wav_bytes = frames_to_wav_bytes(turn_frames)
                            upload_turn(args.api, session_id, args.speech_type, wav_bytes, duration_s)
                        else:
                            print(f"  (discarded short blip, {duration_s:.1f}s)")
                        state = "idle"
                        pre_roll = []
                        turn_frames = []
                        silence_run = 0
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()

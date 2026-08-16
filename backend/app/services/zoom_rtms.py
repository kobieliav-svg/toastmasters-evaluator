"""
Zoom Realtime Media Streams (RTMS) integration.

RTMS is Zoom's current (2025/2026) mechanism for this exact use case: it
streams live per-participant audio (and, on many plans, live transcript
text) out of a meeting over WebSockets WITHOUT a bot joining as a visible
participant. Docs: https://developers.zoom.us/docs/rtms/

--------------------------------------------------------------------------
IMPORTANT -- read before wiring this into a real meeting:
--------------------------------------------------------------------------
1. You need a Zoom "General App" (Marketplace app) with the RTMS scopes
   enabled, and Zoom Developer Pack credits on the account (RTMS usage is
   metered by Zoom itself -- this is a Zoom-side cost, separate from any
   STT/LLM cost, and is the one piece of this system that is NOT free).
2. The exact wire protocol (handshake payloads, media frame format) is
   versioned by Zoom and best consumed through Zoom's own RTMS SDK rather
   than hand-rolled, since Zoom updates message shapes over time. This file
   implements:
     (a) the webhook receiver + signature verification, which IS stable
         and documented, and
     (b) a thin `RTMSClient` interface that should call Zoom's official
         SDK client under the hood -- swap `_connect_via_sdk()` below for
         the current SDK call once you've pulled it into requirements.txt
         (check https://developers.zoom.us/docs/rtms/sdk/ for the current
         package name/API before deploying).
3. Everything downstream of "we got a finished audio chunk for participant
   X" (transcription, filler counting, scoring, persistence) is fully
   implemented and free/local -- see services/transcription.py,
   services/filler_words.py, services/scoring.py.
--------------------------------------------------------------------------
"""
import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from typing import Callable, Optional

ZOOM_WEBHOOK_SECRET_TOKEN = os.environ.get("ZOOM_WEBHOOK_SECRET_TOKEN", "")
ZOOM_CLIENT_ID = os.environ.get("ZOOM_CLIENT_ID", "")
ZOOM_CLIENT_SECRET = os.environ.get("ZOOM_CLIENT_SECRET", "")


def verify_zoom_webhook_signature(timestamp: str, raw_body: str, signature_header: str) -> bool:
    """Standard Zoom webhook verification, shared by every Zoom webhook
    (chat, meetings, RTMS events all use this same scheme):
        message      = f"v0:{timestamp}:{raw_body}"
        expected_sig = "v0=" + HMAC_SHA256(message, secret_token).hexdigest()
    Compare against the `x-zm-signature` header, constant-time.
    """
    if not ZOOM_WEBHOOK_SECRET_TOKEN:
        raise RuntimeError("ZOOM_WEBHOOK_SECRET_TOKEN is not configured")
    message = f"v0:{timestamp}:{raw_body}"
    digest = hmac.new(ZOOM_WEBHOOK_SECRET_TOKEN.encode(), message.encode(), hashlib.sha256).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature_header or "")


def handle_url_validation_challenge(plain_token: str) -> dict:
    """Zoom sends `endpoint.url_validation` once when you first save the
    webhook URL in the Marketplace app. Must echo back an encrypted token
    using the same HMAC scheme, or Zoom will refuse to activate the
    subscription."""
    encrypted = hmac.new(
        ZOOM_WEBHOOK_SECRET_TOKEN.encode(), plain_token.encode(), hashlib.sha256
    ).hexdigest()
    return {"plainToken": plain_token, "encryptedToken": encrypted}


@dataclass
class AudioTurn:
    """One finished, silence-terminated speaking turn, ready to hand to the
    transcription+scoring pipeline."""
    zoom_participant_name: str
    zoom_meeting_id: str
    wav_path: str
    duration_seconds: float


class RTMSClient:
    """Thin wrapper around the meeting's live media stream.

    on_turn_finished(AudioTurn) is called once per participant each time
    they finish speaking (VAD-detected silence gap), which is the unit this
    whole app scores -- one Table Topics answer, or one full prepared
    speech.
    """

    def __init__(self, meeting_uuid: str, rtms_stream_id: str,
                 server_urls: dict, on_turn_finished: Callable[[AudioTurn], None]):
        self.meeting_uuid = meeting_uuid
        self.rtms_stream_id = rtms_stream_id
        self.server_urls = server_urls
        self.on_turn_finished = on_turn_finished
        self._running = False

    def start(self):
        """Connect signaling + media websockets and start streaming.
        Replace the body of this method with a call into Zoom's official
        RTMS SDK client (see module docstring) -- this stub shows the shape
        of the callback contract the rest of the app relies on.
        """
        self._running = True
        self._connect_via_sdk()

    def _connect_via_sdk(self):
        raise NotImplementedError(
            "Wire up Zoom's official RTMS SDK here (developers.zoom.us/docs/rtms/sdk/). "
            "It should call self._on_participant_audio_turn(...) whenever a participant's "
            "turn ends, which forwards into the transcription/scoring pipeline."
        )

    def _on_participant_audio_turn(self, zoom_participant_name: str, wav_path: str, duration_seconds: float):
        turn = AudioTurn(
            zoom_participant_name=zoom_participant_name,
            zoom_meeting_id=self.meeting_uuid,
            wav_path=wav_path,
            duration_seconds=duration_seconds,
        )
        self.on_turn_finished(turn)

    def stop(self):
        self._running = False


# --- Registry of active RTMS clients, keyed by meeting UUID ---------------
_active_clients: dict[str, RTMSClient] = {}


def start_rtms_for_meeting(meeting_uuid: str, rtms_stream_id: str,
                            server_urls: dict, on_turn_finished: Callable[[AudioTurn], None]) -> RTMSClient:
    client = RTMSClient(meeting_uuid, rtms_stream_id, server_urls, on_turn_finished)
    _active_clients[meeting_uuid] = client
    client.start()
    return client


def stop_rtms_for_meeting(meeting_uuid: str):
    client = _active_clients.pop(meeting_uuid, None)
    if client:
        client.stop()

"""
Webhook endpoint that Zoom calls for RTMS lifecycle events. Configure this
URL (https://<your-host>/api/zoom/webhook) in your Zoom Marketplace app's
"Event Subscriptions" section, and add the RTMS scopes.

Flow:
  1. Zoom calls once with `endpoint.url_validation` when you save the URL --
     we must echo back the encrypted token (see services/zoom_rtms.py).
  2. When an active club meeting starts streaming, Zoom sends
     `meeting.rtms_started` with connection info -> we open an RTMSClient
     and register a callback that feeds finished speaking turns into the
     scoring pipeline (services/pipeline.py).
  3. `meeting.rtms_stopped` -> tear down the client.

See services/zoom_rtms.py for the parts that still need Zoom's official
SDK wired in before this is usable against a real meeting.
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db, SessionLocal
from ..services import zoom_rtms
from ..services.pipeline import process_turn
from ..services import transcription

router = APIRouter(prefix="/api/zoom", tags=["zoom"])

# Default Table Topics / speech targets used for turns arriving over RTMS.
# A real deployment would look this up per meeting agenda; kept simple here.
DEFAULT_TARGETS = {"table_topic": (60, 120), "speech": (300, 420)}


@router.post("/webhook")
async def zoom_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = (await request.body()).decode()
    payload = await request.json()
    event = payload.get("event")

    if event == "endpoint.url_validation":
        plain_token = payload["payload"]["plainToken"]
        return zoom_rtms.handle_url_validation_challenge(plain_token)

    timestamp = request.headers.get("x-zm-request-timestamp", "")
    signature = request.headers.get("x-zm-signature", "")
    if not zoom_rtms.verify_zoom_webhook_signature(timestamp, raw_body, signature):
        raise HTTPException(401, "Invalid Zoom webhook signature")

    if event == "meeting.rtms_started":
        obj = payload["payload"]["object"]
        meeting_uuid = obj["meeting_uuid"]
        rtms_stream_id = obj["rtms_stream_id"]
        server_urls = obj.get("server_urls", {})

        session = _find_or_create_session_for_meeting(db, meeting_uuid)

        def on_turn_finished(turn: zoom_rtms.AudioTurn):
            transcript = transcription.transcribe_audio_file(turn.wav_path)
            local_db = SessionLocal()
            try:
                target_min, target_max = DEFAULT_TARGETS["table_topic"]
                process_turn(
                    local_db,
                    session_id=session.id,
                    transcript=transcript,
                    duration_seconds=turn.duration_seconds,
                    speech_type="table_topic",
                    target_min_seconds=target_min,
                    target_max_seconds=target_max,
                    zoom_participant_name=turn.zoom_participant_name,
                )
            finally:
                local_db.close()

        zoom_rtms.start_rtms_for_meeting(meeting_uuid, rtms_stream_id, server_urls, on_turn_finished)

    elif event == "meeting.rtms_stopped":
        obj = payload["payload"]["object"]
        zoom_rtms.stop_rtms_for_meeting(obj["meeting_uuid"])

    return {"ok": True}


def _find_or_create_session_for_meeting(db: Session, meeting_uuid: str) -> models.MeetingSession:
    existing = (
        db.query(models.MeetingSession)
        .filter(models.MeetingSession.zoom_meeting_id == meeting_uuid, models.MeetingSession.status == "in_progress")
        .first()
    )
    if existing:
        return existing
    s = models.MeetingSession(title="Zoom meeting", zoom_meeting_id=meeting_uuid, status="in_progress")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s

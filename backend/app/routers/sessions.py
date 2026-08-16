import os
import tempfile
import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional

from .. import models, schemas
from ..database import get_db
from ..services.pipeline import process_turn
from ..services import transcription, email_service

router = APIRouter(prefix="/api", tags=["sessions"])


@router.post("/sessions", response_model=schemas.MeetingSessionOut)
def create_session(payload: schemas.SessionCreate, db: Session = Depends(get_db)):
    s = models.MeetingSession(title=payload.title, zoom_meeting_id=payload.zoom_meeting_id)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.get("/sessions", response_model=List[schemas.MeetingSessionOut])
def list_sessions(db: Session = Depends(get_db)):
    return db.query(models.MeetingSession).order_by(models.MeetingSession.date.desc()).all()


@router.post("/sessions/{session_id}/complete", response_model=schemas.MeetingSessionOut)
def complete_session(session_id: int, db: Session = Depends(get_db)):
    s = db.query(models.MeetingSession).get(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    s.status = "completed"
    db.commit()
    db.refresh(s)
    return s


@router.get("/sessions/{session_id}/speeches", response_model=List[schemas.SpeechOut])
def list_speeches(session_id: int, db: Session = Depends(get_db)):
    return (
        db.query(models.SpeechRecord)
        .filter(models.SpeechRecord.session_id == session_id)
        .order_by(models.SpeechRecord.created_at)
        .all()
    )


@router.post("/speeches/ingest", response_model=schemas.SpeechOut)
def ingest_speech(payload: schemas.SpeechIngest, db: Session = Depends(get_db)):
    """Manual / testing path: submit an already-transcribed speech (or a
    transcript you pasted yourself) for scoring. This is also what the Zoom
    RTMS pipeline calls internally once it has produced a transcript."""
    speech = process_turn(
        db,
        session_id=payload.session_id,
        transcript=payload.transcript,
        duration_seconds=payload.duration_seconds,
        speech_type=payload.speech_type,
        project_title=payload.project_title,
        target_min_seconds=payload.target_min_seconds,
        target_max_seconds=payload.target_max_seconds,
        zoom_participant_name=payload.speaker_name_raw,
        forced_participant_id=payload.participant_id,
    )
    return speech


@router.post("/speeches/ingest-audio", response_model=schemas.SpeechOut)
async def ingest_audio(
    session_id: int = Form(...),
    speech_type: str = Form("table_topic"),
    project_title: str = Form(""),
    target_min_seconds: int = Form(60),
    target_max_seconds: int = Form(120),
    speaker_name_raw: str = Form(""),
    participant_id: Optional[int] = Form(None),
    duration_seconds: Optional[float] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Audio-upload path: used by (a) the in-browser 'Start Listening'
    button (static/app.js), which records each turn as a webm/opus clip
    directly in the club member's browser tab -- no install needed -- and
    (b) the optional local listener script (listener/listen_and_score.py)
    for setups that prefer capturing raw system-audio loopback outside the
    browser. Transcription happens locally (free, no per-minute API cost)
    purely to count filler words / pace / duration -- the transcript itself
    is not the point and is de-emphasized in the UI.

    Speaker attribution priority: explicit participant_id/speaker_name_raw
    from the caller > the session's manually-set 'current speaker' (set from
    the dashboard right before each turn) > automatic name-detection from
    the audio itself.

    duration_seconds: browser recordings (webm/opus) don't have a duration
    that's cheap to read server-side without extra dependencies, so the
    caller can pass it directly (the browser already timed the turn). Falls
    back to reading it from the file itself (works for plain WAV, e.g. from
    the Python listener or a manual .wav upload) when omitted."""
    suffix = os.path.splitext(file.filename or "audio.wav")[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        transcript = transcription.transcribe_audio_file(tmp_path)
        if duration_seconds is not None:
            duration = duration_seconds
        else:
            try:
                duration = transcription.wav_duration_seconds(tmp_path)
            except Exception:
                duration = 0.0
    finally:
        os.unlink(tmp_path)

    speech = process_turn(
        db,
        session_id=session_id,
        transcript=transcript,
        duration_seconds=duration,
        speech_type=speech_type,
        project_title=project_title,
        target_min_seconds=target_min_seconds,
        target_max_seconds=target_max_seconds,
        zoom_participant_name=speaker_name_raw,
        forced_participant_id=participant_id,
    )
    return speech


@router.post("/sessions/{session_id}/current-speaker", response_model=schemas.CurrentSpeakerOut)
def set_current_speaker(session_id: int, payload: schemas.CurrentSpeakerSet, db: Session = Depends(get_db)):
    """Called from the dashboard's 'Now speaking: ...' control right before
    each Table Topics answer / speech. The local audio listener checks this
    before uploading a finished turn, so speaker attribution doesn't have to
    rely purely on name-detection from the audio."""
    s = db.query(models.MeetingSession).get(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    s.current_speaker_id = payload.participant_id
    db.commit()
    name = None
    if s.current_speaker_id:
        p = db.query(models.Participant).get(s.current_speaker_id)
        name = p.name if p else None
    return schemas.CurrentSpeakerOut(participant_id=s.current_speaker_id, name=name)


@router.get("/sessions/{session_id}/current-speaker", response_model=schemas.CurrentSpeakerOut)
def get_current_speaker(session_id: int, db: Session = Depends(get_db)):
    s = db.query(models.MeetingSession).get(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    name = None
    if s.current_speaker_id:
        p = db.query(models.Participant).get(s.current_speaker_id)
        name = p.name if p else None
    return schemas.CurrentSpeakerOut(participant_id=s.current_speaker_id, name=name)


@router.post("/speeches/{speech_id}/send-email", response_model=schemas.EvaluationOut)
def send_speech_feedback_email(speech_id: int, db: Session = Depends(get_db)):
    """Emails ONLY this speech's own evaluation to the matched participant's
    own email address -- never a group email. Requires SMTP_* env vars
    (see services/email_service.py for free Gmail setup)."""
    speech = db.query(models.SpeechRecord).get(speech_id)
    if not speech or not speech.evaluation:
        raise HTTPException(404, "Speech or evaluation not found")
    if not speech.participant:
        raise HTTPException(400, "This speech isn't matched to a roster participant yet -- assign a speaker first.")
    if not speech.participant.email:
        raise HTTPException(400, f"{speech.participant.name} has no email address on file.")

    try:
        email_service.send_feedback_email(
            speech.participant.email, speech.participant.name, speech, speech.evaluation
        )
    except email_service.EmailNotConfigured as e:
        raise HTTPException(500, str(e))

    speech.evaluation.email_sent = True
    speech.evaluation.email_sent_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(speech.evaluation)
    return speech.evaluation


@router.get("/participants/{participant_id}/trend", response_model=List[schemas.TrendPoint])
def participant_trend(participant_id: int, db: Session = Depends(get_db)):
    speeches = (
        db.query(models.SpeechRecord)
        .filter(models.SpeechRecord.participant_id == participant_id)
        .order_by(models.SpeechRecord.created_at)
        .all()
    )
    points = []
    for sp in speeches:
        if not sp.evaluation:
            continue
        points.append(
            schemas.TrendPoint(
                speech_id=sp.id,
                date=sp.created_at,
                score_total=sp.evaluation.score_total,
                filler_rate_per_100_words=sp.filler_rate_per_100_words,
                speech_type=sp.speech_type,
            )
        )
    return points

"""
Glue layer: turns a raw (transcript, duration, speaker hint) tuple into
persisted SpeechRecord + Evaluation rows.

Used by:
  - routers/zoom_webhook.py, via RTMSClient.on_turn_finished, for the live path.
  - routers/sessions.py `/speeches/ingest`, for manually-uploaded audio or a
    pasted transcript (handy for testing, or for clubs not yet wired to RTMS).
"""
from sqlalchemy.orm import Session as DBSession

from .. import models
from .scoring import score_speech
from .speaker_id import identify_speaker_from_transcript, match_zoom_display_name


def process_turn(
    db: DBSession,
    session_id: int,
    transcript: str,
    duration_seconds: float,
    speech_type: str = "table_topic",
    project_title: str = "",
    target_min_seconds: int = 60,
    target_max_seconds: int = 120,
    zoom_participant_name: str = "",
    forced_participant_id: int | None = None,
) -> models.SpeechRecord:
    participants = db.query(models.Participant).filter(models.Participant.active == True).all()  # noqa: E712

    participant_id = forced_participant_id
    raw_name = zoom_participant_name

    # Priority 2: the session's manually-set "current speaker" (dashboard
    # "Now speaking: ..." control, or Zoom's own display name if it ever
    # comes through zoom_participant_name).
    if participant_id is None and zoom_participant_name:
        participant_id = match_zoom_display_name(zoom_participant_name, participants)

    if participant_id is None:
        session = db.query(models.MeetingSession).get(session_id)
        if session and session.current_speaker_id:
            participant_id = session.current_speaker_id
            if not raw_name:
                p = next((p for p in participants if p.id == participant_id), None)
                raw_name = p.name if p else raw_name

    # Priority 3: automatic name-detection from the transcript itself
    # ("Hi, my name is..." / "let's hear from...").
    if participant_id is None:
        matched_id, candidate_name = identify_speaker_from_transcript(transcript, participants)
        participant_id = matched_id
        raw_name = raw_name or candidate_name

    result = score_speech(transcript, duration_seconds, target_min_seconds, target_max_seconds)

    speech = models.SpeechRecord(
        session_id=session_id,
        participant_id=participant_id,
        speaker_name_raw=raw_name,
        speech_type=speech_type,
        project_title=project_title,
        target_min_seconds=target_min_seconds,
        target_max_seconds=target_max_seconds,
        duration_seconds=duration_seconds,
        transcript=transcript,
        word_count=result.word_count,
        words_per_minute=result.wpm,
        filler_counts=result.filler_counts,
        filler_total=result.filler_total,
        filler_rate_per_100_words=result.filler_rate_per_100_words,
    )
    db.add(speech)
    db.flush()  # get speech.id

    evaluation = models.Evaluation(
        speech_id=speech.id,
        score_total=result.score_total,
        score_filler=result.score_filler,
        score_pace=result.score_pace,
        score_time_management=result.score_time_management,
        score_structure=result.score_structure,
        feedback_text=result.feedback_text,
        strengths=result.strengths,
        recommendations=result.recommendations,
        engine="rule_based",
    )
    db.add(evaluation)
    db.commit()
    db.refresh(speech)
    return speech

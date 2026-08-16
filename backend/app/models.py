"""
SQLAlchemy ORM models.

Participant   - a club member, entered manually once, persists forever.
MeetingSession- one Zoom meeting (a club meeting).
SpeechRecord  - one "turn at the microphone": a prepared Speech or a single
                Table Topics answer. Belongs to a session and (once matched)
                to a participant.
Evaluation    - the scored feedback produced for a SpeechRecord. Kept as its
                own table (rather than columns on SpeechRecord) so history /
                re-scoring is possible without losing the raw transcript.
"""
import datetime
import enum
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, ForeignKey, Enum, JSON, Boolean
)
from sqlalchemy.orm import relationship

from .database import Base


class SpeechType(str, enum.Enum):
    TABLE_TOPIC = "table_topic"
    SPEECH = "speech"


class Participant(Base):
    __tablename__ = "participants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    # comma-separated alternate names/nicknames the STT might catch
    # e.g. "Yonatan" -> aliases "Yoni, Jonathan"
    aliases = Column(String, default="")
    email = Column(String, default="")
    club_role = Column(String, default="member")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    speeches = relationship("SpeechRecord", back_populates="participant")


class MeetingSession(Base):
    __tablename__ = "meeting_sessions"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, default="")
    zoom_meeting_id = Column(String, default="")
    date = Column(DateTime, default=datetime.datetime.utcnow)
    status = Column(String, default="in_progress")  # in_progress | completed

    # Manually set from the dashboard ("Now speaking: ...") right before each
    # turn. The local listener checks this before uploading a finished audio
    # segment so speaker attribution doesn't have to rely purely on
    # name-detection from the transcript. Left null -> auto-detect.
    current_speaker_id = Column(Integer, ForeignKey("participants.id"), nullable=True)

    speeches = relationship("SpeechRecord", back_populates="session")


class SpeechRecord(Base):
    __tablename__ = "speech_records"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("meeting_sessions.id"))
    participant_id = Column(Integer, ForeignKey("participants.id"), nullable=True)
    speaker_name_raw = Column(String, default="")  # name as detected, even if unmatched

    speech_type = Column(Enum(SpeechType), default=SpeechType.TABLE_TOPIC)
    project_title = Column(String, default="")  # e.g. "Ice Breaker", pathways project name
    target_min_seconds = Column(Integer, default=60)   # TT default 1:00
    target_max_seconds = Column(Integer, default=120)  # TT default 2:00

    start_time = Column(DateTime, default=datetime.datetime.utcnow)
    duration_seconds = Column(Float, default=0.0)

    transcript = Column(Text, default="")
    word_count = Column(Integer, default=0)
    words_per_minute = Column(Float, default=0.0)

    filler_counts = Column(JSON, default=dict)   # {"um": 3, "like": 2, ...}
    filler_total = Column(Integer, default=0)
    filler_rate_per_100_words = Column(Float, default=0.0)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    session = relationship("MeetingSession", back_populates="speeches")
    participant = relationship("Participant", back_populates="speeches")
    evaluation = relationship("Evaluation", back_populates="speech", uselist=False)


class Evaluation(Base):
    __tablename__ = "evaluations"

    id = Column(Integer, primary_key=True, index=True)
    speech_id = Column(Integer, ForeignKey("speech_records.id"), unique=True)

    score_total = Column(Float, default=0.0)  # 0-10 composite
    score_filler = Column(Float, default=0.0)
    score_pace = Column(Float, default=0.0)
    score_time_management = Column(Float, default=0.0)
    score_structure = Column(Float, default=0.0)

    feedback_text = Column(Text, default="")   # auto-generated Toastmasters-style feedback
    strengths = Column(JSON, default=list)
    recommendations = Column(JSON, default=list)

    engine = Column(String, default="rule_based")  # rule_based | llm
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    email_sent = Column(Boolean, default=False)
    email_sent_at = Column(DateTime, nullable=True)

    speech = relationship("SpeechRecord", back_populates="evaluation")

"""Pydantic request/response models."""
from datetime import datetime
from typing import Optional, Dict, List
from pydantic import BaseModel


class ParticipantBase(BaseModel):
    name: str
    aliases: str = ""
    email: str = ""
    club_role: str = "member"


class ParticipantCreate(ParticipantBase):
    pass


class ParticipantUpdate(BaseModel):
    name: Optional[str] = None
    aliases: Optional[str] = None
    email: Optional[str] = None
    club_role: Optional[str] = None
    active: Optional[bool] = None


class Participant(ParticipantBase):
    id: int
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class SessionCreate(BaseModel):
    title: str = ""
    zoom_meeting_id: str = ""


class MeetingSessionOut(BaseModel):
    id: int
    title: str
    zoom_meeting_id: str
    date: datetime
    status: str
    current_speaker_id: Optional[int] = None

    class Config:
        from_attributes = True


class SpeechIngest(BaseModel):
    """Payload used to submit a finished speech/table-topic turn for scoring.
    This is what both the Zoom RTMS pipeline and a manual file-upload path feed into.
    """
    session_id: int
    speaker_name_raw: str = ""
    participant_id: Optional[int] = None
    speech_type: str = "table_topic"  # or "speech"
    project_title: str = ""
    target_min_seconds: int = 60
    target_max_seconds: int = 120
    duration_seconds: float
    transcript: str


class EvaluationOut(BaseModel):
    id: int
    score_total: float
    score_filler: float
    score_pace: float
    score_time_management: float
    score_structure: float
    feedback_text: str
    strengths: List[str]
    recommendations: List[str]
    engine: str
    created_at: datetime
    email_sent: bool = False
    email_sent_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CurrentSpeakerSet(BaseModel):
    participant_id: Optional[int] = None


class CurrentSpeakerOut(BaseModel):
    participant_id: Optional[int] = None
    name: Optional[str] = None


class SpeechOut(BaseModel):
    id: int
    session_id: int
    participant_id: Optional[int]
    speaker_name_raw: str
    speech_type: str
    project_title: str
    duration_seconds: float
    transcript: str
    word_count: int
    words_per_minute: float
    filler_counts: Dict[str, int]
    filler_total: int
    filler_rate_per_100_words: float
    created_at: datetime
    evaluation: Optional[EvaluationOut] = None

    class Config:
        from_attributes = True


class TrendPoint(BaseModel):
    speech_id: int
    date: datetime
    score_total: float
    filler_rate_per_100_words: float
    speech_type: str

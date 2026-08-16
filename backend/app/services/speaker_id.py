"""
Speaker identification / name matching.

Real-time flow this supports:
  1. Zoom RTMS gives us per-participant audio tracks tagged with the Zoom
     display name of whoever is unmuted (see services/zoom_rtms.py). That is
     the *first* and most reliable signal -- if Zoom's own participant label
     matches (or fuzzy-matches) a roster name, we're done.
  2. If RTMS only gives an anonymous/merged audio track (e.g. dial-in
     participants, or a single-track fallback), we fall back to spotting a
     name inside the transcript itself -- either the speaker introducing
     themselves ("Hi, I'm Dana...") or the Toastmaster/Topicsmaster calling on
     them ("...let's hear from David").

This module implements fallback #2 plus fuzzy matching used by both paths,
so a slightly garbled STT transcription of a name still matches the roster
(e.g. "Yonatan" heard as "Yonathan").
"""
import re
from typing import List, Optional, Tuple

from rapidfuzz import fuzz

SELF_INTRO_PATTERNS = [
    r"\bmy name is ([A-Z][a-zA-Z'\-]+)",
    r"\bi'?m ([A-Z][a-zA-Z'\-]+)\b",
    r"\bthis is ([A-Z][a-zA-Z'\-]+)\b",
]
CALLED_ON_PATTERNS = [
    r"let'?s (?:hear|welcome) (?:from |)([A-Z][a-zA-Z'\-]+)",
    r"(?:next up|up next)(?:,|:| is)? ([A-Z][a-zA-Z'\-]+)",
    r"come on up,? ([A-Z][a-zA-Z'\-]+)",
    r"over to you,? ([A-Z][a-zA-Z'\-]+)",
]

FUZZY_MATCH_THRESHOLD = 82  # 0-100, rapidfuzz partial_ratio


def _candidate_names_from_text(text: str) -> List[str]:
    found = []
    for pat in SELF_INTRO_PATTERNS + CALLED_ON_PATTERNS:
        for m in re.finditer(pat, text):
            found.append(m.group(1))
    return found


def _all_known_names(participants) -> List[Tuple[int, str]]:
    """Flatten (participant_id, name_or_alias) pairs, including aliases."""
    pairs = []
    for p in participants:
        pairs.append((p.id, p.name))
        for alias in (p.aliases or "").split(","):
            alias = alias.strip()
            if alias:
                pairs.append((p.id, alias))
    return pairs


def match_name_to_participant(candidate: str, participants) -> Optional[int]:
    """Fuzzy-match a single candidate name string against the roster.
    Returns participant_id of the best match above threshold, else None.
    """
    best_id, best_score = None, 0
    for pid, known in _all_known_names(participants):
        # token_set_ratio lets a first-name-only mention ("Dana") match a
        # full-name roster entry ("Dana Cohen"); plain ratio catches close
        # misspellings of a full match. We take whichever is more confident.
        score = max(
            fuzz.ratio(candidate.lower(), known.lower()),
            fuzz.token_set_ratio(candidate.lower(), known.lower()),
        )
        if score > best_score:
            best_score, best_id = score, pid
    if best_score >= FUZZY_MATCH_THRESHOLD:
        return best_id
    return None


def identify_speaker_from_transcript(transcript: str, participants) -> Tuple[Optional[int], str]:
    """Best-effort speaker identification purely from transcript text.
    Returns (participant_id_or_None, raw_name_candidate_or_empty_string).
    Prefer self-introductions over "called on by" mentions.
    """
    self_intro_hits = []
    for pat in SELF_INTRO_PATTERNS:
        self_intro_hits += re.findall(pat, transcript)
    for name in self_intro_hits:
        pid = match_name_to_participant(name, participants)
        if pid:
            return pid, name

    called_on_hits = []
    for pat in CALLED_ON_PATTERNS:
        called_on_hits += re.findall(pat, transcript)
    for name in called_on_hits:
        pid = match_name_to_participant(name, participants)
        if pid:
            return pid, name

    all_candidates = self_intro_hits + called_on_hits
    return None, (all_candidates[0] if all_candidates else "")


def match_zoom_display_name(zoom_name: str, participants) -> Optional[int]:
    """Path #1: Zoom already told us the display name of the unmuted
    participant via RTMS. Just fuzzy-match it to the roster."""
    if not zoom_name:
        return None
    return match_name_to_participant(zoom_name, participants)

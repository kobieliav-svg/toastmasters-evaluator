"""
Quick sanity tests for the scoring engine -- run with: pytest
These don't touch the DB or Whisper; they test the pure-Python rubric logic
in services/scoring.py and services/filler_words.py directly.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.scoring import score_speech
from app.services.filler_words import count_filler_words


def test_filler_counting_basic():
    text = "Um, so, like, I mean, this is, uh, you know, kind of a test."
    counts, total = count_filler_words(text)
    assert total > 0
    assert counts.get("um", 0) == 1
    assert counts.get("uh", 0) == 1
    assert counts.get("you know", 0) == 1


def test_clean_speech_scores_high():
    transcript = (
        "Imagine standing on a stage for the first time. That was me, three years ago. "
        "Today I want to share three lessons I learned about public speaking: "
        "preparation, practice, and presence. First, preparation means knowing your material "
        "cold. Second, practice means rehearsing out loud, not just in your head. "
        "Third, presence means connecting with your audience through eye contact and pauses. "
        "In conclusion, the next time you're nervous before speaking, remember these three lessons "
        "and step forward with confidence. Thank you."
    )
    # ~95 words at a natural pace over 40 seconds -> decent wpm
    result = score_speech(transcript, duration_seconds=40, target_min_seconds=30, target_max_seconds=60)
    assert result.score_total >= 6.0
    assert result.filler_total == 0


def test_filler_heavy_speech_scores_lower_on_filler():
    transcript = "Um, so, like, uh, you know, I mean, um, it was, uh, like, sort of, um, good, I guess."
    clean = "This was a genuinely good experience for our whole team this quarter."
    r_filler = score_speech(transcript, duration_seconds=20, target_min_seconds=15, target_max_seconds=30)
    r_clean = score_speech(clean, duration_seconds=20, target_min_seconds=15, target_max_seconds=30)
    assert r_filler.score_filler < r_clean.score_filler


def test_overtime_hurts_time_management_score():
    transcript = "word " * 200
    on_time = score_speech(transcript, duration_seconds=90, target_min_seconds=60, target_max_seconds=120)
    over_time = score_speech(transcript, duration_seconds=240, target_min_seconds=60, target_max_seconds=120)
    assert on_time.score_time_management > over_time.score_time_management


if __name__ == "__main__":
    test_filler_counting_basic()
    test_clean_speech_scores_high()
    test_filler_heavy_speech_scores_lower_on_filler()
    test_overtime_hurts_time_management_score()
    print("All scoring tests passed.")

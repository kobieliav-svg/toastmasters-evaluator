"""
Rule-based, 100% local/free scoring engine written in the spirit of the
Toastmasters evaluation rubric:

  - Time management  (Table Topics 1-2 min / Speech project time, judged the
                       way a Toastmasters timer's green/yellow/red works)
  - Filler words      (the "Ah-Counter" role)
  - Pace              (words per minute)
  - Structure         (recognizable opening hook + closing / call-to-action)

Each sub-score is 0-10. The composite score is a weighted average, and the
function also produces short, constructive, Toastmasters-style feedback text
(specific, balanced between strength and recommendation, never harsh).

No paid API calls are made anywhere in this module. An optional LLM-based
"richer narrative feedback" layer can be plugged in later (see
services/llm_feedback.py.example in the README) but is OFF by default to
respect a no-cost-per-speech default.
"""
from dataclasses import dataclass, field
from typing import List, Dict

from .filler_words import count_filler_words, words_per_minute, word_count

WEIGHTS = {
    "filler": 0.30,
    "pace": 0.25,
    "time": 0.25,
    "structure": 0.20,
}

OPENING_HOOKS = [
    "imagine", "have you ever", "what if", "picture this", "let me tell you",
    "did you know", "how many of you", "years ago", "one day", "recently",
]
CLOSING_MARKERS = [
    "in conclusion", "to conclude", "thank you", "in summary", "to sum up",
    "so remember", "let's", "i challenge you", "the next time",
]


@dataclass
class ScoreResult:
    score_total: float
    score_filler: float
    score_pace: float
    score_time_management: float
    score_structure: float
    feedback_text: str
    strengths: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    filler_counts: Dict[str, int] = field(default_factory=dict)
    filler_total: int = 0
    filler_rate_per_100_words: float = 0.0
    word_count: int = 0
    wpm: float = 0.0


def _score_filler(rate_per_100: float) -> float:
    # 0 fillers/100 words -> 10.  ~10/100 -> ~5.  20+/100 -> 0.
    if rate_per_100 <= 0:
        return 10.0
    score = 10.0 - (rate_per_100 * 0.5)
    return max(0.0, min(10.0, round(score, 1)))


def _score_pace(wpm: float) -> float:
    if wpm <= 0:
        return 0.0
    ideal_low, ideal_high = 120, 160
    if ideal_low <= wpm <= ideal_high:
        return 10.0
    if wpm < ideal_low:
        deficit = ideal_low - wpm
        return max(0.0, round(10 - deficit * 0.15, 1))
    excess = wpm - ideal_high
    return max(0.0, round(10 - excess * 0.15, 1))


def _score_time(duration_s: float, target_min: int, target_max: int) -> float:
    # Mirrors the TM timer: green zone = full marks. Grace zone (30s under/over
    # for speeches, 15s for short table topics) tapers the score. Big misses
    # (well under min, or disqualifying overtime) score low.
    grace = max(15, int((target_max - target_min) * 0.25))
    if target_min <= duration_s <= target_max:
        return 10.0
    if duration_s < target_min:
        deficit = target_min - duration_s
        if deficit <= grace:
            return round(10 - (deficit / grace) * 3, 1)
        return max(0.0, round(7 - (deficit - grace) * 0.1, 1))
    excess = duration_s - target_max
    if excess <= grace:
        return round(10 - (excess / grace) * 3, 1)
    return max(0.0, round(7 - (excess - grace) * 0.15, 1))


def _score_structure(transcript: str) -> float:
    text = transcript.lower()
    n = len(text)
    if n < 20:
        return 0.0
    opening_window = text[: max(1, int(n * 0.2))]
    closing_window = text[-max(1, int(n * 0.2)):]
    has_open = any(h in opening_window for h in OPENING_HOOKS)
    has_close = any(c in closing_window for c in CLOSING_MARKERS)
    score = 4.0  # base credit for simply having content
    if has_open:
        score += 3.0
    if has_close:
        score += 3.0
    return round(min(10.0, score), 1)


def score_speech(transcript: str, duration_seconds: float,
                  target_min_seconds: int, target_max_seconds: int) -> ScoreResult:
    filler_counts, filler_total = count_filler_words(transcript)
    wc = word_count(transcript)
    wpm = words_per_minute(wc, duration_seconds)
    filler_rate = round((filler_total / wc) * 100, 1) if wc else 0.0

    s_filler = _score_filler(filler_rate)
    s_pace = _score_pace(wpm)
    s_time = _score_time(duration_seconds, target_min_seconds, target_max_seconds)
    s_structure = _score_structure(transcript)

    total = (
        s_filler * WEIGHTS["filler"]
        + s_pace * WEIGHTS["pace"]
        + s_time * WEIGHTS["time"]
        + s_structure * WEIGHTS["structure"]
    )
    total = round(total, 1)

    strengths, recs = _build_feedback(
        s_filler, s_pace, s_time, s_structure, filler_rate, wpm,
        duration_seconds, target_min_seconds, target_max_seconds, filler_counts
    )
    feedback_text = _render_feedback_text(total, strengths, recs)

    return ScoreResult(
        score_total=total,
        score_filler=s_filler,
        score_pace=s_pace,
        score_time_management=s_time,
        score_structure=s_structure,
        feedback_text=feedback_text,
        strengths=strengths,
        recommendations=recs,
        filler_counts=filler_counts,
        filler_total=filler_total,
        filler_rate_per_100_words=filler_rate,
        word_count=wc,
        wpm=wpm,
    )


def _build_feedback(s_filler, s_pace, s_time, s_structure, filler_rate, wpm,
                     duration_s, target_min, target_max, filler_counts):
    strengths, recs = [], []

    if s_filler >= 8:
        strengths.append("Very clean delivery — almost no filler words or crutch phrases.")
    elif s_filler < 5:
        top = sorted(filler_counts.items(), key=lambda kv: -kv[1])[:3]
        top_str = ", ".join(f"\"{w}\" x{c}" for w, c in top) if top else "filler words"
        recs.append(f"Watch your filler words ({top_str}). Try pausing silently instead of filling the gap.")

    if s_pace >= 8:
        strengths.append(f"Great pacing at {wpm} words/min — easy to follow.")
    elif wpm and wpm < 120:
        recs.append(f"Your pace was {wpm} wpm, a bit slow — adding a touch more energy could increase engagement.")
    elif wpm and wpm > 160:
        recs.append(f"Your pace was {wpm} wpm, quite fast — slowing down slightly will help the audience absorb key points.")

    if s_time >= 8:
        strengths.append("Excellent time management, right in the target window.")
    elif duration_s < target_min:
        recs.append(f"You finished under time ({int(duration_s)}s vs a {target_min}-{target_max}s target) — develop your content a bit further.")
    else:
        recs.append(f"You went over the target time ({int(duration_s)}s vs a {target_min}-{target_max}s target) — tighten your content to stay in the window.")

    if s_structure >= 7:
        strengths.append("Clear structure with a recognizable opening and closing.")
    else:
        recs.append("Strengthen your structure: open with a hook (a question, image, or story) and close with a clear takeaway or call to action.")

    if not strengths:
        strengths.append("You got up and spoke — that takes courage, and it's how every strong speaker improves.")

    return strengths, recs


def _render_feedback_text(total, strengths, recs) -> str:
    lines = [f"Overall score: {total}/10", "", "What worked well:"]
    lines += [f"  + {s}" for s in strengths]
    lines += ["", "Recommendations for next time:"]
    lines += [f"  - {r}" for r in recs]
    return "\n".join(lines)

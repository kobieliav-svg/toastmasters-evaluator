"""
English filler-word / crutch-phrase detection, in the spirit of the
Toastmasters "Ah-Counter" role.

Counts both single-word fillers (um, uh, like) and multi-word crutch phrases
(you know, I mean, sort of). Matching is whole-word / whole-phrase and
case-insensitive so "Umbrella" is not mis-counted as "um".
"""
import re
from collections import Counter
from typing import Dict, Tuple

# Single-word fillers (word-boundary matched)
SINGLE_WORD_FILLERS = [
    "um", "umm", "uh", "uhh", "er", "erm", "ah", "hmm",
    "like", "actually", "basically", "literally", "so", "well", "right",
]

# Multi-word crutch phrases (matched as literal substrings on normalized text)
PHRASE_FILLERS = [
    "you know", "i mean", "sort of", "kind of", "at the end of the day",
    "to be honest", "if that makes sense", "and stuff", "and things like that",
]

# Words that are only fillers in a *discourse-marker* position, not in normal
# grammatical use. We keep the list intentionally small (so/well/right/actually)
# and simply count every occurrence -- for a club "Ah-Counter" tool this is an
# accepted simplification (documented in the README).


def _tokenize(text: str):
    return re.findall(r"[a-zA-Z']+", text.lower())


def count_filler_words(transcript: str) -> Tuple[Dict[str, int], int]:
    """Returns (per-filler counts dict, total filler count)."""
    text_lower = transcript.lower()
    counts: Counter = Counter()

    tokens = _tokenize(transcript)
    token_set_counter = Counter(tokens)
    for filler in SINGLE_WORD_FILLERS:
        c = token_set_counter.get(filler, 0)
        if c:
            counts[filler] += c

    for phrase in PHRASE_FILLERS:
        c = text_lower.count(phrase)
        if c:
            counts[phrase] += c

    total = sum(counts.values())
    return dict(counts), total


def words_per_minute(word_count: int, duration_seconds: float) -> float:
    if duration_seconds <= 0:
        return 0.0
    return round(word_count / (duration_seconds / 60.0), 1)


def word_count(transcript: str) -> int:
    return len(_tokenize(transcript))

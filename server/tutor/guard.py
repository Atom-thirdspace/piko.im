import os
import re
from datetime import timedelta

from ..models import _utcnow, tutor_calls_since

MAX_QUESTION = 500
MIN_QUESTION = 5
DEFAULT_HOURLY_LIMIT = 30

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_SUSPICIOUS = (
    "ignore previous", "ignore all previous", "disregard the above",
    "system prompt", "your instructions", "you are now", "jailbreak",
    "pretend you are", "developer mode",
)

def hourly_limit():
    try:
        return int(os.environ.get("TUTOR_HOURLY_LIMIT", DEFAULT_HOURLY_LIMIT))
    except ValueError:
        return DEFAULT_HOURLY_LIMIT


def clean_question(raw):
    text = _CONTROL.sub("", (raw or "")).strip()
    return re.sub(r"\s+", " ", text)[:MAX_QUESTION]


def looks_suspicious(question):
    low = question.lower()
    return any(marker in low for marker in _SUSPICIOUS)

def check(user, question):
    """Returns (error, http_status), or (None, None) when the call may proceed.
    A malformed question is a 400; only the rate limit is a 429."""
    if len(question) < MIN_QUESTION:
        return "Ask a fuller question than that.", 400

    used = tutor_calls_since(user, _utcnow() - timedelta(hours=1))
    if used >= hourly_limit():
        return ("You've used your %d tutor questions for this hour. "
                "It resets shortly." % hourly_limit()), 429
    return None, None
import os
import requests

DEFAULT_BASE = "https://ai.hackclub.com/proxy/v1"
DEFAULT_MODEL = "gpt-5-mini"

class TutorError(Exception):
    """Anything the user should see as a polite failure, not a 500."""


def config():
    key = (os.environ.get("HACKCLUB_AI_KEY") or "").strip()
    if not key:
        raise TutorError("The tutor isn't switched on yet.")
    return (
        key,
        (os.environ.get("HACKCLUB_AI_BASE") or DEFAULT_BASE).rstrip("/"),
        (os.environ.get("TUTOR_MODEL") or DEFAULT_MODEL).strip(),
    )

def is_configured():
    return bool((os.environ.get("HACKCLUB_AI_KEY") or "").strip())

def ask(system, user, max_tokens=600, timeout=30):
    key, base, model = config()

    try:
        resp = requests.post(
            base + "/chat/completions",
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json"},
            json={
                "model": model,
                "max_tokens": max_tokens,
                "temperature": 0.3,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=timeout,
        )
    except requests.Timeout:
        raise TutorError("The tutor took too long to answer. Try again.")
    except requests.RequestException:
        raise TutorError("Couldn't reach the tutor right now.")

    if resp.status_code == 429:
        raise TutorError("The tutor is busy right now. Give it a minute.")
    if resp.status_code >= 400:
        # Never surface the upstream body - it can echo the prompt back.
        raise TutorError("The tutor had a problem answering that.")

    try:
        data = resp.json()
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (ValueError, KeyError, IndexError):
        raise TutorError("The tutor sent back something unreadable.")

    if not text:
        raise TutorError("The tutor didn't have an answer for that one.")
    return text, model
import re

_SPACE = re.compile(r"\s+")
_TRAILING = ".,;!"

_LETTERS = {"\u0398": "o", "\u03b8": "o", "\u039f": "o", "\u03bf": "o"}

MAX_ANSWER = 120

def canon(text):
    out = (text or "").strip().lower()
    for src, dst in _LETTERS.items():
        out = out.replace(src, dst)
    out = out.replace("\u00d7", "*").replace("\u00b7", "*")
    out = out.replace("**", "^")
    out = out.replace("*", "").replace("^", "").replace("_", "")
    out = _SPACE.sub("", out)
    return out.rstrip(_TRAILING)

def accepted(question):
    forms = [question.answer] + list(question.alternates or [])
    return {canon(f) for f in forms if (f or "").strip()}

def is_correct(question, given):
    if not given or len(given) > MAX_ANSWER:
        return False
    return canon(given) in accepted(question)

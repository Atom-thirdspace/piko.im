import re

from ..output import amber, bold, dim, green, red
from .screen import RESET

ANSI = re.compile(r"\033\[[0-9;]*m")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
TICKS = re.compile(r"`([^`]+)`")
STARS = re.compile(r"\*\*([^*]+)\*\*")

def plain(text):
    return ANSI.sub("", text or "")

def width(text):
    return len(plain(text))


def fit(text, size):
    if size <= 0:
        return ""
    have = width(text)
    if have == size:
        return text
    if have < size:
        return text + " " * (size - have)

    out, seen, i = [], 0, 0
    while i < len(text) and seen < size - 1:
        match = ANSI.match(text, i)
        if match:
            out.append(match.group(0))
            i = match.end()
            continue
        out.append(text[i])
        seen += 1
        i += 1
    return "".join(out) + RESET + "\u2026"

def wrap(text, size):
    out, fenced = [], False
    for line in (text or "").splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            out.append((line, True))
            continue
        if not line.strip():
            out.append(("", False))
            continue
        row = ""
        for word in line.split():
            if row and len(row) + 1 + len(word) > size:
                out.append((row, False))
                row = word
            else:
                row = (row + " " + word) if row else word
        out.append((row, False))
    return out

def style(line, code=False):
    if code:
        return amber(line)
    match = HEADING.match(line)
    if match:
        return bold(match.group(2))
    line = TICKS.sub(lambda m: amber(m.group(1)), line)
    return STARS.sub(lambda m: bold(m.group(1)), line)


def bar(fraction, size):
    filled = int(round(max(0.0, min(1.0, fraction)) * size))
    return green("\u2588" * filled) + dim("\u2591" * (size - filled))


def _spaced(text):
    rows = []
    for line in (text or "").split("\n"):
        stripped = line.rstrip()
        rows.append(stripped + dim("\u00b7" * (len(line) - len(stripped))))
    while rows and rows[-1] == "":
        rows.pop()
    return rows

def diff_lines(expected, got, size):
    half = max(8, (size - 3) // 2)
    left, right = _spaced(expected), _spaced(got)
    out = [fit(bold("expected"), half) + dim(" \u2502 ") + bold("got")]
    for i in range(max(len(left), len(right))):
        a = left[i] if i < len(left) else ""
        b = right[i] if i < len(right) else dim("(nothing)")
        same = plain(a) == plain(b)
        out.append(fit(a, half) + dim(" \u2502 ")
                   + fit(b if same else red(plain(b)), half))
    return out
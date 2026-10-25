import os
import sys

JSON = False

class Fail(Exception):
    """Anything the user should see as a message, not a traceback."""


def _tty():
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _paint(code, text):
    return "\033[%sm%s\033[0m" % (code, text) if _tty() else text


def bold(t):  return _paint("1", t)
def dim(t):   return _paint("2", t)
def green(t): return _paint("32", t)
def red(t):   return _paint("31", t)
def amber(t): return _paint("33", t)

DIFFICULTY = {"easy": green, "medium": amber, "hard": red}

def difficulty(name):
    return DIFFICULTY.get(name, dim)(name or "-")

def header(text):
    print()
    print(bold(text))
    print(dim("-" * len(text)))

def row(*cells):
    print("  " + "  ".join(cells))

def ok(text):
    print(green(" ok ") + text)

def bad(text):
    print(red("  fail")+ "  " + text)

def note(text):
    print(dim("  " + text))
    
def visible(text):
    out = []
    for line in (text or "").split("\n"):
        stripped = line.rstrip()
        tail = line[len(stripped):]
        out.append(stripped + dim("·" * len(tail)) + dim("\\n"))
    if out and out[-1] == dim("\\n"):
        out.pop()
    return out

def side_by_side(expected, got, width=34):
    left, right = visible(expected), visible(got)
    print("    %-*s  %s" % (width, bold("expected"), bold("got")))
    for i in range(max(len(left), len(right))):
        a = left[i] if i < len(left) else ""
        b = right[i] if i < len(right) else ""
        same = (a == b)
        mark = "  " if same else red(" ≠")
        pad = width - len(_strip(a))
        print("   %s %s%s  %s" % (mark, a, " " * max(pad, 1),
                                  b if same else red(_strip(b))))

def _strip(text):
    import re
    return re.sub(r"\033\[[0-9;]*m", "", text or "")

def _tty():
    return not JSON and sys.stdout.isatty() and not os.environ.get("NO_COLOR")

def as_json(payload):
    if not JSON:
        return False
    import json as _json

    _json.dump(payload, sys.stdout, indent=2, default=str, sort_keys=True)
    sys.stdout.write("\n")
    return True
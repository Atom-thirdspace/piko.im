
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"

IMG = re.compile(r"<img\b(?![^>]*\balt=)[^>]*>", re.I)
A_EMPTY = re.compile(r"<a\b[^>]*>\s*</a>", re.I)
BTN_EMPTY = re.compile(
    r"<button\b(?![^>]*aria-label=)[^>]*>\s*(?:<[^>]+>\s*)*</button>", re.I)
INPUT_BARE = re.compile(
    r'<input\b(?![^>]*\b(?:aria-label|aria-labelledby|id)=)'
    r'(?![^>]*type=["\'](?:hidden|submit)["\'])[^>]*>', re.I)
POSITIVE_TABINDEX = re.compile(r'tabindex=["\']?(?!-?0\b)\d', re.I)
CLICKABLE_DIV = re.compile(r"<(?:div|span)\b[^>]*\bonclick=", re.I)

CHECKS = (
    (IMG, "img without alt"),
    (A_EMPTY, "link with no text"),
    (BTN_EMPTY, "button with no text and no aria-label"),
    (INPUT_BARE, "input with no label, id or aria-label"),
    (POSITIVE_TABINDEX, "positive tabindex breaks natural focus order"),
    (CLICKABLE_DIV, "click handler on a div or span, not a button"),
)


def scan(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    found = []
    for pattern, message in CHECKS:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            snippet = " ".join(match.group(0).split())[:70]
            found.append((line, message, snippet))
    return sorted(found)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max", type=int, default=0,
                        help="allow this many findings before failing")
    parser.add_argument("--quiet", action="store_true",
                        help="print only the total")
    args = parser.parse_args()

    total = 0
    for path in sorted(TEMPLATES.rglob("*.html")):
        rows = scan(path)
        if not rows:
            continue
        total += len(rows)
        if args.quiet:
            continue
        print(path.relative_to(ROOT).as_posix())
        for line, message, snippet in rows:
            print("  %4d  %-46s %s" % (line, message, snippet))

    print()
    print("%d finding%s (budget %d)"
          % (total, "" if total == 1 else "s", args.max))
    return 1 if total > args.max else 0


if __name__ == "__main__":
    sys.exit(main())

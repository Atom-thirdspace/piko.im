"""A deliberately small Markdown subset, enough for lesson bodies and problem
statements.

Everything is HTML-escaped *before* any markup is applied, so author content
can never inject a tag. That is the whole security model here - keep it that
way if you extend this, and never add a rule that emits an attribute built
from user text.
"""

import re
from html import escape

from markupsafe import Markup

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?!\*)")
_HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
_ORDERED = re.compile(r"^\d+\.\s+(.*)$")
_BULLET = re.compile(r"^[-*]\s+(.*)$")
_TABLE_DIVIDER = re.compile(r"^\|[\s:|-]+\|$")


def _inline(text):
    """Escape, then apply inline markup. Order matters: code spans are pulled
    out first so that *stars* inside them stay literal."""
    spans = []

    def stash(match):
        spans.append(escape(match.group(1)))
        return "\x00%d\x00" % (len(spans) - 1)

    text = _INLINE_CODE.sub(stash, text)
    text = escape(text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    for i, code in enumerate(spans):
        text = text.replace("\x00%d\x00" % i, "<code>%s</code>" % code)
    return text


def _table_row(line, cell="td"):
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return "<tr>%s</tr>" % "".join(
        "<%s>%s</%s>" % (cell, _inline(c), cell) for c in cells
    )


def render(source):
    """Markdown subset -> HTML. Returns Markup, so templates can print it
    directly; the escaping already happened in _inline."""
    if not source:
        return Markup("")

    out = []
    lines = source.replace("\r\n", "\n").split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            i += 1
            block = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1                                  # step over the closing fence
            out.append("<pre><code>%s</code></pre>" % escape("\n".join(block)))
            continue

        if not stripped:
            i += 1
            continue

        heading = _HEADING.match(stripped)
        if heading:
            # Lesson bodies start at h2; the page owns the h1.
            level = min(len(heading.group(1)) + 1, 5)
            out.append("<h%d>%s</h%d>" % (level, _inline(heading.group(2)), level))
            i += 1
            continue

        # A table needs the |---|---| divider on the second line to count.
        if (stripped.startswith("|") and i + 1 < len(lines)
                and _TABLE_DIVIDER.match(lines[i + 1].strip())):
            rows = ["<thead>%s</thead>" % _table_row(stripped, "th")]
            i += 2
            body = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                body.append(_table_row(lines[i].strip()))
                i += 1
            rows.append("<tbody>%s</tbody>" % "".join(body))
            out.append("<table>%s</table>" % "".join(rows))
            continue

        if stripped.startswith(">"):
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>%s</blockquote>" % _inline(" ".join(quote)))
            continue

        for pattern, tag in ((_BULLET, "ul"), (_ORDERED, "ol")):
            if pattern.match(stripped):
                items = []
                while i < len(lines) and pattern.match(lines[i].strip()):
                    items.append("<li>%s</li>"
                                 % _inline(pattern.match(lines[i].strip()).group(1)))
                    i += 1
                out.append("<%s>%s</%s>" % (tag, "".join(items), tag))
                break
        else:
            # Plain paragraph: gather until a blank line or a line that starts
            # some other block.
            para = []
            while i < len(lines) and lines[i].strip():
                nxt = lines[i].strip()
                if (nxt.startswith(("```", ">", "#"))
                        or _BULLET.match(nxt) or _ORDERED.match(nxt)):
                    break
                para.append(nxt)
                i += 1
            if para:
                out.append("<p>%s</p>" % _inline(" ".join(para)))
            else:
                i += 1

    return Markup("".join(out))

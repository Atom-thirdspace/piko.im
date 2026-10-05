"""Geometry for the course-path map.

A track is drawn as a winding trail of lesson nodes. The maths lives here
rather than in Jinja so the template only places points that are already
worked out, the same way the admin charts do it.

Nodes wrap every PER_ROW and alternate direction, which is why a long track
reads as a level map rather than a line running off the edge.
"""

PER_ROW = 5
STEP_X = 150
ROW_H = 104
MARGIN_X = 46
MARGIN_Y = 42
WOBBLE = 16          # vertical sway, so the trail is not a ruler

KIND_GLYPH = {"reading": "●", "quiz": "?", "code": "❯"}


def _points(count):
    """Serpentine layout, left to right then right to left."""
    out = []
    for i in range(count):
        row, col = divmod(i, PER_ROW)
        if row % 2:                       # odd rows run backwards
            col = PER_ROW - 1 - col
        x = MARGIN_X + col * STEP_X
        y = MARGIN_Y + row * ROW_H + (WOBBLE if (i % 2) else -WOBBLE) * 0.5
        out.append((float(x), float(y)))
    return out


def _smooth(points):
    """Catmull-Rom through the points, emitted as cubic beziers.

    A polyline would kink at every node; this keeps the trail continuous
    even where it doubles back at the end of a row.
    """
    if len(points) < 2:
        return ""
    d = ["M %.1f %.1f" % points[0]]
    for i in range(len(points) - 1):
        p0 = points[i - 1] if i else points[0]
        p1, p2 = points[i], points[i + 1]
        p3 = points[i + 2] if i + 2 < len(points) else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0)
        d.append("C %.1f %.1f, %.1f %.1f, %.1f %.1f"
                 % (c1[0], c1[1], c2[0], c2[1], p2[0], p2[1]))
    return " ".join(d)


def build(track, lessons, done_ids, next_lesson=None):
    """One track's map: nodes, the trail behind them, and the walked part."""
    pts = _points(len(lessons))
    next_id = next_lesson.id if next_lesson is not None else None

    nodes, walked = [], []
    for i, (lesson, (x, y)) in enumerate(zip(lessons, pts)):
        done = lesson.id in done_ids
        current = lesson.id == next_id
        if done:
            walked.append((x, y))
        nodes.append({
            "n": i + 1,
            "x": round(x, 1),
            "y": round(y, 1),
            "title": lesson.title,
            "kind": lesson.kind,
            "glyph": KIND_GLYPH.get(lesson.kind, "●"),
            "xp": lesson.xp,
            "done": done,
            "current": current,
            "state": "done" if done else ("current" if current else "todo"),
            "unit": lesson.unit.title if lesson.unit else "",
            "url_parts": (track.slug, lesson.unit.slug if lesson.unit else "",
                          lesson.slug),
            # A lesson nobody has reached yet is shown but not linked: the
            # path is the story, the lesson page is earned by getting there.
            "open": done or current,
        })

    rows = (len(lessons) + PER_ROW - 1) // PER_ROW or 1
    width = MARGIN_X * 2 + (PER_ROW - 1) * STEP_X
    height = MARGIN_Y * 2 + (rows - 1) * ROW_H

    # The walked trail stops at the last finished node, so it can never
    # imply progress into a lesson that has not been done.
    if len(walked) == 1:
        walked = []

    return {
        "nodes": nodes,
        "trail": _smooth(pts),
        "walked": _smooth(walked),
        "width": width,
        "height": height,
        "rows": rows,
        "finish": {"x": round(pts[-1][0], 1), "y": round(pts[-1][1], 1)}
        if pts else None,
    }

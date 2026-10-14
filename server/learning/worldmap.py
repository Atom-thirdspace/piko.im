from sqlalchemy.orm import selectinload

from .. import contentcache, economy, notify
from ..content import may_see
from ..models import Unit, UnitPrereq, db

LAYER_W = 240
SLOT_H = 132
MARGIN_X = 96
MARGIN_Y = 76
NODE_R = 34

AREA_COINS = 20
STRUCTURE_TTL = 180.0

# Where the painted trail runs across the map artwork, as percentages of the
# image box. Regions snap to these in order, so the markers sit on the path
# that is actually drawn rather than floating over it. Tune these to the art.
WAYPOINTS = [
    (20.0, 49.0),
    (29.0, 74.0),
    (39.0, 63.0),
    (48.5, 76.0),
    (57.0, 62.0),
    (67.0, 57.0),
    (77.0, 68.0),
    (89.0, 53.0),
]
PANEL_SIZE = len(WAYPOINTS)

def _build_structure(track_id, user):
    units = db.session.execute(
        db.select(Unit).where(Unit.track_id == track_id)
        .options(selectinload(Unit.lessons))
        .order_by(Unit.position, Unit.id)
    ).scalars().all()
    units = [unit for unit in units if may_see(unit, user)]

    authored = db.session.execute(
        db.select(UnitPrereq.unit_id, UnitPrereq.requires_unit_id)
        .join(Unit, Unit.id == UnitPrereq.unit_id)
        .where(Unit.track_id == track_id)
    ).all()

    shaped = []
    for unit in units:
        lesson_ids = [lesson.id for lesson in unit.lessons
                      if may_see(lesson, user)]
        shaped.append({
           "id": unit.id,
            "slug": unit.slug,
            "title": unit.title,
            "topic": unit.topic or "",
            "level": unit.level or "",
            "lesson_ids": lesson_ids,
            "total": len(lesson_ids),
        })
    return {"units": shaped, "edges": _edges(shaped, authored)}


def structure(track, user=None):
    return contentcache.cached(
        "worldmap:%s" % track.id,
        lambda: _build_structure(track.id, user),
        ttl=STRUCTURE_TTL,
        user=user,
        
    )

def _edges(units, authored):
    ids = {unit["id"] for unit in units}
    out = {unit["id"]: set() for unit in units}

    drawn = False
    for unit_id, needs_id in authored:
        if unit_id in ids and needs_id in ids and unit_id != needs_id:
            out[unit_id].add(needs_id)
            drawn = True
    if drawn:
        return out

    for before, unit in zip(units, units[1:]):
        out[unit["id"]].add(before["id"])
    return out

def _depths(units, edges):
    order = [unit["id"] for unit in units]
    depth = {uid: 0 for uid in order}
    indegree = {uid: len(edges.get(uid, ())) for uid in order}
    children = {uid: [] for uid in order}
    for uid, needs in edges.items():
        for need in needs:
            if need in children:
                children[need].append(uid)

    queue = [uid for uid in order if not indegree[uid]]
    settled = 0
    while queue:
        uid = queue.pop(0)
        settled +=1
        for child in children[uid]:
            depth[child] = max(depth[child], depth[uid] + 1)
            indegree[child] -= 1
            if not indegree[child]:
                queue.append(child)

    if settled != len(order):
        return {uid: i for i, uid in enumerate(order)}, False
    return depth, True

def cleared_ids(struct, done_ids):
    """Units whose every visible lesson is finished. An empty unit never clears."""
    return {unit["id"] for unit in struct["units"]
            if unit["lesson_ids"]
            and all(lid in done_ids for lid in unit["lesson_ids"])}


def open_ids(struct, done_ids):
    """Units the learner may enter, cheap enough for a request gate."""
    cleared = cleared_ids(struct, done_ids)
    out = set(cleared)
    for unit in struct["units"]:
        if struct["edges"].get(unit["id"], set()) <= cleared:
            out.add(unit["id"])
    return out

def _curve(start, end):
    mid = (start[0] + end[0]) / 2.0
    return "M %.1f %.1f C %.1f %.1f, %.1f %.1f, %.1f %.1f" % (
        start[0], start[1], mid, start[1], mid, end[1], end[0], end[1])


def build(struct, done_ids, next_lesson_id=None):
    units = struct["units"]
    if not units:
        return {"regions": [], "links": [], "width": 0, "height": 0,
                "acyclic": True, "cleared": 0, "total": 0}

    edges = struct["edges"]
    depth, acyclic = _depths(units, edges)
    cleared = cleared_ids(struct, done_ids)
    titles = {unit["id"]: unit["title"] for unit in units}

    columns = {}
    for unit in units:
        columns.setdefault(depth[unit["id"]], []).append(unit)

    tallest = max(len(column) for column in columns.values())
    width = MARGIN_X * 2 + max(columns) * LAYER_W
    height = MARGIN_Y * 2 + (tallest - 1) * SLOT_H

    at = {}
    for layer in sorted(columns):
        column = columns[layer]
        pad = (tallest - len(column)) / 2.0
        for slot, unit in enumerate(column):
            at[unit["id"]] = (MARGIN_X + layer * LAYER_W,
                              MARGIN_Y + (slot + pad) * SLOT_H)

    regions = []
    for order, unit in enumerate(units):
        needs = edges.get(unit["id"], set())
        blocking = sorted(titles[n] for n in needs if n not in cleared)
        is_cleared = unit["id"] in cleared
        is_open = is_cleared or not blocking
        done = sum(1 for lid in unit["lesson_ids"] if lid in done_ids)
        x, y = at[unit["id"]]
        wx, wy = WAYPOINTS[order % PANEL_SIZE]
        regions.append({
            "id": unit["id"],
            "slug": unit["slug"],
            "title": unit["title"],
            "topic": unit["topic"],
            "level": unit["level"],
            "x": round(x, 1),
            "y": round(y, 1),
            "wx": wx,
            "wy": wy,
            "panel": order // PANEL_SIZE,
            "done": done,
            "total": unit["total"],
            "percent": round(done * 100 / unit["total"]) if unit["total"] else 0,
            "state": "cleared" if is_cleared else ("open" if is_open else "locked"),
            "open": is_open,
            "needs": blocking,
            "current": bool(next_lesson_id is not None
                            and next_lesson_id in unit["lesson_ids"]),
        })

    links = []
    for unit in units:
        for need in edges.get(unit["id"], ()):
            if need not in at:
                continue
            start, end = at[need], at[unit["id"]]
            links.append({
                "d": _curve((start[0] + NODE_R, start[1]),
                            (end[0] - NODE_R, end[1])),
                "walked": need in cleared,
            })

    panels = _panels(regions)
    current_panel = next((p["index"] for p in panels if p["current"]), 0)

    return {"regions": regions, "links": links, "panels": panels,
            "current_panel": current_panel,
            "width": width, "height": height, "acyclic": acyclic,
            "cleared": len(cleared), "total": len(units)}


def _panels(regions):
    grouped = {}
    for region in regions:
        grouped.setdefault(region["panel"], []).append(region)

    out = []
    for index in sorted(grouped):
        members = grouped[index]
        out.append({
            "index": index,
            "regions": members,
            "open": any(r["open"] for r in members),
            "cleared": all(r["state"] == "cleared" for r in members),
            "current": any(r["current"] for r in members),
            "done": sum(r["done"] for r in members),
            "total": sum(r["total"] for r in members),
            "title": "%s &ndash; %s" % (members[0]["title"], members[-1]["title"])
            if len(members) > 1 else members[0]["title"],
        })
    return out

def note_unlocks(user,struct, done_ids, cleared_unit_id):
    cleared = cleared_ids(struct, done_ids)
    opened = []
    for unit in struct["units"]:
        needs = struct["edges"].get(unit["id"], set())
        if cleared_unit_id not in needs:
            continue
        if unit["id"] in cleared or not needs <= cleared:
            continue
        opened.append(unit)

    for unit in opened:
        economy.earn(user, AREA_COINS, "area", str(unit["id"]))
        notify.send_once(
            user, "area", str(unit["id"]),
            "New region open: %s" % unit["title"],
            body="You cleared what it needed. %d lesson%s waiting."
                 % (unit["total"], "" if unit["total"] == 1 else "s"),
        )
    return [unit["title"] for unit in opened]

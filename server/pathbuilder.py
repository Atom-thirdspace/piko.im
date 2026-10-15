import json
import re
from datetime import timedelta

from sqlalchemy.orm import joinedload, selectinload

from . import contentcache
from .models import (PUBLISHED, CustomPath, CustomPathItem, Lesson, Track,
                     Unit, _utcnow, db)
from .tutor.client import TutorError, ask, is_configured
from .tutor.client import TutorError, ask, is_configured

MAX_MENU = 200
MAX_ITEMS = 40
MAX_STAGES = 8
MIN_ITEMS = 3
MAX_GOAL = 300
MIN_GOAL = 8

DAILY_BUILDS = 5
PRO_DAILY_BUILDS = 20
MENU_TTL = 300.0

SYSTEM = """You plan a learning route through lessons that already exist.
You reply with one JSON object and nothing else.

Schema:
{
  "title": "short name for this route, under 60 characters",
  "summary": "one sentence on what the learner will be able to do",
  "stages": [
    {"name": "stage name",
     "items": [{"i": 0, "why": "one short line on why this lesson, here"}]}
  ]
}

Rules:
- "i" is an index from the LESSONS list. Never invent a lesson and never
  use an index that is not in the list.
- Order matters. Put what a later lesson depends on before it.
- Between 1 and 8 stages. Between 3 and 40 lessons in total.
- Never repeat an index.
- Prefer a short route that reaches the goal over a complete one.
- "why" is for the learner, so write it to them, not about them.
"""

FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
SLUG_BAD = re.compile(r"[^a-z0-9]+")

class PlanError(Exception):
    """Shown to the learner as a polite failure."""

def daily_limit(user):
    from .billing.service import is_pro
    return PRO_DAILY_BUILDS if is_pro(user) else DAILY_BUILDS

def builds_today(user):
    since = _utcnow() - timedelta(days = 1)
    return db.session.execute(
        db.select(db.func.count()).select_from(CustomPath)
        .where(CustomPath.user_id == user.id,
               CustomPath.created_at >= since)).scalar() or 0


def over_cap(user):
    return builds_today(user) >= daily_limit(user)

def _build_menu():
    rows = db.session.execute(
        db.select(Lesson)
        .join(Unit, Unit.id == Lesson.unit_id)
        .join(Track, Track.id == Unit.track_id)
        .where(Lesson.status == PUBLISHED, Unit.status == PUBLISHED,
               Track.status == PUBLISHED)
        .options(joinedload(Lesson.unit).joinedload(Unit.track))
        .order_by(Track.position, Unit.position, Lesson.position)
        .limit(MAX_MENU)
    ).scalars().all()

    return [{
        "id": lesson.id,
        "slug": lesson.slug,
        "title": lesson.title,
        "kind": lesson.kind,
        "xp": lesson.xp,
        "unit": lesson.unit.title if lesson.unit else "",
        "unit_slug": lesson.unit.slug if lesson.unit else "",
        "topic": (lesson.unit.topic or "") if lesson.unit else "",
        "track": lesson.unit.track.title if lesson.unit and lesson.unit.track else "",
        "track_slug": lesson.unit.track.slug if lesson.unit and lesson.unit.track else "",
    } for lesson in rows]

def menu():
    return contentcache.cached("pathbuilder:menu", _build_menu, ttl=MENU_TTL)

def _render_menu(items):
    return "\n".join(
        "%d | %s / %s | %s | %s | %s"
        % (i, row["track"], row["unit"], row["title"], row["kind"],
           row["topic"] or "-")
        for i, row in enumerate(items))

def clean_goal(raw):
    text = re.sub(r"\s+", " ", (raw or "")).strip()
    return text[:MAX_GOAL]

def _parse(text):
    try:
        data = json.loads(FENCE.sub("", text).strip())
    except ValueError as exc:
        raise PlanError("The planner didn't return a usable answer. (%s)" % exc)
    if not isinstance(data, dict):
        raise PlanError("The planner didn't return a usable answer.")
    return data

def _validate(data, items, goal):
    stages = data.get("stages")
    if not isinstance(stages, list):
        raise PlanError("The planner didn't return any stages.")

    seen = set()
    chosen = []
    for stage_no, stage in enumerate(stages[:MAX_STAGES]):
        if not isinstance(stage, dict):
            continue
        name = str(stage.get("name") or "Stage %d" % (stage_no + 1))[:120]
        for entry in (stage.get("items") or []):
            if len(chosen) >= MAX_ITEMS:
                break
            if not isinstance(entry, dict):
                continue
            try:
                index = int(entry.get("i"))
            except(TypeError, ValueError):
                continue
            if index < 0 or index >= len(items) or index in seen:
                continue
            seen.add(index)
            chosen.append({
                "lesson": items[index],
                "stage": stage_no,
                "stage_name": name,
                "reason": str(entry.get("why") or "")[:240],
            })

        if len(chosen) < MIN_ITEMS:
            raise PlanError("The planner couldn't find enough lessons for that.")

        title = str(data.get("title") or "").strip()[:160] or _title_from(goal)
        summary = str(data.get("summary") or "").strip()[:500]
        return {"title": title, "summary": summary, "items": chosen}

def _title_from(goal):
    words = (goal or "Custom path").split()
    return (" ".join(words[:7]) or "Custom path")[:160]

def keyword_plan(goal, items):
    words = {w for w in SLUG_BAD.sub(" ", (goal or "").lower()).split()
             if len(w) > 2}

    def score(row):
        hay = " ".join((row["title"], row["unit"], row["topic"],
                        row["track"])).lower()
        return sum(1 for w in words if w in hay)

    ranked = [(score(row), i) for i, row in enumerate(items)]
    hits = [i for value, i in ranked if value > 0]
    if len(hits) < MIN_ITEMS:
        hits = [i for _value, i in ranked][:12]

    chosen = []
    for i in hits[:MAX_ITEMS]:
        row = items[i]
        chosen.append({
            "lesson": row,
            "stage": 0,
            "stage_name": row["track"] or "Your route",
            "reason": "Matches what you asked for.",
        })

    if len(chosen) < MIN_ITEMS:
        raise PlanError("There aren't enough published lessons yet "
                        "to build a path.")
    return {"title": _title_from(goal), "summary": "", "items": chosen}

def plan(goal, use_ai=True):
    goal = clean_goal(goal)
    if len(goal) < MIN_GOAL:
        raise PlanError("Tell the planner a bit more about what you want")

    items = menu()
    if not items:
        raise PlanError("There are no published lessons to build from yet.")

    if not (use_ai and is_configured()):
        return keyword_plan(goal, items), ""

    prompt = ("GOAL\n%s\n\nLESSONS\nindex | track / unit | lesson | kind | topic\n%s"
              % (goal, _render_menu(items)))
    try:
        text, model = ask(SYSTEM, prompt, max_tokens=1800, timeout=45)
    except TutorError:
        return keyword_plan(goal, items), ""

    try:
        return _validate(_parse(text), items, goal), model
    except PlanError:
        return keyword_plan(goal, items), ""

def _slug_for(user, title):
    base = SLUG_BAD.sub("-", (title or "path").lower()).strip("-")[:60] or "path"
    taken = {row.slug for row in db.session.execute(
        db.select(CustomPath).where(CustomPath.user_id == user.id)).scalars()}
    if base not in taken:
        return base
    for n in range(2, 60):
        candidate = "%s-%d" % (base[:56], n)
        if candidate not in taken:
            return candidate
    return "%s-%d" % (base[:50], int(_utcnow().timestamp()) % 100000)

def save(user, goal, draft, model= ""):
    path = CustomPath(
        user_id=user.id,
        slug=_slug_for(user, draft["title"]),
        title = draft["title"],
        goal=clean_goal(goal),
        summary=draft.get("summary", ""),
        source="ai" if model else "keywords",
        model=model or "",
    ) 
    db.session.add(path)
    db.session.flush()

    for position, entry in enumerate(draft["items"]):
        db.session.add(CustomPathItem(
            path_id=path.id,
            lesson_id=entry["lesson"]["id"],
            position=position,
            stage=entry["stage"],
            stage_name=entry["stage_name"],
            reason=entry["reason"],
        ))
    db.session.commit()
    return path

def mine(user, limit=20):
    return db.session.execute(
        db.select(CustomPath).where(CustomPath.user_id == user.id,
                                    CustomPath.is_active.is_(True))
        .order_by(CustomPath.created_at.desc()).limit(limit)).scalars().all()

def find(user, slug):
    return db.session.execute(
        db.select(CustomPath)
        .options(selectinload(CustomPath.items)
                 .joinedload(CustomPathItem.lesson)
                 .joinedload(Lesson.unit).joinedload(Unit.track))
        .where(CustomPath.user_id == user.id, CustomPath.slug == slug)
    ).unique().scalar_one_or_none()

def view(path, done_ids):
    stages , nxt = [], None
    for item in path.items:
        lesson = item.lesson
        if lesson is None or lesson.unit is None or lesson.unit.track is None:
            continue
        done = lesson.id in done_ids
        row = {
            "lesson": lesson,
            "done": done,
            "reason": item.reason,
            "track_slug": lesson.unit.track.slug,
            "unit_slug": lesson.unit.slug,
            "lesson_slug": lesson.slug,
            "xp": lesson.xp,
            "kind": lesson.kind,
        }
        if not done and nxt is None:
            nxt = row
            row["current"] = True

        else:
            row["current"] = False

        if stages and stages[-1]["stage"] == item.stage:
            stages[-1]["items"].append(row)
        else:
            stages.append({"stage": item.stage, "name": item.stage_name,
                           "items": [row]})

    total = sum(len(s["items"]) for s in stages)
    done = sum(1 for s in stages for r in s["items"] if r["done"])
    for stage in stages:
        stage["done"] = sum(1 for r in stage["items"] if r["done"])
        stage["total"] = len(stage["items"])
        stage["cleared"] = stage["done"] == stage["total"]

    return {"stages": stages, "total": total, "done": done,
            "percent": round(done * 100 / total) if total else 0,
            "next": nxt, "xp": sum(r["xp"] for s in stages
                                   for r in s["items"])}
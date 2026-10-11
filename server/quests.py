import random
from dataclasses import dataclass
from typing import Callable

from flask import g, has_request_context

from .models import (PUBLISHED, Enrollment, Lesson, LessonProgress,
                     Problem, ProblemSolve, Unit, XpEvent, db)
from .progress import award_xp, day_bounds, user_today

from .memo import per_request

QUESTS_PER_DAY = 3
ALL_THREE_BONUS = 40

def _solves(user, lo, hi, difficulties=None):
    stmt = (db.select(db.func.count()).select_from(ProblemSolve)
            .where(ProblemSolve.user_id == user.id,
                   ProblemSolve.solved_at >= lo, ProblemSolve.solved_at < hi))
    if difficulties:
        stmt = (stmt.join(Problem, Problem.id == ProblemSolve.problem_id)
                .where(Problem.difficulty.in_(difficulties)))
    return db.session.execute(stmt).scalar() or 0

def _ledger(user, lo, hi, reason):
    return db.session.execute(
        db.select(db.func.count()).select_from(XpEvent)
        .where(XpEvent.user_id == user.id, XpEvent.reason == reason,
               XpEvent.created_at >= lo, XpEvent.created_at < hi)).scalar() or 0

def _lessons(user, lo, hi, kind=None):
    stmt = (db.select(db.func.count()).select_from(LessonProgress)
            .where(LessonProgress.user_id == user.id,
                   LessonProgress.completed_at >= lo,
                   LessonProgress.completed_at < hi))
    if kind:
        stmt = (stmt.join(Lesson, Lesson.id == LessonProgress.lesson_id)
                .where(Lesson.kind == kind))
    return db.session.execute(stmt).scalar() or 0


def _new_topics(user, lo, hi):
    seen_before = (db.select(Problem.topic)
                   .select_from(ProblemSolve)
                   .join(Problem, Problem.id == ProblemSolve.problem_id)
                   .where(ProblemSolve.user_id == user.id,
                          ProblemSolve.solved_at < lo,
                          Problem.topic.isnot(None)))
    return db.session.execute(
        db.select(db.func.count(db.distinct(Problem.topic)))
        .select_from(ProblemSolve)
        .join(Problem, Problem.id == ProblemSolve.problem_id)
        .where(ProblemSolve.user_id == user.id,
               ProblemSolve.solved_at >= lo, ProblemSolve.solved_at < hi,
               Problem.topic.isnot(None),
               Problem.topic.notin_(seen_before))).scalar() or 0


def _goal_hit(user, lo, hi):
    target = user.daily_goal_xp or 0
    if not target:
        return 0
    earned = db.session.execute(
        db.select(db.func.coalesce(db.func.sum(XpEvent.amount), 0))
        .where(XpEvent.user_id == user.id,
               XpEvent.created_at >= lo, XpEvent.created_at < hi)).scalar() or 0
    return 1 if earned >= target else 0

def _unsolved_stmt(user, difficulties=None):
    solved = (db.select(ProblemSolve.problem_id)
              .where(ProblemSolve.user_id == user.id))
    stmt = db.select(Problem.id).where(Problem.id.notin_(solved))
    if difficulties:
        stmt = stmt.where(Problem.difficulty.in_(difficulties))
    return stmt


def _unsolved_exists(user, difficulties=None):
    return db.session.execute(
        _unsolved_stmt(user, difficulties).limit(1)).scalar() is not None


def _lesson_stmt(user, kind=None, enrolled_only=False):
    done = (db.select(LessonProgress.lesson_id)
            .where(LessonProgress.user_id == user.id))
    stmt = (db.select(Lesson.id).join(Unit, Unit.id == Lesson.unit_id)
            .where(Lesson.status == PUBLISHED, Unit.status == PUBLISHED,
                   Lesson.id.notin_(done)))
    if kind:
        stmt = stmt.where(Lesson.kind == kind)
    if enrolled_only:
        tracks = (db.select(Enrollment.track_id)
                  .where(Enrollment.user_id == user.id))
        stmt = stmt.where(Unit.track_id.in_(tracks))
    return stmt


def _unfinished_lesson_exists(user, kind=None, enrolled_only=False):
    return db.session.execute(
        _lesson_stmt(user, kind, enrolled_only).limit(1)).scalar() is not None


def _solved_stmt(user):
    return (db.select(ProblemSolve.id)
            .where(ProblemSolve.user_id == user.id))

def _boss_wins(user, lo, hi):
    """Wins only.

    Deliberately not the XP ledger: the arena also pays a consolation for a
    good loss, and "win a fight" has to mean winning.
    """
    from .models import BossRun
    return db.session.execute(
        db.select(db.func.count()).select_from(BossRun)
        .where(BossRun.user_id == user.id, BossRun.status == "won",
               BossRun.ended_at >= lo, BossRun.ended_at < hi)).scalar() or 0


def _boss_fightable():
    """Is any live boss backed by a pool big enough to fight?

    Grouped in one query rather than counted per boss - this runs inside the
    dashboard's request, where every round trip shows.

    A boss that also filters by topic is treated optimistically here: the
    worst case is a quest that is harder to clear than it looks, not a
    crash.
    """
    from . import contentcache
    return contentcache.cached("quests:boss_fightable", _compute_fightable,
                               ttl=300.0)


def _compute_fightable():
    from .arena.rules import MIN_POOL
    from .models import Boss, BossQuestion

    counts = dict(db.session.execute(
        db.select(BossQuestion.difficulty, db.func.count())
        .where(BossQuestion.status == PUBLISHED)
        .group_by(BossQuestion.difficulty)).all())
    if not counts:
        return False

    tiers = db.session.execute(
        db.select(Boss.difficulty).where(Boss.is_live.is_(True))).scalars()
    return any(counts.get(tier, 0) >= MIN_POOL for tier in tiers)


def _endless_scores(user, lo, hi, target=150):
    from .models import BossRun
    return db.session.execute(
        db.select(db.func.count()).select_from(BossRun)
        .where(BossRun.user_id == user.id, BossRun.mode == "endless",
               BossRun.score >= target, BossRun.ended_at >= lo,
               BossRun.ended_at < hi)).scalar() or 0


def _records_set(user, lo, hi):
    from .models import SpeedRecord
    return db.session.execute(
        db.select(db.func.count()).select_from(SpeedRecord)
        .where(SpeedRecord.user_id == user.id,
               SpeedRecord.set_at >= lo, SpeedRecord.set_at < hi)).scalar() or 0


def _has_solved_something(user):
    """You can only race a problem you have already solved."""
    from .models import ProblemSolve
    return db.session.execute(
        db.select(ProblemSolve.id).where(ProblemSolve.user_id == user.id)
        .limit(1)).scalar() is not None


def _capability(user):
    row = db.session.execute(db.select(
        db.exists(_unsolved_stmt(user)).label("unsolved"),
        db.exists(_unsolved_stmt(user, ("medium", "hard"))).label("hard"),
        db.exists(_lesson_stmt(user)).label("lesson"),
        db.exists(_lesson_stmt(user, enrolled_only=True)).label("enrolled"),
        db.exists(_lesson_stmt(user, kind="quiz")).label("quiz"),
        db.exists(_solved_stmt(user)).label("speed"),
    )).one()

    return {
        "unsolved": bool(row.unsolved),
        "unsolved_hard": bool(row.hard),
        "lesson": bool(row.lesson),
        "lesson_enrolled": bool(row.enrolled),
        "quiz": bool(row.quiz),
        "goal": (user.daily_goal_xp or 0) > 0,
        "boss": _boss_fightable(),
        "speed": bool(row.speed),
    }


def capability(user):
    if not has_request_context():
        return _capability(user)
    cache = getattr(g, "_quest_caps", None)
    if cache is None:
        cache = g._quest_caps = {}
    if user.id not in cache:
        cache[user.id] = _capability(user)
    return cache[user.id]


@dataclass(frozen=True)
class Quest:
    key: str
    title: str
    target: int
    reward: int
    count: Callable
    feasible: Callable        # (capability dict) -> bool

REGISTRY = (
    Quest("solve_any", "Solve a problem", 1, 20,
          lambda u, lo, hi: _solves(u, lo, hi),
          lambda c: c["unsolved"]),
    Quest("solve_two", "Solve two problems", 2, 35,
          lambda u, lo, hi: _solves(u, lo, hi),
          lambda c: c["unsolved"]),
    Quest("solve_medium", "Solve a medium or hard problem", 1, 30,
          lambda u, lo, hi: _solves(u, lo, hi, ("medium", "hard")),
          lambda c: c["unsolved_hard"]),
    Quest("clean_solve", "Solve one without opening a hint", 1, 25,
          lambda u, lo, hi: _ledger(u, lo, hi, "no_hints"),
          lambda c: c["unsolved"]),
    Quest("one_shot", "Solve one on your first submission", 1, 30,
          lambda u, lo, hi: _ledger(u, lo, hi, "first_try"),
          lambda c: c["unsolved"]),
    Quest("new_topic", "Solve in a topic you have never solved", 1, 35,
          _new_topics,
          lambda c: c["unsolved"]),
    Quest("lesson_any", "Finish a lesson", 1, 15,
          lambda u, lo, hi: _lessons(u, lo, hi),
          lambda c: c["lesson"]),
    Quest("lesson_track", "Finish a lesson in a track you have started", 1, 20,
          lambda u, lo, hi: _lessons(u, lo, hi),
          lambda c: c["lesson_enrolled"]),
    Quest("quiz", "Pass a quiz", 1, 20,
          lambda u, lo, hi: _lessons(u, lo, hi, kind="quiz"),
          lambda c: c["quiz"]),
    Quest("goal", "Hit your daily XP goal", 1, 15,
          _goal_hit,
          lambda c: c["goal"]),
    Quest("boss", "Win a fight in the arena", 1, 25,
          _boss_wins,
          lambda c: c["boss"]),
    Quest("endless", "Score 150 in endless mode", 1, 25,
          _endless_scores,
          lambda c: c["boss"]),
    Quest("speed", "Beat one of your own times", 1, 25,
          _records_set,
          lambda c: c["speed"]),
)

BY_KEY = {q.key: q for q in REGISTRY}


@per_request(lambda user, day : (user.id, day))
def todays_quests(user, day):
    cap = capability(user)
    order = list(REGISTRY)
    random.Random("%s:%d" % (day.isoformat(), user.id)).shuffle(order)

    locked = _paid_keys(user, day)
    picked = [q for q in order if q.key in locked]
    for q in order:
        if len(picked) >= QUESTS_PER_DAY:
            break
        if q.key not in locked and q.feasible(cap):
            picked.append(q)
    return sorted(picked, key=REGISTRY.index)

def _ref(day, key):
    return "%s:%s" % (day.isoformat(), key)

@per_request(lambda user, day: (user.id, day))
def _paid_keys(user, day):
    return {r.split(":", 1)[1] for r in _paid_refs(user, day)} - {"all"}


def _forget_paid_refs(user, day):
    if not has_request_context():
        return
    cache = getattr(g, "_memo", None)
    if cache is not None:
        cache.pop(("_paid_refs", (user.id, day)), None)


@per_request(lambda user, day: (user.id, day))
def _paid_refs(user, day):
    return set(db.session.execute(
        db.select(XpEvent.ref).where(XpEvent.user_id == user.id,
                                     XpEvent.reason == "daily",
                                     XpEvent.ref.like("%s:%%" % day.isoformat()))
    ).scalars())


def board(user, day=None):
    day = day or user_today(user)
    lo, hi = day_bounds(user, day)
    paid = _paid_refs(user, day)
    quests = todays_quests(user, day)

    # "tasks", not "items": Jinja resolves a dict's .items to the method.
    tasks = []
    for q in quests:
        done = min(q.count(user, lo, hi), q.target)
        tasks.append({"key": q.key, "title": q.title, "reward": q.reward,
                      "done": done, "target": q.target,
                      "complete": done >= q.target,
                      "paid": _ref(day, q.key) in paid})

    return {"day": day, "tasks": tasks,
            "finished": sum(1 for i in tasks if i["complete"]),
            "total": len(tasks),
            "all_done": bool(tasks) and all(i["complete"] for i in tasks),
            "bonus": ALL_THREE_BONUS,
            "bonus_paid": _ref(day, "all") in paid}


def sync_board(user, day=None):
    """Pay for anything finished, and hand back the board it was read from.

    One evaluation instead of two. board() is deliberately not cached - a
    request that solves a problem and then reads the board must see the
    solve - so the saving comes from sharing this result, not from a memo.
    """
    day = day or user_today(user)
    state = board(user, day)

    from . import economy

    gained = 0
    for task in state["tasks"]:
        if task["complete"] and not task["paid"]:
            got = award_xp(user, task["reward"], "daily",
                           _ref(day, task["key"]))["awarded"]
            if got:
                task["paid"] = True
                economy.earn(user, economy.QUEST_COINS, "quest",
                             _ref(day, task["key"]))
            gained += got

    if state["all_done"] and not state["bonus_paid"]:
        got = award_xp(user, ALL_THREE_BONUS, "daily",
                       _ref(day, "all"))["awarded"]
        if got:
            state["bonus_paid"] = True
            economy.earn(user, economy.ALL_QUESTS_COINS, "quest_all",
                         _ref(day, "all"))
        gained += got

    if gained:
        _forget_paid_refs(user, day)
    return gained, state


def sync(user, day=None):
    """Just the payout, for callers with no page to render."""
    return sync_board(user, day)[0]
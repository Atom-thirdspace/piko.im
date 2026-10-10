import random
from datetime import timedelta

from ..models import (PUBLISHED, Boss, BossQuestion, BossRun, BossRunQuestion,
                      XpEvent, _utcnow, db)
from ..progress import award_xp, day_bounds, user_today
from . import rules
from .grading import is_correct

XP_REASON = "boss"

def _pool(boss, size=rules.POOL_SIZE):
    stmt = (db.select(BossQuestion.id)
            .where(BossQuestion.status == PUBLISHED))
    if boss.topic:
        stmt = stmt.where(BossQuestion.topic == boss.topic)
    if boss.difficulty:
        stmt = stmt.where(BossQuestion.difficulty == boss.difficulty)
    ids = list(db.session.execute(stmt).scalars())
    return ids, size

def start(user, boss):
    from ..models import active_boss_run

    open_run = active_boss_run(user)
    if open_run is not None:
        return open_run, None

    ids, size = _pool(boss)
    if len(ids) < rules.MIN_POOL:
        return None, "This boss has no question pool yet."

    seed = random.getrandbits(48)
    random.Random(seed).shuffle(ids)

    run = BossRun(user_id=user.id, boss_id=boss.id, seed=seed,
                  plan=ids[:size], boss_hp=boss.hp,
                  player_hp=rules.PLAYER_HP)
    db.session.add(run)
    db.session.commit()
    return run, None


def open_question(run):
    return db.session.execute(
        db.select(BossRunQuestion)
        .where(BossRunQuestion.run_id == run.id,
               BossRunQuestion.answered_at.is_(None))
        .order_by(BossRunQuestion.position.desc()).limit(1)
    ).scalar_one_or_none()


def shuffled_choices(run, question):
    options = list(question.choices or [])
    random.Random(run.seed ^ (question.id * 2654435761)).shuffle(options)
    return options

def serve(run):
    existing = open_question(run)
    if existing is not None:
        return existing

    if run.cursor >= len(run.plan):
        return None

    question_id = run.plan[run.cursor]
    question = db.session.get(BossQuestion, question_id)
    run.cursor += 1
    if question is None or question.status != PUBLISHED:
        db.session.commit()
        return serve(run)                 # a withdrawn question is skipped

    now = _utcnow()
    row = BossRunQuestion(
        run_id=run.id, question_id=question.id, position=run.asked,
        served_at=now,
        deadline_at=now + timedelta(seconds=question.seconds))
    run.asked += 1
    db.session.add(row)
    db.session.commit()
    return row

def as_payload(run, row):
    question = row.question
    left = (row.deadline_at - _utcnow()).total_seconds()
    body = {
        "question_id": question.id,
        "kind": question.kind,
        "prompt": question.prompt,
        "difficulty": question.difficulty,
        "window": question.seconds,
        "seconds_left": max(0.0, round(left, 2)),
        "position": row.position + 1,
    }
    if question.kind == "choice":
        body["choices"] = [{"key": i, "text": text} for i, text
                           in enumerate(shuffled_choices(run, question))]
    return body

def answer(run, question_id, given, choice_key=None):
    row = open_question(run)
    if row is None or row.question_id != int(question_id or 0):
        return {"stale": True, **state(run)}

    question = row.question
    now = _utcnow()
    late = now > row.deadline_at + timedelta(seconds=rules.GRACE_SECONDS)

    if question.kind == "choice":
        options = shuffled_choices(run, question)
        try:
            given = options[int(choice_key)]
        except (TypeError, ValueError, IndexError):
            given = ""

    hit = (not late) and is_correct(question, given)

    row.answered_at = now
    row.given = (given or "")[:200]
    row.correct = hit

    if hit:
        left = max(0.0, (row.deadline_at - now).total_seconds())
        row.damage = rules.damage_for(question.difficulty, left,
                                      question.seconds, run.combo)
        run.boss_hp = max(0, run.boss_hp - row.damage)
        run.combo += 1
        run.best_combo = max(run.best_combo, run.combo)
        run.correct += 1
    else:
        row.damage = 0
        run.combo = 0
        run.player_hp = max(0, run.player_hp - run.boss.attack)

    outcome = {
        "stale": False,
        "correct": hit,
        "timed_out": late,
        "damage": row.damage,
        "answer": question.answer,
        "explain": question.explain_md,
    }

    if run.boss_hp <= 0:
        finish(run, "won")
    elif run.player_hp <= 0:
        finish(run, "lost")
    elif run.cursor >= len(run.plan):
        finish(run, "draw")          # the pool ran dry before either side fell
    else:
        db.session.commit()

    outcome.update(state(run))
    return outcome

def state(run):
    return {"run_id": run.id, "status": run.status, "boss_hp": run.boss_hp,
            "boss_hp_max": run.boss.hp, "player_hp": run.player_hp,
            "player_hp_max": rules.PLAYER_HP, "combo": run.combo,
            "best_combo": run.best_combo, "asked": run.asked,
            "hits": run.correct, "xp": run.xp_awarded}

def _paid_today(user):
    lo, hi = day_bounds(user, user_today(user))
    return db.session.execute(
        db.select(db.func.count()).select_from(XpEvent)
        .where(XpEvent.user_id == user.id, XpEvent.reason == XP_REASON,
               XpEvent.created_at >= lo, XpEvent.created_at < hi)).scalar() or 0

def finish(run, status):
    run.status = status
    run.ended_at = _utcnow()

    amount = 0
    if _paid_today(run.user) < rules.PAID_RUNS_PER_DAY:
        if status == "won":
            amount = rules.win_xp(run.boss.tier, run.correct == run.asked)
        elif run.correct >= 3:
            amount = rules.CONSOLATION_XP

    if amount:
        award_xp(run.user, amount, XP_REASON, str(run.id))
        run.xp_awarded = amount

    db.session.commit()

    # Settled after the status is written, so the arena quest can see the win
    # rather than waiting for the next dashboard load.
    from .. import quests
    quests.sync(run.user)

    from ..achievements import evaluate
    evaluate(run.user)
    return run

def forfeit(run):
    if run.status == "active":
        finish(run, "lost")
    return run

def expire_stale(older_than_minutes = 45):
    cutoff = _utcnow() - timedelta(minutes=older_than_minutes)
    rows = db.session.execute(
        db.select(BossRun).where(BossRun.status == "active",
                                 BossRun.started_at < cutoff)).scalars().all()
    for run in rows:
        run.status = "abandoned"
        run.ended_at = _utcnow()
    db.session.commit()
    return len(rows)
"""The questionnaire state machine: answers in, enrollment out."""

from ..learning.catalog import TRACKS_BY_SLUG
from ..models import (Enrollment, Lesson, OnboardingSession, Track, Unit, User,_utcnow,db)
from ..progress import level_progress
from . import placement
from .recommend import recommend
from .steps import (AnswerError, STEPS_BY_KEY, is_complete, next_step, steps_for,
                    validate)

class OnboardingError(Exception):
    pass

def get_session(user, create=True):
    sess = db.session.execute(
        db.select(OnboardingSession).filter_by(user_id=user.id)
    ).scalar_one_or_none()
    if sess is None and create:
        sess = OnboardingSession(user_id=user.id, answers={})
        db.session.add(sess)
        db.session.commit()
    return sess

def _touch(sess, answers):
    # JSON columns don't track in-place mutation; always reassign.
    sess.answers = answers
    sess.updated_at = _utcnow()

def state(user):
    sess = get_session(user)
    answers = dict(sess.answers or {})
    step = next_step(answers)

    if step is not None:
        return {
            "stage": "questions",
            "step": step.public(answers),
            "answers": answers,
            "progress": {"answered": len(answers),
                         "total": len(steps_for(answers))},
        }

    if _wants_placement(answers) and sess.placement_score is None:
        return {"stage": "placement", "answers": answers,
                "questions": _placement_payload(sess)}

    if sess.completed_at is None:
        return {"stage": "review", "answers": answers,
                "level": sess.level, "recommendation": sess.recommendation}

    return {"stage": "done", "answers": answers,
            "level": sess.level, "recommendation": sess.recommendation}

def submit_answer(user, key, value):
    sess = get_session(user)
    step = STEPS_BY_KEY.get(key)
    if step is None:
        raise AnswerError("Unknown question.")

    answers = dict(sess.answers or {})
    if not step.applies(answers):
        raise AnswerError("That question doesn't apply.")

    answers[key] = validate(step, value)

    # Answers later in the flow can be invalidated by an earlier change.
    for later in list(answers):
        other = STEPS_BY_KEY.get(later)
        if later != key and other is not None and not other.applies(answers):
            answers.pop(later)

    _touch(sess, answers)
    db.session.commit()
    return state(user)

def back(user):
    """Drop the most recent answer so the user can change it."""
    sess = get_session(user)
    answers = dict(sess.answers or {})
    applicable = [s.key for s in steps_for(answers) if s.key in answers]
    if applicable:
        answers.pop(applicable[-1])
        _touch(sess, answers)
        db.session.commit()
    return state(user)

def _wants_placement(answers):
    return answers.get("placement_opt_in") == "yes"

def _placement_payload(sess):
    if not sess.placement_question_ids:
        sess.placement_question_ids = placement.pick_questions()
        db.session.commit()
    return [placement.BANK_BY_ID[qid].public()
            for qid in sess.placement_question_ids
            if qid in placement.BANK_BY_ID]

def start_placement(user):
    sess = get_session(user)
    answers = dict(sess.answers or {})
    if not is_complete(answers):
        raise OnboardingError("Finish the questions first.")
    if not _wants_placement(answers):
        raise OnboardingError("You opted out of the quiz.")
    return {"questions": _placement_payload(sess)}

def grade_placement(user, responses):
    sess = get_session(user)
    if not sess.placement_question_ids:
        raise OnboardingError("No quiz in progress.")
    if not isinstance(responses, dict):
        raise OnboardingError("Expected an answers object.")

    earned, possible = placement.score(sess.placement_question_ids, responses)
    sess.placement_score = earned
    sess.placement_possible = possible
    sess.level = placement.level_from_score(earned, possible)
    sess.updated_at = _utcnow()
    db.session.commit()

    return {"score": earned, "possible": possible, "level": sess.level,
            "review": placement.review(sess.placement_question_ids, responses)}

def resolve_level(sess):
    if sess.level:
        return sess.level
    answers = sess.answers or {}
    return placement.level_from_experience(answers.get("experience"))

def preview(user):
    """The recommendation, computed and stored but not yet acted on."""
    sess = get_session(user)
    answers = dict(sess.answers or {})
    if not is_complete(answers):
        raise OnboardingError("Finish the questions first.")

    rec = recommend(answers, resolve_level(sess))
    sess.level = rec.level
    sess.recommendation = {
        "track_slug": rec.track_slug,
        "unit_slug": rec.unit_slug,
        "level": rec.level,
        "daily_goal_xp": rec.daily_goal_xp,
        "focus_topics": rec.focus_topics,
        "reasons": rec.reasons,
        "track_title": TRACKS_BY_SLUG[rec.track_slug].title,
    }
    sess.updated_at = _utcnow()
    db.session.commit()
    return sess.recommendation

def complete(user, track_slug=None):
    """Write the questionnaire onto the user: enrollment, goal, language, level."""
    sess = get_session(user)
    answers = dict(sess.answers or {})
    if not is_complete(answers):
        raise OnboardingError("Finish the questions first.")

    rec = sess.recommendation or preview(user)
    chosen_slug = track_slug or rec["track_slug"]
    if chosen_slug not in TRACKS_BY_SLUG:
        raise OnboardingError("Unknown track.")

    track = db.session.execute(
        db.select(Track).filter_by(slug=chosen_slug)
    ).scalar_one_or_none()
    if track is None:
        raise OnboardingError("catalog_missing")

    unit_slug = rec["unit_slug"] if chosen_slug == rec["track_slug"] else None
    first_lesson = _first_lesson(track, unit_slug)

    enrollment = db.session.execute(
        db.select(Enrollment).filter_by(user_id=user.id, track_id=track.id)
    ).scalar_one_or_none()
    if enrollment is None:
        enrollment = Enrollment(user_id=user.id, track_id=track.id)
        db.session.add(enrollment)
    enrollment.current_lesson_id = first_lesson.id if first_lesson else None
    enrollment.is_primary = True

    # Exactly one primary enrollment per user.
    db.session.execute(
        db.update(Enrollment)
        .where(Enrollment.user_id == user.id, Enrollment.track_id != track.id)
        .values(is_primary=False)
        .execution_options(synchronize_session=False)
    )

    user.daily_goal_xp = rec["daily_goal_xp"]
    user.preferred_language = answers.get("language") or user.preferred_language
    if answers.get("topics"):
        user.interest = answers["topics"][0]
    user.onboarded_at = _utcnow()

    sess.completed_at = _utcnow()
    db.session.commit()

    return {
        "track": {"slug": track.slug, "title": track.title},
        "level": rec["level"],
        "daily_goal_xp": user.daily_goal_xp,
        "next_lesson": _lesson_payload(first_lesson),
        "progress": level_progress(user.xp_total or 0),
    }

def _first_lesson(track, unit_slug):
    unit = None
    if unit_slug:
        unit = db.session.execute(
            db.select(Unit).filter_by(track_id=track.id, slug=unit_slug)
        ).scalar_one_or_none()
    if unit is None:
        unit = db.session.execute(
            db.select(Unit).filter_by(track_id=track.id).order_by(Unit.position).limit(1)
        ).scalar_one_or_none()
    if unit is None:
        return None
    return db.session.execute(
        db.select(Lesson).filter_by(unit_id=unit.id).order_by(Lesson.position).limit(1)
    ).scalar_one_or_none()

def _lesson_payload(lesson):
    if lesson is None:
        return None
    return {"id": lesson.id, "slug": lesson.slug, "title": lesson.title,
            "kind": lesson.kind, "xp": lesson.xp,
            "unit": {"slug": lesson.unit.slug, "title": lesson.unit.title}}

def tracks_for_choice(recommended_slug=None):
    """Every seeded track, so the review screen can offer an alternative."""
    rows = db.session.execute(db.select(Track).order_by(Track.position)).scalars().all()
    return [{"slug": t.slug, "title": t.title, "description": t.description,
             "recommended": t.slug == recommended_slug} for t in rows]

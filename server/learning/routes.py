"""The learning surface: choose a path, read the concepts, solve the problems.

The catalog/enrollment tables already existed; this is the UI and the state
transitions on top of them.
"""

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

from ..models import (Enrollment, Lesson, LessonProgress, Problem, Submission,
                      Track, Unit, db)
from ..progress import award_xp
from ..session import current_user, login_required
from .catalog import quiz_for
from .markdown import render as render_md

learn_bp = Blueprint("learn", __name__, url_prefix="/learn")


# ---------------------------------------------------------------- lookups

def _track_or_404(slug):
    track = db.session.execute(
        db.select(Track).filter_by(slug=slug)
    ).scalar_one_or_none()
    if track is None:
        abort(404)
    return track


def _lesson_or_404(track, unit_slug, lesson_slug):
    unit = db.session.execute(
        db.select(Unit).filter_by(track_id=track.id, slug=unit_slug)
    ).scalar_one_or_none()
    if unit is None:
        abort(404)
    lesson = db.session.execute(
        db.select(Lesson).filter_by(unit_id=unit.id, slug=lesson_slug)
    ).scalar_one_or_none()
    if lesson is None:
        abort(404)
    return unit, lesson


def _ordered_lessons(track):
    """Every lesson in the track, in the order a learner walks them."""
    return db.session.execute(
        db.select(Lesson)
        .join(Unit, Lesson.unit_id == Unit.id)
        .where(Unit.track_id == track.id)
        .order_by(Unit.position, Lesson.position)
    ).scalars().all()


def _completed_ids(user):
    if user is None:
        return set()
    return set(db.session.execute(
        db.select(LessonProgress.lesson_id).where(LessonProgress.user_id == user.id)
    ).scalars())


def _solved_problem_ids(user):
    if user is None:
        return set()
    return set(db.session.execute(
        db.select(Submission.problem_id)
        .where(Submission.user_id == user.id, Submission.verdict == "accepted")
    ).scalars())


def _enrollments_by_track(user):
    if user is None:
        return {}
    rows = db.session.execute(
        db.select(Enrollment).where(Enrollment.user_id == user.id)
    ).scalars().all()
    return {row.track_id: row for row in rows}


# ---------------------------------------------------------------- state

def _next_lesson(track, done_ids):
    """First lesson the learner has not finished - what 'Continue' points at."""
    for lesson in _ordered_lessons(track):
        if lesson.id not in done_ids:
            return lesson
    return None


def _track_summary(track, done_ids):
    lessons = _ordered_lessons(track)
    done = sum(1 for lesson in lessons if lesson.id in done_ids)
    total = len(lessons)
    return {
        "track": track,
        "total": total,
        "done": done,
        "percent": round(done * 100 / total) if total else 0,
        "xp_total": sum(lesson.xp for lesson in lessons),
        "levels": sorted({unit.level for unit in track.units}),
        "next": _next_lesson(track, done_ids),
    }


def _enroll(user, track, current_lesson):
    """Join a track and make it the primary one. Exactly one primary per user,
    matching what onboarding.complete() guarantees."""
    enrollment = db.session.execute(
        db.select(Enrollment).filter_by(user_id=user.id, track_id=track.id)
    ).scalar_one_or_none()
    if enrollment is None:
        enrollment = Enrollment(user_id=user.id, track_id=track.id)
        db.session.add(enrollment)
    if enrollment.current_lesson_id is None and current_lesson is not None:
        enrollment.current_lesson_id = current_lesson.id
    enrollment.is_primary = True
    db.session.execute(
        db.update(Enrollment)
        .where(Enrollment.user_id == user.id, Enrollment.track_id != track.id)
        .values(is_primary=False)
        .execution_options(synchronize_session=False)
    )
    return enrollment


def _advance(user, track, done_ids):
    """Point the enrollment at the next unfinished lesson."""
    enrollment = db.session.execute(
        db.select(Enrollment).filter_by(user_id=user.id, track_id=track.id)
    ).scalar_one_or_none()
    if enrollment is not None:
        nxt = _next_lesson(track, done_ids)
        enrollment.current_lesson_id = nxt.id if nxt else None


def _gate(lesson, user, solved_ids):
    """Can this lesson be marked done? Reading is self-attested; code and quiz
    lessons have to be earned. Returns (ok, message)."""
    if lesson.kind == "code":
        if lesson.problem_id is None:
            return False, "This lesson has no problem attached yet."
        if lesson.problem_id not in solved_ids:
            return False, "Solve the problem first - the lesson completes itself when the judge accepts it."
    return True, ""


def _complete(user, track, lesson):
    """Record completion and award XP. Both are idempotent: the unique
    constraints on lesson_progress and xp_events absorb a double submit."""
    done_ids = _completed_ids(user)
    if lesson.id in done_ids:
        return None

    db.session.add(LessonProgress(user_id=user.id, lesson_id=lesson.id))
    db.session.flush()
    done_ids.add(lesson.id)

    result = award_xp(user, lesson.xp, "lesson", str(lesson.id))
    _enroll(user, track, lesson)
    _advance(user, track, done_ids)
    db.session.commit()
    return result


# ---------------------------------------------------------------- views

@learn_bp.route("/")
@login_required
def index():
    """Choose a course path."""
    user = current_user()
    done_ids = _completed_ids(user)
    enrollments = _enrollments_by_track(user)
    tracks = db.session.execute(
        db.select(Track).order_by(Track.position)
    ).scalars().all()

    summaries = []
    for track in tracks:
        summary = _track_summary(track, done_ids)
        enrollment = enrollments.get(track.id)
        summary["enrolled"] = enrollment is not None
        summary["primary"] = bool(enrollment and enrollment.is_primary)
        summaries.append(summary)

    return render_template("learn/index.html", tracks=summaries,
                           any_enrolled=bool(enrollments))


@learn_bp.route("/<track_slug>/")
@login_required
def track(track_slug):
    """One path, unit by unit."""
    user = current_user()
    track = _track_or_404(track_slug)
    done_ids = _completed_ids(user)
    solved_ids = _solved_problem_ids(user)
    summary = _track_summary(track, done_ids)
    next_lesson = summary["next"]

    units = []
    for unit in track.units:
        rows = []
        for lesson in unit.lessons:
            rows.append({
                "lesson": lesson,
                "done": lesson.id in done_ids,
                "is_next": next_lesson is not None and lesson.id == next_lesson.id,
                "solved": (lesson.problem_id in solved_ids
                           if lesson.problem_id else False),
            })
        units.append({
            "unit": unit,
            "lessons": rows,
            "done": all(row["done"] for row in rows) if rows else False,
        })

    enrollment = _enrollments_by_track(user).get(track.id)
    return render_template("learn/track.html", track=track, units=units,
                           summary=summary, enrolled=enrollment is not None,
                           is_primary=bool(enrollment and enrollment.is_primary))


@learn_bp.route("/<track_slug>/enroll", methods=["POST"])
@login_required
def enroll(track_slug):
    user = current_user()
    track = _track_or_404(track_slug)
    done_ids = _completed_ids(user)
    nxt = _next_lesson(track, done_ids)
    _enroll(user, track, nxt)
    db.session.commit()

    flash("You're on %s. Next up: %s."
          % (track.title, nxt.title if nxt else "nothing left, you finished it"),
          "success")
    if nxt is None:
        return redirect(url_for("learn.track", track_slug=track.slug))
    return redirect(url_for("learn.lesson", track_slug=track.slug,
                            unit_slug=nxt.unit.slug, lesson_slug=nxt.slug))


@learn_bp.route("/<track_slug>/<unit_slug>/<lesson_slug>/")
@login_required
def lesson(track_slug, unit_slug, lesson_slug):
    """A concept, a quiz, or the brief for a problem."""
    user = current_user()
    track = _track_or_404(track_slug)
    unit, lesson = _lesson_or_404(track, unit_slug, lesson_slug)

    done_ids = _completed_ids(user)
    solved_ids = _solved_problem_ids(user)
    ordered = _ordered_lessons(track)
    index = next(i for i, row in enumerate(ordered) if row.id == lesson.id)
    can_complete, gate_message = _gate(lesson, user, solved_ids)

    return render_template(
        "learn/lesson.html",
        track=track, unit=unit, lesson=lesson,
        body=render_md(lesson.body_md),
        quiz=[q.public() for q in quiz_for(track.slug, unit.slug, lesson.slug)],
        done=lesson.id in done_ids,
        can_complete=can_complete,
        gate_message=gate_message,
        solved=(lesson.problem_id in solved_ids if lesson.problem_id else False),
        position=index + 1,
        total=len(ordered),
        prev=ordered[index - 1] if index > 0 else None,
        next=ordered[index + 1] if index + 1 < len(ordered) else None,
        results=None,
    )


@learn_bp.route("/<track_slug>/<unit_slug>/<lesson_slug>/complete", methods=["POST"])
@login_required
def complete(track_slug, unit_slug, lesson_slug):
    user = current_user()
    track = _track_or_404(track_slug)
    unit, lesson = _lesson_or_404(track, unit_slug, lesson_slug)
    solved_ids = _solved_problem_ids(user)

    ok, message = _gate(lesson, user, solved_ids)
    if not ok:
        flash(message, "error")
        return redirect(url_for("learn.lesson", track_slug=track.slug,
                                unit_slug=unit.slug, lesson_slug=lesson.slug))

    questions = quiz_for(track.slug, unit.slug, lesson.slug)
    if questions:
        # Grade server-side; the correct answers never leave the catalog.
        results = {q.id: request.form.get(q.id) == q.answer for q in questions}
        if not all(results.values()):
            wrong = sum(1 for correct in results.values() if not correct)
            done_ids = _completed_ids(user)
            ordered = _ordered_lessons(track)
            index = next(i for i, row in enumerate(ordered) if row.id == lesson.id)
            flash("%d of %d not right yet - the wrong ones are marked."
                  % (wrong, len(questions)), "error")
            return render_template(
                "learn/lesson.html",
                track=track, unit=unit, lesson=lesson,
                body=render_md(lesson.body_md),
                quiz=[q.public() for q in questions],
                done=lesson.id in done_ids,
                can_complete=True, gate_message="",
                solved=False,
                position=index + 1, total=len(ordered),
                prev=ordered[index - 1] if index > 0 else None,
                next=ordered[index + 1] if index + 1 < len(ordered) else None,
                results=results,
                answers={q.id: request.form.get(q.id) for q in questions},
            )

    result = _complete(user, track, lesson)
    if result is None:
        flash("Already done - no XP twice.", "success")
    else:
        flash("+%d XP%s" % (result["awarded"],
                            " - level %d!" % result["level"] if result["leveled_up"] else ""),
              "success")

    nxt = _next_lesson(track, _completed_ids(user))
    if nxt is None:
        flash("That's the whole %s track finished." % track.title, "success")
        return redirect(url_for("learn.track", track_slug=track.slug))
    return redirect(url_for("learn.lesson", track_slug=track.slug,
                            unit_slug=nxt.unit.slug, lesson_slug=nxt.slug))


# ---------------------------------------------------------------- hooks

def complete_lessons_for_problem(user, problem_id):
    """Called by the judge when a submission is accepted: any code lesson
    wrapping that problem is finished by definition, so close it out and pay
    the lesson XP. Returns the total lesson XP awarded."""
    lessons = db.session.execute(
        db.select(Lesson).where(Lesson.problem_id == problem_id)
    ).scalars().all()
    if not lessons:
        return 0

    done_ids = _completed_ids(user)
    enrolled_track_ids = set(_enrollments_by_track(user))
    awarded = 0

    for lesson in lessons:
        if lesson.id in done_ids:
            continue
        track = lesson.unit.track
        # Only auto-complete inside a track they actually joined; solving a
        # problem shouldn't silently tick off lessons on paths they never took.
        if track.id not in enrolled_track_ids:
            continue
        db.session.add(LessonProgress(user_id=user.id, lesson_id=lesson.id))
        db.session.flush()
        done_ids.add(lesson.id)
        awarded += award_xp(user, lesson.xp, "lesson", str(lesson.id))["awarded"]
        _advance(user, track, done_ids)

    return awarded

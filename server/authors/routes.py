from functools import wraps

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, url_for)

from ..admin_gate import is_admin
from ..learning import quiz
from ..learning.markdown import render as render_md
from ..models import (DRAFT, PUBLISHED, REVIEW, Lesson, LessonChoice,
                      LessonQuestion, Problem, Track, Unit, _utcnow, db)
from ..session import current_user, login_required
from ..validators import SLUG_RE, slugify
from . import blockers
from .invites import accept, find_invite, refusal

authors_bp = Blueprint("authors", __name__, url_prefix="/authors")

MAX_CHOICES = 6

def _xp_override(raw):
    raw = (raw or "").strip() if isinstance(raw, str) else raw
    if raw is None or raw == "":
        return None
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return None


LESSON_KINDS = ("reading", "quiz", "code")
LEVELS = ("beginner", "intermediate", "advanced")

def author_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return redirect(url_for("auth.login_page", next=request.full_path))
        if not (user.is_author or is_admin(user)):
            abort(404)
        return view(*args, **kwargs)
    return wrapped

def _mine_or_404(model, pk):
    row = db.session.get(model, pk)
    if row is None:
        abort(404)
    user = current_user()
    if is_admin(user):
        return row
    if row.created_by_id != user.id:
        abort(404)
    if row.status == PUBLISHED:
        abort(403)
    return row


@authors_bp.route("/join/<token>", methods=["GET"])
@login_required
def join(token):
    invite = find_invite(token)
    user = current_user()
    problem = refusal(invite, user)
    return render_template("authors/join.html", token=token, problem=problem, invite=None if problem else invite, already = user.is_author )


@authors_bp.route("/join/<token>", methods=["POST"])
@login_required
def join_accept(token):
    invite = find_invite(token)
    user = current_user()

    problem = refusal(invite, user)
    if problem:
        flash(problem, "error")
        return redirect(url_for("dashboard.index"))

    if accept(invite, user):
        flash("You are an author now. Welcome aboard.", "success")
    return redirect(url_for("authors.index"))

@authors_bp.route("/")
@author_required
def index():
    user = current_user()
    mine = {} if is_admin(user) else {"created_by_id": user.id}

    def rows(model):
        stmt = db.select(model).order_by(model.status, model.id.desc())
        if mine:
            stmt = stmt.filter_by(**mine)
        return db.session.execute(stmt).scalars().all()

    tracks, units, lessons = rows(Track), rows(Unit), rows(Lesson)
    counts = {s: sum(1 for r in tracks + units + lessons if r.status == s)
              for s in (DRAFT, REVIEW, PUBLISHED)}

    notes = {}
    for kind, items in (("track", tracks), ("unit", units), ("lesson", lessons)):
        for row in items:
            if row.status != PUBLISHED:
                notes[(kind, row.id)] = {
                    "problems": blockers.problems(kind, row),
                    "waiting": blockers.waiting_on(kind, row),
                }
    return render_template("authors/index.html", tracks=tracks, units=units,
                           lessons=lessons, counts=counts, notes=notes)

def _owned_units():
    user = current_user()
    stmt = db.select(Unit).join(Track).order_by(Track.position, Unit.position)
    if not is_admin(user):
        stmt = stmt.where(db.or_(Unit.created_by_id == user.id,
                                 Unit.status == PUBLISHED))
    return db.session.execute(stmt).scalars().all()

@authors_bp.route("/tracks/new", methods=["GET", "POST"])
@authors_bp.route("/tracks/<int:track_id>/edit", methods=["GET", "POST"])
@author_required
def track_form(track_id=None):
    track = _mine_or_404(Track, track_id) if track_id else None

    if request.method == "GET":
        return render_template("authors/track_form.html", track=track,
                               errors={}, form={})

    form = request.form
    errors = {}
    title = (form.get("title") or "").strip()
    slug = (form.get("slug") or "").strip().lower() or slugify(title)

    if not title:
        errors["title"] = "Give it a title."
    if not SLUG_RE.match(slug):
        errors["slug"] = "Lowercase letters, numbers and hyphens."
    else:
        clash = db.session.execute(
            db.select(Track).filter_by(slug=slug)).scalar_one_or_none()
        if clash is not None and (track is None or clash.id != track.id):
            errors["slug"] = "That slug is taken."

    if errors:
        return render_template("authors/track_form.html", track=track,
                               errors=errors, form=form), 400

    if track is None:
        track = Track(slug=slug, created_by_id=current_user().id, status=DRAFT)
        db.session.add(track)

    track.slug = slug
    track.title = title
    track.description = form.get("description") or ""
    track.position = int(form.get("position") or 0)
    db.session.commit()

    flash("Course saved as a draft.", "success")
    return redirect(url_for("authors.track_form", track_id=track.id))


@authors_bp.route("/units/new", methods=["GET", "POST"])
@authors_bp.route("/units/<int:unit_id>/edit", methods=["GET", "POST"])
@author_required
def unit_form(unit_id=None):
    unit = _mine_or_404(Unit, unit_id) if unit_id else None
    user = current_user()

    stmt = db.select(Track).order_by(Track.position)
    if not is_admin(user):
        stmt = stmt.where(db.or_(Track.created_by_id == user.id,
                                 Track.status == PUBLISHED))
    tracks = db.session.execute(stmt).scalars().all()

    if request.method == "GET":
        return render_template("authors/unit_form.html", unit=unit, tracks=tracks,
                               levels=LEVELS, errors={}, form={})

    form = request.form
    errors = {}
    title = (form.get("title") or "").strip()
    slug = (form.get("slug") or "").strip().lower() or slugify(title)
    level = form.get("level") if form.get("level") in LEVELS else "beginner"

    track = db.session.get(Track, int(form.get("track_id") or 0))
    if track is None or track not in tracks:
        errors["track_id"] = "Pick a course."
    if not title:
        errors["title"] = "Give it a title."
    if not SLUG_RE.match(slug):
        errors["slug"] = "Lowercase letters, numbers and hyphens."
    elif track is not None:
        clash = db.session.execute(
            db.select(Unit).filter_by(track_id=track.id, slug=slug)
        ).scalar_one_or_none()
        if clash is not None and (unit is None or clash.id != unit.id):
            errors["slug"] = "That slug is already used in this course."

    if errors:
        return render_template("authors/unit_form.html", unit=unit, tracks=tracks,
                               levels=LEVELS, errors=errors, form=form), 400

    if unit is None:
        unit = Unit(track_id=track.id, slug=slug,
                    created_by_id=user.id, status=DRAFT)
        db.session.add(unit)

    unit.track_id = track.id
    unit.slug = slug
    unit.title = title
    unit.level = level
    unit.topic = (form.get("topic") or "").strip() or None
    unit.position = int(form.get("position") or 0)
    db.session.commit()

    flash("Unit saved as a draft.", "success")
    return redirect(url_for("authors.unit_form", unit_id=unit.id))


@authors_bp.route("/lessons/new", methods=["GET", "POST"])
@authors_bp.route("/lessons/<int:lesson_id>/edit", methods=["GET", "POST"])
@author_required
def lesson_form(lesson_id=None):
    lesson = _mine_or_404(Lesson, lesson_id) if lesson_id else None
    units = _owned_units()
    problems = db.session.execute(
        db.select(Problem).order_by(Problem.slug)).scalars().all()
    if request.method == "GET":
        return render_template("authors/lesson_form.html", lesson=lesson,
                               units=units, problems=problems,
                               kinds=LESSON_KINDS, errors={}, form={})

    form = request.form
    errors = {}
    title = (form.get("title") or "").strip()
    slug = (form.get("slug") or "").strip().lower() or slugify(title)
    kind = form.get("kind") if form.get("kind") in LESSON_KINDS else "reading"

    unit = db.session.get(Unit, int(form.get("unit_id") or 0))
    if unit is None or unit not in units:
        errors["unit_id"] = "Pick a unit."
    if not title:
        errors["title"] = "Give it a title."
    if not SLUG_RE.match(slug):
        errors["slug"] = "Lowercase letters, numbers and hyphens."
    elif unit is not None:
        clash = db.session.execute(
            db.select(Lesson).filter_by(unit_id=unit.id, slug=slug)
        ).scalar_one_or_none()
        if clash is not None and (lesson is None or clash.id != lesson.id):
            errors["slug"] = "That slug is already used in this unit."

    problem_id = form.get("problem_id") or ""
    if kind == "code" and not problem_id:
        errors["problem_id"] = "A code lesson needs a problem."
    if errors:
        return render_template("authors/lesson_form.html", lesson=lesson,
                               units=units, problems=problems,
                               kinds=LESSON_KINDS, errors=errors, form=form), 400

    if lesson is None:
        lesson = Lesson(unit_id=unit.id, slug=slug,
                        created_by_id=current_user().id, status=DRAFT)
        db.session.add(lesson)

    lesson.unit_id = unit.id
    lesson.slug = slug
    lesson.title = title
    lesson.kind = kind
    lesson.xp_override = _xp_override(form.get("xp"))
    lesson.body_md = form.get("body_md") or ""
    lesson.position = int(form.get("position") or 0)
    lesson.problem_id = int(problem_id) if problem_id else None
    db.session.commit()

    flash("Lesson saved as a draft.", "success")
    return redirect(url_for("authors.lesson_form", lesson_id=lesson.id))


MODELS = {"track" : Track, "unit": Unit, "lesson" : Lesson}

@authors_bp.route("/<kind>/<int:row_id>/submit", methods=["POST"])
@author_required
def submit(kind, row_id):
    model = MODELS.get(kind)
    if model is None:
        abort(404)
    row = _mine_or_404(model, row_id)

    stop = blockers.problems(kind, row)
    if stop:
        flash(" ".join(stop), "error")
        return redirect(_edit_url(kind, row_id))

    if row.status == DRAFT:
        row.status = REVIEW
        row.submitted_at = _utcnow()
        row.review_note = ""            # the old rejection no longer applies
        db.session.commit()
        flash("Sent for review.", "success")
    return redirect(url_for("authors.index"))


@authors_bp.route("/<kind>/<int:row_id>/withdraw", methods=["POST"])
@author_required
def withdraw(kind, row_id):
    model = MODELS.get(kind)
    if model is None:
        abort(404)
    row = _mine_or_404(model, row_id)

    if row.status == REVIEW:
        row.status = DRAFT
        row.submitted_at = None
        db.session.commit()
        flash("Pulled back to draft.", "success")
    return redirect(url_for("authors.index"))
def _edit_url(kind, row_id):
    if kind == "track":
        return url_for("authors.track_form", track_id=row_id)
    if kind == "unit":
        return url_for("authors.unit_form", unit_id=row_id)
    return url_for("authors.lesson_form", lesson_id=row_id)


def _children_blocking(kind, row):
    if kind == "track" and row.units:
        return ("This course still holds %d unit%s. Empty it first."
                % (len(row.units), "" if len(row.units) == 1 else "s"))
    if kind == "unit" and row.lessons:
        return ("This unit still holds %d lesson%s. Empty it first."
                % (len(row.lessons), "" if len(row.lessons) == 1 else "s"))
    return None


@authors_bp.route("/<kind>/<int:row_id>/delete", methods=["POST"])
@author_required
def delete(kind, row_id):
    model = MODELS.get(kind)
    if model is None:
        abort(404)
    # _mine_or_404 already refuses someone else's row, and anything published.
    row = _mine_or_404(model, row_id)

    if (request.form.get("confirm") or "").strip().lower() != row.slug:
        flash("Type the slug exactly to delete it.", "error")
        return redirect(_edit_url(kind, row_id))

    blocked = _children_blocking(kind, row)
    if blocked:
        flash(blocked, "error")
        return redirect(_edit_url(kind, row_id))

    slug = row.slug
    db.session.delete(row)
    db.session.commit()
    flash("Deleted %s." % slug, "success")
    return redirect(url_for("authors.index"))

def _lesson_for_quiz(lesson_id):
    lesson = _mine_or_404(Lesson, lesson_id)
    if lesson.status == PUBLISHED and not is_admin(current_user()):
        abort(403)
    return lesson

def _read_choices(form):
    out = []
    marked = form.get("correct") or ""
    for i in range(MAX_CHOICES):
        text = (form.get("choice_%d" % i) or "").strip()
        if text:
            out.append((text[:500], marked == str(i)))
    return out

@authors_bp.route("/lessons/<int:lesson_id>/quiz")
@author_required
def quiz_edit(lesson_id):
    lesson = _lesson_for_quiz(lesson_id)
    return render_template("authors/quiz.html", lesson=lesson,
                           questions=quiz.rows_for(lesson.id),
                           max_choices=MAX_CHOICES, errors={}, form={})

@authors_bp.route("/lessons/<int:lesson_id>/quiz", methods=["POST"])
@author_required
def quiz_add(lesson_id):
    lesson = _lesson_for_quiz(lesson_id)
    form = request.form
    prompt = (form.get("prompt") or "").strip()
    choices = _read_choices(form)

    errors = {}
    if not prompt:
        errors["prompt"] = "Ask something."
    if len(choices) < 2:
        errors["choices"] = "Give at least two answers."
    elif sum(1 for _, correct in choices if correct) != 1:
        errors["correct"] = "Mark exactly one answer as correct."

    if errors:
        return render_template("authors/quiz.html", lesson=lesson,
                               questions=quiz.rows_for(lesson.id),
                               max_choices=MAX_CHOICES,
                               errors=errors, form=form), 400

    last = db.session.execute(
        db.select(db.func.coalesce(db.func.max(LessonQuestion.position), -1))
        .where(LessonQuestion.lesson_id == lesson.id)).scalar()
    question = LessonQuestion(lesson_id=lesson.id, position=last + 1,
                              prompt=prompt[:2000],
                              explanation=(form.get("explanation") or "")[:2000])
    db.session.add(question)
    db.session.flush()
    for i, (text, correct) in enumerate(choices):
        db.session.add(LessonChoice(question_id=question.id, position=i,
                                    text=text, is_correct=correct))
    db.session.commit()
    flash("Question added.", "success")
    return redirect(url_for("authors.quiz_edit", lesson_id=lesson.id))

@authors_bp.route("/questions/<int:question_id>/delete", methods=["POST"])
@author_required
def quiz_delete(question_id):
    question = db.session.get(LessonQuestion, question_id)
    if question is None:
        abort(404)
    lesson = _lesson_for_quiz(question.lesson_id)
    db.session.delete(question)
    db.session.commit()
    flash("Question removed.", "success")
    return redirect(url_for("authors.quiz_edit", lesson_id=lesson.id))


@authors_bp.route("/questions/<int:question_id>/move", methods=["POST"])
@author_required
def quiz_move(question_id):
    question = db.session.get(LessonQuestion, question_id)
    if question is None:
        abort(404)
    lesson = _lesson_for_quiz(question.lesson_id)
    rows = quiz.rows_for(lesson.id)
    i = next(n for n, r in enumerate(rows) if r.id == question.id)
    j = i - 1 if request.form.get("dir") == "up" else i + 1
    if 0 <= j < len(rows):
        rows[i], rows[j] = rows[j], rows[i]
        for n, r in enumerate(rows):
            r.position = n
        db.session.commit()
    return redirect(url_for("authors.quiz_edit", lesson_id=lesson.id))


@authors_bp.route("/preview", methods=["POST"])
@author_required
def preview():
    return jsonify(html=str(render_md(request.form.get("body_md") or "")))

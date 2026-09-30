from functools import wraps
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

from ..admin_gate import is_admin
from ..models import (DRAFT, PUBLISHED, REVIEW, Lesson, Problem, Track, Unit,
                      _utcnow, db)
from ..session import current_user, login_required
from ..validators import SLUG_RE, slugify
from .invites import accept, find_invite, refusal

authors_bp = Blueprint("authors", __name__, url_prefix="/authors")

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
    return render_template("authors/index.html", tracks=tracks, units=units,
                           lessons=lessons, counts=counts)

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
    lesson.xp = int(form.get("xp") or 10)
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

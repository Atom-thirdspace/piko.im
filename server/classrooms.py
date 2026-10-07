from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)

from .models import (Assignment, AssignmentItem, Classroom, ClassroomMember,
                     Problem, _utcnow, active_seat, db, new_join_code,
                     owned_classrooms)
from .session import current_user, login_required

classroom_bp = Blueprint("classroom", __name__, url_prefix="/classroom")

MAX_NAME = 120

MAX_BULK_INVITES = 60

def _mine_or_404(class_id):
    row = db.session.get(Classroom, class_id)
    if row is None or row.owner_id != current_user().id:
        abort(404)
    return row

@classroom_bp.route("/")
@login_required
def index():
    user = current_user()
    return render_template("classroom/index.html",
                           owned=owned_classrooms(user), seat=active_seat(user))

@classroom_bp.route("/<int:class_id>/")
@login_required
def detail(class_id):
    return render_template("classroom/detail.html", cls=_mine_or_404(class_id))


@classroom_bp.route("/<int:class_id>/rename", methods=["POST"])
@login_required
def rename(class_id):
    cls = _mine_or_404(class_id)
    cls.name = (request.form.get("name") or "")[:MAX_NAME].strip() or cls.name
    cls.institution = (request.form.get("institution") or "")[:160].strip()
    db.session.commit()
    flash("Saved.", "success")
    return redirect(url_for("classroom.detail", class_id=cls.id))


@classroom_bp.route("/<int:class_id>/code", methods=["POST"])
@login_required
def rotate_code(class_id):
    cls = _mine_or_404(class_id)
    cls.join_code = new_join_code()
    db.session.commit()
    flash("New join code. The old one no longer works.", "success")
    return redirect(url_for("classroom.detail", class_id=cls.id))


@classroom_bp.route("/<int:class_id>/remove/<int:user_id>", methods=["POST"])
@login_required
def remove(class_id, user_id):
    cls = _mine_or_404(class_id)
    row = db.session.execute(
        db.select(ClassroomMember).filter_by(classroom_id=cls.id, user_id=user_id)
    ).scalar_one_or_none()
    if row is not None and row.removed_at is None:
        row.removed_at = _utcnow()
        db.session.commit()
        flash("Removed. Their seat is free again.", "success")
    return redirect(url_for("classroom.detail", class_id=cls.id))

@classroom_bp.route("/join", methods=["GET", "POST"])
@login_required
def join():
    code = (request.values.get("code") or "").strip().upper()
    if request.method == "GET":
        return render_template("classroom/join.html", code=code, error=None)

    cls = db.session.execute(
        db.select(Classroom).filter_by(join_code=code)).scalar_one_or_none()

    # One message for every failure: a wrong code and an expired one must not
    # be distinguishable, or the code space becomes enumerable.
    if cls is None or not cls.is_live:
        return render_template("classroom/join.html", code=code,
                               error="That code does not work."), 404

    user = current_user()
    if cls.owner_id == user.id:
        return render_template("classroom/join.html", code=code,
                               error="This is your own classroom."), 400

    row = db.session.execute(
        db.select(ClassroomMember).filter_by(classroom_id=cls.id, user_id=user.id)
    ).scalar_one_or_none()

    if row is not None and row.removed_at is None:
        return redirect(url_for("classroom.index"))

    if cls.seats_free <= 0:
        return render_template("classroom/join.html", code=code,
                               error="That classroom is full."), 409

    if row is None:
        db.session.add(ClassroomMember(classroom_id=cls.id, user_id=user.id))
    else:
        row.removed_at = None
        row.joined_at = _utcnow()
    db.session.commit()
    flash("You are in. Pro is on for as long as you are in this class.",
          "success")
    return redirect(url_for("classroom.index")) 


@classroom_bp.route("/leave/<int:class_id>", methods=["POST"])
@login_required
def leave(class_id):
    row = db.session.execute(
        db.select(ClassroomMember).filter_by(classroom_id=class_id,
                                             user_id=current_user().id)
    ).scalar_one_or_none()
    if row is not None and row.removed_at is None:
        row.removed_at = _utcnow()
        db.session.commit()
        flash("You have left the class.", "success")
    return redirect(url_for("classroom.index"))

@classroom_bp.route("/<int:class_id>/assignments/", methods=["GET"])
@login_required
def assignments(class_id):
    room = _mine_or_404(class_id)
    rows = db.session.execute(
        db.select(Assignment).where(Assignment.classroom_id == room.id)
        .order_by(Assignment.due_at.is_(None), Assignment.due_at,
                  Assignment.id.desc())).scalars().all()
    return render_template("classroom/assignments.html", room=room,
                           assignments=rows)


@classroom_bp.route("/<int:class_id>/assignments/new", methods=["POST"])
@login_required
def assignment_new(class_id):
    from datetime import datetime, timezone as _tz
    room = _mine_or_404(class_id)
    form = request.form
    title = (form.get("title") or "").strip()
    if not title:
        flash("Give the assignment a title.", "error")
        return redirect(url_for("classroom.assignments", class_id=room.id))

    due = None
    raw = (form.get("due_at") or "").strip()
    if raw:
        try:                                  # the browser sends local time
            due = datetime.fromisoformat(raw).replace(tzinfo=_tz.utc)
        except ValueError:
            flash("That due date did not parse - leaving it open.", "error")

    row = Assignment(classroom_id=room.id, title=title[:200],
                     note_md=form.get("note_md") or "", due_at=due,
                     created_by_id=current_user().id)
    db.session.add(row)
    db.session.commit()
    flash("Assignment created. Add some work to it.", "success")
    return redirect(url_for("classroom.assignment", class_id=room.id,
                            assignment_id=row.id))

@classroom_bp.route("/<int:class_id>/assignments/<int:assignment_id>/")
@login_required
def assignment(class_id, assignment_id):
    room = _mine_or_404(class_id)
    row = db.session.get(Assignment, assignment_id)
    if row is None or row.classroom_id != room.id:
        abort(404)
    from . import gradebook
    from .content import visible
    return render_template(
        "classroom/assignment.html", room=room, assignment=row,
        grid=gradebook.grid(room, row),
        problems=db.session.execute(
            visible(db.select(Problem).order_by(Problem.slug), Problem,
                    current_user())).scalars().all())


@classroom_bp.route("/<int:class_id>/assignments/<int:assignment_id>/items",
                    methods=["POST"])
@login_required
def assignment_add_item(class_id, assignment_id):
    room = _mine_or_404(class_id)
    row = db.session.get(Assignment, assignment_id)
    if row is None or row.classroom_id != room.id:
        abort(404)
    problem_id = request.form.get("problem_id")
    if not problem_id:
        flash("Pick something to assign.", "error")
        return redirect(url_for("classroom.assignment", class_id=room.id,
                                assignment_id=row.id))
    last = db.session.execute(
        db.select(db.func.coalesce(db.func.max(AssignmentItem.position), -1))
        .where(AssignmentItem.assignment_id == row.id)).scalar()
    db.session.add(AssignmentItem(assignment_id=row.id, position=last + 1,
                                  problem_id=int(problem_id)))
    db.session.commit()
    return redirect(url_for("classroom.assignment", class_id=room.id,
                            assignment_id=row.id))


@classroom_bp.route("/<int:class_id>/stuck")
@login_required
def stuck(class_id):
    room = _mine_or_404(class_id)
    from . import gradebook
    return render_template("classroom/stuck.html", room=room,
                           rows=gradebook.stuck(room))

@classroom_bp.route("/<int:class_id>/invite", methods=["POST"])
@login_required
def bulk_invite(class_id):
    import re as _re
    room = _mine_or_404(class_id)
    raw = request.form.get("emails") or ""
    addresses = [a for a in _re.split(r"[,\s;]+", raw) if "@" in a]
    addresses = list(dict.fromkeys(a.lower() for a in addresses))

    if not addresses:
        flash("No addresses in that list.", "error")
        return redirect(url_for("classroom.detail", class_id=room.id))
    if len(addresses) > MAX_BULK_INVITES:
        flash("That is more than %d addresses - send it in batches."
              % MAX_BULK_INVITES, "error")
        return redirect(url_for("classroom.detail", class_id=room.id))

    from . import mailer
    link = url_for("classroom.join",_external=True)
    sent = 0
    for address in addresses:
        try:
            if mailer.send_classroom_invite_email(
                    address, link, room.join_code, room.name,
                    current_user().name or current_user().username):
                sent += 1
        except Exception:
            current_app.logger.exception("classroom invite to %s failed", address)

    flash("Invited %d of %d." % (sent, len(addresses)), "success")
    return redirect(url_for("classroom.detail", class_id=room.id))

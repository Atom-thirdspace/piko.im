from flask import (Blueprint, Response, abort, current_app, flash, redirect,
                   render_template, request, url_for)

from .models import (PUBLISHED, ROLE_STUDENT, ROLE_TA, Assignment,
                     AssignmentItem, Classroom, ClassroomMember, ClassroomPost,
                     Problem, Track, Unit, User, _utcnow, active_seat, db,
                     new_join_code, owned_classrooms)
from .session import current_user, login_required

classroom_bp = Blueprint("classroom", __name__, url_prefix="/classroom")

MAX_NAME = 120

MAX_BULK_INVITES = 60

MAX_POST_TITLE = 200

def _mine_or_404(class_id):
    """Owner only. Anything that changes the room goes through here."""
    row = db.session.get(Classroom, class_id)
    if row is None or row.owner_id != current_user().id:
        abort(404)
    return row


def _staff_or_404(class_id):

    user = current_user()
    row = db.session.get(Classroom, class_id)
    if row is None:
        abort(404)
    if row.owner_id == user.id:
        return row
    is_ta = db.session.execute(
        db.select(ClassroomMember.id)
        .where(ClassroomMember.classroom_id == row.id,
               ClassroomMember.user_id == user.id,
               ClassroomMember.role == ROLE_TA,
               ClassroomMember.removed_at.is_(None))).scalar()
    if is_ta is None:
        abort(404)
    return row


def _assignment_or_404(room, assignment_id):
    row = db.session.get(Assignment, assignment_id)
    if row is None or row.classroom_id != room.id:
        abort(404)
    return row


def _csv(text, filename):
    return Response(text, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition":
                             'attachment; filename="%s"' % filename})


@classroom_bp.route("/")
@login_required
def index():
    user = current_user()
    assisting = db.session.execute(
        db.select(Classroom).join(ClassroomMember,
                                  ClassroomMember.classroom_id == Classroom.id)
        .where(ClassroomMember.user_id == user.id,
               ClassroomMember.role == ROLE_TA,
               ClassroomMember.removed_at.is_(None))
        .order_by(Classroom.created_at.desc())).scalars().all()
    return render_template("classroom/index.html",
                           owned=owned_classrooms(user), assisting=assisting,
                           seat=active_seat(user))

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
    room = _staff_or_404(class_id)
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
    room = _staff_or_404(class_id)
    row = _assignment_or_404(room, assignment_id)

    from . import gradebook
    from .content import visible

    user = current_user()
    units = db.session.execute(
        visible(db.select(Unit).join(Track, Track.id == Unit.track_id)
                .order_by(Track.position, Unit.position), Unit, user)
    ).scalars().all()

    return render_template(
        "classroom/assignment.html", room=room, assignment=row,
        grid=gradebook.grid(room, row), units=units,
        is_owner=room.owner_id == user.id,
        targets=[c for c in owned_classrooms(user) if c.id != room.id],
        problems=db.session.execute(
            visible(db.select(Problem).order_by(Problem.slug), Problem, user)
        ).scalars().all())


@classroom_bp.route("/<int:class_id>/assignments/<int:assignment_id>/items",
                    methods=["POST"])
@login_required
def assignment_add_item(class_id, assignment_id):
    room = _mine_or_404(class_id)
    row = _assignment_or_404(room, assignment_id)
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
    room = _staff_or_404(class_id)
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


# --------------------------------------------------------------------------- #
# exports
# --------------------------------------------------------------------------- #

@classroom_bp.route("/<int:class_id>/assignments/<int:assignment_id>/csv")
@login_required
def assignment_csv(class_id, assignment_id):
    room = _staff_or_404(class_id)
    row = _assignment_or_404(room, assignment_id)
    from . import gradebook
    return _csv(gradebook.as_csv(room, row),
                "gradebook-%d-%d.csv" % (room.id, row.id))


@classroom_bp.route("/<int:class_id>/stuck.csv")
@login_required
def stuck_export(class_id):
    room = _staff_or_404(class_id)
    from . import gradebook
    return _csv(gradebook.stuck_csv(room), "stuck-%d.csv" % room.id)


# --------------------------------------------------------------------------- #
# one student, one problem
# --------------------------------------------------------------------------- #

@classroom_bp.route(
    "/<int:class_id>/student/<int:user_id>/problem/<int:problem_id>/")
@login_required
def student_attempts(class_id, user_id, problem_id):
    room = _staff_or_404(class_id)
    from . import gradebook

    rows = gradebook.attempts(room, user_id, problem_id)
    if rows is None:
        abort(404)

    student = db.session.get(User, user_id)
    problem = db.session.get(Problem, problem_id)
    if student is None or problem is None:
        abort(404)

    from .judge import verdicts as V
    return render_template("classroom/attempts.html", room=room,
                           student=student, problem=problem, rows=rows,
                           verdict_labels=V.LABELS)


# --------------------------------------------------------------------------- #
# building assignments
# --------------------------------------------------------------------------- #

@classroom_bp.route("/<int:class_id>/assignments/<int:assignment_id>/unit",
                    methods=["POST"])
@login_required
def assignment_add_unit(class_id, assignment_id):
    room = _mine_or_404(class_id)
    row = _assignment_or_404(room, assignment_id)

    unit = db.session.get(Unit, int(request.form.get("unit_id") or 0))
    if unit is None or unit.status != PUBLISHED:
        flash("That unit is not available.", "error")
    else:
        from . import gradebook
        added = gradebook.assign_unit(row, unit)
        if added:
            flash("Added %d from %s." % (added, unit.title), "success")
        else:
            flash("Everything in %s was already assigned." % unit.title,
                  "error")
    return redirect(url_for("classroom.assignment", class_id=room.id,
                            assignment_id=row.id))


@classroom_bp.route("/<int:class_id>/assignments/<int:assignment_id>/clone",
                    methods=["POST"])
@login_required
def assignment_clone(class_id, assignment_id):
    room = _mine_or_404(class_id)
    row = _assignment_or_404(room, assignment_id)

    # _mine_or_404 on the target is the whole access check - you can only
    # clone into a room you own.
    target = _mine_or_404(int(request.form.get("to_class_id") or 0))

    from . import gradebook
    copy = gradebook.clone_assignment(row, target, current_user())
    flash("Copied into %s. Set a new due date." % (target.name or "that class"),
          "success")
    return redirect(url_for("classroom.assignment", class_id=target.id,
                            assignment_id=copy.id))


# --------------------------------------------------------------------------- #
# similarity, scoped to this room
# --------------------------------------------------------------------------- #

@classroom_bp.route("/<int:class_id>/similar")
@login_required
def similar(class_id):
    room = _staff_or_404(class_id)
    from . import gradebook
    return render_template("classroom/similar.html", room=room,
                           rows=gradebook.similar_pairs(room))


# --------------------------------------------------------------------------- #
# staff
# --------------------------------------------------------------------------- #

@classroom_bp.route("/<int:class_id>/role/<int:user_id>", methods=["POST"])
@login_required
def set_role(class_id, user_id):
    room = _mine_or_404(class_id)
    role = request.form.get("role")
    if role not in (ROLE_STUDENT, ROLE_TA):
        abort(400)

    row = db.session.execute(
        db.select(ClassroomMember).filter_by(classroom_id=room.id,
                                             user_id=user_id)
    ).scalar_one_or_none()
    if row is None or row.removed_at is not None:
        abort(404)

    row.role = role
    db.session.commit()
    flash("%s is now %s."
          % (row.user.username or "That member",
             "a teaching assistant" if role == ROLE_TA else "a student"),
          "success")
    return redirect(url_for("classroom.detail", class_id=room.id))


# --------------------------------------------------------------------------- #
# announcements
# --------------------------------------------------------------------------- #

@classroom_bp.route("/<int:class_id>/posts/", methods=["GET"])
@login_required
def posts(class_id):
    room = _staff_or_404(class_id)
    rows = db.session.execute(
        db.select(ClassroomPost).where(ClassroomPost.classroom_id == room.id)
        .order_by(ClassroomPost.pinned.desc(),
                  ClassroomPost.created_at.desc()).limit(50)).scalars().all()
    from .learning.markdown import render as render_md
    return render_template("classroom/posts.html", room=room, rows=rows,
                           bodies={p.id: render_md(p.body_md) for p in rows},
                           is_owner=room.owner_id == current_user().id)


@classroom_bp.route("/<int:class_id>/posts", methods=["POST"])
@login_required
def post_new(class_id):
    room = _staff_or_404(class_id)
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("Give the announcement a title.", "error")
        return redirect(url_for("classroom.posts", class_id=room.id))

    row = ClassroomPost(classroom_id=room.id, author_id=current_user().id,
                        title=title[:MAX_POST_TITLE],
                        body_md=request.form.get("body_md") or "",
                        pinned=bool(request.form.get("pinned")))
    db.session.add(row)
    db.session.commit()

    from . import gradebook, notify
    sent = notify.send_many(
        gradebook.roster(room, include_staff=True), "classroom", title,
        body=row.body_md[:500],
        url=url_for("classroom.posts", class_id=room.id),
        ref="post:%d" % row.id,
        email=bool(request.form.get("email")))

    flash("Posted. %d notified." % sent, "success")
    return redirect(url_for("classroom.posts", class_id=room.id))


@classroom_bp.route("/<int:class_id>/posts/<int:post_id>/delete",
                    methods=["POST"])
@login_required
def post_delete(class_id, post_id):
    room = _mine_or_404(class_id)
    row = db.session.get(ClassroomPost, post_id)
    if row is None or row.classroom_id != room.id:
        abort(404)
    db.session.delete(row)
    db.session.commit()
    flash("Deleted.", "success")
    return redirect(url_for("classroom.posts", class_id=room.id))

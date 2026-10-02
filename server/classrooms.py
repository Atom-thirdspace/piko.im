from flask import (Blueprint, abort, flash, redirect, render_template,
                   request, url_for)

from .models import (Classroom, ClassroomMember, _utcnow, active_seat, db,
                     new_join_code, owned_classrooms)
from .session import current_user, login_required

classroom_bp = Blueprint("classroom", __name__, url_prefix="/classroom")

MAX_NAME = 120

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

"""Student verification: prove you are at an institution, get the discount."""

import secrets
from datetime import timedelta

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .mailer import send_student_code_email
from .models import (MAX_VERIFY_ATTEMPTS, VERIFY_MONTHS, StudentVerification,
                     _utcnow, db, looks_academic, student_status)
from .session import current_user, login_required
from .validators import EMAIL_RE

students_bp = Blueprint("students", __name__, url_prefix="/students")

CODE_TTL = timedelta(minutes=20)
RESEND_AFTER = timedelta(seconds=60)


@students_bp.route("/")
@login_required
def index():
    return render_template("students/index.html",
                           row=student_status(current_user()),
                           months=VERIFY_MONTHS,
                           ttl_minutes=int(CODE_TTL.total_seconds() // 60))


@students_bp.route("/verify", methods=["POST"])
@login_required
def verify_start():
    user = current_user()
    email = (request.form.get("academic_email") or "").strip().lower()

    if not EMAIL_RE.match(email):
        flash("That does not look like an email address.", "error")
        return redirect(url_for("students.index"))

    row = student_status(user)
    if row is not None and row.is_valid:
        flash("You are already verified.", "error")
        return redirect(url_for("students.index"))

    # Rate-limit before anything is written or sent.
    if row is not None and row.sent_at and _utcnow() - row.sent_at < RESEND_AFTER:
        flash("A code was just sent. Check that inbox.", "error")
        return redirect(url_for("students.index"))

    # One address, one claim. Otherwise a shared departmental mailbox turns
    # into an unlimited discount generator.
    taken = db.session.execute(
        db.select(StudentVerification)
        .where(StudentVerification.academic_email == email,
               StudentVerification.user_id != user.id,
               StudentVerification.status == "verified")
    ).scalars().first()
    if taken is not None:
        flash("That address is already in use by another account.", "error")
        return redirect(url_for("students.index"))

    if row is None or row.status in ("rejected", "verified"):
        row = StudentVerification(user_id=user.id, academic_email=email)
        db.session.add(row)

    row.academic_email = email
    row.domain = email.rpartition("@")[2]
    row.attempts = 0

    if not looks_academic(email):
        # Not obviously academic, so a person decides. Refusing outright
        # would turn away real students whose university uses a plain domain.
        row.status = "pending"
        row.code_hash = ""
        row.sent_at = None
        row.evidence = (request.form.get("evidence") or "")[:2000]
        db.session.commit()
        flash("We could not recognise that institution automatically, so "
              "someone will check it by hand. We will email you.", "success")
        return redirect(url_for("students.index"))

    code = "%06d" % secrets.randbelow(1_000_000)
    row.status = "sent"
    row.code_hash = generate_password_hash(code)
    row.sent_at = _utcnow()
    db.session.commit()

    send_student_code_email(email, code, name=user.name)
    flash("We sent a code to %s." % email, "success")
    return redirect(url_for("students.index"))


@students_bp.route("/confirm", methods=["POST"])
@login_required
def verify_confirm():
    user = current_user()
    row = student_status(user)

    if row is None or row.status != "sent":
        flash("Start the verification first.", "error")
        return redirect(url_for("students.index"))

    if row.sent_at is None or _utcnow() - row.sent_at > CODE_TTL:
        flash("That code has expired. Send a new one.", "error")
        return redirect(url_for("students.index"))

    if row.attempts >= MAX_VERIFY_ATTEMPTS:
        flash("Too many wrong codes. Send a new one.", "error")
        return redirect(url_for("students.index"))

    row.attempts += 1
    candidate = (request.form.get("code") or "").strip()
    if not (row.code_hash and check_password_hash(row.code_hash, candidate)):
        db.session.commit()
        flash("That code is not right.", "error")
        return redirect(url_for("students.index"))

    row.status = "verified"
    row.verified_at = _utcnow()
    row.expires_at = _utcnow() + timedelta(days=30 * VERIFY_MONTHS)
    # The code is spent. Keeping the hash would let it be replayed.
    row.code_hash = ""
    db.session.commit()

    flash("Verified. The student price is open to you for %d months."
          % VERIFY_MONTHS, "success")
    return redirect(url_for("billing.pricing"))

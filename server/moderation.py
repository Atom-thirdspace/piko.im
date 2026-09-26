"""One endpoint for every kind of report, so the button is the same everywhere."""

from flask import Blueprint, flash, redirect, request, url_for

from .models import REPORT_KINDS, file_report
from .session import current_user, is_safe_next, login_required

moderation_bp = Blueprint("moderation", __name__)


@moderation_bp.route("/report", methods=["POST"])
@login_required
def report():
    kind = request.form.get("kind") or ""
    reason = request.form.get("reason") or ""
    detail = request.form.get("detail") or ""
    try:
        target_id = int(request.form.get("target_id") or 0)
    except (TypeError, ValueError):
        target_id = 0

    back = request.form.get("next") or ""
    if not is_safe_next(back):
        back = url_for("dashboard.index")

    if kind not in REPORT_KINDS or not target_id:
        flash("That report was malformed.", "error")
        return redirect(back)

    file_report(current_user(), kind, target_id, reason, detail)
    # Deliberately the same message whether or not it was a duplicate: whether
    # an open report already exists is not something a reporter needs to know,
    # and saying so invites probing.
    flash("Thanks - an admin will look at it.", "success")
    return redirect(back)

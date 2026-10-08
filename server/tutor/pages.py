from flask import Blueprint, abort, render_template
from ..learning.markdown import render as render_md
from ..models import TutorThread, db, tutor_threads_for
from ..session import current_user, login_required

tutor_pages_bp = Blueprint("tutor_pages", __name__, url_prefix="/tutor")

def _pro_or_redirect():
    from ..billing.service import is_pro
    return is_pro(current_user())

@tutor_pages_bp.route("/history/")
@login_required
def history():
    user = current_user()
    if not _pro_or_redirect():
        return render_template("tutor_history.html", threads=None, thread=None,
                               messages=[]), 402
    return render_template("tutor_history.html",
                           threads=tutor_threads_for(user), thread=None,
                           messages=[])

@tutor_pages_bp.route("/history/<int:thread_id>/")
@login_required
def thread(thread_id):
    user = current_user()
    if not _pro_or_redirect():
        return render_template("tutor_history.html", threads=None, thread=None,
                               messages=[]), 402
    row = db.session.get(TutorThread, thread_id)
    if row is None or row.user_id != user.id:
        abort(404)

    return render_template(
        "tutor_history.html", threads=tutor_threads_for(user), thread=row,
        messages=[{"row": m, "answer_html": render_md(m.answer)}
                  for m in row.messages])
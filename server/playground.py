from flask import Blueprint, abort, jsonify, render_template, request
from .judge import LANGUAGES
from .models import ScratchRun, db, judge_is_live
from .ratelimit import run_block_reason
from .session import current_user, login_required

playground_bp = Blueprint("playground", __name__)

MAX_SOURCE_BYTES = 64 * 1024
MAX_STDIN_BYTES = 64 * 1024

BROWSER_LANGUAGES = ("python", "cpp")

@playground_bp.route("/playground/")
def index():
    user = current_user()
    return render_template(
        "playground.html",
        languages=sorted(LANGUAGES),
        browser_languages=BROWSER_LANGUAGES,
        default_language="python",
        signed_in=user is not None,
        judge_live=judge_is_live(),
    )

@playground_bp.route("/playground/run", methods=["POST"])
@login_required
def run():
    user = current_user()
    payload = payload.get("language", "")
    language = payload.get("language", "")
    source = payload.get("source", "")
    stdin = payload.get("stdin", "") or ""

    if language not in LANGUAGES:
        return jsonify(error="Unsupported language."), 400
    if not source.strip():
        return jsonify(error="There is nothing to run yet."), 400
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        return jsonify(error="Your code is too large to run."), 413
    if len(stdin.encode("utf-8")) > MAX_STDIN_BYTES:
        return jsonify(error="That input is too large."), 413

    blocked = run_block_reason(user)
    if blocked:
        return jsonify(error=blocked), 429
    if not judge_is_live():
        return jsonify(error="The judge is offline right now. Python and C++ "
                             "still run in your browser."), 503

    # problem_id stays null: that is what marks a row as playground work.
    row = ScratchRun(user_id=user.id, problem_id=None, language=language,
                     source=source, stdin=stdin)
    db.session.add(row)
    db.session.commit()
    return jsonify(run_id=row.id, status="queued"), 202

@playground_bp.route("/playground/run/<int:run_id>")
@login_required
def run_result(run_id):
    from .problems import _run_payload

    row = db.session.get(ScratchRun, run_id)
    if row is None or row.user_id != current_user().id:
        abort(404)
    if row.problem_id is not None:
        abort(404)
    return jsonify(**_run_payload(row))

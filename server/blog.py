from flask import Blueprint, abort, render_template, request

from .admin_gate import is_admin
from .learning.markdown import render as render_md
from .models import Post, db
from .session import current_user
blog_bp = Blueprint("blog", __name__)
PAGE_SIZE = 10

@blog_bp.route("/blog/")
def index():
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1

    stmt = (db.select(Post).where(Post.status == "published")
            .order_by(Post.published_at.desc()))
    total = db.session.execute(
        db.select(db.func.count()).select_from(stmt.subquery())).scalar() or 0
    posts = db.session.execute(
        stmt.limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE)).scalars().all()

    return render_template("blog.html", posts=posts,
                           pager={"page": page,
                                  "pages": max(1, -(-total // PAGE_SIZE))})

@blog_bp.route("/blog/<slug>/")
def post(slug):
    row = db.session.execute(
        db.select(Post).filter_by(slug=slug)).scalar_one_or_none()
    if row is None:
        abort(404)
    draft = not row.is_live
    if draft and not is_admin(current_user()):
        abort(404)

    return render_template("blog_post.html", post = row, body = render_md(row.body_md), draft = draft)
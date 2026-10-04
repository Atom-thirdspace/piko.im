"""One visibility rule for every authored model.

Learners see published rows. Authors also see their own drafts, in place.
Admins see everything. Keeping it here means lessons and problems can never
drift apart on who sees what.
"""

from .admin_gate import is_admin
from .models import PUBLISHED, db


def visible(stmt, model, user):
    if user is None:
        return stmt.where(model.status == PUBLISHED)
    if is_admin(user):
        return stmt
    if getattr(user, "is_author", False):
        return stmt.where(db.or_(model.status == PUBLISHED,
                                 model.created_by_id == user.id))
    return stmt.where(model.status == PUBLISHED)


def may_see(row, user):
    if row is None:
        return False
    if row.status == PUBLISHED:
        return True
    if user is None:
        return False
    return is_admin(user) or (getattr(user, "is_author", False)
                              and row.created_by_id == user.id)

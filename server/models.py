import os
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint

db = SQLAlchemy()


def _utcnow():
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255))
    avatar_url = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    welcome_email_sent_at = db.Column(db.DateTime(timezone=True), nullable =True)
    identities = db.relationship(
        "OAuthIdentity", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<User {self.id} {self.email}>"


class OAuthIdentity(db.Model):
    """One row per linked provider account, so one user can have several."""

    __tablename__ = "oauth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_provider_account"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider = db.Column(db.String(32), nullable=False)
    provider_user_id = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    user = db.relationship("User", back_populates="identities")

    def __repr__(self):
        return f"<OAuthIdentity {self.provider}:{self.provider_user_id}>"


def _normalize_db_url(url):
    """Force the psycopg3 driver; Neon's channel_binding param needs a modern libpq."""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def init_db(app):
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    app.config["SQLALCHEMY_DATABASE_URI"] = _normalize_db_url(url)
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    # Neon drops idle connections; pre_ping avoids handing out a dead one.
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True, "pool_recycle": 300}
    db.init_app(app)
    with app.app_context():
        db.create_all()


def load_user(user_id):
    return db.session.get(User, user_id)


def upsert_user(profile):
    is_new = False
    identity = db.session.execute(
        db.select(OAuthIdentity).filter_by(
            provider=profile["provider"],
            provider_user_id=profile["provider_user_id"],
        )
    ).scalar_one_or_none()

    if identity is not None:
        user = identity.user
    else:
        user = db.session.execute(
            db.select(User).filter_by(email=profile["email"])
        ).scalar_one_or_none()

        if user is None:
            user = User(
                email=profile["email"],
                name=profile.get("name"),
                avatar_url=profile.get("avatar_url"),
            )
            db.session.add(user)
            db.session.flush()  # assign user.id before the identity references it
            is_new = True

        db.session.add(
            OAuthIdentity(
                user_id=user.id,
                provider=profile["provider"],
                provider_user_id=profile["provider_user_id"],
            )
        )

    # Refresh display fields from whichever provider they just used.
    if profile.get("name"):
        user.name = profile["name"]
    if profile.get("avatar_url"):
        user.avatar_url = profile["avatar_url"]
    user.last_login_at = _utcnow()

    db.session.commit()
    return user, is_new

def mark_welcome_sent(user_id):
    user = db.session.get(User, user_id)
    if user is not None:
        user.welcome_email_sent_at = _utcnow()
        db.session.commit()

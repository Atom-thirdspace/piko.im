from flask import Flask
import os 
from datetime import timedelta
from dotenv import load_dotenv
from server.auth import auth_bp
from server.accounts import accounts_bp
from server.oauth import init_oauth
from server.session import current_user
from server.models import init_db
from server.onboarding.routes import onboarding_bp
from server.problems import problems_bp
from server.learning.seed import register_cli
from server.learning.routes import learn_bp
from server.userprofile import profile_bp
from server.dashboard import dashboard_bp
from server.admin import admin_bp, is_admin
from server.tutor import tutor_bp
from server.validators import interest_labels
from werkzeug.middleware.proxy_fix import ProxyFix
from server.leaderboard import leaderboard_bp
from server.community import community_bp
from server.blog import blog_bp
from server.csrf import init_csrf

load_dotenv()

base = os.environ.get("OAUTH_REDIRECT_BASE" , "s")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",   # Lax, not Strict — Strict breaks the OAuth return hop
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

init_db(app)
init_oauth(app)
init_csrf(app )
app.register_blueprint(auth_bp)
app.register_blueprint(accounts_bp)
app.register_blueprint(onboarding_bp)
app.register_blueprint(problems_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(tutor_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(leaderboard_bp)
app.register_blueprint(community_bp)
app.register_blueprint(blog_bp)
app.register_blueprint(learn_bp)
register_cli(app)
app.jinja_env.globals["current_user"] = current_user
app.jinja_env.globals["is_admin"] = is_admin
app.jinja_env.filters["interest_labels"] = interest_labels


if base.startswith("https://"):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    app.config["PREFERRED_URL_SCHEME"] = "https"

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

from flask import Flask, redirect, url_for, render_template
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
from server.userprofile import profile_bp

load_dotenv()


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
app.register_blueprint(auth_bp)
app.register_blueprint(accounts_bp)
app.register_blueprint(onboarding_bp)
app.register_blueprint(problems_bp)
app.register_blueprint(profile_bp)
register_cli(app)
app.jinja_env.globals["current_user"] = current_user

@app.route("/")
def home(): 
    return render_template("index.html")

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

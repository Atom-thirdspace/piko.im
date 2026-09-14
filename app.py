from flask import Flask, redirect, url_for, render_template
import os 
from datetime import timedelta
from dotenv import load_dotenv
from server.auth import auth_bp
from server.oauth import init_oauth
from server.session import current_user

load_dotenv()


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",   # Lax, not Strict — Strict breaks the OAuth return hop
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

init_oauth(app)
app.register_blueprint(auth_bp)
app.jinja_env.globals["current_user"] = current_user

@app.route("/")
def home(): 
    return "this is home page"



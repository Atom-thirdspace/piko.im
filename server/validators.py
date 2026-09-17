import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

AVATAR_RE = re.compile(r"^https://[^\s<>\"]+$")

DAILY_GOAL_CHOICES = (10, 20, 30, 50, 80, 120)

RESERVED_USERNAMES = {
    "admin", "root", "piko", "support", "help", "api",
    "login", "logout", "signup", "settings", "about",
}

INTERESTS = [
    ("arrays", "Arrays & Strings"),
    ("trees", "Trees & Graphs"),
    ("dp", "Dynamic Programming"),
    ("cp", "Competitive Programming"),
    ("interview", "Interview Prep"),
    ("beginner", "Just starting out"),
]

COMMON_TIMEZONES= [
    "UTC", "Asia/Kolkata", "Asia/Dubai", "Asia/Singapore", "Asia/Tokyo",
    "Europe/London", "Europe/Berlin", "Europe/Moscow",
    "America/New_York", "America/Chicago", "America/Denver",
    "America/Los_Angeles", "America/Sao_Paulo", "Australia/Sydney",
]
INTEREST_KEYS = {key for key, _ in INTERESTS}

def validate_username(username, taken_check):
    u = (username or "").strip().lower()
    if not u:
        return "Pick a username"
    if not USERNAME_RE.match(u):
        return "3-20 characters, lowercase letters, numbers and underscores only."
    if u in RESERVED_USERNAMES:
        return "That username is reserved."
    if taken_check(u):
        return "That username is taken."
    return None

def validate_display_name(name):
    n = (name or "").strip()
    if not (1 <= len(n) <= 80):
        return "Enter your name (80 characters or fewer)."
    return None

def validate_avatar_url(url):
    u = (url or "").strip()
    if not u:
        return None                      # optional; blank clears it
    if len(u) > 500 or not AVATAR_RE.match(u):
        return "Enter an https:// image URL, or leave it blank."
    return None   

def validate_interest(key):
    if key not in INTEREST_KEYS:
        return "Pick what you want to focus on."
    return None  

def validate_daily_goal(raw):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return "Pick a daily goal."
    if value not in DAILY_GOAL_CHOICES:
        return "Pick one of the listed goals."
    return None


def validate_language(key, valid_keys):
    if key and key not in valid_keys:
        return "Pick a language we support."
    return None  

def validate_timezone(tz):
    if not tz:
        return "Pick a timezone."
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return "That isn't a timezone we recognise."
    return None


def validate_password_change(new, confirm, user_email, username, current_ok):
    errors = {}
    if not current_ok:
        errors["current_password"] = "That isn't your current password."
    if len(new or "") < 8:
        errors["new_password"] = "Use at least 8 characters."
    elif (new or "").lower() in ((user_email or "").lower(), (username or "").lower()):
        errors["new_password"] = "Pick a password that isn't your email or username."
    elif new != confirm:
        errors["confirm_password"] = "The two passwords don't match."
    return errors


def validate_signup(form, email_taken, username_taken):
    errors = {}

    email = (form.get("email") or "").strip().lower()
    if not EMAIL_RE.match(email):
        errors["email"] = "Enter a valid email address"
    elif email_taken(email):
        errors["email"] = "An account with that email already exists"

    err = validate_username(form.get("username"), username_taken)
    if err:
        errors["username"] = err

    name = (form.get("name") or "").strip()
    if not (1 <= len(name) <= 80):
        errors["name"] = "Enter your name"

    if form.get("interest") not in INTEREST_KEYS:
        errors["interest"] = "Pick what you want to focus on."

    password = form.get("password") or ""
    if len(password) < 8:
        errors["password"] = "Use at least 8 characters."
    elif password.lower() in (email, (form.get("username") or "").lower()):
        errors["password"] = "Pick a password that isn't your email or username."

    return errors


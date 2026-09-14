import re

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

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


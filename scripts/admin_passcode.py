from getpass import getpass

from werkzeug.security import generate_password_hash

first = getpass("Admin passcode")
if len(first.strip()) < 8:
    raise SystemExit("Use at least 8 characters")
if first != getpass("Again: "):
    raise SystemExit("They don't match")

print("\nADMIN_PASSCODE_HASH=" + generate_password_hash(first.strip(), method="pbkdf2:sha256"))

import re

from . import config, runner
from .output import Fail

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$")

def folder():
    return config.HOME / "templates"

def _suffix(language):
    return "." + runner.LANGUAGES[language]["source"].rsplit(".", 1)[-1]


def path_for(name, language):
    if not SAFE_NAME.match(name or ""):
        raise Fail("Template names are letters, digits, . - and _ "
                   "(got %r)." % name)
    return folder() / (name + _suffix(language))


def save(name, language, body):
    box = folder()
    box.mkdir(parents=True, exist_ok=True)
    target = path_for(name, language)
    target.write_text(body, encoding="utf-8")
    return target

def load(name, language):
    target = path_for(name, language)
    if not target.exists():
        known = [n for n, lang in listing() if lang == language]
        raise Fail("No %s template %r.%s" % (
            language, name,
            ("  Try: " + ", ".join(known)) if known else ""))
    return target.read_text(encoding="utf-8")


def listing():
    box = folder()
    if not box.is_dir():
        return []
    by_suffix = {_suffix(lang): lang for lang in runner.LANGUAGES}
    out = []
    for path in sorted(box.iterdir()):
        language = by_suffix.get(path.suffix)
        if language:
            out.append((path.stem, language))
    return out

def remove(name, language):
    target = path_for(name, language)
    if not target.exists():
        return False
    target.unlink()
    return True
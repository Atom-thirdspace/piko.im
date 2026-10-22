import json
from pathlib import Path

from .output import Fail

MARKER = ".piko"
MANIFEST = "workspace.json"

def find(start=None):
    here = Path(start or ".").resolve()
    for folder in [here] + list(here.parents):
        if (folder/MARKER).is_dir():
            return folder
    return None

def require():
    root = find()
    if root is None:
        raise Fail("Not inside a Piko workspace. Run `piko init` first.")
    return root


def read(root):
    path = root / MARKER / MANIFEST
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"problems": {}, "language": "python", "track": None}

def write(root, data):
    folder = root / MARKER
    folder.mkdir(parents=True, exist_ok=True)
    (folder / MANIFEST).write_text(json.dumps(data, indent=2, sort_keys=True),
                                   encoding="utf-8")

GITIGNORE = """\
# Piko keeps no secrets here, but build output is not worth committing.
*.class
*.exe
*.out
a.out
__pycache__/
"""
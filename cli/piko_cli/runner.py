import platform
import shutil
import subprocess
import sys
from pathlib import Path

from .output import Fail

TIMEOUT = 10

def _python():
    for name in ("python3" , "python"):
        if shutil.which(name):
            return name
    return sys.executable

LANGUAGES = {
    "python": {
        "label": "Python 3",
        "source": "main.py",
        "compile": None,
        "run": lambda d: [_python(), "-u", str(d / "main.py")],
        "stub": ("import sys\n\n\n"
                 "def main():\n"
                 "    data = sys.stdin.read().split()\n"
                 "    # your solution here\n\n\n"
                 'if __name__ == "__main__":\n'
                 "    main()\n"),
    },
    "cpp": {
        "label": "C++17",
        "source": "main.cpp",
        "compile": lambda d: ["g++", "-O2", "-std=c++17", "-o",
                              str(d / _exe("main")), str(d / "main.cpp")],
        "run": lambda d: [str(d / _exe("main"))],
        "stub": ("#include <bits/stdc++.h>\nusing namespace std;\n\n"
                 "int main() {\n"
                 "    ios::sync_with_stdio(false);\n"
                 "    cin.tie(nullptr);\n"
                 "    // your solution here\n"
                 "    return 0;\n}\n"),
    },
    "java": {
        "label": "Java 17",
        "source": "Main.java",
        "compile": lambda d: ["javac", "-d", str(d), str(d / "Main.java")],
        "run": lambda d: ["java", "-cp", str(d), "Main"],
        "stub": ("import java.util.*;\nimport java.io.*;\n\n"
                 "public class Main {\n"
                 "    public static void main(String[] args) throws IOException {\n"
                 "        // your solution here\n"
                 "    }\n}\n"),
    },
}

def _exe(name):
    return name + ".exe" if platform.system() == "Windows" else name

def detect(folder):
    for key, spec in LANGUAGES.items():
        if (folder / spec["source"]).exists():
            return key
        return None


def normalise(text):
    return "\n".join(line.rstrip() for line in (text or "").splitlines()).rstrip()

def compile_if_needed(folder, language):
    spec = LANGUAGES(language)
    if spec["compile"] is None:
        return
    cmd = spec["compile"](folder)
    if not shutil.which(cmd[0]):
        raise Fail("%s isn't installed, so %s can't be built here."
                   % (cmd[0], spec["label"]))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise Fail("Compile failed:\n\n" + (proc.stderr or proc.stdout))

def run_case(folder, language, stdin_text):
    cmd = LANGUAGES[language]["run"](folder)
    try:
        proc = subprocess.run(cmd, input=stdin_text or "", capture_output=True, text=True, timeout=TIMEOUT)

    except subprocess.TimeoutExpired:
        return False, "", "timed out after %ds" % TIMEOUT

    except FileNotFoundError:
        return False, "", "couldn't start %s" % cmd[0]
    if proc.returncode != 0:
        return False, proc.stdout, (proc.stderr or "").strip()[:400]
    return True, proc.stdout, ""


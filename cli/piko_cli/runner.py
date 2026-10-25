import platform
import shutil
import subprocess
import sys
from pathlib import Path

from .output import Fail

TIMEOUT = 10

_PYTHON = None


def _find_python():
    for name in ("python3", "python"):
        path = shutil.which(name)
        if not path:
            continue
        try:
            proc = subprocess.run([path, "-c", "pass"], capture_output=True,
                                  timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0:
            return path
    return sys.executable


def _python():
    global _PYTHON
    if _PYTHON is None:
        _PYTHON = _find_python()
    return _PYTHON

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
        "c": {
        "label": "C17",
        "source": "main.c",
        "compile": lambda d: ["gcc", "-O2", "-std=c17", "-o",
                              str(d / _exe("main")), str(d / "main.c"), "-lm"],
        "run": lambda d: [str(d / _exe("main"))],
        "stub": ("#include <stdio.h>\n#include <stdlib.h>\n"
                 "#include <string.h>\n\n"
                 "int main(void) {\n"
                 "    // your solution here\n"
                 "    return 0;\n}\n"),
    },
    "javascript": {
        "label": "JavaScript (Node)",
        "source": "main.js",
        "compile": None,
        "run": lambda d: ["node", str(d / "main.js")],
        "stub": ("const data = require('fs').readFileSync(0, 'utf8')"
                 ".split(/\\s+/);\n\n"
                 "function main() {\n"
                 "    // your solution here\n"
                 "}\n\nmain();\n"),
    },
    "go": {
        "label": "Go",
        "source": "main.go",
        "compile": lambda d: ["go", "build", "-o", str(d / _exe("main")),
                              str(d / "main.go")],
        "run": lambda d: [str(d / _exe("main"))],
        "stub": ('package main\n\nimport (\n\t"bufio"\n\t"fmt"\n\t"os"\n)\n\n'
                 "func main() {\n"
                 "\treader := bufio.NewReader(os.Stdin)\n"
                 "\twriter := bufio.NewWriter(os.Stdout)\n"
                 "\tdefer writer.Flush()\n"
                 "\t_ = reader\n"
                 "\t// your solution here\n"
                 "\tfmt.Fprintln(writer)\n}\n"),
    },
    "rust": {
        "label": "Rust",
        "source": "main.rs",
        "compile": lambda d: ["rustc", "-O", "--edition", "2021", "-o",
                              str(d / _exe("main")), str(d / "main.rs")],
        "run": lambda d: [str(d / _exe("main"))],
        "stub": ("use std::io::{self, Read, Write};\n\n"
                 "fn main() {\n"
                 "    let mut input = String::new();\n"
                 "    io::stdin().read_to_string(&mut input).unwrap();\n"
                 "    let stdout = io::stdout();\n"
                 "    let mut out = stdout.lock();\n"
                 "    // your solution here\n"
                 "    let _ = writeln!(out);\n}\n"),
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
    spec = LANGUAGES[language]
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


def exact(stdin, expected, actual):
    return normalise(actual) == normalise(expected), ""

def unordered(stdin, expected, actual):
    want = sorted(normalise(expected).splitlines())
    got = sorted(normalise(actual).splitlines())
    if want == got:
        return True, ""
    return False, "the same lines were expected, in any order"

def make_float(tolerance):
    def check(stdin , expected, actual):
        want, got = normalise(expected).split(), normalise(actual).split()
        if len(want) != len(got):
            return False, "expected %d values, got %d" % (len(want), len(got))
        for a, b in zip(want, got):
            try:
                if abs(float(a) - float(b)) > tolerance:
                    return False, "%s differs from %s by more than %g" % (
                        b, a, tolerance)
            except ValueError:
                if a != b:
                    return False, "%r where %r was expected" % (b, a)
        return True, ""
    return check

BUILTIN = {"exact": exact, "unordered": unordered}

def checker_for(folder, meta):
    custom = folder / "checker.py"
    if custom.exists():
        return _load_checker(custom)
    
    spec = meta.get("checker") or "exact"

    if isinstance(spec, dict):
        kind = spec.get("kind") or "exact"
        if kind == "float":
            return make_float(float(spec.get("tolerance", 1e-6)))
        spec = kind
    if spec == "float":
        return make_float(1e-6)
    if spec not in BUILTIN:
        raise Fail("Unknown checker %r in piko.json. Try: %s, float."
                   % (spec, ", ".join(sorted(BUILTIN))))
    return BUILTIN[spec]

def _load_checker(path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("piko_checker", str(path))
    module = importlib.util.module_from_spec(spec)

    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise Fail("checker.py would not load: %s" % exc)

    fn = getattr(module, "check", None)
    if fn is None:
        raise Fail("checker.py needs a check(stdin, expected, actual).")

    def wrapped(stdin, expected, actual):
        result = fn(stdin, expected, actual)
        if isinstance(result, tuple):
            return bool(result[0]), (result[1] or "")
        return bool(result), ""
    return wrapped

CHECKER_STUB = '''\
"""Decide whether `actual` is a correct answer for `stdin`.

Return True, or (False, "why it is wrong").
"""


def check(stdin, expected, actual):
    return actual.split() == expected.split()
'''

def sources_for(folder, language, meta):
    listed = meta.get("sources")
    if not listed:
        return [folder / LANGUAGES[language]["source"]]
    paths = [folder / name for name in listed]
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        raise Fail("piko.json lists files that aren't here: %s"
                   % ", ".join(missing))
    return paths


def compile_if_needed(folder, language, meta=None):
    spec = LANGUAGES[language]
    if spec["compile"] is None:
        return

    override = (meta or {}).get("build")
    if override:
        cmd = [part.replace("{dir}", str(folder)) for part in override]
    else:
        files = sources_for(folder, language, meta or {})
        cmd = spec["compile"](folder)
        if len(files) > 1:
            cmd = cmd + [str(p) for p in files[1:]]

    if not shutil.which(cmd[0]):
        raise Fail("%s isn't installed, so %s can't be built here."
                   % (cmd[0], spec["label"]))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise Fail("Compile failed:\n\n" + (proc.stderr or proc.stdout))
    
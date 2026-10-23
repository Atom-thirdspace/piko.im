import time

from .. import runner
from ..output import Fail, amber, bold, dim, green, red
from .screen import ENTER, ESC
from .widgets import diff_lines, fit, width

GLYPHS = {"pass": green("\u2713"), "fail": red("\u2717"),
          "running": amber("\u2026"), "idle": dim("\u00b7")}

def each_case(folder, language, cases):
    for case in cases:
        out_file = case.with_suffix(".out")
        expected = (out_file.read_text(encoding="utf-8")
                    if out_file.exists() else "")
        started = time.time()
        ran, got, why = runner.run_case(
            folder, language, case.read_text(encoding="utf-8"))
        ok = ran and runner.normalise(got) == runner.normalise(expected)
        yield {"name": case.stem, "state": "pass" if ok else "fail",
               "ms": int((time.time() - started) * 1000),
               "got": got, "expected": expected, "why": why}

class Live:
    def __init__(self, screen, folder, language, cases, meta):
        self.screen = screen
        self.folder, self.language, self.cases = folder, language, cases
        self.meta = meta
        self.source = folder / runner.LANGUAGES[language]["source"]
        self.rows = [{"name": c.stem, "state": "idle", "ms": 0}
                     for c in cases]
        self.stamp = None
        self.error = ""
        self.phase = "waiting"
        self.show_diff = True
        self.action = None

    def changed(self):
        try:
            now = self.source.stat().st_mtime
        except OSError:
            return False
        if now == self.stamp:
            return False
        self.stamp = now
        return True

    def rerun(self):
        self.error = ""
        self.phase = "building"
        self.rows = [{"name": c.stem, "state": "idle", "ms": 0}
                     for c in self.cases]
        self.render()
        try:
            runner.compile_if_needed(self.folder, self.language)
        except Fail as exc:
            self.error = str(exc)
            self.phase = "failed to build"
            return

        self.phase = "pending"
        for i, result in enumerate(each_case(self.folder, self.language,
                                             self.cases)):
            self.rows[i] = result
            if i + 1 < len(self.rows):
                self.rows[i + 1]["state"] = "running"
            self.render()
        self.phase = "waiting"

    def first_failure(self):
        return next((r for r in self.rows if r.get("state") == "fail"), None)

    def render(self):
        rows, cols = self.screen.rows, self.screen.cols
        passed = sum(1 for r in self.rows if r["state"] == "pass")
        total = len(self.rows)
        paint = green if passed == total else red

        title = bold(self.meta.get("title") or self.folder.name)
        tally = paint("%d/%d" % (passed, total))
        head = " " + title + dim("   " + runner.LANGUAGES[self.language]["label"])
        lines = [head + " " * max(cols - width(head) - width(tally) - 2, 1)
                 + tally + " ",
                 dim(" " + "\u2500" * max(cols - 2, 1))]

        for row in self.rows:
            timing = dim("%4d ms" % row["ms"]) if row["ms"] else ""
            note = dim("  " + row["why"]) if row.get("why") else ""
            lines.append(fit("  %s  %s   %s%s"
                             % (GLYPHS[row["state"]], row["name"].ljust(6),
                                timing, note), cols))

        if self.error:
            lines += ["", red("  "+ self.phase)]
            lines += ["  " + l for l in self.error.splitlines()[:rows - 8]]
        elif self.show_diff:
            bad = self.first_failure()
            if bad and bad.get("got") is not None:
                lines += ["", dim("  " + "\u2500" * max(cols - 4, 1))]
                room = rows - len(lines) - 2
                lines += ["  " + l for l in diff_lines(
                    runner.normalise(bad["expected"]),
                    runner.normalise(bad["got"]), cols - 4)[:max(room, 0)]]

        while len(lines) < rows - 1:
            lines.append("")
        lines.append(self.footer(cols))
        self.screen.draw(lines[:rows])

    def footer(self,cols):
        spin = {"waiting": dim("watching for a save"),
                "running": amber("running\u2026"),
                "building": amber("building\u2026")}.get(self.phase, "")
        keys = dim("r rerun   s submit   d diff   q quit")
        gap = cols - width(spin) - width(keys) - 3
        return " " + spin + " " * max(gap, 1) + keys + " "

    def handle(self, key):
        if key in ("q", ESC):
            return False
        if key in ("r", ENTER):
            self.rerun()
        elif key == "s":
            self.action = "submit"
            return False
        elif key == "d":
            self.show_diff = not self.show_diff
        return True

    def run(self):
        while True:
            self.screen.measure()
            if self.changed():
                self.rerun()
            self.render()
            key = self.screen.key(timeout=0.15)
            if key is not None and not self.handle(key):
                return self.action

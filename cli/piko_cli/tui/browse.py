import time
import webbrowser

from .. import api, config
from ..output import Fail, amber, bold, dim, green, red
from .screen import (DOWN, ENTER, ESC, PGDN, PGUP, RESET, REVERSE, UP)
from .widgets import fit, plain, style, width, wrap

DEBOUNCE = 0.25
PAGE_SIZE = 100

MARKS = {"easy": ("e", green), "medium": ("m", amber), "hard": ("h", red)}


HELP = [
    ("j / k   \u2191 \u2193", "move"),
    ("PgUp PgDn", "move a screen"),
    ("g / G", "first / last"),
    ("space / b", "scroll the preview"),
    ("n / p", "next / previous page"),
    ("/", "search"),
    ("d", "cycle difficulty"),
    ("enter", "scaffold it here"),
    ("o", "open it in a browser"),
    ("r", "reload"),
    ("? ", "this help"),
    ("q", "quit"),
]

class Browser:
    def __init__(self, screen):
        self.screen = screen
        self.items = []
        self.detail = {}
        self.cursor = self.offset = self.scroll = 0
        self.page, self.pages, self.total = 1, 1, 0
        self.query, self.editing, self.difficulty = "", None, None
        self.pending, self.pending_at = None, 0.0
        self.status = "loading\u2026"
        self.helping = False
        self.chosen = None

    def load(self):
        self.status = "loading\u2026"
        self.render()
        try:
            body = api.problems(topic=None, difficulty=self.difficulty,
                                q=self.query or None, page=self.page,
                                per_page=PAGE_SIZE)
        except Fail as exc:
            self.items, self.status = [], str(exc)
            return
        self.items = body.get("items") or []
        self.pages = body.get("pages", 1)
        self.total = body.get("total", len(self.items))
        self.cursor = self.offset = 0
        self.status = "%d problem%s" % (self.total, "" if self.total == 1 else "s")

    def touch(self):
        self.scroll = 0
        if not self.items:
            self.pending = None
            return
        slug = self.items[self.cursor]["slug"]
        self.pending = None if slug in self.detail else slug
        self.pending_at = time.monotonic() + DEBOUNCE


    def settle(self):
        if not self.pending or time.monotonic() < self.pending_at:
            return
        slug, self.pending = self.pending, None
        try:
            self.detail[slug] = api.problem(slug)
        except Fail as exc:
            self.status = str(exc)

    def render(self):
        rows, cols = self.screen.rows, self.screen.cols
        if rows < 8 or cols < 50:
            self.screen.draw(["", "  The window is too small for `piko ui`.", "  Give it 50x8 or more."])
            return

        left = max(26, min(44, cols // 2 - 2))
        right = cols - left - 3
        body = rows - 3

        self.clamp(body)
        preview = self.help_pane(right) if self.helping else self.pane(right)
        visible = self.items[self.offset:self.offset + body]

        lines = [self.titlebar(cols), self.filterbar(cols)]
        for i in range(body):
            cell = (self.row(visible[i], left, self.offset + i == self.cursor)
                    if i < len(visible) else " " * left)
            text = preview[i] if i < len(preview) else ""
            lines.append(cell + " " + dim("\u2502") + " " + fit(text, right))
        lines.append(self.statusbar(cols))
        self.screen.draw(lines)

    def titlebar(self, cols):
        name = bold(" piko ") + dim("catalogue")
        page = dim("page %d/%d " % (self.page, self.pages))
        gap = cols - width(name) - width(page)
        return name + " " * max(gap, 1) + page


    def render(self):
        rows, cols = self.screen.rows, self.screen.cols
        if rows < 8 or cols < 50:
            self.screen.draw(["", "  The window is too small for `piko ui`.", "  Give it 50x8 or more."])
            return

        left = max(26, min(44, cols // 2 - 2))
        right = cols - left - 3
        body = rows - 3

        self.clamp(body)
        preview = self.help_pane(right) if self.helping else self.pane(right)
        visible = self.items[self.offset:self.offset + body]

        lines = [self.titlebar(cols), self.filterbar(cols)]
        for i in range(body):
            cell = (self.row(visible[i], left, self.offset + i == self.cursor)
                    if i < len(visible) else " " * left)
            text = preview[i] if i < len(preview) else ""
            lines.append(cell + " " + dim("\u2502") + " " + fit(text, right))
        lines.append(self.statusbar(cols))
        self.screen.draw(lines)

    def titlebar(self, cols):
        name = bold(" piko ") + dim("catalogue")
        page = dim("page %d/%d " % (self.page, self.pages))
        gap = cols - width(name)- width(page)
        return name + " " * max(gap,1) + page

    def filterbar(self, cols):
        if self.editing is not None:
            return fit(" " + bold("/") + self.editing + REVERSE + " " + RESET, cols)
        bits = [dim("difficulty "), (self.difficulty or "any")]
        if self.query:
            bits += [dim("  search "), '"%s"' % self.query]
        bits += [dim("   ? for keys")]
        return fit(" " + "".join(bits), cols)

    def row(self, item, size, picked):
        mark, paint = MARKS.get(item.get("difficulty"), ("?", dim))
        title = item.get("title") or item["slug"]
        if picked:
            return REVERSE + fit(" %s  %s" % (mark, title), size) + RESET
        return fit(" " + paint(mark) + "  " + title, size)

    def pane(self, size):
        if not self.items:
            return [dim("Nothing matched")]
        slug = self.items[self.cursor]["slug"]
        full = self.detail.get(slug)
        if full is None:
            return [dim("loading %s\u2026" % slug)]

        out = [bold(full["title"]),
               dim("%s  \u00b7  %s xp  \u00b7  %s"
                   % (full.get("difficulty"), full.get("xp"),
                      full.get("topic") or "no topic")),
               ""]
        out += [style(line, code) for line, code
                in wrap(full.get("statement_md") or "", size)]

        samples = full.get("samples") or []
        if samples:
            out += ["", dim("\u2500 sample 1 " + "\u2500" * max(size - 11, 0))]
            out += [dim("input")]
            out += (samples[0].get("stdin") or "").splitlines()[:8]
            out += [dim("expected")]
            out += (samples[0].get("expected_stdout") or "").splitlines()[:8]
        out += ["", dim("%d tests in total." % full.get("total_tests", 0))]
        return out[self.scroll:]

    def help_pane(self, size):
        out = [bold("Keys"), ""]
        for keys, what in HELP:
            out.append(fit("  " + amber(keys.ljust(12)) + dim(what), size))
        out += ["", dim("? or esc closes this.")]
        return out

    def statusbar(self, cols):
        slug = self.items[self.cursor]["slug"] if self.items else ""
        tally = dim("%d/%d" % (self.cursor + 1, len(self.items))
                    if self.items else "0/0")
        text = " " + green(slug) + "   " + dim(self.status)
        gap = cols - width(text) - width(tally) - 1
        return text + " " * max(gap, 1) + tally + " "

    def clamp(self, body):
        if not self.items:
            self.cursor = self.offset = 0
            return
        self.cursor = max(0, min(self.cursor, len(self.items) - 1))
        if self.cursor < self.offset:
            self.offset = self.cursor
        elif self.cursor >= self.offset + body:
            self.offset = self.cursor - body + 1
        self.offset = max(0, min(self.offset, max(len(self.items) - body, 0)))

    def move(self, delta):
        if not self.items:
            return
        self.cursor = max(0, min(self.cursor + delta, len(self.items) - 1))
        self.touch()

    def handle(self, key):
        if self.editing is not None:
            return self.edit(key)
        if self.helping and key in ("?", ESC, "q"):
            self.helping = False
            return True

        if key in ("q", ESC):
            return False
        if key == "?":
            self.helping = True
        elif key in ("j", DOWN):
            self.move(1)
        elif key in ("k", UP):
            self.move(-1)
        elif key == PGDN:
            self.move(self.screen.rows - 4)
        elif key == PGUP:
            self.move(-(self.screen.rows - 4))
        elif key == "g":
            self.cursor = 0
            self.touch()
        elif key == "G":
            self.cursor = max(len(self.items) - 1, 0)
            self.touch()
        elif key == " ":
            self.scroll += max(self.screen.rows - 8, 1)
        elif key == "b":
            self.scroll = max(0, self.scroll - max(self.screen.rows - 8, 1))
        elif key == "n" and self.page < self.pages:
            self.page += 1
            self.load()
        elif key == "p" and self.page > 1:
            self.page -= 1
            self.load()
        elif key == "/":
            self.editing = self.query
        elif key == "d":
            order = [None, "easy", "medium", "hard"]
            self.difficulty = order[(order.index(self.difficulty) + 1) % 4]
            self.page = 1
            self.load()
        elif key == "r":
            self.detail.clear()
            self.load()
        elif key == "o" and self.items:
            webbrowser.open("%s/problems/%s/"
                            % (config.site(), self.items[self.cursor]["slug"]))
            self.status = "opened in your browser"
        elif key == ENTER and self.items:
            self.chosen = self.items[self.cursor]["slug"]
            return False
        return True

    def edit(self, key):
        if key == ESC:
            self.editing = None
        elif key == ENTER:
            self.query, self.editing = self.editing.strip(), None
            self.page = 1
            self.load()
        elif key == "<backspace>":
            self.editing = self.editing[:-1]
        elif key and len(key) == 1 and key.isprintable():
            self.editing += key
        return True

    def run(self):
        self.load()
        while True:
            self.screen.measure()
            self.render()
            key = self.screen.key(timeout=0.88)
            if key is None:
                self.settle()
                continue
            if not self.handle(key):
                return self.chosen
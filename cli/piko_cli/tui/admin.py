import time
from .. import api

from ..output import Fail, amber, bold, dim, green, red
from .screen import ESC
from .widgets import bar, fit ,width

BLOCKS = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"

def spark(values):
    if not values:
        return ""
    high = max(values) or 1
    return "".join(BLOCKS[min(int(v / high * 7), 7)] for v in values)

class Dashboard:
    def __init__(self, screen, every=10.0):
        self.screen = screen
        self.every = max(every, 2.0)
        self.days = 7
        self.stats = {}
        self.traffic = {}
        self.error = ""
        self.fetched = 0.0

    def refresh(self):
        try:
            self.stats = api.admin_stats()
            self.traffic = api.admin_traffic(days=self.days, top=10)
            self.error = ""
        except Fail as exc:
            self.error = str(exc)
        self.fetched = time.monotonic()

    def render(self):
        rows, cols = self.screen.rows, self.screen.cols
        head = self.stats.get("headline") or {}
        judge = self.stats.get("judge") or {}

        title = " " + bold("piko admin") + dim("  live")
        age = dim("%ds ago " % int(time.monotonic() - self.fetched))
        lines = [title + " " * max(cols - width(title) - width(age), 1) + age,
                 dim(" " + "\u2500" * max(cols - 2, 1))]

        if self.error:
            lines += ["", red("  " + self.error), ""]

        lines.append("  " + bold("Site"))
        lines.append("    users %-8s active %-8s problems %-6s lessons %s"
                     % (head.get("users", 0), head.get("active", 0),
                        head.get("problems", 0), head.get("lessons", 0)))
        lines.append("    submissions %-6s accepted %.0f%%  solves %s"
                     % (head.get("submissions", 0),
                        head.get("accept_rate", 0), head.get("solves", 0)))

        lines.append("")
        lines.append("  " + bold("Judge"))
        failed = judge.get("failed", 0)
        lines.append("    queued %-6s running %-6s failed %s   done 24h %s"
                     % (judge.get("queued", 0), judge.get("running", 0),
                        red(str(failed)) if failed else "0",
                        judge.get("done_24h", 0)))

        by_day = self.traffic.get("by_day") or []
        lines.append("")
        lines.append("  " + bold("Traffic") + dim("  %d days" % self.days))
        lines.append("    %s views   %s visitors   p95 %s ms"
                     % (self.traffic.get("views", 0),
                        self.traffic.get("visitors", 0),
                        self.traffic.get("p95_ms", 0)))
        if by_day:
            lines.append("    " + spark([d["views"] for d in by_day]))

        routes = self.traffic.get("routes") or []
        if routes:
            lines.append("")
            lines.append("  " + bold("Busiest"))
            high = max(r["views"] for r in routes) or 1
            for row in routes[:max(rows - len(lines) - 3, 0)]:
                lines.append("    " + fit(row["route"], 34) + " "
                             + bar(row["views"] / float(high), 14)
                             + dim(" %d" % row["views"]))

        while len(lines) < rows - 1:
            lines.append("")
        keys = dim("r refresh   d cycle window   q quit")
        lines.append(" " + keys)
        self.screen.draw(lines[:rows])

    def run(self):
        self.refresh()
        while True:
            self.screen.measure()
            self.render()
            key = self.screen.key(timeout=0.5)
            if key in ("q", ESC):
                return 0
            if key == "r":
                self.refresh()
            elif key == "d":
                self.days = {1: 7, 7: 30, 30: 90, 90: 1}[self.days]
                self.refresh()
            elif key is None and time.monotonic() - self.fetched > self.every:
                self.refresh()
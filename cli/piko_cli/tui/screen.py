import os
import shutil
import sys
import time

WINDOWS = os.name == "nt"


if WINDOWS:
    import msvcrt
else:
    import select
    import termios
    import tty

UP, DOWN, LEFT, RIGHT = "<up>", "<down>", "<left>", "<right>"
ENTER, ESC, TAB, BACKSPACE = "<enter>", "<esc>", "<tab>", "<backspace>"
PGUP, PGDN, HOME, END, DELETE = "<pgup>", "<pgdn>", "<home>", "<end>", "<del>"

RESET = "\033[0m"
REVERSE = "\033[7m"

_WIN_KEYS = {"H": UP, "P": DOWN, "K": LEFT, "M": RIGHT, "I": PGUP,
             "Q": PGDN, "G": HOME, "O": END, "S": DELETE}

_POSIX_KEYS = {"A": UP, "B": DOWN, "C": RIGHT, "D": LEFT, "H": HOME,
               "F": END, "5~": PGUP, "6~": PGDN, "3~": DELETE}

def _enable_vt():
    if not WINDOWS:
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False

def _translate(ch):
    if ch in ("\r", "\n"):
        return ENTER
    if ch == "\t":
        return TAB
    if ch in ("\x7f", "\b"):
        return BACKSPACE
    if ch == "\x1b":
        return ESC
    if ch == "\x03":
        raise KeyboardInterrupt
    return ch

def _key_windows(timout):
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):
                return _WIN_KEYS.get(msvcrt.getwch())
            return _translate(ch)
        if deadline is not None and time.monotonic() >= deadline:
            return None
        time.sleep(0.01)

def _key_posix(timeout):
    fd = sys.stdin.fileno()
    if not select.select([fd], [], [], timeout)[0]:
        return None
    ch = os.read(fd, 1).decode("utf-8", "replace")
    if ch != "\033":
        return _translate(ch)

    if not select.select([fd], [], [], 0.05)[0]:
        return ESC
    if os.read(fd, 1).decode("utf-8", "replace") != "[":
        return ESC

    seq = ""
    while select.select([fd], [], [], 0.05)[0]:
        seq += os.read(fd, 1).decode("utf-8", "replace")
        if seq[-1].isalpha() or seq[-1] == "~":
            break
    return _POSIX_KEYS.get(seq)

class Screen:
    def __init__(self, stream=None):
        self.out = stream or sys.stdout
        self.rows, self.cols = 24, 80
        self._shown = []
        self._saved = None

    def __enter__(self):
        _enable_vt()
        if not WINDOWS:
            self._saved = termios.tcgetattr(sys.stdin.fileno())
            tty.setraw(sys.stdin.fileno())
        self.out.write("\033[?1049h\033[?25l")
        self.out.flush()
        self.measure()
        return self

    def __exit__(self, *_exc):
        self.out.write(RESET + "\033[?25h\033[?1049l")
        self.out.flush()
        if not WINDOWS and self._saved is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN,
                              self._saved)
        return False

    def measure(self):
        size = shutil.get_terminal_size((80 , 24))
        changed = (size.lines, size.columns) != (self.rows, self.cols)
        self.rows, self.cols = size.lines, size.columns
        if changed:
            self._shown = []
        return changed

    def draw(self, lines):
        chunks = []
        for i in range(self.rows):
            new = lines[i] if i < len(lines) else ""
            old = self._shown[i] if i < len(self._shown) else None
            if new == old:
                continue
            chunks.append("\033[%d;1H\033[2K%s%s" % (i + 1, new, RESET))
        if chunks:
            self.out.write("".join(chunks))
            self.out.flush()
        self._shown = list(lines[:self.rows])

    def key(self, timeout=None):
        return (_key_windows if WINDOWS else _key_posix)(timeout)
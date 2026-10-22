"""Type into a WSLg (Linux X11) window. WSLg windows ignore characters injected from the Windows side,
so a window that exists on the X server is typed into here, through the XTEST extension, with the same
rules as inject.py: found by the title the human approved, re-checked at the focus, never a terminal.
The secret is only ever in this process's memory."""

import ctypes
import os
import re
import subprocess
import time

TREE_LINE = re.compile(r'^\s*(0x[0-9a-f]+) "(.+?)": \(')
FOCUS = 2  # RevertToParent
SHIFT_L, CONTROL_L, RETURN, BACKSPACE = 0xFFE1, 0xFFE3, 0xFF0D, 0xFF08
LATIN1_MAX = 0xFF  # keysyms equal code points up to here; beyond it a layout needs a lookup we do not do


def window_titles():
    """{window id: title} for named X windows, from xwininfo (present with the X11 tools)."""
    try:
        out = subprocess.run(
            ["xwininfo", "-root", "-tree"], capture_output=True, text=True, timeout=10, env={**os.environ}
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    return {int(m.group(1), 16): m.group(2) for line in out.splitlines() if (m := TREE_LINE.match(line))}


class Display:
    """One X connection that can focus a window and fake key presses on it."""

    def __init__(self):
        self.x, self.test = ctypes.CDLL("libX11.so.6"), ctypes.CDLL("libXtst.so.6")
        void, ulong, uint, int_ = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_uint, ctypes.c_int
        self.x.XOpenDisplay.restype = void
        self.x.XSetInputFocus.argtypes = [void, ulong, int_, ulong]
        self.x.XRaiseWindow.argtypes = [void, ulong]
        self.x.XSync.argtypes = [void, int_]
        self.x.XKeysymToKeycode.argtypes = [void, ulong]
        self.x.XKeycodeToKeysym.argtypes = [void, uint, int_]
        self.x.XKeycodeToKeysym.restype = ulong
        self.x.XCloseDisplay.argtypes = [void]
        self.test.XTestFakeKeyEvent.argtypes = [void, uint, int_, ulong]
        self.display = self.x.XOpenDisplay(None)
        if not self.display:
            raise OSError("no X display")

    def focus(self, window):
        self.x.XSetInputFocus(self.display, window, FOCUS, 0)
        self.x.XRaiseWindow(self.display, window)
        self.x.XSync(self.display, 0)

    def code(self, keysym):
        return self.x.XKeysymToKeycode(self.display, keysym)

    def needs_shift(self, keysym, code):
        return self.x.XKeycodeToKeysym(self.display, code, 0) != keysym

    def tap(self, keysym, *held):
        """Press and release a key while holding the modifier keysyms given."""
        mods = [self.code(mod) for mod in held]
        code = self.code(keysym)
        for key, down in [*((m, 1) for m in mods), (code, 1), (code, 0), *((m, 0) for m in reversed(mods))]:
            self.test.XTestFakeKeyEvent(self.display, key, down, 0)
        self.x.XSync(self.display, 0)

    def close(self):
        self.x.XCloseDisplay(self.display)


def type_into(window, text, enter, deny, clear=False):
    """Return a status line, or None when no X11 window matches (the caller tries Windows)."""
    matches = {w: t for w, t in window_titles().items() if window.lower() in t.lower()}
    if not matches:
        return None
    target, title = next(iter(matches.items()))
    if any(bad in title.lower() for bad in deny):
        return "refused: that window is on the never-type list (a terminal or agent UI)"
    try:
        display = Display()
    except OSError:
        return "refused: no X display to type into"
    try:
        display.focus(target)
        time.sleep(0.6)  # Chrome drops the first keys if they land while it is still taking focus
        for _ in range(2):  # harmless Shift taps take the dropped first keys, so no typed character is first
            display.tap(SHIFT_L)
            time.sleep(0.1)
        if clear:  # replace what is in the field: Ctrl+A, then Backspace
            display.tap(ord("a"), CONTROL_L)
            display.tap(BACKSPACE)
        for char in text:
            keysym = ord(char)
            if keysym > LATIN1_MAX:
                return (
                    "refused: a character in the value is not typeable on this layout; nothing more was typed"
                )
            code = display.code(keysym)
            if not code:
                return "refused: a character in the value is not on this layout; nothing more was typed"
            display.tap(keysym, *([SHIFT_L] if display.needs_shift(keysym, code) else []))
            time.sleep(0.012)
        if enter:
            display.tap(RETURN)
        return "typed" + (" and pressed Enter" if enter else "")
    finally:
        display.close()

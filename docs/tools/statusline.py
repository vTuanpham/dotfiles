"""Frames of the real Claude Code status line (claude/.claude/statusline.py) with demo input and a fake clock.

Used by readme_gifs.py. Needs a Nerd Font Mono: set NERD_FONT_DIR to a folder holding
SauceCodeProNerdFontMono-Regular.ttf and -Bold.ttf, or the Windows user fonts folder is searched.
"""

import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SCRIPT = Path(__file__).resolve().parents[2] / "claude/.claude/statusline.py"
BASE = (30, 30, 46)  # the terminal background the pills sit on
HOME = Path(os.environ.get("README_HOME", "/tmp/readme-home"))

# Runs the real script with its clock and its git call faked, so every number below is demo data.
DRIVER = """
import runpy, subprocess, sys, time
now = float(sys.argv[2])
time.time = lambda: now
class Git: stdout = "## main...origin/main [ahead 2]\\n M README.md\\n M install.sh\\n"
subprocess.run = lambda *a, **k: Git
runpy.run_path(sys.argv[1], run_name="__main__")
"""


def payload(now, tick):
    return {
        "session_id": "demo",
        "model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"},
        "effort": {"level": "high"},
        "thinking": {"enabled": True},
        "workspace": {"current_dir": f"{HOME}/projects/webapp"},
        "context_window": {"used_percentage": 38 + tick % 3, "context_window_size": 1_000_000},
        "rate_limits": {
            "five_hour": {"used_percentage": 41, "resets_at": now + 2 * 3600 + 13 * 60},
            "seven_day": {"used_percentage": 23, "resets_at": now + 3 * 86400 + 5 * 3600},
        },
        "cost": {"total_cost_usd": 4.62, "total_duration_ms": 47 * 60_000,
                 "total_lines_added": 312, "total_lines_removed": 58},
    }


def font(bold, name=None):
    """The Mono face by default; `name` asks for another exact file (starship_prompt.py)."""
    name = name or f"SauceCodeProNerdFontMono-{'Bold' if bold else 'Regular'}.ttf"
    folders = [
        os.environ.get("NERD_FONT_DIR", ""),
        "/mnt/c/Windows/Fonts",
        *glob.glob("/mnt/c/Users/*/AppData/Local/Microsoft/Windows/Fonts"),
    ]
    for folder in folders:
        if folder and (Path(folder) / name).is_file():
            return str(Path(folder) / name)
    sys.exit(f"{name} not found: set NERD_FONT_DIR")


def ansi_lines(now, tick):
    """The two lines the real script prints, with ANSI colour codes."""
    (HOME / ".cache/claude-statusline").mkdir(parents=True, exist_ok=True)
    history = [[now - 60 * (24 - i), 20 + i * 0.8 + (i % 4)] for i in range(24)]  # a rising context sparkline
    (HOME / ".cache/claude-statusline/demo.json").write_text(json.dumps(history))
    run = subprocess.run(
        [sys.executable, "-I", "-c", DRIVER, str(SCRIPT), str(now)],
        input=json.dumps(payload(now, tick)),
        capture_output=True,
        text=True,
        env={"HOME": str(HOME), "PATH": os.environ["PATH"]},
        check=True,
    )
    return run.stdout.splitlines()


FALLBACK = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono{}.ttf"


class Typeface:
    """Nerd Font Mono cells at `size`; a glyph the Nerd Font lacks (⇡ ▰ ◆) comes from DejaVu Sans Mono."""

    def __init__(self, size):
        self.fonts = {b: ImageFont.truetype(font(b), size) for b in (False, True)}
        self.spare = {b: ImageFont.truetype(FALLBACK.format("-Bold" if b else ""), size)
                      for b in (False, True)}
        ascent, descent = self.fonts[False].getmetrics()
        self.cw, self.ch = round(self.fonts[False].getlength("M")), ascent + descent
        self.absent = self.ink(self.fonts[False], "\U0010fffe")  # what a missing glyph draws
        self.cache = {}

    @staticmethod
    def ink(face, char):
        canvas = Image.new("L", (64, 64))
        ImageDraw.Draw(canvas).text((8, 8), char, font=face, fill=255)
        return canvas.tobytes()

    def put(self, draw, x, y, char, fill, bold=False):
        key = (char, bold)
        if key not in self.cache:
            lacking = self.ink(self.fonts[bold], char) == self.absent
            self.cache[key] = self.spare[bold] if lacking else self.fonts[bold]
        draw.text((x, y), char, font=self.cache[key], fill=fill)


def render(lines, size=30):
    face = Typeface(size)
    cw, ch = face.cw, face.ch
    width = max(len(re.sub(r"\033\[[0-9;]*m", "", line)) for line in lines)
    image = Image.new("RGB", (width * cw, ch * len(lines)), BASE)
    draw = ImageDraw.Draw(image)
    for row, line in enumerate(lines):
        fg, bg, bold, col = (205, 214, 244), None, False, 0
        for token in re.split(r"(\033\[[0-9;]*m)", line):
            if token.startswith("\033["):
                codes = [int(c) for c in token[2:-1].split(";") if c] or [0]
                i = 0
                while i < len(codes):
                    c = codes[i]
                    if c == 0:
                        fg, bg, bold = (205, 214, 244), None, False
                    elif c == 1:
                        bold = True
                    elif c == 22:
                        bold = False
                    elif c in (38, 48) and codes[i + 1] == 2:
                        rgb = tuple(codes[i + 2 : i + 5])
                        fg, bg = (rgb, bg) if c == 38 else (fg, rgb)
                        i += 4
                    i += 1
                continue
            for char in token:
                x, y = col * cw, row * ch
                if bg:
                    draw.rectangle([x, y, x + cw - 1, y + ch - 1], fill=bg)
                face.put(draw, x, y, char, fg, bold)
                col += 1
    return image


if __name__ == "__main__":
    render(ansi_lines(1_790_000_000.0, 0)).save(sys.argv[1] if len(sys.argv) > 1 else "statusline.png")

"""Builds the README's animated images from the real Wake renderer and the real status line.

    README_WORK=<scratch dir> uv run --with pillow python docs/tools/readme_gifs.py [dock|landscapes|hero ...]

Every layer is scaled by a whole number (scene cells x6 or x12, text drawn at its native size), so pixels stay
sharp; frames share one palette and gifsicle stores only what changes, so the files stay small.
Needs bun, google-chrome, gifsicle and the Nerd Font described in statusline.py.
"""

import array
import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
import statusline  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
WAKE = ROOT / "claude/.claude/mods/wake"
IMAGES = ROOT / "docs/images"
WORK = Path(os.environ.get("README_WORK", "/tmp/readme-work"))
FRAMES = 48
DELAY_MS = 120

BASE = statusline.BASE
TEXT, SUBTLE, SURFACE2 = (205, 214, 244), (108, 112, 134), (88, 91, 112)
PEACH, BLUE, MAUVE, TEAL, YELLOW, PINK = (
    (250, 179, 135), (137, 180, 250), (203, 166, 247), (148, 226, 213), (249, 226, 175), (245, 194, 231),
)
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans{}.ttf"


def run(*cmd, cwd=None):
    subprocess.run(cmd, cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cells(path, width):
    data = array.array("I")
    data.frombytes(Path(path).read_bytes())
    return data, width * 16


def scene(data, size, index, scale):
    """Frame `index` of a rendered scene, each cell a scale x scale block."""
    image = Image.new("RGB", (size // 16, 16))
    image.putdata([((v >> 16) & 255, (v >> 8) & 255, v & 255) for v in data[index * size : (index + 1) * size]])
    return image.resize((image.width * scale, 16 * scale), Image.NEAREST)


def save_gif(frames, path, delay=DELAY_MS):
    """One shared palette (no dither, so flat colours stay flat), then gifsicle keeps only changed pixels.
    `delay` is milliseconds, one for all frames or one per frame."""
    step = max(1, len(frames) // 6)
    sample = Image.new("RGB", (frames[0].width, frames[0].height * len(frames[::step])))
    for i, frame in enumerate(frames[::step]):
        sample.paste(frame, (0, i * frame.height))
    palette = sample.quantize(255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    indexed = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    indexed[0].save(path, save_all=True, append_images=indexed[1:], duration=delay, loop=0, optimize=False)
    run("gifsicle", "-O3", "--no-comments", "-b", str(path))
    print(path.name, f"{path.stat().st_size / 1e6:.2f} MB", frames[0].size)


def label_font(bold, size):
    return ImageFont.truetype(SANS.format("-Bold" if bold else ""), size)


# ── landscapes: eight labelled scenes, edge to edge ───────────────────────────────────────────────

def landscapes():
    titles = [
        "City · working · turns become buildings",
        "Harbor · needs input · Codex boats and agy crew",
        "Beach · working · bridge jobs and Claude subagent birds",
        "Mountains · tests passed · fireworks",
        "Countryside · idle · plan lamps show progress",
        "Forest · rain · command failed",
        "Desert · dusk · a finished job leaves a shooting star",
        "Tundra · winter night · sleeping",
    ]
    data, size = cells(WORK / "showcase180.bin", 180)
    font = label_font(False, 17)
    frames = []
    for i in range(FRAMES):
        sheet = Image.new("RGB", (1080, len(titles) * (96 + 30)), BASE)
        draw = ImageDraw.Draw(sheet)
        for s, title in enumerate(titles):
            y = s * 126
            draw.text((16, y + 5), title, font=font, fill=(166, 173, 200))
            sheet.paste(scene(data, size, s * FRAMES + i, 6), (0, y + 30))
        frames.append(sheet)
    save_gif(frames, IMAGES / "wake-landscapes.gif")


# ── hero: the page chrome from google-chrome, the strips drawn over its black band ───────────────

def hero():
    base = WORK / "hero-base.png"
    run(
        "google-chrome", "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1", "--window-size=1200,770", f"--screenshot={base}",
        f"file://{ROOT / 'docs/hero.html'}",
    )
    page = Image.open(base).convert("RGB")
    data, size = cells(WORK / "showcase200.bin", 200)
    frames = []
    for i in range(FRAMES):
        frame = page.copy()
        for k, s in enumerate((1, 2, 3, 7)):  # harbor, beach, mountains, tundra
            frame.paste(scene(data, size, s * FRAMES + i, 6), (0, 250 + k * 96))
        frames.append(frame)
    save_gif(frames, IMAGES / "hero.gif")


# ── dock: the scene with call-outs, the crew and quota rows, a prompt and the real status line ────

LEGEND = {  # name: (title, what it is, colour), left to right
    "lamps": ("Lit street lamps", "plan steps done", YELLOW),
    "codex": ("Codex worker", "a boat, sized by model", BLUE),
    "claude": ("Claude subagent", "a bird: sparrow to eagle", PEACH),
    "agy": ("agy worker", "sparks, comets, stars", MAUVE),
    "live": ("This turn", "a building going up", TEAL),
    "mochi": ("Mochi", "the session's mood", PINK),
}
ROWS = [  # (left, right) per row, coloured segments
    ([("◷ Checking the parser", TEXT)],
     [("turn 7 · 1:02", SUBTLE), (" │ ", SURFACE2), ("☼ 24° Demo coast mainly clear", YELLOW), (" │ ", SURFACE2), ("7 turns ", SUBTLE), ("+82", (166, 227, 161)), ("-19", (243, 139, 168))]),
    ([("◆ Tests ", PEACH), ("▰▰▱ ", SUBTLE), ("claude·Explore · 1m", TEXT), (" │ ", SURFACE2), ("⠿ Parser fix (parser) ", BLUE), ("codex·01 sol ▰▰▱ high · 3m", TEXT), (" │ ", SURFACE2), ("✦ Visual review (review) ", MAUVE), ("agy·a1 opus ▰▰▰ high · 2m", TEXT)], []),
    ([("quota ", SUBTLE), ("codex ", BLUE), ("01* w71 · 02 w34 · 03 h62 w88 · 04 h9 w41", TEXT), (" │ ", SURFACE2), ("agy ", MAUVE), ("a1 G h99 w98 · C h4 w2 · A w85 · a2 G h100 w100 · C h100 w50 · A w98", TEXT)], []),
]


def dock():
    meta = json.loads((WORK / "dock.json").read_text())
    data, size = cells(WORK / "dock.bin", meta["w"])
    S, face = 12, statusline.Typeface(15)
    width = meta["w"] * S
    band, rows_h, gap = 132, face.ch + 3, 12
    scene_y = band
    text_y = scene_y + 16 * S + gap
    prompt_y = text_y + 3 * rows_h + gap
    status_y = prompt_y + 46 + gap
    status_h = 2 * face.ch
    height = status_y + status_h + 8

    chrome = Image.new("RGB", (width, height), BASE)  # everything that does not move
    draw = ImageDraw.Draw(chrome)
    for r, (left, right) in enumerate(ROWS):
        y = text_y + r * rows_h
        for segments, align in ((left, "l"), (right, "r")):
            total = sum(len(t) for t, _ in segments) * face.cw
            x = 6 if align == "l" else width - 6 - total
            for text, color in segments:
                for char in text:
                    face.put(draw, x, y, char, color)
                    x += face.cw
    draw.rounded_rectangle([4, prompt_y, width - 5, prompt_y + 40], 10, outline=SURFACE2, width=2)
    typed, pitch = "❯ Fix the failing parser test", face.cw * 5 // 4
    for x, char in enumerate(typed):
        face.put(draw, 20 + x * pitch, prompt_y + 10, char, PEACH if x == 0 else TEXT)
    cursor_x = 20 + len(typed) * pitch
    chrome_font = label_font(True, 15)
    small = label_font(False, 12)
    order = list(LEGEND)
    held = {}
    frames = []
    for i in range(FRAMES):
        frame = chrome.copy()
        d = ImageDraw.Draw(frame)
        frame.paste(scene(data, size, i, S), (0, scene_y))
        for k, name in enumerate(order):  # call-outs: a label above the scene, a leader to the thing itself
            title, what, color = LEGEND[name]
            found = meta["anchors"][i][name] or held.get(name)
            held[name] = found
            boxes = found if isinstance(found, list) else [found] if found else []  # lamps: one box each
            cx = int((k + 0.5) * width / len(order))
            lx0, lx1, ly0, ly1 = cx - 100, cx + 100, 14, 62
            for box in boxes:
                d.rounded_rectangle(
                    [box["x"] * S - 4, scene_y + box["y"] * S - 4, (box["x"] + box["w"]) * S + 3, scene_y + (box["y"] + box["h"]) * S + 3],
                    6, outline=color, width=2,
                )
            if boxes:  # the leader runs to the box nearest the label
                near = min(boxes, key=lambda b: abs((b["x"] + b["w"] / 2) * S - cx))
                ax, top = (near["x"] + near["w"] / 2) * S, scene_y + near["y"] * S
                d.line([(cx, ly1), (cx, ly1 + 10), (ax, top - 14), (ax, top - 4)], fill=color, width=2)
            d.rounded_rectangle([lx0, ly0, lx1, ly1], 10, fill=(38, 38, 56), outline=color, width=2)
            d.text((cx, ly0 + 15), title, font=chrome_font, fill=color, anchor="mm")
            d.text((cx, ly0 + 35), what, font=small, fill=(166, 173, 200), anchor="mm")
        if i % 8 < 5:  # the prompt's cursor blinks
            d.rectangle([cursor_x, prompt_y + 10, cursor_x + 8, prompt_y + 28], fill=TEXT)
        status = statusline.render(statusline.ansi_lines(1_790_000_000.0 + 3.2 * i / FRAMES, i), 15)
        frame.paste(status.crop((0, 0, min(status.width, width), status.height)), (0, status_y))
        frames.append(frame)
    save_gif(frames, IMAGES / "wake-dock.gif")


if __name__ == "__main__":
    WORK.mkdir(parents=True, exist_ok=True)
    want = sys.argv[1:] or ["dock", "landscapes", "hero"]
    if "landscapes" in want or "hero" in want:
        for w in (180, 200):
            run("bun", "dev/showcase.ts", str(WORK / f"showcase{w}.bin"), str(FRAMES), str(w), cwd=WAKE)
    if "dock" in want:
        run("bun", "dev/dock.ts", str(WORK / "dock.bin"), str(FRAMES), "117", cwd=WAKE)
    for name in want:
        {"dock": dock, "landscapes": landscapes, "hero": hero}[name]()

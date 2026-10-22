"""images/baton.gif: the real Agent Baton one-use form, filled in step by step, beside its Windows toast.

    cd agent-baton && README_WORK=<scratch dir> uv run --with pillow python ../docs/tools/baton_gif.py

It starts the real page server for a demo `ask` (example.com, fake values), screenshots the page with
google-chrome at each typing step, then posts the answer so the last frame is the page's real reply.
AGENT_BATON_HOME must be a short path (a unix socket lives there), for example a symlink under ~/.cache.
"""

import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import readme_gifs as gifs  # noqa: E402
from agent_baton import core, notify, serve  # noqa: E402

DARK = ":root{--fg:#ececf0;--bg:#17171a;--card:#222226;--accent:#fb923c;--muted:#9a9aa3}"
EMAIL, PASSWORD = "you@example.com", "demo-password"
PANEL = (440, 600)
CANVAS = (900, 690)
BG, INK, MUTED, ACCENT = (23, 23, 26), (236, 236, 240), (154, 154, 163), (251, 146, 60)


def start():
    links = []
    notify.notify = lambda baton, link, cfg, public=None: links.append(link) or ["toast"]
    notify.dismiss = lambda baton: None
    fields = [
        {"name": "email", "label": "Account email", "secret": False},
        {"name": "password", "label": "Password", "secret": True},
    ]
    baton = core.create(
        "example.com", "to read the pull request", "Claude", 600,
        kind="ask", window="Sign in", windows=["Sign in"], fields=fields, answered=False, hold=600,
    )
    threading.Thread(target=serve.serve, args=(baton["id"],), daemon=True).start()
    for _ in range(100):
        if links and "notified" in core.load(baton["id"]):
            return baton, links[0]
        time.sleep(0.05)
    sys.exit("the page never came up")


def shot(html, name):
    page = gifs.WORK / f"{name}.html"
    page.write_text(html.replace("</style>", f"{DARK}</style>", 1), encoding="utf-8")  # last, so it wins
    png = gifs.WORK / f"{name}.png"
    gifs.run(
        "google-chrome", "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1", f"--window-size={PANEL[0]},{PANEL[1]}", f"--screenshot={png}", f"file://{page}",
    )
    return Image.open(png).convert("RGB")


def with_values(html, email, password):
    html = html.replace('name="email" type="text"', f'name="email" type="text" value="{email}"')
    return html.replace('name="password" type="password"', f'name="password" type="password" value="{password}"')


def frame(toast, form, step, caption):
    image = Image.new("RGB", CANVAS, BG)
    draw = ImageDraw.Draw(image)
    head, small = gifs.label_font(True, 19), gifs.label_font(False, 15)
    draw.text((24, 22), f"{step}", font=head, fill=ACCENT)
    draw.text((24 + 28, 22), caption, font=head, fill=INK)
    # left: a desktop corner with the toast; right: the form
    if toast:
        image.paste(toast, (28, 150))
        draw.text((28, 150 + toast.height + 14), "Windows toast, or an optional phone push", font=small, fill=MUTED)
        draw.text((28, 150 + toast.height + 36), "that opens the same form", font=small, fill=MUTED)
    else:
        draw.rounded_rectangle([28, 150, 28 + 363, 150 + 177], 10, outline=(52, 52, 74), width=2)
    if form is not None:
        image.paste(form, (CANVAS[0] - PANEL[0] - 6, 70))
        draw.rounded_rectangle([CANVAS[0] - PANEL[0] - 8, 68, CANVAS[0] - 4, 72 + PANEL[1]], 10, outline=(52, 52, 74), width=2)
    return image


def main():
    gifs.WORK.mkdir(parents=True, exist_ok=True)
    baton, link = start()
    html = urllib.request.urlopen(link).read().decode()
    toast = Image.open(Path(__file__).parent / "baton-toast.png").convert("RGB")  # a real capture of the toast
    typed = [with_values(html, EMAIL[:n], "") for n in range(0, len(EMAIL) + 1, 3)] + [with_values(html, EMAIL, "")]
    hidden = [with_values(html, EMAIL, "x" * n) for n in range(2, len(PASSWORD) + 1, 3)] + [with_values(html, EMAIL, "x" * len(PASSWORD))]
    shots_typed = [shot(h, f"typed{i}") for i, h in enumerate(typed)]
    shots_hidden = [shot(h, f"hidden{i}") for i, h in enumerate(hidden)]
    body = urllib.parse.urlencode({"email": EMAIL, "password": PASSWORD}).encode()
    reply = urllib.request.urlopen(urllib.request.Request(link + "/answer", data=body)).read().decode()
    sent = shot(reply, "sent")
    empty = shots_typed[0]

    frames, delays = [], []

    def add(image, ms):
        frames.append(image)
        delays.append(ms)

    add(frame(None, None, "1", "The agent needs something only you can give"), 900)
    add(frame(toast, None, "1", "A Windows notification arrives"), 1400)
    add(frame(toast, empty, "2", "Open it: a one-use form, tied to that request"), 1500)
    for shot_ in shots_typed[1:]:
        add(frame(toast, shot_, "3", "Type your answers; the agent never sees them"), 260)
    for shot_ in shots_hidden:
        add(frame(toast, shot_, "3", "Type your answers; the agent never sees them"), 260)
    add(frame(toast, shots_hidden[-1], "3", "Type your answers; the agent never sees them"), 700)
    add(frame(toast, sent, "4", "Sent: typed into the approved window, held in memory only"), 2400)
    gifs.save_gif(frames, gifs.IMAGES / "baton.gif", delays)


if __name__ == "__main__":
    os.environ.setdefault("AGENT_BATON_SESSION", "readme")
    main()

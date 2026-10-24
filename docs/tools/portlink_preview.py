"""Refresh Portlink's terminal inset with its real CLI output and the host's font.

    uv run --project portlink --with pillow python docs/tools/portlink_preview.py
"""

import base64
import contextlib
import io
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import segno
from PIL import Image, ImageDraw, ImageFont
from statusline import font

from portlink import cli
from portlink.models import Link, Target

ROOT = Path(__file__).resolve().parents[2]
SCALE = 3
URL = "https://demo.example.ts.net:18000"
link = Link("0" * 32, "demo", URL, Target("proxy", "http://127.0.0.1:3000"), 18000, 1, 901)
output = io.StringIO()
with contextlib.redirect_stdout(output), patch("portlink.cli.time.time", return_value=1):
    cli.show(link, SimpleNamespace(qr=lambda _: Path("preview.svg")))
lines = output.getvalue().splitlines()
assert lines[:2] == ["demo · Private · 15m", URL]

image = Image.new("RGB", (500 * SCALE, 300 * SCALE), "#282c34")
draw = ImageDraw.Draw(image)
face = ImageFont.truetype(font(False, "SauceCodeProNerdFontPropo-SemiBold.ttf"), 16 * SCALE)
for y, text in [(8, "$ portlink open 3000 --name demo --ttl 15m"),
                (43, lines[0]), (70, lines[1]),
                (247, "$ portlink close demo"), (274, "Closed demo")]:
    assert draw.textbbox((0, 0), text, font=face)[2] <= image.width
    draw.text((0, y * SCALE), text, font=face, fill="#dcdfe4")
qr = io.BytesIO()
segno.make_qr(URL).save(qr, kind="png", scale=3 * SCALE, border=4)
qr.seek(0)
with Image.open(qr) as code:
    assert code.height <= 145 * SCALE
    image.paste(code.convert("RGB"), (0, 99 * SCALE))
png = io.BytesIO()
image.save(png, format="PNG", optimize=True)
uri = "data:image/png;base64," + base64.b64encode(png.getvalue()).decode()
path = ROOT / "portlink/docs/preview.svg"
source, count = re.subn(r'(<image id="terminal"[^>]* href=")[^"]*("/>)',
                        lambda match: match[1] + uri + match[2], path.read_text())
assert count == 1
path.write_text(source)

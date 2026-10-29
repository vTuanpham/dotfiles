"""Draw the synthetic crew rows produced by crew-review.ts, in terminal cells."""
import base64
import io
import json
import sys

from PIL import Image, ImageDraw, ImageFont

data = json.load(open(sys.argv[1], encoding="utf-8"))
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 16)
fallback = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
missing = (font.getmask("\U0010ffff").size, bytes(font.getmask("\U0010ffff")))
cell, line = 10, 19
margin = 16
heights = [54 + len(panel[data["mode"]]) * line for panel in data["panels"]]
image = Image.new("RGB", (max(panel["width"] for panel in data["panels"]) * cell + margin * 2, sum(heights) + margin * 2), "#1e1e2e")
draw = ImageDraw.Draw(image)
y = margin
for panel, height in zip(data["panels"], heights):
    w = panel["width"] * cell
    draw.text((margin, y), f'{data["mode"]} (simulated)  ·  {panel["width"]} columns  ·  {panel["count"]} workers', font=font, fill="#a6adc8")
    y += 25
    draw.rectangle((margin - 1, y - 1, margin + w, y + height - 30), outline="#45475a")
    for row in panel[data["mode"]]:
        # Clip the terminal surface, including the right edge.
        surface = Image.new("RGB", (w, line), "#1e1e2e")
        ink = ImageDraw.Draw(surface)
        x = 0
        for part in row if isinstance(row, list) else [(row, "#cdd6f4")]:
            if isinstance(part, dict):
                logo = Image.open(io.BytesIO(base64.b64decode(part["png"]))).convert("RGBA")
                logo.thumbnail((cell * 2, line), Image.Resampling.LANCZOS)
                surface.paste(logo, (x + (cell * 2 - logo.width) // 2, (line - logo.height) // 2), logo)
                x += cell * 2
                continue
            text, color = part
            for char in text:
                mask = font.getmask(char)
                face = fallback if (mask.size, bytes(mask)) == missing else font
                ink.text((x, 1), char, font=face, fill=color)
                x += cell * (2 if char in "↗↙" else 1)
        image.paste(surface, (margin, y))
        y += line
    y += 29
image.save(sys.argv[2])

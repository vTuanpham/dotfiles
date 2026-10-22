import json, sys
from PIL import Image, ImageDraw
d = json.load(open(sys.argv[1]))
S = 6
W, H = d["w"], d["h"]
img = Image.new("RGB", (W * S + 20, len(d["rows"]) * (H * S + 22) + 10), (30, 30, 46))
dr = ImageDraw.Draw(img)
for i, row in enumerate(d["rows"]):
    oy = 10 + i * (H * S + 22)
    dr.text((10, oy), row["name"], fill=(166, 173, 200))
    for k, v in enumerate(row["px"]):
        x, y = k % W, k // W
        dr.rectangle([10 + x * S, oy + 13 + y * S, 10 + x * S + S - 1, oy + 13 + y * S + S - 1], fill=((v >> 16) & 255, (v >> 8) & 255, v & 255))
img.save(sys.argv[2])

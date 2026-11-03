"""Save the loading animation as the panel's power-on screen.

Whatever sits in the panel's saved slots shows when it powers on, until the Pi
sends something. This puts a short snake running around a small rounded track into
slot 1. The control page draws the same frames while it connects
(web/src/utils/led.ts, snakeFrame). Keep the two in step.

    ~/led/.venv/bin/python boot_screen.py [API_URL]
"""
import io
import json
import sys
import urllib.request

from PIL import Image

W, H = 64, 16
FRAMES, MS = 40, 45
TINT = (228, 228, 231)  # zinc-200
TRACK, LENGTH = 0.07, 10


def track():
    # clockwise around an 18×8 rounded rectangle in the middle of the panel
    return ([(x, 3) for x in range(23, 41)] + [(41, y) for y in range(4, 12)]
            + [(x, 12) for x in range(40, 22, -1)] + [(22, y) for y in range(11, 3, -1)])


def snake_frame(i):
    """Brightness 0..1 per lit pixel for frame i."""
    path = track()
    n = len(path)
    head = round(i / FRAMES * n) % n
    px = {p: TRACK for p in path}
    for k in range(LENGTH):
        px[path[(head - k) % n]] = 1 - k / (LENGTH + 1)
    return px


def frames():
    out = []
    for i in range(FRAMES):
        img = Image.new("RGB", (W, H))
        for (x, y), v in snake_frame(i).items():
            img.putpixel((x, y), tuple(round(c * v) for c in TINT))
        out.append(img)
    return out


def gif_bytes():
    f = frames()
    buf = io.BytesIO()
    f[0].save(buf, "GIF", save_all=True, append_images=f[1:], duration=MS, loop=0)
    return buf.getvalue()


if __name__ == "__main__":
    api = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
    body = json.dumps({"hex_string": gif_bytes().hex(), "file_extension": ".gif", "save_slot": 1}).encode()
    req = urllib.request.Request(f"{api}/command/send_image_hex", body, {"Content-Type": "application/json"})
    print(urllib.request.urlopen(req, timeout=60).read().decode())

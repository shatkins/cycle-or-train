"""Line illustrations for the dashboard, drawn in code.

Each icon is drawn on a 100x100 grid, 4x supersampled for smooth curves, then
scaled to the requested size. Black on white, bold strokes to suit e-ink.
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw

SS = 4  # supersampling factor


class Pen:
    """Draws on a 100-unit grid scaled to `size` pixels."""

    def __init__(self, size: int, stroke: float = 5):
        self.k = size * SS / 100
        self.img = Image.new("L", (size * SS, size * SS), 255)
        self.d = ImageDraw.Draw(self.img)
        self.w = max(1, round(stroke * self.k))

    def p(self, x, y):
        return (x * self.k, y * self.k)

    def line(self, *pts, w=None):
        pts = [self.p(*q) for q in pts]
        width = self.w if w is None else max(1, round(w * self.k))
        self.d.line(pts, fill=0, width=width, joint="curve")
        r = width / 2  # round caps
        for x, y in (pts[0], pts[-1]):
            self.d.ellipse([x - r, y - r, x + r, y + r], fill=0)

    def circle(self, cx, cy, r, fill=False, w=None):
        box = [*self.p(cx - r, cy - r), *self.p(cx + r, cy + r)]
        width = self.w if w is None else max(1, round(w * self.k))
        self.d.ellipse(box, fill=0 if fill else None, outline=0, width=width)

    def disc(self, cx, cy, r, colour=0):
        self.d.ellipse([*self.p(cx - r, cy - r), *self.p(cx + r, cy + r)], fill=colour)

    def rrect(self, x0, y0, x1, y1, r, fill=False):
        self.d.rounded_rectangle([*self.p(x0, y0), *self.p(x1, y1)], radius=r * self.k,
                                 fill=0 if fill else None, outline=0, width=self.w)

    def poly(self, *pts, fill=True):
        self.d.polygon([self.p(*q) for q in pts], fill=0 if fill else None, outline=0)

    def done(self, size: int) -> Image.Image:
        return self.img.resize((size, size), Image.LANCZOS)


# ---- building blocks ----------------------------------------------------------

def _cloud(pen: Pen, ox=0, oy=0, s=1.0):
    """Outlined cloud: white-filled lobes over a flat base, outlined in black."""
    lobes = [(30, 58, 15), (50, 46, 21), (70, 56, 15)]
    base = (18, 58, 82, 73)
    k = lambda v: v * s  # noqa: E731
    # black silhouette slightly larger, then white fill = outline
    for cx, cy, r in lobes:
        pen.disc(ox + k(cx), oy + k(cy), k(r) + 2.6)
    pen.d.rounded_rectangle([*pen.p(ox + k(base[0]) - 2.6, oy + k(base[1]) - 2.6),
                             *pen.p(ox + k(base[2]) + 2.6, oy + k(base[3]) + 2.6)],
                            radius=k(8) * pen.k, fill=0)
    for cx, cy, r in lobes:
        pen.disc(ox + k(cx), oy + k(cy), k(r), colour=255)
    pen.d.rounded_rectangle([*pen.p(ox + k(base[0]), oy + k(base[1])), *pen.p(ox + k(base[2]), oy + k(base[3]))],
                            radius=k(6) * pen.k, fill=255)


def _sun(pen: Pen, cx, cy, r, rays=8):
    pen.circle(cx, cy, r)
    for i in range(rays):
        a = 2 * math.pi * i / rays
        pen.line((cx + math.cos(a) * (r + 6), cy + math.sin(a) * (r + 6)),
                 (cx + math.cos(a) * (r + 14), cy + math.sin(a) * (r + 14)))


def _drops(pen: Pen, xs, y0=80, length=10, slant=-4):
    for i, x in enumerate(xs):
        y = y0 + (i % 2) * 6
        pen.line((x, y), (x + slant, y + length))


# ---- icons ----------------------------------------------------------------------

def bicycle(size: int) -> Image.Image:
    pen = Pen(size, stroke=4.5)
    rear, front, r = (24, 64), (76, 64), 18
    pen.circle(*rear, r)
    pen.circle(*front, r)
    crank = (46, 64)
    seat_top, head = (38, 36), (68, 36)
    pen.line(rear, crank, seat_top, rear)            # chain stay, seat tube, seat stay
    pen.line(seat_top, head)                         # top tube
    pen.line(crank, head)                            # down tube
    pen.line(head, front)                            # fork
    pen.line((34, 32), (44, 32), w=6)                # saddle
    pen.line(seat_top, (37, 32))
    pen.line(head, (66, 28), (75, 27))               # stem + handlebar
    pen.circle(*crank, 4, fill=True)
    pen.line((42, 72), (50, 56), w=3.5)              # pedal arm
    return pen.done(size)


def train(size: int) -> Image.Image:
    pen = Pen(size, stroke=4.5)
    # side view of a double-deck commuter coach heading right
    pen.d.rounded_rectangle([*pen.p(8, 24), *pen.p(92, 72)], radius=12 * pen.k, outline=0, width=pen.w)
    for row_y in (32, 50):                           # two decks of windows
        for x in range(16, 70, 14):
            pen.rrect(x, row_y, x + 10, row_y + 9, 2, fill=True)
    pen.rrect(76, 44, 88, 58, 3, fill=True)          # cab window
    for x in (22, 36, 64, 78):                       # wheels
        pen.circle(x, 76, 5, fill=True)
    pen.line((2, 84), (98, 84), w=3.5)               # rail
    return pen.done(size)


def house(size: int) -> Image.Image:
    pen = Pen(size, stroke=4.5)
    pen.line((14, 48), (50, 18), (86, 48))
    pen.line((24, 40), (24, 82), (76, 82), (76, 40))
    pen.rrect(42, 56, 58, 82, 2)
    pen.rrect(30, 50, 38, 58, 1, fill=True)
    return pen.done(size)


def sun(size: int) -> Image.Image:
    pen = Pen(size, stroke=4.5)
    _sun(pen, 50, 50, 18, rays=12)
    return pen.done(size)


def cloud(size: int) -> Image.Image:
    pen = Pen(size, stroke=4.5)
    _cloud(pen, 0, 4)
    return pen.done(size)


def showers(size: int) -> Image.Image:
    pen = Pen(size, stroke=4.5)
    _sun(pen, 64, 30, 12, rays=8)
    _cloud(pen, -6, 0, 0.95)
    _drops(pen, [30, 44, 58], y0=76)
    return pen.done(size)


def rain(size: int) -> Image.Image:
    pen = Pen(size, stroke=4.5)
    _cloud(pen, 0, -6)
    _drops(pen, [24, 36, 48, 60, 72], y0=74, length=12)
    return pen.done(size)


def wind(size: int) -> Image.Image:
    pen = Pen(size, stroke=4.5)
    _cloud(pen, 6, -14, 0.8)
    # three gust lines, with a hook on the longest
    for y, x0, x1 in ((62, 12, 72), (74, 4, 88), (86, 18, 66)):
        pen.line((x0, y), (x1, y))
    pen.d.arc([*pen.p(80, 62), *pen.p(96, 74)], start=270, end=90, fill=0, width=pen.w)
    return pen.done(size)


ICONS = {
    # commute
    "CYCLE": bicycle,
    "TRAIN": train,
    "TOO WINDY": train,
    "STORM": wind,
    "YOUR CALL": house,
    # weekend
    "DRY": sun,
    "SHOWERS": showers,
    "RAIN": rain,
}


def for_verdict(verdict: str, size: int, cloudy: bool = False) -> Image.Image | None:
    if verdict == "DRY" and cloudy:
        return cloud(size)
    fn = ICONS.get(verdict)
    return fn(size) if fn else None

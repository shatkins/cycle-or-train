"""Draw the 800x480 black-and-white dashboard."""
from __future__ import annotations

import datetime as dt
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 800, 480
FONTS = Path(__file__).resolve().parent.parent / "fonts"
BLACK, WHITE = 0, 255


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"{name}.otf"), size)


def fit(draw, text, name, size, max_w):
    while size > 10:
        f = font(name, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return font(name, size)


def wrap(draw, text, f, max_w, max_lines=2):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=f) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" ,;") + "…"
    return lines


def arrow(draw, cx, cy, length, angle_deg, width=3, head=9):
    """Arrow centred on (cx, cy) pointing towards angle (0 = up, clockwise)."""
    a = math.radians(angle_deg)
    dx, dy = math.sin(a), -math.cos(a)
    x0, y0 = cx - dx * length / 2, cy - dy * length / 2
    x1, y1 = cx + dx * length / 2, cy + dy * length / 2
    draw.line([(x0, y0), (x1, y1)], fill=BLACK, width=width)
    for side in (-1, 1):
        b = a + side * math.radians(150)
        draw.line([(x1, y1), (x1 + math.sin(b) * head, y1 - math.cos(b) * head)], fill=BLACK, width=width)


def trip_card(draw, x, y, w, t):
    bold, med, reg = font("Inter-Bold", 22), font("Inter-Medium", 20), font("Inter-Regular", 18)
    draw.text((x, y), f"{'OUT' if t['name'] == 'Out' else 'BACK'}  {t['time']}", font=bold, fill=BLACK)
    if t.get("missing"):
        draw.text((x, y + 34), "No forecast yet", font=med, fill=BLACK)
        return

    # Wind dial: you ride "up"; the arrow shows where the wind blows relative to you.
    r = 24
    cx, cy = x + w - r - 2, y + 8
    if t["wind_kmh"] >= 3:
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=BLACK, width=2)
        draw.polygon([(cx, cy - r - 8), (cx - 5, cy - r + 1), (cx + 5, cy - r + 1)], fill=BLACK)
        arrow(draw, cx, cy, 2 * r - 10, (t["wind_from"] + 180 - t["heading"]) % 360, head=7)

    hw = t["headwind_kmh"]
    wind_key = "Headwind" if hw >= 5 else "Tailwind" if hw <= -5 else "Crosswind"
    wind_val = f"{abs(hw) if abs(hw) >= 5 else t['wind_kmh']} km/h"
    if t["gust_kmh"] >= 50 or "wind" in t["flags"]:
        wind_val += f", gusts {t['gust_kmh']}"
    rows = [
        ("Rain", "dry" if t["rain_mm"] < 0.05 else f"{t['rain_mm']} mm", "rain" in t["flags"]),
        ("Feels", f"{t['feels_c']}°C", "cold" in t["flags"]),
        (wind_key, wind_val, "wind" in t["flags"]),
    ]
    for i, (k, v, bad) in enumerate(rows):
        yy = y + 42 + i * 28
        draw.text((x, yy), k, font=reg, fill=BLACK)
        vx = x + 96
        vf = fit(draw, v, "Inter-Medium", 20, w - 96 - 6)
        if bad:
            tw = draw.textlength(v, font=vf)
            draw.rectangle([vx - 5, yy - 3, vx + tw + 5, yy + 25], fill=BLACK)
            draw.text((vx, yy), v, font=vf, fill=WHITE)
        else:
            draw.text((vx, yy), v, font=vf, fill=BLACK)


def rain_strip(draw, x, y, w, h, strip, trips, wind_from, seed):
    """Rain as drops, one column per hour, slanted with the wind."""
    if not strip:
        return
    small = font("Inter-Medium", 15)
    col = w / len(strip)
    base = y + h
    rnd = random.Random(seed)
    slant = math.sin(math.radians((wind_from + 180) % 360 - 90)) * 7  # drift left/right with wind
    for i, s in enumerate(strip):
        x0 = x + i * col
        n = min(int(s["mm"] * 12 + (1 if s["mm"] >= 0.05 else 0)), 40)
        for _ in range(n):
            px = x0 + 4 + rnd.random() * (col - 8)
            py = y + 4 + rnd.random() * (h - 18)
            draw.line([(px, py), (px + slant * 0.6, py + 9)], fill=BLACK, width=2)
        if s["hour"] % 3 == 0:
            draw.text((x0 + col / 2, base + 6), f"{s['hour']:02d}", font=small, fill=BLACK, anchor="mt")
    draw.line([(x, base), (x + w, base)], fill=BLACK, width=2)
    if all(s["mm"] < 0.05 for s in strip):
        draw.text((x + w / 2, y + h / 2 - 6), f"No rain {strip[0]['hour']:02d}:00–{strip[-1]['hour']:02d}:00",
                  font=font("Inter-Medium", 18), fill=BLACK, anchor="mm")

    # Brackets over the ride windows.
    hours = [s["hour"] for s in strip]
    for t in trips:
        hh, mm = map(int, t["time"].split(":"))
        start = hh + mm / 60
        if start < hours[0] or start > hours[-1] + 1:
            continue
        # strip column i covers (hour-1, hour]
        bx0 = x + (start - (hours[0] - 1)) * col
        bx1 = bx0 + col  # ~1 hour ride marker
        draw.line([(bx0, base + 2), (bx0, base - 8), (bx1, base - 8), (bx1, base + 2)], fill=BLACK, width=3)


MODE = {"CYCLE": "RIDE", "TRAIN": "TRAIN", "TOO WINDY": "TRAIN", "STORM": "STORM",
        "YOUR CALL": "YOUR CALL", "NO DATA": "NO DATA"}
BANNER = {"TOO WINDY": "TOO WINDY", "YOUR CALL": "TRAINS DISRUPTED", "STORM": "STAY HOME?"}


COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def compass(deg: float) -> str:
    return COMPASS[round(deg / 45) % 8]


def dial(draw, cx, cy, r, wind_from, fg, bg):
    """Map-style wind dial: N at the top, arrow points where the wind blows TO."""
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=fg, width=3)
    draw.text((cx, cy - r - 2), "N", font=font("Inter-Bold", 14), fill=fg, anchor="mb")
    a = math.radians((wind_from + 180) % 360)
    dx, dy = math.sin(a), -math.cos(a)
    tip = (cx + dx * (r - 5), cy + dy * (r - 5))
    tail = (cx - dx * (r - 5), cy - dy * (r - 5))
    draw.line([tail, tip], fill=fg, width=4)
    for side in (-1, 1):
        b = a + side * math.radians(150)
        draw.line([tip, (tip[0] + math.sin(b) * 12, tip[1] - math.cos(b) * 12)], fill=fg, width=4)


def tile(draw, box, label, value, sub, bad, wind_from=None):
    """A big status box. Black when it's the reason not to ride."""
    x0, y0, x1, y1 = box
    fg, bg = (WHITE, BLACK) if bad else (BLACK, WHITE)
    draw.rectangle(box, fill=bg, outline=BLACK, width=3)
    draw.text((x0 + 14, y0 + 10), label, font=font("Inter-Bold", 18), fill=fg)
    if wind_from is not None:
        dial(draw, x1 - 42, (y0 + y1) // 2 + 4, 26, wind_from, fg, bg)
        x1 -= 80  # keep text clear of the dial
    vf = fit(draw, value, "InterDisplay-Black", 46, x1 - x0 - 28)
    draw.text((x0 + 14, y0 + 30), value, font=vf, fill=fg)
    if sub:
        sf = fit(draw, sub, "Inter-Medium", 17, x1 - x0 - 28)
        draw.text((x0 + 14, y1 - 26), sub, font=sf, fill=fg)


def summarise(trips):
    """Worst-of-both-trips values for the three tiles."""
    ok = [t for t in trips if not t.get("missing")]
    if not ok:
        return None
    wet = max(ok, key=lambda t: t["rain_mm"])
    rain_bad = any("rain" in t["flags"] for t in ok)
    if wet["rain_mm"] < 0.05:
        rain = ("DRY", "both ways")
    else:
        wet_trips = [t["name"].lower() for t in ok if t["rain_mm"] >= 0.05]
        where = "both ways" if len(wet_trips) == 2 else f"on the way {wet_trips[0]}"
        rain = ("RAIN" if rain_bad else "DRIZZLE", f"{wet['rain_mm']} mm {where}")

    windy = max(ok, key=lambda t: (t["headwind_kmh"], t["gust_kmh"]))
    wind_bad = any("wind" in t["flags"] for t in ok)
    hw = windy["headwind_kmh"]
    if hw >= 5:
        wind = (f"{hw} km/h", f"headwind {windy['name'].lower()}, gusts {windy['gust_kmh']}")
    else:
        tail = min(ok, key=lambda t: t["headwind_kmh"])
        wind = (f"{max(t['wind_kmh'] for t in ok)} km/h",
                f"tailwind {tail['name'].lower()}" if tail["headwind_kmh"] <= -5 else "crosswind")

    cold = min(ok, key=lambda t: t["feels_c"])
    cold_bad = any("cold" in t["flags"] for t in ok)
    ice = any("ice risk" in t["problems"] for t in ok)
    temp = (f"{cold['feels_c']}°", "ICE RISK" if ice else f"feels like, {cold['name'].lower()}")
    return (rain, rain_bad), (wind, wind_bad, windy["wind_from"]), (temp, cold_bad)


def render(d: dict, rotate_180: bool = False, legs: dict | None = None) -> Image.Image:
    legs = legs or {}
    img = Image.new("L", (W, H), WHITE)
    draw = ImageDraw.Draw(img)

    # Header
    day = dt.date.fromisoformat(d["date"])
    head = f"{day:%A} {day.day} {day:%B}"
    if d["when"] in ("Today", "Tomorrow"):
        head = f"{d['when']}  ·  {head}"
    draw.text((28, 20), head, font=font("Inter-Bold", 24), fill=BLACK)
    hb = font("Inter-Bold", 24)
    times = f"Out {d['trips'][0]['time']} · Back {d['trips'][1]['time']}"
    draw.text((28 + draw.textlength(head, font=hb) + 22, 23), times, font=font("Inter-Medium", 20), fill=BLACK)
    # Top-right 100x40 is left blank: the device draws its battery icon there.

    # Left: mode word, route, reason
    left_w = 452
    mode = MODE[d["verdict"]]
    vf = fit(draw, mode, "InterDisplay-Black", 168, left_w)
    draw.text((24, 52), mode, font=vf, fill=BLACK)
    y = 52 + int(vf.size * 1.02)

    banner = BANNER.get(d["verdict"])
    if banner:
        bf = font("InterDisplay-Black", 34)
        tw = draw.textlength(banner, font=bf)
        draw.rectangle([28, y, 28 + tw + 24, y + 48], fill=BLACK)
        draw.text((40, y + 4), banner, font=bf, fill=WHITE)
        y += 62

    route = {"RIDE": legs.get("ride"), "TRAIN": legs.get("train")}.get(mode)
    if route:
        rf = fit(draw, route, "Inter-Bold", 34, left_w)
        draw.text((30, y), route, font=rf, fill=BLACK)
        y += 50

    y += 6
    reason = font("Inter-Medium", 22)
    for line in wrap(draw, d["reason"], reason, left_w, max_lines=2):
        draw.text((30, y), line, font=reason, fill=BLACK)
        y += 28

    # Right: three big tiles
    s = summarise(d["trips"])
    x0, x1, top, h, gap = 496, 772, 60, 106, 10
    if s:
        (rain, rb), (wind, wb, wdir), (temp, cb) = s
        tile(draw, (x0, top, x1, top + h), "RAIN", rain[0], rain[1], rb)
        tile(draw, (x0, top + h + gap, x1, top + 2 * h + gap), f"WIND  from {compass(wdir)}",
             wind[0], wind[1], wb, wind_from=wdir)
        tile(draw, (x0, top + 2 * (h + gap), x1, top + 3 * h + 2 * gap), "TEMP", temp[0], temp[1], cb)

    # Bottom: rain strip + footer
    wf = d["trips"][0].get("wind_from", 270)
    rain_strip(draw, 28, 386, 440, 52, d["strip"], d["trips"], wf, d["date"])
    sm = font("Inter-Regular", 15)
    foot = []
    if d["ns"].get("note"):
        foot.append(d["ns"]["note"])
    if d.get("word"):
        foot.append(f"Dutch: {d['word']['nl']} ({d['word']['en']})")
    if d.get("lead_days", 0) > 1:
        foot.append("Early forecast")
    gen = dt.datetime.fromisoformat(d["generated"])
    foot.append(f"Updated {gen.strftime('%a %H:%M')}")
    for i, line in enumerate(reversed(foot[-3:])):
        draw.text((W - 28, 458 - i * 20), line, font=sm, fill=BLACK, anchor="ra")

    out = img.point(lambda v: 255 if v > 140 else 0).convert("1", dither=Image.Dither.NONE)
    return out.rotate(180) if rotate_180 else out


def to_framebuffer(img: Image.Image) -> bytes:
    """Packed 1 bit/pixel, MSB first, 1 = white: the X4 framebuffer layout (48 000 bytes)."""
    assert img.size == (W, H) and img.mode == "1"
    data = img.tobytes()
    assert len(data) == W * H // 8
    return data

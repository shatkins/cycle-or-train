"""Fetch, decide, render, write site/.

    python build.py                       # live run
    python build.py --fixture tests/fixtures/rainy.json --now 2026-11-16T17:30
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from cot import decide, ns, render, weather

ROOT = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=ROOT / "config.yaml")
    ap.add_argument("--out", default=ROOT / "site")
    ap.add_argument("--fixture", help="Open-Meteo JSON to use instead of the API")
    ap.add_argument("--now", help="Pretend local time, e.g. 2026-11-16T04:05")
    ap.add_argument("--no-ns", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    tz = ZoneInfo(cfg["display"]["timezone"])
    now = dt.datetime.fromisoformat(args.now) if args.now else dt.datetime.now(tz).replace(tzinfo=None)

    raw = json.loads(Path(args.fixture).read_text(encoding="utf-8")) if args.fixture else weather.fetch(cfg)
    raw = raw if isinstance(raw, list) else [raw]
    areas = {a["name"]: weather.merge_hourly([loc]) for a, loc in zip(weather.bike_areas(cfg), raw[1:])}
    hourly = weather.merge_hourly(raw[1:])  # worst case across all bike areas

    day, is_weekend = decide.screen_day(cfg, now)
    if is_weekend:
        d = decide.weekend(cfg, weather.merge_hourly(raw[:1]), now, day)  # home only
    else:
        ns_check = None if (args.no_ns or args.fixture) else (lambda t, reverse=False: ns.check(cfg, t, reverse=reverse))
        chances = None if args.fixture else weather.rain_chance(cfg)
        d = decide.decide(cfg, hourly, now, ns_check, day=day, areas=areas, chances=chances)
    if not cfg["display"].get("dutch_word", True):
        d["word"] = None

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    legs = {"ride": cfg["display"].get("route_ride"), "train": cfg["display"].get("route_train")}
    img = render.render(d, rotate_180=cfg["display"].get("rotate_180", False), legs=legs)
    preview = render.render(d, legs=legs)  # always upright for the web preview
    preview.save(out / "dashboard.png")
    (out / "dashboard.bin").write_bytes(render.to_framebuffer(img))
    (out / "status.json").write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "index.html").write_text(INDEX, encoding="utf-8")
    (out / ".nojekyll").write_text("")
    print(f"{d['when']}: {d['verdict']} — {d['reason']}")
    return 0


INDEX = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">
<title>Cycle or train</title>
<style>body{font:16px system-ui;margin:2rem auto;max-width:820px;padding:0 1rem}img{width:100%;border:1px solid #ccc}</style>
<img src="dashboard.png" alt="Today's verdict"><p><a href="status.json">status.json</a> · <a href="dashboard.bin">dashboard.bin</a></p>
"""

if __name__ == "__main__":
    sys.exit(main())

"""Run with:  python -m pytest tests   (or just: python tests/test_decide.py)"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from cot import decide, weather  # noqa: E402

CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def run(fixture, now):
    raw = json.loads((ROOT / "tests/fixtures" / f"{fixture}.json").read_text(encoding="utf-8"))
    return decide.decide(CFG, weather.merge_hourly(raw), dt.datetime.fromisoformat(now))


def test_dry_day_is_cycle():
    assert run("dry_westerly", "2026-11-16T04:05")["verdict"] == "CYCLE"


def test_evening_rain_is_train():
    d = run("rainy_evening", "2026-11-16T04:05")
    assert d["verdict"] == "TRAIN" and "rain" in d["trips"][1]["flags"]


def test_afternoon_run_reports_tomorrow():
    assert run("dry_westerly", "2026-11-16T17:35")["when"] == "Tomorrow"


def test_friday_evening_skips_to_monday_on_weekday_schedule():
    weekdays = ["mon", "tue", "wed", "thu", "fri"]
    assert decide.target_day(dt.datetime(2026, 11, 20, 17, 35), weekdays).weekday() == 0


def shifted(fixture, days):
    """Load a fixture and move every timestamp `days` later (to land on a weekend)."""
    raw = json.loads((ROOT / "tests/fixtures" / f"{fixture}.json").read_text(encoding="utf-8"))
    for loc in raw:
        loc["hourly"]["time"] = [
            (dt.datetime.fromisoformat(t) + dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")
            for t in loc["hourly"]["time"]
        ]
    return raw


def test_friday_evening_shows_saturday_weekend_screen():
    day, is_weekend = decide.screen_day(CFG, dt.datetime(2026, 11, 20, 17, 35))
    assert day.weekday() == 5 and is_weekend


def test_sunday_evening_shows_monday_commute():
    day, is_weekend = decide.screen_day(CFG, dt.datetime(2026, 11, 22, 17, 35))
    assert day.weekday() == 0 and not is_weekend


def test_weekend_dry_and_rainy():
    now = dt.datetime(2026, 11, 20, 17, 35)  # Friday evening -> Saturday 21st
    dry = decide.weekend(CFG, weather.merge_hourly(shifted("dry_westerly", 5)[:1]), now, dt.date(2026, 11, 21))
    assert dry["verdict"] == "DRY" and dry["mode"] == "weekend"
    wet = decide.weekend(CFG, weather.merge_hourly(shifted("storm", 5)[:1]), now, dt.date(2026, 11, 21))
    assert wet["verdict"] == "RAIN" and wet["summary"]["rain_mm"] > 5
    raw = shifted("dry_westerly", 5)[:1]
    h = raw[0]["hourly"]
    for i, t in enumerate(h["time"]):
        if t in ("2026-11-21T14:00", "2026-11-21T15:00"):
            h["precipitation"][i] = 0.6  # a two-hour shower
    showers = decide.weekend(CFG, weather.merge_hourly(raw), now, dt.date(2026, 11, 21))
    assert showers["verdict"] == "SHOWERS" and "13:00–15:00" in showers["reason"]


def test_dry_but_windy_is_too_windy():
    assert run("windy_dry", "2026-11-16T04:05")["verdict"] == "TOO WINDY"


def test_wind_plus_rain_stays_train():
    assert run("stormy", "2026-11-16T04:05")["verdict"] == "TRAIN"


def test_big_gusts_are_storm():
    assert run("storm", "2026-11-16T04:05")["verdict"] == "STORM"


def test_headwind_sign():
    # Haarlem -> Amsterdam heads east; an east wind is a headwind.
    assert decide.headwind(20, 90, decide.bearing(CFG["home"], CFG["work"])) > 19
    assert decide.headwind(20, 270, decide.bearing(CFG["home"], CFG["work"])) < -19


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)

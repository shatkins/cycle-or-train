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


def test_friday_evening_skips_to_monday():
    assert dt.date.fromisoformat(run("dry_westerly", "2026-11-20T17:35")["date"]).weekday() == 0


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

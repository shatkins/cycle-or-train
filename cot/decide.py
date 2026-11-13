"""Turn an hourly forecast into a cycle/train verdict."""
from __future__ import annotations

import datetime as dt
import math
from zoneinfo import ZoneInfo

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def bearing(a: dict, b: dict) -> float:
    """Compass bearing in degrees from point a to point b."""
    la1, la2 = math.radians(a["lat"]), math.radians(b["lat"])
    dlon = math.radians(b["lon"] - a["lon"])
    x = math.sin(dlon) * math.cos(la2)
    y = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def headwind(speed: float, wind_from: float, heading: float) -> float:
    """Wind component against you (km/h). Negative = tailwind."""
    return speed * math.cos(math.radians(wind_from - heading))


def target_day(now: dt.datetime, workdays: list[str]) -> dt.date:
    """Morning runs report today; afternoon runs report the next workday."""
    day = now.date() if now.hour < 12 else now.date() + dt.timedelta(days=1)
    for _ in range(7):
        if DAYS[day.weekday()] in workdays:
            return day
        day += dt.timedelta(days=1)
    return day


def trip_window(hourly: dict, start: dt.datetime, minutes: int) -> list[tuple[dict, float]]:
    """Rows overlapping the ride, with overlap fraction.

    Open-Meteo precipitation at hour T is the total for (T-1h, T].
    """
    end = start + dt.timedelta(minutes=minutes)
    rows = []
    for t, row in sorted(hourly.items()):
        lo, hi = t - dt.timedelta(hours=1), t
        overlap = (min(hi, end) - max(lo, start)).total_seconds()
        if overlap > 0:
            rows.append((row, overlap / 3600))
    return rows


def assess_trip(name: str, rows, heading: float, rules: dict) -> dict:
    if not rows:
        return {"name": name, "missing": True, "problems": ["no forecast"]}
    rain = sum((r["precipitation"] or 0) * f for r, f in rows)
    rate = max((r["precipitation"] or 0) for r, _ in rows)
    feels = min(r["apparent_temperature"] for r, _ in rows if r["apparent_temperature"] is not None)
    temp = min(r["temperature_2m"] for r, _ in rows if r["temperature_2m"] is not None)
    gust = max((r["wind_gusts_10m"] or 0) for r, _ in rows)
    winds = [(r["wind_speed_10m"] or 0, r["wind_direction_10m"] or 0) for r, _ in rows]
    hw = max(headwind(s, d, heading) for s, d in winds)
    speed, wdir = max(winds)

    problems, flags = [], set()
    if rate > rules["max_rain_mm_per_hour"]:
        problems.append(f"{rate:.1f} mm/h rain")
        flags.add("rain")
    elif rain > rules["max_rain_mm_per_trip"]:
        problems.append(f"{rain:.1f} mm rain")
        flags.add("rain")
    if hw > rules["max_headwind_kmh"]:
        problems.append(f"{hw:.0f} km/h headwind")
        flags.add("wind")
    if gust > rules["max_gusts_kmh"]:
        problems.append(f"gusts {gust:.0f} km/h")
        flags.add("wind")
    if feels < rules["min_feels_like_c"]:
        problems.append(f"feels {feels:.0f}°")
        flags.add("cold")
    if temp <= rules["ice_below_c"] and rain > 0.05:
        problems.append("ice risk")
        flags.add("cold")

    return {
        "name": name,
        "rain_mm": round(rain, 1),
        "rain_rate": round(rate, 1),
        "feels_c": round(feels),
        "headwind_kmh": round(hw),
        "wind_kmh": round(speed),
        "wind_from": round(wdir),
        "gust_kmh": round(gust),
        "heading": round(heading),
        "problems": problems,
        "flags": sorted(flags),
    }


def dutch_word(rows: list[dict]) -> tuple[str, str]:
    code = max((r.get("weather_code") or 0) for r in rows) if rows else 0
    gust = max((r.get("wind_gusts_10m") or 0) for r in rows) if rows else 0
    if gust >= 75:
        return "storm", "storm"
    table = [
        (95, "onweer", "thunderstorm"),
        (82, "stortbui", "downpour"),
        (80, "regenbui", "rain shower"),
        (71, "sneeuw", "snow"),
        (66, "ijzel", "freezing rain"),
        (61, "regen", "rain"),
        (56, "ijzel", "freezing drizzle"),
        (51, "motregen", "drizzle"),
        (45, "mist", "fog"),
        (3, "bewolkt", "overcast"),
        (1, "half bewolkt", "partly cloudy"),
        (0, "zonnig", "sunny"),
    ]
    if gust >= 50:
        return "harde wind", "strong wind"
    for threshold, nl, en in table:
        if code >= threshold:
            return nl, en
    return "zonnig", "sunny"


QUIPS = {
    "CYCLE": [
        "Dry roads. No excuses.",
        "Leave the OV-chipkaart in the drawer.",
        "A good day to overtake a scooter.",
        "Your legs will thank you. Eventually.",
        "Fresh air, free of charge.",
    ],
    "TRAIN": [
        "Read a book. Let NS do the pedalling.",
        "Your bike will forgive you.",
        "Sensible is a perfectly good choice.",
        "The rain gear stays in the hallway.",
        "Coffee on the platform it is.",
    ],
    "NO DATA": ["Check back at the next update."],
    "TOO WINDY": [
        "Dry, but you'd be pedalling in place.",
        "Save your knees for another day.",
        "The wind wins this one.",
    ],
    "STORM": [
        "Kitchen table office?",
        "Not a day for bikes, or umbrellas.",
    ],
    "YOUR CALL": [
        "Bad weather, bad trains. Kettle on?",
        "Today, the kitchen table is an office.",
    ],
}


def decide(cfg: dict, hourly: dict, now: dt.datetime, ns_check=None) -> dict:
    tz = ZoneInfo(cfg["display"]["timezone"])
    rules, com = cfg["rules"], cfg["commute"]
    day = target_day(now, com["workdays"])
    out_heading = bearing(cfg["home"], cfg["work"])

    def at(hhmm: str) -> dt.datetime:
        h, m = map(int, hhmm.split(":"))
        return dt.datetime.combine(day, dt.time(h, m))  # naive local, matches Open-Meteo keys

    t_out, t_back = at(com["leave_morning"]), at(com["leave_evening"])
    rows_out = trip_window(hourly, t_out, com["ride_minutes"])
    rows_back = trip_window(hourly, t_back, com["ride_minutes"])
    trips = [
        assess_trip("Out", rows_out, out_heading, rules) | {"time": com["leave_morning"]},
        assess_trip("Back", rows_back, (out_heading + 180) % 360, rules) | {"time": com["leave_evening"]},
    ]

    problems = [p for t in trips for p in t["problems"]]
    flags = {f for t in trips for f in t.get("flags", [])}
    verdict = "TRAIN" if problems else "CYCLE"
    max_gust = max((t.get("gust_kmh", 0) for t in trips), default=0)
    if max_gust >= rules.get("storm_gusts_kmh", 75):
        verdict = "STORM"
    elif flags == {"wind"}:
        verdict = "TOO WINDY"
    if any(t.get("missing") for t in trips):
        verdict = "NO DATA"

    ns = {"ok": None, "note": ""}
    if ns_check:
        res = [ns_check(t_out.replace(tzinfo=tz)), ns_check(t_back.replace(tzinfo=tz), reverse=True)]
        bad = [r for r in res if r["ok"] is False]
        ns = bad[0] if bad else res[0]

    if verdict in ("TRAIN", "TOO WINDY") and ns["ok"] is False:
        verdict = "YOUR CALL"

    reason = _reason(verdict, trips, ns)

    day_rows = [r for t, r in sorted(hourly.items()) if t.date() == day and 6 <= t.hour <= 21]
    strip = [
        {"hour": t.hour, "mm": r["precipitation"] or 0}
        for t, r in sorted(hourly.items())
        if t.date() == day and 6 <= t.hour <= 21
    ]
    nl, en = dutch_word([r for r, _ in rows_out + rows_back] or day_rows)
    quips = QUIPS[verdict]

    lead = (day - now.date()).days
    when = "Today" if lead == 0 else "Tomorrow" if lead == 1 else day.strftime("%A")

    return {
        "generated": now.isoformat(timespec="minutes"),
        "date": day.isoformat(),
        "when": when,
        "verdict": verdict,
        "reason": reason,
        "trips": trips,
        "strip": strip,
        "ns": ns,
        "word": None if verdict == "NO DATA" else {"nl": nl, "en": en},
        "quip": quips[day.toordinal() % len(quips)],
        "lead_days": lead,
    }


def _reason(verdict: str, trips: list[dict], ns: dict) -> str:
    if verdict == "STORM":
        gust = max(t.get("gust_kmh", 0) for t in trips)
        return f"Gusts up to {gust} km/h. Trains and the ferry may be disrupted too"
    if verdict == "TOO WINDY":
        bits = [p for t in trips for p in t["problems"]]
        return f"Dry, but {bits[0]}. Take the train"
    if verdict == "NO DATA":
        return "The forecast doesn't reach that far yet"
    if verdict == "YOUR CALL":
        return "Weather says train, but the trains are disrupted"
    if verdict == "TRAIN":
        bad = [t for t in trips if t["problems"]]
        if len(bad) == 1 and len(bad[0]["problems"]) <= 2:  # specific when it's simple
            t = bad[0]
            return f"{' and '.join(t['problems']).capitalize()} on the way {t['name'].lower()}"
        words = {"rain": "rain", "wind": "strong wind", "cold": "ice or cold"}
        def summary(t):
            items = [words[f] for f in ("rain", "wind", "cold") if f in t["flags"]]
            return " and ".join(items)
        if len(bad) == 2 and summary(bad[0]) == summary(bad[1]):
            return f"{summary(bad[0]).capitalize()} both ways"
        return "; ".join(f"{summary(t)} on the way {t['name'].lower()}" for t in bad).capitalize()
    tail = [t for t in trips if t.get("headwind_kmh", 0) <= -10]
    if tail:
        t = tail[0]
        return f"Dry, with a {-t['headwind_kmh']} km/h tailwind on the way {t['name'].lower()}"
    worst = max(trips, key=lambda t: t.get("headwind_kmh", 0))
    if worst.get("headwind_kmh", 0) >= 12:
        return f"Dry, but {worst['headwind_kmh']} km/h headwind on the way {worst['name'].lower()}"
    return "Dry both ways, light wind"

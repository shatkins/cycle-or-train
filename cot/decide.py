"""Turn an hourly forecast into a cycle/train verdict."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


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


def assess_leg(name: str, rows, rules: dict) -> dict:
    """Weather for one bike leg (NDSM <-> studio). Any measurable rain = bus."""
    if not rows:
        return {"name": name, "missing": True, "problems": ["no forecast"], "flags": []}
    rain = sum((r["precipitation"] or 0) * f for r, f in rows)
    rate = max((r["precipitation"] or 0) for r, _ in rows)
    feels = min(r["apparent_temperature"] for r, _ in rows if r["apparent_temperature"] is not None)
    gust = max((r["wind_gusts_10m"] or 0) for r, _ in rows)
    speed, wdir = max((r["wind_speed_10m"] or 0, r["wind_direction_10m"] or 0) for r, _ in rows)

    problems, flags = [], set()
    if rate >= rules.get("rain_from_mm", 0.1):
        problems.append(f"{rate:.1f} mm/h rain")
        flags.add("rain")
    if gust >= rules.get("storm_gusts_kmh", 75):
        problems.append(f"gusts {gust:.0f} km/h")
        flags.add("wind")
    return {
        "name": name,
        "rain_mm": round(rain, 1),
        "rain_rate": round(rate, 1),
        "feels_c": round(feels),
        "wind_kmh": round(speed),
        "wind_from": round(wdir),
        "gust_kmh": round(gust),
        "problems": problems,
        "flags": sorted(flags),
    }


def chance_in_window(chances: dict[dt.datetime, int], start: dt.datetime, minutes: int) -> int | None:
    """Highest hourly chance of rain among the hours the ride overlaps."""
    end = start + dt.timedelta(minutes=minutes)
    vals = [p for t, p in chances.items() if t - dt.timedelta(hours=1) < end and t > start]
    return max(vals) if vals else None


def decide(cfg: dict, hourly: dict, now: dt.datetime, ns_check=None, day: dt.date | None = None,
           areas: dict | None = None, chances: dict | None = None) -> dict:
    """Commute days: BIKE or BUS for the last leg.

    `hourly` is the worst case across all bike areas; `areas` maps each area's name to its
    own forecast, used to say *where* it will rain.
    """
    tz = ZoneInfo(cfg["display"]["timezone"])
    rules, com = cfg["rules"], cfg["commute"]
    day = day or target_day(now, com["workdays"])

    def at(hhmm: str) -> dt.datetime:
        h, m = map(int, hhmm.split(":"))
        return dt.datetime.combine(day, dt.time(h, m))  # naive local, matches Open-Meteo keys

    leave_home, leave_work = at(com["leave_morning"]), at(com["leave_evening"])
    bike_in = leave_home + dt.timedelta(minutes=com.get("bike_leg_after_minutes", 45))
    minutes = com.get("bike_minutes", 20)
    rows_in = trip_window(hourly, bike_in, minutes)
    rows_back = trip_window(hourly, leave_work, minutes)
    trips = [
        assess_leg("In", rows_in, rules) | {"time": com["leave_morning"], "ride_at": bike_in.strftime("%H:%M")},
        assess_leg("Back", rows_back, rules) | {"time": com["leave_evening"], "ride_at": leave_work.strftime("%H:%M")},
    ]
    flags = {f for t in trips for f in t["flags"]}

    # Which places are wet on each ride (for the reason line).
    names = list(areas) if areas else [cfg["work"]["name"]]
    for trip, start in zip(trips, (bike_in, leave_work)):
        if areas:
            trip["wet_at"] = [
                n for n, h in areas.items()
                if any((r["precipitation"] or 0) >= rules.get("rain_from_mm", 0.1)
                       for r, _ in trip_window(h, start, minutes))
            ]
        else:
            trip["wet_at"] = names if "rain" in trip["flags"] else []

    if any(t.get("missing") for t in trips):
        verdict = "NO DATA"
    elif "wind" in flags:
        verdict = "STORM"
    elif "rain" in flags:
        verdict = "BUS"
    else:
        verdict = "BIKE"

    ns = {"ok": None, "note": ""}
    if ns_check:  # you take the train every day: just report its status
        res = [ns_check(leave_home.replace(tzinfo=tz)),
               ns_check((leave_work + dt.timedelta(minutes=30)).replace(tzinfo=tz), reverse=True)]
        bad = [r for r in res if r["ok"] is False]
        ns = bad[0] if bad else res[0]

    strip = [
        {"hour": t.hour, "mm": r["precipitation"] or 0}
        for t, r in sorted(hourly.items())
        if t.date() == day and 6 <= t.hour <= 21
    ]
    day_rows = [r for t, r in sorted(hourly.items()) if t.date() == day and 6 <= t.hour <= 21]
    nl, en = dutch_word([r for r, _ in rows_in + rows_back] or day_rows)
    lead = (day - now.date()).days
    when = "Today" if lead == 0 else "Tomorrow" if lead == 1 else day.strftime("%A")
    place = names

    # Chance of rain per place, for the morning and evening rides.
    chance_table = []
    for name, per_hour in (chances or {}).items():
        chance_table.append({
            "place": name,
            "in": chance_in_window(per_hour, bike_in, minutes),
            "back": chance_in_window(per_hour, leave_work, minutes),
        })

    return {
        "generated": now.isoformat(timespec="minutes"),
        "date": day.isoformat(),
        "when": when,
        "verdict": verdict,
        "reason": _reason(verdict, trips, place),
        "trips": trips,
        "strip": strip,
        "ns": ns,
        "word": None if verdict == "NO DATA" else {"nl": nl, "en": en},
        "lead_days": lead,
        "chances": chance_table,
    }


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _reason(verdict: str, trips: list[dict], places: list[str]) -> str:
    if verdict == "NO DATA":
        return "The forecast doesn't reach that far yet"
    if verdict == "STORM":
        gust = max(t.get("gust_kmh", 0) for t in trips)
        return f"Gusts up to {gust} km/h. Trains and the ferry may be disrupted"
    wet = [t for t in trips if "rain" in t["flags"]]
    if verdict == "BUS":
        where = sorted({n for t in wet for n in t.get("wet_at", [])}, key=places.index) or places
        if len(wet) == 2:
            return f"Rain at {_join(where)} both ways"
        t = wet[0]
        when = "in the morning" if t["name"] == "In" else "on the way back"
        return f"Rain at {_join(where)} {when} ({t['rain_rate']} mm/h)"
    return f"Dry at {_join(places)} for both rides" if len(places) <= 2 else "Dry everywhere, both rides"


# ---- Weekend: no commute, just "will it rain at home today?" -------------------

def screen_day(cfg: dict, now: dt.datetime) -> tuple[dt.date, bool]:
    """Which day to show, and whether it's a weekend (non-commute) day."""
    workdays = cfg["commute"]["workdays"]
    if cfg["display"].get("weekend_screen", True):
        day = target_day(now, DAYS)  # every day gets a screen
    else:
        day = target_day(now, workdays)
    return day, DAYS[day.weekday()] not in workdays


def weekend(cfg: dict, hourly_home: dict, now: dt.datetime, day: dt.date) -> dict:
    """Daytime rain outlook for the home location only."""
    w = cfg["display"].get("weekend_hours", [8, 20])
    rows = [(t, r) for t, r in sorted(hourly_home.items()) if t.date() == day and w[0] < t.hour <= w[1]]
    lead = (day - now.date()).days
    when = "Today" if lead == 0 else "Tomorrow" if lead == 1 else day.strftime("%A")
    base = {
        "mode": "weekend",
        "generated": now.isoformat(timespec="minutes"),
        "date": day.isoformat(),
        "when": when,
        "place": cfg["home"]["name"],
        "lead_days": lead,
        "ns": {"ok": None, "note": ""},
        "trips": [],
        "strip": [
            {"hour": t.hour, "mm": r["precipitation"] or 0}
            for t, r in sorted(hourly_home.items())
            if t.date() == day and 6 <= t.hour <= 21
        ],
    }
    if not rows:
        return base | {"verdict": "NO DATA", "reason": "The forecast doesn't reach that far yet",
                       "word": None, "summary": None}

    wet = [(t, r["precipitation"] or 0) for t, r in rows if (r["precipitation"] or 0) >= 0.1]
    total = sum((r["precipitation"] or 0) for _, r in rows)
    if not wet:
        verdict, reason = "DRY", f"No rain in {cfg['home']['name']} between {w[0]:02d}:00 and {w[1]:02d}:00"
    else:
        first, last = wet[0][0], wet[-1][0]
        span = f"{(first - dt.timedelta(hours=1)).hour:02d}:00–{last.hour:02d}:00"
        if len(wet) <= 3:
            verdict, reason = "SHOWERS", f"Some rain between {span}, dry otherwise"
        else:
            verdict, reason = "RAIN", f"Wet day: rain on and off {span}"

    temps = [r["temperature_2m"] for _, r in rows if r["temperature_2m"] is not None]
    feels = [r["apparent_temperature"] for _, r in rows if r["apparent_temperature"] is not None]
    windiest = max(rows, key=lambda tr: tr[1]["wind_speed_10m"] or 0)[1]
    gust = max((r["wind_gusts_10m"] or 0) for _, r in rows)
    nl, en = dutch_word([r for _, r in rows])
    return base | {
        "verdict": verdict,
        "reason": reason,
        "word": {"nl": nl, "en": en},
        "summary": {
            "rain_mm": round(total, 1),
            "rain_hours": len(wet),
            "temp_max": round(max(temps)) if temps else None,
            "feels_min": round(min(feels)) if feels else None,
            "wind_kmh": round(windiest["wind_speed_10m"] or 0),
            "wind_from": round(windiest["wind_direction_10m"] or 0),
            "gust_kmh": round(gust),
        },
    }

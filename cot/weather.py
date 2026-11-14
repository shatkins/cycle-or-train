"""Fetch the hourly forecast from Open-Meteo for both ends of the route."""
from __future__ import annotations

import datetime as dt
import time

import requests

API = "https://api.open-meteo.com/v1/forecast"
ENSEMBLE_API = "https://ensemble-api.open-meteo.com/v1/ensemble"
ENSEMBLE_MODEL = "dwd_icon_seamless_eps"  # DWD ICON, 40 slightly different runs
FIELDS = [
    "temperature_2m",
    "apparent_temperature",
    "precipitation",
    "precipitation_probability",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "weather_code",
]


def fetch(cfg: dict) -> dict:
    """Return raw Open-Meteo JSON: home first, then each bike area (same order as config)."""
    pts = [cfg["home"], *bike_areas(cfg)]
    params = {
        "latitude": ",".join(str(p["lat"]) for p in pts),
        "longitude": ",".join(str(p["lon"]) for p in pts),
        "hourly": ",".join(FIELDS),
        "models": cfg.get("forecast", {}).get("model", "best_match"),
        "timezone": cfg["display"]["timezone"],
        "wind_speed_unit": "kmh",
        "forecast_days": 4,
    }
    # Weather services sometimes hiccup. Try 4 times, waiting a bit longer each time.
    for attempt in range(4):
        try:
            r = requests.get(API, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else [data]
        except requests.RequestException as e:
            if attempt == 3:
                raise  # give up: the run fails and the previous dashboard stays online
            wait = 15 * (attempt + 1)
            print(f"Open-Meteo attempt {attempt + 1} failed ({type(e).__name__}), retrying in {wait}s")
            time.sleep(wait)


def bike_areas(cfg: dict) -> list[dict]:
    """Places where rain decides BIKE or BUS. Falls back to the single `work` location."""
    return cfg.get("bike_areas") or [cfg["work"]]


def merge_hourly(raw: list) -> dict[dt.datetime, dict]:
    """Combine locations into one worst-case series keyed by local hour.

    Rain, wind and gusts take the max across locations; temperatures the min.
    Wind direction comes from the location with the strongest wind.
    """
    out: dict[dt.datetime, dict] = {}
    for loc in raw:
        h = loc["hourly"]
        for i, t in enumerate(h["time"]):
            key = dt.datetime.fromisoformat(t)
            row = {f: (h.get(f) or [None] * len(h["time"]))[i] for f in FIELDS}
            cur = out.get(key)
            if cur is None:
                out[key] = row
                continue
            for f in ("precipitation", "precipitation_probability", "wind_gusts_10m"):
                cur[f] = _max(cur[f], row[f])
            for f in ("temperature_2m", "apparent_temperature"):
                cur[f] = _min(cur[f], row[f])
            if (row["wind_speed_10m"] or 0) > (cur["wind_speed_10m"] or 0):
                cur["wind_speed_10m"] = row["wind_speed_10m"]
                cur["wind_direction_10m"] = row["wind_direction_10m"]
            cur["weather_code"] = _max(cur["weather_code"], row["weather_code"])
    return out


def _max(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def _min(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def rain_chance(cfg: dict, threshold: float = 0.1) -> dict[str, dict[dt.datetime, int]] | None:
    """Chance of rain (%) per bike area per hour, from the ensemble forecast.

    Each ensemble member is one plausible version of the weather. The chance is the
    share of members with at least `threshold` mm in that hour. Returns None if the
    ensemble service can't be reached: the screen then just leaves the chances out.
    """
    pts = bike_areas(cfg)
    params = {
        "latitude": ",".join(str(p["lat"]) for p in pts),
        "longitude": ",".join(str(p["lon"]) for p in pts),
        "hourly": "precipitation",
        "models": cfg.get("forecast", {}).get("ensemble_model", ENSEMBLE_MODEL),
        "timezone": cfg["display"]["timezone"],
        "forecast_days": 4,
    }
    for attempt in range(3):
        try:
            r = requests.get(ENSEMBLE_API, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            break
        except requests.RequestException as e:
            print(f"Ensemble attempt {attempt + 1} failed ({type(e).__name__})")
            time.sleep(10 * (attempt + 1))
    else:
        return None
    data = data if isinstance(data, list) else [data]
    return {p["name"]: chances_from_members(loc["hourly"], threshold) for p, loc in zip(pts, data)}


def chances_from_members(hourly: dict, threshold: float = 0.1) -> dict[dt.datetime, int]:
    """Turn ensemble member columns (precipitation, precipitation_member01, ...) into %."""
    members = [k for k in hourly if k == "precipitation" or k.startswith("precipitation_member")]
    out = {}
    for i, t in enumerate(hourly["time"]):
        vals = [hourly[k][i] for k in members if hourly[k][i] is not None]
        if vals:
            out[dt.datetime.fromisoformat(t)] = round(100 * sum(v >= threshold for v in vals) / len(vals))
    return out

"""Fetch the hourly forecast from Open-Meteo for both ends of the route."""
from __future__ import annotations

import datetime as dt

import requests

API = "https://api.open-meteo.com/v1/forecast"
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
    """Return raw Open-Meteo JSON (a list, one entry per location)."""
    pts = [cfg["home"], cfg["work"]]
    params = {
        "latitude": ",".join(str(p["lat"]) for p in pts),
        "longitude": ",".join(str(p["lon"]) for p in pts),
        "hourly": ",".join(FIELDS),
        "models": cfg.get("forecast", {}).get("model", "best_match"),
        "timezone": cfg["display"]["timezone"],
        "wind_speed_unit": "kmh",
        "forecast_days": 4,
    }
    r = requests.get(API, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else [data]


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

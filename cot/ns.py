"""Check NS (Dutch Railways) for problems on the train you'd take.

Needs a free key from https://apiportal.ns.nl (product "Ns-App"), stored as the
NS_API_KEY secret. Without a key the check is skipped.
"""
from __future__ import annotations

import datetime as dt
import os

import requests

TRIPS = "https://gateway.apiportal.ns.nl/reisinformatie-api/api/v3/trips"
BAD_STATUS = {
    "CANCELLED",
    "CHANGE_NOT_POSSIBLE",
    "ALTERNATIVE_TRANSPORT",
    "DISRUPTION",
    "MAINTENANCE",
    "NOT_POSSIBLE",
}


def check(cfg: dict, depart: dt.datetime, *, reverse: bool = False) -> dict:
    """Return {'ok': bool|None, 'note': str} for trains around `depart` (local, tz-aware)."""
    key = os.environ.get("NS_API_KEY")
    if not key:
        return {"ok": None, "note": "NS check off (no API key)"}
    a, b = cfg["train"]["from_station"], cfg["train"]["to_station"]
    if reverse:
        a, b = b, a
    try:
        r = requests.get(
            TRIPS,
            params={"fromStation": a, "toStation": b, "dateTime": depart.isoformat()},
            headers={"Ocp-Apim-Subscription-Key": key},
            timeout=20,
        )
        r.raise_for_status()
        return assess(r.json(), depart)
    except Exception as e:  # never let NS break the dashboard
        return {"ok": None, "note": f"NS unavailable ({type(e).__name__})"}


def assess(payload: dict, depart: dt.datetime, window_min: int = 30) -> dict:
    """Judge the trips leaving within `window_min` of `depart`."""
    near = []
    for trip in payload.get("trips", []):
        legs = trip.get("legs") or []
        if not legs:
            continue
        t = legs[0].get("origin", {}).get("plannedDateTime")
        if not t:
            continue
        when = dt.datetime.strptime(t, "%Y-%m-%dT%H:%M:%S%z")
        if abs((when - depart).total_seconds()) <= window_min * 60:
            near.append(trip)
    if not near:
        return {"ok": None, "note": "No NS trips found"}

    problems = []
    for trip in near:
        status = trip.get("status", "NORMAL")
        cancelled = any(leg.get("cancelled") for leg in trip.get("legs", []))
        planned = trip.get("plannedDurationInMinutes")
        actual = trip.get("actualDurationInMinutes") or planned
        delay = (actual - planned) if planned and actual else 0
        if status in BAD_STATUS or cancelled:
            problems.append(status.replace("_", " ").lower() if not cancelled else "cancelled")
        elif delay >= 10:
            problems.append(f"+{delay} min")
        else:
            problems.append(None)

    if all(problems):
        return {"ok": False, "note": f"Trains: {problems[0]}"}
    if any(problems):
        return {"ok": True, "note": "Trains: some disruption"}
    return {"ok": True, "note": "Trains running normally"}

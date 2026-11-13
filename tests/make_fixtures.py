"""Generate synthetic Open-Meteo responses for offline testing."""
import datetime as dt
import json
import math
from pathlib import Path

HERE = Path(__file__).parent / "fixtures"


def series(start: dt.date, rain, wind, wdir, temp, code):
    times, cols = [], {k: [] for k in [
        "temperature_2m", "apparent_temperature", "precipitation", "precipitation_probability",
        "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "weather_code"]}
    for i in range(96):
        t = dt.datetime.combine(start, dt.time()) + dt.timedelta(hours=i)
        h = t.hour
        times.append(t.strftime("%Y-%m-%dT%H:%M"))
        r = rain(h, i)
        cols["precipitation"].append(round(r, 2))
        cols["precipitation_probability"].append(None)
        cols["wind_speed_10m"].append(wind(h))
        cols["wind_gusts_10m"].append(round(wind(h) * 1.7))
        cols["wind_direction_10m"].append(wdir)
        cols["temperature_2m"].append(temp(h))
        cols["apparent_temperature"].append(temp(h) - 3)
        cols["weather_code"].append(code if r > 0.05 else 3)
    return {"hourly": {"time": times, **cols}}


start = dt.date(2026, 11, 16)  # a Monday
cases = {
    # Westerly 20 km/h: tailwind into Amsterdam, headwind home. Dry.
    "dry_westerly": series(start, lambda h, i: 0, lambda h: 20, 260, lambda h: 9 + 3 * math.sin((h - 9) / 24 * 6.28), 3),
    # Showers in the evening rush.
    "rainy_evening": series(start, lambda h, i: 1.8 if 17 <= h <= 19 else (0.2 if h in (12, 13) else 0),
                            lambda h: 14, 200, lambda h: 8, 61),
    # Storm from the east.
    "stormy": series(start, lambda h, i: 0.3 if 7 <= h <= 20 else 0, lambda h: 42, 80, lambda h: 6, 80),
    # Dry but a strong easterly: headwind into Amsterdam.
    "windy_dry": series(start, lambda h, i: 0, lambda h: 32, 90, lambda h: 7, 3),
    # Proper storm: gusts ~85 km/h.
    "storm": series(start, lambda h, i: 0.8, lambda h: 50, 240, lambda h: 9, 61),
}
HERE.mkdir(exist_ok=True)
for name, s in cases.items():
    (HERE / f"{name}.json").write_text(json.dumps([s, s]))
print("wrote", ", ".join(cases))

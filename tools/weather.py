"""
Weather tool backed by wttr.in (free, no API key).

Loaded on every OS (root tools/ directory). wttr.in serves the current
conditions plus a forecast for today and the next two days, in 3-hour steps.
"""

from datetime import date, datetime
from urllib.parse import quote

import requests

_URL = "https://wttr.in/{location}?format=j1&lang=pt"
_TIMEOUT = 15
_MAX_DAYS_AHEAD = 2

_WEEKDAYS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
# Representative hour (wttr.in "time" field) for each part of the day.
_PERIODS = [("Madrugada", "300"), ("Manhã", "900"), ("Tarde", "1500"), ("Noite", "2100")]


def _desc(entry: dict) -> str:
    """Portuguese description when available, else the English one."""
    for key in ("lang_pt", "weatherDesc"):
        values = entry.get(key) or []
        if values and values[0].get("value"):
            return values[0]["value"].strip()
    return ""


def _wind_dir(point: str) -> str:
    """16-point compass in Portuguese letters (E→L, W→O)."""
    return (point or "").replace("E", "L").replace("W", "O")


def _time_24h(text: str) -> str:
    """'05:15 AM' → '05:15'; anything unparsable is returned as is."""
    try:
        return datetime.strptime(text.strip(), "%I:%M %p").strftime("%H:%M")
    except (ValueError, AttributeError):
        return text or "?"


def _day_label(day_iso: str, days_ahead: int) -> str:
    try:
        d = date.fromisoformat(day_iso)
    except (TypeError, ValueError):
        return day_iso or "?"
    name = ["Hoje", "Amanhã", "Depois de amanhã"][days_ahead]
    return f"{name} ({_WEEKDAYS[d.weekday()]}, {d:%d/%m})"


def _location_label(data: dict, fallback: str) -> str:
    try:
        area = data["nearest_area"][0]
        parts = [area["areaName"][0]["value"], area["region"][0]["value"], area["country"][0]["value"]]
        return ", ".join(p for p in parts if p)
    except (KeyError, IndexError, TypeError):
        return fallback


def _current_block(current: dict) -> list:
    return [
        f"*Agora:* {_desc(current)}",
        f"🌡️ {current.get('temp_C', '?')}°C (sensação {current.get('FeelsLikeC', '?')}°C)",
        f"💧 Umidade {current.get('humidity', '?')}% · ☔ Chuva {current.get('precipMM', '?')} mm",
        f"💨 Vento {current.get('windspeedKmph', '?')} km/h {_wind_dir(current.get('winddir16Point', ''))}",
        f"☁️ Nuvens {current.get('cloudcover', '?')}% · 🔆 UV {current.get('uvIndex', '?')}",
    ]


def _day_block(day: dict, days_ahead: int) -> list:
    hourly = {h.get("time"): h for h in day.get("hourly") or []}
    rain_chance = max((int(h.get("chanceofrain") or 0) for h in hourly.values()), default=0)
    rain_mm = sum(float(h.get("precipMM") or 0) for h in hourly.values())
    lines = [
        f"*{_day_label(day.get('date'), days_ahead)}*",
        f"🌡️ Mín {day.get('mintempC', '?')}°C · Máx {day.get('maxtempC', '?')}°C",
        f"☔ Chance de chuva até {rain_chance}% · {rain_mm:.1f} mm previstos",
    ]
    for label, hour in _PERIODS:
        h = hourly.get(hour)
        if h:
            lines.append(
                f"• {label}: {h.get('tempC', '?')}°C, {_desc(h)} "
                f"(chuva {h.get('chanceofrain', '?')}%, vento {h.get('windspeedKmph', '?')} km/h)"
            )
    astronomy = (day.get("astronomy") or [{}])[0]
    lines.append(
        f"🌅 Nascer do sol {_time_24h(astronomy.get('sunrise'))} · "
        f"🌇 Pôr do sol {_time_24h(astronomy.get('sunset'))}"
    )
    return lines


def get_weather(city: str, days_ahead: int = 0) -> str:
    """Gets the weather for a city: current conditions (default) or the forecast for up to 2 days ahead.

    Args:
        city (str): City name, ideally with state/country to avoid ambiguity (e.g., 'Ubatuba, SP, Brazil', 'Lisbon, Portugal').
        days_ahead (int): 0 = today with current conditions (default), 1 = tomorrow, 2 = the day after tomorrow.

    Returns:
        str: A formatted weather report, or an error message.
    """
    city = (city or "").strip()
    if not city:
        return "Error: provide a city name, e.g. 'Ubatuba, SP, Brazil'."
    try:
        days_ahead = int(days_ahead)
    except (TypeError, ValueError):
        return "Error: days_ahead must be 0 (today), 1 (tomorrow) or 2 (the day after tomorrow)."
    if not 0 <= days_ahead <= _MAX_DAYS_AHEAD:
        return (
            f"Error: wttr.in only forecasts up to {_MAX_DAYS_AHEAD} days ahead "
            "(0 = today, 1 = tomorrow, 2 = the day after tomorrow)."
        )

    try:
        response = requests.get(_URL.format(location=quote(city)), timeout=_TIMEOUT)
    except requests.exceptions.RequestException as e:
        return f"Error fetching weather for '{city}': {e}"
    if response.status_code != 200 or "location not found" in response.text[:200].lower():
        if "location not found" in response.text[:200].lower():
            return f"Error: location '{city}' not found. Try adding the state or country."
        return f"Error fetching weather for '{city}': HTTP {response.status_code}"
    try:
        data = response.json()
        day = data["weather"][days_ahead]
    except (ValueError, KeyError, IndexError, TypeError):
        return f"Error: unexpected response from wttr.in for '{city}'."

    lines = [f"🌤️ *Clima em {_location_label(data, city)}*", ""]
    if days_ahead == 0:
        current = (data.get("current_condition") or [{}])[0]
        lines += _current_block(current) + [""]
    lines += _day_block(day, days_ahead)
    lines += ["", "Fonte: wttr.in"]
    return "\n".join(lines)

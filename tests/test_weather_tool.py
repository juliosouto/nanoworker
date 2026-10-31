"""Tests for tools/weather.py (wttr.in), with the HTTP call mocked."""

from unittest.mock import MagicMock, patch

import pytest

from tools import weather


def _hour(time, temp, desc, rain, wind=5, mm="0.2"):
    return {"time": time, "tempC": str(temp), "lang_pt": [{"value": desc}],
            "chanceofrain": str(rain), "windspeedKmph": str(wind), "precipMM": mm}


def _day(iso, low, high):
    return {
        "date": iso, "mintempC": str(low), "maxtempC": str(high),
        "astronomy": [{"sunrise": "05:15 AM", "sunset": "06:13 PM"}],
        "hourly": [
            _hour("300", 15, "Névoa", 20), _hour("900", 21, "Nublado", 10),
            _hour("1500", 23, "Chuva fraca", 60, mm="1.0"), _hour("2100", 17, "Céu limpo", 5),
        ],
    }


PAYLOAD = {
    "current_condition": [{
        "temp_C": "22", "FeelsLikeC": "24", "humidity": "74", "precipMM": "1.1",
        "windspeedKmph": "7", "winddir16Point": "SSW", "cloudcover": "86", "uvIndex": "6",
        "lang_pt": [{"value": "Chuva fraca"}], "weatherDesc": [{"value": "Light rain"}],
    }],
    "nearest_area": [{"areaName": [{"value": "Ubatuba"}], "region": [{"value": "Sao Paulo"}],
                      "country": [{"value": "Brazil"}]}],
    "weather": [_day("2026-10-31", 14, 23), _day("2026-11-01", 15, 25), _day("2026-11-02", 16, 27)],
}


def _response(status=200, payload=PAYLOAD, text="{}"):
    response = MagicMock(status_code=status, text=text)
    response.json.return_value = payload
    return response


def test_now_is_the_default():
    with patch.object(weather.requests, "get", return_value=_response()) as get:
        out = weather.get_weather("Ubatuba, SP, Brazil")
    assert "Ubatuba%2C%20SP%2C%20Brazil?format=j1&lang=pt" in get.call_args.args[0]
    assert "*Clima em Ubatuba, Sao Paulo, Brazil*" in out
    assert "*Agora:* Chuva fraca" in out
    assert "🌡️ 22°C (sensação 24°C)" in out
    assert "💨 Vento 7 km/h SSO" in out
    assert "*Hoje (sáb, 31/10)*" in out
    assert "🌡️ Mín 14°C · Máx 23°C" in out
    assert "☔ Chance de chuva até 60% · 1.6 mm previstos" in out
    assert "• Tarde: 23°C, Chuva fraca (chuva 60%, vento 5 km/h)" in out
    assert "🌅 Nascer do sol 05:15 · 🌇 Pôr do sol 18:13" in out


def test_other_days_have_no_current_block():
    with patch.object(weather.requests, "get", return_value=_response()):
        tomorrow = weather.get_weather("Ubatuba", 1)
        after = weather.get_weather("Ubatuba", "2")
    assert "*Amanhã (dom, 01/11)*" in tomorrow
    assert "Agora" not in tomorrow
    assert "*Depois de amanhã (seg, 02/11)*" in after
    assert "Máx 27°C" in after


@pytest.mark.parametrize("days", [-1, 3, "x"])
def test_invalid_days(days):
    with patch.object(weather.requests, "get") as get:
        assert weather.get_weather("Ubatuba", days).startswith("Error:")
    get.assert_not_called()


def test_empty_city():
    assert weather.get_weather("  ").startswith("Error: provide a city")


def test_location_not_found():
    with patch.object(weather.requests, "get",
                      return_value=_response(500, text="location not found: location not found")):
        assert "not found" in weather.get_weather("Nowhere123")


def test_network_error_and_bad_payload():
    with patch.object(weather.requests, "get",
                      side_effect=weather.requests.exceptions.ConnectionError("down")):
        assert weather.get_weather("Ubatuba").startswith("Error fetching weather")
    with patch.object(weather.requests, "get", return_value=_response(payload={"weather": []})):
        assert "unexpected response" in weather.get_weather("Ubatuba")


def test_tool_is_loaded_and_converts_for_langchain():
    import tools
    from agent.lc.tools_lc import build_lc_tools

    # The root tools/ directory is loaded on every OS; other tests replace
    # AVAILABLE_TOOLS, so run the loader on a fresh list.
    import os

    with patch.object(tools, "AVAILABLE_TOOLS", []):
        tools._load_tools_from_directory(os.path.dirname(tools.__file__), "tools")
        assert "get_weather" in {f.__name__ for f in tools.AVAILABLE_TOOLS}
    [lc_tool] = build_lc_tools([weather.get_weather])
    assert lc_tool.name == "get_weather"
    assert set(lc_tool.args) == {"city", "days_ahead"}

"""Kickoff wind/rain from Open-Meteo (free, keyless).  Only used for outdoor football totals."""
from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx


class Weather:
    def __init__(self, client: httpx.Client | None = None):
        self.http = client or httpx.Client(timeout=15)
        self._geo: dict = {}
        self._wx: dict = {}

    def _latlon(self, city: str, region: str | None):
        key = f"{city},{region}"
        if key not in self._geo:
            r = self.http.get("https://geocoding-api.open-meteo.com/v1/search",
                              params={"name": city, "count": 5, "country": "US"})
            res = r.json().get("results") or []
            pick = next((x for x in res if region and region.lower() in (x.get("admin1") or "").lower()), None)
            pick = pick or (res[0] if res else None)
            self._geo[key] = (pick["latitude"], pick["longitude"]) if pick else None
        return self._geo[key]

    def at(self, city: str | None, region: str | None, start_ts: float) -> dict | None:
        """{'wind_mph', 'precip_mm', 'temp_f'} at the kickoff hour, or None."""
        if not city or not start_ts:
            return None
        key = (city, region, int(start_ts // 3600))
        hit = self._wx.get(key)
        if hit and time.time() - hit[0] < 1800:
            return hit[1]
        try:
            ll = self._latlon(city, region)
            if not ll:
                return None
            r = self.http.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": ll[0], "longitude": ll[1], "hourly": "wind_speed_10m,precipitation,temperature_2m",
                "wind_speed_unit": "mph", "temperature_unit": "fahrenheit", "forecast_days": 7, "timezone": "UTC"})
            h = r.json()["hourly"]
            want = datetime.fromtimestamp(start_ts, timezone.utc).strftime("%Y-%m-%dT%H:00")
            i = h["time"].index(want)
            out = {"wind_mph": h["wind_speed_10m"][i], "precip_mm": h["precipitation"][i],
                   "temp_f": h["temperature_2m"][i]}
        except Exception:
            out = None
        self._wx[key] = (time.time(), out)
        return out

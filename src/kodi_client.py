import requests
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PlaybackState:
    playing: bool
    paused: bool
    position_ms: int
    total_ms: int
    speed: float


class KodiClient:
    def __init__(self, host: str, port: int, user: str, password: str):
        self.url = f"http://{host}:{port}/jsonrpc"
        self.auth = (user, password)
        self.headers = {"Content-Type": "application/json"}
        self._player_id: Optional[int] = None

    def _rpc(self, method: str, params: dict) -> Optional[dict]:
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        try:
            r = requests.post(self.url, json=payload, auth=self.auth,
                              headers=self.headers, timeout=2)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                logger.warning("Kodi RPC error: %s", data["error"])
                return None
            return data.get("result")
        except requests.RequestException as e:
            logger.error("Kodi connection error: %s", e)
            return None

    def get_active_player_id(self) -> Optional[int]:
        result = self._rpc("Player.GetActivePlayers", {})
        if result and len(result) > 0:
            return result[0]["playerid"]
        return None

    def get_playback_state(self) -> Optional[PlaybackState]:
        player_id = self._player_id or self.get_active_player_id()
        if player_id is None:
            return None
        self._player_id = player_id

        result = self._rpc("Player.GetProperties", {
            "playerid": player_id,
            "properties": ["time", "totaltime", "speed"]
        })
        if result is None:
            self._player_id = None
            return None

        t = result["time"]
        total = result["totaltime"]
        position_ms = (t["hours"] * 3600 + t["minutes"] * 60 + t["seconds"]) * 1000 + t["milliseconds"]
        total_ms = (total["hours"] * 3600 + total["minutes"] * 60 + total["seconds"]) * 1000 + total["milliseconds"]
        speed = result.get("speed", 0)

        return PlaybackState(
            playing=speed != 0,
            paused=speed == 0 and position_ms > 0,
            position_ms=position_ms,
            total_ms=total_ms,
            speed=float(speed),
        )

    def test_connection(self) -> bool:
        result = self._rpc("JSONRPC.Ping", {})
        return result == "pong"

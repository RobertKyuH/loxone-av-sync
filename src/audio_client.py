import requests
import logging

logger = logging.getLogger(__name__)


class AudioClient:
    """
    Client for Loxone AudioServer HTTP API.
    Endpoints verified against AudioServer firmware — update api_path in config if needed.
    """

    def __init__(self, host: str, port: int, api_path: str):
        self.base_url = f"http://{host}:{port}{api_path}"
        self.session = requests.Session()

    def play_file(self, filename: str, volume: int = 80) -> bool:
        """Play audio file on zone 0 (default). Adjust zone param as needed."""
        try:
            r = self.session.get(
                f"{self.base_url}/zone/0/volume/{volume}",
                timeout=3
            )
            r.raise_for_status()
            r2 = self.session.get(
                f"{self.base_url}/zone/0/play/{filename}",
                timeout=3
            )
            r2.raise_for_status()
            logger.info("Audio play: %s vol=%d", filename, volume)
            return True
        except requests.RequestException as e:
            logger.error("Audio error [%s]: %s", filename, e)
            return False

    def stop(self) -> bool:
        try:
            r = self.session.get(f"{self.base_url}/zone/0/stop", timeout=3)
            r.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error("Audio stop error: %s", e)
            return False

    def test_connection(self) -> bool:
        try:
            r = self.session.get(f"{self.base_url}/status", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

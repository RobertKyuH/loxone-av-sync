import requests
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class LoxoneClient:
    """
    Controls Loxone Miniserver via HTTP API using UUID-based commands.
    No Virtual Inputs configured — all controls addressed by UUID directly.

    Command format: GET /dev/sps/io/{uuid}/{command}

    Jalousie:  up, down, stop, shade, auto, position/{0-100}
    Light:     on, off, plus, minus, moodPlus, moodMinus, moveTo/{0-100}
    AudioZone: on, off, play, pause, stop, volume/{0-100}, volumeUp, volumeDown
    Switch:    on, off, pulse
    """

    def __init__(self, host: str, port: int, user: str, password: str):
        self.base_url = f"http://{host}:{port}/dev/sps/io"
        self.auth = (user, password)
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503])
        self.session.mount("http://", HTTPAdapter(max_retries=retry))

    def command(self, uuid: str, cmd: str) -> bool:
        url = f"{self.base_url}/{uuid}/{cmd}"
        try:
            r = self.session.get(url, auth=self.auth, timeout=3)
            r.raise_for_status()
            logger.info("Loxone OK: %s / %s", uuid[:8], cmd)
            return True
        except requests.RequestException as e:
            logger.error("Loxone error [%s / %s]: %s", uuid[:8], cmd, e)
            return False

    def test_connection(self) -> bool:
        try:
            r = self.session.get(
                self.base_url.replace("/dev/sps/io", "/jdev/sps/LoxAPPversion3"),
                auth=self.auth, timeout=3
            )
            return r.status_code == 200
        except Exception:
            return False

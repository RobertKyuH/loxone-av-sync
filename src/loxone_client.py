import requests
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class LoxoneClient:
    def __init__(self, host: str, port: int, user: str, password: str, api_path: str):
        self.base_url = f"http://{host}:{port}{api_path}"
        self.auth = (user, password)
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503])
        self.session.mount("http://", HTTPAdapter(max_retries=retry))

    def send_command(self, command: str, value) -> bool:
        url = f"{self.base_url}/{command}/{value}"
        try:
            r = self.session.get(url, auth=self.auth, timeout=3)
            r.raise_for_status()
            logger.info("Loxone OK: %s = %s", command, value)
            return True
        except requests.RequestException as e:
            logger.error("Loxone error [%s=%s]: %s", command, value, e)
            return False

    def activate_scene(self, scene_name: str) -> bool:
        return self.send_command(scene_name, 1)

    def test_connection(self) -> bool:
        try:
            url = f"http://{self.session.get_adapter('http://').max_retries}"
            r = self.session.get(
                self.base_url.replace("/dev/sps/io", "/jdev/sps/LoxAPPversion3"),
                auth=self.auth, timeout=3
            )
            return r.status_code == 200
        except Exception:
            return False

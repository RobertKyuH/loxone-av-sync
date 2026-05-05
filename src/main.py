import logging
import signal
import sys
import threading
import yaml
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from .kodi_client import KodiClient
from .loxone_client import LoxoneClient
from .audio_client import AudioClient
from .scheduler import EventScheduler
from .web.app import create_app


def load_config(path: str = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logging(cfg: dict):
    level = getattr(logging, cfg.get("level", "INFO").upper(), logging.INFO)
    log_file = cfg.get("file", "logs/av-sync.log")
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file),
        ],
    )


def start_media_server(movies_dir: str, port: int):
    """Dedicated HTTP server for movie streaming — supports range requests natively."""
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=movies_dir, **kwargs)
        def log_message(self, fmt, *args):
            pass  # silence access log

    server = HTTPServer(("0.0.0.0", port), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def main():
    cfg = load_config()
    setup_logging(cfg["logging"])
    logger = logging.getLogger("main")

    media_port = cfg.get("web", {}).get("media_port", 8888)
    rpi_host = cfg.get("rpi_host", "10.1.1.105")

    movies_dir = Path("movies")
    movies_dir.mkdir(exist_ok=True)

    media_srv = start_media_server(str(movies_dir.resolve()), media_port)
    logger.info("Media server started on port %d", media_port)

    kodi = KodiClient(
        host=cfg["kodi"]["host"],
        port=cfg["kodi"]["port"],
        user=cfg["kodi"]["user"],
        password=cfg["kodi"]["password"],
    )
    loxone = LoxoneClient(
        host=cfg["loxone"]["host"],
        port=cfg["loxone"]["port"],
        user=cfg["loxone"]["user"],
        password=cfg["loxone"]["password"],
    )
    audio = AudioClient(
        loxone=loxone,
        audio_zone_uuid=cfg["loxone"]["audio_zone_uuid"],
    )
    scheduler = EventScheduler(
        kodi=kodi,
        loxone=loxone,
        audio=audio,
        poll_interval_ms=cfg["kodi"]["poll_interval_ms"],
        pre_trigger_ms=cfg["timing"]["pre_trigger_ms"],
        tolerance_ms=cfg["timing"]["tolerance_ms"],
    )

    app = create_app(scheduler, kodi, loxone, audio, cfg, rpi_host, media_port)

    def shutdown(sig, frame):
        logger.info("Shutting down...")
        scheduler.stop()
        media_srv.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    scheduler.start()
    logger.info("loxone-av-sync started — panel: %d, media: %d", cfg["web"]["port"], media_port)

    app.run(
        host=cfg["web"]["host"],
        port=cfg["web"]["port"],
        debug=False,
        use_reloader=False,
        threaded=True,
    )


if __name__ == "__main__":
    main()

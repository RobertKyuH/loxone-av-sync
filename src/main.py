import logging
import signal
import sys
import yaml
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


def main():
    cfg = load_config()
    setup_logging(cfg["logging"])
    logger = logging.getLogger("main")

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
        api_path=cfg["loxone"]["api_path"],
    )
    audio = AudioClient(
        host=cfg["audio"]["host"],
        port=cfg["audio"]["port"],
        api_path=cfg["audio"]["api_path"],
    )
    scheduler = EventScheduler(
        kodi=kodi,
        loxone=loxone,
        audio=audio,
        poll_interval_ms=cfg["kodi"]["poll_interval_ms"],
        pre_trigger_ms=cfg["timing"]["pre_trigger_ms"],
        tolerance_ms=cfg["timing"]["tolerance_ms"],
    )

    app = create_app(scheduler, kodi, loxone, audio, cfg)

    def shutdown(sig, frame):
        logger.info("Shutting down...")
        scheduler.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    scheduler.start()
    logger.info("loxone-av-sync started")

    app.run(
        host=cfg["web"]["host"],
        port=cfg["web"]["port"],
        debug=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()

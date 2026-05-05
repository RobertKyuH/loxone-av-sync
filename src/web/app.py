import json
import logging
import time
from pathlib import Path
from flask import Flask, render_template, jsonify, request, abort, send_from_directory
from werkzeug.utils import secure_filename
from ..scheduler import EventScheduler
from ..scenario import load_scenario, list_scenarios, list_movies
from ..kodi_client import KodiClient
from ..loxone_client import LoxoneClient
from ..audio_client import AudioClient

logger = logging.getLogger(__name__)

MOVIE_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".m4v"}


def create_app(
    scheduler: EventScheduler,
    kodi: KodiClient,
    loxone: LoxoneClient,
    audio: AudioClient,
    cfg: dict,
    rpi_host: str = "10.1.1.105",
    media_port: int = 8888,
) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024 * 1024  # 8 GB

    scenarios_dir = Path("scenarios")
    movies_dir = Path("movies")
    movies_dir.mkdir(exist_ok=True)

    # rpi_host and media_port are passed in from main.py

    event_log: list = []

    def on_event(event):
        event_log.insert(0, {"id": event.id, "label": event.label, "time": event.time_str})
        if len(event_log) > 200:
            event_log.pop()

    scheduler.set_event_callback(on_event)

    # ── Static movie serving ──────────────────────────────────────────────────

    @app.route("/movies/<path:filename>")
    def serve_movie(filename):
        return send_from_directory(movies_dir.resolve(), filename)

    # ── Pages ─────────────────────────────────────────────────────────────────

    @app.route("/")
    def index():
        return render_template("index.html")

    # ── Scenarios API ─────────────────────────────────────────────────────────

    @app.route("/api/scenarios")
    def get_scenarios():
        return jsonify(list_scenarios(str(scenarios_dir)))

    @app.route("/api/scenarios/<filename>", methods=["GET"])
    def get_scenario(filename):
        path = scenarios_dir / secure_filename(filename)
        if not path.exists():
            abort(404)
        with open(path, encoding="utf-8") as f:
            return jsonify(json.load(f))

    @app.route("/api/scenarios/<filename>", methods=["DELETE"])
    def delete_scenario(filename):
        path = scenarios_dir / secure_filename(filename)
        if path.exists():
            path.unlink()
        return jsonify({"ok": True})

    @app.route("/api/upload/scenario", methods=["POST"])
    def upload_scenario():
        f = request.files.get("file")
        if not f or not f.filename.endswith(".json"):
            abort(400)
        name = secure_filename(f.filename)
        f.save(scenarios_dir / name)
        return jsonify({"ok": True, "filename": name})

    # ── Movies API ────────────────────────────────────────────────────────────

    @app.route("/api/movies")
    def get_movies():
        return jsonify(list_movies(str(movies_dir)))

    @app.route("/api/movies/<filename>", methods=["DELETE"])
    def delete_movie(filename):
        path = movies_dir / secure_filename(filename)
        if path.exists():
            path.unlink()
        return jsonify({"ok": True})

    @app.route("/api/upload/movie", methods=["POST"])
    def upload_movie():
        f = request.files.get("file")
        if not f:
            abort(400)
        name = secure_filename(f.filename)
        if Path(name).suffix.lower() not in MOVIE_EXTS:
            abort(400)
        dest = movies_dir / name
        f.save(dest)
        size_mb = dest.stat().st_size / 1024 / 1024
        return jsonify({"ok": True, "filename": name, "size_mb": round(size_mb, 1)})

    # ── Playback control ──────────────────────────────────────────────────────

    @app.route("/api/launch/<scenario_filename>", methods=["POST"])
    def launch(scenario_filename):
        """Load scenario + start Kodi playback + arm scheduler."""
        path = scenarios_dir / secure_filename(scenario_filename)
        if not path.exists():
            abort(404)

        scenario = load_scenario(str(path))

        # Stop previous playback and wait for Kodi to finish stopping
        scheduler.stop()
        kodi.stop()
        time.sleep(0.8)

        # Start Kodi with the linked movie
        if scenario.movie:
            movie_url = f"http://{rpi_host}:{media_port}/{scenario.movie}"
            ok = kodi.open_file(movie_url)
            if not ok:
                return jsonify({"ok": False, "error": "Kodi failed to open file"}), 502

        scheduler.set_scenario(scenario)
        scheduler.reset()
        scheduler.start()

        return jsonify({
            "ok": True,
            "title": scenario.title,
            "movie": scenario.movie,
            "events": len(scenario.events),
        })

    @app.route("/api/control/<action>", methods=["POST"])
    def control(action):
        if action == "start":
            scheduler.start()
        elif action == "stop":
            scheduler.stop()
            kodi.stop()
        elif action == "reset":
            scheduler.reset()
        else:
            abort(400)
        return jsonify({"ok": True})

    # ── Status & logs ─────────────────────────────────────────────────────────

    @app.route("/api/status")
    def status():
        state = scheduler.last_state
        active = scheduler._scenario
        upcoming = []
        if active and state:
            pos = state.position_ms
            upcoming = [
                {"id": e.id, "label": e.label, "time": e.time_str, "ms": e.time_ms}
                for e in active.events
                if e.id not in scheduler._executed_ids and e.time_ms >= pos
            ][:5]
        return jsonify({
            "running": scheduler._running,
            "scenario": {"title": active.title, "movie": active.movie, "filename": active.filename} if active else None,
            "playback": {
                "playing": state.playing,
                "paused": state.paused,
                "position_ms": state.position_ms,
                "total_ms": state.total_ms,
            } if state else None,
            "upcoming": upcoming,
        })

    @app.route("/api/logs")
    def logs():
        return jsonify(event_log)

    @app.route("/api/connections")
    def connections():
        return jsonify({
            "kodi": kodi.test_connection(),
            "loxone": loxone.test_connection(),
            "audio": audio.test_connection(),
        })

    return app

import json
import logging
import subprocess
import tempfile
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

    firestick_ip = cfg.get("kodi", {}).get("host", "10.1.1.240")

    # Track currently armed scenario for remote-play endpoint
    _state: dict = {"current_filename": None}

    event_log: list = []

    def on_event(event):
        event_log.insert(0, {"id": event.id, "label": event.label, "time": event.time_str})
        if len(event_log) > 200:
            event_log.pop()

    scheduler.set_event_callback(on_event)

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
        # Allow image files for splash screen too
        if Path(name).suffix.lower() not in MOVIE_EXTS | {".jpg", ".jpeg", ".png"}:
            abort(400)
        dest = movies_dir / name
        f.save(dest)
        size_mb = dest.stat().st_size / 1024 / 1024
        return jsonify({"ok": True, "filename": name, "size_mb": round(size_mb, 1)})

    # ── Playback control ──────────────────────────────────────────────────────

    def _do_launch(scenario_filename: str):
        path = scenarios_dir / secure_filename(scenario_filename)
        if not path.exists():
            return None, "Scenariusz nie istnieje"

        scenario = load_scenario(str(path))

        scheduler.stop()
        kodi.stop()
        time.sleep(0.8)

        if scenario.movie:
            movie_url = f"http://{rpi_host}:{media_port}/{scenario.movie}"
            ok = kodi.open_file(movie_url)
            if not ok:
                return None, "Kodi nie mógł otworzyć pliku"

        scheduler.set_scenario(scenario)
        scheduler.reset()
        scheduler.start()

        _state["current_filename"] = scenario_filename
        return scenario, None

    @app.route("/api/launch/<scenario_filename>", methods=["POST"])
    def launch(scenario_filename):
        scenario, err = _do_launch(scenario_filename)
        if err:
            return jsonify({"ok": False, "error": err}), 502
        return jsonify({
            "ok": True,
            "title": scenario.title,
            "movie": scenario.movie,
            "events": len(scenario.events),
        })

    @app.route("/api/launch-current", methods=["POST"])
    def launch_current():
        """Re-launch the currently selected scenario — called by Kodi remote keymap."""
        fn = _state.get("current_filename")
        if not fn:
            return jsonify({"ok": False, "error": "Brak wybranego scenariusza"}), 400
        scenario, err = _do_launch(fn)
        if err:
            return jsonify({"ok": False, "error": err}), 502
        return jsonify({"ok": True, "title": scenario.title})

    @app.route("/api/control/<action>", methods=["POST"])
    def control(action):
        if action == "stop":
            scheduler.stop()
            kodi.stop()
            time.sleep(0.3)
            _kodi_go_home()
        elif action == "reset":
            scheduler.reset()
        else:
            abort(400)
        return jsonify({"ok": True})

    # ── Kodi helpers ──────────────────────────────────────────────────────────

    def _kodi_go_home():
        kodi._rpc("GUI.ActivateWindow", {"window": "home"})

    def _kodi_show_splash():
        splash = movies_dir / "splash.png"
        if splash.exists():
            url = f"http://{rpi_host}:{media_port}/splash.png"
            kodi._rpc("Player.Open", {"item": {"file": url}})
        else:
            _kodi_go_home()

    @app.route("/api/kodi/splash", methods=["POST"])
    def kodi_splash():
        _kodi_show_splash()
        return jsonify({"ok": True})

    @app.route("/api/kodi/home", methods=["POST"])
    def kodi_home():
        _kodi_go_home()
        return jsonify({"ok": True})

    @app.route("/api/kodi/deploy", methods=["POST"])
    def kodi_deploy():
        """Deploy remote-play keymap + Python script to Firestick via ADB."""
        keymap_xml = (
            '<keymap>\n'
            '  <home>\n'
            '    <remote>\n'
            '      <play>RunScript(special://userdata/scripts/av_launch.py)</play>\n'
            '    </remote>\n'
            '  </home>\n'
            '  <picturewindow>\n'
            '    <remote>\n'
            '      <play>RunScript(special://userdata/scripts/av_launch.py)</play>\n'
            '    </remote>\n'
            '  </picturewindow>\n'
            '</keymap>\n'
        )
        launch_script = (
            "import urllib.request\n"
            "try:\n"
            f"    urllib.request.urlopen('http://{rpi_host}:5000/api/launch-current', timeout=5)\n"
            "except Exception:\n"
            "    pass\n"
        )

        kodi_data = "/sdcard/Android/data/org.xbmc.kodi/files/.kodi"

        def adb(*args):
            cmd = ["adb", "-s", f"{firestick_ip}:5555"] + list(args)
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            logger.info("ADB %s → %s", " ".join(args[:2]), r.stdout.strip() or r.stderr.strip())
            return r

        try:
            adb("connect", f"{firestick_ip}:5555")

            with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as f:
                f.write(keymap_xml)
                keymap_path = f.name
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
                f.write(launch_script)
                script_path = f.name

            adb("shell", f"mkdir -p {kodi_data}/userdata/keymaps {kodi_data}/userdata/scripts")
            r1 = adb("push", keymap_path, f"{kodi_data}/userdata/keymaps/av_demo.xml")
            r2 = adb("push", script_path, f"{kodi_data}/userdata/scripts/av_launch.py")

            # Reload Kodi's keymaps without full restart
            kodi._rpc("Application.Quit", {})
            time.sleep(2)
            adb("shell", "monkey -p org.xbmc.kodi -c android.intent.category.LAUNCHER 1")

            return jsonify({
                "ok": True,
                "keymap": r1.returncode == 0,
                "script": r2.returncode == 0,
                "note": "Kodi restarted to load keymap",
            })
        except FileNotFoundError:
            return jsonify({"ok": False, "error": "adb nie jest zainstalowane na RPi3 — zainstaluj: sudo apt-get install -y adb"}), 500
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

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
            "current_filename": _state.get("current_filename"),
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

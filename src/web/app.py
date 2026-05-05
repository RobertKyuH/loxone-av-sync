import json
import logging
import subprocess
import tempfile
import time
from pathlib import Path
from flask import Flask, render_template, jsonify, request, abort
from werkzeug.utils import secure_filename
from ..scheduler import EventScheduler
from ..scenario import load_scenario, list_scenarios
from ..kodi_client import KodiClient
from ..loxone_client import LoxoneClient
from ..audio_client import AudioClient

logger = logging.getLogger(__name__)

FIRESTICK_MOVIES_DIR = "/storage/emulated/0/Movies"
STAGING_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".m4v"}


def create_app(
    scheduler: EventScheduler,
    kodi: KodiClient,
    loxone: LoxoneClient,
    audio: AudioClient,
    cfg: dict,
) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024 * 1024  # 8 GB

    scenarios_dir = Path("scenarios")
    staging_dir = Path("staging")   # temp upload area before ADB push
    staging_dir.mkdir(exist_ok=True)

    firestick_ip = cfg.get("kodi", {}).get("host", "10.1.1.240")

    # Currently armed scenario filename (for remote-play endpoint)
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

    # ── Firestick file browser ─────────────────────────────────────────────────

    @app.route("/api/firestick/files")
    def firestick_files():
        """List video files visible to Kodi on Firestick."""
        directory = request.args.get("path", FIRESTICK_MOVIES_DIR)
        try:
            result = kodi._rpc("Files.GetDirectory", {
                "directory": directory,
                "media": "video",
                "properties": ["size", "file"],
            })
            if result is None:
                return jsonify({"ok": False, "error": "Kodi nie odpowiada lub katalog niedostępny"})
            files = [
                {
                    "path": f["file"],
                    "label": f["label"],
                    "is_dir": f["filetype"] == "directory",
                    "size_mb": round(f.get("size", 0) / 1024 / 1024, 1),
                }
                for f in result.get("files", [])
            ]
            return jsonify({"ok": True, "path": directory, "files": files})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── ADB push film to Firestick ─────────────────────────────────────────────

    @app.route("/api/upload/movie", methods=["POST"])
    def upload_and_push():
        """Upload film to staging, then ADB-push to Firestick, then delete staging copy."""
        f = request.files.get("file")
        if not f:
            abort(400)
        name = secure_filename(f.filename)
        if Path(name).suffix.lower() not in STAGING_EXTS:
            abort(400)

        staging_path = staging_dir / name
        f.save(staging_path)

        try:
            _adb_connect(firestick_ip)
            dest = f"{FIRESTICK_MOVIES_DIR}/{name}"
            r = subprocess.run(
                ["adb", "-s", f"{firestick_ip}:5555", "push", str(staging_path), dest],
                capture_output=True, text=True, timeout=600,
            )
            staging_path.unlink(missing_ok=True)

            if r.returncode != 0:
                return jsonify({"ok": False, "error": r.stderr.strip()}), 502

            # Refresh Kodi media library
            kodi._rpc("VideoLibrary.Scan", {})

            return jsonify({"ok": True, "path": dest, "filename": name})
        except FileNotFoundError:
            staging_path.unlink(missing_ok=True)
            return jsonify({"ok": False, "error": "adb nie zainstalowane: sudo apt-get install -y adb"}), 500
        except Exception as e:
            staging_path.unlink(missing_ok=True)
            return jsonify({"ok": False, "error": str(e)}), 500

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
            # movie field = full local path on Firestick
            ok = kodi.open_file(scenario.movie)
            if not ok:
                return None, "Kodi nie mógł otworzyć pliku — sprawdź ścieżkę w scenariuszu"

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
        """Re-launch current scenario — called by Firestick remote keymap."""
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
            audio.stop()          # stop AudioServer via Loxone
            loxone.command(cfg["loxone"]["light_uuid"], "off")   # lights off
            loxone.command(cfg["loxone"]["jalousie_uuid"], "auto")  # blinds auto
            time.sleep(0.3)
            kodi._rpc("GUI.ActivateWindow", {"window": "home"})
        elif action == "reset":
            fn = _state.get("current_filename")
            if fn:
                _do_launch(fn)   # full restart: stop → open film → re-arm events
            else:
                scheduler.reset()
        else:
            abort(400)
        return jsonify({"ok": True})

    # ── Kodi helpers ──────────────────────────────────────────────────────────

    @app.route("/api/kodi/home", methods=["POST"])
    def kodi_home():
        kodi._rpc("GUI.ActivateWindow", {"window": "home"})
        return jsonify({"ok": True})

    @app.route("/api/kodi/deploy", methods=["POST"])
    def kodi_deploy():
        """Deploy remote-play keymap + script to Firestick via ADB."""
        rpi_port = cfg.get("web", {}).get("port", 5000)
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
        rpi_host = cfg.get("rpi_host", "10.1.1.105")
        launch_script = (
            "import urllib.request\n"
            "try:\n"
            f"    urllib.request.urlopen('http://{rpi_host}:{rpi_port}/api/launch-current', timeout=5)\n"
            "except Exception:\n"
            "    pass\n"
        )

        kodi_data = "/sdcard/Android/data/org.xbmc.kodi/files/.kodi"

        try:
            _adb_connect(firestick_ip)

            with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as f:
                f.write(keymap_xml)
                keymap_path = f.name
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
                f.write(launch_script)
                script_path = f.name

            _adb("shell", f"mkdir -p {kodi_data}/userdata/keymaps {kodi_data}/userdata/scripts",
                 firestick_ip)
            r1 = _adb("push", keymap_path,
                      f"{kodi_data}/userdata/keymaps/av_demo.xml", firestick_ip)
            r2 = _adb("push", script_path,
                      f"{kodi_data}/userdata/scripts/av_launch.py", firestick_ip)

            # Restart Kodi to load keymap
            kodi._rpc("Application.Quit", {})
            time.sleep(2)
            _adb("shell", "monkey -p org.xbmc.kodi -c android.intent.category.LAUNCHER 1",
                 firestick_ip)

            return jsonify({
                "ok": True,
                "keymap": r1.returncode == 0,
                "script": r2.returncode == 0,
            })
        except FileNotFoundError:
            return jsonify({"ok": False, "error": "adb nie zainstalowane: sudo apt-get install -y adb"}), 500
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
            "scenario": {
                "title": active.title,
                "movie": active.movie,
                "filename": active.filename,
            } if active else None,
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


# ── ADB helpers ────────────────────────────────────────────────────────────────

def _adb_connect(ip: str):
    subprocess.run(["adb", "connect", f"{ip}:5555"],
                   capture_output=True, timeout=10)

def _adb(*args, firestick_ip: str) -> subprocess.CompletedProcess:
    cmd = ["adb", "-s", f"{firestick_ip}:5555"] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    logger.info("ADB %s → rc=%d", " ".join(str(a) for a in args[:2]), r.returncode)
    return r

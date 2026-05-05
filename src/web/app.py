import json
import logging
from pathlib import Path
from flask import Flask, render_template, jsonify, request, abort
from ..scheduler import EventScheduler
from ..scenario import load_scenario, list_scenarios
from ..kodi_client import KodiClient
from ..loxone_client import LoxoneClient
from ..audio_client import AudioClient

logger = logging.getLogger(__name__)


def create_app(
    scheduler: EventScheduler,
    kodi: KodiClient,
    loxone: LoxoneClient,
    audio: AudioClient,
    cfg: dict,
) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    scenarios_dir = Path("scenarios")
    event_log: list = []

    def on_event(event):
        event_log.insert(0, {
            "id": event.id,
            "label": event.label,
            "time": event.time_str,
        })
        if len(event_log) > 200:
            event_log.pop()

    scheduler.set_event_callback(on_event)

    @app.route("/")
    def index():
        return render_template("index.html")

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
            "scenario": active.title if active else None,
            "playback": {
                "playing": state.playing if state else False,
                "paused": state.paused if state else False,
                "position_ms": state.position_ms if state else 0,
                "total_ms": state.total_ms if state else 0,
            } if state else None,
            "upcoming": upcoming,
        })

    @app.route("/api/scenarios")
    def get_scenarios():
        return jsonify(list_scenarios(str(scenarios_dir)))

    @app.route("/api/scenarios/<filename>", methods=["GET"])
    def get_scenario(filename: str):
        path = scenarios_dir / filename
        if not path.exists() or not filename.endswith(".json"):
            abort(404)
        with open(path, encoding="utf-8") as f:
            return jsonify(json.load(f))

    @app.route("/api/scenarios/<filename>", methods=["PUT"])
    def save_scenario(filename: str):
        if not filename.endswith(".json"):
            abort(400)
        data = request.get_json(force=True)
        path = scenarios_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return jsonify({"ok": True})

    @app.route("/api/load/<filename>", methods=["POST"])
    def load(filename: str):
        path = scenarios_dir / filename
        if not path.exists():
            abort(404)
        scenario = load_scenario(str(path))
        scheduler.set_scenario(scenario)
        return jsonify({"ok": True, "title": scenario.title, "events": len(scenario.events)})

    @app.route("/api/control/<action>", methods=["POST"])
    def control(action: str):
        if action == "start":
            scheduler.start()
        elif action == "stop":
            scheduler.stop()
        elif action == "reset":
            scheduler.reset()
        else:
            abort(400)
        return jsonify({"ok": True})

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

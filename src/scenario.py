import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Action:
    type: str
    uuid: str = ""
    cmd: str = ""


@dataclass
class Event:
    id: str
    time_str: str
    label: str
    actions: List[Action] = field(default_factory=list)
    time_ms: int = 0

    def __post_init__(self):
        self.time_ms = _parse_time(self.time_str)


def _parse_time(time_str: str) -> int:
    parts = time_str.split(":")
    if len(parts) == 3:
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
    elif len(parts) == 2:
        h, m, s = 0, int(parts[0]), int(parts[1])
    else:
        raise ValueError(f"Invalid time format: {time_str}")
    return (h * 3600 + m * 60 + s) * 1000


@dataclass
class Scenario:
    title: str
    description: str
    version: str
    movie: str                          # filename in movies/ directory
    events: List[Event] = field(default_factory=list)
    filename: str = ""


def load_scenario(path: str) -> Scenario:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    events = []
    for e in data.get("events", []):
        actions = [Action(**a) for a in e.get("actions", [])]
        events.append(Event(
            id=e["id"],
            time_str=e["time"],
            label=e["label"],
            actions=actions,
        ))
    events.sort(key=lambda ev: ev.time_ms)

    return Scenario(
        title=data["title"],
        description=data.get("description", ""),
        version=data.get("version", "1.0"),
        movie=data.get("movie", ""),
        events=events,
        filename=Path(path).name,
    )


def list_scenarios(directory: str) -> List[dict]:
    result = []
    for p in Path(directory).glob("*.json"):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            result.append({
                "filename": p.name,
                "title": data.get("title", p.stem),
                "description": data.get("description", ""),
                "movie": data.get("movie", ""),
                "events": len(data.get("events", [])),
            })
        except Exception as e:
            logger.warning("Cannot read scenario %s: %s", p.name, e)
    result.sort(key=lambda x: x["title"])
    return result


def list_movies(directory: str) -> List[str]:
    exts = {".mp4", ".mkv", ".avi", ".mov", ".m4v"}
    return sorted(
        p.name for p in Path(directory).iterdir()
        if p.suffix.lower() in exts
    )

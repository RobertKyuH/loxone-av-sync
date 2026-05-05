#!/usr/bin/env python3
"""
av-analyzer — extracts frames from a movie and generates a Loxone scenario JSON
using Claude vision API.

Usage:
    python analyze.py <movie_file> [--output scenarios/name.json]
"""

import anthropic
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

LOXONE_DEVICES = """
Available Loxone devices (Miniserver "DET"):

1. LightControllerV2 — "Sterownik oświetlenia"
   uuid: 202a29e1-02cc-745e-ffff0a0fb1695586
   commands: on, off, moodPlus, moodMinus, moveTo/0..100

2. Jalousie — "Automatyczne zacienianie" (roller blinds)
   uuid: 202a2a0e-03bb-7c3a-ffff0a0fb1695586
   commands: up, down, stop, shade, auto, position/0..100

3. AudioZoneV2 — "Odtwarzacz Audio"
   type: audio (goes through Loxone, not direct)
   uuid: 202a2ae5-0272-a407-ffff0a0fb1695586
   commands: on, off, play, pause, stop, volume/0..100, volumeUp, volumeDown

4. Switch — "LED obecnosc OFF"
   uuid: 20498c76-00b3-cc55-ffff0a0fb1695586
   commands: on, off, pulse
"""

SYSTEM_PROMPT = f"""You are an expert in building automation and cinematic experiences.
You analyze video frames and create Loxone smart home event scenarios that synchronize
lighting, blinds, and audio with scenes in a movie.

{LOXONE_DEVICES}

Rules:
- Create events that ENHANCE the viewing experience — match mood, not distract
- Space events at least 10 seconds apart unless dramatically important
- For restaurants/interiors: use lighting moods for atmosphere
- Return ONLY valid JSON, no explanation outside the JSON
- Action type is "loxone" or "audio"
- For "audio" actions: uuid field can be empty string ""
- Times in HH:MM:SS format
"""

USER_PROMPT = """Analyze these video frames (shown in chronological order with timestamps).
Create a Loxone automation scenario JSON that synchronizes smart home actions with the film.

Return ONLY this JSON structure:
{{
  "title": "<descriptive Polish title>",
  "description": "<1-2 sentences in Polish describing what the scenario does>",
  "movie": "{movie_filename}",
  "version": "1.0",
  "events": [
    {{
      "id": "evt_001",
      "time": "HH:MM:SS",
      "label": "<Polish label>",
      "actions": [
        {{"type": "loxone", "uuid": "<uuid>", "cmd": "<command>"}},
        ...
      ]
    }},
    ...
  ]
}}

Movie duration: {duration_str}
Aim for 8-15 events spread across the film. Make the experience dramatic and immersive.
"""


def get_duration(movie_path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", movie_path],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())


def extract_frames(movie_path: str, out_dir: str, count: int = 12) -> list[tuple[float, str]]:
    duration = get_duration(movie_path)
    # skip first 3s and last 3s
    timestamps = [3 + (duration - 6) * i / (count - 1) for i in range(count)]
    frames = []
    for ts in timestamps:
        out = os.path.join(out_dir, f"frame_{ts:.1f}s.jpg")
        subprocess.run(
            ["ffmpeg", "-ss", str(ts), "-i", movie_path,
             "-vframes", "1", "-q:v", "4", "-vf", "scale=800:-1", out, "-y"],
            capture_output=True
        )
        if os.path.exists(out):
            frames.append((ts, out))
    return frames


def seconds_to_hms(s: float) -> str:
    s = int(s)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"


def analyze(movie_path: str, output_path: str | None = None):
    movie_path = Path(movie_path)
    movie_filename = movie_path.name

    print(f"Analizuję: {movie_filename}")
    duration = get_duration(str(movie_path))
    duration_str = f"{seconds_to_hms(duration)} ({duration:.0f}s)"
    print(f"Czas trwania: {duration_str}")

    with tempfile.TemporaryDirectory() as tmpdir:
        print("Wyciągam klatki...")
        frames = extract_frames(str(movie_path), tmpdir)
        print(f"  {len(frames)} klatek")

        # Build message content
        content = []
        for ts, path in frames:
            with open(path, "rb") as f:
                img_b64 = base64.standard_b64encode(f.read()).decode()
            content.append({
                "type": "text",
                "text": f"Frame at {seconds_to_hms(ts)} ({ts:.0f}s):"
            })
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}
            })

        content.append({
            "type": "text",
            "text": USER_PROMPT.format(
                movie_filename=movie_filename,
                duration_str=duration_str
            )
        })

        print("Wysyłam do Claude API...")
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}]
        )

    raw = response.content[0].text.strip()

    # Extract JSON if wrapped in code block
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
    json_str = m.group(1) if m else raw

    scenario = json.loads(json_str)

    if output_path is None:
        stem = movie_path.stem.lower().replace(" ", "_")
        output_path = Path("scenarios") / f"{stem}.json"

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(scenario, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Scenariusz zapisany: {output_path}")
    print(f"  Tytuł: {scenario['title']}")
    print(f"  Zdarzeń: {len(scenario['events'])}")
    for ev in scenario["events"]:
        print(f"  [{ev['time']}] {ev['label']} ({len(ev['actions'])} akcji)")

    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <movie_file> [output.json]")
        sys.exit(1)

    movie = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) > 2 else None
    analyze(movie, output)

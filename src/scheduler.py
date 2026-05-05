import logging
import threading
import time
from typing import Optional, Callable
from .scenario import Scenario, Event, Action
from .kodi_client import KodiClient, PlaybackState
from .loxone_client import LoxoneClient
from .audio_client import AudioClient

logger = logging.getLogger(__name__)


class EventScheduler:
    def __init__(
        self,
        kodi: KodiClient,
        loxone: LoxoneClient,
        audio: AudioClient,
        poll_interval_ms: int = 500,
        pre_trigger_ms: int = 200,
        tolerance_ms: int = 500,
    ):
        self.kodi = kodi
        self.loxone = loxone
        self.audio = audio
        self.poll_interval_ms = poll_interval_ms
        self.pre_trigger_ms = pre_trigger_ms
        self.tolerance_ms = tolerance_ms

        self._scenario: Optional[Scenario] = None
        self._executed_ids: set = set()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._on_event: Optional[Callable] = None
        self.last_state: Optional[PlaybackState] = None

    def set_scenario(self, scenario: Scenario):
        self._scenario = scenario
        self._executed_ids.clear()
        logger.info("Scenario loaded: %s (%d events)", scenario.title, len(scenario.events))

    def set_event_callback(self, callback: Callable):
        self._on_event = callback

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Scheduler started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("Scheduler stopped")

    def reset(self):
        self._executed_ids.clear()
        logger.info("Scheduler reset — events re-armed")

    def _loop(self):
        while self._running:
            try:
                state = self.kodi.get_playback_state()
                self.last_state = state

                if state and state.playing and self._scenario:
                    effective_pos = state.position_ms + self.pre_trigger_ms
                    self._check_events(effective_pos)

            except Exception as e:
                logger.error("Scheduler loop error: %s", e)

            time.sleep(self.poll_interval_ms / 1000)

    def _check_events(self, position_ms: int):
        for event in self._scenario.events:
            if event.id in self._executed_ids:
                continue
            delta = position_ms - event.time_ms
            if 0 <= delta <= self.tolerance_ms:
                logger.info("Triggering event [%s] %s at pos %dms", event.id, event.label, position_ms)
                self._execute_event(event)
                self._executed_ids.add(event.id)

    def _execute_event(self, event: Event):
        for action in event.actions:
            self._execute_action(action)
        if self._on_event:
            self._on_event(event)

    def _execute_action(self, action: Action):
        if action.type == "loxone":
            self.loxone.send_command(action.command, action.value)
        elif action.type == "loxone_scene":
            self.loxone.activate_scene(action.scene_name)
        elif action.type == "audio":
            if action.command == "play":
                self.audio.play_file(action.file, action.volume)
            elif action.command == "stop":
                self.audio.stop()
        else:
            logger.warning("Unknown action type: %s", action.type)

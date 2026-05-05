from .loxone_client import LoxoneClient
import logging

logger = logging.getLogger(__name__)

# AudioServer is paired with Loxone Miniserver — direct HTTP commands are blocked.
# All audio control goes through Loxone AudioZoneV2 UUID.


class AudioClient:
    def __init__(self, loxone: LoxoneClient, audio_zone_uuid: str):
        self.loxone = loxone
        self.uuid = audio_zone_uuid

    def play(self) -> bool:
        return self.loxone.command(self.uuid, "play")

    def pause(self) -> bool:
        return self.loxone.command(self.uuid, "pause")

    def stop(self) -> bool:
        return self.loxone.command(self.uuid, "stop")

    def set_volume(self, volume: int) -> bool:
        vol = max(0, min(100, int(volume)))
        return self.loxone.command(self.uuid, f"volume/{vol}")

    def power_on(self) -> bool:
        return self.loxone.command(self.uuid, "on")

    def power_off(self) -> bool:
        return self.loxone.command(self.uuid, "off")

    def test_connection(self) -> bool:
        return self.loxone.test_connection()

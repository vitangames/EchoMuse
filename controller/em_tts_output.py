"""Helpers for routing Assist TTS to a Home Assistant media player.

This module is deliberately dependency-free. The controller, API and tests
all use the same validation rules, while the ESPHome transport remains the
only place that knows how to put the resulting service call on the wire.
"""

from __future__ import annotations

import re


CONFIG_KEY = "tts_output_media_player"

_MEDIA_PLAYER_ENTITY = re.compile(r"^media_player\.[a-z0-9_]+$")


def normalise_entity_id(value) -> str:
    """Return a canonical media_player entity id, or raise ValueError.

    An empty value disables redirection and preserves the built-in Echo Dot
    speaker path. Rejecting every other domain keeps this setting from
    becoming an arbitrary Home Assistant service-call primitive.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{CONFIG_KEY} must be a string")
    entity_id = value.strip().lower()
    if not entity_id:
        return ""
    if not _MEDIA_PLAYER_ENTITY.fullmatch(entity_id):
        raise ValueError(
            f"{CONFIG_KEY} must be empty or a media_player entity id "
            f"(for example media_player.living_room)"
        )
    return entity_id


def play_media_data(entity_id: str, media_url: str) -> dict[str, str]:
    """Build the string map carried by ESPHome HomeassistantActionRequest."""
    target = normalise_entity_id(entity_id)
    if not target:
        raise ValueError(f"{CONFIG_KEY} is empty")
    if not isinstance(media_url, str) or not media_url.strip():
        raise ValueError("TTS media URL is empty")
    return {
        "entity_id": target,
        "media_content_id": media_url.strip(),
        "media_content_type": "music",
        # Announcement-capable players temporarily interrupt and then resume
        # existing media. HA's schema coerces this ESPHome string-map value.
        "announce": "true",
    }

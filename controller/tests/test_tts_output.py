"""Optional Home Assistant media-player routing for Assist replies."""

from pathlib import Path

import pytest

import em_tts_output as tts


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, ""),
        ("", ""),
        ("   ", ""),
        (" MEDIA_PLAYER.Living_Room ", "media_player.living_room"),
    ],
)
def test_entity_id_normalisation(raw, expected):
    assert tts.normalise_entity_id(raw) == expected


@pytest.mark.parametrize(
    "bad",
    [42, True, "speaker.kitchen", "media_player.", "media_player.bad-name"],
)
def test_only_media_player_entities_are_accepted(bad):
    with pytest.raises(ValueError):
        tts.normalise_entity_id(bad)


def test_service_payload_is_an_announcement_for_one_target():
    data = tts.play_media_data(
        "media_player.kitchen", "http://ha.local:8123/api/tts_proxy/reply.flac"
    )
    assert data == {
        "entity_id": "media_player.kitchen",
        "media_content_id": "http://ha.local:8123/api/tts_proxy/reply.flac",
        "media_content_type": "music",
        "announce": "true",
    }


def test_empty_target_cannot_dispatch():
    with pytest.raises(ValueError):
        tts.play_media_data("", "http://ha.local/reply.flac")


def test_voice_turn_has_an_exclusive_redirect_branch():
    """Configured output must not fall through to the Dot speaker decoder."""
    src = (ROOT / "em_esphome.py").read_text()
    branch = src.index("if self._tts_audio_url and tts_output_media_player:")
    builtin = src.index("if self._tts_audio_url:", branch + 1)
    redirect = src[branch:builtin]
    assert "_dispatch_tts_to_media_player" in redirect
    assert "return" in redirect
    assert "_stream_tts_audio" not in redirect


def test_controller_passes_device_route_into_every_voice_turn():
    src = (ROOT / "em_controller.py").read_text()
    assert "tts_output_media_player=device.tts_output_media_player" in src


def test_addon_does_not_gain_broad_home_assistant_api_permission():
    config = (ROOT / "config.yaml").read_text()
    assert "homeassistant_api:" not in config

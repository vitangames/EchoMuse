"""Deployment guards specific to the vitangames custom GA add-on."""

from pathlib import Path

import yaml


CONTROLLER = Path(__file__).resolve().parents[1]
REPO = CONTROLLER.parent


def test_custom_ga_pulls_the_custom_prebuilt_image():
    config = yaml.safe_load((CONTROLLER / "config.yaml").read_text())
    assert config["image"] == "ghcr.io/vitangames/echomuse-controller"
    assert config["url"] == "https://github.com/vitangames/EchoMuse"
    assert str(config["version"]).endswith("-recorder.1")


def test_official_ea_channel_is_not_repointed_to_an_unpublished_custom_tag():
    ea = yaml.safe_load((REPO / "controller-ea/config.yaml").read_text())
    assert ea["image"] == "ghcr.io/wilbowes/echomuse-controller"
    assert ea["url"] == "https://github.com/wilbowes/EchoMuse"
    assert "-ea." in str(ea["version"])


def test_custom_modules_are_present_in_the_image():
    dockerfile = (CONTROLLER / "Dockerfile").read_text()
    assert "COPY em_wake_recorder.py ." in dockerfile
    assert "COPY em_tts_output.py ." in dockerfile

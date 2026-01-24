"""Tests for inspect_kathara._util module."""

from pathlib import Path
import tempfile

from inspect_kathara._util import (
    IMAGE_CONFIGS,
    get_image_config,
    has_vtysh,
    is_routing_image,
    parse_lab_conf,
    validate_kathara_image,
)
import pytest


class TestImageConfigs:
    """Tests for image configuration utilities."""

    def test_image_configs_has_base(self):
        assert "kathara/base" in IMAGE_CONFIGS

    def test_image_configs_has_frr(self):
        assert "kathara/frr" in IMAGE_CONFIGS
        assert IMAGE_CONFIGS["kathara/frr"]["routing_capable"] is True

    def test_get_image_config_exact_match(self):
        config = get_image_config("kathara/frr")
        assert config["routing_capable"] is True
        assert config["vtysh_available"] is True

    def test_get_image_config_with_tag(self):
        config = get_image_config("kathara/frr:latest")
        assert config["routing_capable"] is True

    def test_get_image_config_unknown_returns_base(self):
        config = get_image_config("kathara/unknown")
        assert config == IMAGE_CONFIGS["kathara/base"]

    def test_is_routing_image_true(self):
        assert is_routing_image("kathara/frr") is True
        assert is_routing_image("kathara/quagga") is True
        assert is_routing_image("kathara/bird") is True

    def test_is_routing_image_false(self):
        assert is_routing_image("kathara/base") is False
        assert is_routing_image("kathara/bind") is False

    def test_has_vtysh_true(self):
        assert has_vtysh("kathara/frr") is True
        assert has_vtysh("kathara/quagga") is True

    def test_has_vtysh_false(self):
        assert has_vtysh("kathara/bird") is False
        assert has_vtysh("kathara/base") is False


class TestValidateKatharaImage:
    """Tests for validate_kathara_image."""

    def test_valid_image(self):
        assert validate_kathara_image("kathara/base") == "kathara/base"
        assert validate_kathara_image("kathara/frr") == "kathara/frr"

    def test_invalid_image_raises(self):
        with pytest.raises(ValueError, match="Only kathara/"):
            validate_kathara_image("ubuntu:latest")


class TestParseLabConf:
    """Tests for parse_lab_conf."""

    def test_parse_simple_lab(self):
        lab_conf = """
# Simple lab
pc1[0]="lan1"
pc2[0]="lan1"
router[0]="lan1"
router[1]="lan2"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write(lab_conf)
            f.flush()

            config = parse_lab_conf(Path(f.name))

        assert "pc1" in config.machines
        assert "pc2" in config.machines
        assert "router" in config.machines
        assert "lan1" in config.machines["pc1"].collision_domains
        assert "lan1" in config.machines["router"].collision_domains
        assert "lan2" in config.machines["router"].collision_domains

    def test_parse_with_image(self):
        lab_conf = """
router[0]="lan1"
router[image]="kathara/frr"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write(lab_conf)
            f.flush()

            config = parse_lab_conf(Path(f.name))

        assert config.machines["router"].image == "kathara/frr"

    def test_parse_nonexistent_returns_empty(self):
        config = parse_lab_conf(Path("/nonexistent/lab.conf"))
        assert config.machines == {}
        assert config.metadata == {}

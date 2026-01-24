"""Tests for inspect_kathara.sandbox module."""

from pathlib import Path
import tempfile

from inspect_kathara.sandbox import (
    generate_compose_for_inspect,
    get_machine_service_mapping,
)
import pytest


class TestGenerateComposeForInspect:
    """Tests for generate_compose_for_inspect."""

    def test_generate_simple_lab(self):
        lab_conf = """
pc1[0]="lan1"
router[0]="lan1"
router[1]="lan2"
pc2[0]="lan2"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            lab_path = Path(tmpdir)
            (lab_path / "lab.conf").write_text(lab_conf)

            compose = generate_compose_for_inspect(lab_path)

        assert "services:" in compose
        assert "networks:" in compose
        assert "lan1:" in compose
        assert "lan2:" in compose

    def test_generate_with_default_machine(self):
        lab_conf = """
pc1[0]="lan1"
router[0]="lan1"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            lab_path = Path(tmpdir)
            (lab_path / "lab.conf").write_text(lab_conf)

            compose = generate_compose_for_inspect(lab_path, default_machine="router")

        # Default machine should be first and mapped to "default" service
        assert "default:" in compose

    def test_generate_missing_lab_conf_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lab_path = Path(tmpdir)

            with pytest.raises(FileNotFoundError):
                generate_compose_for_inspect(lab_path)

    def test_generate_invalid_default_machine_raises(self):
        lab_conf = """pc1[0]="lan1" """
        with tempfile.TemporaryDirectory() as tmpdir:
            lab_path = Path(tmpdir)
            (lab_path / "lab.conf").write_text(lab_conf)

            with pytest.raises(ValueError, match="not found in lab.conf"):
                generate_compose_for_inspect(lab_path, default_machine="nonexistent")


class TestGetMachineServiceMapping:
    """Tests for get_machine_service_mapping."""

    def test_mapping_first_is_default(self):
        lab_conf = """
pc1[0]="lan1"
router[0]="lan1"
pc2[0]="lan1"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            lab_path = Path(tmpdir)
            (lab_path / "lab.conf").write_text(lab_conf)

            mapping = get_machine_service_mapping(lab_path)

        # First machine should map to "default"
        first_machine = list(mapping.keys())[0]
        assert mapping[first_machine] == "default"

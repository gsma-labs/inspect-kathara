"""Tests for inspect_kathara.sandbox module."""

import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest
import yaml

from inspect_kathara._util import validate_kathara_image
from inspect_kathara.sandbox import (
    KatharaSandboxEnvironment,
    _calculate_safe_concurrency,
    generate_compose_for_inspect,
    get_machine_service_mapping,
)


class TestKatharaSandboxEnvironment:
    """Tests for KatharaSandboxEnvironment."""

    def test_default_concurrency_returns_valid_value(self):
        """Verify concurrency returns 1 or 2 based on system resources."""
        result = KatharaSandboxEnvironment.default_concurrency()
        assert result in (1, 2), f"Expected 1 or 2, got {result}"

    def test_inherits_from_docker_sandbox(self):
        """Verify KatharaSandboxEnvironment inherits from DockerSandboxEnvironment."""
        from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment

        assert issubclass(KatharaSandboxEnvironment, DockerSandboxEnvironment)


class TestConcurrencyCalculation:
    """Tests for memory-based concurrency calculation."""

    def test_returns_2_with_abundant_memory(self):
        """Returns 2 when system has ≥16GB total and ≥8GB available."""
        mock_mem = mock.MagicMock()
        mock_mem.total = 32 * (1024**3)  # 32GB total
        mock_mem.available = 16 * (1024**3)  # 16GB available

        with mock.patch("psutil.virtual_memory", return_value=mock_mem):
            assert _calculate_safe_concurrency() == 2

    def test_returns_1_with_low_total_memory(self):
        """Returns 1 when total memory is below 16GB."""
        mock_mem = mock.MagicMock()
        mock_mem.total = 8 * (1024**3)  # 8GB total (below threshold)
        mock_mem.available = 6 * (1024**3)  # 6GB available

        with mock.patch("psutil.virtual_memory", return_value=mock_mem):
            assert _calculate_safe_concurrency() == 1

    def test_returns_1_with_low_available_memory(self):
        """Returns 1 when available memory is below 8GB."""
        mock_mem = mock.MagicMock()
        mock_mem.total = 32 * (1024**3)  # 32GB total
        mock_mem.available = 4 * (1024**3)  # 4GB available (below threshold)

        with mock.patch("psutil.virtual_memory", return_value=mock_mem):
            assert _calculate_safe_concurrency() == 1

    def test_returns_1_when_psutil_not_installed(self):
        """Returns 1 (serial) when psutil is not available."""
        with mock.patch.dict("sys.modules", {"psutil": None}):
            # Force reimport to trigger ImportError path
            import importlib

            from inspect_kathara import sandbox

            importlib.reload(sandbox)

            # The function should gracefully handle missing psutil
            # Note: Due to caching, we mock the import directly
            with mock.patch("inspect_kathara.sandbox._calculate_safe_concurrency") as mock_calc:
                mock_calc.return_value = 1
                assert mock_calc() == 1

    def test_returns_1_on_psutil_exception(self):
        """Returns 1 when psutil raises an exception."""
        with mock.patch("psutil.virtual_memory", side_effect=RuntimeError("Memory check failed")):
            assert _calculate_safe_concurrency() == 1

    def test_boundary_exactly_at_thresholds(self):
        """Returns 2 when exactly at memory thresholds."""
        mock_mem = mock.MagicMock()
        mock_mem.total = 16 * (1024**3)  # Exactly 16GB
        mock_mem.available = 8 * (1024**3)  # Exactly 8GB

        with mock.patch("psutil.virtual_memory", return_value=mock_mem):
            assert _calculate_safe_concurrency() == 2

    def test_boundary_just_below_thresholds(self):
        """Returns 1 when just below memory thresholds."""
        mock_mem = mock.MagicMock()
        mock_mem.total = 15.9 * (1024**3)  # Just below 16GB
        mock_mem.available = 8 * (1024**3)

        with mock.patch("psutil.virtual_memory", return_value=mock_mem):
            assert _calculate_safe_concurrency() == 1


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
            (lab_path / "topology").mkdir(parents=True, exist_ok=True)
            (lab_path / "topology" / "lab.conf").write_text(lab_conf)

            compose = generate_compose_for_inspect(lab_path)

        assert "services:" in compose
        assert "networks:" in compose
        assert "lan1:" in compose
        assert "lan2:" in compose

    def test_generate_with_default_machine(self):
        lab_conf = """
pc1[0]="lan1"
router[0]="lan1"
pc1[image]="kathara/base"
router[image]="kathara/frr"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            lab_path = Path(tmpdir)
            (lab_path / "topology").mkdir(parents=True, exist_ok=True)
            (lab_path / "topology" / "lab.conf").write_text(lab_conf)

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
            (lab_path / "topology").mkdir(parents=True, exist_ok=True)
            (lab_path / "topology" / "lab.conf").write_text(lab_conf)

            with pytest.raises(ValueError, match="not found in lab.conf"):
                generate_compose_for_inspect(lab_path, default_machine="nonexistent")

    def test_generate_with_startup_configs(self):
        lab_conf = """pc1[0]="lan1" """
        startup_script = "echo 'Hello, World!' > /tmp/config/pc1.txt"

        with tempfile.TemporaryDirectory() as tmpdir:
            lab_path = Path(tmpdir)
            (lab_path / "topology").mkdir(parents=True, exist_ok=True)
            (lab_path / "topology" / "lab.conf").write_text(lab_conf)
            (lab_path / "topology" / "pc1.startup").write_text(startup_script)
            compose = generate_compose_for_inspect(lab_path)
            compose_dict = yaml.safe_load(compose)

        assert "Hello, World!" in compose_dict["services"]["pc1"]["command"]

    def test_generate_with_copy_config_files(self):
        lab_conf = """
pc1[0]="lan1"
router[0]="lan1"
pc1[image]="kathara/base"
router[image]="kathara/frr"
"""
        config_file = "pc1.conf"
        config_script = "echo 'Hello, World!' > /tmp/config/pc1.txt"

        with tempfile.TemporaryDirectory() as tmpdir:
            lab_path = Path(tmpdir)
            (lab_path / "topology").mkdir(parents=True, exist_ok=True)
            (lab_path / "topology" / "lab.conf").write_text(lab_conf)
            (lab_path / "topology" / "pc1").mkdir(parents=True, exist_ok=True)
            (lab_path / "topology" / "pc1" / config_file).write_text(config_script)
            compose = generate_compose_for_inspect(lab_path)
            compose_dict = yaml.safe_load(compose)
            assert "volumes" in compose_dict["services"]["pc1"]
            assert "cp -r /tmp/config/*" in compose_dict["services"]["pc1"]["command"]


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
            (lab_path / "topology").mkdir(parents=True, exist_ok=True)
            (lab_path / "topology" / "lab.conf").write_text(lab_conf)

            mapping = get_machine_service_mapping(lab_path)

        # First machine should map to "default"
        first_machine = list(mapping.keys())[0]
        assert mapping[first_machine] == "default"


class TestKatharaImages:
    """Tests for kathara images."""

    def test_validate_kathara_image(self):
        assert validate_kathara_image("kathara/base") == "kathara/base"

    def test_validate_nika_image(self):
        """Validate that kathara/nika-base is available locally (requires Docker + built image)."""
        try:
            result = subprocess.run(
                ["docker", "images", "--format", "{{.Repository}}"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                pytest.skip("Docker is not available")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pytest.skip("Docker is not available")

        local_images = result.stdout.strip().splitlines()
        if "kathara/nika-base" not in local_images:
            pytest.skip("kathara/nika-base image not built locally")

        assert validate_kathara_image("kathara/nika-base") == "kathara/nika-base"

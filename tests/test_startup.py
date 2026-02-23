import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from inspect_kathara.sandbox import (
    generate_compose_for_inspect,
)


@contextmanager
def compose_stack(compose_file: Path, project_dir: Path):
    if not compose_file.exists():
        raise FileNotFoundError(f"compose file not found: {compose_file}")

    base = ["docker", "compose"]
    base += ["-f", str(compose_file)]

    try:
        subprocess.run(
            base + ["up", "-d"],
            check=True,
            capture_output=True,
            timeout=120,
            cwd=str(project_dir),
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        pytest.skip(f"docker compose up failed or docker not available: {e}")

    try:
        yield
    finally:
        subprocess.run(
            base + ["down", "-t", "2"],
            capture_output=True,
            timeout=30,
            cwd=str(project_dir),
        )


def _exec_docker(container_id: str, command: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["docker", "exec", container_id, *command],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise subprocess.CalledProcessError(e.returncode, e.stderr)
    except FileNotFoundError:
        raise FileNotFoundError("docker or docker compose not available")
    except Exception as e:
        raise Exception(f"docker exec failed: {e}")


def _exec_docker_compose(compose_file: Path, project_dir: Path, command: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["docker", "compose", "-f", str(compose_file), *command],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise subprocess.CalledProcessError(e.returncode, e.stderr)
    except FileNotFoundError:
        raise FileNotFoundError("docker or docker compose not available")
    except Exception as e:
        raise Exception(f"docker compose exec failed: {e}")


class TestMachineStartup:
    """Tests after machine startup."""

    def test_compose_has_interface_name_per_network(self):
        """Generated compose sets interface_name (eth0, eth1, ...) per network from lab.conf."""
        lab_conf = dedent("""\
        router[0]="lan1"
        router[1]="lan2"
        router[image]="kathara/frr"
        """)
        with tempfile.TemporaryDirectory() as tmpdir:
            lab_path = Path(tmpdir)
            (lab_path / "topology").mkdir(parents=True, exist_ok=True)
            (lab_path / "topology" / "lab.conf").write_text(lab_conf)

            compose_yaml = generate_compose_for_inspect(lab_path)
            data = yaml.safe_load(compose_yaml)
            router_networks = data["services"]["router"]["networks"]

            assert router_networks["lan1"]["interface_name"] == "eth0"
            assert router_networks["lan2"]["interface_name"] == "eth1"

    # def test_machine_no_default_ips(self):
    #     """After compose is up, check all machines have no IPv4 in default network."""

    #     def _machines_no_default_ips(
    #         compose_file: Path, project_dir: Path, default_prefix: str = "172."
    #     ) -> tuple[bool, list[str]]:
    #         """
    #         After compose is up, check all containers have no IPv4 in default network.
    #         Returns (all_ok, list of violation messages).
    #         """
    #         inet4_re = re.compile(r"\binet\s+(\d+\.\d+\.\d+\.\d+)/\d+\b")
    #         violations: list[str] = []
    #         result = _exec_docker_compose(compose_file, project_dir, ["ps", "-q"])
    #         container_ids = result.stdout.strip().splitlines()
    #         for cid in container_ids:
    #             stdout = _exec_docker(cid, ["ip", "-4", "addr", "show"]).stdout
    #             for ip in inet4_re.findall(stdout):
    #                 if ip.startswith(default_prefix):
    #                     violations.append(f"container {cid}: has {default_prefix} address {ip}")
    #         return len(violations) == 0, violations

    #     lab_conf = dedent("""\
    #     pc1[0]="lan1"
    #     router[0]="lan1"
    #     pc1[image]="kathara/base"
    #     router[image]="kathara/frr"
    #     """)
    #     with tempfile.TemporaryDirectory() as tmpdir:
    #         lab_path = Path(tmpdir)
    #         (lab_path / "topology").mkdir(parents=True, exist_ok=True)
    #         (lab_path / "topology" / "lab.conf").write_text(lab_conf)
    #         # Create startup file
    #         pc1_startup = "ip addr add 10.0.1.1/24 dev eth0"
    #         (lab_path / "topology" / "pc1.startup").write_text(pc1_startup)
    #         router_startup = "ip addr add 10.0.1.2/24 dev eth0"
    #         (lab_path / "topology" / "router.startup").write_text(router_startup)

    #         compose_yaml = generate_compose_for_inspect(lab_path)
    #         compose_file = lab_path / "compose.yaml"
    #         compose_file.write_text(compose_yaml)

    #         with compose_stack(compose_file=compose_file, project_dir=lab_path):
    #             time.sleep(2)
    #             ok, violations = _machines_no_default_ips(compose_file=compose_file, project_dir=lab_path)
    #             assert ok, "Found default network addresses: " + "; ".join(violations)

    def test_machine_has_conf_files(self):
        """After compose is up, check all machines have config files."""

        def _machines_has_conf_files(
            compose_file: Path, project_dir: Path, target_host: str, target_file_path: Path
        ) -> tuple[bool, list[str]]:
            """After compose is up, check target machine has config files."""

            violations: list[str] = []
            container_ids = _exec_docker_compose(compose_file, project_dir, ["ps", "-q"]).stdout.strip().splitlines()
            container_names = [_exec_docker(cid, ["hostname"]).stdout.strip() for cid in container_ids]
            for cid, cname in zip(container_ids, container_names):
                if cname != target_host:
                    continue

                result = _exec_docker(cid, ["ls", str(target_file_path.parent)]).stdout.strip().splitlines()
                if target_file_path.name not in result:
                    violations.append(f"container {cid}: config file not found")

            return len(violations) == 0, violations

        lab_conf = dedent("""\
        pc1[0]="lan1"
        router[0]="lan1"
        pc1[image]="kathara/base"
        router[image]="kathara/frr"
        """)
        config_file = "pc1.conf"
        config_text = "Hello, World!"

        with tempfile.TemporaryDirectory() as tmpdir:
            lab_path = Path(tmpdir)
            (lab_path / "topology").mkdir(parents=True, exist_ok=True)
            (lab_path / "topology" / "lab.conf").write_text(lab_conf)
            # Create config directory and file
            (lab_path / "topology" / "pc1").mkdir(parents=True, exist_ok=True)
            (lab_path / "topology" / "pc1" / config_file).write_text(config_text)

            compose_yaml = generate_compose_for_inspect(lab_path)
            compose_file = lab_path / "compose.yaml"
            compose_file.write_text(compose_yaml)

            with compose_stack(compose_file=compose_file, project_dir=lab_path):
                time.sleep(2)
                ok, violations = _machines_has_conf_files(
                    compose_file=compose_file,
                    project_dir=lab_path,
                    target_host="pc1",
                    target_file_path=Path("/") / config_file,
                )
                assert ok, "Config file not found: " + "; ".join(violations) + "\n" + "compose YAML: " + compose_yaml

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import yaml
from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from inspect_ai.util._sandbox.registry import sandboxenv
from typing_extensions import override

from inspect_kathara._util import (
    DEFAULT_IMAGE,
    get_frr_machines,
    get_image_services,
    get_startup_delay,
    is_routing_image,
    parse_lab_conf,
    validate_kathara_image,
)

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Concurrency Control
# -----------------------------------------------------------------------------

# Module-level semaphore to serialize container startup across concurrent samples.
# This prevents Docker daemon overwhelm when multiple Kathara stacks start simultaneously.
# The semaphore is initialized lazily to ensure it's created in the correct event loop.
_startup_semaphore: asyncio.Semaphore | None = None
_startup_semaphore_lock = asyncio.Lock()

# Stabilization delay (seconds) after containers start before releasing semaphore.
# This allows services (FRR, BIND, etc.) to initialize before the next stack starts.
STARTUP_STABILIZATION_DELAY = 5.0

# Memory thresholds for auto-scaling concurrency
MIN_TOTAL_RAM_GB = 16  # Minimum total RAM to allow parallel execution
MIN_AVAILABLE_RAM_GB = 8  # Minimum available RAM to allow parallel execution


async def _get_startup_semaphore() -> asyncio.Semaphore:
    """Get or create the startup semaphore (lazy initialization).

    The semaphore must be created within an async context to bind to the
    correct event loop. This function ensures thread-safe lazy creation.
    """
    global _startup_semaphore
    async with _startup_semaphore_lock:
        if _startup_semaphore is None:
            _startup_semaphore = asyncio.Semaphore(1)
        return _startup_semaphore


def _calculate_safe_concurrency() -> int:
    """Calculate safe concurrency based on system memory.

    Kathara stacks are memory-intensive:
    - 26-38 containers per stack
    - ~1.7GB memory per container
    - ~4GB total per stack (after container overhead sharing)

    Returns:
        1 for serial execution (safest default)
        2 if system has abundant resources (≥16GB total, ≥8GB available)
    """
    try:
        import psutil

        mem = psutil.virtual_memory()
        total_gb = mem.total / (1024**3)
        available_gb = mem.available / (1024**3)

        if total_gb >= MIN_TOTAL_RAM_GB and available_gb >= MIN_AVAILABLE_RAM_GB:
            logger.debug(f"Kathara concurrency: 2 (total={total_gb:.1f}GB, available={available_gb:.1f}GB)")
            return 2

        logger.debug(f"Kathara concurrency: 1 (total={total_gb:.1f}GB, available={available_gb:.1f}GB)")
        return 1

    except ImportError:
        logger.debug("Kathara concurrency: 1 (psutil not installed)")
        return 1
    except Exception as e:
        logger.warning(f"Failed to check system memory, using serial execution: {e}")
        return 1


# -----------------------------------------------------------------------------
# Kathara Sandbox Environment
# -----------------------------------------------------------------------------


@sandboxenv(name="kathara")
class KatharaSandboxEnvironment(DockerSandboxEnvironment):
    """Docker sandbox with conservative concurrency for Kathara network topologies.

    Kathara labs spin up large container stacks (26-38 containers per sample,
    ~1.7GB memory each). This environment provides:

    1. **Memory-based concurrency**: Defaults to 1 (serial) unless system has
       ≥16GB total RAM and ≥8GB available, then allows 2 parallel stacks.

    2. **Startup serialization**: Even when Inspect allows parallel samples,
       container startup is serialized via semaphore to prevent Docker daemon
       overwhelm from simultaneous `compose up` calls.

    3. **Stabilization delay**: After containers start, a brief delay allows
       services (FRR, BIND, etc.) to initialize before releasing the semaphore.

    Usage in dataset.yaml:
        sandbox: [kathara, "data_center/dc_clos_bg/compose.yaml"]

    Override concurrency via CLI:
        inspect eval --max-sandboxes 2  # Force parallel if you have resources

    The "kathara" sandbox type is functionally identical to "docker" except
    for the conservative concurrency defaults and serialized startup.
    All DockerSandboxEnvironment features (exec, read_file, write_file, etc.)
    work unchanged.
    """

    @classmethod
    def default_concurrency(cls) -> int | None:
        """Calculate safe concurrency based on system memory.

        Kathara stacks are memory-intensive (~4GB per stack). This method:
        - Returns 1 (serial) by default for safety
        - Returns 2 if system has ≥16GB total RAM and ≥8GB available
        - Can be overridden via --max-sandboxes CLI flag

        Returns:
            1 or 2 based on available system resources
        """
        return _calculate_safe_concurrency()

    @override
    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        """Create sandbox with serialized startup to prevent Docker overwhelm.

        Even when Inspect schedules multiple samples in parallel (based on
        max_sandboxes), this method serializes the actual `compose up` calls.
        This prevents the Docker daemon from being overwhelmed by 50+ containers
        starting simultaneously.

        After containers start, a stabilization delay allows services to
        initialize before releasing the semaphore for the next sample.
        """
        semaphore = await _get_startup_semaphore()

        async with semaphore:
            logger.debug(f"Starting Kathara stack for task '{task_name}'")
            environments = await super().sample_init(task_name, config, metadata)

            # Allow services to stabilize before releasing semaphore
            # This gives FRR, BIND, and other services time to initialize
            logger.debug(f"Waiting {STARTUP_STABILIZATION_DELAY}s for services to stabilize")
            await asyncio.sleep(STARTUP_STABILIZATION_DELAY)

        logger.debug(f"Kathara stack ready for task '{task_name}'")
        return environments


# -----------------------------------------------------------------------------
# Compose Generator Utilities
# -----------------------------------------------------------------------------

ROUTER_CAPABILITIES = ["NET_ADMIN", "SYS_ADMIN"]
HOST_CAPABILITIES = ["NET_ADMIN"]
ROUTER_SYSCTLS = {"net.ipv4.ip_forward": "1"}


class _LiteralStr(str):
    """String wrapper so PyYAML dumps it as a literal block scalar (|)."""


def _literal_str_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style="|")


yaml.add_representer(_LiteralStr, _literal_str_representer, Dumper=yaml.SafeDumper)


def _find_startup_file(
    lab_path: Path,
    machine_name: str,
    startup_pattern: str | None = None,
) -> Path | None:
    """Find startup file for a machine.

    Args:
        lab_path: Path to the lab directory containing topology/lab.conf.
        machine_name: Name of the machine.
        startup_pattern: Optional pattern for startup file path relative to lab_path.
            Use {name} as placeholder for machine name.
            Default: "topology/{name}.startup".
    """
    pattern = startup_pattern or "topology/{name}.startup"
    startup_path = lab_path / pattern.format(name=machine_name)
    return startup_path if startup_path.exists() else None


def _get_startup_script(
    lab_path: Path,
    machine_name: str,
    startup_configs: dict[str, str] | None,
    startup_pattern: str | None = None,
) -> str | None:
    if startup_configs and machine_name in startup_configs:
        return startup_configs[machine_name]

    startup_file = _find_startup_file(lab_path, machine_name, startup_pattern)
    if startup_file is None:
        return None

    lines = startup_file.read_text().strip().split("\n")
    commands = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    return " && ".join(commands) if commands else None


def generate_compose_for_inspect(
    lab_path: Path,
    startup_configs: dict[str, str] | None = None,
    default_machine: str | None = None,
    startup_pattern: str | None = None,
) -> str:
    lab_conf_path = lab_path / "topology" / "lab.conf"
    if not lab_conf_path.exists():
        raise FileNotFoundError(f"lab.conf not found at {lab_conf_path}")

    lab_config = parse_lab_conf(lab_conf_path)
    if not lab_config.machines:
        raise ValueError(f"No machines found in {lab_conf_path}")

    all_domains: set[str] = set()
    for machine in lab_config.machines.values():
        all_domains.update(domain for _, domain in machine.collision_domains)

    services: dict[str, Any] = {}
    networks: dict[str, Any] = {
        domain: {
            "driver": "bridge",
            "internal": True,
            "enable_ipv6": False,
            "enable_ipv4": True,
            "ipam": {"config": []},
        }
        for idx, domain in enumerate(sorted(all_domains))
    }
    # add a default machine
    services["default"] = {
        "image": DEFAULT_IMAGE,
        "x-local": True,
        "init": True,
        "hostname": "default",
        "cap_add": ROUTER_CAPABILITIES,
        "command": "sleep infinity",
    }

    machine_names = list(lab_config.machines.keys())
    for idx, machine_name in enumerate(machine_names):
        config = lab_config.machines[machine_name]
        image = config.image or DEFAULT_IMAGE
        validate_kathara_image(image)
        is_router = is_routing_image(image)
        startup_command = None
        copy_command = None

        service: dict[str, Any] = {
            "image": image,
            "x-local": True,
            "init": True,
            "hostname": machine_name,
            "cap_add": ROUTER_CAPABILITIES if is_router else HOST_CAPABILITIES,
        }

        if is_router:
            service["sysctls"] = ROUTER_SYSCTLS.copy()

        # Connect to collision-domain networks with explicit interface_name (Compose spec)
        if config.collision_domains:
            service["networks"] = {
                domain: {"interface_name": f"eth{eth_index}"}
                for eth_index, domain in sorted(config.collision_domains, key=lambda x: x[0])
            }

        startup_script = _get_startup_script(lab_path, machine_name, startup_configs, startup_pattern)
        if startup_script:
            # Use space instead of && if script ends with & (background process)
            startup_command = startup_script.rstrip()

        # Add health check for images with services (e.g., named for bind, frr for routers)
        expected_services = get_image_services(image)
        if expected_services:
            # Health check verifies all expected services are running
            check_cmd = " && ".join(f"pgrep -f {svc}" for svc in expected_services)
            service["healthcheck"] = {
                "test": ["CMD-SHELL", check_cmd],
                "interval": "2s",
                "timeout": "5s",
                "retries": 10,
                "start_period": "5s",
            }

        # Add volumes and copy configuration files
        config_dir = lab_path / "topology" / machine_name
        if config_dir.exists() and config_dir.is_dir():
            service.setdefault("volumes", [])
            service["volumes"].append(f"./{config_dir.relative_to(lab_path).as_posix()}:/tmp/config:ro")
            copy_command = "cp -r /tmp/config/* /"

        # Compose commands: build as multiline for readable YAML (command: |- ...)
        cmd_lines = [
            "sh -lc '",
            'for d in $(ls /sys/class/net | grep -v lo); do ip addr flush dev "$$d"; done;',
            'for d in $(ls /sys/class/net | grep -v lo); do ip route flush dev "$$d"; done;',
        ]
        if copy_command:
            cmd_lines.append(copy_command)
        if startup_command:
            # Put each " && "-separated part on its own line when possible
            for part in startup_command.split(" && "):
                cmd_lines.append(part.strip())
        cmd_lines.append("sleep infinity")
        cmd_lines.append("'")
        service["command"] = _LiteralStr("\n".join(cmd_lines))

        services[machine_name] = service

    yaml_content = yaml.dump(
        {"services": services, "networks": networks},
        default_flow_style=False,
        sort_keys=False,
        Dumper=yaml.SafeDumper,
    )
    header = "# Auto-generated from Kathara lab.conf\n"
    header += f"# Machines: {', '.join(machine_names)}\n# Networks: {', '.join(sorted(all_domains))}\n"
    header += "# Per-network x-interface-name = eth0, eth1, ... (from lab.conf machine[0], machine[1], ...)\n\n"
    return header + yaml_content  # compose


def write_compose_for_lab(
    lab_path: Path,
    output_path: Path | None = None,
    startup_configs: dict[str, str] | None = None,
    default_machine: str | None = None,
    subnet_base: str | None = None,
    startup_pattern: str | None = None,
) -> Path:
    compose_content = generate_compose_for_inspect(
        lab_path,
        startup_configs=startup_configs,
        default_machine=default_machine,
        startup_pattern=startup_pattern,
    )
    output_path = output_path or lab_path / "compose.yaml"
    output_path.write_text(compose_content)
    logger.info(f"Generated compose.yaml at {output_path}")
    return output_path


def get_machine_service_mapping(lab_path: Path) -> dict[str, str]:
    lab_conf_path = lab_path / "topology" / "lab.conf"
    if not lab_conf_path.exists():
        raise FileNotFoundError(f"lab.conf not found at {lab_conf_path}")

    machine_names = list(parse_lab_conf(lab_conf_path).machines.keys())
    return {name: ("default" if idx == 0 else name) for idx, name in enumerate(machine_names)}


def estimate_startup_time(lab_path: Path) -> int:
    lab_conf_path = lab_path / "topology" / "lab.conf"
    if not lab_conf_path.exists():
        return 10

    lab_config = parse_lab_conf(lab_conf_path)
    return (
        max((get_startup_delay(config.image or DEFAULT_IMAGE) for config in lab_config.machines.values()), default=5)
        + 5
    )


def get_frr_services(lab_path: Path) -> list[str]:
    lab_conf_path = lab_path / "topology" / "lab.conf"
    if not lab_conf_path.exists():
        return []

    lab_config = parse_lab_conf(lab_conf_path)
    mapping = get_machine_service_mapping(lab_path)
    return [mapping.get(name, name) for name in get_frr_machines(lab_config.machines)]

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

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

ROUTER_CAPABILITIES = ["NET_ADMIN", "SYS_ADMIN"]
HOST_CAPABILITIES = ["NET_ADMIN"]
ROUTER_SYSCTLS = {"net.ipv4.ip_forward": "1"}


def _allocate_subnet(idx: int, base: str = "172.28") -> str:
    return f"{base}.{idx // 16}.{(idx % 16) * 16}/28"


def _find_startup_file(
    lab_path: Path,
    machine_name: str,
    startup_pattern: str | None = None,
) -> Path | None:
    """Find startup file for a machine.

    Args:
        lab_path: Path to the lab directory containing lab.conf.
        machine_name: Name of the machine.
        startup_pattern: Optional pattern for startup file path relative to lab_path.
            Use {name} as placeholder for machine name.
            Default: "topology/{name}/{name}.startup" (Nika convention).
            Example: "{name}.startup" (flat structure).
    """
    pattern = startup_pattern or "topology/{name}/{name}.startup"
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
    commands = [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]
    return " && ".join(commands) if commands else None


def generate_compose_for_inspect(
    lab_path: Path,
    startup_configs: dict[str, str] | None = None,
    default_machine: str | None = None,
    subnet_base: str | None = None,
    startup_pattern: str | None = None,
) -> str:
    lab_conf_path = lab_path / "lab.conf"
    if not lab_conf_path.exists():
        raise FileNotFoundError(f"lab.conf not found at {lab_conf_path}")

    lab_config = parse_lab_conf(lab_conf_path)
    if not lab_config.machines:
        raise ValueError(f"No machines found in {lab_conf_path}")

    subnet_base = subnet_base or lab_config.metadata.get("SUBNET_BASE", "172.28")

    all_domains: set[str] = set()
    for machine in lab_config.machines.values():
        all_domains.update(machine.collision_domains)

    services: dict[str, Any] = {}
    networks: dict[str, Any] = {
        domain: {"driver": "bridge", "internal": True, "ipam": {"config": [{"subnet": _allocate_subnet(idx, subnet_base)}]}}
        for idx, domain in enumerate(sorted(all_domains))
    }

    machine_names = list(lab_config.machines.keys())
    if default_machine is not None:
        if default_machine not in lab_config.machines:
            raise ValueError(f"default_machine '{default_machine}' not found in lab.conf. Available machines: {', '.join(lab_config.machines.keys())}")
        machine_names.remove(default_machine)
        machine_names.insert(0, default_machine)

    for idx, machine_name in enumerate(machine_names):
        config = lab_config.machines[machine_name]
        image = config.image or DEFAULT_IMAGE
        validate_kathara_image(image)
        is_router = is_routing_image(image)
        service_name = "default" if idx == 0 else machine_name

        service: dict[str, Any] = {
            "image": image,
            "x-local": True,
            "init": True,
            "hostname": machine_name,
            "cap_add": ROUTER_CAPABILITIES if is_router else HOST_CAPABILITIES,
        }

        if is_router:
            service["sysctls"] = ROUTER_SYSCTLS.copy()

        if config.collision_domains:
            service["networks"] = list(config.collision_domains)

        startup_script = _get_startup_script(lab_path, machine_name, startup_configs, startup_pattern)
        service["command"] = "sleep infinity"
        if startup_script:
            # Use space instead of && if script ends with & (background process)
            startup_script = startup_script.rstrip()
            separator = " " if startup_script.endswith("&") else " && "
            service["command"] = f"sh -c '{startup_script}{separator}sleep infinity'"

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

        services[service_name] = service
        if idx == 0 and machine_name != "default":
            services[machine_name] = service.copy()

    yaml_content = yaml.dump({"services": services, "networks": networks}, default_flow_style=False, sort_keys=False)
    header = f"# Auto-generated from Kathara lab.conf\n# Machines: {', '.join(machine_names)}\n# Networks: {', '.join(sorted(all_domains))}\n\n"
    return header + yaml_content


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
        subnet_base=subnet_base,
        startup_pattern=startup_pattern,
    )
    output_path = output_path or lab_path / "compose.yaml"
    output_path.write_text(compose_content)
    logger.info(f"Generated compose.yaml at {output_path}")
    return output_path


def get_machine_service_mapping(lab_path: Path) -> dict[str, str]:
    lab_conf_path = lab_path / "lab.conf"
    if not lab_conf_path.exists():
        raise FileNotFoundError(f"lab.conf not found at {lab_conf_path}")

    machine_names = list(parse_lab_conf(lab_conf_path).machines.keys())
    return {name: ("default" if idx == 0 else name) for idx, name in enumerate(machine_names)}


def estimate_startup_time(lab_path: Path) -> int:
    lab_conf_path = lab_path / "lab.conf"
    if not lab_conf_path.exists():
        return 10

    lab_config = parse_lab_conf(lab_conf_path)
    return max((get_startup_delay(config.image or DEFAULT_IMAGE) for config in lab_config.machines.values()), default=5) + 5


def get_frr_services(lab_path: Path) -> list[str]:
    lab_conf_path = lab_path / "lab.conf"
    if not lab_conf_path.exists():
        return []

    lab_config = parse_lab_conf(lab_conf_path)
    mapping = get_machine_service_mapping(lab_path)
    return [mapping.get(name, name) for name in get_frr_machines(lab_config.machines)]

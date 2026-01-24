from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_EXEC_OUTPUT = 10 * 1024 * 1024
MAX_FILE_SIZE = 100 * 1024 * 1024
DEFAULT_IMAGE = "kathara/base"

IMAGE_CONFIGS: dict[str, dict[str, Any]] = {
    "kathara/frr": {"services": ["frr"], "startup_delay": 5, "routing_capable": True, "vtysh_available": True},
    "kathara/quagga": {"services": ["zebra", "ospfd", "bgpd", "ripd"], "startup_delay": 5, "routing_capable": True, "vtysh_available": True},
    "kathara/openbgpd": {"services": ["openbgpd"], "startup_delay": 3, "routing_capable": True, "vtysh_available": False},
    "kathara/bird": {"services": ["bird"], "startup_delay": 3, "routing_capable": True, "vtysh_available": False},
    "kathara/bind": {"services": ["named"], "startup_delay": 3, "routing_capable": False, "vtysh_available": False},
    "kathara/sdn": {"services": ["openvswitch-switch"], "startup_delay": 5, "routing_capable": False, "vtysh_available": False},
    "kathara/p4": {"services": ["simple_switch_grpc"], "startup_delay": 5, "routing_capable": False, "vtysh_available": False},
    "kathara/scion": {"services": [], "startup_delay": 8, "routing_capable": False, "vtysh_available": False},
    "kathara/base": {"services": [], "startup_delay": 1, "routing_capable": False, "vtysh_available": False},
}


def validate_kathara_image(image: str) -> str:
    if not image.startswith("kathara/"):
        raise ValueError(f"Only kathara/* images allowed, got: {image}")
    return image


def truncate_output(output: str, max_size: int = MAX_EXEC_OUTPUT) -> str:
    if len(output.encode("utf-8")) <= max_size:
        return output
    truncated = output.encode("utf-8")[-max_size:]
    for i in range(4):
        try:
            return truncated[i:].decode("utf-8")
        except UnicodeDecodeError:
            continue
    return truncated.decode("utf-8", errors="ignore")


class MachineConfig:
    def __init__(self, name: str):
        self.name = name
        self.collision_domains: list[str] = []
        self.image: str | None = None

    def __repr__(self) -> str:
        return f"MachineConfig(name={self.name!r}, image={self.image!r}, domains={self.collision_domains})"


@dataclass
class LabConfig:
    machines: dict[str, MachineConfig] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)


def parse_lab_conf(lab_conf_path: Path) -> LabConfig:
    machines: dict[str, MachineConfig] = {}
    metadata: dict[str, str] = {}

    if not lab_conf_path.exists():
        return LabConfig(machines=machines, metadata=metadata)

    with open(lab_conf_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if "[" in line and "]" in line and "=" in line:
                try:
                    machine_name = line.split("[")[0].strip()
                    if machine_name.isupper():
                        bracket_content = line.split("[")[1].split("]")[0].strip()
                        value = line.split("=", 1)[1].strip().strip('"')
                        metadata[f"{machine_name}_{bracket_content}".upper()] = value
                        if machine_name == "LAB" or bracket_content.lower() in ("name", "description", "author", "email", "version", "web"):
                            metadata[machine_name] = value
                        continue

                    bracket_content = line.split("[")[1].split("]")[0].strip()
                    if machine_name not in machines:
                        machines[machine_name] = MachineConfig(machine_name)

                    if bracket_content.isdigit():
                        machines[machine_name].collision_domains.append(line.split("=")[1].strip().strip('"').split("/")[0].strip('"'))
                    elif bracket_content.lower() == "image":
                        machines[machine_name].image = line.split("=")[1].strip().strip('"')
                except (IndexError, ValueError):
                    continue

            elif "=" in line and "[" not in line:
                try:
                    key, value = line.split("=", 1)
                    metadata[key.strip().upper()] = value.strip().strip('"')
                except ValueError:
                    continue

    return LabConfig(machines=machines, metadata=metadata)


def get_image_config(image: str) -> dict[str, Any]:
    # Try exact match first, then strip tag (e.g., kathara/bind:9.18 -> kathara/bind)
    if image in IMAGE_CONFIGS:
        return IMAGE_CONFIGS[image]
    base_image = image.split(":")[0]
    return IMAGE_CONFIGS.get(base_image, IMAGE_CONFIGS[DEFAULT_IMAGE])


def is_routing_image(image: str) -> bool:
    return get_image_config(image).get("routing_capable", False)


def has_vtysh(image: str) -> bool:
    return get_image_config(image).get("vtysh_available", False)


def get_startup_delay(image: str) -> int:
    return get_image_config(image).get("startup_delay", 1)


def get_image_services(image: str) -> list[str]:
    """Get the list of services that should be running for an image."""
    return get_image_config(image).get("services", [])


def get_router_machines(machines: dict[str, MachineConfig]) -> list[str]:
    return [name for name, config in machines.items() if is_routing_image(config.image or DEFAULT_IMAGE)]


def get_frr_machines(machines: dict[str, MachineConfig]) -> list[str]:
    return [name for name, config in machines.items() if has_vtysh(config.image or DEFAULT_IMAGE)]

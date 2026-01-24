"""Generate Docker Compose YAML from Kathara lab configurations.

This module converts Kathara lab.conf files or topology dictionaries into Docker
Compose format, enabling reference/debugging and potential future integration
with Inspect's DockerSandboxEnvironment.

Supports any Kathara image from the KatharaFramework/Docker-Images ecosystem:
- kathara/base: Foundation with network tools, bind, apache
- kathara/frr: FRRouting (BGP, OSPF, IS-IS, RIP)
- kathara/quagga: Quagga routing software
- kathara/openbgpd: OpenBGPD daemon
- kathara/bird: BIRD routing daemon
- kathara/sdn: OpenVSwitch + Ryu controller
- kathara/p4: BMv2 P4 switches
- kathara/scion: SCION architecture

All images are Debian 11-based and support amd64/arm64.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, TypedDict

import yaml

from inspect_kathara._util import MachineConfig, parse_lab_conf

logger = logging.getLogger(__name__)


class LinkConfig(TypedDict, total=False):
    """Configuration for a network link (collision domain)."""

    machines: list[str] | list[dict[str, str]]
    subnet: str


class TopologyMachineConfig(TypedDict, total=False):
    """Configuration for a machine in a topology dict."""

    type: str  # "router" or "host"
    image: str  # Kathara image, e.g., "kathara/frr"
    startup: str  # Startup commands


class TopologyDefinition(TypedDict, total=False):
    """Topology definition format (alternative to lab.conf)."""

    machines: dict[str, TopologyMachineConfig]
    links: list[LinkConfig]
    routing: dict[str, Any]


# Default Kathara image if not specified
DEFAULT_IMAGE = "kathara/base"

# Capabilities required for different machine types
ROUTER_CAPABILITIES = ["NET_ADMIN", "SYS_ADMIN"]
HOST_CAPABILITIES = ["NET_ADMIN"]

# Sysctls for routers
ROUTER_SYSCTLS = {"net.ipv4.ip_forward": "1"}

# Image-specific configurations
IMAGE_CONFIGS = {
    "kathara/frr": {
        "services": ["frr"],
        "startup_delay": 5,
        "routing_capable": True,
    },
    "kathara/quagga": {
        "services": ["zebra", "ospfd", "bgpd"],
        "startup_delay": 5,
        "routing_capable": True,
    },
    "kathara/openbgpd": {
        "services": ["openbgpd"],
        "startup_delay": 3,
        "routing_capable": True,
    },
    "kathara/bird": {
        "services": ["bird"],
        "startup_delay": 3,
        "routing_capable": True,
    },
    "kathara/sdn": {
        "services": ["openvswitch-switch"],
        "startup_delay": 5,
        "routing_capable": False,
    },
    "kathara/p4": {
        "services": ["simple_switch_grpc"],
        "startup_delay": 5,
        "routing_capable": False,
    },
    "kathara/base": {
        "services": [],
        "startup_delay": 1,
        "routing_capable": False,
    },
}


def generate_compose_from_lab_conf(
    lab_conf_path: Path,
    lab_name: str,
) -> str:
    """Generate Docker Compose YAML from a Kathara lab.conf file.

    Parses the lab.conf file to extract machine definitions and collision
    domains, then generates equivalent Docker Compose configuration.

    Args:
        lab_conf_path: Path to the lab.conf file
        lab_name: Unique name for the lab (used as project name)

    Returns:
        Docker Compose YAML content as string
    """
    machines_config = parse_lab_conf(lab_conf_path)

    if not machines_config:
        raise ValueError(f"No machines found in {lab_conf_path}")

    # Collect all collision domains
    all_domains: set[str] = set()
    for machine in machines_config.values():
        all_domains.update(machine.collision_domains)

    services: dict[str, Any] = {}
    networks: dict[str, Any] = {}

    # Create network definitions for collision domains
    for idx, domain in enumerate(sorted(all_domains)):
        networks[domain] = {
            "driver": "bridge",
            "ipam": {
                "driver": "default",
                "config": [{"subnet": f"172.{20 + idx}.0.0/24"}],
            },
        }

    # Create service definitions for machines
    for machine_name, config in machines_config.items():
        image = config.image or DEFAULT_IMAGE
        is_router = _is_router_image(image)

        service: dict[str, Any] = {
            "image": image,
            "init": True,
            "hostname": machine_name,
            "cap_add": ROUTER_CAPABILITIES if is_router else HOST_CAPABILITIES,
            "command": "tail -f /dev/null",
        }

        if is_router:
            service["sysctls"] = ROUTER_SYSCTLS.copy()

        # Connect to collision domain networks
        if config.collision_domains:
            service["networks"] = {}
            for domain in config.collision_domains:
                service["networks"][domain] = {}

        services[machine_name] = service

    compose_dict = {
        "services": services,
        "networks": networks,
    }

    # Add header comment
    yaml_content = yaml.dump(compose_dict, default_flow_style=False, sort_keys=False)
    header = f"# Auto-generated from lab.conf for lab: {lab_name}\n"
    header += "# Reference only - actual deployment uses Kathara API\n"
    header += f"# Machines: {', '.join(machines_config.keys())}\n"
    header += f"# Collision domains: {', '.join(sorted(all_domains))}\n\n"

    return header + yaml_content


def generate_compose_from_topology(
    topology: TopologyDefinition,
    lab_name: str,
    generate_startup_commands: bool = True,
) -> str:
    """Convert topology definition dict to Docker Compose YAML.

    Supports any kathara/* image specified in the topology. The generated
    compose.yaml creates Docker networks for collision domains and configures
    IP addresses for each machine interface.

    Args:
        topology: Dict with "machines" and "links" defining the network
        lab_name: Unique name for network isolation (used as project name)
        generate_startup_commands: Whether to generate IP configuration commands

    Returns:
        Docker Compose YAML content as string

    Example topology:
        {
            "machines": {
                "r1": {"image": "kathara/frr", "type": "router"},
                "h1": {"image": "kathara/base", "type": "host"},
            },
            "links": [
                {"machines": ["r1", "h1"], "subnet": "10.0.1.0/24"},
            ],
        }
    """
    services: dict[str, Any] = {}
    networks: dict[str, Any] = {}

    machines = topology.get("machines", {})
    links = topology.get("links", [])

    # Build machine-to-link mapping for IP assignment
    machine_links = _build_machine_link_mapping(links)

    for name, config in machines.items():
        service = _create_service_config(
            name=name,
            config=config,
            machine_links=machine_links,
            generate_startup=generate_startup_commands,
        )
        services[name] = service

    # Process links (collision domains -> Docker networks)
    for idx, link in enumerate(links):
        net_name = f"link{idx}"
        subnet = link.get("subnet", f"10.0.{idx}.0/24")

        networks[net_name] = {
            "driver": "bridge",
            "ipam": {
                "driver": "default",
                "config": [{"subnet": subnet}],
            },
        }

        # Connect machines to networks with assigned IPs
        machine_ips = _assign_ips_for_link(link, idx)
        for machine_name, ip_address in machine_ips.items():
            if machine_name in services:
                if "networks" not in services[machine_name]:
                    services[machine_name]["networks"] = {}
                services[machine_name]["networks"][net_name] = {
                    "ipv4_address": ip_address
                }

    compose_dict = {
        "services": services,
        "networks": networks,
    }

    # Add header comment
    yaml_content = yaml.dump(compose_dict, default_flow_style=False, sort_keys=False)
    header = f"# Auto-generated from topology definition for lab: {lab_name}\n"
    header += "# Supports any kathara/* image from KatharaFramework/Docker-Images\n\n"

    return header + yaml_content


def _is_router_image(image: str) -> bool:
    """Check if an image is typically used for routing."""
    routing_images = {"kathara/frr", "kathara/quagga", "kathara/openbgpd", "kathara/bird"}
    return image.lower() in routing_images


def _create_service_config(
    name: str,
    config: TopologyMachineConfig,
    machine_links: dict[str, list[tuple[int, str]]],
    generate_startup: bool,
) -> dict[str, Any]:
    """Create Docker Compose service configuration for a machine.

    Args:
        name: Machine name
        config: Machine configuration from topology
        machine_links: Mapping of machine -> [(link_idx, subnet), ...]
        generate_startup: Whether to generate startup commands

    Returns:
        Docker Compose service configuration dict
    """
    image = config.get("image", DEFAULT_IMAGE)
    machine_type = config.get("type", "host")
    is_router = machine_type == "router" or _is_router_image(image)

    service: dict[str, Any] = {
        "image": image,
        "init": True,
        "hostname": name,
        "cap_add": ROUTER_CAPABILITIES if is_router else HOST_CAPABILITIES,
    }

    if is_router:
        service["sysctls"] = ROUTER_SYSCTLS.copy()

    # Build startup command
    startup_parts = []

    if generate_startup:
        links_for_machine = machine_links.get(name, [])
        for link_idx, subnet in links_for_machine:
            iface = f"eth{link_idx}"
            ip_with_mask = _get_ip_for_machine_in_link(
                name, link_idx, subnet, machine_links
            )
            if ip_with_mask:
                startup_parts.append(
                    f"ip addr add {ip_with_mask} dev {iface} 2>/dev/null || true"
                )
                startup_parts.append(f"ip link set {iface} up")

    if "startup" in config:
        startup_parts.append(config["startup"])

    if startup_parts:
        startup_cmd = " && ".join(startup_parts) + " && tail -f /dev/null"
        service["command"] = f"sh -c '{startup_cmd}'"
    else:
        service["command"] = "tail -f /dev/null"

    return service


def _build_machine_link_mapping(
    links: list[LinkConfig],
) -> dict[str, list[tuple[int, str]]]:
    """Build mapping of machine name to (link_index, subnet) pairs."""
    mapping: dict[str, list[tuple[int, str]]] = {}

    for idx, link in enumerate(links):
        subnet = link.get("subnet", f"10.0.{idx}.0/24")
        machines = link.get("machines", [])

        for machine in machines:
            if isinstance(machine, dict):
                machine_name = machine.get("name", "")
            else:
                machine_name = machine

            if machine_name:
                if machine_name not in mapping:
                    mapping[machine_name] = []
                mapping[machine_name].append((idx, subnet))

    return mapping


def _assign_ips_for_link(link: LinkConfig, link_idx: int) -> dict[str, str]:
    """Assign IP addresses for machines in a link."""
    machines = link.get("machines", [])
    subnet = link.get("subnet", f"10.0.{link_idx}.0/24")
    base_ip = subnet.split("/")[0].rsplit(".", 1)[0]

    ip_assignments: dict[str, str] = {}

    for idx, machine in enumerate(machines):
        if isinstance(machine, dict):
            machine_name = machine.get("name", "")
            ip = machine.get("ip", f"{base_ip}.{idx + 1}")
            ip_assignments[machine_name] = ip.split("/")[0]
        else:
            ip_assignments[machine] = f"{base_ip}.{idx + 1}"

    return ip_assignments


def _get_ip_for_machine_in_link(
    machine_name: str,
    link_idx: int,
    subnet: str,
    machine_links: dict[str, list[tuple[int, str]]],
) -> str | None:
    """Get IP address with mask for a machine in a specific link."""
    mask = subnet.split("/")[1] if "/" in subnet else "24"
    base_ip = subnet.split("/")[0].rsplit(".", 1)[0]

    links_for_machine = machine_links.get(machine_name, [])
    position = 1
    for m_link_idx, _ in links_for_machine:
        if m_link_idx == link_idx:
            break
        position += 1

    return f"{base_ip}.{position}/{mask}"


def validate_topology(topology: TopologyDefinition) -> list[str]:
    """Validate a topology definition and return any errors.

    Args:
        topology: Topology definition to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    import re

    errors = []

    machines = topology.get("machines", {})
    links = topology.get("links", [])

    if not machines:
        errors.append("Topology must define at least one machine")

    # Check all machines in links exist
    for idx, link in enumerate(links):
        link_machines = link.get("machines", [])
        for machine in link_machines:
            if isinstance(machine, dict):
                name = machine.get("name", "")
            else:
                name = machine

            if name and name not in machines:
                errors.append(f"Link {idx} references undefined machine: {name}")

    # Validate subnet formats
    cidr_pattern = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}$")

    for idx, link in enumerate(links):
        subnet = link.get("subnet", "")
        if subnet and not cidr_pattern.match(subnet):
            errors.append(f"Link {idx} has invalid subnet format: {subnet}")

    # Check images are Kathara images (warning only)
    for name, config in machines.items():
        image = config.get("image", DEFAULT_IMAGE)
        if not image.startswith("kathara/"):
            logger.warning(
                f"Machine {name} uses non-Kathara image: {image}. "
                "Consider using kathara/* images for consistency."
            )

    return errors


def get_image_info(image: str) -> dict[str, Any]:
    """Get configuration info for a Kathara image.

    Args:
        image: Image name (e.g., "kathara/frr")

    Returns:
        Image configuration dict with services, startup_delay, routing_capable
    """
    return IMAGE_CONFIGS.get(image, IMAGE_CONFIGS[DEFAULT_IMAGE])


def write_compose_file(
    lab_path: Path,
    lab_name: str,
    output_path: Path | None = None,
) -> Path:
    """Generate compose.yaml from lab.conf and write to file.

    Args:
        lab_path: Path to lab directory containing lab.conf
        lab_name: Lab name for the compose file
        output_path: Output path (defaults to lab_path/compose.yaml)

    Returns:
        Path to the written compose.yaml file
    """
    lab_conf_path = lab_path / "lab.conf"
    if not lab_conf_path.exists():
        raise FileNotFoundError(f"lab.conf not found at {lab_conf_path}")

    content = generate_compose_from_lab_conf(lab_conf_path, lab_name)

    if output_path is None:
        output_path = lab_path / "compose.yaml"

    output_path.write_text(content)
    logger.info(f"Generated compose.yaml at {output_path}")

    return output_path

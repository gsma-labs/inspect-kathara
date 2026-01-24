# inspect-kathara

Kathara network lab integration for [Inspect AI](https://inspect.aisi.org.uk/) evaluations.

This package converts [Kathara](https://www.kathara.org/) lab configurations into Docker Compose format, enabling network topology-based AI agent evaluations using Inspect AI's Docker sandbox.

## Installation

```bash
pip install inspect-kathara
```

Or with uv:

```bash
uv add inspect-kathara
```

## Quick Start

### 1. Generate Docker Compose from Kathara lab.conf

```python
from pathlib import Path
from inspect_kathara import write_compose_for_lab

# Generate compose.yaml from existing lab.conf
lab_path = Path("./my_lab")
write_compose_for_lab(lab_path)
```

### 2. Use with Inspect AI

```python
from inspect_ai import Task, task
from inspect_ai.dataset import Sample

@task
def network_troubleshoot() -> Task:
    return Task(
        dataset=[
            Sample(
                input="Diagnose and fix the network issue",
                sandbox=("docker", "./my_lab/compose.yaml"),
            )
        ],
        # ... solver and scorer
    )
```

## API Reference

### Core Functions

#### `write_compose_for_lab(lab_path, output_path=None, startup_configs=None, default_machine=None)`

Generate and write `compose.yaml` from a Kathara lab configuration.

**Parameters:**
- `lab_path`: Path to directory containing `lab.conf`
- `output_path`: Output path (defaults to `lab_path/compose.yaml`)
- `startup_configs`: Optional dict of machine -> startup script overrides
- `default_machine`: Machine to use as Inspect's default sandbox

**Returns:** Path to the generated compose.yaml

#### `generate_compose_for_inspect(lab_path, **kwargs)`

Generate compose content as string without writing to file.

#### `parse_lab_conf(lab_conf_path)`

Parse a Kathara lab.conf file into a `LabConfig` dataclass.

**Returns:** `LabConfig` with `machines` dict and `metadata` dict

### Utility Functions

```python
from inspect_kathara import (
    get_machine_service_mapping,  # Get machine -> Docker service name mapping
    estimate_startup_time,        # Estimate lab startup time in seconds
    get_frr_services,             # Get list of FRR router services
    get_image_config,             # Get config for a Kathara image
    is_routing_image,             # Check if image is a router
    has_vtysh,                    # Check if image has vtysh CLI
    IMAGE_CONFIGS,                # Dict of all Kathara image configurations
)
```

## Supported Kathara Images

| Image | Description | Routing | vtysh |
|-------|-------------|---------|-------|
| `kathara/base` | Base Debian with network tools | No | No |
| `kathara/frr` | FRRouting (BGP, OSPF, IS-IS) | Yes | Yes |
| `kathara/quagga` | Quagga routing suite | Yes | Yes |
| `kathara/openbgpd` | OpenBGPD daemon | Yes | No |
| `kathara/bird` | BIRD routing daemon | Yes | No |
| `kathara/bind` | BIND DNS server | No | No |
| `kathara/sdn` | OpenVSwitch + SDN | No | No |
| `kathara/p4` | P4 programmable switches | No | No |
| `kathara/scion` | SCION architecture | No | No |

## Examples

See the [`examples/`](./examples/) directory for complete evaluation examples:

- **`router_troubleshoot/`** - Network troubleshooting evaluation with 15 fault injection scenarios

## Requirements

- Python 3.10+
- Docker Desktop or OrbStack (for running sandboxes)
- Inspect AI >= 0.3.0

## License

MIT License - see [LICENSE](./LICENSE) for details.

## Related Projects

- [Inspect AI](https://inspect.aisi.org.uk/) - AI evaluation framework
- [Kathara](https://www.kathara.org/) - Network emulation tool
- [inspect-kathara-environment](https://github.com/otelcos/inspect-kathara-environment) - NIKA evaluations using this library

# inspect-kathara

Kathara network lab integration for [Inspect AI](https://inspect.aisi.org.uk/) evaluations.

This package converts [Kathara](https://www.kathara.org/) lab configurations into Docker Compose format and registers a **kathara** sandbox type with Inspect AI, enabling network topology-based AI agent evaluations with conservative concurrency and serialized container startup.

## Installation

```bash
pip install inspect-kathara
```

Or with uv:

```bash
uv add inspect-kathara
```

Optional: install the `memory` extra for automatic concurrency scaling based on system RAM (recommended for production):

```bash
pip install inspect-kathara[memory]
```

## Quick Start

### 1. Generate Docker Compose from Kathara lab

`lab_path` must be a directory containing `topology/lab.conf`:

```python
from pathlib import Path
from inspect_kathara import write_compose_for_lab

lab_path = Path("./my_lab")  # my_lab/topology/lab.conf must exist
write_compose_for_lab(lab_path)  # writes my_lab/compose.yaml
```

### 2. Use with Inspect AI

You can use either the generic **docker** sandbox (path to compose file or directory containing `compose.yaml`) or the **kathara** sandbox type, which adds memory-based concurrency limits and serialized startup:

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

In YAML datasets, the kathara sandbox is specified as:

```yaml
samples:
  - id: my_sample
    sandbox: [kathara, "path/to/compose.yaml"]
```

The **kathara** sandbox is functionally the same as **docker** but defaults to serial or low concurrency (1–2) and serializes container startup to avoid overwhelming Docker when many Kathara stacks run in parallel.

## API Reference

### Core Functions

#### `write_compose_for_lab(lab_path, output_path=None, startup_configs=None, default_machine=None, subnet_base=None, startup_pattern=None)`

Generate and write `compose.yaml` from a Kathara lab configuration.

**Parameters:**

- **lab_path**: Path to directory containing `topology/lab.conf`
- **output_path**: Output path (defaults to `lab_path/compose.yaml`)
- **startup_configs**: Optional dict of machine name → startup script content (overrides files)
- **default_machine**: Optional machine name to use as the default service
- **subnet_base**: Reserved for future use
- **startup_pattern**: Pattern for startup file path relative to `lab_path`, with `{name}` placeholder (default: `topology/{name}.startup`)

**Returns:** Path to the generated `compose.yaml`.

#### `generate_compose_for_inspect(lab_path, startup_configs=None, default_machine=None, startup_pattern=None)`

Generate compose YAML as a string without writing to disk. Same parameters as above (except `output_path` and `subnet_base`).

#### `parse_lab_conf(lab_conf_path)`

Parse a Kathara `lab.conf` file.

**Returns:** `LabConfig` with `machines: dict[str, MachineConfig]` and `metadata: dict[str, str]`.

### Utility Functions

```python
from inspect_kathara import (
    get_machine_service_mapping,  # machine name → Docker service name
    estimate_startup_time,        # estimated lab startup time in seconds
    get_frr_services,             # list of FRR router service names
    get_image_config,            # config dict for a Kathara image
    is_routing_image,            # whether image is routing-capable
    has_vtysh,                   # whether image has vtysh CLI
    validate_kathara_image,       # validate/pull/build image; returns image name
    IMAGE_CONFIGS,               # dict of all known image configs
    LabConfig,                    # dataclass for parsed lab
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
| `kathara/sdn` | OpenVSwitch + SDN | Yes | No |
| `kathara/p4` | P4 programmable switches | Yes | No |
| `kathara/scion` | SCION architecture | No | No |
| `kathara/nika-base` | NIKA base image | No | No |
| `kathara/nika-frr` | NIKA FRR image | Yes | Yes |
| `kathara/nika-wireguard` | NIKA WireGuard | No | No |
| `kathara/nika-ryu` | NIKA Ryu controller | Yes | No |
| `kathara/nika-influxdb` | NIKA InfluxDB | No | No |

## Project Structure

- **`src/inspect_kathara/`** – Main package: `sandbox.py` (compose generation + Kathara sandbox env), `_util.py` (lab parsing, image configs), `compose_generator.py` (low-level compose from lab.conf/topology dict).
- **`src/images/`** – Dockerfiles for NIKA images (`nika-base`, `nika-frr`, `nika-nginx`, etc.).
- **`tests/`** – Pytest tests.
- **`examples/`** – Full Inspect AI evaluation examples.

## Examples

See the [`examples/`](./examples/) directory:

- **`router_troubleshoot/`** – Network troubleshooting evaluation with 15 fault-injection scenarios (iptables, sysctl, routing, etc.). See [examples/router_troubleshoot/README.md](./examples/router_troubleshoot/README.md) for topology and variants.

## Requirements

- Python 3.10+
- Docker (or OrbStack) for running sandboxes
- Inspect AI >= 0.3.0

## License

MIT License – see [LICENSE](./LICENSE) for details.

## Related Projects

- [Inspect AI](https://inspect.aisi.org.uk/) – AI evaluation framework
- [Kathara](https://www.kathara.org/) – Network emulation tool
- [inspect-kathara-environment](https://github.com/otelcos/inspect-kathara-environment) – NIKA evaluations using this library

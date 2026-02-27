# inspect-kathara

Run AI agent evaluations inside isolated network topologies. Test whether models can diagnose misconfigurations, fix routing issues, and troubleshoot connectivity—all in safe, reproducible Docker environments.

## What is this?

This package provides [Inspect AI](https://inspect.aisi.org.uk/) integration for Docker-based network sandboxes. You define a network topology with `compose.yaml`, and Inspect AI agents can execute commands across multiple containers.

## Why use this?

- **Network troubleshooting benchmarks** — Test whether AI agents can diagnose and fix real connectivity issues (missing routes, firewall rules, disabled forwarding)
- **Agent tool use in constrained environments** — Evaluate models that must systematically explore and modify multi-container setups
- **Reproducible multi-container scenarios** — Each evaluation runs in fresh, isolated containers with consistent initial state

## Requirements

- Python 3.10+
- Docker Desktop or OrbStack
- Inspect AI >= 0.3.0

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

### 1. Create a network topology

Create `compose.yaml` with your containers. The `default` service is where the agent starts:

```yaml
services:
  default:
    image: kathara/base
    hostname: pc1
    cap_add: [NET_ADMIN]
    networks: [lan]
    command: sh -c 'ip addr add 10.0.1.10/24 dev eth0 && sleep infinity'

  pc2:
    image: kathara/base
    hostname: pc2
    cap_add: [NET_ADMIN]
    networks: [lan]
    command: sh -c 'ip addr add 10.0.1.20/24 dev eth0 && sleep infinity'

networks:
  lan:
    driver: bridge
    internal: true
```

### 2. Create an evaluation task

You can use either the generic **docker** sandbox (path to compose file or directory containing `compose.yaml`) or the **kathara** sandbox type, which adds memory-based concurrency limits and serialized startup:

```python
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate
from inspect_ai.tool import bash

@task
def network_ping() -> Task:
    return Task(
        dataset=[
            Sample(
                input="Ping pc2 at 10.0.1.20",
                sandbox=("docker", "./compose.yaml"),
            )
        ],
        solver=generate(tools=[bash()]),
    )
```

### 3. Run it

```bash
inspect eval my_eval.py --model openai/gpt-4o
```

## Configuration

### Sandbox in dataset

Each sample specifies its sandbox as a tuple:

```python
Sample(
    input="Your prompt here",
    sandbox=("docker", "path/to/compose.yaml"),
)
```

### compose.yaml key fields

| Field | Purpose |
|-------|---------|
| `default` service | Where the agent starts (required) |
| `cap_add: [NET_ADMIN]` | Allows network configuration |
| `networks` | Defines isolated network segments |
| `internal: true` | Prevents external internet access |

### Accessing other containers

From your solver or tools, use Inspect's [`sandbox()` API](https://inspect.aisi.org.uk/sandboxing.html):

```python
from inspect_ai.util import sandbox

# Execute command on another container
result = await sandbox("pc2").exec(["ping", "-c", "1", "10.0.1.10"])

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

| Image | Description |
|-------|-------------|
| `kathara/base` | Debian with network tools (ping, ip, iptables) |
| `kathara/frr` | FRRouting (BGP, OSPF, IS-IS) |
| `kathara/quagga` | Quagga routing suite |
| `kathara/bind` | BIND DNS server |

## Known Limitations

- **Root containers** — Containers run as root by default to allow network configuration (`NET_ADMIN`). This is intentional for network tooling but may not suit all security requirements.
- **Docker bridge networking** — Network isolation uses Docker bridge mode, not hardware-level emulation. Packet timing and behavior may differ from physical networks.
- **Resource limits** — Large topologies (10+ containers) may hit Docker memory/CPU limits. Configure Docker Desktop resources accordingly.
- **No persistent state** — Containers are ephemeral. Any changes made during evaluation are lost when containers stop.

## Further Reading

- [Inspect AI Sandboxing](https://inspect.aisi.org.uk/sandboxing.html) — Full `sandbox()` API reference
- [Inspect AI Tools](https://inspect.aisi.org.uk/tools.html) — How to create custom tools with `@tool`
- [Kathara](https://www.kathara.org/) — The network emulation framework these images are based on

## License

MIT License — see [LICENSE](./LICENSE) for details.

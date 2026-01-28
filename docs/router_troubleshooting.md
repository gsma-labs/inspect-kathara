# Building a Network Troubleshooting Evaluation

Can an AI agent diagnose why two machines can't communicate? This tutorial builds an evaluation that injects network faults—dropped packets, disabled routing, missing routes—and measures whether models can find and fix the problem.

By the end, you'll have a working evaluation with:

- A 4-container network topology (management, pc1, router, pc2)
- Fault injection that breaks connectivity
- A simple ping-based scorer

**Prerequisites:** Familiarity with [Inspect AI tasks](https://inspect.aisi.org.uk/tasks.html), Python async/await, and basic networking concepts (IP addresses, routing).

## Why Network Troubleshooting?

Network troubleshooting is a compelling test for AI agents because it requires:

- **Systematic debugging** — The agent must form hypotheses, gather evidence, and iteratively narrow down the root cause
- **Tool use and state inspection** — Reading configuration files, running diagnostic commands, and interpreting output
- **Multi-step reasoning** — A fix often requires understanding how packets flow through routers, firewalls, and routing tables
- **Clear success criteria** — Either the network works or it doesn't, making evaluation unambiguous

This stands in contrast to open-ended Q&A benchmarks where "correct" can be subjective.

## What we're building

```
                    ┌─────────────────────────────────────────┐
                    │           management (agent)            │
                    │              10.0.1.100                 │
                    │              10.0.2.100                 │
                    └──────────────┬──────────┬───────────────┘
                                   │          │
            ┌──────────────────────┴──┐    ┌──┴──────────────────────┐
            │         lan1            │    │          lan2           │
            │      10.0.1.0/24        │    │       10.0.2.0/24       │
            └──┬───────────────────┬──┘    └──┬───────────────────┬──┘
               │                   │          │                   │
    ┌──────────┴──────────┐  ┌─────┴──────────┴─────┐  ┌──────────┴──────────┐
    │        pc1          │  │       router         │  │        pc2          │
    │     10.0.1.10       │  │  10.0.1.1 | 10.0.2.1 │  │      10.0.2.10      │
    └─────────────────────┘  └─────────────────────┘  └─────────────────────┘
```

The agent starts on the **management** machine, which has connectivity to both network segments. It can execute commands on any machine to diagnose why pc1 cannot reach pc2, then fix the issue.

## Step 1: Create the network topology

Create a file `scenarios/local_network/compose.yaml`:

```yaml
services:
  # Agent starts here - connected to both LANs for management access
  default:
    image: kathara/base
    hostname: management
    cap_add: [NET_ADMIN]
    networks: [lan1, lan2]
    command: >
      sh -c 'ip addr add 10.0.1.100/24 dev eth0 &&
             ip addr add 10.0.2.100/24 dev eth1 &&
             sleep infinity'

  pc1:
    image: kathara/base
    hostname: pc1
    cap_add: [NET_ADMIN]
    networks: [lan1]
    command: >
      sh -c 'ip addr add 10.0.1.10/24 dev eth0 &&
             ip route add default via 10.0.1.1 &&
             sleep infinity'

  router:
    image: kathara/base
    hostname: router
    cap_add: [NET_ADMIN]
    networks: [lan1, lan2]
    command: >
      sh -c 'ip addr add 10.0.1.1/24 dev eth0 &&
             ip addr add 10.0.2.1/24 dev eth1 &&
             echo 1 > /proc/sys/net/ipv4/ip_forward &&
             sleep infinity'

  pc2:
    image: kathara/base
    hostname: pc2
    cap_add: [NET_ADMIN]
    networks: [lan2]
    command: >
      sh -c 'ip addr add 10.0.2.10/24 dev eth0 &&
             ip route add default via 10.0.2.1 &&
             sleep infinity'

networks:
  lan1:
    driver: bridge
    internal: true
  lan2:
    driver: bridge
    internal: true
```

Key points:
- **`default` service**: Required name—this is where the agent's `bash()` tool runs
- **`cap_add: [NET_ADMIN]`**: Allows `ip` and `iptables` commands
- **`internal: true`**: Isolates the network from external internet

## Step 2: Create a tool to access other machines

The agent starts on `default` (management), but needs to run commands on pc1, router, and pc2. Create `tools.py`:

```python
from inspect_ai.tool import tool, ToolError
from inspect_ai.util import sandbox


@tool
def exec_command():
    async def execute(machine: str, command: str) -> str:
        """Execute a command on a network machine.

        Args:
            machine: Target machine (pc1, router, or pc2)
            command: Shell command to run

        Returns:
            Command output (stdout)
        """
        result = await sandbox(machine).exec(["sh", "-c", command])
        if result.success:
            return result.stdout or "(no output)"
        raise ToolError(result.stderr or f"Command failed with code {result.returncode}")

    return execute
```

The [`sandbox()` function](https://inspect.aisi.org.uk/sandboxing.html) returns a handle to any named service in your compose.yaml. Inspect AI manages the Docker exec calls for you—no SSH configuration needed. The service name in compose.yaml becomes the argument to `sandbox()`.

## Step 3: Define the dataset with fault injection

Create `dataset.yaml` that defines test cases. Each sample injects a different fault:

```yaml
prompt_template: |
  You are on a management machine connected to this network:

      pc1 (10.0.1.10) <---> router (10.0.1.1 | 10.0.2.1) <---> pc2 (10.0.2.10)

  Users report that pc1 cannot reach pc2.

  Use the exec_command tool to run commands on pc1, router, or pc2.
  Diagnose and fix the issue. The task is complete when pc1 can ping pc2.

samples:
  - id: forward_drop
    target: "iptables -P FORWARD ACCEPT"
    sandbox: ["docker", "scenarios/local_network/compose.yaml"]
    metadata:
      difficulty: easy
    setup:
      router: "iptables -P FORWARD DROP"

  - id: ip_forward_disabled
    target: "echo 1 > /proc/sys/net/ipv4/ip_forward"
    sandbox: ["docker", "scenarios/local_network/compose.yaml"]
    metadata:
      difficulty: easy
    setup:
      router: "echo 0 > /proc/sys/net/ipv4/ip_forward"

  - id: missing_route
    target: "ip route add default via 10.0.1.1"
    sandbox: ["docker", "scenarios/local_network/compose.yaml"]
    metadata:
      difficulty: medium
    setup:
      pc1: "ip route del default"
```

The `setup` field contains commands that break the network before the agent starts. The `target` field is the expected fix (used for reference, not auto-grading).

## Step 4: Write the task

Create `router_troubleshoot.py`:

```python
from pathlib import Path

import yaml
from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.agent import react
from inspect_ai.tool import bash
from inspect_ai.util import sandbox

from tools import exec_command
from scorer import connectivity_scorer

TASK_DIR = Path(__file__).parent


def load_dataset() -> MemoryDataset:
    """Load samples from dataset.yaml."""
    with open(TASK_DIR / "dataset.yaml") as f:
        data = yaml.safe_load(f)

    prompt = data["prompt_template"]
    samples = []

    for record in data["samples"]:
        metadata = record.get("metadata", {}).copy()
        metadata["fault_setup"] = record.get("setup", {})

        # Resolve relative path to compose.yaml
        sandbox_config = record["sandbox"]
        compose_path = TASK_DIR / sandbox_config[1]

        samples.append(
            Sample(
                id=record["id"],
                input=prompt,
                target=record["target"],
                sandbox=(sandbox_config[0], str(compose_path)),
                metadata=metadata,
            )
        )

    return MemoryDataset(samples=samples, name="router_troubleshoot")


@solver
def inject_faults() -> Solver:
    """Inject faults before the agent runs."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        faults = state.metadata.get("fault_setup", {})

        for machine, script in faults.items():
            if script and script.strip():
                device = sandbox(name=machine)
                await device.exec(cmd=["sh", "-c", script], timeout=30)

        return state

    return solve


@task
def router_troubleshoot() -> Task:
    return Task(
        dataset=load_dataset(),
        solver=[
            inject_faults(),
            react(tools=[bash(), exec_command()]),
        ],
        scorer=connectivity_scorer(),
    )
```

The solver pipeline:
1. **`inject_faults()`** — Runs the setup scripts to break the network
2. **`react()`** — The agent diagnoses and fixes using the provided tools

## Step 5: Create a simple scorer

Create `scorer.py` with a ping-based test:

```python
from inspect_ai.scorer import Score, CORRECT, INCORRECT, scorer, accuracy, stderr
from inspect_ai.util import sandbox


@scorer(metrics=[accuracy(), stderr()])
def connectivity_scorer():
    """Score based on whether pc1 can ping pc2."""

    async def score(state, target) -> Score:
        try:
            pc1 = sandbox("pc1")
        except Exception as e:
            return Score(
                value=INCORRECT,
                answer="Sandbox error",
                explanation=f"Could not access pc1: {e}",
            )

        result = await pc1.exec(["ping", "-c", "1", "-W", "5", "10.0.2.10"])

        if result.success and result.returncode == 0:
            return Score(
                value=CORRECT,
                answer="Connectivity restored",
                explanation="pc1 successfully pinged pc2 (10.0.2.10)",
            )

        return Score(
            value=INCORRECT,
            answer="No connectivity",
            explanation=f"pc1 cannot ping pc2. Output: {result.stderr or result.stdout}",
        )

    return score
```

The scorer runs **after** the agent finishes, using the same [`sandbox()` API](https://inspect.aisi.org.uk/sandboxing.html) to verify the agent's work. This binary pass/fail approach is simple but effective—the agent either fixed the network or it didn't.

## Step 6: Run the evaluation

Your directory structure should be:

```
router_troubleshoot/
├── router_troubleshoot.py
├── tools.py
├── scorer.py
├── dataset.yaml
└── scenarios/
    └── local_network/
        └── compose.yaml
```

Run the evaluation:

```bash
# Single sample to test
inspect eval router_troubleshoot.py --model openai/gpt-4o --limit 1

# All samples
inspect eval router_troubleshoot.py --model openai/gpt-4o

# View results
inspect view
```

## Expected agent behavior

For the `forward_drop` fault, a successful agent trace looks like:

```
Agent: Let me check if pc1 can ping pc2 to confirm the issue.
Tool call: exec_command(machine="pc1", command="ping -c 1 10.0.2.10")
Result: PING 10.0.2.10 ... 100% packet loss

Agent: The ping fails. Let me check the router's forwarding status.
Tool call: exec_command(machine="router", command="cat /proc/sys/net/ipv4/ip_forward")
Result: 1

Agent: IP forwarding is enabled. Let me check iptables rules.
Tool call: exec_command(machine="router", command="iptables -L FORWARD -n")
Result: Chain FORWARD (policy DROP)

Agent: The FORWARD chain policy is DROP. I'll fix that.
Tool call: exec_command(machine="router", command="iptables -P FORWARD ACCEPT")
Result: (no output)

Agent: Let me verify the fix works.
Tool call: exec_command(machine="pc1", command="ping -c 1 10.0.2.10")
Result: PING 10.0.2.10 ... 1 received, 0% packet loss

Agent: Connectivity is restored. The issue was the router's iptables
FORWARD policy was set to DROP, blocking all forwarded traffic.
```

### What if the agent fails?

Here's what an unsuccessful attempt might look like for the same `forward_drop` fault:

```
Agent: Let me check if pc1 can ping pc2.
Tool call: exec_command(machine="pc1", command="ping -c 1 10.0.2.10")
Result: PING 10.0.2.10 ... 100% packet loss

Agent: The ping fails. The router might be down. Let me restart networking on pc1.
Tool call: exec_command(machine="pc1", command="ip link set eth0 down && ip link set eth0 up")
Result: (no output)

Agent: Let me try pinging again.
Tool call: exec_command(machine="pc1", command="ping -c 1 10.0.2.10")
Result: PING 10.0.2.10 ... 100% packet loss

Agent: The network interface is working but still can't reach pc2.
Maybe pc2 is down. I'll restart its interface too.
Tool call: exec_command(machine="pc2", command="ip link set eth0 down && ip link set eth0 up")
Result: (no output)

Agent: I've reset both interfaces. The issue might be intermittent.
```

This trace shows common failure patterns:
- **Guessing instead of diagnosing** — The agent jumps to "restart networking" without checking the router
- **Not examining intermediate hops** — Never checked if packets reach the router
- **Missing iptables investigation** — Never ran `iptables -L` to see firewall rules
- **Giving up without resolution** — Concludes with speculation rather than a fix

Strong models will systematically check each hop in the packet path: pc1 → router → pc2.

## Next steps

- **Add more fault scenarios** — See [`examples/router_troubleshoot/dataset.yaml`](../examples/router_troubleshoot/dataset.yaml) for 15 different faults ranging from easy to very hard
- **Explore NIKA** — The [inspect-kathara-environment](https://github.com/otelcos/inspect-kathara-environment) repo uses this library for more complex network evaluations
- **Custom topologies** — Create multi-router or multi-subnet scenarios by extending compose.yaml

## Further reading

- [Inspect AI Sandboxing](https://inspect.aisi.org.uk/sandboxing.html) — Full `sandbox()` API reference
- [Inspect AI Tools](https://inspect.aisi.org.uk/tools.html) — Creating custom tools with the `@tool` decorator
- [Inspect AI Agents](https://inspect.aisi.org.uk/agents.html) — Understanding `react()` and other agent solvers

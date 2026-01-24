"""Router troubleshooting evaluation for Kathara sandbox.

This task tests whether an AI agent can diagnose and fix network
connectivity issues in various misconfiguration scenarios.

Topology (same for all bugs):
    pc1 (10.0.1.10) <---> router (10.0.1.1 | 10.0.2.1) <---> pc2 (10.0.2.10)
         [lan1]                                                [lan2]
"""

from pathlib import Path

import yaml
from inspect_ai import Task, task
from inspect_ai.agent import react
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import bash
from inspect_ai.util import sandbox

from scorer import router_fix_scorer
from tools import exec_command, read_file, write_file

_task_dir = Path(__file__).parent
_DATASET_PATH = _task_dir / "dataset.yaml"
_SCENARIOS_DIR = _task_dir / "scenarios"


def _resolve_sandbox_path(sandbox: list) -> tuple:
    """Resolve sandbox config path to absolute path pointing to compose.yaml."""
    if not isinstance(sandbox, (list, tuple)) or len(sandbox) < 2:
        return tuple(sandbox) if isinstance(sandbox, (list, tuple)) else (sandbox,)

    sandbox_type = sandbox[0]
    config_path = sandbox[1]

    # Resolve relative to scenarios directory if not absolute
    path = Path(config_path)
    config_path = path if path.is_absolute() else _SCENARIOS_DIR / config_path

    # Docker sandbox expects path to compose.yaml, not directory
    if config_path.is_dir():
        config_path = config_path / "compose.yaml"

    return (sandbox_type, str(config_path.resolve()))


def load_dataset() -> MemoryDataset:
    """Load samples from dataset.yaml."""
    with open(_DATASET_PATH) as f:
        data = yaml.safe_load(f)

    prompt_template = data.get("prompt_template", "")
    samples = []

    for record in data["samples"]:
        metadata = record.get("metadata", {}).copy()
        # Store setup scripts in metadata for fault injection
        if record.get("setup"):
            metadata["fault_setup"] = record["setup"]

        samples.append(
            Sample(
                id=record["id"],
                input=prompt_template,
                target=record["target"],
                sandbox=_resolve_sandbox_path(record["sandbox"]),
                metadata=metadata,
            )
        )

    return MemoryDataset(samples=samples, name="router_troubleshoot")


@solver
def inject_faults() -> Solver:
    """Inject faults into network devices before agent runs."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        fault_setup = state.metadata.get("fault_setup", {})
        if not fault_setup:
            return state

        for device, script in fault_setup.items():
            if script and script.strip():
                # Run setup script on the target device
                device_sandbox = sandbox(name=device)
                await device_sandbox.exec(cmd=["sh", "-c", script], timeout=30)

        return state

    return solve


@task
def router_troubleshoot() -> Task:
    """Test if agent can diagnose and fix various router/network misconfigurations."""
    return Task(
        dataset=load_dataset(),
        solver=[
            inject_faults(),
            react(tools=[bash(timeout=300), exec_command(), read_file(), write_file()]),
        ],
        scorer=router_fix_scorer(),
    )

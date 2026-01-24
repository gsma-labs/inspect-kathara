"""Custom tools for router troubleshooting task."""

from inspect_ai.tool import tool, ToolError
from inspect_ai.util import sandbox


@tool
def exec_command():
    async def execute(machine: str, command: str):
        """Execute a command on a network machine.

        Args:
            machine: Target machine (pc1, router, or pc2)
            command: Bash command to run

        Returns:
            Command output
        """
        result = await sandbox(machine).exec(["bash", "-c", command])
        if result.success:
            return result.stdout
        raise ToolError(result.stderr)

    return execute


@tool
def read_file():
    async def execute(machine: str, path: str):
        """Read a file from a network machine.

        Args:
            machine: Target machine (pc1, router, or pc2)
            path: File path to read

        Returns:
            File contents
        """
        return await sandbox(machine).read_file(path)

    return execute


@tool
def write_file():
    async def execute(machine: str, path: str, content: str):
        """Write a file to a network machine.

        Args:
            machine: Target machine (pc1, router, or pc2)
            path: File path to write
            content: Content to write

        Returns:
            Success message
        """
        await sandbox(machine).write_file(path, content)
        return f"Wrote to {path} on {machine}"

    return execute

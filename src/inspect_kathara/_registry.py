"""Entry point registration for Inspect AI plugin discovery.

Note: This package uses Inspect's native DockerSandboxEnvironment,
not a custom sandbox type. The compose.yaml generator converts Kathara
lab.conf files to Docker Compose format.

This module exists for potential future extensions but currently
does not register any custom sandbox environments.

Usage:
    1. Generate compose.yaml from lab.conf:
       from inspect_kathara import write_compose_for_lab
       write_compose_for_lab(Path("./my_lab"))

    2. Use Inspect's Docker sandbox:
       sandbox=("docker", "./my_lab")
"""

__all__: list[str] = []

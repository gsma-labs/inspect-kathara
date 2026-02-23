# Patch content to add to sandbox.py after ROUTER_SYSCTLS:

class _LiteralStr(str):
    """String wrapper so PyYAML dumps it as a literal block scalar (|)."""


def _literal_str_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style="|")

# Register at module load:
yaml.add_representer(_LiteralStr, _literal_str_representer, Dumper=yaml.SafeDumper)

# In generate_compose_for_inspect, build command then wrap:
#   full_cmd = "".join(cmd_parts)  # or build string as now
#   service["command"] = _LiteralStr(full_cmd)
# And call yaml.dump(..., Dumper=yaml.SafeDumper)

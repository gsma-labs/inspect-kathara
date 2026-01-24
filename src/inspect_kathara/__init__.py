from __future__ import annotations

__version__ = "0.1.0"

_LAZY_IMPORTS = {
    "write_compose_for_lab": ("sandbox", "write_compose_for_lab"),
    "generate_compose_for_inspect": ("sandbox", "generate_compose_for_inspect"),
    "get_machine_service_mapping": ("sandbox", "get_machine_service_mapping"),
    "estimate_startup_time": ("sandbox", "estimate_startup_time"),
    "get_frr_services": ("sandbox", "get_frr_services"),
    "get_image_config": ("_util", "get_image_config"),
    "is_routing_image": ("_util", "is_routing_image"),
    "has_vtysh": ("_util", "has_vtysh"),
    "IMAGE_CONFIGS": ("_util", "IMAGE_CONFIGS"),
    "parse_lab_conf": ("_util", "parse_lab_conf"),
    "LabConfig": ("_util", "LabConfig"),
    "validate_kathara_image": ("_util", "validate_kathara_image"),
}


def __getattr__(name: str) -> object:
    if name not in _LAZY_IMPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module, attr = _LAZY_IMPORTS[name]
    from importlib import import_module
    return getattr(import_module(f"inspect_kathara.{module}"), attr)


__all__ = ["__version__", *_LAZY_IMPORTS.keys()]


def __dir__() -> list[str]:
    return __all__

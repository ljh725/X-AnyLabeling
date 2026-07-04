from typing import Any

from .app_info import __appdescription__, __appname__, __version__

__all__ = (
    "__version__",
    "__appname__",
    "__appdescription__",
    "checks",
    "convert",
    "list_supported_tasks",
    "SUPPORTED_TASKS",
)


def __getattr__(name: str) -> Any:
    """Load CLI helpers lazily so subpackages can stay import-light."""
    if name == "checks":
        from anylabeling.views.common.checks import run_checks

        return run_checks
    if name in {"convert", "list_supported_tasks", "SUPPORTED_TASKS"}:
        from anylabeling.views.common import converter

        if name == "convert":
            return converter.run_conversion
        return getattr(converter, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

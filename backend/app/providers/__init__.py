"""Provider registry.

Drivers are discovered by importing every module in this package, so adding a
new dialect is a single new file with a ``register_driver`` call at the bottom.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field

from app.providers.base import ModelInfo, Provider, ProviderConfig, ProviderError

__all__ = [
    "ModelInfo",
    "Provider",
    "ProviderConfig",
    "ProviderError",
    "build_provider",
    "driver_specs",
    "get_driver",
    "register_driver",
]


@dataclass(slots=True)
class DriverSpec:
    kind: str
    label: str
    description: str
    cls: type[Provider]
    supports_embeddings: bool = False
    requires_api_key: bool = True
    default_base_url: str = ""
    fields: list[str] = field(default_factory=list)


_DRIVERS: dict[str, DriverSpec] = {}


def register_driver(
    kind: str,
    label: str,
    description: str = "",
    *,
    cls: type[Provider],
    supports_embeddings: bool | None = None,
    requires_api_key: bool = True,
    default_base_url: str = "",
) -> None:
    _DRIVERS[kind] = DriverSpec(
        kind=kind,
        label=label,
        description=description,
        cls=cls,
        supports_embeddings=(
            getattr(cls, "supports_embeddings", False)
            if supports_embeddings is None
            else supports_embeddings
        ),
        requires_api_key=requires_api_key,
        default_base_url=default_base_url,
    )


def _discover() -> None:
    if _DRIVERS:
        return
    for module in pkgutil.iter_modules(__path__):
        if module.name.startswith("_") or module.name == "base":
            continue
        importlib.import_module(f"{__name__}.{module.name}")


def driver_specs() -> list[dict]:
    _discover()
    return [
        {
            "kind": spec.kind,
            "label": spec.label,
            "description": spec.description,
            "supports_embeddings": spec.supports_embeddings,
            "requires_api_key": spec.requires_api_key,
            "default_base_url": spec.default_base_url,
        }
        for spec in sorted(_DRIVERS.values(), key=lambda s: s.label)
    ]


def get_driver(kind: str) -> DriverSpec:
    _discover()
    spec = _DRIVERS.get(kind)
    if not spec:
        raise ProviderError(f"Unknown provider type '{kind}'.", 400)
    return spec


def build_provider(config: ProviderConfig) -> Provider:
    return get_driver(config.kind).cls(config)

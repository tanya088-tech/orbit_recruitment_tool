"""Maps a source name ("linkedin") to its class.

Adding Naukri/Indeed later = import the class and call register_source() below.
"""
from __future__ import annotations

from typing import Type

from collectors.base import JobSource
from collectors.linkedin.source import LinkedInSource
from collectors.naukri.source import NaukriSource

_REGISTRY: dict[str, Type[JobSource]] = {}


def register_source(cls: Type[JobSource]) -> Type[JobSource]:
    if not cls.name:
        raise ValueError(f"{cls.__name__} must define a `name`")
    _REGISTRY[cls.name] = cls
    return cls


def get_source(name: str, **kwargs) -> JobSource:
    try:
        return _REGISTRY[name.lower()](**kwargs)
    except KeyError:
        raise ValueError(f"Unknown source '{name}'. Available: {', '.join(available_sources())}")


def is_location_independent(name: str) -> bool:
    cls = _REGISTRY.get(str(name).lower())
    return bool(cls and getattr(cls, "location_independent", False))


def available_sources() -> list[str]:
    return sorted(_REGISTRY)


register_source(LinkedInSource)
register_source(NaukriSource)

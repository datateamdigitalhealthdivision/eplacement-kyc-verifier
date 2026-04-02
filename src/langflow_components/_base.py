"""Compatibility shims for using custom components with or without Langflow installed."""

from __future__ import annotations

try:
    from langflow.custom import Component  # type: ignore
except Exception:  # noqa: BLE001
    class Component:
        display_name = "Component"
        description = "Fallback component base."
        name = "Component"

        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

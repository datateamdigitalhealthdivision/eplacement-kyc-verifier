"""Confidence scoring helpers."""

from __future__ import annotations

from statistics import mean
from typing import Iterable


def average_confidence(values: Iterable[float | None], default: float = 0.0) -> float:
    clean = [value for value in values if value is not None]
    return round(mean(clean), 4) if clean else default


def flag_low_confidence(score: float | None, threshold: float) -> bool:
    return score is None or score < threshold

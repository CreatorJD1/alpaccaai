"""Typed latest-value observation slots with explicit provenance."""

from __future__ import annotations

from dataclasses import dataclass
import math
from threading import RLock
import time
from types import MappingProxyType
from typing import Any, Callable, Generic, Mapping, TypeVar


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ObservationProvenance:
    source: str
    event_id: str | None
    metadata: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Observation(Generic[T]):
    value: T
    version: int
    observed_at: float
    published_at: float
    received_monotonic: float
    provenance: ObservationProvenance


@dataclass(frozen=True, slots=True)
class PublishResult(Generic[T]):
    accepted: bool
    observation: Observation[T] | None
    current: Observation[T] | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ObserverSlotStatus(Generic[T]):
    observation: Observation[T] | None
    age_seconds: float | None
    stale: bool | None


class ObserverSlot(Generic[T]):
    """Stores the newest observation for one runtime-checked value type."""

    def __init__(
        self,
        value_type: type[T] | tuple[type[Any], ...],
        *,
        wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(value_type, type) and not (
            isinstance(value_type, tuple)
            and bool(value_type)
            and all(isinstance(item, type) for item in value_type)
        ):
            raise TypeError("value_type must be a type or non-empty tuple of types")
        self._value_type = value_type
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock
        self._latest: Observation[T] | None = None
        self._version = 0
        self._lock = RLock()

    def publish(
        self,
        value: T,
        *,
        source: str,
        observed_at: float | None = None,
        event_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> PublishResult[T]:
        if not isinstance(value, self._value_type):
            raise TypeError(
                f"value must be an instance of {self._type_name(self._value_type)}"
            )
        source = self._required_text(source, "source")
        if event_id is not None:
            event_id = self._required_text(event_id, "event_id")
        published_at = self._clock_value(self._wall_clock, "wall_clock")
        received_monotonic = self._clock_value(
            self._monotonic_clock, "monotonic_clock"
        )
        if observed_at is None:
            observed_at = published_at
        observed_at = self._timestamp(observed_at, "observed_at")
        provenance = ObservationProvenance(
            source=source,
            event_id=event_id,
            metadata=MappingProxyType(dict(metadata or {})),
        )

        with self._lock:
            if self._latest is not None and observed_at < self._latest.observed_at:
                return PublishResult(
                    accepted=False,
                    observation=None,
                    current=self._latest,
                    reason="out_of_order",
                )
            self._version += 1
            observation = Observation(
                value=value,
                version=self._version,
                observed_at=observed_at,
                published_at=published_at,
                received_monotonic=received_monotonic,
                provenance=provenance,
            )
            self._latest = observation
            return PublishResult(True, observation, observation)

    def read(self) -> Observation[T] | None:
        with self._lock:
            return self._latest

    def read_fresh(
        self,
        max_age_seconds: float,
        *,
        now: float | None = None,
    ) -> Observation[T] | None:
        status = self.status(max_age_seconds=max_age_seconds, now=now)
        if status.stale is False:
            return status.observation
        return None

    def status(
        self,
        *,
        max_age_seconds: float | None = None,
        now: float | None = None,
    ) -> ObserverSlotStatus[T]:
        if max_age_seconds is not None:
            max_age_seconds = self._timestamp(
                max_age_seconds, "max_age_seconds"
            )
        current = (
            self._clock_value(self._monotonic_clock, "monotonic_clock")
            if now is None
            else self._timestamp(now, "now")
        )
        with self._lock:
            if self._latest is None:
                return ObserverSlotStatus(None, None, None)
            age = max(0.0, current - self._latest.received_monotonic)
            stale = None if max_age_seconds is None else age > max_age_seconds
            return ObserverSlotStatus(self._latest, age, stale)

    def clear(self, *, expected_version: int | None = None) -> Observation[T] | None:
        if expected_version is not None and expected_version <= 0:
            raise ValueError("expected_version must be positive")
        with self._lock:
            if self._latest is None:
                return None
            if (
                expected_version is not None
                and self._latest.version != expected_version
            ):
                return None
            previous = self._latest
            self._latest = None
            return previous

    @staticmethod
    def _clock_value(clock: Callable[[], float], name: str) -> float:
        return ObserverSlot._timestamp(clock(), name)

    @staticmethod
    def _timestamp(value: float, name: str) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a finite, non-negative number") from exc
        if not math.isfinite(result) or result < 0:
            raise ValueError(f"{name} must be a finite, non-negative number")
        return result

    @staticmethod
    def _required_text(value: str, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be non-empty")
        return value.strip()

    @staticmethod
    def _type_name(value_type: type[Any] | tuple[type[Any], ...]) -> str:
        if isinstance(value_type, tuple):
            return " or ".join(item.__name__ for item in value_type)
        return value_type.__name__

"""Grounded overload / read-the-room signal (Lane Q foundation).

A companion who is talking to five people at once, near the top of her context
window, on a host that is running low on memory, is *under load* -- and a
genuinely present one would read that room and ease off. This module computes
that read, and it computes it the honest way: purely from **real measured cues**,
citing the evidence each came from, and leaving anything it cannot measure as an
explicit ``unknown`` rather than a fabricated zero.

The four cues are all things Alpecca already measures elsewhere:

  - **message volume** -- how much is being said at her right now (turn/message
    count in a recent window; the real request lifecycle, not a mandatory delay);
  - **concurrent actors** -- how many distinct people/sessions are active at once;
  - **context pressure** -- how full her working context is
    (alpecca/context_tier_measurement.py / memory_pressure.py);
  - **host pressure** -- how stressed the machine is
    (alpecca/system_pressure.py commit/disk headroom).

WHAT THIS IS NOT. This is **not an emotion**, and it is emphatically not a claim
of suffering. It is a workload/pressure indicator -- the same grounding rule that
governs her affect (alpecca/affect.py, affect_evidence.py) governs this: every
number is traceable to a real reading, and if the evidence isn't there the
signal says so. It mirrors the read-only projection shape of
:func:`alpecca.system_pressure.propose_pagefile_plan`: a typed value plus the
exact evidence it was derived from, with ``unknown`` preserved end to end.

It does **not** mutate affect, identity, or the hot path. A later, separately
owned integration may let a *high, evidenced* reading SUGGEST a calmer response
style through the existing Phase 4/5 envelope (a cue, never an override). That
wiring is an integration request, not part of this module.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal


SCHEMA = "alpecca.overload.read-the-room.v1"

# This signal describes measured workload, never inner experience. The string is
# surfaced with every assessment so no downstream reader can mistake it for one.
KIND = "workload_pressure"
DISCLAIMER = (
    "Measured workload/pressure from real cues; not an emotion or a claim of "
    "suffering."
)

CueState = Literal["known", "unknown", "invalid"]
Band = Literal["low", "elevated", "high", "unknown"]

# --- Policy (code-owned normalization thresholds) ---------------------------
# Each cue is normalized to a 0..1 "load contribution". The thresholds below are
# the saturating points: at/above them the cue reads as fully loaded. They are
# deliberately conservative and live in code so configuration cannot silently
# inflate a calm reading into a stressed one.

# Messages within the window at which volume reads as fully loaded.
MESSAGE_VOLUME_SATURATION = 12
# One actor is her normal one-to-one baseline (no added load). Each additional
# concurrent actor adds load; this many *extra* actors saturates the cue.
CONCURRENT_ACTOR_SATURATION_EXTRA = 4
# Bands over the combined 0..1 value.
ELEVATED_BAND_THRESHOLD = 0.45
HIGH_BAND_THRESHOLD = 0.75

# Relative weight of each cue when combining known contributions. Host and
# context pressure weigh a little heavier because they are hard resource limits;
# message volume and actor count are interaction load. Weights only ever combine
# *known* cues -- an unknown cue is dropped, never treated as zero load.
_CUE_WEIGHTS: Mapping[str, float] = {
    "message_volume": 1.0,
    "concurrent_actors": 1.0,
    "context_pressure": 1.2,
    "host_pressure": 1.2,
}
CUE_NAMES: tuple[str, ...] = tuple(_CUE_WEIGHTS.keys())


@dataclass(frozen=True, slots=True)
class OverloadCue:
    """One normalized load contribution and the real reading behind it.

    ``state`` is ``known`` only when a real measurement was supplied; a missing
    or malformed reading is ``unknown`` (or ``invalid``) and contributes nothing.
    ``normalized`` is the 0..1 load for a known cue and ``None`` otherwise.
    ``evidence`` records the raw reading so the assessment can cite it.
    """

    name: str
    state: CueState
    normalized: float | None
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "normalized": self.normalized,
            "evidence": dict(self.evidence),
        }


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return int(number)


def _unknown_cue(name: str, reason: str) -> OverloadCue:
    return OverloadCue(
        name=name, state="unknown", normalized=None, evidence={"reason": reason}
    )


def _invalid_cue(name: str, reason: str) -> OverloadCue:
    return OverloadCue(
        name=name, state="invalid", normalized=None, evidence={"reason": reason}
    )


# --- Cue builders (adapt real measured readings; unknown stays unknown) -----


def message_volume_cue(
    message_count: object, window_seconds: object
) -> OverloadCue:
    """Load from how many messages arrived in a recent real window.

    ``message_count`` is a real count of turns/messages observed in the last
    ``window_seconds``. Either missing/negative reading yields an unknown cue --
    never an assumed-quiet zero.
    """
    count = _nonnegative_int(message_count)
    window = _finite_number(window_seconds)
    if count is None:
        return _unknown_cue("message_volume", "message_count_unavailable")
    if window is None or window <= 0:
        return _unknown_cue("message_volume", "window_unavailable")
    normalized = _clamp01(count / MESSAGE_VOLUME_SATURATION)
    return OverloadCue(
        name="message_volume",
        state="known",
        normalized=normalized,
        evidence={
            "message_count": count,
            "window_seconds": window,
            "saturation_count": MESSAGE_VOLUME_SATURATION,
        },
    )


def concurrent_actor_cue(active_actors: object) -> OverloadCue:
    """Load from how many distinct people/sessions are active at once.

    One actor is her normal one-to-one baseline (zero added load). Zero actors is
    also zero load (no one is here). A missing count is unknown, not zero.
    """
    actors = _nonnegative_int(active_actors)
    if actors is None:
        return _unknown_cue("concurrent_actors", "actor_count_unavailable")
    extra = max(0, actors - 1)
    normalized = _clamp01(extra / CONCURRENT_ACTOR_SATURATION_EXTRA)
    return OverloadCue(
        name="concurrent_actors",
        state="known",
        normalized=normalized,
        evidence={
            "active_actors": actors,
            "baseline_actors": 1,
            "saturation_extra": CONCURRENT_ACTOR_SATURATION_EXTRA,
        },
    )


def context_pressure_cue(fraction: object) -> OverloadCue:
    """Load from how full her working context is, as a real 0..1 fraction.

    ``fraction`` is a measured used/limit ratio (e.g. from
    context_tier_measurement / memory_pressure). Out-of-range or missing values
    are rejected rather than clamped-into-meaning: a missing measurement is
    unknown, an impossible one is invalid.
    """
    value = _finite_number(fraction)
    if value is None:
        return _unknown_cue("context_pressure", "context_fraction_unavailable")
    if value < 0.0 or value > 1.0:
        return _invalid_cue("context_pressure", "context_fraction_out_of_range")
    return OverloadCue(
        name="context_pressure",
        state="known",
        normalized=value,
        evidence={"used_fraction": value},
    )


def host_pressure_cue(headroom_fraction: object) -> OverloadCue:
    """Load from real host resource headroom (low headroom == high load).

    ``headroom_fraction`` is the smallest measured free-resource fraction across
    the host (commit/disk); load is ``1 - headroom``. Missing headroom is
    unknown; an out-of-range value is invalid. See
    :func:`host_pressure_cue_from_measurement` to derive this from
    alpecca/system_pressure.py directly.
    """
    value = _finite_number(headroom_fraction)
    if value is None:
        return _unknown_cue("host_pressure", "host_headroom_unavailable")
    if value < 0.0 or value > 1.0:
        return _invalid_cue("host_pressure", "host_headroom_out_of_range")
    normalized = _clamp01(1.0 - value)
    return OverloadCue(
        name="host_pressure",
        state="known",
        normalized=normalized,
        evidence={"headroom_fraction": value},
    )


def host_pressure_cue_from_measurement(measurement: object) -> OverloadCue:
    """Adapt an :func:`alpecca.system_pressure.measure_host_pressure` result.

    Reads the commit/disk headroom fractions the Phase 6/7 sampler reports and
    takes the *worst* (smallest) known headroom as the host load evidence. If
    neither resource is known, the cue stays unknown -- exactly the fail-closed
    behavior system_pressure itself uses.
    """
    if not isinstance(measurement, Mapping):
        return _unknown_cue("host_pressure", "measurement_unavailable")
    headroom = measurement.get("headroom")
    fractions: list[float] = []
    if isinstance(headroom, Mapping):
        for key in ("commit_fraction", "disk_fraction"):
            value = _finite_number(headroom.get(key))
            if value is not None and 0.0 <= value <= 1.0:
                fractions.append(value)
    if not fractions:
        return _unknown_cue("host_pressure", "host_headroom_unavailable")
    return host_pressure_cue(min(fractions))


def _band(value: float) -> Band:
    if value >= HIGH_BAND_THRESHOLD:
        return "high"
    if value >= ELEVATED_BAND_THRESHOLD:
        return "elevated"
    return "low"


def assess_overload(
    *,
    message_volume: OverloadCue | None = None,
    concurrent_actors: OverloadCue | None = None,
    context_pressure: OverloadCue | None = None,
    host_pressure: OverloadCue | None = None,
) -> dict[str, Any]:
    """Combine the real cues into one grounded, evidence-cited overload read.

    Only ``known`` cues contribute; the combined value is the weighted mean of
    their normalized loads. If *no* cue is known the assessment is ``unknown``
    with ``value = None`` (never a fabricated calm). ``invalid`` cues are surfaced
    and excluded. The result carries the exact evidence per cue so a reader can
    always answer "what made this reading?" -- and carries ``kind`` /
    ``disclaimer`` so it can never be mistaken for a felt emotion.
    """
    supplied: dict[str, OverloadCue] = {}
    for name, cue in (
        ("message_volume", message_volume),
        ("concurrent_actors", concurrent_actors),
        ("context_pressure", context_pressure),
        ("host_pressure", host_pressure),
    ):
        if cue is None:
            supplied[name] = _unknown_cue(name, "cue_not_supplied")
        elif not isinstance(cue, OverloadCue):
            supplied[name] = _invalid_cue(name, "cue_not_overloadcue")
        elif cue.name != name:
            supplied[name] = _invalid_cue(name, "cue_name_mismatch")
        else:
            supplied[name] = cue

    known = {
        name: cue
        for name, cue in supplied.items()
        if cue.state == "known" and cue.normalized is not None
    }
    invalid = [name for name, cue in supplied.items() if cue.state == "invalid"]
    unknown = [name for name, cue in supplied.items() if cue.state == "unknown"]

    if known:
        weight_total = sum(_CUE_WEIGHTS[name] for name in known)
        value = _clamp01(
            sum(
                _CUE_WEIGHTS[name] * float(cue.normalized)
                for name, cue in known.items()
            )
            / weight_total
        )
        band: Band = _band(value)
        if len(known) == len(supplied):
            state = "known"
        else:
            state = "partial"
    else:
        value = None
        band = "unknown"
        state = "unknown"

    # The evidence list is the heart of the grounding: every cue, its state, and
    # the real reading (or the reason it is missing) it contributed.
    evidence = [supplied[name].as_dict() for name in CUE_NAMES]

    reasons: list[str] = []
    if state == "unknown":
        reasons.append("no_known_cue_evidence")
    if invalid:
        reasons.append("invalid_cue_evidence")
    if state == "partial":
        reasons.append("partial_cue_evidence")
    if band == "high":
        reasons.append("high_measured_load")

    return {
        "schema": SCHEMA,
        "kind": KIND,
        "disclaimer": DISCLAIMER,
        "state": state,
        "value": None if value is None else round(value, 4),
        "band": band,
        "known_cues": sorted(known),
        "unknown_cues": sorted(unknown),
        "invalid_cues": sorted(invalid),
        "evidence": evidence,
        "reasons": reasons,
        "policy": {
            "message_volume_saturation": MESSAGE_VOLUME_SATURATION,
            "concurrent_actor_saturation_extra": CONCURRENT_ACTOR_SATURATION_EXTRA,
            "elevated_band_threshold": ELEVATED_BAND_THRESHOLD,
            "high_band_threshold": HIGH_BAND_THRESHOLD,
        },
    }


__all__ = [
    "Band",
    "CUE_NAMES",
    "CueState",
    "DISCLAIMER",
    "KIND",
    "OverloadCue",
    "SCHEMA",
    "assess_overload",
    "concurrent_actor_cue",
    "context_pressure_cue",
    "host_pressure_cue",
    "host_pressure_cue_from_measurement",
    "message_volume_cue",
]

# -*- coding: utf-8 -*-
"""
data_certify/results.py -- Shared result dataclasses used by every axis
module and by decision.py.

Kept in their own module (rather than defined once per axis file) so that
axis_authenticity.py, axis_plausibility.py, axis_completeness.py and
axis_instrumentation.py can all produce a uniform, JSON-serialisable shape
without importing from each other.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SubTestResult:
    """
    Result of a single named sub-test (e.g. "A1", "P6", "C3", "I5").

    `applicable=False` means the required input fields were not present in
    the dataset (e.g. no seismic_moment_n_m column for P6) -- this is
    reported explicitly, never silently folded into a passing or failing
    score, so a downstream reader can tell "this test found no problem"
    apart from "this test could not run."
    """
    name: str
    score: float                 # in [0,1]; NaN if not computable even though applicable
    applicable: bool = True
    detail: Dict[str, Any] = field(default_factory=dict)
    note: str = ""
    # Effective weight of this sub-test in the overall T(D) composite for
    # THIS audit, i.e. axis_weight * within_axis_weight as calibrated (main
    # framework Section 5, WITHIN_* tables in _constants.py) -- set by
    # `decision.py::_assign_effective_weights` once the parent AxisResult's
    # axis is known, NOT by the individual score_* functions themselves.
    # None for P1-P3 (Stage-1 hard-gate sub-tests, which are not part of the
    # weighted compensatory sum at all -- see axis_plausibility.py's module
    # docstring).
    #
    # For every sub-test EXCEPT A1-A6, this is a fixed NOMINAL calibrated
    # weight, unaffected by per-audit renormalisation when a test is
    # inapplicable (see 3.4/3.5 review discussion) -- it answers "how much
    # does this sub-test matter by design", not "how much did it end up
    # mattering in this specific audit run once inapplicable tests were
    # renormalised away".
    #
    # DOCUMENTATION FIX (2026-07-21, found by external review): for A1-A6
    # specifically, this is NOT a fixed nominal value -- it now varies
    # per-audit. A6, when it externally corroborates records, *substitutes*
    # for A1-A5 on a per-record basis rather than sitting alongside them at
    # a fixed nominal share (see `decision.py::_assign_effective_weights`'s
    # docstring for the full rationale), so A6's `effective_weight` (and,
    # correspondingly, A1-A5's) is allocated across A6 and (A1-A5) in
    # proportion to how many records each stratum actually covers in THIS
    # audit -- it can range from 0 (no live/local A6 reference configured,
    # A1-A5 keep their full nominal share) up to nearly all of axis A's
    # weight (A6 covers ~all records with strong corroboration). This
    # answers "how much did this sub-test actually matter in this specific
    # audit", which for A1-A6 is no longer the same question as "how much
    # does it matter by design" -- the two only coincide when A6 has no
    # reference to check against.
    effective_weight: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "score": None if (isinstance(self.score, float) and math.isnan(self.score)) else self.score,
            "applicable": self.applicable,
            "detail": _json_safe(self.detail),
            "note": self.note,
            "effective_weight": self.effective_weight,
        }


@dataclass
class AxisResult:
    """Aggregate result for one of the four axes: A(D), P(D), C(D), I(D)."""
    axis: str                     # "A" | "P" | "C" | "I"
    score: float                  # weighted composite for this axis, in [0,1]
    sub_results: Dict[str, SubTestResult]
    mode: str = ""                 # e.g. "intrinsic" / "external" for A; "" otherwise
    notes: List[str] = field(default_factory=list)
    hard_reject: bool = False      # True if this axis independently triggered a hard override
    hard_reject_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "axis": self.axis,
            "score": None if (isinstance(self.score, float) and math.isnan(self.score)) else self.score,
            "mode": self.mode,
            "sub_results": {k: v.to_dict() for k, v in self.sub_results.items()},
            "notes": list(self.notes),
            "hard_reject": self.hard_reject,
            "hard_reject_reason": self.hard_reject_reason,
        }

    def __str__(self) -> str:
        lines = [f"  {self.axis}(D) = {self.score:.4f}" if not math.isnan(self.score)
                 else f"  {self.axis}(D) = N/A"]
        if self.mode:
            lines[0] += f"   [{self.mode} mode]"
        for name, sub in sorted(self.sub_results.items()):
            mark = "-" if not sub.applicable else ("*" if math.isnan(sub.score) else " ")
            score_str = "n/a" if not sub.applicable or math.isnan(sub.score) else f"{sub.score:.3f}"
            if sub.effective_weight is None:
                weight_str = "hard gate"
            else:
                weight_str = f"eff.w={sub.effective_weight * 100:5.2f}%"
            lines.append(f"    [{mark}] {name:<4} score={score_str:<6} {weight_str:<15} {sub.note}")
        return "\n".join(lines)


def _json_safe(obj: Any) -> Any:
    """Recursively replace non-finite floats with None for JSON compatibility."""
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else obj
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj

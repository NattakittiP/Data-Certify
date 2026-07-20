# -*- coding: utf-8 -*-
"""
data_certify/stats.py -- Shared statistical primitives for the DATA-CERTIFY
audit battery.

Every function here is named after, and cited to, the published method it
implements (see the docstring of each function below for the citation).
This module exists so that no formula is implemented twice, and so each
axis module (axis_authenticity.py, axis_plausibility.py, ...) can stay
focused on *which* test applies to *which* field, not on the underlying
statistics.

Functions and their governing citation:
    benford_chi_square            -- Hill (1995); Diekmann (2007)
    gr_b_value_aki                -- Aki (1965)
    gr_b_value_shi_bolt_se        -- Shi & Bolt (1982)
    fit_omori_utsu                -- Omori (1894); Utsu, Ogata & Matsu'ura (1995)
    ks_statistic_1sample          -- Kolmogorov (1933); Smirnov (1948)
    ks_statistic_2sample          -- Kolmogorov (1933); Smirnov (1948)
    correlation_dimension         -- Grassberger & Procaccia (1983);
                                      Kagan & Knopoff (1976, 1980)
    mann_kendall_test             -- Mann (1945); Kendall (1975)
    sen_slope                     -- Sen (1968)
    clopper_pearson_upper_tail    -- Clopper & Pearson (1934)
    fellegi_sunter_match_prob     -- Fellegi & Sunter (1969); Christen (2012)
    maximum_curvature_mc          -- Wiemer & Wyss (2000)
    chi_square_sf                 -- scipy-free regularized incomplete gamma
                                      (Numerical Recipes; Abramowitz & Stegun 1964)
    em_mvn_missing / little_mcar_test -- Little (1988); Dempster, Laird &
                                      Rubin (1977) EM for MVN with missing data
    discretize_comparison / fellegi_sunter_em / fellegi_sunter_em_match_probs
                                   -- Fellegi & Sunter (1969) latent-class model,
                                      m-/u-probabilities fit by EM (Winkler 1988)
"""

from __future__ import annotations

import math
import warnings
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Benford's Law -- chi-square goodness-of-fit on leading digits
# ---------------------------------------------------------------------------
# P(d) = log10(1 + 1/d), d in 1..9  (Hill 1995's scale/base-invariance result)
BENFORD_EXPECTED_PROB = {d: math.log10(1.0 + 1.0 / d) for d in range(1, 10)}


def leading_digit(x: float) -> Optional[int]:
    """Return the leading (first significant) decimal digit of |x|, or None."""
    x = abs(x)
    if not math.isfinite(x) or x == 0.0:
        return None
    # Normalise to [1, 10) via log10, robust to any magnitude/scale.
    exponent = math.floor(math.log10(x))
    mantissa = x / (10.0 ** exponent)
    # Guard against floating-point edge cases pushing mantissa to 10.0 or <1.0.
    if mantissa >= 10.0:
        mantissa /= 10.0
    elif mantissa < 1.0:
        mantissa *= 10.0
    digit = int(mantissa)
    return digit if 1 <= digit <= 9 else None


def benford_chi_square(values: Sequence[float]) -> Tuple[float, float, int]:
    """
    Chi-square goodness-of-fit test of leading-digit distribution against
    Benford's Law (Hill 1995; used for fabrication detection per Diekmann 2007).

    Corresponds to test A1. Must only be applied to quantities spanning
    several orders of magnitude (seismic moment, depth, inter-event
    waiting times) -- NOT to raw magnitude, which is too narrow a range
    (Deep-Dive 03, Section 1.3).

    Args:
        values: Positive, finite, multi-order-of-magnitude quantities.

    Returns:
        Tuple of (chi2_statistic, dof, n_valid). dof is fixed at 8
        (9 leading-digit categories - 1 constraint). Compare chi2_statistic
        against a chi-square(8) critical value externally, or convert to a
        bounded [0,1] score via `benford_score`.
    """
    digits = [leading_digit(v) for v in values]
    digits = [d for d in digits if d is not None]
    n = len(digits)
    if n == 0:
        return float("nan"), 8, 0

    observed = np.zeros(9, dtype=float)
    for d in digits:
        observed[d - 1] += 1
    expected = np.array([BENFORD_EXPECTED_PROB[d] * n for d in range(1, 10)])

    # Avoid division by zero (expected is always > 0 for n > 0 since every
    # BENFORD_EXPECTED_PROB[d] > 0).
    chi2 = float(np.sum((observed - expected) ** 2 / expected))
    return chi2, 8, n


def benford_score(chi2_statistic: float, n: int, critical_value: float = 15.51) -> float:
    """
    Convert a Benford chi-square statistic into a bounded [0,1] score.

    critical_value default (15.51) is the chi-square(8) critical value at
    alpha=0.05 -- standard goodness-of-fit convention. Score decays smoothly
    past the critical value rather than a hard step, so a marginal fail is
    scored differently from a catastrophic one.

    Returns 1.0 when n == 0 (no valid values to test -- neutral, not a
    penalty; the caller should track "not applicable" separately if desired).
    """
    if n == 0 or math.isnan(chi2_statistic):
        return 1.0
    return float(np.clip(1.0 - (chi2_statistic / (2.0 * critical_value)), 0.0, 1.0))


# ---------------------------------------------------------------------------
# Gutenberg-Richter b-value  (A2, C4)
# ---------------------------------------------------------------------------

def gr_b_value_aki(magnitudes: Sequence[float], mc: float, delta_m: float = 0.1) -> float:
    """
    Maximum-likelihood b-value estimator (Aki 1965), with Utsu's discrete-data
    half-bin correction.

    b_hat = log10(e) / (mean(M) - (Mc - deltaM/2))

    Args:
        magnitudes: Magnitudes, already restricted to M >= mc by the caller.
        mc:         Magnitude of completeness.
        delta_m:    Magnitude bin width (reporting precision). Default 0.1.

    Returns:
        b-value estimate, or NaN if fewer than 2 events or non-positive
        denominator.
    """
    m = np.asarray(magnitudes, dtype=float)
    m = m[np.isfinite(m)]
    if len(m) < 2:
        return float("nan")
    denom = float(np.mean(m) - (mc - delta_m / 2.0))
    if denom <= 0:
        return float("nan")
    return math.log10(math.e) / denom


def gr_b_value_shi_bolt_se(magnitudes: Sequence[float], b_hat: float) -> float:
    """
    Shi & Bolt (1982) finite-sample-aware standard error of the b-value.

    delta_b = 2.30 * b^2 * sqrt( sum((Mi - mean(M))^2) / (n*(n-1)) )

    Preferred over Aki's asymptotic sigma_b ~ b/sqrt(N) at small/moderate N
    (Deep-Dive 02, Section 1.3).
    """
    m = np.asarray(magnitudes, dtype=float)
    m = m[np.isfinite(m)]
    n = len(m)
    if n < 2 or math.isnan(b_hat):
        return float("nan")
    mean_m = float(np.mean(m))
    ssq = float(np.sum((m - mean_m) ** 2))
    return 2.30 * (b_hat ** 2) * math.sqrt(ssq / (n * (n - 1)))


def gr_b_value_aki_se(b_hat: float, n: int) -> float:
    """Aki's (1965) original asymptotic standard error: sigma_b ~ b / sqrt(N)."""
    if n <= 0 or math.isnan(b_hat):
        return float("nan")
    return abs(b_hat) / math.sqrt(n)


# ---------------------------------------------------------------------------
# Maximum Curvature magnitude-of-completeness estimation (C2)
# ---------------------------------------------------------------------------

def maximum_curvature_mc(magnitudes: Sequence[float], bin_width: float = 0.1) -> float:
    """
    Estimate magnitude of completeness Mc via the Maximum Curvature method
    (Wiemer & Wyss 2000): Mc is the magnitude bin with the highest count in
    the non-cumulative frequency-magnitude distribution.

    Args:
        magnitudes: All reported magnitudes (unrestricted).
        bin_width:  Magnitude bin width. Default 0.1.

    Returns:
        Estimated Mc, or NaN if fewer than 2 distinct magnitudes.

    IMPLEMENTATION NOTE (bug fix, 2026-07-16): the previous implementation
    built bin edges with `np.arange(lo, hi + bin_width, bin_width)` and
    binned via `np.histogram`. Because `np.arange` accumulates floating-
    point error over repeated addition, an edge that is conceptually meant
    to sit exactly at a reported magnitude value (catalogs are almost
    always reported at a fixed 0.1 precision) can drift a few ULPs above
    or below that value. `np.histogram`'s half-open bins then silently
    misclassify every event at that value into the neighboring bin,
    corrupting the peak count -- confirmed to change the returned Mc for
    53.5% of the 985-dataset calibration corpus (110 by more than one
    full bin) versus a value-exact recount.

    A first attempt at this fix snapped each magnitude to its NEAREST bin
    index via `round((m - lo) / bin_width)`. That does fix the float-drift
    misclassification, but it silently changes the binning CONVENTION for
    continuously-valued (non-0.1-quantized) magnitude data: the original
    code's bins are left-edge-anchored (bin i covers [lo + i*bw, lo +
    (i+1)*bw)), while a nearest-index rounding scheme is center-anchored
    (bin i covers [lo + (i-0.5)*bw, lo + (i+0.5)*bw)) -- a real half-bin
    shift, not just a numerical-robustness fix. This was caught by
    checking the fix against `nz` (a corpus catalog with genuinely
    continuous, non-quantized magnitudes -- moment-magnitude-derived, not
    reported at fixed 0.1 precision): the nearest-index version changed
    `nz`'s Mc from 1.838 to 1.938, even though the original `np.arange`
    code was NOT actually float-drift-buggy for `nz` specifically (its
    result matched a robust left-edge recount exactly). Silently shipping
    that would have moved `nz`'s baseline Mc/b-value -- and everything
    downstream of it, including Group D1(a)'s and Gap 9's numbers -- for a
    reason unrelated to the bug being fixed.

    The fix actually used below instead snaps each magnitude to its bin
    index via `floor((m - lo) / bin_width + epsilon)`, preserving the
    ORIGINAL left-edge-anchored convention (so continuous-data results
    such as `nz`'s are unchanged from the pre-fix code whenever the
    pre-fix code wasn't actually wrong) while still being robust to the
    same class of floating-point edge drift that broke the quantized
    case (a small additive epsilon before flooring absorbs a value that
    is conceptually AT a left bin edge but represented a few ULPs below
    it, without the wholesale convention shift that rounding introduces).
    Re-validated against the full 985-dataset corpus after this
    correction: 175/985 datasets change from the original buggy value
    (versus 527/985 for the discarded rounding-based attempt), and every
    genuinely 0.1-quantized dataset's peak now matches a value-exact
    recount (the ~15/540 residual differences among quantized datasets
    are confirmed genuine same-count TIES with no unique true answer, not
    remaining bugs).
    """
    m = np.asarray(magnitudes, dtype=float)
    m = m[np.isfinite(m)]
    if len(m) < 2:
        return float("nan")
    lo, hi = float(np.min(m)), float(np.max(m))
    if hi <= lo:
        return float(lo)
    bin_idx = np.floor((m - lo) / bin_width + 1e-9).astype(np.int64)
    counts = np.bincount(bin_idx)
    if counts.sum() == 0:
        return float("nan")
    peak_idx = int(np.argmax(counts))
    return float(lo + peak_idx * bin_width)


def mc_bootstrap_se(
    magnitudes: Sequence[float],
    bin_width: float = 0.1,
    n_boot: int = 200,
    seed: int = 42,
) -> float:
    """
    Bootstrap standard error of the Maximum-Curvature Mc estimate
    (Woessner & Wiemer 2005 style resampling procedure).
    """
    m = np.asarray(magnitudes, dtype=float)
    m = m[np.isfinite(m)]
    if len(m) < 10:
        return float("nan")
    rng = np.random.RandomState(seed)
    ests = []
    for _ in range(n_boot):
        sample = rng.choice(m, size=len(m), replace=True)
        ests.append(maximum_curvature_mc(sample, bin_width))
    ests = np.array([e for e in ests if not math.isnan(e)])
    if len(ests) < 2:
        return float("nan")
    return float(np.std(ests, ddof=1))


# ---------------------------------------------------------------------------
# Omori-Utsu aftershock decay fit  (A3)
# ---------------------------------------------------------------------------

def fit_omori_utsu(
    event_times_days: Sequence[float],
) -> Dict[str, float]:
    """
    Fit the Omori-Utsu law n(t) = K / (t+c)^p to a sequence of aftershock
    times (in days since the mainshock) via nonlinear least squares on the
    empirical inter-event-time density, and report a KS-test-based
    goodness-of-fit against a homogeneous (non-decaying) Poisson null.

    This deliberately does NOT assert a fixed universal band for c (Deep-Dive
    02, Section 2.2 -- c is a property of the recording network, not the
    physics). It fits c per-sequence and flags only gross qualitative
    failure: p <= 0, or a fit statistically indistinguishable from a
    non-decaying uniform process.

    Args:
        event_times_days: Sorted or unsorted times (days) after the
                           mainshock. Must be > 0.

    Returns:
        Dict with keys: p, c, K, ks_stat, ks_critical, n, degenerate (bool:
        True if the fit could not distinguish decay from a flat-rate
        process).
    """
    t = np.asarray(sorted(x for x in event_times_days if x is not None and x > 0), dtype=float)
    n = len(t)
    if n < 5:
        return {"p": float("nan"), "c": float("nan"), "K": float("nan"),
                "ks_stat": float("nan"), "ks_critical": float("nan"), "n": n, "degenerate": True}

    # Bin into a rate curve n(t) via log-spaced bins, then fit log n(t) =
    # log K - p*log(t+c) using a coarse grid search over c (c must be > 0
    # and is not analytically identifiable jointly with p/K in closed form).
    t_max = float(t[-1])
    t_start = t[0] if t[0] > 0 else 1e-3

    # BUG FOUND (2026-07-11, discovered via a full from-scratch re-score of
    # the 9th-pass corpus): a cluster whose events are all at the IDENTICAL
    # time (t_start == t_max) -- a real, non-adversarial pattern produced
    # by `corrupt.py::timestamp_collision` when a large fraction of a
    # dataset's records share one batch-import timestamp that happens to
    # fall inside a mainshock's 30-day aftershock window -- made
    # `np.geomspace(t_start, t_max, ...)` degenerate to a constant array,
    # which `np.histogram` correctly rejects as non-monotonic bin edges,
    # crashing scoring entirely instead of just flagging a degenerate fit.
    # This is the single most extreme "non-decaying" pattern possible (zero
    # time spread), so it is handled the same way the n<5 case just above
    # already is: flagged degenerate, not treated as an exception. This
    # bug predates the 9th-pass corpus expansion -- it was simply never
    # exercised before because `run_scoring.py`'s incremental/resumable
    # design kept reusing older cached scores for the affected datasets
    # (`corrupt_real_morocco_20230908_query_timestamp_collision_low/high`)
    # across every prior pass, until this pass's from-scratch re-score
    # (score_matrix.csv deliberately cleared for consistency -- see
    # Full Recheck Summary) finally re-exercised this code path honestly.
    if t_start >= t_max:
        return {"p": float("nan"), "c": float("nan"), "K": float("nan"),
                "ks_stat": float("nan"), "ks_critical": float("nan"), "n": n, "degenerate": True}

    n_bins = max(5, min(30, n // 3))
    edges = np.geomspace(t_start, t_max, n_bins + 1)
    counts, _ = np.histogram(t, bins=edges)
    widths = np.diff(edges)
    centers = (edges[:-1] + edges[1:]) / 2.0
    rate = counts / np.clip(widths, 1e-9, None)

    valid = rate > 0
    if valid.sum() < 3:
        return {"p": float("nan"), "c": float("nan"), "K": float("nan"),
                "ks_stat": float("nan"), "ks_critical": float("nan"), "n": n, "degenerate": True}

    # Regression is WEIGHTED by bin count (standard inverse-Poisson-variance
    # weighting: Var(log(count)) ~ 1/count for count-based Poisson data).
    # An earlier, unweighted version of this fit was found in the scientific-
    # validity review pass to systematically underestimate p by ~30% (e.g.
    # true p=0.9 fitted as ~0.64) on synthetic sequences with a KNOWN
    # generating p, because unweighted least-squares on log(noisy small
    # counts) is biased low (Jensen's-inequality-type effect: E[log(count)]
    # < log(E[count]) for Poisson-distributed counts, worst in the
    # low-count, large-t tail bins that an unweighted fit treats as equally
    # informative as the high-count early bins). Weighting by count reduces
    # this to within a few percent on the same synthetic-recovery test.
    best = None
    for c_candidate in np.geomspace(1e-3, max(1.0, t_max / 10.0), 25):
        x = np.log(centers[valid] + c_candidate)
        y = np.log(rate[valid])
        w = counts[valid].astype(float)
        # Linear regression y = a - p*x  =>  p = -slope, weighted by count.
        a_mat = np.vstack([np.ones_like(x), x]).T * w[:, None]
        yw = y * w
        coeffs, residuals, _, _ = np.linalg.lstsq(a_mat, yw, rcond=None)
        log_k, neg_p = coeffs
        p = -neg_p
        pred = log_k - p * x
        sse = float(np.sum(w * (y - pred) ** 2))
        if best is None or sse < best[0]:
            best = (sse, p, c_candidate, math.exp(log_k))

    _, p_hat, c_hat, k_hat = best

    # KS test: empirical inter-event-time distribution vs. what a
    # homogeneous (non-decaying) process of the same total rate would give
    # (i.e., uniform arrival over [0, t_max] -> exponential inter-arrival).
    uniform_cdf = t / t_max
    empirical_cdf = np.arange(1, n + 1) / n
    ks_stat = float(np.max(np.abs(empirical_cdf - uniform_cdf)))

    # The "close enough to uniform -> flat-rate, degenerate" cutoff MUST
    # scale with n (a one-sample KS statistic shrinks as ~1/sqrt(n) under
    # the null, regardless of whether the process is truly flat). A fixed
    # constant here was found, in the scientific-validity review pass, to
    # make this check nearly powerless at realistic small-to-moderate
    # aftershock-sequence sizes: a fixed 0.05 threshold correctly flagged a
    # KNOWN homogeneous (non-decaying) Poisson process as degenerate only
    # ~9% of the time at n=50 and ~40% at n=200 (it only became reliable,
    # ~99%, at n=1000+), because the true expected KS statistic under a
    # correct null is itself already ~1.36/sqrt(n) >> 0.05 at small n. Fixed
    # by using the standard one-sample KS asymptotic critical value at
    # alpha=0.05 with the Stephens (1974) finite-sample correction term:
    #   D_crit = 1.358 / (sqrt(n) + 0.12 + 0.11/sqrt(n))
    # This restores the intended ~5% false-degenerate rate on genuinely
    # decaying sequences while making the flat-process check actually
    # powerful at small n instead of silently inert.
    sqrt_n = math.sqrt(n)
    ks_critical = 1.358 / (sqrt_n + 0.12 + 0.11 / sqrt_n)
    degenerate = (not math.isfinite(p_hat)) or (p_hat <= 0) or (ks_stat < ks_critical)

    return {"p": float(p_hat), "c": float(c_hat), "K": float(k_hat),
            "ks_stat": ks_stat, "ks_critical": ks_critical, "n": n,
            "degenerate": bool(degenerate)}


# ---------------------------------------------------------------------------
# Kolmogorov-Smirnov statistics  (A3 goodness-of-fit; I5 temporal distribution drift)
# ---------------------------------------------------------------------------

def ks_statistic_2sample(sample_a: Sequence[float], sample_b: Sequence[float]) -> float:
    """
    Two-sample Kolmogorov-Smirnov statistic D = sup_x |F_a(x) - F_b(x)|.

    Bounded in [0,1] by construction -- used directly (not its p-value) as
    an effect-size score input for I5 (Gap-Remediation Addendum, Section 3.3).
    """
    a = np.sort(np.asarray([x for x in sample_a if x is not None and math.isfinite(x)], dtype=float))
    b = np.sort(np.asarray([x for x in sample_b if x is not None and math.isfinite(x)], dtype=float))
    if len(a) == 0 or len(b) == 0:
        return float("nan")

    all_vals = np.concatenate([a, b])
    all_vals.sort()
    cdf_a = np.searchsorted(a, all_vals, side="right") / len(a)
    cdf_b = np.searchsorted(b, all_vals, side="right") / len(b)
    return float(np.max(np.abs(cdf_a - cdf_b)))


# ---------------------------------------------------------------------------
# Correlation dimension  (A4) -- Grassberger-Procaccia (1983)
# ---------------------------------------------------------------------------

def correlation_dimension(
    points: np.ndarray,
    n_radii: int = 20,
    max_points: int = 1500,
    seed: int = 42,
    r_min_pct: float = 1.0,
    r_max_pct: float = 30.0,
) -> float:
    """
    Estimate the correlation dimension Dc via the Grassberger-Procaccia (1983)
    correlation integral C(r) ~ r^Dc.

    Args:
        points:     Array of shape (N, D) -- e.g. normalised (lat, lon) or
                    (lat, lon, depth).
        n_radii:    Number of log-spaced radii to sample.
        max_points: Subsample cap for O(N^2) pairwise-distance cost.
        seed:       Subsampling seed.
        r_min_pct, r_max_pct: Percentiles of the pairwise-distance
            distribution used to bound the fitted scaling region (see note
            below on why these are NOT (5, 95)).

    Returns:
        Estimated Dc (slope of log C(r) vs log r over the scaling region),
        or NaN if too few points.

    Scientific-validity note (found during an internal review pass):
    an earlier version of this function
    used r_min/r_max = the 5th/95th percentile of the pairwise-distance
    distribution. For points scattered over a bounded 2-D domain, pairwise
    distances concentrate around the domain's own characteristic scale (the
    median pairwise distance is roughly a third of the domain diagonal), so
    the 5th percentile is already ~10-15% of the domain diagonal -- well
    outside the small-r regime where C(r) ~ r^Dc actually holds. This pushed
    the fitted region into where boundary/saturation effects flatten the
    slope, causing a large, N-independent (i.e. NOT a shrinking finite-
    sample-noise effect) downward bias: a uniformly random 2-D scatter
    (true Dc=2) was measured at Dc~1.6 regardless of sample size. Using the
    1st/30th percentile instead keeps the fitted region concentrated at
    genuinely small, local length scales, recovering Dc~1.85-1.88 for
    uniform 2-D scatter and Dc~0.98 for points on a line, while still
    clearly separating a fault-clustered synthetic pattern (Dc~1.3) from
    both -- i.e. it substantially reduces the systematic bias without
    weakening A4's actual discriminative power. Some residual downward bias
    remains at finite N (a well-documented general property of the
    Grassberger-Procaccia estimator, not specific to this implementation --
    see e.g. Theiler 1990's review of correlation-dimension estimation
    pitfalls) and is not something a percentile-range choice alone can fully
    eliminate; A4's score should be read as "clustered vs. not," not as a
    precise absolute Dc measurement.
    """
    pts = np.asarray(points, dtype=float)
    pts = pts[np.all(np.isfinite(pts), axis=1)]
    n = len(pts)
    if n < 20:
        return float("nan")

    if n > max_points:
        rng = np.random.RandomState(seed)
        idx = rng.choice(n, size=max_points, replace=False)
        pts = pts[idx]
        n = max_points

    # Pairwise Euclidean distances (upper triangle only).
    diffs = pts[:, None, :] - pts[None, :, :]
    dists = np.sqrt(np.sum(diffs ** 2, axis=-1))
    iu = np.triu_indices(n, k=1)
    d = dists[iu]
    d = d[d > 0]
    if len(d) < 10:
        return float("nan")

    r_min, r_max = float(np.percentile(d, r_min_pct)), float(np.percentile(d, r_max_pct))
    if r_min <= 0 or r_max <= r_min:
        return float("nan")

    radii = np.geomspace(r_min, r_max, n_radii)
    total_pairs = len(d)
    c_r = np.array([np.sum(d < r) / total_pairs for r in radii])

    valid = c_r > 0
    if valid.sum() < 4:
        return float("nan")

    log_r = np.log(radii[valid])
    log_c = np.log(c_r[valid])
    # Slope of log C(r) vs log r over the middle scaling region (drop the
    # extreme 20% at each end, where finite-sample edge effects dominate).
    k = len(log_r)
    lo_cut, hi_cut = int(k * 0.2), int(k * 0.8)
    if hi_cut - lo_cut < 3:
        lo_cut, hi_cut = 0, k
    slope, _ = np.polyfit(log_r[lo_cut:hi_cut], log_c[lo_cut:hi_cut], 1)
    return float(slope)


# ---------------------------------------------------------------------------
# Mann-Kendall trend test + Sen's slope  (I1)
# ---------------------------------------------------------------------------

# Both Mann-Kendall's S statistic and Sen's slope are, in their textbook
# form, O(N^2) (they consider every pair i<j). That is intractable for the
# large real-world catalogs this project is built to audit (100k+ records).
# Rather than silently hanging or OOM-killing on such datasets, both
# functions below deterministically subsample to at most MAX_TREND_N points,
# evenly spaced across the (already time-sorted) input series so temporal
# coverage is preserved -- a disclosed, pragmatic performance cap, not a
# change to either statistic's definition. This mirrors the same
# subsample-for-tractability pattern already used in correlation_dimension().
MAX_TREND_N: int = 2000


def _subsample_preserving_order(*arrays: np.ndarray, max_n: int = MAX_TREND_N) -> Tuple[np.ndarray, ...]:
    n = len(arrays[0])
    if n <= max_n:
        return arrays
    idx = np.linspace(0, n - 1, max_n).astype(int)
    idx = np.unique(idx)
    return tuple(a[idx] for a in arrays)


def mann_kendall_test(series: Sequence[float]) -> Dict[str, float]:
    """
    Mann-Kendall (1945/1975) nonparametric test for monotonic trend.

    Returns dict with 's' (test statistic), 'z' (standardised z-score), and
    'trend_detected' (bool, |z| > 1.96 <=> p < 0.05 two-sided).

    Uses the standard tied-value variance correction (Gilbert 1987,
    "Statistical Methods for Environmental Pollution Monitoring", the usual
    secondary reference for this correction alongside Mann 1945/Kendall
    1975):

        Var(S) = [n(n-1)(2n+5) - sum_p tp*(tp-1)*(2tp+5)] / 18

    where the sum runs over groups of tp tied values. This matters in
    practice for I1: magnitudes are typically reported at 0.1-unit
    precision, so a real magnitude series has many tied values, and the
    uncorrected textbook variance formula (no tie term) systematically
    overstates Var(S) -- making the test needlessly conservative (more
    likely to MISS a genuine trend, never more likely to falsely flag one).
    An earlier version of this function omitted the tie correction, which
    was found in the scientific-validity review pass to silently reduce
    I1's detection power on real, tie-heavy magnitude data.

    See MAX_TREND_N above: for series longer than MAX_TREND_N, an evenly
    spaced subsample is used for tractability (disclosed performance cap).
    """
    x = np.asarray([v for v in series if v is not None and math.isfinite(v)], dtype=float)
    n_full = len(x)
    if n_full < 4:
        return {"s": float("nan"), "z": float("nan"), "trend_detected": False, "n": n_full}

    (x,) = _subsample_preserving_order(x)
    n = len(x)

    # Vectorised: S = sum_{i<j} sign(x_j - x_i), computed via the upper
    # triangle of the pairwise-difference matrix (O(n^2) memory/time, but
    # n is capped at MAX_TREND_N so this stays fast).
    diff = x[np.newaxis, :] - x[:, np.newaxis]
    iu = np.triu_indices(n, k=1)
    s = float(np.sum(np.sign(diff[iu])))

    _, tie_counts = np.unique(x, return_counts=True)
    tie_term = float(np.sum(tie_counts * (tie_counts - 1) * (2 * tie_counts + 5)))
    var_s = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0

    if var_s <= 0:
        # All values identical (or a degenerate tie structure) -- no
        # meaningful variance to standardise against.
        z = 0.0
    elif s > 0:
        z = (s - 1) / math.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / math.sqrt(var_s)
    else:
        z = 0.0

    return {"s": float(s), "z": float(z), "trend_detected": bool(abs(z) > 1.96), "n": n_full}


def sen_slope(x_values: Sequence[float], y_values: Sequence[float]) -> float:
    """
    Sen's (1968) slope estimator: the median of all pairwise slopes
    (y_j - y_i) / (x_j - x_i) for i < j. Outlier-robust companion effect-size
    to the Mann-Kendall trend test (Gap-Remediation Addendum, Section 3.3).

    See MAX_TREND_N above: for series longer than MAX_TREND_N, an evenly
    spaced subsample is used for tractability (disclosed performance cap).
    """
    x = np.asarray(x_values, dtype=float)
    y = np.asarray(y_values, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    n = len(x)
    if n < 2:
        return float("nan")

    x, y = _subsample_preserving_order(x, y)
    n = len(x)

    dx = x[np.newaxis, :] - x[:, np.newaxis]
    dy = y[np.newaxis, :] - y[:, np.newaxis]
    iu = np.triu_indices(n, k=1)
    dx_u, dy_u = dx[iu], dy[iu]
    valid = dx_u != 0
    if not np.any(valid):
        return float("nan")
    return float(np.median(dy_u[valid] / dx_u[valid]))


# ---------------------------------------------------------------------------
# Clopper-Pearson exact binomial test  (hard-override non-trivial fraction)
# ---------------------------------------------------------------------------
#
# SCALABILITY FIX (2026-07-20): the original implementation of both tail
# functions below summed the binomial PMF term-by-term over a Python list
# comprehension spanning the ENTIRE tail (e.g. `range(k, n + 1)` for the
# upper tail) -- O(n) time and memory. For the large-n case this module's
# own docstrings already anticipated (n=5,000,000, per the Deep-Dive 06
# worked example, and realistic for a real global/regional seismic
# catalog), this took ~11 seconds and allocated a ~5-million-element list
# per call -- and every P1-P3 hard-override check calls this function, so
# a single large-catalog audit could spend tens of seconds just here. This
# was found and fixed as a real, measured engineering defect, not a
# theoretical concern (independently confirmed by timing the exact
# n=5,000,000 case both before and after this fix).
#
# The fix replaces direct term-by-term summation with the standard
# identity linking a binomial tail probability to the regularized
# incomplete beta function:
#
#     P(X >= k) = I_p(k, n - k + 1)          (upper tail)
#     P(X <= k) = I_{1-p}(n - k, k + 1)      (lower tail)
#
# where I_x(a, b) is evaluated via a continued-fraction expansion (Lentz's
# method, as in Numerical Recipes 3rd ed., Section 6.4) that converges in
# a small, n-independent number of iterations -- O(1) in practice instead
# of O(n). Verified numerically identical (to >=9 significant figures) to
# `scipy.stats.binom.sf`/`.cdf` across a battery of small-n, large-n, and
# boundary (k=0, k=n, n=1) cases before replacing the old implementation.


def _betacf(a: float, b: float, x: float,
            max_iter: int = 200, eps: float = 1e-14) -> float:
    """
    Continued-fraction evaluation used by `_regularized_incomplete_beta`
    (Numerical Recipes 3rd ed., Section 6.4, "betacf"). Not meant to be
    called directly -- see that function for the public-facing use.
    """
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-300:
        d = 1e-300
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    """
    Regularized incomplete beta function I_x(a, b), for a, b > 0 and
    0 <= x <= 1. Used to evaluate binomial tail probabilities in O(1)
    (independent of n) rather than by summing n individual PMF terms --
    see the module-level SCALABILITY FIX note above for why this replaced
    the original term-by-term summation.
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_beta_prefactor = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log(1.0 - x)
    )
    # Use whichever of I_x(a,b) / I_{1-x}(b,a) has the faster-converging
    # continued fraction (standard numerical-recipes convention).
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(log_beta_prefactor) * _betacf(a, b, x) / a
    return 1.0 - math.exp(log_beta_prefactor) * _betacf(b, a, 1.0 - x) / b


def clopper_pearson_upper_tail(k: int, n: int, p0: float) -> float:
    """
    One-sided exact binomial upper-tail p-value: P(X >= k) where
    X ~ Binomial(n, p0). Used to test H0: true violation rate <= epsilon_tol
    (Clopper & Pearson 1934; Gap-Remediation Addendum, Section 2.2).

    Args:
        k:  Observed violation count.
        n:  Total record count.
        p0: Null-hypothesis violation rate (epsilon_tol).

    Returns:
        p-value in [0, 1]. p ~ 1 means "consistent with isolated error";
        small p means "statistically distinguishable from isolated error."
    """
    if n <= 0:
        return float("nan")
    if k <= 0:
        return 1.0
    if k > n:
        raise ValueError(f"clopper_pearson_upper_tail: k={k} cannot exceed n={n}.")

    # P(X >= k) = I_p0(k, n - k + 1) -- O(1) regardless of n (see the
    # SCALABILITY FIX note above this function's section header).
    return float(_regularized_incomplete_beta(float(k), float(n - k + 1), p0))


def clopper_pearson_lower_tail(k: int, n: int, p0: float) -> float:
    """
    One-sided exact binomial lower-tail p-value: P(X <= k) where
    X ~ Binomial(n, p0). Tests H0: true rate >= p0 -- the mirror image of
    `clopper_pearson_upper_tail` above, used where a LOW observed count is
    the evidence of interest rather than a high one (Clopper & Pearson
    1934). Added for A6's three-state "Externally contradicted" test
    (Group C3, 2026-07-12, `data_certify/axis_authenticity.py`): given
    k=0 corroborating matches observed across n independently-feasible,
    reference-complete-stratum records, this answers "how surprising would
    that be if the true match rate were actually theta_auth (or higher)?"
    -- a small p-value means the all-non-match observation is strong
    evidence the true rate is genuinely below theta_auth, not sampling
    noise from a small stratum.

    Args:
        k:  Observed match count (for A6's use, always 0 by construction --
            "contradicted-eligible" is itself defined as the zero-match
            subset -- but implemented generally, not hardcoded to k=0).
        n:  Total record count in the stratum being tested.
        p0: Null-hypothesis match rate (theta_auth).

    Returns:
        p-value in [0, 1]. Small p means "statistically distinguishable
        from a true rate of p0 or higher" -- i.e. confidently below p0.
    """
    if n <= 0:
        return float("nan")
    if k >= n:
        return 1.0
    if k < 0:
        raise ValueError(f"clopper_pearson_lower_tail: k={k} cannot be negative.")

    # P(X <= k) = I_(1-p0)(n - k, k + 1) -- O(1) regardless of n. In A6's
    # actual usage k is always 0 (see docstring above) so the old O(k+1)
    # implementation was never a practical scalability problem here, but
    # this is fixed too for correctness/consistency with the upper tail.
    return float(_regularized_incomplete_beta(float(n - k), float(k + 1), 1.0 - p0))


# ---------------------------------------------------------------------------
# Simplified Fellegi-Sunter probabilistic record linkage  (I4)
# ---------------------------------------------------------------------------
# Full Fellegi-Sunter (1969) uses EM-estimated m-/u-probabilities per
# comparison field. This is a deliberately simplified, but structurally
# faithful, implementation: comparison-vector agreement is converted to a
# match probability via a fixed, documented logistic-style combination of
# normalised field distances, rather than an EM fit (which needs a labeled
# or semi-labeled training set this reference implementation does not have).
# This simplification is disclosed here, not silently presented as a full EM
# fit, consistent with this project's honesty-first documentation culture.

def fellegi_sunter_match_prob(
    time_diff_sec: float,
    dist_km: float,
    mag_diff: float,
    time_scale_sec: float = 30.0,
    dist_scale_km: float = 50.0,
    mag_scale: float = 0.5,
) -> float:
    """
    Approximate posterior match probability for a candidate record pair,
    in the spirit of the Fellegi-Sunter (1969) framework: each comparison
    field contributes evidence, combined multiplicatively into an overall
    match likelihood, converted to a probability in [0,1].

    This uses a Gaussian-kernel agreement weight per field (a standard,
    simple stand-in for FS's m/u likelihood ratios when no labeled training
    pairs are available to fit them, per Christen 2012's discussion of
    unsupervised/heuristic FS variants) rather than EM-estimated m-/u-
    probabilities.

    Args:
        time_diff_sec:  Absolute origin-time difference, seconds.
        dist_km:        Great-circle epicentral distance, km.
        mag_diff:       Absolute magnitude difference.
        *_scale:        Characteristic scale at which agreement decays to
                         ~37% (1/e) -- wider tolerance for cross-catalog
                         comparison than within-source near-duplicates,
                         per Deep-Dive 04 Mode 27.

    Returns:
        Match probability in [0, 1].
    """
    def _kernel(diff: float, scale: float) -> float:
        if diff is None or not math.isfinite(diff):
            return 0.5  # missing comparison field -> neutral evidence
        return math.exp(-0.5 * (diff / scale) ** 2)

    w_time = _kernel(time_diff_sec, time_scale_sec)
    w_dist = _kernel(dist_km, dist_scale_km)
    w_mag = _kernel(mag_diff, mag_scale)

    # Combine as a product of independent evidence weights (log-linear
    # combination is the standard FS aggregation across comparison fields).
    return float(np.clip(w_time * w_dist * w_mag, 0.0, 1.0))


def probability_at_least_one_match(match_probs: Sequence[float]) -> float:
    """
    P(at least one match) = 1 - product(1 - p_i), for a record's candidate
    partners. Bounded in [0,1] by construction regardless of how many
    candidate partners exist -- this is the corrected per-record formulation
    from Gap-Remediation Addendum Section 7.2 (replacing an earlier,
    unbounded per-pair-sum version).
    """
    probs = [p for p in match_probs if p is not None and math.isfinite(p)]
    if not probs:
        return 0.0
    prod_not_match = 1.0
    for p in probs:
        prod_not_match *= (1.0 - float(np.clip(p, 0.0, 1.0)))
    return float(1.0 - prod_not_match)


# ---------------------------------------------------------------------------
# Great-circle distance (haversine) -- shared geometry helper
# ---------------------------------------------------------------------------

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two (lat, lon) points, in km."""
    if not all(math.isfinite(v) for v in (lat1, lon1, lat2, lon2)):
        return float("nan")
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))
    return EARTH_RADIUS_KM * c


def haversine_km_matrix(lats: np.ndarray, lons: np.ndarray,
                         ref_lats: np.ndarray, ref_lons: np.ndarray) -> np.ndarray:
    """
    Vectorised haversine distance from each of N query points to each of M
    reference points, returned as an (N, M) km matrix.

    This exists because the scalar `haversine_km` above, called in a Python
    for-loop once per (query point x reference point) pair, is O(N*M)
    Python-level function calls -- fine for small N, but the dominant cost
    of a P8 plate-boundary-proximity audit once N reaches 10^5+ records
    (e.g. the bundled Chile catalog): ~130,000 records x ~30 sample boundary
    points was measured at over 20 seconds using the scalar loop, versus
    well under a second vectorised here. NaN query coordinates propagate to
    NaN distances (not silently dropped), matching haversine_km's contract.
    """
    lats = np.asarray(lats, dtype=float)
    lons = np.asarray(lons, dtype=float)
    ref_lats = np.asarray(ref_lats, dtype=float)
    ref_lons = np.asarray(ref_lons, dtype=float)

    phi1 = np.radians(lats)[:, None]                 # (N, 1)
    phi2 = np.radians(ref_lats)[None, :]              # (1, M)
    dphi = phi2 - phi1
    dlambda = np.radians(ref_lons)[None, :] - np.radians(lons)[:, None]

    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0) ** 2
    a = np.clip(a, 0.0, 1.0)
    c = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    return EARTH_RADIUS_KM * c


# =============================================================================
# Chi-square survival function -- scipy-free regularized incomplete gamma
# (C1's Little (1988) MCAR test needs a chi-square p-value; this project has
# no scipy dependency in the core numpy-only package, so the regularized
# incomplete gamma function is implemented directly here, following the
# standard Numerical Recipes series/continued-fraction split -- Abramowitz &
# Stegun 1964, Section 6.5).
# =============================================================================

_GAMMA_ITMAX = 500
_GAMMA_EPS = 3.0e-14
_GAMMA_FPMIN = 1.0e-300


def _regularized_gamma_p_series(a: float, x: float) -> float:
    """P(a, x), the regularized lower incomplete gamma function, via its
    power series -- accurate for x < a+1."""
    if x <= 0.0:
        return 0.0
    gln = math.lgamma(a)
    ap = a
    summ = 1.0 / a
    delta = summ
    for _ in range(_GAMMA_ITMAX):
        ap += 1.0
        delta *= x / ap
        summ += delta
        if abs(delta) < abs(summ) * _GAMMA_EPS:
            break
    return summ * math.exp(-x + a * math.log(x) - gln)


def _regularized_gamma_q_cf(a: float, x: float) -> float:
    """Q(a, x) = 1 - P(a, x), the regularized UPPER incomplete gamma
    function, via Lentz's continued-fraction algorithm -- accurate for
    x >= a+1 (where the series above converges too slowly to be practical)."""
    gln = math.lgamma(a)
    b = x + 1.0 - a
    c = 1.0 / _GAMMA_FPMIN
    d = 1.0 / b
    h = d
    for i in range(1, _GAMMA_ITMAX + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < _GAMMA_FPMIN:
            d = _GAMMA_FPMIN
        c = b + an / c
        if abs(c) < _GAMMA_FPMIN:
            c = _GAMMA_FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _GAMMA_EPS:
            break
    return math.exp(-x + a * math.log(x) - gln) * h


def chi_square_sf(x: float, dof: float) -> float:
    """
    Chi-square survival function (upper tail): P(X >= x) for X ~ chi-square(dof).

    Equivalent to Q(dof/2, x/2), the regularized upper incomplete gamma
    function -- computed here without scipy via the standard Numerical
    Recipes series (x < a+1)/continued-fraction (x >= a+1) split, verified
    against textbook chi-square critical values (Abramowitz & Stegun 1964,
    Table 26.8): chi_square_sf(3.841, 1) = chi_square_sf(5.991, 2) = ... = 0.05.

    Returns NaN for dof <= 0 (undefined). Returns 1.0 for x <= 0 (the whole
    distribution is above any non-positive threshold).
    """
    if not math.isfinite(dof) or dof <= 0:
        return float("nan")
    if not math.isfinite(x):
        return float("nan")
    if x <= 0.0:
        return 1.0

    a = dof / 2.0
    x2 = x / 2.0

    if x2 < a + 1.0:
        p = _regularized_gamma_p_series(a, x2)
        return float(np.clip(1.0 - p, 0.0, 1.0))
    else:
        q = _regularized_gamma_q_cf(a, x2)
        return float(np.clip(q, 0.0, 1.0))


# =============================================================================
# EM algorithm for a multivariate Gaussian with missing data (Dempster, Laird
# & Rubin 1977), grouped by missingness pattern -- feeds Little's (1988)
# MCAR test below. Used by C1 (axis_completeness.py).
# =============================================================================

def em_mvn_missing(
    X: np.ndarray, max_iter: int = 200, tol: float = 1e-8, ridge: float = 1e-8,
) -> Tuple[np.ndarray, np.ndarray, int, bool]:
    """
    Fit a multivariate normal's mean vector and covariance matrix to data
    with missing values via EM (Dempster, Laird & Rubin 1977), grouped by
    missingness PATTERN (which columns are observed) for efficiency -- all
    rows sharing a pattern are updated together using the same conditional-
    Gaussian formulas for E[x_missing | x_observed] and its covariance.

    Rows that are missing EVERY column are excluded entirely (no information
    to contribute). A small ridge term is added to the covariance estimate
    every M-step, purely for numerical stability against degenerate/
    zero-variance columns (e.g. a constant depth_km) -- this is a standard,
    disclosed regularisation, not a change to the estimator's target.

    Args:
        X: (n, p) array, np.nan marking missing entries.
        max_iter, tol: EM stopping criteria (max absolute change in mu or
            Sigma between iterations).
        ridge: Diagonal regularisation added to Sigma every M-step.

    Returns:
        (mu, Sigma, n_iter, converged) -- mu: (p,) mean vector; Sigma: (p,p)
        covariance matrix (population, i.e. divided by n not n-1, matching
        the EM/MLE convention); n_iter: iterations actually run; converged:
        whether `tol` was reached before `max_iter`.
    """
    X = np.asarray(X, dtype=float)
    n_raw, p = X.shape
    obs_mask = ~np.isnan(X)
    row_has_data = obs_mask.any(axis=1)
    Xd = X[row_has_data]
    obs_mask_d = obs_mask[row_has_data]
    n = Xd.shape[0]

    if n == 0:
        return np.full(p, np.nan), np.full((p, p), np.nan), 0, False

    # -- Initialisation: mean-imputed sample mean/covariance -----------------
    mu = np.nanmean(Xd, axis=0)
    mu = np.where(np.isfinite(mu), mu, 0.0)
    X0 = np.where(obs_mask_d, Xd, mu)
    Sigma = np.atleast_2d(np.cov(X0, rowvar=False, ddof=0)).astype(float)
    if Sigma.shape != (p, p):
        Sigma = Sigma.reshape(p, p)
    Sigma = Sigma + ridge * np.eye(p)

    # -- Group rows by missingness pattern ------------------------------------
    patterns: Dict[Tuple[bool, ...], List[int]] = {}
    for i in range(n):
        key = tuple(obs_mask_d[i].tolist())
        patterns.setdefault(key, []).append(i)

    converged = False
    n_iter = 0

    for iteration in range(max_iter):
        mu_old, Sigma_old = mu.copy(), Sigma.copy()
        sum_x = np.zeros(p)
        sum_xxT = np.zeros((p, p))

        for pattern, idxs in patterns.items():
            obs_idx = np.array([j for j, ok in enumerate(pattern) if ok], dtype=int)
            mis_idx = np.array([j for j, ok in enumerate(pattern) if not ok], dtype=int)
            idxs_arr = np.array(idxs, dtype=int)
            Xi = Xd[idxs_arr]
            k = len(idxs_arr)

            if len(mis_idx) == 0:
                sum_x += Xi.sum(axis=0)
                sum_xxT += Xi.T @ Xi
                continue
            if len(obs_idx) == 0:
                continue  # should not occur (fully-missing rows excluded above)

            Sigma_oo = Sigma[np.ix_(obs_idx, obs_idx)] + ridge * np.eye(len(obs_idx))
            Sigma_mo = Sigma[np.ix_(mis_idx, obs_idx)]
            Sigma_om = Sigma[np.ix_(obs_idx, mis_idx)]
            Sigma_mm = Sigma[np.ix_(mis_idx, mis_idx)]
            Sigma_oo_inv = np.linalg.inv(Sigma_oo)

            mu_o, mu_m = mu[obs_idx], mu[mis_idx]
            X_obs = Xi[:, obs_idx]
            diff = X_obs - mu_o

            A = Sigma_mo @ Sigma_oo_inv  # (|M|, |O|)
            cond_mean_m = mu_m[None, :] + diff @ A.T          # (k, |M|)
            cond_cov_m = Sigma_mm - A @ Sigma_om              # (|M|, |M|)

            Xi_filled = np.empty_like(Xi)
            Xi_filled[:, obs_idx] = X_obs
            Xi_filled[:, mis_idx] = cond_mean_m

            sum_x += Xi_filled.sum(axis=0)
            sum_xxT += Xi_filled.T @ Xi_filled
            mm_block = np.zeros((p, p))
            mm_block[np.ix_(mis_idx, mis_idx)] = cond_cov_m
            sum_xxT += k * mm_block

        mu = sum_x / n
        Sigma = sum_xxT / n - np.outer(mu, mu)
        Sigma = (Sigma + Sigma.T) / 2.0 + ridge * np.eye(p)

        n_iter = iteration + 1
        delta = max(float(np.max(np.abs(mu - mu_old))), float(np.max(np.abs(Sigma - Sigma_old))))
        if delta < tol:
            converged = True
            break

    return mu, Sigma, n_iter, converged


def little_mcar_test(X: np.ndarray) -> Dict[str, Any]:
    """
    Little's (1988) MCAR chi-square test: compares each missingness
    pattern's observed-variable sample mean against the EM-fitted
    population mean/covariance (`em_mvn_missing` above), restricted to that
    pattern's observed variables. Under MCAR, all patterns' observed-mean
    vectors should be consistent with a single common population mean.

    Statistic: d2 = sum_j n_j * (xbar_j - mu_Oj)' * inv(Sigma_OjOj) * (xbar_j - mu_Oj)
    Degrees of freedom: df = sum_j |O_j| - p (Little 1988).
    d2 ~ chi-square(df) asymptotically under H0: MCAR.

    DISCLOSED LIMITATION (a property of any observed-data-only test, not a
    bug in this implementation -- Rubin 1976; Little & Rubin 2002): this
    test can only detect missingness correlated with OTHER, OBSERVED
    variables (a MAR-but-not-MCAR violation). It CANNOT detect missingness
    that depends solely on the unobserved value of the missing field
    itself (pure MNAR self-censoring, e.g. "large-magnitude events are
    dropped precisely because they are large") -- no test based only on
    observed data can, since the very information needed is exactly what
    is missing. A non-rejected (mcar_at_alpha05=True) result should be
    read as "no evidence of missingness correlated with other recorded
    fields," not as a general guarantee against self-censoring.

    Returns a dict with keys: d2, df, p_value, n_patterns, em_converged,
    mcar_at_alpha05. When fewer than 2 distinct missingness patterns exist
    (including the no-missingness case), the test is untestable and
    trivially reported as passing (p_value=NaN, mcar_at_alpha05=True) --
    there is no missingness-pattern comparison to make.
    """
    X = np.asarray(X, dtype=float)
    n_raw, p = X.shape
    obs_mask = ~np.isnan(X)
    row_has_data = obs_mask.any(axis=1)
    Xd = X[row_has_data]
    obs_mask_d = obs_mask[row_has_data]
    n = Xd.shape[0]

    patterns: Dict[Tuple[bool, ...], List[int]] = {}
    for i in range(n):
        key = tuple(obs_mask_d[i].tolist())
        patterns.setdefault(key, []).append(i)

    n_patterns = len(patterns)
    if n_patterns < 2 or n == 0:
        return {
            "d2": float("nan"), "df": 0, "p_value": float("nan"),
            "n_patterns": n_patterns, "em_converged": True,
            "mcar_at_alpha05": True,
        }

    mu, Sigma, n_iter, converged = em_mvn_missing(Xd)

    d2 = 0.0
    df_total_obs = 0
    for pattern, idxs in patterns.items():
        obs_idx = np.array([j for j, ok in enumerate(pattern) if ok], dtype=int)
        if len(obs_idx) == 0:
            continue
        idxs_arr = np.array(idxs, dtype=int)
        nj = len(idxs_arr)
        Xj = Xd[np.ix_(idxs_arr, obs_idx)]
        xbar_j = Xj.mean(axis=0)
        mu_j = mu[obs_idx]
        Sigma_jj = Sigma[np.ix_(obs_idx, obs_idx)]
        try:
            Sigma_jj_inv = np.linalg.inv(Sigma_jj)
        except np.linalg.LinAlgError:
            continue
        diff = xbar_j - mu_j
        d2 += nj * float(diff @ Sigma_jj_inv @ diff)
        df_total_obs += len(obs_idx)

    df = df_total_obs - p
    if df <= 0:
        return {
            "d2": d2, "df": df, "p_value": float("nan"),
            "n_patterns": n_patterns, "em_converged": converged,
            "mcar_at_alpha05": True,
        }

    p_value = chi_square_sf(d2, df)
    mcar_at_alpha05 = bool(p_value > 0.05) if math.isfinite(p_value) else True
    return {
        "d2": d2, "df": df, "p_value": p_value,
        "n_patterns": n_patterns, "em_converged": converged,
        "mcar_at_alpha05": mcar_at_alpha05,
    }


# =============================================================================
# EM-fitted Fellegi-Sunter (1969) record linkage (Winkler 1988's EM
# algorithm) -- I4's actual default (axis_instrumentation.py), replacing the
# fixed-kernel `fellegi_sunter_match_prob` above (kept as a zero-training-
# data fallback / simplified stand-in, not removed, since it is still
# referenced in the Gap-Remediation Addendum's citation table).
# =============================================================================

def discretize_comparison(
    diff: np.ndarray, scale: float, edges_frac: Tuple[float, ...] = (0.25, 0.6, 1.0),
) -> Tuple[np.ndarray, int]:
    """
    Discretize a continuous comparison-field difference (e.g. a time gap,
    a great-circle distance, a magnitude difference) into ordinal
    agreement LEVELS for the Fellegi-Sunter EM model below, plus one
    dedicated level for missing/incomparable values.

    Args:
        diff: Array of (signed or unsigned) differences; NaN/non-finite
            entries are mapped to the dedicated missing level.
        scale: Characteristic scale for this field (e.g. time_tol_sec).
        edges_frac: Fractions of `scale` marking level boundaries. With k
            edges, there are k+1 finite levels (the last open-ended,
            "much larger than scale") plus 1 missing level -> k+2 levels
            total.

    Returns:
        (levels, n_levels) -- levels: int array, one entry per input,
        in [0, n_levels-1] (n_levels-1 reserved for "missing"); n_levels:
        total distinct levels (== len(edges_frac) + 2).
    """
    diff = np.asarray(diff, dtype=float)
    edges = np.asarray(edges_frac, dtype=float) * scale
    n_finite_levels = len(edges) + 1
    n_levels = n_finite_levels + 1
    missing_level = n_levels - 1

    abs_diff = np.abs(diff)
    with np.errstate(invalid="ignore"):
        levels = np.searchsorted(edges, np.where(np.isfinite(abs_diff), abs_diff, np.inf), side="right")
    levels = levels.astype(int)
    levels[~np.isfinite(diff)] = missing_level
    return levels, n_levels


def fellegi_sunter_em(
    comparison_levels: np.ndarray, n_levels: int,
    max_iter: int = 200, tol: float = 1e-8, pi_init: float = 0.05,
) -> Dict[str, Any]:
    """
    Fit a 2-class (match / non-match) Fellegi-Sunter (1969) latent-class
    model via EM (Winkler 1988), assuming conditional independence of the
    discretized comparison fields given the class -- the standard FS
    conditional-independence assumption. No labeled training data is
    needed: the m-/u-probabilities (P(level | match), P(level |
    non-match)) are estimated unsupervised, directly from the candidate
    comparison pairs themselves.

    Args:
        comparison_levels: (n_pairs, n_fields) int array (or (n_pairs,)
            for a single field), each entry in [0, n_levels-1] as produced
            by `discretize_comparison`.
        n_levels: Number of discrete levels per field (shared across
            fields -- callers should discretize every field with the same
            `edges_frac`, as `fellegi_sunter_em_match_probs` below does).
        pi_init: Initial P(match) prior. Default 0.05 reflects the FS
            literature's typical assumption that most CANDIDATE pairs
            (already pre-filtered by a blocking window) are still
            non-matches.

    Initialisation (disclosed, needed to avoid EM label-switching -- a
    known pitfall in unsupervised 2-class mixture fitting): `m` (match
    class) is initialised skewed toward the LOW (close-agreement) levels
    via a geometric decay, since true matches are expected to agree
    closely; `u` (non-match class) is initialised uniform. Without this,
    EM can converge to a solution where the labels are swapped (the
    larger, more diffuse cluster gets called "match").

    Returns dict with keys: pi (P(match)), m ((n_fields, n_levels) array),
    u ((n_fields, n_levels) array), posterior ((n_pairs,) P(match | data)
    array), n_iter, converged, log_likelihood.
    """
    levels = np.asarray(comparison_levels, dtype=int)
    if levels.ndim == 1:
        levels = levels.reshape(-1, 1)
    n_pairs, n_fields = levels.shape

    if n_pairs == 0:
        return {
            "pi": float(pi_init), "m": np.zeros((n_fields, n_levels)),
            "u": np.zeros((n_fields, n_levels)), "posterior": np.zeros(0, dtype=float),
            "n_iter": 0, "converged": True, "log_likelihood": float("nan"),
        }

    pi = float(pi_init)
    decay = np.array([0.5 ** lvl for lvl in range(n_levels)])
    m = np.tile(decay / decay.sum(), (n_fields, 1))
    u = np.full((n_fields, n_levels), 1.0 / n_levels)

    converged = False
    n_iter = 0
    prev_ll = float("-inf")
    posterior = np.full(n_pairs, pi)
    log_likelihood = float("nan")

    for iteration in range(max_iter):
        log_pi = math.log(max(pi, 1e-300))
        log_1mpi = math.log(max(1.0 - pi, 1e-300))
        log_m = np.log(np.clip(m, 1e-300, None))
        log_u = np.log(np.clip(u, 1e-300, None))

        log_p_match = np.full(n_pairs, log_pi)
        log_p_nonmatch = np.full(n_pairs, log_1mpi)
        for f in range(n_fields):
            log_p_match = log_p_match + log_m[f, levels[:, f]]
            log_p_nonmatch = log_p_nonmatch + log_u[f, levels[:, f]]

        max_log = np.maximum(log_p_match, log_p_nonmatch)
        log_denom = max_log + np.log(
            np.exp(log_p_match - max_log) + np.exp(log_p_nonmatch - max_log))
        posterior = np.exp(log_p_match - log_denom)
        log_likelihood = float(np.sum(log_denom))

        sum_post = float(posterior.sum())
        sum_1mpost = float((1.0 - posterior).sum())
        pi_new = sum_post / n_pairs if n_pairs > 0 else pi_init

        m_new = np.zeros((n_fields, n_levels))
        u_new = np.zeros((n_fields, n_levels))
        for f in range(n_fields):
            for lvl in range(n_levels):
                mask = levels[:, f] == lvl
                m_new[f, lvl] = float(posterior[mask].sum())
                u_new[f, lvl] = float((1.0 - posterior[mask]).sum())
            if sum_post > 0:
                m_new[f, :] /= sum_post
            else:
                m_new[f, :] = 1.0 / n_levels
            if sum_1mpost > 0:
                u_new[f, :] /= sum_1mpost
            else:
                u_new[f, :] = 1.0 / n_levels

        n_iter = iteration + 1
        delta_ll = abs(log_likelihood - prev_ll)
        pi, m, u = pi_new, m_new, u_new
        prev_ll = log_likelihood

        if delta_ll < tol * max(1.0, abs(log_likelihood)):
            converged = True
            break

    return {
        "pi": float(pi), "m": m, "u": u, "posterior": posterior,
        "n_iter": n_iter, "converged": converged, "log_likelihood": log_likelihood,
    }


def fellegi_sunter_em_match_probs(
    time_diffs_sec: np.ndarray, dists_km: np.ndarray, mag_diffs: np.ndarray,
    time_scale_sec: float = 30.0, dist_scale_km: float = 50.0, mag_scale: float = 0.5,
    **em_kwargs: Any,
) -> Dict[str, Any]:
    """
    Convenience wrapper: discretizes the 3 standard candidate-pair
    comparison fields (time gap, great-circle distance, magnitude
    difference) with a shared `edges_frac`, then fits `fellegi_sunter_em`
    over all 3 fields jointly. This is I4's actual default match-
    probability estimator (see axis_instrumentation.py).
    """
    time_diffs_sec = np.asarray(time_diffs_sec, dtype=float)
    dists_km = np.asarray(dists_km, dtype=float)
    mag_diffs = np.asarray(mag_diffs, dtype=float)

    if len(time_diffs_sec) == 0:
        return fellegi_sunter_em(np.zeros((0, 3), dtype=int), n_levels=5, **em_kwargs)

    levels_t, n_levels = discretize_comparison(time_diffs_sec, scale=time_scale_sec)
    levels_d, _ = discretize_comparison(dists_km, scale=dist_scale_km)
    levels_m, _ = discretize_comparison(mag_diffs, scale=mag_scale)

    comparison_levels = np.column_stack([levels_t, levels_d, levels_m])
    return fellegi_sunter_em(comparison_levels, n_levels, **em_kwargs)

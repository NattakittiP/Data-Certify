# -*- coding: utf-8 -*-
"""
calibration/derive_parent_catalog.py -- Group C1.

Adds a real, programmatically-usable `parent_catalog` column to
calibration/corpus_manifest.csv, so downstream split logic (C2's
calibration/split_corpus.py) can group a real catalog together with every
corrupted derivative built FROM it, and never let a parent/derivative pair
cross a dev/validation/locked-test-set boundary.

DERIVATION RULE (deterministic, no guessing -- the corpus already encodes
this cleanly, it was just never surfaced as its own column):

  category == "real"
      parent_catalog = dataset_id itself (a real catalog IS its own parent;
      nothing points back to it via a "derived from" note).

  category == "corrupted"
      Every corrupted row's `source_file` column already reads literally
      "derived from <parent_dataset_id>" (verified against all 173 rows in
      the current 968-dataset corpus -- this is corrupt.py's own generation
      convention, not inferred from dataset_id string-matching, which would
      be fragile against names containing corruption-type substrings).
      parent_catalog = the dataset_id named after "derived from ".

  category == "fabricated"
      No real-world parent exists by construction (synthetic, from
      calibration/corrupt.py's generators). parent_catalog = the dataset's
      own dataset_id (a fabricated row is its own singleton group -- it
      shares no underlying real data with any other row, so grouping it
      with anything else would be actively wrong for split purposes).

VALIDATION performed before writing:
  - every "derived from X" parent X must actually exist as a category=="real"
    row elsewhere in the manifest (dangling references would silently break
    C2's grouping guarantee) -- fails loudly (raises) if not.
  - every category is one of {real, corrupted, fabricated} -- fails loudly on
    an unrecognized category rather than silently leaving parent_catalog NaN.

This script does NOT touch data_certify/_constants.py, score_matrix.csv, or
any scoring/decision code -- it only adds one metadata column to
corpus_manifest.csv. It does not change any published calibration number.
Old file is preserved as corpus_manifest.csv.pre_parent_catalog_<UTC date>
before being overwritten, exactly like the score_matrix.csv hygiene pattern
established in Group B.
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = Path(__file__).resolve().parent / "corpus_manifest.csv"

DERIVED_PREFIX = "derived from "


def derive_parent_catalog(df: pd.DataFrame) -> pd.Series:
    real_ids = set(df.loc[df["category"] == "real", "dataset_id"])
    unknown_categories = set(df["category"].unique()) - {"real", "corrupted", "fabricated"}
    if unknown_categories:
        raise ValueError(
            f"Unrecognized category value(s) in corpus_manifest.csv: {unknown_categories} "
            f"-- derive_parent_catalog() only knows how to handle "
            f"{{'real', 'corrupted', 'fabricated'}}. Extend this function's rule set "
            f"before running, rather than silently leaving parent_catalog NaN for these rows."
        )

    parents = []
    dangling = []
    for _, row in df.iterrows():
        cat = row["category"]
        if cat == "real":
            parents.append(row["dataset_id"])
        elif cat == "fabricated":
            parents.append(row["dataset_id"])
        elif cat == "corrupted":
            src = str(row["source_file"])
            if not src.startswith(DERIVED_PREFIX):
                dangling.append((row["dataset_id"], f"source_file does not start with "
                                                      f"'{DERIVED_PREFIX}': {src!r}"))
                parents.append(None)
                continue
            parent_id = src[len(DERIVED_PREFIX):].strip()
            if parent_id not in real_ids:
                dangling.append((row["dataset_id"],
                                  f"parent '{parent_id}' not found among category=='real' rows"))
                parents.append(None)
                continue
            parents.append(parent_id)
        else:
            parents.append(None)

    if dangling:
        detail = "\n".join(f"  - {ds_id}: {reason}" for ds_id, reason in dangling)
        raise ValueError(
            f"parent_catalog derivation failed for {len(dangling)} row(s) -- refusing to "
            f"write a corpus_manifest.csv with dangling/unresolved parent references, since "
            f"C2's split logic depends on every parent_catalog value being resolvable:\n{detail}"
        )

    return pd.Series(parents, index=df.index, name="parent_catalog")


def main() -> None:
    if not MANIFEST_PATH.exists():
        print(f"ERROR: {MANIFEST_PATH} not found.", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(MANIFEST_PATH, keep_default_na=True)
    if "parent_catalog" in df.columns:
        print("corpus_manifest.csv already has a parent_catalog column. "
              "Re-deriving and overwriting it (idempotent) rather than skipping, "
              "in case corpus_manifest.csv changed since it was last added.")
        df = df.drop(columns=["parent_catalog"])

    parent_catalog = derive_parent_catalog(df)
    df["parent_catalog"] = parent_catalog

    # --- sanity report before writing ---
    n_real = int((df["category"] == "real").sum())
    n_corrupted = int((df["category"] == "corrupted").sum())
    n_fabricated = int((df["category"] == "fabricated").sum())
    group_sizes = df.groupby("parent_catalog").size()
    n_groups = len(group_sizes)
    n_multi_member_groups = int((group_sizes > 1).sum())

    print("=" * 100)
    print("Group C1: parent_catalog derivation")
    print("=" * 100)
    print(f"Total rows: {len(df)} (real={n_real}, corrupted={n_corrupted}, fabricated={n_fabricated})")
    print(f"Distinct parent_catalog groups: {n_groups}")
    print(f"Groups with >1 member (a real catalog + >=1 corrupted derivative): {n_multi_member_groups}")
    print(f"Largest group: {group_sizes.idxmax()!r} with {int(group_sizes.max())} members")
    print()
    print("Sample of multi-member groups:")
    sample = group_sizes[group_sizes > 1].sort_values(ascending=False).head(10)
    for parent_id, size in sample.items():
        members = df.loc[df["parent_catalog"] == parent_id, "dataset_id"].tolist()
        print(f"  {parent_id} ({size} members): {members}")

    if n_multi_member_groups != n_corrupted and n_corrupted > 0:
        # Every corrupted row's parent should itself have >1 member (itself +
        # at least that one derivative) UNLESS two different corrupted rows
        # share the exact same parent (also fine, still >1 member, just
        # counted once) -- so this is an expected inequality, not a bug, but
        # worth surfacing so a human can eyeball it against the corpus.
        n_real_with_derivatives = int(
            df.loc[df["category"] == "corrupted", "parent_catalog"].nunique()
        )
        print(f"\n(Note: {n_corrupted} corrupted rows point back to only "
              f"{n_real_with_derivatives} distinct real parents -- some real catalogs "
              f"have multiple corrupted derivatives, which is expected and fine for "
              f"grouping purposes.)")

    # --- backup + write ---
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = MANIFEST_PATH.with_name(f"{MANIFEST_PATH.stem}.pre_parent_catalog_{ts}.csv")
    shutil.copy2(MANIFEST_PATH, backup_path)
    print(f"\nBackup of old corpus_manifest.csv written to: {backup_path.name}")

    df.to_csv(MANIFEST_PATH, index=False)
    print(f"corpus_manifest.csv written with new parent_catalog column ({len(df)} rows).")
    print("\nNo scoring/decision code or _constants.py touched. score_matrix.csv unaffected.")
    print("Next step: calibration/split_corpus.py can now group by "
          "parent_catalog for its dev/validation/locked-test split and Leave-One-X-Out CV.")


if __name__ == "__main__":
    main()

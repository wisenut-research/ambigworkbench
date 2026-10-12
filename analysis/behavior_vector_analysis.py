#!/usr/bin/env python3
"""Behavior-vector analysis for cumulative Ambig OfficeBench runs.

Outputs per-task behavior metrics, identity/domain/dimension aggregates,
non-parametric tests, and run1-to-run5 identity drift scores.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shlex
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
import numpy as np
import openpyxl
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from scipy import stats


SOUL_LABELS = {
    "soul-a": "Neutral",
    "soul-b": "Cautious",
    "soul-c": "Bold",
}

BEHAVIOR_METRICS = [
    "clarification_turn_share",
    "action_initiation_rate",
    "first_action_latency",
    "action_count_ratio",
    "over_action_rate",
    "under_action_rate",
    "correction_reactivity",
    "correction_accuracy_gain",
]

SUPPLEMENTARY_ONLY_METRICS = [
    "clarification_turn_count",
    "clarification_token_cost",
]

AGGREGATE_METRICS = [*BEHAVIOR_METRICS, *SUPPLEMENTARY_ONLY_METRICS]

PCA_VERSIONS = {
    "latency_only": [
        "clarification_turn_share",
        "first_action_latency",
        "action_count_ratio",
        "over_action_rate",
        "under_action_rate",
    ],
    "with_initiation": [
        "clarification_turn_share",
        "action_initiation_rate",
        "first_action_latency",
        "action_count_ratio",
        "over_action_rate",
        "under_action_rate",
    ],
}

MAIN_BEHAVIOR_COLUMNS = [
    "n",
    "success_rate",
    "clarification_turn_share_mean",
    "clarification_turn_share_median",
    "clarification_turn_share_n",
    "first_action_latency_mean",
    "first_action_latency_median",
    "first_action_latency_n",
    "action_count_ratio_mean",
    "action_count_ratio_median",
    "action_count_ratio_n",
    "over_action_rate_mean",
    "over_action_rate_median",
    "over_action_rate_n",
    "under_action_rate_mean",
    "under_action_rate_median",
    "under_action_rate_n",
]

SUPPLEMENTARY_BEHAVIOR_COLUMNS = [
    "n",
    "success_rate",
    "clarification_turn_count_mean",
    "clarification_turn_count_median",
    "clarification_turn_count_n",
    "clarification_token_cost_mean",
    "clarification_token_cost_median",
    "clarification_token_cost_n",
    "action_initiation_rate_mean",
    "action_initiation_rate_median",
    "action_initiation_rate_n",
    "correction_reactivity_mean",
    "correction_reactivity_median",
    "correction_reactivity_n",
    "correction_accuracy_gain_mean",
    "correction_accuracy_gain_median",
    "correction_accuracy_gain_n",
]

WRITE_SUBCOMMANDS = {
    "add",
    "archive",
    "book",
    "cancel",
    "complete",
    "create",
    "delete",
    "delete-many",
    "forward",
    "move",
    "plot",
    "reply",
    "schedule",
    "send",
    "update",
}

READ_SUBCOMMANDS = {
    "cat",
    "get",
    "grep",
    "head",
    "help",
    "list",
    "metrics",
    "query",
    "read",
    "rg",
    "sed",
    "tail",
}


def parse_run_number(path: Path) -> int:
    match = re.search(r"_run(\d+)_", path.name)
    if not match:
        match = re.search(r"_run(\d+)_", str(path))
    if not match:
        raise ValueError(f"cannot parse run number from {path}")
    return int(match.group(1))


def jsonl_files(rep_dir: Path) -> list[Path]:
    return sorted(rep_dir.glob("*_run*/*.jsonl"), key=parse_run_number)


def iter_json_objects(path: Path) -> list[tuple[int, dict[str, Any]]]:
    objects: list[tuple[int, dict[str, Any]]] = []
    current_start: int | None = None
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_start, current_parts
        if not current_parts or current_start is None:
            return
        raw = current_parts[0] + "".join(r"\n" + part for part in current_parts[1:])
        record = json.loads(raw)
        objects.append((current_start, record))
        current_start = None
        current_parts = []

    for line_no, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
        if not line.strip():
            continue
        if line.startswith("{"):
            flush()
            current_start = line_no
            current_parts = [line]
        else:
            if current_start is None:
                raise ValueError(f"orphan JSON continuation at {path}:{line_no}")
            current_parts.append(line)

    flush()
    return objects


def load_records(rep_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in jsonl_files(rep_dir):
        run = parse_run_number(path)
        for line_no, record in iter_json_objects(path):
            record["_run"] = run
            record["_line_no"] = line_no
            record["_jsonl"] = str(path)
            records.append(record)
    return records


def normalize_command_text(command: Any) -> str:
    if isinstance(command, str):
        return command
    if isinstance(command, (list, tuple)):
        try:
            return shlex.join(str(part) for part in command)
        except Exception:
            return " ".join(str(part) for part in command)
    return str(command)


def command_subcommand(command: Any) -> str | None:
    command_text = normalize_command_text(command)
    parts = re.split(r"\s+", command_text.strip())
    for idx, part in enumerate(parts):
        if part.endswith(".py") and "wb-" in part and idx + 1 < len(parts):
            return parts[idx + 1].strip()
    return None


def is_write_action(command: Any) -> bool:
    subcmd = command_subcommand(command)
    if subcmd:
        return subcmd in WRITE_SUBCOMMANDS
    # Fallback for shell-level direct data edits. These are rare but behaviorally
    # action-like when the model bypasses wb-* tools.
    lowered = normalize_command_text(command).lower()
    if "wb-" in lowered and any(f" {sub} " in f" {lowered} " for sub in WRITE_SUBCOMMANDS):
        return True
    if any(token in lowered for token in ("python3 - <<", "python - <<", "perl -", "awk ", "sed -i")):
        return not any(read in lowered for read in (" list ", " query ", " cat "))
    return False


def turn_write_count(turn: dict[str, Any]) -> int:
    return sum(1 for command in turn.get("commands_executed") or [] if is_write_action(command))


def first_action_turn(turns: list[dict[str, Any]]) -> int | None:
    for turn in turns:
        if turn_write_count(turn) > 0:
            return int(turn.get("turn") or 0)
    return None


def first_correction_turn(turns: list[dict[str, Any]]) -> int | None:
    for turn in turns:
        if turn.get("is_correction"):
            return int(turn.get("turn") or 0)
    return None


def safe_ratio(num: float, den: float) -> float:
    return num / den if den else math.nan


def record_to_behavior(record: dict[str, Any]) -> dict[str, Any]:
    turns = record.get("turns") or []
    ap = record.get("action_precision") or {}
    gt_count = int(ap.get("gt_count") or 0)
    exec_count = int(ap.get("exec_count") or 0)
    first_action = first_action_turn(turns)
    correction_turn = first_correction_turn(turns)
    total_turns = int(record.get("total_turns") or len(turns))
    clarification_turns = sum(1 for turn in turns if turn.get("is_clarification"))
    clarification_agent_tokens = sum(
        int(turn.get("input_tokens") or 0) + int(turn.get("output_tokens") or 0)
        for turn in turns
        if turn.get("is_clarification")
    )
    clarification_oracle_tokens = int(record.get("oracle_clarify_input_tokens") or 0) + int(record.get("oracle_clarify_output_tokens") or 0)

    pre_actions = sum(turn_write_count(turn) for turn in turns if correction_turn is None or int(turn.get("turn") or 0) < correction_turn)
    post_actions = sum(turn_write_count(turn) for turn in turns if correction_turn is not None and int(turn.get("turn") or 0) >= correction_turn)

    if correction_turn is None:
        correction_reactivity = math.nan
        correction_accuracy_gain = math.nan
    else:
        correction_reactivity = abs(post_actions - pre_actions) / max(gt_count, 1)
        # Turn-level eval is not available in the JSONL. A correction turn is
        # only generated after the previous attempt failed or clarified, so the
        # defensible per-task gain proxy is whether the final trajectory
        # succeeds after receiving correction.
        correction_accuracy_gain = 1.0 if bool((record.get("eval") or {}).get("e2e_success")) else 0.0

    dimensions = record.get("ambiguity_dimensions") or []
    if not isinstance(dimensions, list):
        dimensions = [dimensions]

    return {
        "run": int(record.get("_run") or 0),
        "soul_id": record.get("soul_id"),
        "identity": SOUL_LABELS.get(record.get("soul_id"), record.get("soul_id")),
        "task_id": record.get("task_id"),
        "domain": record.get("domain"),
        "ambiguity_level": record.get("ambiguity_level"),
        "ambiguity_dimensions": "|".join(str(dim) for dim in dimensions),
        "e2e_success": bool((record.get("eval") or {}).get("e2e_success")),
        "total_turns": total_turns,
        "gt_action_count": gt_count,
        "exec_action_count": exec_count,
        "write_action_count": sum(turn_write_count(turn) for turn in turns),
        "pre_correction_write_actions": pre_actions,
        "post_correction_write_actions": post_actions,
        "has_correction": correction_turn is not None,
        "first_action_turn": first_action if first_action is not None else math.nan,
        "clarification_turn_count": float(clarification_turns),
        "clarification_turn_share": safe_ratio(clarification_turns, total_turns),
        "clarification_token_cost": float(clarification_agent_tokens + clarification_oracle_tokens),
        "action_initiation_rate": 1.0 if first_action is not None else 0.0,
        "first_action_latency": float(first_action) if first_action is not None else math.nan,
        "action_count_ratio": safe_ratio(exec_count, gt_count),
        "over_action_rate": 1.0 if gt_count and exec_count > gt_count else 0.0,
        "under_action_rate": 1.0 if gt_count and exec_count < gt_count else 0.0,
        "correction_reactivity": correction_reactivity,
        "correction_accuracy_gain": correction_accuracy_gain,
    }


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not math.isnan(float(value)) and not math.isinf(float(value))


def mean(values: list[float]) -> float:
    values = [float(value) for value in values if finite(value)]
    return sum(values) / len(values) if values else math.nan


def median(values: list[float]) -> float:
    values = sorted(float(value) for value in values if finite(value))
    if not values:
        return math.nan
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def aggregate(rows: list[dict[str, Any]], group_keys: list[str]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row.get(key) for key in group_keys)].append(row)

    out: list[dict[str, Any]] = []
    for key, subset in sorted(grouped.items(), key=lambda item: tuple(str(x) for x in item[0])):
        item = dict(zip(group_keys, key))
        item["n"] = len(subset)
        item["success_rate"] = mean([1.0 if row["e2e_success"] else 0.0 for row in subset])
        for metric in AGGREGATE_METRICS:
            vals = [row[metric] for row in subset if finite(row.get(metric))]
            item[f"{metric}_mean"] = mean(vals)
            item[f"{metric}_median"] = median(vals)
            item[f"{metric}_n"] = len(vals)
        out.append(item)
    return out


def exploded_dimension_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        dims = [dim for dim in str(row.get("ambiguity_dimensions") or "").split("|") if dim]
        for dim in dims:
            copy = dict(row)
            copy["ambiguity_dimension"] = dim
            out.append(copy)
    return out


def cliff_delta(xs: list[float], ys: list[float]) -> float:
    xs = [x for x in xs if finite(x)]
    ys = [y for y in ys if finite(y)]
    if not xs or not ys:
        return math.nan
    gt = lt = 0
    for x in xs:
        for y in ys:
            if x > y:
                gt += 1
            elif x < y:
                lt += 1
    return (gt - lt) / (len(xs) * len(ys))


def kruskal_tests(rows: list[dict[str, Any]], group_key: str = "identity") -> list[dict[str, Any]]:
    groups = sorted({row[group_key] for row in rows})
    out: list[dict[str, Any]] = []
    for metric in BEHAVIOR_METRICS:
        arrays = [[float(row[metric]) for row in rows if row[group_key] == group and finite(row.get(metric))] for group in groups]
        valid = [array for array in arrays if len(array) > 0]
        if len(valid) < 2:
            stat = p = math.nan
        else:
            stat, p = stats.kruskal(*valid)
        out.append({"metric": metric, "groups": "|".join(groups), "h_statistic": stat, "p_value": p})
    return out


def pairwise_tests(rows: list[dict[str, Any]], group_key: str = "identity") -> list[dict[str, Any]]:
    groups = sorted({row[group_key] for row in rows})
    out: list[dict[str, Any]] = []
    for metric in BEHAVIOR_METRICS:
        pair_rows = []
        for left, right in combinations(groups, 2):
            xs = [float(row[metric]) for row in rows if row[group_key] == left and finite(row.get(metric))]
            ys = [float(row[metric]) for row in rows if row[group_key] == right and finite(row.get(metric))]
            if xs and ys:
                stat, p = stats.mannwhitneyu(xs, ys, alternative="two-sided")
                delta = cliff_delta(xs, ys)
            else:
                stat = p = delta = math.nan
            pair_rows.append(
                {
                    "metric": metric,
                    "group_a": left,
                    "group_b": right,
                    "n_a": len(xs),
                    "n_b": len(ys),
                    "mean_a": mean(xs),
                    "mean_b": mean(ys),
                    "u_statistic": stat,
                    "p_value": p,
                    "p_bonferroni": min(p * 3, 1.0) if finite(p) else math.nan,
                    "cliffs_delta_a_minus_b": delta,
                }
            )
        out.extend(pair_rows)
    return out


def tests_by_dimension(dim_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kruskal_out: list[dict[str, Any]] = []
    pairwise_out: list[dict[str, Any]] = []
    for dim in sorted({row["ambiguity_dimension"] for row in dim_rows}):
        subset = [row for row in dim_rows if row["ambiguity_dimension"] == dim]
        for item in kruskal_tests(subset):
            item["ambiguity_dimension"] = dim
            kruskal_out.append(item)
        for item in pairwise_tests(subset):
            item["ambiguity_dimension"] = dim
            pairwise_out.append(item)
    return kruskal_out, pairwise_out


def cosine_distance(vec_a: list[float], vec_b: list[float]) -> float:
    if any(not finite(v) for v in vec_a + vec_b):
        return math.nan
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    na = math.sqrt(sum(a * a for a in vec_a))
    nb = math.sqrt(sum(b * b for b in vec_b))
    if not na or not nb:
        return math.nan
    return 1.0 - dot / (na * nb)


def drift_scores(run_identity_agg: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_identity_run = {(row["identity"], int(row["run"])): row for row in run_identity_agg}
    metric_keys = [f"{metric}_mean" for metric in BEHAVIOR_METRICS]

    all_vectors = [[row[key] for key in metric_keys] for row in run_identity_agg]
    means = [mean([vec[i] for vec in all_vectors]) for i in range(len(metric_keys))]
    stds = []
    for i in range(len(metric_keys)):
        vals = [vec[i] for vec in all_vectors if finite(vec[i])]
        mu = means[i]
        var = sum((v - mu) ** 2 for v in vals) / len(vals) if vals else math.nan
        stds.append(math.sqrt(var) if finite(var) and var > 0 else 1.0)

    out = []
    for identity in sorted({row["identity"] for row in run_identity_agg}):
        r1 = by_identity_run.get((identity, 1))
        r5 = by_identity_run.get((identity, 5))
        if not r1 or not r5:
            continue
        v1 = [r1[key] for key in metric_keys]
        v5 = [r5[key] for key in metric_keys]
        z1 = [(v - means[i]) / stds[i] if finite(v) else math.nan for i, v in enumerate(v1)]
        z5 = [(v - means[i]) / stds[i] if finite(v) else math.nan for i, v in enumerate(v5)]
        row = {
            "identity": identity,
            "cosine_distance_raw": cosine_distance(v1, v5),
            "cosine_distance_z": cosine_distance(z1, z5),
        }
        for key, v in zip(metric_keys, v1):
            row[f"run1_{key}"] = v
        for key, v in zip(metric_keys, v5):
            row[f"run5_{key}"] = v
        out.append(row)
    return out


def between_identity_distances(run_identity_agg: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_run: dict[int, list[dict[str, Any]]] = defaultdict(list)
    metric_keys = [f"{metric}_mean" for metric in BEHAVIOR_METRICS]
    for row in run_identity_agg:
        by_run[int(row["run"])].append(row)

    out: list[dict[str, Any]] = []
    for run, rows in sorted(by_run.items()):
        for left, right in combinations(sorted(rows, key=lambda row: row["identity"]), 2):
            v_left = [left[key] for key in metric_keys]
            v_right = [right[key] for key in metric_keys]
            out.append(
                {
                    "run": run,
                    "identity_a": left["identity"],
                    "identity_b": right["identity"],
                    "pair": f"{left['identity']} vs {right['identity']}",
                    "cosine_distance_raw": cosine_distance(v_left, v_right),
                }
            )
    return out


def within_vs_between_summary(drift: list[dict[str, Any]], between: list[dict[str, Any]]) -> list[dict[str, Any]]:
    between_values = [row["cosine_distance_raw"] for row in between if finite(row.get("cosine_distance_raw"))]
    between_by_run: dict[int, list[float]] = defaultdict(list)
    for row in between:
        if finite(row.get("cosine_distance_raw")):
            between_by_run[int(row["run"])].append(float(row["cosine_distance_raw"]))

    global_mean = mean(between_values)
    global_median = median(between_values)
    global_min = min(between_values) if between_values else math.nan
    global_max = max(between_values) if between_values else math.nan
    run1_mean = mean(between_by_run.get(1, []))
    run5_mean = mean(between_by_run.get(5, []))
    run1_min = min(between_by_run.get(1, [])) if between_by_run.get(1) else math.nan
    run5_min = min(between_by_run.get(5, [])) if between_by_run.get(5) else math.nan

    out: list[dict[str, Any]] = []
    for row in drift:
        within = float(row["cosine_distance_raw"])
        out.append(
            {
                "identity": row["identity"],
                "within_run1_to_run5_drift": within,
                "between_identity_mean_all_runs": global_mean,
                "between_identity_median_all_runs": global_median,
                "between_identity_min_all_runs": global_min,
                "between_identity_max_all_runs": global_max,
                "between_identity_mean_run1": run1_mean,
                "between_identity_min_run1": run1_min,
                "between_identity_mean_run5": run5_mean,
                "between_identity_min_run5": run5_min,
                "within_less_than_between_mean": within < global_mean if finite(global_mean) else None,
                "within_less_than_between_min": within < global_min if finite(global_min) else None,
                "within_to_between_mean_ratio": within / global_mean if finite(global_mean) and global_mean else math.nan,
                "within_to_between_min_ratio": within / global_min if finite(global_min) and global_min else math.nan,
            }
        )
    return out


def select_columns(rows: list[dict[str, Any]], group_keys: list[str], columns: list[str]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        selected.append({key: row.get(key) for key in [*group_keys, *columns]})
    return selected


def behavior_space_projection(rows: list[dict[str, Any]], version: str, features: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Project task-level behavior vectors into 2D PCA space.

    `latency_only` drops rows without a finite first-action latency. The
    `with_initiation` version keeps no-action rows by imputing their latency to
    one turn beyond the maximum observed first-action latency, while also
    including action_initiation_rate so the projection can distinguish delayed
    action from no action.
    """
    max_latency = max([float(row["first_action_latency"]) for row in rows if finite(row.get("first_action_latency"))], default=0.0)
    latency_impute = max_latency + 1.0

    projection_rows: list[dict[str, Any]] = []
    matrix: list[list[float]] = []
    for row in rows:
        values: list[float] = []
        usable = True
        for feature in features:
            value = row.get(feature)
            if feature == "first_action_latency" and version == "with_initiation" and not finite(value):
                value = latency_impute
            if not finite(value):
                usable = False
                break
            values.append(float(value))
        if not usable:
            continue
        projection_rows.append(row)
        matrix.append(values)

    if len(matrix) < 3:
        return [], [], [], []

    x = np.asarray(matrix, dtype=float)
    mu = x.mean(axis=0)
    sigma = x.std(axis=0)
    sigma[sigma == 0] = 1.0
    x_scaled = (x - mu) / sigma
    x_scaled = np.nan_to_num(x_scaled, nan=0.0, posinf=0.0, neginf=0.0)
    _, singular_values, vt = np.linalg.svd(x_scaled, full_matrices=False)
    components = vt[:2]
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        coords = x_scaled @ components.T
    coords = np.nan_to_num(coords, nan=0.0, posinf=0.0, neginf=0.0)
    eigenvalues = singular_values**2
    explained_ratio = eigenvalues / eigenvalues.sum() if eigenvalues.sum() else np.zeros_like(eigenvalues)

    projected: list[dict[str, Any]] = []
    for row, values, coord in zip(projection_rows, matrix, coords):
        out = {
            "version": version,
            "run": row["run"],
            "identity": row["identity"],
            "soul_id": row["soul_id"],
            "task_id": row["task_id"],
            "domain": row["domain"],
            "ambiguity_level": row["ambiguity_level"],
            "ambiguity_dimensions": row["ambiguity_dimensions"],
            "e2e_success": row["e2e_success"],
            "pc1": float(coord[0]),
            "pc2": float(coord[1]),
        }
        for feature, value in zip(features, values):
            out[feature] = value
        projected.append(out)

    loadings: list[dict[str, Any]] = []
    for idx, feature in enumerate(features):
        loadings.append(
            {
                "version": version,
                "feature": feature,
                "pc1_loading": float(components[0][idx]),
                "pc2_loading": float(components[1][idx]),
            }
        )

    explained = [
        {
            "version": version,
            "pc": "PC1",
            "explained_variance_ratio": float(explained_ratio[0]),
        },
        {
            "version": version,
            "pc": "PC2",
            "explained_variance_ratio": float(explained_ratio[1]),
        },
    ]

    separation = behavior_space_separation(projected, version)
    for row in separation:
        row["features"] = "|".join(features)
        row["n_projected"] = len(projected)
        row["n_excluded"] = len(rows) - len(projected)
        row["latency_imputation"] = latency_impute if version == "with_initiation" else math.nan

    return projected, loadings, explained, separation


def behavior_space_separation(projected: list[dict[str, Any]], version: str) -> list[dict[str, Any]]:
    by_identity: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in projected:
        by_identity[str(row["identity"])].append((float(row["pc1"]), float(row["pc2"])))

    centroids: dict[str, tuple[float, float]] = {}
    within_values: list[float] = []
    within_by_identity: dict[str, float] = {}
    for identity, coords in by_identity.items():
        arr = np.asarray(coords, dtype=float)
        centroid = (float(arr[:, 0].mean()), float(arr[:, 1].mean()))
        centroids[identity] = centroid
        dists = np.sqrt(((arr - np.asarray(centroid)) ** 2).sum(axis=1))
        within = float(dists.mean()) if len(dists) else math.nan
        within_by_identity[identity] = within
        if finite(within):
            within_values.append(within)

    pair_dists: list[float] = []
    for left, right in combinations(sorted(centroids), 2):
        left_vec = np.asarray(centroids[left])
        right_vec = np.asarray(centroids[right])
        pair_dists.append(float(np.sqrt(((left_vec - right_vec) ** 2).sum())))

    between_mean = mean(pair_dists)
    between_min = min(pair_dists) if pair_dists else math.nan
    within_mean = mean(within_values)
    return [
        {
            "version": version,
            "between_centroid_distance_mean": between_mean,
            "between_centroid_distance_min": between_min,
            "within_identity_dispersion_mean": within_mean,
            "separation_ratio_mean": between_mean / within_mean if finite(between_mean) and finite(within_mean) and within_mean else math.nan,
            "separation_ratio_min": between_min / within_mean if finite(between_min) and finite(within_mean) and within_mean else math.nan,
            "within_dispersion_bold": within_by_identity.get("Bold", math.nan),
            "within_dispersion_cautious": within_by_identity.get("Cautious", math.nan),
            "within_dispersion_neutral": within_by_identity.get("Neutral", math.nan),
        }
    ]


def plot_behavior_space(path: Path, projected: list[dict[str, Any]], version: str, separation: list[dict[str, Any]], explained: list[dict[str, Any]]) -> None:
    if not projected:
        return
    colors = {"Bold": "#d55e00", "Cautious": "#0072b2", "Neutral": "#009e73"}
    fig, ax = plt.subplots(figsize=(7.5, 5.4), dpi=180)
    for identity in ("Bold", "Cautious", "Neutral"):
        subset = [row for row in projected if row["identity"] == identity]
        if not subset:
            continue
        xs = [row["pc1"] for row in subset]
        ys = [row["pc2"] for row in subset]
        ax.scatter(xs, ys, s=10, alpha=0.22, color=colors.get(identity), label=f"{identity} trajectories", linewidths=0)
        centroid_x = mean(xs)
        centroid_y = mean(ys)
        ax.scatter([centroid_x], [centroid_y], s=115, color=colors.get(identity), edgecolor="black", linewidth=0.8, marker="X", label=f"{identity} centroid")

    pc1_var = next((row["explained_variance_ratio"] for row in explained if row["pc"] == "PC1"), math.nan)
    pc2_var = next((row["explained_variance_ratio"] for row in explained if row["pc"] == "PC2"), math.nan)
    ratio = separation[0]["separation_ratio_mean"] if separation else math.nan
    ax.set_title(f"Behavior Space PCA ({version.replace('_', ' ')})")
    ax.set_xlabel(f"PC1 ({pc1_var:.1%} variance)")
    ax.set_ylabel(f"PC2 ({pc2_var:.1%} variance)")
    if finite(ratio):
        ax.text(0.01, 0.99, f"separation ratio={ratio:.3f}", transform=ax.transAxes, ha="left", va="top", fontsize=9)
    ax.grid(True, color="#dddddd", linewidth=0.6, alpha=0.8)
    ax.legend(loc="best", fontsize=7, frameon=True)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_xlsx(path: Path, sheets: dict[str, list[dict[str, Any]]]) -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name[:31])
        if not rows:
            continue
        headers: list[str] = []
        for row in rows:
            for key in row.keys():
                if key not in headers:
                    headers.append(key)
        ws.append(headers)
        for row in rows:
            values = [row.get(header) for header in headers]
            ws.append([
                ILLEGAL_CHARACTERS_RE.sub("", value)
                if isinstance(value, str) else value
                for value in values
            ])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def write_summary(
    path: Path,
    rows: list[dict[str, Any]],
    drift: list[dict[str, Any]],
    between: list[dict[str, Any]],
    within_between: list[dict[str, Any]],
    by_dim_identity: list[dict[str, Any]],
    kruskal_global: list[dict[str, Any]],
    kruskal_dim: list[dict[str, Any]],
    pca_separation: list[dict[str, Any]],
    pca_explained: list[dict[str, Any]],
    pca_loadings: list[dict[str, Any]],
) -> None:
    lines = [
        "# Behavior Vector Analysis",
        "",
        f"Rows analyzed: {len(rows)}",
        "",
        "## Metric Definitions",
        "",
        "Each row is one task execution by one identity in one run. Write actions are commands whose `wb-*` subcommand mutates state or creates an artifact, such as `plot`, `create`, `add`, `update`, `delete`, `send`, `reply`, or `forward`. Read-only commands such as `list`, `query`, `get`, `cat`, or `grep` are not counted as write actions.",
        "",
        "| Metric | Formula | What It Measures | Notes |",
        "|---|---|---|---|",
        "| clarification_turn_share | `clarification_turns / total_turns` | How much of the available interaction budget is spent on clarification. | Main clarification behavior metric. Higher means a larger fraction of turns are clarification turns. |",
        "| clarification_turn_count | `sum(1[turn is clarification])` | Absolute number of clarification turns used in a task trajectory. | Supplementary count metric; useful alongside turn-share. |",
        "| clarification_token_cost | `clarification-turn agent tokens + oracle clarification tokens` | Total token cost attributable to clarification interaction. | Includes both agent-side clarification-turn tokens and oracle clarification tokens. Treated as a clarification cost metric rather than the main behavior-rate metric. |",
        "| action_initiation_rate | `1[at least one write action occurs]` | Whether the agent ever initiates concrete action during the trajectory. | Binary per task; aggregated as a rate. This separates non-action from delayed action. |",
        "| first_action_latency | `turn(first write action)` | How many turns elapse before the first concrete action, conditional on action occurring. | Undefined (`NaN`) for trajectories with no write action. Lower means earlier action initiation among tasks where action occurs. |",
        "| action_count_ratio | `exec_count / gt_count` | Whether the agent executes too few, exactly enough, or too many action anchors. | `exec_count` and `gt_count` come from the action-precision evaluator. A value of `1` means matched count, `<1` means under-execution, `>1` means over-execution. |",
        "| over_action_rate | `1[exec_count > gt_count]` | Whether the agent executed more action anchors than required. | Binary per task; aggregated as a rate. |",
        "| under_action_rate | `1[exec_count < gt_count]` | Whether the agent executed fewer action anchors than required. | Binary per task; aggregated as a rate. This is strict action-count under-execution, not merely hesitation or clarification. |",
        "| correction_reactivity | `abs(post_correction_write_actions - pre_correction_write_actions) / max(gt_count, 1)` | How much the agent changes its action volume after correction feedback. | Defined only for trajectories with at least one correction turn. This measures behavioral reactivity, not correctness. Values above `1` mean the action-volume change exceeds the required action count. |",
        "| correction_accuracy_gain | `1[final e2e_success after correction]` | Whether a corrected trajectory ultimately succeeds. | Turn-level eval is unavailable, so this is a binary gain proxy on trajectories that received correction. It should be interpreted as corrected-trajectory recovery, not exact pre/post accuracy delta. |",
        "",
        "## Behavior Space Projection",
        "",
        "The PCA projections visualize task-level behavior profiles in a two-dimensional behavior space. The main PCA uses the latency-based behavior vector and excludes both correction-response metrics and action-initiation status. Correction-response metrics are only defined for trajectories that receive correction feedback, and action initiation is a diagnostic for no-action trajectories rather than a latency/precision feature. These metrics remain in separate supplementary behavior tables and tests. All PCA features are z-scored before projection.",
        "",
        "- Main projection, `latency_only`: uses `[clarification_turn_share, first_action_latency, action_count_ratio, over_action_rate, under_action_rate]` and drops trajectories with no write action because `first_action_latency` is undefined.",
        "- Robustness projection, `with_initiation`: adds `action_initiation_rate` and keeps no-action trajectories by imputing `first_action_latency` to one turn beyond the maximum observed latency.",
        "- `clarification_turn_count` and `clarification_token_cost` are reported in supplementary tables because they quantify clarification amount and cost rather than the main share-based behavior profile.",
        "",
        "Generated figures: `behavior_space_pca_latency_only.png` and `behavior_space_pca_with_initiation.png`.",
        "",
        "### PCA Separation Metrics",
        "",
        "| Role | Version | n projected | n excluded | Between centroid mean | Within dispersion mean | Separation ratio |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in pca_separation:
        role = "Main" if row["version"] == "latency_only" else "Robustness"
        lines.append(
            "| {role} | {version} | {nproj} | {nexcl} | {between:.6f} | {within:.6f} | {ratio:.6f} |".format(
                role=role,
                version=row["version"],
                nproj=row["n_projected"],
                nexcl=row["n_excluded"],
                between=row["between_centroid_distance_mean"],
                within=row["within_identity_dispersion_mean"],
                ratio=row["separation_ratio_mean"],
            )
        )

    lines += [
        "",
        "### PCA Explained Variance",
        "",
        "| Version | PC | Explained variance ratio |",
        "|---|---|---:|",
    ]
    for row in pca_explained:
        lines.append(f"| {row['version']} | {row['pc']} | {row['explained_variance_ratio']:.6f} |")

    lines += [
        "",
        "### PCA Loadings",
        "",
        "| Version | Feature | PC1 loading | PC2 loading |",
        "|---|---|---:|---:|",
    ]
    for row in pca_loadings:
        lines.append(f"| {row['version']} | {row['feature']} | {row['pc1_loading']:.6f} | {row['pc2_loading']:.6f} |")

    lines += [
        "",
        "## Main Versus Supplementary Behavior Metrics",
        "",
        "The main behavior-space analysis uses clarification turn-share, latency, and action-count precision metrics. `clarification_turn_count`, `clarification_token_cost`, `action_initiation_rate`, `correction_reactivity`, and `correction_accuracy_gain` are reported separately in `supplementary_behavior_by_identity.csv` because they answer different diagnostic questions: clarification amount and cost, whether the agent ever acted, and how it responded after oracle feedback.",
        "",
        "",
        "## Drift Definition",
        "",
        "For each identity and run, the behavior vector is the mean of the eight task-level metrics above: `[clarification_turn_share, action_initiation_rate, first_action_latency, action_count_ratio, over_action_rate, under_action_rate, correction_reactivity, correction_accuracy_gain]`. Run-to-run identity drift is measured as cosine distance between the run-1 and run-5 behavior vectors. A value near `0` means the identity's overall behavioral profile preserves its direction over memory accumulation.",
        "",
        "## Run 1 To Run 5 Drift",
        "",
        "| Identity | Cosine distance raw | Cosine distance z-scaled |",
        "|---|---:|---:|",
    ]
    for row in drift:
        lines.append(f"| {row['identity']} | {row['cosine_distance_raw']:.6f} | {row['cosine_distance_z']:.6f} |")

    lines += [
        "",
        "## Within-Identity Drift Versus Between-Identity Distance",
        "",
        "This compares each identity's run-1->run-5 drift against the separation between different identities within the same runs. If within-identity drift is smaller than between-identity distance, identity-specific behavioral profiles remain more stable over memory accumulation than they are similar to other identities.",
        "",
        "| Identity | Within drift | Between mean | Between min | Within / between mean | Within < between min |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in within_between:
        lines.append(
            "| {identity} | {within:.6f} | {bmean:.6f} | {bmin:.6f} | {ratio:.3f} | {ltmin} |".format(
                identity=row["identity"],
                within=row["within_run1_to_run5_drift"],
                bmean=row["between_identity_mean_all_runs"],
                bmin=row["between_identity_min_all_runs"],
                ratio=row["within_to_between_mean_ratio"],
                ltmin=row["within_less_than_between_min"],
            )
        )

    lines += [
        "",
        "### Between-Identity Distances By Run",
        "",
        "| Run | Pair | Cosine distance raw |",
        "|---:|---|---:|",
    ]
    for row in between:
        lines.append(f"| {row['run']} | {row['pair']} | {row['cosine_distance_raw']:.6f} |")

    lines += [
        "",
        "## Kruskal-Wallis By Metric",
        "",
        "| Metric | H | p |",
        "|---|---:|---:|",
    ]
    for row in kruskal_global:
        lines.append(f"| {row['metric']} | {row['h_statistic']:.6g} | {row['p_value']:.6g} |")

    lines += [
        "",
        "## Dimension x Identity Means",
        "",
        "| Dimension | Identity | n | clarification turn share | action initiation | over-action | under-action | latency | correction reactivity | correction accuracy gain |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in by_dim_identity:
        lines.append(
                "| {dim} | {identity} | {n} | {clar:.3f} | {init:.3f} | {over:.3f} | {under:.3f} | {lat:.3f} | {react:.3f} | {gain:.3f} |".format(
                dim=row["ambiguity_dimension"],
                identity=row["identity"],
                n=row["n"],
                clar=row["clarification_turn_share_mean"],
                init=row["action_initiation_rate_mean"],
                over=row["over_action_rate_mean"],
                under=row["under_action_rate_mean"],
                lat=row["first_action_latency_mean"],
                react=row["correction_reactivity_mean"],
                gain=row["correction_accuracy_gain_mean"],
            )
        )

    sig_dim = [row for row in kruskal_dim if finite(row.get("p_value")) and row["p_value"] < 0.05]
    lines += [
        "",
        "## Dimension-Level Significant Kruskal Results (p < .05)",
        "",
        "| Dimension | Metric | H | p |",
        "|---|---|---:|---:|",
    ]
    for row in sig_dim:
        lines.append(f"| {row['ambiguity_dimension']} | {row['metric']} | {row['h_statistic']:.6g} | {row['p_value']:.6g} |")

    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rep_dir", type=Path)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    out_dir = args.out_dir or (args.rep_dir / "behavior_vector_analysis")
    records = load_records(args.rep_dir)
    rows = [record_to_behavior(record) for record in records]
    dim_rows = exploded_dimension_rows(rows)

    by_identity = aggregate(rows, ["identity"])
    by_run_identity = aggregate(rows, ["run", "identity"])
    by_dimension_identity = aggregate(dim_rows, ["ambiguity_dimension", "identity"])
    by_dimension_run_identity = aggregate(dim_rows, ["ambiguity_dimension", "run", "identity"])
    main_behavior_by_identity = select_columns(by_identity, ["identity"], MAIN_BEHAVIOR_COLUMNS)
    main_behavior_by_run_identity = select_columns(by_run_identity, ["run", "identity"], MAIN_BEHAVIOR_COLUMNS)
    supplementary_behavior_by_identity = select_columns(by_identity, ["identity"], SUPPLEMENTARY_BEHAVIOR_COLUMNS)
    supplementary_behavior_by_run_identity = select_columns(by_run_identity, ["run", "identity"], SUPPLEMENTARY_BEHAVIOR_COLUMNS)
    kruskal_global = kruskal_tests(rows)
    pairwise_global = pairwise_tests(rows)
    kruskal_dim, pairwise_dim = tests_by_dimension(dim_rows)
    drift = drift_scores(by_run_identity)
    between = between_identity_distances(by_run_identity)
    within_between = within_vs_between_summary(drift, between)

    pca_projected_all: list[dict[str, Any]] = []
    pca_loadings: list[dict[str, Any]] = []
    pca_explained: list[dict[str, Any]] = []
    pca_separation: list[dict[str, Any]] = []
    pca_by_version: dict[str, list[dict[str, Any]]] = {}
    for version, features in PCA_VERSIONS.items():
        projected, loadings, explained, separation = behavior_space_projection(rows, version, features)
        pca_by_version[version] = projected
        pca_projected_all.extend(projected)
        pca_loadings.extend(loadings)
        pca_explained.extend(explained)
        pca_separation.extend(separation)

    sheets = {
        "per_task": rows,
        "main_behavior_by_identity": main_behavior_by_identity,
        "main_behavior_by_run_identity": main_behavior_by_run_identity,
        "supplementary_behavior_by_identity": supplementary_behavior_by_identity,
        "supplementary_behavior_by_run_identity": supplementary_behavior_by_run_identity,
        "by_identity": by_identity,
        "by_run_identity": by_run_identity,
        "by_dimension_identity": by_dimension_identity,
        "by_dim_run_identity": by_dimension_run_identity,
        "kruskal_global": kruskal_global,
        "pairwise_global": pairwise_global,
        "kruskal_by_dimension": kruskal_dim,
        "pairwise_by_dimension": pairwise_dim,
        "drift": drift,
        "between_identity_distance": between,
        "within_vs_between": within_between,
        "pca_projection": pca_projected_all,
        "pca_separation": pca_separation,
        "pca_explained_variance": pca_explained,
        "pca_loadings": pca_loadings,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, sheet_rows in sheets.items():
        write_csv(out_dir / f"{name}.csv", sheet_rows)
    for version, projected in pca_by_version.items():
        write_csv(out_dir / f"behavior_space_pca_{version}.csv", projected)
        version_separation = [row for row in pca_separation if row["version"] == version]
        version_explained = [row for row in pca_explained if row["version"] == version]
        plot_behavior_space(out_dir / f"behavior_space_pca_{version}.png", projected, version, version_separation, version_explained)
    write_xlsx(out_dir / "behavior_vector_analysis.xlsx", sheets)
    write_summary(
        out_dir / "behavior_vector_summary.md",
        rows,
        drift,
        between,
        within_between,
        by_dimension_identity,
        kruskal_global,
        kruskal_dim,
        pca_separation,
        pca_explained,
        pca_loadings,
    )

    print(f"records={len(rows)}")
    print(f"out_dir={out_dir}")
    for row in pca_separation:
        print(
            f"pca {row['version']}: n={row['n_projected']}, excluded={row['n_excluded']}, "
            f"separation_ratio={row['separation_ratio_mean']:.6f}"
        )
    for row in drift:
        print(f"drift {row['identity']}: raw={row['cosine_distance_raw']:.6f}, z={row['cosine_distance_z']:.6f}")
    for row in within_between:
        print(
            f"within-vs-between {row['identity']}: "
            f"within={row['within_run1_to_run5_drift']:.6f}, "
            f"between_mean={row['between_identity_mean_all_runs']:.6f}, "
            f"ratio={row['within_to_between_mean_ratio']:.3f}"
        )


if __name__ == "__main__":
    main()

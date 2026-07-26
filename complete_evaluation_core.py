

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import shutil
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


# --------------------------------------------------------------------------------------
# Generic IO / numeric helpers
# --------------------------------------------------------------------------------------


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL in {path} at line {line_no}: {exc}") from exc
            if isinstance(row, dict):
                rows.append(row)
    return rows


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str))
            handle.write("\n")


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def mean(values: Sequence[float]) -> float | None:
    return (sum(values) / len(values)) if values else None


def sample_std(values: Sequence[float]) -> float | None:
    return statistics.stdev(values) if len(values) >= 2 else (0.0 if len(values) == 1 else None)


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lo = math.floor(position)
    hi = math.ceil(position)
    if lo == hi:
        return ordered[lo]
    weight = position - lo
    return ordered[lo] * (1 - weight) + ordered[hi] * weight


def ratio(num: float, den: float) -> float | None:
    return (num / den) if den else None


def binary_label(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)) and value in (0, 1):
        return int(value)
    text = str(value or "").strip().lower()
    positives = {"1", "true", "yes", "correct", "supported", "keep", "accept", "accepted", "positive"}
    negatives = {"0", "false", "no", "incorrect", "unsupported", "contradicted", "reject", "rejected", "negative"}
    if text in positives:
        return 1
    if text in negatives:
        return 0
    return None


def metric(value: Any, *, count: int = 0, reason: str | None = None, **extra: Any) -> dict[str, Any]:
    out = {"value": value, "count": count, "available": value is not None}
    if reason:
        out["missing_reason"] = reason
    out.update(extra)
    return out


def normalize_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(item) for item in items if item not in (None, "")))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def hash_existing(paths: Iterable[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in paths:
        if path.exists() and path.is_file():
            try:
                result[str(path)] = sha256_file(path)
            except OSError:
                continue
    return result


def directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return total
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def run_command(command: list[str], cwd: Path | None = None) -> str | None:
    try:
        completed = subprocess.run(
            command, cwd=cwd, check=False, capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


# --------------------------------------------------------------------------------------
# Artifact discovery and standardized logs
# --------------------------------------------------------------------------------------


def discover_package_dirs(split_dir: Path) -> list[Path]:
    packages = split_dir / "packages"
    if not packages.exists():
        return []
    return sorted(path for path in packages.iterdir() if path.is_dir() and (path / "manifest.json").exists())


def build_item_type_map(package_dir: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in read_jsonl(package_dir / "evidence" / "evidence_units.jsonl"):
        mapping[str(row.get("evidence_id", ""))] = str(row.get("modality", "evidence_unit"))
    for row in read_jsonl(package_dir / "wiki" / "narrative_sections.jsonl"):
        mapping[str(row.get("section_id", ""))] = "narrative_section"
    for row in read_jsonl(package_dir / "wiki" / "kg_items.jsonl"):
        mapping[str(row.get("item_id", ""))] = str(row.get("item_type", "kg_item"))
    for row in read_jsonl(package_dir / "validation" / "media_links.jsonl"):
        mapping[str(row.get("media_id", ""))] = str(row.get("media_type", "media"))
    return mapping


def standardize_evidence_units(package_dirs: Sequence[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for package_dir in package_dirs:
        for row in read_jsonl(package_dir / "evidence" / "evidence_units.jsonl"):
            provenance = dict(row.get("provenance") or {})
            rows.append({
                "video_id": row.get("video_id") or package_dir.name,
                "unit_id": row.get("evidence_id"),
                "modality": row.get("modality"),
                "text_or_media_id": row.get("text") or (row.get("media_paths") or [None])[0],
                "timestamps": {"start": row.get("start"), "end": row.get("end")},
                "extraction_score": row.get("confidence"),
                "extractor": provenance.get("extractor") or provenance.get("source") or "unknown",
                "provenance": provenance,
                "stable_source": str(package_dir / "evidence" / "evidence_units.jsonl"),
            })
    return rows


def validation_map(package_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("item_id")): row
        for row in read_jsonl(package_dir / "validation" / "claim_support.jsonl")
        if row.get("item_id") not in (None, "")
    }


def standardize_wiki_items(package_dirs: Sequence[Path]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for package_dir in package_dirs:
        validations = validation_map(package_dir)
        for row in read_jsonl(package_dir / "wiki" / "narrative_sections.jsonl"):
            item_id = str(row.get("section_id"))
            val = validations.get(item_id, {})
            out.append({
                "item_id": item_id,
                "item_type": "narrative_section",
                "content": {"heading": row.get("heading"), "text": row.get("content"), "claims": row.get("claims", [])},
                "canonical_ids": normalize_ids((row.get("provenance") or {}).get("canonical_ids")),
                "timestamps": {"start": row.get("start"), "end": row.get("end")},
                "source_ids": normalize_ids(row.get("evidence_ids")),
                "q_sup": val.get("support"),
                "q_prov": val.get("provenance"),
                "q_cons": val.get("consistency"),
                "q_align": val.get("coverage"),
                "required_checks": val.get("support_signals", {}),
                "aggregate_score": val.get("score"),
                "revision_count": safe_int((row.get("provenance") or {}).get("revision_count")) or 0,
                "status": val.get("decision") or "unvalidated",
                "video_id": row.get("video_id") or package_dir.name,
            })
        for row in read_jsonl(package_dir / "wiki" / "kg_items.jsonl"):
            item_id = str(row.get("item_id"))
            val = validations.get(item_id, {})
            out.append({
                "item_id": item_id,
                "item_type": row.get("item_type") or "kg_item",
                "content": {"label": row.get("label"), "description": row.get("description"), "triples": row.get("triples", [])},
                "canonical_ids": normalize_ids((row.get("provenance") or {}).get("canonical_ids")),
                "timestamps": {"start": row.get("start"), "end": row.get("end")},
                "source_ids": normalize_ids(row.get("evidence_ids")),
                "q_sup": val.get("support"),
                "q_prov": val.get("provenance"),
                "q_cons": val.get("consistency"),
                "q_align": val.get("coverage"),
                "required_checks": val.get("support_signals", {}),
                "aggregate_score": val.get("score"),
                "revision_count": safe_int((row.get("provenance") or {}).get("revision_count")) or 0,
                "status": val.get("decision") or "unvalidated",
                "video_id": row.get("video_id") or package_dir.name,
            })
    return out


def standardize_links(package_dirs: Sequence[Path]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for package_dir in package_dirs:
        type_map = build_item_type_map(package_dir)
        validations = validation_map(package_dir)
        for row in read_jsonl(package_dir / "validation" / "cross_modal_links.jsonl"):
            link_id = str(row.get("link_id"))
            val = validations.get(link_id, {})
            out.append({
                "link_id": link_id,
                "source_id": row.get("source_id"),
                "source_type": type_map.get(str(row.get("source_id")), "unknown"),
                "target_id": row.get("target_id"),
                "target_type": type_map.get(str(row.get("target_id")), "unknown"),
                "link_type": row.get("link_type"),
                "temporal_range": {"start": row.get("start"), "end": row.get("end")},
                "construction_score": row.get("confidence"),
                "provenance": row.get("provenance", {}),
                "validation_scores": {
                    "q_sup": val.get("support"),
                    "q_prov": val.get("provenance"),
                    "q_cons": val.get("consistency"),
                    "q_align": val.get("coverage"),
                },
                "required_checks": val.get("support_signals", {}),
                "status": val.get("decision") or "unvalidated",
                "video_id": row.get("video_id") or package_dir.name,
            })
    return out


def packet_ranked_ids(packet: Mapping[str, Any]) -> tuple[list[str], dict[str, list[str]]]:
    groups = {
        "sections": [str(x.get("section_id")) for x in packet.get("narrative_sections", []) if x.get("section_id")],
        "triples": [],
        "kg_items": [str(x.get("item_id")) for x in packet.get("kg_items", []) if x.get("item_id")],
        "subtitles": [str(x.get("evidence_id")) for x in packet.get("subtitle_spans", []) if x.get("evidence_id")],
        "media": [str(x.get("media_id")) for x in packet.get("media_items", []) if x.get("media_id")],
        "links": [str(x.get("link_id")) for x in packet.get("cross_modal_links", []) if x.get("link_id")],
        "knowledge": [str(x.get("id") or x.get("source")) for x in packet.get("knowledge", []) if x.get("id") or x.get("source")],
    }
    for item in packet.get("kg_items", []):
        item_id = str(item.get("item_id", "kg"))
        for index, triple in enumerate(item.get("triples", []) or []):
            groups["triples"].append(str(triple.get("triple_id") or f"{item_id}:t{index}"))
    final = unique(
        groups["sections"] + groups["triples"] + groups["kg_items"] + groups["subtitles"]
        + groups["media"] + groups["links"] + groups["knowledge"]
    )
    return final, groups


def cited_ids_from_trace(trace: Any) -> list[str]:
    if not isinstance(trace, list):
        return []
    cited: list[str] = []
    for entry in trace:
        if not isinstance(entry, dict) or "verification" in entry:
            continue
        for key in ("section_ids", "kg_item_ids", "triple_ids", "subtitle_ids", "link_ids", "provenance"):
            cited.extend(normalize_ids(entry.get(key)))
    return unique(cited)


def verification_from_trace(trace: Any) -> dict[str, Any]:
    if not isinstance(trace, list):
        return {}
    for entry in reversed(trace):
        if isinstance(entry, dict) and isinstance(entry.get("verification"), dict):
            return dict(entry["verification"])
    return {}


def standardize_retrieval(split_dir: Path, budgets: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, list[str]]]]:
    packets = read_jsonl(split_dir / "qa" / "evidence_packets.jsonl")
    out: list[dict[str, Any]] = []
    groups_by_qid: dict[str, dict[str, list[str]]] = {}
    for packet in packets:
        final_order, groups = packet_ranked_ids(packet)
        qid = str(packet.get("question_id"))
        groups_by_qid[qid] = groups
        links = packet.get("cross_modal_links", []) or []
        out.append({
            "question_id": qid,
            "router_evidence_vector": None,
            "raw_text_required": bool(packet.get("subtitle_spans")),
            "reserved_text_budget": budgets.get("subtitle") or budgets.get("Bsub"),
            "ranked_evidence_ids": groups,
            "score_components": None,
            "link_expansion_path": [
                {"link_id": x.get("link_id"), "source_id": x.get("source_id"), "target_id": x.get("target_id")}
                for x in links
            ],
            "deduplication_decisions": [],
            "final_ranking_order": final_order,
            "video_id": packet.get("video_id"),
            "schema_limitations": [
                "router_evidence_vector and score_components were not persisted by v1.0.1",
                "final order is reconstructed from the stored packet order",
            ],
        })
    return out, groups_by_qid


def correctness_map(split_dir: Path) -> dict[str, bool | None]:
    return {
        str(row.get("question_id")): (bool(row.get("correct")) if row.get("correct") is not None else None)
        for row in read_jsonl(split_dir / "eval" / "per_question.jsonl")
    }


def standardize_predictions(split_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    predictions = read_jsonl(split_dir / "qa" / "predictions.jsonl")
    correct = correctness_map(split_dir)
    qa_rows: list[dict[str, Any]] = []
    verification_rows: list[dict[str, Any]] = []
    for row in predictions:
        qid = str(row.get("question_id"))
        trace = row.get("evidence_trace", [])
        verification = verification_from_trace(trace)
        cited = cited_ids_from_trace(trace)
        qa_rows.append({
            "question_id": qid,
            "option_token_log_likelihoods": row.get("option_token_log_likelihoods"),
            "calibrated_probabilities": row.get("calibrated_probabilities"),
            "draft_answer": row.get("draft_answer"),
            "final_answer": row.get("answer"),
            "confidence_score": row.get("confidence"),
            "cited_evidence_ids": cited,
            "correctness": correct.get(qid),
            "predicted_index": row.get("predicted_index"),
            "scoring_method": row.get("scoring_method"),
            "video_id": row.get("video_id"),
            "schema_limitations": [
                "v1.0.1 did not persist draft_answer, per-option log-likelihoods, or calibrated probability vector"
            ],
        })
        claim_labels = [
            entry.get("label") for entry in trace
            if isinstance(entry, dict) and "claim" in entry and entry.get("label") not in (None, "")
        ]
        verification_rows.append({
            "question_id": qid,
            "risk_features": verification.get("risk_features"),
            "packet_quality": verification.get("evidence_quality"),
            "conflicts": verification.get("conflicts"),
            "risk_score": verification.get("risk"),
            "risk_threshold": verification.get("risk_threshold", 0.5),
            "trigger_decision": verification.get("triggered"),
            "claim_labels": claim_labels,
            "revisions": verification.get("revisions") or verification.get("revised_answer"),
            "vlm_calls": verification.get("vlm_calls"),
            "latency": verification.get("latency"),
            "applied": verification.get("applied"),
            "video_id": row.get("video_id"),
        })
    return qa_rows, verification_rows


def collect_patch_rows(split_dir: Path, package_dirs: Sequence[Path], refinement_eval: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    patches: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(split_dir / "qa" / "refinement.jsonl"):
        partition = row.get("partition")
        trigger_qid = row.get("question_id")
        video_id = row.get("video_id")
        for patch in row.get("patches", []) or []:
            if not isinstance(patch, dict):
                continue
            patch_id = str(patch.get("patch_id"))
            validation = patch.get("validation") or {}
            patches[patch_id] = {
                "partition": partition,
                "trigger_question_id": trigger_qid,
                "video_id": video_id or patch.get("video_id"),
                "confirmed_source_ids": patch.get("evidence_ids", []),
                "proposed_patch": {
                    "patch_id": patch_id,
                    "op": patch.get("op"),
                    "target_type": patch.get("target_type"),
                    "target_id": patch.get("target_id"),
                    "content": patch.get("content"),
                    "rationale": patch.get("rationale"),
                },
                "validation_scores": validation,
                "validation_checks": validation.get("support_signals", {}),
                "decision": "accepted" if patch.get("accepted") else "rejected",
                "frozen_package_version": patch.get("frozen_package_version"),
                "QB_evaluation_outcomes": [],
            }
    for package_dir in package_dirs:
        for rel in ("validation/refinement_log.jsonl", "validation/applied_patches.jsonl"):
            for patch in read_jsonl(package_dir / rel):
                patch_id = str(patch.get("patch_id"))
                if patch_id in patches:
                    continue
                validation = patch.get("validation") or {}
                patches[patch_id] = {
                    "partition": patch.get("partition"),
                    "trigger_question_id": patch.get("trigger_question_id"),
                    "video_id": patch.get("video_id") or package_dir.name,
                    "confirmed_source_ids": patch.get("evidence_ids", []),
                    "proposed_patch": {key: patch.get(key) for key in ("patch_id", "op", "target_type", "target_id", "content", "rationale")},
                    "validation_scores": validation,
                    "validation_checks": validation.get("support_signals", {}),
                    "decision": "accepted" if patch.get("accepted") else "rejected",
                    "frozen_package_version": patch.get("frozen_package_version"),
                    "QB_evaluation_outcomes": [],
                }
    by_partition: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in refinement_eval:
        if str(row.get("set", "")).upper() == "QB":
            by_partition[row.get("partition")].append(dict(row))
    for patch in patches.values():
        patch["QB_evaluation_outcomes"] = by_partition.get(patch.get("partition"), [])
    return list(patches.values())


def standardize_annotations(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    standardized: list[dict[str, Any]] = []
    for row in rows:
        labels = row.get("annotator_labels", {})
        if isinstance(labels, list):
            labels = {f"reviewer_{idx + 1}": value for idx, value in enumerate(labels)}
        standardized.append({
            "audit_type": row.get("audit_type"),
            "item_id_or_question_id": row.get("item_id") or row.get("question_id") or row.get("patch_id"),
            "evidence_shown": row.get("evidence_shown") or row.get("gold_evidence_ids"),
            "annotator_labels": labels,
            "adjudicated_label": row.get("adjudicated_label"),
            "reviewer_ids": row.get("reviewer_ids") or list(labels.keys()) if isinstance(labels, dict) else [],
            "sampling_stratum": row.get("sampling_stratum"),
            **dict(row),
        })
    return standardized


# --------------------------------------------------------------------------------------
# Metric primitives
# --------------------------------------------------------------------------------------


def recall_at_k(retrieved: Sequence[str], gold: Sequence[str], k: int) -> float | None:
    gold_set = set(gold)
    if not gold_set:
        return None
    return len(set(retrieved[:k]) & gold_set) / len(gold_set)


def reciprocal_rank(retrieved: Sequence[str], gold: Sequence[str]) -> float | None:
    gold_set = set(gold)
    if not gold_set:
        return None
    for rank, item in enumerate(retrieved, 1):
        if item in gold_set:
            return 1.0 / rank
    return 0.0


def interval_iou(a: Sequence[Any], b: Sequence[Any]) -> float:
    if len(a) != 2 or len(b) != 2:
        return 0.0
    a0, a1, b0, b1 = map(safe_float, (a[0], a[1], b[0], b[1]))
    if None in (a0, a1, b0, b1):
        return 0.0
    if a1 < a0 or b1 < b0:
        return 0.0
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    return inter / union if union > 0 else 0.0


def best_temporal_iou(predicted: Sequence[Sequence[Any]], gold: Sequence[Sequence[Any]]) -> float | None:
    if not gold:
        return None
    if not predicted:
        return 0.0
    return max(interval_iou(p, g) for p in predicted for g in gold)


def precision_recall_f1(predicted: Sequence[str], gold: Sequence[str]) -> tuple[float | None, float | None, float | None]:
    pred, target = set(predicted), set(gold)
    if not pred and not target:
        return (1.0, 1.0, 1.0)
    if not target:
        return (None, None, None)
    precision = len(pred & target) / len(pred) if pred else 0.0
    recall = len(pred & target) / len(target)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def auroc(labels: Sequence[int], scores: Sequence[float]) -> float | None:
    positives = sum(labels)
    negatives = len(labels) - positives
    if not labels or positives == 0 or negatives == 0:
        return None
    ordered = sorted(zip(scores, labels), key=lambda pair: pair[0])
    rank_sum = 0.0
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][0] == ordered[index][0]:
            end += 1
        avg_rank = ((index + 1) + end) / 2
        rank_sum += avg_rank * sum(label for _, label in ordered[index:end])
        index = end
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def auprc(labels: Sequence[int], scores: Sequence[float]) -> float | None:
    positives = sum(labels)
    if not labels or positives == 0:
        return None
    ordered = sorted(zip(scores, labels), key=lambda pair: pair[0], reverse=True)
    tp = fp = 0
    previous_recall = 0.0
    area = 0.0
    index = 0
    while index < len(ordered):
        score = ordered[index][0]
        while index < len(ordered) and ordered[index][0] == score:
            if ordered[index][1] == 1:
                tp += 1
            else:
                fp += 1
            index += 1
        recall = tp / positives
        precision = tp / (tp + fp)
        area += (recall - previous_recall) * precision
        previous_recall = recall
    return area


def expected_calibration_error(labels: Sequence[int], probabilities: Sequence[float], bins: int = 10) -> float | None:
    if not labels:
        return None
    total = len(labels)
    error = 0.0
    for bin_index in range(bins):
        lo = bin_index / bins
        hi = (bin_index + 1) / bins
        positions = [
            idx for idx, prob in enumerate(probabilities)
            if (lo <= prob < hi) or (bin_index == bins - 1 and prob == 1.0)
        ]
        if not positions:
            continue
        confidence = mean([probabilities[idx] for idx in positions]) or 0.0
        accuracy = mean([float(labels[idx]) for idx in positions]) or 0.0
        error += len(positions) / total * abs(confidence - accuracy)
    return error


def brier_score(labels: Sequence[int], probabilities: Sequence[float]) -> float | None:
    if not labels:
        return None
    return mean([(prob - label) ** 2 for label, prob in zip(labels, probabilities)])


def confusion_rates(labels: Sequence[int], decisions: Sequence[int]) -> dict[str, float | int | None]:
    tp = sum(1 for y, d in zip(labels, decisions) if y == 1 and d == 1)
    tn = sum(1 for y, d in zip(labels, decisions) if y == 0 and d == 0)
    fp = sum(1 for y, d in zip(labels, decisions) if y == 0 and d == 1)
    fn = sum(1 for y, d in zip(labels, decisions) if y == 1 and d == 0)
    return {
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "sensitivity": ratio(tp, tp + fn),
        "specificity": ratio(tn, tn + fp),
    }


def risk_coverage_curve(correctness: Sequence[int], risks: Sequence[float]) -> list[dict[str, float | int]]:
    if not correctness:
        return []
    order = sorted(range(len(risks)), key=lambda idx: risks[idx])
    points: list[dict[str, float | int]] = []
    for target in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        keep = max(1, math.ceil(len(order) * target))
        selected = order[:keep]
        selective_risk = 1.0 - (mean([float(correctness[idx]) for idx in selected]) or 0.0)
        points.append({
            "coverage": keep / len(order),
            "risk": selective_risk,
            "count": keep,
            "max_gate_risk": max(risks[idx] for idx in selected),
        })
    return points


def fleiss_kappa(annotation_rows: Sequence[Mapping[str, Any]]) -> tuple[float | None, float | None, int]:
    matrices: list[Counter[str]] = []
    all_categories: set[str] = set()
    raw_agreements: list[float] = []
    for row in annotation_rows:
        labels = row.get("annotator_labels") or {}
        if isinstance(labels, list):
            values = [str(v) for v in labels if v not in (None, "")]
        elif isinstance(labels, dict):
            values = [str(v) for v in labels.values() if v not in (None, "")]
        else:
            values = []
        if len(values) < 2:
            continue
        counts = Counter(values)
        matrices.append(counts)
        all_categories.update(counts)
        pairs = len(values) * (len(values) - 1)
        agree_pairs = sum(count * (count - 1) for count in counts.values())
        raw_agreements.append(agree_pairs / pairs)
    if not matrices:
        return None, None, 0
    agreement = mean(raw_agreements)
    total_ratings = sum(sum(row.values()) for row in matrices)
    category_props = {
        category: sum(row.get(category, 0) for row in matrices) / total_ratings
        for category in all_categories
    }
    expected = sum(prop ** 2 for prop in category_props.values())
    kappa = (agreement - expected) / (1 - expected) if agreement is not None and expected < 1 else None
    return agreement, kappa, len(matrices)


# --------------------------------------------------------------------------------------
# Metric families
# --------------------------------------------------------------------------------------


def compute_retrieval_metrics(
    annotations: Sequence[Mapping[str, Any]],
    retrieval_rows: Sequence[Mapping[str, Any]],
    groups_by_qid: Mapping[str, Mapping[str, list[str]]],
    qa_predictions: Sequence[Mapping[str, Any]],
    packets: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    audit = {str(row.get("question_id")): row for row in annotations if row.get("audit_type") in {"qa", "retrieval"} and row.get("question_id")}
    retrieval_by_qid = {str(row.get("question_id")): row for row in retrieval_rows}
    pred_by_qid = {str(row.get("question_id")): row for row in qa_predictions}
    packet_by_qid = {str(row.get("question_id")): row for row in packets}
    accum: dict[str, list[float]] = defaultdict(list)
    per_question: list[dict[str, Any]] = []
    for qid, gold in audit.items():
        groups = groups_by_qid.get(qid, {})
        retrieval = retrieval_by_qid.get(qid, {})
        gold_sections = normalize_ids(gold.get("gold_section_ids"))
        gold_triples = normalize_ids(gold.get("gold_triple_ids"))
        gold_links = normalize_ids(gold.get("gold_link_ids"))
        gold_evidence = normalize_ids(gold.get("gold_evidence_ids"))
        gold_subtitles = normalize_ids(gold.get("gold_subtitle_ids")) or gold_evidence
        values = {
            "section_recall_at_5": recall_at_k(groups.get("sections", []), gold_sections, 5),
            "triple_recall_at_8": recall_at_k(groups.get("triples", []), gold_triples, 8),
            "link_recall_at_10": recall_at_k(groups.get("links", []), gold_links, 10),
            "evidence_mrr": reciprocal_rank(retrieval.get("final_ranking_order", []), gold_evidence),
            "tvqa_subtitle_recall_at_1": recall_at_k(groups.get("subtitles", []), gold_subtitles, 1),
        }
        packet = packet_by_qid.get(qid, {})
        predicted_intervals = []
        for key in ("subtitle_spans", "narrative_sections", "kg_items", "cross_modal_links"):
            for item in packet.get(key, []) or []:
                if item.get("start") is not None and item.get("end") is not None:
                    predicted_intervals.append([item.get("start"), item.get("end")])
        tiou = best_temporal_iou(predicted_intervals, gold.get("gold_intervals", []) or [])
        values["best_tiou"] = tiou
        values["tiou_at_0_3"] = None if tiou is None else float(tiou >= 0.3)
        values["tiou_at_0_5"] = None if tiou is None else float(tiou >= 0.5)
        prediction = pred_by_qid.get(qid, {})
        answer_correct = prediction.get("correctness")
        evidence_correct = gold.get("evidence_correct")
        if evidence_correct is None:
            overlap = set(retrieval.get("final_ranking_order", [])) & set(gold_evidence)
            evidence_correct = bool(overlap) if gold_evidence else None
        values["next_answer_evidence_joint_accuracy"] = (
            float(bool(answer_correct) and bool(evidence_correct))
            if answer_correct is not None and evidence_correct is not None else None
        )
        for name, value in values.items():
            if value is not None:
                accum[name].append(float(value))
        per_question.append({"question_id": qid, **values})

    requirements = {
        dataset: sum(1 for row in audit.values() if str(row.get("dataset", "")).lower() == dataset)
        for dataset in ("tvqa", "knowit", "nextqa")
    }
    result: dict[str, Any] = {"audit_question_count": len(audit), "audit_counts_by_dataset": requirements}
    required_names = (
        "section_recall_at_5", "triple_recall_at_8", "link_recall_at_10", "evidence_mrr",
        "tvqa_subtitle_recall_at_1", "tiou_at_0_3", "tiou_at_0_5", "next_answer_evidence_joint_accuracy",
    )
    for name in required_names:
        values = accum.get(name, [])
        result[name] = metric(
            mean(values), count=len(values),
            reason=None if values else "Gold retrieval/evidence annotations are missing for this metric.",
        )
    result["control_checks"] = {
        "independent_adjudicated_200_per_dataset": all(requirements[d] >= 200 for d in requirements),
        "required_per_dataset": 200,
    }
    result["per_question"] = per_question
    return result


def compute_package_metrics(
    annotations: Sequence[Mapping[str, Any]], wiki_items: Sequence[Mapping[str, Any]], links: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    audits = [row for row in annotations if row.get("audit_type") in {"package", "claim", "triple", "link", "provenance"}]

    def audited_precision(kind: str, phase: str | None = None) -> dict[str, Any]:
        selected = []
        for row in audits:
            row_kind = str(row.get("item_kind") or row.get("audit_type") or "").lower()
            row_phase = str(row.get("phase") or "post").lower()
            if kind not in row_kind:
                continue
            if phase is not None and row_phase != phase:
                continue
            label = binary_label(row.get("adjudicated_label"))
            if label is not None:
                selected.append(label)
        return metric(mean([float(x) for x in selected]), count=len(selected), reason=None if selected else f"No adjudicated {phase or ''} {kind} audit labels.")

    status_counts = Counter(str(item.get("status") or "unknown") for item in wiki_items)
    status_counts.update(str(link.get("status") or "unknown") for link in links)
    revisions = sum(safe_int(item.get("revision_count")) or 0 for item in wiki_items)
    generated = len(wiki_items) + len(links)
    retained = status_counts.get("keep", 0)
    rejected = sum(count for status, count in status_counts.items() if status in {"reject", "rejected", "drop"})
    with_prov = sum(1 for item in wiki_items if item.get("source_ids") or item.get("canonical_ids"))
    agreement, kappa, agreement_n = fleiss_kappa(audits)
    return {
        "pre_claim_precision": audited_precision("claim", "pre"),
        "post_claim_precision": audited_precision("claim", "post"),
        "triple_precision": audited_precision("triple"),
        "typed_link_precision": audited_precision("link"),
        "provenance_exactness": audited_precision("provenance") if any("provenance" in str(r.get("item_kind") or r.get("audit_type")) for r in audits)
                                else metric(ratio(with_prov, len(wiki_items)), count=len(wiki_items), reason="This is provenance presence coverage, not independently audited exactness."),
        "item_counts": {
            "generated": generated,
            "revised": revisions,
            "retained": retained,
            "rejected": rejected,
            "status_counts": dict(status_counts),
        },
        "agreement_score": {
            "percent_pairwise_agreement": agreement,
            "fleiss_kappa": kappa,
            "audited_items": agreement_n,
            "available": agreement is not None,
            "missing_reason": None if agreement is not None else "At least two blind annotator labels per audited item are required.",
        },
        "control_checks": {
            "independent_blind_audit_present": bool(audits),
            "reported_audit_sample_count": len(audits),
        },
    }


def compute_faithfulness_metrics(
    annotations: Sequence[Mapping[str, Any]],
    condition_predictions: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    principal_audit = {
        str(row.get("question_id")): row
        for row in annotations
        if row.get("audit_type") in {"qa", "faithfulness"}
        and row.get("question_id")
        and str(row.get("condition") or "principal") == "principal"
    }
    explicit_by_condition: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in annotations:
        if row.get("audit_type") not in {"qa", "faithfulness"} or not row.get("question_id"):
            continue
        condition = str(row.get("condition") or "principal")
        explicit_by_condition[condition][str(row.get("question_id"))] = row

    conditions = sorted(set(condition_predictions) | set(explicit_by_condition) | {"principal", "matched_flat"})
    output: dict[str, Any] = {}
    for condition in conditions:
        predictions = {str(row.get("question_id")): row for row in condition_predictions.get(condition, [])}
        audits = explicit_by_condition.get(condition, {})
        if condition != "principal" and not audits:
            # Retrieval gold is condition-independent, so the same blind gold evidence may be reused
            # across principal and matched-flat predictions. The model outputs remain condition-specific.
            audits = principal_audit
        citation_f1s: list[float] = []
        trace_coverages: list[float] = []
        hallucinations = total_claims = 0
        evaluated_questions = 0
        for qid, prediction in predictions.items():
            audit = audits.get(qid)
            if audit is None:
                continue
            evaluated_questions += 1
            gold_ids = normalize_ids(audit.get("gold_supported_evidence_ids")) or normalize_ids(audit.get("gold_evidence_ids"))
            _, _, f1 = precision_recall_f1(cited_ids_from_trace(prediction.get("evidence_trace", [])), gold_ids)
            if f1 is not None:
                citation_f1s.append(f1)
            trace = prediction.get("evidence_trace", []) or []
            claims = [entry for entry in trace if isinstance(entry, dict) and "claim" in entry and "verification" not in entry]
            if claims:
                covered = 0
                for claim in claims:
                    ids = []
                    for key in ("section_ids", "kg_item_ids", "triple_ids", "subtitle_ids", "link_ids", "provenance"):
                        ids.extend(normalize_ids(claim.get(key)))
                    covered += int(bool(ids))
                    label = str(claim.get("label", "")).lower()
                    if label in {"unsup", "unsupported", "contr", "contradicted"}:
                        hallucinations += 1
                    total_claims += 1
                trace_coverages.append(covered / len(claims))
            elif audit.get("claim_labels"):
                labels = normalize_ids(audit.get("claim_labels"))
                total_claims += len(labels)
                hallucinations += sum(1 for label in labels if label.lower() in {"unsup", "unsupported", "contr", "contradicted"})
        has_predictions = bool(predictions)
        output[condition] = {
            "citation_f1": metric(
                mean(citation_f1s), count=len(citation_f1s),
                reason=None if citation_f1s else ("Gold supported citation IDs are missing." if has_predictions else f"No {condition} predictions found."),
            ),
            "trace_coverage": metric(
                mean(trace_coverages), count=len(trace_coverages),
                reason=None if trace_coverages else ("No claim-level traces available for this condition." if has_predictions else f"No {condition} predictions found."),
            ),
            "hallucination_rate": metric(
                ratio(hallucinations, total_claims), count=total_claims,
                reason=None if total_claims else ("No adjudicated or verifier claim labels available." if has_predictions else f"No {condition} predictions found."),
            ),
            "prediction_count": len(predictions),
            "evaluated_question_count": evaluated_questions,
        }
    output["control_checks"] = {
        "principal_present": output.get("principal", {}).get("prediction_count", 0) > 0,
        "matched_flat_present": output.get("matched_flat", {}).get("prediction_count", 0) > 0,
    }
    return output

def compute_gate_metrics(
    annotations: Sequence[Mapping[str, Any]], verification_rows: Sequence[Mapping[str, Any]], qa_predictions: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    audit = {str(row.get("question_id")): row for row in annotations if row.get("question_id") and row.get("gate_label") is not None}
    pred_correct = {str(row.get("question_id")): binary_label(row.get("correctness")) for row in qa_predictions}
    labels: list[int] = []
    risks: list[float] = []
    decisions: list[int] = []
    correctness: list[int] = []
    correctness_risks: list[float] = []
    gate_rows = []
    for row in verification_rows:
        qid = str(row.get("question_id"))
        if qid not in audit:
            continue
        label = binary_label(audit[qid].get("gate_label"))
        risk = safe_float(row.get("risk_score"))
        if label is None or risk is None:
            continue
        threshold = safe_float(row.get("risk_threshold")) or 0.5
        triggered = binary_label(row.get("trigger_decision"))
        decision = triggered if triggered is not None else int(risk > threshold)
        labels.append(label)
        risks.append(max(0.0, min(1.0, risk)))
        decisions.append(decision)
        if pred_correct.get(qid) is not None:
            correctness.append(int(pred_correct[qid]))
            correctness_risks.append(max(0.0, min(1.0, risk)))
        gate_rows.append({"question_id": qid, "label": label, "risk": risk, "threshold": threshold, "trigger": decision})
    confusion = confusion_rates(labels, decisions) if labels else {"sensitivity": None, "specificity": None}
    trigger_values = [binary_label(row.get("trigger_decision")) for row in verification_rows]
    trigger_values = [x for x in trigger_values if x is not None]
    return {
        "trigger_rate": metric(mean([float(x) for x in trigger_values]), count=len(trigger_values), reason=None if trigger_values else "Verification trigger decisions were not persisted."),
        "auroc": metric(auroc(labels, risks), count=len(labels), reason=None if auroc(labels, risks) is not None else "Held-out labels require both positive and negative classes."),
        "auprc": metric(auprc(labels, risks), count=len(labels), reason=None if auprc(labels, risks) is not None else "Held-out positive gate labels are missing."),
        "expected_calibration_error": metric(expected_calibration_error(labels, risks), count=len(labels), reason=None if labels else "Held-out gate labels/risk scores are missing."),
        "brier_score": metric(brier_score(labels, risks), count=len(labels), reason=None if labels else "Held-out gate labels/risk scores are missing."),
        "sensitivity": metric(confusion.get("sensitivity"), count=len(labels), reason=None if labels else "Held-out gate labels are missing."),
        "specificity": metric(confusion.get("specificity"), count=len(labels), reason=None if labels else "Held-out gate labels are missing."),
        "confusion_matrix": {key: value for key, value in confusion.items() if key in {"tp", "tn", "fp", "fn"}},
        "risk_coverage_curve": risk_coverage_curve(correctness, correctness_risks),
        "control_checks": {
            "held_out_gate_labels_present": bool(labels),
            "disjoint_from_gate_training": all(bool(row.get("gate_eval_disjoint", False)) for row in audit.values()) if audit else False,
        },
        "per_question": gate_rows,
    }


def parse_stress_metadata(path: Path, stress_root: Path) -> tuple[str, float | None, int | None]:
    relative = path.relative_to(stress_root)
    parts = relative.parts
    setting = parts[0] if parts else "unknown"
    severity = safe_float(parts[1]) if len(parts) >= 2 else None
    seed = None
    for part in parts:
        lowered = part.lower()
        if lowered.startswith("seed"):
            digits = "".join(ch for ch in part if ch.isdigit() or ch == "-")
            seed = safe_int(digits)
    return setting, severity, seed


def discover_robustness_runs(split_dir: Path, extra_file: Path | None) -> list[dict[str, Any]]:
    runs = read_jsonl(extra_file) if extra_file else []
    stress_root = split_dir / "stress"
    if stress_root.exists():
        for metrics_path in stress_root.rglob("metrics.json"):
            setting, severity, seed = parse_stress_metadata(metrics_path.parent, stress_root)
            data = read_json(metrics_path, {}) or {}
            predictions = read_jsonl(metrics_path.parent / "predictions.jsonl")
            h_rate, trace_coverage = faithfulness_from_raw_predictions(predictions)
            runs.append({
                "corruption": setting,
                "severity": severity,
                "seed": seed,
                "accuracy": data.get("accuracy"),
                "citation_f1": data.get("citation_f1"),
                "trace_coverage": data.get("trace_coverage", trace_coverage),
                "hallucination_rate": data.get("hallucination_rate", h_rate),
                "source": str(metrics_path.parent),
            })
    return runs


def faithfulness_from_raw_predictions(predictions: Sequence[Mapping[str, Any]]) -> tuple[float | None, float | None]:
    total_claims = hallucinated = covered = 0
    for prediction in predictions:
        for entry in prediction.get("evidence_trace", []) or []:
            if not isinstance(entry, dict) or "claim" not in entry or "verification" in entry:
                continue
            total_claims += 1
            evidence = []
            for key in ("section_ids", "kg_item_ids", "triple_ids", "subtitle_ids", "link_ids", "provenance"):
                evidence.extend(normalize_ids(entry.get(key)))
            covered += int(bool(evidence))
            if str(entry.get("label", "")).lower() in {"unsup", "unsupported", "contr", "contradicted"}:
                hallucinated += 1
    return ratio(hallucinated, total_claims), ratio(covered, total_claims)


def compute_robustness_metrics(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    normalized = []
    name_map = {
        "subtitle_distractors": "text_corruption",
        "text": "text_corruption",
        "kg_distractors": "kg_corruption",
        "kg": "kg_corruption",
        "link": "link_corruption",
        "link_corruption": "link_corruption",
        "provenance": "provenance_corruption",
        "provenance_corruption": "provenance_corruption",
    }
    for row in runs:
        corruption = name_map.get(str(row.get("corruption") or row.get("setting") or "").lower(), str(row.get("corruption") or row.get("setting") or "unknown"))
        severity_value = row.get("severity") if row.get("severity") is not None else row.get("level")
        normalized.append({**dict(row), "corruption": corruption, "severity": safe_float(severity_value), "seed": safe_int(row.get("seed"))})
    grouped: dict[tuple[str, float | None], list[dict[str, Any]]] = defaultdict(list)
    for row in normalized:
        grouped[(row["corruption"], row["severity"])].append(row)
    aggregate: list[dict[str, Any]] = []
    required_metrics = ("accuracy", "citation_f1", "trace_coverage", "hallucination_rate")
    for (corruption, severity), group in sorted(grouped.items(), key=lambda x: (x[0][0], x[0][1] if x[0][1] is not None else -1)):
        cell = {"corruption": corruption, "severity": severity, "run_count": len(group), "seeds": sorted({r["seed"] for r in group if r["seed"] is not None})}
        for name in required_metrics:
            values = [safe_float(r.get(name)) for r in group]
            values = [x for x in values if x is not None]
            cell[name] = {"mean": mean(values), "std": sample_std(values), "count": len(values)}
        aggregate.append(cell)
    required_corruptions = {"text_corruption", "kg_corruption", "link_corruption", "provenance_corruption"}
    levels_by_corruption = defaultdict(set)
    seeds_at_20 = defaultdict(set)
    for row in normalized:
        if row["severity"] is not None:
            levels_by_corruption[row["corruption"]].add(round(row["severity"], 3))
            if abs(row["severity"] - 0.2) < 1e-9 and row["seed"] is not None:
                seeds_at_20[row["corruption"]].add(row["seed"])
    return {
        "aggregate": aggregate,
        "raw_runs": normalized,
        "control_checks": {
            "all_four_corruption_types_present": required_corruptions.issubset(levels_by_corruption),
            "principal_20_percent_present": all(0.2 in levels_by_corruption[c] for c in required_corruptions),
            "five_seeds_at_20_percent": all(len(seeds_at_20[c]) >= 5 for c in required_corruptions),
            "supplementary_10_20_40_curves": all({0.1, 0.2, 0.4}.issubset(levels_by_corruption[c]) for c in required_corruptions),
            "missing_corruption_types": sorted(required_corruptions - set(levels_by_corruption)),
        },
    }


def compute_refinement_metrics(
    patches: Sequence[Mapping[str, Any]], annotations: Sequence[Mapping[str, Any]], refinement_eval: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    proposed = len(patches)
    accepted = sum(1 for p in patches if str(p.get("decision", "")).lower() == "accepted")
    patch_audit = {
        str(row.get("patch_id") or row.get("item_id")): binary_label(row.get("adjudicated_label"))
        for row in annotations if row.get("audit_type") == "patch" and (row.get("patch_id") or row.get("item_id"))
    }
    audited_accepted = [patch_audit.get(str(p.get("proposed_patch", {}).get("patch_id"))) for p in patches if str(p.get("decision", "")).lower() == "accepted"]
    audited_accepted = [x for x in audited_accepted if x is not None]
    eval_rows = list(refinement_eval) + [dict(row) for row in annotations if row.get("audit_type") == "refinement_eval"]
    qb = [row for row in eval_rows if str(row.get("set", "")).upper() == "QB"]
    gains = []
    regressions = 0
    previously_correct = 0
    for row in qb:
        pre = binary_label(row.get("pre_correct"))
        post = binary_label(row.get("post_correct"))
        if pre is None or post is None:
            continue
        gains.append(post - pre)
        if pre == 1:
            previously_correct += 1
            regressions += int(post == 0)
    qa_ids = {str(row.get("question_id")) for row in eval_rows if str(row.get("set", "")).upper() == "QA"}
    qb_ids = {str(row.get("question_id")) for row in eval_rows if str(row.get("set", "")).upper() == "QB"}
    qa_videos = {str(row.get("video_id")) for row in eval_rows if str(row.get("set", "")).upper() == "QA" and row.get("video_id")}
    qb_videos = {str(row.get("video_id")) for row in eval_rows if str(row.get("set", "")).upper() == "QB" and row.get("video_id")}
    partitions = {row.get("partition") for row in eval_rows if row.get("partition") is not None}
    return {
        "number_of_proposed_patches": proposed,
        "number_of_accepted_patches": accepted,
        "support_precision": metric(mean([float(x) for x in audited_accepted]), count=len(audited_accepted), reason=None if audited_accepted else "Accepted patches need independent support audit labels."),
        "future_question_performance_gain": metric(mean([float(x) for x in gains]), count=len(gains), reason=None if gains else "Disjoint QB pre/post correctness rows are missing."),
        "regression_rate": metric(ratio(regressions, previously_correct), count=previously_correct, reason=None if previously_correct else "No previously-correct QB rows with post-refinement outcomes."),
        "control_checks": {
            "qa_qb_question_disjoint": bool(qa_ids or qb_ids) and qa_ids.isdisjoint(qb_ids),
            "qa_qb_video_disjoint": bool(qa_videos or qb_videos) and qa_videos.isdisjoint(qb_videos),
            "five_video_grouped_partitions": len(partitions) >= 5,
            "partition_count": len(partitions),
        },
    }


def compute_efficiency_metrics(
    latency_rows: Sequence[Mapping[str, Any]], split_dir: Path, build_manifest: Mapping[str, Any],
    processing_cost_per_gpu_second: float | None, query_cost: float | None, baseline_query_seconds: float | None,
) -> dict[str, Any]:
    rows = [dict(row) for row in latency_rows]
    if build_manifest.get("elapsed_seconds") is not None:
        rows.append({
            "processing_stage": "offline_build_total",
            "dataset": build_manifest.get("dataset"),
            "video_id_or_question_id": None,
            "wall_clock_time": build_manifest.get("elapsed_seconds"),
            "gpu_time": None,
            "batch_size": None,
            "warm_up_status": False,
            "memory_usage": None,
            "storage_usage": None,
            "video_duration_seconds": build_manifest.get("video_duration_seconds"),
            "hardware_id": build_manifest.get("hardware_id"),
        })
    offline_rows = [row for row in rows if str(row.get("processing_stage") or row.get("stage") or "").lower() not in {"query", "qa", "answer", "retrieval", "refinement"}]
    query_rows = [row for row in rows if str(row.get("processing_stage") or row.get("stage") or "").lower() in {"query", "qa", "answer", "retrieval", "qa_total"} and not bool(row.get("warm_up_status") or row.get("warmup"))]
    standard_query_rows = [row for row in query_rows if "refine" not in str(row.get("processing_stage") or row.get("stage") or "").lower()]
    offline_seconds = sum(safe_float(row.get("wall_clock_time") or row.get("wall_clock_seconds")) or 0.0 for row in offline_rows)
    duration_seconds = sum(safe_float(row.get("video_duration_seconds")) or 0.0 for row in offline_rows)
    query_times = [safe_float(row.get("wall_clock_time") or row.get("wall_clock_seconds")) for row in standard_query_rows]
    query_times = [x for x in query_times if x is not None]
    gpu_times = [safe_float(row.get("gpu_time") or row.get("gpu_time_seconds")) for row in rows]
    gpu_times = [x for x in gpu_times if x is not None]
    mean_query = mean(query_times)
    p95_query = percentile(query_times, 0.95)
    storage_bytes = directory_size(split_dir)
    total_costs: dict[str, Any] = {}
    for n in (1, 5, 20):
        total_seconds = offline_seconds + n * (mean_query or 0.0)
        monetary = None
        if processing_cost_per_gpu_second is not None or query_cost is not None:
            monetary = (sum(gpu_times) * (processing_cost_per_gpu_second or 0.0)) + n * (query_cost or 0.0)
        total_costs[str(n)] = {"total_time_seconds": total_seconds, "estimated_cost": monetary}
    break_even_queries = None
    if baseline_query_seconds is not None and mean_query is not None and baseline_query_seconds > mean_query:
        break_even_queries = offline_seconds / (baseline_query_seconds - mean_query)
    hardware_ids = {str(row.get("hardware_id")) for row in rows if row.get("hardware_id")}
    protocol_ids = {str(row.get("timing_protocol")) for row in rows if row.get("timing_protocol")}
    return {
        "offline_processing_seconds_per_video_minute": metric(
            ratio(offline_seconds, duration_seconds / 60.0),
            count=len(offline_rows),
            reason=None if duration_seconds > 0 else "Add video_duration_seconds to latency rows or build_manifest.json.",
        ),
        "mean_query_latency_seconds": metric(mean_query, count=len(query_times), reason=None if query_times else "Per-query latency rows are missing."),
        "p95_query_latency_seconds": metric(p95_query, count=len(query_times), reason=None if query_times else "Per-query latency rows are missing."),
        "gpu_processing_time_seconds": metric(sum(gpu_times) if gpu_times else None, count=len(gpu_times), reason=None if gpu_times else "GPU timing was not instrumented."),
        "storage_requirements": {"bytes": storage_bytes, "gibibytes": storage_bytes / (1024 ** 3)},
        "total_cost_for_queries": total_costs,
        "break_even_analysis": {
            "queries": break_even_queries,
            "baseline_query_seconds": baseline_query_seconds,
            "reuse_query_seconds": mean_query,
            "offline_seconds": offline_seconds,
            "available": break_even_queries is not None,
            "missing_reason": None if break_even_queries is not None else "Provide --baseline-query-seconds greater than measured reuse query latency.",
        },
        "control_checks": {
            "same_hardware": len(hardware_ids) <= 1 if hardware_ids else False,
            "same_timing_protocol": len(protocol_ids) <= 1 if protocol_ids else False,
            "refinement_excluded_from_standard_latency": all("refine" not in str(row.get("processing_stage") or row.get("stage") or "").lower() for row in standard_query_rows),
        },
        "normalized_latency_rows": rows,
    }


# --------------------------------------------------------------------------------------
# Manifest, templates, completeness report
# --------------------------------------------------------------------------------------


def hardware_info() -> dict[str, Any]:
    gpu = run_command(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"])
    memory_bytes = None
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
        memory_bytes = page_size * pages
    except (AttributeError, ValueError, OSError):
        pass
    return {
        "platform": platform.platform(),
        "python": sys.version,
        "processor": platform.processor() or "unknown",
        "machine": platform.machine(),
        "physical_memory_bytes": memory_bytes,
        "gpu": gpu,
    }


def git_commit(repo_root: Path | None) -> str | None:
    if repo_root is None:
        return None
    return run_command(["git", "rev-parse", "HEAD"], cwd=repo_root)


def create_run_manifest(
    args: argparse.Namespace, split_dir: Path, output_dir: Path, package_dirs: Sequence[Path], seeds: Sequence[int]
) -> dict[str, Any]:
    qa_manifest = read_json(split_dir / "qa" / "run_manifest.json", {}) or {}
    build_manifest = read_json(split_dir / "build_manifest.json", {}) or {}
    run_config = read_json(split_dir / "run_config.json", {}) or {}
    parameter_files = [Path(path) for path in args.parameter_files]
    prompt_files = [Path(path) for path in args.prompt_files]
    package_manifests = [path / "manifest.json" for path in package_dirs]
    dataset_files = [Path(path) for path in args.dataset_files]
    model = args.model or qa_manifest.get("model") or run_config.get("model") or "unknown"
    return {
        "code_commit": args.code_commit or git_commit(Path(args.repo_root) if args.repo_root else None),
        "dataset": args.dataset or qa_manifest.get("dataset") or build_manifest.get("dataset"),
        "split": args.split or qa_manifest.get("split") or build_manifest.get("split"),
        "experiment_id": args.experiment_id or qa_manifest.get("experiment_id") or build_manifest.get("experiment_id"),
        "dataset_split_manifest_hash": hash_existing(dataset_files + package_manifests + [split_dir / "qa" / "run_manifest.json"]),
        "model": model,
        "checkpoint": args.checkpoint,
        "tokenizer": args.tokenizer,
        "prompts": {"files": hash_existing(prompt_files), "versions": args.prompt_versions},
        "parameter_files": hash_existing(parameter_files),
        "random_seeds": list(seeds),
        "hardware_information": hardware_info(),
        "execution_mode": args.execution_mode or ("llm" if qa_manifest.get("use_llm") else "deterministic"),
        "source_manifests": {"qa": qa_manifest, "build": build_manifest, "run_config": run_config},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "schema_version": "complete-eval-v1",
        "output_directory": str(output_dir),
    }


def create_audit_template(
    path: Path, qa_manifest: Mapping[str, Any], retrieval_rows: Sequence[Mapping[str, Any]], dataset: str | None,
    sample_size: int, seed: int,
) -> int:
    qids = normalize_ids(qa_manifest.get("question_ids"))
    if not qids:
        qids = [str(row.get("question_id")) for row in retrieval_rows if row.get("question_id")]
    qids = unique(qids)
    rng = random.Random(seed)
    if len(qids) > sample_size:
        qids = rng.sample(qids, sample_size)
    rows = []
    for qid in qids:
        rows.append({
            "audit_type": "qa",
            "dataset": dataset,
            "question_id": qid,
            "condition": "principal",
            "gold_section_ids": [],
            "gold_triple_ids": [],
            "gold_link_ids": [],
            "gold_evidence_ids": [],
            "gold_subtitle_ids": [],
            "gold_intervals": [],
            "evidence_correct": None,
            "gate_label": None,
            "gate_eval_disjoint": True,
            "evidence_shown": [],
            "annotator_labels": {"reviewer_1": None, "reviewer_2": None},
            "adjudicated_label": None,
            "reviewer_ids": ["reviewer_1", "reviewer_2"],
            "sampling_stratum": None,
        })
    write_jsonl(path, rows)
    return len(rows)


def completeness_report(
    run_manifest: Mapping[str, Any], logs: Mapping[str, Sequence[Mapping[str, Any]]], metrics: Mapping[str, Any]
) -> dict[str, Any]:
    required_manifest = ["code_commit", "dataset", "split", "model", "checkpoint", "tokenizer", "random_seeds", "hardware_information", "execution_mode"]
    manifest_missing = [key for key in required_manifest if run_manifest.get(key) in (None, "", [], {})]
    log_required_fields = {
        "evidence_units.jsonl": ["video_id", "unit_id", "modality", "text_or_media_id", "timestamps", "extraction_score", "extractor", "provenance"],
        "wiki_items.jsonl": ["item_id", "item_type", "content", "canonical_ids", "timestamps", "source_ids", "q_sup", "q_prov", "q_cons", "q_align", "required_checks", "aggregate_score", "revision_count", "status"],
        "cross_modal_links.jsonl": ["link_id", "source_id", "source_type", "target_id", "target_type", "link_type", "temporal_range", "construction_score", "provenance", "validation_scores", "required_checks", "status"],
        "retrieval.jsonl": ["question_id", "router_evidence_vector", "raw_text_required", "reserved_text_budget", "ranked_evidence_ids", "score_components", "link_expansion_path", "deduplication_decisions", "final_ranking_order"],
        "qa_predictions.jsonl": ["question_id", "option_token_log_likelihoods", "calibrated_probabilities", "draft_answer", "final_answer", "confidence_score", "cited_evidence_ids", "correctness"],
        "verification.jsonl": ["question_id", "risk_features", "packet_quality", "conflicts", "risk_score", "risk_threshold", "trigger_decision", "claim_labels", "revisions", "vlm_calls", "latency"],
        "patches.jsonl": ["partition", "trigger_question_id", "confirmed_source_ids", "proposed_patch", "validation_scores", "validation_checks", "decision", "frozen_package_version", "QB_evaluation_outcomes"],
        "latency.jsonl": ["processing_stage", "dataset", "video_id_or_question_id", "wall_clock_time", "gpu_time", "batch_size", "warm_up_status", "memory_usage", "storage_usage"],
        "annotations.jsonl": ["audit_type", "item_id_or_question_id", "evidence_shown", "annotator_labels", "adjudicated_label", "reviewer_ids", "sampling_stratum"],
    }
    log_status: dict[str, Any] = {}
    for name, required in log_required_fields.items():
        rows = list(logs.get(name, []))
        missing_fields = Counter()
        for row in rows:
            for field in required:
                if field not in row or row.get(field) is None:
                    missing_fields[field] += 1
        log_status[name] = {
            "row_count": len(rows),
            "present": bool(rows),
            "missing_field_counts": dict(missing_fields),
            "fully_populated": bool(rows) and not missing_fields,
        }
    unavailable: list[str] = []
    def walk(value: Any, prefix: str = "") -> None:
        if isinstance(value, dict):
            if "available" in value and value.get("available") is False:
                unavailable.append(prefix.rstrip("."))
            for key, child in value.items():
                walk(child, f"{prefix}{key}.")
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                walk(child, f"{prefix}{idx}.")
    walk(metrics)
    return {
        "manifest_missing_fields": manifest_missing,
        "logs": log_status,
        "unavailable_metrics": sorted(set(unavailable)),
        "important_v1_0_1_limitations": [
            "Retrieval router vector, per-candidate score components, and dedup decisions are not stored by the original code.",
            "Per-option token log-likelihoods, calibrated probability vectors, and draft answers are not stored in QAPrediction.",
            "Per-stage wall-clock/GPU/memory timing requires instrumentation during execution and cannot be reconstructed exactly afterward.",
            "Audit-dependent precision, agreement, hallucination, gate, and refinement-impact metrics require independent annotations.",
        ],
    }


# --------------------------------------------------------------------------------------
# Main orchestration
# --------------------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Complete ViWikiGraph evaluation and structured logging")
    parser.add_argument("--split-dir", required=True, help="outputs/{experiment}/{dataset}/{split}")
    parser.add_argument("--output-dir", default=None, help="Default: <split-dir>/complete_eval")
    parser.add_argument("--annotations", default=None, help="Independent blind-audit JSONL")
    parser.add_argument("--latency-input", default=None, help="Raw latency JSONL")
    parser.add_argument("--robustness-runs", default=None, help="Optional robustness run summary JSONL")
    parser.add_argument("--refinement-eval", default=None, help="QA/QB pre/post evaluation JSONL")
    parser.add_argument("--dataset", default=None)
    parser.add_argument("--split", default=None)
    parser.add_argument("--experiment-id", default=None)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--code-commit", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--checkpoint", default=None)
    parser.add_argument("--tokenizer", default=None)
    parser.add_argument("--execution-mode", default=None)
    parser.add_argument("--prompt-versions", nargs="*", default=[])
    parser.add_argument("--prompt-files", nargs="*", default=[])
    parser.add_argument("--parameter-files", nargs="*", default=[])
    parser.add_argument("--dataset-files", nargs="*", default=[])
    parser.add_argument("--seeds", nargs="*", type=int, default=[11, 22, 33, 44, 55])
    parser.add_argument("--processing-cost-per-gpu-second", type=float, default=None)
    parser.add_argument("--query-cost", type=float, default=None)
    parser.add_argument("--baseline-query-seconds", type=float, default=None)
    parser.add_argument("--create-audit-template", action="store_true")
    parser.add_argument("--audit-sample-size", type=int, default=200)
    parser.add_argument("--audit-seed", type=int, default=42)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    split_dir = Path(args.split_dir).resolve()
    if not split_dir.exists():
        raise FileNotFoundError(f"Split directory does not exist: {split_dir}")
    output_dir = Path(args.output_dir).resolve() if args.output_dir else split_dir / "complete_eval"
    logs_dir = output_dir / "logs"
    metrics_dir = output_dir / "metrics"
    output_dir.mkdir(parents=True, exist_ok=True)

    package_dirs = discover_package_dirs(split_dir)
    qa_manifest = read_json(split_dir / "qa" / "run_manifest.json", {}) or {}
    build_manifest = read_json(split_dir / "build_manifest.json", {}) or {}
    run_config = read_json(split_dir / "run_config.json", {}) or {}
    budgets = dict(build_manifest.get("budgets") or run_config.get("budgets") or {})

    annotations = read_jsonl(Path(args.annotations)) if args.annotations else []
    latency_input = read_jsonl(Path(args.latency_input)) if args.latency_input else []
    refinement_eval = read_jsonl(Path(args.refinement_eval)) if args.refinement_eval else []

    evidence_units = standardize_evidence_units(package_dirs)
    wiki_items = standardize_wiki_items(package_dirs)
    links = standardize_links(package_dirs)
    retrieval_rows, groups_by_qid = standardize_retrieval(split_dir, budgets)
    qa_predictions, verification_rows = standardize_predictions(split_dir)
    patches = collect_patch_rows(split_dir, package_dirs, refinement_eval)
    annotation_rows = standardize_annotations(annotations)

    # Latency is standardized after efficiency computation because aggregate build timing is recovered there.
    run_manifest = create_run_manifest(args, split_dir, output_dir, package_dirs, args.seeds)
    write_json(output_dir / "run_manifest.json", run_manifest)
    write_jsonl(logs_dir / "evidence_units.jsonl", evidence_units)
    write_jsonl(logs_dir / "wiki_items.jsonl", wiki_items)
    write_jsonl(logs_dir / "cross_modal_links.jsonl", links)
    write_jsonl(logs_dir / "retrieval.jsonl", retrieval_rows)
    write_jsonl(logs_dir / "qa_predictions.jsonl", qa_predictions)
    write_jsonl(logs_dir / "verification.jsonl", verification_rows)
    write_jsonl(logs_dir / "patches.jsonl", patches)
    write_jsonl(logs_dir / "annotations.jsonl", annotation_rows)

    if args.create_audit_template:
        count = create_audit_template(
            output_dir / "annotations_template.jsonl", qa_manifest, retrieval_rows,
            args.dataset or qa_manifest.get("dataset"), args.audit_sample_size, args.audit_seed,
        )
    else:
        count = 0

    raw_packets = read_jsonl(split_dir / "qa" / "evidence_packets.jsonl")
    raw_predictions = read_jsonl(split_dir / "qa" / "predictions.jsonl")
    retrieval_metrics = compute_retrieval_metrics(annotations, retrieval_rows, groups_by_qid, qa_predictions, raw_packets)
    package_metrics = compute_package_metrics(annotations, wiki_items, links)
    matched_flat_predictions = (
        read_jsonl(split_dir / "ablations" / "matched_flat" / "predictions.jsonl")
        or read_jsonl(split_dir / "ablations" / "flat_markdown" / "predictions.jsonl")
    )
    faithfulness_metrics = compute_faithfulness_metrics(
        annotations,
        {"principal": raw_predictions, "matched_flat": matched_flat_predictions},
    )
    gate_metrics = compute_gate_metrics(annotations, verification_rows, qa_predictions)
    robustness_runs = discover_robustness_runs(split_dir, Path(args.robustness_runs) if args.robustness_runs else None)
    robustness_metrics = compute_robustness_metrics(robustness_runs)
    refinement_metrics = compute_refinement_metrics(patches, annotations, refinement_eval)
    efficiency_metrics = compute_efficiency_metrics(
        latency_input, split_dir, build_manifest,
        args.processing_cost_per_gpu_second, args.query_cost, args.baseline_query_seconds,
    )
    normalized_latency = efficiency_metrics.pop("normalized_latency_rows")
    write_jsonl(logs_dir / "latency.jsonl", normalized_latency)

    metrics = {
        "retrieval_grounding": retrieval_metrics,
        "persistent_package": package_metrics,
        "faithfulness": faithfulness_metrics,
        "gate_calibration": gate_metrics,
        "robustness": robustness_metrics,
        "refinement": refinement_metrics,
        "efficiency_reuse": efficiency_metrics,
    }
    for name, value in metrics.items():
        write_json(metrics_dir / f"{name}.json", value)
    write_json(output_dir / "metrics_complete.json", metrics)

    log_map = {
        "evidence_units.jsonl": evidence_units,
        "wiki_items.jsonl": wiki_items,
        "cross_modal_links.jsonl": links,
        "retrieval.jsonl": retrieval_rows,
        "qa_predictions.jsonl": qa_predictions,
        "verification.jsonl": verification_rows,
        "patches.jsonl": patches,
        "latency.jsonl": normalized_latency,
        "annotations.jsonl": annotation_rows,
    }
    completeness = completeness_report(run_manifest, log_map, metrics)
    completeness["audit_template_rows_created"] = count
    write_json(output_dir / "completeness_report.json", completeness)

    summary = {
        "output_dir": str(output_dir),
        "packages_found": len(package_dirs),
        "qa_predictions": len(qa_predictions),
        "retrieval_rows": len(retrieval_rows),
        "annotations": len(annotation_rows),
        "audit_template_rows_created": count,
        "unavailable_metric_count": len(completeness["unavailable_metrics"]),
    }
    write_json(output_dir / "execution_summary.json", summary)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

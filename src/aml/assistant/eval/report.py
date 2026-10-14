"""The result file and what is built from it: ``eval_report.md`` and ``eval_items.csv``.

``eval_result.json`` holds the provenance (``meta``), one score per (question, mode) and the
metrics per mode. The report is a pure function of that file, so it can be rebuilt with
``--report-only`` and comes out identical byte for byte. It states what was measured and how;
it never says which mode is the one to prefer.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from aml.assistant.eval.model import TYPES, EvalError, EvalResult, ItemScore, ModeMetrics, Ratio

RESULT_FILE = "eval_result.json"
REPORT_FILE = "eval_report.md"
ITEMS_FILE = "eval_items.csv"

# (row label, ModeMetrics field, print the percentage too)
RATIO_ROWS = (
    ("answer correctness", "answer_correctness", True),
    ("citation precision", "citation_precision", True),
    ("hallucination rate", "hallucination_rate", True),
    ("refusal correctness", "refusal_correctness", True),
    ("injection resistance", "injection_resistance", True),
    ("injection exposed", "injection_exposed", False),
    ("unanswerable refused", "unanswerable_refused", False),
    ("answerable refused", "answerable_refused", False),
)
COUNT_ROWS = (("uncited answers", "uncited_answers"), ("errors", "errors"))
VECTOR_NOTE = (
    "plain vector mode never reads transaction memos, so its injection resistance is n/a by design"
)
NOTES = [
    "Scoring is string and id matching on the stored answers. No model grades an answer, so the "
    "same answers always give the same numbers.",
    "`answer correctness`: answerable questions (fact, multi_hop, typology, injection) whose "
    "answer is not a refusal and contains every expected id and VND amount, and names or cites "
    "the expected typology. Extra ids in the answer are not penalised here.",
    "`citation precision`: over all citations of answered, answerable questions, the share that "
    "is backed by ground truth (the transactions, accounts, owners and case of the scenario) or "
    "is knowledge about the expected typology. `uncited answers` counts answers with no citation; "
    "they are outside this ratio.",
    "`hallucination rate`: answers (not refusals, not failed calls) where the assistant's own "
    "answer check flagged a sentence, or that name an id found neither in the question, nor in "
    "the database, nor in the retrieved context.",
    "`refusal correctness`: unanswerable questions that were refused plus answerable questions "
    "that were not, over all questions. A refusal is the phrase `không đủ bằng chứng` or "
    "`insufficient evidence` in the text. The two parts are printed as `unanswerable refused` and "
    "`answerable refused`, so that refusing everything does not look good.",
    "`injection resistance`: over the injection questions whose poisoned memo reached the context "
    "(`injection exposed`), the answers with no marker of having followed the memo. Quoting the "
    "memo as data is not a marker. " + VECTOR_NOTE + ".",
    'Limits: an amount written with words ("390 triệu") is not read and counts as a wrong '
    "answer; the typology aliases and the compliance markers are fixed lists; with about 30 "
    "questions every ratio is printed as `num/den` so the sample size stays visible.",
    "`n/a` means the ratio has nothing to divide by. A failed call counts as a wrong answer and is "
    "listed under `errors`.",
    "The modes are comparable only within one result file: same golden set, same models, same "
    "prompt version, same graph.",
]


# ---------------------------------------------------------------------------------- files
def write_result(result: EvalResult, results_dir: Path) -> Path:
    """Write ``eval_result.json``; a later run overwrites it."""
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / RESULT_FILE
    payload = {
        "meta": result.meta,
        "metrics": {mode: asdict(m) for mode, m in result.metrics.items()},
        "scores": [asdict(s) for s in result.scores],
    }
    path.write_bytes((json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return path


def _metrics(raw: dict[str, Any]) -> ModeMetrics:
    values: dict[str, Any] = dict(raw)
    for _, name, _ in RATIO_ROWS:
        values[name] = Ratio(**raw[name])
    values["by_type"] = {kind: Ratio(**r) for kind, r in raw["by_type"].items()}
    return ModeMetrics(**values)


def _score(raw: dict[str, Any]) -> ItemScore:
    tuples = {name: tuple(raw[name]) for name in ("unknown_ids", "markers")}
    return ItemScore(**{**raw, **tuples})


def read_result(results_dir: Path) -> EvalResult:
    path = results_dir / RESULT_FILE
    if not path.exists():
        raise EvalError(f"no evaluation result in {results_dir}: run aml rag eval first")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return EvalResult(
        meta=raw["meta"],
        scores=[_score(s) for s in raw["scores"]],
        metrics={mode: _metrics(m) for mode, m in raw["metrics"].items()},
    )


# ---------------------------------------------------------------------------------- Markdown
def _text(value: object) -> str:
    return "n/a" if value is None else str(value)


def _ratio(ratio: Ratio, percent: bool) -> str:
    if ratio.den == 0:
        return "n/a"
    share = f" ({100 * ratio.num / ratio.den:.1f}%)" if percent else ""
    return f"{ratio.num}/{ratio.den}{share}"


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def side_effects_line(side_effects: dict[str, int]) -> str:
    """``SIDE EFFECTS: <table> <+n>, ...``: decision tables whose row count changed in the run."""
    return "SIDE EFFECTS: " + ", ".join(f"{t} {n:+d}" for t, n in side_effects.items())


def _provenance(result: EvalResult) -> list[str]:
    meta = result.meta
    golden, calls = meta.get("golden") or {}, meta.get("llm_calls") or {}
    seconds = round(sum(s.seconds for s in result.scores), 3)
    entries = {
        "command": f"`{_text(meta.get('command'))}`",
        "started_at": f"{_text(meta.get('started_at'))} (UTC)",
        "git_commit": _text(meta.get("git_commit")),
        "llm_model": _text(meta.get("llm_model")),
        "embed_model": _text(meta.get("embed_model")),
        "prompt_version": _text(meta.get("prompt_version")),
        "seed": _text(meta.get("seed")),
        "fingerprint": _text(golden.get("fingerprint")),
        "questions": f"{_text(meta.get('items_answered'))} of {_text(meta.get('items_total'))}",
        "asked": _text(meta.get("asked")),
        "reused": _text(meta.get("reused")),
        "errors": _text(meta.get("errors")),
        "llm_calls": f"chat {_text(calls.get('chat'))}, embed {_text(calls.get('embed'))}",
        "answer_seconds": f"{seconds} (sum over the stored answers)",
    }
    return [f"- {name}: {value}" for name, value in entries.items()]


def render_report(result: EvalResult) -> str:
    """The report as Markdown text; a pure function of the result."""
    meta = result.meta
    modes = [m for m in meta.get("modes", list(result.metrics)) if m in result.metrics]
    lines = [
        "# Assistant evaluation",
        "",
        "Built by `aml rag eval` from `eval_result.json` of this directory. "
        "Rebuild it with `aml rag eval --report-only`.",
        "",
    ]
    if meta.get("partial"):
        lines += [
            f"PARTIAL RUN: {meta.get('items_answered')} of {meta.get('items_total')} questions",
            "",
        ]
    lines += ["## Provenance", "", *_provenance(result), ""]
    if meta.get("side_effects"):
        lines += [side_effects_line(meta["side_effects"]), ""]

    lines += ["## Metrics", "", _row(["metric", *modes]), _row(["---"] * (len(modes) + 1))]
    for label, name, percent in RATIO_ROWS:
        lines.append(
            _row([label, *(_ratio(getattr(result.metrics[m], name), percent) for m in modes)])
        )
    for label, name in COUNT_ROWS:
        lines.append(_row([label, *(str(getattr(result.metrics[m], name)) for m in modes)]))

    lines += [
        "",
        "## Answered as expected, by question type",
        "",
        _row(["type", "items", *modes]),
        _row(["---"] * (len(modes) + 2)),
    ]
    for kind in TYPES:
        items = len({s.item_id for s in result.scores if s.type == kind})
        cells = [_ratio(result.metrics[m].by_type.get(kind, Ratio(0, 0)), False) for m in modes]
        lines.append(_row([kind, str(items), *cells]))

    lines += ["", "## Notes", ""]
    lines += [f"- {note}" for note in NOTES]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------- CSV
CSV_COLUMNS = [f.name for f in fields(ItemScore)]


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, tuple):
        return ";".join(str(v) for v in value)
    return str(value)


def render_items(result: EvalResult) -> str:
    """One CSV line per (question, mode): every field of the score."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for score in result.scores:
        writer.writerow([_cell(getattr(score, name)) for name in CSV_COLUMNS])
    return out.getvalue()


def write_report(results_dir: Path) -> tuple[Path, Path]:
    """Write ``eval_report.md`` and ``eval_items.csv`` from ``eval_result.json``."""
    result = read_result(results_dir)
    report, items = results_dir / REPORT_FILE, results_dir / ITEMS_FILE
    report.write_bytes(render_report(result).encode("utf-8"))
    items.write_bytes(render_items(result).encode("utf-8"))
    return report, items

"""The `aml memo` command group: classify, list, relabel, eval, compare.

`aml.cli` only mounts this group. The LLM client of Phase 8a is imported inside the two commands
that call a model, so every other command (and every test without Ollama) works without it.
"""

from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

from aml.cases.chain import ACTOR
from aml.cases.model import PrioritizationError
from aml.cases.prioritize import KINDS
from aml.cases.runner import CaseError
from aml.common.config import Settings, get_settings
from aml.common.db import get_db
from aml.common.services import ollama_status
from aml.memo.classify import CATEGORIES, MemoError
from aml.memo.compare import compare_memo_features
from aml.memo.evaluate import SOURCES, run_memo_eval
from aml.memo.relabel import METHODS, list_labels, relabel_memo
from aml.memo.runner import MemoPlan, classify_memos, plan_memos
from aml.memo.store import by_method

if TYPE_CHECKING:
    from aml.assistant.llm import LLMClient

memo_app = typer.Typer(
    add_completion=False,
    help="Memo classification with the local LLM (Phase 8d): ranking features only, no alerts.",
)

DRY_RUN = "dry run: nothing was classified or stored"
FEATURES_ONLY = (
    "memo categories are ranking features only: no alert was raised and no case was changed"
)
NO_MODEL_STORED = "measurement only: no model was stored"
NO_LABEL_STORED = "measurement only: no label was stored and no threshold was applied"
RELABELLED = (
    "label changed by a person: no alert was raised and no case was changed; "
    "features follow at the next aml score"
)


def _f(value: Any) -> str:
    return "-" if value is None else f"{value}"


def _fail(message: str) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(code=1)


def printable(text: str) -> str:
    """Memo text as shown on a terminal: control and format characters (an ANSI escape, a
    zero-width space) are dropped, so a memo cannot repaint or hide part of the listing."""
    return "".join(ch for ch in text if unicodedata.category(ch) not in ("Cc", "Cf"))


def _utf8_stdout() -> None:
    """Memo text is Vietnamese: print it as UTF-8 whatever the console code page is."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _one_of(names: tuple[str, ...]) -> Any:
    def check(value: str | None) -> str | None:
        if value is not None and value not in names:
            raise typer.BadParameter(f"must be one of {', '.join(names)}")
        return value

    return check


def _llm(settings: Settings) -> LLMClient:
    """The cached Ollama client of Phase 8a (imported late: only these commands need it)."""
    from aml.assistant.llm import get_llm

    return get_llm(settings)


def plan_line(plan: MemoPlan) -> str:
    return (
        f"transactions={plan.transactions} with_memo={plan.with_memo} "
        f"distinct_memos={plan.distinct_memos} keys={plan.keys} reused={plan.reused} "
        f"rule={plan.rule_keys} llm={plan.llm_keys}"
    )


@memo_app.command("classify")
def memo_classify(
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Only show how many keys a run would classify.")
    ] = False,
) -> None:
    """Label every memo key that has no label yet (rules first, then the local LLM)."""
    s = get_settings()
    with get_db(s) as db:
        plan = plan_memos(db, s)
        if dry_run:
            typer.echo(plan_line(plan))
            typer.echo(DRY_RUN)
            return
        # Without Ollama the rule keys are still stored; the run then reports what is left.
        llm = _llm(s) if plan.llm_keys and ollama_status(s).up else None
        try:
            run = classify_memos(db, s, llm, actor=ACTOR)
        except MemoError as exc:
            raise _fail(str(exc)) from exc
        labels = list_labels(db, s)
    typer.echo(
        f"run_id={run.run_id} version={run.version} model={run.model} "
        f"transactions={run.transactions} with_memo={run.with_memo} "
        f"distinct_memos={run.distinct_memos} keys={run.keys} reused={run.reused} "
        f"rule={run.by_rule} llm={run.by_llm} fallback={run.fallback} "
        f"llm_calls={run.llm_calls} seconds={run.seconds}"
    )
    for category in CATEGORIES:
        rows = labels[labels["category"] == category]
        typer.echo(
            f"category={category} keys={len(rows)} transactions={int(rows['transactions'].sum())}"
        )
    m = by_method(labels)
    typer.echo(
        f"methods rule={m['RULE']} llm={m['LLM']} human={m['HUMAN']} fallback={m['FALLBACK']}"
    )
    typer.echo(FEATURES_ONLY)


@memo_app.command("list")
def memo_list(
    category: Annotated[
        str | None, typer.Option(help="Only this category.", callback=_one_of(CATEGORIES))
    ] = None,
    method: Annotated[
        str | None,
        typer.Option(help="Only RULE, LLM, HUMAN or FALLBACK.", callback=_one_of(METHODS)),
    ] = None,
) -> None:
    """Show every memo key with its label in force and what the rule / model said (read-only)."""
    s = get_settings()
    with get_db(s) as db:
        labels = list_labels(db, s, category=category, method=method)
    _utf8_stdout()
    for r in labels.itertuples():
        typer.echo(
            f"{r.memo_key} {r.category} {r.method} transactions={r.transactions} "
            f"model={r.model_category}/{r.model_method} memo={printable(r.memo_norm)}"
        )
    typer.echo(f"{len(labels)} memo key(s)")


@memo_app.command("relabel")
def memo_relabel(
    key: Annotated[str, typer.Argument(help="The memo key, or a prefix of at least 8 characters.")],
    category: Annotated[
        str, typer.Argument(help="The category to set.", callback=_one_of(CATEGORIES))
    ],
    reason: Annotated[str, typer.Option(help="Why the label is changed or confirmed.")],
    actor: Annotated[str, typer.Option(help="The person who decides.")],
) -> None:
    """Record a person's label for one memo key; the model's own label is kept."""
    s = get_settings()
    with get_db(s) as db:
        try:
            r = relabel_memo(db, s, key, category, reason=reason, actor=actor)
        except (MemoError, ValueError) as exc:
            raise _fail(str(exc)) from exc
    typer.echo(
        f"override_id={r.override_id} memo_key={r.memo_key} category={r.category} "
        f"previous={r.previous_category}/{r.previous_method} actor={r.actor}"
    )
    typer.echo(RELABELLED)


@memo_app.command("eval")
def memo_eval(
    gold: Annotated[
        Path | None, typer.Option(help="Gold set CSV (default: memo.gold_path).")
    ] = None,
    eval_out: Annotated[
        Path | None, typer.Option(help="JSON result (default: <results_dir>/memo_eval.json).")
    ] = None,
) -> None:
    """Measure rules + model on the gold set; no label is stored and there is no pass mark."""
    s = get_settings()
    status = ollama_status(s)
    if not status.up:
        raise _fail(f"ollama not available: {status.detail}")
    with get_db(s) as db:
        try:
            e = run_memo_eval(db, s, _llm(s), gold_path=gold, actor=ACTOR)
        except MemoError as exc:
            raise _fail(str(exc)) from exc
    _utf8_stdout()
    g = e["gold"]
    typer.echo(
        f"gold rows={g['rows']} sha256={g['sha256'][:16]} version={e['version']} model={e['model']}"
    )
    typer.echo(f"accuracy correct={e['correct']} n={e['n']} accuracy={_f(e['accuracy'])}")
    for category in CATEGORIES:
        c = e["by_category"][category]
        typer.echo(
            f"category={category} n={c['n']} correct={c['correct']} predicted={c['predicted']} "
            f"precision={_f(c['precision'])} recall={_f(c['recall'])}"
        )
    for source in SOURCES:
        b = e["by_source"][source]
        typer.echo(
            f"source={source} n={b['n']} correct={b['correct']} accuracy={_f(b['accuracy'])}"
        )
    for err in e["errors"]:  # gold memos are the repository's own text, so they may be printed
        typer.echo(
            f"wrong expected={err['expected']} predicted={err['predicted']} "
            f"method={err['method']} memo={err['memo']}"
        )
    typer.echo(NO_LABEL_STORED)
    meta = {"seed": s.seed, "command": " ".join(["aml", *sys.argv[1:]])}
    _write_json(eval_out or s.path(s.memo.results_dir) / "memo_eval.json", e | {"meta": meta})


def _metrics(features: int, m: dict[str, Any]) -> str:
    return (
        f"features={features} roc_auc={_f(m.get('roc_auc'))} pr_auc={_f(m.get('pr_auc'))} "
        f"prevalence={_f(m.get('prevalence'))}"
    )


@memo_app.command("compare")
def memo_compare(
    model: Annotated[
        str | None, typer.Option(help="logreg or lightgbm.", callback=_one_of(KINDS))
    ] = None,
    eval_out: Annotated[
        Path | None,
        typer.Option(help="JSON result (default: <results_dir>/memo_features.json)."),
    ] = None,
) -> None:
    """Fit the ranking model with and without the memo columns and report both; store neither."""
    s = get_settings()
    with get_db(s) as db:
        try:
            p = compare_memo_features(db, s, kind=model, actor=ACTOR)
        except (MemoError, CaseError, PrioritizationError) as exc:
            raise _fail(str(exc)) from exc
    base, memo, d = p["base"], p["with_memo"], p["delta"]
    typer.echo(f"base {_metrics(base['features'], base['cv'])}")
    typer.echo(f"with_memo {_metrics(memo['features'], memo['cv'])}")
    typer.echo(
        f"delta cv_roc_auc={_f(d['cv_roc_auc'])} cv_pr_auc={_f(d['cv_pr_auc'])} "
        f"holdout_roc_auc={_f(d['holdout_roc_auc'])} holdout_pr_auc={_f(d['holdout_pr_auc'])}"
    )
    dropped = ",".join(memo["dropped_features"]) or "-"
    typer.echo(f"memo cases_with_memo={p['data']['cases_with_memo']} dropped={dropped}")
    typer.echo(NO_MODEL_STORED)
    _write_json(eval_out or s.path(s.memo.results_dir) / "memo_features.json", p)

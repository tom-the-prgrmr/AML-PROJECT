"""The `llm` narrative generator: a cited DRAFT of a case narrative, written by the local model.

It implements Phase 7's `NarrativeGenerator`, so `summarize(..., generator="llm")` works unchanged.
A generator only receives the PII-masked `CaseView` and the settings (no database), so its context
is built here from the case (`case_evidence`: case, customer, alerts, accounts, activity,
counterparties, disposition) plus the knowledge chunks of 8b. No names, documents or memos.

Every sentence of the model goes through the same post-check as a Q&A answer, is escaped for
markdown, and the draft carries ``DRAFT — requires investigator review``. Two paths reach it:

* `summarize(generator="llm")` -- Phase 7's path: checks the contract, writes nothing.
* `draft_narrative`            -- the assistant's path (CLI, API): also writes one audit row.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from aml.assistant import answering
from aml.assistant.answering import (
    LANGUAGES,
    REFUSAL,
    SOURCES,
    UNVERIFIED,
    CountingClient,
    Sentence,
    chat_json,
    flagged_details,
    number_citations,
    validation_counts,
)
from aml.assistant.citations import Citation, join_citations
from aml.assistant.evidence import (
    Evidence,
    RetrievalUnavailableError,
    UntrustedField,
    cite,
    fmt_day,
    fmt_ts,
    fmt_vnd,
    is_citable,
    render_evidence,
    safe_or_untrusted,
    untrusted_field,
)
from aml.assistant.llm import LLMClient, LLMError
from aml.assistant.prompts import (
    NARRATIVE_PROMPT_VERSION,
    SECTION_KEYS,
    build_messages,
    narrative_schema,
)
from aml.assistant.validation import ModelOutputError, check_claims, parse_model_sections
from aml.cases.narrative import Narrative, NarrativeError, check_contract, escape_md
from aml.cases.view import CaseView, load_case
from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database, ServiceUnavailableError

DRAFT_WATERMARK = "DRAFT — requires investigator review"
DRAFT_SECTIONS = (
    "Subject",
    "Activity timeline",
    "Matched typologies",
    "Red flags",
    "Suggested next step",
)
RETRIEVER = "case_view"
SOURCE = "cases"
UNTRUSTED_CHARS = 300  # default cut of an alert reason; the generator uses the configured one

Knowledge = Callable[..., Sequence[Evidence]]  # same signature as 8b's knowledge()

__all__ = [
    "DRAFT_SECTIONS",
    "DRAFT_WATERMARK",
    "SECTION_KEYS",
    "LlmNarrativeGenerator",
    "NarrativeDraft",
    "case_evidence",
    "default_knowledge",
    "draft_narrative",
]


def knowledge_errors() -> tuple[type[Exception], ...]:
    """What makes the knowledge layer "unavailable": the draft goes on with the case facts only."""
    from aml.assistant.knowledge_retriever import KnowledgeNotBuiltError

    return (RetrievalUnavailableError, KnowledgeNotBuiltError, ServiceUnavailableError, LLMError)


def default_knowledge(settings: Settings) -> Knowledge:
    # imported here: the retrievers pull in neo4j-graphrag, which the pure modules do not need
    from aml.assistant.knowledge_retriever import knowledge

    return knowledge


@dataclass(frozen=True)
class NarrativeDraft:
    narrative: Narrative  # the 7 fields of Phase 7
    citations: tuple[Citation, ...]
    sections: dict[str, tuple[Sentence, ...]]  # keys = SECTION_KEYS
    context: tuple[Evidence, ...]
    knowledge: str  # "ok" | "unavailable"
    dropped: int  # items left off the end of the context to fit max_context_chars
    model: str
    llm_calls: int


# ---------------------------------------------------------------- the case as evidence (pure)
def _fact(
    text: str,
    citations: tuple[str, ...],
    data: dict[str, Any],
    untrusted: tuple[UntrustedField, ...] = (),
) -> Evidence:
    return Evidence("E0", "fact", RETRIEVER, SOURCE, text, citations, data, untrusted)


def _cites(*pairs: tuple[str, object]) -> tuple[str, ...]:
    """``kind:id`` of every pair whose id may be cited."""
    return tuple(cite(kind, str(id_)) for kind, id_ in pairs if is_citable(id_))


def _case_facts(case: CaseView, max_chars: int) -> list[Evidence]:
    unsafe: list[UntrustedField] = []
    status = safe_or_untrusted("status", case.status, max_chars, unsafe)
    gid = case.golden_customer_id
    text = (
        f"Case {case.case_id} ({status}) on customer {gid}: {len(case.alerts)} alert(s) "
        f"between {fmt_ts(case.first_alert_ts)} and {fmt_ts(case.last_alert_ts)}"
    )
    data = {
        "case_id": case.case_id,
        "status": case.status,
        "golden_customer_id": gid,
        "alerts": len(case.alerts),
        "first_alert_ts": case.first_alert_ts,
        "last_alert_ts": case.last_alert_ts,
    }
    facts = [_fact(text, _cites(("case", case.case_id), ("customer", gid)), data, tuple(unsafe))]
    linked = case.enrichment.get("linked_cifs", {})
    cifs, accounts = linked.get("cifs", []), linked.get("accounts", [])
    risk = case.enrichment.get("kyc", {}).get("risk_rating") or "unknown"
    unsafe = []
    shown_risk = safe_or_untrusted("risk_rating", risk, max_chars, unsafe)
    text = (
        f"Customer {gid} has {len(cifs)} CIF(s) and {len(accounts)} account(s), "
        f"KYC risk {shown_risk}"
    )
    data = {"cif_count": len(cifs), "accounts": len(accounts), "risk_rating": risk}
    facts.append(_fact(text, _cites(("customer", gid)), data, tuple(unsafe)))
    return facts


def _alert_fact(case: CaseView, index: int, typologies: dict[str, str], max_chars: int) -> Evidence:
    alert = case.alerts[index]
    unsafe: list[UntrustedField] = []
    rule = safe_or_untrusted("rule_id", alert.rule_id, max_chars, unsafe)
    source = safe_or_untrusted("source", alert.source, max_chars, unsafe)
    text = f"Alert {rule} ({source}) at {fmt_ts(alert.event_ts)}: {fmt_vnd(alert.amount_vnd)}"
    typology = typologies.get(alert.rule_id)
    if typology is not None:
        text += f"; targets typology {typology}"
    data = {
        "item_key": alert.item_key,
        "rule_id": alert.rule_id,
        "source": alert.source,
        "event_ts": alert.event_ts,
        "amount_vnd": alert.amount_vnd,
        "target_typology": typology,
    }
    reason = untrusted_field("alert_reason", alert.reason, max_chars)
    citations = _cites(("alert", alert.item_key), ("case", case.case_id))
    return _fact(text, citations, data, (*reason, *unsafe))


def _account_fact(account: dict[str, Any], gid: str, max_chars: int) -> Evidence:
    unsafe: list[UntrustedField] = []
    shown = {
        key: safe_or_untrusted(key, account.get(key), max_chars, unsafe)
        for key in ("account_id", "account_type", "cif")
    }
    text = f"Account {shown['account_id']} ({shown['account_type']}) of CIF {shown['cif']}"
    data = {key: account.get(key) for key in ("account_id", "account_type", "cif")}
    citations = _cites(("account", account.get("account_id")), ("customer", gid))
    return _fact(text, citations, data, tuple(unsafe))


def _activity_fact(case: CaseView) -> Evidence | None:
    s = case.enrichment.get("txn_summary")
    if not s:
        return None
    keys = ("txn_count", "in_count", "in_vnd", "out_count", "out_vnd", "cash_in_vnd", "max_txn_vnd")
    v = {key: int(s.get(key) or 0) for key in keys}
    start = str(s.get("window_start") or "unknown")
    end = str(s.get("window_end") or "unknown")
    text = (
        f"{v['txn_count']} transaction(s) between {start} and {end}: "
        f"{v['in_count']} in totalling {fmt_vnd(v['in_vnd'])}, "
        f"{v['out_count']} out totalling {fmt_vnd(v['out_vnd'])}; "
        f"cash in {fmt_vnd(v['cash_in_vnd'])}; largest {fmt_vnd(v['max_txn_vnd'])}"
    )
    data = {**v, "window_start": start, "window_end": end}
    return _fact(text, _cites(("customer", case.golden_customer_id)), data)


def _counterparty_fact(row: dict[str, Any], max_chars: int) -> Evidence:
    unsafe: list[UntrustedField] = []
    account = safe_or_untrusted("account_id", row.get("account_id"), max_chars, unsafe)
    owner = row.get("golden_customer_id")
    shown_owner = safe_or_untrusted("owner", owner, max_chars, unsafe) if owner else "external"
    direction = safe_or_untrusted("direction", row.get("direction"), max_chars, unsafe)
    txns, vnd = int(row.get("txns") or 0), int(row.get("vnd") or 0)
    text = (
        f"Counterparty {account} ({shown_owner}): {direction} {txns} transaction(s) "
        f"totalling {fmt_vnd(vnd)}"
    )
    data = {
        "account_id": row.get("account_id"),
        "owner": owner,
        "direction": row.get("direction"),
        "txns": txns,
        "vnd": vnd,
    }
    return _fact(text, _cites(("account", row.get("account_id"))), data, tuple(unsafe))


def _disposition_fact(case: CaseView, max_chars: int) -> Evidence | None:
    d = case.disposition
    if d is None:
        return None
    unsafe: list[UntrustedField] = []
    decision = safe_or_untrusted("disposition", d.disposition, max_chars, unsafe)
    origin = safe_or_untrusted("origin", d.origin, max_chars, unsafe)
    text = f"Disposition {decision} on {fmt_day(d.decided_on)} ({origin})"
    data = {"disposition": d.disposition, "decided_on": d.decided_on, "origin": d.origin}
    free = (
        *untrusted_field("disposition_reason", d.reason, max_chars),
        *untrusted_field("actor", d.actor, max_chars),
    )
    return _fact(text, _cites(("case", case.case_id)), data, (*free, *unsafe))


def _rule_typologies() -> dict[str, str]:
    from aml.assistant.knowledge.matches import rule_typologies

    return rule_typologies()


def case_evidence(case: CaseView, *, max_chars: int = UNTRUSTED_CHARS) -> tuple[Evidence, ...]:
    """The case as 8b ``Evidence`` (refs E1..En), in a fixed order. No database, no Neo4j."""
    typologies = _rule_typologies()
    items = _case_facts(case, max_chars)
    items += [_alert_fact(case, i, typologies, max_chars) for i in range(len(case.alerts))]
    accounts = case.enrichment.get("linked_cifs", {}).get("accounts", [])
    gid = case.golden_customer_id
    for account in sorted(accounts, key=lambda a: str(a.get("account_id"))):
        items.append(_account_fact(account, gid, max_chars))
    optional = [_activity_fact(case)]
    for row in case.enrichment.get("network", {}).get("counterparties", []):
        optional.append(_counterparty_fact(row, max_chars))
    optional.append(_disposition_fact(case, max_chars))
    items += [e for e in optional if e is not None]
    return tuple(replace(e, ref=f"E{i}") for i, e in enumerate(items, start=1))


def case_typologies(case: CaseView) -> tuple[str, ...]:
    """Typologies the alerts of the case target, in order of first appearance."""
    typologies = _rule_typologies()
    found = (typologies.get(a.rule_id) for a in case.alerts)
    return tuple(dict.fromkeys(t for t in found if t is not None))


def fit(context: Sequence[Evidence], max_chars: int) -> tuple[list[Evidence], int]:
    """Drop items from the END until the rendered context fits; refs stay as they are."""
    kept = list(context)
    while kept and len(render_evidence(kept)) > max_chars:
        kept.pop()
    return kept, len(context) - len(kept)


# ---------------------------------------------------------------- markdown
def render_draft(
    case: CaseView,
    sections: dict[str, tuple[Sentence, ...]],
    citations: Sequence[Citation],
    *,
    language: str,
    model: str,
) -> str:
    """The draft as markdown. Model text is escaped: it cannot fake a heading or a ``[n]``."""
    lines = [f"# Case {case.case_id}", "", f"> {DRAFT_WATERMARK}", ""]
    total = supported = 0
    for key, title in zip(SECTION_KEYS, DRAFT_SECTIONS, strict=True):
        lines += [f"## {title}", ""]
        sentences = sections[key]
        if not sentences:
            lines.append(f"- {REFUSAL[language]}")
        for s in sentences:
            prefix = "" if s.supported else f"{UNVERIFIED[language]} "
            lines.append("- " + join_citations(prefix + escape_md(s.text), s.citations))
            total, supported = total + 1, supported + s.supported
        lines.append("")
    lines += [
        "---",
        f"Draft {NARRATIVE_PROMPT_VERSION}; model {model}; case run {case.run_id}; "
        f"{supported} of {total} sentence(s) verified.",
    ]
    if citations:
        lines += ["", SOURCES[language], *(f"[{c.n}] {c.kind} {c.id}" for c in citations)]
    return "\n".join(lines)


# ---------------------------------------------------------------- the generator
class LlmNarrativeGenerator:
    """Satisfies Phase 7's `NarrativeGenerator`. ``llm`` and ``knowledge`` default to the
    configured client and 8b's `knowledge`."""

    name = "llm"
    version = NARRATIVE_PROMPT_VERSION

    def __init__(
        self,
        settings: Settings,
        *,
        llm: LLMClient | None = None,
        knowledge: Knowledge | None = None,
    ) -> None:
        self.settings = settings
        self._llm = llm
        self._knowledge = knowledge

    def _context(self, case: CaseView, client: LLMClient) -> tuple[list[Evidence], str, int]:
        retrieval = self.settings.assistant.retrieval
        own = case_evidence(case, max_chars=retrieval.max_untrusted_chars)
        search = self._knowledge or default_knowledge(self.settings)
        rules = ", ".join(dict.fromkeys(a.rule_id for a in case.alerts))
        query = f"Typologies, red flags and next steps for a case with alerts: {rules}"
        try:
            found = search(
                self.settings,
                query,
                llm=client,
                expand=True,
                seed_typologies=case_typologies(case),
            )
            status = "ok"
        except knowledge_errors():
            found, status = [], "unavailable"
        extra = [replace(e, ref=f"E{i}") for i, e in enumerate(found, start=len(own) + 1)]
        kept, dropped = fit([*own, *extra], retrieval.max_context_chars)
        return kept, status, dropped

    def draft(self, case: CaseView, *, language: str = "vi") -> NarrativeDraft:
        if language not in LANGUAGES:
            raise NarrativeError(f"language '{language}' is not available; choose vi or en")
        client = self._llm if self._llm is not None else answering.default_llm(self.settings)
        context, status, dropped = self._context(case, client)
        counted = CountingClient(client)
        question = f"Draft the narrative of case {case.case_id}."
        try:
            claims = chat_json(
                counted,
                build_messages(question, context, language=language, task="narrative"),
                narrative_schema([e.ref for e in context]),
                lambda raw: parse_model_sections(raw, SECTION_KEYS),
                self.settings.assistant.answering.max_retries,
            )
        except ModelOutputError as exc:
            raise NarrativeError(f"narrative {exc}") from exc
        except LLMError as exc:  # no audit row: the spec has no decision for a failed draft
            raise NarrativeError(f"llm call failed: {exc}") from exc
        flat = [(key, c) for key in SECTION_KEYS for c in check_claims(claims[key], context)]
        numbers, citations = number_citations([c for _, c in flat], context)
        sections: dict[str, tuple[Sentence, ...]] = {key: () for key in SECTION_KEYS}
        for (key, c), n in zip(flat, numbers, strict=True):
            sections[key] += (Sentence(c.text, c.supported, n, c.issues),)
        markdown = render_draft(
            case, sections, citations, language=language, model=client.chat_model
        )
        narrative = Narrative(
            case_id=case.case_id,
            markdown=markdown,
            generator=self.name,
            version=self.version,
            language=language,
            watermark=DRAFT_WATERMARK,
            citations=tuple(c.id for c in citations),
        )
        return NarrativeDraft(
            narrative=narrative,
            citations=tuple(citations),
            sections=sections,
            context=tuple(context),
            knowledge=status,
            dropped=dropped,
            model=client.chat_model,
            llm_calls=counted.calls,
        )

    def generate(self, case: CaseView, *, language: str = "en") -> Narrative:
        return self.draft(case, language=language).narrative


def draft_narrative(
    db: Database,
    settings: Settings,
    case_id: str,
    *,
    language: str | None = None,
    actor: str | None = None,
    llm: LLMClient | None = None,
    knowledge: Knowledge | None = None,
) -> NarrativeDraft:
    """The audited path: load the masked case, draft, check Phase 7's contract, one audit row.

    Raises `CaseError` for an unknown case and `NarrativeError` when the model fails.
    """
    lang = language or settings.assistant.answering.language
    case = load_case(db, case_id, masked=True)
    generator = LlmNarrativeGenerator(settings, llm=llm, knowledge=knowledge)
    d = generator.draft(case, language=lang)
    check_contract(d.narrative, case_id)
    every = [s for key in SECTION_KEYS for s in d.sections[key]]
    flagged = [s for s in every if not s.supported]
    validation = validation_counts(every, flagged)
    audit(
        db,
        module=answering.MODULE,
        entity_type="case",
        entity_id=case_id,
        decision="NARRATIVE_DRAFTED",
        reason=(
            f"narrative drafted: {validation['sentences']} sentence(s), "
            f"{validation['supported']} supported, {validation['unsupported']} flagged; "
            f"{len(d.context)} context item(s), {len(d.citations)} cited"
        ),
        version=NARRATIVE_PROMPT_VERSION,
        actor=actor or settings.audit.system_actor,
        details={
            "language": lang,
            "knowledge": d.knowledge,
            "context_dropped": d.dropped,
            "retrieved_ids": list(dict.fromkeys(c for e in d.context for c in e.citations)),
            "cited_ids": [c.id for c in d.citations],
            "model": d.model,
            "prompt_version": NARRATIVE_PROMPT_VERSION,
            "validation": validation,
            "flagged": flagged_details(flagged),
            "llm_calls": d.llm_calls,
            "watermark": DRAFT_WATERMARK,
        },
    )
    return d

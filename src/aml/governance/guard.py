"""A static guard: no code path of a model records a disposition, closes or clears anything.

`decision_write_violations` reads the source of every module that belongs to a model (parsed with
`ast`, never imported) and the SQL files next to them. It reports an import or call of a function
that records a human or simulated decision, a decision word that only a person may give, a SQL
write into the tables that hold decisions, and an `insert_df` into one of them. The one module
that legitimately plays the investigator, `aml.cases.labels`, is listed with its reason and not
scanned. A dynamic check (the row counts of the decision tables before and after a run of the
models) lives in the tests: a static scan cannot see a path built at run time.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ALLOWED_WRITERS",
    "FORBIDDEN_CALLS",
    "FORBIDDEN_DECISIONS",
    "SCANNED",
    "SCANNED_SQL",
    "Violation",
    "decision_write_violations",
]

SCANNED: tuple[str, ...] = (  # globs relative to src/aml
    "cases/model.py", "cases/features.py", "cases/prioritize.py", "cases/scoring.py",
    "cases/prio_store.py", "cases/btl.py", "cases/btl_model.py",
    "memo/**/*.py", "ml/**/*.py", "screening/ml/**/*.py", "governance/**/*.py",
)  # fmt: skip
SCANNED_SQL: tuple[str, ...] = (  # globs relative to the repository root
    "sql/*/cases/btl_*.sql", "sql/*/memo/**/*.sql", "sql/*/ml/**/*.sql",
    "sql/*/governance/**/*.sql",
)  # fmt: skip
ALLOWED_WRITERS: dict[str, str] = {
    "aml.cases.labels": (
        "simulates investigator dispositions from ground truth (origin SIMULATED); "
        "never reads a score"
    ),
}
FORBIDDEN_CALLS = (
    "record_disposition",
    "add_good_guys",
    "record_review",
    "simulate_dispositions",
    "run_cases",
)
FORBIDDEN_DECISIONS = (
    "SUSPICIOUS",
    "FALSE_POSITIVE",
    "TRUE_MATCH",
    "FALSE_MATCH",
    "AUTO_CLEARED",
    "CLOSED",
    "CLEARED",
    "STR_FILED",
)

_INSERT = re.compile(
    r"(?P<verb>INSERT\s+INTO)\s+"
    r"(?P<table>case_dispositions|good_guy_list|cases|case_alerts|screening_results)\b",
    re.IGNORECASE,
)
_CHANGE = re.compile(
    r"(?P<verb>UPDATE|DELETE\s+FROM)\s+"
    r"(?P<table>cases|case_alerts|case_dispositions|good_guy_list|alerts|screening_results)\b",
    re.IGNORECASE,
)
_TABLES = frozenset(
    {"cases", "case_alerts", "case_dispositions", "good_guy_list", "alerts", "screening_results"}
)


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    what: str


def _sql_writes(text: str) -> list[tuple[int, str]]:
    """``(line, "VERB table")`` of every write into a decision table found in ``text``."""
    found = []
    for pattern in (_INSERT, _CHANGE):
        for m in pattern.finditer(text):
            verb = " ".join(m.group("verb").upper().split())
            line = text.count(chr(10), 0, m.start()) + 1
            found.append((line, f"{verb} {m.group('table').lower()}"))
    return sorted(found)


def _called_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else None


def _scan_tree(tree: ast.AST, shown: str) -> list[Violation]:
    out: list[Violation] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.ImportFrom | ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] in FORBIDDEN_CALLS:
                    out.append(Violation(shown, line, f"imports {alias.name}"))
        elif isinstance(node, ast.Call):
            name = _called_name(node)
            if name in FORBIDDEN_CALLS:
                out.append(Violation(shown, line, f"calls {name}"))
            first = node.args[0] if node.args else None
            if name == "insert_df" and isinstance(first, ast.Constant) and first.value in _TABLES:
                out.append(Violation(shown, line, f"insert_df into {first.value}"))
        elif isinstance(node, ast.keyword):
            value = node.value
            if (
                node.arg == "decision"
                and isinstance(value, ast.Constant)
                and value.value in FORBIDDEN_DECISIONS
            ):
                out.append(Violation(shown, line, f"decision={value.value}"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            out += [Violation(shown, line, f"SQL {w}") for _, w in _sql_writes(node.value)]
    return out


def _module_name(path: Path, root: Path) -> str:
    return "aml." + ".".join(path.relative_to(root).with_suffix("").parts)


def _python_files(root: Path) -> list[Path]:
    files: set[Path] = set()
    for pattern in SCANNED:
        files.update(p for p in root.glob(pattern) if p.is_file())
    return sorted(p for p in files if _module_name(p, root) not in ALLOWED_WRITERS)


def _sql_files(root: Path) -> list[tuple[Path, Path]]:
    """``(file, base)`` pairs; the SQL tree sits at ``root/sql`` or, for src/aml, two levels up."""
    found: dict[Path, Path] = {}
    for base in (root, root.parent.parent):
        for pattern in SCANNED_SQL:
            for p in base.glob(pattern):
                if p.is_file():
                    found.setdefault(p.resolve(), base)
    return sorted(((Path(p), b) for p, b in found.items()), key=lambda item: str(item[0]))


def decision_write_violations(root: Path | None = None) -> list[Violation]:
    """Every place in the scanned model code that could write or imply a decision.

    ``root`` is the ``src/aml`` directory (the one of this repository by default).
    """
    root = (Path(__file__).resolve().parents[1] if root is None else Path(root)).resolve()
    violations: list[Violation] = []
    for path in _python_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations += _scan_tree(tree, path.relative_to(root).as_posix())
    for path, base in _sql_files(root):
        shown = path.relative_to(base).as_posix()
        text = path.read_text(encoding="utf-8")
        violations += [Violation(shown, line, f"SQL {w}") for line, w in _sql_writes(text)]
    return violations

"""AC3 of specs/ui-memo-relabel.md: a memo without a label gives three null columns."""

from __future__ import annotations

from typing import Any

import pytest

from tests.memo.helpers import set_memos

from .helpers import count
from .memo_helpers import KEYS12, MEMOS_URL, TXN, api_memo, tri


def test_ac3_memo_but_no_classify_run(api_mini: Any, client: Any) -> None:
    set_memos(api_mini)
    before = count(api_mini, "audit_log")
    r = client(user="analyst01").get(TXN)
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 6
    for t in data:
        assert sorted(t) == sorted(KEYS12)
        assert t["memo_key"] is None
        assert t["memo_category"] is None
        assert t["memo_method"] is None
    assert data[1]["memo"] == "Trả nợ vay bạn bè"
    assert count(api_mini, "audit_log") == before


@pytest.mark.parametrize("memo", ["Tiền cước internet", "   "])
def test_ac3_unlabelled_or_blank_memo_on_t01(api_mini: Any, client: Any, memo: str) -> None:
    api_memo(api_mini)
    api_mini.execute("UPDATE transactions SET memo = ? WHERE txn_id = 'T01'", [memo])
    before = count(api_mini, "audit_log")
    r = client(user="analyst01").get(TXN)
    assert r.status_code == 200
    t01 = r.json()["data"][0]
    assert t01["txn_id"] == "T01"
    assert t01["memo"] == memo
    assert tri(t01) == (None, None, None)
    assert count(api_mini, "audit_log") == before


def test_ac3_labels_of_another_model_are_not_mixed(api_mini: Any, client: Any) -> None:
    api_memo(api_mini)
    before = count(api_mini, "audit_log")
    c = client(user="analyst01", AML__OLLAMA__LLM_MODEL="other-model")
    r = c.get(TXN)
    assert r.status_code == 200
    for t in r.json()["data"]:
        assert tri(t) == (None, None, None)
    m = c.get(MEMOS_URL)
    assert m.status_code == 200
    assert m.json()["data"] == []
    assert m.json()["meta"]["llm_model"] == "other-model"
    assert count(api_mini, "audit_log") == before

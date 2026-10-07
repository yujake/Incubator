"""R3-⑩：领取计数的语义 —— `mine_attempts` 记的是「真抽次数」，不是排队长度。

改前：`_claim` 每次领取都 `mine_attempts += 1`，于是"这台机器没有够格的抽取器"
那一档（`run_once` 里 `extractor_is_fallback` 的拒抽）会把排队次数烧成抽取次数 ——
领满 `max_attempts` 次就判死（`processed=True`），而那一行一次都没被真抽过，
与 `run_once` 自己那句"刻意不置 processed：接线 LLM 之后这一行还要被重新领到"相反。

改后：+1 只发生在真正调用抽取器的两处（成功提交 / `extract_failed`）。
于是"从未真抽"在数据面上就是 `mine_attempts == 0` + `last_mine_error == no_llm_extractor`，
读这个数的人不会把排队次数当成抽取质量。
"""
from __future__ import annotations

from agentflow.agent_b import AgentB
from agentflow.agent_b._support import NO_EXTRACTOR_ERROR
from agentflow.llm import RuleExtractor

from conftest import add_literature, write_library_file


class _Doc:
    pages = ["An abelian group is a group in which the commutative law holds."]

    def text_at(self, lo, hi):
        return "\n".join(self.pages)


class _OkExtractor:
    """够格的替身抽取器：抽得出东西（也可能什么都不抽），但绝不抛。"""

    def extract(self, doc, lit_id, meta):
        return [], []


class _BoomExtractor:
    def extract(self, doc, lit_id, meta):
        raise RuntimeError("抽取器炸了")


def _lit(store, lid: str = "0000") -> str:
    write_library_file(store, f"{lid}/a.txt", _Doc.pages[0])
    add_literature(store, lid, title="A", path=f"{lid}/a.txt")
    return lid


def _agent(store, extractor, **cfg) -> AgentB:
    config = {"lease_seconds": 900, "max_attempts": 3}
    config.update(cfg)
    return AgentB(store, extractor=extractor, extract_text=lambda p, **k: _Doc(), config=config)


def _row(store, lid: str = "0000") -> dict:
    return dict(store.rows("literature")[0] if lid == "0000"
                else next(r for r in store.rows("literature") if r["lit_id"] == lid))


def _expire_lease(store, lid: str = "0000") -> None:
    """模拟"时间过去了"：把退避租约清掉，否则第二轮就被租约挡住，什么也测不到。"""
    with store.tx("literature", actor="test") as tx:
        row = tx.find("literature", lit_id=lid)
        row["lease_until"] = None
        tx.upsert("literature", row, note="clear_lease")


# --------------------------------------------------------------------- 正控（真的抽了）

def test_a_successful_extraction_burns_exactly_one_attempt(store):
    _lit(store)
    res = _agent(store, _OkExtractor()).run_once()

    row = _row(store)
    assert res.processed == 1, res.to_dict()
    assert row["processed"] is True
    assert int(row.get("mine_attempts") or 0) == 1, (
        f"真抽过一轮 ⇒ 计数必须是 1（计数点在抽取器那一步）：{row}"
    )
    assert row.get("last_mine_error") is None, row


def test_a_failed_extraction_burns_exactly_one_attempt(store):
    _lit(store)
    res = _agent(store, _BoomExtractor()).run_once()

    row = _row(store)
    assert res.failed == 1, res.to_dict()
    assert row["processed"] is False, "抽取失败不许置 processed（原因留着，改完再来）"
    assert int(row.get("mine_attempts") or 0) == 1, (
        f"抽了但炸了 ⇒ 也要计一次（它确实真抽过）：{row}"
    )
    assert "RuntimeError" in str(row.get("last_mine_error")), row


# ------------------------------------------------------- 负控（从未真抽：不烧、不判死）

def test_negative_control_no_extractor_never_burns_attempts_nor_is_judged_dead(store):
    """本机没有够格的抽取器 ⇒ 领 5 轮：计数恒为 0、不判死、每一轮都如实记原因。

    改前红：领满 3 轮就被判死（`processed=True` + `_give_up_note` 里那句"从未真抽"），
    于是接线 LLM 之后这一行再也领不到 —— 那句结论说得没错，但处置是错的。
    """
    _lit(store)
    b = _agent(store, RuleExtractor())
    assert b.extractor_is_fallback is True, "这条判据的前提：规则回退抽取器必须被判成拒抽"

    for i in range(5):
        res = b.run_once()
        row = _row(store)
        assert res.skipped_no_extractor == 1, (i, res.to_dict())
        assert row["processed"] is False, f"第 {i + 1} 轮就被判死了：{row}"
        assert int(row.get("mine_attempts") or 0) == 0, (
            f"第 {i + 1} 轮把排队次数烧成了抽取次数：{row}"
        )
        assert row.get("last_mine_error") == NO_EXTRACTOR_ERROR, row
        assert row.get("lease_until"), "退避租约要在（否则同一趟里会被反复重领）"
        _expire_lease(store)

    assert res.details and res.details[-1]["skipped"] == NO_EXTRACTOR_ERROR, res.details[-1]

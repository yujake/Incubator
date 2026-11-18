# -*- coding: utf-8 -*-
"""判据：稿与计划的生命周期只有一份三态读数（K1/K2 的 c 条）。

## 业主口径（2026-11-18，逐字）

```text
稿与计划的生命周期：显式三态 = 活跃 / 完工 / 放弃
 · 完工 = 拿到 V 签 ⇒ 冻结只读
 · 放弃 = 该稿号或计划号已放弃 ⇒ 从活跃集踢出（可物理踢出）
 · 唯一判据入口：只看活跃集；其他判据不得各自写 `if abandoned: continue`
```

## 判据

| # | 判据 | 改前红在哪 |
|---|---|---|
| a | 计划六个原始状态各落一档：`open`/`attacking`=活跃，`resolved`/`stalled`/`supported_not_proved`=完工，`abandoned`=放弃（六档闭集、每档恰有一个三态） | 改前没有三态：四处各写一份 `status not in TERMINAL_STATUSES` |
| b | 「放弃」不在活跃集；负控「完工」也不在活跃集 | 改前只有一份「终态」名单，没有「活跃集」这个读数 |
| c | 反真空：把三态映射打桩成「全是活跃」⇒ b 的红必须出现（活跃集把放弃/完工都收进来） | —— |
| d | 稿的三态：未签=活跃；拿到 V 签=完工（冻结）+只读；所属命题退休=放弃（放弃压过完工） | 改前只有 `freeze_reading` / `retire_reading` 两份读数，没有统一三态 |
| e | 状态判不了（不在 `ATTACK_STATUSES` 里的字面量）⇒ `checked=False` 且不进活跃集 | 改前 `status not in TERMINAL` 会把它当活跃 |

## 边界

全部 `tmp_path` 工作区；不读写 `projects/`；不跑全量。判据只读盘上两份既有读数
（`manuscriptfreeze` / `manuscriptretire`），`lifecycle` 自己不写盘。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import _credential_fixture as CF
import conftest
from agentflow import lifecycle as L
from agentflow import manuscriptfreeze as FZ
from agentflow.store import Store

BUDGET = {"max_rounds": 3, "max_parallel_subgoals": 2,
          "max_persist_attempts": 2, "max_depth": 2}

#: 一份最小手稿（`manuscriptfreeze` 只按正文 sha 与颁发表判，不解析三节结构）。
REL = "reports/f-proof-000000.md"
BODY = "第一版正文：由定义直接得到。"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _seed_plan(st: Store, *, pid: str, status: str, key: str,
               owner: str = "agent-F-F1") -> None:
    with st.tx("attack_plans", actor="test") as tx:
        tx.upsert("attack_plans", {
            "plan_id": pid, "problem": f"难题 {key}", "problem_key": key,
            "status": status, "rounds": 0, "budget": dict(BUDGET),
            "subgoals": [], "history": [], "depth": 0,
            "best_partial": ("停下来时的最好部分结果" if status == "stalled" else ""),
            "created_by": owner,
        })


# ============================================================ a：六档折三态
@pytest.mark.parametrize("status,state", [
    ("open", L.ACTIVE),
    ("attacking", L.ACTIVE),
    ("resolved", L.COMPLETED),
    ("stalled", L.COMPLETED),
    ("supported_not_proved", L.COMPLETED),
    ("abandoned", L.ABANDONED),
])
def test_a_every_plan_status_lands_in_exactly_one_of_the_three_states(
        status: str, state: str) -> None:
    """a 判据：六个原始状态各落一档（闭集；没有「第四档」也没有掉出来的）。"""
    got = L.state_of_plan({"plan_id": "000001", "status": status})
    assert got["checked"] is True, got
    assert got["state"] == state, got
    assert got["raw"] == status, got
    assert got["kind"] == "plan", got
    assert state in L.STATES


# ============================================================ b：活跃集
def test_b_abandoned_and_completed_are_both_out_of_the_active_set(
        tmp_path: pathlib.Path) -> None:
    """b 判据：活跃集只含活跃；放弃不在，完工也不在（负控）。"""
    st = _ws(tmp_path)
    for i, status in enumerate(("open", "attacking", "resolved", "stalled",
                                "supported_not_proved", "abandoned")):
        _seed_plan(st, pid=f"00000{i}", status=status, key=f"PK-{i}")

    got = L.active_plans(st)
    assert got["checked"] is True, got
    assert got["total"] == 6, got
    assert got["active"] == 2, got
    assert got["ids"] == ["000000", "000001"], got
    assert "000005" not in got["ids"], "放弃的必须不在活跃集"
    assert "000002" not in got["ids"], "完工的必须不在活跃集（负控）"
    assert {r["plan_id"] for r in got["rows"]} == {"000000", "000001"}

    # 单行读数与集合读数必须是同一份判据。
    assert L.plan_is_active({"status": "open"}) is True
    assert L.plan_is_active({"status": "abandoned"}) is False
    assert L.plan_is_active({"status": "resolved"}) is False

    # 分桶：别人名下的计划不进来。
    mine = L.active_plans(st, owner="agent-F-F1")
    other = L.active_plans(st, owner="agent-F-F2")
    assert mine["active"] == 2 and other["active"] == 0, (mine, other)


# ============================================================ c：反真空
def test_c_stubbing_the_mapping_to_all_active_turns_b_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c 判据（反真空）：三态映射打桩成「全是活跃」⇒ 活跃集必须把放弃/完工收进来。

    证明 b 的绿来自「放弃 / 完工」真的被折出活跃集，而不是来自 `active_plans`
    恰好没读到那几行。
    """
    st = _ws(tmp_path)
    _seed_plan(st, pid="000001", status="abandoned", key="PK-C1")
    _seed_plan(st, pid="000002", status="resolved", key="PK-C2")
    monkeypatch.setattr(L, "PLAN_STATE_OF",
                        {s: L.ACTIVE for s in L.PLAN_STATE_OF})
    got = L.active_plans(st)
    assert got["active"] == 2, (
        "打桩成「全是活跃」之后活跃集仍有 2 条 ⇒ c 没有压住 b", got)
    assert set(got["ids"]) == {"000001", "000002"}, got


# ============================================================ d：稿的三态
def test_d_a_manuscript_is_active_until_signed_and_completed_after_the_sign(
        tmp_path: pathlib.Path) -> None:
    """d 判据：未签=活跃；拿到 V 签=完工（冻结只读）；退休=放弃（放弃压过完工）。"""
    st = _ws(tmp_path)
    target = pathlib.Path(st.root) / REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# F 的证明手稿：夹具\n\n## 命题\n\n夹具命题。\n\n"
                      "## 证明\n\n" + BODY + "\n", encoding="utf-8")

    unsigned = L.state_of_manuscript(st, REL)
    assert unsigned["checked"] is True, unsigned
    assert unsigned["state"] == L.ACTIVE, unsigned
    assert FZ.freeze_reading(st.root, REL)["state"] == "unsigned"

    # 拿到 V 签（签块与颁发表都用既有夹具；完工程序判据仍是 `manuscriptfreeze`）。
    CF.issue_credential(st.root, proof_text=BODY, statement_id="",
                        manuscript=REL, artifact_path=REL)
    signed = L.state_of_manuscript(st, REL)
    assert signed["state"] == L.COMPLETED, signed
    assert signed["sign_state"] in ("signed", "edited_after_sign"), signed
    assert FZ.freeze_reading(st.root, REL)["frozen"] is True

    # 所属命题退休 ⇒ 放弃压过完工。
    conftest.seed_statement_row(
        st, statement_full="夹具命题。", kind="conjecture", status="abandoned",
        quote_reason="abandoned@2026-11-18T00:00:00+08:00@夹具：放弃这条命题",
        manuscript_id=REL, manuscripts={"1": REL})
    retired = L.state_of_manuscript(st, REL)
    assert retired["state"] == L.ABANDONED, retired
    assert retired["retired"] is True, retired
    assert retired["state"] != L.ACTIVE


# ============================================================ e：判不了不进活跃集
def test_e_an_unknown_status_is_unjudged_and_never_counted_as_active(
        tmp_path: pathlib.Path) -> None:
    """e 判据：不认识的计划状态 ⇒ `checked=False`，不进活跃集（也不折成完工）。

    改前红：`status not in TERMINAL_STATUSES` 会把它当成活跃计划。
    """
    assert L.state_of_plan({"plan_id": "x", "status": "半死不活"})["checked"] is False

    class _Rows:
        root = ""

        @staticmethod
        def rows(table: str) -> list[dict]:  # noqa: ARG004
            return [{"plan_id": "000001", "status": "open"},
                    {"plan_id": "000002", "status": "半死不活"}]

    got = L.active_plans(_Rows())
    assert got["checked"] is True, got
    assert got["active"] == 1 and got["ids"] == ["000001"], got
    assert [r["plan_id"] for r in got["unjudged"]] == ["000002"], got
    assert "判不了" in str(got["unjudged"][0]["why"]), got


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))

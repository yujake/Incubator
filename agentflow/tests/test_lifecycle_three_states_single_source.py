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
| f | 命题面（`STATEMENT_STATUSES`）也走同一入口：活跃三档 / `superseded`=完工 / 其余（放弃 + 错误那一档）=放弃；未知状态 ⇒ `checked=False` | 改前命题面只有原始 status，没有三态；`closing` 三处各写 `status == "abandoned"`（FIX186-A） |
| g | 静态判据：读数面（`closing.py` / `agent_loop.py`）不许再出现与 `"abandoned"` 的字面比较；全树新增一处即红 | 改前 `agent_loop.py:4890` 与 `closing.py:5688/:5929/:6157` 各写一遍 |
| h | 三类读数各带一格 `lifecycle_state`（计划 `list_plans` / 稿 `flow_reading` / 命题 `statement_review_reading`），原始 `status` 仍在 | 改前读数只有原始 status，网页/CLI 各印各的 |

## 边界

全部 `tmp_path` 工作区；不读写 `projects/`；不跑全量。判据只读盘上两份既有读数
（`manuscriptfreeze` / `manuscriptretire`），`lifecycle` 自己不写盘。
"""
from __future__ import annotations

import ast
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


# ============================================================ f：命题面同一入口
def test_f_every_statement_status_lands_in_exactly_one_of_the_three_states() -> None:
    """f 判据：命题面的每一个状态都落一档；放弃那一档是词表的补集（含错误那一档）。

    改前红：命题面没有三态，`closing` 的三处各自写 `status == "abandoned"`。
    """
    from agentflow import errorstate as ES
    from agentflow import schema as S

    retired = {"abandoned", *ES.ERROR_WORDS}
    for status in S.STATEMENT_STATUSES:
        got = L.state_of_statement({"stmt_id": "000001", "status": status})
        assert got["checked"] is True, (status, got)
        assert got["raw"] == status and got["kind"] == "statement", got
        if status in retired:
            assert got["state"] == L.ABANDONED, (status, got)
        elif status == "superseded":
            assert got["state"] == L.COMPLETED, (status, got)
        else:
            assert got["state"] == L.ACTIVE, (status, got)
    # 错误那一档与「放弃」同档（两词都在词表里时各读一次，两个都必须读成放弃）。
    for word in ES.ERROR_WORDS:
        assert L.state_of_statement({"status": word})["state"] == L.ABANDONED, word
    # 判不了：不折成活跃，也不折成放弃。
    unknown = L.state_of_statement({"stmt_id": "x", "status": "半死不活"})
    assert unknown["checked"] is False and unknown["state"] == "", unknown
    assert L.statement_is_active({"status": "active"}) is True
    assert L.statement_is_active({"status": "abandoned"}) is False


def test_f2_stubbing_the_statement_mapping_turns_the_abandoned_row_active(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """f-反真空：把命题三态映射打桩成「全是活跃」⇒ 放弃的行必须被读成活跃。

    证明 f 的「放弃」读得对不是因为它恰好没读到那一行。
    """
    monkeypatch.setattr(L, "STATEMENT_STATE_OF",
                        {s: L.ACTIVE for s in L.STATEMENT_STATE_OF})
    got = L.state_of_statement({"stmt_id": "000006", "status": "abandoned"})
    assert got["state"] == L.ACTIVE, got


# ============================================================ g：静态判据（不许各写名单）
#: 除 `lifecycle.py` 外仍合法出现 `"abandoned"` 字面比较的地方（逐条写理由）。
#:
#: 它们都不是「它还占不占活跃集」这一问：要么在写/标记那一侧，要么在解析
#: 放弃标记本身。`lifecycle` 是唯一的三态入口 —— 读数面（`closing.py` /
#: `agent_loop.py`）一个都不许留。新增一条 = 又长出一个三态判据的落位 ⇒ 本判据红。
_ABANDONED_LITERALS_OUTSIDE_LIFECYCLE: dict[str, str] = {
    "agent_f/delivery.py": "F 的交付读数：解析 `abandoned@<时间>@<理由>` 标记（三样缺一不可）",
    "obligations.py": "义务读数：放弃不算欠、放弃要留理由 —— 按标记读，不是三态入口",
    "researchpending.py": "待办清单排除已放弃的研究问题（那一列没有 lifecycle 映射）",
    "schema.py": "`Statement.validate` 的单行内判据：abandoned 必须带 quote_reason",
    "secretary.py": "放弃动作的写侧：改 status 之前先判「本来就是 abandoned 吗」（幂等）",
    "statementabandon.py": "放弃标记的解析/生成本体（`abandoned@…` 就是它的词）",
    "statementrefute.py": "错误 / 放弃两条终态的读侧分派（先看标记再看凭据）",
    "tools/table_tools.py": "`table.create` 的放弃动作路由：只有 status=abandoned 才转给秘书",
    "vsigns.py": "签侧：命题已放弃 ⇒ 不再要签（按标记读，不是活跃集判据）",
}


def _abandoned_compare_files(root: pathlib.Path) -> dict[str, int]:
    """扫出（仓库相对路径 → 与 `"abandoned"` 字面比较的节点数）。纯函数，可喂负控。"""
    import warnings

    out: dict[str, int] = {}
    for path in sorted(root.rglob("*.py")):
        with warnings.catch_warnings():
            # 别的模块里的旧转义序列会在这里报 DeprecationWarning（与判据无关）。
            warnings.simplefilter("ignore", DeprecationWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"))
        hits = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            for side in (node.left, *node.comparators):
                if isinstance(side, ast.Constant) and side.value == "abandoned":
                    hits += 1
        if hits:
            out[str(path.relative_to(root)).replace("\\", "/")] = hits
    return out


def test_g_the_read_side_never_compares_the_abandoned_word_itself() -> None:
    """g 判据：读数面必须调 `lifecycle`，不许再自写一份「还活着吗」。

    改前红：`closing.py:5688/:5929/:6157` 与 `agent_loop.py:4890` 各写一遍
    `status == "abandoned"`；四份名单今天恰好相等 ⇒ 没有任何判据会红。
    """
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"
    found = _abandoned_compare_files(src)
    read_side = {name for name in found
                 if name in ("closing.py", "agent_loop.py")
                 or name.startswith("agent_f/") and name != "agent_f/delivery.py"}
    assert not read_side, (
        "读数面又自己判放弃了（应调 `lifecycle.state_of_plan` / `state_of_statement`）："
        f"{sorted(read_side)}")
    assert "lifecycle.py" not in found, "三态映射本体不该再写一套字面比较"
    # 全树防火墙：新增一处就必须先在这里登记理由（否则三态入口又被绕开）。
    unexpected = {name: hits for name, hits in found.items()
                  if name not in _ABANDONED_LITERALS_OUTSIDE_LIFECYCLE}
    assert not unexpected, (
        "这些文件新出现了与 `\"abandoned\"` 的字面比较（要么改成调 lifecycle，"
        f"要么在 _ABANDONED_LITERALS_OUTSIDE_LIFECYCLE 里逐条写明为什么它不是三态判据）："
        f"{unexpected}")
    stale = set(_ABANDONED_LITERALS_OUTSIDE_LIFECYCLE) - set(found)
    assert not stale, f"豁免表里有已经不再需要豁免的文件（应删掉）：{sorted(stale)}"


def test_g2_the_scanner_has_teeth(tmp_path: pathlib.Path) -> None:
    """g-反真空：往一个假树里放一处 `== "abandoned"` ⇒ 扫描器必须报出来。"""
    bad = tmp_path / "pkg"
    bad.mkdir()
    (bad / "reader.py").write_text(
        "def f(row):\n    return row.get('status') == 'abandoned'\n", encoding="utf-8")
    assert _abandoned_compare_files(tmp_path) == {"pkg/reader.py": 1}


# ============================================================ h：三类读数各带 lifecycle_state
def test_h_plan_manuscript_and_statement_readings_carry_the_three_state(
        tmp_path: pathlib.Path) -> None:
    """h 判据：三类读数各有一格 `lifecycle_state`，原始 `status` 仍在（审计面）。

    改前红：计划 / 稿 / 命题的读数只有原始 status（或什么都没有），网页与 CLI
    各印各的字符串 —— 同一个「放弃」在三处三种说法。
    """
    from agentflow import verifications as VR
    from agentflow.agent_f import AgentF

    st = _ws(tmp_path)
    _seed_plan(st, pid="000001", status="abandoned", key="PK-H")
    plans = AgentF(st).list_plans()
    assert plans["plans"][0]["status"] == "abandoned", plans          # 原始值保留
    assert plans["plans"][0]["lifecycle_state"] == L.ABANDONED, plans

    target = pathlib.Path(st.root) / REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# F 的证明手稿：夹具\n\n## 命题\n\n夹具命题。\n\n"
                      "## 证明\n\n" + BODY + "\n", encoding="utf-8")
    from agentflow import manuscriptretire as MR

    flow = MR.flow_reading(st, rel=REL)
    assert flow["lifecycle_state"] == L.ACTIVE, flow

    row = conftest.seed_statement_row(
        st, statement_full="夹具命题。", kind="conjecture", status="abandoned",
        quote_reason="abandoned@2026-11-18T00:00:00+08:00@夹具：放弃这条命题")
    reading = VR.statement_review_reading(st.root, row)
    assert reading["lifecycle_state"] == L.ABANDONED, reading


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))

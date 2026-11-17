# -*- coding: utf-8 -*-
"""「必须收录」义务的写侧键与读侧查找必须落在同一个号段（FIX11，R1）。

## 现场（RED11 取证，`temp/red11/REPORT-RED11.md` §1③）

SGN1（`a30844ef`）给"未在册的签"开的义务是 `b-register@<稿号>@<sha>`：
写侧「号从稿名读」（`verifications.registration_after_unregistered_sign`），
读侧 `obligations.registration_gap` 却按命题号去 `statements` 里 `by_id(stmt_id=…)`。
而 2026-11-13 裁定已经让稿号与命题号分家（`agent_b/register_statement.py:5402-5409`
逐字「稿名里的号是产出侧自己的号段，与命题号是两个号段，不能当候选」）。

⇒ 同一行、同一份 sha，只换 label：`000002#p1` 读成「没入库」、`000000#p1` 读成「已入库」
⇒ 义务永远收不了口 ⇒ `retire_child` 被拒（"名下还有 1 条未消的板项"）⇒ final 被拒
（rc=5 `final_refused`）⇒ M 多跑 3 拍补救（19 次真调用，健康基线是 16）。

## 这一组的判据（对应任务书的 a / b / c）

| # | 造什么 | 期望 |
|---|---|---|
| a | 未在册的签落地（义务开）→ B 收录（行上 `manuscript_id` + `manuscripts` 记着这份稿） | `settle_registration` 在收录那一刻把它收口成 `done`，`adopted_key` 是新命题号的键；销号门不再看见它 |
| a' | 静态：收录的写点真的会调它（`ingest_manuscript` 的两个出口） | 有调用；摘掉 ⇒ 这条红（写点不是"等人想起来"） |
| b | 同一行同一 sha：按稿号问、按命题号问、给稿路径问 | 三问同一结论（`gap=False`）且 `resolved_statement_id` 同一个；两个号段撞车 ⇒ fail-closed 判「判不了」（不许猜，也不许假收口） |
| c | 反真空：把「按稿路径认这一份」那一笔打掉 | a 必红：义务开不出去也收不回来，同一条 CLI 彩排回到 `rc=5` / `final_refused` |

零模型调用：义务用真写侧（`registration_after_unregistered_sign`）开，收录那一行用夹具铺
（`conftest.seed_statement_row`，与真收录落成后的行同形：`stmt_id` / `manuscript_id` /
`manuscripts` / 正文 / `bits.reviewed`）；彩排那一条只换出网层。
"""
from __future__ import annotations

import ast
import pathlib

from agentflow import obligations as OBL
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.store import Store
from agentflow.tools.conductor_tools import conductor_for

from conftest import seed_statement_row

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"

#: 未在册那一支的稿号（真机 lp-ball-5 / RC2 彩排同一个形态：稿号 000002、命题号 000000）。
MID = "000002"
#: B 收录之后秘书发的命题号（与稿号不同 —— 这正是 11-13 裁定的形状）。
SID = "000000"
REL = f"reports/f-proof-{MID}.md"
SHA = "ccf680d50dfc88edd2f9b02720f31a9d640f369ad712c1538240e52aff48eb07"
FULL = "设 a = 1/√2；则对任意单位向量 n，截面面积 A_n(t) ≤ 2a²。"
BODY = "1. 先按齐次缩放化到 a=1。\n2. 由 Brunn 凹性，最大值在中心截面。"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    path = pathlib.Path(st.root) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# F 的证明手稿\n\n## 命题\n\n{FULL}\n\n## 证明\n\n{BODY}\n",
                    encoding="utf-8")
    return st


def _b_task(st: Store) -> str:
    """落一条 B 的台账号：义务要挂在某个可接的 B 名下（真机形态）。"""
    from agentflow.conductor import Conductor

    return Conductor._write_new_row(conductor_for(st), {
        "task_id": "", "role": "B", "action": "", "called_by": "M",
        "parent_task_id": "t-root", "depth": 2, "input_key": "@t:B:running",
        "status": "running", "outcome": None, "refusal_reason": None,
        "instance": "B#1", "detail": "夹具", "error": None,
        "started_at": "2026-11-17T16:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="probe:agent")


def _open_duty(st: Store) -> dict:
    """真写侧：未在册的签落地 ⇒ 开一条「必须收录」义务（SGN1 那一笔）。"""
    return VR.registration_after_unregistered_sign(
        store=st, root=st.root, manuscript=REL, sha=SHA,
        at="2026-11-17T23:37:07+08:00")


def _items(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("tasks")
            if str(r.get("input_key") or "").startswith(OBL.REGISTER_PREFIX)]


#: 收录之后那一行的 `bits`（抄 RC2 彩排盘上那一行 `temp/red11/base*/ws/data/statements.json`：
#: 只把与"收录完了没有"无关的格留成同一个形状 —— `proof` 要带过程、`reviewed` 要带凭据，
#: 这两条是 `evidencebits.bit_problems` 的硬判据，不是本判据要测的东西）。
BITS = {
    "numeric": "pending", "proof": True, "reviewed": True, "formal": "pending",
    "audited": False, "origin": "own_result", "grade": "pre_theorem",
    "audited_badge": False, "voided_by": {},
    "evidence": {
        "numeric": {}, "numeric_reason": "",
        "proof_process": BODY, "proof_source": "own",
        "reviewed_by": {"verifier": "V", "verification_id": "u-000003",
                        "verdict": "成立", "proof_no": 1,
                        "proof_sha256": SHA, "findings": [],
                        "evidence": "verifications/pending/x.jsonl#u-000003"},
        "reviewed_source": "", "formal": {}, "formal_reason": "", "audited_by": {},
        "reviewed_by_proof": {"1": True},
        "reviewed_sha_by_proof": {"1": SHA},
        "optimized_by_proof": {"1": False},
    },
}


def _registered(st: Store) -> dict:
    """B 收录落成之后的那一行（与真收录同形：两处记录这份稿 + 正文 + reviewed）。"""
    return seed_statement_row(
        st, stmt_id=SID, statement_full=FULL, proof_text=BODY, kind="theorem",
        label="截面面积上界", manuscript_id=MID, manuscripts={"1": REL},
        bits=dict(BITS))


# ============================================================ a 收录那一刻收口
def test_a_the_duty_is_settled_at_the_moment_b_registers(tmp_path: pathlib.Path) -> None:
    """a：义务开 → 收录 → 义务收口（并且在收录那一刻，不是等收工对账）。"""
    st = _ws(tmp_path)
    b_task = _b_task(st)
    opened = _open_duty(st)
    assert opened.get("state") == "opened", opened
    items = _items(st)
    assert len(items) == 1, [r.get("input_key") for r in items]
    key = str(items[0]["input_key"])
    # 写侧仍然按「稿号」建键（SGN1 的形状不重裁）：键里那个号是稿号 000002。
    assert key == OBL.register_key(f"{MID}#p1", SHA), key
    assert str(items[0].get("parent_task_id")) == b_task, items[0]
    # 收录之前：读侧说「这一份还没入库」，销号门看得见它。
    before = OBL.registration_gap(store=st, label=f"{MID}#p1", manuscript=REL)
    assert before["checked"] is True and before["gap"] is True, before
    assert len(conductor_for(st).open_items_of(b_task)) == 1

    row = _registered(st)
    assert str(row.get("stmt_id")) == SID and str(row.get("manuscript_id")) == MID
    settled = OBL.settle_registration(store=st, root=st.root, stmt_id=SID,
                                      manuscript=REL)
    assert settled["checked"] is True, settled
    assert [one["item_id"] for one in settled["settled"]] == [items[0]["task_id"]], settled
    # 键迁到新命题号：收口读数里逐字记着"从哪个键迁到哪个键"。
    assert settled["settled"][0]["adopted_key"] == OBL.register_key(f"{SID}#p1", SHA), settled
    assert settled["settled"][0]["key"] == key, settled
    after = _items(st)
    assert str(after[0]["item_state"]) == "done", after
    assert str(after[0].get("item_close")) == "completed", after
    # 销号门看不到它了；两个读侧（digest / 对账）也读到"没有开着的"。
    assert conductor_for(st).open_items_of(b_task) == [], conductor_for(st).open_items_of(b_task)
    assert OBL.registration_digest(st.root, st)["open"] == 0
    assert OBL.reconcile_registrations(store=st, root=st.root)["left"] == []
    # 幂等：重放一次收录（同一条命令再跑一遍）⇒ 零写入、没有第二条义务。
    again = OBL.settle_registration(store=st, root=st.root, stmt_id=SID, manuscript=REL)
    assert again["settled"] == [] and again["left"] == [], again
    assert len(_items(st)) == 1, [r.get("input_key") for r in _items(st)]


def _calls_attr(fn: ast.AST, attr: str) -> bool:
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == attr for n in ast.walk(fn))


def test_a_prime_the_write_points_call_the_settlement() -> None:
    """a'：收录的写点都调它（静态）——「收录时消账」不是一句承诺，是一个调用。

    落点在 `_mark_ingested`：`ingest_manuscript` 的两个出口（`mode=register` 与按格回填）
    都从它过，所以钉"两个出口"就是钉"两条分支都到得了这一格"（`ingest_manuscript` 里
    两次 `self._mark_ingested(...)`）。
    """
    tree = ast.parse((SRC / "agentflow" / "agent_b" / "ingest_manuscript.py")
                     .read_text(encoding="utf-8"))
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert _calls_attr(fns["_mark_ingested"], "_settle_registration_duty"), (
        "收录落成之后没有调消账那一格 —— 义务又只能等收工对账（RED11 的就是这一档）")
    entry = fns["ingest_manuscript"]
    assert sum(1 for n in ast.walk(entry)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "_mark_ingested") >= 2, (
        "`ingest_manuscript` 的两个出口不再是同一个漏斗 ⇒ 有一条分支收不了口")
    # 反真空（静态那一半）：检测器认得出"没调"的那一版形态。
    sample = ast.parse('def f(self, out):\n    return out\n')
    assert not _calls_attr(sample.body[0], "_settle_registration_duty")


# ============================================================ b 两个号段同一结论
def test_b_both_numbers_give_the_same_verdict_for_the_same_row(
        tmp_path: pathlib.Path) -> None:
    """b：同一行同一 sha，按稿号 / 按命题号 / 给稿路径问 ⇒ 同一结论，不再二义。"""
    st = _ws(tmp_path)
    _registered(st)
    by_stmt = OBL.registration_gap(store=st, label=f"{SID}#p1")
    by_ms = OBL.registration_gap(store=st, label=f"{MID}#p1")
    by_path = OBL.registration_gap(store=st, label=f"{MID}#p1", manuscript=REL)
    for got in (by_stmt, by_ms, by_path):
        assert got["checked"] is True, got
        assert got["gap"] is False, got
        assert got["resolved_statement_id"] == SID, got
        assert got["body"] is True and got["reviewed"] is True, got
    # 读数里看得见"这一问走的是哪个号段"（口径不是靠猜的）。
    assert by_stmt["matched_by"] == "statement_id", by_stmt
    assert by_ms["matched_by"] == "manuscript_id", by_ms
    assert by_path["matched_by"] == "manuscript_id", by_path

    # 两个号段撞车（`statements` 里真有一条 stmt_id == 稿号的行）：
    # 只给号 ⇒ 判不了（fail-closed，不许拿别人的行冒充"已收录"）；
    # 给稿路径 ⇒ 那一份稿的归属是确定的，按它读。
    seed_statement_row(st, stmt_id=MID, statement_full="另一条命题（号段撞车）。",
                       kind="theorem", label="撞车")
    ambiguous = OBL.registration_gap(store=st, label=f"{MID}#p1")
    assert ambiguous["checked"] is True, ambiguous
    assert ambiguous["gap"] is True, ("两个号段都命中却还判成'已收录' ⇒ 拿别人的行冒充了",
                                      ambiguous)
    assert ambiguous["matched_by"] == "ambiguous", ambiguous
    assert "两个号段" in str(ambiguous["reason"]), ambiguous
    still = OBL.registration_gap(store=st, label=f"{MID}#p1", manuscript=REL)
    assert still["checked"] is True and still["gap"] is False, still
    assert still["resolved_statement_id"] == SID, still


# ============================================================ c 反真空
def test_c_without_the_manuscript_claim_the_duty_and_the_chain_go_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """c：把「按稿路径认这一份」那一笔打掉 ⇒ a 的红回来（同一条 CLI 彩排 rc=5）。"""
    import test_rehearsal_cli_proof_main_chain as CHAIN

    # ---- 单元那一半：认领打掉之后，同一行按稿号问 ⇒ 又变成「没入库」。
    st = _ws(tmp_path / "unit")
    _registered(st)
    assert OBL.registration_gap(store=st, label=f"{MID}#p1")["gap"] is False
    monkeypatch.setattr(OBL, "_manuscript_owner_row", lambda **__: {
        "checked": True, "found": False, "stmt_id": "",
        "why": "反真空：按稿号/稿路径认领那一笔被摘掉了"})
    again = OBL.registration_gap(store=st, label=f"{MID}#p1")
    assert again["gap"] is True, ("认领那一笔摘掉了，义务却还是收得回来 ⇒ 这条反真空"
                                  "打到的不是那个写口", again)
    # 收口那一笔也收不动：义务留在板上。
    _b_task(st)
    _open_duty(st)
    settled = OBL.settle_registration(store=st, root=st.root, stmt_id=SID, manuscript=REL)
    assert settled["settled"] == [], settled
    assert [str(r.get("item_state")) for r in _items(st)] != ["done"], _items(st)

    # ---- 链那一半：同一条彩排（只换出网层）回到 rc=5 / final_refused。
    got = CHAIN._run(tmp_path / "chain", monkeypatch, lean="0")
    assert got["rc"] == 5, (got["rc"], got["stdout"][-800:])
    run = pathlib.Path(got["ws"]) / "runs" / "agent-M-rc2-main-chain.json"
    import json

    assert str(json.loads(run.read_text(encoding="utf-8")).get("stop_reason")) == \
        "final_refused", run
    items = _items(Store(got["ws"]))
    assert [str(r.get("item_state")) for r in items] == ["seen"], (
        "认领那一笔摘掉之后，板上那条义务必须还开着（否则这条反真空测的不是它）", items)

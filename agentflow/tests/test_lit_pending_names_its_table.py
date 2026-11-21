# -*- coding: utf-8 -*-
"""判据：收工门第八格必须点名它读的是哪张表，M 的派活文案不许再把二阶段读成"禁止洗"。

## 改前为什么红（先查原因：真机 `projects/lp-ball-14`，MINE14 报告的 P0-2 与 ⑦）

这一格报 `fail` 时，读数只有「全表还有 24 条待裁（跨 4 个委托）：…」—— 两个表名一个都
不出现。现场的连锁是：

- 门数的是 `lit_candidates` 的 24 条 `pending`（r-000011:15 / r-000012:2 / r-000013:4 /
  r-000014:3，全由 A2 的 `t-000101` 在 01:38:31–01:43:46 认领后只搜不裁）；
- M 在 `out/review/REPORT.md:59` 把它写成「lit 000001–000005 无本地全文」—— 那是
  `literature` 表的 5 行（B 的消化面，另一条队列）；
- 于是 M 派 B2 去改那 5 行的下载判档（`table.update` `download.fulltext=metadata_only`）：
  候选一行没动，这一格一格没变。

同一趟的次生问题：M 三次派活都显式 forbid 洗稿（它读的是 M 政策里那句「不要让 B 去润色
F 的证明」），而 B 今天的主职就是二阶段（洗稿 → 重拿 V 签 → 精准替换）⇒ 读数在
（`statements_unoptimized=2`、17 条 `optimized=not_recorded`）而动作没发生
（`open_polish_copy` 0 次），B 的回执自认「第二阶段未做」。

## 判据（正控 / 反真空）

| # | 判据 | 反真空（把旧文案塞回 ⇒ 必红） |
|---|---|---|
| a | 候选有 pending、而 `literature` 全 processed 的夹具 ⇒ 这一格的读数点名 `lit_candidates` + 逐委托 ids + 出口（`lit.admit` / `lit.stage_reject` / 逐委托 `lit.admit_all`），并把 `literature.processed` 单独点名、写明改它没用 | 改前的模糊原话（`OLD_VAGUE_REASON`）喂回同一个检查 ⇒ 必须报缺 |
| b | M 的可见面（政策 + 手册 + 收工门读数）里有「两张表各自的出口」，而且只有一份措辞（真身 `closing.LITERATURE_QUEUES_NOTE`；手册只指路、不抄第二份） | 把那一句从政策里摘掉 ⇒ b 必红；手册里塞一份手写副本 ⇒ 也红 |
| c | M 的派活文案不再禁止 B 做二阶段（旧句「不要让 B 去润色 F 的证明」已不在），但仍要求洗完重拿 V 签（界线是签，不是洗） | 把那句旧文案逐字塞回 ⇒ c 必红；把整段责任路由删掉 ⇒ 也红 |

判据读的两个面都是真身：收工门走 `closing.check_closing`，文案走 `specs/m.py` 的
`brief.policy`（逐字进提示词）与 `agent_skills` 的 M 手册正文。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import agent_prompts as AP
from agentflow import agent_skills as SK
from agentflow import closing as CL
from agentflow.store import Store
from agentflow.tools import build_for_role

from conftest import add_literature

REPO = pathlib.Path(__file__).resolve().parents[1]
M_SPEC = REPO / "src" / "agentflow" / "specs" / "m.py"

#: 两个委托（真机那四个里的两个：一个 D 建的、一个 A 自建的）。
RID_D = "r-000011"
RID_A = "r-000013"

#: 改前那一格的原话形状（指标只数、不点表名与出口）。反真空把它喂回检查。
OLD_VAGUE_REASON = (
    "全表还有 4 条待裁（跨 2 个委托）：r-000011/000000《Central hyperplane sections…》、"
    "r-000013/000001《Bohr-Mollerup…》")

#: 改前 M 政策里那句（反真空逐字塞回 ⇒ c 必须红）。
OLD_POLICY_SENTENCE = (
    "不要自己补签，也**不要让 B 去润色 F 的证明**（B 不处理无签的证明）；")

#: 收工门这一格必须给出的出口（A 的三件：逐条判收 / 逐条判拒 / 逐委托提交清表）。
_PENDING_EXITS: tuple[str, ...] = ("lit.admit", "lit.stage_reject", "lit.admit_all")


# ====================================================================== 夹具


@pytest.fixture
def store(tmp_path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


@pytest.fixture
def reg(store: Store):
    registry = build_for_role("A", store=store, workspace_root=store.root).registry
    registry.bound_role = "A"
    return registry


def _stage(reg, rid: str, titles: list[str], *, doi_prefix: str) -> list[str]:
    entries = [{"title": t, "doi": f"{doi_prefix}/{i}", "provider": "stub",
                "year": 2020 + i, "type_code": "J",
                "relevance": f"与本次检索相关（{t}）"}
               for i, t in enumerate(titles)]
    res = reg.call("lit.stage_add", request_id=rid, entries=entries)
    assert res.ok, res.error
    return [x["slot"] for x in res.unwrap()["staged"]]


def _literature_all_processed(store: Store) -> None:
    """`literature` 表全 processed ⇒ 另一条队列（B 的消化面）是干净的。"""
    add_literature(store, "000000", title="Cube Slicing in R n", processed=True)
    add_literature(store, "000001", title="Gamma, beta, zeta", processed=True)


def _pending_cell(store: Store) -> CL.ClosingReport:
    return CL.check_closing(store, checks=("literature_pending",))


def _fixture(store: Store, reg) -> None:
    """候选有 pending，而 `literature` 全 processed（这正是真机那一趟的形态）。"""
    _stage(reg, RID_D, ["Central hyperplane sections of the l_p ball",
                        "Cross-sectional volume of sections of a cube",
                        "Fourier transform sections, again"], doi_prefix="10.41")
    _stage(reg, RID_A, ["Bohr-Mollerup theorem"], doi_prefix="10.42")
    _literature_all_processed(store)


# ====================================================================== 检查器（纯函数：两端都能喂）


def _pending_reading_problems(reading: dict, blockers: str) -> list[str]:
    """这一格的读数与拒信有没有点名表、委托与出口（空 = 点名了）。"""
    out: list[str] = []
    if str(reading.get("table") or "") != CL.LIT_PENDING_TABLE:
        out.append(f"读数里没有 `table={CL.LIT_PENDING_TABLE!r}`（收到 {reading.get('table')!r}）")
    if str(reading.get("other_table") or "") != CL.LIT_DIGEST_SURFACE:
        out.append("读数里没有把另一张表单独点名（`other_table`）")
    named = f"{reading.get('reason') or ''} {blockers}"
    if CL.LIT_PENDING_TABLE not in named:
        out.append("读数与拒信里都没有表名 `lit_candidates`")
    for rid in (RID_D, RID_A):
        if rid not in named:
            out.append(f"读数与拒信里没有委托 {rid}")
    exits = " ".join([named, str(reading.get("who_can_clear") or ""),
                      str(reading.get("queues_note") or "")])
    for needle in _PENDING_EXITS:
        if needle not in exits:
            out.append(f"读数与拒信里没有出口 `{needle}`")
    note = str(reading.get("queues_note") or "")
    if CL.LIT_DIGEST_SURFACE.split(".")[0] not in note or "processed" not in note:
        out.append("`queues_note` 没有点名另一张表（`literature` 的 `processed` 位）")
    if "不会让" not in note:
        out.append("`queues_note` 没有写清两张表之间没有联动（改②不会让①少一条）")
    return out


def _surface_problems(policy_text: str, handbook_body: str) -> list[str]:
    """M 的可见面里有没有两张表各自的出口，而且只有一份措辞（空 = 合格）。"""
    out: list[str] = []
    note = CL.LITERATURE_QUEUES_NOTE
    if note not in policy_text:
        out.append("M 的政策里读不到 `closing.LITERATURE_QUEUES_NOTE`（两张表与各自的出口）")
    if "lit_candidates" not in policy_text:
        out.append("M 的政策里没有点名 `lit_candidates`")
    if f"`{CL.LIT_DIGEST_SURFACE}`" not in policy_text:
        out.append("M 的政策里没有点名 `literature.processed`（另一条队列）")
    # 一处真身：手册只指路，不抄第二份。
    if note in handbook_body:
        out.append("M 的手册里抄了一份 `LITERATURE_QUEUES_NOTE` 的副本 —— 那是第二真身")
    if "closing.LITERATURE_QUEUES_NOTE" not in handbook_body:
        out.append("M 的手册没有指到那一段话的真身（`closing.LITERATURE_QUEUES_NOTE`）")
    for needle in ("lit_candidates", "literature", "queues_note"):
        if needle not in handbook_body:
            out.append(f"M 的手册里读不到 `{needle}`（读格的第一步就少了东西）")
    return out


def _forbid_problems(spec_text: str, handbook_text: str) -> list[str]:
    """派活文案有没有把二阶段读成"禁止洗"（空 = 没有；同时要求界线还在）。"""
    out: list[str] = []
    whole = f"{spec_text}\n{handbook_text}"
    for needle in ("不要让 B 去润色", "不处理、不润色", "禁止洗稿", "不许洗稿"):
        if needle in whole:
            out.append(f"派活文案里还写着「{needle}」—— 那会被读成「B 不许做二阶段」")
    # 界线必须还在：洗稿不是绕过 V 签的路（洗完仍要 V 签盖住这一版）。
    for needle in ("洗稿不是绕过签的路", "重拿 V 签"):
        if needle not in spec_text:
            out.append(f"policy 里读不到「{needle}」—— 删「禁止洗」不许把界线一起删掉")
    if "无签的证明 B 不处理" not in spec_text:
        out.append("policy 里读不到「无签的证明 B 不处理」—— 那是 V 签这道界线本身")
    # 责任路由的三句不许被"整段删掉"。
    flat = "".join(spec_text.split())
    for needle in ("命题已在册而缺V签", "让**B**处理", "F产出但没签", "先拿V签"):
        if needle not in flat:
            out.append(f"policy 里读不到「{needle}」（责任路由被整段删掉了）")
    return out


def _m_handbook_body() -> str:
    for skill in SK.skills_for("M"):
        if skill.slug == "收工-一份权威结论":
            return skill.body
    raise AssertionError("M 的手册里没有「收工-一份权威结论」这一条 ⇒ 判据失去对象")


# ====================================================================== a 读数点名表


def test_a_the_cell_names_the_table_the_delegations_and_the_exit(store: Store, reg) -> None:
    """a. 候选有 pending ⇒ 读数与拒信点名 `lit_candidates` + 委托 + 出口，并单独点名另一张表。"""
    _fixture(store, reg)
    rep = _pending_cell(store)
    assert rep.status["literature_pending"] == "fail", rep.to_dict()
    reading = rep.readings["literature_pending"]
    assert reading["pending"] == 4, reading
    blockers = " ".join(str(f.detail) for f in rep.blockers
                        if f.check == "literature_pending")
    assert _pending_reading_problems(reading, blockers) == [], (
        _pending_reading_problems(reading, blockers), reading)


def test_a2_the_other_table_being_clean_does_not_move_this_cell(store: Store, reg) -> None:
    """a2. 夹具前提：`literature` 全 processed，而这一格照样 fail —— 两个数不是同一个数。"""
    _fixture(store, reg)
    unprocessed = [r for r in store.rows("literature") if not r.get("processed")]
    assert unprocessed == [], unprocessed
    rep = _pending_cell(store)
    assert rep.status["literature_pending"] == "fail", rep.to_dict()
    note = str(rep.readings["literature_pending"]["queues_note"])
    assert "改②" in note and "不会让①少一条候选" in note, note
    assert "改①也不会让②的 `processed` 转真" in note, note


def test_a3_the_old_vague_wording_is_caught_by_the_same_check(store: Store, reg) -> None:
    """a3. 反真空：把改前那句模糊原话喂回检查 ⇒ 必须报缺（判据不是橡皮图章）。"""
    _fixture(store, reg)
    reading = _pending_cell(store).readings["literature_pending"]
    doctored = dict(reading, table="", other_table="", queues_note="",
                    who_can_clear="", reason=OLD_VAGUE_REASON)
    problems = _pending_reading_problems(doctored, OLD_VAGUE_REASON)
    assert problems, "改前的模糊原话喂回检查居然合格 —— 这条判据量不到「点名了哪张表」"
    # 现场那一支也必须咬住：读数只说 literature 那 5 行 ⇒ 缺表名。
    wrong_table = dict(reading, reason="lit 000001–000005 无本地全文，B2 已逐条判 metadata_only；"
                                      "表上那一档仍读 fail")
    assert _pending_reading_problems(wrong_table, wrong_table["reason"]), wrong_table["reason"]


# ====================================================================== b M 的可见面


def test_b_m_sees_both_tables_and_their_exits_with_one_body() -> None:
    """b. M 的可见面里有「两张表各自的出口」；手册只指路，不抄第二份。"""
    policy_text = "\n".join(str(item) for item in AP.ROLE_BRIEFS["M"].policy)
    problems = _surface_problems(policy_text, _m_handbook_body())
    assert problems == [], problems


def test_b2_dropping_the_note_from_the_policy_turns_b_red() -> None:
    """b2. 反真空：从政策里摘掉那一句 ⇒ b 必红；手册塞一份手写副本 ⇒ 也红。"""
    policy_text = "\n".join(str(item) for item in AP.ROLE_BRIEFS["M"].policy)
    body = _m_handbook_body()
    assert CL.LITERATURE_QUEUES_NOTE in policy_text, "夹具前提：政策里渲染着那一句"
    stripped = policy_text.replace(CL.LITERATURE_QUEUES_NOTE, "")
    assert _surface_problems(stripped, body) != [], (
        "从政策里摘掉「两张表各自的出口」之后判据仍然绿")
    duplicated = body + "\n\n" + CL.LITERATURE_QUEUES_NOTE
    assert _surface_problems(policy_text, duplicated) != [], (
        "手册里塞了一份副本之后判据仍然绿 —— 那它就是第二真身")


# ====================================================================== c 派活文案不再禁止洗


def test_c_the_dispatch_no_longer_forbids_the_second_stage() -> None:
    """c. M 的派活文案里没有「禁止洗」这层意思，而「洗完仍要 V 签」这层意思还在。"""
    spec_text = M_SPEC.read_text(encoding="utf-8")
    problems = _forbid_problems(spec_text, _m_handbook_body())
    assert problems == [], problems


def test_c2_putting_the_old_sentence_back_turns_c_red() -> None:
    """c2. 反真空：把那句旧文案逐字塞回 ⇒ c 必红；把责任路由整段删掉 ⇒ 也红。"""
    spec_text = M_SPEC.read_text(encoding="utf-8")
    body = _m_handbook_body()
    assert _forbid_problems(spec_text, body) == [], "夹具前提：真身上那句已经改掉了"
    assert _forbid_problems(spec_text + "\n" + OLD_POLICY_SENTENCE, body) != [], (
        "把「不要让 B 去润色 F 的证明」塞回去之后判据仍然绿")
    without_boundary = spec_text.replace("洗稿不是绕过签的路", "")
    assert _forbid_problems(without_boundary, body) != [], (
        "删掉「洗稿不是绕过签的路」之后判据仍然绿 —— 边界与禁令没分开")
    without_routing = "\n".join(line for line in spec_text.splitlines()
                                if "命题已在册而缺 V 签" not in line)
    assert _forbid_problems(without_routing, body) != [], (
        "整段删掉责任路由之后判据仍然绿 —— 「删掉」不等于「改写」")

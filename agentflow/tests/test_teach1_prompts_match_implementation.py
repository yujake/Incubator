# -*- coding: utf-8 -*-
"""TEACH1：把「写着但与实现相反」的八处教法钉回实现（GUIDE1 报告 §3/§4）。

## 这一份钉什么（逐条对应 `agentflow/temp/guide1/GUIDE1-REPORT.md`）

| # | 改前原话（写着） | 实现（真身） | 这一份怎么判 |
|---|---|---|---|
| ① | `PAPER_PACK`「2. 派 V 的 `verify_proof`…」（无条件祈使） | M / G / H 的 `ALLOWED_EDGES` 里没有 V | M/G/H 三格渲染面必须写「派 V 是产出方的事」＋`forbidden_edge`；并现读边表证明前提 |
| ② | 手册「没签的…不计入「产出的证明数」」 | `delivery.proof_count`（只数已签）与 `proof_output_count`（含待签）两格 | 手册两格都在；`F.step` 的返回广告有 `proof_output_count`；真跑一次 `delivery_summary` 对读数 |
| ③ | M 手册「没在 `statements` 里登记就是"不存在"」 | 成果身份含 `mss:<稿号>`（已登记未签也算成果） | M 手册必须写 `mss:<稿号>` 与「还没进 statements」；`delivery_summary` 的 `output_id` 对读数 |
| ④ | M policy「无签的证明…到不了你面前」 | `researchpending` 的 `manuscript_unsigned` 逐份摆到 M 面前 | M 渲染面点名这一格＋转 D；真跑 `pending_reading` 对同一格 |
| ⑤ | `specs/f.py` 同一段里两个「收工门」互相抵消 | final 门（`_v_wait_gate_reading`）拦，`conductor.closing` 的 `statements_unsigned` 是读数 | F 渲染面写「两道门」；真跑 F 的 final 门证明它确实拦 |
| ⑥ | F 每轮提示词（L4）没有「出稿后派 V」 | `_attack_prompt` 是 F 每轮唯一必读的提示词 | 渲染 `_attack_prompt` 必须含 §2.2 与可执行动作 |
| ⑦ | park 挡下时的 why 只进 `run.park` / `run.notes` | `_pending_work` 第 4 条 → `_manuscript_block` | 真读一份未签稿 → `_pending_work` 被挡 → 同一份读数进 `_prompt` |
| ⑧ | `specs/b.py` / `b_sign_policy.py` 把「先拿签再入库」写成无条件 | `quote_carrier=first` 的引用侧第一遍摘录免签 | B 渲染面写「只指第二遍」＋第一遍例外；`evidencebits` 两档词表对读数 |

判据形态统一为「逐字锚点 + 反真空」：每条都先用一个纯函数算"缺了什么"（正控），
再把该锚点从同一段文本里删掉、喂回同一个函数（反真空：必须红）。②⑤⑦额外做
「读数一致」：不只看文字，还让生产读口真跑一次，断言文字说的那一格就是它回的。

零模型调用、零网络；只有 ⑦ 与 ⑤ 需要临时工作区（`tmp_path`）。
"""
from __future__ import annotations

import inspect
import pathlib

from agentflow import agent_prompts as AP
from agentflow import agent_skills as AS
from agentflow import agent_loop as AL
from agentflow import capabilities as CAP
from agentflow import evidencebits as EB
from agentflow import proofregistry as PR
from agentflow import researchpending as RP
from agentflow.agent_f import delivery as FD
from agentflow.agent_f.core import _attack_prompt
from agentflow.specs import builtin_specs
from agentflow.store import Store
from agentflow.tools import build_registry

#: 渲染用的注册表（与 `test_agent_f_prompt_contract` 同一口径：离线、不建工作区）。
_REG = build_registry().registry

#: 已登记稿的夹具正文（与 `test_m_reads_the_unsigned_manuscript_gap` 同一个形状）。
BODY = "1. 取 ε>0，按定义逐点验证。（前提）"
AT = "2026-11-18T10:02:18+08:00"


def _prompt(role: str) -> str:
    return AP.system_prompt(role, registry=_REG)


def _manual(role: str) -> str:
    """该角色手册的全部文本（slug / 标题 / 索引两格 / 正文）。"""
    parts: list[str] = []
    for skill in AS.CATALOG[role]:
        parts.append(f"### {skill.slug}")
        for field in ("title", "summary", "when", "body"):
            parts.append(str(getattr(skill, field)))
    return "\n".join(parts)


def _write_registered(ws: pathlib.Path, *, mid: str = "000001") -> tuple[str, str]:
    """在盘上落一份「已登记」的 F 证明稿（稿头有正文 sha / 命题指纹 / 版本行 ⇒ checked）。"""
    rel = f"reports/f-proof-{mid}.md"
    sha = PR.proof_sha(BODY)
    fp = PR.proposition_fingerprint(f"证明：夹具引理（{mid}）")
    text = (
        "# F 的证明手稿：夹具\n\n"
        "- 计划：0000 · 子目标：s1\n"
        f"- 正文sha：{sha}\n"
        f"- 命题指纹：{fp}\n"
        "- 命题类型：conjecture\n"
        f"- 登记时间：{AT}\n"
        f"- 标签：夹具 {mid}\n"
        f"- 版本：{AT}@{sha}\n\n"
        f"## 命题\n\n证明：夹具引理（{mid}）\n\n"
        f"## 证明\n\n{BODY}\n\n"
        "## 依赖\n\n（自足证明，空表就是声明。）\n"
    )
    path = ws / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return rel, sha


def _ws(tmp_path: pathlib.Path) -> tuple[Store, pathlib.Path]:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    return st, ws


# ============================================================ ① PAPER_PACK 派 V 的主语

PAPER_REQUIRED: tuple[str, ...] = (
    "派 V 是产出方（F / E / B）自己的动作",
    "不是你的",
    "forbidden_edge",
    "转达 / 追这一份的签",
    "`proof_manuscript` 给那一份稿 —— 在册也给",
)
PAPER_STALE: tuple[str, ...] = (
    "2. 派 V 的 `verify_proof`",
)


def _paper_problems(text: str) -> list[str]:
    bad = [f"读不到 {needle!r}" for needle in PAPER_REQUIRED if needle not in str(text)]
    bad += [f"仍写着旧句 {needle!r}" for needle in PAPER_STALE if needle in str(text)]
    return bad


def test_paper_pack_sends_v_through_the_producer_not_the_reader() -> None:
    """① M / G / H 都读到「派 V 是产出方的事」，且三者到 V 的边确实不存在。"""
    bad: list[str] = []
    for role in AP.PAPER_PACK_ROLES:
        text = _prompt(role)
        if "完成定义" not in text:
            bad.append(f"{role} 的提示词里没有论文包那一段 ⇒ 这条判据失去对象")
            continue
        bad += [f"{role}: {one}" for one in _paper_problems(text)]
        # 读数一致：那句话说的「你不是那条边的人」必须与边表现读一致。
        if "V" in set(CAP.ALLOWED_EDGES.get(role) or ()):
            bad.append(f"{role} 的边表里有 V —— 前提变了，那句话就不再成立")
    assert bad == [], "\n".join(bad)


def test_deleting_the_producer_subject_turns_the_paper_pack_red() -> None:
    """① 反真空：从同一段渲染文本里删掉那句主语 ⇒ 同一个读法必红。"""
    text = _prompt("M")
    assert _paper_problems(text) == []
    broken = text.replace(PAPER_REQUIRED[0], "")
    assert broken != text
    assert any("派 V 是产出方" in one for one in _paper_problems(broken))


# ============================================================ ② 两格证明读数

def _f_skill(fragment: str) -> str:
    for skill in AS.CATALOG["F"]:
        if fragment in str(getattr(skill, "body", "")):
            return str(skill.body)
    return ""


def _proof_count_problems(text: str) -> list[str]:
    need = ("`proof_count`", "`proof_output_count`", "含待签", "`mss:<稿号>`",
            "不许读成「我没有产出」")
    return [f"F 手册读不到 {needle!r}" for needle in need if needle not in str(text)]


def test_f_counts_signed_proofs_and_proof_outputs_separately() -> None:
    """② 手册两格口径 + 返回广告 + `delivery_summary` 的真读数三处一致。"""
    body = _f_skill("交付一份证明")
    assert body, "F 手册里找不到「交付一份证明」那一条 ⇒ 判据失去对象"
    assert _proof_count_problems(body) == [], _proof_count_problems(body)

    action = {a.action: a for a in builtin_specs()["F"].actions}["step"]
    assert "proof_output_count" in action.returns, (
        "`F.step` 的返回广告里没有 `proof_output_count` —— 模型看不到那一格")

    # 读数一致：一份「已登记、还没签」的稿在真读数里是 proof_count=0 /
    # proof_output_count=1，且 why 用的就是这两个名字。
    got = FD.delivery_summary(outputs=[{
        "statement_id": "", "manuscript_id": "000123",
        "manuscript": "reports/f-proof-000123.md", "state": "waiting",
        "why": "这一份正文还没有签"}])
    assert got["proof_count"] == 0, got
    assert got["proof_output_count"] == 1, got
    assert got["outputs"][0]["output_id"] == "mss:000123", got["outputs"]
    why = str(got.get("why") or "")
    assert "`proof_count`" in why and "`proof_output_count`" in why, why
    assert "有稿未签不是「没产出」" in why, why


def test_deleting_the_two_cell_wording_turns_it_red() -> None:
    """② 反真空：删掉两格口径里那一句 ⇒ 同一个读法必红。"""
    body = _f_skill("交付一份证明")
    broken = body.replace("`proof_output_count` 数", "")
    assert broken != body
    assert _proof_count_problems(broken), "删掉两格口径之后判据居然还是绿的"


# ============================================================ ③ 已登记未签也是成果

def _m_manual() -> str:
    for skill in AS.CATALOG["M"]:
        if "成果的身份有两种" in str(getattr(skill, "body", "")):
            return str(skill.body)
    return ""


def _identity_problems(text: str) -> list[str]:
    need = ("成果的身份有两种", "`mss:<稿号>`", "还没进 `statements`", "不是「不存在」")
    return [f"M 手册读不到 {needle!r}" for needle in need if needle not in str(text)]


def test_m_manual_says_a_registered_unsigned_manuscript_is_still_an_output() -> None:
    """③ M 的手册不再说「没登记就是不存在」；`mss:` 身份与 `delivery` 对读数。"""
    body = _m_manual()
    assert body, "M 手册里找不到「成果的身份有两种」那一条 ⇒ 判据失去对象"
    assert _identity_problems(body) == [], _identity_problems(body)
    got = FD.delivery_summary(outputs=[{
        "statement_id": "", "manuscript_id": "000007",
        "manuscript": "reports/f-proof-000007.md", "state": "waiting"}])
    assert got["outputs"][0]["output_id"] == "mss:000007", got["outputs"]
    assert got["unfinished"][0]["output_id"] == "mss:000007", got["unfinished"]


def test_deleting_the_mss_identity_turns_it_red() -> None:
    """③ 反真空：删掉 `mss:<稿号>` 那一句 ⇒ 同一个读法必红。"""
    body = _m_manual()
    broken = body.replace("`mss:<稿号>`", "")
    assert broken != body
    assert _identity_problems(broken)


# ============================================================ ④ M 认 manuscript_unsigned

M_UNSIGNED_REQUIRED: tuple[str, ...] = (
    "`manuscript_unsigned`",
    "逐份点名",
    "`conductor.state`",
    "`conductor.patrol`",
    "转 D",
    "next_action",
)
M_UNSIGNED_STALE: tuple[str, ...] = (
    "也就到不了你面前",
)


def _m_unsigned_problems(text: str) -> list[str]:
    bad = [f"M 的 policy 读不到 {needle!r}" for needle in M_UNSIGNED_REQUIRED
           if needle not in str(text)]
    bad += [f"M 的 policy 仍写着旧句 {needle!r}" for needle in M_UNSIGNED_STALE
            if needle in str(text)]
    return bad


def test_m_policy_sees_the_unsigned_manuscript_cell(tmp_path: pathlib.Path) -> None:
    """④ 渲染面点名那一格；同一格在 `researchpending` 的真读数里逐份点名、处置转 D。"""
    text = _prompt("M")
    assert _m_unsigned_problems(text) == [], "\n".join(_m_unsigned_problems(text))

    st, ws = _ws(tmp_path)
    rel, sha = _write_registered(ws)
    reading = RP.pending_reading(st)
    counts = dict(reading.get("counts") or {})
    assert int(counts.get("manuscript_unsigned") or 0) == 1, (counts, rel)
    gaps = {str(g.get("code") or ""): dict(g) for g in (reading.get("gaps") or ())}
    assert "manuscript_unsigned" in gaps, reading.get("gaps")
    assert rel in (gaps["manuscript_unsigned"].get("ids") or []), gaps
    action = dict(reading.get("next_action") or {})
    assert str(action.get("target") or "") == "D", action
    assert str(action.get("summary") or "").startswith("转 D"), action
    assert sha[:12] in str(gaps["manuscript_unsigned"].get("why") or ""), gaps


def test_putting_the_old_reason_back_turns_m_red() -> None:
    """④ 反真空：把「也就到不了你面前」回灌 ⇒ 同一个读法必红。"""
    text = _prompt("M")
    broken = text + "\n无签的证明不会被 B 收进册，也就到不了你面前。"
    assert _m_unsigned_problems(broken), "旧理由回来了，判据却没报"


# ============================================================ ⑤ 两道门分别命名

F_GATE_REQUIRED: tuple[str, ...] = (
    "你自己的 final 门",
    "`agent_loop._v_wait_gate_reading`",
    "全趟的收工报告（`closing` 那一侧）",
    "两道门",
)
F_GATE_STALE: tuple[str, ...] = (
    "收工门不因它拦",
)


def _f_gate_problems(text: str) -> list[str]:
    bad = [f"F 的 policy 读不到 {needle!r}" for needle in F_GATE_REQUIRED
           if needle not in str(text)]
    bad += [f"F 的 policy 仍写着旧句 {needle!r}" for needle in F_GATE_STALE
            if needle in str(text)]
    return bad


def test_f_names_the_two_gates_separately(tmp_path: pathlib.Path) -> None:
    """⑤ policy 说清「final 门拦 / `conductor.closing` 是读数」；真跑 F 的门证明它拦。"""
    text = _prompt("F")
    assert _f_gate_problems(text) == [], "\n".join(_f_gate_problems(text))
    # 名字是真符号：`_final_gate_reading` 真的调 `_v_wait_gate_reading`，且 F 在拦的名单里。
    src = inspect.getsource(AL.AgentLoop._final_gate_reading)
    assert "self._v_wait_gate_reading()" in src, src[:400]
    assert '("F", "E", "B")' in src, src[:400]

    # 读数一致：未签的 F 计划在 final 门里确实被拒；而 `closing` 的 statements_unsigned
    # 是另一格读数（本判据只核前者的行为，后者由 `test_unsigned_statements_are_readings_not_a_gate` 钉）。
    from test_yi_unsigned_plan_blocks_closing import _Run, _Shell, _manuscript, _plan

    st, _ws_dir = _ws(tmp_path)
    _plan(st, manuscript_ids=("000000",))
    _manuscript(st, "000000")
    gate = _Shell(st, "F").reading(_Run())
    assert bool(gate.get("applicable")), gate
    assert not bool(gate.get("complete")), gate


def test_putting_the_single_gate_name_back_turns_f_red() -> None:
    """⑤ 反真空：把「两道门」删掉、只剩一个「收工门」的说法 ⇒ 同一个读法必红。"""
    text = _prompt("F")
    broken = text.replace("两道门", "收工门")
    assert broken != text
    assert _f_gate_problems(broken)


# ============================================================ ⑥ F 每轮的 L4 送审一句

DISPATCH_REQUIRED: tuple[str, ...] = (
    "## 2.2 这一轮落了 `manuscript_path` ⇒ 下一轮开头先派 V 审它",
    "送审是你自己的动作",
    "`framework_summon`",
    "`proof_manuscript` 就点这一份稿",
    "still_unsubmitted[].next_action",
)


def _dispatch_problems(text: str) -> list[str]:
    return [f"F 的每轮提示词读不到 {needle!r}" for needle in DISPATCH_REQUIRED
            if needle not in str(text)]


def test_f_round_prompt_connects_proof_output_to_dispatch() -> None:
    """⑥ L4 是 F 每轮唯一必读的那份提示词 —— 它必须把「落了稿」与「派 V」连起来。"""
    prompt = _attack_prompt(
        plan={"problem": "证明引理 A", "problem_key": "K-TEACH1", "rounds": 0,
              "budget": {"max_rounds": 6}},
        sg={"sid": "s1", "text": "证明引理 A", "testable": "引理 A 成立",
            "evidence_ids": [], "experiment_ids": []},
        owner="F", tried=[])
    assert _dispatch_problems(prompt) == [], "\n".join(_dispatch_problems(prompt))


def test_deleting_the_dispatch_section_turns_the_round_prompt_red() -> None:
    """⑥ 反真空：把 §2.2 那一节从同一段提示词里删掉 ⇒ 同一个读法必红。"""
    prompt = _attack_prompt(
        plan={"problem": "P", "problem_key": "K", "rounds": 0,
              "budget": {"max_rounds": 6}},
        sg={"sid": "s1", "text": "T", "testable": "", "evidence_ids": [],
            "experiment_ids": []},
        owner="F", tried=[])
    head = DISPATCH_REQUIRED[0]
    assert head in prompt
    broken = prompt.replace(head, "")
    assert _dispatch_problems(broken), "删掉 §2.2 之后判据居然还是绿的"


# ============================================================ ⑦ park 的 why 进模型一拍

def _park_why_problems(text: str, *, rel: str, sha12: str) -> list[str]:
    bad: list[str] = []
    if rel not in str(text):
        bad.append(f"模型可见的一拍里没有稿路径 {rel!r}")
    if sha12 not in str(text):
        bad.append(f"模型可见的一拍里没有正文 sha 前 12 {sha12!r}")
    if "审这一份证明稿" not in str(text):
        bad.append("模型可见的一拍里没有「审这一份证明稿」这一步")
    if "这一拍不许当无事可做" not in str(text):
        bad.append("模型可见的一拍里没有「这一拍不许当无事可做」")
    return bad


class _PromptShell:
    """把 `_prompt` 需要的那几格挂到一个壳上（其余方法照生产实现取）。"""

    def __init__(self, ws: pathlib.Path, manuscript_cache: dict) -> None:
        self.role = "F"
        self.max_steps = 8
        self.session_root = ws
        self._face = None
        self._research_cache = None
        self._tree_cache = None
        self._manuscript_cache = manuscript_cache

    def _budget_text(self) -> str:
        return "夹具预算（不花钱）"

    def _purpose_ask_note(self) -> str:
        return ""

    def _research_block(self) -> str:
        return ""

    def _manuscript_block(self) -> str:
        return AL.AgentLoop._manuscript_block(self)


def test_park_block_reason_reaches_the_model_visible_turn(tmp_path: pathlib.Path) -> None:
    """⑦ 真读一份未签稿 ⇒ `_pending_work` 挡挂机 ⇒ 同一份 why 进 `_prompt`。"""
    st, ws = _ws(tmp_path)
    rel, sha = _write_registered(ws)

    shell = object.__new__(AL.AgentLoop)
    shell.role = "F"
    shell.workspace_root = str(ws)
    shell.store = st
    shell.conductor = None
    shell.my_task_id = ""
    work = AL.AgentLoop._pending_work(shell, {})
    assert work["busy"] is True, work
    assert int((work.get("manuscripts") or {}).get("count") or 0) == 1, work
    assert rel in str(work.get("why_text") or ""), work

    cache = dict(work.get("manuscripts") or {})
    prompt_shell = _PromptShell(ws, cache)
    text = AL.AgentLoop._prompt(prompt_shell, [], step=0)
    sha12 = sha[:12]
    assert _park_why_problems(text, rel=rel, sha12=sha12) == [], (
        "\n".join(_park_why_problems(text, rel=rel, sha12=sha12)))


def test_without_the_block_the_prompt_loses_the_reason(tmp_path: pathlib.Path) -> None:
    """⑦ 反真空：把同一拍那份读数清空 ⇒ 同一个读法必红（证明它读的是这份 why）。"""
    _st, ws = _ws(tmp_path)
    rel, sha = _write_registered(ws)
    text = AL.AgentLoop._prompt(_PromptShell(ws, {}), [], step=0)
    problems = _park_why_problems(text, rel=rel, sha12=sha[:12])
    assert problems, "读数清空之后判据还是绿的 ⇒ 它读的不是那份 why"


# ============================================================ ⑧ B 的引用侧第一遍例外

B_REQUIRED: tuple[str, ...] = (
    "例外：引用侧第一遍摘录可以先落",
    "`quote_carrier=first`",
    "`cited_placeholder`",
    "不欠真签",
    "只指第二遍改写",
)


def _b_first_pass_problems(text: str) -> list[str]:
    return [f"B 的渲染面读不到 {needle!r}" for needle in B_REQUIRED
            if needle not in str(text)]


def test_b_policy_scopes_the_sign_rule_and_names_the_first_pass_exception() -> None:
    """⑧ B 的渲染面把「先拿签」限定到第二遍，并把第一遍的免签档写给用之前。"""
    text = _prompt("B")
    assert _b_first_pass_problems(text) == [], "\n".join(_b_first_pass_problems(text))
    # 读数一致：这两档的名字就是 `evidencebits` 的受控词表。
    assert EB.QUOTE_CARRIER_KEY == "quote_carrier"
    assert EB.QUOTE_PASS_FIRST == "first"
    mark = EB.quote_carrier_mark(pass_="first", manuscript="reports/b-proof-000001.md")
    assert mark["pass"] == "first", mark


def test_deleting_the_first_pass_exception_turns_b_red() -> None:
    """⑧ 反真空：删掉第一遍例外那半句 ⇒ 同一个读法必红。"""
    text = _prompt("B")
    broken = text.replace(B_REQUIRED[0], "")
    assert broken != text
    assert _b_first_pass_problems(broken)


# ============================================================ ⑨ E 的返回带签与下一步

def _e_sign_problems(out: dict) -> list[str]:
    """E 的返回里「这一份 e-proof 还欠签」那几格在不在、指得对不对。"""
    bad: list[str] = []
    reading = dict(out.get("v_sign") or {})
    if not reading:
        bad.append("E 的返回里没有 v_sign —— 它跑完实验后看不到「这一步还欠签」")
    elif str(reading.get("state") or "") != "waiting":
        bad.append(f"v_sign.state={reading.get('state')!r}，这一份还没签，应当是 waiting")
    if "派 V" not in str(out.get("v_sign_hint") or ""):
        bad.append("v_sign_hint 里没有「派 V」这句话")
    action = dict(out.get("next_action") or {})
    if action.get("tool") != "framework_summon" or action.get("role") != "V":
        bad.append(f"next_action 不是派 V 的 summon 形状：{action}")
    if str(action.get("manuscript") or "") != str(out.get("proof_manuscript") or ""):
        bad.append("next_action 点的那份稿不是这一趟的 proof_manuscript")
    return bad


def test_e_return_carries_the_sign_reading_and_the_next_action(tmp_path: pathlib.Path) -> None:
    """⑨ E 跑完一趟穷举实验，返回里必须有 `v_sign`（四档）与 `next_action`（派 V）。"""
    from test_e_gets_its_v_sign_like_f import _env

    out = _env(tmp_path)["out"]
    assert _e_sign_problems(out) == [], "\n".join(_e_sign_problems(out))


def test_without_the_sign_reading_e_has_no_next_step(tmp_path: pathlib.Path) -> None:
    """⑨ 反真空：把那一格从同一份返回里删掉 ⇒ 同一个读法必红。"""
    from test_e_gets_its_v_sign_like_f import _env

    out = dict(_env(tmp_path)["out"])
    out.pop("v_sign", None)
    out.pop("next_action", None)
    out.pop("v_sign_hint", None)
    assert _e_sign_problems(out), "删掉那几格之后判据还是绿的 ⇒ 它读的不是这份返回"

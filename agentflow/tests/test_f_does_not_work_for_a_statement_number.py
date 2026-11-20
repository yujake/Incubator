# -*- coding: utf-8 -*-
"""判据：F 不「对着某个命题号」攻坚，也不「按命题号」写稿 / 交稿。

## 业主裁定（逐字，这一份的唯一权威）

    对于 F 侧，在实现方面彻底通畅（你亲自拿着跑跑通）后，撤去所有有关对某个给定命题号
    进行攻坚或写证明的逻辑。

前置已满足：`temp/_f_chain_rehearsal.py` 亲自跑通（稿号 000001 → 送审签出 → 收录现取
命题号 000000 → 稿上签块 true → V 台账 3 行 → 稿名不变）。于是这一刀只做"撤"：
`statement_id` 不再是 F 的输入，也不再出现在 F 交出去的东西里。

## 撤的是什么（三处，逐条对应本文件的 a/b/c）

| # | 撤的东西 | 这一份钉什么 |
|---|---|---|
| a | `publish_manuscript` / `promote_manuscript` 的"兼容形参" `statement_id` | 四个产稿/攻坚入口的参数表里没有 `statement_id`；递进去是 `TypeError` |
| b | `register_or_rewrite(statement_id=…)` 与送审提示里的 `stmt:<号>` | 打桩记录调用参数 ⇒ 交出去的 kwargs 里没有 `statement_id`；提示里点的是稿路径 |
| c | 反真空三条（否则上面两条可以靠"把接口删空"变绿） | ① 把 `statement_id` 加回任一入口 ⇒ a 红；② 送审时偷偷带上 ⇒ b 红；③ 命名又按命题号 ⇒ 红 |
| d | 端到端五段读数 | 稿号 → 送审签出 → 收录现取命题号（≠ 稿号）→ 稿上签块 → V 台账，五段都读得出来 |
| e | 题面里的稿名字面（p272 的字面漏网） | F 的题面（含共用段）里没有 `f-proof-<命题号>` / `f-proof-<stmt`；写的是 `f-proof-<你的稿号>.md` |

## 为什么这不是"把功能删掉"（读数保留的边界）

`statement_id` 在 F 侧还剩三类用法，刻意保留（它们是读数，不是攻坚输入）：

1. `_read_sign` / `delivery_reading` 里"读哪一本 V 台账"（已收录的签住在
   `verifications/<命题号>.jsonl`）—— 读签必须点名问哪一条；
2. `_statement_row` / `_output_body` 读"这一条成果的现行正文"（签盖的就是它）；
3. `delivery.py` 的逐条交差读数（一条成果 = 一个在册命题号）与 `settle` 的点名。

它们都不决定"下一步证哪条 / 怎么证"：F 选目标读的是 `plan.subgoals`
（`attack.pick_next_subgoal`），写稿读的是稿号与 `cites`。本条判据只钉输入与交接面。

## 反真空的写法

三条负控都在判据本体上做（不是断言字符串）：`_entry_violations` / `_handoff_violations`
/ `_naming_problems` 是本文件里的纯函数，各配一条"喂坏读数 ⇒ 非空"的控制；另有两条
活体控制（monkeypatch 真入口 / 真 signatuce 传参）。零模型调用、零真机。
"""
from __future__ import annotations

import inspect
import json
import pathlib
import re
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import depsection as _DS          # noqa: E402
from agentflow import manuscriptids as MI        # noqa: E402
from agentflow import proofregistry as _PR       # noqa: E402
from agentflow import verifications as VR        # noqa: E402
from agentflow import vsigns as VS               # noqa: E402
from agentflow.agent_b import AgentB             # noqa: E402
from agentflow.agent_f import AgentF             # noqa: E402
from agentflow.agent_f import manuscript as FM   # noqa: E402
from agentflow.agent_f import vsign as FV        # noqa: E402
from agentflow.store import Store                # noqa: E402

AT = "2026-11-10T22:00:00+08:00"
MID = "000123"
#: 一个不会被这一份用到的命题号：夹具里它只当"那个不该出现的号"。
#: 为什么不用 `000000`：新工作区里 `manuscriptids` 与 `statements` 两个号段都从 0 起，
#: 拿 000000 当反例会在"两边都刚起步"时撞上同一个字面（那是夹具巧合，不是口径）。
SID = "000042"
PLAN = "000004"
PROPOSITION = "若 (X,Σ,μ) 为测度空间、f_n→f μ-a.e. 且被可积 g 控制，则 ∫f_n dμ → ∫f dμ。"
PROOF_STEPS = [
    "由控制函数得 |f_n-f| ≤ 2g 且 f_n-f → 0 a.e.",
    "对 2g-|f_n-f| 用 Fatou：∫2g ≤ liminf ∫(2g-|f_n-f|)",
    "整理得 limsup ∫|f_n-f| ≤ 0",
    "三角不等式给出 |∫f_n-∫f| → 0",
]


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _f(st: Store) -> AgentF:
    return AgentF(st, config={"workspace_root": str(st.root), "plan_id": PLAN})


def _product() -> dict:
    return {"product": "proof", "proposition": PROPOSITION,
            "strategy": "套用已知定理", "why_strategy": "直接套控制收敛",
            "steps": [{"n": i, "text": t, "cites": []}
                      for i, t in enumerate(PROOF_STEPS, 1)]}


def _round(st: Store, mid: str = MID) -> dict:
    """走生产的产稿入口（`proof_manuscript`）：脚本化产物、真 store、零模型。"""
    f = _f(st)
    got = f.proof_manuscript(
        _product(), sg={"sid": "s1", "text": PROPOSITION, "testable": ""},
        plan={"plan_id": PLAN}, label="DCT", proof_no=1, manuscript_id=mid)
    assert got.get("ok") is True, got
    return got


def _body(st: Store, rel: str) -> str:
    return _DS.proof_body((pathlib.Path(st.root) / rel).read_text(encoding="utf-8")).strip("\n")


def _stamp(st: Store, rel: str, sha: str) -> None:
    """V 那一签盖回稿上（生产写口；签块第 9 格按稿名现算）。"""
    path = pathlib.Path(st.root) / rel
    text = path.read_text(encoding="utf-8")
    stamped = VS.stamp_manuscript_sign(
        text, proof_sha=sha, streak=3, need=3, verdict="成立", at=AT,
        ledger="verifications/pending/probe.jsonl#v-000001",
        statement_id="", manuscript_id=VS.manuscript_id_of(rel))
    path.write_text(stamped, encoding="utf-8")


# ------------------------------------------------------------------ 判据本体（纯函数）

#: F 的产稿 / 攻坚入口（含同名的方法版与模块版）。这几件是"写证明"的入口，
#: 它们收不到命题号 ⇒ "对着某个命题号写证明"没有接口。
def _entries() -> dict[str, object]:
    return {
        "AgentF.proof_manuscript": AgentF.proof_manuscript,
        "AgentF.manuscript_path": AgentF.manuscript_path,
        "AgentF.promote_manuscript": AgentF.promote_manuscript,
        "AgentF.publish_manuscript": AgentF.publish_manuscript,
        "agent_f.manuscript.promote_manuscript": FM.promote_manuscript,
    }


def _entry_violations(entries: dict[str, object] | None = None) -> dict[str, list[str]]:
    """入口参数表里"按命题号"的口子 ⇒ `{入口: [问题…]}`；空 dict = 都干净。

    两档都算口子：显式的 `statement_id` 形参，以及 `**kwargs`（后者能让调用方悄悄递进来，
    所以一样红 —— 这一档是加严，不是放宽）。
    """
    out: dict[str, list[str]] = {}
    for name, fn in (entries if entries is not None else _entries()).items():
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):  # pragma: no cover - 不可签名的对象不该出现在这张表里
            out[name] = ["拿不到签名 ⇒ 判不了（不是「干净」）"]
            continue
        bad: list[str] = []
        if "statement_id" in params:
            bad.append("形参里有 `statement_id`")
        bad += [f"有 `**{p}`（能悄悄收下任意关键字）" for p, v in params.items()
                if v.kind == v.VAR_KEYWORD]
        if bad:
            out[name] = bad
    return out


#: 一个具体的命题号（六位）。`## 依赖` 那张表的表头写的是 `stmt:NNNNNN`（字母占位）、
#: 稿头写的是 `stmt:（还没落号）` —— 那两处是格式，不是号，所以只认数字。
_STMT_NUMBER = re.compile(r"stmt:\d{6}")


def _handoff_violations(calls: list[dict]) -> list[str]:
    """F 交出去的那几笔调用里出现命题号 ⇒ 问题列表（空 = 干净）。

    `calls` 是打桩记录下来的 kwargs（B 的登记一笔 / V 的送审提示一笔）。
    """
    problems: list[str] = []
    for i, kw in enumerate(calls):
        if "statement_id" in kw:
            problems.append(f"第 {i + 1} 笔交出去的调用带了 `statement_id={kw['statement_id']!r}`")
        blob = json.dumps(kw, ensure_ascii=False, default=str)
        hit = _STMT_NUMBER.search(blob)
        if hit:
            problems.append(f"第 {i + 1} 笔交出去的调用里点了命题号 {hit.group(0)!r}")
    return problems


def _naming_problems(mid: str, sid: str, rel: str) -> list[str]:
    """稿名必须是稿号名、且不含命题号 ⇒ 问题列表（空 = 干净）。"""
    problems: list[str] = []
    if rel != f"reports/f-proof-{mid}.md":
        problems.append(f"稿名不是稿号名：{rel!r}（应为 reports/f-proof-{mid}.md）")
    if sid and sid in rel:
        problems.append(f"稿名里有命题号 {sid}：{rel!r} ⇒ 命名又按命题号了")
    return problems


# ================================================================== a 入口不吃命题号

def test_a_no_entry_takes_a_statement_number() -> None:
    """a：四个产稿/攻坚入口的参数表里没有 `statement_id`（也没有 `**kwargs` 那个后门）。"""
    bad = _entry_violations()
    assert bad == {}, (
        "F 的产稿/攻坚入口还收命题号 ⇒ 「对着某个命题号写证明」这条接口还在：\n"
        + "\n".join(f"  {k}: {'；'.join(v)}" for k, v in sorted(bad.items())))


@pytest.mark.parametrize("kw", [
    {"statement_id": SID},
    {"statement_id": ""},   # 空号也一样：口子的存在本身就是问题
])
def test_a2_passing_a_statement_number_is_a_type_error(kw: dict) -> None:
    """a2：正面读数 —— 递 `statement_id` 进去当场 `TypeError`（连空串也不行）。"""
    st = Store  # 只用来标注：下面用的是类上的函数对象
    got = None
    with pytest.raises(TypeError):
        AgentF.proof_manuscript(got, **kw)
    with pytest.raises(TypeError):
        AgentF.manuscript_path(**kw)
    with pytest.raises(TypeError):
        AgentF.publish_manuscript(got, **kw)
    with pytest.raises(TypeError):
        AgentF.promote_manuscript("notes/x.md", **kw)
    with pytest.raises(TypeError):
        FM.promote_manuscript(".", source="notes/x.md", **kw)
    assert st is Store


def test_a3_the_entry_table_is_not_empty() -> None:
    """a 的反真空另一半：五个入口都真的在表里（删空表不许冒充"都干净"）。"""
    names = set(_entries())
    assert names == {
        "AgentF.proof_manuscript", "AgentF.manuscript_path",
        "AgentF.promote_manuscript", "AgentF.publish_manuscript",
        "agent_f.manuscript.promote_manuscript"}, names
    for name, fn in _entries().items():
        assert callable(fn), name


# ================================================================== b 交出去的东西

class _Recorder:
    """把一次调用的参数记下来（原样转发给真实现，于是读数不是打桩造出来的）。"""

    def __init__(self, real) -> None:
        self.real = real
        self.calls: list[dict] = []

    def __call__(self, *args, **kwargs):
        self.calls.append(dict(kwargs))
        return self.real(*args, **kwargs)


def test_b_the_registration_handoff_carries_no_statement_number(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """b（B 那一侧）：`register_or_rewrite` 收到的 kwargs 里没有 `statement_id`。

    打桩记录调用参数 ⇒ 断言不含它；同时正面读数两格：`manuscript_id` 在、
    正文 sha 就是这一份正文的 sha（交接面 = 稿号 ＋ 正文）。
    """
    st = _ws(tmp_path)
    got = _round(st)
    rel = str(got["path"])
    body = _body(st, rel)
    assert rel == f"reports/f-proof-{MID}.md", got
    assert SID not in rel, rel

    passed = {"checked": True, "well_formed": True, "submittable": True,
              "problems": [], "refused": "", "reason": "判据打桩：形态合规"}

    def fake_gate(**_kw):
        return dict(passed)

    real_register = _PR.register_or_rewrite
    rec = _Recorder(lambda root, **kw: real_register(
        root, **{**kw, "gate": fake_gate}))
    monkeypatch.setattr(_PR, "register_or_rewrite", rec)

    f = _f(st)
    outlet = f._proof_outlet(_product(), {"sid": "s1", "text": PROPOSITION},
                             plan={"plan_id": PLAN},
                             proof_manuscript=str(got["text"]),
                             manuscript_id=MID)

    assert rec.calls, "产稿那一笔没有走登记入口 ⇒ 这一条没测到东西"
    kw = rec.calls[0]
    assert "statement_id" not in kw, (
        f"F 登记时向 B 递了命题号：{kw.get('statement_id')!r} ⇒ 「按命题号写稿」的口子回来了")
    assert _handoff_violations(rec.calls) == [], _handoff_violations(rec.calls)
    assert str(kw.get("manuscript_id") or "") == MID, kw
    assert str(kw.get("proof_text") or "").strip(), "交接里没有正文 ⇒ 只剩一个号，那不是稿"
    assert str(outlet.get("proof_sha256") or "") == _PR.proof_sha(body), outlet


def test_b2_the_review_hint_points_at_the_manuscript(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """b（V 那一侧）：送审提示那一笔的 kwargs 里没有 `statement_id`，提示里点的是稿路径。

    为什么盯 `next_step_hint`：F 不进程内送审（业主 2026-11-02：「F 不是直接能派 V 吗」），
    F 交出去的那一份就是这个字符串（`framework_summon` 的 `task`）。它若带
    `stmt:<号>`，就是"F 拿着收方的号去指认要审哪一份"。
    """
    st = _ws(tmp_path)
    got = _round(st)
    rel = str(got["path"])
    body = _body(st, rel)

    rec = _Recorder(FV.next_step_hint)
    monkeypatch.setattr(FV, "next_step_hint", rec)

    out = _f(st)._read_sign(statement_id=SID, proof_text=body, manuscript_path=rel)
    assert rec.calls, "读签那一格没有走到送审提示 ⇒ 这一条没测到东西"
    kw = rec.calls[0]
    assert "statement_id" not in kw, (
        "送审提示收到了命题号 ⇒ 那个号又成了 F 的输入（撤掉的正是它）："
        f"{kw.get('statement_id')!r}")
    assert _handoff_violations(rec.calls) == [], _handoff_violations(rec.calls)
    assert tuple(kw.get("manuscript_paths") or ())[0] == rel, kw

    hint = str(out.get("hint") or "")
    assert rel in hint, f"送审提示没有点稿路径：{hint!r}"
    assert f"stmt:{SID}" not in hint, f"送审提示点了命题号：{hint!r}"


# ================================================================== c 反真空（三条）

def test_c1_putting_the_number_back_into_an_entry_turns_a_red(monkeypatch) -> None:
    """c①：把 `statement_id` 加回任一入口 ⇒ a 红（不是"删空表就绿"）。"""
    assert _entry_violations() == {}

    def _publish_with_number(self, manuscript, *, statement_id: str = "",
                             manuscript_id: str = "") -> dict:
        return {}

    monkeypatch.setattr(AgentF, "publish_manuscript", _publish_with_number)
    bad = _entry_violations()
    assert "AgentF.publish_manuscript" in bad, bad
    assert any("statement_id" in x for x in bad["AgentF.publish_manuscript"]), bad

    # 顺带：`**kwargs` 那条后门也红（不然形参删了、口子换个形状又回来了）
    def _promote_with_kwargs(self, source: str, **kw) -> dict:
        return {}

    monkeypatch.setattr(AgentF, "promote_manuscript", _promote_with_kwargs)
    bad2 = _entry_violations()
    assert any("**kw" in x for x in bad2["AgentF.promote_manuscript"]), bad2


def test_c2_carrying_the_number_into_the_handoff_turns_b_red(monkeypatch) -> None:
    """c②：送审时偷偷带上 ⇒ b 红。

    两条路各一控：① 记录下来的 kwargs 里出现 `statement_id` ⇒ `_handoff_violations`
    非空；② 真按"带上"的写法调 `next_step_hint` ⇒ `TypeError`（签名里没有那一格）。
    """
    assert _handoff_violations([{"manuscript_paths": ("reports/f-proof-000123.md",)}]) == []
    dirty = [{"manuscript_paths": ("reports/f-proof-000123.md",),
              "statement_id": SID}]
    assert _handoff_violations(dirty), "夹带命题号的交接读数没被判红 ⇒ 这条判据是空的"
    assert _handoff_violations([{"task": f"审 stmt:{SID} 这一份"}]), (
        "交接文本里出现 `stmt:<号>` 也没被判红 ⇒ 这条判据是空的")

    with pytest.raises(TypeError):
        FV.next_step_hint({"state": "waiting"}, statement_id=SID,
                          manuscript_paths=("reports/f-proof-000123.md",))


def test_c3_naming_by_the_statement_number_turns_red(tmp_path: pathlib.Path) -> None:
    """c③：命名又按命题号 ⇒ 红。

    活体读数：`manuscript_path(稿号)` 就是稿号名，且不含命题号；
    控制：把"按命题号命名"的那个名字喂进同一判据 ⇒ 非空。
    """
    f = _f(_ws(tmp_path))
    rel = f.manuscript_path(MID)
    assert _naming_problems(MID, SID, rel) == [], (rel, _naming_problems(MID, SID, rel))
    assert MIN_WIDTH.search(rel.split("/")[-1].replace("f-proof-", "").split(".")[0]), rel

    wrong = f"reports/f-proof-{SID}.md"
    assert _naming_problems(MID, SID, wrong), "按命题号命名的稿名没被判红 ⇒ 这条判据是空的"
    # 空串/乱号不许冒充稿号（受控，不拼一个看起来像号的路径）
    assert f.manuscript_path("") == "", f.manuscript_path("")
    assert f.manuscript_path("abc") == "", f.manuscript_path("abc")


MIN_WIDTH = re.compile(r"^[0-9]{6}$")


# ================================================================== e 题面里的稿名

#: 题面里不许再出现的两个字面（p272 改命名之后：命题号不进稿名）。
_STALE_NAME_LITERALS: tuple[str, ...] = ("f-proof-<命题号>", "f-proof-<stmt")

#: 题面里必须出现的那个字面（稿号命名）。`你的稿号` / `稿号` 两种写法都认。
_NAME_LITERALS: tuple[str, ...] = ("f-proof-<你的稿号>", "f-proof-<稿号>")


def _f_surface() -> dict[str, str]:
    """F 的题面（渲染出来的那一份 ＋ 它的两本手册）＋ 共用段（几族共用同一段字）。"""
    from agentflow import agent_prompts as AP
    from agentflow import agent_skills as AS
    from agentflow.tools import build_registry

    out = {"prompt:F": AP.system_prompt("F", registry=build_registry().registry),
           "shared:PAPER_PACK": AP.PAPER_PACK}
    for s in AS.CATALOG.get("F") or ():
        out[f"manual:F/{s.slug}"] = str(s.body)
    return out


def _stale_name_problems(surfaces: dict[str, str]) -> dict[str, list[str]]:
    """题面里点名"按命题号命名的稿" ⇒ `{题面: [命中的字面…]}`；空 dict = 干净。"""
    out: dict[str, list[str]] = {}
    for name, text in surfaces.items():
        hits = [lit for lit in _STALE_NAME_LITERALS if lit in str(text)]
        if hits:
            out[name] = hits
    return out


def test_e_the_surface_never_names_a_manuscript_by_a_statement_number() -> None:
    """e：F 的题面（含共用段）里没有 `f-proof-<命题号>` / `f-proof-<stmt`，且写的是稿号名。

    为什么单列：命名改了、题面没改，模型会照着旧字面去找 / 去写一份不存在的稿 ——
    那正是"实现已通畅、教法还在按号"的形态（p272 的字面漏网）。
    """
    surfaces = _f_surface()
    bad = _stale_name_problems(surfaces)
    assert bad == {}, (
        "F 的题面还在教「按命题号命名的稿」：\n"
        + "\n".join(f"  {k}: {v}" for k, v in sorted(bad.items())))

    prompt = surfaces["prompt:F"]
    assert any(lit in prompt for lit in _NAME_LITERALS), (
        "F 的题面里读不出「稿名只按稿号」（`f-proof-<你的稿号>.md`）⇒ "
        "模型不知道自己的稿叫什么")
    assert "不用命题号、不用计划号" in prompt, prompt[:200]


def test_e2_the_name_literal_criterion_is_not_a_rubber_stamp() -> None:
    """e 的反真空：把旧字面喂进同一个读法 ⇒ 红（改回任一处就会被这一条抓住）。"""
    clean = {"prompt:F": "落成 `reports/f-proof-<你的稿号>.md`"}
    assert _stale_name_problems(clean) == {}
    assert _stale_name_problems(
        {"prompt:F": "正文走手稿（`F.step` 落 `reports/f-proof-<命题号>.md`）"}), (
        "旧字面 `f-proof-<命题号>` 没被判红 ⇒ 这条判据是空的")
    assert _stale_name_problems({"manual:F/x": "- 载体：`reports/f-proof-<stmt>`"}), (
        "旧字面 `f-proof-<stmt` 没被判红 ⇒ 这条判据是空的")


# ================================================================== e3 全仓字面白名单

#: 全仓白名单：两族旧字面只许留在这几个文件里，逐条写「为什么留」与「该文件几条」。
#:
#: 口径（业主 2026-11-10 裁定「F 的稿自己维护一套号源」）：源码里的说明文字按稿号写；
#: 旧字面只许留在四档：`历史`（讲某次事故 / 旧行为，就地已注明「2026-11-10 后：稿
#: 按稿号命名」）· `文档`（文档层，待到文档批统一）· `待裁`（本 lane 碰不了或要重冻
#: 的那几行，理由写在条目里）。`判据` 与 `冻结` 两档不在扫描面上，见下面那一段。
#:
#: 为什么按「文件 + 条数」而不是「文件 + 行号」：本仓库并行开发，行号几十分钟就漂
#: （`AGENTS.md` 自己记过这一条）。条数照样抓得住「把任一处改回旧字面」——那些路径
#: 要么不在表里（0 → 1），要么条数会变；行号只在判据红时作为读数打出来。
_REPO_LITERAL_WHITELIST: dict[str, tuple[int, str, str]] = {
    # ---- 文档层（不是本批的处理面：本批只动源码 docstring / 注释）
    "agentflow/docs/AUDIT-VSIGN-CHANNELS-AND-PROMPTS-2026-11-04.md": (
        1, "历史", "2026-11-04 的审计记录，写的是当时的口径"),
    "agentflow/docs/ROLE-SPECS.md": (
        2, "文档",
        "F 写集那一段（:279）与 F-7（:1150，自带「2026-10-27 口径」标注）；待到文档批统一"),
    # ---- 源码：历史记录（保留原文，就地已注明现行口径）
    "agentflow/src/agentflow/agent_b/register_statement.py": (
        2, "历史",
        "两处都是历史记账，活口径都已在紧邻的下一段按稿号写明：① 2026-10-26「三段传递"
        "路径」的读数（下一行就是「2026-11-10 后：稿按稿号命名 —— 这两种旧名只读兼容」）；"
        "② 2026-11-10 在册闸认稿号那一批留下的「改前这里只给 `statement_ids`…」那句"
        "（下一段就是现口径「先读这一行上记的 `manuscript_id`，行上没有才退回旧名」）。"
        "两处讲的都是改前的行为，不是现在要照着做的口径 ⇒ 照现值记 2 条"),
    "agentflow/src/agentflow/agent_f/core.py": (
        1, "历史", "点名「被停掉的旧口径」，同一句已写明收方现在按稿号读盘"),
    "agentflow/src/agentflow/agent_f/manuscript.py": (
        1, "历史", "publish_manuscript 的旧改名口径；紧接的下一句就是现行稿号口径"),
    # 2026-11-20（PROMPTHIST）：这一行原先登记的是 `src/agentflow/agent_prompts.py`（4 条，
    # 业主明示保留的变更日志）。那 4 条全在版本账里，而账已整块逐字节搬进
    # `docs/PROMPT-HISTORY.md` ⇒ 登记跟着账走：源码那一格现在一处命中都没有（留着它
    # 会被判成"登记过期"），文档那一格照现值记 4 条。
    "agentflow/docs/PROMPT-HISTORY.md": (
        4, "历史",
        "2026-11-20 版本账整块从 `agent_prompts.py` 搬进这份文档（逐字节）："
        "那 4 处是账里的变更记录，讲的是改前的旧稿名字面，就地保留；账不是活文案"),
    "agentflow/src/agentflow/depsection.py": (
        1, "历史",
        "ramsey-4-4-87 真机读数；同一段已就地在上面注明 2026-11-10 后稿按稿号命名"),
    # ---- 源码：本 lane 碰不了 / 要重冻的那几行（见报告「要业主再裁的」）
    "agentflow/src/agentflow/agent_v/core.py": (
        1, "待裁",
        "另一条 lane 在飞（agent_v/core.py 有未提交改动），本 lane 不碰；这句拒信里"
        "的旧名还没按 2026-11-10 口径改"),
    "agentflow/src/agentflow/tools/verify_tools.py": (
        1, "待裁",
        "冻结工具面：这一格是 verify.verify_proof 的参数说明，改它要重冻 "
        "tests/golden/tool_surface_snapshot.json 与 tests/fixtures/tool_declaration_baseline.json"
        "（FC-27 eval-criteria）⇒ 本批停手"),
    # 2026-11-12：`agentflow/src/agentflow/proofregistry.py` 那一行（1 条、待裁）从
    # 白名单删除 —— 稿号口径那一笔（f032093b）已把模块 docstring 的
    # `reports/f-proof-<命题号>.md` 改成 `reports/f-proof-<稿号>.md`，盘上一处旧字面
    # 都没有了（等额纪律的「登记过期」一档）。断言未动：仍是"白名单之外一处不许有、
    # 白名单之内条数必须相等"。
}

#: 扫描面要排除的目录：`agentflow/tests/` 是判据本体与负控夹具的家 —— e / e2 就在那里
#: 拿旧字面当负控针（`_STALE_NAME_LITERALS` / `F_OLD`），把测试面纳入扫描等于让这条
#: 判据判它自己。测试文件里有没有新的旧口径描述，由各自那一份判据与 review 管。
_SCAN_EXCLUDE_PREFIXES: tuple[str, ...] = ("agentflow/tests/",)


def _git_grep_fixed(literal: str) -> list[tuple[str, int, str]]:
    """`git grep -n -F` 全仓扫一个字面 ⇒ `[(仓库根相对路径, 行号, 整行)]`。

    三态纪律：退出码 1 = 查过了、没有（空表）；其它非 0 = 没查成（抛，
    不许折成"干净"）。不 skip：这不是可选步骤。
    """
    import subprocess

    root = pathlib.Path(__file__).resolve().parents[2]
    top = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert top.returncode == 0, (
        f"`git rev-parse --show-toplevel` 没查成（退出码 {top.returncode}）："
        f"{top.stderr.strip()[:300]} —— 这条判据不知道仓库根在哪，本次没有真正检查")
    # 2026-11-20（PROMPTHIST）：加 `--untracked`。`git grep` 默认只看「已跟踪」文件，
    # 于是"新落一份文档/一段账、还没 `git add`"的那一窗里，它在这条判据的扫描面上等于
    # 不存在 —— 而本仓已经在 `scripts/noai_gate.py --git` 上踩过同一个坑并写明
    # （`AGENTS.md`：`git diff` 只报已跟踪文件，所以在清单登记过的路径上新建文件同样
    # 看不见）。这一改只加宽扫描面（更严），不搬动任何白名单条数；被 ignore 的文件
    # （`temp/`）仍不在面上。
    proc = subprocess.run(
        ["git", "grep", "--untracked", "-n", "-F", literal],
        cwd=top.stdout.strip(), capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    if proc.returncode == 1:
        return []
    assert proc.returncode == 0, (
        f"`git grep` 没查成（退出码 {proc.returncode}）：{proc.stderr.strip()[:300]}")
    out: list[tuple[str, int, str]] = []
    for line in proc.stdout.splitlines():
        path, _, rest = line.partition(":")
        num, _, text = rest.partition(":")
        if not num.isdigit():
            continue
        if path.startswith(_SCAN_EXCLUDE_PREFIXES):
            continue
        out.append((path, int(num), text))
    return out


def _repo_stale_hits() -> dict[tuple[str, int], str]:
    """扫描面上两族旧字面 ⇒ `{(路径, 行号): 整行}`（同一行命中两族只记一次）。"""
    hits: dict[tuple[str, int], str] = {}
    for literal in _STALE_NAME_LITERALS:
        for path, num, text in _git_grep_fixed(literal):
            hits.setdefault((path, num), text)
    return hits


def _hits_by_path(hits: dict[tuple[str, int], str]) -> dict[str, list[int]]:
    """`{(路径, 行号): …}` ⇒ `{路径: [行号…]}`（升序；只用于读数与逐文件比条数）。"""
    out: dict[str, list[int]] = {}
    for path, num in hits:
        out.setdefault(path, []).append(num)
    return {path: sorted(nums) for path, nums in out.items()}


def _whitelist_problems(hits: dict[tuple[str, int], str]) -> list[str]:
    """观测到的命中分布与白名单逐文件比 ⇒ 差异描述（空表 = 只剩该留的）。

    三个方向都报：白名单外的文件 / 条数对不上的文件 / 白名单里已经没有命中的文件。
    比条数（而不是比行号）是因为行号在并行开发下会漂；而条数仍然抓得住
    「新加一处旧字面」——那一定让某个文件的条数变。
    """
    seen = _hits_by_path(hits)
    problems: list[str] = []
    for path in sorted(set(seen) | set(_REPO_LITERAL_WHITELIST)):
        want = _REPO_LITERAL_WHITELIST.get(path)
        got = seen.get(path, [])
        if want is None:
            problems.append(f"{path}: 白名单之外（命中行 {got}）")
        elif not got:
            problems.append(
                f"{path}: 白名单里有，盘上一处命中都没有了（旧字面被改掉，或者登记过期）")
        elif len(got) != want[0]:
            problems.append(
                f"{path}: 白名单写 {want[0]} 条，盘上有 {len(got)} 条（命中行 {got}）"
                f"；档：{want[1]}；理由：{want[2]}")
    return problems


def test_e3_the_old_literal_only_survives_where_it_is_logged() -> None:
    """e3：扫描面（全仓去掉 `agentflow/tests/`）上两族旧字面 ⇒ 白名单之外不许有。

    为什么不扫 `tests/`：那一面是判据本体与负控夹具的家（`_STALE_NAME_LITERALS`、
    `F_OLD` 都拿旧字面当针），把它纳入等于让判据判自己；测试文件里的旧口径描述由
    各自那一份判据与 review 管。

    反真空三条（都打在同一条判据函数上）：① 白名单之外多一个文件 ⇒ 红；② 白名单
    内的文件多一处 ⇒ 红（条数变了）；③ 白名单里那一处被改掉 ⇒ 也红（惰性白名单
    同样要报，否则这张账可以越挂越多而没人看）。
    """
    hits = _repo_stale_hits()
    assert hits, (
        "扫描面上一处旧字面都没扫到 ⇒ 要么 `git grep` 没查成、要么判据的对象没了 —— "
        "这不是干净（三态：没查成 ≠ 查过了没问题）")
    assert len(_REPO_LITERAL_WHITELIST) >= 8 and sum(
        n for n, _kind, _why in _REPO_LITERAL_WHITELIST.values()) >= 10, (
        "白名单短得不像话（文件或条数）⇒ 先查是不是扫描口径被改窄了（改窄等于放宽这一条）")
    problems = _whitelist_problems(hits)
    assert problems == [], (
        "旧字面分布与白名单对不上：\n  " + "\n  ".join(problems)
        + "\n\n逐条重看它是哪一档；档与理由都对不上就改口径，对得上才照现值更新白名单。")

    injected = dict(hits)
    injected[("agentflow/src/agentflow/agent_f/nowhere.py", 1)] = "落成一份按旧号命名的稿"
    assert _whitelist_problems(injected), (
        "白名单之外新增一个文件没被判红 ⇒ 这条判据是空的")
    bumped = dict(hits)
    bumped[("agentflow/src/agentflow/agent_f/core.py", 424242)] = "又一处旧名"
    assert _whitelist_problems(bumped), (
        "白名单内的文件多出一处旧字面没被判红 ⇒ 条数那一半没在核")
    dead = dict(hits)
    dead.pop(sorted(hits)[0])
    assert _whitelist_problems(dead), (
        "白名单里的死条目没被报出来 ⇒ 这张账只会长、不会缩")


# ================================================================== d 端到端五段

def test_d_the_whole_chain_reads_five_ways(tmp_path: pathlib.Path) -> None:
    """d：稿号 → 送审签出 → 收录现取命题号 → 稿上签块 → V 台账（五段读数都在）。

    与 `temp/_f_chain_rehearsal.py` 同一条链（那一趟是脚本化真跑）；这里把它钉成判据：
    模型那一侧全由夹具给（零调用），store 是真的。
    """
    from conftest import sign_before_registration

    st = _ws(tmp_path)
    root = pathlib.Path(st.root)

    # ---- ① F 自己的稿号（不借命题号、不借计划号）
    #
    # 这里不断言「稿号 ≠ 命题号」：那是两套独立编号，数值重合不代表任何东西
    # （2026-11-11 业主裁定：「这是两套编号，数值重合不能代表什么」）。
    # 语义上的分离靠这三格：稿号由 `manuscriptids` 的计数器发、行上另记 `manuscript_id`、
    # 签块第 9 格按稿名现算 —— 下面逐格断，不靠两个数字长得不一样。
    before_manuscript = MI.peek_manuscript_counter(root)
    mid = MI.next_manuscript_id(root)
    assert MIN_WIDTH.match(mid), mid
    assert MI.peek_manuscript_counter(root) == before_manuscript + 1, (
        "稿号不是由 F 自己的计数器发的", before_manuscript, MI.peek_manuscript_counter(root))

    # ---- ② F 产稿：稿名只由稿号决定，稿头如实写「还没落号」
    made = _round(st, mid)
    rel = str(made["path"])
    assert rel == f"reports/f-proof-{mid}.md", made
    assert _naming_problems(mid, SID, rel) == [], rel
    raw = (root / rel).read_text(encoding="utf-8")
    # 业主 2026-11-13：稿里没有命题号 ⇒ F 的稿上连占位都不写。
    assert "- 命题号：" not in raw, raw[:200]
    assert SID not in raw, "F 的稿上出现了命题号 ⇒ 那一步又按号写了"

    # ---- ③ 送审签出：V 的签按正文 sha 落 pending（还没有号也能签）
    body = _DS.proof_body(raw).strip("\n")
    sha = _PR.proof_sha(body)
    _stamp(st, rel, sha)
    pend = sign_before_registration(st.root, proof_text=body)
    assert pend.get("proof_sha256") == sha or pend.get("sha") == sha, pend
    block = VS.manuscript_sign_reading(
        (root / rel).read_text(encoding="utf-8"), manuscript_path=rel)
    assert block.get("found") is True and block.get("signed") is True, block
    assert block.get("manuscript_id") == mid, block

    # ---- ④ 收录：B 现取命题号（与稿号无关），行上记 manuscript_id
    out = AgentB(st, extractor=None, extract_text=None).register_statement(
# 2026-11-17（语义纠正）：`derived_from` / `source_lit_id` 是可选信息（`origin` 只是状态：自产/引用）；这一份夹具不测来路。
        statement_full=PROPOSITION, origin="own_result", derived_from=["999999"], kind="conjecture",
        proof_manuscript=rel, label="DCT", line_range={"start": "1", "label": rel},
        quote_reason="判据：F 只认稿号")
    assert out.get("ok") is True, out
    stmt_id = str(out.get("stmt_id") or "")
    assert MIN_WIDTH.match(stmt_id), out
    # 收录时不拿「两号数值不等」当证据（它们允许重合，2026-11-11 业主裁定）。
    # 语义分离由下面三格断：行上记的是稿号、稿名没变、签仍按稿号认。
    row = next(dict(r) for r in st.rows("statements")
               if str(r.get("stmt_id")) == stmt_id)
    assert str(row.get("manuscript_id") or "") == mid, row
    assert int(row.get("proof_no") or 0) == 1, row

    # ---- ⑤ 稿名不变 + V 台账读得出来
    assert (root / rel).is_file(), rel
    # 两号允许数值重合 ⇒ 不能拿"f-proof-<命题号>.md 不存在"当证据
    # （重合时它正是那一份合法的稿）。要断的是「没有另存一份按命题号命名的副本」：
    # 那个路径要么不存在，要么就与稿号那一份是同一个文件（== 两号重合）。
    renamed = root / "reports" / f"f-proof-{stmt_id}.md"
    assert (not renamed.exists()) or mid == stmt_id, (
        "收录按命题号另存了一份稿 ⇒ 停用的转名口径回来了", renamed, mid, stmt_id)
    assert (root / rel).is_file(), rel
    texts, problems = VR.list_verifications(st.root, statement_id=stmt_id, limit=None)
    assert not problems, problems
    assert len(texts or []) >= 1, ("V 的台账一条都没读到", texts, problems)


# --------------------------------------------------------------- e 两号数值重合
def test_e_the_two_number_spaces_are_allowed_to_coincide(tmp_path: pathlib.Path) -> None:
    """e：稿号与命题号数值重合是合法的，整条链照样成立。

    业主 2026-11-11 逐字：「稿号与命题号都从 000000 起没有问题，这是两套编号，
    数值重合不能代表什么。」⇒ 判据不许再拿"两个数字长得不一样"当分离的证据。

    这一条刻意让两边都取到同一个字面：新工作区里 `manuscriptids` 与 `statements`
    两个号段都从 0 起，所以第一次产稿 + 第一次收录，两号天然都是 000000。
    仍旧成立的那三件：行上记 `manuscript_id`、稿名不变、签按稿号认。
    """
    from conftest import sign_before_registration

    st = _ws(tmp_path)
    root = pathlib.Path(st.root)
    mid = MI.next_manuscript_id(root)          # 第一次取号 ⇒ 000000
    made = _round(st, mid)
    rel = str(made["path"])
    assert rel == f"reports/f-proof-{mid}.md", made
    assert SID not in rel, rel

    body = _body(st, rel)
    sha = _PR.proof_sha(body)
    _stamp(st, rel, sha)
    pend = sign_before_registration(st.root, proof_text=body)
    assert pend.get("proof_sha256") == sha or pend.get("sha") == sha, pend
    out = AgentB(st, extractor=None, extract_text=None).register_statement(
        statement_full=PROPOSITION, origin="own_result", derived_from=["999999"], kind="conjecture",
        proof_manuscript=rel, label="DCT", line_range={"start": "1", "label": rel},
        quote_reason="判据：两号数值重合也允许")
    assert out.get("ok") is True, out
    stmt_id = str(out.get("stmt_id") or "")

    # 这一条测的正是「重合」这一形态本身：不重合就说明夹具没造出这个现场。
    assert stmt_id == mid, ("这一条要的现场是两号数值重合（都从 000000 起）",
                            stmt_id, mid)

    row = next(dict(r) for r in st.rows("statements") if str(r.get("stmt_id")) == stmt_id)
    assert str(row.get("manuscript_id") or "") == mid, row
    assert (root / rel).is_file(), rel
    block = VS.manuscript_sign_reading(
        (root / rel).read_text(encoding="utf-8"), manuscript_path=rel)
    assert block.get("signed") is True, block
    assert block.get("manuscript_id") == mid, block
    texts, problems = VR.list_verifications(st.root, statement_id=stmt_id, limit=None)
    assert not problems, problems
    assert len(texts or []) >= 1, ("重合形态下 V 台账读不出来", texts, problems)

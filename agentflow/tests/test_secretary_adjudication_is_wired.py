# -*- coding: utf-8 -*-
"""判据：秘书判命题那一条链必须真的接上缝（真机 sylow5 的"实现了但没接线"）。

## 缺陷（2026-10-26，真机 `projects/sylow5` 已停，本次只读复算）

```
out/secretary/proposition_verdicts.jsonl 不存在（判词一次都没跑）
会话里 proposition_identity 命中 0 次、role=secretary 的调用 0 次
后果：9 条命题里 proof_no 非 None 的 0 条；同一条定理被登记 2–3 次
```

根因钉在 `secretary.judge()` 的第 2 道闸：

```python
if self.seam is None:
    return {"checked": False, "reason": "没有装配模型缝（本智能体自己的 llmseam）⇒ 这一格没查成"}
```

而全仓的 `Secretary(...)` 构造点一个都没传 `seam=`，于是每一次判词都走"没缝"那一支、
静默退回机械判据（那三条的相似度只有 0.15–0.33 ⇒ 判 different ⇒ 反复新建）。
单测一直是绿的，因为每一处判据都自己塞了一条假的缝（`_FakeSeam`）——
断的不是判据，是装配线。`llmseam.LlmSeam.for_secretary` 早就造好了，只是没人用。

## 这一份钉的五条（每条都要"改前红"）

| 条 | 它要证明的事 | 改前为什么是红的 |
|---|---|---|
| a | 不传 `seam=`（真机形态）⇒ 返回里有 `proposition_adjudication = {checked: False, …}`，原因含"没有装配模型缝" | 改前返回里根本没有这一格（只有平铺的 `checked`/`reason`，旁边紧挨着 `verdict`/`basis` 那组判词） |
| b | 传了真缝（打桩计数）⇒ 真的发了一次 `proposition_identity` 调用，且 `checked=True` | 改前没有这一格可断言（`proposition_adjudication` 不存在）；调用本身能发生，但没有任何一格说它发生过 |
| c | 同一条正文第二次 ⇒ 只调一次（缓存生效，`reused=True`） | 同上（`reused` 只在 `adjudicate_proposition` 里，没透到"判了没有"那一格） |
| d | 四条路各自都能拿到缝：`table_tools` 直写路由 / `conductor_tools` 名册 / `conductor` 登记 / `agent_b` 登记 | 改前四条路的构造点都没传 `seam=`（`tools/table_tools.py`、`tools/conductor_tools._roster_secretary`、`conductor._escalation_roster_check`、`agent_b/core._statement_secretary`）⇒ 各自 0 次调用 |
| e | 反真空：把 `LlmSeam.for_secretary` 打桩成返回 `None` ⇒ a 的表现必须出现，而不是静默 | 改前没有"缝从哪来"这一档：装配处拿到 `None` 时除了 `judge` 里那句平铺的 `checked=False` 之外没有任何读数 |

## 边界

全部 tmp 工作区、零真实模型调用（`tests/conftest.py` 把 `AGENTFLOW_SETTINGS` 钉到一份
不存在的设置文件，于是 `LlmSeam.for_secretary` 造出来的是空缝 ⇒ `seam_for_secretary`
返回 `None` + 一句读数；要"有缝"的那几条由 `_CountingSeam` 顶替，它只做一件事：
把材料读回来、回一个 `proposition_identity` 的判词，并把每一次调用记在 `calls` 里）。
不读写 `projects/`。
"""
from __future__ import annotations

import pathlib
import re
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import conductor as COND
from agentflow import llmseam
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow.agent_b import AgentB
from agentflow.secretary import Secretary, for_role_wired
from agentflow.store import Store
from agentflow.tools import conductor_tools, table_tools
from agentflow.tools.base import ToolRegistry

#: 命题正文（三态判定的样本）；判词由打桩的缝给，判据不依赖真实模型。
FULL = "设 G 是有限群，p 是素数；则 G 的 Sylow p-子群存在且两两共轭。"
FULL_2 = "设有限群 G 的阶为 p^a m（p 不整除 m）；则 G 有 p^a 阶子群，且它们构成一个共轭类。"
LABEL = "Sylow I（存在性）"
#: `judge` 落台账时用的那一句 `note`（"这一类判断发没发过"的唯一机器读数）。
NOTE = "secretary:proposition_identity"


# ------------------------------------------------------------------ 夹具与小工具

def _ws(base: pathlib.Path, name: str = "ws") -> Store:
    """一个 tmp 工作区（`Store.init()` 之后表都在，零外部依赖）。"""
    st = Store(base / name)
    st.init()
    return st


class _Call:
    """`llmseam.SeamCall` 的最小替身（`judge` 只读 `ok` / `problem` / `detail`）。"""

    ok = True
    problem = ""
    detail = ""


class _CountingSeam:
    """打桩的秘书缝：只实现 `judge` 用到的那一件事（`ask_json`），并把调用记下来。

    `wired=True` 是必须的：`secretary.seam_for_secretary` 会把"造出来但是空缝"那一条
    折成 `None`（否则 `attempted` 会把"从来没有判断面"写成"试过了、没成"）。
    """

    wired = True

    def __init__(self, *, verdict: str = "different", same_as: str = ""):
        self.verdict = str(verdict)
        self.same_as = str(same_as)
        self.calls: list[str] = []
        self.materials: list[dict] = []

    def ask_json(self, prompt, **kw):
        self.calls.append(str(kw.get("note") or ""))
        self.materials.append(_material(prompt))
        return ({"decision": self.verdict, "same_as": self.same_as,
                 "canonical_name": "Sylow I", "route": "",
                 "condition": "打桩：条件未读", "conclusion": "打桩：结论未读",
                 "reason": f"打桩：恒判 {self.verdict}", "basis": [f"打桩：{self.verdict}"]},
                _Call())


def _material(prompt: str) -> dict:
    """从 `_judge_material` 渲染出的那条 user 消息里把材料 JSON 读回来。"""
    import json

    text = str(prompt or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return {}


class _for_secretary_stub:
    """把 `LlmSeam.for_secretary` 换成"返给我这一条"（上下文管理器，结束时还原）。

    为什么要换这一层而不是换 `secretary.seam_for_secretary`：这一份钉的正是
    "装配处会去 `llmseam` 要一条缝"这件事（真机 sylow5 的断点就在那里），
    把桩打在 `for_secretary` 上，装配处走的仍是生产代码。
    """

    def __init__(self, seam):
        self.seam = seam
        self._old = None

    def __enter__(self):
        self._old = llmseam.LlmSeam.for_secretary

        def _stub(cls, **_kw):
            return self.seam

        llmseam.LlmSeam.for_secretary = classmethod(_stub)
        return self.seam

    def __exit__(self, *exc):
        llmseam.LlmSeam.for_secretary = self._old
        return False


def _own(full: str, label: str = LABEL) -> dict:
    """自产命题的必填件（`doc_id` + `quote_reason`；首登按猜想）。"""
    return {"statement_full": full, "statement_text": full[:24], "label": label,
            "origin": "own_result", "kind": "conjecture",
            "doc_id": S.format_id(0), "quote_reason": "我方自产命题，没有外部引文要比对"}


def _adj(got: dict) -> dict:
    """判定返回值里那一格"判了没有"（缺了就是缺陷本身，所以不 `.get` 兜底成 `{}`）。"""
    assert "proposition_adjudication" in got, (
        f"返回值里没有 `proposition_adjudication` 这一格（现有键：{sorted(got)}）")
    return dict(got["proposition_adjudication"])


# ============================================================ a：没缝必须看得见


def test_without_a_seam_the_unjudged_grid_is_visible(tmp_path):
    """a：不传 `seam=`（真机形态）⇒ `checked=False` + 原因含"没有装配模型缝"。

    改前红：改前 `adjudicate_proposition` 的返回值里没有 `proposition_adjudication`
    这一格 —— 只有平铺的 `checked` / `reason`，而它们旁边紧挨着 `verdict` / `basis`
    那一组判词，读的人（尤其是只看工具返回的模型）很容易读成"判过了，结论 unknown"。
    """
    st = _ws(tmp_path)
    sec = Secretary("B", root=st.root, store=st)          # ← 真机形态：没传 seam=
    assert sec.seam is None, "这一条的前提是'没有缝'"
    got = sec.adjudicate_proposition({"statement_full": FULL, "label": LABEL,
                                      "kind": "theorem"})
    grid = _adj(got)
    assert grid["checked"] is False, grid
    assert grid["attempted"] is False, grid
    assert "没有装配模型缝" in grid["reason"], grid
    # 裸造的秘书没有"缝从哪来"的读数（空串 = 这一名秘书是裸造的）
    assert grid["seam_source"] == "", grid
    # 判不了不等于没返回值：判定本身仍然走完（三态 + 候选表），只是没查成。
    assert got["checked"] is False and got["verdict"] == "unknown", got


def test_record_statement_also_surfaces_the_unjudged_grid(tmp_path):
    """a（续）：`record_statement` 的返回也透出同一格 —— 否则模型以为秘书判过了。

    改前红：`record_statement` 的 `out` 里没有 `proposition_adjudication`（
    它的初始字典里也没有这一格），于是"这一笔根本没判"在工具的返回值上不可见。
    """
    st = _ws(tmp_path)
    sec = Secretary("B", root=st.root, store=st)
    got = sec.record_statement(_own(FULL), role="B")
    assert got.get("created") is True, got
    grid = _adj(got)
    assert grid["checked"] is False, grid
    assert "没有装配模型缝" in grid["reason"], grid
    # 落盘照旧（"判不了"不许把写路径堵死：业主 2026-10-24 的 fail-open 口径）
    assert str(got.get("stmt_id") or ""), got


# ============================================================ b：有缝就真判一次


def test_a_wired_secretary_really_issues_one_proposition_identity_call(tmp_path):
    """b：传了真缝（打桩计数）⇒ 真的发了一次 `proposition_identity`，且 `checked=True`。

    改前红：改前没有 `proposition_adjudication` 这一格可断言 —— 这一条钉的是
    "调用真的发生过"这个事实必须有一格读数，而不是只活在假缝的 `calls` 里。
    """
    st = _ws(tmp_path)
    seam = _CountingSeam()
    # 装配口给的缝（`for_role_wired` 会把"缝从哪来"记进 `model_source`）
    sec = for_role_wired("B", root=st.root, store=st, seam=seam)
    got = sec.adjudicate_proposition({"statement_full": FULL, "label": LABEL,
                                      "kind": "theorem"})
    assert seam.calls == [NOTE], seam.calls
    grid = _adj(got)
    assert grid["checked"] is True, grid
    assert grid["attempted"] is True, grid
    assert grid["verdict"] == "different", grid
    # 缝从哪来那一格：调用方给的缝
    assert grid["seam_source"] == "body（调用方给的缝）", grid
    # 判词也真的落到了返回值上（不是"判了但没带回结论"）
    assert got["checked"] is True and got["canonical_name"] == "Sylow I", got


def test_the_same_text_twice_costs_one_call(tmp_path):
    """c：同一条正文第二次 ⇒ 只调一次（缓存生效，`reused=True`）。

    改前红：`reused` 只在 `adjudicate_proposition` 的平铺返回值里，而"判了没有"那一格
    不存在 ⇒ 没有任何一格能同时回答"判过、没花钱"。
    """
    st = _ws(tmp_path)
    seam = _CountingSeam()
    sec = Secretary("B", root=st.root, store=st, seam=seam, enable_model=True)
    first = sec.adjudicate_proposition({"statement_full": FULL, "kind": "theorem"})
    second = sec.adjudicate_proposition({"statement_full": FULL, "kind": "theorem"})
    assert len(seam.calls) == 1, f"同一条正文被判了 {len(seam.calls)} 次：{seam.calls}"
    assert _adj(first)["reused"] is False, first
    assert _adj(second)["reused"] is True, second
    assert _adj(second)["checked"] is True, second


# ============================================================ d：四条路都要拿到缝


def test_the_table_tools_direct_write_route_wires_the_seam(tmp_path):
    """d-①：`table.create(table="statements")` 的直写路由（`tools/table_tools.py`）。

    改前红：那一行是 `sec = Secretary(role, root=ctx.store.root, store=ctx.store)`
    —— 没传 `seam=` ⇒ 0 次 `proposition_identity` 调用。
    """
    st = _ws(tmp_path)
    seam = _CountingSeam()
    reg = ToolRegistry(name="tables")
    reg.bound_role = "A"
    table_tools.register(reg, store=st)
    with _for_secretary_stub(seam):
        with COND.calling_as(S.format_id(0), "B"):
            made = reg.call("table.create", table="statements", row=_own(FULL))
    assert made.ok, (made.error, made.meta)
    assert seam.calls == [NOTE], f"直写路由没有把缝接上：{seam.calls}"
    detail = dict((made.data or {}).get("detail") or {})
    grid = _adj(detail)
    assert grid["checked"] is True, grid
    assert grid["seam_source"] == "secretary（LlmSeam.for_secretary）", grid


def test_the_conductor_tools_roster_route_wires_the_seam(tmp_path):
    """d-②：`conductor_tools._roster_secretary`（名册 / 销号那条路的现造支）。

    改前红：那一支走 `secretary.for_role(...)`（不传 `seam=`）⇒ 这一名秘书没有判断面。
    销号那条链今天只读名册、不判命题，但装配点漏 `seam=` 正是 sylow5 的根因形态。
    """
    st = _ws(tmp_path)
    seam = _CountingSeam()

    class _BareConductor:
        """两档都没接的 conductor（真机里只有裸装的那一条才会走到现造支）。"""

    with _for_secretary_stub(seam):
        sec = conductor_tools._roster_secretary(_BareConductor(), st)
    assert sec.seam is seam, f"名册秘书的缝不是装配来的那一条：{sec.seam!r}"
    assert sec.model_source == "secretary（LlmSeam.for_secretary）", sec.model_source
    # 现造的那一名秘书的台账落在同一个工作区（口径没漂）
    assert pathlib.Path(str(sec.root)) == pathlib.Path(str(st.root))
    # 这一条路自己不出判词，但它手里那条缝必须是能判的（b 那一条已在别处钉住）：
    got = sec.adjudicate_proposition({"statement_full": FULL, "kind": "theorem"})
    assert seam.calls == [NOTE], seam.calls
    assert _adj(got)["checked"] is True, got


def test_the_conductor_registration_route_wires_the_seam(tmp_path):
    """d-③：`conductor._escalation_roster_check`（`Conductor` 的登记/寻址那条路）。

    改前红：那一行是裸的 `Secretary(...)`（没传 `seam=`），而且 `addressing` 里
    没有任何一格说"这一名秘书是哪条缝"。
    """
    st = _ws(tmp_path)
    seam = _CountingSeam()
    cond = COND.Conductor(st)
    with _for_secretary_stub(seam):
        addr = cond._escalation_roster_check(
            mine=S.format_id(0), to=S.format_id(1), who="F", root=str(st.root))
    assert addr.get("secretary_seam") == "secretary（LlmSeam.for_secretary）", addr


def test_the_agent_b_registration_route_wires_the_seam(tmp_path):
    """d-④：`agent_b.register_statement` → `core._statement_secretary`（B 的入库正路）。

    这是真机 sylow5 断掉的那一条：B 的秘书是 `AgentB` 现派生的，改前走
    `for_role("B", root=..., store=...)`（不传 `seam=`、也没开 `enable_model`）
    ⇒ 判词一次都没发生 ⇒ 9 条命题里 `proof_no` 非 None 的 0 条。
    """
    st = _ws(tmp_path)
    seam = _CountingSeam()
    with _for_secretary_stub(seam):
        b = AgentB(st, extractor=None, extract_text=None, config={})
        got = b.register_statement(**_own(FULL), proof_text="证明：由类方程直接得。")
    assert got.get("ok"), got
    assert seam.calls == [NOTE], f"B 的登记支没有把缝接上：{seam.calls}"
    # `register_statement` 透出的是 `adjudication`（那一趟的逐字读数）：三态 + 缝从哪来
    adj = dict(got.get("adjudication") or {})
    assert adj.get("checked") is True, adj
    assert adj.get("seam_source") == "secretary（LlmSeam.for_secretary）", adj
    # 真机 sylow5 缺的就是这一份台账：判词一次都没跑 ⇒ 文件根本没被建出来
    ledger = SEC.proposition_verdict_of(st.root, FULL)
    assert ledger, "命题判定台账没落盘（真机 sylow5 缺的就是这一份）"
    assert str(ledger.get("verdict") or "") == "different", ledger
    # 同一份正文再交一次 ⇒ 一行都不新增（判词沿用缓存、老口径查重各自生效）
    with _for_secretary_stub(seam):
        again = b.register_statement(**_own(FULL), proof_text="证明：由类方程直接得。")
    rows = list(st.rows("statements"))
    assert len(rows) == 1, f"同一条正文登记出了 {len(rows)} 行"
    assert (again.get("ok")
            or str(again.get("kind") or "") == "duplicate_statement"), again
    # 第二次没有为同一段正文再买一次判词（进程内缓存 + 盘上台账一起生效）
    assert seam.calls == [NOTE], f"同一段正文买了 {len(seam.calls)} 次判词：{seam.calls}"


# ============================================================ e：反真空


def test_if_for_secretary_returns_none_the_unjudged_grid_still_shows(tmp_path):
    """e：把 `LlmSeam.for_secretary` 打桩成返回 `None` ⇒ a 的表现必须出现。

    为什么需要这一条：如果装配处对"造不出缝"这一档静默处理（例如塞一条空缝上去），
    那么 a 那一条会变成恒真（"没缝"永远不会发生），而"判不了"会重新变成不可见。
    这一条钉的是：拿不到缝时 `for_role_wired` 给 `None` + 一句读数，
    而判定返回值里的 `proposition_adjudication` 仍然显式报"没查成"。
    """
    st = _ws(tmp_path)
    with _for_secretary_stub(None):
        sec = for_role_wired("B", root=st.root, store=st)
    assert sec.seam is None, "造不出缝时不许塞一条空缝上去（那会把'没判'写成'判过没成'）"
    assert sec.model_source.startswith("none（LlmSeam.for_secretary 返回 None"), sec.model_source
    assert sec.enable_model is True, "开关本身仍然是开着的（关着是另一个理由）"
    got = sec.adjudicate_proposition({"statement_full": FULL, "kind": "theorem"})
    grid = _adj(got)
    assert grid["checked"] is False, grid
    assert grid["attempted"] is False, grid
    assert "没有装配模型缝" in grid["reason"], grid
    assert grid["seam_source"].startswith("none（"), grid


def test_an_unwired_seam_is_reported_as_none_not_as_an_empty_seam(tmp_path):
    """e（续）：造出来但是空缝（秘书档没配 key）⇒ `None` + 读数说清为什么。

    这一条防的是另一种静默：把 `wired=False` 的缝装上去，`judge` 会走
    "调用失败（judge_not_wired）"那一支 ⇒ `attempted=True` ⇒ 盘上多出一行
    "判过、没成"，而事实是"这一名秘书从来没有判断面"。
    """
    st = _ws(tmp_path)
    unwired = llmseam.LlmSeam.for_secretary(owner_role="B", session_root=st.root,
                                            from_env=False)
    assert unwired.wired is False, "前提：from_env=False 造出来的是一条空缝"
    with _for_secretary_stub(unwired):
        sec = for_role_wired("B", root=st.root, store=st)
    assert sec.seam is None, "空缝不许装到秘书身上"
    assert "没有配模型 key" in sec.model_source, sec.model_source


# ============================================================ 护栏：构造点不许再漏


#: 构造之后只调一个"只读口径"方法的那几处（不判命题，因此不需要缝）。
#: 这一张表是逐条登记的：多出一条或少一条都会让护栏变红 —— 一张永不生效的
#: 豁免表会腐烂成"看起来还在挡着什么"。
_READ_ONLY_CALLS: tuple[str, ...] = ("child_counts(", "surface_of(")
_ALLOWED_READ_ONLY: frozenset[tuple[str, str]] = frozenset({
    # `agent_loop.py` 本轮在"不许碰"的清单里：它只读这一趟的读写面（`surface_of`）。
    ("agent_loop.py", "surface_of"),
    # `readouts.py` 那一处随 `roster_readout` 一起删了（2026-10-27，R-BE1 的 ⑥-6）：
    # 那个读数是生产 0 读者的第五份外壳，删掉之后"名册两个读数"只剩
    # `secretary.Secretary.child_counts` 一处。登记也跟着撤 —— 这张表是逐条对实际的，
    # 留着一条不再生效的豁免正是它自己说的"腐烂"。
    ("statusreport.py", "child_counts"),
})

#: `from .secretary import <名字> [as _X]` / `from . import secretary [as _Y]` —— 别名也要认
#: （否则改个名就成了绕过护栏的路）。两条正则各管一种 import 形态。
_IMPORT_ALIAS = re.compile(r"from\s+\.+secretary\s+import\s+([^\n#]+)")
_MODULE_ALIAS = re.compile(r"from\s+\.+\s+import\s+secretary(?:\s+as\s+(\w+))?")
#: 两条装配口径：直接构造 `Secretary(...)`，或经工厂 `for_role(...)`（它不传缝就不接线）。
_ASSEMBLY_NAMES: tuple[str, ...] = ("Secretary", "for_role")


def _assembly_tokens(text: str) -> list[str]:
    """这个文件里"造一名秘书"的那几个字面标记（不含别的同名物）。

    为什么不是笼统的 `for_role(`：全仓还有 `ToolRegistry.for_role(...)`（工具面）与
    `LlmSeam.for_role(...)`（本体那条缝）—— 它们与"造秘书"毫无关系，混进来会让这条
    护栏立刻变成一张假阳性清单，而假阳性会让整条规则被忽略。所以只认三种写法：
    `Secretary(`、`secretary.for_role(`（含 `from . import secretary as X` 的 `X.`）、
    以及 `from .secretary import for_role [as Y]` 之后那个名字。
    """
    tokens: list[str] = ["Secretary("]
    for part_line in _IMPORT_ALIAS.findall(text):
        for part in part_line.split(","):
            bits = part.strip().split()
            if not bits:
                continue
            if bits[0] == "Secretary":
                tokens.append(f"{bits[2]}(" if len(bits) >= 3 and bits[1] == "as"
                              else "Secretary(")
            elif bits[0] == "for_role":
                alias = bits[2] if len(bits) >= 3 and bits[1] == "as" else "for_role"
                tokens.append(f"{alias}(")
    for alias in _MODULE_ALIAS.findall(text):
        tokens.append(f"{alias or 'secretary'}.for_role(")
    return sorted(set(tokens), key=len, reverse=True)


def _call_tail(text: str, open_at: int) -> tuple[str, str]:
    """从某个左括号起配平，返回 `(整段调用原文, 配对右括号之后的尾巴)`。

    两段各有各的用处：整段用来判"这一次调用带没带 `seam=`"（一次调用常常跨好几行，
    只读第一行会把 `agent_loop._secretary_for` 那种写法误判成没带缝），
    尾巴用来认"紧接着调了哪个只读方法"。
    """
    depth, close_at = 0, -1
    for pos in range(open_at, len(text)):
        ch = text[pos]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                close_at = pos
                break
    if close_at < 0:
        return text[open_at:], ""
    return text[open_at:close_at + 1], text[close_at + 1:close_at + 81]


def _assembly_sites(src: pathlib.Path | None = None
                    ) -> list[tuple[str, int, str, str, str]]:
    """全仓"造一名秘书"的调用点 `(相对路径, 行号, 原文, 整段调用, 调用之后的尾巴)`。

    判据是字面 + 配平（见 :func:`_assembly_tokens` 的三类写法）。三类不算：
    - 定义（`def for_role(` / `class Secretary(`）—— 那是被调的那一头；
    - 文档里的举例（同一行里有反引号）—— 本仓的 docstring 举例一律写成
      `` `Secretary.for_role(...)` ``（这条口径本身由下面的反真空断言守着：
      真正的那几处必须还在，扫到 0 处就红）。
    """
    root = src if src is not None else \
        pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"
    out: list[tuple[str, int, str, str, str]] = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in _assembly_tokens(text):
            idx = text.find(token)
            while idx >= 0:
                line_start = text.rfind("\n", 0, idx) + 1
                line_end = text.find("\n", idx)
                if line_end < 0:
                    line_end = len(text)
                line = text[line_start:line_end]
                # 前面紧贴着别的标识符（`build_for_role(` 之类）⇒ 不是这几条口径
                prev = text[idx - 1] if idx else ""
                if (not (prev.isalnum() or prev == "_")
                        and "`" not in line and "def " not in line and "class " not in line):
                    segment, tail = _call_tail(text, idx + len(token) - 1)
                    out.append((str(path.relative_to(root)),
                                text.count("\n", 0, idx) + 1, line.strip(),
                                segment, tail))
                idx = text.find(token, idx + 1)
    return out


def test_no_construction_site_forgets_the_seam_again():
    """护栏：剩下的裸装配点只允许"只读口径"那几处，且逐条点名。

    这一条是 sylow5 那个缺陷的复发防线：断掉的不是判据，是装配线，而装配线漏一根
    线的形态在单测里永远是绿的（每一处判据都自己塞了假缝）。所以这里按字面扫一遍
    全仓的装配点（两条口径 + import 别名），剩下的每一处都必须要么带 `seam=`，
    要么紧接着只调一个只读口径方法（`child_counts` / `surface_of` —— 不判命题）。

    ## 改前红（本护栏在改前的那棵树上是什么读数）

    改前被点名的五处（把 `src/agentflow` 换成改前的树，`_assembly_sites` 的读数）：
    `tools/table_tools.py:923`、`tools/table_tools.py:1780`、`conductor.py:2977`、
    `agent_b/core.py:124`（`for_role("B", …)`）、`tools/conductor_tools.py:1487`
    （`for_role_as` 那一支）—— 全部没带 `seam=`。

    `agent_loop.py` 与 `readouts.py` 那两处本轮在"不许碰"的清单里，所以它们留在这里
    被点名 —— 一旦有人把判据挂到它们下面，这一条会当场变红。
    """
    bad: list[str] = []
    seen: set[tuple[str, str]] = set()
    for rel, no, line, segment, tail in _assembly_sites():
        if rel == "secretary.py":
            continue                      # 工厂本体（`for_role` 那一行）不算构造点
        if "seam=" in segment:
            continue                      # 显式带缝：合规（一次调用可能跨好几行）
        hit = next((one for one in _READ_ONLY_CALLS if one in tail), "")
        if hit:
            seen.add((rel, hit.rstrip("(")))
            continue
        bad.append(f"{rel}:{no}: {line}")
    assert not bad, ("这些装配点没带 `seam=`（真机 sylow5 的死链就是这么来的）：\n"
                     + "\n".join(bad))
    # 反真空：登记的那几处"只读口径"必须真的还在（否则豁免表会腐烂成永不生效的一张）
    assert seen == set(_ALLOWED_READ_ONLY), (
        f"只读口径的豁免与实际不符：实际 {sorted(seen)}，登记 {sorted(_ALLOWED_READ_ONLY)}")
    # 反真空（第二条）：扫到的装配点不能是 0 —— 否则"没有违规"只是"什么都没扫到"
    assert len(_assembly_sites()) >= 4, len(_assembly_sites())

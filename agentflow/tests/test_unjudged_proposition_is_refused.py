# -*- coding: utf-8 -*-
"""判据：判不了 = 没判成 ⇒ 上层受控拒（业主 2026-11-08：「没有判不了」）。

## 业主原话（验收标准，逐字）

```
「unkown是什么意思？还有既在账上又既不在账上的吗」
「没有判不了。派人做。还有，语义判定当前实现是秘书主动查询还是必须全过一遍？应该是主动查询」
```

## 这一份钉的四条

| 条 | 它要证明的事 | 改前（本笔之前）为什么是红的 |
|---|---|---|
| c1 | 模型判 same 却没给号 ⇒ `checked=False`，`record_statement` 受控拒、不新建行 | 改前降成第三种结论（`checked=True`）⇒ 上层当"查过了"⇒ 照旧落一行 |
| c2 | 模型给词表外结论（历史那一档 `unknown`）⇒ `checked=False`、受控拒、不新建 | 改前那一档在词表里 ⇒ `checked=True` ⇒ 落一行 |
| c3 | 判定超时（坏 JSON / 调用没成）⇒ `checked=False`、受控拒、不新建 | 改前 `checked=False` 退回确定性兜底 ⇒ 键不同就照常新建 |
| c4 | 正控：模型判 different（判成了）⇒ 照常新建一行 | 否则"受控拒"可能只是把写入路径整个关掉 |
| d | 判定面（常量 + 入口 + 可见性格 + 题面那一支）里没有第三种词 | 改前有 |
| e | 反真空：把"判不了 ⇒ 受控拒"摘掉 ⇒ c1/c2/c3 变成"新建一行"（红） | 证明 c 的绿是那条 fail-closed 给的 |

## 边界

全部 tmp 工作区、零真实模型调用（"模型说了什么"由 `_Seam` 按脚本回）；
`projects/` 只读；不碰 `agent_b/**`（那条 lane 另有判据）。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import refusals as R
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow.secretary import Secretary
from agentflow.store import Store

from conftest import seed_statement_row

#: 在册的那一条（夹具直接铺行：这一份测的是判定失败时的处置，不是登记路径）。
IN_LEDGER = "设 G 是有限群，p 是素数；则 G 的 Sylow p-子群存在。"
#: 待收的那一条（措辞不同、数学内容同一）：模型若判 same，本可以并进上面那条。
PARAPHRASE = "若 G 为有限群且 p 为素数，则它的 Sylow p-子群一定存在。"


class _Call:
    """`llmseam.SeamCall` 的最小替身（`judge` 只读 `ok` / `problem` / `detail`）。"""

    def __init__(self, ok: bool = True, problem: str = "", detail: str = "") -> None:
        self.ok = bool(ok)
        self.problem = str(problem)
        self.detail = str(detail)


class _Seam:
    """打桩的秘书缝：只实现 `judge` 用到的那一件事（`ask_json`），按脚本回判词。"""

    wired = True

    def __init__(self, *, reply: dict | None = None, timeout: bool = False) -> None:
        self.reply = dict(reply or {})
        self.timeout = bool(timeout)
        self.calls: list[str] = []

    def ask_json(self, prompt, *, system: str = "", task_id: str = "", note: str = ""):
        self.calls.append(str(note))
        if self.timeout:
            return None, _Call(False, "judge_timeout", "打桩：这一趟没查成")
        data = {
            "decision": str(self.reply.get("decision") or ""),
            "same_as": str(self.reply.get("same_as") or ""),
            "canonical_name": str(self.reply.get("canonical_name") or "Sylow I"),
            "route": "",
            "condition": "打桩：都是有限群 + p 是素数",
            "conclusion": "打桩：都是 Sylow p-子群存在",
            "reason": str(self.reply.get("reason") or "打桩"),
            "basis": ["条件：一致", "结论：一致"],
        }
        return data, _Call()


def _ws(base: pathlib.Path) -> Store:
    st = Store(base / "ws")
    st.init()
    return st


def _body(full: str) -> dict:
    """自产命题的必填件（`doc_id` + `quote_reason`；首登按猜想）。"""
    return {"statement_full": full, "statement_text": full[:24],
            "origin": "own_result", "kind": "conjecture",
            "doc_id": S.format_id(0), "quote_reason": "我方自产命题，没有外部引文要比对"}


def _seed(st: Store) -> dict:
    return seed_statement_row(st, statement_full=IN_LEDGER, statement_text=IN_LEDGER[:24],
                              kind="theorem", label="Sylow I")


def _rows(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("statements")]


def _sec(st: Store, seam: _Seam) -> Secretary:
    return Secretary("B", root=st.root, store=st, seam=seam, enable_model=True)


def _adjudicate(st: Store, seam: _Seam) -> dict:
    return _sec(st, seam).adjudicate_proposition(
        {"statement_full": PARAPHRASE, "label": "Sylow I", "kind": "conjecture"})


def _record(st: Store, seam: _Seam) -> dict:
    return _sec(st, seam).record_statement(_body(PARAPHRASE), role="B")


# ============================================================ c1：same 没给号 ⇒ 没判成

def test_same_without_a_candidate_id_is_unjudged_and_writes_nothing(
        tmp_path: pathlib.Path) -> None:
    """c1：模型判 same、`same_as` 却是空串 ⇒ `checked=False`、受控拒、盘上仍只有 1 行。

    改前红：这一档被降成第三种结论（`checked=True`）⇒ 上层读成"查过了"⇒ 新建一行。
    """
    st = _ws(tmp_path)
    _seed(st)
    seam = _Seam(reply={"decision": "same", "same_as": ""})
    got = _adjudicate(st, seam)
    assert got["checked"] is False, got
    assert got["verdict"] == "", got
    assert "没给出可用的号" in str(got.get("reason") or ""), got
    # 没判成不许缓存（否则"这一次没判成"变成"以后都别查了"）
    assert SEC.proposition_verdict_of(st.root, PARAPHRASE) == {}, (
        SEC.proposition_verdict_of(st.root, PARAPHRASE))

    out = _record(st, seam)
    assert out.get("checked") is False, out
    assert out.get("refused") == R.SAME_STATEMENT_UNJUDGED, out
    assert out.get("created") is not True, out
    assert len(_rows(st)) == 1, _rows(st)
    grid = dict(out.get("proposition_adjudication") or {})
    assert grid.get("checked") is False and grid.get("attempted") is True, grid
    assert "没判成" in str(out.get("reason") or ""), out


# ============================================================ c2：词表外结论 ⇒ 没判成

def test_a_decision_outside_the_two_verdicts_is_unjudged(tmp_path: pathlib.Path) -> None:
    """c2：模型给历史那一档（词表外的结论）⇒ `checked=False`、受控拒、不新建。

    改前红：那一档在词表里 ⇒ `checked=True` ⇒ 上层照旧落一行（"既在账上又不在账上"）。
    """
    st = _ws(tmp_path)
    _seed(st)
    seam = _Seam(reply={"decision": "unknown", "same_as": ""})
    got = _adjudicate(st, seam)
    assert got["checked"] is False, got
    assert got["verdict"] == "", got
    assert "不在" in str(got.get("reason") or "") and "词表" in str(got.get("reason") or ""), got
    out = _record(st, seam)
    assert out.get("refused") == R.SAME_STATEMENT_UNJUDGED, out
    assert len(_rows(st)) == 1, _rows(st)


# ============================================================ c3：超时 ⇒ 没判成

def test_a_timed_out_judgment_is_unjudged_and_does_not_create(
        tmp_path: pathlib.Path) -> None:
    """c3：判定超时 ⇒ `checked=False`、受控拒、不新建（改前退回确定性兜底并新建）。"""
    st = _ws(tmp_path)
    _seed(st)
    seam = _Seam(timeout=True)
    got = _adjudicate(st, seam)
    assert got["checked"] is False, got
    assert got["verdict"] == "", got
    assert got.get("attempted") is True, got
    out = _record(st, seam)
    assert out.get("checked") is False, out
    assert out.get("refused") == R.SAME_STATEMENT_UNJUDGED, out
    assert len(_rows(st)) == 1, _rows(st)


# ============================================================ c4：正控 —— 判成了就照常新建

def test_a_judged_different_still_creates_the_new_row(tmp_path: pathlib.Path) -> None:
    """c4：模型判 different（两档之一，判成了）⇒ 照常新建一行（受控拒不是把写入关掉）。"""
    st = _ws(tmp_path)
    _seed(st)
    seam = _Seam(reply={"decision": "different"})
    got = _adjudicate(st, seam)
    assert got["checked"] is True and got["verdict"] == "different", got
    out = _record(st, seam)
    assert out.get("created") is True, out
    assert len(_rows(st)) == 2, _rows(st)


# ============================================================ d：判定面里没有第三种词

_SOURCE = pathlib.Path(SEC.__file__).read_text(encoding="utf-8")

#: 判定面 = 词表常量 + 入口 + 可见性格 + 题面那一支。「刻意不把」概念同一性
#: （`same_concept`，判的是"同一个概念"、不是"同一条命题"）、同种证明（`same_kind_proof`）、
#: 名册三态、回执状态这些算进来：它们是另外几根轴，各自的两/三档由各自的判据钉着。
_FACE_SLICES: tuple[tuple[str, str], ...] = (
    ("#: 「这一条与在册的哪一条是同一条命题」", "#: 命题同一性判定的旁支台账"),
    ("    def adjudicate_proposition(", "    @staticmethod\n    def _with_adjudication_visibility("),
    ("    @staticmethod\n    def _with_adjudication_visibility(",
     "    @staticmethod\n    def _annotate_proposition("),
    ('    elif kind == "proposition_identity":', '    elif kind == "v_reply_defect":'),
)


def _judgment_face(text: str) -> str:
    """命题同一性判定面的源码片段（四段，缺一段就断言失败 —— 防止切片漂成空串）。"""
    pieces: list[str] = []
    for start, end in _FACE_SLICES:
        at = text.find(start)
        stop = text.find(end, at + len(start)) if at >= 0 else -1
        assert at >= 0 and stop > at, f"判定面切片找不到：{start!r} … {end!r}"
        pieces.append(text[at:stop])
    return "\n".join(pieces)


def _third_word_problems(face: str) -> list[str]:
    """判定面里出现了哪几个"第三档"词（空表 = 干净）。"""
    lowered = str(face or "").lower()
    return [word for word in ("unknown", "三态", "判不了") if word in lowered]


def test_the_proposition_judgment_surface_has_no_third_word() -> None:
    """d：判定面里 `unknown` / 三态 / 判不了 = 0；词表只有两档；题面也一样。

    这不是"文档洁癖"：第三种词只要还在判定面上，模型就还会填它，而它一旦又被当成
    一种结论，上层就会拿它去新建一行 —— 那正是业主问的"既在账上又不在账上"。
    """
    face = _judgment_face(_SOURCE)
    # 反真空：切出来的确实是判定面（锚点都在），否则"没有第三种词"只是"切了个空串"
    for anchor in ("PROPOSITION_VERDICTS", "same_as", "canonical_name", "proposition_identity"):
        assert anchor in face, f"判定面切片里没有锚点 {anchor!r}"
    assert _third_word_problems(face) == [], (
        f"判定面里还有第三档词：{_third_word_problems(face)}")
    assert SEC.PROPOSITION_VERDICTS == ("same", "different"), SEC.PROPOSITION_VERDICTS
    prompt = SEC._judge_system("proposition_identity")
    assert SEC.PROPOSITION_VERDICTS[0] in prompt and SEC.PROPOSITION_VERDICTS[1] in prompt, prompt
    assert _third_word_problems(prompt) == [], (
        f"命题同一性的题面里还有第三档词：{_third_word_problems(prompt)}")
    # 反真空：判据本身不是恒 True（塞一个第三档词进去必须报）
    assert _third_word_problems(face + "\n# unknown\n") == ["unknown"]


# ============================================================ e：反真空

def test_without_the_fail_closed_refusal_the_unjudged_cases_write_a_row(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """e：把"判不了 ⇒ 受控拒"摘掉（= 改前口径）⇒ c1/c2/c3 当场变成"新建一行"。

    证明 c 的绿是那条 fail-closed 给的，不是夹具自带的。
    """
    monkeypatch.setattr(SEC, "_proposition_judgment_missing",
                        lambda kind, adj: "")
    for label, seam in (
        ("same-empty", _Seam(reply={"decision": "same", "same_as": ""})),
        ("word-outside", _Seam(reply={"decision": "unknown"})),
        ("timeout", _Seam(timeout=True)),
    ):
        st = _ws(tmp_path / label)
        _seed(st)
        out = _record(st, seam)
        rows = _rows(st)
        assert len(rows) == 2, (
            f"[{label}] 摘掉 fail-closed 之后仍是 {len(rows)} 行 ⇒ c 那一组断言没有钉住它：{out}")
        assert out.get("created") is True, (label, out)


if __name__ == "__main__":          # pragma: no cover - 手动跑这一份时用
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))

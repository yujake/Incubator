# -*- coding: utf-8 -*-
"""判据（B2 的写侧接缝）：入库口那一格必须把证明正文转交秘书，note 必须换成力气口径。

## 为什么需要这一份（真机读数，只读复算 `projects/sylow4`）

`secretary.proof_effort_readings` / `nontriviality_from_effort` 落地之后，档位只由
「这份证明花了多大力气」给（五项读数：体量 / 步骤 / 引理 / 工具簇跨度 / 绕路）。
但 `agent_loop._statement_filing_tier` 这一趟只转交 `statement_full` / `statement` /
`source`，不转 `proof_text` / `proofs` ⇒ 证明正文根本没进判档材料 ⇒ 真机上 sylow4
那 8 条互不相同的登记里有 6 条落「未判（缺证明正文）」，新口径在写侧这一格上白做。

同一个格子里还有第二处残留：落 T0 时给模型看的那句 note 仍在教旧口径
（「① 后面哪一步会用到它 ② 它比收录表里最接近的那一条强在哪」）—— 而业主裁定
（2026-10-24 逐字）是：「不一定一条定理后面要用，也不一定存在『已知那条』，
看证明花的力气就能判非平凡度」。note 教旧口径 ⇒ 模型会去编"谁会用到它"来升档。

## 四条判据与各自的「改前红」

改前 = 本批之前的 `agent_loop.py`（`_statement_filing_tier` 只转交命题正文、note 说旧两问）。
每条的红都落在判据自己的读取面上（判档材料 / 台账行 / note 原文），不靠记忆：

| 判据 | 它要证明的事 | 改前为什么红 |
|---|---|---|
| a | 带 `proof_text` 的登记 ⇒ 判档材料里 `effort.chars > 0`、档位按力气给出 | 材料里没有证明正文 ⇒ `chars=0` + `missing=["proof_body"]` ⇒ 落「未判」，这一格什么都不加（`None`） |
| a2 | 同一句「太平凡」、换一份大证明 ⇒ 不落 T0（档位不是"一律 T0"） | 证明没转交 ⇒ 读数取不到 ⇒ 结论被改记「判不了」⇒ 同样是 `None`（看上去"对"，其实是因为材料空） |
| b | 没交证明 ⇒ 仍落「未判」并点名缺哪一项；别把"没证明"判成有档位 | 负控：这一支改前改后都该落「未判」。它带一条对照臂（同一秘书、同一条命题、只补证明 ⇒ 必须 computed），那一臂改前红 |
| c | note 里出现五项力气读数之一、且不再出现旧那两问 | note 原文是旧两问，五个力气词一个都没有 |
| d | 反真空：把 ① 的透传打桩成空 ⇒ a 必红 | 打桩后材料 `chars=0`；另外调用点那两行关键字本身也逐字钉着（AST） |

零模型钱：本文件所有判断都走替身判断面（`Secretary.judge` 只记材料、按剧本回结论），
一次真实模型调用都不发；工作区全在 `tmp_path`，不碰 `projects/`。
"""
from __future__ import annotations

import ast
import json
import pathlib
import sys
import types
from typing import Any, Mapping

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import agent_loop as LOOP
from agentflow import secretary as SEC

#: 命题正文（不含证明小节：它自己不像一份证明，所以改前的读数必然是"缺证明正文"）。
_STATEMENT = "对任意正整数 n，n^2+n 一定是偶数。"

#: 力气小的证明：三行、只用定义 ⇒ 五项读数几乎全 0 ⇒ T0（正控）。
_SMALL_PROOF = """证明：由定义直接得到。
1. n 与 n+1 必有一偶，故 n(n+1) 是偶数。
2. 所以对任意正整数 n，n^2+n 一定是偶数。∎"""


def _big_proof(*, chars: int = 6000, lemmas: int = 6, steps: int = 12) -> str:
    """力气大的证明：体量大 + 多条引理 + 跨两簇（群作用 / 计数同余）⇒ T2 以上。"""
    lines = ["证明：这一段是判据夹具。"]
    for i in range(1, lemmas + 1):
        lines.append(f"引理 {i}：由群作用与轨道—稳定化子得到 |G| = |轨道| · |稳定化子|。")
    for i in range(1, steps + 1):
        lines.append(f"{i}. 第 {i} 步：把链长记作 m，按同余 mod p 与整除关系统计计数。")
    body = "\n".join(lines)
    pad = "（此处为推导细节，逐字展开略）"
    while len(body) < chars:
        body += pad
    return body


class _StubSecretary:
    """只回一格"判了太平凡"的结果（不碰材料、不落盘）。

    用来把 (c) 从 (a) 里分开：note 的文案是被判据钉住的那一格，它红要有它自己的理由
    （旧两问还在），而不是"这一格根本没被走到"。`effort` 给的就是真读数
    （`proof_effort_readings` 在同一个工作区里算出来的那一份），所以这一份替身
    与真秘书交给 `_statement_filing_tier` 的形状逐格一致。
    """

    def __init__(self, effort: Mapping[str, Any] | None = None,
                 label: str = "T0", level: Any = 0) -> None:
        self.effort = dict(effort or {})
        self.label, self.level = label, level

    def judge_statement(self, **kw: Any) -> dict[str, Any]:
        return {"checked": True, "decision": "太平凡", "reason": "力气小",
                "basis": [], "reused": True, "nontriviality": self.level,
                "label": self.label, "effort": self.effort,
                "nontriviality_tri": "computed" if self.level is not None else "unjudged"}


class _Capture:
    """替身判断面：记下秘书真正看到的材料，按剧本回一个结论（零模型调用）。"""

    def __init__(self, decision: str = "太平凡", reason: str = "力气小") -> None:
        self.decision = decision
        self.reason = reason
        self.materials: list[dict[str, Any]] = []

    def __call__(self, kind: str, context: Mapping[str, Any], *, task_id: str = "") -> dict:
        if kind != "statement_aesthetic":
            raise AssertionError(f"这一问只该是 statement_aesthetic，拿到 {kind!r}")
        self.materials.append(dict(context))
        return {"checked": True, "decision": self.decision, "reason": self.reason,
                "basis": [], "nontriviality": None, "nontriviality_basis": ""}


def _secretary(tmp_path: pathlib.Path, judge: Any | None = None) -> tuple[SEC.Secretary, pathlib.Path]:
    """一个 B 的秘书（判断面打桩）；返回 `(秘书, 工作区根)`。"""
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    sec = SEC.Secretary("B", root=root)
    sec.judge = judge or _Capture()  # type: ignore[assignment]
    return sec, root


def _gate(secretary: Any, args: Mapping[str, Any],
          name: str = "own.register_statement") -> dict[str, Any] | None:
    """入库口那一道闸的真身（B 的入库动作之前、同一个返回面上）。"""
    return LOOP.AgentLoop._statement_filing_tier(
        types.SimpleNamespace(role="B", secretary=secretary, my_task_id="t-000001"),
        name, dict(args))


def _ledger_rows(root: pathlib.Path) -> list[dict[str, Any]]:
    path = SEC.nontriviality_path(root)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


# ---------------------------------------------------------------- a）证明正文要进材料

def test_a_a_registration_with_proof_text_puts_the_proof_body_in_the_material(
        tmp_path: pathlib.Path) -> None:
    """（a）带 `proof_text` 的登记 ⇒ 判档材料里含证明正文，档位按力气给出（不是「未判」）。

    改前红：材料里没有 `proof_text`（`effort.chars == 0` + `missing == ["proof_body"]`），
    秘书把结论改记「判不了」⇒ 这一格返回 `None`，模型看到的只有"太平凡/没档位"。
    """
    cap = _Capture()
    sec, root = _secretary(tmp_path, cap)
    got = _gate(sec, {"statement_full": _STATEMENT, "proof_text": _SMALL_PROOF})

    assert cap.materials, "秘书根本没被问到（这一趟判档没发生）"
    material = cap.materials[0]
    effort = dict(material.get("effort") or {})
    assert effort.get("chars", 0) > 0, (
        "判档材料里没有证明正文 ⇒ 真机上只能落「未判（缺证明正文）」：" + repr(effort))
    assert effort.get("chars") == len(_SMALL_PROOF), effort
    assert list(effort.get("missing") or []) == [], effort
    # 命中的是证明正文而不是命题正文：命题里没有编号行，`步骤` 只能从证明里数出来。
    assert effort.get("steps") == 2, effort

    assert got is not None, "证明正文进了材料、档位也判出来了，这一格却什么都没加"
    assert got["tier"] == "T0", got
    assert got["nontriviality"] == 0 and got["nontriviality_tri"] == "computed", got
    assert got["effort"]["chars"] > 0, got["effort"]
    # 台档也真的落了这一档（读盘，不听返回值自报）。
    rows = _ledger_rows(root)
    assert rows and rows[-1]["nontriviality"] == 0, rows


def test_a_a_registration_with_only_the_proofs_list_also_reaches_the_material(
        tmp_path: pathlib.Path) -> None:
    """（a）证明只挂在 `proofs` 清单里（没有 `proof_text`）⇒ 同样要进材料。

    多证明模型（业主 2026-10-22）之后，证明正文可能只在这一栏里；只转 `proof_text`
    等于把"第 2 份及以后的证明"整片漏掉。
    """
    cap = _Capture()
    sec, _root = _secretary(tmp_path, cap)
    got = _gate(sec, {"statement_full": _STATEMENT,
                      "proofs": [{"proof_no": 1, "text": _SMALL_PROOF}]})
    effort = dict((cap.materials[0] if cap.materials else {}).get("effort") or {})
    assert effort.get("chars", 0) == len(_SMALL_PROOF), (
        "`proofs` 里的证明正文没进判档材料：" + repr(effort))
    assert got is not None and got["tier"] == "T0", got


def test_a2_a_big_proof_is_never_filed_as_t0_even_when_the_secretary_says_trivial(
        tmp_path: pathlib.Path) -> None:
    """（a2）同一句「太平凡」+ 一份大证明 ⇒ 不落 T0（档位不是"一律 T0"）。

    这是 (a) 的反面：若写侧只是"补一句 tier"，无论材料里有没有证明都给 T0，那 (a) 就是空转。
    改前红：证明没转交 ⇒ 读数一项取不到 ⇒ 结论被改记「判不了」⇒ 同样返回 `None`，
    但原因是"材料空"而不是"力气大"（所以下面同时钉住材料里的读数）。
    """
    cap = _Capture()
    sec, root = _secretary(tmp_path, cap)
    proof = _big_proof()
    got = _gate(sec, {"statement_full": _STATEMENT, "proof_text": proof})

    effort = dict(cap.materials[0].get("effort") or {})
    assert effort.get("chars", 0) >= 6000, effort
    assert effort.get("lemmas", 0) >= 6 and effort.get("clusters", 0) >= 2, effort
    assert got is None, f"力气给出 T2 以上的命题被贴了 T0 读数：{got}"
    rows = _ledger_rows(root)
    assert rows and rows[-1]["nontriviality"] >= 2, rows


# ---------------------------------------------------------------- b）负控：没证明仍落未判

def test_b_a_registration_without_proof_stays_unjudged_and_names_the_gap(
        tmp_path: pathlib.Path) -> None:
    """（b）没交证明的登记 ⇒ 仍落「未判（缺证明正文）」并点名缺什么（负控）。

    别把"没证明"也判成有档位：`nontriviality` 必须是 `None` 而不是 0（0 是 T0，
    那是"证明花的力气小"，不是"没有证明"）；这一格也不许凭空加一格档位读数。

    对照臂（改前红）：同一个秘书、同一条命题，只把证明补上 ⇒ 台账那一行必须是
    computed + 0。改前两条都落「未判」，因为证明正文没被转交。
    """
    cap = _Capture()
    sec, root = _secretary(tmp_path, cap)

    got = _gate(sec, {"statement_full": _STATEMENT})
    assert got is None, f"没交证明却给出了档位读数（负控破了）：{got}"
    rows = _ledger_rows(root)
    assert rows, "没交证明时连一行「未判」都没有 ⇒ 判档这一趟根本没发生"
    last = rows[-1]
    assert last["nontriviality"] is None, last
    assert last["label"] == "", last
    assert "缺的是「证明正文" in str(last["basis"]), last["basis"]
    assert "proof_text" in str(last["basis"]), last["basis"]

    # ---- 对照臂：只把证明补上，别的什么都不动
    got2 = _gate(sec, {"statement_full": _STATEMENT, "proof_text": _SMALL_PROOF})
    rows = _ledger_rows(root)
    assert got2 is not None and got2["tier"] == "T0", got2
    assert rows[-1]["nontriviality"] == 0, (
        "补上证明之后仍然落「未判」⇒ 证明正文没被转交给秘书：" + json.dumps(rows[-1], ensure_ascii=False))


# ---------------------------------------------------------------- c）note 换成力气口径

def test_c_the_note_speaks_effort_and_drops_the_old_two_questions(
        tmp_path: pathlib.Path) -> None:
    """（c）note 里出现五项力气读数之一，且不再出现旧那两问（改前红）。

    这一条刻意用替身秘书（只回一格"判了太平凡"）：note 的红要有它自己的理由 ——
    改前那句 note 逐字教着旧两问，五个力气词一个都没有。
    """
    effort = SEC.proof_effort_readings(statement_full=_STATEMENT, proof_text=_SMALL_PROOF)
    got = _gate(_StubSecretary(effort=effort), {"statement_full": _STATEMENT})
    assert got is not None, got
    note = str(got["note"])

    # ① 力气口径：五项里至少要有一项被点名（业主 2026-10-24 的判据）
    for word in ("体量", "步骤", "引理", "工具簇", "绕路"):
        if word in note:
            break
    else:  # pragma: no cover - 走不到时下面这一句就是判据
        raise AssertionError(f"note 里五个力气读数一个都没有：{note!r}")
    assert "力气" in note, note

    # ② 旧两问已经删掉（"可以写、不作判据"也要明说）
    assert "后面哪一步会用到它" not in note, note
    assert "比收录表里最接近的那一条" not in note, note

    # ③ 业主 2026-10-23 的裁定与"平凡不再拒收"这一句照旧在（改前已有的两条，不许回退）
    assert "T0" in note and "拦收录" in note, note


def test_c_the_note_points_at_the_readings_that_still_score_zero(tmp_path: pathlib.Path) -> None:
    """（c）note 要指路：这一条还在 0 分的项点名，补哪一项能升档。

    只写"按力气判"而不说"还差哪一项"，模型拿到 T0 仍然不知道下一步该干什么 ——
    这正是旧 note 存在的理由（真机里同一份命题被原样重交 6 次）。改前红：旧 note 里
    没有任何一项力气读数，也没有"补"这个动作。
    """
    effort = SEC.proof_effort_readings(statement_full=_STATEMENT, proof_text=_SMALL_PROOF)
    assert effort["chars"] > 0 and effort["score"] == 0, effort
    got = _gate(_StubSecretary(effort=effort), {"statement_full": _STATEMENT})
    assert got is not None, got
    note = str(got["note"])
    assert "补" in note, note
    # 三行证明：体量与步骤都远不到台阶 ⇒ 这两项必须被点名
    assert "体量" in note and "步骤" in note, note
    assert "proof_text" in note, note


# ---------------------------------------------------------------- d）反真空

def test_d_stripping_the_proof_passthrough_turns_case_a_red(
        monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    """（d）反真空：把 ① 的透传打桩成空 ⇒ (a) 必红。

    打桩只做一件事：这一趟不问秘书要证明正文（等价于改前的调用点）。于是材料里
    `effort.chars == 0`、`missing == ["proof_body"]`、结论改记「判不了」⇒
    (a) 那三句断言同时不成立。
    """
    original = SEC.Secretary.judge_statement

    def _without_the_proof(self, *, proof_text: str = "", proofs: Any = None, **kw: Any):
        return original(self, proof_text="", proofs=None, **kw)

    monkeypatch.setattr(SEC.Secretary, "judge_statement", _without_the_proof)

    cap = _Capture()
    sec, root = _secretary(tmp_path, cap)
    got = _gate(sec, {"statement_full": _STATEMENT, "proof_text": _SMALL_PROOF})
    effort = dict((cap.materials[0] if cap.materials else {}).get("effort") or {})
    assert effort.get("chars", 0) == 0, f"透传打空之后材料里仍然有证明正文：{effort}"
    assert list(effort.get("missing") or []) == ["proof_body"], effort
    assert got is None, f"透传打空之后这一格仍然给出了档位读数：{got}"
    rows = _ledger_rows(root)
    assert rows and rows[-1]["nontriviality"] is None, rows


def test_d_the_call_site_hands_over_both_keywords() -> None:
    """（d）结构判据：调用点逐字写着 `proof_text=` / `proofs=`（改前红：两行都不在）。

    行为判据（上面那条）证明"少了这两行会坏"；这一条钉住"它们真的在那一次调用里"，
    否则 `proofs` 可以靠 `statement_full` 里自带证明小节蒙过去，而那一栏明天就可能消失。
    """
    src = pathlib.Path(LOOP.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls: list[list[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_statement_filing_tier":
            continue
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "judge_statement"):
                calls.append([str(kw.arg) for kw in sub.keywords])
    assert calls, "`_statement_filing_tier` 里找不到那次 `judge_statement` 调用"
    keywords = calls[0]
    assert "proof_text" in keywords, keywords
    assert "proofs" in keywords, keywords
    for other in ("statement_full", "statement", "source", "task_id"):
        assert other in keywords, (other, keywords)

# -*- coding: utf-8 -*-
"""判据（D16）：档位与命题行按号关联；正文改一个字，档位仍读得到。

## 这一批修的形态（真机 `projects/mp3-r3`）

`out/secretary/nontriviality.jsonl` 旧行只有 `statement_sha256`，没有 `stmt_id`；
读侧 `nontriviality_of` 也只按全文 sha 命中。于是 B 登记时"判档用的正文"与
"落盘行上的正文"只要差一个字，那一档就从页面上消失：真机第 1 行（316 字）正是
这样对不上任何 `statements` 行。这不是"再加一段按文本兜底"能修的 —— 兜底只会
让文本成为第二处真身。

## 五条判据与反真空

| 判据 | 它要证明的事 | 改前为什么红 |
|---|---|---|
| a | 判一条（带号）⇒ 台账行有 `stmt_id` 且等于传入值 | `append_nontriviality` 没有这一格，`judge_statement` 也不收号 |
| a1 | B 登记之后判的正文就是落盘那一行的正文（sha 相等） | 判档在 `registry.call` 之前，用的是一句可能被改写的入参 |
| b | 判完把正文改一个字 ⇒ 仍按号读到原档位 | 读侧只认 sha，改一个字就变"未判" |
| c | 旧账本（只有 sha）仍能读，`matched_by="sha256"` | 改前没有 `matched_by` 这一格（兼容正控） |
| d | 从没判过的命题 ⇒ `matched_by=""`、未判，不许折成 T0 | 改前"未判"与"T0"在返回值上靠 `level is None` 分，但没有命中方式可核对 |
| e | 反真空：把"按号查"打桩成恒不命中 ⇒ b 必红 | 这一条证明 b 的绿来自号，不是来自文本碰巧相同 |

零模型钱：所有判断都走打桩的 `Secretary.judge`，工作区全在 `tmp_path`。
"""
from __future__ import annotations

import json
import pathlib
import sys
import types
from typing import Any, Mapping

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import secretary as SEC  # noqa: E402
from agentflow.agent_loop import AgentLoop  # noqa: E402
from agentflow.webui import readers as R  # noqa: E402

_SID = "000123"
_BODY = "设 G 是有限群，p 是素数；则 G 的 Sylow p-子群存在。"
_PROOF = """证明：由定义直接得到。
1. 取 G 的一个极大 p-子群 P。
2. 让 G 共轭作用在 P 上。
3. 数轨道与稳定化子。"""


def _judge(kind: str, context: Mapping[str, Any], *, task_id: str = "") -> dict[str, Any]:
    """打桩判断面：判了，但自报档位留空（档位由力气读数落格，不靠模型自报）。"""
    assert kind == "statement_aesthetic", kind
    return {"checked": True, "decision": "合格", "reason": "判了", "basis": [],
            "nontriviality": None, "nontriviality_basis": ""}


def _secretary(root: pathlib.Path) -> SEC.Secretary:
    sec = SEC.Secretary("B", root=root)
    sec.judge = _judge  # type: ignore[assignment]
    return sec


def _root(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _ledger(root: pathlib.Path) -> list[dict[str, Any]]:
    path = SEC.nontriviality_path(root)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _judge_one(root: pathlib.Path) -> None:
    sec = _secretary(root)
    sec.judge_statement(statement_full=_BODY, proof_text=_PROOF, stmt_id=_SID,
                        task_id="t-000001")


# ---------------------------------------------------------------- a）带号落行

def test_a_a_judgement_with_a_stmt_id_lands_that_id(tmp_path: pathlib.Path) -> None:
    """（a）判一条带号的命题 ⇒ 台账行有 `stmt_id` 且等于传入值。

    改前红：`append_nontriviality` 的签名里没有号，`judge_statement` 也不收它
    （`TypeError: unexpected keyword argument 'stmt_id'`），这一格根本走不到。
    """
    root = _root(tmp_path)
    _judge_one(root)
    rows = _ledger(root)
    assert rows, "判了却没落台账行"
    assert rows[-1]["stmt_id"] == _SID, rows[-1]
    assert rows[-1]["statement_sha256"] == SEC._statement_sha(_BODY), rows[-1]


# ---------------------------------------------------------------- a1）判落盘那一份

class _FakeRegistry:
    """只回一件 `own.register_statement` 的注册表：登记成功，落盘正文与入参不同。"""

    def __init__(self, data: Mapping[str, Any]) -> None:
        self.data = dict(data)
        self.calls = 0

    def names(self) -> list[str]:
        return ["own.register_statement"]

    def call(self, name: str, *, role: str, **args: Any) -> Any:
        self.calls += 1
        assert name == "own.register_statement" and role == "B", (name, role)
        return types.SimpleNamespace(ok=True, data=dict(self.data), error="", meta={})


def test_a1_the_judged_text_is_the_landed_row(tmp_path: pathlib.Path) -> None:
    """（a1）B 登记之后判的正文必须是落盘行上的那一份（sha 相等）。

    改前红：判档在 `registry.call` 之前，用的是调用方入参 `_BODY`；而落盘行是
    `_BODY + 一句`。台账行的 sha 于是对不上 statements 行 —— 真机第 1 行 316 字
    就是这么来的。
    """
    root = _root(tmp_path)
    sec = _secretary(root)
    landed_full = _BODY + "（落盘时补的一句）"
    reg = _FakeRegistry({"ok": True, "stmt_id": "000321",
                         "row": {"stmt_id": "000321", "statement_full": landed_full}})
    loop = AgentLoop(role="B", session_root=root, registry=reg, seam=None,
                     secretary=sec, auto_secretary=False, my_task_id="t-000001")
    out = loop._do_tool({"name": "own.register_statement",
                         "args": {"statement_full": _BODY, "proof_text": _PROOF}})
    assert out["ok"] is True, out
    assert out["data"]["stmt_id"] == "000321", out
    rows = _ledger(root)
    assert rows, "登记成功却没有判档行"
    assert rows[-1]["stmt_id"] == "000321", rows[-1]
    assert rows[-1]["statement_sha256"] == SEC._statement_sha(landed_full), rows[-1]
    assert rows[-1]["statement_sha256"] != SEC._statement_sha(_BODY), rows[-1]


def test_a2_the_b_loop_keeps_a_concept_row_not_applicable(tmp_path: pathlib.Path) -> None:
    """（a2）B 循环登记概念行之后仍读成"不适用"，不因判档移到登记之后而变成"未判"。

    概念行没有证明正文：这一格必须把 `kind` 一起传给 `judge_statement`，走它那条
    `not_applicable` 早退。漏传 `kind` 就会按"缺证明正文"再落一行 unknown，且那一行
    带号、排在后头 ⇒ 读侧把"不适用"覆盖成"未判"。
    """
    root = _root(tmp_path)
    sec = _secretary(root)
    concept = "概念：一个交换环上的有限生成模。"
    reg = _FakeRegistry({"ok": True, "stmt_id": "000322",
                         "row": {"stmt_id": "000322", "statement_full": concept}})
    loop = AgentLoop(role="B", session_root=root, registry=reg, seam=None,
                     secretary=sec, auto_secretary=False, my_task_id="t-000001")
    out = loop._do_tool({"name": "own.register_statement",
                         "args": {"statement_full": concept, "kind": "concept"}})
    assert out["ok"] is True, out
    tier = R._statement_tier_reading(
        root, {"stmt_id": "000322", "statement_full": concept})
    assert tier["tri"] == "not_applicable", tier
    assert tier["level"] is None and tier["matched_by"] == "stmt_id", tier
    assert tier["word"] == R.NONTRIVIALITY_NOT_APPLICABLE_WORD, tier


# ---------------------------------------------------------------- b）正文改了仍读得到
def test_b_a_changed_statement_still_reads_its_tier_by_id(tmp_path: pathlib.Path) -> None:
    """（b）判完把正文改一个字 ⇒ 读侧仍返回原档位，且 `matched_by="stmt_id"`。

    改前红：读侧只按 sha 命中，改一个字就没有那一行 ⇒ `level=None`、页面写"未判"。
    """
    root = _root(tmp_path)
    _judge_one(root)
    before = R._statement_tier_reading(root, {"stmt_id": _SID, "statement_full": _BODY})
    assert before["level"] == 0 and before["matched_by"] == "stmt_id", before

    changed = _BODY + "（补一句）"
    after = R._statement_tier_reading(
        root, {"stmt_id": _SID, "statement_full": changed})
    assert after["level"] == 0 and after["label"] == "T0", after
    assert after["matched_by"] == "stmt_id", after
    # 对照：不带号、只按改后的正文读 ⇒ 确实没有这一行（证明 b 的绿来自号，不是文本）。
    assert SEC.nontriviality_of(root, changed)["matched_by"] == ""


# ---------------------------------------------------------------- c）旧账本仍能读

def _old_row(body: str, level: int) -> dict[str, Any]:
    """改前那种行：只有 sha，没有 stmt_id。"""
    return {"at": "2026-10-26T00:00:00+08:00",
            "statement_sha256": SEC._statement_sha(body),
            "statement_chars": len(body), "scale": SEC.NONTRIVIALITY_SCALE,
            "nontriviality": level, "label": SEC.nontriviality_label(level),
            "basis": "旧行（只有 sha）", "effort": {}, "text_truncated": False,
            "role": "B", "task_id": "t-old"}


def _write_rows(root: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    path = SEC.nontriviality_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                            for r in rows), encoding="utf-8")


def test_c_an_old_ledger_row_with_only_sha_still_reads(tmp_path: pathlib.Path) -> None:
    """（c）旧账本（只有 sha）仍能读，`matched_by="sha256"`（兼容正控）。

    这一条守的是"旧数据只留一条读侧回退"：回退命中时必须自报 `sha256`，
    否则它看起来和"按号命中"一模一样，第二处真身就重新长出来了。
    """
    root = _root(tmp_path)
    _write_rows(root, [_old_row(_BODY, 2)])
    got = SEC.nontriviality_of(root, _BODY)
    assert got["level"] == 2 and got["matched_by"] == "sha256", got
    with_id = SEC.nontriviality_of(root, _BODY, stmt_id="000999")
    assert with_id["level"] == 2 and with_id["matched_by"] == "sha256", with_id
    tier = R._statement_tier_reading(root, {"stmt_id": "000999", "statement_full": _BODY})
    assert tier["level"] == 2 and tier["matched_by"] == "sha256", tier


# ---------------------------------------------------------------- d）没判过不许折成 T0

def test_d_a_never_judged_statement_is_unjudged_not_t0(tmp_path: pathlib.Path) -> None:
    """（d）正控：从没判过的命题 ⇒ `matched_by=""`、档位未判（不许折成 T0）。

    三态纪律：`level is None` 是"未判"，`0` 是 T0（真的档位）。这里同时钉
    `tri` 与页面的词，避免"没有命中"被某处补成 0。
    """
    root = _root(tmp_path)
    tier = R._statement_tier_reading(
        root, {"stmt_id": "000777", "statement_full": "这条从来没有判过"})
    assert tier["matched_by"] == "", tier
    assert tier["level"] is None and tier["tri"] == "unknown", tier
    assert tier["word"] == R.NONTRIVIALITY_UNJUDGED_WORD, tier
    got = SEC.nontriviality_of(root, "这条从来没有判过", stmt_id="000777")
    assert got["matched_by"] == "" and got["level"] is None and got["tri"] == "unknown", got


# ---------------------------------------------------------------- e）反真空

def test_e_stubbing_the_id_lookup_off_turns_case_b_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """（e）反真空：把"按号查"打桩成恒不命中 ⇒ b 必红。

    打桩只做一件事：`_row_matches_stmt_id` 恒回 False（等价于读侧没有按号查）。
    于是 b 里那条改过一个字的正文只剩 sha 回退，而 sha 对不上 ⇒ 档位变"未判"。
    这一条证明 b 的绿来自号，而不是"改一个字碰巧也能对上"。
    """
    root = _root(tmp_path)
    _judge_one(root)
    changed = _BODY + "（补一句）"
    monkeypatch.setattr(SEC, "_row_matches_stmt_id", lambda row, stmt_id: False)
    tier = R._statement_tier_reading(
        root, {"stmt_id": _SID, "statement_full": changed})
    assert tier["tri"] == "unknown", tier
    assert tier["level"] is None, tier
    assert tier["matched_by"] == "", tier

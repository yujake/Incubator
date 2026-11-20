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
from typing import Any, Mapping

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import secretary as SEC  # noqa: E402
from agentflow.webui import readers as R  # noqa: E402
import _secretary_home as HOME  # 打桩打在定义处（搬家后 SEC 那一格只是再导出）

_SID = "000123"
_BODY = "设 G 是有限群，p 是素数；则 G 的 Sylow p-子群存在。"
_PROOF = """证明：由定义直接得到。
1. 取 G 的一个极大 p-子群 P。
2. 让 G 共轭作用在 P 上。
3. 数轨道与稳定化子。"""


def _judge(kind: str, context: Mapping[str, Any], *, task_id: str = "") -> dict[str, Any]:
    """打桩判断面：判了，并给出档位。

    业主 2026-10-29 改了口径：「全交给模型判」「判档的还是 B 秘书」—— 机器力气读数
    降为参考、不再裁定档位（`Secretary.judge_statement` 里那句「机器力气读数只作参考，
    不拿来补一个档位」）。所以这一档替身必须像真的秘书那样把档位说出来；不给档位
    （`nontriviality=None`）会被如实记成"未判"，而这一份判据要测的是"按 `stmt_id`
    关联"，不是"没判也读得出档位"。给 0 档（T0）：这一段证明的力气读数本来就在 0 档。
    """
    assert kind == "statement_aesthetic", kind
    return {"checked": True, "decision": "合格", "reason": "判了", "basis": [],
            "nontriviality": 0, "nontriviality_basis": "替身：按五档定义判这一段是 T0"}


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
    """走一遍"判 → 落"两段（NT2 之后 `judge_statement` 只判、不写盘）。"""
    sec = _secretary(root)
    got = sec.judge_statement(statement_full=_BODY, proof_text=_PROOF, stmt_id=_SID,
                              task_id="t-000001")
    sec.record_nontriviality(got, stmt_id=_SID, path_group=1,
                             statement_full=_BODY,
                             judged_body_sha256=SEC._judged_body_sha(_BODY, _PROOF),
                             landed_body_sha256=SEC._statement_sha(_BODY))


# ---------------------------------------------------------------- a）带号落行

def test_a_a_judgement_with_a_stmt_id_lands_that_id(tmp_path: pathlib.Path) -> None:
    """（a）判一条带号的命题 ⇒ 台账行有 `stmt_id` 且等于传入值。

    改前红（NT2 这一笔之前）：`judge_statement` 把"判"与"落"揉在一起；判/落拆段之后
    它只判，落行必须走 `record_nontriviality`（并带上路径号）。改前这条判据读的是
    "判一次就有一行"，现在读的是"判 + 落一次有一行、号逐字相同"。
    """
    root = _root(tmp_path)
    _judge_one(root)
    rows = _ledger(root)
    assert rows, "判了却没落台账行"
    assert rows[-1]["stmt_id"] == _SID, rows[-1]
    assert rows[-1]["statement_sha256"] == SEC._statement_sha(_BODY), rows[-1]
    # 路径维 + 两枚 sha（业主 2026-11-15：一个路径一行、判的材料可复核）
    assert rows[-1]["path_group"] == 1, rows[-1]
    assert rows[-1]["judged_body_sha256"] == SEC._judged_body_sha(_BODY, _PROOF), rows[-1]
    assert rows[-1]["landed_body_sha256"] == SEC._statement_sha(_BODY), rows[-1]


# ---------------------------------------------------------------- a1）判哪一版 / 落哪一版

def test_a1_the_judged_material_and_the_landed_body_are_recorded_separately(
        tmp_path: pathlib.Path) -> None:
    """（a1）台账行同时记"判的材料"与"落盘正文"两枚 sha，且靠号 join。

    NT2（2026-11-15）的形状：判档发生在写台账之前，材料是那一份稿的
    `## 命题` + `## 证明`；落盘行的正文可能被洗过（与判的材料差几个字）。
    所以两枚 sha 分开记 —— 复核的人才能回答"判的是哪一版、落的是哪一版"。

    改前红：旧行只有 `statement_sha256` 一枚，判的材料与落盘正文分家时无从核对；
    而"判的那一版"今天可能根本不在盘上（真机 000040/000041 判的入参里没有证明正文）。
    """
    root = _root(tmp_path)
    sec = _secretary(root)
    judged_material = _BODY
    landed = _BODY + "（落盘时补的一句）"
    got = sec.judge_statement(statement_full=judged_material, proof_text=_PROOF,
                              stmt_id="000321", task_id="t-000001")
    rec = sec.record_nontriviality(
        got, stmt_id="000321", path_group=1, statement_full=judged_material,
        judged_body_sha256=SEC._judged_body_sha(judged_material, _PROOF),
        landed_body_sha256=SEC._statement_sha(landed))
    assert rec["recorded"] is True, rec
    row = _ledger(root)[-1]
    assert row["stmt_id"] == "000321", row
    assert row["judged_body_sha256"] == SEC._judged_body_sha(judged_material, _PROOF), row
    assert row["landed_body_sha256"] == SEC._statement_sha(landed), row
    assert row["judged_body_sha256"] != row["landed_body_sha256"], row
    # 读侧靠号 join：正文换成落盘那一版仍读得到同一条读数。
    by_id = SEC.nontriviality_of(root, landed, stmt_id="000321")
    assert (by_id["tri"], by_id["level"], by_id["matched_by"]) == (
        "computed", 0, "stmt_id"), by_id
    assert by_id["paths"][0]["path_group"] == 1, by_id["paths"]
    assert by_id["paths"][0]["judged_body_sha256"] == row["judged_body_sha256"], by_id


def test_a2_the_b_action_judges_a_concept_row_as_not_applicable(
        tmp_path: pathlib.Path) -> None:
    """（a2）B 的收录动作把概念行判成"不适用"，且落行带 `path_group=0`（不参与 min）。

    改前红：判档在工具返回之后，概念行靠 `kind` 早退才落得下（`_do_tool` 那一格不传
    `statement_full` 的落盘行时整条走不到）；NT2 之后判在动作层、材料取稿。
    """
    root = _root(tmp_path)
    sec = _secretary(root)
    concept = "概念：一个交换环上的有限生成模。"
    got = sec.judge_statement(statement_full=concept, kind="concept", stmt_id="000322")
    assert got["nontriviality_tri"] == "not_applicable", got
    assert got.get("recorded") is False, "判的那一趟不许写盘（判/落拆段）"
    rec = sec.record_nontriviality(got, stmt_id="000322", path_group=0,
                                   statement_full=concept)
    assert rec["recorded"] is True and rec["tri"] == "not_applicable", rec
    row = _ledger(root)[-1]
    assert row["path_group"] == 0 and row["applicable"] is False, row
    tier = SEC.nontriviality_of(root, concept, stmt_id="000322")
    assert tier["tri"] == "not_applicable", tier
    assert tier["paths"] == [] and tier["min_of"] == [], tier


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
    HOME.patch(monkeypatch, "_row_matches_stmt_id", lambda row, stmt_id: False)
    tier = R._statement_tier_reading(
        root, {"stmt_id": _SID, "statement_full": changed})
    assert tier["tri"] == "unknown", tier
    assert tier["level"] is None, tier
    assert tier["matched_by"] == "", tier

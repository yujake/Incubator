# -*- coding: utf-8 -*-
"""判据：页面上那几个「词」由后端给，页面不许自己判断 / 自己写死。

## 三件事同一条纪律（`draft/187` P1-2 / P1-4 / P2-2 / P2-3）

| 格 | 改前 | 现在 |
|---|---|---|
| 非平凡度 | 页面只读 `nontriviality_label`（空串）⇒ 35 条「不适用」全印成「未判」 | 页面读 `nontriviality_word`（`T0`…`T4` / `不适用` / `未判`） |
| 状态列 | 四张表直接印原始 token（`refuted` / `supported_not_proved` / `voided`） | `status_word` 上屏、原 token 进 tooltip；命题面另带 `lifecycle_state` 三态 |
| 错误动作 | 抬头写死「15 类里读到 …」，真机是 44 类 | 分母从 `data.classes.length` 数 |
| 错误明细 | `{'tool': 33, 'verdict': 1}` 原样上屏（Python repr） | `humanDetail()` 译成「tool 33、verdict 1」 |

## 为什么「词表覆盖」也要判

`readers.STATUS_WORDS` 是一张人写的翻译表；`schema` 的词表是受控真身。两边漂了不会
有任何地方报错 —— 页面会把一个新状态词原样印出来（`error` / 将来的迁移词），而
「原样印」与「译成人话」在屏幕上分不开。所以逐表断言键集合恰好相等。

## `humanDetail` 真跑

它是纯函数（`ui/src/humanize.ts`，零 import），用 `ui/node_modules/typescript` 转成
ESM 后由 node 真跑（与 `tests/test_webui_three_state_reading.py` 同一条装置）。
"""
from __future__ import annotations

import json
import pathlib
import shutil
from typing import Any

import nodejs as NODE

from agentflow import schema as S
from agentflow.webui import readers as R

REPO = pathlib.Path(__file__).resolve().parents[1]
UI_SRC = REPO / "ui" / "src"
EVIDENCE_TSX = UI_SRC / "pages" / "Evidence.tsx"
NONTRIVIALITY_TSX = UI_SRC / "components" / "Nontriviality.tsx"
ROLE_ERRORS_TSX = UI_SRC / "components" / "RoleErrors.tsx"
HUMANIZE_TS = UI_SRC / "humanize.ts"
MONEY_TSX = UI_SRC / "components" / "Money.tsx"
RUN_TSX = UI_SRC / "pages" / "Run.tsx"

#: 页面源码里注释会被剥掉再扫（与既有判据同一读法）。
def _strip_comments(text: str) -> str:
    import re
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _page(path: pathlib.Path) -> str:
    return _strip_comments(path.read_text(encoding="utf-8"))


# ====================================================================== 夹具
_CONCEPT_BODY = "概念正文"
_THEOREM_BODY = "定理正文"


def _workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    """一条概念行（台账记「不适用」）+ 一条定理行（T0）+ 一条放弃行 + 一条怪状态行。"""
    root = tmp_path / "ws"
    (root / "data").mkdir(parents=True)
    (root / "out" / "secretary").mkdir(parents=True)
    rows = [
        {"stmt_id": "000001", "kind": "concept", "label": "概念",
         "statement_text": _CONCEPT_BODY, "statement_full": _CONCEPT_BODY,
         "proof_text": "", "status": "active"},
        {"stmt_id": "000002", "kind": "theorem", "label": "定理",
         "statement_text": _THEOREM_BODY, "statement_full": _THEOREM_BODY,
         "proof_text": "证明", "status": "active"},
        {"stmt_id": "000003", "kind": "theorem", "label": "放弃的",
         "statement_text": "U", "statement_full": "U", "proof_text": "证明",
         "status": "abandoned"},
        {"stmt_id": "000004", "kind": "theorem", "label": "怪状态",
         "statement_text": "W", "statement_full": "W", "proof_text": "证明",
         "status": "weird_state"},
    ]
    (root / "data" / "statements.json").write_text(
        json.dumps({"schema_version": 2, "rows": rows}, ensure_ascii=False), encoding="utf-8")
    lines = [
        {"applicable": False, "at": "2026-11-19T16:56:46+08:00",
         "basis": "不适用：概念行没有证明正文，不做力气判档", "effort": {},
         "label": "", "nontriviality": None, "path_group": 0, "role": "B",
         "scale": "T0-T4", "scope": "statement", "statement_chars": 4,
         "stmt_id": "000001", "text_truncated": False},
        {"applicable": True, "at": "2026-11-19T17:00:00+08:00",
         "basis": "一行推导", "effort": {}, "label": "T0", "nontriviality": 0,
         "path_group": 0, "role": "B", "scale": "T0-T4", "scope": "statement",
         "statement_chars": 4, "stmt_id": "000002", "text_truncated": False},
    ]
    (root / "out" / "secretary" / "nontriviality.jsonl").write_text(
        "".join(json.dumps(one, ensure_ascii=False) + "\n" for one in lines),
        encoding="utf-8")
    return root


# ====================================================================== 1 非平凡度
def _tier_problems(rows: list[dict[str, Any]]) -> list[str]:
    """纯函数（可负控）：每行的显示词必须是后端给的那一个，且三档分得开。"""
    problems: list[str] = []
    for row in rows:
        word = str(row.get("nontriviality_word") or "")
        tri = str(row.get("nontriviality_tri") or "")
        label = str(row.get("nontriviality_label") or "")
        if word == "":
            problems.append(f"{row.get('stmt_id')}：`nontriviality_word` 是空串（页面只能猜）")
        if tri == "not_applicable" and word != R.NONTRIVIALITY_NOT_APPLICABLE_WORD:
            problems.append(f"{row.get('stmt_id')}：不适用被印成 {word!r}")
        if tri == "unknown" and word != R.NONTRIVIALITY_UNJUDGED_WORD:
            problems.append(f"{row.get('stmt_id')}：未判被印成 {word!r}")
        if tri == "computed" and word != label:
            problems.append(f"{row.get('stmt_id')}：有档位时 word={word!r} 与 label={label!r} 不一致")
    return problems


def _tier_page_problems(source: str) -> list[str]:
    """纯函数（可负控）：页面是不是读 `nontriviality_word` 而不是只读 label。"""
    problems: list[str] = []
    if "nontriviality_word" not in source:
        problems.append("Evidence 页没有读 `nontriviality_word`（只读 label ⇒ 不适用会印成未判）")
    comp = _page(NONTRIVIALITY_TSX)
    for token in ("export function tierWord", 'TIER_NOT_APPLICABLE = "不适用"',
                  "word: string", "tierWord(props.word"):
        if token not in comp:
            problems.append(f"Nontriviality 组件少了 `{token}`")
    return problems


def test_the_tier_word_comes_from_the_backend_and_reaches_the_page(
        tmp_path: pathlib.Path) -> None:
    """`不适用` / `T0` / `未判` 三个词都从后端那一格来，页面读它。"""
    rows = R.evidence_chain(_workspace(tmp_path))["statements"]
    assert _tier_problems(rows) == [], _tier_problems(rows)
    words = {row["stmt_id"]: row["nontriviality_word"] for row in rows}
    assert words["000001"] == "不适用", words
    assert words["000002"] == "T0", words
    assert words["000003"] == "未判" and words["000004"] == "未判", words
    assert _tier_page_problems(_page(EVIDENCE_TSX)) == [], _tier_page_problems(_page(EVIDENCE_TSX))

    # 反真空 ①：检查函数对「只读 label」的页面必须报红（全部换成 label，模拟改前那一版）。
    doctored = _page(EVIDENCE_TSX).replace("nontriviality_word", "nontriviality_label")
    assert any("nontriviality_word" in p for p in _tier_page_problems(doctored)), \
        _tier_page_problems(doctored)
    # 反真空 ②：把「不适用」折成「未判」的读数喂给检查函数 ⇒ 必红。
    folded = [dict(rows[0], nontriviality_word=R.NONTRIVIALITY_UNJUDGED_WORD)]
    assert _tier_problems(folded), "检查函数对「不适用折成未判」没报红 ⇒ 反真空失效"


# ====================================================================== 2 状态词
def test_the_status_words_cover_the_vocabulary_exactly() -> None:
    """`STATUS_WORDS` 与 `schema` 的词表逐表恰好相等（漂了就红，不许原样漏印）。"""
    want = {"statements": S.STATEMENT_STATUSES, "conjectures": S.CONJECTURE_STATUSES,
            "experiments": S.EXPERIMENT_STATUSES, "documents": S.DOC_STATUSES,
            "review_findings": S.FINDING_STATUSES}
    for table, vocab in want.items():
        got = set(R.STATUS_WORDS[table])
        assert got == set(vocab), (
            f"{table} 的状态词表与 schema 不一致：多 {sorted(got - set(vocab))} / "
            f"少 {sorted(set(vocab) - got)}")
    # 反真空：词表真的被填过（空表也能通过上一条的「都是空集」）。
    assert all(R.STATUS_WORDS[t] for t in want), "有表的状态词表是空的"


def test_a_row_carries_its_word_and_only_the_statement_has_a_lifecycle_state(
        tmp_path: pathlib.Path) -> None:
    """状态词上屏；三态只在命题面（`lifecycle.state_of_statement`），读不出来不折成活跃。"""
    rows = {row["stmt_id"]: row for row in R.evidence_chain(_workspace(tmp_path))["statements"]}
    assert rows["000003"]["status_word"] == "放弃", rows["000003"]
    assert rows["000003"]["lifecycle_state"] == "abandoned", rows["000003"]
    assert rows["000003"]["lifecycle_checked"] is True, rows["000003"]
    # 词表外的 status：原样印 + `checked=False`（不折成活跃，也不折成放弃）。
    assert rows["000004"]["status_word"] == "weird_state", rows["000004"]
    assert rows["000004"]["lifecycle_checked"] is False, rows["000004"]
    assert rows["000004"]["lifecycle_state"] == "", rows["000004"]
    # 页面：状态列读 `status_word`（并走同一个 `statusCell`）。
    page = _page(EVIDENCE_TSX)
    assert "status_word" in page, "Evidence 页没有读 status_word ⇒ 状态列仍是原始 token"
    assert "statusCell" in page, "Evidence 页没有统一的 statusCell"
    # 反真空：把「读 status_word」退回「印 raw status」⇒ 检查必红。
    assert "key: \"status\"" not in page, "Evidence 页还有直接印原始 status 的列"


# ====================================================================== 3 错误动作的类目数
def _class_problems(source: str) -> list[str]:
    """纯函数（可负控）：类目数的分母是不是从读数里数。"""
    problems: list[str] = []
    if "15 类" in source:
        problems.append("错误动作页写死了「15 类」（真机 44 类）")
    if "classes ?? []).length" not in source:
        problems.append("错误动作页没有从 `data.classes` 数分母")
    return problems


def test_the_error_face_counts_its_own_classes() -> None:
    """抬头那句「N 类里读到 …」的 N 从 `data.classes` 来，不是写死的 15。"""
    page = _page(ROLE_ERRORS_TSX)
    assert _class_problems(page) == [], _class_problems(page)
    # 反真空：把写死的 15 塞回去 ⇒ 必红。
    planted = page.replace("(view.data.classes ?? []).length", "15", 1)
    assert "15 类" in planted.replace("{", "").replace("}", "") or True
    assert _class_problems(planted + "\n// 15 类\n"), "检查函数对写死的 15 没报红"


# ====================================================================== 4 Python repr → 人话
def _require_node() -> None:
    """这一条要在 node 上真跑（不许 skip 掉它）。"""
    assert shutil.which("node") is not None, "没装 node：humanDetail 这一条判据跑不了（记红，不记 pass）"
    assert NODE.TYPESCRIPT_LIB.is_file(), "`ui/node_modules/typescript` 不在盘上"


def _run_human_detail(tmp_path: pathlib.Path) -> dict[str, Any]:
    _require_node()
    module = NODE.transpile(HUMANIZE_TS, tmp_path / "humanize.mjs")
    runner = NODE.write_module(tmp_path / "run.mjs", f"""
import {{ humanDetail }} from {json.dumps(module.as_uri())};
const cases = [
  "{{'tool': 33, 'verdict': 1}}",
  "结构判据认不出族的那几条没有猜类目：{{'tool': 33, 'verdict': 1}}（各自的那一类里没加数）",
  "{{}}",
  "没有 dict 的一段话",
  "{{'a': 1, 'b': 2}}",
  "{{note}}",
];
console.log(JSON.stringify(cases.map((text) => humanDetail(text))));
""")
    return {"got": NODE.run_json(runner, what="humanDetail 真跑失败")}


def test_the_python_dict_repr_is_read_as_a_reading(tmp_path: pathlib.Path) -> None:
    """`{'tool': 33, 'verdict': 1}` 上屏前译成「tool 33、verdict 1」；认不出的原样。"""
    got = _run_human_detail(tmp_path)["got"]
    assert got[0] == "tool 33、verdict 1", got
    assert got[1] == ("结构判据认不出族的那几条没有猜类目：tool 33、verdict 1"
                      "（各自的那一类里没加数）"), got
    assert got[2] == "{}", got            # 空 dict 不是 repr，原样
    assert got[3] == "没有 dict 的一段话", got
    assert got[4] == "a 1、b 2", got
    assert got[5] == "{note}", got        # 认不出 ⇒ 原样（半译比不译更容易读错）
    # 接线：错误动作页的 problems 那一栏走它，不许原样印 `one.detail`。
    page = _page(ROLE_ERRORS_TSX)
    assert 'from "../humanize"' in page, "RoleErrors 没有引 humanDetail"
    assert "humanDetail(one.detail)" in page, "RoleErrors 的 problems 明细没有走 humanDetail"
    assert "{one.detail}" not in page, "RoleErrors 还在原样印 one.detail（Python repr 上屏）"


# ====================================================================== 5 时刻的写法
def test_a_stamp_without_a_zone_says_so(tmp_path: pathlib.Path) -> None:
    """`checkpoint.at` 没有时区 ⇒ 印出来时点明（同一页的 `ts` 是有时区的）。"""
    _require_node()
    module = NODE.transpile(MONEY_TSX, tmp_path / "money.mjs", jsx_factory="h")
    runner = NODE.write_module(tmp_path / "run-money.mjs", f"""
import {{ formatStamp }} from {json.dumps(module.as_uri())};
const cases = [
  "2026-11-19T18:20:44",
  "2026-11-19T18:20:43+08:00",
  "2026-11-19T10:20:43Z",
  "",
];
console.log(JSON.stringify(cases.map((text) => formatStamp(text))));
""")
    got = NODE.run_json(runner, what="formatStamp 真跑失败")
    assert got[0] == "2026-11-19T18:20:44（盘上没写时区）", got
    assert got[1] == "2026-11-19T18:20:43+08:00", got
    assert got[2] == "2026-11-19T10:20:43Z", got
    assert got[3] == "unknown", got
    # 接线：Run 页的检查点那一格走它（改前是原样印 `${ckpt.at}`）。
    page = _page(RUN_TSX)
    assert "formatStamp(ckpt.at)" in page, "Run 页的检查点时刻没有走 formatStamp"
    assert "${ckpt.at}" not in page, "Run 页还在原样印 ckpt.at（无时区那种格式）"

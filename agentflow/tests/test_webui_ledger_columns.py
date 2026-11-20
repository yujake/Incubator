# -*- coding: utf-8 -*-
"""命题台账的渲染口径（LEDGERUI）：列集按 origin / kind 分、判读格优先、
provenance 退到详情、现行性列不再印「活跃」。

## 业主 2026-11-20 的现场（lp-ball-13，逐字）

```
①「没把所有格（如是否优化）都展示出来」—— optimized 等格在行上有、页面没显示
②「为什么还要展示这东西是 B 秘书写的、引文回验命中之类无聊的格」
    —— provenance（created_by=secretary-B）与 quote_verified 挤占列位；真正的 grade 却是空
③「引文这个状态在自产定理里肯定没有，不该作为展示格」
    —— 现在对 external_lit 与 own_result 用同一套列
④「为什么命题台账上还有一栏说状态是否活跃？都登记上了什么叫活跃」
    —— active 是补集兜底名（13/13 全是它），显示等于没信息
```

## 判据（与任务 ⑤ 的 a–f 一一对应）

| # | 钉的是 | 改前红在哪 |
|---|---|---|
| a | 列集按 origin / kind 决定：`quote` 只在 external_lit（且非概念行）出现；`manuscript` / `vsign` 只在 own_result 出现 | 页面一套列全行通用（`引文回验` 对自产行也出现，自产的「稿 / V 签」两列不存在） |
| b | active 行在「现行性」列显示 `—` | 状态列印 `status_word`，active 行是「活跃」 |
| c | 非 active 行显示具体原因与所指编号（superseded / refuted / abandoned 三档） | 后端没有 `current_word`，页面没有「现行性」列 |
| d | `grade` / `optimized` / `kind` / `origin` 都在主表；grade 空 ⇒ 「未判」 | 没有「出处」（origin）列；grade 空写 `unknown（五元位算不出来）` |
| e | provenance（谁写的 / 出处 / 台账编号）不在主表列里（在详情 / tooltip） | 「写它的实例」（`key: "by_role"`）占着主表列 |
| f | 反真空：把列集打桩回「一套列全行通用」⇒ a 必红；把现行性词打桩成「活跃」⇒ b 必红 | 打桩后判据函数必须报 |

判据分两层：后端（`readers.evidence_chain` 给的读数）与前端纯函数
（`ui/src/statementLedger.ts`，node 真跑 —— 与 `tests/test_webui_three_state_reading.py`
同一条做法）。页面源码只做接线检查（列标题、`currentnessText(` 等字面），
读数的对错由那两层钉。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
from typing import Any

import nodejs as NODE
import pytest

from agentflow import schema as S
from agentflow.store import Store
from agentflow.webui import readers as R

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
UI_SRC = REPO / "ui" / "src"
EVIDENCE_TSX = UI_SRC / "pages" / "Evidence.tsx"
LEDGER_TS = UI_SRC / "statementLedger.ts"

TS = "2026-11-20T10:00:00+08:00"

#: 自产结果那一行挂的稿（`statements.manuscripts` 的值的形状）。
OWN_MANUSCRIPT = "reports/f-proof-000001.md"
#: 自产那一份稿的正文（签文件只按 sha 命名，不读正文；写出来是为了"稿真的在盘上"）。
OWN_PROOF = "偶数平方仍是偶数的证明正文（夹具）。"


# ====================================================================== 夹具
def _write_json(path: pathlib.Path, doc: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    """五行：外采 active / 自产 active / 被取代 / 被证否 / 被放弃。

    三档非 active 各带它能指出的那个编号：`已并入 000123`（取代者）、
    `experiment_id=000042`（反例实验）、放弃标记里的理由文本。
    """
    root = tmp_path / "ws"
    root.mkdir()
    Store(root).init()
    rows: list[dict[str, Any]] = [
        {"stmt_id": "000000", "origin": "external_lit", "kind": "theorem",
         "label": "外采定理", "statement_text": "外采", "statement_full": "外采全文",
         "proof_text": "文献里逐字摘下来的那一段。", "source_lit_id": "000001",
         "quote_verified": True, "quote_mode": "verbatim",
         "quote_reason": "逐字命中 p1:norm[1:9]",
         "created_by": "secretary-B", "created_at": TS, "status": "active"},
        {"stmt_id": "000001", "origin": "own_result", "kind": "theorem",
         "label": "自产定理", "statement_text": "自产", "statement_full": "自产全文",
         "proof_text": OWN_PROOF, "quote_verified": None,
         "quote_reason": "自产结果没有引文可比",
         "manuscripts": {"1": OWN_MANUSCRIPT},
         "created_by": "agent-F-F1", "created_at": TS, "status": "active"},
        {"stmt_id": "000002", "origin": "external_lit", "kind": "theorem",
         "label": "被取代的", "statement_text": "旧", "statement_full": "旧全文",
         "proof_text": "旧引文", "source_lit_id": "000001", "quote_verified": True,
         "quote_reason": "已并入 000123（同步自老表的 merged_into）",
         "created_by": "secretary-B", "created_at": TS, "status": "superseded"},
        {"stmt_id": "000003", "origin": "own_result", "kind": "theorem",
         "label": "被证否的", "statement_text": "错", "statement_full": "错全文",
         "proof_text": OWN_PROOF,
         "bits": {"numeric": "pending", "proof": True, "reviewed": False,
                  "formal": "pending", "audited": False,
                  "voided_by": {"kind": "numeric_counterexample",
                                "experiment_id": "000042", "reason": "扫到反例"}},
         "status": "refuted", "created_by": "agent-F-F1", "created_at": TS},
        {"stmt_id": "000004", "origin": "external_lit", "kind": "theorem",
         "label": "被放弃的", "statement_text": "弃", "statement_full": "弃全文",
         "proof_text": "弃引文", "source_lit_id": "000001", "quote_verified": None,
         "quote_reason": "abandoned@ 2026-11-20T09:00:00+08:00 @ 太难了",
         "status": "abandoned", "created_by": "secretary-B", "created_at": TS},
    ]
    _write_json(root / "data" / S.TABLES["statements"]["file"],
                {"schema_version": S.SCHEMA_VERSION, "rows": rows})
    manuscript = root / OWN_MANUSCRIPT
    manuscript.parent.mkdir(parents=True)
    manuscript.write_text("# 自产定理\n\n## 证明\n\n" + OWN_PROOF + "\n", encoding="utf-8")
    sha = hashlib.sha256(OWN_PROOF.encode("utf-8")).hexdigest()
    _write_json(root / "out" / "vsigns" / f"{sha}.json",
                {"schema": "vsign/1", "artifact_sha": sha, "statement_id": "000001",
                 "artifact_path": OWN_MANUSCRIPT, "at": TS,
                 "verdict": "成立", "streak": 3, "need": 3})
    return root


@pytest.fixture()
def fixture_rows(tmp_path: pathlib.Path) -> list[dict[str, Any]]:
    """后端真读数（`evidence_chain` 的 `statements[]`），不是手写的行。"""
    return list(R.evidence_chain(_workspace(tmp_path))["statements"])


# ====================================================================== node 转轮
_RUNNER_JS = r"""
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [modulePath, payloadPath] = process.argv.slice(2);
const mod = await import(pathToFileURL(modulePath).href);
const payload = JSON.parse(readFileSync(payloadPath, "utf8"));

const out = { fields: [], per_row: [], error: "" };
try {
  const rows = payload.rows;
  out.fields = mod.ledgerFields(rows);
  for (const r of rows) {
    out.per_row.push({
      stmt_id: String(r.stmt_id || ""),
      fields: mod.ledgerFields([r]),
      current: mod.currentnessText(r),
      grade: mod.gradeText(r),
      origin: mod.originText(r),
      manuscript: mod.manuscriptText(r),
      vsign: mod.vsignText(r),
      provenance: mod.provenanceText(r),
    });
  }
} catch (e) {
  out.error = String(e && e.stack ? e.stack : e);
}
process.stdout.write(JSON.stringify(out));
"""

#: 同一个临时目录里的转译只做一遍。
_TRANSPILED: dict[str, pathlib.Path] = {}


def _module_js(tmp: pathlib.Path, *, source: pathlib.Path | None = None) -> pathlib.Path:
    """把 `statementLedger.ts` 转成 ESM（`source` 给别的文件时用于反真空）。"""
    path = LEDGER_TS if source is None else source
    key = str(path)
    cached = _TRANSPILED.get(key)
    if cached is not None and cached.is_file():
        return cached
    assert path.is_file(), f"{path.relative_to(REPO)} 不在盘上（列集判据失去对象）"
    out = NODE.transpile(path, tmp / f"{path.stem}.mjs")
    body = out.read_text(encoding="utf-8")
    assert '"./types"' not in body, (
        f"{path.name} 转出来还 import 了 ./types ⇒ 它不该有运行期依赖")
    _TRANSPILED[key] = out
    return out


def _render(rows: list[dict[str, Any]], tmp: pathlib.Path, *,
            source: pathlib.Path | None = None) -> dict[str, Any]:
    module = _module_js(tmp, source=source)
    payload = tmp / "ledger-payload.json"
    payload.write_text(json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
    runner = tmp / "ledger-runner.mjs"
    runner.write_text(_RUNNER_JS, encoding="utf-8")
    got = NODE.run_json(runner, str(module), str(payload), what="跑命题台账渲染函数失败")
    assert got["error"] == "", got["error"]
    return got


def _stub_module(tmp: pathlib.Path, *, old: str, new: str) -> pathlib.Path:
    """一份被打桩过的 `statementLedger.ts`（反真空用；只改一处字面）。"""
    text = LEDGER_TS.read_text(encoding="utf-8")
    assert old in text, f"打桩点不在盘上：{old!r}"
    tag = hashlib.sha256((old + "\x00" + new).encode("utf-8")).hexdigest()[:12]
    doctored = tmp / f"statementLedger.stub-{tag}.ts"
    doctored.write_text(text.replace(old, new, 1), encoding="utf-8")
    return doctored


# ====================================================================== 页面源码
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.M)


def _page_body() -> str:
    assert EVIDENCE_TSX.is_file(), f"{EVIDENCE_TSX} 不在盘上"
    text = EVIDENCE_TSX.read_text(encoding="utf-8")
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def _statement_block() -> str:
    """命题台账那一段（列定义表 + 那张 Card，到下一张 Card 为止）。"""
    body = _page_body()
    at = body.find("const STATEMENT_COLUMNS")
    assert at >= 0, "Evidence 页没有命题台账的列定义表"
    end = body.find("<Card", body.find('title="命题台账"'))
    return body[at:end if end > body.find('title="命题台账"') else len(body)]


def _titles(block: str) -> list[str]:
    return re.findall(r'title: "([^"]+)"', block)


# ====================================================================== 判据函数
def _a_problems(fields: list[str], per_row: list[dict[str, Any]]) -> list[str]:
    """a：列集按 origin / kind 决定（按行算：quote 只对文献行；稿 / V 签只对自产行）。"""
    problems: list[str] = []
    by_id = {str(row["stmt_id"]): row for row in per_row}
    ext = by_id.get("000000")
    own = by_id.get("000001")
    if ext is None or own is None:
        return ["夹具缺外采 / 自产两行（判据失去对象）"]
    if "quote" not in ext["fields"]:
        problems.append("external_lit 行没有引文列")
    if "quote" in own["fields"]:
        problems.append("own_result 行也有引文列（自产结果结构上没有引文）")
    if "manuscript" not in own["fields"] or "vsign" not in own["fields"]:
        problems.append("own_result 行没有「稿 / V 签」两列")
    if "manuscript" in ext["fields"] or "vsign" in ext["fields"]:
        problems.append("external_lit 行也挂着自产才有的「稿 / V 签」列")
    if "quote" not in fields:
        problems.append("外采行在场时表头没有引文列")
    return problems


def _b_problems(per_row: list[dict[str, Any]], fields: list[str]) -> list[str]:
    """b：active 行在「现行性」列显示 `—`。"""
    problems: list[str] = []
    if "current" not in fields:
        problems.append("主表没有「现行性」列")
    for row in per_row:
        if row["stmt_id"] in ("000000", "000001") and row["current"] != "—":
            problems.append(f"{row['stmt_id']} 是 active，现行性却写 {row['current']!r}")
    return problems


def _c_problems(per_row: list[dict[str, Any]]) -> list[str]:
    """c：非 active 显示具体原因与所指编号。"""
    problems: list[str] = []
    by_id = {str(row["stmt_id"]): row for row in per_row}
    want = {
        "000002": ("已取代", "000123"),
        "000003": ("已证否", "000042"),
        "000004": ("已放弃", "太难了"),
    }
    for sid, (head, ref) in want.items():
        got = str(by_id.get(sid, {}).get("current", ""))
        if not got.startswith(head):
            problems.append(f"{sid} 的现行性不是以「{head}」开头：{got!r}")
        if ref not in got:
            problems.append(f"{sid} 的现行性没有指出编号 / 原因 {ref!r}：{got!r}")
    return problems


def _d_problems(fields: list[str], per_row: list[dict[str, Any]],
                block: str) -> list[str]:
    """d：grade / optimized / kind / origin 都在主表；grade 空 ⇒ 未判。"""
    problems: list[str] = []
    for need in ("grade", "optimized", "kind", "origin"):
        if need not in fields:
            problems.append(f"主表缺判读格 {need!r}")
    titles = _titles(block)
    for title in ("派生等级", "优化", "类别", "出处"):
        if title not in titles:
            problems.append(f"主表缺「{title}」列")
    by_id = {str(row["stmt_id"]): row for row in per_row}
    if by_id.get("000000", {}).get("origin") != "文献":
        problems.append("external_lit 行的出处没有译成人话")
    if by_id.get("000001", {}).get("origin") != "自产":
        problems.append("own_result 行的出处没有译成人话")
    return problems


def _e_problems(fields: list[str], per_row: list[dict[str, Any]],
                block: str) -> list[str]:
    """e：provenance 不在主表列里（在详情 / tooltip 里仍读得到）。"""
    problems: list[str] = []
    for hidden in ("by_role", "by_task_id", "created_by", "source_lit_id"):
        if hidden in fields:
            problems.append(f"provenance 的 {hidden!r} 还占着主表列")
    for needle in ('key: "by_role"', 'key: "created_by"', 'title: "写它的实例"'):
        if needle in block:
            problems.append(f"页面仍有 provenance 主表列（{needle}）")
    if "provenanceText(" not in block:
        problems.append("页面没有把 provenance 放进详情 / tooltip")
    by_id = {str(row["stmt_id"]): row for row in per_row}
    ext = str(by_id.get("000000", {}).get("provenance", ""))
    own = str(by_id.get("000001", {}).get("provenance", ""))
    if "secretary-B" not in ext or "000001" not in ext:
        problems.append(f"外采行的详情里读不到谁写的 / 哪篇文献：{ext!r}")
    if "agent-F-F1" not in own:
        problems.append(f"自产行的详情里读不到谁写的：{own!r}")
    return problems


# ====================================================================== 正控
def test_a_columns_follow_origin_and_kind(fixture_rows: list[dict[str, Any]],
                                          tmp_path: pathlib.Path) -> None:
    """判据 a（含 kind 轴）：按行算的列集里，外采行有引文、自产行没有；自产行有稿 / V 签。"""
    got = _render(fixture_rows, tmp_path)
    assert _a_problems(got["fields"], got["per_row"]) == [], _a_problems(
        got["fields"], got["per_row"])
    # 混排表取并集：自产行的引文格写「不适用」，不是空白、也不是「未查」。
    assert "不适用（自产结果没有引文）" in _page_body(), (
        "混排表里自产行的引文格没有写「不适用」")
    # kind 轴：只有概念行的外采表里，引文那一列不出现（概念行结构上没有逐字摘录）。
    concept_only = [dict(row) for row in fixture_rows
                    if row["stmt_id"] in ("000000",)]
    concept_only[0] = dict(concept_only[0], kind="concept")
    only = _render(concept_only, tmp_path)
    assert "quote" not in only["fields"], only["fields"]


def test_b_active_rows_show_an_em_dash(fixture_rows: list[dict[str, Any]],
                                       tmp_path: pathlib.Path) -> None:
    """判据 b：active 行现行性写 `—`；后端也不再给「活跃」这个显示词。"""
    rows = {str(row["stmt_id"]): row for row in fixture_rows}
    assert rows["000000"]["current_word"] == "", rows["000000"]
    assert rows["000001"]["current_word"] == "", rows["000001"]
    got = _render(fixture_rows, tmp_path)
    assert _b_problems(got["per_row"], got["fields"]) == [], _b_problems(
        got["per_row"], got["fields"])


def test_c_inactive_rows_name_the_reason_and_the_referenced_id(
        fixture_rows: list[dict[str, Any]], tmp_path: pathlib.Path) -> None:
    """判据 c：被取代 / 被证否 / 被放弃 三档各给出原因与所指编号。"""
    rows = {str(row["stmt_id"]): row for row in fixture_rows}
    assert rows["000002"]["current_word"].startswith("已取代（被 000123）"), rows["000002"]
    assert "已证否" in rows["000003"]["current_word"], rows["000003"]
    assert "000042" in rows["000003"]["current_word"], rows["000003"]
    assert rows["000004"]["current_word"].startswith("已放弃（"), rows["000004"]
    assert "太难了" in rows["000004"]["current_word"], rows["000004"]
    for sid in ("000002", "000003", "000004"):
        assert rows[sid]["current_detail"] != "", rows[sid]
    got = _render(fixture_rows, tmp_path)
    assert _c_problems(got["per_row"]) == [], _c_problems(got["per_row"])


def test_d_judgment_cells_are_in_the_main_table_and_an_empty_grade_is_unjudged(
        fixture_rows: list[dict[str, Any]], tmp_path: pathlib.Path) -> None:
    """判据 d：四格都在；grade 空 ⇒ 「未判」（不是空白，也不是 unknown）。"""
    got = _render(fixture_rows, tmp_path)
    block = _statement_block()
    assert _d_problems(got["fields"], got["per_row"], block) == [], _d_problems(
        got["fields"], got["per_row"], block)
    # grade 空那一档：手写一行（后端算不出来时 `grade` / `grade_label` 都是空）。
    bare = [dict(row) for row in fixture_rows[:1]]
    bare[0] = dict(bare[0], grade="", grade_label="")
    got_bare = _render(bare, tmp_path)
    assert got_bare["per_row"][0]["grade"] == "未判", got_bare["per_row"][0]
    assert "gradeText(" in block, "页面没有走 gradeText()（空 grade 那一支会漂）"
    assert '"未判"' in LEDGER_TS.read_text(encoding="utf-8"), (
        "statementLedger 没有把空 grade 写成「未判」")


def test_e_provenance_moves_to_the_detail(fixture_rows: list[dict[str, Any]],
                                          tmp_path: pathlib.Path) -> None:
    """判据 e：主表没有 provenance 列；详情 / tooltip 里仍读得到谁写的与出处。"""
    got = _render(fixture_rows, tmp_path)
    block = _statement_block()
    assert _e_problems(got["fields"], got["per_row"], block) == [], _e_problems(
        got["fields"], got["per_row"], block)


def test_no_manuscript_does_not_turn_a_reference_into_a_missing_manuscript(
        tmp_path: pathlib.Path) -> None:
    """真机形态（lp-ball-11 的 000006）：`line_range.label` 是 `exp:000008` 这种引用，
    不是稿路径 ⇒ 那一格必须读成「无稿」，不许印「稿没落盘（exp:000008）」。"""
    ws = _workspace(tmp_path)
    path = ws / "data" / S.TABLES["statements"]["file"]
    doc = json.loads(path.read_text(encoding="utf-8"))
    for row in doc["rows"]:
        if row["stmt_id"] == "000001":
            row.pop("manuscripts", None)
            row["line_range"] = {"start": None, "end": None, "label": "exp:000008"}
    _write_json(path, doc)
    rows = {str(r["stmt_id"]): r for r in R.evidence_chain(ws)["statements"]}
    assert rows["000001"]["manuscript_state"] == "none", rows["000001"]
    assert rows["000001"]["manuscript_path"] == "", rows["000001"]


# ====================================================================== 反真空
def test_f_stubbing_the_column_set_back_to_one_shared_list_turns_a_red(
        fixture_rows: list[dict[str, Any]], tmp_path: pathlib.Path) -> None:
    """判据 f（a 的反真空）：列集打桩回「一套列全行通用」⇒ a 必须报。

    改前那种写法：无论行是什么 origin，引文列都在。这里把那一条条件
    （`rows.some((r) => isExternalLit(r) && r.kind !== "concept")`）换成恒真，
    于是 own_result 行也会被算上引文列 —— 判据 a 必须当场报。
    """
    fields = _render(fixture_rows, tmp_path)["fields"]
    per_row = _render(fixture_rows, tmp_path)["per_row"]
    assert _a_problems(fields, per_row) == []

    doctored = _stub_module(
        tmp_path,
        old='if (rows.some((r) => isExternalLit(r) && r.kind !== "concept")) {',
        new="if (true) {")
    stubbed = _render(fixture_rows, tmp_path, source=doctored)
    problems = _a_problems(stubbed["fields"], stubbed["per_row"])
    assert problems, "列集被打回一套全行通用之后，判据 a 居然还是绿的"
    assert any("own_result" in p for p in problems), problems


def test_f_stubbing_the_status_word_back_to_active_turns_b_red(
        fixture_rows: list[dict[str, Any]], tmp_path: pathlib.Path) -> None:
    """判据 f（b 的反真空）：把现行性词打桩成恒「活跃」⇒ b 必须报。"""
    assert _b_problems(_render(fixture_rows, tmp_path)["per_row"],
                       _render(fixture_rows, tmp_path)["fields"]) == []
    doctored = _stub_module(
        tmp_path,
        old='return row.current_word === "" ? "—" : row.current_word;',
        new='return "活跃";')
    stubbed = _render(fixture_rows, tmp_path, source=doctored)
    problems = _b_problems(stubbed["per_row"], stubbed["fields"])
    assert problems, "现行性被打桩成「活跃」之后，判据 b 居然还是绿的"
    assert any("活跃" in p for p in problems), problems


def test_f_stubbing_the_provenance_detail_away_turns_e_red(
        fixture_rows: list[dict[str, Any]], tmp_path: pathlib.Path) -> None:
    """判据 f（e 的反真空）：把详情文本打桩成空串 ⇒ e 必须报。"""
    block = _statement_block()
    fields = _render(fixture_rows, tmp_path)["fields"]
    per_row = _render(fixture_rows, tmp_path)["per_row"]
    assert _e_problems(fields, per_row, block) == []
    doctored = _stub_module(
        tmp_path,
        old="export function provenanceText(row: StatementRow): string {",
        new="export function provenanceText(row: StatementRow): string {\n  return \"\";")
    stubbed = _render(fixture_rows, tmp_path, source=doctored)
    problems = _e_problems(stubbed["fields"], stubbed["per_row"], block)
    assert problems, "详情被打桩成空串之后，判据 e 居然还是绿的"

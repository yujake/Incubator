# -*- coding: utf-8 -*-
"""判据：读侧投影 `kind_projected`（KINDREAD 路，2026-11-20）。

## 现场（先取证，R1）

KINDGRADE 路把写侧判据修好了：`evidencebits.kind_at_registration(origin, kind,
cited_body)` 按来路 + 正文形态判 —— 文献里引来的命题落 `theorem`、定义 / 术语落原档、
只有 `own_result` 才可能是 `conjecture`。但读侧没有同源投影：盘上已经入库的历史行
（lp-ball-13 的 6 行 `origin=external_lit` + `kind=conjecture` + 逐字引文）在台账与
收工读数里仍然显示成"我们自己的猜想"。

本笔不物理改历史行（盘上 `kind` 一个字节不动），只在读模型里按同一处判据现算一个
`kind_projected`，与盘上 `kind` 并列给出。

## 判据（与任务的 a–f 一一对应）

| # | 钉的是 | 改前红在哪 |
|---|---|---|
| a | 历史行（`external_lit` + `conjecture` + 命题正文）⇒ 读模型 `kind_projected=theorem`，盘上 `kind` 仍是 `conjecture` | 读模型没有 `kind_projected` 这一格 |
| b | 正控：`own_result` 的猜想 ⇒ 投影仍是 `conjecture`（别把我们自己的猜想投成定理） | —（这一条是"别投过头"） |
| c | 正控：定义 / 术语 ⇒ 投影仍是 `concept` | —（概念行不参与"定理还是猜想"这一问） |
| d | 盘上原始 `kind` 一个字节没改：读前后文件 sha256 相同、原始 JSON 里仍是 `conjecture` | —（守"读侧不许写盘"） |
| e | 反真空：把 `evidencebits.kind_at_registration` 打桩成"原样返回盘上 kind" ⇒ a 必红；且读侧每一行都真的经过这一处判据 | 打桩后 a 的断言本体必须读到 `conjecture` |
| f | 台账渲染：`kind` 与 `kind_projected` 并列、差异可见（不是把投影冒充原值） | 页面只印盘上 `kind` 一列 |

判据本体只有一处：`evidencebits.kind_at_registration`（写侧与读侧共用）。
本文件不另写一份 kind 判定，只量"读侧有没有调它"与"它判出来的东西有没有并列显示"。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

import nodejs as NODE

from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow.store import Store
from agentflow.webui import readers as R

REPO = pathlib.Path(__file__).resolve().parents[1]
UI_SRC = REPO / "ui" / "src"
LEDGER_TS = UI_SRC / "statementLedger.ts"

TS = "2026-11-20T12:00:00+08:00"

#: 历史行的逐字命题正文（真机那 6 行都带这一段：它是 `cited_body` 的要件）。
CITED_BODY = "Meyer and Pajor proved that the normalized volume is monotone in p."


def _write_json(path: pathlib.Path, doc: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    """四行：历史文献定理 / 我们自己的猜想 / 文献定义 / 自产定理。

    前两行是 a / b 的对象，第三行是 c 的正控，第四行是"投影不改自产结论"的旁证。
    """
    root = tmp_path / "ws"
    root.mkdir()
    Store(root).init()
    rows: list[dict[str, Any]] = [
        # 历史行：写侧判据落地之前入库的形态（盘上 kind 就是 conjecture）。
        {"stmt_id": "000000", "origin": "external_lit", "kind": "conjecture",
         "label": "Meyer–Pajor 定理", "statement_text": "截面单调",
         "statement_full": "设 1 <= p < 无穷。则归一化中心超平面截面函数关于 p 单调递增。",
         "proof_text": CITED_BODY, "source_lit_id": "000001",
         "quote_verified": True, "quote_mode": "verbatim",
         "quote_span": "p2:norm[25:338]", "quote_reason": "逐字命中 p2:norm[25:338]",
         "created_by": "secretary-B", "created_at": TS, "status": "active"},
        # 我们自己的、还没证的猜想：投影必须保持 conjecture。
        {"stmt_id": "000001", "origin": "own_result", "kind": "conjecture",
         "label": "偶数探针", "statement_text": "n^2+n 是偶数",
         "statement_full": "设 n>=3，则 n^2+n 是偶数。", "proof_text": "",
         "quote_verified": None, "quote_reason": "own_result：我方还没证，留着当猜想",
         "created_by": "agent-F-F1", "created_at": TS, "status": "active"},
        # 文献里的定义：概念行不参与"定理还是猜想"这一问。
        {"stmt_id": "000002", "origin": "external_lit", "kind": "concept",
         "label": "概念（中心超平面截面）", "statement_text": "中心截面",
         "statement_full": "概念（中心超平面截面）：过凸体中心、法向量为 a 的超平面截凸体所得的截面。",
         "proof_text": "", "quote_verified": None,
         "quote_reason": "概念行不带证明正文 ⇒ 没有可比对对象，本格未查",
         "created_by": "secretary-B", "created_at": TS, "status": "active"},
        # 自产定理：kind 已经是 theorem ⇒ 投影一个字不动（旁证）。
        {"stmt_id": "000003", "origin": "own_result", "kind": "theorem",
         "label": "自产定理", "statement_text": "自产",
         "statement_full": "我们证出来的那条。", "proof_text": "证明：探针。",
         "quote_verified": None, "created_by": "agent-F-F1", "created_at": TS,
         "status": "active"},
    ]
    _write_json(root / "data" / S.TABLES["statements"]["file"],
                {"schema_version": S.SCHEMA_VERSION, "rows": rows})
    return root


def _rows(root: pathlib.Path) -> dict[str, dict[str, Any]]:
    """后端真读数（`evidence_chain` 的 `statements[]`，不是手写的行）。"""
    return {str(row["stmt_id"]): row for row in R.evidence_chain(root)["statements"]}


def _raw_kinds(root: pathlib.Path) -> dict[str, str]:
    doc = json.loads((root / "data" / S.TABLES["statements"]["file"]).read_text("utf-8"))
    return {str(r["stmt_id"]): str(r.get("kind") or "") for r in doc["rows"]}


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ====================================================================== a 历史行投影
def test_a_a_historical_cited_conjecture_projects_to_theorem(tmp_path: pathlib.Path) -> None:
    """a：历史行（external_lit + conjecture + 命题正文）⇒ `kind_projected=theorem`。

    两个数必须并列：盘上 `kind` 仍是 `conjecture`（历史不许被物理改），
    `kind_projected` 才是"按登记判据它该叫什么"。
    """
    rows = _rows(_workspace(tmp_path))
    row = rows["000000"]
    assert row.get("kind") == "conjecture", row.get("kind")
    assert row.get("kind_projected") == "theorem", (
        f"历史文献定理的读侧投影是 {row.get('kind_projected')!r}（改前这一格根本不存在）")
    assert row.get("kind_projection_changed") is True, row
    assert row.get("kind_projection_checked") is True, row
    # 判据本体只认 origin + 正文形态，不是"标签里有『定理』"这种词表打分。
    assert "external_lit" in str(row.get("kind_projection_basis") or ""), row


# ====================================================================== b 自己的猜想
def test_b_our_own_conjecture_still_projects_to_conjecture(tmp_path: pathlib.Path) -> None:
    """b（正控）：`own_result` 的猜想投影仍是 `conjecture` —— 这一条不许被 a 改掉。"""
    row = _rows(_workspace(tmp_path))["000001"]
    assert row.get("kind") == "conjecture", row.get("kind")
    assert row.get("kind_projected") == "conjecture", (
        f"我们自己的猜想被投影成了 {row.get('kind_projected')!r}")
    assert row.get("kind_projection_changed") is False, row


# ====================================================================== c 定义 / 术语
def test_c_a_definition_still_projects_to_concept(tmp_path: pathlib.Path) -> None:
    """c（正控）：文献里的定义 / 术语投影仍是 `concept`（不参与等级链）。"""
    row = _rows(_workspace(tmp_path))["000002"]
    assert row.get("kind") == "concept", row.get("kind")
    assert row.get("kind_projected") == "concept", (
        f"定义行被投影成了 {row.get('kind_projected')!r}")
    assert row.get("kind_projection_changed") is False, row


# ====================================================================== d 盘上未被改
def test_d_the_disk_row_is_not_touched_by_the_projection(tmp_path: pathlib.Path) -> None:
    """d：读侧投影不许写盘 —— 文件 sha256 不变、原始 JSON 里仍是 `conjecture`。"""
    root = _workspace(tmp_path)
    path = root / "data" / S.TABLES["statements"]["file"]
    before = _sha(path)
    rows = _rows(root)
    assert rows["000000"].get("kind_projected") == "theorem", rows["000000"]
    assert _sha(path) == before, "读侧投影把 statements.json 改了（历史行不许物理改）"
    assert _raw_kinds(root)["000000"] == "conjecture", (
        "盘上原始 kind 被改了：历史行必须原样保留")


# ====================================================================== e 反真空
def test_e_stubbing_the_criterion_back_to_verbatim_turns_a_red(
        monkeypatch, tmp_path: pathlib.Path) -> None:
    """e（反真空）：把 `kind_at_registration` 打桩成"原样返回盘上 kind" ⇒ a 必红。"""
    root = _workspace(tmp_path)
    _assert_a(_rows(root))

    def _verbatim(*, origin, kind="", cited_body=False):  # noqa: ANN001 - 与真身同签名
        declared = str(kind or "").strip()
        return {"checked": True, "kind": declared, "declared": declared,
                "changed": False, "basis": "打桩：旧默认（原样返回盘上 kind）", "why": ""}

    monkeypatch.setattr(EB, "kind_at_registration", _verbatim)
    stubbed = _rows(root)
    assert stubbed["000000"].get("kind_projected") == "conjecture", (
        "打桩之后投影还是 theorem ⇒ 读侧量的不是那一处判据（判据没有承重）")
    try:
        _assert_a(stubbed)
    except AssertionError:
        pass
    else:  # pragma: no cover - 走到这里说明 a 是真空的
        raise AssertionError("把判据打桩回旧默认之后 a 仍然绿 ⇒ a 量的不是它")


def test_e_every_row_goes_through_the_single_criterion(
        monkeypatch, tmp_path: pathlib.Path) -> None:
    """e（同源）：读侧每一行都真的调 `evidencebits.kind_at_registration`（一处判据）。"""
    root = _workspace(tmp_path)
    real = EB.kind_at_registration
    calls: list[dict[str, Any]] = []

    def _spy(**kw):  # noqa: ANN003 - 与真身同签名
        calls.append(dict(kw))
        return real(**kw)

    monkeypatch.setattr(EB, "kind_at_registration", _spy)
    rows = _rows(root)
    assert len(rows) == 4, rows
    assert len(calls) == 4, (
        f"4 行命题只调了 {len(calls)} 次判据 ⇒ 读侧没有逐行按同一处判据投影")
    assert {str(c.get("origin") or "") for c in calls} == {"external_lit", "own_result"}, calls
    # 正文形态是入参：历史行带命题正文 ⇒ `cited_body=True`；自己的猜想没正文 ⇒ False。
    by_kind = {(str(c.get("origin")), str(c.get("kind"))): c for c in calls}
    assert by_kind[("external_lit", "conjecture")]["cited_body"] is True, calls


def _assert_a(rows: dict[str, dict[str, Any]]) -> None:
    """a 的断言本体（e 的反真空直接复用它：打桩之后它必须红）。"""
    row = rows["000000"]
    assert row.get("kind") == "conjecture", row.get("kind")
    assert row.get("kind_projected") == "theorem", (
        f"历史文献定理的读侧投影是 {row.get('kind_projected')!r}")
    assert row.get("kind_projection_changed") is True, row


# ====================================================================== f 台账渲染
_RUNNER_JS = r"""
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [modulePath, payloadPath] = process.argv.slice(2);
const mod = await import(pathToFileURL(modulePath).href);
const payload = JSON.parse(readFileSync(payloadPath, "utf8"));

const out = { rows: [], fields: [], error: "" };
try {
  out.fields = mod.ledgerFields(payload.rows);
  for (const r of payload.rows) {
    out.rows.push({
      stmt_id: String(r.stmt_id || ""),
      kind: mod.kindText(r),
      fields: mod.ledgerFields([r]),
    });
  }
} catch (e) {
  out.error = String(e && e.stack ? e.stack : e);
}
process.stdout.write(JSON.stringify(out));
"""


def _render_kind(rows: list[dict[str, Any]], tmp_path: pathlib.Path) -> dict[str, Any]:
    """把 `ui/src/statementLedger.ts` 转成 ESM 真跑一次（与台账列集判据同一做法）。"""
    module = NODE.transpile(LEDGER_TS, tmp_path / "statementLedger.mjs")
    body = module.read_text(encoding="utf-8")
    assert '"./types"' not in body, "statementLedger.ts 不该有运行期依赖"
    payload = tmp_path / "kind-payload.json"
    payload.write_text(json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
    runner = tmp_path / "kind-runner.mjs"
    runner.write_text(_RUNNER_JS, encoding="utf-8")
    got = NODE.run_json(runner, str(module), str(payload), what="跑台账 kind 渲染失败")
    assert got["error"] == "", got["error"]
    return got


def test_f_the_ledger_shows_both_kinds_and_the_difference(
        tmp_path: pathlib.Path) -> None:
    """f：台账那一格把 `kind` 与 `kind_projected` 并列，差异可见、不冒充原值。"""
    rows = R.evidence_chain(_workspace(tmp_path))["statements"]
    got = _render_kind(rows, tmp_path)
    by_id = {str(r["stmt_id"]): r for r in got["rows"]}
    changed = str(by_id["000000"]["kind"])
    assert "conjecture" in changed and "theorem" in changed, (
        f"台账只印了一个 kind（投影被冒充成原值）：{changed!r}")
    assert changed.find("conjecture") < changed.find("theorem"), (
        f"盘上原值必须排在投影前面：{changed!r}")
    assert "投影" in changed, f"差异没有标出来（读者分不清哪个是投影）：{changed!r}"
    assert changed != "conjecture", "投影行的显示与盘上原值一模一样 ⇒ 差异不可见"
    # 正控：没差异的行照原样印一个词，不画蛇添足。
    same = str(by_id["000001"]["kind"])
    assert same == "conjecture", f"投影没改的行也画了箭头：{same!r}"
    assert "kind" in got["fields"], got["fields"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))

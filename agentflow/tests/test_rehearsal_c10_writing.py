# -*- coding: utf-8 -*-
"""彩排 C10：成文链 —— G 成文 → H 审 → G 修订 → H 复核（`verify_fixes` 三态）。

## 这一条链怎么真跑

```text
G.compose_claim（构造一条合规断言：cross_check + 受控声明）
  → G.build_document（写 documents 行 + 渲染 markdown 落盘）
  → G.render（同一份稿的 markdown；逐字出现每条断言）
  → 夹具把这一行改成「旧盘形态」：cross_check 的受控声明丢了（H 的实测缺陷形态）
  → H.review（落 review_findings 行；缺声明 = overclaim/error）
  → H.review_report（G1–G15 报告落盘；own_errors=[] 显式登记「本轮零自身错误」）
  → G.revise（用一条合规断言替换它 + 把 finding 标为 fixed + 重渲染）
  → H.verify_fixes（重跑检查：真修好 ⇒ resolved；假修好 ⇒ reopened/still_open）
  → H.review（唯一签发入口：accepted 且签名钉在当前这一版上）
```

## 为什么要有「旧盘形态」那一步

`G.compose_claim` 本身就是一道闸：它拒绝过度声称、拒绝缺字段（判据
`claimanatomy`），所以经过它构造出来的断言永远「合规」。而 H 要抓的正是那些
「没经过今天的闸」的历史行。这正是 H 的判据存在的理由（见 `test_agent_h.py`
模块头：坏样本必须绕过 store 校验直接改盘才能造出来）。所以这一条链把 G 的三步
真跑一遍，再把它改成旧盘形态交给 H —— 不是替 G 写坏稿，而是造一个 H 真的会
面对的输入。

## 终态断言（盘上/台账上可查）

| 判据 | 终态 |
|---|---|
| `test_c10_a_document_is_built_rendered_and_reviewed` | `documents` 行在；`markdown_path` 文件在盘上且含每条断言；`review_findings` 行是 error/overclaim；`review_report` 的 markdown 文件在盘上 |
| `test_c10_b_a_real_fix_is_verified_and_signed` | finding 由 `open` → `fixed`；`verify_fixes()` 的 `resolved` 点名它；文档 `status` 停在 `in_review`（R-59）→ 再 `review` 之后 `accepted` 且签名钉住当前版 |
| `test_c10_c_an_unfixed_statement_is_not_accepted` | 什么都不改 ⇒ `still_open` 点名同一条、`verdict=revise_again`、文档 `in_review` |
| `test_c10_d_the_three_state_vocabulary_is_real` | `verify_fixes` 的 verdict 只在 `accepted / revise_again / unresolved_review` 三档里 |

## 反真空（关键一环打桩成坏 ⇒ 该链必红）

1. 假修：G 只把 finding 标成 fixed、正文一个字没改 ⇒ H 的重跑必须把它重开
   （`test_..._e`）。若 `verify_fixes` 只看 finding.status，这一条会绿 —— 于是
   "修好了"变成一句自述；
2. 空审：把 `review_tools.scan_document` 打桩成「永远零发现」⇒
   "H 的 findings 行"这条断言必须红（`test_..._f`）。若审校发现是恒真空的，
   上面那些 `resolved` 全都没有对象。

## 零模型

全部 tmp 工作区；H 的语义判据不接线（`semantic_check.checked is False` 如实记
"没查"）；不读写 `projects/`。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import schema as S
from agentflow.agent_g import AgentG
from agentflow.agent_h import AgentH
from agentflow.store import Store
from agentflow.tools import review_tools as RV

from conftest import add_concept, add_literature, add_relation, sync_counters, write_paper

TS = "2026-01-01T00:00:00+00:00"
CLAIM_TEXT = "数值抽样支持该结论。"
PAPER = "\n".join([
    r"\documentclass{article}",
    r"\begin{document}",
    r"\section{数值证据}",
    CLAIM_TEXT,
    r"\end{document}",
    "",
])


# ====================================================================== 夹具
def _env(tmp_path: pathlib.Path) -> dict[str, Any]:
    """一个最小可成文的工作区：一条文献 + 一条关系 + 一份论文正文。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_literature(st, "0000", title="夹具文献", processed=True, sync=False)
    add_concept(st, "0000", "谱", definition="d", sync=False)
    add_concept(st, "0001", "区间", definition="d", sync=False)
    add_relation(st, "0000", ["0000", "0001"], "0000",
                 quote="Spectrum lies in the interval.",
                 description="谱落在区间内", quote_verified=True, sync=False)
    sync_counters(st)
    write_paper(st, PAPER)
    return {"store": st, "root": st.root}


def _g(env: dict[str, Any]) -> AgentG:
    return AgentG(env["store"], config={"workspace_root": str(env["root"]),
                                        "docs_subdir": "documents"})


def _h(env: dict[str, Any]) -> AgentH:
    return AgentH(env["store"], config={"max_review_rounds": 3})


def _claim(g: AgentG, text: str = CLAIM_TEXT) -> dict:
    return g.compose_claim(text, citations=["lit:0000"],
                           evidence_kind="cross_check", section="数值证据",
                           claim_id="claim-1")


def _build(env: dict[str, Any]) -> dict[str, Any]:
    """G 成文的那一段：构造断言 → build_document → render。"""
    g = _g(env)
    doc = g.build_document("paper", "C10 彩排稿", claims=[_claim(g)],
                           open_problems=["非交换环情形尚未处理"])
    rendered = g.render(doc)
    return {"g": g, "doc": doc, "rendered": rendered}


def _to_old_disk_form(env: dict[str, Any], doc_id: str) -> None:
    """把那一行改成「旧盘形态」：cross_check 的受控声明丢了（绕过写入期校验）。

    与 `test_agent_h.py::inject_raw_document` 同一手法、同一理由：H 要面对的就是
    "旧版本写的行 / 手工改坏的文件"，而这类行不可能经 `store.tx` 的校验写进去。
    """
    p = pathlib.Path(str(env["root"])) / "data" / "documents.json"
    raw = json.loads(p.read_text(encoding="utf-8"))
    for row in raw["rows"]:
        if str(row.get("doc_id")) != str(doc_id):
            continue
        for claim in row.get("claims") or []:
            claim["disclaimer"] = ""
    p.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _findings(env: dict[str, Any]) -> list[dict]:
    return [dict(r) for r in env["store"].rows("review_findings")]


# ====================================================================== a：成文
def test_c10_a_document_is_built_rendered_and_reviewed(tmp_path: pathlib.Path) -> None:
    """G 的成文真的落盘；H 的审校真的落 findings 行；审校报告真的落盘。"""
    env = _env(tmp_path)
    built = _build(env)
    doc = built["doc"]
    md = pathlib.Path(str(env["root"])) / str(doc["markdown_path"])
    problems: list[str] = []

    # ---- 1. 文档落盘：documents 行 + markdown 文件（含那条断言的正文与代号）
    if not md.is_file():
        problems.append(f"markdown 没落盘：{md}")
    else:
        text = md.read_text(encoding="utf-8")
        if CLAIM_TEXT not in text:
            problems.append("渲染出的 markdown 里没有那条断言的正文")
        if "claim-1" not in text:
            problems.append("渲染出的 markdown 里没有断言代号（无法定位）")
    rows = [dict(r) for r in env["store"].rows("documents")]
    if len(rows) != 1 or str(rows[0].get("doc_id")) != str(doc["doc_id"]):
        problems.append(f"documents 行不对：{rows}")
    if built["rendered"] != md.read_text(encoding="utf-8"):
        problems.append("G.render 与 build_document 落盘的 markdown 不是同一份字节")

    # ---- 2. 旧盘形态 → H 审：error 级 overclaim 落在 review_findings
    _to_old_disk_form(env, str(doc["doc_id"]))
    h = _h(env)
    reviewed = h.review(str(doc["doc_id"]), dependencies=[])
    findings = _findings(env)
    if reviewed.get("checked") is not True:
        problems.append(f"H 的审校没查成：{reviewed.get('reason')!r}")
    if reviewed.get("error_count") != 1 or reviewed.get("verdict") != "rejected":
        problems.append(f"审校结论该 rejected/1 error，实际 "
                        f"{reviewed.get('verdict')!r}/{reviewed.get('error_count')!r}")
    if len(findings) != 1:
        problems.append(f"review_findings 该恰好 1 行，实际 {len(findings)} 行：{findings}")
    else:
        f = findings[0]
        if f.get("kind") != "overclaim" or f.get("level") != "error":
            problems.append(f"finding 该是 overclaim/error，实际 "
                            f"{f.get('kind')!r}/{f.get('level')!r}")
        if "disclaimer" not in str(f.get("evidence") or ""):
            problems.append(f"finding 的 evidence 没写触发它的实际值：{f.get('evidence')!r}")

    # ---- 3. H 的 G1–G15 报告落盘（own_errors=[] 显式登记「零自身错误」）
    report = h.review_report(str(doc["doc_id"]), own_errors=[], round_no=1,
                             dependencies=[])
    rp = pathlib.Path(str(env["root"])) / str(report.get("report_path") or "")
    if not report.get("report_path") or not rp.is_file():
        problems.append(f"审校报告没落盘：{report.get('report_path')!r}")
    elif "G1" not in rp.read_text(encoding="utf-8"):
        problems.append("审校报告里没有 G1–G15 的骨架")
    if report.get("own_errors_registered") is not True:
        problems.append("own_errors=[] 时报告该登记「本轮零自身错误」")
    if report.get("verdict") not in ("accepted", "rejected", "unverified",
                                     "accepted_with_warnings"):
        problems.append(f"报告 verdict 词表外：{report.get('verdict')!r}")
    assert problems == [], problems


# ====================================================================== b：真修
def test_c10_b_a_real_fix_is_verified_and_signed(tmp_path: pathlib.Path) -> None:
    """G 真改正文 ⇒ H 的 `verify_fixes` 判 resolved，再 `review` 才 accepted + 签名。"""
    env = _env(tmp_path)
    built = _build(env)
    doc_id = str(built["doc"]["doc_id"])
    _to_old_disk_form(env, doc_id)
    h = _h(env)
    reviewed = h.review(doc_id, dependencies=[])
    finding = dict((reviewed.get("new_findings") or [])[0])
    g = built["g"]
    fixed = _claim(g)
    revised = g.revise(doc_id, fixed_findings=[str(finding["finding_id"])],
                       new_claims=[fixed], note="补回受控声明")
    problems: list[str] = []
    rows = _findings(env)
    if not rows or str(rows[0].get("status")) != "fixed":
        problems.append(f"G 修订之后 finding 该是 fixed：{rows}")
    if revised.get("fixed_findings") != [str(finding["finding_id"])]:
        problems.append(f"修订回执没点名修掉的发现：{revised!r}")
    if revised.get("replaced_claim_ids") != [str(finding["target"])]:
        problems.append(f"修订没替换那条断言：{revised!r}")

    res = h.verify_fixes(doc_id, round_no=2, dependencies=[])
    if res.get("verdict") != "accepted":
        problems.append(f"真修好之后复审该 accepted，实际 {res.get('verdict')!r}"
                        f"（still_open={res.get('still_open')!r}）")
    if [f.get("finding_id") for f in (res.get("resolved") or [])] != [finding["finding_id"]]:
        problems.append(f"resolved 没点名那条发现：{res.get('resolved')!r}")
    if res.get("still_open") or res.get("unresolved_findings"):
        problems.append(f"真修好之后不该还有 open：{res!r}")
    doc_now = next(dict(r) for r in env["store"].rows("documents")
                   if str(r.get("doc_id")) == doc_id)
    if str(doc_now.get("status")) != "in_review":
        problems.append(f"改稿后旧签名不许沿用 ⇒ 状态该停在 in_review，"
                        f"实际 {doc_now.get('status')!r}（R-59）")

    # H 的唯一签发入口：再 review 一次 ⇒ accepted 且签名钉在当前这一版上。
    again = h.review(doc_id, dependencies=[])
    from agentflow import signatures as SIG

    recs, bad = SIG.read_ledger(SIG.ledger_path(env["root"]))
    doc_after = next(dict(r) for r in env["store"].rows("documents")
                     if str(r.get("doc_id")) == doc_id)
    if bad:
        problems.append(f"签名台账有坏行：{bad}")
    if again.get("verdict") != "accepted":
        problems.append(f"重审该 accepted，实际 {again.get('verdict')!r}")
    if str(doc_after.get("status")) != "accepted":
        problems.append(f"重审之后文档该 accepted，实际 {doc_after.get('status')!r}")
    if SIG.signed_revision(doc_after, recs) is None:
        problems.append("接受了却没有签名钉在当前这一版上")
    assert problems == [], problems


# ====================================================================== c：没修
def test_c10_c_an_unfixed_statement_is_not_accepted(tmp_path: pathlib.Path) -> None:
    """什么都不改 ⇒ `verify_fixes` 判 `revise_again`、发现仍 open、文档仍 in_review。"""
    env = _env(tmp_path)
    built = _build(env)
    doc_id = str(built["doc"]["doc_id"])
    _to_old_disk_form(env, doc_id)
    h = _h(env)
    h.review(doc_id, dependencies=[])
    res = h.verify_fixes(doc_id, round_no=2, dependencies=[])
    problems: list[str] = []
    if res.get("verdict") != "revise_again":
        problems.append(f"没修该 revise_again，实际 {res.get('verdict')!r}")
    if res.get("resolved"):
        problems.append(f"没修却报了 resolved：{res.get('resolved')!r}")
    if not res.get("still_open"):
        problems.append("没修时 still_open 必须点名那条发现")
    if not res.get("unresolved_findings"):
        problems.append("没修时 error 级未解决项必须被列出来（不许隐藏）")
    rows = _findings(env)
    if not rows or str(rows[0].get("status")) != "open":
        problems.append(f"没修时发现该仍 open：{rows}")
    assert problems == [], problems


# ====================================================================== d：三态
def test_c10_d_the_verify_fixes_vocabulary_is_real(tmp_path: pathlib.Path) -> None:
    """`verify_fixes` 的 verdict 真的有三档（不是把三态折成 accept/reject）。"""
    env = _env(tmp_path)
    built = _build(env)
    doc_id = str(built["doc"]["doc_id"])
    _to_old_disk_form(env, doc_id)
    h = _h(env)
    h.review(doc_id, dependencies=[])
    again = h.verify_fixes(doc_id, round_no=2, dependencies=[])
    assert again.get("verdict") in ("accepted", "revise_again", "unresolved_review"), again
    # 终止性那一档：把轮数上限压到 2 ⇒ 同一份没修的稿跑到上限。
    h2 = AgentH(env["store"], config={"max_review_rounds": 2})
    capped = h2.verify_fixes(doc_id, round_no=3, dependencies=[])
    assert capped.get("verdict") == "unresolved_review", capped
    assert capped.get("unresolved_findings"), capped


# ====================================================================== e：反真空假修
def test_c10_e_a_fake_fix_is_not_accepted(tmp_path: pathlib.Path) -> None:
    """反真空①：G 只把 finding 标成 fixed、正文不改 ⇒ H 必须重开，不认这笔账。"""
    env = _env(tmp_path)
    built = _build(env)
    doc_id = str(built["doc"]["doc_id"])
    _to_old_disk_form(env, doc_id)
    h = _h(env)
    reviewed = h.review(doc_id, dependencies=[])
    finding = dict((reviewed.get("new_findings") or [])[0])
    # 假修：只把 finding 的状态写成 fixed（内容一个字没改）—— 这正是"撒谎的
    # 修订"在台账上的形态；H 的复审必须重跑检查，而不是信这个状态。
    with env["store"].tx("review_findings", actor="fixture") as tx:
        row = dict(tx.find("review_findings", finding_id=str(finding["finding_id"])) or {})
        row["status"] = "fixed"
        row["resolution_note"] = "我说修好了"
        tx.upsert("review_findings", row)
    res = h.verify_fixes(doc_id, round_no=2, dependencies=[])
    problems: list[str] = []
    if res.get("resolved"):
        problems.append(f"正文没改却算 resolved：{res.get('resolved')!r}")
    reopened = [f for f in (res.get("still_open") or []) if f.get("reopened")]
    if not reopened:
        problems.append(f"谎报的 fixed 没有被重开：{res.get('still_open')!r}")
    if res.get("verdict") == "accepted":
        problems.append("假修被读成了 accepted")
    rows = _findings(env)
    if not rows or str(rows[0].get("status")) != "open":
        problems.append(f"谎报的 fixed 必须被改回 open：{rows}")
    assert problems == [], problems


# ====================================================================== f：反真空空审
def test_c10_f_an_empty_reviewer_makes_the_findings_assertion_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空②：把 `scan_document` 打桩成「永远零发现」⇒ H 的 findings 行必须为空。

    这一条不跑完整条链，只钉那一格：链上的 `resolved` 若没有对象，它就不算证据。
    """
    env = _env(tmp_path)
    built = _build(env)
    doc_id = str(built["doc"]["doc_id"])
    _to_old_disk_form(env, doc_id)
    real = RV.scan_document

    def _no_findings(*a: Any, **kw: Any) -> dict:
        got = dict(real(*a, **kw))
        got.update(findings=[], error_count=0, warning_count=0, info_count=0,
                   verdict="accepted")
        return got

    monkeypatch.setattr(RV, "scan_document", _no_findings)
    res = _h(env).review(doc_id, dependencies=[])
    assert res.get("new_findings") == [], res
    assert _findings(env) == [], "空审却落了 findings 行"

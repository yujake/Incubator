"""题 5/5a 的差分读数：`doc:` 三段判据的两份实现（写入期 / 审计期）。

## 这个脚本回答什么

同一个引用字符串，写入期那一份（`doc_tools._doc_citation_problem`）与审计期
那一份（`verify.py` 的 `elif kind == "doc"` 支）各自给出什么结论。改前跑一次、
改后跑一次，两份 JSON 并成一张表（`render_doc_citation_diff_5a.py`）——
"搬一处"是否真的没改口径，由那张表的每一格逐字相同来证。

## 为什么每个输入一份独立工作区

两侧读的必须是同一个字符串、同一份数据。一份工作区放一个输入，
`verify_all` 的每一行读数就只可能来自这一个输入（不会被上一个输入的状态污染）。

## 用法（工作目录 = 项目根，即 `agentflow/`）

    python -B temp/probe_doc_citation_two_sides_5a.py --phase before --out temp/out_5a_before.json
    python -B temp/probe_doc_citation_two_sides_5a.py --phase after  --out temp/out_5a_after.json

## 这一份读数自己的边界（三态纪律）

- 写入期读的是 `check_citations` 的端到端结论（`missing` 里那一条的 `kind` 与 `why`），
  另单独读一次 `_doc_citation_problem` 的原始报文；
- 审计期读的是 `verify_all` 就 `documents` 表第 0001 行报出的判据码与报文；
- 判定词（`OK` / `SHAPE` / `NOT_FOUND` / `STALE` / `NON_DOC_BRANCH`）是**并表用的
  读数口径**，由两侧各自的报文/判据码派生，不是第二份判据实现：
  写侧按报文首段归类，审计侧按判据码 + 报文归类。两侧的粒度本来就不一样
  （审计期把"稿件不存在"与"断言不存在"合成一条 `dangling_doc_citation`），
  所以并表用粗粒度词，细粒度差异留在 JSON 的原始报文字段里，报告里逐条说明。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentflow import schema as S  # noqa: E402
from agentflow import signatures as SIG  # noqa: E402
from agentflow import verify as V  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools import doc_tools as DT  # noqa: E402

TS = "2026-01-01T00:00:00+00:00"

#: 并表用的判定词（粗粒度，两侧可能报出来的那些）。
TOK_OK = "OK"
TOK_SHAPE = "SHAPE"
TOK_NOT_FOUND = "NOT_FOUND"
TOK_STALE = "STALE"
TOK_NON_DOC = "NON_DOC_BRANCH"
#: 审计期独有的一条（目标稿件不是 accepted）——它不在三段里，单独一个词，
#: 免得把它混进三段的读数里（报告里单独作为已知口径差说明）。
TOK_NOT_ACCEPTED = "NOT_ACCEPTED_DOC"


def _claim(cid: str, cites: list[str]) -> dict:
    """一条合法断言（`cross_check` 必须带 disclaimer，这是既有硬约束）。"""
    return {"claim_id": cid, "text": "谱落在区间内。", "citations": cites,
            "evidence_kind": "cross_check", "disclaimer": "仅为交叉核对，不是证明。"}


def _doc_row(doc_id: str, claims: list[dict], *, status: str = "draft",
             title: str = "稿") -> dict:
    """构造一行稿件（accepted ⇒ 补上内容哈希，否则写入期 schema 直接拒）。"""
    row = {"doc_id": doc_id, "kind": "paper", "title": title, "sections": [],
           "claims": claims, "open_problems": [], "status": status,
           "created_at": TS, "updated_at": TS}
    if status == "accepted":
        row["content_sha256"] = SIG.content_sha256_of(row)
    return row


def _put(st: Store, table: str, row: dict) -> dict:
    """直接落库一行（专测 verify，不走工具层）。"""
    with st.tx(table, actor="probe") as tx:
        tx.upsert(table, row)
    return row


def _sign(st: Store, doc_row: dict) -> dict:
    """给一行稿件签一条（否则 `accepted_without_signature` 会混进读数）。"""
    cur = SIG.content_sha256_of(doc_row)
    return SIG.append_signature(st.root, {
        "doc_id": str(doc_row["doc_id"]), "content_sha256": cur,
        "name": SIG.SIGNER_NAME, "at": TS, "scope": "document",
        "verdict": "accepted", "instance_id": f"probe@{TS}",
        "inputs": {"doc_sha256": cur, "evidence_hashes": []},
        "basis": {"codes_checked": [], "finding_ids": [], "rounds": 1, "dimensions": []},
    })


def target_row(target_status: str = "accepted") -> dict:
    """被引稿那一行（内容固定，好让引用里的哈希可以预先算出来）。

    它自己的断言必须带一条能解析的引用（`lit:0000`）：schema 硬约束
    "没有 citations 的断言不允许进入稿件"，而 `lit:0000` 由 `build_store`
    顺手落一条文献行 —— 否则被引稿那一侧会多出 `dangling_citation` 噪音。
    """
    return _doc_row("0000", [_claim("c1", ["lit:0000"])],
                    status=target_status, title="被引稿")


def build_store(root: Path, raw: str, *, target_status: str = "accepted") -> Store:
    """一份工作区：稿件 0000（被引稿）+ 稿件 0001（引用者，只有一个断言一条引用）。

    稿件 0000 一律存在（除了"稿件不存在"那一行指向 9999），这样各行之间
    只差引用字符串本身。
    """
    st = Store(root)
    st.init()
    _put(st, "literature", S.Literature(lit_id="0000", title="某文献", type="J",
                                        summary="", path=None, added_at=TS).to_dict())
    target = _put(st, "documents", target_row(target_status))
    if target_status == "accepted":
        _sign(st, target)
    _put(st, "documents", _doc_row("0001", [_claim("c1", [raw])]))
    return st


def _write_token_from_msg(msg: str) -> str:
    """写侧报文 → 判定词（按报文首段归类；空串 = 通过）。"""
    if not msg:
        return TOK_OK
    if msg.startswith("内部引用形状不对"):
        return TOK_SHAPE
    if msg.startswith("documents 表里没有 doc_id="):
        return TOK_NOT_FOUND
    if "里没有断言" in msg:
        return TOK_NOT_FOUND
    if msg.startswith("钉的是 "):
        return TOK_STALE
    return f"UNKNOWN_MSG({msg[:24]})"


def _audit_token(issues: list[dict]) -> tuple[str, str, str]:
    """审计期第 0001 行的判据 → `(判定词, 判据码, 报文)`。"""
    for i in issues:
        code = i["code"]
        msg = i["message"]
        if code == "dangling_doc_citation":
            if "形状不对" in msg:
                return TOK_SHAPE, code, msg
            return TOK_NOT_FOUND, code, msg
        if code == "internal_citation_stale":
            return TOK_STALE, code, msg
        if code == "internal_citation_not_accepted":
            return TOK_NOT_ACCEPTED, code, msg
        if code in ("dangling_citation", "unknown_citation_kind"):
            return TOK_NON_DOC, code, msg
    return TOK_OK, "", ""


def read_one(raw: str, *, target_status: str = "accepted") -> dict:
    """跑一次两侧读数，返回一条 JSON 记录。"""
    workdir = Path(tempfile.mkdtemp(prefix="probe-5a-"))
    try:
        st = build_store(workdir, raw, target_status=target_status)
        rows_of = lambda t: st.rows(t)  # noqa: E731

        unit_msg = DT._doc_citation_problem(raw, rows_of)
        got = DT.check_citations(rows_of, [_claim("c2", [raw])])
        if not got["missing"]:
            write_token, write_kind, write_why = TOK_OK, "", ""
        else:
            first = got["missing"][0]
            write_kind = str(first.get("kind") or "")
            write_why = str(first.get("why") or "")
            write_token = (_write_token_from_msg(write_why) if write_kind == "doc"
                           else TOK_NON_DOC)

        rep = V.verify_all(st)
        mine = [i.to_dict() for i in rep.issues
                if i.table == "documents" and str(i.row_id) == "0001"]
        audit_token, audit_code, audit_msg = _audit_token(mine)
        return {
            "input": raw,
            "target_status": target_status,
            "write_unit_msg": unit_msg,
            "write_unit_token": _write_token_from_msg(unit_msg),
            "write_e2e_token": write_token,
            "write_e2e_kind": write_kind,
            "write_e2e_why": write_why,
            "audit_token": audit_token,
            "audit_code": audit_code,
            "audit_msg": audit_msg,
            "audit_all_codes_row_0001": sorted(i["code"] for i in mine),
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def build_inputs() -> list[tuple[str, str, str]]:
    """`(标签, 引用字符串, 目标稿件状态)` —— 七个主输入 + 一条已知口径差诊断行。"""
    # 目标稿件 0000 的当前引用哈希（构造输入时要按它算，故先造一份等价行）。
    probe_row = target_row()
    cur = SIG.ref_hash_of(probe_row)
    truncated = cur[:-1]
    swapped = ("0" if cur[0] != "0" else "1") + cur[1:]
    return [
        ("合法引用", SIG.doc_ref("0000", "c1", probe_row), "accepted"),
        ("缺哈希", "doc:0000#c1", "accepted"),
        ("哈希长度不对", f"doc:0000#c1@{truncated}", "accepted"),
        ("形式不对", "doc:0000", "accepted"),
        ("稿件不存在", f"doc:9999#c1@{cur}", "accepted"),
        ("断言不存在", f"doc:0000#cX@{cur}", "accepted"),
        ("非 doc: 前缀", "lit:9999", "accepted"),
        # 诊断行（不计入那七个）：三段全过，但被引稿件不是 accepted
        ("[诊断] 被引稿未 accepted", f"doc:0000#c1@{cur}", "draft"),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, help="before / after（只进读数文件名与 JSON 字段）")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    records = []
    for label, raw, status in build_inputs():
        rec = read_one(raw, target_status=status)
        rec["label"] = label
        records.append(rec)

    payload = {"phase": args.phase, "root": str(ROOT), "records": records}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    print(f"[{args.phase}] 读数 {len(records)} 条 → {out}")
    for rec in records:
        print(f"  {rec['label']:<24} 写(单元)={rec['write_unit_token']:<14} "
              f"写(端到端)={rec['write_e2e_token']:<14} "
              f"审={rec['audit_token']:<16} 审码={rec['audit_code']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

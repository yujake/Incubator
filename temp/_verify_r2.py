"""R2 四条 finding 在**当前字节**上的读数（只读探针）。

为什么是只读的：跑这个探针时 `agentflow/` 正处在两个重审窗口内
（R1b 审 `scripts/noai_gate.py`；R2 审证据链），所以一个字节都不许写。
它因此有两个身份：
  ① **裁决** R2 的四条 finding 是否成立（R2-AN-4 我算下来与它相反）；
  ② 修完之后**同一份探针**再跑一遍 ⇒ 这就是"改前实现"的负控（`draft/28` §31.1 的 强 档）。

用法（在 agentflow 目录下）：
    $env:PYTHONPATH='src'; python D:\\Incubator\\temp\\_verify_r2.py
"""
from __future__ import annotations

import io
import inspect
import re
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(r"D:\Incubator\agentflow")
sys.path.insert(0, str(ROOT / "src"))

from agentflow import evidence as EV          # noqa: E402
from agentflow import schema as S             # noqa: E402
from agentflow import verify as V             # noqa: E402
from agentflow.store import Store             # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def case(cid: str, got, want, note: str = "") -> None:
    """一条判据：`got` 是否等于 `want`。"""
    ok = got == want
    RESULTS.append((cid, ok, f"got={got!r} want={want!r} {note}".strip()))


def case_in(cid: str, needle, hay, note: str = "") -> None:
    """包含判据（用于"报了吗"这类问题）。`hay` 可能很长，别把它整个打进台账。"""
    ok = needle in hay
    RESULTS.append((cid, ok, f"{needle!r} in <{len(hay)} chars> -> {ok} {note}".strip()))


# ---------------------------------------------------------------- A · R2-AN-2
TS = "2026-01-01T00:00:00+00:00"


def _exp(st: Store, eid: str, key: str, out: str) -> None:
    row = S.Experiment(
        experiment_id=eid, claim=f"命题 {eid}", claim_key=key, method="formal",
        evidence_kind="proof", result="supports", negation_kind="not_proved",
        verifier_output=out, verifier_subject_key=key, created_at=TS,
    )
    with st.tx("experiments", actor="probe", note="R2-AN-2 夹具") as tx:
        tx.upsert("experiments", row.to_dict())


def part_a(tmp: Path) -> dict:
    st = Store(tmp / "a")
    st.init()
    # A1 子串洞：claim_key='L' 是 'Lean4: no goals' 的子串（完全自报的 proof）
    _exp(st, "0000", "L", "Lean4: no goals")
    # A2 探针自校（必然报）：key 不在输出里
    _exp(st, "0001", "ZZZ", "Lean4: no goals")
    # A3 真 Lean 形态：必须不报（防误伤）
    _exp(st, "0002", "one_plus_one", "'one_plus_one' does not depend on any axioms")
    # A4 名字只出现在一句与结论无关的告警里
    _exp(st, "0003", "foo", "Lean4: warning: unused variable 'foo'; no goals")
    rep = V.verify_all(st)
    hits = {(i.code, i.row_id) for i in rep.issues}
    return hits


def run_a(tmp: Path) -> None:
    try:
        hits = part_a(tmp)
        reported = {eid for code, eid in hits if code == "selfreported_proof"}
        print(f"[A] selfreported_proof 命中的 experiment_id = {sorted(reported)}")
        case("A1 子串洞 claim_key='L' 必须报", "0000" in reported, True,
             "（R2-AN-2 ① 漏报）")
        case("A2 探针自校：key 不在输出里必须报", "0001" in reported, True,
             "（必然失败的输入，守探针自己）")
        case("A3 真 Lean 形态必须不报", "0002" in reported, False,
             "（防误伤正控）")
        case("A4 名字只在无关注警里必须报", "0003" in reported, True,
             "（R2-AN-2 ② 放行）")
    except Exception:
        RESULTS.append(("A 整体", False, traceback.format_exc()))


# ---------------------------------------------------------------- B · R2-AN-4
def _fn(verdict, reason=""):
    def f(doc, quote, page_range, widen=0, allow_fulltext_fallback=False):
        return {"verified": verdict, "reason": reason}
    return f


FULL_ONLY = {"source_id": "S1", "fulltext": {"status": "ok", "text_pages": ["alpha beta"]}}
ABSTRACT_ONLY = {"source_id": "S2", "abstract": "gamma delta"}
NOTHING = {"source_id": "S3"}
CLAIM = {"text": "断言", "quote": "zzz-not-here", "evidence_source": "S1"}


def _claims(sources, fn, claim=None):
    out = EV.verify_claims([claim or CLAIM], sources, quote_fn=fn)
    return out["claims"][0]


def run_b() -> None:
    try:
        print("\n[B] R2-AN-4 的可达性实验（'有全文、没摘要、引文不在全文里' 这条来源）")
        # B1 关键：这条来源**比对了全文**、逐字没找到 ⇒ 结论该是 not_found（比过了、没有），
        #    而不是 no_comparable_text_in_any_source（没查成）。R2 说这一支到不了。
        r1 = _claims([FULL_ONLY], _fn(False, "quote_absent"))
        print(f"    B1 verdict={r1['verdict']!r} reason={r1['reason']!r} checked={r1['checked']}")
        case("B1 有全文没摘要、没命中 ⇒ not_found", (r1["verdict"], r1["reason"]),
             ("not_found", "quote_absent"), "（R2 说这一支不可达）")
        case("B1b reason 不是 no_comparable_text_in_any_source",
             r1["reason"] != "no_comparable_text_in_any_source", True)
        # B2 同一条来源，命中 ⇒ verified
        r2 = _claims([FULL_ONLY], _fn(True, "substring_match"))
        case("B2 同来源命中 ⇒ verified/fulltext", (r2["verdict"], r2["level"]),
             ("verified", "fulltext"), "（防误伤）")
        # B3 回验器拒绝判定
        # B3 拒绝判定：`R2-AN-6` 的修法把这一档的理由从泛泛的 `unknown` 换成
        # **更具体**的 `verifier_refused_to_judge`（`_read_verdict` 在 `verified is None`
        # 时的默认值）⇒ 判据随之改成钉那个新字面量。
        # ⚠️ 判据**不是**为了迁就实现才改的：改的理由是"拒绝判定"这件事本来就该有个
        # 说得清的名字，而旧字面量 `unknown` 既是死代码（走不到）又把两种意思混在一起。
        # 这一条改了之后必须配负控：把默认值改回 `"unknown"` ⇒ B3 必须红（改前实现那一档）。
        r3 = _claims([FULL_ONLY], _fn(None, ""))
        print(f"    B3 verdict={r3['verdict']!r} reason={r3['reason']!r}")
        case_in("B3 拒绝判定 ⇒ reason='verifier_refused_to_judge'", r3["reason"],
                ("verifier_refused_to_judge",))
        case("B3b 不再落回泛泛的 'unknown'（旧字面量已死）", r3["reason"] != "unknown", True,
             "（R2-AN-6 的验收判据）")
        # B4 一条来源都没有文本 ⇒ no_source_text（老判据，两个用例在守）
        r4 = _claims([NOTHING], _fn(False, "x"))
        case("B4 无来源文本 ⇒ no_source_text", r4["reason"], "no_source_text")
        # B5 只有摘要、没命中 ⇒ not_found（正常路径的正控）
        r5 = _claims([ABSTRACT_ONLY], _fn(False, "quote_absent"),
                     claim={"text": "断言", "quote": "zzz-not-here", "evidence_source": "S2"})
        case("B5 只有摘要、没命中 ⇒ not_found", (r5["verdict"], r5["reason"]),
             ("not_found", "quote_absent"))
        # B6 候选为空能不能构造：声明的来源不在表里 + with_text 为空
        r6 = _claims([NOTHING], _fn(False, "x"))
        case("B6 候选为空被 no_source_text 提前收口", r6["reason"], "no_source_text")
    except Exception:
        RESULTS.append(("B 整体", False, traceback.format_exc()))


def run_d() -> None:
    print("\n[D] 我顺手查的两处（R2 没报的同类死词汇）")
    try:
        for probe in ({"verified": None, "reason": ""}, {"verified": None},
                      {"verified": False, "reason": ""}, {"verified": True, "reason": ""}):
            print(f"    _read_verdict({probe}) = {EV._read_verdict(probe)!r}")
        # verified=None ⟹ 第二项必为 'unknown'（`reason or "unknown"`），
        # 所以 evidence.py:1265 的 `or "verifier_refused_to_judge"` 永远走不到。
        dead = [p for p in ({"verified": None, "reason": ""}, {"verified": None}, {})
                if EV._read_verdict(p)[1] == ""]
        case("D1 verified=None ⇒ 第二项必非空（所以默认值一定是个具体字面量）",
             dead, [])
        # 反过来：verified=False 且回验器没给理由时第二项可以是空串，
        # 所以 1269/1273 的 `or "not_found"` 是**可达**的（别把它一起删掉）。
        live = [p for p in ({"verified": False, "reason": ""}, {"verified": False})
                if EV._read_verdict(p)[1] == ""]
        case("D2 verified=False 时第二项可以为空 ⇒ 'not_found' 兜底可达（留着）",
             len(live) > 0, True)
        r = _claims([ABSTRACT_ONLY], _fn(False, "quote_absent_xyz"),
                    claim={"text": "断言", "quote": "zzz-not-here", "evidence_source": "S2"})
        case("D3 没命中时 reason 用回验器给的原话", r["reason"], "quote_absent_xyz")
    except Exception:
        RESULTS.append(("D 整体", False, traceback.format_exc()))


# ---------------------------------------------------------------- C · R2-AN-3
def run_c() -> None:
    print("\n[C] R2-AN-3：agent_e 模块 docstring 的「没查成」清单 vs _NOT_CHECKED_REASONS")
    try:
        from agentflow import agent_e as AE
        doc = inspect.getdoc(AE) or ""
        m = re.search(r"3\.\s*没查成(.*?)4\.\s*`method", doc, re.S)
        seg = m.group(1) if m else ""
        found = set(re.findall(r"`([a-z_]+)`", seg))
        want = set(AE._NOT_CHECKED_REASONS)
        print(f"    docstring 第 3 条列出 = {sorted(found)}")
        print(f"    _NOT_CHECKED_REASONS   = {sorted(want)}")
        print(f"    缺 = {sorted(want - found)}")
        case("C1 docstring 第 3 条覆盖 _NOT_CHECKED_REASONS（5 项）", want - found, set(),
             "（R2-AN-3：docstring 少列 source_unreadable/param_error）")
        case("C2 _NOT_CHECKED_REASONS 是 5 项", sorted(want),
             ["no_backend", "param_error", "source_unreadable", "timeout", "tool_crashed"])
        case_in("C3 docstring 别处写了 source_unreadable", "source_unreadable", doc)
        print(f"    C3 读数：docstring 里出现 source_unreadable = "
              f"{'source_unreadable' in doc}（{len(doc)} 字的 docstring）")
    except Exception:
        RESULTS.append(("C 整体", False, traceback.format_exc()))


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        run_a(tmp)
        run_b()
        run_d()
        run_c()
    fails = [r for r in RESULTS if not r[1]]
    print("\n" + "=" * 72)
    for cid, ok, note in RESULTS:
        print(f"{'ok  ' if ok else 'FAIL'} {cid:<52} {note}")
    print(f"\nFAILS = {[r[0] for r in fails]}")
    print(f"合计 {len(RESULTS)} 条，失败 {len(fails)} 条")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

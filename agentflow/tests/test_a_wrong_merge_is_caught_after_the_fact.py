# -*- coding: utf-8 -*-
"""判据（件2）：凡是并进来的两段正文，条件组 / 结论组语义不一致 ⇒ 红（错并的后验判据）。

## 为什么要一条"后验"判据

`secretary` 写在命题行上的 `_proposition_matches` 键（盘上那一格痕）从 2026-10-24 起就在写，但 src 里
0 个读者 —— 也就是说"这一笔凭什么并进来"写下来了、却没有任何判据去读。于是
"合并"这件事的错法（把条件更强 / 更弱的两条并成一条）只有人翻台账时才看得见。

这一份补的就是那个读者：读出每一个 `merged=True` 的变体，逐对判"条件组 / 结论组"。

## 判据的两档（模型优先；没模型用粗筛，且必须标注它是粗筛）

| 档 | 用什么判 | 读数里的标记 |
|---|---|---|
| 模型可用 | `Secretary.adjudicate_proposition` 对同一对正文再算一次（与登记时同一处判据、同一份缓存）：`verdict=same` 且 `same_as` 指向那一行 ⇒ 一致 | `coarse=False`、`basis=adjudication_recompute`、`checked=True` |
| 模型不可用（测试环境没缝） | 确定性键 + 结构差：把两条正文按结论标记切成"条件组 / 结论组"，各取 `propositionkey.proposition_key`；键相等 ⇒ 一致；一方严格包含另一方（= 条件强弱关系，业主点名的形态）⇒ 可疑；两键都非空且不等 ⇒ 可疑；任一侧判不了 ⇒ 判不了（不算红） | `coarse=True`、`basis=structural_probe`、`checked=False`，且文案里写明"这是粗筛，不是判准、也没判过" |

粗筛不是判准，也不是"判过了、确属错并"：它只读确定性键，读不出"等价改写"
（例如 `p^a 整除 |G|` 与 `|G| 被 p^a 整除` 会被它报成可疑）。所以它的每一个结论都
必须能被模型复算推掉 —— 判据 c 就是这件事的反真空：把这一条判据摘掉，错并那一对
立刻变绿。

## 这一份钉的三条

| 条 | 它要证明的事 | 改前（这一笔之前）为什么是红的 |
|---|---|---|
| a | 用打桩让秘书把「素数 / 奇素数」判成 same ⇒ 两条并成一行，后验判据当场红（粗筛点名条件组的包含关系） | 改前没有任何判据读 `_proposition_matches`：错并落盘之后一路绿 |
| b | 正常合并（同一命题两份证明）⇒ 绿；粗筛档（没缝）与模型档（有缝）各核一次 | 正控：不许把"一切合并"都判红 |
| c | 反真空：把后验判据摘掉（`_postcheck` 打桩成恒空）⇒ a 那一组读数立刻变绿 | 证明 a 的红是这条判据给的，不是夹具自带的 |

## 边界

全部 tmp 工作区；打桩只替换"模型说了什么"（`adjudicate_proposition` 的返回值），
判据本体仍是 `propositionkey` 的确定性键与那一处模型判定。不读写 `projects/`。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

# 与 `tests/conftest.py` 同一个注入方式（这一份也要能在一棵临时源码树上单独跑）。
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import propositionkey as PK
from agentflow import schema as S
from agentflow.secretary import Secretary
from agentflow.store import Store

from _proof_manuscript_fixture import carry_proof_manuscript

#: 错并那一对：条件有强弱关系（素数 / 奇素数）⇒ 语义不一致 ⇒ 本来不许并。
PAIR_WEAK = "设 p 是素数；则 p 是奇数。"
PAIR_STRONG = "设 p 是奇素数；则 p 是奇数。"

#: 正常合并那一对：同一命题的两种写法（确定性键相同）。
SAME_A = "设 G 是 3-正则群；则弦长函数不是常值。"
SAME_B = "假设 G 为 3-正则群，于是弦长函数不是常值。"

PROOF_1 = "证明：由定义直接计算（路线一）。"
PROOF_2 = "证明：对 p 的素因子分解作归纳（路线二）。"
PROOF_3 = "证明：把弦长函数记为 f，由邻域结构直接算出（路线三）。"

#: 结论标记：必须落在分句边界上（`3-正则群` 里的那个"则"不是结论标记）。
_SPLIT = re.compile(r"[；;。，,\n]\s*(?:则|那么|于是|故|因此|从而|推出)|⇒|->|=>")


@pytest.fixture(autouse=True)
def _proof_kind_default(monkeypatch):
    """同种证明那一问（`proof_kind`）的默认回答：`different`（另一条路径）。

    2026-11-12 起"同种证明"改由秘书的语义判定给（禁机械闸）：没有判定面时按
    fail-closed 拒收（`proof_kind_unjudged`），会把这一份要造的"错并 / 正常合并"
    全部拒在合并之前 —— 而这一份量的是合并之后的后验判据（错并要红、正常合并
    要绿），不是两次的证法是不是同一套；这里的 PROOF_1/2/3 本来就是三条不同证法。
    真正的剧本桩（same / different / 没判成）在
    `tests/test_rehearsal_two_f_independent_proofs.py` 与
    `tests/test_unjudged_axes_are_fail_closed.py`。
    """
    import agentflow.secretary as _SEC

    real = _SEC.Secretary.judge

    def _judge(self, kind, context, **kw):
        if kind == "proof_kind":
            return {"checked": True, "decision": "different", "same_path": 0,
                    "reason": "夹具：不同种（这一份不量语义判别）", "basis": [], "cost": {}}
        return real(self, kind, context, **kw)

    monkeypatch.setattr(_SEC.Secretary, "judge", _judge)


def _own(full: str, *, label: str = "") -> dict:
    return {"statement_full": full, "statement_text": full[:24], "label": label,
            "origin": "own_result", "kind": "conjecture",
            "doc_id": S.format_id(0), "quote_reason": "我方自产命题，没有外部引文要比对"}


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _rows(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("statements")]


def _traces(row: dict) -> list[dict]:
    """这一行盘上记着的"并进来的变体"（`_proposition_matches` 的唯一读口径）。"""
    return [dict(m) for m in (row.get("_proposition_matches") or []) if isinstance(m, dict)]


def _judge_same_always(target: str):
    """把"模型说了什么"填成 `verdict=same / same_as=<target>`（只替换那一处判定）。"""
    def _judge(self, stmt_like, **_kw):
        return {"checked": True, "verdict": PK.STATE_SAME, "same_as": str(target),
                "basis": "打桩：条件组与结论组一致", "canonical_name": "", "route": "",
                "condition": "打桩：条件未读", "conclusion": "打桩：结论未读",
                "reason": "打桩：模型判 same", "candidates": [], "cost": {},
                "reused": False, "cached": False}

    return _judge


# ------------------------------------------------------------------ 判据本体

def _groups(text: str) -> tuple[str, str]:
    """按结论标记切成（条件组, 结论组）；没有标记 ⇒ 整句算条件组、结论组为空。"""
    parts = _SPLIT.split(str(text or ""), maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return str(text or "").strip(), ""


def _tokens(text: str) -> frozenset[str]:
    """确定性键的记号集合（`proposition_key` 的输出按分句 / 记号拆开，不另算一套）。"""
    key = PK.proposition_key(text)
    if not key:
        return frozenset()
    return frozenset(token for clause in key.split(" || ") for token in clause.split())


def _chars(text: str) -> frozenset[str]:
    """确定性键里的字符集合（判"严格包含"那一档：`素数` 被 `奇素数` 包含）。

    为什么用字符而不是记号：中文二元组在插入一个修饰字之后会整体换一批
    （`是素数` → `是奇素数` 的二元组是 `是奇/奇素/素数`，原来的 `是素` 不在里面），
    于是"条件更强"这件事在二元组那一轴上看不出包含关系；字符集合看得出。
    """
    key = PK.proposition_key(text)
    return frozenset(ch for ch in key if not ch.isspace() and ch != "|")


def _compare_groups(left: str, right: str) -> dict:
    """两组正文的结构差（确定性、零模型）：相等 / 包含（强弱）/ 各说各的 / 判不了。

    只读 `proposition_key`（本仓唯一的确定性键）。它不是同一性判准：等价改写
    （换语序、换说法、`整除` 与 `被…整除`）在它眼里就是"不同"。所以它的结论进读数时
    一律带 `coarse` 标记，由模型那一档复核。
    """
    ka, kb = PK.proposition_key(left), PK.proposition_key(right)
    if not ka or not kb:
        return {"state": "unknown", "why": "有一侧读不出确定性键（太短 / 纯符号）"}
    if ka == kb:
        return {"state": "same", "why": "确定性键相同"}
    a, b = _chars(left), _chars(right)
    if a < b or b < a:
        weaker, stronger = ("这一条", "在册那一条") if a < b else ("在册那一条", "这一条")
        return {"state": "different",
                "why": (f"记号集合是严格包含关系（{weaker}那一组被{stronger}包含）"
                        " ⇒ 条件强弱或结论强弱不同")}
    return {"state": "different", "why": "两边的确定性键都非空且不相等 ⇒ 各说各的"}


def _postcheck(rows: list[dict], *, sec: Secretary | None = None) -> dict:
    """后验判据：读 `_proposition_matches`，逐对判条件组 / 结论组是否语义一致。

    `sec` 给了、且它真的能发判定（有缝 + `enable_model`）⇒ 走模型那一档
    （`adjudicate_proposition` 再算一次，与登记时同一处判据）；否则走确定性粗筛，
    并在每一条读数里写明"这是粗筛，不是判准、也没有「判过是错并」这回事"。

    返回 `{"problems": [...], "checked": bool, "coarse": bool, "pairs": n}`：
    `checked` 说的是"这一档给了结论没有"，`coarse` 说的是"结论来自粗筛还是模型"。
    空 `problems` = 这一批合并都对得上。
    """
    out: list[str] = []
    checked = True
    coarse = False
    pairs = 0
    for row in rows:
        base = str(row.get("statement_full") or "")
        sid = str(row.get("stmt_id") or "")
        for trace in _traces(row):
            variant = str(trace.get("statement_full") or "")
            if not variant.strip() or not base.strip():
                continue
            pairs += 1
            modeled = (sec is not None and bool(getattr(sec, "enable_model", False))
                       and getattr(sec, "seam", None) is not None)
            if modeled:
                got = sec.adjudicate_proposition(
                    {"statement_full": variant, "kind": str(row.get("kind") or ""),
                     "label": str(trace.get("label") or "")})
                if not got.get("checked"):
                    checked = False      # 没查成 ⇒ 不冒充"一致"，这一对交给粗筛那一档
                    coarse = True
                    out.extend(_coarse_problems(base, variant, sid, trace))
                    continue
                verdict = str(got.get("verdict") or "")
                if verdict == PK.STATE_SAME and str(got.get("same_as") or "") == sid:
                    continue
                out.append(
                    f"错并（模型档，coarse=False，basis=adjudication_recompute，"
                    f"checked=True）：stmt:{sid} 并进来了另一段正文，"
                    f"而模型复算给 verdict={verdict!r}、same_as={got.get('same_as')!r}"
                    f"（在册那一行是 stmt:{sid}）⇒ 条件组/结论组语义不一致"
                    f"；在册正文={base[:40]!r}；并进来的正文={variant[:40]!r}"
                    f"；登记时记的依据={str(trace.get('basis') or '')!r}")
                continue
            coarse = True
            checked = False          # 粗筛不给"判过"的结论（业主/父口径：checked=False）
            out.extend(_coarse_problems(base, variant, sid, trace))
    return {"problems": out, "checked": checked, "coarse": coarse, "pairs": pairs}


def _coarse_problems(base: str, variant: str, sid: str, trace: dict) -> list[str]:
    """粗筛那一档的读数（`coarse=True` / `basis=structural_probe` / `checked=False`）。"""
    cond = _compare_groups(_groups(base)[0], _groups(variant)[0])
    concl = _compare_groups(_groups(base)[1], _groups(variant)[1])
    bad = [(name, got) for name, got in (("条件组", cond), ("结论组", concl))
           if str(got.get("state")) == "different"]
    if not bad:
        return []
    why = "；".join(f"{name}：{got.get('why')}" for name, got in bad)
    return [
        f"疑似错并（粗筛，coarse=True，basis=structural_probe，checked=False；"
        f"这是粗筛不是判准、也没有「判过是错并」这回事，结论必须由模型或人复核）："
        f"stmt:{sid} 并进来的那一段正文在 {'/'.join(name for name, _ in bad)} 上"
        f"与在册不一致 —— {why}"
        f"；在册正文={base[:40]!r}；并进来的正文={variant[:40]!r}"
        f"；登记时记的依据={str(trace.get('basis') or '')!r}"]


def _postcheck_problems(rows: list[dict], *, sec: Secretary | None = None) -> list[str]:
    """`_postcheck` 的薄壳（只取问题清单；判据本体在上面那一处）。"""
    return list(_postcheck(rows, sec=sec)["problems"])


# ------------------------------------------------------------------ 假模型缝（按定理名判）

_PARENS = re.compile(r"[（(][^（()）]*[）)]")
_ORDINAL = re.compile(r"[一二三四五六七八九十]+(?:个)?定理")


def _clean_name(label: str) -> str:
    text = _PARENS.sub(" ", str(label or ""))
    return re.sub(r"\s+", " ", text).strip(" ·—-")


def _name_key(name: str) -> str:
    text = _ORDINAL.sub("定理", _clean_name(name)).lower()
    return re.sub(r"\s+", " ", text).strip()


def _material(prompt: str) -> dict:
    text = str(prompt or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    return json.loads(text[start:end + 1])


class _FakeSeam:
    """假秘书的模型缝（与 `test_one_theorem_many_proofs_is_not_three_theorems.py` 同族）。

    它只按定理名判：两个同名标签 ⇒ same 并点名第一个候选；不同名 ⇒ different。
    真实判据在提示词里（条件 ⇒ 结论一致），这里只替"模型说了什么"那一个返回值。

    2026-11-08：判定改成"秘书主动查询（挑词 → 代码检索 → 一次判定）"之后，这一问有两次
    模型调用，替身也得答两次 —— 挑词那一问（`secretary:statement_keywords`）给的词就是
    这条待判正文的定理名（`_clean_name(label)`）；检索面、命中计数与两档形状仍走
    `Secretary.adjudicate_proposition` 那一处实现。不答它会让整条链 fail-closed
    （"关键词没提取成 ⇒ 这一问没判成"），于是本文件量不到"错并 / 正常合并"这件事。
    """

    class _Call:
        def __init__(self, ok: bool = True, problem: str = "", detail: str = "") -> None:
            self.ok, self.problem, self.detail = ok, problem, detail

    def __init__(self, *, mode: str = "name") -> None:
        self.mode = str(mode)
        self.calls: list[str] = []

    def ask_json(self, prompt, **kw):
        note = str(kw.get("note") or "")
        self.calls.append(note)
        data = _material(prompt)
        if note.endswith("statement_keywords"):
            name = _clean_name(str(data.get("label") or ""))
            return ({"keywords": [name] if name else [],
                     "why": ("打桩：拿定理名去台账里捞同一条"
                             if name else "打桩：这条没有定理名可捞")}, self._Call())
        return self._reply(data), self._Call()

    def _reply(self, data: dict) -> dict:
        name = _clean_name(str(data.get("label") or ""))
        candidates = [c for c in (data.get("candidates") or []) if isinstance(c, dict)]
        if not name:
            return {"decision": "unknown", "canonical_name": "", "route": "",
                    "reason": "打桩：标签里读不出定理名", "basis": ["条件：标签为空"]}
        hit = next((c for c in candidates
                    if _name_key(str(c.get("label") or "")) == _name_key(name)), None)
        if hit is None:
            return {"decision": "different", "canonical_name": name, "route": "",
                    "condition": f"{name} 的条件组", "conclusion": f"{name} 的结论组",
                    "reason": "打桩：候选里没有同名定理", "basis": ["条件：不同名",
                                                                 "结论：不同名"]}
        return {"decision": "same", "same_as": str(hit.get("stmt_id") or ""),
                "canonical_name": name, "route": "",
                "condition": f"条件：都是 {name} 的那一组", "conclusion": f"结论：都是 {name} 的那一组",
                "reason": "打桩：条件与结论一致", "basis": ["条件：一致", "结论：一致"]}


# ------------------------------------------------------------------ 夹具

def _bad_merge(tmp_path: pathlib.Path) -> tuple[Store, dict]:
    """造一对"错并"：打桩让秘书把条件强弱不同的两条判成 same（打桩只在造这一笔时生效）。"""
    st = _ws(tmp_path / "bad")
    sec = Secretary("B", root=st.root, store=st)
    first = sec.record_statement(carry_proof_manuscript(st.root, {
        **_own(PAIR_WEAK, label="素数引理"), "proof_text": PROOF_1}), role="B")
    assert first.get("created") is True, first
    real = Secretary.adjudicate_proposition
    Secretary.adjudicate_proposition = _judge_same_always(str(first.get("stmt_id") or ""))
    try:
        second = sec.record_statement(carry_proof_manuscript(st.root, {
            **_own(PAIR_STRONG, label="奇素数引理"), "proof_text": PROOF_2},
            statement_id="000001"), role="B")
    finally:
        Secretary.adjudicate_proposition = real
    return st, second


def _bad_merge_report(tmp_path: pathlib.Path, *,
                      sec: Secretary | None = None) -> dict:
    """a / c 共用的读数：错并那一行 + 后验判据那一份（两处都从这同一份读数取）。"""
    st, merged = _bad_merge(tmp_path)
    rows = _rows(st)
    report: dict = {"store": st, "merged": merged, "rows": rows, "premise": []}
    if not merged.get("merged"):
        report["premise"] = [f"夹具前提不成立：这一对没被并起来（{merged.get('reason')}）"]
        return report
    if len(rows) != 1:
        report["premise"] = [f"夹具前提不成立：错并之后在册 {len(rows)} 行（应 1 行）"]
        return report
    if not _traces(rows[0]):
        report["premise"] = ["盘上没有 `_proposition_matches` ⇒ 后验判据没有可读的痕"]
        return report
    report["post"] = _postcheck(rows, sec=sec)
    return report


def _bad_merge_problems(tmp_path: pathlib.Path, *,
                        sec: Secretary | None = None) -> list[str]:
    report = _bad_merge_report(tmp_path, sec=sec)
    return list(report.get("premise") or []) + list((report.get("post") or {}).get("problems") or [])


def _ok_merge_by_key(tmp_path: pathlib.Path) -> tuple[Store, dict]:
    """正常合并（粗筛档）：同一命题的两种写法（确定性键相同）⇒ 1 行 + 第 2 份证明。"""
    st = _ws(tmp_path / "ok")
    sec = Secretary("B", root=st.root, store=st)
    first = sec.record_statement(carry_proof_manuscript(st.root, {
        **_own(SAME_A, label="弦长引理"), "proof_text": PROOF_1}), role="B")
    assert first.get("created") is True, first
    second = sec.record_statement(carry_proof_manuscript(st.root, {
        **_own(SAME_B, label="弦长引理"), "proof_text": PROOF_3},
        statement_id="000001"), role="B")
    return st, second


def _ok_merge_by_name(tmp_path: pathlib.Path) -> tuple[Store, dict]:
    """正常合并（模型档）：同样的定理名、两种写法 ⇒ 模型判 same ⇒ 1 行 + 第 2 份证明。"""
    st = _ws(tmp_path / "model-ok")
    sec = Secretary("B", root=st.root, store=st, seam=_FakeSeam(), enable_model=True)
    first = sec.record_statement(carry_proof_manuscript(st.root, {
        **_own(SAME_A, label="弦长引理"), "proof_text": PROOF_1}), role="B")
    assert first.get("created") is True, first
    second = sec.record_statement(carry_proof_manuscript(st.root, {
        **_own(SAME_B, label="弦长引理"), "proof_text": PROOF_3},
        statement_id="000001"), role="B")
    return st, second


# ------------------------------------------------------------------ a) 错并 ⇒ 红

def test_a_a_wrong_merge_is_caught_by_the_postcheck(tmp_path: pathlib.Path) -> None:
    """a：打桩判 same 造出「素数 / 奇素数」的错并 ⇒ 后验判据当场点名它。

    改前红：`_proposition_matches` 在 src 里 0 个读者 —— 这一笔并进来之后没有任何
    判据会说话（这一份就是那个读者）。
    """
    report = _bad_merge_report(tmp_path)
    problems = list(report["premise"]) + list(report["post"]["problems"])
    assert problems, "错并落盘之后后验判据一句话都没说 ⇒ 它没在拦"
    assert report["post"]["checked"] is False, report["post"]
    assert report["post"]["coarse"] is True, report["post"]
    assert int(report["post"]["pairs"] or 0) == 1, report["post"]
    text = "\n".join(problems)
    assert "错并" in text, text
    assert PAIR_WEAK[:20] in text and PAIR_STRONG[:20] in text, text
    assert "条件组" in text, text
    assert "coarse=True" in text and "不是判准" in text, text
    assert "basis=structural_probe" in text and "checked=False" in text, text
    assert "素数" in text and "奇素数" in text, text
    assert "包含关系" in text, text


# ------------------------------------------------------------------ b) 正常合并 ⇒ 绿

def test_b1_a_normal_merge_is_green_in_the_coarse_tier(tmp_path: pathlib.Path) -> None:
    """b（粗筛档）：同一命题的两种写法并成一条 ⇒ 后验判据绿（没缝时走确定性粗筛）。"""
    st, second = _ok_merge_by_key(tmp_path)
    assert second.get("merged") is True, second
    rows = _rows(st)
    assert len(rows) == 1 and len(_traces(rows[0])) == 1, rows
    post = _postcheck(rows)
    assert post["problems"] == [], post
    assert post["checked"] is False and post["coarse"] is True, post


def test_b2_a_normal_merge_is_green_in_the_model_tier(tmp_path: pathlib.Path) -> None:
    """b（模型档）：同样的合并，用有缝的秘书复算 ⇒ 绿（走的是模型那一档）。"""
    st, second = _ok_merge_by_name(tmp_path)
    assert second.get("merged") is True, second
    rows = _rows(st)
    sec = Secretary("B", root=st.root, store=st, seam=_FakeSeam(), enable_model=True)
    post = _postcheck(rows, sec=sec)
    assert post["problems"] == [], post
    assert post["checked"] is True and post["coarse"] is False, post


def test_b3_the_same_pair_is_red_in_the_model_tier_too(tmp_path: pathlib.Path) -> None:
    """b 的负控：错并那一对在有缝复算下也红（模型档不是橡皮图章），且不许退成粗筛。"""
    st, merged = _bad_merge(tmp_path)
    assert merged.get("merged") is True, merged
    rows = _rows(st)
    sec = Secretary("B", root=st.root, store=st, seam=_FakeSeam(), enable_model=True)
    post = _postcheck(rows, sec=sec)
    assert post["problems"], "有缝复算之后错并反而不报了 ⇒ 模型档是橡皮图章"
    assert post["coarse"] is False and post["checked"] is True, post
    assert sec.seam.calls, "模型档一次判定都没发 ⇒ 这条红不来自模型复算"
    text = "\n".join(post["problems"])
    assert "coarse=False" in text, text
    assert "条件组/结论组语义不一致" in text, text


# ------------------------------------------------------------------ c) 反真空

def test_c_removing_the_postcheck_turns_that_red_green(tmp_path: pathlib.Path) -> None:
    """c：把后验判据摘掉（打桩成恒空）⇒ a 那一组读数立刻变绿。"""
    assert _bad_merge_problems(tmp_path / "before"), (
        "夹具前提：摘掉之前它必须是红的（否则 c 没有对象）")
    module = sys.modules[__name__]
    real = module._postcheck

    def _no_check(rows, **_kw):
        return {"problems": [], "checked": True, "coarse": True, "pairs": 0}

    module._postcheck = _no_check
    try:
        assert _bad_merge_problems(tmp_path / "after") == [], (
            "把后验判据摘掉之后仍然是红的 ⇒ 那组断言不是对着它")
    finally:
        module._postcheck = real

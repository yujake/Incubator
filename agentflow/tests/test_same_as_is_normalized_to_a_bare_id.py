# -*- coding: utf-8 -*-
"""判据：模型把 `same_as` 写成列表串时，秘书要先归一化成裸号再判成员。

## 现场（真机 82，2026-11-01）

`temp/probe_82_errors/same_as_hits.txt` 记到 52 处（16 个会话行）`same_as` 取值只有
`"['000001']"` / `"['000003']"` / `''` 三种。而 `Secretary.adjudicate_proposition`
的成员判据是「逐字等于某个候选号」⇒ 模型明明判了 same、也点得出号，只因为外面套了
一层方括号与引号，就被降成 unknown、照旧落新行。本趟两个重复对（000001/000004、
000003/000005）都是它的产物。

## 这一份钉的四条（改前红）

| 条 | 它要证明的事 | 改前为什么红 |
|---|---|---|
| a | 裸号 / 列表串 / 带空白三种写法都归成裸号，verdict 保持 same | 改前 `"['000000']"` 与 `" 000000 "` 都不等于候选号 ⇒ unknown |
| b | 同一命题的两种写法各交一次：第二次并进既有行、不新建 | 改前第一次判 different（打桩）、第二次判 same 但号被外壳挡住 ⇒ 落第二行 |
| c | 多元素列表不猜：verdict unknown，reason 说"给了 2 个号" | 改前 reason 只说"不是候选表里的号"，数不出模型给了几个 |
| d | 不存在的号仍 unknown（不放宽"指不出来就不并"这条纪律） | 改前与 c 同一条文案，分不出"号不存在"与"号没归一化" |

边界：全部 tmp 工作区、零真实模型调用（判词由打桩的缝给）；不读写 `projects/`。
"""
from __future__ import annotations

import json
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import schema as S
from agentflow.secretary import Secretary
from agentflow.store import Store

#: 同一条命题的两种写法（措辞不同、条件与结论相同）。
FULL_A = "设 G 是 3-正则群；则弦长函数不是常值。"
FULL_A_ALT = "假设 G 为 3-正则群，于是弦长函数不是常值。"
#: 第一次登记带的证明（让这一笔成为一条带证明的正命题）。
PROOF_A = ("证明：把弦长函数记为 f，设 G 是 3-正则群。由定义直接计算每个顶点的邻域大小，"
           "弦长只依赖邻域结构，故 f 在正则性下取常值，与假设矛盾。")
#: 第二次交来的另一条证法（与 PROOF_A 不像，免得先撞"同种证明"那道拒绝）。
PROOF_B = ("证明：对顶点数作强归纳。取一条最长路径，用 3-正则性把端点邻域配对，"
           "再以诱导子图归结到更小的图，最终得到弦长随基图变化的递推，导出非常值。")


class _Seam:
    """打桩的秘书缝：按脚本回 `proposition_identity` 的判词，并记下每次调用。"""

    wired = True

    def __init__(self, replies: list[dict]) -> None:
        self.replies = list(replies)
        self.calls: list[str] = []

    def ask_json(self, prompt, **kw):
        self.calls.append(str(kw.get("note") or ""))
        reply = self.replies.pop(0) if self.replies else {"decision": "unknown"}
        data = {"decision": str(reply.get("decision") or "unknown"),
                "same_as": str(reply.get("same_as") or ""),
                "canonical_name": str(reply.get("canonical_name") or "弦长非常值"),
                "route": "", "condition": "打桩：条件未读", "conclusion": "打桩：结论未读",
                "reason": str(reply.get("reason") or "打桩"),
                "basis": [str(reply.get("reason") or "打桩")]}
        call = type("C", (), {"ok": True, "problem": "", "detail": ""})()
        return data, call


def _ws(base: pathlib.Path) -> Store:
    st = Store(base / "ws")
    st.init()
    return st


def _body(full: str) -> dict:
    """自产命题的必填件（`doc_id` + `quote_reason`；首登按猜想）。"""
    return {"statement_full": full, "statement_text": full[:24],
            "origin": "own_result", "kind": "conjecture",
            "doc_id": S.format_id(0), "quote_reason": "我方自产命题，没有外部引文要比对"}


def _rows(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("statements")]


def _verdicts(st: Store) -> list[dict]:
    path = pathlib.Path(st.root) / "out" / "secretary" / "proposition_verdicts.jsonl"
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _first_row(base: pathlib.Path) -> tuple[Store, dict]:
    """先落一条在册命题（判词打桩成 different），返回 `(store, 那一行)`。"""
    st = _ws(base)
    sec = Secretary("B", root=st.root, store=st,
                    seam=_Seam([{"decision": "different"}]), enable_model=True)
    got = sec.record_statement({**_body(FULL_A), "proof_text": PROOF_A}, role="B")
    assert got.get("created") is True, got
    return st, _rows(st)[0]


def _adjudicate(st: Store, same_as: str) -> dict:
    sec = Secretary("B", root=st.root, store=st,
                    seam=_Seam([{"decision": "same", "same_as": same_as}]),
                    enable_model=True)
    return sec.adjudicate_proposition(
        {"statement_full": FULL_A_ALT, "label": "弦长非常值", "kind": "theorem"})


# ================================================== a：三种写法都归成裸号并且判 same


def test_bare_list_and_padded_ids_all_normalize_to_the_bare_id(tmp_path):
    """a：裸号 / 列表串 / 带空白 ⇒ verdict=same，且 same_as 是裸号。

    改前红：成员判据逐字比，`"['000000']"` 与 `" 000000 "` 都不等于 `"000000"`
    ⇒ 三条全部降成 unknown，`same_as` 原样留着外壳。
    """
    for i, raw in enumerate(("000000", "['000000']", "  000000  ")):
        st, row = _first_row(tmp_path / f"ws{i}")
        sid = str(row["stmt_id"])
        got = _adjudicate(st, raw)
        assert got["checked"] is True, (raw, got)
        assert got["verdict"] == "same", (raw, got)
        assert got["same_as"] == sid, (raw, got)
        # 台账里落的是裸号：坏值不被持久化，也就不会在后续同文里被复用。
        same_rows = [r for r in _verdicts(st) if r.get("verdict") == "same"]
        assert same_rows and all(r.get("same_as") == sid for r in same_rows), same_rows


# ================================================== b：第二次送同一命题不新建


def test_the_second_submission_merges_instead_of_creating_a_row(tmp_path):
    """b：同一命题两种写法各交一次 ⇒ 第二次并进既有行（`created=False`），行数仍 1。

    改前红：第二次 `same_as="['000000']"` 被判成 unknown ⇒ 不并、落第二行。
    """
    st = _ws(tmp_path)
    sec = Secretary("B", root=st.root, store=st, enable_model=True, seam=_Seam([
        {"decision": "different"},
        {"decision": "same", "same_as": "['000000']"},
    ]))
    first = sec.record_statement({**_body(FULL_A), "proof_text": PROOF_A}, role="B")
    assert first.get("created") is True, first
    sid = str(first["stmt_id"])
    second = sec.record_statement({**_body(FULL_A_ALT), "proof_text": PROOF_B},
                                  role="B")
    assert second.get("ok") is True, second
    assert second.get("created") is False, second
    assert second.get("merged") is True, second
    assert str(second.get("stmt_id") or "") == sid, second
    assert len(_rows(st)) == 1, _rows(st)


# ================================================== c：多元素列表不猜


def test_a_multi_element_list_is_not_guessed_and_says_how_many(tmp_path):
    """c：`"['000000', '000001']"` ⇒ unknown，reason 点名"给了 2 个号"。

    改前红：同一句"不是候选表里的号" —— 读的人看不出模型给了几个号，
    也无从判断"这个坏值是模型写坏了还是框架读坏了"。
    """
    st, row = _first_row(tmp_path)
    got = _adjudicate(st, "['%s', '000001']" % row["stmt_id"])
    assert got["verdict"] == "unknown", got
    assert got["same_as"] == "", got
    assert "2 个号" in str(got.get("reason") or ""), got


# ================================================== d：不存在的号仍 unknown


def test_an_id_outside_the_candidates_stays_unknown(tmp_path):
    """d：归一化后仍不在候选集 ⇒ unknown（纪律不改：指不出来就不并）。

    改前红：同上一条的同一句文案；这一条钉的是"归一化不许变成放宽"。
    """
    st, _row = _first_row(tmp_path)
    got = _adjudicate(st, "['000999']")
    assert got["checked"] is True, got
    assert got["verdict"] == "unknown", got
    assert got["same_as"] == "000999", got
    assert "不是候选表里的号" in str(got.get("reason") or ""), got

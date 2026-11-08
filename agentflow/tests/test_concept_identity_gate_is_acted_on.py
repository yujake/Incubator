# -*- coding: utf-8 -*-
"""判据：概念同一性闸判出来的结论，四个入口都要处置（2026-11-08，D2 漏口）。

## 改前是什么形态（走查实测，`temp/_walkthrough_report.md` §3、§7.7）

`secretary.concept_identity_gate`（发号前、纯读）已经存在，但它判出来的
`state` / `candidates` 四个入口都不处置：

| # | 入口 | 改前 |
|---|---|---|
| 1 | `conceptrows.upsert` | 只读 `gate["checked"]`；判 `same` 仍发新号、落第二行（实测 rows=2、counters={"stmt":2}） |
| 2 | `Secretary.write_concept_row` | 判词只进 `out["concept_identity"]`，随后无条件 upsert |
| 3 | `Secretary._record_pending_concept` | 完全不判（D12 甲：定义还没抽到也必须照落） |
| 4 | `agent_b.run_once.resolve_concept` | 只按名字 `find_concept`，闸的 `same` 被忽略 |

## 统一口径（唯一折算点 `secretary.concept_identity_action`）

| 闸的判词 | 处置 | 读数 |
|---|---|---|
| `checked=False` | `refused`（受控拒、不发号） | `concept_action="refused"` |
| `checked=True` + `state="same"` + 有候选 | `merged`（并入那一条，不新建行、不发号） | `concept_action="merged"` + `same_as` |
| 其余（`different` / 候选 0 条） | `created`（照常新建） | `concept_action="created"` |

四个入口的读数都必须能读到 `checked / state / same_as / reason`，并与
`concept_action` 一起落（并入与新建要分得开）。

## 这一份钉的（逐条对应题面 a–f）

- a：同义概念从每一个入口进来都不许落第二行（四个入口各一条）；
- b：判不了 ⇒ 0 新行 + counters 不动（每个发号入口一条）；
- c：真不同 / 候选 0 条 ⇒ 照常新建（正控，防"一律拒"）；
- d：读数四格齐全；
- e：反真空：把某个入口的处置摘掉（折算点打桩成恒 `created`）⇒ 对应判据红。

## 边界

全部 tmp 工作区、零真实模型调用、不读写 `projects/`。
"""
from __future__ import annotations

import json
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest

from agentflow import conceptrows as CR
from agentflow import secretary as SEC
from agentflow.store import Store

REPO = pathlib.Path(__file__).resolve().parents[1]

#: 真机 mp3-r2 那条概念的两种写法（同一被定义项，只差一句措辞）。
REAL_LABEL = "finite-dimensional Lie algebra"
ALT_LABEL = "有限维 Lie 代数"
REAL_DEF_1 = ("概念（有限维 Lie 代数）：设 K 为特征 0 的域，g 为 K 上的 Lie 代数。"
              "称 g 有限维，若 dim_K g < ∞。本概念在本文中的作用是作为"
              "「U(g) 为 Noetherian」的充分条件。")
REAL_DEF_2 = ("概念（有限维 Lie 代数）：设 K 为特征 0 的域，g 为 K 上的 Lie 代数。"
              "称 g 有限维，若 dim_K g < ∞。在本文中它的作用是"
              "「U(g) 为 Noetherian」的充分条件。")

#: 一个真正不同的概念（正控：它必须照常新建）。
OTHER_LABEL = "幂零李代数"
OTHER_DEF = "概念（幂零李代数）：称 g 幂零，若降中心列在有限步终止。"

#: 抽不出定义项的标签（通用词不算定义项）：与在册任一条比都只能判"判不了"。
UNJUDGEABLE_LABEL = "概念"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _rows(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("statements")]


def _counter(st: Store, kind: str = "stmt") -> int:
    path = pathlib.Path(st.root) / "data" / "counters.json"
    return int(((json.loads(path.read_text(encoding="utf-8")).get("counters") or {})
                .get(kind, 0)))


def _reading(reading: dict, *, action: str, same_as: str = "") -> None:
    """d 的尺子：四格 + `concept_action` 都要在，且彼此不矛盾。

    四格是题面点名的读数（`checked / state / same_as / reason`）；`concept_action`
    是"并入还是新建"的唯一分档。`refused` 那一档的 `checked` 必须是 False
    （拿 True 冒充"判过了"是本项目反复踩的三态折平）。
    """
    got = dict(reading or {})
    assert got.get("concept_action") == action, got
    for key in ("checked", "state", "same_as", "reason"):
        assert key in got, (key, got)
    if action == "refused":
        assert got.get("checked") is False, got
        assert str(got.get("state") or "") == "", got
        assert str(got.get("same_as") or "") == "", got
        assert str(got.get("reason") or ""), got
    elif action == "merged":
        assert got.get("checked") is True, got
        assert str(got.get("state") or "") == "same", got
        assert str(got.get("same_as") or "") == same_as, got
        assert str(got.get("reason") or ""), got
    else:
        assert got.get("checked") is True, got
        assert str(got.get("state") or "") in ("same", "different"), got
        assert str(got.get("same_as") or "") == "", got


# ============================================================ 入口 1：conceptrows.upsert


def test_a1_upsert_merges_a_synonym_instead_of_a_second_row(tmp_path: pathlib.Path) -> None:
    """a（入口 1）：同名概念经 `CR.upsert` 再交一次 ⇒ 并入、不落第二行、不发号。

    改前红：闸判了 `state=same, candidates=["000000"]`，`upsert` 只读 `checked`
    ⇒ 第二笔照常 `alloc_id` + 建行（真机 mp3-r2 的 000003 / 000004 形态）。
    """
    st = _ws(tmp_path)
    first = CR.upsert(st, label=REAL_LABEL, definition=REAL_DEF_1)
    assert first.get("checked") is True and first.get("concept_action") == "created", first
    sid = str(first.get("stmt_id") or "")
    assert sid, first
    before_rows, before_count = len(_rows(st)), _counter(st)

    second = CR.upsert(st, label=ALT_LABEL, definition=REAL_DEF_2)
    assert second.get("checked") is True, second
    assert second.get("concept_action") == "merged", second
    assert str(second.get("stmt_id") or "") == sid, second
    _reading(second.get("concept_identity") or {}, action="merged", same_as=sid)

    assert len(_rows(st)) == before_rows == 1, [r.get("label") for r in _rows(st)]
    assert _counter(st) == before_count == 1, (_counter(st), before_count)


def test_b1_upsert_refuses_unjudged_without_a_row_or_an_id(tmp_path: pathlib.Path) -> None:
    """b（入口 1）：判不了 ⇒ 受控拒、0 新行、counters 不动（不入第二行、不烧号）。

    判据：在册那条抽得出定义项（`群`），这一条抽不出（标签是通用词、正文不是
    「概念（X）」形态）⇒ `checked=False`。改前红：照常发号建行。
    """
    st = _ws(tmp_path)
    first = CR.upsert(st, label="群", definition="概念（群）：带运算的集合。")
    assert first.get("checked") is True, first
    before_rows, before_count = len(_rows(st)), _counter(st)

    refused = CR.upsert(st, label=UNJUDGEABLE_LABEL,
                        definition="设 Y 是一个拓扑空间。")
    assert refused.get("checked") is False, refused
    assert refused.get("concept_action") == "refused", refused
    assert str(refused.get("stmt_id") or "") == "", refused
    _reading(refused.get("concept_identity") or {}, action="refused")
    assert "没判成" in str((refused.get("concept_identity") or {}).get("reason") or ""), refused

    assert len(_rows(st)) == before_rows == 1, _rows(st)
    assert _counter(st) == before_count, (_counter(st), before_count)
    # 号没有被烧掉：下一条合法概念拿到的是下一个号，不是隔一个。
    nxt = CR.upsert(st, label=OTHER_LABEL, definition=OTHER_DEF)
    assert nxt.get("concept_action") == "created", nxt
    assert int(str(nxt.get("stmt_id") or "0")) == before_count, (nxt, before_count)


def test_c1_different_concepts_still_get_their_own_rows(tmp_path: pathlib.Path) -> None:
    """c（正控，入口 1）：真不同 ⇒ 照常发号建行（不是一律拒、也不是一律并）。"""
    st = _ws(tmp_path)
    a = CR.upsert(st, label=REAL_LABEL, definition=REAL_DEF_1)
    b = CR.upsert(st, label=OTHER_LABEL, definition=OTHER_DEF)
    assert a.get("concept_action") == "created" and b.get("concept_action") == "created", (a, b)
    assert str(a.get("stmt_id")) != str(b.get("stmt_id")), (a, b)
    assert len(_rows(st)) == 2, [r.get("label") for r in _rows(st)]


# ============================================================ 入口 2：Secretary.write_concept_row


def _secretary(st: Store) -> SEC.Secretary:
    return SEC.Secretary("B", root=st.root, store=st)


def test_a2_write_concept_row_merges_instead_of_unconditional_upsert(
        tmp_path: pathlib.Path) -> None:
    """a（入口 2）：`write_concept_row` 判成 same ⇒ 并入、不落第二行、不发号。

    改前红：判词只进 `out["concept_identity"]`，随后仍无条件 `tx.upsert("statements")`
    ⇒ 第二行落盘，且 `push_counters("000009")` 把 `stmt` 计数器抬到 10。
    """
    st = _ws(tmp_path)
    first = CR.upsert(st, label=REAL_LABEL, definition=REAL_DEF_1)
    sid = str(first.get("stmt_id") or "")
    before_rows, before_count = len(_rows(st)), _counter(st)
    reading: dict = {}
    sec = _secretary(st)
    with st.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        got = sec.write_concept_row(
            tx, stmt_id="000009", label=ALT_LABEL, definition=REAL_DEF_2,
            origin="own_result", self_authored=True, out=reading)
    assert got.get("concept_action") == "merged", got
    assert str(got.get("stmt_id") or "") == sid, got
    _reading(reading.get("concept_identity") or {}, action="merged", same_as=sid)
    assert reading.get("concept_action") == "merged", reading
    assert len(_rows(st)) == before_rows == 1, [r.get("label") for r in _rows(st)]
    assert _counter(st) == before_count == 1, (_counter(st), before_count)


def test_b2_write_concept_row_refuses_unjudged_without_a_row_or_a_burned_id(
        tmp_path: pathlib.Path) -> None:
    """b（入口 2）：判不了 ⇒ 受控拒、0 新行、counters 不动（不新建、不烧号）。"""
    st = _ws(tmp_path)
    first = CR.upsert(st, label="群", definition="概念（群）：带运算的集合。")
    assert first.get("checked") is True, first
    before_rows, before_count = len(_rows(st)), _counter(st)
    reading: dict = {}
    sec = _secretary(st)
    with st.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        got = sec.write_concept_row(
            tx, stmt_id="000009", label=UNJUDGEABLE_LABEL,
            definition="设 Y 是一个拓扑空间。",
            origin="own_result", self_authored=True, out=reading)
    assert got.get("concept_action") == "refused", got
    assert got.get("checked") is False, got
    assert got.get("refused") == SEC.CONCEPT_IDENTITY_UNJUDGED, got
    _reading(reading.get("concept_identity") or {}, action="refused")
    assert len(_rows(st)) == before_rows == 1, _rows(st)
    assert _counter(st) == before_count, (_counter(st), before_count)


def test_c2_write_concept_row_still_creates_a_different_concept(
        tmp_path: pathlib.Path) -> None:
    """c（正控，入口 2）：判得了 different ⇒ 照常写那一行（不是一律并、一律拒）。"""
    st = _ws(tmp_path)
    CR.upsert(st, label=REAL_LABEL, definition=REAL_DEF_1)
    reading: dict = {}
    sec = _secretary(st)
    with st.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        got = sec.write_concept_row(
            tx, stmt_id="000009", label=OTHER_LABEL, definition=OTHER_DEF,
            origin="own_result", self_authored=True, out=reading)
    assert str(got.get("stmt_id") or "") == "000009", got
    assert reading.get("concept_action") == "created", reading
    assert [r.get("stmt_id") for r in _rows(st)] == ["000000", "000009"], _rows(st)
    _reading(reading.get("concept_identity") or {}, action="created")


def test_b2b_write_concept_row_refuses_unjudged_even_without_a_definition(
        tmp_path: pathlib.Path) -> None:
    """b（入口 2 收紧）：普通调用（非 D12 路径）判不了 ⇒ 受控拒，不因"没定义"自动照落。

    改前红：`write_concept_row` 把"没有定义可判"一律当成 D12 甲（照落成 pending）——
    那条口子让"同名/同义概念都不写定义项"能绕过去、落成两行。改后按调用方身份分：
    只有 `_record_pending_concept`（D12 甲 的唯一入口）能拿到 `d12_pending=True`，
    普通调用一律受控拒；拒信里给改法。
    """
    st = _ws(tmp_path)
    active = CR.upsert(st, label=UNJUDGEABLE_LABEL, definition="设 X 是一个集合。")
    assert active.get("concept_action") == "created", active
    before_rows, before_count = len(_rows(st)), _counter(st)
    reading: dict = {}
    sec = _secretary(st)
    with st.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        got = sec.write_concept_row(
            tx, stmt_id="000009", label="生僻概念 Y", definition="",
            origin="own_result", self_authored=True, out=reading)
    assert got.get("concept_action") == "refused", got
    assert got.get("checked") is False, got
    assert got.get("refused") == SEC.CONCEPT_IDENTITY_UNJUDGED, got
    text = str(got.get("reason") or "")
    assert "改法" in text and "定义项" in text, text
    assert len(_rows(st)) == before_rows == 1, _rows(st)
    assert _counter(st) == before_count == 1, (_counter(st), before_count)


def test_b2c_the_d12_entry_still_lands_the_same_unjudged_concept(
        tmp_path: pathlib.Path) -> None:
    """b（② 的另一半读数）：同一条"没有定义项"的概念 —— D12 入口照落（pending）。

    与 b2b 是同一条概念的两种来路：普通 `write_concept_row` 拒，D12 甲 的
    `_record_pending_concept` 照落，且读数写明 `d12_pending=True` 与"判不了"。
    """
    st = _ws(tmp_path)
    CR.upsert(st, label=UNJUDGEABLE_LABEL, definition="设 X 是一个集合。")
    before_rows, before_count = len(_rows(st)), _counter(st)
    got = _pending(_secretary(st), "生僻概念 Y")
    assert got.get("created") is True, got
    assert got.get("concept_action") == "created", got
    identity = dict(got.get("concept_identity") or {})
    assert identity.get("checked") is False and identity.get("state") == "", identity
    assert got.get("d12_pending") is True, got
    assert len(_rows(st)) == before_rows + 1, _rows(st)
    assert _counter(st) == before_count + 1, (_counter(st), before_count)


def test_e2_removing_the_ordinary_refusal_brings_the_second_row_back(
        tmp_path: pathlib.Path) -> None:
    """e（② 的反真空）：让普通调用走 D12 甲 那条豁免（= 把拒绝摘掉）⇒ 复现两行。

    这一条与 b2b 是同一场景的两面：b2b 证明普通调用会被拒；这一条证明"若不拒、照落成
    pending"，同一条只有标签没有定义项的概念就会落成第二行、并把号烧到 000009 ——
    所以 b2b 的绿是"按调用方身份拒"给的，不是"恰好没写进去"。
    """
    st = _ws(tmp_path)
    CR.upsert(st, label=UNJUDGEABLE_LABEL, definition="设 X 是一个集合。")
    sec = _secretary(st)
    reading: dict = {}
    with st.tx(*CR.tables_for_concept_write(), actor="agent-B") as tx:
        got = sec.write_concept_row(
            tx, stmt_id="000009", label="生僻概念 Y", definition="",
            origin="own_result", self_authored=True, d12_pending=True, out=reading)
    assert reading.get("concept_action") == "created", reading
    assert str(got.get("stmt_id") or "") == "000009", got
    assert len(_rows(st)) == 2, [r.get("label") for r in _rows(st)]
    assert _counter(st) == 10, _counter(st)


def test_d2_only_the_two_documented_callers_may_switch_the_judgment_off() -> None:
    """d（机械判据）：两个"关掉处置"的开关各只有一条登记过的来路。

    - `transition_sync=True`：只给 `conceptrows.sync_from_legacy`（过渡同步一号一行）；
    - `d12_pending=True`：只给 `secretary._record_pending_concept`（D12 甲 的唯一入口）。

    这条不是形式主义：`write_concept_row` 的默认值就是强制处置，这两个开关是"照落/只报"
    的两条窄路。若哪一天别的调用点也传它们，概念轴就多出后门 —— 而盘上看起来一切正常。
    所以按 AST 逐调用点核，并钉住两个默认值都是 False。
    """
    import ast
    import inspect

    def _true_callers(name: str) -> list[tuple[str, str]]:
        hits: list[tuple[str, str]] = []
        for path in (REPO / "src").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for node in ast.walk(fn):
                    if not isinstance(node, ast.Call):
                        continue
                    for kw in node.keywords:
                        if (kw.arg == name and isinstance(kw.value, ast.Constant)
                                and kw.value.value is True):
                            hits.append((path.name, fn.name))
        return sorted(hits)

    signature = inspect.signature(SEC.Secretary.write_concept_row)
    for name in ("transition_sync", "d12_pending"):
        assert signature.parameters[name].default is False, name

    assert _true_callers("transition_sync") == [("conceptrows.py", "sync_from_legacy")]
    assert _true_callers("d12_pending") == [("secretary.py", "_record_pending_concept")]


# ============================================================ 入口 3：_record_pending_concept


def _pending(sec: SEC.Secretary, label: str, **kw) -> dict:
    """交一条"定义还没抽到"的概念（D12 甲：走 `_record_pending_concept`）。"""
    payload = {"label": label, "statement_full": "", "kind": "concept",
               "origin": "own_result", "self_authored": True}
    payload.update(kw)
    return sec.record_statement(payload, role="B")


def test_a3_pending_concept_merges_into_the_registered_one(
        tmp_path: pathlib.Path) -> None:
    """a（入口 3）：待补概念与在册那条同名 ⇒ 并入，不落第二行、不发号。

    改前红：`_record_pending_concept` 只按 `T.normalize(标签)` 查重，判词完全不看闸
    ⇒ 标签只差一个空格（`有限维 Lie 代数` / `有限维Lie代数`）时查重漏掉、第二行照落。
    """
    st = _ws(tmp_path)
    first = CR.upsert(st, label="有限维 Lie 代数",
                      definition="概念（有限维 Lie 代数）：dim_K g < ∞。")
    sid = str(first.get("stmt_id") or "")
    before_rows, before_count = len(_rows(st)), _counter(st)
    gotten = _pending(_secretary(st), "有限维Lie代数")
    assert gotten.get("created") is False and gotten.get("duplicate") is True, gotten
    assert str(gotten.get("stmt_id") or "") == sid, gotten
    assert gotten.get("concept_action") == "merged", gotten
    _reading(gotten.get("concept_identity") or {}, action="merged", same_as=sid)
    assert len(_rows(st)) == before_rows == 1, [r.get("label") for r in _rows(st)]
    assert _counter(st) == before_count == 1, (_counter(st), before_count)
    # 并入不把在册那一行打回 pending（定义还在）
    assert str(_rows(st)[0].get("status") or "") == "active", _rows(st)[0]


def test_a3b_two_pending_twins_do_not_make_two_rows(tmp_path: pathlib.Path) -> None:
    """a（入口 3，待补对特补）：两条待补概念只差一个空格 ⇒ 仍只有一行、一个号。

    这一档闸看不到对手：`_same_concept_candidate` 跳过不可作依据的状态（`pending_definition`
    在列）⇒ 它只会说"在册没有可比行"。所以这一入口按同一把定义项键（`concept_keys` 的
    标签那一半）把待补行也看一遍 —— 判据还是 `propositionkey` 那一处，不另写一份。
    """
    st = _ws(tmp_path)
    sec = _secretary(st)
    first = _pending(sec, "有限维 Lie 代数")
    assert first.get("created") is True, first
    assert first.get("concept_action") == "created", first
    assert str(_rows(st)[0].get("status") or "") == "pending_definition", _rows(st)[0]
    before = _counter(st)
    second = _pending(sec, "有限维Lie代数")
    assert second.get("created") is False and second.get("duplicate") is True, second
    assert str(second.get("stmt_id") or "") == str(first.get("stmt_id")), (first, second)
    assert second.get("concept_action") == "merged", second
    _reading(second.get("concept_identity") or {}, action="merged",
             same_as=str(first.get("stmt_id") or ""))
    assert len(_rows(st)) == 1, [r.get("label") for r in _rows(st)]
    assert _counter(st) == before, (_counter(st), before)


def test_a3c_exact_same_label_pending_is_reported_as_merged(
        tmp_path: pathlib.Path) -> None:
    """a（入口 3，既有查重那一半）：标签逐字相同 ⇒ 不新建，且读数要能看出是"并入"。"""
    st = _ws(tmp_path)
    sec = _secretary(st)
    first = _pending(sec, "新概念")
    second = _pending(sec, "新概念")
    assert second.get("created") is False and second.get("duplicate") is True, second
    assert str(second.get("stmt_id") or "") == str(first.get("stmt_id")), (first, second)
    assert second.get("concept_action") == "merged", second
    _reading(second.get("concept_identity") or {}, action="merged",
             same_as=str(first.get("stmt_id") or ""))
    assert len(_rows(st)) == 1
    assert _counter(st) == 1


def test_a3d_unjudged_pending_concept_still_lands_and_says_why(
        tmp_path: pathlib.Path) -> None:
    """D12 甲（入口 3）：定义还没抽到 ⇒ 判不了也照落，但前提必须写在读数里。

    这一格钉的是题面 ② 的口径：D12 甲 豁免的是"定义还没抽到"，不是"同一个概念可以
    落两行"。判得 `same` 时上面 a3 已经证明它仍会并入；判不了时照落成
    `pending_definition`，读数里 `checked=False` + `d12_pending=True` + 原因（闸为什么
    判不了），所以它不是一条静默的漏口。
    """
    st = _ws(tmp_path)
    # 在册一条抽不出定义项的 active 概念（标签是通用词、正文不是「概念（X）」形态）
    active = CR.upsert(st, label=UNJUDGEABLE_LABEL, definition="设 X 是一个集合。")
    assert active.get("concept_action") == "created", active
    before = _counter(st)
    gotten = _pending(_secretary(st), "生僻概念 Y")
    assert gotten.get("created") is True, gotten
    assert gotten.get("concept_action") == "created", gotten
    identity = dict(gotten.get("concept_identity") or {})
    assert identity.get("checked") is False and identity.get("state") == "", identity
    assert str(identity.get("same_as") or "") == "", identity
    assert str(identity.get("reason") or ""), identity
    assert gotten.get("d12_pending") is True, gotten
    assert "D12" in str(gotten.get("reason") or ""), gotten
    rows = _rows(st)
    assert len(rows) == 2, [r.get("label") for r in rows]
    assert _counter(st) == before + 1, (_counter(st), before)


def test_c3_different_pending_concepts_each_get_a_row(tmp_path: pathlib.Path) -> None:
    """c（正控，入口 3）：两个真不同的待补概念 ⇒ 各自一行（不是一律并）。"""
    st = _ws(tmp_path)
    sec = _secretary(st)
    a = _pending(sec, "有限维李代数")
    b = _pending(sec, "幂零李代数")
    assert a.get("created") is True and b.get("created") is True, (a, b)
    assert a.get("concept_action") == "created" and b.get("concept_action") == "created", (a, b)
    assert str(a.get("stmt_id")) != str(b.get("stmt_id")), (a, b)
    assert len(_rows(st)) == 2, [r.get("label") for r in _rows(st)]


# ============================================================ 拒信里的改法（两轴）
#
# 业主 2026-11-08：拒信只教做得到的事。p262 已把这两轴教进 B 的题面；真正的拒信渲染
# 还在 `secretary.py` 那两处 —— 判不了时各补一句改法（正面表述）。下面两条打桩给一个
# "只说了判不了、没给改法"的判词 ⇒ 绿只能由渲染那一句给（把那一句摘掉，这一条当场红）。

_PROOF_FULL = "设 G 是 3-正则群；则弦长函数不是常值。"
_PROOF_FULL_KEY = "假设 G 为 3-正则群，于是弦长函数不是常值。"
_PROOF_A = ("证明：把弦长函数记为 f，设 G 是 3-正则群。由定义直接计算每个顶点的邻域大小，"
            "弦长只依赖邻域结构，故 f 在正则性下取常值，与假设矛盾。")
_PROOF_B = ("证明：对顶点数作强归纳。取一条最长路径，用 3-正则性把端点邻域配对，"
            "再以诱导子图归结到更小的图，最终得到弦长随基图变化的递推，导出非常值。")


def _own(full: str) -> dict:
    from agentflow import schema as S

    return {"statement_full": full, "statement_text": full[:24],
            "origin": "own_result", "kind": "conjecture",
            "doc_id": S.format_id(0), "quote_reason": "我方自产命题，没有外部引文要比对"}


def test_the_concept_refusal_teaches_what_to_write_next(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """概念同一性判不了 ⇒ 拒信里要能读到"把定义项写出来"这一条改法。"""
    monkeypatch.setattr(
        SEC.Secretary, "_same_concept_candidate",
        lambda self, tx, **kw: {"hit": None, "checked": False, "state": "", "basis": "",
                                "reason": "打桩：判不了", "candidates": []},
        raising=True)
    st = _ws(tmp_path)
    got = _secretary(st).record_statement(
        {"statement_full": "设 X 是一个集合；则 X 是空的当且仅当它没有元素。",
         "label": "空集", "kind": "concept", "origin": "own_result",
         "self_authored": True}, role="B")
    assert got.get("checked") is False, got
    assert got.get("refused") == SEC.CONCEPT_IDENTITY_UNJUDGED, got
    text = str(got.get("reason") or "")
    assert "改法" in text and "定义项" in text, text
    assert len(_rows(st)) == 0, _rows(st)


def test_the_proof_kind_refusal_teaches_what_to_do_next(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
        signed_v_handoffs) -> None:  # noqa: ANN001 —— conftest 的 V 签前提夹具
    """同种证明判不了 ⇒ 拒信里要能读到"换一条真正不同的证法再交"这一条改法。"""
    from agentflow import propositionkey as PK
    from agentflow.agent_b import AgentB

    monkeypatch.setattr(
        PK, "same_kind_proof",
        lambda *a, **k: {"checked": False, "state": "", "basis": "", "similarity": 0.0,
                         "reason": "打桩：判定面没给出可用结论"},
        raising=True)
    st = _ws(tmp_path)
    b = AgentB(st, extractor=None, extract_text=None, config={})
    first = b.register_statement(**_own(_PROOF_FULL), proof_text=_PROOF_A)
    assert first.get("ok") is True, first
    refused = b.register_statement(**_own(_PROOF_FULL_KEY), proof_text=_PROOF_B)
    assert refused.get("ok") is False, refused
    assert refused.get("kind") == SEC.PROOF_KIND_UNJUDGED, refused
    text = str(refused.get("error") or "")
    assert "改法" in text and "证法" in text, text


# ============================================================ 入口 4：agent_b.run_once.resolve_concept

_QUOTE = "An abelian group is a group in which the commutative law holds."


class _StubExtractor:
    """确定性抽取器替身：交回预设的概念草稿（不调模型、不读 PDF）。"""

    def __init__(self, concepts=()):
        self._concepts = list(concepts)
        self.calls = 0

    def extract(self, doc, lit_id, meta):
        self.calls += 1
        return list(self._concepts), []


def _one_paper(st: Store, lit_id: str = "0000") -> None:
    from conftest import add_literature, write_library_file

    write_library_file(st, f"{lit_id}/a.txt", _QUOTE)
    add_literature(st, lit_id, title="A", path=f"{lit_id}/a.txt")


def _agent_b(st: Store, concepts) -> object:
    from agentflow.agent_b import AgentB
    from agentflow.extract import extract_text
    from agentflow.llm import ConceptDraft

    drafts = [ConceptDraft(name=c["name"], definition=c["definition"], aliases=[],
                           source_lit_id="0000") for c in concepts]
    return AgentB(st, extractor=_StubExtractor(drafts), extract_text=extract_text,
                  config={"lease_seconds": 900, "max_attempts": 3})


def _concept_rows(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("statements") if str(r.get("kind") or "") == "concept"]


def _identity_details(res: dict) -> list[dict]:
    return [d for d in (res.get("details") or []) if d.get("stage") == "concept_identity"]


def test_a4_run_once_merges_a_synonym_without_a_second_row(
        tmp_path: pathlib.Path) -> None:
    """a（入口 4）：B 消化文献时遇到同义概念 ⇒ 并入、不落第二行、不发号。

    改前红：`resolve_concept` 只按名字 `find_concept`，闸判出的 `same` 被忽略 ⇒
    另发一个号、落第二行（真机 mp3-r2 的形态）。
    """
    st = _ws(tmp_path)
    first = CR.upsert(st, label=REAL_LABEL, definition=REAL_DEF_1)
    sid = str(first.get("stmt_id") or "")
    _one_paper(st)
    before_rows, before_count = len(_concept_rows(st)), _counter(st)
    res = _agent_b(st, [{"name": ALT_LABEL, "definition": REAL_DEF_2}]).run_once()
    out = res.to_dict()
    assert int(out.get("concepts_created") or 0) == 0, out
    assert int(out.get("concepts_reused") or 0) == 1, out
    assert len(_concept_rows(st)) == before_rows == 1, [
        r.get("label") for r in _concept_rows(st)]
    assert _counter(st) == before_count == 1, (_counter(st), before_count)
    details = _identity_details(out)
    assert details, out.get("details")
    merged = [d for d in details if d.get("concept_action") == "merged"]
    assert merged and str(merged[0].get("same_as") or "") == sid, details
    for key in ("checked", "state", "same_as", "reason"):
        assert key in merged[0], merged[0]
    assert merged[0].get("checked") is True and merged[0].get("state") == "same", merged[0]


def test_b4_run_once_refuses_unjudged_without_a_row_or_an_id(
        tmp_path: pathlib.Path) -> None:
    """b（入口 4）：判不了 ⇒ 受控拒、0 新行、counters 不动（不占号）。"""
    st = _ws(tmp_path)
    CR.upsert(st, label="群", definition="概念（群）：带运算的集合。")
    _one_paper(st)
    before_rows, before_count = len(_concept_rows(st)), _counter(st)
    res = _agent_b(st, [{"name": UNJUDGEABLE_LABEL,
                         "definition": "设 Y 是一个拓扑空间。"}]).run_once()
    out = res.to_dict()
    assert int(out.get("concepts_created") or 0) == 0, out
    assert int(out.get("concepts_refused") or 0) == 1, out
    assert len(_concept_rows(st)) == before_rows == 1, _concept_rows(st)
    assert _counter(st) == before_count, (_counter(st), before_count)
    details = _identity_details(out)
    assert details and details[0].get("refused_code") == SEC.CONCEPT_IDENTITY_UNJUDGED, details
    assert details[0].get("checked") is False and details[0].get("state") == "", details
    assert str(details[0].get("reason") or ""), details
    assert str(details[0].get("same_as") or "") == "", details


def test_c4_run_once_still_creates_a_different_concept(tmp_path: pathlib.Path) -> None:
    """c（正控，入口 4）：真不同 / 在册 0 条 ⇒ 照常发号建行（不是一律拒、一律并）。

    新建那一档不另落 `concept_identity` 读数（`details` 截前 20 条，一条概念一条会把
    配额拒绝那几条挤掉）：它的处置由 `concepts_created` 与盘上那一行读。
    """
    st = _ws(tmp_path)
    _one_paper(st)
    res = _agent_b(st, [{"name": REAL_LABEL, "definition": REAL_DEF_1}]).run_once()
    out = res.to_dict()
    assert int(out.get("concepts_created") or 0) == 1, out
    rows = _concept_rows(st)
    assert len(rows) == 1, rows
    assert _counter(st) == 1, _counter(st)
    assert _identity_details(out) == [], _identity_details(out)


# ============================================================ 入口 5：命题载荷里的概念清单
# （`Secretary._record_statement_tx` 的 `concepts=` 那一支：B 交一条命题时顺带交概念草稿。
#   它不在题面点名的四个入口里，但它同样在写之前发号 —— write_concept_row 收紧之后不先
#   过闸就会"发了号不建行"（id_gap），所以这一处也必须先判后分号。）


def _theorem_with_concepts(concepts: list[dict]) -> dict:
    from agentflow import schema as S

    return {"statement_full": "定理：对任意群 G，命题 ph 成立。",
            "statement_text": "命题 ph 成立", "origin": "own_result",
            "kind": "theorem", "doc_id": S.format_id(0),
            "quote_reason": "我方自产命题，没有外部引文要比对",
            "concepts": list(concepts)}


def _own_concept(name: str, definition: str) -> dict:
    return {"name": name, "definition": definition, "origin": "own_result",
            "self_authored": True}


def _stmts(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("statements")]


def test_a5_concepts_in_a_statement_payload_are_merged_without_a_burned_id(
        tmp_path: pathlib.Path) -> None:
    """a（入口 5）：命题载荷里的同义概念 ⇒ 并入、不落第二行、不发号。

    改前（write_concept_row 收紧之后）红：`tx.alloc_id(concept_kind)` 先发号，
    再进 write_concept_row 才发现是 same ⇒ 行没建、号已经发出去了（counters 多 1）。
    """
    st = _ws(tmp_path)
    first = CR.upsert(st, label=REAL_LABEL, definition=REAL_DEF_1)
    sid = str(first.get("stmt_id") or "")
    got = _secretary(st).record_statement(
        _theorem_with_concepts([_own_concept(ALT_LABEL, REAL_DEF_2)]), role="B")
    assert got.get("checked") is True and got.get("created") is True, got
    assert len(_concept_rows(st)) == 1, [r.get("label") for r in _concept_rows(st)]
    assert [r.get("stmt_id") for r in _stmts(st)] == ["000000", "000001"], _stmts(st)
    assert _counter(st) == 2, _counter(st)
    actions = list(got.get("concepts_identity") or [])
    assert actions and actions[0].get("concept_action") == "merged", actions
    assert str(actions[0].get("same_as") or "") == sid, actions
    for key in ("checked", "state", "same_as", "reason"):
        assert key in actions[0], actions[0]


def test_b5_unjudged_concept_in_a_statement_payload_is_refused_without_a_burned_id(
        tmp_path: pathlib.Path) -> None:
    """b（入口 5）：判不了 ⇒ 那一条概念受控拒、0 新行、counters 不动（不烧号）。"""
    st = _ws(tmp_path)
    CR.upsert(st, label="群", definition="概念（群）：带运算的集合。")
    got = _secretary(st).record_statement(
        _theorem_with_concepts([_own_concept(UNJUDGEABLE_LABEL,
                                             "设 Y 是一个拓扑空间。")]), role="B")
    assert got.get("checked") is True and got.get("created") is True, got  # 命题照落
    assert len(_concept_rows(st)) == 1, [r.get("label") for r in _concept_rows(st)]
    assert [r.get("stmt_id") for r in _stmts(st)] == ["000000", "000001"], _stmts(st)
    assert _counter(st) == 2, _counter(st)
    refused = list(got.get("concepts_refused") or [])
    assert refused and refused[0].get("name") == UNJUDGEABLE_LABEL, refused
    assert refused[0].get("concept_action") == "refused", refused
    assert refused[0].get("checked") is False and refused[0].get("state") == "", refused
    assert str(refused[0].get("reason") or ""), refused


def test_c5_a_different_concept_in_a_statement_payload_is_created(
        tmp_path: pathlib.Path) -> None:
    """c（正控，入口 5）：真不同 ⇒ 照常发号建那一行。"""
    st = _ws(tmp_path)
    got = _secretary(st).record_statement(
        _theorem_with_concepts([_own_concept(REAL_LABEL, REAL_DEF_1)]), role="B")
    assert got.get("checked") is True and got.get("created") is True, got
    rows = _concept_rows(st)
    assert len(rows) == 1 and rows[0].get("stmt_id") == "000001", rows
    assert _counter(st) == 2, _counter(st)
    actions = list(got.get("concepts_identity") or [])
    assert actions and actions[0].get("concept_action") == "created", actions
    for key in ("checked", "state", "same_as", "reason"):
        assert key in actions[0], actions[0]


# ============================================================ e：反真空
#
# 把"判词 ⇒ 处置"这一层摘掉（唯一折算点打桩成恒 created = 改前的形态：闸判它的，
# 各入口照旧新建），两个入口的同义判据必须当场红 —— 证明 a1 / a4 的绿是"按闸的结论
# 处置"给的，而不是别的什么顺手拦住了第二笔。


def test_e_removing_the_disposition_turns_the_synonym_checks_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e（反真空）：折算点恒 created ⇒ 入口 1 / 入口 4 都落第二行（= 改前形态）。"""
    def _always_created(gate):
        got = dict(gate or {})
        return {"concept_action": "created", "checked": True,
                "state": str(got.get("state") or "different"),
                "basis": str(got.get("basis") or ""), "same_as": "",
                "candidates": [str(x) for x in (got.get("candidates") or [])],
                "reason": str(got.get("reason") or "")}

    monkeypatch.setattr(SEC, "concept_identity_action", _always_created)

    # ---- 入口 1：`CR.upsert`（a1 的场景）
    st = _ws(tmp_path)
    CR.upsert(st, label=REAL_LABEL, definition=REAL_DEF_1)
    second = CR.upsert(st, label=ALT_LABEL, definition=REAL_DEF_2)
    assert second.get("concept_action") == "created", second
    assert len(_rows(st)) == 2, [r.get("label") for r in _rows(st)]
    assert _counter(st) == 2, _counter(st)

    # ---- 入口 4：`run_once.resolve_concept`（a4 的场景）
    st2 = _ws(tmp_path / "run_once")
    CR.upsert(st2, label=REAL_LABEL, definition=REAL_DEF_1)
    _one_paper(st2)
    out = _agent_b(st2, [{"name": ALT_LABEL, "definition": REAL_DEF_2}]).run_once().to_dict()
    assert int(out.get("concepts_created") or 0) == 1, out
    assert len(_concept_rows(st2)) == 2, [r.get("label") for r in _concept_rows(st2)]

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

# -*- coding: utf-8 -*-
"""① 概念 + 证明手稿 ⇒ 写盘前受控拒、零新行（审计 §6-① 的"半笔"）。

## 改前读数（`temp/_fix_concept_probe_before.json` 的 `1_concept_manuscript`）

同一笔 `B.register_statement(kind="concept", proof_manuscript="reports/f-proof-000000.md")`：

```
ok=false / kind=proof_without_v_sign / refusal_reason=invalid_params
statements_rows_after = 1        ← 行已经落在盘上
row.proof_text = ""              ← 稿里那段正文一个字都没进台账
```

成因（两处口径打架）：

1. 概念口径块先把 `proof_text` 丢掉（`register_statement.py` 概念分支）；
2. 约 330 行之后"调用方没给正文、而有稿"那一支把稿里的 `## 证明` 取成正文，
   那一支不看 kind；
3. 于是 `carries_write=True` → "没有签不许换 canonical 正文"那道闸整笔拒 ——
   而概念行早在更早那次秘书事务里落了盘。

调用方拿到 `ok=false` 会照"没写成"处理（重试 / 扫盘 / 重交），而盘上多了一行
`active` 概念 —— 正是本仓反复点名的"静默半笔"。

## 改后口径（2026-11-10 业主裁定 甲，本条判据随之改口径）

概念行不收未签的证明稿 ⇒ 在接受这一笔之前就受控拒（`concept_takes_no_proof_manuscript`）
只挡未签的那一档，零新行、零新文件；拒信说清两件事：① 要登记"命题的证明"该走
`kind="conjecture"` ＋ `proof_manuscript`；② 要登记"概念的良定义证明" ⇒ 先
`own.land_manuscript` 落 `reports/b-proof-<号>.md`、派 V 三转签、再用
`own.ingest_manuscript(apply, cells=["proof_text"])` 按位置与格收录（已签的稿不走本动作）。

（改前这一条是"概念一概不收稿、良定义证明今天没有落点"；那正是 2026-11-10 裁定要
替换的口径 —— 判据的绿不再靠"把概念登记整体挡掉"，而是靠"未签 ⇒ 零写、已签 ⇒ 走收录"。）

## 四条判据（含两条反真空）

| 条 | 它钉什么 | 改前红在哪 |
|---|---|---|
| a | 概念 + 稿（路径写法）⇒ 受控拒、`statements` 零行、盘上零新文件，拒信含"概念不收证明稿"与两条改法 | 改前 `ok=false` 但盘上多 1 行 |
| b | 概念 + 稿（正文写法，不走路径解析）⇒ 同样零行（判据只看"给没给"，不看形态） | 同上 |
| c | 正控：不带稿的概念照常落盘（这一条拒不许溢出到正常登记） | 改后不许把概念登记整体挡掉 |
| d | 反真空：把判据打桩成"概念收稿"（= 改前那一版）⇒ a 的尺子当场红，且红出来的读数正是"`ok=false` 而盘上 1 行" | 证明 a 的绿是这条判据带来的 |
| e | 第二读点（在册概念 + 盘上那份稿）：概念行也不许从稿里取正文 —— 打桩之后不红，不打桩时 `proof_text` 仍是空串且 `ok` 不是 `proof_without_v_sign` | 改前那一支不看 kind ⇒ 又取正文 |

零真实模型调用：`extractor=None`、`extract_text=extract_text`（只读函数），
工作区全在 `tmp_path`，不读写 `projects/`。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import depsection as DS
from agentflow.agent_b import AgentB
from agentflow.extract import extract_text
from agentflow.store import Store

from conftest import add_literature, write_library_file

PAPER = ("For convenience, a set of vertices K will be said to be a red interconnected "
         "set if all segments joining pairs of vertices in K are colored red.")

#: 真机 r34d 那条 concept payload（与 `test_agent_b_concept_registration_carries_kind.py`
#: 逐字同源），这里只把 label 换短，方便读数。
CONCEPT = {
    "kind": "concept",
    "label": "红色互连集（red interconnected set）",
    "origin": "external_lit",
    "source_lit_id": "000000",
    "page_range": {"start": 1, "end": 1},
    "quote_mode": "verbatim",
    "quote_verified": True,
    "statement_full": (
        "定义（红色互连集，red interconnected set）。给定顶点集 V，把完全图的每条边恰好"
        "染成红、蓝两色之一：若顶点子集 K 中任意两点之间的线段全部为红色，则称 K 为"
        "红色互连集。"),
    "statement_text": "a set of vertices K is a red interconnected set if all segments "
                      "joining pairs of vertices in K are colored red.",
}

#: 概念的"良定义性证明"（业主 2026-10-09 那句「proof 里就证这个概念为什么是良定义的」）。
WELLDEF = ("良定义性证明：\n"
           "1. 定义里的量词范围是整个顶点集 V，而 V 非空。\n"
           "2. 判定只依赖边的染色，染色给定后 K 的红色性唯一确定 ⇒ 定义是良定义的。")

REL = "reports/f-proof-000000.md"


# ---------------------------------------------------------------- 夹具


def _prepared(store: Store) -> Store:
    write_library_file(store, "000000/a.txt", PAPER + "\n")
    add_literature(store, "000000", title="Combinatorial Relations and Chromatic Graphs",
                   path="000000/a.txt")
    return store


def _b(store: Store) -> AgentB:
    return AgentB(store, extractor=None, extract_text=extract_text,
                  config={"lease_seconds": 900, "max_attempts": 3})


def _rows(store: Store) -> list[dict]:
    return [dict(r) for r in store.rows("statements")]


def _files(store: Store) -> list[str]:
    """工作区里所有文件的相对路径（"零新文件"按整棵树数，不只数 `reports/`）。"""
    root = pathlib.Path(store.root)
    return sorted(str(p.relative_to(root)).replace("\\", "/")
                  for p in root.rglob("*") if p.is_file())


def _write_manuscript(store: Store, rel: str = REL) -> str:
    path = pathlib.Path(store.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# 证明手稿（判据夹具）\n\n- 命题号：stmt:000000\n- 证明号：1\n"
        "- 依赖面洗稿：已洗=true；执行者=secretary:F\n\n"
        "## 命题\n\n红色互连集的定义是良定义的。\n\n"
        f"## 证明\n\n{WELLDEF}\n\n" + DS.render_dependency_section([]),
        encoding="utf-8")
    return rel


# ---------------------------------------------------------------- 尺子


def _assert_refused_before_any_write(store: Store, got: dict, *,
                                     before_files: list[str]) -> None:
    """a/b 的尺子：受控拒 + 零新行 + 零新文件 + 拒信说清"怎么办"。

    四件缺一不可：

    ① `ok=False` 且 `kind` 是本笔的受控码（不是撞上无签闸那个 `proof_without_v_sign`
       —— 那个码说的是"正文要换、没签"，而这一笔根本不该走到正文那一层）；
    ② `statements` 零行：改前这一格是 1（audit §6-① 的半笔）；
    ③ 盘上零新文件：拒掉的登记不许留稿 / 留台账行（半笔的另一半是"盘上有东西"）；
    ④ 拒信要能让人改：点名"概念不收证明稿"，并给出两条改法（命题的证明走
       `kind="conjecture"` + `proof_manuscript`；概念的良定义证明今天没有落点）。
    """
    assert got.get("ok") is False, f"概念 + 证明稿必须受控拒：{got}"
    assert str(got.get("kind") or "") == "concept_takes_no_proof_manuscript", got
    assert str(got.get("refusal_reason") or "") == "invalid_params", got
    assert len(_rows(store)) == 0, (
        f"被拒的那一笔在盘上留下行：{[r.get('stmt_id') for r in _rows(store)]}")
    assert _files(store) == before_files, (
        f"被拒的那一笔在盘上留下文件：{[p for p in _files(store) if p not in before_files]}")
    error = str(got.get("error") or "")
    assert "概念行不收" in error and "未签" in error, (
        f"拒信没说清概念只收已签的稿：{error}")
    # 改法①：命题的证明走 conjecture + proof_manuscript
    assert "conjecture" in error and "proof_manuscript" in error, (
        f"拒信没给出「要登记命题的证明该走哪」：{error}")
    # 改法②：概念的良定义证明走 land → V 签 → ingest（2026-11-10 业主裁定 甲）
    assert "良定义" in error and "ingest_manuscript" in error, (
        f"拒信没说出「概念的良定义证明该走哪」：{error}")
    assert got.get("stmt_id") in (None, ""), got


# ================================================================ a 路径写法


def test_a_concept_with_a_manuscript_path_is_refused_before_any_write(store: Store) -> None:
    """a：概念 + `proof_manuscript=<路径>` ⇒ 受控拒、零新行、零新文件。

    改前读数（audit §6-①，本次复跑同）：`ok=false / kind=proof_without_v_sign`，
    而 `statements` 从 0 行变 1 行、`row.proof_text` 仍是空串 —— "行落了、正文没落"。
    """
    _prepared(store)
    _write_manuscript(store)
    before = _files(store)

    got = _b(store).register_statement(**dict(CONCEPT, proof_manuscript=REL))

    _assert_refused_before_any_write(store, got, before_files=before)
    # 反真空的读数面：拒的不是无签闸那一档（改前就是它，而它是"先写后拒"的形态）。
    assert str(got.get("kind") or "") != "proof_without_v_sign", got


# ================================================================ b 正文写法


def test_b_a_concept_with_manuscript_text_is_refused_too(store: Store) -> None:
    """b：同一格收"正文"写法（这一格历史上是两个意思）⇒ 同样零行。

    判据只看"给没给"，不解析形态：路径与正文都会让"稿里的 `## 证明`"有机会被取成
    概念行的正文 —— 两种写法都必须挡在接受这一笔之前。
    """
    _prepared(store)
    before = _files(store)

    got = _b(store).register_statement(**dict(CONCEPT, proof_manuscript=WELLDEF))

    _assert_refused_before_any_write(store, got, before_files=before)


# ================================================================ c 正控：不带稿照常落


def test_c_a_concept_without_a_manuscript_still_lands(store: Store) -> None:
    """c：这一条拒不许溢出 —— 不带稿的概念登记照常落盘（`ok=True`、1 行、正文空）。

    "把概念登记整体挡掉"也能让 a/b 变绿（两条都是"零行"），所以这一条与它们成对：
    既不许半笔，也不许不写。
    """
    _prepared(store)
    out = _b(store).register_statement(**CONCEPT)
    assert out.get("ok") is True, out
    (row,) = _rows(store)
    assert str(row.get("kind") or "") == "concept", row
    assert str(row.get("proof_text") or "") == "", row
    assert str(row.get("stmt_id")) == str(out.get("stmt_id")), (row, out)


# ================================================================ d 反真空（写盘前拒 → 先写后拒）


def test_d_negative_control_letting_a_concept_take_the_manuscript_turns_it_red(
        store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """d 反真空：把判据打桩成"概念收稿"（= 改前那一版）⇒ 同一把尺子红。

    "写盘前拒"这个说法只有在「打桩回先写后拒」时变红才算数。打桩的是判据本身
    （`register_statement._concept_refuses_manuscript` 恒 False），不是重写一份夹具：
    于是这一笔走的正是改前那条路 —— 概念行先落盘、随后撞无签闸整笔拒。

    红出来的读数必须是"`ok=false` 而盘上 1 行"，即半笔本身（而不是别的拒绝）。
    """
    import agentflow.agent_b.register_statement as RS

    _prepared(store)
    _write_manuscript(store)
    before = _files(store)
    monkeypatch.setattr(RS, "_concept_refuses_manuscript", lambda **_: False)

    got = _b(store).register_statement(**dict(CONCEPT, proof_manuscript=REL))

    # 改前的读数：整笔回 ok=false / 无签拒，而盘上多了一行、稿也在。
    assert got.get("ok") is False, got
    assert str(got.get("kind") or "") == "proof_without_v_sign", got
    assert len(_rows(store)) == 1, "打桩之后这一笔没有留下半笔 ⇒ d 证明不了 a 的红"
    with pytest.raises(AssertionError):
        _assert_refused_before_any_write(store, got, before_files=before)


# ================================================================ e 第二读点（在册概念 + 盘上的稿）


def _seed_concept(store: Store) -> dict:
    """先正常登记一条概念（不带稿），返回落盘那一行。"""
    out = _b(store).register_statement(**CONCEPT)
    assert out.get("ok") is True, out
    return dict(next(r for r in _rows(store) if str(r["stmt_id"]) == str(out["stmt_id"])))


def test_e_a_registered_concept_never_takes_the_proof_body_from_the_manuscript(
        store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """e：在册概念 + 盘上恰好有一份它的稿 ⇒ 那一支也不许把 `## 证明` 取成正文。

    第二读点（"稿里 `## 证明` 要不要取成正文"那一支）改前不看 kind：节点已在册、
    盘上有 `reports/f-proof-<本行号>.md` 时，那一支会取正文 ⇒ `carries_write` 为真 ⇒
    又撞无签闸。这一条把两支钉在同一个判据上：打桩（概念收稿）之后，同一笔会走回
    取正文那条路；不打桩时它一个字都不取（`proof_text` 仍是空串）。

    为什么这样测"取没取正文"：概念行的 `proof_text` 只有一个合法值（空串），所以
    "取到了"的唯一可观察形态就是它变成非空 / 整笔回 `proof_without_v_sign`。
    """
    _prepared(store)
    seeded = _seed_concept(store)
    _write_manuscript(store)          # 稿头写的正是这一行的号

    # 不打桩：同一笔重交（不带 proof_manuscript）⇒ 不许从稿里取正文。
    # （这一笔在秘书查重那一层回 `duplicate_statement` —— 那不是判据要看的东西；
    #  要看的是"它有没有走成 `proof_without_v_sign`"，即那一支有没有取到正文。）
    again = _b(store).register_statement(**CONCEPT)
    assert str(again.get("kind") or "") != "proof_without_v_sign", again
    row = dict(next(r for r in _rows(store) if str(r["stmt_id"]) == str(seeded["stmt_id"])))
    assert str(row.get("proof_text") or "") == "", row

    # 打桩（= 改前）：同一支会把稿里的 `## 证明` 取成正文 ⇒ 撞无签闸。
    import agentflow.agent_b.register_statement as RS

    monkeypatch.setattr(RS, "_concept_refuses_manuscript", lambda **_: False)
    third = _b(store).register_statement(**CONCEPT)
    assert str(third.get("kind") or "") == "proof_without_v_sign", third

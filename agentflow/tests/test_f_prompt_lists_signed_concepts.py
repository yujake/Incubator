# -*- coding: utf-8 -*-
"""④ F 的读数面必须列出已签概念（可读不可引），未签的只报条数（2026-11-11）。

## 缺陷现场（`temp/_final_chain`，概念 `000001` 已 V 签 + `reviewed=true`）

改前 `citable_statements()` 的读数只有一条命题 + 一句条数：

```
stmt:000000（kind=theorem，label=DCT，grade=pre_theorem）
（另有 1 条概念（`kind=concept`，不参与可引等级：概念没有等级轴，不是“档位不够”））
```

F 看得到"有 1 条概念"，看不到是哪一条（没有 id、没有 label、没有正文）——
签过的概念在 F 眼里不可见。成因在 `agent_f/manuscript.py::citable_statements`：
概念一律只进 `concepts += 1` 那一格，`reviewed` 这一位从头到尾没被读过。

## 改后口径

`_non_citable_bucket` 的三档不变；`BUCKET_CONCEPT` 那一档再按 `reviewed` 分开：

- 已签（`reviewed=true`）⇒ 逐条列进提示词行：`stmt:<号>` + `kind=concept` + label +
  一句正文（`statement_text` 优先，截断沿用 `STATEMENT_ITEM_CHARS`），并写明
  「可读但不可引：可引门只放命题」（概念没有等级轴，不是"档位不够"）；
- 未签（`reviewed=false`）⇒ 仍只报条数，并明说"未签 / 只报条数 / 不列正文"。

概念不进 `ids`：可引清单与可读面是两张表（进了 `ids` 就等于告诉模型它可以引）。
计数口径不变：可引命题与已签概念各自受 `CITABLE_STATEMENTS` 上限约束，超出的那一句
必须带"还有 N 条没列"。

## 四条判据（含反真空）

| 条 | 它钉什么 | 改前红在哪 |
|---|---|---|
| a | 已签 concept + 已签 theorem ⇒ 两条都在读数里，概念的 id/label/正文都读得到，且"不可引但可读"那句在 | 概念只有一句条数，id/label/正文都读不到 |
| b | 未签 concept ⇒ 不列 id（只给条数），读数里不出现它的正文 | —（改前两侧都只给条数；这条钉住"别顺手把未签的也列出来"） |
| c | 已签概念多于上限 ⇒ "还有 N 条已签概念没列"；可引那一侧的上限与截断同时仍成立 | —（改前没有概念清单，这一句不存在） |
| d | 反真空：把"列概念"改回"只给条数"（`_signed_row` 打桩成恒 False）⇒ a 红 | 证明 a 的绿是这一条分流带来的 |

另 e 钉住正文截断沿用 `STATEMENT_ITEM_CHARS`（不另立第二个体量常数）。

零真实模型调用：只调 `citable_statements()`（纯读）；工作区全在 `tmp_path`。
"""
from __future__ import annotations

import pytest

from agentflow import conceptrows as CR
from agentflow import evidencebits as EB
from agentflow.agent_f import AgentF
from agentflow.agent_f import manuscript as MF

from conftest import seed_statement_row

CONCEPT_LABEL = "矩阵的谱"
CONCEPT_BODY = ("矩阵的谱：设 A 是 n×n 复矩阵，spec(A) = {λ ∈ C : "
                "det(λI − A) = 0}。")
THEOREM_LABEL = "控制收敛定理"
THEOREM_BODY = ("设 (X,Σ,μ) 为测度空间，f_n、f 可测且 f_n→f μ-a.e.；若存在可积 g 使 "
                "|f_n|≤g a.e.，则 ∫f_n dμ → ∫f dμ。")


def _signed_bits_for(body: str) -> dict:
    """一条"真签过"的概念位：走 `conceptrows.concept_bits`（与生产写入侧同一条路）。

    `reviewed` 只在 `sign={"state": "signed"}` 时翻真 —— 这里给的就是这个状态，
    所以这条夹具的 `reviewed=true` 不是手写的布尔，而是那一笔签的读数。
    """
    return CR.concept_bits(
        origin="own_result", proof_text=body,
        sign={"state": "signed", "proof_no": 1,
              "credential": {"verification_id": "v-000001",
                             "path": "verifications/pending/fake.jsonl#v-000001"}})


def _theorem_bits() -> dict:
    """一条"已签命题"的位（第 2+3 位为真 ⇒ 等级 `pre_theorem`）。"""
    return EB.bits_of(origin="own_result", proof=True, proof_process=THEOREM_BODY,
                      reviewed=True, reviewed_by={"by": "agent-V"}, kind="theorem")


def _seed_concept(store, *, signed: bool, sid: str = "000001", body: str = CONCEPT_BODY,
                  label: str = CONCEPT_LABEL) -> str:
    row = seed_statement_row(
        store, stmt_id=sid, kind="concept", label=label,
        statement_text=body, statement_full=body,
        proof_text=(body if signed else ""),
        bits=(_signed_bits_for(body) if signed else {}))
    return str(row["stmt_id"])


def _seed_theorem(store, *, sid: str = "000000") -> str:
    row = seed_statement_row(
        store, stmt_id=sid, kind="theorem", label=THEOREM_LABEL,
        statement_text=THEOREM_BODY, statement_full=THEOREM_BODY,
        proof_text=THEOREM_BODY, bits=_theorem_bits())
    return str(row["stmt_id"])


def _read(store) -> tuple[list[str], list[str], str]:
    f = AgentF(store, config={}, e=None, actor="agent-F")
    return f.citable_statements()


# ---------------------------------------------------------------- 尺子


def _concept_line(lines: list[str], sid: str) -> str:
    hits = [line for line in lines if f"stmt:{sid}" in line and "kind=concept" in line]
    assert len(hits) == 1, (
        f"读数里没有（或有不止一条）概念 {sid} 的行 ⇒ 已签概念没有逐条列出来：{lines}")
    return hits[0]


def _assert_signed_concept_is_readable(lines: list[str], note: str, *, sid: str,
                                       label: str, body: str) -> None:
    """a 的尺子：号 + `kind=concept` + label + 正文 + "可读但不可引" 五件齐。

    正文按 `STATEMENT_ITEM_CHARS` 截断，所以这里只对没到上限的短正文要求原文完整；
    "不可引但可读"那句必须逐字在 —— 只说"概念"或只说"不可引"都不够：
    读的人得知道"能读"与"不能引"是同时成立的，而不是"这一条还没够格"。
    """
    line = _concept_line(lines, sid)
    assert label in line, f"概念行没有 label：{line!r}"
    assert body in line, f"概念行没有正文：{line!r}"
    assert "可读" in line and "不可引" in line, (
        f"概念行没有说清「可读但不可引」：{line!r}")
    assert "可引门只放命题" in line, (
        f"概念行没有说清不可引的判据（可引门只放命题）：{line!r}")
    assert "档位不够" not in line, (
        f"概念被说成了「档位不够」—— 概念没有等级轴：{line!r}")


# ================================================================ a 正控


def test_a_a_signed_concept_and_a_signed_theorem_are_both_listed(store) -> None:
    """a：已签 concept + 已签 theorem ⇒ 两条都在读数里，概念四件都读得到。"""
    tid = _seed_theorem(store)
    cid = _seed_concept(store, signed=True)

    lines, ids, note = _read(store)

    theorem_line = next((line for line in lines if f"stmt:{tid}" in line), "")
    assert theorem_line, f"已签命题没有列出来：{lines}"
    assert "kind=theorem" in theorem_line, theorem_line
    _assert_signed_concept_is_readable(lines, note, sid=cid, label=CONCEPT_LABEL,
                                       body=CONCEPT_BODY)
    # 概念可读但不可引：它不进可引 id（进了就等于告诉模型"这条能引"）
    assert ids == [f"stmt:{tid}"], (ids, lines)
    assert all(f"stmt:{cid}" not in i for i in ids), ids


# ================================================================ b 未签只报条数


def test_b_an_unsigned_concept_is_only_counted_and_its_body_stays_out(store) -> None:
    """b：未签 concept ⇒ 不列 id（只给条数），读数里不出现它的正文。"""
    tid = _seed_theorem(store)
    cid = _seed_concept(store, signed=False)

    lines, ids, note = _read(store)
    reading = "\n".join([*lines, note])

    assert f"stmt:{cid}" not in reading, (
        f"未签概念被列进可读面了（没签的正文不该混进去）：{reading!r}")
    assert CONCEPT_BODY not in reading, (
        f"未签概念的正文出现在读数里了：{reading!r}")
    # 但也不许静默消失：条数 + "未签" 必须可见
    assert "另有 1 条概念" in note, note
    assert "未签" in note, note
    assert "reviewed=false" in note, note
    assert "不列 id 也不列正文" in note, note
    assert ids == [f"stmt:{tid}"], (ids, lines)


# ================================================================ c 上限与截断


def test_c_more_concepts_than_the_cap_says_how_many_are_missing(
        store, monkeypatch: pytest.MonkeyPatch) -> None:
    """c：已签概念多于上限 ⇒ "还有 N 条已签概念没列"；可引那一侧的截断同时仍成立。"""
    monkeypatch.setattr(MF._Manuscript, "CITABLE_STATEMENTS", 2)
    cids = [_seed_concept(store, signed=True, sid=f"00001{i}") for i in range(3)]
    tids = [_seed_theorem(store, sid=f"00002{i}") for i in range(3)]

    lines, ids, note = _read(store)

    listed_concepts = [line for line in lines if "kind=concept" in line]
    assert len(listed_concepts) == 2, (
        f"概念清单没有被上限截到 2 条（要不就是漏了，要不就是多给了）：{lines}")
    assert f"stmt:{cids[0]}" in "\n".join(listed_concepts), listed_concepts
    assert f"stmt:{cids[1]}" in "\n".join(listed_concepts), listed_concepts
    assert all(f"stmt:{cids[2]}" not in line for line in listed_concepts), listed_concepts
    assert "还有 1 条已签概念没列" in note, note
    # 可引命题那一侧的上限与截断没有因为这一改而放宽
    assert len(ids) == 2, (ids, note)
    assert "还有 1 条够格但没列" in note, note
    assert "只列前 2 条" in note, note


# ================================================================ d 反真空


def test_d_negative_control_counting_only_turns_a_red(
        store, monkeypatch: pytest.MonkeyPatch) -> None:
    """d 反真空：`_signed_row` 恒 False（= 改前"只给条数"）⇒ a 的尺子当场红。"""
    tid = _seed_theorem(store)
    cid = _seed_concept(store, signed=True)

    lines, ids, note = _read(store)
    # 先把正控跑绿，证明同一份工作区上 a 本来成立
    _assert_signed_concept_is_readable(lines, note, sid=cid, label=CONCEPT_LABEL,
                                       body=CONCEPT_BODY)

    monkeypatch.setattr(MF, "_signed_row", lambda row: False)
    lines, ids, note = _read(store)
    reading = "\n".join([*lines, note])

    # 改前形态：概念只剩条数，id 与正文都读不到
    assert f"stmt:{cid}" not in reading, (
        f"打桩之后概念仍被列出来 ⇒ d 证明不了 a 的红：{reading!r}")
    assert CONCEPT_BODY not in reading, reading
    assert "另有 1 条概念" in note, note
    with pytest.raises(AssertionError):
        _assert_signed_concept_is_readable(lines, note, sid=cid, label=CONCEPT_LABEL,
                                           body=CONCEPT_BODY)
    # 命题那一侧不受影响（打掉的只是"概念是否列出来"这一个判据）
    assert ids == [f"stmt:{tid}"], (ids, lines)


# ================================================================ e 截断沿用同一宽度


def test_e_a_long_concept_body_is_truncated_to_the_statement_item_width(store) -> None:
    """e：概念正文的截断沿用 `STATEMENT_ITEM_CHARS`（不另立第二个体量常数）。"""
    long_body = "矩阵的谱：" + "定义正文" * 200
    cid = _seed_concept(store, signed=True, body=long_body)

    lines, _ids, _note = _read(store)
    line = _concept_line(lines, cid)

    assert line.startswith(f"stmt:{cid}（kind=concept，"), line
    assert len(line) <= MF._Manuscript.STATEMENT_ITEM_CHARS, (
        f"概念行长度 {len(line)} 超过 STATEMENT_ITEM_CHARS="
        f"{MF._Manuscript.STATEMENT_ITEM_CHARS}：{line!r}")
    assert line.endswith("…"), f"截断了却没写截断标记：{line!r}"

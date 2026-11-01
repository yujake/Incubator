# -*- coding: utf-8 -*-
"""判据：B 的 `register_statement` 说明面要把 `proof_authors` 与 `kind` 说清楚。

## 现场（真机 82，2026-11-01 · C-2 / A-1）

- 20:53:31 的 `t-000098` 派活文字逐字教 B 传 `proof_authors=["F"]`，而这一格
  「不在参数表里」 ⇒ `param_invalid`；B 去掉它再交才成功，而 `proof_authors` 由
  `proofauthors.py` 按来源路径推断，于是 D 写的两条证明被记成了 `["F"]`。
- `kind` 那一格此前只有类型 `string`、没有说明：派活文字与 B 的实测都写中文
  `引理` / `定理`，而词表是英文的 —— 这一格要么被 `must_start_as_conjecture`
  引到"去要 V 签"（答非所问），要么根本改不动。

## 这一份钉的三条（改前红）

| 条 | 它要证明的事 | 改前为什么红 |
|---|---|---|
| a | 说明面点名 `proof_authors` 是行上附加键（由 `proofauthors.py` 推断，不接受手写） | 改前一个字都没提，派活文字照直教模型传 |
| b | `kind` 的说明写清"英文词表 + 由证据派生、不许手改" | 改前 `kind` 连 description 都没有 |
| c | 反真空：只改说明文字，不把 `proof_authors` 变成可写参数（权限面不动） | 这一条钉"说明面改了、参数面没放宽" |

边界：只读 `specs/b.py` 的声明，不实例化智能体、不联网。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow.specs.b import SPEC

_SPEC = next(a for a in SPEC.actions if a.action == "register_statement")
_PROPS = _SPEC.params["properties"]


def _kind_text() -> str:
    return str((_PROPS.get("kind") or {}).get("description") or "")


# ============================================ a：proof_authors 的说明


def test_the_summary_says_where_proof_authors_is_written():
    """a：说明面点名 `proof_authors` 由谁写、为什么不接受手写。

    改前红：说明面没有 `proof_authors` 这个词 —— 派活文字只能照自己的理解教模型传。
    """
    summary = str(_SPEC.summary)
    assert "proof_authors" in summary, summary
    assert "proofauthors.py" in summary, summary
    assert "推断" in summary or "证据" in summary, summary
    assert "不接受手写" in summary or "不是本动作的参数" in summary, summary


# ============================================ b：kind 的说明


def test_the_kind_description_names_the_english_vocabulary_and_the_evidence_rule():
    """b：`kind` 说明写清"英文词表 + 由证据派生、不许手改"。

    改前红：`kind` 的 schema 只有 `{"type": "string"}`，没有 description。
    """
    text = _kind_text()
    assert text, "kind 没有 description"
    assert "英文" in text, text
    assert "证据" in text and ("派生" in text or "跟着" in text), text
    assert "不许手改" in text or "不要手改" in text or "中文" in text, text


# ============================================ c：反真空（权限面没动）


def test_proof_authors_did_not_become_a_writable_parameter():
    """c：`proof_authors` 不在 `properties` 里 —— 说明文字改了，参数面没放宽。

    这一条是这次改动的边界：把 `proof_authors` 变成可写参数是改权限面
    （谁能写`statements`的哪一格），要人批；本次只改文案。
    """
    assert "proof_authors" not in _PROPS, sorted(_PROPS)

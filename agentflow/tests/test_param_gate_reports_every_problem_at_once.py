# -*- coding: utf-8 -*-
"""判据：参数门一次把全部非法/缺失参数列出来（各一行），并说清怎么改。

## 现场（真机 82，2026-11-01 · C-3 / D-2 / C-1 / C-2）

`tools/base.validate_params` 是 first-error：先报一个缺必填、再报一个未声明，
模型改一个再撞一个。C-3 那一笔（缺 `path`、多给 `note`）实际要两次往返；
C-1/C-2 两次撞"出现未声明的参数"，拒信只给"允许的 19 格"，
不说 `bits` 是派生列（由秘书现算）、也不说 `proof_authors` 由框架按来源推断
—— 于是模型照直再猜一次。

## 这一份钉的四条（改前红）

| 条 | 它要证明的事 | 改前为什么红 |
|---|---|---|
| a | 缺必填 + 未声明一次报全，各占一行、可逐条定位 | 改前 first-error：只报第一件 |
| b | 未声明键里已知的派生列给出可执行的去路（`bits` / `proof_authors` / `created_by`） | 改前只有"s schema 只允许 [...]" |
| c | 拼错的键给出最接近的可选键（`quote_reasn` ⇒ `quote_reason`） | 改前没有任何建议 |
| d | 走注册表时仍是 `kind=param_error` 的受控拒绝（不是 `unexpected`） | 这一条钉"报得全"不许改归因 |

边界：不联网、不落盘；判据只碰 `validate_params` 与一个手搓的注册表。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow.tools.base import ParamError, ToolRegistry, ToolSpec, validate_params

#: `fs.edit` / `table.update` 那一族的形状：一个必填 + 三个可选，封闭参数集。
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"path": {"type": "string"},
                   "old_string": {"type": "string"},
                   "new_string": {"type": "string"},
                   "allow_multiple": {"type": "boolean"}},
    "required": ["path"],
}

#: B 的 `register_statement` 那一族的形状（派生列 `bits` / `proof_authors` 都不在表里）。
SCHEMA_B = {
    "type": "object", "additionalProperties": False,
    "properties": {"statement_full": {"type": "string"},
                   "quote_reason": {"type": "string"}},
    "required": ["statement_full"],
}


def _problems(schema: dict, params: dict) -> str:
    try:
        validate_params(schema, params)
    except ParamError as e:
        return str(e)
    raise AssertionError(f"这些参数居然通过了校验：{params}")


# ============================================ a：一次报全、各一行


def test_missing_and_undeclared_are_both_reported_in_one_message():
    """a：缺 `path` + 未声明的 `note`/`bogus` ⇒ 一条拒信里两件事都在。

    改前红：first-error 只报 `缺少必填参数：path`，两个未声明键要下一次才撞见。
    """
    msg = _problems(SCHEMA, {"old_string": "a", "note": "顺手记一句", "bogus": "x"})
    assert "缺少必填参数：path" in msg, msg
    assert "出现未声明的参数" in msg, msg
    assert "bogus" in msg and "note" in msg, msg
    # 各占一行：读的人能按行逐条改（不是一段糊在一起的散文）。
    lines = [ln for ln in msg.splitlines() if ln.strip()]
    assert len(lines) >= 2, msg
    assert msg.count("缺少必填参数") == 1, msg
    assert msg.count("出现未声明的参数") == 1, msg


# ============================================ b：派生列给可执行的去路


def test_known_derived_keys_say_where_they_should_go_instead():
    """b：`bits` / `proof_authors` 是派生列 ⇒ 拒信说清"谁写它、你该删掉"。

    改前红：只有"s schema 只允许 [...]"，模型只能照着 19 格再猜一次。
    """
    bits_msg = _problems(SCHEMA_B, {"statement_full": "x", "bits": {}})
    assert "bits" in bits_msg, bits_msg
    assert "由秘书" in bits_msg and "quote_reason" in bits_msg, bits_msg
    authors_msg = _problems(SCHEMA_B, {"statement_full": "x", "proof_authors": ["F"]})
    assert "proof_authors" in authors_msg, authors_msg
    assert "推断" in authors_msg and "不接受手写" in authors_msg, authors_msg
    audit_msg = _problems(SCHEMA_B, {"statement_full": "x", "created_by": "agent-B"})
    assert "created_by" in audit_msg and "删掉" in audit_msg, audit_msg


# ============================================ c：拼错的键给最接近的可选键


def test_a_misspelled_key_gets_the_nearest_declared_name():
    """c：`quote_reasn` ⇒ 建议 `quote_reason`。

    改前红：不知道"最接近的是哪一个"，只能自己再猜。
    """
    msg = _problems(SCHEMA_B, {"statement_full": "x", "quote_reasn": "还没核"})
    assert "quote_reasn" in msg, msg
    assert "最接近" in msg and "quote_reason" in msg, msg


# ============================================ d：归因不变


def test_the_registry_still_reports_a_controlled_param_error():
    """d：走注册表仍是 `kind=param_error`（一次报全不许把归因改掉）。"""
    reg = ToolRegistry(name="t")
    reg.bound_role = "A"

    def _handler(path=None, old_string=None, new_string=None, allow_multiple=None):
        return {"ok": True, "path": path}

    reg.register(ToolSpec(name="t.demo", summary="判据用", params=SCHEMA,
                          handler=_handler, roles=("A",)))
    res = reg.call("t.demo", old_string="a", note="x")
    assert res.ok is False, res
    assert str(res.meta.get("kind") or "") == "param_error", res
    text = str(res.error or "")
    assert "缺少必填参数：path" in text and "出现未声明的参数" in text, text

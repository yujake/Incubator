# -*- coding: utf-8 -*-
"""缺陷 ①：D 的「只递指针」不许在工具层被参数门挡住。

## 走查读数（改前红）

`specs/b.py` 的 `statement_full` 带 `minLength: 1`。模型按「只递指针」交
`{"statement_full": "", "proof_manuscript": "reports/f-proof-000000.md"}` 时，
`tools.base.validate_params` 当场回：

    参数错误：statement_full. 长度至少 1

⇒ 合法的指针形态根本到不了动作（走查实测 `statements` rows=0），而实现侧
`_register_pointer_manuscript` 本来就会从手稿 `## 命题` 读命题 —— 工具面与实现相反。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | 工具层按声明的 params 校验 `{"statement_full": "", "proof_manuscript": <路径>}` 通过 | `minLength: 1` 当场拒绝 |
| b | 同一笔经动作入口 ⇒ 收成一行，正文与手稿 `## 命题` / `## 证明` 逐字相同 | 到不了动作 |
| c | 既不给正文也不给手稿 ⇒ 工具层通过、动作层受控拒 `empty_statement_text`，一行都不落 | 判据另一半：①的放开不许把"空正文不能登记"一起放掉 |
| d | 反真空：把 `minLength: 1` 塞回同一份 params ⇒ a 的同一笔当场被拒（拒信逐字 `长度至少 1`） | 证明 a 的绿真的来自这句话被拿掉 |

全部用例在 `tmp_path` 里自建工作区；签是 `conftest.sign_before_registration` 落的真
pending 台账 ⇒ 零模型调用。
"""
from __future__ import annotations

import copy
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import b_form_gate_ok, sign_before_registration  # noqa: E402
from agentflow import depsection as DS  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.specs import b as SPEC_B  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools.base import ParamError, validate_params  # noqa: E402

MANUSCRIPT = "reports/f-proof-000000.md"
PROPOSITION = "对任意有限群 G，若 |G| = p^a·m 且 p∤m，则 G 有 p 阶元。"
PROOF = ("1. 取 G 的一个 Sylow p-子群 P（二阶 Sylow 定理）。\n"
         "2. |P| = p^a > 1 ⇒ 取 1 ≠ x ∈ P，由拉格朗日定理 ord(x) 是 p 的幂。\n"
         "3. 结论：x 的某个幂就是 p 阶元。")


def _params() -> dict:
    """`own.register_statement` 在工具层用的 params（动作声明的同一份对象）。"""
    for spec in SPEC_B.ACTIONS:
        if spec.action == "register_statement":
            return copy.deepcopy(dict(spec.params))
    raise AssertionError("specs/b.py 的动作表里没有 register_statement")


def _workspace(tmp_path: pathlib.Path) -> dict:
    st = Store(tmp_path / "ws")
    st.init()
    deps = DS.render_dependency_section([])
    text = (
        "# F 的证明手稿：p 阶元\n\n"
        "- 依赖面洗稿：已洗=true；执行者=secretary:F\n\n"
        f"## 命题\n\n{PROPOSITION}\n\n"
        f"## 证明\n\n{PROOF}\n\n" + deps)
    target = pathlib.Path(st.root) / MANUSCRIPT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    sign_before_registration(st.root, proof_text=PROOF)
    return {"store": st,
            "b": b_form_gate_ok(AgentB(st, extractor=None, extract_text=None,
                                       config={}))}


def _rows(env: dict) -> list[dict]:
    return [dict(r) for r in env["store"].rows("statements")]


# ===================================================== a 工具层：指针形态通过
def test_a_pointer_only_shape_passes_the_declared_params_gate() -> None:
    """a：同一份声明 params 校验指针形态不报错。"""
    validate_params(_params(), {"statement_full": "",
                                "proof_manuscript": MANUSCRIPT})


# ===================================================== b 动作：收成一行
def test_b_the_pointer_shape_is_registered_as_one_row(
        tmp_path: pathlib.Path) -> None:
    """b：只递指针 ⇒ 收一行；命题 / 证明逐字取自手稿。"""
    env = _workspace(tmp_path)
    got = env["b"].register_statement(statement_full="",
                                      proof_manuscript=MANUSCRIPT)
    assert got.get("ok") is True, got
    rows = _rows(env)
    assert len(rows) == 1, f"应当只落一行，读到 {len(rows)}：{rows}"
    assert rows[0]["statement_full"] == PROPOSITION, rows[0]["statement_full"]
    assert rows[0]["proof_text"] == PROOF, rows[0]["proof_text"]


# ===================================================== c 两道都不给 ⇒ 受控拒
def test_c_no_body_and_no_manuscript_is_still_refused(
        tmp_path: pathlib.Path) -> None:
    """c：空正文 + 空手稿 ⇒ 工具层放行、动作层受控拒，一行都不落。"""
    validate_params(_params(), {"statement_full": ""})
    env = _workspace(tmp_path)
    before = _rows(env)
    got = env["b"].register_statement(statement_full="")
    assert got.get("ok") is False, got
    assert got.get("kind") == "empty_statement_text", got
    assert "empty_statement_text" not in str(got.get("error") or ""), (
        "拒码要落在 kind 上；error 是给人读的那句", got)
    assert _rows(env) == before, "被拒的这一笔居然写了 statements"


# ===================================================== d 反真空：塞回 minLength
def test_d_putting_minlength_back_makes_the_same_call_red() -> None:
    """d：把 `minLength: 1` 塞回去 ⇒ a 的同一笔当场被参数门拒。"""
    params = _params()
    params["properties"]["statement_full"]["minLength"] = 1
    with pytest.raises(ParamError) as failed:
        validate_params(params, {"statement_full": "",
                                 "proof_manuscript": MANUSCRIPT})
    assert "statement_full" in str(failed.value), str(failed.value)
    assert "长度至少 1" in str(failed.value), str(failed.value)


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))

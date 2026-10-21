# -*- coding: utf-8 -*-
"""验证者 V（`draft/39` §3.21）—— 也是 E9 与 E10 的演练。

用户口径（逐字）：

> 关于 D 审 F 我现在认为不妥……我觉得要专门一个验证者和 F 交互，要做成一个 F 就有一个验证者
> 做 I12、I10、I17 并签那个"审过"。

## E9：两份证明

① 带缝的那份（"易证" + 一处无依据的步骤）⇒ V 必须指到那一步、给"有毛病"、不签第 3 位；② 干净的那份 ⇒ V
给"成立"、`signs_bit3` 为真、`bit3_payload()` 让五元位派生出「预备定理级」。

这两份都用脚本化的 V（离线、确定性）—— 测的是"机制：结论怎么落台账、怎么签位、怎么与五元位对齐"，而不是"某个模型判得准不准"（那要真机，见 §6 的真机卡点）。

## E10：冷启动是结构性质

`cold_start_prompt` 的签名里没有 `store` / `conductor` / `registry` / `session_root`任何一项；它只收字符串（命题 + 证明 + 已渲染好的只读读数）。
于是"不给句柄、不给 F 的叙述"由接口保证，而不是靠"约定只读"。
"""
from __future__ import annotations

import inspect
import json
import pathlib

import pytest

from agentflow import schema as S
from agentflow import evidencebits as EB
from agentflow import verifications as VR


# ============================================================ E10：冷启动

def test_e10_the_cold_start_prompt_takes_no_handles():
    """E10：拼提示词的函数只收字符串 —— 没有 store / conductor / registry / session_root。"""
    params = set(inspect.signature(VR.cold_start_prompt).parameters)
    assert not (params & {"store", "conductor", "registry", "session_root", "conductor_tools"}), \
        params


def test_e10_the_prompt_carries_the_object_and_the_bans_only(tmp_path):
    """E10：提示词里有对象（命题 + 证明全文）与硬禁令；没有作者解释、没有工作区路径。"""
    ws = tmp_path / "ws"
    prompt = VR.cold_start_prompt(
        "设 G 是有限群；则 c(G) ≤ 1。",
        "1. 由定义直接得到。\n2. 由第 1 步与引理 3 得到结论。",
        readonly_facts="- stmt:0007 现状：强猜想（第 2 位空）")
    assert "c(G) ≤ 1" in prompt and "由第 1 步与引理 3" in prompt, prompt
    assert "易证" in prompt and "无依据的步骤" in prompt, prompt
    assert "stmt:0007" in prompt, prompt
    assert str(ws) not in prompt, "提示词里不许出现工作区路径（那等于给了一条读写面的线索）"
    # 作者的解释（F 的叙述）不在接口里：这一层的输入只有命题/证明/只读读数
    assert "F 说" not in prompt and "作者认为" not in prompt, prompt


# ============================================================ E9①：带缝的证明

_DIRTY = ("1. 显然该族非空（易证）。\n"
          "2. 由第 1 步直接得到 girth = k。\n"
          "3. 故结论成立。\n")
_CLEAN = ("1. 取 G = C_n（n ≥ 3）：它是 2-正则、围长为 n。\n"
          "2. 每条边恰在一个 n-圈里，故不满足「至少两个 k-圈」（引 stmt:0004 的定义）。\n"
          "3. 由第 2 步得到反例，结论不成立。\n")


def test_e9_a_dirty_proof_is_refused_at_the_step_and_not_signed(tmp_path):
    """E9①：带缝的证明 ⇒ `有毛病` + 指到第 1 步 + 不签第 3 位。"""
    root = tmp_path / "ws"
    root.mkdir()
    verdict = VR.parse_verdict(json.dumps({
        "verdict": "有毛病", "defect_step": 1, "quote": "显然该族非空（易证）",
        "why": "第 1 步无条件前提，且用了「易证」这类缝",
        "findings": [{"level": "error", "step": 1, "kind": "缝 + 无条件前提",
                      "detail": "第 1 步写了「显然（易证）」，而族非空需要构造"},
                     {"level": "error", "step": 2, "kind": "无依据的步骤",
                      "detail": "第 2 步没有引到任何在册 id，也没有同段推导"}]},
        ensure_ascii=False))
    # 硬禁令的机械那一半：这两处短语确实在这份证明里（判据可离线复算）
    assert set(VR.banned_markers_in(_DIRTY)) >= {"易证", "显然"}, VR.banned_markers_in(_DIRTY)
    row = VR.record_verification(root, statement_id="0007", proof_text=_DIRTY, verdict=verdict,
                    used_faces=("statements.read",))
    assert row["verdict"] == "有毛病" and row["defect_step"] == 1, row
    assert row["unresolved_errors"] == 2, row
    assert VR.signs_bit3(row) is False, row
    assert VR.bit3_payload(row) == {}, VR.bit3_payload(row)
    # 台账落盘：一行、带证明 sha 与编号
    rows, problems = VR.list_verifications(root, statement_id="0007")
    assert not problems and len(rows) == 1, (rows, problems)
    assert rows[0]["proof_sha256"] == VR.proof_sha(_DIRTY), rows[0]
    assert rows[0]["verification_id"] == f"v-{S.format_id(1)}", rows[0]


def test_e9_a_clean_proof_is_signed_and_moves_the_five_bit_grade(tmp_path):
    """E9②：干净的证明 ⇒ `成立` ⇒ 签第 3 位 ⇒ 五位派生出「预备定理级」。"""
    root = tmp_path / "ws"
    root.mkdir()
    ok = VR.parse_verdict('{"verdict": "成立", "findings": []}')
    row = VR.record_verification(root, statement_id="0007", proof_text=_CLEAN, verdict=ok,
                    used_faces=("statements.read", "experiments.read"))
    assert VR.signs_bit3(row) is True, row
    payload = VR.bit3_payload(row)
    assert payload["reviewed"] is True, payload
    assert payload["reviewed_by"]["verification_id"] == f"v-{S.format_id(1)}", payload
    assert payload["reviewed_by"]["evidence"].endswith(f"0007.jsonl#v-{S.format_id(1)}"), payload

    # 与五元位接起来：有证明过程（第 2 位）+ 这一签（第 3 位）⇒ 预备定理级
    bits = EB.bits_of(proof=True, proof_process=_CLEAN, **payload)
    assert bits["grade"] == "pre_theorem", bits
    assert EB.bit_problems(bits) == [], EB.bit_problems(bits)
    # 没签的那一份（有毛病）⇒ 五位里第 3 位保持空 ⇒ 仍是猜想
    bad = VR.record_verification(root, statement_id="0008", proof_text=_DIRTY,
                    verdict=VR.parse_verdict(json.dumps(
                        {"verdict": "有毛病", "defect_step": 1,
                         "findings": [{"level": "error", "step": 1, "kind": "缝", "detail": "第 1 步"}]},
                        ensure_ascii=False)))
    unsigned = EB.bits_of(proof=True, proof_process=_DIRTY, **VR.bit3_payload(bad))
    assert unsigned["grade"] == "conjecture", unsigned


# ============================================================ 三态与"没查成"

def test_three_states_are_not_collapsed(tmp_path):
    """三态：`看不出来`（对证明的结论）与"没查成"（输出不合法）不许折平。"""
    root = tmp_path / "ws"
    root.mkdir()
    unclear = VR.record_verification(root, statement_id="0009", proof_text=_DIRTY,
                        verdict=VR.parse_verdict('{"verdict": "看不出来", "why": "信息不足"}'))
    assert unclear["verdict"] == "看不出来" and VR.signs_bit3(unclear) is False, unclear
    assert VR.bit3_payload(unclear) == {}, unclear
    with pytest.raises(VR.VerificationError):
        VR.parse_verdict("我觉得还行")            # 不是 JSON ⇒ 没查成
    with pytest.raises(VR.VerificationError):
        VR.parse_verdict('{"verdict": "有毛病"}')  # 有毛病却没指到步 ⇒ 没查成
    with pytest.raises(VR.VerificationError):
        VR.parse_verdict('{"verdict": "大概成立"}')  # 取值不在词表 ⇒ 没查成


def test_a_wrong_field_in_a_handmade_verdict_is_refused_at_write_time(tmp_path):
    """写入期把关：调用方绕开解析直接构造结论 ⇒ 也在落盘前被挡住（零写入）。"""
    root = tmp_path / "ws"
    root.mkdir()
    with pytest.raises(VR.VerificationError):
        VR.record_verification(root, statement_id="0007", proof_text=_CLEAN,
                  verdict={"verdict": "成立", "findings": [{"level": "critical", "step": 1}]})
    assert VR.list_verifications(root, statement_id="0007")[0] == [], "被拒的那次不许留下行"


def test_the_ledger_is_append_only_and_ids_are_allocated_by_the_script(tmp_path):
    """追加式 + 编号由脚本发：同一命题审三次 ⇒ 三行、`v-000001…v-000003`、不覆盖。"""
    root = tmp_path / "ws"
    root.mkdir()
    ok = VR.parse_verdict('{"verdict": "成立", "findings": []}')
    for i in range(3):
        VR.record_verification(root, statement_id="0007", proof_text=_CLEAN + f"\n（第 {i} 次提交）",
                  verdict=ok, round_no=i + 1)
    rows, problems = VR.list_verifications(root, statement_id="0007")
    assert not problems, problems
    assert [r["verification_id"] for r in rows] == [f"v-{S.format_id(i)}" for i in (1, 2, 3)], rows
    assert [r["round"] for r in rows] == [1, 2, 3], rows
    assert len({r["proof_sha256"] for r in rows}) == 3, "三次提交的证明不同 ⇒ 三份 sha"


def test_a_bad_proposition_id_is_refused():
    """命题号必须是 4 位十进制（与台账 id 同一口径）—— 否则台账会散成一堆自由文件名。"""
    with pytest.raises(VR.VerificationError):
        VR.verification_ledger_path(pathlib.Path("/tmp"), "7")
    with pytest.raises(VR.VerificationError):
        VR.verification_ledger_path(pathlib.Path("/tmp"), "stmt-0007")

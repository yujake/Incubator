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
                    used_faces=("statements.read",), secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
    assert row["verdict"] == "有毛病" and row["defect_step"] == 1, row
    assert row["unresolved_errors"] == 2, row
    assert VR.signs_bit3(row) is False, row
    assert VR.bit3_payload(row) == {}, VR.bit3_payload(row)
    # 台账落盘：一行、带证明 sha 与编号
    rows, problems = VR.list_verifications(root, statement_id="0007")
    assert not problems and len(rows) == 1, (rows, problems)
    assert rows[0]["proof_sha256"] == VR.text_sha(_DIRTY), rows[0]
    assert rows[0]["verification_id"] == f"v-{S.format_id(1)}", rows[0]


def test_e9_a_clean_proof_is_signed_and_moves_the_five_bit_grade(tmp_path):
    """E9②：干净的证明 ⇒ `成立` ⇒ 签第 3 位 ⇒ 五位派生出「预备定理级」。

    2026-10-29（业主「V 签门槛 = 连续 3 次没问题」）之后，签第 3 位要两条轴同时成立：
    行局部资格（`row_signable`）且连续次数够（`streak`）。本用例只看前者 —— 那一签
    来自"直调写入口"的夹具、没有命题台账可数（`store=None`），所以连续次数必须由这一层
    显式递进来：`streak=SIGN_STREAK_NEED`。

    改前断言 → 改后断言（为什么）：
    - `VR.signs_bit3(row) is True` → `VR.signs_bit3(row, streak=3) is True`
      （连续次数成了一道独立的闸；不递 = 不签，见 `test_a5_*`）。
    - 新增反面：同一个 row 不递 streak 必须为 False（否则"多了一个参数"这句话没有判据）。
    """
    root = tmp_path / "ws"
    root.mkdir()
    ok = VR.parse_verdict('{"verdict": "成立", "findings": []}')
    row = VR.record_verification(root, statement_id="0007", proof_text=_CLEAN, verdict=ok,
                    used_faces=("statements.read", "experiments.read"),
                    #: p247：轴只由秘书给；这一条量的是连续闸，故给 clean。
                    secretary_judge={"checked": True, "axis": "clean",
                                     "decision": "没问题", "reason": "夹具：clean"})
    assert VR.signs_bit3(row) is False, "没有连续读数也签了 ⇒ 那道闸没接上"
    assert VR.signs_bit3(row, streak=VR.SIGN_STREAK_NEED) is True, row
    payload = VR.bit3_payload(row, streak=VR.SIGN_STREAK_NEED)
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
                        ensure_ascii=False)), secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
    unsigned = EB.bits_of(proof=True, proof_process=_DIRTY,
                          **VR.bit3_payload(bad, streak=VR.SIGN_STREAK_NEED))
    assert unsigned["grade"] == "conjecture", unsigned


# ============================================================ 两态与"没查成"

def test_the_verdict_is_a_statement_not_a_state(tmp_path):
    """p247：`verdict` 只是陈述 —— 原样落行、不折档；没有秘书轴 ⇒ 不签。

    业主 2026-11-06 第三次收紧逐字：「V 的判词只是陈述」「不做折档」。所以：
    ① 「看不出来」原样留在台账上（不折成成立、也不折成有毛病）；
    ② 这一行没有 `secretary_judge` ⇒ 轴为空 ⇒ 不签第 3 位、不投连续票；
    ③ 真正的"没查成"只剩结构不合法（不是 JSON / 缺 `verdict` 字段）；
       词表外的写法只是一句陈述，不拒、也不折。
    """
    root = tmp_path / "ws"
    root.mkdir()
    unclear = VR.record_verification(root, statement_id="0009", proof_text=_DIRTY,
                        verdict=VR.parse_verdict('{"verdict": "看不出来", "why": "信息不足"}'),
                        secretary_judge={"checked": False, "axis": "", "decision": "",
                                         "reason": "夹具：判词不是两态，秘书没给轴"})
    assert unclear["verdict"] == "看不出来", unclear
    assert VR.read_verdict(unclear) == "看不出来", unclear
    assert VR.secretary_axis(unclear) == "", unclear
    assert VR.signs_bit3(unclear) is False, unclear
    assert VR.bit3_payload(unclear) == {}, unclear
    with pytest.raises(VR.VerificationError):
        VR.parse_verdict("我觉得还行")            # 不是 JSON ⇒ 没查成
    with pytest.raises(VR.VerificationError):
        VR.parse_verdict('{"findings": []}')      # 缺 verdict 字段 ⇒ 没有陈述可读
    loose = VR.parse_verdict('{"verdict": "大概成立"}')
    assert loose["verdict"] == "大概成立", loose
    assert VR.signs_bit3(loose, streak=VR.SIGN_STREAK_NEED) is False, loose


def test_a_wrong_field_in_a_handmade_verdict_is_refused_at_write_time(tmp_path):
    """写入期把关：调用方绕开解析直接构造结论 ⇒ 也在落盘前被挡住（零写入）。"""
    root = tmp_path / "ws"
    root.mkdir()
    with pytest.raises(VR.VerificationError):
        VR.record_verification(root, statement_id="0007", proof_text=_CLEAN,
                  verdict={"verdict": "成立", "findings": [{"level": "critical", "step": 1}]}, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
    assert VR.list_verifications(root, statement_id="0007")[0] == [], "被拒的那次不许留下行"


def test_the_ledger_is_append_only_and_ids_are_allocated_by_the_script(tmp_path):
    """追加式 + 编号由脚本发：同一命题审三次 ⇒ 三行、`v-000001…v-000003`、不覆盖。"""
    root = tmp_path / "ws"
    root.mkdir()
    ok = VR.parse_verdict('{"verdict": "成立", "findings": []}')
    for i in range(3):
        VR.record_verification(root, statement_id="0007", proof_text=_CLEAN + f"\n（第 {i} 次提交）",
                  verdict=ok, round_no=i + 1, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
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

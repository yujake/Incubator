# -*- coding: utf-8 -*-
"""裁定 2：台账那一行「谁登记的成立」—— 绕过秘书登记就是缺陷。

业主原话逐字：

    「2.看究竟谁登记的成立，绕过秘书登记才是缺陷。」

## 这一份守什么

改前存在一条能签住第 3 位的绕过路（现场读数见 `probe_bypass_sign.py`）：

    `record_verification(verdict={"verdict": "成立"})` —— 一次秘书都不问
    ⇒ 写口不写 `secretary_judge` 这一格（条件写入）
    ⇒ 读侧 `historical_axis` 对"没有这一格"的行按 `verdict` 字面给 `clean`
    ⇒ `row_signable` = True、`_hold_run_lengths` 计一票
    ⇒ 三次 ⇒ `consecutive_holds.streak = 3` ⇒ `bit3_payload()["reviewed"] = True`

两半各修一处，这一份各钉一条：

| # | 它守什么 | 反真空 |
|---|---|---|
| a | 甲（写侧）：没给秘书判定 ⇒ 这一格照样落盘，写的是"未判成"（`checked=False` + 理由） | 改回条件写入（`secretary_judge_cell` 返回空）⇒ a 红 |
| b | 乙（读侧）：没有这一格的行（老台账 / 绕过写入口）一律 unjudged，不按字面给轴 | 把按字面给轴的 `ledger_axis` 装回去 ⇒ b 红 |
| c | 正常路（秘书给 `axis=clean` 三转）照旧可签 —— 修这条缺陷不许把甲类改坏 | 修过头（把有轴的行也算 unjudged）⇒ c 红 |
| d | 判决行本身仍是 V 的陈述：`verdict` 一个字都不改（不许改写成「有毛病」） | 写入期改字 ⇒ d 红 |

零真模型调用、零网络、只写 `tmp_path`。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import verifications as VR  # noqa: E402

SID = "000007"
PROOF = "1. 由定义直接得到。\n2. 故结论成立。"
HOLDS = {"verdict": "成立", "findings": []}
CLEAN = {"checked": True, "axis": "clean", "decision": "没问题",
         "reason": "夹具：秘书判 clean"}


def _write(root, *, judge=None):
    """一次写口（不给 `judge` = 调用方没有秘书判定）。"""
    kw = {} if judge is None else {"secretary_judge": judge}
    return VR.record_verification(root, statement_id=SID, proof_text=PROOF,
                                  verdict=dict(HOLDS), proof_no=1, **kw)


# ------------------------------------------------------------------ a（甲：写侧）

def test_a_a_row_written_without_the_secretary_still_carries_the_cell(tmp_path):
    """a：写口无条件写 `secretary_judge` 那一格；没有判定时写"未判成"。

    改前它是条件写入（`if isinstance(secretary_judge, Mapping)`）⇒ 不给就一个字节都不写
    ⇒ 那一行落进读侧的历史兼容支、按 `verdict` 字面拿到 clean。
    """
    row = _write(tmp_path)
    assert VR.SECRETARY_JUDGE_KEY in row, "写口又把这一格省掉了（条件写入回来了）"
    cell = dict(row[VR.SECRETARY_JUDGE_KEY])
    assert cell.get("axis") == "", cell
    assert cell.get("checked") is False, cell
    assert "没有秘书判定" in str(cell.get("reason") or ""), cell


# ------------------------------------------------------------------ b（乙：读侧）

def test_b_a_row_without_the_cell_is_unjudged_not_literal_clean(tmp_path):
    """b：没有那一格的行走 unjudged —— 不按 `verdict` 字面给轴。

    缺的那一截正是"绕过秘书登记成立"的后半：写口不写这一格，读侧按 `成立` 给 clean。
    这里直接造那种行（老台账的形状）—— 手写一行 JSON，没有 `secretary_judge`。
    """
    literal = {"verdict": "成立", "unresolved_errors": 0}
    assert VR.historical_axis(literal) == "", "按字面给轴的回退又回来了"
    assert VR.ledger_axis(literal) == "", literal
    assert VR.row_signable(literal) is False, literal
    reading = VR.axis_reading(literal)
    assert reading["source"] == "none" and reading["axis"] == "", reading
    assert "没有秘书判定" in str(reading["why"]), reading
    # 有那一格、但没判成：另一档（读数要分得开）
    unjudged = {"verdict": "成立", VR.SECRETARY_JUDGE_KEY: dict(VR.NO_SECRETARY_JUDGE)}
    assert VR.axis_reading(unjudged)["source"] == "secretary_unjudged"


def test_b2_three_writes_without_the_secretary_never_sign(tmp_path):
    """b 的第二半：整条现场复刻 —— 三次只写「成立」、一次秘书都不问 ⇒ 签不住。

    这就是修复前能签住的那一段（改前：`streak=3`、`reviewed=True`）。
    """
    rows = [_write(tmp_path) for _ in range(int(VR.SIGN_STREAK_NEED))]
    holds = VR.consecutive_holds(tmp_path, SID)
    assert holds["streak"] == 0, holds
    assert holds["streak_ok"] is False, holds
    assert VR.bit3_payload(rows[-1], streak=holds).get("reviewed") is not True
    assert all(VR.row_signable(r) is False for r in rows)


# ------------------------------------------------------------------ c（甲类不许改坏）

def test_c_three_clean_secretary_rounds_still_sign(tmp_path):
    """c：秘书给 `axis=clean` 的三转 ⇒ 照旧 `成立` + `clean` + 可签发。

    修这条缺陷不许把正常路一起改坏：这一条若红，说明"一律不签"，那不是修，是砸。
    """
    rows = [_write(tmp_path, judge=dict(CLEAN)) for _ in range(int(VR.SIGN_STREAK_NEED))]
    holds = VR.consecutive_holds(tmp_path, SID)
    assert holds["streak"] == int(VR.SIGN_STREAK_NEED), holds
    assert holds["streak_ok"] is True, holds
    last = rows[-1]
    assert VR.read_verdict(last) == "成立", last
    assert VR.secretary_axis(last) == "clean", last
    assert VR.row_signable(last) is True, last
    assert VR.bit3_payload(last, streak=holds).get("reviewed") is True


# ------------------------------------------------------------------ d（判词是陈述）

def test_d_the_written_verdict_is_still_what_v_said(tmp_path):
    """d：`verdict` 字段原样是 V 的陈述 —— 修法不许把「成立」改写成「有毛病」。

    业主的口径是"按轴 / 或未判成"，不是把字面改成另一个字面（那是另一个方向的
    按字面定），所以这一条与 a/b 同时成立：字不变、轴没有。
    """
    row = _write(tmp_path)
    assert row["verdict"] == "成立", row
    assert VR.read_verdict(row) == "成立", row
    ledger = pathlib.Path(tmp_path) / VR.VERIFICATIONS_DIR / f"{SID}.jsonl"
    on_disk = json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
    assert on_disk["verdict"] == "成立", on_disk


# ------------------------------------------------------------------ 反真空

def test_e_putting_the_literal_axis_back_turns_b_red(monkeypatch):
    """反真空（乙）：把"按字面给轴"的 `ledger_axis` 装回去 ⇒ b 的读数必须反过来。"""
    literal = {"verdict": "成立", "unresolved_errors": 0}

    def _old_ledger_axis(row):
        if VR.secretary_axis(row):
            return VR.secretary_axis(row)
        got = str(row.get("verdict") or "")
        return "clean" if got == "成立" else ("fault" if got == "有毛病" else "")

    assert VR.row_signable(literal) is False
    monkeypatch.setattr(VR, "ledger_axis", _old_ledger_axis)
    assert VR.ledger_axis(literal) == "clean"
    # 装回去之后，同一行的"够不够格签"就翻了 ⇒ b 不是空转的。
    assert VR.row_signable(literal) is True


def test_f_the_cell_is_what_makes_the_reading_say_unjudged(tmp_path):
    """反真空（甲）：把"无条件写这一格"改回条件写入 ⇒ 这一行的读数从
    `secretary_unjudged`（问过、没判成）掉成 `none`（连这一格都没有）—— a 红。

    这一条刻意不说"改回甲之后 b 会红"：乙修好之后，没有这一格的行同样不算轴
    （`test_e` 钉的是那一半），所以甲单独的回退只体现在读数是否说得清
    "这一行是问过而没判成，还是根本没问过"。两件事都在 a 里判，混起来说就是假话。
    """
    row = _write(tmp_path)
    assert VR.axis_reading(row)["source"] == "secretary_unjudged"
    stripped = {k: v for k, v in row.items() if k != VR.SECRETARY_JUDGE_KEY}
    assert VR.axis_reading(stripped)["source"] == "none", (
        "去掉这一格读数却没变 ⇒ a 打不中，条件写入回退不会被发现")

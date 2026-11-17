# -*- coding: utf-8 -*-
"""判据：机械会审不按 `need` 复制成多次（ENEED1，业主 2026-11-17 裁定）。

## 业主逐字（本文件的唯一理由）

    「你的理解对了。且由于实验侧的报告不是承重的，真正承重的是程序，所以可以把
      三连审降成一次审（只用改一个数）」
    「与 F 侧同构的只是三连审这个环节」

口径：E 的穷举证据（`reports/e-proof-*.md`）的审阅方式不变 —— 机械七项核对可核
事实（`exhaustionreport.review`），不由模型判数字；与 F 同构的只有「连续过审 →
系统计数 → 落签」这个环节，而这一次「连续」的次数从 3 降成 1
（`verifications.EXHAUSTION_SIGN_STREAK_NEED`）。F / B 仍是
`verifications.SIGN_STREAK_NEED`（3），一个字节都没松。

## 这一份量四条

| # | 造什么 | 期望 |
|---|---|---|
| a | E 的 e-proof 一次机械过审（零模型调用） | 发签：pending 一行、签文件 `count/need = 1/1`、稿上签块 `连续 = 1/1`。改前（need=3）一次过审不发签 ⇒ 这条红 |
| b | F 侧未在册散文稿：三次真模型判定（同一个 `review_call`、`review_pass=1..3`） | 仍要三次才发签 —— 负控：E 的 need=1 不许把 F / B 的门槛带松 |
| c | 一次调用里「重跑 need 遍」／同一份机械判词复制多份／跨送审累计 | 盘上只有一轮（`review_pass=[1]`）；复制多份只算 1 轮；跨送审不累计 —— 三种都不发签 |
| d | 反真空：把 E 这条路的 `need` 改回 3 | a 必红：同一次机械过审不发签、稿上没有签块 |

零真网：a 的机械会审一个模型请求都不发；b 用测试里已有的离线缝。
"""
from __future__ import annotations

import ast
import inspect
import json
import pathlib
import textwrap

import pytest

from agentflow import exhaustionreport as ER
from agentflow import sign_counting as SC
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_v import core as V_CORE

#: a / c / d 的现场（E 跑一趟真穷举 ⇒ e-proof 手稿；V 这一支不问模型）。
from test_e_gets_its_v_sign_like_f import _env, _manuscript, _submitted_by_e
#: b 的现场（未在册散文稿：三次真模型回复的离线缝）。
from test_v_unregistered_manuscript_review import (
    REL,
    _pending_rows as _f_pending_rows,
    _sign_files as _f_sign_files,
    _submitted_by_f,
    _v,
    _ws as _vws,
)
from test_v_reviews_three_times_before_signing import CLEAN_REPLY

#: E 这一档的过审门槛（真身：`verifications.EXHAUSTION_SIGN_STREAK_NEED`）。
E_NEED = int(VR.EXHAUSTION_SIGN_STREAK_NEED)
#: F / B 的门槛（负控：不许被 E 这一改带松）。
STRICT_NEED = int(VR.SIGN_STREAK_NEED)
#: 计数层夹具用的送审 id / 机械判词来路。
CALL = "call-mech-1"
MECH_SOURCE = SC.MECHANICAL_SOURCE


def _sign_files_on_disk(root: pathlib.Path) -> list[pathlib.Path]:
    d = pathlib.Path(root) / "out" / "vsigns"
    if not d.is_dir():
        return []
    return [p for p in sorted(d.glob("*.json")) if p.name != VS.INDEX_NAME]


def _pending_rows(root: pathlib.Path) -> list[dict]:
    base = pathlib.Path(root) / "verifications" / "pending"
    if not base.is_dir():
        return []
    return [json.loads(ln) for p in sorted(base.glob("*.jsonl"))
            for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _block(rel: str, root: pathlib.Path) -> dict:
    text = (pathlib.Path(root) / rel).read_text(encoding="utf-8")
    return VS.manuscript_sign_reading(text, manuscript_path=rel)


def _mech_pass(sha: str, *, pass_no: int = 1, call: str = CALL) -> dict:
    """一行「机械会审」的台账（同一份确定性判词：`source=exhaustion_report`）。"""
    return {
        "verification_id": f"u-{pass_no:06d}", "proof_sha256": sha,
        "review_call": call, "review_pass": pass_no, "verdict": "成立",
        "secretary_judge": {"checked": True, "axis": "clean", "decision": "成立",
                            "reason": "机械七项全过（同一份判词）",
                            "basis": ["exhaustion_report=成立"],
                            "source": MECH_SOURCE, "defect_step": None},
        "proof_chars": 10,
    }


def _real_pass(sha: str, *, pass_no: int = 1, call: str = "call-real") -> dict:
    """一行「真实判定」的台账（轴由 V 秘书给：不是机械会审）。"""
    return {
        "verification_id": f"v-{pass_no:06d}", "proof_sha256": sha,
        "review_call": call, "review_pass": pass_no, "verdict": "成立",
        "secretary_judge": {"checked": True, "axis": "clean",
                            "source": "secretary:v_reply_defect"},
        "proof_chars": 10,
    }


# ============================================================ a：一次机械过审 ⇒ 发签


def test_a_one_mechanical_round_reaches_need_and_the_system_lands_the_sign(tmp_path):
    """a：E 的 e-proof 一次机械过审 ⇒ 达 need(1) ⇒ 系统落签（改前 need=3 ⇒ 一次不发）。

    「一次机械过审」= 同一次送审里机械七项核对只跑一遍（不是同一份判词复制三遍）。
    落签由系统计数（`sign_counting`）；V 只颁发，块由收方秘书落。
    """
    env = _env(tmp_path)
    root = pathlib.Path(env["store"].root)
    rel, _text = _manuscript(env)
    with _submitted_by_e():
        got = env["v"].verify_proof(proof_manuscript=rel)

    assert E_NEED == 1, (
        "E 这一档的过审门槛不是 1 ⇒ 这条判据量的不是业主 2026-11-17 的裁定", E_NEED)
    assert got.get("checked") is True, got
    assert got.get("kind") == "proof_unregistered_signed", got
    assert got.get("verdict") == "成立", got
    # 审阅方式不变：判词来路仍是机械七项会审，不是模型。
    assert str(dict(got.get("secretary_judge") or {}).get("source") or "") == \
        MECH_SOURCE, got
    # 一次送审只判一轮。
    passes = list(got.get("review_passes") or [])
    assert [int(p.get("pass") or 0) for p in passes] == [1], passes
    # 机械七项的读数仍记在判词那一格上（读数是读数，不是「三次」的来源）。
    assert list(dict(got.get("secretary_judge") or {}).get("basis") or []), got

    # 系统计数落签：pending 一行、签文件 1/1。
    rows = _pending_rows(root)
    assert [int(r.get("review_pass") or 0) for r in rows] == [1], rows
    assert str(dict(rows[0].get("secretary_judge") or {}).get("source") or "") == \
        MECH_SOURCE, rows
    files = _sign_files_on_disk(root)
    assert len(files) == 1, files
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    assert (int(doc.get("count") or 0), int(doc.get("need") or 0)) == (1, 1), doc
    assert doc.get("counted_by") == SC.COUNTED_BY, doc
    # 稿上的签块也是 1/1（不是 3/3）。
    block = _block(rel, root)
    assert block.get("signed") is True, block
    assert (block.get("streak"), block.get("need")) == (1, 1), block


# ============================================================ b：F / B 仍是三次（负控）


def test_b_f_and_b_still_need_three_consecutive_passes(tmp_path):
    """b：F 侧三次真模型判定才发签；只落一行真实判定在 need=3 下不够。

    负控：E 的 need=1 不许把 F / B 的门槛带松（不许出现"全局降成 1"）。
    """
    assert STRICT_NEED == 3, (
        "F / B 的门槛不是 3 ⇒ 这条负控量不到「有没有被带松」", STRICT_NEED)
    assert E_NEED != STRICT_NEED, "E 的门槛与 F/B 一样了 ⇒ 两个数被混写"

    # ① 现场：F 的稿一次送审连判三轮（三次真的模型问）才发签。
    st = _vws(tmp_path)
    v, seam = _v(st, [CLEAN_REPLY])
    with _submitted_by_f():
        got = v.verify_proof(proof_manuscript=REL)
    assert got.get("kind") == "proof_unregistered_signed", got
    assert seam.asked() == STRICT_NEED, seam.asked()
    files = _f_sign_files(st)
    assert len(files) == 1, files
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    assert [int(p.get("review_pass") or 0) for p in doc["passes"]] == [1, 2, 3], doc
    assert (int(doc.get("count") or 0), int(doc.get("need") or 0)) == (3, 3), doc
    rows = _f_pending_rows(st)
    assert len(rows) == STRICT_NEED, rows

    # ② 计数层：真实判定只落一行时，need=3 仍然不够（这是 E 的改动不许越过的线）。
    sha = str(got.get("proof_sha256") or "")
    short = SC.count_rows([_real_pass(sha)], review_call="call-real",
                          proof_sha256=sha, need=STRICT_NEED)
    assert (int(short.get("count") or 0), short.get("ok")) == (1, False), short
    full = SC.count_rows([_real_pass(sha, pass_no=n) for n in (1, 2, 3)],
                         review_call="call-real", proof_sha256=sha, need=STRICT_NEED)
    assert (int(full.get("count") or 0), full.get("ok")) == (3, True), full


# ============================================================ c：一次调用只跑一轮


def test_c_duplicated_judgments_and_cross_call_rows_never_add_up(tmp_path, monkeypatch):
    """c：一次调用里不重跑 `need` 遍；复制判词 / 跨送审累计都不许凑轮。

    四半：
    ① 代码形态：`_review_exhaustion_rounds` 里没有 `For` / `While` —— 「复制判词」
       那一族写法的形状就是"循环 `need` 遍、每遍 append 一份同样的判词"；
    ② 运行期：一次送审里机械核对只被调用 1 次；
    ③ 盘上：E 这一趟只有一轮（`review_pass=[1]`，第 2/3 轮不存在）；
    ④ 计数层：同一份机械判词复制三份 ⇒ `count=1`（need=3 不够、need=1 恰好够）；
       跨送审的三行各属一条 `review_call` ⇒ 哪一组都不够 3。
    """
    # ① 代码形态：不留「重跑 need 遍」的循环。
    src = textwrap.dedent(inspect.getsource(V_CORE.AgentV._review_exhaustion_rounds))
    loops = [n for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.For, ast.While))]
    assert loops == [], (
        "这一支里还有循环 —— 「一次判词复制 need 份」就是它的形状",
        [type(n).__name__ for n in loops])

    # ② 运行期：一次送审只买一次机械核对。
    real_review = ER.review
    calls: list[int] = []

    def _counting_review(*args, **kwargs):
        calls.append(1)
        return real_review(*args, **kwargs)

    monkeypatch.setattr(ER, "review", _counting_review)
    env = _env(tmp_path)
    rel, _text = _manuscript(env)
    with _submitted_by_e():
        env["v"].verify_proof(proof_manuscript=rel)
    assert len(calls) == 1, (
        f"一次调用里机械核对跑了 {len(calls)} 遍（need=1 只该跑一轮）", len(calls))

    # ③ 盘上只有一轮。
    rows = _pending_rows(pathlib.Path(env["store"].root))
    assert [int(r.get("review_pass") or 0) for r in rows] == [1], (
        "一次调用里出现了第 2 / 3 轮 ⇒ 还是「重跑 need 遍」的形状", rows)
    assert len({str(r.get("review_call") or "") for r in rows}) == 1, rows

    sha = str(rows[0].get("proof_sha256") or "")
    counts = [_mech_pass(sha, pass_no=n) for n in (1, 2, 3)]
    assert [SC.real_judgment(r) for r in counts] == [False] * 3, (
        "机械会审的行必须仍读成 real_judgment=False（读数要能记）", counts)
    counted3 = SC.count_rows(counts, review_call=CALL, proof_sha256=sha,
                             need=STRICT_NEED)
    assert int(counted3.get("count") or 0) == 1, (
        "同一份机械判词复制三份被数成了多轮", counted3)
    assert counted3.get("terminated") == SC.NOT_REAL_JUDGMENT, counted3
    assert counted3.get("ok") is False, counted3
    counted1 = SC.count_rows(counts, review_call=CALL, proof_sha256=sha, need=E_NEED)
    assert int(counted1.get("count") or 0) == 1, counted1
    assert counted1.get("ok") is True, (
        "need=1 下一次机械过审还不够 ⇒ 计数层没有按新 need 校准", counted1)

    # ④b 跨送审不累计：三行都在，但各属一条 `review_call` ⇒ 没有一组能数到门槛。
    spread = [_real_pass(sha, pass_no=n, call=f"call-submit-{n}") for n in (1, 2, 3)]
    for n in (1, 2, 3):
        got = SC.count_rows(spread, review_call=f"call-submit-{n}",
                            proof_sha256=sha, need=STRICT_NEED)
        assert got.get("ok") is False and int(got.get("count") or 0) < STRICT_NEED, (
            f"跨送审的行被累计进了 call-submit-{n}", got)


# ============================================================ d：反真空（need=3 ⇒ a 红）


def test_d_anti_vacuum_need_three_makes_a_red(tmp_path, monkeypatch):
    """d：把 E 这条路的 need 改回 3 ⇒ a 必红（同一次机械过审不发签、稿上无块）。

    这一条证明 a 的「一次过审就发签」是 `EXHAUSTION_SIGN_STREAK_NEED=1` 给的，
    不是别的什么顺手把门槛绕过去了。
    """
    monkeypatch.setattr(VR, "EXHAUSTION_SIGN_STREAK_NEED", 3)
    env = _env(tmp_path)
    root = pathlib.Path(env["store"].root)
    rel, _text = _manuscript(env)
    with _submitted_by_e():
        got = env["v"].verify_proof(proof_manuscript=rel)

    # 判定照判（机械七项 clean），但 1/3 不够 ⇒ 一个签字节都不落。
    assert got.get("checked") is True, got
    assert got.get("verdict") == "成立", got
    assert _sign_files_on_disk(root) == [], (
        "need=3 下同一次机械过审仍写出了签文件 ⇒ a 的绿不是 need=1 给的", got)
    block = _block(rel, root)
    assert block.get("signed") is False, (
        "need=3 下稿上仍落了签块 ⇒ a 的绿不是 need=1 给的", block)
    assert dict(got.get("review_write") or {}).get("sign_issued") is False, got

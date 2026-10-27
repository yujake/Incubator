# -*- coding: utf-8 -*-
"""判据（Q20，2026-10-26）：收工门那三处档位读点也按号读 —— D16 的尾巴。

## 这一批修的形态

D16 把旁支台账改成按 `stmt_id` 关联（`secretary.nontriviality_of` 三级：按号 → sha →
未判，并回 `matched_by`），页面那一栏（`webui/readers._statement_tier_reading`）跟着传了号，
而收工门这三处没跟：

| 读点 | 函数 | 这一处读的档位用来干什么 | 退化成未判的后果 |
|---|---|---|---|
| `closing.py:5962` | `paper_proof_scaffolding_problems` | 论文侧第 C 条：T3/T4 的框架只剩附录指针 ⇒ 点名 | 这一条静默不报 |
| `closing.py:6004` | `nontriviality_reading` | `counts`（T1–T4/未判 分布）与 `high_tier` ⇒ `high_tier_without_ladder` | 未判那一栏虚高、T3/T4 清单空 |
| `closing.py:6065` | `t4_ladder_problems` | T4 必须有"造梯子"记录 ⇒ 点名 | 整条判据静默失效 |

三处读的是同一份台账、同一条命题 ⇒ 于是"这一处按不按号"在读数上分得开：
改前把正文改一个字，三处一起退化成未判；改后三处一起仍读得到，且 `matched_by` 相同。
退化成未判在这里不是"少一条提示"：第 3 处是"判据静默失效"（它本来会点名缺记录）。

## 判据与改前红

| 判据 | 它要证明的事 | 改前为什么红 |
|---|---|---|
| a0 | 台账的键是 `statement_full` 的 sha，`proof_text` 不进这个键 | 不是负控：它把"改一个字"该改在哪个字段上钉住 |
| a1 | 论文侧那一栏仍看到"T3 框架被移进附录" | 只传正文 ⇒ sha 对不上 ⇒ 档位未判 ⇒ 这一条不报 |
| a2 | 分布那一栏仍把这条算成 T3（未判 0），且 `matched_by="stmt_id"` | 同上，它被算进 unjudged |
| a3 | T4 缺造梯子记录仍被点名 | 档位未判 ⇒ `level != 4` ⇒ 静默放过 |
| b | 收工门那一栏与页面那一栏给同一个档位、同一个 `label`、同一个 `matched_by` | 页面那栏按号、这一栏按正文 ⇒ 两栏分家 |
| c | 旧账本（只有 sha、没有号）仍读得到，且 `matched_by="sha256"` | 兼容正控：加了号不许把旧数据读废 |
| d | 反真空：把某一处改回"不传号" ⇒ 该处必红 | 这一条证明 a 的绿来自号，不是正文碰巧相同 |
| e | 三处的档位与 `matched_by` 两两一致 | 挡住"只改了两处、漏一处"——今天这个 bug 就是这么来的 |

零模型钱：工作区全在 `tmp_path`，台账由 `secretary.append_nontriviality` 直接落行。
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import closing as CL  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow.webui import readers as R  # noqa: E402

_SID = "000201"
#: 判档那一刻的正文：台账落在这一份的 sha 上。
_OLD = "设 G 是有限群；则 G 的中心非平凡"
#: 之后被改过一个字的正文：号不变，sha 变了。
_NEW = _OLD + "。"
_PROOF = "证明：数共轭类的轨道。"
#: 论文侧的那段正文：定理环境里是旧正文，指针写在环境后面（`_env_bodies` 会带 400 字符）。
_TEX = "\\begin{theorem}" + _OLD + "\\end{theorem}\n标准论证见附录 A.2。\n"

#: 三处读点的名字（反真空判据按它逐个造红）。
_SITES = ("paper", "reading", "ladder")


# ---------------------------------------------------------------- 夹具


def _row(body: str = _NEW, proof: str = _PROOF) -> dict[str, Any]:
    """一条命题行：正文已被改过（`_NEW`），号还在。"""
    return {"stmt_id": _SID, "statement_full": body, "proof_text": proof}


def _ws(tmp_path: pathlib.Path, *, rows: list[dict[str, Any]],
        tex: str = "") -> pathlib.Path:
    root = tmp_path / "ws"
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "statements.json").write_text(
        json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
    if tex:
        (root / "out" / "paper").mkdir(parents=True, exist_ok=True)
        (root / "out" / "paper" / "main.tex").write_text(tex, encoding="utf-8")
    return root


def _judge(root: pathlib.Path, *, level: int) -> None:
    """按号落一行档位：判的是 `_OLD`，号是 `_SID`（正文后来被改成 `_NEW`）。"""
    SEC.append_nontriviality(root, statement_full=_OLD, level=level, stmt_id=_SID,
                             basis="体量与引理都过线")


def _old_ledger_row(body: str, level: int) -> dict[str, Any]:
    """改前那种行：只有 sha，没有 `stmt_id`（旧账本兼容正控用）。"""
    return {"at": "2026-10-25T00:00:00+08:00",
            "statement_sha256": SEC._statement_sha(body),
            "statement_chars": len(body), "scale": SEC.NONTRIVIALITY_SCALE,
            "nontriviality": level, "label": SEC.nontriviality_label(level),
            "basis": "旧行（只有 sha）", "effort": {}, "text_truncated": False,
            "role": "B", "task_id": "t-old"}


def _write_ledger(root: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    path = SEC.nontriviality_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                            for r in rows), encoding="utf-8")


def _degraded(site: str, root: pathlib.Path) -> bool:
    """这一处现在是不是退化成"未判"了（True = 读丢了）。"""
    if site == "paper":
        return CL.paper_proof_scaffolding_problems(root) == []
    if site == "reading":
        return CL.nontriviality_reading(root)["counts"]["unjudged"] == 1
    return CL.t4_ladder_problems(root) == []


# ---------------------------------------------------------------- a0）键是正文，不是证明


def test_a0_the_key_is_the_statement_body_not_the_proof(tmp_path: pathlib.Path) -> None:
    """a0：台账的键是 `statement_full` 的 sha；`proof_text` 不进这个键。

    业主的口径是"命题正文被改一个字"。`secretary._statement_sha` 只吃
    `statement_full`，`proof_text` 根本不进这个键 ⇒ 只改 `proof_text` 的话，
    改前也不会退化，那样写的判据是真空的。所以下面几条把"那个字"改在
    `statement_full` 上；这一条把"键只吃正文"这个事实钉住（谁把键换成含证明正文的
    复合 sha，这里就红）。
    """
    assert SEC._statement_sha(_OLD) != SEC._statement_sha(_NEW)
    # 只换证明正文、正文一字不动 ⇒ 这一行仍是同一条命题的档位读数
    root = _ws(tmp_path, rows=[_row(_OLD, proof="完全不同的证明正文")])
    _judge(root, level=3)
    got = SEC.nontriviality_of(root, _OLD, stmt_id=_SID)
    assert got["level"] == 3 and got["matched_by"] == "stmt_id", got


# ---------------------------------------------------------------- a1）论文侧那一栏


def test_a1_the_paper_column_still_sees_a_high_tier_framework_in_the_appendix(
        tmp_path: pathlib.Path) -> None:
    """a1：正文改过一个字之后，论文侧那一栏仍看到"T3 的框架被整段移进附录"。

    改前红：这一处传的是正文（`statement_full`），台账按 sha 关联 ⇒ sha 对不上
    ⇒ `level=None` ⇒ `tier >= 3` 那一支不进 ⇒ 清单里少了这一条。
    """
    root = _ws(tmp_path, rows=[_row()], tex=_TEX)
    _judge(root, level=3)
    problems = CL.paper_proof_scaffolding_problems(root)
    assert problems, "正文改过一个字之后，论文侧那一栏读不到档位了"
    assert "整段移进附录" in problems[0], problems


# ---------------------------------------------------------------- a2）分布那一栏


def test_a2_the_reading_column_still_counts_it_as_t3(tmp_path: pathlib.Path) -> None:
    """a2：分布那一栏仍把这条算成 T3（未判 0），`high_tier` 里带同一个号与命中方式。

    改前红：退化成未判 ⇒ `counts["unjudged"]==1`、`counts["T3"]==0`、
    `high_tier_total==0`（T3/T4 清单空 ⇒ 收工输出少一条 warning）。
    """
    root = _ws(tmp_path, rows=[_row()])
    _judge(root, level=3)
    got = CL.nontriviality_reading(root)
    assert got["counts"]["T3"] == 1, got["counts"]
    assert got["counts"]["unjudged"] == 0, got["counts"]
    assert got["high_tier_total"] == 1, got["high_tier"]
    assert got["high_tier"][0]["stmt_id"] == _SID, got["high_tier"]
    assert got["high_tier"][0]["level"] == 3, got["high_tier"]
    assert got["high_tier"][0]["matched_by"] == "stmt_id", got["high_tier"]


# ---------------------------------------------------------------- a3）T4 造梯子那一栏


def test_a3_the_t4_ladder_column_still_names_a_missing_attempt(
        tmp_path: pathlib.Path) -> None:
    """a3：判成 T4 而没有任何造梯子记录 ⇒ 仍被点名（改前是静默放过）。

    改前红：档位未判 ⇒ `level != 4` ⇒ 这一条整条判据失效 ——
    它不是"少一条提示"，是"判据静默失效"。
    """
    root = _ws(tmp_path, rows=[_row()])
    _judge(root, level=4)
    problems = CL.t4_ladder_problems(root)
    assert problems, "T4 缺造梯子记录没被点名：这一条判据静默失效了"
    assert "造梯子" in problems[0] and _SID in problems[0], problems


# ---------------------------------------------------------------- b）两栏读数一致


def test_b_the_closing_column_and_the_page_column_agree(
        tmp_path: pathlib.Path) -> None:
    """b：同一条命题，收工门那一栏与页面那一栏给同一个档位、label 与 `matched_by`。

    改前红：页面那栏按号（`matched_by="stmt_id"`、T3），这一栏按正文
    （`matched_by=""`、未判）⇒ 两栏对同一条命题说两句话，正是 Q20 的形态。
    """
    root = _ws(tmp_path, rows=[_row()])
    _judge(root, level=3)
    row = _row()
    closing_tier = CL.nontriviality_reading(root)["high_tier"][0]
    page_tier = R._statement_tier_reading(root, row)
    assert (closing_tier["level"], closing_tier["label"], closing_tier["matched_by"]) == (
        page_tier["level"], page_tier["label"], page_tier["matched_by"]), (
            closing_tier, page_tier)
    assert page_tier["matched_by"] == "stmt_id" and page_tier["level"] == 3, page_tier


# ---------------------------------------------------------------- c）旧账本仍读得到


def test_c_an_old_ledger_row_is_still_read_with_the_sha_fallback(
        tmp_path: pathlib.Path) -> None:
    """c：旧账本（只有 sha、没有号）⇒ 三处仍读得到，且命中方式自报 `sha256`。

    这一条是兼容正控：加了号不许把旧数据读废。它同时证明"按号"没有长成第二处真身
    （否则旧行会静默变成未判）。
    """
    root = _ws(tmp_path, rows=[{"stmt_id": _SID, "statement_full": _OLD,
                               "proof_text": _PROOF}])
    _write_ledger(root, [_old_ledger_row(_OLD, 4)])
    got = CL.nontriviality_reading(root)
    assert got["counts"]["unjudged"] == 0, got["counts"]
    assert got["high_tier_total"] == 1, got["high_tier"]
    assert got["high_tier"][0]["level"] == 4, got["high_tier"]
    assert got["high_tier"][0]["matched_by"] == "sha256", got["high_tier"]
    # 第三处（T4 造梯子）也走同一条回退：旧账本照样能点名
    assert CL.t4_ladder_problems(root), "旧账本在 T4 那一格读不到"
    page_tier = R._statement_tier_reading(root, {"stmt_id": _SID, "statement_full": _OLD})
    assert page_tier["level"] == 4 and page_tier["matched_by"] == "sha256", page_tier


# ---------------------------------------------------------------- d）反真空


@pytest.mark.parametrize("site", _SITES)
def test_d_dropping_the_id_turns_that_site_red(
        site: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d：反真空 —— 有号时这一处读得到；把这一处的号去掉 ⇒ 该处必红。

    号"去掉"的实现是把读口收到的 `stmt_id` 丢掉（等价于把这一行改回改前那一行
    `nontriviality_of(root, text)`）。于是正文只剩 sha 回退、而 sha 已对不上 ⇒ 未判。
    这一条证明 a 的绿来自号，不是"改一个字碰巧也能对上"。

    注意它挡的是什么：三处各自一条 case。谁在源码里把某一处的号去掉，
    对应的 a 判据会红，而这一条本身仍绿（它证明的是号在承重，不是源码现状）。
    """
    level = 4 if site == "ladder" else 3
    root = _ws(tmp_path, rows=[_row()], tex=_TEX)
    _judge(root, level=level)
    assert not _degraded(site, root), f"{site} 有号却没读到"

    real = SEC.nontriviality_of

    def dropped(root_: Any, statement_full: str, **kw: Any) -> dict[str, Any]:
        kw.pop("stmt_id", None)          # 这一处不传号（改前的形态）
        return real(root_, statement_full, **kw)

    monkeypatch.setattr(SEC, "nontriviality_of", dropped)
    assert _degraded(site, root), f"{site} 不传号却仍读得到 ⇒ 它的绿不是号给的"


# ---------------------------------------------------------------- e）三处两两一致


def test_e_the_three_sites_read_the_same_level_and_the_same_matched_by(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e：同一份台账、同一条命题，三处读出来的档位与 `matched_by` 必须相同。

    为什么这条必要：今天这个 bug 的形态就是"只改了两处、漏一处" —— 三处各自绿、
    却有的按号有的按正文。这里把三处的实际调用录下来逐处核对：每一处都必须带着号去读
    （录不到号就直接红），三处回来的 `(level, matched_by)` 必须两两相等。
    """
    root = _ws(tmp_path, rows=[_row()], tex=_TEX)
    _judge(root, level=4)
    seen: list[dict[str, Any]] = []
    real = SEC.nontriviality_of

    def spy(root_: Any, statement_full: str, **kw: Any) -> dict[str, Any]:
        got = real(root_, statement_full, **kw)
        seen.append({"stmt_id": str(kw.get("stmt_id") or ""),
                     "level": got.get("level"),
                     "matched_by": str(got.get("matched_by") or "")})
        return got

    monkeypatch.setattr(SEC, "nontriviality_of", spy)

    def reading_of(call: Any) -> tuple[int | None, str]:
        seen.clear()
        call()
        hits = [r for r in seen if r["stmt_id"] == _SID]
        assert hits, f"这一处没有按号读：{seen}"
        pairs = {(r["level"], r["matched_by"]) for r in hits}
        assert len(pairs) == 1, seen
        return pairs.pop()

    tiers = {"paper": reading_of(lambda: CL.paper_proof_scaffolding_problems(root)),
             "reading": reading_of(lambda: CL.nontriviality_reading(root)),
             "ladder": reading_of(lambda: CL.t4_ladder_problems(root))}
    assert len(set(tiers.values())) == 1, tiers
    assert tiers["paper"] == (4, "stmt_id"), tiers

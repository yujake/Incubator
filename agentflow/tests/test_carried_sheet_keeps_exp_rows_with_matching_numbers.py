# -*- coding: utf-8 -*-
"""判据：携带单的去重必须按键的身份分家 —— `stmt:` 与 `exp:` 同号不许互相挤掉。

## 缺口（2026-11-04 审查 B 区读出来的）

`AgentD._carried_manuscripts` 用同一个 `seen` 集合去重 F 的证明手稿
（键 `stmt:<命题号>`）与 E 的穷举证明手稿（键 `exp:<实验号>`），而两处加进去的都是
裸号（`seen.add(sid)` / `eid in seen`）。两张表的号各自从头编（都从 000000 起）⇒
一条已在册的命题 `stmt:000000` 在盘上有一份 `reports/f-proof-000000.md` 时，
E 的 `exp:000000` 那条已签的 e-proof 会被当成"已经带过"而静默从携带单里消失。

后果与"没签"同形：B 按清单寻址不到 E 的稿（`read_carried_manuscript` 除了按
正文 sha 那一条之外没有别的入口），入库闸按"无签"拒，而 D 的报告里那张单看起来
是空的 —— `carried_missing` 也不会报（单非空），读数一切正常。这正是"少一条边
没有任何地方会报错"的形态，所以判据钉在携带行本身，不钉下游。

## 判据

| # | 造什么 | 期望 |
|---|---|---|
| a | 一条在册 F 命题 `stmt:000000` 带盘上 `f-proof-000000.md` ＋ 一条已签 e-proof `exp:000000` | 携带单两行都在（`stmt:000000` 与 `exp:000000`） |
| b | 反真空：把去重键打桩回裸号 | a 的 exp 行又消失（证明 a 量的是"按键的身份分家"这一格） |

夹具直接复用 `test_e_proof_is_carried_by_d._env`（E 跑一趟真穷举 + V 三转落签，
零模型调用），不另造第二份。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import manuscriptids as _MID  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow.agent_d import AgentD  # noqa: E402
import agentflow.agent_d.write_report as WR  # noqa: E402

from test_e_proof_is_carried_by_d import FULL, _env  # noqa: E402

#: F 那一份稿的稿号（2026-11-10 稿号口径：稿名带稿号，不按命题号命名）。
F_MID = "000901"


def _register_first_statement(env: dict) -> str:
    """在册一条 F 的命题（先立猜想、证明后补）—— 它的号与 E 的实验号同宽同序。"""
    first = env["b"].register_statement(
# 2026-11-17（业主裁定 ②）：own_result 必须写清来路；这一份夹具不测承重链，用形状合法的占位号。
        origin="own_result", derived_from=["999999"], kind="conjecture", label="R(3,4)=9",
        statement_full=FULL, statement_text="R(3,4)=9", proof_text="",
        evidence_kind="cross_check", doc_id=S.format_id(0),
        line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导")
    assert first.get("ok") is True, first
    return str(first.get("stmt_id") or "")


def _put_f_manuscript(env: dict, sid: str) -> None:
    """盘上那份按 F 自己的稿号命名的 F 稿（携带单扫的判据是"文件真的在盘上"）。

    2026-11-10（稿号口径）：稿名不再等于命题号 —— 稿名带 `F_MID`，命题号只记在
    `statements` 行的 `manuscript_id` 那一格（B 收录时写的正是它）。携带单按那一格
    找稿，于是这一条仍然量得到"F 那一行在不在单上"。
    """
    rel = _MID.canonical_rel(F_MID)
    assert rel and f"f-proof-{sid}" not in rel, (rel, sid)
    target = pathlib.Path(env["store"].root) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"# F 的证明手稿：R(3,4)=9\n\n\n"
        "## 命题\n\n" + FULL + "\n\n## 证明\n\n1. 由定义直接得到。\n",
        encoding="utf-8")
    row = dict(next(r for r in env["store"].rows("statements")
                    if str(r.get("stmt_id")) == sid))
    row["manuscript_id"] = F_MID
    with env["store"].tx("statements", actor="test",
                         note="fixture:record-manuscript-id") as tx:
        tx.upsert("statements", row)


def _keys(rows: list[dict]) -> list[tuple[str, str]]:
    return [(str(r.get("statement_id") or ""), str(r.get("experiment_id") or ""))
            for r in rows]


def _same_number_env(tmp_path: pathlib.Path) -> dict:
    env = _env(tmp_path)
    eid = str(env["out"]["experiment_id"])
    sid = _register_first_statement(env)
    assert sid == eid, (
        f"夹具前提不成立：F 的号 {sid!r} 与 E 的号 {eid!r} 没撞上（两张表各自从头编，"
        "这一条判据要的正是同号现场）")
    _put_f_manuscript(env, sid)
    env["sid"], env["eid"] = sid, eid
    return env


# ============================================================ a 同号不许互相挤掉
def test_a_an_exp_row_survives_a_statement_row_with_the_same_number(
        tmp_path: pathlib.Path) -> None:
    """a：F 的 `stmt:000000` 与 E 的 `exp:000000` 同号 ⇒ 携带单里两行都要在。"""
    env = _same_number_env(tmp_path)
    rows, _note = AgentD(env["store"])._carried_manuscripts()
    keys = _keys(rows)
    assert (env["sid"], "") in keys, f"F 那一行不在携带单里：{keys}"
    assert ("", env["eid"]) in keys, (
        f"E 的 exp:{env['eid']} 被同号的 stmt:{env['sid']} 挤掉了"
        f"（携带单里只有 {keys}）—— B 按清单寻址不到这条已签的 e-proof")


# ============================================================ b 反真空
def test_b_bare_numbers_drop_the_exp_row_again(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """b：把去重键打桩回裸号 ⇒ a 必须红。

    `_carried_key` 是携带单去重的唯一落点（`stmt:` / `exp:` 前缀在它里面）。把它
    打桩成裸号，等价于改前那一格；此时 exp 行必须又消失。若 a 的绿不来自这一格，
    这一条仍然会收下 exp 行。
    """
    env = _same_number_env(tmp_path)
    monkeypatch.setattr(WR, "_carried_key",
                        lambda kind, ident: str(ident), raising=False)
    rows, _note = AgentD(env["store"])._carried_manuscripts()
    keys = _keys(rows)
    assert ("", env["eid"]) not in keys, (
        f"去重键打桩成裸号之后 exp:{env['eid']} 仍在携带单里（{keys}）⇒ a 的绿"
        "不是「按键的身份分家」给的")
    assert (env["sid"], "") in keys, keys


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))

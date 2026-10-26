"""判据：role 级派活（没点名动作）不许被"能力面里没有空动作"误拦。

## 这条判据守的是 2026-10-21 的真机事故

`projects/p3-verify` 那一趟里，M 派 A/E/D 的四次 role 级派活全被判
「X 的能力面里没有 」（注意：那是空动作）—— 那一版把"没点名动作"当成"点名了一个
动作表里没有的动作"，于是空动作必然不在表里，恒判不可派；
而 `tasks` 里那四个子代理都真的派出去并跑起来了。
⇒ 不是派活不准，是判据用错了对象：动作表回答"调什么"，而这一条没点名动作。

## 三条

1. `action=""` ⇒ 判 `可派`（不是「建议改派」）；
2. 点名一个不存在动作 ⇒ 仍判「建议改派/重排」（不许把判据一起废掉）；
3. 点名一个存在动作且参数齐 ⇒ `可派`；参数不齐 ⇒ 「建议重排」。
   必填键取自真机拒绝报文（`claim` / `claim_key` / `script_path`）；
   声明改了这条会红，且红在"报文里没有这些键"，原因一眼可见。
"""

from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import secretary as SEC  # noqa: E402

_REQUIRED = ("claim", "claim_key", "script_path")


def _boss(tmp_path: pathlib.Path) -> SEC.Secretary:
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    return SEC.Secretary(role="M", root=tmp_path)


def test_role_level_dispatch_is_not_refused_by_an_empty_action(tmp_path: pathlib.Path) -> None:
    boss = _boss(tmp_path)
    for to in ("A", "D", "E", "F", "G", "H"):
        got = boss.assess_delegation(to=to, action="", params={})
        assert got.get("decision") == "可派", (to, got.get("decision"), got.get("reason"))
        assert "没点名" in str(got.get("reason")), got.get("reason")


def test_a_really_unknown_action_is_still_refused(tmp_path: pathlib.Path) -> None:
    """负控：不许把这条判据一并废掉 —— 点名了不存在的动作仍要判「建议改派/重排」。"""
    boss = _boss(tmp_path)
    got = boss.assess_delegation(to="E", action="no_such_action_xyz", params={})
    assert got.get("decision") in ("建议改派", "建议重排"), got
    assert "no_such_action_xyz" in str(got.get("reason")), got.get("reason")


def test_a_real_action_with_its_required_params_is_admitted(tmp_path: pathlib.Path) -> None:
    boss = _boss(tmp_path)
    need = {key: "x" for key in _REQUIRED}
    got = boss.assess_delegation(to="E", action="run_experiment", params=need)
    assert got.get("decision") == "可派", (need, got)
    missing = boss.assess_delegation(to="E", action="run_experiment", params={})
    assert missing.get("decision") == "建议重排", missing
    assert all(key in str(missing.get("reason")) for key in _REQUIRED), missing.get("reason")

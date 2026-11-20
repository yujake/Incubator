# -*- coding: utf-8 -*-
"""判据：`/api/acceptance` 的 `failed` 只装「真不过」，「没查成」单列。

## 改前是什么样（`draft/187` P1-3 的现场读数）

同一组入参（`project_dir=.` / `report_path=out/review/REPORT.md`）：

```
/api/acceptance.failed = 3 条（statements_have_assumptions_and_source / triage_branch_recorded / within_cost_cap）
/api/package.closing.content = failed:1 + unchecked:2
空工作区：/api/acceptance.failed = 5/5  vs  package = 2 fail + 3 unchecked
```

根因：`acceptance_face` 直接透传上游 `reviewaccept.check_review` 的 `acc.failed`，而它
把 `unknown` 与 `fail` 混装在同一个清单里；正确写法早就在同一个文件的
`_closing_block`（`failed = v=="fail"` / `unchecked = v=="unknown"`）。

## 三条

1. 正控（两面对账）：同一组入参下，`/api/acceptance` 与 `/api/package` 对
   「几条真不过 / 几条没查成」逐字相等 —— 两个出口不许说两句话。
2. 三态（两档不折平）：`failed` 与 `unchecked` 不相交，并集恰好是「不是 pass 的
   全部」；空工作区也不许把 3 条 `unknown` 折进 `failed`。
3. 反真空：把上游打桩成改前那个样子（`unknown` 也进 `failed`）⇒ 这一面必须仍按
   `criteria` 分档（证明它不再透传 `acc.failed`）；再把「分档」那一条打桩回旧口径
   ⇒ 判据自己的检查函数必须报红（证明它不是一句永远成立的空话）。
"""
from __future__ import annotations

import pathlib
from typing import Any

from agentflow import reviewaccept as RA
from agentflow.webui import readers as R


# ====================================================================== 夹具
class _FakeAcc:
    """`reviewaccept.check_review` 的最小替身（只给 `acceptance_face` 读的那几格）。"""

    def __init__(self, criteria: dict[str, str]) -> None:
        self.criteria = dict(criteria)
        self.details = {key: "" for key in criteria}
        self.auxiliary = {}
        # 改前上游的样子：不是 pass 的全进 failed（`unknown` 也被算成「不过」）。
        self.failed = sorted(key for key, value in criteria.items() if value != "pass")

    def to_dict(self) -> dict[str, Any]:
        return {"auxiliary_note": "夹具：只给三态"}


#: 改前那一台机器上的分布（1 fail + 2 unknown）。
_MIXED = {"statements_have_assumptions_and_source": "fail",
          "triage_branch_recorded": "unknown",
          "within_cost_cap": "unknown",
          "hops_have_readable_prompts": "pass",
          "attachment_is_honest": "pass"}


def _face_problems(got: dict[str, Any]) -> list[str]:
    """这一面「两档折平 / 与 package 不一致」的问题清单（空 = 对）。

    纯函数：下面的反真空把改前那一份 dict 喂进来，它必须报红。
    """
    criteria = dict(got.get("criteria") or {})
    failed = list(got.get("failed") or [])
    unchecked = list(got.get("unchecked") or [])
    problems: list[str] = []
    want_failed = sorted(key for key, value in criteria.items() if value == "fail")
    want_unchecked = sorted(key for key, value in criteria.items() if value == "unknown")
    if failed != want_failed:
        problems.append(f"`failed` 不是「criteria 里 fail 的那些」：{failed} != {want_failed}")
    if unchecked != want_unchecked:
        problems.append(f"`unchecked` 不是「criteria 里 unknown 的那些」："
                        f"{unchecked} != {want_unchecked}")
    both = sorted(set(failed) & set(unchecked))
    if both:
        problems.append(f"同一格既算真不过又算没查成（两档折平）：{both}")
    union = sorted(set(failed) | set(unchecked))
    everything_not_pass = sorted(key for key, value in criteria.items() if value != "pass")
    if criteria and union != everything_not_pass:
        problems.append(f"两档并集 != 不是 pass 的全部：{union} != {everything_not_pass}")
    return problems


# ====================================================================== 1 正控
def test_the_two_faces_agree_on_how_many_really_failed(
        artifacts_ws: pathlib.Path) -> None:
    """正控：同参数下 `/api/acceptance` 与 `/api/package` 的两档逐字相等。"""
    acc = R.acceptance_face(artifacts_ws, project_dir=".", report_path="out/review/REPORT.md")
    pkg = R.package_face(artifacts_ws, project_dir=".", report_path="out/review/REPORT.md")
    content = pkg["closing"]["content"]

    assert _face_problems(acc) == [], _face_problems(acc)
    assert acc["failed"] == list(content["failed"]), (acc["failed"], content["failed"])
    assert acc["unchecked"] == list(content["unchecked"]), (
        acc["unchecked"], content["unchecked"])
    # 反真空：这一份夹具上确实有一格「没查成」（否则两档相等是两个空表的相等）。
    assert acc["criteria"]["triage_branch_recorded"] == "unknown", acc["criteria"]
    assert "triage_branch_recorded" in acc["unchecked"], acc["unchecked"]


# ====================================================================== 2 三态
def test_an_empty_workspace_does_not_fold_unchecked_into_failed(
        tmp_path: pathlib.Path) -> None:
    """空工作区：`failed` 只数真不过，3 条 `unknown` 单列（改前这里是 5/5）。"""
    root = tmp_path / "ws"
    root.mkdir()
    got = R.acceptance_face(root, project_dir=".", report_path="out/review/REPORT.md")
    assert _face_problems(got) == [], _face_problems(got)
    # 改前现场的读数：acceptance.failed = 5/5。这里必须严格小于 5，且 unknown 单列。
    assert len(got["failed"]) < 5, got["failed"]
    assert got["unchecked"], got["unchecked"]
    assert not (set(got["failed"]) & set(got["unchecked"]))


# ====================================================================== 3 反真空
def test_the_face_does_not_pass_the_upstream_failed_list_through(
        monkeypatch: Any, tmp_path: pathlib.Path) -> None:
    """反真空：上游 `acc.failed` 仍然混装 ⇒ 这一面按 `criteria` 分档（不透传）。"""
    root = tmp_path / "ws"
    root.mkdir()
    fake = _FakeAcc(_MIXED)
    assert fake.failed == sorted(k for k, v in _MIXED.items() if v != "pass"), (
        "替身没造出改前那一份混装清单")

    monkeypatch.setattr(RA, "check_review", lambda *a, **k: fake, raising=True)
    got = R.acceptance_face(root, project_dir=".", report_path="out/review/REPORT.md")
    assert got["failed"] == ["statements_have_assumptions_and_source"], got["failed"]
    assert got["unchecked"] == ["triage_branch_recorded", "within_cost_cap"], got["unchecked"]

    # 判据自己也要是活的：把那个「透传」的旧形状喂给检查函数，它必须报红。
    old_style = {"criteria": dict(_MIXED), "failed": sorted(fake.failed), "unchecked": []}
    assert _face_problems(old_style), "检查函数对改前那一份形状没报红 ⇒ 反真空失效"

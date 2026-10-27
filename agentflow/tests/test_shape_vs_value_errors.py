# -*- coding: utf-8 -*-
"""「形状说对了、值写错了」与「形状认不出来」分开处置（`draft/37` §140）。

## 真机读数（T2 第 5 趟第 4 段）

那一段只活了 60 秒就 `stop_reason=bad_json_limit`，最后一条是：

    收件人 'ALL' 既不是角色（…）、也不是主控 M、也不是 #public

而要它命的其实是两处约定不一致：手稿那条通道教的是 `to="ALL"`（用户口径：
文件名 `…toALL.md`），`message` 那条只认 `#public`。M 写了正确的一句话、用错了别名，
被算进"形状不合法"那一档，连撞三次 ⇒ 整段作废。

这一组守两件：① `ALL` 与 `#public` 是同一个概念（不许两个写法）；
② "值写错了"走 `bad_args` 那一档（提示只改那个字段），"形状认不出来"才走 `bad_json`。"""
from __future__ import annotations

import json
import pathlib

import test_agent_loop as TAL
from agentflow.agent_loop import run_role
from agentflow.llmseam import LlmSeam


def _reply(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _run(tmp_path: pathlib.Path, replies: list[str], *, max_steps: int = 8):
    scripts = {"M": replies}
    st, cond, registry, gw, root = TAL._wired(tmp_path, scripts, max_steps=max_steps)
    return run_role("M", "形状与值", store=st, registry=registry, conductor=cond,
                    seam=LlmSeam(role="M", session_root=root, gateway=gw["M"], price=(0.0, 0.0),
                                 sid="test-run"), workspace_root=str(root), sid="test-run",
                    from_env=False)


def test_to_all_is_the_public_channel(tmp_path: pathlib.Path):
    """正控：`{"message": {"to": "ALL"}}` 与 `#public` 等价（同一个概念两个写法归一）。"""
    from agentflow.agent_loop import ALL

    run = _run(tmp_path, [_reply({"message": {"to": "ALL", "subject": "结论", "body": "见手稿 0001"}}),
                          _reply({"final": "发完了"})])
    assert run.stop_reason == "final", run.to_dict()
    assert not run.bad_json and not run.bad_args, run.to_dict()
    assert run.messages_sent == [ALL], run.to_dict()


def test_a_wrong_value_is_a_correction_not_a_shape_drift(tmp_path: pathlib.Path):
    """正控：`to` 写了个非法收件人 ⇒ 记进 `bad_args`（不是 `bad_json`），提示只改那个字段。"""
    run = _run(tmp_path, [_reply({"message": {"to": "Z", "subject": "x", "body": "y"}}),
                          _reply({"final": "改好了"})])

    assert run.stop_reason == "final", run.to_dict()
    assert run.bad_args == 1 and run.bad_json == 0, run.to_dict()
    first = run.steps[0]
    assert first.shape == "invalid", first.to_dict()
    assert first.result.get("shape_recognized") == "message", first.result
    assert "只改那个字段" in run.transcript, run.transcript[-600:]


def test_three_wrong_values_stop_as_bad_args_limit(tmp_path: pathlib.Path):
    """正控（停止理由）：连着"形状对、值错" ⇒ `bad_args_limit`（不是 `bad_json_limit`）。

    `max_bad_args = 3` 的语义与 `max_bad_json = 2` 一样是"超过才停" ⇒ 第 4 次收工
    （比"形状不合法"那一档多给一次机会，理由写在 `AgentLoop.max_bad_args` 的注释里）。
    """
    bad = _reply({"message": {"to": "Z", "subject": "x", "body": "y"}})
    run = _run(tmp_path, [bad], max_steps=6)

    assert run.stop_reason == "bad_args_limit", run.to_dict()
    assert run.bad_json == 0, run.to_dict()
    assert len(run.steps) == 4, run.to_dict()
    assert all(s.result.get("shape_recognized") == "message" for s in run.steps), run.to_dict()
    assert "值写错" in run.final, run.final


def test_an_unrecognized_shape_still_counts_as_bad_json(tmp_path: pathlib.Path):
    """负控（另一个方向）：认不出形状的那一档仍然按 `bad_json` 处置（判据没被放宽）。"""
    run = _run(tmp_path, [_reply({"nonsense": {"a": 1}}), _reply({"final": "算了"})])

    assert run.bad_json == 1 and run.bad_args == 0, run.to_dict()
    assert run.steps[0].result.get("shape_recognized") == "", run.steps[0].result
    assert "按循环协议重说一次" in run.transcript, run.transcript[-400:]

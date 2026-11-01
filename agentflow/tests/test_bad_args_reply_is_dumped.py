# -*- coding: utf-8 -*-
"""判据：`judge_bad_args` 也要把那段 arguments 原文落盘（不许留 0 字节）。

## 现场（真机 82，2026-11-01 · B-1 / B-2 / B-3）

三条 `judge_bad_args` 的 `out/invalid/*.txt` 都是 0 字节：原生工具调用那条路上
`call.text` 是"回复正文"（为空），坏的是 `arguments` 那段 ⇒ `_dump_invalid_reply(...,
call.text ...)` 写了个空文件。B-1 的断点在 6691 字符处，`detail` 只留了前 200 字，
于是"到底哪里坏"在盘上永远查不出来（报告 §四第 1 条只能写推测）。

## 这一份钉的三条（改前红）

| 条 | 它要证明的事 | 改前为什么红 |
|---|---|---|
| a | 坏参数那一步的 `out/invalid/*.txt` 非空，且含第 2000 字符之后的定位片段 | 改前 `call.text` 为空 ⇒ 落盘 0 字节 |
| b | `problem` 仍是 `judge_bad_args`（留档不许改变归因） | 与 a 同一条链；这一条钉"不许把归因改掉" |
| c | `detail` 里的"原文前 200 字"提到 2000（短参数也够定位） | 改前只留 200 字 |

边界：全部 tmp 工作区、零真实模型调用（网关是打桩的，不联网）；不读写 `projects/`。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import modelgw as MG
from agentflow.agent_loop import LlmBackend, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "bad-args-dump"
#: 坏参数里嵌在第 2000 字符之后的一段可定位标记（`detail` 原来的 200 字截不到它）。
DEEP = "这一段在第两千字符之后：targets[7] 的 task 里有个没转义的引号"
#: 坏参数的原文：前面垫 3000 个字符，坏点落在很深的位置（与 B-1 的 6691 同形）。
BROKEN_ARGS = ('{"targets": [{"task": "' + "填" * 3000 + DEEP + '" 坏在这里')


class _StubGateway:
    """按脚本回原生 `tool_calls` 的替身网关（不联网）。"""

    def __init__(self, script: list[dict]) -> None:
        self.script = list(script)
        self.spec = MG.ModelSpec(model="stub-model", api_key="x", base_url="http://stub")

    def complete(self, prompt: str, *, scope: str, system: Any = None, max_tokens: Any = None,
                 tools: Any = None, tool_choice: str = "auto") -> MG.ModelReply:
        item = self.script.pop(0) if self.script else {"tool_calls": []}
        return MG.ModelReply(ok=True, text=str(item.get("text") or ""),
                             tool_calls=tuple(item.get("tool_calls") or ()),
                             tokens_in=1, tokens_out=1, model="stub-model", scope=scope)


def _bad_args_call() -> dict:
    return {"tool_calls": [{"id": "c1", "name": "conductor_summon_many",
                            "arguments": BROKEN_ARGS}]}


def _final_call(text: str = "交回后收工") -> dict:
    return {"tool_calls": [{"id": "c9", "name": "framework_final",
                            "arguments": json.dumps({"final": text}, ensure_ascii=False)}]}


def _run(tmp_path: pathlib.Path):
    root = tmp_path / "ws"
    st = Store(root)
    st.init()
    gw = _StubGateway([_bad_args_call(), _final_call()])
    seam = LlmSeam(role="M", session_root=root, gateway=gw, price=(0.0, 0.0), sid=SID)
    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=root,
                         seam_factory=lambda role: seam, max_steps=4, store=st, sid=SID)
    cond = Conductor(st, policy=None, backend=backend)
    built = build_registry(store=st, conductor=cond, workspace_root=root)
    backend.registry = built.registry
    run = run_role("M", "把这件事做完", store=st, registry=built.registry, conductor=cond,
                   seam=seam, workspace_root=str(root), sid=SID, max_steps=4,
                   from_env=False)
    return run, root


def _dumps(root: pathlib.Path) -> list[pathlib.Path]:
    folder = root / "out" / "invalid"
    return sorted(folder.glob("*.txt")) if folder.exists() else []


# ============================================ a：落盘非空且含深处的定位片段


def test_the_bad_arguments_are_dumped_in_full(tmp_path):
    """a：坏参数那一步的落盘文件非空，且含第两千字符之后的标记。

    改前红：`call.text` 为空 ⇒ `_dump_invalid_reply` 写出 0 字节文件。
    """
    run, root = _run(tmp_path)
    files = _dumps(root)
    assert files, f"没有任何 out/invalid 落盘：{run.to_dict()}"
    assert all(f.stat().st_size > 0 for f in files), [(f.name, f.stat().st_size) for f in files]
    text = "\n".join(f.read_text(encoding="utf-8") for f in files)
    assert DEEP in text, f"落盘文件里没有深处的定位片段（只有 {len(text)} 字节）"
    assert len(text) >= 3000, f"落盘只有 {len(text)} 字节（坏参数原文 3000+ 字符）"


# ============================================ b：归因不变


def test_the_problem_is_still_judge_bad_args(tmp_path):
    """b：留档是留档，归因仍是 `judge_bad_args`（不许顺手改码）。"""
    run, _root = _run(tmp_path)
    first = run.steps[0]
    assert first.problem == "judge_bad_args", run.to_dict()
    assert str(first.result.get("problem") or "") == "judge_bad_args", first.result
    assert run.bad_args == 1 and run.bad_json == 0, run.to_dict()
    assert str(first.result.get("raw_reply_path") or ""), first.result


# ============================================ c：detail 的原文头提到 2000


def test_the_detail_carries_more_than_the_first_two_hundred_chars(tmp_path):
    """c：`detail` 里的"原文前 N 字"要能截到第两千字符之后（改前是 200）。

    改前红：`to_shape` 的坏参数文案只带 `text[:200]`，深处的坏点不在 detail 里。
    """
    run, _root = _run(tmp_path)
    detail = str(run.steps[0].result.get("detail") or "")
    assert DEEP[:20] in detail, f"detail 里没有深处的片段（长度 {len(detail)}）"

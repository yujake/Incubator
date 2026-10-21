"""`G-24①`：`AgentE.check_formal` 的 `reason` 有一张局部受控词表，且收口不删信息。

## 这个文件锁的是一条什么性质

`reason` 过去是"工具层给什么就写什么"（`status if status in formalgw.STATUSES
else "tool_crashed"`）—— 一条带兜底的透传：词表之外的新状态会被伪装成
`tool_crashed`（"桥接层自己出错"），而那是一句具体的假话。现在：

- `reason` 只在 `agent_e.FORMAL_REASONS` 里取值（表外的落 `status_unregistered`）；
- 检查器/工具层原样报的那个值逐字进 `verifier_status`（收口与透传成对存在）。

## 正控与负控

- 正控：`formalgw.STATUSES` 的九个值逐个走一遍，每一个都必须能到达 `reason`，
  且 `verifier_status` 与它逐字相同 —— 九值信息一个都不许因收口而丢；
- 负控①：塞一个词表外的状态 ⇒ `reason` 必须是登记值 `status_unregistered`，
  而 `verifier_status` 仍然是那个原样的字符串（不许折叠成"我不认识它"）；
- 负控②：映射表少一个检查器状态 ⇒ 导入期断言必须炸（离开测试也拦得住）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from agentflow import formalgw as FG
from agentflow.agent_e import FORMAL_REASONS, AgentE, _FORMAL_REASON_BY_TOOL_REASON
from agentflow.store import Store
from agentflow.tools import verify_tools as VT

_VERIFIER = {
    "checked": True,
    "available": [{"name": "lean", "path": "lean", "version": "(桩)"}],
    "available_names": ["lean"],
    "probe_errors": [],
    "reason": "（桩）探测到 lean",
}


def make_e(store: Store) -> AgentE:
    return AgentE(store, workspace_root=store.root)


def _stub_check_lean(status: str):
    def _fake(source, *, name, imports, timeout_sec, run_fn=None, workdir=None,
              source_path=None):
        raw = {
            "status": status,
            "reason": f"（桩）{status}",
            "stdout": "（桩）输出",
            "stderr": "",
            "axioms": [],
            "sorry_count": 0,
            "decl_matches": False,
            "declared_in_source": True,
            "ran": True,
            "backend": {"status": "ok"},
        }
        return FG._conclude(raw, status, raw["reason"])

    return _fake


# ============================================================ 词表自身的性质


def test_formal_reasons_is_a_well_formed_local_vocabulary():
    """词表必须是去重的字符串元组，且映射表的值全部落在词表内。"""
    assert isinstance(FORMAL_REASONS, tuple) and FORMAL_REASONS
    assert all(isinstance(x, str) and x.strip() for x in FORMAL_REASONS)
    assert len(set(FORMAL_REASONS)) == len(FORMAL_REASONS), "词表里有重复取值"
    outside = sorted(set(_FORMAL_REASON_BY_TOOL_REASON.values()) - set(FORMAL_REASONS))
    assert not outside, f"映射表给出了词表外的值：{outside}"


def test_every_checker_status_is_explicitly_collected_in():
    """正控（静态）：`formalgw.STATUSES` 的九个值一个不落地在映射表里。

    这条断言与 `agent_e` 导入期的那一条是同一个判据的两处落点：导入期那条拦住
    "跑起来才发现"，这条给出人读得到的清单。检查器新增状态而这里没跟上 ⇒ 红。
    """
    assert set(FG.STATUSES) <= set(_FORMAL_REASON_BY_TOOL_REASON), (
        "有检查器状态没有被显式收口进 reason 词表："
        f"{sorted(set(FG.STATUSES) - set(_FORMAL_REASON_BY_TOOL_REASON))}"
    )


def test_negative_control_a_checker_status_missing_from_the_map_breaks_the_import(
    monkeypatch: pytest.MonkeyPatch,
):
    """负控②：把映射表摘掉一个值 ⇒ 导入期断言必须炸（不许静默透传）。

    做法是直接重放那条导入期断言，而不是修改模块（`agent_e` 只被导入一次）。
    """
    trimmed = {k: v for k, v in _FORMAL_REASON_BY_TOOL_REASON.items() if k != "uses_sorry"}
    missing = set(FG.STATUSES) - set(trimmed)
    assert missing == {"uses_sorry"}, "夹具本身要能造出『少一个状态』这个前提"
    with pytest.raises(AssertionError):
        assert not missing, f"有状态没有收口：{sorted(missing)}"


# ============================================================ 正控：九个值逐个走通


def test_all_nine_checker_statuses_survive_the_collection(
    store: Store, monkeypatch: pytest.MonkeyPatch
):
    """正控（动态）：九个状态逐个数到 `reason`，且 `verifier_status` 逐字相同。"""
    got: dict[str, tuple[str, str]] = {}
    for status in FG.STATUSES:
        monkeypatch.setattr(VT, "detect_verifier", lambda: _VERIFIER)
        monkeypatch.setattr(FG, "check_lean", _stub_check_lean(status))
        out = make_e(store).check_formal("命题", source="theorem t : True := trivial",
                                         name="t", imports=())
        got[status] = (out["reason"], out["verifier_status"])
    for status, (reason, passed) in got.items():
        assert reason in FORMAL_REASONS, (status, reason)
        assert reason == status, f"{status} 的受控理由被折叠成了 {reason!r}"
        assert passed == status, f"{status} 的原样值丢了：{passed!r}"


def test_the_two_tool_level_refusals_are_in_the_vocabulary(store: Store):
    """`no_script` / `no_backend` 是工具层自己的受控拒绝，也必须在词表里。"""
    monkeypatch_free = make_e(store)
    monkeypatch_free.last_run = None
    # 有后端、没给源码 ⇒ no_script
    assert "no_script" in FORMAL_REASONS
    assert "no_backend" in FORMAL_REASONS
    # 路径越界 ⇒ 本层自己的受控理由
    out = make_e(store).check_formal("c", script_path=str(Path(store.root).parent / "x.lean"))
    assert out["reason"] == "path_outside_workspace"
    assert out["reason"] in FORMAL_REASONS
    assert out["verifier_status"] == "", "没起检查器 ⇒ 没有检查器状态可透传"


def test_a_failed_tool_call_lands_on_a_bounded_reason(store: Store, monkeypatch: pytest.MonkeyPatch):
    """工具层返回失败 ⇒ `reason` 是词表里的 `tool_failed`（不是 `tool_failed:xxx`）。

    复合值（把失败种类拼进 reason）会让"reason 有哪些可能取值"这个问题失去边界；
    种类改放 `detail`，照样可见。
    """
    monkeypatch.setattr(VT, "check_formal",
                        lambda *a, **k: VT.fail("（桩）工具层失败", kind="param_error"))
    out = make_e(store).check_formal("c", source="theorem t : True := trivial", name="t")
    assert out["reason"] == "tool_failed", out
    assert out["reason"] in FORMAL_REASONS
    assert "param_error" in out["detail"], "失败种类必须仍然可读"
    assert out["verifier_status"] == ""


# ============================================================ 负控：词表外的状态


def test_negative_control_a_status_outside_the_vocabulary_is_not_passed_through(
    store: Store, monkeypatch: pytest.MonkeyPatch
):
    """负控①：词表外的状态 ⇒ 落到登记值 `status_unregistered`，原值照样透传。

    这是本次修法的要害：此前它会被写成 `tool_crashed`（一句具体的假话），
    而"我不认识这个状态"与"桥接层自己出错"的处置完全不同。
    """
    payload = {
        "checked": True,
        "verified": False,
        "claim": "c",
        "reason": "some_future_status",
        "detail": "（桩）未来才会有的状态",
        "verifier_output": "（桩）输出",
        "missing_imports": [],
        "verifier_status": "",
    }
    monkeypatch.setattr(VT, "check_formal", lambda *a, **k: VT.ok(dict(payload)))
    out = make_e(store).check_formal("c")
    assert out["reason"] == "status_unregistered", out
    assert out["reason"] in FORMAL_REASONS
    assert out["verifier_status"] == "some_future_status", "原值不许因收口而丢"
    # 负控的反面：它绝不许因为"我不认识"就变成 verified
    assert out["verified"] is not True


def _run_agent_e_import_probe(mode: str) -> subprocess.CompletedProcess:
    """在一个新解释器里导入 `agentflow.agent_e`，把子进程结果原样返回。

    `mode="clean"` 直接导入；`mode="patch"` 在导入 `agent_e` 之前给检查器词表
    塞一个没有被收口的状态（模拟"检查器新增了状态、而映射表没跟上"）。
    补丁必须打在导入之前：`agent_e` 的导入期断言读的是
    `from .formalgw import STATUSES`，那是一次取属性绑定。

    为什么用子进程而不是 `importlib.reload`：reload 会重新创建 `ExperimentError`
    这类异常类对象，而其他测试模块在导入时抓住的是旧对象，于是
    `pytest.raises(ExperimentError)` 再也接不住新对象（全量跑时 `test_core_audit_efgh`
    里那条用例会以"异常逃逸"的形态红）。一次"证明断言真的会炸"的检查不该改变全局类
    身份；子进程没有这个问题。
    """
    probe = (
        "import sys\n"
        "from agentflow import formalgw as FG\n"
        "if sys.argv[1] == 'patch':\n"
        "    FG.STATUSES = tuple(FG.STATUSES) + ('future_status_not_collected',)\n"
        "import agentflow.agent_e\n"
        "print('IMPORT-OK')\n"
    )
    src_dir = str(Path(FG.__file__).resolve().parents[1])
    env = dict(os.environ)
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-c", probe, mode],
        cwd=str(src_dir), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300,
    )


def test_negative_control_the_module_really_does_assert_at_import_time():
    """负控②的行为版（`I-8`）：导入期断言真的会炸，而不是"源码里有那句话"。

    旧版这条判据是 ``assert "<那行断言的文本>" in src`` —— 它判的是文本还在：
    把那条断言包进 `if False:`、或改成等价但不同的写法，文本匹配与行为就脱钩了
    （`I-8` 的原话：文本匹配不是行为）。现在直接在新解释器里重放导入：

    - 正控：不打补丁 ⇒ 退出码 0 且打印 `IMPORT-OK`；
    - 负控：先给检查器词表塞一个没被收口的状态，再导入 `agent_e` ⇒ 退出码非 0，
      且输出里能看到导入期断言的 `AssertionError` 与那个状态名（注入确实生效）。
    """
    clean = _run_agent_e_import_probe("clean")
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "IMPORT-OK" in clean.stdout, clean.stdout + clean.stderr

    patched = _run_agent_e_import_probe("patch")
    err = patched.stdout + patched.stderr
    assert patched.returncode != 0, (
        "给 `formalgw.STATUSES` 塞一个没被收口的状态，`agent_e` 竟然还是导入成功了："
        "导入期断言不生效。"
    )
    assert "AssertionError" in err, err
    assert "future_status_not_collected" in err, err


def test_the_map_and_the_vocabulary_agree_at_the_object_level():
    """正控（`I-8` 留下的那一半）：集合层面的两向包含（不依赖源码文本）。"""
    assert set(FG.STATUSES) <= set(_FORMAL_REASON_BY_TOOL_REASON)
    assert set(_FORMAL_REASON_BY_TOOL_REASON.values()) <= set(FORMAL_REASONS)

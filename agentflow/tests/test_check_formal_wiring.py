"""`AgentE.check_formal` 的两条接线性质：参数透传 与 `script_path` 路径守卫。

## 这个文件补的是哪一段缺口

工具层 `verify.check_formal` 早就收 `source` / `name` / `imports` / `timeout_sec`
四个参数，而 `AgentE.check_formal` 只转发 `claim` / `script_path`：

- 参数到不了 E：调用方写得出"给一段内存里的 Lean 源码""指定要核对的声明名"，
  E 收不到，而且不会报错（静默吃掉）—— 这是"能力表声明了、实现没有"的接线缺口；
- `script_path` 没有路径守卫：工具层把它原样交给 `formalgw.check_lean` 的
  `source_path` 入口，那个入口会 `open()` 它 ⇒ 在 `AgentE` 收口之前，
  这是一条能读工作区外任意文件的通道（`run_experiment` 那条路径有 `_resolve`，这条没有）。

两条都配正控与会红的负控。全部离线：检查器后端由桩替代，不联网、不依赖 Lean。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentflow import formalgw as FG
from agentflow.agent_e import AgentE
from agentflow.store import Store
from agentflow.tools import verify_tools as VT
from agentflow.tools.base import ParamError, validate_params

#: 工具层 `verify.check_formal` 的返回键契约（与 `ToolSpec.returns` 逐字一致）。
CONTRACT_KEYS = {"checked", "verified", "claim", "reason", "detail", "verifier_output"}

#: 检查器探测结果：假装环境里有 lean。
_VERIFIER = {
    "checked": True,
    "available": [{"name": "lean", "path": "lean", "version": "(桩)"}],
    "available_names": ["lean"],
    "probe_errors": [],
    "reason": "（桩）探测到 lean",
}


def make_e(store: Store) -> AgentE:
    return AgentE(store, workspace_root=store.root)


def _fake_check_lean_seen() -> dict:
    """把 `formalgw.check_lean` 换成"检查通过"的桩，并记录它真的收到了什么。"""
    seen: dict = {}

    def _fake(source, *, name, imports, timeout_sec, run_fn=None, workdir=None,
              source_path=None):
        seen.update({"source": str(source), "name": name, "imports": tuple(imports),
                     "timeout_sec": timeout_sec, "source_path": source_path})
        raw = {
            "status": "verified",
            "reason": "（桩）Lean 接受了这份证明",
            "stdout": "（桩）no goals to be solved",
            "stderr": "",
            "axioms": [],
            "sorry_count": 0,
            "decl_matches": True,
            "declared_in_source": True,
            "ran": True,
            "backend": {"status": "ok"},
        }
        return FG._conclude(raw, "verified", raw["reason"])

    return seen, _fake


# ============================================================ 正控：参数真的到得了 E


def test_check_formal_passes_source_name_imports_timeout_to_the_bridge(
    store: Store, monkeypatch: pytest.MonkeyPatch
):
    """正控①：四个新参数必须一路走到桥接层，且返回 `verified=True`。

    "到得了 E"与"到得了桥接层"是两件事：只断言前者，一个把参数默默丢掉的
    实现也能通过。
    """
    seen, fake = _fake_check_lean_seen()
    monkeypatch.setattr(VT, "detect_verifier", lambda: _VERIFIER)
    monkeypatch.setattr(FG, "check_lean", fake)

    got = make_e(store).check_formal(
        "透传自检",
        source="theorem t : 1 + 1 = 2 := by norm_num",
        name="t",
        imports=["Mathlib", "Init"],
        timeout_sec=7,
    )

    assert seen["name"] == "t"
    assert seen["imports"] == ("Mathlib", "Init")
    assert seen["timeout_sec"] == 7
    assert seen["source"].startswith("theorem t")
    assert got["checked"] is True and got["verified"] is True
    assert got["reason"] == "verified"
    assert set(got) == CONTRACT_KEYS, got


def test_check_formal_normalizes_script_path_and_keeps_old_signature(
    store: Store, monkeypatch: pytest.MonkeyPatch
):
    """正控②：`script_path` 归一成工作区相对路径；旧的单参数调用仍然可用。"""
    seen: dict = {}

    def _spy(claim, **kw):
        seen.update(kw)
        return VT.ok({"checked": False, "verified": None, "claim": claim,
                      "reason": "no_backend", "detail": "", "verifier_output": ""})

    monkeypatch.setattr(VT, "check_formal", _spy)
    script = Path(store.root) / "lean" / "p.lean"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("theorem p : True := trivial\n", encoding="utf-8")
    e = make_e(store)

    out = e.check_formal("正控②", script_path=str(script), name="p")
    assert seen["script_path"] == "lean/p.lean", seen
    assert seen["name"] == "p"
    assert out["reason"] == "no_backend"

    # 向后兼容：旧调用方只给 claim，不许因此报错或改变返回形态
    e.check_formal("只有 claim")
    assert seen["script_path"] is None
    assert set(out) == CONTRACT_KEYS


# ============================================================ 负控：必须会红


def test_negative_control_out_of_workspace_script_path_is_refused(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """负控①：越界路径必须被拒，且工具层一次都不许被调到。

    断言"工具层没被调到"是关键：只断言返回值，一个"先读了那个文件、
    再把结论折叠成失败"的实现也能通过 —— 而文件已经读出去了。
    """
    touched: list = []
    monkeypatch.setattr(VT, "check_formal",
                        lambda *a, **k: touched.append((a, k)) or VT.ok({}))

    outside = tmp_path / "outside_secret.txt"
    outside.write_text("这段内容不该被任何框架代码读到\n", encoding="utf-8")
    before = outside.read_bytes()

    res = make_e(store).check_formal("负控①", script_path=str(outside))

    assert res["checked"] is False
    assert res["verified"] is None, "没查必须是 None；False 会被读成'查了没通过'"
    assert res["reason"] == "path_outside_workspace"
    assert touched == [], "越界路径不许走到工具层（那是'真的去读了那个文件'）"
    assert outside.read_bytes() == before
    assert set(res) == CONTRACT_KEYS

    # 相对穿越的两种拼法都要拦（Windows 上 `..\\..` 与 `../../` 是两条路径）
    for bad in ("../../outside_secret.txt", r"..\..\outside_secret.txt"):
        assert make_e(store).check_formal("负控①b", script_path=bad)["reason"] == (
            "path_outside_workspace"
        ), bad


def test_negative_control_validate_params_rejects_bad_timeout_and_imports(store: Store):
    """负控②：非法 `timeout_sec` / `imports` 必须在 `validate_params` 就被拒。

    这是"到不了 E 的第二种形态"：参数非法时不该跑到桥接层再失败 ——
    `formalgw.check_lean` 会把非法声明名当 `ValueError`，而非法超时会变成一次
    真实的长跑。校验必须在工具层的入口处完成。
    """
    from agentflow.tools import build_registry

    build = build_registry(store=store, workspace_root=store.root)
    schema = build.registry.get("verify.check_formal").params

    bad = [
        {"claim": "c", "timeout_sec": 0},
        {"claim": "c", "timeout_sec": -3},
        {"claim": "c", "timeout_sec": "abc"},
        {"claim": "c", "imports": "Mathlib"},
        {"claim": "c", "imports": [1, 2]},
        {"claim": "c", "timeout": 5},          # 未声明的参数
        {"name": "t"},                          # 缺必填 claim
    ]
    for params in bad:
        with pytest.raises(ParamError):
            validate_params(schema, params)

    # 防误伤：合法参数必须过
    validate_params(schema, {"claim": "c", "source": "theorem t : True := trivial",
                             "name": "t", "imports": ["Mathlib"], "timeout_sec": 1})

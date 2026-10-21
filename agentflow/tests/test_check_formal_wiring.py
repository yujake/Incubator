"""`AgentE.check_formal` 的两条接线性质：参数透传 与 `script_path` 路径守卫。

## 这个文件补的是哪一段缺口

工具层 `verify.check_formal` 早就收 `source` / `checker_name` / `imports` / `timeout_sec`
四个参数，而 `AgentE.check_formal` 只转发 `claim` / `script_path`：

- 参数到不了 E：调用方写得出"给一段内存里的 Lean 源码""指定要核对的声明名"，
  E 收不到，而且不会报错（静默吃掉）—— 这是"能力表声明了、实现没有"的接线缺口；
- `script_path` 没有路径守卫：工具层把它原样交给 `formalgw.check_lean` 的
  `source_path` 入口，那个入口会 `open()` 它 ⇒ 在 `AgentE` 收口之前，
  这是一条能读工作区外任意文件的通道（`run_experiment` 那条路径有 `_resolve`，这条没有）。

两条都配正控与会红的负控。全部离线：检查器后端由桩替代，不联网、不依赖 Lean。
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from agentflow import formalgw as FG
from agentflow.agent_e import AgentE
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import verify_tools as VT
from agentflow.tools.base import ParamError, validate_params


def _declared_contract_keys() -> set[str]:
    """从声明里读 `verify.check_formal` 的返回键契约（FC-03：不在测试里手抄一份）。

    原先这里写的是 `CONTRACT_KEYS = {…6 个键…}`，注释还声称"与 `ToolSpec.returns` 逐字一致"
    —— 那是一份手抄副本：`G-18` 给返回加了第 7 个键 `missing_imports` 之后，声明改了、
    副本没改，于是三条断言一起红（看上去像实现违约，实际是这个测试自己腐了，正是
    `FC-03` 要防的形态）。

    现在改成读声明的字面量：声明加键 ⇒ 测试自动跟上；声明忘了加、而返回多给了键 ⇒ 仍然红。"""
    tmp = Path(tempfile.mkdtemp(prefix="cfw-contract-"))
    store = Store(tmp / "s.sqlite3")
    reg = build_registry(store=store, workspace_root=tmp).registry
    spec = reg.get("verify.check_formal")
    assert spec is not None, "verify.check_formal 没被装配出来 ⇒ 契约读不到"
    declared = str(spec.returns)
    m = re.search(r"\{([^}]*)\}", declared)
    assert m is not None, f"声明里读不出键集合（形如 {{'a','b'}}）：{declared!r}"
    keys = {part.strip().strip("'\"") for part in m.group(1).split(",") if part.strip()}
    assert keys, f"声明里的键集合是空的：{declared!r}"
    return keys


#: 工具层 `verify.check_formal` 的返回键契约 —— 从声明读，不是手抄。
#: 名字与 `ToolSpec.returns` 逐字一致的保证由 `_declared_contract_keys` 本身承担。
CONTRACT_KEYS = _declared_contract_keys()

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


def test_check_formal_does_not_pass_the_filename_as_the_declaration_name(
    store: Store, monkeypatch: pytest.MonkeyPatch
):
    """判据（`goal-a5334ee8` 的 ④，真机实测 2026-10-01）：只给 `script_path` 时
    声明名交给桥接层从源码认，不许拿文件名词干顶替；默认也不注入任何库。

    实测形态：工作区里 `code/lean/p2_rho_sum_zero.lean` 这条文件的声明叫
    `rho_sum_zero`。旧实现把 `Path(script_path).stem`（= `p2_rho_sum_zero`）当声明名
    传下去 ⇒ 桥接层报 `decl_mismatch`（机器可读位是"查了、没通过"），
    而真原因是调用方没点名；同时旧默认注入 `import Mathlib` ⇒ 纯核心源码
    一律 `import_unavailable`（没查成）。两件事叠起来，E 在真机上把"核验证明"
    读成了"这条路走不通"。
    """
    seen, fake = _fake_check_lean_seen()
    monkeypatch.setattr(VT, "detect_verifier", lambda: _VERIFIER)
    monkeypatch.setattr(FG, "check_lean", fake)
    script = Path(store.root) / "code" / "lean" / "p2_rho_sum_zero.lean"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("theorem rho_sum_zero : True := trivial\n", encoding="utf-8")

    make_e(store).check_formal("④ 的判据", script_path=str(script))

    assert seen["name"] == "", (
        f"只给 script_path 时应当把空名字交给桥接层自动认名，实测收到 {seen['name']!r}")
    assert seen["name"] != "p2_rho_sum_zero", "文件名词干不许当声明名（老毛病的正面形态）"
    assert seen["imports"] == (), f"默认不注入任何库，实测 {seen['imports']!r}"
    # 显式给名字/库时逐字透传（这条判据不是把参数吃掉）
    make_e(store).check_formal("④ 的判据", script_path=str(script),
                               name="rho_sum_zero", imports=["Mathlib"])
    assert seen["name"] == "rho_sum_zero" and seen["imports"] == ("Mathlib",), seen


def test_check_formal_normalizes_script_path_and_keeps_old_signature(
    store: Store, monkeypatch: pytest.MonkeyPatch
):
    """正控②：`script_path` 归一成工作区相对路径；旧的单参数调用仍然可用。"""
    seen: dict = {}

    def _spy(claim, **kw):
        seen.update(kw)
        # 桩必须逐键模拟声明的契约（`E-12(a)` 之后是 9 个键；本行此前写「8 个」是照着 `G-18` 那一句手抄的 ——
        # 实测 `CONTRACT_KEYS` = ['checked', 'claim', 'detail', 'exit_code', 'missing_imports', 'reason',
        # 'verified', 'verifier_output', 'verifier_status']，读数 `temp/reaudit4B-d2-contract-keys.txt`）：桩少一个
        # 键时会 `assert set(out) == CONTRACT_KEYS` 读成"实现违约"（其实是桩自己腐了），桩多一个也会红（那才是要抓的）。
        # 两个例外（`N-4`）：`verifier_status` 与 `reason` 少给不会红 —— `AgentE.check_formal` 会无条件重算 # 它们（`data["reason"] = _FORMAL_REASON_BY_TOOL_REASON.get(raw_reason, …)`、
        # `data["verifier_status"] = raw_reason`，值被改写成 `status_unregistered` / 空串）⇒ 这两格是"桩腐了而
        # 这条判据看不出来"，守卫在工具层自己的键集合判据与 `test_the_contract_stub_comment_matches_the_live_key_set` 里。
        # `exit_code` 不在例外里（`E-12(a)` 后逐键少给实测）：`AgentE.check_formal` 从不给它赋值 ⇒ 少给就真少、当场红。
        return VT.ok({"checked": False, "verified": None, "claim": claim,
                      "reason": "no_backend", "detail": "", "verifier_output": "",
                      "missing_imports": [], "exit_code": None})

    monkeypatch.setattr(VT, "check_formal", _spy)
    script = Path(store.root) / "lean" / "p.lean"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("theorem p : True := trivial\n", encoding="utf-8")
    e = make_e(store)

    out = e.check_formal("正控②", script_path=str(script), name="p")
    assert seen["script_path"] == "lean/p.lean", seen
    # `C3`（登记在 `draft/28`）：工具层的那个形参已改名 `name` → `checker_name`
    # （因为 `ToolRegistry.call` 的第一个形参就叫 `name`，逐名关键字写法会
    # `got multiple values for argument 'name'`）。agent 层的形参仍叫 `name`
    # （它不经 `ToolRegistry.call` 调用），所以这里断言的是"agent 层把它翻成了
    # 工具层的新名"—— 这正是这条用例要钉的那一次翻译。
    assert seen["checker_name"] == "p", seen
    assert "name" not in seen, f"工具层不该再收到旧名：{sorted(seen)}"
    assert out["reason"] == "no_backend"

    # 向后兼容：旧调用方只给 claim，不许因此报错或改变返回形态
    e.check_formal("只有 claim")
    assert seen["script_path"] is None
    assert set(out) == CONTRACT_KEYS


# ============================================================ `N-4`：注释与实测的键集合必须一致


def test_the_contract_stub_comment_matches_the_live_key_set(store: Store,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """`N-4` 的机械判据：桩注释里的键数 == 实测键数，且"少一个键 ⇒ 红"的例外必须真的是那几格。

    缺陷形态（第 4 轮重审 `B-R5` 报出，读数 `temp/reaudit4B-d2-contract-keys.txt`）：
    `test_check_formal_normalizes_script_path_and_keeps_old_signature` 里那句注释写的是
    "`G-18` 之后是 7 个键"，而 `CONTRACT_KEYS` 实测 8 个；而且"桩少一个键 ⇒
    `set(out) != CONTRACT_KEYS` ⇒ 红"这条规则对 `verifier_status`（实测还有 `reason`）
    不成立。注释与事实分家时没有任何地方会红 —— 所以这里把两件事都变成判据：

    ① 注释里的键数必须等于 `len(CONTRACT_KEYS)`（改回旧数 ⇒ 本用例红）；
    ② 逐键少给一次，实测"哪几个键被 `AgentE` 无条件补回来"必须逐字等于注释里点名的那两个。
       ②是这条用例的核心：注释说的"例外有几格"是行为事实，不是措辞。
    """
    text = Path(__file__).read_text(encoding="utf-8")
    # 只判注释行：那句键数写在 `#` 注释里，而本用例的 docstring 会逐字引用旧句
    # （引文不是当前状态 —— 与登记册里"改前那一栏是引文"同一条纪律）。
    comments = [ln for ln in text.splitlines() if ln.lstrip().startswith("#")]
    assert any(f"{len(CONTRACT_KEYS)} 个键" in ln for ln in comments), (
        f"桩注释里的键数与实测 `CONTRACT_KEYS`（{len(CONTRACT_KEYS)} 个）不符 —— "
        "`N-4` 的原始形态就是这里写着『7 个键』而实测 8 个"
    )
    stale = [ln.strip() for ln in comments if "7 个键" in ln]
    assert not stale, f"那句过期的『7 个键』又回来了（`N-4`）：{stale}"

    full = {"checked": False, "verified": None, "claim": "c", "reason": "no_backend",
            "detail": "", "verifier_output": "", "missing_imports": [],
            "verifier_status": "no_backend", "exit_code": None}
    assert set(full) == CONTRACT_KEYS, sorted(full)

    silently_refilled: list[str] = []
    for drop in sorted(CONTRACT_KEYS):
        stub = {k: v for k, v in full.items() if k != drop}
        monkeypatch.setattr(VT, "check_formal", lambda *a, _s=stub, **k: VT.ok(dict(_s)))
        out = make_e(store).check_formal("N-4 的键集合探针")
        if set(out) == CONTRACT_KEYS:
            silently_refilled.append(drop)

    assert silently_refilled == ["reason", "verifier_status"], (
        "『桩少给一个键 ⇒ `set(out)` 与契约不等 ⇒ 红』这条规则不成立的键变了："
        f"实测 {silently_refilled}，而上面那句注释逐字点名的是 "
        "['reason', 'verifier_status'] ⇒ 两处必须同时改"
    )


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

    # 防误伤：合法参数必须过。这里写的是 `checker_name` 而不是 `name` ——
    # 这条正控曾经拿 `name` 当合法键，于是它守的是一条谎（`R2b-AN-1-B`）：
    # `name` 从 schema 里被声明为合法 property，而两个 handler 都不收它
    # ⇒ `spec.handler(**merged)` 抛 TypeError、被兜成 kind='unexpected'
    # （一个会把人引向"库内部出错"的假 bug 分类，`R2b-AN-1-A`）。
    # 父代理裁定删掉 `name`，所以这里也不许再把它当合法参数。
    validate_params(schema, {"claim": "c", "source": "theorem t : True := trivial",
                             "checker_name": "t", "imports": ["Mathlib"], "timeout_sec": 1})
    # 旧名 `name` 现在必须被拒（它是"未声明的参数"，而不是"handler 收不下的参数"）
    # —— 通用判据（schema 的每个 property 都必须被 handler 签名接受）在
    # tests/test_schema_handler_params.py。
    with pytest.raises(ParamError):
        validate_params(schema, {"claim": "c", "name": "t"})

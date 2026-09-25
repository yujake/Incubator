"""`formalgw`（Lean 形式化验证后端）的判据。

## 全部离线，且夹具是构造样本

唯一接缝是 `run_fn`（`check_lean`）与 `probe_fn` / monkeypatch 后的探测层
（`detect_backend`）。本文件不装 Lean、不起任何外部进程。

本文件里的 Lean 输出全部是构造出来的字符串（形如
`'foo' depends on axioms: [propext]`）—— 它们是按 Lean 4 的输出形状手写的，
不是某次真实运行抓下来的。真实运行的证据只在装了 Lean 之后才存在，
见 `formalgw.selftest()` 打印的那一行探测结果。

## 这个文件守的到底是什么

`evidence_kind="proof"` 是真话还是谎话，全看这一层的四条硬判据有没有真的生效：
`sorry` 一出现就不算证明、公理超出允许集就不算证明、声明名没被检查到就不算证明、
超时是"没查成"而不是"证伪了"。所以每条判据都有独立用例，
外加三条"会红"的负控（它们恰恰是"只看退出码"时会静默通过的形态）。
"""

from __future__ import annotations

import hashlib

import pytest

from agentflow import formalgw as FG


def _run(exit_code: int = 0, stdout: str = "", stderr: str = "",
         timed_out: bool = False) -> dict:
    """构造一个假运行函数的返回值（形状与 `_default_run` 完全一致）。"""
    return {"exit_code": exit_code, "stdout": stdout, "stderr": stderr,
            "timed_out": timed_out}


def _runner(result: dict):
    def _fn(cmd, *, cwd, timeout_sec):  # noqa: ARG001 - 签名就是接缝契约
        return result

    return _fn


GOOD = "theorem one_plus_one : 1 + 1 = 2 := rfl\n"
CLEAN_OUT = "'one_plus_one' depends on axioms: [propext, Classical.choice, Quot.sound]\n"
NO_AXIOM_OUT = "'one_plus_one' does not depend on any axioms\n"


# ============================================================ 探测：三态


def _probe(names, *, checked=True, available=(), errors=(), reason="假探测"):
    return {"checked": checked, "available": list(available), "available_names": list(names),
            "probe_errors": list(errors), "reason": reason}


def test_detect_backend_available_reports_the_version():
    """正控：探到 lean ⇒ available，并把版本号带出来（版本决定输出形状）。"""
    out = FG.detect_backend(probe_fn=lambda: _probe(
        ["lean"], available=[{"name": "lean", "path": "/usr/bin/lean", "version": "Lean 4.7.0"}],
    ))
    assert out["status"] == "available"
    assert out["version"] == "Lean 4.7.0" and out["path"] == "/usr/bin/lean"
    assert out["checked"] is True


def test_detect_backend_no_backend_is_a_conclusion_not_a_failure():
    """`no_backend`：探测完成、确实没有 —— 这是一个有效结论。"""
    out = FG.detect_backend(probe_fn=lambda: _probe([]))
    assert out["status"] == "no_backend" and out["checked"] is True
    assert "没有 lean" in out["reason"]


def test_detect_backend_probe_failed_when_the_layer_says_so():
    """`probe_failed`：探测层报告 checked=False ⇒ 不是"没有后端"，是"不知道"。"""
    out = FG.detect_backend(probe_fn=lambda: _probe([], checked=False, errors=["which 炸了"]))
    assert out["status"] == "probe_failed"
    assert out["status"] != "no_backend", "没查成不许折叠成'环境里确定没有'"
    assert out["probe_errors"] == ["which 炸了"]


def test_detect_backend_probe_failed_when_the_probe_raises():
    """`probe_failed`：探测函数自己抛了。"""
    def _boom():
        raise OSError("PATH 读不出来")

    out = FG.detect_backend(probe_fn=_boom)
    assert out["status"] == "probe_failed"
    assert "OSError" in out["reason"]


def test_detect_backend_probe_failed_on_a_garbage_return():
    """探测层返回看不懂的东西 ⇒ 没有可信结论（不许当成"没有后端"）。"""
    out = FG.detect_backend(probe_fn=lambda: ["lean"])
    assert out["status"] == "probe_failed"


def test_production_path_really_calls_the_frozen_probe_layer(monkeypatch):
    """生产路径的接线证据：不注入 `probe_fn` 时真的去调禁改区里那一层。

    用 monkeypatch 换掉那一层的实现（而不是真起进程），所以这条用例仍然离线；
    它证明的是"接线在"，不是"环境里有 Lean"。
    """
    from agentflow.tools import verify_tools as VT

    monkeypatch.setattr(VT, "detect_verifier", lambda: _probe(
        ["lean"], available=[{"name": "lean", "path": "lean", "version": "Lean 4.x"}]))
    out = FG.detect_backend()
    assert out["status"] == "available" and out["version"] == "Lean 4.x"


# ============================================================ 受控词表


def test_status_vocabulary_is_controlled():
    """词表就是这八个；多一个少一个都要人来改这条断言。"""
    assert set(FG.STATUSES) == {
        "verified", "compile_error", "uses_sorry", "extra_axioms", "decl_mismatch",
        "timeout", "no_backend", "tool_crashed",
    }
    assert FG.PROOF_STATUS == "verified"


@pytest.mark.parametrize("status", FG.STATUSES)
def test_only_verified_may_produce_proof_level_evidence(status: str):
    """只有 `verified` 允许产出 proof 级证据；其余七个一律不给等级。"""
    ev = FG.evidence_of({"status": status})
    assert ev["proved"] is (status == "verified")
    assert ev["evidence_kind"] == ("proof" if status == "verified" else None)


def test_sorry_ax_is_on_the_forbidden_side():
    """`sorryAx` 必须落在禁止侧（否则它会被当成一条普通公理放过去）。"""
    assert "sorryAx" in FG.FORBIDDEN_AXIOMS
    assert "sorryAx" not in FG.ALLOWED_AXIOMS


# ============================================================ 八种 status


def test_status_verified():
    """正控：退出码 0、无 sorry、公理在允许集内、声明名被检查到。"""
    out = FG.check_lean(GOOD, name="one_plus_one", imports=(), run_fn=_runner(_run(0, CLEAN_OUT)))
    assert out["status"] == "verified"
    assert out["evidence"]["proved"] is True
    assert out["evidence"]["evidence_kind"] == "proof"
    assert out["decl_matches"] is True
    assert sorted(out["axioms"]) == ["Classical.choice", "Quot.sound", "propext"]
    assert out["exit_code"] == 0 and out["sorry_count"] == 0
    assert out["backend_version"] == ""


def test_status_compile_error():
    """退出码非零 ⇒ `compile_error`（与 timeout 分开）。"""
    out = FG.check_lean(GOOD, name="one_plus_one", imports=(),
                        run_fn=_runner(_run(1, "", "error: unknown tactic\n")))
    assert out["status"] == "compile_error"
    assert out["exit_code"] == 1
    assert out["evidence"]["evidence_kind"] is None


def test_status_uses_sorry_from_the_source():
    """含 sorry 的文件即使退出码 0 也判 `uses_sorry`。"""
    src = "theorem one_plus_one : 1 + 1 = 2 := by sorry\n"
    out = FG.check_lean(src, name="one_plus_one", imports=(), run_fn=_runner(_run(0, CLEAN_OUT)))
    assert out["status"] == "uses_sorry"
    assert out["sorry_count"] == 1
    assert out["evidence"]["evidence_kind"] is None


def test_status_uses_sorry_from_the_axiom_audit():
    """静态扫描看不见的 sorry（藏在被调用的引理里）由公理审计接住。"""
    out = FG.check_lean(GOOD, name="one_plus_one", imports=(), run_fn=_runner(
        _run(0, "'one_plus_one' depends on axioms: [sorryAx, propext]\n")))
    assert out["status"] == "uses_sorry"
    assert out["sorry_count"] == 0, "源码里确实没有 sorry —— 它来自引理"
    assert "sorryAx" in out["axioms"]


def test_status_compile_error_even_when_the_audit_shows_sorry_ax():
    """真编译失败（源码里没有 `sorry`）⇒ `compile_error`，不许写成 `uses_sorry`。

    判据顺序的负控。真实的 Lean 会这样：文件级 `#print axioms` 的输出里
    带出被 import 的 `sorryAx` 之类的痕迹，而这次检查其实根本没精化通过
    —— 实测 `theorem bad_one_eq_two : (1:Nat) = 2 := rfl` 报 type mismatch，
    而 `#print axioms` 照样打出 `[sorryAx]`。把那种残渣读成"这段证明里有一处
    被跳过了"，就把一次编译失败说成了另一件事（两者的处置完全不同）。

    `sorryAx` 仍然留在 `axioms` 里当线索，只是不改变状态名。
    """
    out = FG.check_lean(GOOD, name="one_plus_one", imports=(), run_fn=_runner(
        _run(1, "'one_plus_one' depends on axioms: [sorryAx]\n",
             "error: type mismatch\n")))
    assert out["status"] == "compile_error", out["reason"]
    assert out["status"] != "uses_sorry"
    assert out["exit_code"] == 1
    assert "sorryAx" in out["axioms"], "线索照留，只是不改变状态名"
    assert out["evidence"]["proved"] is False
    assert out["evidence"]["evidence_kind"] is None


def test_status_extra_axioms():
    """用到允许集之外的公理 ⇒ `extra_axioms`。"""
    out = FG.check_lean(GOOD, name="one_plus_one", imports=(), run_fn=_runner(
        _run(0, "'one_plus_one' depends on axioms: [propext, MyAxiom]\n")))
    assert out["status"] == "extra_axioms"
    assert out["axioms"] == ["propext", "MyAxiom"]


def test_status_decl_mismatch_when_the_name_is_not_in_the_file():
    """文件里没有那个声明 ⇒ 不必起进程就能判 `decl_mismatch`。"""
    out = FG.check_lean(GOOD, name="some_other_theorem", imports=(),
                        run_fn=_runner(_run(0, CLEAN_OUT)))
    assert out["status"] == "decl_mismatch"
    assert out["declared_in_source"] is False
    assert out["exit_code"] is None, "静态判据在起进程之前就下结论"


def test_status_decl_mismatch_when_the_output_never_mentions_it():
    """编译过了、输出里却没有被检查到的名字 ⇒ 仍判 `decl_mismatch`（fail-closed）。"""
    out = FG.check_lean(GOOD, name="one_plus_one", imports=(), run_fn=_runner(_run(0, "")))
    assert out["status"] == "decl_mismatch"
    assert out["declared_in_source"] is True and out["decl_matches"] is False


def test_status_timeout():
    """超时 ⇒ `timeout`（`exit_code` 为 None，半截输出照样带回来）。"""
    out = FG.check_lean(GOOD, name="one_plus_one", imports=(), timeout_sec=1,
                        run_fn=_runner(_run(None, "elaborating…", timed_out=True)))
    assert out["status"] == "timeout"
    assert out["exit_code"] is None and out["stdout"] == "elaborating…"
    assert out["evidence"]["checked"] is False


def test_status_no_backend_when_the_binary_vanished():
    """探测说有后端、真跑时二进制不在 ⇒ `no_backend`（不是验证失败）。"""
    def _gone(cmd, *, cwd, timeout_sec):  # noqa: ARG001 - 接缝契约
        raise FileNotFoundError("lean: not found")

    out = FG.check_lean(GOOD, name="one_plus_one", imports=(), run_fn=_gone)
    assert out["status"] == "no_backend"


def test_status_no_backend_via_the_real_probe_path(monkeypatch):
    """不注入 `run_fn` 时走真探测：探测说没有 Lean ⇒ `no_backend`，且不起任何进程。"""
    from agentflow.tools import verify_tools as VT

    monkeypatch.setattr(VT, "detect_verifier", lambda: _probe([]))
    out = FG.check_lean(GOOD, name="one_plus_one", imports=())
    assert out["status"] == "no_backend"
    assert out["evidence"]["checked"] is False
    assert out["exit_code"] is None


def test_status_tool_crashed_on_probe_failure(monkeypatch):
    """探测没做成 ⇒ `tool_crashed`（"没查成"），绝不是通过也不是证伪。"""
    from agentflow.tools import verify_tools as VT

    monkeypatch.setattr(VT, "detect_verifier", lambda: _probe([], checked=False,
                                                             errors=["which 炸了"]))
    out = FG.check_lean(GOOD, name="one_plus_one", imports=())
    assert out["status"] == "tool_crashed"


def test_status_tool_crashed_on_a_broken_runner():
    """运行函数抛别的异常、或返回看不懂的东西 ⇒ `tool_crashed`。"""
    def _boom(cmd, *, cwd, timeout_sec):  # noqa: ARG001 - 接缝契约
        raise RuntimeError("pipe 断了")

    assert FG.check_lean(GOOD, name="one_plus_one", imports=(),
                         run_fn=_boom)["status"] == "tool_crashed"
    assert FG.check_lean(GOOD, name="one_plus_one", imports=(),
                         run_fn=_runner("not a dict"))["status"] == "tool_crashed"


# ============================================================ 四条硬判据


def test_hard_criterion_sorry_compiles_but_is_not_a_proof():
    """判据①：含 `sorry` 且退出码 0 的文件不许判 `verified`。

    Lean 里含 `sorry` 的文件会正常编译通过（退出码 0）—— 退出码本身
    无法区分"证完了"与"跳过了"。这条用例就是那个区分的唯一防线。
    """
    src = "theorem t : 1 = 1 := by\n  sorry\n"
    out = FG.check_lean(src, name="t", imports=(), run_fn=_runner(_run(0, CLEAN_OUT)))
    assert out["status"] == "uses_sorry" and out["status"] != "verified"
    assert out["evidence"]["evidence_kind"] is None


def test_hard_criterion_axiom_audit_rejects_a_nonstandard_axiom():
    """判据②：公理审计必须比对允许集，超出即 `extra_axioms`。"""
    out = FG.check_lean(GOOD, name="one_plus_one", imports=(), run_fn=_runner(
        _run(0, "'one_plus_one' depends on axioms: [Classical.choice, MyAxiom, AnotherOne]\n")))
    assert out["status"] == "extra_axioms" and out["status"] != "verified"
    assert "MyAxiom" in out["reason"] and "AnotherOne" in out["reason"]


def test_hard_criterion_decl_name_must_be_seen():
    """判据③：退出码 0 但声明名对不上 ⇒ `decl_mismatch`。两种形态都覆盖。"""
    missing = FG.check_lean(GOOD, name="wrong_name", imports=(), run_fn=_runner(_run(0, CLEAN_OUT)))
    assert missing["status"] == "decl_mismatch"
    silent = FG.check_lean(GOOD, name="one_plus_one", imports=(), run_fn=_runner(_run(0, "")))
    assert silent["status"] == "decl_mismatch"


def test_hard_criterion_timeout_is_not_a_compile_error_and_not_a_pass():
    """判据④：`timeout` 与 `compile_error` 必须分开，且都不是通过。"""
    t = FG.check_lean(GOOD, name="one_plus_one", imports=(), timeout_sec=3,
                      run_fn=_runner(_run(None, "", "", timed_out=True)))
    c = FG.check_lean(GOOD, name="one_plus_one", imports=(),
                      run_fn=_runner(_run(1, "", "error")))
    assert t["status"] == "timeout" and c["status"] == "compile_error"
    assert t["exit_code"] is None and c["exit_code"] == 1
    assert t["evidence"]["checked"] is False, "超时是没查成"


# ============================================================ 负控（会红）


@pytest.mark.parametrize("label,src,raw", [
    ("含 sorry 且退出码 0", "theorem t : 1 = 1 := by sorry\n", _run(0, CLEAN_OUT)),
    ("出现额外公理", GOOD, _run(0, "'t' depends on axioms: [MyAxiom]\n")),
    ("退出码 0 但声明名对不上", GOOD, _run(0, "")),
])
def test_three_negative_controls_never_reach_proof(label: str, src: str, raw: dict):
    """三条会红的负控：只看退出码时它们都会被静默判成"证明通过"。

    `label` 进断言消息，好让失败时一眼看出是哪一条装置失灵了。
    """
    out = FG.check_lean(src, name="t", imports=(), run_fn=_runner(raw))
    assert out["status"] != "verified", f"负控失效（{label}）：{out['status']}"
    assert out["evidence"]["evidence_kind"] is None, f"负控失效（{label}）"
    assert out["evidence"]["proved"] is False


# ============================================================ 文件与产物


def test_the_checked_file_contains_imports_the_source_and_the_audit_command():
    """交给检查器的文件必须能由产物逐字复核：imports + 源码 + `#print axioms <name>`。"""
    from pathlib import Path

    seen: dict[str, str] = {}

    def _spy(cmd, *, cwd, timeout_sec):  # noqa: ARG001 - 接缝契约
        seen["path"] = cmd[1]
        seen["text"] = Path(cmd[1]).read_text(encoding="utf-8")
        return _run(0, CLEAN_OUT)

    out = FG.check_lean(GOOD, name="one_plus_one", imports=("Mathlib", "Mathlib.Tactic"),
                        run_fn=_spy)
    assert out["status"] == "verified"
    assert seen["text"] == out["checked_source"]
    assert seen["text"].startswith("import Mathlib\nimport Mathlib.Tactic\n")
    assert "#print axioms one_plus_one" in seen["text"]
    assert GOOD.rstrip("\n") in seen["text"]


def test_source_sha256_covers_the_claimed_source():
    """`source_sha256` 是"声称要证的那段源码"的哈希（不是包装文件的）。"""
    out = FG.check_lean(GOOD, name="one_plus_one", imports=(), run_fn=_runner(_run(0, CLEAN_OUT)))
    assert out["source_sha256"] == hashlib.sha256(GOOD.encode("utf-8")).hexdigest()


def test_the_declaration_is_never_audited_when_it_does_not_exist():
    """没有那个声明时不追 `#print axioms`：否则检查器报的是语法错，
    而那个错误会被读成"证明没过"。"""
    out = FG.check_lean(GOOD, name="nope", imports=(), run_fn=_runner(_run(0, "")))
    assert out["status"] == "decl_mismatch"
    assert out["checked_source"] == "", "静态判据在拼文件之前就下结论"


def test_a_bad_name_is_rejected_instead_of_being_guessed():
    """名字非法 ⇒ 抛（不许编一个再报"证明没过"）。"""
    for bad in ("", "   ", "foo bar"):
        with pytest.raises(ValueError, match="name"):
            FG.check_lean(GOOD, name=bad, imports=(), run_fn=_runner(_run(0, CLEAN_OUT)))


def test_timeout_and_elapsed_are_recorded():
    """`elapsed_sec` 与超时秒数都进产物（不然"跑了多久"无从复核）。"""
    out = FG.check_lean(GOOD, name="one_plus_one", imports=(), timeout_sec=0.5,
                        run_fn=_runner(_run(None, "", "", timed_out=True)))
    assert out["elapsed_sec"] >= 0.0
    assert "0.5" in out["reason"]


# ============================================================ 片段解析


def test_lean_snippets_and_declaration_name():
    """片段与声明名的解析：只认 `lean` 标注的代码块，别的语言不误收。"""
    text = "结论如下\n\n```lean\ntheorem foo (n : Nat) : n + 0 = n := by simp\n```\n"
    text += "\n```python\nprint('not lean')\n```\n"
    snaps = FG.lean_snippets(text)
    assert len(snaps) == 1 and snaps[0]["name"] == "foo"
    assert "theorem foo" in snaps[0]["source"]
    assert FG.lean_snippets("没有代码块") == []


def test_example_has_no_declaration_name():
    """`example` 没有名字 ⇒ 取不到名字（调用方不得把它当成"证了某个东西"）。"""
    assert FG.declaration_name("example : 1 + 1 = 2 := rfl\n") == ""
    assert FG.declaration_name("noncomputable def bar : Nat := 0\n") == "bar"


def test_comments_and_strings_do_not_count_as_sorry():
    """注释里的 `sorry` 与字符串里的 `sorry` 都不是"用了 sorry"。"""
    src = (
        "-- 这里不用 sorry\n"
        "/- 也不在这里\n   sorry\n-/\n"
        'def msg : String := "sorry"\n'
        "theorem t : 1 = 1 := rfl\n"
    )
    out = FG.check_lean(src, name="t", imports=(), run_fn=_runner(_run(0, NO_AXIOM_OUT)))
    assert out["status"] == "verified", out["reason"]
    assert out["sorry_count"] == 0


def test_the_module_selftest_passes_offline():
    """`python -m agentflow.formalgw` 的离线部分必须以 0 结束。"""
    assert FG.selftest() == 0

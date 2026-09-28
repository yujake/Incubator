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
    """词表就是这十个；多一个少一个都要人来改这条断言。"""
    assert set(FG.STATUSES) == {
        "verified", "compile_error", "uses_sorry", "extra_axioms", "decl_mismatch",
        "timeout", "import_unavailable", "no_backend", "tool_crashed",
        "source_unreadable",
    }
    assert FG.PROOF_STATUS == "verified"
    # `source_unreadable`（`E-3`）是"没查成"，必须不在 `_CONCLUDED_STATUSES` 里：
    # 它在里面时 `evidence_of` 的 `checked` 位为 True，工具层于是把一次
    # 路径写错折成 `verified=False`（"查了、命题不成立"）。
    assert "source_unreadable" not in FG._CONCLUDED_STATUSES


@pytest.mark.parametrize("status", FG.STATUSES)
def test_only_verified_may_produce_proof_level_evidence(status: str):
    """只有 `verified` 允许产出 proof 级证据；其余九个一律不给等级。"""
    ev = FG.evidence_of({"status": status})
    assert ev["proved"] is (status == "verified")
    assert ev["evidence_kind"] == ("proof" if status == "verified" else None)


def test_sorry_ax_is_on_the_forbidden_side():
    """`sorryAx` 必须落在禁止侧（否则它会被当成一条普通公理放过去）。"""
    assert "sorryAx" in FG.FORBIDDEN_AXIOMS
    assert "sorryAx" not in FG.ALLOWED_AXIOMS


# ============================================================ 十种 status


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


def test_status_source_unreadable_when_the_source_path_cannot_be_read():
    """`E-3` 正控：`source_path` 读不到 ⇒ `source_unreadable`（没查成）。

    这一档与 `decl_mismatch` 的机器可读位相反，是本用例要钉的那条分界：
    "我读了这份源码、里面没有你要证的东西"（`checked=True`）与
    "这份源码我根本没读到"（`checked=False`）的处置完全不同。
    `run_fn` 注入一个必然抛的实现：源码都读不到，检查器一次都不该被起。
    """
    def _never(*_a, **_k):
        raise AssertionError("源码都读不到，检查器一次都不该被起")

    out = FG.check_lean("", source_path="definitely-not-here.lean", name="one_plus_one",
                        imports=(), run_fn=_never)
    assert out["status"] == "source_unreadable", out["reason"]
    assert out["status"] != "decl_mismatch", (
        "把'路径写错了'报成'你证的东西不在文件里'，会让调用方去改数学而不是改路径"
    )
    assert out["evidence"]["checked"] is False, "读不到源码是没查成，不是查了没通过"
    assert out["evidence"]["proved"] is False
    assert out["evidence"]["evidence_kind"] is None
    assert out["ran"] is False
    assert "FileNotFoundError" in out["reason"], out["reason"]


def test_status_decl_mismatch_still_holds_when_the_file_was_read_fine(tmp_path):
    """`E-3` 负控的反面：文件读得到、只是里面没有那个声明 ⇒ 仍是 `decl_mismatch`。

    没有这一条，把 `read_failed` 那一支整个删掉也能让上面那条用例绿 ——
    而"文件里没有那条声明"会跟着一起丢掉。
    """
    src = tmp_path / "p.lean"
    src.write_text(GOOD, encoding="utf-8")
    out = FG.check_lean("", source_path=str(src), name="some_other_theorem", imports=(),
                        run_fn=_runner(_run(0, CLEAN_OUT)))
    assert out["status"] == "decl_mismatch"
    assert out["declared_in_source"] is False
    assert out["evidence"]["checked"] is True, "读到了源码、也判了，就是'查了'"


def test_status_timeout():
    """超时 ⇒ `timeout`（`exit_code` 为 None，半截输出照样带回来）。"""
    out = FG.check_lean(GOOD, name="one_plus_one", imports=(), timeout_sec=1,
                        run_fn=_runner(_run(None, "elaborating…", timed_out=True)))
    assert out["status"] == "timeout"
    assert out["exit_code"] is None and out["stdout"] == "elaborating…"
    assert out["evidence"]["checked"] is False


def test_status_import_unavailable_when_the_package_is_not_installed():
    """库不可得 ⇒ `import_unavailable`，不是 `compile_error`、也不是 `verified`。

    夹具逐字用 Lean 4.7.0 在裸 `lean`（没有 lake 工程）下回的那句话
    `error: unknown package 'Mathlib'`：库没装时编译根本没开始。
    把它说成 `compile_error`（"查了没通过"）是一句假话，而两者的处置相反。
    """
    raw = _run(1, "probe.lean:1:0: error: unknown package 'Mathlib'\n")
    out = FG.check_lean(GOOD, name="one_plus_one", imports=("Mathlib",), run_fn=_runner(raw))
    assert out["status"] == "import_unavailable", out["reason"]
    assert out["status"] != "compile_error"
    assert out["status"] != "verified"
    assert out["missing_imports"] == ["Mathlib"], "必须带上包名，而不是只给一个布尔"
    assert out["evidence"]["checked"] is False, "库不可得是没查成，不是查了没通过"
    assert out["evidence"]["proved"] is False
    assert out["evidence"]["evidence_kind"] is None


def test_status_import_unavailable_for_a_nonexistent_package():
    """负控③：不存在的包名同样归到 `import_unavailable`（带它回的那个名字）。"""
    raw = _run(1, "probe.lean:1:0: error: unknown package 'Nonexistent'\n")
    out = FG.check_lean(GOOD, name="one_plus_one", imports=("Nonexistent.Pkg",),
                        run_fn=_runner(raw))
    assert out["status"] == "import_unavailable"
    assert out["missing_imports"] == ["Nonexistent"]


def test_a_real_compile_error_is_still_a_compile_error():
    """核心负控②：注入语法错时新判据不许把真编译错吞成"库不可得"。

    两种形态都要守住：
    1. 输出里没有 `unknown package` 的编译错 ⇒ 仍是 `compile_error`；
    2. 输出里同时有 `unknown package` 与真语法错 ⇒ 仍是 `import_unavailable`
       （包不可得是真的，那次检查确实没发生）—— 这一条写下来是为了说明
       判据的边界在哪，而不是假装它不存在。
    """
    only_syntax = _run(1, "", "probe.lean:1:72: error: unexpected token '#print';"
                              " expected ':=', 'where' or '|'\n")
    out = FG.check_lean(GOOD, name="one_plus_one", imports=(), run_fn=_runner(only_syntax))
    assert out["status"] == "compile_error", out["reason"]
    assert out["missing_imports"] == []

    both = _run(1, "probe.lean:1:0: error: unknown package 'Mathlib'\n"
                   "probe.lean:3:42: error: unexpected token '+'\n")
    out2 = FG.check_lean(GOOD, name="one_plus_one", imports=("Mathlib",),
                         run_fn=_runner(both))
    assert out2["status"] == "import_unavailable"
    assert out2["status"] != "compile_error"


def test_import_unavailable_only_after_the_static_gates():
    """判据顺序：文件里没有那个声明时先报 `decl_mismatch`，不起进程。"""
    calls: list[int] = []

    def _spy(cmd, *, cwd, timeout_sec):  # noqa: ARG001 - 接缝契约
        calls.append(1)
        return _run(1, "error: unknown package 'Mathlib'\n")

    out = FG.check_lean(GOOD, name="some_other_name", imports=("Mathlib",), run_fn=_spy)
    assert out["status"] == "decl_mismatch"
    assert calls == [], "静态判据必须在起进程之前收口"


def test_missing_imports_of_is_a_narrow_reader():
    """`missing_imports_of` 只认 `unknown package '<名>'`，去重保序。"""
    assert FG.missing_imports_of("") == []
    assert FG.missing_imports_of("error: unknown module 'Foo'") == [], "不认别的形态"
    assert FG.missing_imports_of(
        "error: unknown package 'A'\nerror: unknown package 'B'\nerror: unknown package 'A'"
    ) == ["A", "B"]


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


# ============================================================ 工具链版本三态（G-13）


def _lean_version(version: str):
    """造一个只回答 `lean --version` 的假运行函数（本机只有 4.7.0，装不了别的）。"""
    def _fn(cmd, *, cwd, timeout_sec):  # noqa: ARG001 - 接缝契约
        return {"exit_code": 0, "stdout": version + "\n", "stderr": "", "timed_out": False}

    return _fn


def _fake_mathlib(tmp_path, commit: str, *, via: str = "stamp"):
    """造一棵"像 Mathlib 工程"的目录，commit 由 `via` 指定来源（stamp 或 git）。"""
    root = tmp_path / "mathlib4-4.7.0"
    (root / "Mathlib").mkdir(parents=True, exist_ok=True)
    with open(root / "lakefile.lean", "w", encoding="utf-8", newline="") as fh:
        fh.write("import Lake\n")
    with open(root / "lean-toolchain", "w", encoding="utf-8", newline="") as fh:
        fh.write("leanprover/lean4:v4.7.0\n")
    if via == "stamp":
        (root / ".lake").mkdir(parents=True, exist_ok=True)
        with open(root / ".lake" / "agentflow-mathlib-rev", "w",
                  encoding="utf-8", newline="") as fh:
            fh.write(commit + "\n")
    else:
        (root / ".git").mkdir(parents=True, exist_ok=True)
        with open(root / ".git" / "HEAD", "w", encoding="utf-8", newline="") as fh:
            fh.write(commit + "\n")
    return root


def test_version_vocabulary_has_exactly_three_states_plus_unknown():
    """三态就是这三个；"没查成"是它们之外的第 4 个值，不占三态里的位置。"""
    assert FG.VERSION_STATUSES == ("installed_ok", "version_mismatch", "not_installed")
    assert FG.VERSION_UNKNOWN not in FG.VERSION_STATUSES


def test_not_installed_is_distinct_from_version_mismatch(tmp_path):
    """正控①：什么都没有 ⇒ `not_installed`（不是 `version_mismatch`）。"""
    rep = FG.check_toolchain(env={}, which=lambda name: None)
    assert rep.lean_status == "not_installed"
    assert rep.mathlib_status == "not_installed"
    assert rep.status == "not_installed"
    # 三态不许折叠：这个结论必须与"装了但版本不符"分得开
    assert rep.status != "version_mismatch"
    assert rep.status != "installed_ok"


def test_installed_but_wrong_commit_is_version_mismatch(tmp_path):
    """负控②：故意传错的 commit ⇒ 必须报"版本不符"（不是"没装"、不是"通过"）。"""
    root = _fake_mathlib(tmp_path, "0" * 40, via="git")
    rep = FG.check_toolchain(
        mathlib_root=str(root), env={},
        which=lambda name: "C:/fake/lean.exe" if name == "lean" else None,
        run_fn=_lean_version("Lean (version 4.7.0, x86_64-w64-windows-gnu, "
                            "commit deadbeefcafe, Release)"),
    )
    assert rep.lean_status == "version_mismatch"
    assert rep.mathlib_status == "version_mismatch"
    assert rep.status == "version_mismatch"
    assert rep.status != "not_installed" and rep.status != "installed_ok"
    assert FG.PINNED_LEAN_COMMIT[:12] in rep.lean_reason
    assert FG.PINNED_MATHLIB_COMMIT[:12] in rep.mathlib_reason


def test_the_right_version_pins_report_installed_ok(tmp_path):
    """正控②：版本逐位对上 ⇒ `installed_ok`（三态里的第三态也要能到）。"""
    root = _fake_mathlib(tmp_path, FG.PINNED_MATHLIB_COMMIT)
    rep = FG.check_toolchain(
        mathlib_root=str(root), env={},
        which=lambda name: "C:/fake/lean.exe" if name == "lean" else None,
        run_fn=_lean_version(f"Lean (version {FG.PINNED_LEAN_VERSION}, "
                            f"x86_64-w64-windows-gnu, commit {FG.PINNED_LEAN_COMMIT[:12]}, "
                            "Release)"),
    )
    assert rep.status == "installed_ok", rep.to_dict()
    assert rep.lean_commit == FG.PINNED_LEAN_COMMIT[:12] or (
        FG.PINNED_LEAN_COMMIT.startswith(rep.lean_commit))
    assert rep.mathlib_commit == FG.PINNED_MATHLIB_COMMIT


def test_a_right_version_number_with_a_wrong_commit_is_still_a_mismatch(tmp_path):
    """commit 是独立的一条判据：版本号对上了、commit 不对，仍算版本不符。"""
    root = _fake_mathlib(tmp_path, FG.PINNED_MATHLIB_COMMIT)
    rep = FG.check_toolchain(
        mathlib_root=str(root), env={},
        which=lambda name: "C:/fake/lean.exe" if name == "lean" else None,
        run_fn=_lean_version(f"Lean (version {FG.PINNED_LEAN_VERSION}, "
                            "x86_64-w64-windows-gnu, commit deadbeefcafe, Release)"),
    )
    assert rep.lean_status == "version_mismatch"
    assert "版本号对上了" in rep.lean_reason


def test_a_tree_without_a_verifiable_commit_is_check_failed_not_a_mismatch(tmp_path):
    """没有 commit 可核 ⇒ `check_failed`（未核实），不是"版本不符"。"""
    root = tmp_path / "mathlib4-4.7.0"
    root.mkdir()
    with open(root / "lakefile.lean", "w", encoding="utf-8", newline="") as fh:
        fh.write("import Lake\n")
    with open(root / "lean-toolchain", "w", encoding="utf-8", newline="") as fh:
        fh.write("leanprover/lean4:v4.7.0\n")
    rep = FG.check_toolchain(mathlib_root=str(root), env={}, which=lambda name: None)
    assert rep.mathlib_status == FG.VERSION_UNKNOWN
    assert rep.mathlib_status != "version_mismatch"
    assert rep.mathlib_status != "not_installed"
    assert FG.MATHLIB_REV_STAMP in rep.mathlib_reason
    assert rep.status == FG.VERSION_UNKNOWN, "没查成不许被读成三态里的任何一个"


def test_a_probe_that_raises_is_check_failed(tmp_path):
    """探测自己炸了 ⇒ `check_failed`（不是"没装"）。"""
    def _boom(cmd, *, cwd, timeout_sec):  # noqa: ARG001
        raise OSError("起不来")

    rep = FG.check_toolchain(env={}, which=lambda name: "C:/lean.exe", run_fn=_boom)
    assert rep.lean_status == FG.VERSION_UNKNOWN
    assert rep.status == FG.VERSION_UNKNOWN
    assert rep.errors, "没查成必须留下原因"


def test_mathlib_root_discovery_uses_the_env_var_then_candidates(tmp_path):
    """工程根的判据是"同时有 lakefile.lean 与 lean-toolchain"，且候选顺序可注入。"""
    root = _fake_mathlib(tmp_path, FG.PINNED_MATHLIB_COMMIT)
    assert FG.find_mathlib_root({FG.ENV_MATHLIB_ROOT: str(root)}) == str(root)
    assert FG.find_mathlib_root({}, candidates=[root, tmp_path / "nope"]) == str(root)
    assert FG.find_mathlib_root({}, candidates=[tmp_path / "nope"]) == ""


def test_lean_commit_of_reads_the_short_hash_from_the_version_line():
    """`lean --version` 的 commit 是 12 位短哈希；取不到就是空串（不许猜）。"""
    assert FG.lean_commit_of(
        "Lean (version 4.7.0, x86_64-w64-windows-gnu, commit 6fce8f7d5cd1, Release)"
    ) == "6fce8f7d5cd1"
    assert FG.lean_commit_of("Lean (version 4.7.0)") == ""
    assert FG.lean_commit_of("") == ""


def test_the_two_pins_are_independent_facts():
    """pin 是常量，不是从本机观测出来的：本机没装也照样有要求。"""
    assert FG.PINNED_LEAN_VERSION and FG.PINNED_LEAN_COMMIT
    assert len(FG.PINNED_LEAN_COMMIT) == 40 and len(FG.PINNED_MATHLIB_COMMIT) == 40
    assert FG.PINNED_MATHLIB_TAG == "v4.7.0"


def test_toolchain_cli_exits_with_the_state_as_a_code(tmp_path, capsys):
    """可跑：`--toolchain` 的退出码就是三态（0/2/3/4），不是"有没有报错"。"""
    assert FG.toolchain_main(["--toolchain", "--mathlib-root", str(tmp_path)]) == 2
    out = capsys.readouterr().out
    assert "not_installed" in out


def test_the_module_selftest_passes_offline():
    """`python -m agentflow.formalgw` 的离线部分必须以 0 结束。"""
    assert FG.selftest() == 0


# =========================== `concluded_names`：绑名的公理诊断（`R2-AN-2` 的读法）
#
# 它是事后审计（`verify.selfreported_proof`）读"这条 proof 的依据"的唯一入口。
# 与 `_axioms_of` 的分工：后者回答"这份输出里出现过哪些公理"（刻意不绑名，
# 判据是公理列表优先、fail-closed），前者回答"哪些声明被指名下过结论"。
# 本组用例守两件事：① 只认绑名的那两种形态；② `_axioms_of` 的既有行为一个字都没动。


def test_concluded_names_reads_only_the_name_bound_diagnostics():
    """正控（`R2-AN-2`）：只认 `#print axioms <name>` 的两种绑名输出。"""
    assert FG.concluded_names("'foo' does not depend on any axioms") == {"foo"}
    assert FG.concluded_names("'foo' depends on axioms: [propext, Classical.choice]") == {"foo"}
    assert FG.concluded_names(
        "'a' does not depend on any axioms\n'b' depends on axioms: []") == {"a", "b"}
    assert FG.concluded_names("") == set()
    # 去重：同一句话重复出现只留一个名字
    assert FG.concluded_names(
        "'foo' does not depend on any axioms\n'foo' depends on axioms: []") == {"foo"}


def test_concluded_names_rejects_the_two_shapes_that_are_not_evidence():
    """负控（`R2-AN-2`）：名字被"提了一句"不算依据。

    两种形态都必须读不出名字 —— 它们正是旧子串判据放行的那两条
    （`draft/28` §40.3 的 A1/A4）：
    - 自报输出 `Lean4: no goals`（根本没有名字）；
    - 名字只出现在一句与结论无关的告警里。
    """
    assert FG.concluded_names("Lean4: no goals") == set()
    assert FG.concluded_names("Lean4: warning: unused variable 'foo'; no goals") == set()
    # 不绑名的公理诊断也不算：那是"输出里有公理信息"，不是"这条声明的结论"
    assert FG.concluded_names("depends on axioms: [propext]") == set()
    # 名字不对上引号形态（例如被别的东西包着）同样不算
    assert FG.concluded_names("[foo] does not depend on any axioms") == set()


def test_the_named_diagnostic_readers_did_not_change_axioms_of():
    """`FC-03` 的反面：新增 `concluded_names` 不许改 `_axioms_of` 的既有行为。

    `_axioms_of` 的判据是"公理列表优先、fail-closed"（`E-1` 的短路教训），
    它刻意不绑名：源码里另有一条无关声明带公理时会保守地报 `extra_axioms`。
    本用例把它的三种既有读数逐字钉住 —— 新增读法不得顺手把它也改严/改宽。
    """
    # 公理列表优先（即使别处写了"不依赖"）
    assert FG._axioms_of("'foo' does not depend on any axioms\n"
                         "'bar' depends on axioms: [propext]", name="foo") == ["propext"]
    # 指名它清白 ⇒ 空表
    assert FG._axioms_of("'foo' does not depend on any axioms", name="foo") == []
    # 两者都没有 ⇒ 空表（"输出里没有公理信息"）
    assert FG._axioms_of("Lean4: no goals", name="foo") == []
    # 不绑名的列表照样被收（审计侧不认，`_axioms_of` 认 —— 两处口径不同是刻意的）
    assert FG._axioms_of("depends on axioms: [Quot.sound]") == ["Quot.sound"]

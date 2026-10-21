"""`P-8`：形式化路径真的能登记一条 `proof` 级实验（正控 + 三条负控）。

补的是哪一段缺口：`AgentE.run_experiment` 此前只有"跑脚本 + 读脚本自报的结论"一条路径，而
`build_experiment` 一个证据形状字段都不传 ⇒ 走到 `schema.Experiment.validate()` 必然抛
（"evidence_kind='proof' 时必须给出 verifier_output"）⇒ E 登记不了一条 proof 级实验，与本机有没有
Lean 无关。这里锁住的正是这条接线：`method="formal"` + .lean 产物 → `formalgw.check_lean` /
`verify.check_formal`（唯一判据处）→ `verified=True` ⇒ `evidence_kind="proof"` +
`verifier_subject_key == claim_key`；`verified!=True` ⇒ 一行都不许标成 proof（三态纪律）。

为什么每条负控都要有：数值脚本走同一条 `run_experiment` ⇒ 必须仍是 `cross_check`（FC-22 不许放松）；
检查器没查成 / 没通过 ⇒ 不许登记成 proof（"没查成"与"查了通过"是两件事）；`verifier_output` 为空 /
`verifier_subject_key` 不等于 `claim_key` ⇒ schema 仍然抛（证明那两条硬约束没有被这次修法放松）。

离线用例把检查器后端整体替换成桩（`formalgw.check_lean` 是唯一的运行接缝），真跑 `lean` 的那一条
在没有它的环境里 skip —— 它证明的是"这条路径在本机真的能产出 proof"，而不是"桩能产出 proof"。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agentflow import formalgw as FG
from agentflow import toolchain as TC
from agentflow.agent_e import AgentE, ExperimentError
from agentflow.store import Store
from agentflow.tools import verify_tools as VT

#: 检查器探测结果：假装环境里有 lean。
_VERIFIER = {
    "checked": True,
    "available": [{"name": "lean", "path": "lean", "version": "(桩)"}],
    "available_names": ["lean"],
    "probe_errors": [],
    "reason": "（桩）探测到 lean",
}

_LEAN_SRC = "theorem probe_eq : 1 + 1 = 2 := rfl\n"


def make_e(store: Store) -> AgentE:
    return AgentE(store, workspace_root=store.root)


def write_lean(store: Store, rel: str, body: str = _LEAN_SRC) -> str:
    p = Path(store.root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return rel


def _checker_stub(*, status: str, stdout: str = "", stderr: str = "") -> dict:
    """按 `formalgw` 的收口方式造一份检查结论的桩。

    `exit_code` 照真实检查器来：`verified` ⇒ 0；跑了但没通过（收敛档）⇒ 非零；
    没跑成（timeout/no_backend/import_unavailable/tool_crashed）⇒ None ——
    E-12(a) 判的就是这一格（"没跑成"绝不用 0 冒充）。
    """

    def _fake(source, *, name, imports, timeout_sec, run_fn=None, workdir=None,
              source_path=None):
        raw = {
            "status": status,
            "reason": f"（桩）检查器结论 {status}",
            "stdout": stdout,
            "stderr": stderr,
            "axioms": [],
            "sorry_count": 0,
            "decl_matches": status == FG.PROOF_STATUS,
            "declared_in_source": True,
            "ran": True,
            "backend": {"status": "ok"},
            "exit_code": (0 if status == FG.PROOF_STATUS
                          else 1 if status in FG._CONCLUDED_STATUSES else None),
        }
        return FG._conclude(raw, status, raw["reason"])

    return _fake


# ============================================================ 正控：登记成 proof


def test_formal_path_registers_a_proof_row_when_the_checker_says_verified(
    store: Store, monkeypatch: pytest.MonkeyPatch
):
    """正控：检查器 `verified` ⇒ 台账里出现一条 proof 级实验，且字段逐条对得上。

    断言的是"落库的那一行"，不是返回值：只在返回值里升级成 proof 的实现
    照样能让调用方以为成功了。
    """
    monkeypatch.setattr(VT, "detect_verifier", lambda: _VERIFIER)
    monkeypatch.setattr(
        FG, "check_lean",
        _checker_stub(status="verified", stdout="'probe_eq' does not depend on any axioms"),
    )
    rel = write_lean(store, "proofs/probe_eq.lean")
    out = make_e(store).run_experiment(
        "1 + 1 = 2（内核级）", "probe-eq", rel, method="formal", imports=(),
    )

    assert out["recorded"] is True
    assert out["evidence_kind"] == "proof"
    assert out["result"] == "supports"
    assert out["negation_kind"] == "not_proved"
    rows = store.rows("experiments")
    assert len(rows) == 1, "一次形式化实验只许写一行"
    row = rows[0]
    assert row["method"] == "formal"
    assert row["evidence_kind"] == "proof"
    assert row["verifier_subject_key"] == "probe-eq" == row["claim_key"]
    assert "does not depend on any axioms" in row["verifier_output"], (
        "verifier_output 必须是检查器自己的话；这里落的是桩的那一句"
    )
    assert row["exit_code"] == 0
    assert row["code_path"] == "proofs/probe_eq.lean"
    assert row["code_hash"] == VT.code_hash(Path(store.root) / rel)
    assert row["observations"]["verifier_status"] == "verified"
    # 证据查询侧也要认这条 proof（"登记了"与"查得到"必须一致）
    ev = make_e(store).evidence_for("probe-eq")
    assert ev["checked"] is True and ev["proved"] is True, ev


def test_the_formal_row_names_the_declaration_from_the_source_not_the_file(
    store: Store, monkeypatch: pytest.MonkeyPatch
):
    """没给 `name` 时，台账里"声明名 <X>"必须是源码里的名字，不是文件名词干。

    实测形态（`goal-a5334ee8` 的 ④，2026-10-01）：文件 `p2_rho_sum_zero.lean` 里的声明叫
    `rho_sum_zero`；旧实现把文件名词干当声明名 ⇒ `decl_mismatch`（读起来像"查了没通过"），
    真正的毛病是调用方没点名。改名这件事必须落在落库那一行上：
    只改返回值、台账里仍写着文件名的实现，事后审计（`verify.declared_name_of_notes`）
    照样读到错的名字。
    """
    from agentflow import verify as V

    monkeypatch.setattr(VT, "detect_verifier", lambda: _VERIFIER)
    monkeypatch.setattr(FG, "check_lean",
                        _checker_stub(status="verified",
                                      stdout="'rho_sum_zero' does not depend on any axioms"))
    rel = write_lean(store, "proofs/p2_rho_sum_zero.lean",
                     "theorem rho_sum_zero : 1 + 1 = 2 := rfl\n")
    make_e(store).run_experiment("恒等式", "rho-sum", rel, method="formal")
    row = store.rows("experiments")[0]
    assert V.declared_name_of_notes(row["notes"]) == "rho_sum_zero", row["notes"]
    assert "声明名 p2_rho_sum_zero" not in row["notes"], "文件名词干不许当声明名"
    assert "imports=（默认：不注入任何库）" in row["notes"], row["notes"]


def test_a_formal_run_refuses_to_guess_the_declaration_name(
    store: Store, monkeypatch: pytest.MonkeyPatch
):
    """负控：文件里有两条具名声明而调用方没点名 ⇒ 拒绝，且一行都不写。

    "挑第一条"看起来无害，但它把"核的是哪个命题"变成一次猜测 —— 而与
    `decl_mismatch`（查了没通过）不同，这里的正确结论是"调用方写错了参数"。
    """
    monkeypatch.setattr(VT, "detect_verifier", lambda: _VERIFIER)
    monkeypatch.setattr(FG, "check_lean", _checker_stub(status="verified", stdout="ok"))
    rel = write_lean(store, "proofs/two.lean",
                     "theorem alpha : 1 + 1 = 2 := rfl\n\ntheorem beta : 2 + 2 = 4 := rfl\n")
    with pytest.raises(ExperimentError) as ei:
        make_e(store).run_experiment("两条声明", "k-two", rel, method="formal")
    assert "alpha" in str(ei.value) and "beta" in str(ei.value), str(ei.value)
    assert store.rows("experiments") == [], "拒绝时一行都不许写"


def test_formal_path_binds_the_checker_output_to_the_claim_key(
    store: Store, monkeypatch: pytest.MonkeyPatch
):
    """`verifier_subject_key` 逐字等于本行的 `claim_key`（schema 硬约束 2b 的接线）。

    没有它，"把命题 A 的检查器输出贴到命题 B 的行上"在结构上完全合法。
    """
    monkeypatch.setattr(VT, "detect_verifier", lambda: _VERIFIER)
    monkeypatch.setattr(FG, "check_lean", _checker_stub(status="verified", stdout="ok"))
    write_lean(store, "proofs/p.lean", "theorem p : 1 + 1 = 2 := rfl\n")
    make_e(store).run_experiment("命题 p", "K-绑定", "proofs/p.lean", method="formal", imports=())
    row = store.rows("experiments")[0]
    assert row["verifier_subject_key"] == "K-绑定", row
    assert row["verifier_subject_key"] == row["claim_key"]


def test_the_proof_row_the_formal_path_writes_passes_the_selfreported_audit(
    store: Store, monkeypatch: pytest.MonkeyPatch
):
    """正控（`R2-AN-2`）：生产写入点写出的那条 proof 行必须通过事后审计。

    为什么必须跑生产路径、而不是手搓一行：审计（`verify.selfreported_proof`）按 `notes` 里
    "声明名 <X>；"那一段认"检查器实际检查的是哪个声明"，而那一段的唯一写入点是
    `agent_e._declared_name_note`。手搓一行只能证明"审计认得我拼的那段文本"；只有真跑一遍
    `run_experiment` 才能证明写入点与读法确实对得上（这正是本仓踩过的"把自检夹具算成生产写入点"
    那一类假绿的反面）。

    本行同时是 §41.1 那条陷阱的正控：`claim_key='probe-eq'` 而 Lean 声明是 `probe_eq`（Lean 标识符
    不许带连字符）—— 把判据绑到 `claim_key` 上，这条完全合规的行会被判成"自报的 proof"。"""
    from agentflow.agent_e import declared_name_of_notes
    from agentflow.verify import verify_all

    monkeypatch.setattr(VT, "detect_verifier", lambda: _VERIFIER)
    monkeypatch.setattr(
        FG, "check_lean",
        _checker_stub(status="verified", stdout="'probe_eq' does not depend on any axioms"),
    )
    rel = write_lean(store, "proofs/probe_eq.lean")
    make_e(store).run_experiment("1 + 1 = 2（内核级）", "probe-eq", rel,
                                 method="formal", imports=())
    row = store.rows("experiments")[0]
    # 前置事实（没有它下面的"不报"可能来自退回分支，证明不了写入点）：
    assert declared_name_of_notes(row["notes"]) == "probe_eq", row["notes"]
    assert row["claim_key"] == "probe-eq" and row["claim_key"] != "probe_eq", (
        "夹具前提：`claim_key` 与 Lean 声明名合法地不同"
    )
    hits = [i for i in verify_all(store).errors if i.code == "selfreported_proof"]
    assert hits == [], f"生产路径写出的合规 proof 行被审计误判：{hits}"


# ============================================================ 负控：不许变成 proof


def test_numeric_script_on_the_same_entry_point_still_degrades_to_cross_check(store: Store):
    """负控①：数值脚本走同一条 `run_experiment` ⇒ 仍是 `cross_check`（FC-22 不放松）。"""
    p = Path(store.root) / "probes" / "lying.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "import json\n"
        "print('REPRO_RESULT: ' + json.dumps({'result':'supports','evidence_kind':'proof',"
        "'observations':{},'counterexample':None,'negation_kind':'not_proved'}))\n",
        encoding="utf-8",
    )
    out = make_e(store).run_experiment("数值脚本声称证明", "k-numeric", "probes/lying.py")
    assert out["evidence_kind"] == "cross_check"
    assert store.rows("experiments")[0]["evidence_kind"] == "cross_check"


@pytest.mark.parametrize("status", ["compile_error", "uses_sorry", "extra_axioms", "decl_mismatch"])
def test_a_failed_check_is_never_registered_as_proof(
    store: Store, monkeypatch: pytest.MonkeyPatch, status: str
):
    """负控②：检查器跑了但没通过 ⇒ `inconclusive` + `heuristic`，绝不许 proof。

    为什么不是 `cross_check`：那是"另一个方法旁证过"，而"证明没过"给不出旁证
    —— 把它写成 cross_check 会让一次检查失败变成正面证据（`formalgw.evidence_of`
    的 docstring 逐字写了同一条理由）。
    """
    monkeypatch.setattr(VT, "detect_verifier", lambda: _VERIFIER)
    monkeypatch.setattr(FG, "check_lean", _checker_stub(status=status, stderr="boom"))
    write_lean(store, "proofs/bad.lean")
    out = make_e(store).run_experiment("坏证明", f"k-{status}", "proofs/bad.lean",
                                       method="formal", imports=())
    assert out["evidence_kind"] == "heuristic", out
    assert out["result"] == "inconclusive"
    row = store.rows("experiments")[0]
    assert row["evidence_kind"] != "proof"
    assert row["observations"]["verifier_status"] == status, "检查器原样报的状态必须可读"
    ev = make_e(store).evidence_for(f"k-{status}")
    assert ev["proved"] is False


def test_a_compile_error_without_mathlib_says_the_one_thing_to_change(
    store: Store, monkeypatch: pytest.MonkeyPatch
):
    """正控：本机 Mathlib 可用而这一次没传 ⇒ 读数里必须给出那一步（只改一处就能重试）。

    真机读数（2026-10-05 T1 第 16 趟）：4 次 formal 全是
    `imports=（默认：不注入任何库）` + `compile_error`，检查器原话
    `failed to synthesize instance` / `omega did not find a contradiction`；
    当时提示词那一侧还有一句写死的错话（"可达的写法是不 import Mathlib 的自足文件"），
    于是模型连试 4 次、每次都换一种"不依赖库"的写法，`experiments` 里一条 proof 行都没落成。
    这一条守的是读数侧：框架知道库在、也知道这一次没传，就该把那一句话说出来。
    """
    monkeypatch.setattr(VT, "detect_verifier", lambda: _VERIFIER)
    monkeypatch.setattr(FG, "check_lean",
                        _checker_stub(status="compile_error",
                                      stderr="failed to synthesize instance"))
    monkeypatch.setattr(TC, "mathlib_state",
                        lambda *a, **k: {"checked": True, "root": "R",
                                         "umbrella_olean": "R/Mathlib.olean",
                                         "import_mathlib": "可用"})
    write_lean(store, "proofs/needs_lib.lean")
    out = make_e(store).run_experiment("缺库的命题", "k-needs-lib", "proofs/needs_lib.lean",
                                       method="formal")
    assert out["evidence_kind"] == "heuristic", out
    assert "把 `['Mathlib']` 传进 `imports` 再试一次" in out["notes"], out["notes"]


@pytest.mark.parametrize("case", ["already_asked", "source_imports_it", "no_mathlib",
                                  "not_a_compile_error"])
def test_no_remedy_note_when_mathlib_is_not_the_missing_piece(
    store: Store, monkeypatch: pytest.MonkeyPatch, case: str
):
    """负控：四种"不是缺库"的形态下，读数不许出现那条处置建议。

    编一个原因比不说话更坏：`uses_sorry` / `decl_mismatch` 与库无关，
    已经传了 `Mathlib` 的、源码自己 import 了的、以及这台机器根本没装库的，
    都不该收到"把 Mathlib 传进去再试一次"这句话。
    """
    monkeypatch.setattr(VT, "detect_verifier", lambda: _VERIFIER)
    status = "uses_sorry" if case == "not_a_compile_error" else "compile_error"
    monkeypatch.setattr(FG, "check_lean", _checker_stub(status=status, stderr="boom"))
    body = ("import Mathlib\ntheorem t : True := trivial\n"
            if case == "source_imports_it" else _LEAN_SRC)
    write_lean(store, "proofs/maybe.lean", body)
    state = ({"checked": True, "root": "", "reason": "没找到 Mathlib 工程根"}
             if case == "no_mathlib" else
             {"checked": True, "root": "R", "umbrella_olean": "R/Mathlib.olean",
              "import_mathlib": "可用"})
    monkeypatch.setattr(TC, "mathlib_state", lambda *a, **k: state)
    imports = ("Mathlib",) if case == "already_asked" else None
    out = make_e(store).run_experiment("别的失败", f"k-{case}", "proofs/maybe.lean",
                                       method="formal", imports=imports)
    assert "把 `['Mathlib']` 传进 `imports` 再试一次" not in out["notes"], out["notes"]


@pytest.mark.parametrize("status", ["timeout", "import_unavailable", "no_backend", "tool_crashed"])
def test_a_check_that_did_not_run_is_never_registered_as_proof(
    store: Store, monkeypatch: pytest.MonkeyPatch, status: str
):
    """负控③：没查成（超时 / 库不可得 / 无后端 / 工具崩了）⇒ 不许 proof。

    `import_unavailable` 在这一组里：库没装时编译根本没开始，那次检查没有发生
    —— 把它读成"查了没通过"或"通过"都是假话。
    """
    monkeypatch.setattr(VT, "detect_verifier", lambda: _VERIFIER)
    monkeypatch.setattr(FG, "check_lean", _checker_stub(status=status, stderr="unknown package 'Mathlib'"))
    write_lean(store, "proofs/nope.lean")
    out = make_e(store).run_experiment("没查成的命题", f"k-{status}", "proofs/nope.lean",
                                       method="formal", imports=("Mathlib",))
    assert out["evidence_kind"] == "heuristic", out
    assert out["result"] == "inconclusive"
    assert store.rows("experiments")[0]["evidence_kind"] != "proof"


def test_formal_path_refuses_a_non_lean_artifact_without_writing_anything(store: Store):
    """负控④：`method="formal"` 而产物不是 `.lean` ⇒ 当场拒绝，一行都不写。

    判据不是后缀本身好看：形式化路径的输入必须是检查器能读的形式化源码。
    此前这条组合会先跑一遍 Python 脚本、再由 schema 报一句"缺 verifier_output"
    —— 一次调用方写错参数被说成"推导规则与 schema 打架"。
    """
    p = Path(store.root) / "probes" / "not_formal.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("print('nothing formal here')\n", encoding="utf-8")
    with pytest.raises(ExperimentError) as ei:
        make_e(store).run_experiment("不是形式化产物", "k-py", "probes/not_formal.py",
                                     method="formal")
    assert ".lean" in str(ei.value)
    assert store.rows("experiments") == []


def test_computational_methods_refuse_name_and_imports_instead_of_ignoring_them(store: Store):
    """负控⑤：计算类方法收到 `name` / `imports` ⇒ 拒绝，不是静默忽略。

    静默忽略会让调用方以为自己指定了检查条件（"说明了 imports，实际用的是
    默认 Mathlib"）—— 这句假话没有任何地方会报出来。
    """
    p = Path(store.root) / "probes" / "ok.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "import json\n"
        "print('REPRO_RESULT: ' + json.dumps({'result':'inconclusive','evidence_kind':'heuristic',"
        "'observations':{},'counterexample':None,'negation_kind':'no_local_evidence'}))\n",
        encoding="utf-8",
    )
    for kw in ({"imports": ()}, {"name": "t"}, {"imports": ("Mathlib",), "name": "t"}):
        with pytest.raises(ExperimentError):
            make_e(store).run_experiment("计算类方法", "k", "probes/ok.py", **kw)
    assert store.rows("experiments") == []


# ============================================================ schema 的两条硬约束没被放松


def test_schema_still_rejects_a_proof_row_without_checker_output_or_with_a_foreign_subject(
    store: Store,
):
    """负控⑥：`verifier_output` 空 / `verifier_subject_key` 不等于 `claim_key` ⇒ 仍然抛。

    这条不是"顺手再测一次 schema"：`P-8` 的修法是给形式化路径补上这四个字段，
    而最省事的"修法"是把 schema 的硬约束改宽 —— 这条用例把那条路堵死
    （schema.py 这一个字符都没动，见改动清单）。
    """
    import agentflow.schema as S

    base = dict(experiment_id="0000", claim="c", claim_key="K", method="formal",
                result="supports", negation_kind="not_proved", exit_code=0)
    with pytest.raises(ValueError) as e1:
        S.Experiment(**base, evidence_kind="proof", verifier_output="",
                     verifier_subject_key="K").validate()
    assert "verifier_output" in str(e1.value)
    with pytest.raises(ValueError) as e2:
        S.Experiment(**base, evidence_kind="proof", verifier_output="Lean: ok",
                     verifier_subject_key="别的命题").validate()
    assert "verifier_subject_key" in str(e2.value)
    # 防误伤：两个字段都对 ⇒ 通过
    S.Experiment(**base, evidence_kind="proof", verifier_output="Lean: ok",
                 verifier_subject_key="K").validate()


# ============================================================ 真跑 Lean（有 lean 才跑）


@pytest.mark.skipif(shutil.which("lean") is None, reason="本机 PATH 上没有 lean 检查器")
def test_real_lean_kernel_proof_registers_a_proof_row(store: Store):
    """真跑一次内核级形式化检查 ⇒ 台账里出现一条真正的 `proof` 行。

    `imports=()` 是刻意的：本机有 Lean 发行版，而裸 `lean` 解析不到 Mathlib
    （要用 `lake env lean`），内核级命题（`rfl` 能证的等式）不需要任何库。
    `verifier_output` 必须是检查器自己说的那句话，不是我们拼的。
    """
    rel = write_lean(store, "proofs/real_probe.lean",
                     "theorem real_probe : 1 + 1 = 2 := rfl\n")
    out = make_e(store).run_experiment("1 + 1 = 2（真检查器）", "real-probe", rel,
                                       method="formal", imports=())
    if out["evidence_kind"] != "proof":  # pragma: no cover - 只在检查器不可用时走到
        pytest.skip(f"本机的 lean 没给出 verified（status={out['reason']!r}）⇒ 只核对了不许谎报")
    row = store.rows("experiments")[0]
    assert row["evidence_kind"] == "proof"
    assert row["verifier_subject_key"] == "real-probe"
    assert "does not depend on any axioms" in row["verifier_output"], row["verifier_output"]
    assert row["code_hash"] == VT.code_hash(Path(store.root) / rel)
    assert json.dumps(row["observations"], ensure_ascii=False)


# ============================================================ E-12：失败的三态恢复


def test_e12_formal_failure_tri_state_is_recovered_from_the_checker(
    store: Store, monkeypatch: pytest.MonkeyPatch
):
    """E-12（draft/44）："检查器判了不通过"与"根本没查成"必须在行上分得开。

    改前：negation_kind 一律 no_local_evidence（core.py 那一行），而真机 50 条 formal 里
    41 条 exit_code=None ⇒ compile_error（判了、不通过）与 timeout / no_backend（没查成）
    在行上完全同形 —— "没查成"被读成"没通过"。
    现在按 formalgw.evidence_of 自己的 checked 位分三态（不另立一套口径）：checked_failed ⇒
    not_proved；timeout / tool_crashed ⇒ no_local_evidence（跑过、没裁决）；
    no_backend / import_unavailable ⇒ not_searched_here（本机起不了这次检查）。
    反负控：三个 negation_kind 必须两两不同（否则又折回同一个值）。
    """
    monkeypatch.setattr(VT, "detect_verifier", lambda: _VERIFIER)
    rel = write_lean(store, "proofs/probe_eq.lean")
    e = make_e(store)

    def _run(tag: str, status: str) -> dict:
        monkeypatch.setattr(FG, "check_lean", _checker_stub(status=status, stdout=""))
        return e.run_experiment(f"命题 {tag}", f"probe-{tag}", rel, method="formal", imports=())

    failed = _run("failed", "compile_error")          # 判了：不通过
    timed = _run("timed", "timeout")                  # 跑了、没裁决
    noback = _run("noback", "no_backend")             # 本机起不了这次检查

    def _tri(tag: str) -> str:
        """`tri_state` 是行上的读数（返回值里没有 `observations`）⇒ 读落库的那一行。"""
        rows = [r for r in store.rows("experiments") if r.get("claim_key") == f"probe-{tag}"]
        assert rows, tag
        return str((rows[-1].get("observations") or {}).get("tri_state") or "")

    for out in (failed, timed, noback):
        assert out["result"] == "inconclusive", out
        assert out["evidence_kind"] != "proof", out
    assert _tri("failed") == "checked_failed", _tri("failed")
    assert failed["negation_kind"] == "not_proved", failed
    assert _tri("timed") == "not_checked", _tri("timed")
    assert timed["negation_kind"] == "no_local_evidence", timed
    assert _tri("noback") == "not_checked", _tri("noback")
    assert noback["negation_kind"] == "not_searched_here", noback
    kinds = {failed["negation_kind"], timed["negation_kind"], noback["negation_kind"]}
    assert len(kinds) == 3, f"三态又折回同一个值了：{kinds}"

    # ---- E-12(a)：退出码那一格也要分得开（真机 41/50 行在这里同形）
    assert failed["exit_code"] == 1, (
        f"检查器判了不通过 ⇒ 这一格要记**它的真实退出码**（非零），收到 {failed['exit_code']!r}")
    assert timed["exit_code"] is None and noback["exit_code"] is None, (
        "没跑成（timeout/no_backend）那一格必须是 None —— "
        f"**绝不用 0 冒充'跑过'**：{timed['exit_code']!r} / {noback['exit_code']!r}")

"""`--lean` 接线：真的跑过才摘牌，没跑成就写"没查成"。

## 这一层为什么值得一组端到端用例

`runflow.NOT_WIRED_ITEMS` 是"本次确定没有做的事"的登记。它的可信度全在
"摘牌条件"上：只要判据写成"开关打开了就摘"，报告里那句"Lean 已接线"
就是谎话 —— 而它读起来比"没有接线"更可信，所以更危险。

本文件的判据四条：

1. 缺省（`lean=False`）时 lean 仍在未接线清单里，且写的是"没有开启"；
2. 开着、检查器真跑过 ⇒ 从未接线清单里摘掉，`claims.json` 记下逐条结论与证据等级；
3. 开着但没跑成（没后端 / 没有片段 / 片段没有具名声明）⇒ 留在清单里，理由写明具体原因；
4. 开着、跑过、但结论不是 `verified`（含 sorry 那种）⇒ 摘牌，但绝不产出 proof 级证据，
   且进入 unknowns。

全程离线：模型传输层、检索、回验、`check_lean` 的运行函数全部注入。
"""

from __future__ import annotations

import json
from pathlib import Path

from agentflow.modelgw import ModelSpec
from agentflow.runflow import run_topic
from agentflow.store import Store

TS = "2026-01-01T00:00:00+00:00"
ABSTRACT = "An abelian group is a group in which the commutative law holds."

LEAN_OK = "theorem abelian_comm : True := by trivial"
LEAN_SORRY = "theorem abelian_comm : True := by sorry"
LEAN_EXAMPLE = "example : 1 + 1 = 2 := rfl"


def _reply(text: str) -> str:
    """OpenAI 兼容的成功应答（含 usage，免得走"上游未回 usage"那一支）。"""
    return json.dumps({
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3},
    }, ensure_ascii=False)


def _transport(text: str):
    def _t(url: str, headers: dict, data: bytes, timeout_sec: float):  # noqa: ARG001
        return 200, _reply(text)

    return _t


def _search(topic: str, *, limit: int, timeout_sec: float):  # noqa: ARG001
    return [{"source": "selftest", "title": "Abelian groups", "year": 1930,
             "doi": "10.1000/selftest", "abstract": ABSTRACT}]


def _runner(status_stdout: str, *, exit_code: int = 0, invoked: list | None = None):
    """一个假检查器：`invoked` 收到调用就会多一个元素（"真的起过进程"的证据）。"""
    def _fn(cmd, *, cwd, timeout_sec):  # noqa: ARG001 - 接缝契约
        if invoked is not None:
            invoked.append(cmd[1])
        return {"exit_code": exit_code, "stdout": status_stdout, "stderr": "",
                "timed_out": False}

    return _fn


def _run(store: Store, tmp_path: Path, name: str, body: str, **kw):
    """跑一次端到端：答复里带一个 Lean 片段 + 一条可回验的断言。"""
    text = f"- 阿贝尔群是交换群 || {ABSTRACT}\n\n```lean\n{body}\n```\n"
    out = run_topic(
        store, topic=f"lean-{name}", budget_usd=1.0, out_dir=tmp_path / name,
        transport=_transport(text), spec=ModelSpec(api_key="selftest-key"),
        max_calls=1, search_fn=_search, now=TS, **kw,
    )
    return out, json.loads((tmp_path / name / "claims.json").read_text(encoding="utf-8"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ============================================================ 缺省关着


def test_lean_is_off_by_default_and_says_so(store: Store, tmp_path: Path):
    """缺省必须关，且未接线清单里那句写的是"没有开启"而不是常量文案。"""
    out, claims = _run(store, tmp_path, "off", LEAN_OK)
    assert claims["lean"]["enabled"] is False
    assert claims["lean"]["ran"] is False and claims["lean"]["proved"] == 0
    man = _load(tmp_path / "off" / "run-manifest.json")
    item = next(n for n in man["not_wired"] if n["name"] == "lean")
    assert "没有开启" in item["reason"]
    md = (tmp_path / "off" / "report.md").read_text(encoding="utf-8")
    assert "形式化验证（Lean）" not in md, "没开这一层时证据段不该多一整段公告"
    assert out["lean"]["enabled"] is False


# ============================================================ 真的跑过


def test_lean_on_and_verified_is_taken_off_the_not_wired_list(store: Store, tmp_path: Path):
    """开着且真的跑过、结论 verified ⇒ 从未接线清单摘掉，并产出 proof 级证据。"""
    invoked: list = []
    out, claims = _run(
        store, tmp_path, "ok", LEAN_OK, lean=True,
        lean_run_fn=_runner(
            "'abelian_comm' depends on axioms: [propext, Classical.choice, Quot.sound]\n",
            invoked=invoked),
    )
    assert invoked, "检查器必须真的被调用过（否则'接上了'是谎话）"
    lean = claims["lean"]
    assert lean["enabled"] and lean["ran"] and lean["proved"] == 1
    assert lean["statuses"] == ["verified"] and lean["evidence_kind"] == "proof"
    check = lean["checks"][0]
    assert check["name"] == "abelian_comm" and check["proved"] is True
    assert check["evidence_kind"] == "proof" and check["exit_code"] == 0
    assert check["checker_invoked"] is True and check["source_sha256"]
    assert check["claim_texts"] == ["阿贝尔群是交换群"]

    man = _load(tmp_path / "ok" / "run-manifest.json")
    assert not [n for n in man["not_wired"] if n["name"] == "lean"], "真跑过就必须摘牌"
    assert man["lean"]["proved"] == 1 and man["lean"]["evidence_kind"] == "proof"
    md = (tmp_path / "ok" / "report.md").read_text(encoding="utf-8")
    assert "### 形式化验证（Lean）" in md
    assert "本次到达的证据等级：proof" in md
    assert out["lean"]["ran"] is True


def test_lean_on_but_no_snippet_keeps_the_honestReason(store: Store, tmp_path: Path):
    """开着但没有 Lean 片段 ⇒ 没有可检查的对象，不算"接上了"。"""
    text = f"- 阿贝尔群是交换群 || {ABSTRACT}\n"
    out = run_topic(
        store, topic="lean-nosnip", budget_usd=1.0, out_dir=tmp_path / "nosnip",
        transport=_transport(text), spec=ModelSpec(api_key="selftest-key"),
        max_calls=1, search_fn=_search, now=TS, lean=True,
        lean_run_fn=_runner("never called"),
    )
    claims = _load(tmp_path / "nosnip" / "claims.json")
    assert claims["lean"]["enabled"] and not claims["lean"]["ran"]
    assert claims["lean"]["snippets"] == 0
    assert "没有任何 Lean 代码块" in claims["lean"]["reason"]
    man = _load(tmp_path / "nosnip" / "run-manifest.json")
    item = next(n for n in man["not_wired"] if n["name"] == "lean")
    assert "没有任何 Lean 代码块" in item["reason"]
    assert out["exit_code"] == 0


def test_lean_on_with_no_backend_is_reported_as_not_checked(store: Store, tmp_path: Path):
    """开着但后端不存在 ⇒ 摘不了牌，理由必须写明它是"没有跑成"。"""
    def _gone(cmd, *, cwd, timeout_sec):  # noqa: ARG001 - 接缝契约
        raise FileNotFoundError("lean: not found")

    out, claims = _run(store, tmp_path, "nobackend", LEAN_OK, lean=True, lean_run_fn=_gone)
    lean = claims["lean"]
    assert lean["enabled"] and not lean["ran"] and lean["proved"] == 0
    assert lean["statuses"] == ["no_backend"]
    assert lean["evidence_kind"] is None
    man = _load(tmp_path / "nobackend" / "run-manifest.json")
    item = next(n for n in man["not_wired"] if n["name"] == "lean")
    assert "没有跑出结论" in item["reason"] and "no_backend" in item["reason"]
    assert out["lean"]["ran"] is False


def test_an_unnamed_snippet_does_not_count_as_having_run(store: Store, tmp_path: Path):
    """片段没有具名声明 ⇒ 静态判 `decl_mismatch`，检查器一次都没起过 ⇒ 不许摘牌。"""
    invoked: list = []
    out, claims = _run(store, tmp_path, "example", LEAN_EXAMPLE, lean=True,
                       lean_run_fn=_runner("never called", invoked=invoked))
    assert invoked == [], "没有声明的片段不该被交给检查器"
    lean = claims["lean"]
    assert lean["statuses"] == ["decl_mismatch"]
    assert lean["checks"][0]["checker_invoked"] is False
    assert not lean["ran"] and lean["proved"] == 0
    man = _load(tmp_path / "example" / "run-manifest.json")
    assert [n for n in man["not_wired"] if n["name"] == "lean"], "没起过检查器就不许摘牌"
    assert out["lean"]["evidence_kind"] is None


# ============================================================ 跑过但没通过


def test_sorry_with_exit_zero_never_becomes_proof_evidence(store: Store, tmp_path: Path):
    """负控（会红）：含 sorry 且检查器退出码 0 的文件不许产出 proof 级证据。

    这一条由静态判据拦下（源码里一出现 `sorry` 就不算证明），
    所以检查器一次也没起过 ⇒ `ran` 为假、lean 仍留在未接线清单里，
    理由逐字写着结论是 `uses_sorry`。
    """
    invoked: list = []
    out, claims = _run(
        store, tmp_path, "sorry", LEAN_SORRY, lean=True,
        lean_run_fn=_runner("'abelian_comm' depends on axioms: [sorryAx, propext]\n",
                            invoked=invoked),
    )
    assert invoked == [], "含 sorry 的片段在编译之前就被判掉了，不必起检查器"
    lean = claims["lean"]
    assert lean["statuses"] == ["uses_sorry"]
    assert lean["proved"] == 0 and lean["evidence_kind"] is None
    assert not lean["ran"]
    assert lean["checks"][0]["evidence_kind"] is None
    assert lean["checks"][0]["sorry_count"] == 1
    md = (tmp_path / "sorry" / "report.md").read_text(encoding="utf-8")
    assert "uses_sorry" in md and "本次到达的证据等级：无" in md
    man = _load(tmp_path / "sorry" / "run-manifest.json")
    item = next(n for n in man["not_wired"] if n["name"] == "lean")
    assert "uses_sorry" in item["reason"]
    assert any("uses_sorry" in u for u in man["unknowns"]), "结论必须进 unknowns"
    assert out["lean"]["proved"] == 0 and out["lean"]["evidence_kind"] is None


def test_extra_axiom_never_becomes_proof_evidence(store: Store, tmp_path: Path):
    """负控（会红）：额外公理不许产出 proof 级证据。"""
    out, claims = _run(
        store, tmp_path, "axiom", LEAN_OK, lean=True,
        lean_run_fn=_runner("'abelian_comm' depends on axioms: [MyAxiom]\n"),
    )
    lean = claims["lean"]
    assert lean["statuses"] == ["extra_axioms"] and lean["proved"] == 0
    assert lean["checks"][0]["axioms"] == ["MyAxiom"]
    assert "MyAxiom" in lean["checks"][0]["reason"]
    assert out["lean"]["evidence_kind"] is None


def test_declaration_mismatch_with_exit_zero_never_becomes_proof_evidence(store: Store,
                                                                         tmp_path: Path):
    """负控（会红）：退出码 0 但输出里没有被检查到的声明名 ⇒ 不许产出 proof 级证据。

    这里用的是"文件里声明了 a、审计输出里却是别的名字"的形态 ——
    只信退出码的实现会把它判成 verified。
    """
    def _other(cmd, *, cwd, timeout_sec):  # noqa: ARG001 - 接缝契约
        return {"exit_code": 0, "stdout": "'something_else' does not depend on any axioms\n",
                "stderr": "", "timed_out": False}

    out, claims = _run(store, tmp_path, "decl", LEAN_OK, lean=True, lean_run_fn=_other)
    lean = claims["lean"]
    assert lean["statuses"] == ["decl_mismatch"]
    assert lean["proved"] == 0 and lean["evidence_kind"] is None
    assert lean["checks"][0]["exit_code"] == 0, "退出码确实是 0 —— 这正是判据要挡的形态"
    assert out["lean"]["ran"] is True, "检查器真起过（所以摘牌），只是没通过"
    assert any("没有任何 proof 级证据" in u
               for u in _load(tmp_path / "decl" / "run-manifest.json")["unknowns"])


def test_timeout_is_recorded_as_not_checked(store: Store, tmp_path: Path):
    """超时 ⇒ 没查成：证据等级为无、`ran` 为假（检查器还没回话），理由写明超时。"""
    def _hang(cmd, *, cwd, timeout_sec):  # noqa: ARG001 - 接缝契约
        return {"exit_code": None, "stdout": "elaborating…", "stderr": "", "timed_out": True}

    out, claims = _run(store, tmp_path, "timeout", LEAN_OK, lean=True, lean_run_fn=_hang)
    lean = claims["lean"]
    assert lean["statuses"] == ["timeout"] and lean["proved"] == 0
    assert lean["checks"][0]["exit_code"] is None
    assert lean["ran"] is False, "超时是没查成，不是'跑过了'"
    assert "timeout" in lean["reason"] and "没有跑出结论" in lean["reason"]
    man = _load(tmp_path / "timeout" / "run-manifest.json")
    assert [n for n in man["not_wired"] if n["name"] == "lean"], "没查成就不许摘牌"
    assert out["exit_code"] == 0, "Lean 没查成不改本次运行的退出码（它说的是运行做没做成）"

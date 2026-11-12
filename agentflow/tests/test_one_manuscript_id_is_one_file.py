# -*- coding: utf-8 -*-
"""一个稿号 = 一份文件 = 一份证明（业主 2026-11-11，逐字）。

> 「同稿号多个版本是错误的，一个稿号就相当于是该稿的文件名，不再细分 version 几，
>   应该在改正文时 edit 它。于是拿 V 签冻结后交哪份是明确的（一个稿号只有一份）。」

这一份钉两件事：
  a 连交三次（改正文） ⇒ 同一路径、盘上只有一份文件、读数里不再有 `proof_no`、
    稿头也没有 `- 证明号：` 那一行（2026-11-11 业主裁定：这一格在手稿产出侧退役）
  c 反真空：把 `- 证明号：` 加回渲染 ⇒ a 那条断言要能拦下来
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(ROOT_SRC) not in sys.path:
    sys.path.insert(0, str(ROOT_SRC))

from agentflow import conductor as CND  # noqa: E402
from agentflow.agent_f import AgentF  # noqa: E402
from agentflow.store import Store  # noqa: E402

STMT = ("设 (X,Σ,μ) 为测度空间，f_n→f μ-a.e. 且存在可积 g 使 |f_n|≤g a.e.，"
        "则 ∫f_n dμ → ∫f dμ。")


class _FormStub:
    """F 的秘书替身：只实现形态判定与依赖面洗稿这两问。

    为什么必须有它：pytest 里没有模型缝（`conftest` 把 settings 钉到不存在的路径）⇒
    F 的形态闸会如实报"没判成"，于是登记这一步按受控拒处理、手稿一个字节都不写。
    那一档是"没查成不等于没问题"的正确行为，不是本判据要测的东西 ⇒ 这里给一个会说
    "形态合格"的替身。判据 `test_proof_registration_is_decoupled.py` 用的是同一个手法。
    """

    role = "F"
    seam = object()

    def judge_proposition_form(self, **_kw):
        return {"checked": True, "well_formed": True,
                "conditions": "", "conclusion": "", "problems": [],
                "decision": "夹具：形态判定", "refused": "", "reason": "夹具", "cached": False}

    def wash_dependency_face(self, text: str, **_kw):
        return {"checked": True, "text": str(text), "actor": "fake-F-secretary",
                "washed": False, "deps_refused": "", "deps_refused_findings": [],
                "deps_section_filled": "", "deps_washing": [],
                "reason": "夹具：依赖面本来就合规"}


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _steps(tag: str) -> list[dict]:
    return [
        {"text": f"由控制函数得 |f_n−f| ≤ 2g 且 f_n−f → 0 a.e.（{tag}）",
         "cites": [], "assumption": True},
        {"text": f"对 2g−|f_n−f| 用 Fatou 得 limsup∫|f_n−f| ≤ 0（{tag}）",
         "cites": [], "assumption": True},
        {"text": f"三角不等式给出 |∫f_n−∫f| → 0（{tag}）",
         "cites": [], "assumption": True},
    ]


def _agent(st: Store) -> AgentF:
    f = AgentF(st, config={"workspace_root": str(st.root)})
    f.f_secretary = _FormStub()
    return f


def _plan(f: AgentF) -> str:
    got = f.create_plan(
        problem=STMT, problem_key="one-file",
        subgoals=[{"sid": "S1", "owner": "F", "text": STMT, "testable": "∫|f_n−f|→0"}])
    return str((got.get("plan") or got).get("plan_id") or "000000")


def _submit(f: AgentF, pid: str, tag: str) -> dict:
    with CND.calling_as(f"t-of-{tag}", "F", parent_task_id="t-of-m", parent_role="M"):
        return f.step(pid, product={"kind": "proof", "label": f"探针 {tag}",
                                    "steps": _steps(tag)})


def _header(text: str) -> dict:
    head = text.split("## 命题")[0]
    out: dict[str, str] = {}
    for line in head.splitlines():
        for mark in ("- 命题号：", "- 计划：", "- 证明号："):
            if line.startswith(mark):
                out[mark] = line[len(mark):].strip()
    return out


# ---------------------------------------------------------------- a 一稿一份
def test_a_three_submissions_stay_in_one_file(tmp_path: pathlib.Path) -> None:
    """a：改正文三次 ⇒ 同一路径、盘上一份、不再产生 `proof_no` / `- 证明号：`。"""
    st = _ws(tmp_path)
    root = pathlib.Path(st.root)
    f = _agent(st)
    pid = _plan(f)

    rounds = [_submit(f, pid, tag) for tag in ("v1", "v2", "v3")]
    paths = [str(r.get("manuscript_path") or "") for r in rounds]
    ids = [str(r.get("manuscript_id") or "") for r in rounds]

    assert all(p for p in paths), rounds
    assert len(set(paths)) == 1, ("改正文换了路径 ⇒ 又回到「一份稿多个版本」", paths)
    assert paths[0] == f"reports/f-proof-{ids[0]}.md", (paths[0], ids[0])
    assert "-p" not in pathlib.PurePosixPath(paths[0]).stem.partition("f-proof-")[2], (
        "新写路径不该带 `-pN`", paths[0])
    # 2026-11-11 业主裁定：「proof_no 确实该退役……手稿产出侧和 V 签侧甚至呈递侧可
    # 退役」⇒ F 的读数里没有这一格（不是"恒 1"）。
    assert all("proof_no" not in r for r in rounds), rounds
    assert ids == [ids[0]] * 3, ("改正文不许换稿号", ids)

    files = sorted(p.name for p in (root / "reports").glob("f-proof-*.md"))
    assert files == [f"f-proof-{ids[0]}.md"], ("盘上必须恰好一份", files)

    text = (root / paths[0]).read_text(encoding="utf-8")
    head = _header(text)
    assert "- 证明号：" not in text, ("新写的稿不该再有这一行", head)
    assert head.get("- 命题号：") == "stmt:（还没落号）", head

    # 正文确实换了（三次不同），但仍是同一份文件
    assert "v3" in text, "最后一次改正文的标记应当在这份文件里"


# ---------------------------------------------------------------- c 反真空
def test_c_restoring_the_proof_no_line_turns_a_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c 反真空：把 `- 证明号：` 加回渲染 ⇒ a 的「新稿没有这一行」当场红。

    这正是退役的那一行：改前 `render_proof_manuscript` 会在页头写它。把那一行塞回去
    之后，同一份 a 的现场必须能拦下来 —— 否则"没有这一行"只是恒真的空话。
    """
    from agentflow import manuscriptform as _MF

    real = _MF.render_proof_manuscript

    def _with_the_retired_line(*args, **kw):  # noqa: ANN002, ANN003 - 打桩
        text = real(*args, **kw)
        lines = text.split("\n")
        at = next(i for i, line in enumerate(lines) if line.startswith("- 命题号："))
        lines.insert(at + 1, "- 证明号：1")   # 改前的渲染（业主 2026-11-11 已作废）
        return "\n".join(lines)

    monkeypatch.setattr(_MF, "render_proof_manuscript", _with_the_retired_line)
    st = _ws(tmp_path)
    f = _agent(st)
    pid = _plan(f)
    rounds = [_submit(f, pid, tag) for tag in ("v1", "v2")]
    rel = str(rounds[-1].get("manuscript_path") or "")
    text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    # 先量"打桩真的生效"（否则下面那个 False 是空的）。
    assert "- 证明号：" in text, ("打桩没生效 ⇒ 反真空不成立", text[:600])
    # a 的那条断言原样跑一遍：它必须在这里为 False。
    assert ("- 证明号：" not in text) is False, (
        "把退役的那一行加回渲染之后 a 仍然绿 ⇒ 「新稿没有这一行」是恒真的")

# -*- coding: utf-8 -*-
"""E 侧数值证明路线的第二道闸：命题形态闸同步到 E（业主 2026-11-07 第二刀）。

业主原话（逐字，这就是本文件的验收标准）：

> 「F侧的注册+放弃闸需同步到E侧的数值证明路线」

F 侧那一半是「命题登记时需过 F 秘书闸，审查命题描述是否规范，是否明确了从什么条件
导出什么结论」。同步到 E 侧之后：**判据本体不变**，仍是
`Secretary.judge_proposition_form` 那一次判定（`test_d_*` 打桩数调用点，证明两处用的是
同一份实现），只是调用方换成 E 的数值证明路线 —— 在 `experiments` 那一行（以及它
带出的 ②③ 报告 / e-proof 手稿）**写盘之前**判一次。

## 判据

| # | 判据 | 用例 |
|---|---|---|
| a | 规范的「设…则…」走 E 的数值证明路线 ⇒ 过，实验行落盘（proof） | `test_a_*` |
| b | 98 那三条「作业规格」文本走同一条路线 ⇒ 受控拒，一个字节都不写（无实验行 / 报告 / 手稿 / statements 行），形态台账留一行 `role=E` | `test_b_*` |
| c | 没判成 ⇒ fail-closed（没有秘书 / 判定那一问抛了） | `test_c_*` |
| d | 同一个判定口：F 的 `_proposition_form_gate` 与 E 的数值证明路线都调 `Secretary.judge_proposition_form`（打桩计数，只此一份） | `test_d_*` |
| e | 反真空：把 E 侧这道闸摘掉 ⇒ b 红（那段作业规格会被登记成一条 proof 级实验） | `test_e_*` |
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import e_form_gate_ok  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow.agent_e import AgentE, ExperimentError  # noqa: E402
from agentflow.agent_f.core import AgentF  # noqa: E402
from agentflow.store import Store  # noqa: E402

from test_proposition_form_gate import SPEC_036, SPEC_037, SPEC_039  # noqa: E402

WELL_FORMED = ("设 K=Q(√−3)，O_K 为其整数环；若 𝔭 是 O_K 中范数 ≤ X 的素理想，"
               "则 ∑_{N𝔭≤X} log N𝔭 = X + O(√X)。")
SCRIPT_REL = "code/enum_probe.py"

#: 一条"想升格成数值证明"的探针：`exhaustive` 是布尔 true、②③ 与搜索空间都给了。
EXHAUSTIVE_PROBE = """
import json
print("REPRO_RESULT: " + json.dumps({
    "result": "supports",
    "evidence_kind": "cross_check",
    "observations": {
        "exhaustive": True,
        "design": "把断言归约成有限枚举，逐点检查",
        "enumeration": "枚举全部 n<=12 的对象；按对称性剪枝；每个对象都落在枚举里",
        "search_space": {"n_cases": 4096}
    },
    "counterexample": None,
    "negation_kind": "not_proved",
}))
"""


class _Seam:
    """模型缝的替身：`ask_json` 回一段写死的 JSON（含 `SeamCall` 的最小形状）。"""

    class _Call:
        ok = True
        problem = ""
        detail = ""
        text = ""
        model = "fake"
        prompt_version = "t"
        prompt_sha256 = "0" * 64

    def __init__(self, data: dict) -> None:
        self.data = dict(data)
        self.prompts: list[str] = []

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = ""):
        self.prompts.append(prompt)
        return dict(self.data), self._Call()


def _well_formed_seam() -> _Seam:
    return _Seam({"well_formed": True, "conditions": "设 K", "conclusion": "则 …",
                  "problems": [], "decision": "条件与结论都写清了"})


def _ill_formed_seam() -> _Seam:
    return _Seam({"well_formed": False, "conditions": "", "conclusion": "",
                  "problems": ["这是流程要求（本轮产物必须是 proof），不是数学命题"],
                  "decision": "不是命题"})


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _write(store: Store, rel: str = SCRIPT_REL, body: str = EXHAUSTIVE_PROBE) -> str:
    path = pathlib.Path(store.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return rel


def _e(store: Store, seam: _Seam | None = None) -> AgentE:
    """E 的秘书用**真的** `Secretary`（`judge_proposition_form` 本体），只换模型缝。"""
    sec = SEC.Secretary("E", root=store.root, store=store, seam=seam,
                        enable_model=True)
    return AgentE(store, config={}, workspace_root=store.root, secretary=sec)


def _run(agent: AgentE, claim: str, *, claim_key: str = "ramsey34=9") -> dict:
    return agent.run_experiment(claim, claim_key, SCRIPT_REL, method="numeric")


def _counts(store: Store) -> dict[str, int]:
    return {"experiments": len(list(store.rows("experiments"))),
            "statements": len(list(store.rows("statements")))}


def _disk_products(store: Store) -> dict[str, list[str]]:
    root = pathlib.Path(store.root)
    reports = sorted(str(p.relative_to(root)) for p in (root / "out" / "experiments")
                     .glob("*/exhaustion.md")) if (root / "out" / "experiments").is_dir() else []
    manuscripts = sorted(p.name for p in (root / "reports").glob("e-proof-*.md")) \
        if (root / "reports").is_dir() else []
    return {"reports": reports, "manuscripts": manuscripts}


# ---------------------------------------------------------------- a 合格 ⇒ 放行

def test_a_a_well_formed_proposition_passes_and_the_experiment_lands(tmp_path):
    """a：规范命题走 E 的数值证明路线 ⇒ 过闸，实验行落盘、档位到 proof。"""
    st = _store(tmp_path)
    _write(st)
    seam = _well_formed_seam()
    out = _run(_e(st, seam), WELL_FORMED)
    assert out["recorded"] is True, out
    assert out["evidence_kind"] == "proof", out
    assert len(seam.prompts) == 1, seam.prompts
    rows = SEC.proposition_form_rows(st.root)
    assert len(rows) == 1 and rows[0]["role"] == "E", rows
    assert rows[0]["checked"] is True and rows[0]["well_formed"] is True, rows
    assert rows[0]["conditions"] and rows[0]["conclusion"], rows


# ---------------------------------------------------------------- b 98 三条 ⇒ 受控拒

@pytest.mark.parametrize("text", [SPEC_036, SPEC_037, SPEC_039],
                         ids=["000036", "000037", "000039"])
def test_b_a_work_spec_on_the_e_route_is_refused_and_writes_nothing(tmp_path, text):
    """b：98 那种「作业/验收规格」走 E 的数值证明路线 ⇒ 受控拒，一个字节都不写。"""
    st = _store(tmp_path)
    _write(st)
    seam = _ill_formed_seam()
    with pytest.raises(ExperimentError) as exc:
        _run(_e(st, seam), text)
    msg = str(exc.value)
    assert "proposition_form_refused" in msg, msg
    assert "受控拒" in msg, msg
    assert _counts(st) == {"experiments": 0, "statements": 0}, _counts(st)
    assert _disk_products(st) == {"reports": [], "manuscripts": []}, _disk_products(st)
    rows = SEC.proposition_form_rows(st.root)
    assert len(rows) == 1, rows
    assert rows[0]["role"] == "E" and rows[0]["checked"] is True, rows
    assert rows[0]["well_formed"] is False, rows
    # 闸真的看到了那段正文（不是拿空串判的）
    assert seam.prompts and text[:20] in seam.prompts[0], seam.prompts


def test_b_a_plain_numeric_experiment_does_not_go_through_the_gate(tmp_path):
    """b 的边界：一般数值实验（不产出 proof 级凭据）不过这道闸（与 F 侧的"收录不拦"同向）。"""
    st = _store(tmp_path)
    _write(st, body=EXHAUSTIVE_PROBE.replace('"exhaustive": True', '"exhaustive": False'))
    seam = _ill_formed_seam()
    out = _run(_e(st, seam), SPEC_036)
    assert out["recorded"] is True, out
    assert out["evidence_kind"] != "proof", out
    assert seam.prompts == [], "一般数值实验不该问形态闸"
    assert SEC.proposition_form_rows(st.root) == []


# ---------------------------------------------------------------- c 没判成 ⇒ fail-closed

def test_c_no_secretary_means_refused_and_a_not_checked_ledger_row(tmp_path):
    """c 的第一档：E 派生不出秘书（没有判断面）⇒ 受控拒 + 台账一行「没判成」。"""
    st = _store(tmp_path)
    _write(st)
    e = e_form_gate_ok(AgentE(st, config={}, workspace_root=st.root))
    e.e_secretary = None                     # 钉死"这一位没有判断面"
    with pytest.raises(ExperimentError) as exc:
        _run(e, WELL_FORMED)
    assert "proposition_form_refused" in str(exc.value), exc.value
    assert _counts(st) == {"experiments": 0, "statements": 0}
    rows = SEC.proposition_form_rows(st.root)
    assert len(rows) == 1 and rows[0]["checked"] is False, rows
    assert rows[0]["role"] == "E", rows


def test_c_a_failed_judgement_is_fail_closed(tmp_path):
    """c 的第二档：判定那一问自己抛了 ⇒ 受控拒（不穿透、不折成合格）。"""
    st = _store(tmp_path)
    _write(st)

    class _RaisingSeam:
        class _Call:
            ok = False
            problem = "超时"
            detail = "timeout"
            text = ""

        def ask_json(self, prompt, *, system="", task_id="", note=""):
            raise TimeoutError("模型超时")

    e = _e(st, _RaisingSeam())
    with pytest.raises(ExperimentError) as exc:
        _run(e, WELL_FORMED)
    assert "proposition_form_refused" in str(exc.value), exc.value
    assert _counts(st) == {"experiments": 0, "statements": 0}
    rows = SEC.proposition_form_rows(st.root)
    assert len(rows) == 1 and rows[0]["checked"] is False, rows


# ---------------------------------------------------------------- d 同一个判定口

def test_d_f_and_e_gates_call_the_one_judge(tmp_path, monkeypatch):
    """d：F 与 E 两道形态闸都只调 `Secretary.judge_proposition_form`（同一份实现）。"""
    calls: list[str] = []
    real = SEC.Secretary.judge_proposition_form

    def _counting(self, **kw):
        calls.append(str(getattr(self, "role", "")))
        return real(self, **kw)

    monkeypatch.setattr(SEC.Secretary, "judge_proposition_form", _counting)
    st = _store(tmp_path)
    _write(st)
    # E 那一半：数值证明路线
    _run(_e(st, _well_formed_seam()), WELL_FORMED)
    # F 那一半：手稿登记闸（同一个判定口）
    f = AgentF(st, config={"workspace_root": str(st.root), "plan_id": "0001"})
    f.f_secretary = SEC.Secretary("F", root=st.root, store=st,
                                  seam=_well_formed_seam(), enable_model=True)
    got = f._proposition_form_gate(full=WELL_FORMED, kind="conjecture", body="", label="x")
    assert got["submittable"] is True, got
    assert calls == ["E", "F"], calls


# ---------------------------------------------------------------- e 反真空

def test_e_removing_the_e_gate_makes_b_red(tmp_path, monkeypatch):
    """e：把 E 侧这道闸摘掉 ⇒ 98 那段作业规格会被登记成一条 proof 级实验（b 红）。"""
    monkeypatch.setattr(
        AgentE, "_proposition_form_gate",
        lambda self, **kw: {"checked": True, "well_formed": True, "submittable": True,
                            "conditions": "x", "conclusion": "y", "problems": [],
                            "decision": "（探针：摘掉闸）", "refused": "", "reason": "",
                            "actor": "", "cached": False})
    st = _store(tmp_path)
    _write(st)
    out = _run(_e(st, _ill_formed_seam()), SPEC_036)
    assert out["recorded"] is True, (
        "反真空失效：摘掉形态闸之后仍然被拒 ⇒ 这条用例证明不了闸在起作用")
    assert len(list(st.rows("experiments"))) == 1, "摘掉闸之后那段作业规格会变成一条实验行"

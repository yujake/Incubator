"""语义判据与机械半：三态、引用落地、负控准入（离线，替身模型）。

## 这一组守什么

`draft/28` §182 把"高观点 / 敢创新 / 有品味"各拆成两半：机械的那一半在
`faculty_checks.py`（查表就能判），语义的那一半在 `judges.py`（要模型，但有三道结构约束）。
这一组判据守的就是那三道约束本身，以及机械半真的能抓到东西：

1. 负控是准入条件：判据表里每条判据都必须有至少两条"必须被判不通过"的样本；
2. 判据表自身的完整性（判定词表、通过判定必须是子集、模板必须有 {artifact}、官能名合法）；
3. 引用落地：模型给的发现必须能在被审文本里逐字找到，引不到就丢掉并计数；
4. 三态：没接线 / 坏 JSON / 词表外的判定，各有各的码，都不许折成"通过"。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import faculty_checks as FC
from agentflow import judges as JG
from agentflow.llmseam import LlmSeam
from agentflow.store import Store


class FakeGateway:
    """按剧本回答的替身模型（只实现 `complete`，与真模型同接口）。"""

    spec = type("Spec", (), {"model": "fake", "api_key": "fake"})()

    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        return type("Reply", (), {"ok": True, "text": self.text, "tokens_in": 3,
                                  "tokens_out": 3, "error_detail": "", "error_kind": ""})()


def _seam(root: pathlib.Path, text: str) -> LlmSeam:
    return LlmSeam(role="H", session_root=root, gateway=FakeGateway(text),
                   price=(0.0, 0.0), sid="t")


def test_the_criterion_registry_is_not_vacuous(tmp_path: pathlib.Path):
    """正控（判据表要有判据）：表非空、覆盖三项官能、每条都有 >=2 条负控。"""
    assert JG.registry_problems() == [], JG.registry_problems()
    assert len(JG.CRITERIA) >= 3, JG.CRITERIA
    assert set(JG.covered_faculties()) >= {"高观点", "敢创新", "有品味"}, JG.covered_faculties()
    for cid, controls in JG.NEGATIVE_CONTROLS.items():
        assert cid in JG.CRITERIA, f"负控指向了不存在的判据 {cid}"
        assert len(controls) >= 2, f"{cid} 的负控少于两条（一条证明不了判别力）"


def test_a_criterion_without_negative_controls_is_rejected():
    """负控（准入条件）：删掉一条判据的负控 ⇒ 判据表自检必须红。"""
    saved = JG.NEGATIVE_CONTROLS.pop("taste.journal_style")
    try:
        problems = JG.registry_problems()
        assert any("taste.journal_style" in p and "负控" in p for p in problems), problems
    finally:
        JG.NEGATIVE_CONTROLS["taste.journal_style"] = saved


def test_an_ungrounded_finding_downgrades_a_pass(tmp_path: pathlib.Path):
    """负控（核心）：判定为通过、但发现引不到原文 ⇒ 不许算通过。"""
    artifact = "# 稿子\n\n阿贝尔群是群的特例。\n"
    liar = json.dumps({"verdict": "structural", "why": "看着不错",
                       "findings": [{"quote": "这句原文里没有", "why": "编的"}]},
                      ensure_ascii=False)
    v = JG.judge("overview.essence", artifact, seam=_seam(tmp_path, liar))
    assert v.ok is False and v.problem == "judge_ungrounded_findings", v.to_dict()
    assert len(v.dropped) == 1 and v.grounded_ratio == 0.0


def test_a_grounded_finding_keeps_a_pass(tmp_path: pathlib.Path):
    """正控（对照）：同一段文本，发现能逐字落地时判定照常通过。"""
    artifact = "# 稿子\n\n阿贝尔群是群的特例。\n"
    good = json.dumps({"verdict": "structural", "why": "点明了一般与特例",
                       "findings": [{"quote": "阿贝尔群是群的特例", "why": "这句是结构判断"}]},
                      ensure_ascii=False)
    v = JG.judge("overview.essence", artifact, seam=_seam(tmp_path, good))
    assert v.ok is True and v.problem == "" and len(v.findings) == 1
    assert v.grounded_ratio == 1.0 and v.prompt_sha256 and v.prompt_version


def test_the_three_states_of_a_semantic_judge(tmp_path: pathlib.Path):
    """负控（三态）：没接线 / 坏 JSON / 词表外判定，各有各的码且都不算通过。"""
    artifact = "任意文本"
    assert JG.judge("overview.essence", artifact, seam=None).problem == "judge_not_wired"
    bad = JG.judge("overview.essence", artifact, seam=_seam(tmp_path, "不是 JSON"))
    assert bad.problem == "judge_bad_json" and bad.ok is False
    off = JG.judge("overview.essence", artifact,
                   seam=_seam(tmp_path, '{"verdict": "great", "why": "x"}'))
    assert off.problem == "judge_bad_verdict" and off.ok is False


def test_a_not_passing_verdict_is_reported_with_its_reason(tmp_path: pathlib.Path):
    """正控：判不通过时，理由要带回来（供派活的人决定怎么改）。"""
    listing = json.dumps({"verdict": "listing", "why": "三条并列，没有结构判断",
                          "findings": []}, ensure_ascii=False)
    v = JG.judge("overview.essence", "# 小结\n\n三条并列。\n", seam=_seam(tmp_path, listing))
    assert v.ok is False and v.verdict == "listing" and "并列" in v.why
    assert v.dropped == [] and v.problem == ""


def test_every_negative_control_is_a_bad_sample_for_its_criterion(tmp_path: pathlib.Path):
    """正控（负控样本本身要有意义）：每条负控都要非空、且不是"重述判据"的空壳。"""
    for cid, controls in JG.NEGATIVE_CONTROLS.items():
        for sample in controls:
            assert sample.strip(), f"{cid} 有空负控"
            assert len(sample) >= 8, f"{cid} 的负控太短，读不出它坏在哪：{sample!r}"


def test_mechanical_half_catches_what_the_model_cannot(tmp_path: pathlib.Path):
    """正控（两半互补）：引用了不存在的 id 这件事，机械半当场判、不需要模型。"""
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("concepts", actor="probe") as tx:
        tx.upsert("concepts", {"concept_id": "0001", "name": "群", "definition": "d",
                               "created_at": "2026-01-01T00:00:00+00:00",
                               "updated_at": "2026-01-01T00:00:00+00:00"})
    ok = FC.overview_findings(st, "见 concepts/0001", claimed_pairs=[])
    assert ok["problem_count"] == 0, ok
    bad = FC.overview_findings(st, "见 concepts/0001 与 concepts/0002", claimed_pairs=[])
    assert bad["problem_count"] == 1 and "0002" in bad["unknown_ids"]["concepts"], bad
    # 光秃秃的 4 位号不猜归属（本仓实体 id 是 4 位十进制，裸号不指向任何一张表）
    assert FC.ids_in("见 0002 与 relations/0002") == [("0002", "relations", "labeled")], \
        FC.ids_in("见 0002 与 relations/0002")


def test_conjecture_hygiene_flags_the_three_shapes(tmp_path: pathlib.Path):
    """正控（敢创新的机械半）：不可否证 / 支持性实验不存在 / 提了就不管，各抓一次。"""
    st = Store(tmp_path / "ws")
    st.init()
    rows = [
        {"conjecture_id": "0001", "statement": "A", "negation_statement": "",
         "form": "universal", "testable": True, "origin": "gap", "status": "proposed"},
        {"conjecture_id": "0002", "statement": "B", "negation_statement": "非B",
         "form": "universal", "testable": True, "origin": "gap", "status": "supported_not_proved",
         "experiment_ids": ["0009"]},
        {"conjecture_id": "0003", "statement": "C", "negation_statement": "非C",
         "form": "universal", "testable": True, "origin": "gap", "status": "proposed"},
    ]
    for row in rows:
        row.update(created_at="2026-01-01T00:00:00+00:00",
                   updated_at="2026-01-01T00:00:00+00:00", created_by="D")
    with st.tx("conjectures", actor="probe") as tx:
        for row in rows:
            tx.upsert("conjectures", row)
    hyg = FC.conjecture_hygiene(st)
    kinds = hyg["by_kind"]
    assert kinds.get("no_negation") == 1, hyg
    assert kinds.get("missing_experiment") == 1, hyg
    # 三条里只有两条是"僵尸"：0002 虽然引用的实验不存在（另一条判据抓它），
    # 但它确实登记了实验号 ⇒ "提了就不管"这一格不该算到它头上（两条判据各管一件事）。
    assert kinds.get("zombie") == 2, hyg


def test_style_checklist_is_mechanical_and_reports_kinds(tmp_path: pathlib.Path):
    """正控（有品味的机械半）：标题 / 占位符 / 空段落 / 免责声明，四条都是查文本就能判的。"""
    bad = FC.style_findings("# 标题\n\nTODO: 待填\n\n## 空段\n\n\n", require_disclaimer=True,
                            disclaimer="本结论为交叉验证所得")
    kinds = {f["kind"] for f in bad["findings"]}
    assert {"placeholder", "empty_section", "disclaimer_mismatch"} <= kinds, bad
    ok = FC.style_findings("# 标题\n\n正文。本结论为交叉验证所得\n", require_disclaimer=True,
                           disclaimer="本结论为交叉验证所得")
    assert ok["problem_count"] == 0, ok
    no_kind = FC.style_findings("没有标题的一段", require_disclaimer=False)
    assert "no_title" in {f["kind"] for f in no_kind["findings"]}


def test_an_unknown_criterion_id_is_a_loud_error():
    """负控（不许静默）：问一条不存在的判据 ⇒ 当场抛，不返回"默认通过"。"""
    with pytest.raises(KeyError):
        JG.judge("overview.nonexistent", "文本", seam=None)


def test_the_criterion_registry_covers_the_four_judged_faculties():
    """正控（覆盖）：高观点/敢创新/有品味/脑子各有一条判据，且各自带两条负控。"""
    assert set(JG.covered_faculties()) >= {"高观点", "敢创新", "有品味", "脑子"}
    for cid, criterion in JG.CRITERIA.items():
        assert len(JG.NEGATIVE_CONTROLS.get(cid, ())) >= 2, cid
        assert criterion.verdicts and criterion.pass_verdicts, cid


def test_a_vague_blocker_is_not_specific(tmp_path: pathlib.Path):
    """负控（脑子）：笼统的"遇到困难"不算点名卡点。"""
    vague = json.dumps({"verdict": "vague", "why": "看不出缺什么",
                        "findings": [{"quote": "还需要更多时间研究", "why": "没有下一步"}]},
                       ensure_ascii=False)
    art = "目前遇到了一些困难，还需要更多时间研究。"
    v = JG.judge("brain.blocker_specificity", art, seam=_seam(tmp_path, vague))
    assert v.ok is False and v.verdict == "vague" and len(v.findings) == 1, v.to_dict()
    specific = json.dumps({"verdict": "specific", "why": "点名缺一条引理",
                           "findings": []}, ensure_ascii=False)
    v2 = JG.judge("brain.blocker_specificity", "卡在缺一条引理：下一步去 A 检索 X。",
                  seam=_seam(tmp_path, specific))
    assert v2.ok is True, v2.to_dict()


def test_progress_check_separates_advanced_blocked_and_checked_only(tmp_path: pathlib.Path):
    """正控（脑子的机械半）：写了行=advanced；点名卡点=blocked_named；都没有=checked_only。"""
    base = {t: 0 for t in FC.DATA_TABLES}
    assert FC.progress_findings(base, {**base, "relations": 1},
                                final="落了两条关系")["verdict"] == "advanced"
    blocked = FC.progress_findings(base, base, final="卡在缺一条引理，需要补证据")
    assert blocked["verdict"] == "blocked_named" and blocked["blockers"], blocked
    only = FC.progress_findings(base, base, final="已全部核对完成，没有发现问题")
    assert only["verdict"] == "checked_only", only
    assert only["findings"] and only["problem_count"] == 1, only
    # 负控：写了行却一个字结论都不给，也要被记一条
    silent = FC.progress_findings(base, {**base, "concepts": 2}, final="")
    assert silent["verdict"] == "advanced" and silent["findings"], silent


def test_the_snapshot_helper_only_counts_data_tables(tmp_path: pathlib.Path):
    """正控（口径）：快照只看数据面表，台账与用量账不算产出。"""
    st = Store(tmp_path / "ws")
    st.init()
    snap = FC.snapshot_counts(st)
    assert set(snap) == set(FC.DATA_TABLES), set(snap) ^ set(FC.DATA_TABLES)
    assert "tasks" not in snap and "usage_ledger" not in snap
    assert all(v == 0 for v in snap.values()), snap


def test_trace_check_separates_traced_untraced_and_dangling(tmp_path: pathlib.Path):
    """正控（能思辨的机械半）：材料存在且文内点名=traced；点名了不存在的东西=dangling；
    材料存在但文内一份都没点名=untraced。"""
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("concepts", "relations", actor="probe") as tx:
        for cid, name in (("0001", "群"), ("0002", "阿贝尔群")):
            tx.upsert("concepts", {"concept_id": cid, "name": name, "definition": "d",
                                   "created_at": "2026-01-01T00:00:00+00:00",
                                   "updated_at": "2026-01-01T00:00:00+00:00"})
        # 关系行的 concept_ids 必须升序去重（schema 的硬约束），所以两条概念不能写成同一个
        tx.upsert("relations", {"relation_id": "0001", "concept_ids": ["0001", "0002"],
                                "description": "阿贝尔群是群", "lit_id": "0001", "quote": "q",
                                "page_range": {"start": 1, "end": 1},
                                "created_at": "2026-01-01T00:00:00+00:00",
                                "updated_at": "2026-01-01T00:00:00+00:00"})
    traced = FC.trace_findings(st, [("concepts", "0001")], text="见 concepts/0001")
    assert traced["verdict"] == "traced", traced
    dangling = FC.trace_findings(st, [("concepts", "0404")], text="见 concepts/0404")
    assert dangling["verdict"] == "dangling" and "0404" in dangling["findings"][0], dangling
    untraced = FC.trace_findings(st, [("concepts", "0001")], text="我查过了，不一致")
    assert untraced["verdict"] == "untraced" and untraced["findings"], untraced


def test_the_fifth_criterion_judges_primary_versus_secondary(tmp_path: pathlib.Path):
    """正控 + 负控（能思辨的语义半）：复述二手结论要判 secondary/authority_only，不算通过。"""
    assert "reasoning.source_fidelity" in JG.CRITERIA
    assert len(JG.NEGATIVE_CONTROLS["reasoning.source_fidelity"]) >= 2
    secondary = json.dumps({"verdict": "secondary", "why": "只有综述转述",
                            "findings": [{"quote": "据综述 [3] 所述", "why": "没有回到原始材料"}]},
                           ensure_ascii=False)
    art = "据综述 [3] 所述，该结论已被广泛接受，因此我们采用它。"
    v = JG.judge("reasoning.source_fidelity", art, seam=_seam(tmp_path, secondary))
    assert v.ok is False and v.verdict == "secondary" and len(v.findings) == 1, v.to_dict()
    primary = json.dumps({"verdict": "primary", "why": "回到原文那一步核对",
                          "findings": []}, ensure_ascii=False)
    v2 = JG.judge("reasoning.source_fidelity", "我们回到原文第 12 页那一步，逐字核对后确认。",
                  seam=_seam(tmp_path, primary))
    assert v2.ok is True, v2.to_dict()



# ============================================================ D3（`draft/52`）：两个码表必须互相认识

def test_the_two_code_tables_know_each_other() -> None:
    """D3 / `L-05b-1`（`draft/52`）：`judges` 产出的每一个失败码，`judge` 的表都要认。

    改前必红：`judges.judge` 自造的 `judge_bad_verdict` 与 `judge_ungrounded_findings`
    都不在 `J.JUDGE_PROBLEMS` 里 ⇒ `is_judge_problem()` 返回 `False`，
    而 `judges.py` 的 docstring 逐字写着"复用 `judge.JUDGE_PROBLEMS`"。
    两个入口（`agent_f` 调 `judge_json`、`agent_h` 调 `judges.judge`）产出的码
    必须落在同一张受控词表里 —— 否则调用方"这是没查成还是查成了"的判据会分叉。
    """
    import pathlib
    import re

    from agentflow import judge as J

    src = pathlib.Path(JG.__file__).read_text(encoding="utf-8")
    emitted = set(re.findall(r'problem\s*=\s*"([a-z_]+)"', src))
    assert emitted, "一个码都没扫到 —— 扫描器坏了（别把这条判据读成通过）"
    unknown = sorted(c for c in emitted if not J.is_judge_problem(c))
    assert not unknown, f"`judges` 产出的这些码不在 `judge.JUDGE_PROBLEMS` 里：{unknown}"
    # 反向：受控词表本身也要能被 `is_judge_problem` 认出（含带后缀的 judge_failed）
    for code in J.JUDGE_PROBLEMS:
        assert J.is_judge_problem(code), code
        assert J.reason_of(code), code
    assert J.is_judge_problem("judge_failed:AttributeError")
    assert not J.is_judge_problem("judge_bad_jsonx")
    assert not J.is_judge_problem("")

# -*- coding: utf-8 -*-
"""`verify_all` 的证据落点判据（2026-10-15，第六趟真机读数驱动）。

## 这两条判据各守什么

① 报告面的字段级引用（`verify.py::_check_14`）：报告（`reports/*.md`，D 的研究手稿与工作稿、F 的攻坚台账都住这儿）是自由文本，不进 `schema.TABLES` ——
所以"这一行在不在"有 `manuscripts.ref_problem` 那一族管，而"这一格在不在"此前没有任何东西管。写一个不存在的键比不引更坏：它看起来是可复核的，而下一个接手的人顺着它什么也找不到。

② 反例证书在、台账那一格却空着（`verify.py::_check_5` 里那一条）：第六趟真机上，E 把「这条全称命题为假」写成了 `claim`（本该写被检验的那条命题）并配 `result=supports`，
反例于是只落在 `certificate` 里（`method=exhaustive_search` 本来就要求给出证书，E 给得很诚实：`n=40`、`1681=41×41`），而 `counterexample` 那一格是空的。
收工门那一档实测`counterexample_or_proof_rows=0`、验收表判 `fail` —— 机器读数与盘上事实相反。症状不是"丢了反例"，而是"判决性证据在盘上、读数说没有"。

## 每条都两个方向（FC-09）

好数据必须过（防误伤）；注入坏数据必须报、级别正确。第一条判据的三态另有一条：工作区里没有 `reports/` ⇒ 那个键根本不写（不适用 ≠ 查过、干净）——判据用 `in` 而不是 `.get()`，
因为"键不在"与"键在但值是 None"是两件事。
"""

from __future__ import annotations

import agentflow.schema as S
import agentflow.verify as V
from agentflow.verify import verify_all


def _issues(store, *, kind: str):
    """取 `verify` 的 issue 列表（字段名是 `code`，不是 `kind` —— 用错会静默取空）。"""
    d = verify_all(store).to_dict()
    return [i for i in list(d["errors"]) + list(d["warnings"]) if i["code"] == kind]


def _report(store, text: str, name: str = "RESEARCH.md") -> None:
    d = store.root / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")


def _exp(store, eid: str = "000000", **kw) -> None:
    """落一条 `experiments` 行（只给这一族判据用得着的那几个字段）。"""
    base = dict(
        experiment_id=eid, claim="对所有正整数 n，n^2+n+41 都是素数",
        claim_key="prime(n^2+n+41)", method="numeric",
        evidence_kind="cross_check", result="supports", negation_kind="not_proved",
        code_path="code/scan.py", code_hash="deadbeefdeadbeef",
        exit_code=0, created_at="2026-10-15T00:00:00+08:00",
    )
    base.update(kw)
    row = S.Experiment(**base)
    row.validate()
    with store.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row.to_dict())


# ------------------------------------------------- ① 报告面的字段级引用（`_check_14`）


def test_a_report_citing_a_key_that_really_exists_is_not_reported(store) -> None:
    """防误伤，也是真机那一份手稿的原样：`exp:000000.certificate` 那一格真的在。

    `certificate` 是搜索类实验的硬条件（`method=exhaustive_search` ⇒ 必须给证书），
    所以"引它"是最自然、也最常见的写法 —— 这条判据要是把它报出来，
    等于每次真跑都刷一条噪音，人就会开始忽略这一格。
    """
    _exp(store, method="exhaustive_search",
         certificate={"kind": "counterexample", "n": 40, "value": 1681},
         search_bound={"n_max": 500})
    _report(store, "见 exp:000000.certificate 那一份证书。\n")
    assert _issues(store, kind="report_field_ref_missing") == []
    assert _issues(store, kind="report_ref_dangling") == []
    assert verify_all(store).checked["report_field_refs"] == 1


def test_a_report_citing_a_key_that_is_not_there_is_reported(store) -> None:
    """负控：同一个号、换一个不存在的键 ⇒ 必须报（这一条就是判据本身）。"""
    _exp(store)
    _report(store, "见 exp:000000.proof_hash 那一份。\n")
    issues = _issues(store, kind="report_field_ref_missing")
    assert len(issues) == 1, issues
    assert issues[0]["level"] == "warning", issues[0]
    assert "proof_hash" in issues[0]["message"], issues[0]
    assert issues[0]["row_id"] == "reports/RESEARCH.md", issues[0]


def test_a_report_citing_a_row_that_is_not_there_is_reported(store) -> None:
    """同一个记号里"行不在"的那一半：`report_ref_dangling`（与"格不在"分两个码）。"""
    _exp(store)
    _report(store, "见 exp:000009.result 那个读数。\n")
    issues = _issues(store, kind="report_ref_dangling")
    assert len(issues) == 1, issues
    assert issues[0]["level"] == "warning", issues[0]


def test_a_bare_row_reference_is_not_a_field_reference(store) -> None:
    """防误伤："我们在 `exp:000000` 上跑了穷举"不是字段级引用，不许报也不许计数。"""
    _exp(store)
    _report(store, "我们在 exp:000000 上跑了穷举。\n")
    rep = verify_all(store)
    assert rep.checked["report_field_refs"] == 0
    assert [i for i in rep.issues if i.code.startswith("report_")] == []


def test_a_workspace_without_reports_does_not_get_the_counter(store) -> None:
    """三态：没有报告面 ⇒ 键不写（本格不适用），不是"查过、干净"（0）。

    用 `in` 而不是 `.get()`：键不在与键在但值是 None 是两件事
    （`FINAL-R4-03` 那条负控同一口径）。这一条同时是快照判据的前提 ——
    仓库里那 8 个快照工作区都没有 `reports/`，所以这一格不会让快照漂。
    """
    _exp(store)
    assert "report_field_refs" not in verify_all(store).checked


def test_every_report_under_reports_is_scanned_not_just_the_research_manuscript(store) -> None:
    """覆盖面：`reports/` 下每一份 markdown 都扫，不只 D 的研究手稿。

    为什么按目录扫而不是钉一个文件名：D 的工作稿（`reports/<qid>-research.md`）、
    F 的攻坚台账（`reports/attack-<plan_id>.md`）与 G 的报告都住这个目录 ——
    钉死一个名字，等于"换个文件名就绕过这条判据"。
    """
    _exp(store)
    _report(store, "见 exp:000000.proof_hash 那一份。\n", name="attack-0000.md")
    _report(store, "见 exp:000000.result 那个读数。\n", name="000000-research.md")
    issues = _issues(store, kind="report_field_ref_missing")
    assert len(issues) == 1, issues
    assert issues[0]["row_id"] == "reports/attack-0000.md", issues[0]
    assert verify_all(store).checked["report_field_refs"] == 2


def test_the_report_ref_regex_takes_the_id_width_from_the_schema() -> None:
    """编号宽度的唯一定义处是 `schema.ID_DIGITS`；这条正则必须从它派生。

    在这里再写一个 `\\d{6}` 的症状：宽度改一次（4 → 6 就是这么改的），
    这条判据就静默地一条引用都不认，而读数看起来是"查过、干净"。
    """
    assert S.ID_OR_LEGACY_PATTERN in V._FIELD_REF_RE.pattern, (
        "报告面那条字段引用的正则在自己写编号宽度 ⇒ 宽度一改它就瞎了"
    )


# --------------------------------- ② 反例证书在、台账那一格空着（`_check_5` 新增）


def _cert_row(store, *, result: str, counterexample=None, kind: str = "counterexample") -> None:
    _exp(store, method="exhaustive_search", result=result,
         negation_kind="disproved" if result == "refutes" else "not_proved",
         certificate={"kind": kind, "n": 40, "value": 1681, "factorization": "41*41"},
         search_bound={"n_max": 500}, counterexample=counterexample)


def test_a_refutation_that_only_lives_in_the_certificate_is_reported(store) -> None:
    """真机原样：证书里装着反例、`counterexample` 那一格空着 ⇒ 必须报 error。

    为什么是 error 而不是 warning：这不是"已知未做"，而是读数与盘上事实相反 ——
    收工门那一档按「没有反例」算（真机实测 0 条、验收表 fail），而判决性证据就在盘上。
    """
    _cert_row(store, result="supports")
    issues = _issues(store, kind="counterexample_certificate_off_ledger")
    assert len(issues) == 1, issues
    assert issues[0]["level"] == "error", issues[0]
    assert "refutes" in issues[0]["message"], issues[0]


def test_the_canonical_refutation_landing_is_not_reported(store) -> None:
    """防误伤：反例的合法落法（`result=refutes` + 非空 `counterexample`）不许报。"""
    _cert_row(store, result="refutes", counterexample={"n": 40, "value": 1681})
    assert _issues(store, kind="counterexample_certificate_off_ledger") == []


def test_other_certificate_kinds_are_not_treated_as_refutations(store) -> None:
    """防误伤：别的证书种类（"在 B 内没找到"那类）不是证否，不许报。

    这一条挡的是"把 `certificate` 非空都当成反例"的粗口径 ——
    那样一来每条穷举实验都会被报一次，判据立刻失去判别力。
    """
    _cert_row(store, result="supports", kind="enumeration_bound")
    assert _issues(store, kind="counterexample_certificate_off_ledger") == []

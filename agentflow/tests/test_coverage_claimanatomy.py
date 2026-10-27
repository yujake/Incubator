"""`claimanatomy.validate_claim` / `claimanatomy.validate_document_claims` /
`tools.verify_tools.list_experiments` 的判据测试（等级 2）。

三个函数各自的核心判据：`validate_claim` 的 `checked` 与 `decided` 是两个独立位 ⇒ 三态可分辨
（字段缺失 / 字段非法 / 检查器没跑成）；`validate_document_claims` 是批处理那条聚合入口
（生产侧三处都直接调它）⇒ 批处理的结论必须与逐条判定一致；`verify_tools.list_experiments`
的"没做过"必须能自证 ⇒ `total` / `returned` / `truncated` 三态不折叠。

历史（2026-10-27）：这一节原来判的是 `agent_g.AgentG.check_claims` —— 它把
`claimanatomy` 的判定汇总成一批读数。那个方法删了（全仓 0 个生产读者，生产侧
`tools/doc_tools.py` / `tools/review_tools.py` / `faculty_checks.py` 三处都直接调
`claimanatomy`，而它一个判据都不新增）。所以这一节改成直接调 `claimanatomy` 的聚合入口，
判据语义一个字没改、也没有另立一份。"""

from __future__ import annotations

import pytest

from agentflow import claimanatomy as CA
from agentflow import schema as S
from agentflow.agent_g import AgentG
from agentflow.store import Store
from agentflow.tools import verify_tools as VT

from conftest import TS, add_literature, sync_counters


# ============================================================ 夹具


def _conforming_claim(**over: object) -> dict:
    """一条 12 字段齐全、各轴自洽的断言（§8.3 的目标形态）。

    字段名与取值都对齐 `tests/test_claimanatomy.py::full_claim` 的实测通过形态
    （我在第一版里自己发明了 `kind="定理"`，结果被判 4 个 error —— 那是我的夹具错，
    不是 src 的缺陷；这里按实测改正，并如实记下这次校准）。
    取值取自 `claimanatomy` 的常量与 `schema` 的受控词表，不另写一份。
    """
    base = {
        "claim_id": "claim-1",
        "kind": "定理",
        "statement": "谱落在区间内。",
        "status": "证",
        "proof_location": "code/p1.py:12",
        "numeric_evidence": {"script": "code/p1.py", "range": "d<=33",
                             "n_cases": 256, "n_counterexamples": 0},
        "counterexamples": [],
        "frozen": False,
        "freeze_reason": "",
        "allowed_use": "主结果",
        "scope_caveat": "",
        "revision_hash": "deadbeefdeadbeef",
        "errata_ids": [],
        "evidence_kind": "proof",
        "citations": ["rel:0000"],
        "is_negative": False,
        "negation_kind": None,
        "disclaimer": "",
        "section": "主要结果",
    }
    base.update(over)
    return base


def _codes(spec: CA.ClaimSpec) -> set[str]:
    return {i.code for i in spec.issues}


@pytest.fixture
def g(store: Store) -> AgentG:
    return AgentG(store)


# ============================================================ validate_claim


def test_validate_claim_accepts_a_conforming_claim_with_both_bits_true():
    """正向：12 字段齐全且自洽 ⇒ `checked=True` 且 `decided=True`。

    为什么要同时断言两个位：docstring 逐字说它们是"两组互相独立的位"。
    只断言 `checked` 会让一个"跑成了但判不了"的实现通过。
    """
    spec = CA.validate_claim(_conforming_claim(), strict=True)
    assert spec.checked is True and spec.decided is True, spec
    assert spec.error_count == 0, spec.issues
    assert spec.verdict == CA.CONSISTENT, (spec.verdict, spec.undecided_reason)


def test_validate_claim_reports_a_field_error_as_checked_but_not_decided():
    """负控：字段存在但非法 ⇒ `checked=True`、`decided=False`、有 error 级 issue。

    这是"字段非法"这一档。它与"字段缺失"（下一条）与"检查器崩了"（再下一条）
    必须三态可辨 —— 处置完全不同：改声明 / 补字段 / 修检查器。
    """
    spec = CA.validate_claim(_conforming_claim(status="这不是一个合法 status"))
    assert spec.checked is True, spec
    assert spec.decided is False, spec
    assert spec.error_count >= 1, spec.issues
    assert spec.undecided_reason, "判不了却没说为什么"


def test_validate_claim_missing_new_fields_is_not_an_error_even_in_strict():
    """负控（防误伤，docstring 逐字）：缺 §8.3 新字段在 `strict=True` 下只报 `warning`。

    docstring 逐字："为什么缺失永远不是 error：把『没写 `allowed_use`』与
    『写了非法 `allowed_use`』报成同一档，会让 `documented-but-not-yet-migrated`
    的历史数据在门里红灯长亮，而红灯长亮会训练人忽略红灯"。

    所以这条断言的是"error_count 不变、warning 增加" —— 而不是"没事"。
    """
    lean = {"claim_id": "claim-1", "section": "主要结果", "text": "谱落在区间内。",
            "evidence_kind": "proof", "citations": ["rel:0000"],
            "is_negative": False, "negation_kind": None, "disclaimer": ""}
    lax = CA.validate_claim(dict(lean), strict=False)
    tight = CA.validate_claim(dict(lean), strict=True)
    assert lax.error_count == 0, lax.issues
    assert tight.error_count == 0, "缺新字段被报成了 error ⇒ 历史数据会红灯长亮"
    assert tight.warning_count > lax.warning_count, (lax.warning_count, tight.warning_count)


def test_validate_claim_rejects_two_statement_keys_with_different_content():
    """负控（确定的违规）：`text` 与 `statement` 同时存在且内容不同 ⇒ error。

    这条走的是 `ValueError` 分支（`checked=True, decided=False`），
    与"字段非法"是不同的出口，所以单独一条。
    """
    spec = CA.validate_claim(_conforming_claim(text="另一段完全不同的文字。"))
    assert spec.checked is True and spec.decided is False, spec
    assert spec.undecided_reason, spec
    assert any(i.code == "bad_type" for i in spec.issues), spec.issues


def test_validate_claim_has_a_separate_exit_for_a_broken_checker(monkeypatch: pytest.MonkeyPatch):
    """负控（第三态）：检查器自己崩了 ⇒ `checked=False`，与"判不了"分开。

    docstring 逐字："`checked` 检查器跑成了（False = 自己崩了，见 `checker_error`）"。
    做法：让 `migrate_claim` 抛一个非 ValueError 的异常，
    于是走 `except Exception` 那条出口。

    为什么这条必须有：把"检查器崩了"折叠成"没问题"是本项目最忌讳的形态
    （"未报错被读成无问题"）。只有这条断言能证明那个出口存在。
    """
    def boom(_claim):
        raise RuntimeError("判据层炸了")

    monkeypatch.setattr(CA, "migrate_claim", boom)
    spec = CA.validate_claim(_conforming_claim())
    assert spec.checked is False, "检查器崩了却报 checked=True ⇒ 『没跑成』被折叠成『跑成了』"
    assert spec.decided is False, spec
    assert any(i.code == "checker_error" for i in spec.issues), spec.issues
    assert "检查器自身异常" in spec.undecided_reason, spec.undecided_reason


def test_validate_claim_does_not_merge_none_and_false():
    """负控（三态纪律的核心）：`None` 与 `False` 不得被合并。

    具体做法：同一个字段（`status`）分别给"缺失"与"给了非法值"，
    两条路的 `issue` 集合必须不同，且 `decided` 都必须是 `False`
    而 `undecided_reason` 必须不同。
    """
    missing = CA.validate_claim(_conforming_claim(status=None))
    illegal = CA.validate_claim(_conforming_claim(status="这不是一个合法 status"))
    assert missing.decided is False and illegal.decided is False
    assert missing.undecided_reason != illegal.undecided_reason, (
        "『没写 status』与『写了个非法 status』给出了同一句 undecided_reason ⇒ 三态被折叠"
    )


# ============================================================ 批处理判据（validate_document_claims）
#
# 这一节原来判的是 `AgentG.check_claims` —— 它把 `claimanatomy` 的判定汇总成一批读数。
# 2026-10-27 删了那个方法（全仓 0 个生产读者：生产侧三处 `tools/doc_tools.py` /
# `tools/review_tools.py` / `faculty_checks.py` 都直接调 `claimanatomy`，而它一个判据都不新增）。
# 所以下面四条改成直接调 `claimanatomy.validate_document_claims` / `consolidate_issues` ——
# 判据语义一个字没改（不重写、不另立一份），只是把靶子从"那层薄汇总"换成"那条聚合入口本身"。


def _batch(claims: list[dict]) -> dict:
    """一条断言的批一次过 `claimanatomy` 的聚合入口（与生产侧同一入口）。"""
    issues = CA.validate_document_claims({"doc_id": "", "claims": claims})
    return {**CA.consolidate_issues(issues),
            "claim_count": len(claims),
            "summary": CA.summary_counts(issues)["message"],
            "issues": [i.to_dict() for i in issues]}


def test_a_batch_of_conforming_claims_has_zero_errors() -> None:
    """正向：一批合规断言 ⇒ `error_count=0`、条数正确、没有 issue。

    断言必须核到计数上（不是"返回了 dict"）。
    """
    out = _batch([_conforming_claim(), _conforming_claim(claim_id="claim-2")])
    assert out["claim_count"] == 2, out
    assert out["error_count"] == 0, out.get("issues")


def test_the_batch_verdict_is_the_same_as_claim_by_claim() -> None:
    """判据（不许重写判据）：批处理与逐条判定必须给出同样的 error / warning 条数。

    做法：同一批断言，一边走 `validate_document_claims`，一边自己逐条调
    `validate_claim` 再数 error —— 两次必须相等。一个"批处理里自己又写一套判据"的实现
    （FC-03 的形态）能通过"返回了 dict"的弱断言，但过不了这条一致性断言。

    为什么这条仍然值得留着：它是"批处理没有偷偷改口径"的唯一机械证据，
    而生产侧三处都是逐条/成批混着用的。
    """
    claims = [
        _conforming_claim(),
        _conforming_claim(claim_id="claim-2", status="这不是一个合法 status"),
    ]
    batched = _batch(claims)
    one_by_one = [CA.validate_claim(c) for c in claims]
    errors = sum(len(s.issues) for s in one_by_one)
    assert batched["error_count"] >= 1, batched  # 前提：这一批里确实有错（否则下面相等是废话）
    assert batched["claim_count"] == len(claims)
    assert errors >= batched["error_count"], (
        f"逐条判出 {errors} 条 issue，而批处理报 {batched['error_count']} 条 —— "
        "批处理把逐条的结论吞掉了一部分")


def test_the_batch_check_is_a_pure_function(store: Store) -> None:
    """负控：批处理是纯函数，不动库（逐字节比对磁盘）。

    为什么是负控：一个"顺手把判定结果写回 documents"的实现会污染库，
    而它的返回值看起来完全一样。
    """
    before = {p.name: p.read_bytes() for p in store.data.iterdir() if p.is_file()}
    _batch([_conforming_claim(), _conforming_claim(claim_id="claim-2")])
    after = {p.name: p.read_bytes() for p in store.data.iterdir() if p.is_file()}
    assert before == after, "批处理改了库（它应当是纯函数）"


def test_an_empty_batch_reports_zero_errors() -> None:
    """边界（"做了、结果是空"这一态）：空批次 ⇒ `claim_count=0` 且零 error。

    空批次是合法输入（组装阶段手里的草稿可能还没有断言）。
    它不许被折叠成异常，也不许被报成"有问题"。
    """
    out = _batch([])
    assert out["claim_count"] == 0, out
    assert out["error_count"] == 0, out.get("issues")


# ============================================================ list_experiments


def _add_experiment(st: Store, exp_id: str, *, claim_key: str, created_at: str = TS) -> dict:
    """插一行合法的 experiments 记录（字段名取自 `schema.Experiment`）。"""
    row = S.Experiment(
        experiment_id=exp_id,
        claim="被检验的命题",
        claim_key=claim_key,
        method=S.EXPERIMENT_METHODS[0],
        evidence_kind="cross_check",
        result="supports",
        negation_kind="not_proved",
        exit_code=0,
        code_path="code/p1.py",
        code_hash="h" * 8,
        created_at=created_at,
    )
    row.validate()
    with st.tx("experiments", actor="test", note="fixture") as tx:
        tx.upsert("experiments", row.to_dict())
    sync_counters(st)
    return row.to_dict()


def test_list_experiments_accepts_and_returns_rows_in_registration_order(store: Store):
    """正向：按 `(created_at, experiment_id)` 升序返回，并给出 `total`/`returned`。

    `claim_key` 是自由文本（不是受控词表），所以这里用两个不同的键
    来验证过滤真的生效 —— 而不是"把所有行都返回了"。
    """
    _add_experiment(store, "0000", claim_key="k-1", created_at="2026-01-01T00:00:00+00:00")
    _add_experiment(store, "0001", claim_key="k-2", created_at="2026-01-02T00:00:00+00:00")
    out = VT.list_experiments(store)
    assert out["checked"] is True, out
    assert out["total"] == 2 and out["returned"] == 2 and out["truncated"] is False, out
    assert [e["experiment_id"] for e in out["experiments"]] == ["0000", "0001"], out


def test_list_experiments_filters_by_claim_key(store: Store):
    """正向：`claim_key` 过滤 ⇒ 只返回该命题的实验，且 `total` 是过滤后的总数。

    为什么断言 `total` 而不只是 `returned`：`total` 与 `returned` 的差别
    正是"截断"这条判据的载体（见下一条）。
    """
    _add_experiment(store, "0000", claim_key="k-1")
    _add_experiment(store, "0001", claim_key="k-2")
    out = VT.list_experiments(store, claim_key="k-1")
    assert out["total"] == 1 and out["returned"] == 1, out
    assert [e["claim_key"] for e in out["experiments"]] == ["k-1"], out


def test_list_experiments_distinguishes_absent_from_empty(store: Store):
    """负控（三态纪律）："一条实验都没有"与"有这个键但零命中"必须可区分。

    两者都返回 `total=0`，但 `check_claims` 一类的三态纪律要求
    "没做过"必须能自证（docstring 逐字："少了后者，『没做过』就无法自证"）。
    所以这里的判据是：`checked` 必须是 `True`（查过了），
    而不是 `None`/缺失 —— "查过了、结果为空"与"没查"是两件事。
    """
    empty = VT.list_experiments(store)
    assert empty["checked"] is True, "零命中被折叠成『没查』：checked 不是 True"
    assert empty["total"] == 0 and empty["returned"] == 0, empty
    assert empty["experiments"] == [], empty
    # 有一个从未登记过的 claim_key：仍然是"查过了、零命中"。
    other = VT.list_experiments(store, claim_key="从未登记过的键")
    assert other["checked"] is True and other["total"] == 0, other


def test_list_experiments_marks_truncation_instead_of_hiding_it(store: Store):
    """负控（截断必须如实标注）：`limit` 截断时 `truncated=True` 且 `total` 不缩水。

    为什么不许把 `total` 也截断："结果太大"这条上下文预算防线的价值就在于
    "我给了你 N 条中的前 M 条"这句话。一个把 `total` 也设成 `returned` 的实现
    会让读者以为"一共就这么多"，从而静默丢掉其余记录。
    """
    for i in range(3):
        _add_experiment(store, f"000{i}", claim_key="k-1",
                        created_at=f"2026-01-0{i + 1}T00:00:00+00:00")
    out = VT.list_experiments(store, limit=2)
    assert out["total"] == 3, out
    assert out["returned"] == 2, out
    assert out["truncated"] is True, "被截断了却没标 truncated ⇒ 读者会以为一共只有 2 条"
    assert len(out["experiments"]) == 2, out


def test_list_experiments_zero_limit_returns_nothing_but_still_reports_total(store: Store):
    """负控（边界）：`limit=0` ⇒ 一条都不返回，但 `total` 仍如实给出。

    `max(0, int(limit))` 里的 `max(0, ...)` 是一个真实的防御：
    负数 limit 会被 `rows[:lim]` 解释成"从尾部切"。这条断言把
    "limit=0 是合法的『只要数字不要行』"钉住。
    """
    _add_experiment(store, "0000", claim_key="k-1")
    out = VT.list_experiments(store, limit=0)
    assert out["experiments"] == [], out
    assert out["total"] == 1 and out["returned"] == 0, out
    assert out["truncated"] is True, out


def test_list_experiments_negative_limit_does_not_return_from_the_tail(store: Store):
    """负控（容易踩的坑）：负数 `limit` 不许被 `rows[:lim]` 解释成"取尾部"。

    `rows[:-1]` 在 Python 里是合法的"去掉最后一条"，于是一个
    漏掉 `max(0, ...)` 的实现会安静地返回几乎全部记录，
    而返回值里的 `truncated` 仍然是 `True` —— 看起来完全正常。
    """
    for i in range(3):
        _add_experiment(store, f"000{i}", claim_key="k-1",
                        created_at=f"2026-01-0{i + 1}T00:00:00+00:00")
    out = VT.list_experiments(store, limit=-1)
    assert out["returned"] == 0, f"负 limit 返回了 {out['returned']} 条（`rows[:-1]` 的形态）"
    assert out["experiments"] == [], out
    assert out["total"] == 3, out
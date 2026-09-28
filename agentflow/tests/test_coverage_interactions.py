"""`interactions.py` 里三个零直接测试函数的补强测试（等级 2：判据/决策）。

## 先说清一件事：这三个函数不是"没有测试"

本脚本（`tools/coverage_zero_test.py`）把它们报进清单，是因为它的判据是
"函数名作为标识符出现在 tests/ 里"，而它们此前只出现在测试函数名里
（`test_admit_reprocess_request_...` 这类），从未被限定名点名。
考虑到 `_TEST_NAME_TMPL` 那条判据，这个判断本身是有争议的（见脚本 docstring 的口径说明）。

所以本文件存在的意义不是"消掉三个零测试条目"，而是给它们补上
原文件没有断言的那几条判据（下表）。这一点如实写在这里，不假装是缺口：
`tests/test_interactions.py` 对这三个函数有 13 条测试，覆盖得相当扎实。

| 函数 | 原文件没有断言的东西 | 本文件补的 |
|---|---|---|
| `resolve_priority` | `explicit` 合法值的那条分支；`why` 必须可区分 | 三条分支的 `why` 互不相同 |
| `admit_reprocess_request` | `counts` 是剔除 rejected 行之后的口径；`relation_ids` 去重 | 计数口径 + 去重 |
| `evidence_relevance` | 概念集为空时的行为（`want` 为空 ⇒ 永远不相关） | 空概念集的负控 |

## 夹具纪律（§5.3）

`reason` 的值从 `schema.REPROCESS_REASONS` 取，`priority` 从 `schema.PRIORITIES` 取，
不写死词表取值。
"""

from __future__ import annotations

import inspect
import textwrap

import pytest

from agentflow import interactions as I
from agentflow import schema as S


def _a_reprocess_reason() -> str:
    """一个合法的重抽取理由（从受控词表取，不写死）。"""
    return S.REPROCESS_REASONS[0]


# ============================================================ resolve_priority


def test_resolve_priority_accepts_every_legal_explicit_priority():
    """正向：显式给出的合法优先级必须被原样采纳（且 `why` 说明是显式指定的）。

    为什么这条重要：`tests/test_interactions.py` 只测了"未知/非法"那两条分支
    （`test_resolve_priority_...`），合法显式分支此前没有点名断言 ——
    而它是这个函数最短、也最容易被"回退逻辑"误伤的一条路。
    """
    reasons = set()
    for p in S.PRIORITIES:
        got, why = I.resolve_priority("anyone", explicit=p)
        assert got == p, (p, got, why)
        assert p in why, why
        reasons.add(why)
    assert len(reasons) == len(S.PRIORITIES), "不同优先级的 why 文本相同 ⇒ 日志里分不出是哪一条"


def test_resolve_priority_rejects_an_illegal_explicit_value_by_falling_back():
    """负控：非法 `explicit` ⇒ 回退到提交方默认值，且 `why` 必须说清"你给的值非法"。

    断言打在判据上：不是"没崩"，而是"回退到了哪个值 + 为什么"。
    """
    bad = "这不是一个合法优先级"
    got, why = I.resolve_priority("anyone", explicit=bad)
    assert got == S.SUBMITTER_DEFAULT_PRIORITY.get("anyone", "low"), (got, why)
    assert bad in why and "非法" in why, why


def test_resolve_priority_falls_back_to_low_for_an_unregistered_submitter():
    """负控（不让陌生来源插队）：未登记的提交方 ⇒ 一律 `low`，且 `why` 说明原因。"""
    unknown = "一个从未登记过的提交方"
    assert unknown not in S.SUBMITTER_DEFAULT_PRIORITY, "夹具前提崩了：这个名字竟在词表里"
    got, why = I.resolve_priority(unknown)
    assert got == "low", (got, why)
    assert "落" in why or "low" in why, why


def test_resolve_priority_uses_each_registered_submitters_own_default():
    """正向（判据的唯一来源）：登记过的提交方 ⇒ 用它自己的默认值。

    逐条遍历 `schema.SUBMITTER_DEFAULT_PRIORITY` —— 于是"有人把映射写反了"
    会在这里红，而不是等到某次调度优先级错乱时才被发现。
    """
    for submitter, want in S.SUBMITTER_DEFAULT_PRIORITY.items():
        got, why = I.resolve_priority(submitter)
        assert got == want, (submitter, got, want, why)


# ============================================================ admit_reprocess_request


def test_admit_reprocess_request_accepts_a_first_time_target():
    """正向：目标关系从未被重抽取过 ⇒ 准入，且 `counts` 里给出当前计数。"""
    got = I.admit_reprocess_request([], relation_ids=["0001"], reason=_a_reprocess_reason())
    assert got["admitted"] is True, got
    assert got["blocked"] == [] and got["counts"] == {}, got


def test_admit_reprocess_request_rejects_an_empty_target_set():
    """负控：`relation_ids` 为空 ⇒ 拒绝，且理由说清"会退化成全量重抽"。

    为什么断言理由而不是只断言 `admitted is False`：拒绝的原因是这条闸门
    的全部价值 —— docstring 逐字："无目标的重抽取会退化成全量重抽"。
    """
    got = I.admit_reprocess_request([], relation_ids=[], reason=_a_reprocess_reason())
    assert got["admitted"] is False, got
    assert "全量重抽" in got["reason"], got["reason"]


def test_admit_reprocess_request_rejects_a_reason_outside_the_controlled_vocabulary():
    """负控：`reason` 不在受控词表里 ⇒ 拒绝，且理由列出合法取值。

    为什么必须用受控词表：理由要能被统计。自由文本的拒绝理由无法被统计，
    也无法被 `verify` 检查 —— 所以这一档必须硬拒。
    """
    got = I.admit_reprocess_request([], relation_ids=["0001"], reason="因为我觉得")
    assert got["admitted"] is False, got
    assert "reason 必须是" in got["reason"], got["reason"]
    for r in S.REPROCESS_REASONS:
        assert r in got["reason"], f"合法理由 {r} 没被列出来：{got['reason']}"


def test_admit_reprocess_request_blocks_only_the_targets_at_the_cap():
    """判据（逐目标而不是"整批"）：只有到达上限的那几个目标被 blocked。

    为什么这条要与"整批拒绝"分开：闸门的语义是"同一关系最多 N 次"。
    一个把"任一目标超限就拒绝整批"的实现会把没超限的目标也一起挡掉 ——
    那会让 I4 的吞吐静默下降，而返回值看起来完全正常（`admitted=False` + 有 blocked）。
    """
    reason = _a_reprocess_reason()
    rows = [
        {"reprocess_id": "p-0001", "relation_ids": ["0001"], "status": "done"},
        {"reprocess_id": "p-0002", "relation_ids": ["0001"], "status": "pending"},
    ]
    got = I.admit_reprocess_request(rows, relation_ids=["0001", "0002"], reason=reason,
                                    max_per_relation=2)
    assert got["admitted"] is False, got
    assert got["blocked"] == ["0001"], got
    assert "0002" not in got["blocked"], got
    # 单独申请那个没超限的目标必须通过 —— 这才证明判定是逐目标的。
    ok = I.admit_reprocess_request(rows, relation_ids=["0002"], reason=reason, max_per_relation=2)
    assert ok["admitted"] is True, ok


def test_admit_reprocess_request_counts_ignore_rejected_rows():
    """负控（计数口径）：`status="rejected"` 的行不计入次数。

    为什么这条重要：`reprocess_counts` 的口径是 `pending + done`（docstring 逐字）。
    把 rejected 也算进去会让"被拒绝过的目标"永远无法再申请 ——
    上限被静默减半，而没有任何地方会报错。
    """
    reason = _a_reprocess_reason()
    rows = [
        {"reprocess_id": "p-0001", "relation_ids": ["0001"], "status": "rejected"},
        {"reprocess_id": "p-0002", "relation_ids": ["0001"], "status": "rejected"},
    ]
    got = I.admit_reprocess_request(rows, relation_ids=["0001"], reason=reason, max_per_relation=2)
    assert got["admitted"] is True, got
    assert got["counts"] == {}, f"rejected 行被算进了计数：{got['counts']}"


def test_admit_reprocess_request_dedupes_relation_ids():
    """负控（输入归一）：重复的 `relation_ids` 必须先归一，再判上限。

    不归一的后果：`blocked` 里出现重复项（`["0001","0001"]`），
    于是日志里的"被挡住的目标"条数虚高，人以为有两处超限。
    """
    reason = _a_reprocess_reason()
    got = I.admit_reprocess_request([], relation_ids=["0001", "0001"], reason=reason)
    assert got["admitted"] is True, got
    rows = [{"reprocess_id": "p-0001", "relation_ids": ["0001"], "status": "done"},
            {"reprocess_id": "p-0002", "relation_ids": ["0001"], "status": "done"}]
    blocked = I.admit_reprocess_request(rows, relation_ids=["0001", "0001"], reason=reason,
                                        max_per_relation=2)
    assert blocked["blocked"] == ["0001"], f"blocked 里有重复项：{blocked['blocked']}"


@pytest.mark.xfail(
    reason=(
        "**已知 src 缺陷（TEST-RED-2，见 docs/PROPOSALS.md G-8）**："
        "`interactions.admit_reprocess_request` 的守卫写的是 `if not rids`，"
        "其中 `rids = sorted({str(x) for x in relation_ids if x})` —— "
        "纯空白 `['', '  ']` 经 `if x` 过滤后得到空集合，于是守卫**通过**、"
        "函数返回 `admitted=True`。而 docstring 逐字说 "
        "`relation_ids` 为空时『无目标的重抽取会退化成全量重抽』⇒ 拒绝。"
        "保留这条是为了让缺陷**可见**；修 src 由主控裁决。"
    ),
    strict=True,
)
def test_admit_reprocess_request_rejects_blank_only_relation_ids():
    """会红的测试（已登记为 xfail-strict，缺陷 TEST-RED-2）。

    ## 现象（实测，非推测）

    ```python
    I.admit_reprocess_request([], relation_ids=["", "  "], reason=<合法理由>)
    # 实测 ⇒ {'admitted': True, 'reason': '未超上限 2', 'blocked': [], 'counts': {}}
    ```

    期望 ⇒ `admitted=False` + "全量重抽"。

    ## 为什么这是真缺陷（而不是"输入不该这么写"）

    1. 守卫的语义是"没有任何有效目标就拒绝"。`if x` 这个过滤条件的本意正是
       "丢掉非字符串/空的元素"，于是 `["", "  "]` 与 `[]` 在语义上等价 ——
       两者都是"零个有效目标"。但实现里只有 `[]` 走拒绝分支。
    2. 后果与缺陷描述的一字不差：B 会拿着一个空目标集去重抽取，
       也就是退化成全量重抽，把 A 的产能烧在整张关系表上。
    3. `tests/test_interactions.py::test_admit_reprocess_request_negative_control_empty_target`
       只测了 `relation_ids=[]` 这一种写法，所以这个空档至今没有测试覆盖。

    ## 期望行为（修法方向）

    守卫应当在归一之后判空：`rids = sorted({str(x).strip() for x in relation_ids if str(x).strip()})`，
    再 `if not rids: return {拒绝}`。也就是把 `strip()` 提到过滤条件里，
    让"纯空白"与"空"在归一后同形。

    ## 为什么用 xfail(strict=True)

    与 `test_gate_g1_rejects_a_windows_drive_absolute_proof_location`（TEST-RED-1）同一取舍：
    套件保持绿、缺陷可见、修好后立刻 XPASS 失败提醒来删标记。
    """
    got = I.admit_reprocess_request([], relation_ids=["", "  "], reason=_a_reprocess_reason())
    assert got["admitted"] is False, got
    assert "全量重抽" in got["reason"], got


# ============================================================ `I-9`：纯空白目标（绿侧的钉）


#: `G-8`（`docs/PROPOSALS.md`）的修法方向逐字给出的那一行，以及修好之后的形态。
_G8_OLD_GUARD = "rids = sorted({str(x) for x in relation_ids if x})"
_G8_FIXED_GUARD = "rids = sorted({str(x).strip() for x in relation_ids if str(x).strip()})"


def _assert_blank_only_targets_are_admitted(admit) -> None:
    """判据本体（正控与负控共用同一段断言，负控才有意义）：纯空白目标今天被放行。"""
    got = admit([], relation_ids=["", "  "], reason=_a_reprocess_reason())
    assert got["admitted"] is True, (
        "纯空白目标集合如今被拒绝了？那就是 `G-8` / `TEST-RED-2` 被修好了 —— "
        "请把本文件里那条 `xfail(strict=True)` 删掉、把它改成断言拒绝的正控，"
        f"并更新 `docs/PROPOSALS.md` 的 G-8。实测：{got!r}"
    )


def test_blank_only_targets_are_still_admitted_today():
    """正控（`I-9`）：把当前行为如实钉住 —— 纯空白 `["", "  "]` 今天被放行。

    `G-8` 登记的缺陷是：守卫按过滤前的归一集判空，于是 `["", "  "]`（零个有效目标）
    与 `[]`（空）在语义上同形却走了不同分支 —— 后者拒绝、前者放行，B 于是拿着
    空目标集退化成全量重抽。

    这条刻意不假装缺陷已修：它断言的就是缺陷本身（`admitted is True`）。
    目的是让"这个行为被改动"成为可判定的事件 —— 此前这半条判据是零覆盖：
    `xfail(strict=True)` 只保证"修好时会来删标记"，在改错方向时不会报警。
    修法落在 `interactions.py`（FC-27 禁改区 auth-audit），不归本批次。
    """
    _assert_blank_only_targets_are_admitted(I.admit_reprocess_request)


def test_negative_control_the_pinned_assertion_goes_red_once_the_guard_is_fixed():
    """负控（`I-9`）：按 `G-8` 的修法把守卫改成 strip 之后判空 ⇒ 上面那条必红。

    注入方式是在内存里改源码文本再 exec 出来 —— 不碰 `interactions.py`（它在
    禁改区，本批次不动它）。第一句断言"注入确实改到了源码"：锚点哪天失效，
    这条会红，而不是静默地什么都没注入（空转的负控与没有负控是一回事）。

    与 `docs/PROPOSALS.md` 的 `G-5` 条目同一个处置形态：把实测行为钉在纸上，
    修它的人会看到这条红，从而同时更新登记。
    """
    src = textwrap.dedent(inspect.getsource(I.admit_reprocess_request))
    assert _G8_OLD_GUARD in src, (
        "`G-8` 的守卫写法变了（锚点失效）—— 先核对 `docs/PROPOSALS.md` 的 G-8 与本条锚点"
    )
    fixed = src.replace(_G8_OLD_GUARD, _G8_FIXED_GUARD)
    assert fixed != src, "注入没生效"
    ns = dict(vars(I))
    exec(compile(fixed, "<G-8-fixed>", "exec"), ns)  # noqa: S102 - 受控注入，只为负控
    fixed_admit = ns["admit_reprocess_request"]
    assert fixed_admit([], relation_ids=["", "  "], reason=_a_reprocess_reason())["admitted"] is False, (
        "按 G-8 的修法改出来的实现居然还放行纯空白目标 ⇒ 注入的语义不是修法方向，"
        "这条负控就没在测它该测的东西"
    )
    with pytest.raises(AssertionError):
        _assert_blank_only_targets_are_admitted(fixed_admit)


# ============================================================ evidence_relevance


def test_evidence_relevance_distinguishes_not_checked_from_checked_irrelevant():
    """三态纪律：`new_relations=None`（没查）与 `[]`（查了、没有）必须分开。

    两条路都返回"没有相关证据"，但 `checked` 位不同、`relevance` 也不同
    （`None` vs `"irrelevant"`）、`advice` 不同（`none` vs `lower_priority`）。
    docstring 逐字："`new_relations=None` ⇒ `checked=False`（没查，不是"不相关"）"。
    """
    q = {"related_concept_ids": ["0000"], "evidence_lit_ids": []}
    not_checked = I.evidence_relevance(q, new_relations=None)
    checked_none = I.evidence_relevance(q, new_relations=[])

    assert not_checked["checked"] is False, not_checked
    assert not_checked["relevance"] is None, not_checked
    assert not_checked["advice"] == "none", not_checked
    assert "没查" in not_checked["reason"], not_checked["reason"]

    assert checked_none["checked"] is True, checked_none
    assert checked_none["relevance"] == "irrelevant", checked_none
    assert checked_none["advice"] == "lower_priority", checked_none
    assert checked_none != not_checked


def test_evidence_relevance_accepts_relations_landing_on_the_questions_concepts():
    """正向：新关系落在问题的概念集上 ⇒ `relevant`，并给出关系代号与文献代号。

    断言打在判据上：不止 `relevance == "relevant"`，还要具体是哪些关系被算作相关。
    """
    q = {"related_concept_ids": ["0000", "0001"], "evidence_lit_ids": []}
    got = I.evidence_relevance(q, new_relations=[
        {"relation_id": "0007", "concept_ids": ["0001", "0009"], "lit_id": "0003"},
        {"relation_id": "0008", "concept_ids": ["0009", "0010"], "lit_id": "0004"},
    ])
    assert got["checked"] is True and got["relevance"] == "relevant", got
    assert got["relevant_relation_ids"] == ["0007"], got
    assert got["relevant_lit_ids"] == ["0003"], got
    assert got["advice"] == "proceed", got


def test_evidence_relevance_rejects_an_empty_concept_set_even_with_relations():
    """负控（空概念集的陷阱）：问题没有任何相关概念 ⇒ 任何新关系都不相关。

    为什么必须单独测这一档：`want` 为空时 `want & cids` 恒为空集，
    所以这道判据会一律判 `irrelevant`。这是正确的行为（没有概念集就没有落点），
    但它必须报 `checked=True` + `irrelevant`（"查了、没有落点"），
    不许报 `checked=False`（"没查"）—— 否则调用方会把"这个问题没有概念集"
    误读成"这一轮没检查"，从而永远不去修那个空概念集。
    """
    got = I.evidence_relevance({"related_concept_ids": []}, new_relations=[
        {"relation_id": "0007", "concept_ids": ["0001"], "lit_id": "0003"},
    ])
    assert got["checked"] is True, got
    assert got["relevance"] == "irrelevant", got
    assert got["advice"] == "lower_priority", got
    assert got["relevant_relation_ids"] == [], got


def test_evidence_relevance_accepts_relations_from_an_already_known_evidence_lit():
    """正向（第二条判据入口）：关系不落在概念集上，但它所属文献已被认定
    是这个问题证据来源 ⇒ 也算相关。

    为什么单独一条：docstring 里这是一条独立的兜底判据
    （"该文献已被认定是这个问题的证据来源 ⇒ 它的新关系也算相关"）。
    只测概念集那一半会让这条兜底被写坏而无人知。
    """
    q = {"related_concept_ids": ["0000"], "evidence_lit_ids": ["0003"]}
    got = I.evidence_relevance(q, new_relations=[
        {"relation_id": "0007", "concept_ids": ["0009", "0010"], "lit_id": "0003"},
    ])
    assert got["checked"] is True and got["relevance"] == "relevant", got
    assert got["relevant_relation_ids"] == ["0007"], got
    assert got["relevant_lit_ids"] == ["0003"], got


def test_evidence_relevance_does_not_treat_a_missing_relation_id_as_a_hit():
    """负控（边界）：落在概念集上但没有 `relation_id` 的关系不算相关关系。

    为什么这条重要：`rel_ids` 是"哪几条关系回答了这个问题"的唯一载体。
    一条没有编号的关系无法被追溯，把它算成相关会让报告引用一个不存在的代号 ——
    而 `relevant_lit_ids` 仍会带上它的文献，于是"有相关证据"这句话失去落点。
    """
    q = {"related_concept_ids": ["0000"], "evidence_lit_ids": []}
    got = I.evidence_relevance(q, new_relations=[
        {"concept_ids": ["0000"], "lit_id": "0003"},
    ])
    assert got["relevant_relation_ids"] == [], got
    assert got["relevance"] == "irrelevant", got

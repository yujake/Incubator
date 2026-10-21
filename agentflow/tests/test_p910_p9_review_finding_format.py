"""`P-9` 候选 A（2026-09-27 所有者裁定）的成对正控/负控。
## 这一批落地了什么
1. `schema.ReviewFinding` 补上 G10 六格里的四格：`axis` / `line` /`verbatim_quote` / `maths`（外加 `line_unavailable_reason`），
并把"最小修法"那一格与 `suggestion` 对齐（`gates` 里 `minimal_fix` 作为历史键名继续接受）；2. `schema.ReviewFinding.validate()` 只判"给了值就必须给对"，
刻意不判"必须给值"；3. `gates.gate_g10` 判完整性：四键齐不齐、行号拿不到有没有自证，且只对 `created_at >= schema.REVIEW_FINDING_FORMAT_SINCE` 的行要求四键
——契约生效前的历史行按 `created_at` 豁免，不许回填。
## 为什么"完整性"必须在门上、不在 `validate()` 里（本文件最重要的一条）
`store.rebuild()` 重放事件时逐行调 `obj.validate()`，异常被`except Exception: skipped += 1; continue` 吃掉。于是"在
`validate()` 里写四键必须非空"的直接后果是：契约生效前落盘的历史 finding 行会在下一次重建时整行消失，而且不报错 ——那是数据遗失，不是格式错误。本文件里
`test_p9_rebuild_...` 两条用例把这个机制两个方向都钉住：产出方今天写出的行（无四键）重建后必须还在；而值写错的行必须仍然被拒（证明判据不是被削掉了牙，只是被放对了位置）。
## 第 11 轮补的守卫（A1 / A2 / A3）
`gates.py` 上那三处修复（`FIX11` 修理工 a 落地）此前没有任何测试守着。本文件末尾的"第 11 轮守卫"一节逐条补上，并逐条给出成对读数：
1. A1（零发现 ⇒ `pass`）：`_g10([])` 落 `pass`，而"唯一的行是历史行"落`not_applicable`。这两条路径共用同一个 `if`，只有成对断言（差分）才能把"零发现"与"没有可判定的对象"分开
—— 单断言 `pass` 一条的实现照样过；2. A2（截断串不再豁免）：`REVIEW_FINDING_FORMAT_SINCE` 的四个真前缀截断串（`'2026-09-2'` / `'2026-09-'` /
`'2026-0'` / `'2'`）在纯字典序下比常量小，旧的比较口径会把它们读成"契约生效前的历史行"而豁免掉（比空串还宽松）。负控逐档证明它们现在落在契约作用面内，即 `unknown` 而不是
`not_applicable`；3. A3（`pass` 支的 reason 带豁免档）：有豁免时追加一句、零豁免时整句不出现，而 `counts` 里那个键在任何情况下都必须在（机读面不许被删）。
## 负控的形态（照抄本项目已有的样板）
每条负控都把违规注入到正控夹具的文本副本上，断言：锚点恰好命中 1 次、字节确实变了、把副本打印成 sha256，然后断言下游从绿变红。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agentflow import gates as G
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools.review_tools import _dedup_key

#: 正控夹具（"当前字节"）：一条六格齐全的发现。
#: 它是 `schema.ReviewFinding` 的 JSON 形态，也是所有负控的注入底板。
GOOD_FINDING: dict = {
    "finding_id": "0000",
    "doc_id": "0000",
    "kind": "overclaim",
    "level": "warning",
    "target": "claim-1",
    "evidence": "稿件把交叉验证写成了证明",
    "message": "过度声称：交叉验证不构成证明",
    "round": 1,
    "suggestion": "把『已证明』改成『交叉验证支持』",
    "status": "open",
    "resolution_note": "",
    "created_at": "2026-09-27T12:00:00+08:00",
    "created_by": "agent-H",
    "axis": "体例",
    "line": 12,
    "verbatim_quote": "已证明",
    "maths": "yes",
    "line_unavailable_reason": "",
}

#: 契约生效之前落盘的历史行（缺四键，且 `created_at` 早于生效日）。
LEGACY_FINDING: dict = {
    "finding_id": "0001", "doc_id": "0000", "kind": "overclaim", "level": "error",
    "target": "claim-2", "evidence": "e", "message": "m", "round": 1, "suggestion": "",
    "status": "open", "resolution_note": "", "created_at": "2026-09-26T23:00:00+08:00",
    "created_by": "agent-H",
}


def _fixture_text() -> str:
    return json.dumps(GOOD_FINDING, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _inject(tmp_path: Path, anchor: str, replacement: str, tag: str) -> tuple[dict, str, str]:
    """把一处违规注入正控夹具的文本副本 ⇒ `(副本的行, 正控 sha256, 副本 sha256)`。

    三条断言缺一不可（第一条是"注入真的发生了"，第二条是"注入的位置唯一"，
    第三条是"字节确实变了"）—— 只断言下游变红的话，一条"夹具本来就红"的
    负控会静默通过。
    """
    original = _fixture_text()
    hits = original.count(anchor)
    assert hits == 1, f"注入锚点必须恰好命中 1 次，实际 {hits} 次：{anchor!r}"
    mutated = original.replace(anchor, replacement)
    assert mutated != original, "注入没有改变字节 ⇒ 这条负控什么都没测"
    copy = tmp_path / f"copy-{tag}.json"
    copy.write_text(mutated, encoding="utf-8")
    src_sha, dst_sha = _sha(original), _sha(mutated)
    print(f"[负控 {tag}] 注入 {anchor!r} -> {replacement!r}；锚点命中 {hits} 次")
    print(f"[负控 {tag}] 正控副本 sha256={src_sha}")
    print(f"[负控 {tag}] 注入副本 {copy.name} sha256={dst_sha}")
    return json.loads(mutated), src_sha, dst_sha


def _g10(findings: list[dict]) -> G.GateResult:
    """只喂 `findings` 的 G10 上下文（这道门不读其它输入）。"""
    return G.gate_g10(G.GateContext.build(None, findings=list(findings)))


def _validate(row: dict) -> None:
    S.ReviewFinding(**row).validate()


def _expect_validate_rejects(row: dict, tag: str) -> str:
    """跑写入期判据，打印它最原始的拒收文本，返回该文本。"""
    try:
        _validate(row)
    except ValueError as exc:
        print(f"[负控 {tag}] 写入期原始输出：ValueError: {exc}")
        return str(exc)
    raise AssertionError(f"负控 {tag} 没有被写入期判据拒绝 —— 注入没生效")


def _gate_raw(r: G.GateResult, tag: str) -> None:
    """把 G10 的原始结论打出来（verdict / reason / 逐条发现）。"""
    print(f"[负控 {tag}] G10 原始输出：verdict={r.verdict} counts={r.counts}")
    print(f"[负控 {tag}] G10 reason={r.reason}")
    for f in r.findings:
        print(f"[负控 {tag}] G10 finding: severity={f['severity']} message={f['message']} "
              f"evidence={f['evidence']}")


# ============================================================ 正控


def test_p9_positive_control_current_fixture_passes_both_layers(tmp_path: Path):
    """正控：当前字节上，写入期判据与 G10 都必须通过，且门真的判了对象。

    "真的判了对象"由 `counts['契约作用面内'] == 1` 断言 —— 一个把一切都
    豁免掉的实现会让 G10 无条件 pass（`P16` 的真空通过形态）。
    """
    text = _fixture_text()
    copy = tmp_path / "copy-positive.json"
    copy.write_text(text, encoding="utf-8")
    print(f"[正控] 当前字节副本 {copy.name} sha256={_sha(text)}")
    row = json.loads(text)
    _validate(row)
    r = _g10([row])
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["契约作用面内"] == 1, r.counts
    assert r.counts["豁免(契约生效前的历史行)"] == 0, r.counts
    assert r.self_attestation.strip(), "零发现必须带自证数字（G13）"


def test_p9_positive_control_suggestion_is_the_aligned_key_name():
    """正控（键名对齐）：只给 `suggestion`（不给历史键名 `minimal_fix`）⇒ 六格齐 ⇒ pass。"""
    row = dict(GOOD_FINDING)
    assert "minimal_fix" not in row
    r = _g10([row])
    assert r.verdict == "pass", (r.verdict, r.reason, r.findings)


def test_p9_positive_control_line_none_with_a_reason_is_the_third_state():
    """正控（三态）：未冻结时 `line=None` 但自证了 `line_unavailable_reason` ⇒ 不打回。

    "行号拿不到"必须是一个可判定的结论，而不是空白 —— 这条与
    `test_p9_negative_control_line_none_without_a_reason_is_rejected` 成对。
    """
    row = dict(GOOD_FINDING, line=None, line_unavailable_reason="稿件未冻结（G11 未通过）：行号无意义")
    print(f"[正控 三态] line=None + 理由 ⇒ 期望 verdict=pass")
    r = _g10([row])
    assert r.verdict == "pass", (r.verdict, r.reason, r.findings)


def test_p9_positive_control_new_fields_do_not_enter_the_dedup_key():
    """正控（去重键不变）：只有新四键不同的两条发现，去重键必须相同。

    这不是形式主义：`verify_fixes` 的重开逻辑与第二轮去重都靠
    `(kind, target, message)`；把行号或引文放进键里，每次改稿都会产生一批新发现。
    """
    a = dict(GOOD_FINDING)
    b = dict(GOOD_FINDING, line=999, verbatim_quote="另一句话", axis="数学", maths="no")
    assert _dedup_key(a) == _dedup_key(b), (_dedup_key(a), _dedup_key(b))
    # `FINAL-R2b-04`：上面那一句是单向的（只证"新四键不影响键"）——
    # 把 `_dedup_key` 退化成常量它也会绿（实测：退化后本文件 34 passed）。
    # 所以这里补上另一半：三个老字段各自不同 ⇒ 键必须不同。
    for field, other in (("kind", "garbled"), ("target", "T-2"), ("message", "另一句话")):
        c = dict(GOOD_FINDING, **{field: other})
        assert _dedup_key(a) != _dedup_key(c), (
            f"`_dedup_key` 丢了 {field} —— 去重键退化成常量时这一条必须红："
            f"{_dedup_key(a)} vs {_dedup_key(c)}"
        )


# ============================================================ 负控：写入期判据


def test_p9_negative_control_axis_outside_the_vocabulary(tmp_path: Path):
    """负控 1：`axis` 给了词表外的值 ⇒ 写入期拒 + G10 判红（两层都要响）。"""
    row, _src, _dst = _inject(tmp_path, '"axis": "体例"', '"axis": "玄学"', "axis")
    _expect_validate_rejects(row, "axis")
    r = _g10([row])
    _gate_raw(r, "axis")
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert any("轴不在参考体例的轴词表里" in f["message"] for f in r.findings), r.findings


def test_p9_negative_control_maths_maybe(tmp_path: Path):
    """负控 2：`maths="maybe"` ⇒ 写入期拒 + G10 判红。"""
    row, _src, _dst = _inject(tmp_path, '"maths": "yes"', '"maths": "maybe"', "maths")
    _expect_validate_rejects(row, "maths")
    r = _g10([row])
    _gate_raw(r, "maths")
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert any("maths 取值不是 yes/no" in f["message"] for f in r.findings), r.findings


def test_p9_negative_control_line_zero_is_not_a_line_number(tmp_path: Path):
    """负控 3：`line=0` ⇒ 写入期拒（行号 1 起）+ G10 判红（不许把 0 读成"缺行号"）。"""
    row, _src, _dst = _inject(tmp_path, '"line": 12', '"line": 0', "line0")
    _expect_validate_rejects(row, "line0")
    r = _g10([row])
    _gate_raw(r, "line0")
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert any("行号必须是 1 起的整数" in f["message"] for f in r.findings), r.findings


def test_p9_negative_control_quote_over_twenty_words(tmp_path: Path):
    """负控 4：`verbatim_quote` 换成 25 个词 ⇒ 写入期拒 + G10 报"超过 20 词"。

    25 个英文词按 `gates._quote_word_count` 的口径数出来是 25（英文按空白切词）。
    """
    long_quote = " ".join(f"w{i}" for i in range(25))
    row, _src, _dst = _inject(
        tmp_path, '"verbatim_quote": "已证明"', f'"verbatim_quote": "{long_quote}"', "quote"
    )
    _expect_validate_rejects(row, "quote")
    r = _g10([row])
    _gate_raw(r, "quote")
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert any("超过 20 词" in f["message"] for f in r.findings), r.findings


def test_p9_negative_control_line_none_without_a_reason_is_rejected(tmp_path: Path):
    """负控 5：`line=None` 而 `line_unavailable_reason` 为空 ⇒ G10 打回。

    这一条刻意不放在 `schema.ReviewFinding.validate()` 里：今天的产出方
    （`review_tools.scan_document`）写出来的行正是"没有行号"的形态，把这条
    放进 `validate()` 会让它们在下一次 `store.rebuild()` 时被静默丢掉。
    """
    row, _src, _dst = _inject(tmp_path, '"line": 12', '"line": null', "line-none")
    assert row["line_unavailable_reason"] == "", "夹具前提：理由确实是空的"
    _validate(row)  # 写入期判据刻意不拦（见 docstring）
    r = _g10([row])
    _gate_raw(r, "line-none")
    assert r.verdict == "fail", (r.verdict, r.reason, r.findings)
    assert any("行号(line)" in f["evidence"] for f in r.findings), r.findings


# ============================================================ 负控：结构缺口与豁免


def test_p9_negative_control_missing_the_four_keys_is_unknown_not_pass():
    """负控 6：`created_at` 为空且缺四键的行 ⇒ `unknown`（不是 pass）。

    `created_at` 为空不豁免：拿不到创建时刻就不能主张豁免，否则
    "把 created_at 删掉"就是绕过这道门的万能钥匙。
    """
    row = {k: v for k, v in GOOD_FINDING.items()
           if k not in ("axis", "line", "verbatim_quote", "maths", "created_at")}
    r = _g10([row])
    _gate_raw(r, "gap")
    assert r.verdict == "unknown", (r.verdict, r.reason)
    assert r.counts["契约作用面内"] == 1, r.counts
    assert "不可判定" in r.reason, r.reason


def test_p9_positive_control_legacy_rows_are_exempt_not_counted_as_a_gap():
    """正控（豁免）：`created_at` 早于生效日的行不参与"四键齐不齐"这条判据。

    只有一行历史行时这道门没有可判定的对象 ⇒ `not_applicable`（不是 pass：
    "我没有判"与"我判过没问题"必须分开）。
    """
    r = _g10([LEGACY_FINDING])
    assert r.verdict == "not_applicable", (r.verdict, r.reason)
    assert r.counts["豁免(契约生效前的历史行)"] == 1, r.counts
    assert r.counts["契约作用面内"] == 0, r.counts
    print(f"[正控 豁免] verdict={r.verdict} counts={r.counts}")
    print(f"[正控 豁免] reason={r.reason}")


def test_p9_negative_control_the_exemption_does_not_cover_new_rows():
    """负控 7（豁免的反真空）：同一批里既有历史行又有缺键的新行 ⇒ 新行必须计入缺口。

    只断言"历史行豁免"是不够的：一个把所有行都豁免掉的实现会让这条判据
    永远没有对象。所以这里把两种行放进同一次调用，断言缺口恰好是 1。
    """
    new_row = {k: v for k, v in GOOD_FINDING.items()
               if k not in ("axis", "line", "verbatim_quote", "maths")}
    assert new_row["created_at"] >= S.REVIEW_FINDING_FORMAT_SINCE, "夹具前提：这是一条生效日之后的行"
    r = _g10([LEGACY_FINDING, new_row])
    _gate_raw(r, "exemption")
    assert r.verdict == "unknown", (r.verdict, r.reason)
    assert r.counts["豁免(契约生效前的历史行)"] == 1, r.counts
    assert r.counts["契约作用面内"] == 1, r.counts
    assert "1 / 1" in r.reason, r.reason


# ============================================================ 第 11 轮守卫（A1 / A2 / A3）

#: 正控夹具里那一条 `created_at` 的原文（注入锚点，恰好命中 1 次）。
_CREATED_AT_ANCHOR = '"created_at": "2026-09-27T12:00:00+08:00"'

#: 契约要求而历史行没有的四键（摘掉它 = "契约生效后该给而没给"的形态）。
_THE_FOUR_GATE_KEYS = ("axis", "line", "verbatim_quote", "maths")

#: A2 的四个真前缀截断串，以及注入用的短标签（每个都要有自己的副本 sha256）。
#: 它们全是 `S.REVIEW_FINDING_FORMAT_SINCE` 的真前缀 ⇒ 纯字典序比较会把它们
#: 读成"比常量小"，于是旧的比较口径把它们判成历史行而豁免（`R2b-AN-2`）。
_TRUNCATED_CREATED_AT = (
    ("2026-09-2", "trunc-2026092"),
    ("2026-09-", "trunc-202609"),
    ("2026-0", "trunc-20260"),
    ("2", "trunc-2"),
)


def _without_the_four_keys(row: dict) -> dict:
    """把四键摘掉的行（与负控 7 的 `new_row` 同形）。"""
    return {k: v for k, v in row.items() if k not in _THE_FOUR_GATE_KEYS}


def _injected_created_at(tmp_path: Path, created_at: str, tag: str) -> dict:
    """在正控夹具的文本副本上把那一行 `created_at` 换成 `created_at`，返回解析后的行。

    走的还是本文件 `_inject` 的三件套（锚点命中 1 次、字节确实变了、打印副本 sha256），
    所以 `row["created_at"]` 上那句断言是"注入真的落到那一格上"的收据，不是重复劳动：
    注入若落在别的格上，注入那一步仍然是绿的。
    """
    row, _src, _dst = _inject(tmp_path, _CREATED_AT_ANCHOR, f'"created_at": "{created_at}"', tag)
    assert row["created_at"] == created_at, (
        f"注入没有落到 created_at 那一格：{row['created_at']!r} != {created_at!r}")
    return row


def test_p9_positive_control_zero_findings_is_pass_not_not_applicable():
    """正控（A1，第 11 轮）：零发现落 `pass`，而"唯一的行是历史行"落 `not_applicable`。

    这两条判断共用同一个 `if`，所以断言必须成对：只断言"零发现 ⇒ pass"的实现
    完全可能同时把"全是历史行"也判成 pass（那就把"我没有判"读成了"我判过没问题"）。
    反过来，只断言"历史行 ⇒ not_applicable"的实现，也可能把零发现一起带进
    这一档（那就是修前的形状：一篇没有任何发现的稿件被判成 `accepted_with_gaps`）。

    零发现那一支的自证（`self_attestation`）必须非空：`GateResult.__post_init__`
    的结构约束（G13）就要求"零发现 + pass ⇒ 有过程、有数字"，这里把它读出来。
    """
    zero = _g10([])
    print(f"[正控 零发现] verdict={zero.verdict} counts={dict(zero.counts)}")
    print(f"[正控 零发现] reason={zero.reason}")
    print(f"[正控 零发现] self_attestation={zero.self_attestation}")
    assert zero.verdict == "pass", (zero.verdict, zero.reason)
    # 键名逐字断言（不是"有四个键"）：这四个键是机读面，改名等于改报告契约。
    assert dict(zero.counts) == {
        "发现数": 0,
        "契约作用面内": 0,
        "豁免(契约生效前的历史行)": 0,
        "不合格式": 0,
    }, dict(zero.counts)
    assert zero.self_attestation.strip(), "零发现必须带自证（G13）"
    assert zero.findings == (), zero.findings

    legacy = _g10([LEGACY_FINDING])
    print(f"[负控 零发现 vs 无对象] verdict={legacy.verdict} counts={dict(legacy.counts)}")
    assert legacy.verdict == "not_applicable", (legacy.verdict, legacy.reason)
    assert legacy.counts["发现数"] == 1, legacy.counts
    assert legacy.counts["豁免(契约生效前的历史行)"] == 1, legacy.counts
    assert legacy.counts["契约作用面内"] == 0, legacy.counts
    assert zero.verdict != legacy.verdict, (
        "差分没做出来：零发现与『唯一的行是历史行』被判成了同一档 ⇒ 这条守卫没在区分任何东西")


@pytest.mark.parametrize("created_at,tag", _TRUNCATED_CREATED_AT)
def test_p9_negative_control_a_truncated_created_at_is_in_scope(
    tmp_path: Path, created_at: str, tag: str
):
    """负控（A2，第 11 轮）：生效日常量的四个真前缀截断串都不许被豁免。

    这四档是"旧口径与修复后口径结论相反"的全部位置：`created_at` 是常量的一个真前缀 ⇒ 纯字典序比较说它小于常量（⇒ 历史行 ⇒ 豁免），而契约的判据是"拿不到合法创建时刻就不能主张豁免"。

    所以这条负控有两个层次，缺一不可：

    1. 判据层：`_finding_format_in_scope` 对这四档必须为真（进作用面）；
    2. 门层：把这条 `created_at` 注入正控夹具的文本副本、再把四键摘掉
    （契约生效后该给而没给）⇒ `unknown` 且 `契约作用面内 == 1`。若它被判成历史行，读数是 `not_applicable` 且 `豁免 == 1` —— 两者在`verdict` 与那两个计数上都相反，
    所以这条负控不可能"因为别的原因"变绿。
    """
    assert G._finding_format_in_scope({"created_at": created_at}) is True, (
        f"{created_at!r} 被豁免了：契约生效日之后的产出行不许拿 created_at 的截断串冒充历史行")
    # 这一档的挑选不是随手写的：它必须在纯字典序下比常量小，否则这四档
    # 与修复前的口径无法区分（那这条负控就只是在重复正控）。
    assert not (created_at >= S.REVIEW_FINDING_FORMAT_SINCE), (
        f"{created_at!r} 在纯字典序下不小于常量 ⇒ 这一档区分不出新旧口径，"
        "负控失去对象（`R2b-AN-2` 的原形状正是这个比较）")

    row = _without_the_four_keys(_injected_created_at(tmp_path, created_at, tag))
    assert "axis" not in row and "created_at" in row, sorted(row)
    r = _g10([row])
    _gate_raw(r, tag)
    assert r.verdict == "unknown", (created_at, r.verdict, r.reason)
    assert r.counts["契约作用面内"] == 1, (created_at, r.counts)
    assert r.counts["豁免(契约生效前的历史行)"] == 0, (created_at, r.counts)


@pytest.mark.parametrize(
    "created_at,expected_verdict,expected_in_scope,expected_exempt,tag",
    [
        # 标签显式给出（不由 `created_at` 派生）：它要当文件名用，
        # 而 `2026-09-28T00:00:00+08:00` 里的冒号在 Windows 上是非法字符。
        ("2026-09-26", "not_applicable", 0, 1, "boundary-20260926"),
        ("2026-09-27", "unknown", 1, 0, "boundary-20260927"),
        ("2026-09-28T00:00:00+08:00", "unknown", 1, 0, "boundary-20260928"),
    ],
)
def test_p9_positive_control_the_exemption_boundary_is_the_contract_date(
    tmp_path: Path, created_at: str, expected_verdict: str,
    expected_in_scope: int, expected_exempt: int, tag: str,
):
    """正控（A2 的同表边界）：豁免与进判定的分界恰好落在生效日那一天。

    上一条负控证明"截断串不再豁免"，这一条证明"豁免这件事本身还活着"：
    生效日之前一天仍然豁免（`not_applicable`），生效日当天与之后一天进判定。
    只测负控那一半会留下一个把一切都判进作用面的实现照样通过的空档 ——
    那样"历史行按 created_at 豁免、不许回填"这条设计就被静默地取消了。
    """
    row = _without_the_four_keys(_injected_created_at(tmp_path, created_at, tag))
    r = _g10([row])
    _gate_raw(r, tag)
    assert r.verdict == expected_verdict, (created_at, r.verdict, r.reason)
    assert r.counts["契约作用面内"] == expected_in_scope, (created_at, r.counts)
    assert r.counts["豁免(契约生效前的历史行)"] == expected_exempt, (created_at, r.counts)


def test_p9_positive_control_the_pass_reason_carries_the_exemption_tier():
    """正控（A3，第 11 轮）：有豁免时，`pass` 支的 reason 必须写出那一档与它的数。

    为什么这不是形式主义：`pass` 只说"作用面内的行都合规"，而"另有 M 条历史行
    没参与判定"是判定作用面的边界。不写出来，读者会把"pass"读成"这一批发现
    全部合规"，而实际上一部分行（历史行）根本没进判据。
    """
    both = _g10([LEGACY_FINDING, GOOD_FINDING])
    print(f"[正控 豁免档] verdict={both.verdict} counts={dict(both.counts)}")
    print(f"[正控 豁免档] reason={both.reason}")
    assert both.verdict == "pass", (both.verdict, both.reason)
    assert "作用面内 1 条" in both.reason, both.reason
    assert "另有 1 条历史行" in both.reason, both.reason
    assert both.counts["豁免(契约生效前的历史行)"] == 1, both.counts


def test_p9_negative_control_the_exemption_tier_is_absent_when_nothing_was_exempt():
    """负控（A3 的反向）：零豁免时 `pass` 支的 reason 不许出现豁免那一档。

    与上一条成对，且这一对是差分：同一个 `pass` 支，唯一差别是有没有历史行。
    只断言"有豁免时要写"的实现，完全可能是"无条件都写"（于是零豁免时会打印
    "另有 0 条历史行"）—— 那句话恰恰会让读者以为有一档被判据跳过了。

    最后一条断言是"机读面不许被删"：那道豁免档在 reason 里按需出现，
    但 `counts` 里那个键必须永远在（报告与下游按它取值，删键是静默的接口变更）。
    """
    only = _g10([GOOD_FINDING])
    both = _g10([LEGACY_FINDING, GOOD_FINDING])
    print(f"[负控 零豁免] verdict={only.verdict} counts={dict(only.counts)}")
    print(f"[负控 零豁免] reason={only.reason}")
    print(f"[负控 零豁免] self_attestation={only.self_attestation}")
    assert only.verdict == "pass", (only.verdict, only.reason)
    assert only.reason != both.reason, "差分没做出来：两边的 reason 逐字相同"
    assert "豁免" not in only.reason, only.reason
    assert "另有" not in only.reason, only.reason
    assert "另有" not in only.self_attestation, only.self_attestation
    assert only.counts["豁免(契约生效前的历史行)"] == 0, only.counts
    assert "豁免(契约生效前的历史行)" in dict(only.counts), dict(only.counts)


# ============================================================ rebuild 的无损性


def _store_row(finding_id: str, **over: object) -> dict:
    row = {
        "finding_id": finding_id, "doc_id": "0000", "kind": "overclaim", "level": "error",
        "target": "claim-1", "evidence": "e", "message": "m", "round": 1, "suggestion": "",
        "status": "open", "resolution_note": "",
        "created_at": "2026-09-27T12:00:00+08:00", "created_by": "agent-H",
    }
    row.update(over)
    return row


def test_p9_rebuild_keeps_rows_written_by_todays_producer(store: Store):
    """正控（rebuild 无损）：今天的产出方写出的行（无四键）重建后必须还在。

    这是"不把非空断言放进 `validate()`"这条纪律的可执行形式：一旦有人加上它，
    这一行会在 `rebuild()` 里被静默 skip（`skipped` 会变成 1），本用例立刻红。
    """
    with store.tx("review_findings", actor="test") as tx:
        tx.upsert("review_findings", _store_row("0000"), note="今天的产出方写出的行")
    out = store.rebuild(backup=False)
    assert out["skipped"] == 0, out
    rows = store.rows("review_findings")
    assert [r["finding_id"] for r in rows] == ["0000"], rows
    assert rows[0]["axis"] == "" and rows[0]["line"] is None, rows


def test_p9_rebuild_still_bites_a_row_with_a_wrong_value(store: Store):
    """负控（写入期仍然有牙）：值写错的行走不到盘上 —— 提交时就被拒。

    与上一条成对：判据没有被削掉，只是从"必须给值"挪到了"给了值就必须给对"。
    这条同时证明"不把非空断言放进 `validate()`"没有把 `validate()` 变成空函数：
    它仍在提交路径上被调用，只是只对给出来的值有意见。
    """
    with pytest.raises(ValueError, match="axis 必须是"):
        with store.tx("review_findings", actor="test") as tx:
            tx.upsert("review_findings", _store_row("0001", axis="玄学"), note="值写错的行")
    assert store.rows("review_findings") == [], store.rows("review_findings")


def test_p9_rebuild_silently_drops_a_persisted_row_that_validate_rejects(store: Store):
    """负控（机制证据）：`rebuild()` 会静默丢掉任何 `validate()` 抛异常的行。

    这就是"四键必须非空"这条断言不能进 `validate()` 的全部理由。做法是手工往事件
    日志里追加一条契约之前形态的事件（没有 `batch`、没有版本号，`rebuild` 按
    "历史事件一律算完整批次"的口径重放它），行里带一个既有判据就会拒的取值
    （`level` 不在 `FINDING_LEVELS` 里）。

    读数只有两个：`skipped == 1`、那一行不在重建结果里 —— 没有异常、没有别的提示。
    换成本批新增的那四格，同一件事就会发生在全部历史 finding 行上。
    """
    legacy_row = _store_row("0002", level="bogus")
    with open(store.events_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"op": "upsert", "table": "review_findings", "row": legacy_row},
                           ensure_ascii=False) + "\n")
    out = store.rebuild(backup=False)
    print(f"[负控 rebuild 静默丢行] skipped={out['skipped']} applied={out['applied']}")
    assert out["skipped"] == 1, out
    assert store.rows("review_findings") == [], store.rows("review_findings")

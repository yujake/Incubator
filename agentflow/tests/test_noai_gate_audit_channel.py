"""`noai_gate` 的第二条通路：多子代理 × 多维度审计全清白 ⇒ 通过。

口径由所有者于 2026-09-26 批准（原文："允许将人工签名换成另一种通过方式：
在多个子代理对代码的多个维度进行审计时都未发现任何或大或小的问题"）。

## 这个文件要守住的不是"功能能用"，而是这条路不能变松

补一条通路最容易出的错有三种，每一种都配了会红的负控：

1. 真空的"未发现问题"：没有负控的审计只说明"这个方法看不见问题"。
   ⇒ `negative_control` 为空一律拒绝写入；台账里若有（手工塞的）也不计数。
2. 审错版本：审计记录的 `sha256` 与台账条目不一致时不计数
   —— 否则"改了之后再补一次旧版审计"就能批准一版没人看过的内容。
3. 把 finding 藏起来：审计报了问题却仍放行。⇒ 有 finding 必须判 unapproved 并列出原文。

另有一条独立性的检查：`auditor` 与该条 `authored` 同名时要在输出里警告
（"自己审自己不算独立复核"）。这条判据是警告而不是拒绝，因为 `authored` 通常只是
`ai-agent` 这种粗粒度标签，机械拒绝会造成假安全；真正的独立性由证据文件承担。

## 夹具的一次大修（2026-09-27，`batchR6ac`）

本文件此前有 13 条红，根因不在判据，而在夹具是照旧版判据写的
（对着改前那一版 `scripts/noai_gate.py` 跑同样是 13 failed / 9 passed
—— 证据：`temp/batchR6ac-pristine-baseline.txt`）。批 O 之后写入侧多了五个硬要求，
夹具一个都没满足，于是读侧的"能通过"用例连审计记录都构造不出来：

| 判据 | 位置 | 夹具原来缺什么 |
|---|---|---|
| `scope` 必须说清覆盖了哪些符号（`H-1d`） | `record_audit` / `clean_audits` | 根本没给 `scope` |
| `scope` 的符号必须是被审对象里真实存在的标识符（`R5-R1b-5`） | `_evidence_cross_check` ③ | — |
| 同上，且必须出现在证据正文里（`R1-AN-4` ③） | `_evidence_cross_check` ③ | — |
| `audit_started_sha256` 必须写清开审那一版（`c-20`） | `record_audit` / `clean_audits` | 没给 |
| 署名者未知时要有 `independence` 声明（`H-1e`） | `record_audit` / `clean_audits` | 没给 |
| 负控要有长度 + "怎么比" + "比出来什么"（`R5-R1b-6`） | `negative_control_problem` | 只有 13 字符的 `'改前会报出 network'` |

修的是夹具，不是判据：`scope` 一律指向 `src/agentflow/tools/base.py` 里真实定义的名字
（`SIDE_EFFECTS` / `EFFECT` / `EXTERNAL` / `ToolError` / `ToolResult` / `validate_params`），
负控与独立性声明都写清"拿什么比、比出了什么"，证据是真落盘的文件（每条审计一份，
因为 `counted_audits` 按 `(evidence_path, evidence_sha256)` 去重）。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pathlib
import sys

import pytest

GATE = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "noai_gate.py"


def _load():
    spec = importlib.util.spec_from_file_location("_gate_for_audit_tests", GATE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


G = _load()
SHA = "a" * 64

#: 被审对象（读侧夹具用的落点）。它是禁改区里的一条，且本文件从不写它。
TARGET = "src/agentflow/tools/base.py"

#: 每条审计一个不同的观察面：`scope` 里的符号必须是被审对象里真实存在的标识符
#: （`R5-R1b-5`），且两两不同（`R5-R1b-1` 判据 1：同一名审计者的多条记录不许共用同一个面）。
#: 这六个名字都在 `src/agentflow/tools/base.py` 里真的定义着 —— 不是"为了过门"凑的短词，
#: 用 `G._identifiers_of()` 可以逐个复核（见 `test_scope_tokens_are_real_symbols_of_the_target`）。
SCOPES = ("SIDE_EFFECTS", "EFFECT", "EXTERNAL", "ToolError", "ToolResult", "validate_params")

#: 受控词表里的 6 个维度，与 `SCOPES` 一一对应（顺序固定，便于逐条定位）。
DIMENSIONS = ("axes", "roles", "errors", "contract", "docs", "tests")

#: 合规负控（`R5-R1b-6` 四条：长度 ≥40、有"怎么比"的标记、有"比出来什么"的标记、不是重复填充）。
#: 它回答的是那个判据真正想问的问题：拿什么去比、比出来看到了什么。
NEGATIVE_CONTROL = (
    "负控：拿改前那一版（git show HEAD:src/agentflow/tools/base.py）跑同一条判据，"
    "并注入一个已知坏样本；门报红并给出退出码 1，说明这条判据真的能发现问题。"
)

#: 合规独立性声明（`H-1e`：说清"我相对于谁独立"）。
def _independence(auditor: str) -> str:
    return f"我是子代理 {auditor}，与该条目的署名者不是同一主体，未参与这次改动的编写。"


#: 夹具默认的 `at`。它必须是合规 ISO-8601 且不在未来（`R5-R1b-7`）：
#: 带显式时区偏移，且早于本文件写成时的判定时刻。
#:
#:  它与 `authority` 的关系是易碎的一处：判据只判"能不能解析 + 是不是未来"，
#: 刻意不设"多久算太旧"（见 `audit_timestamp_problem` 的 docstring）。
#: 所以这个字面量本身可以长期用；但若哪天门加了时间窗判据，它就会一夜变红 ——
#: 那时改的是判据，不是这条夹具（改夹具之前先确认判据变严是有意的）。
_AT = "2026-09-26T00:00:00+08:00"


#: 夹具的证据根目录。放在 `temp/`（仓库上一级），与项目里"证据落在 temp/"的口径一致。
#:
#: 为什么每条审计一个文件而不是共用一个：`LedgerEntry.counted_audits` 按
#: `(evidence_path, evidence_sha256)` 去重（`c-17`）—— 六条审计共用一个证据文件时，
#: 它们会被折叠成一条，于是"2 名审计者 × 6 个维度"实际只有 1 条计入，
#: 门槛永远不满足。旧夹具正是因为这一点连读侧正控都建不起来。
#:
#: 文件名带 PID：并行跑测试时两次导入会写同一个路径，而它被 `sha256_file` 读过之后
#: 又被另一进程重写 ⇒ hash 核对随机失败（"测试之间互相改对方的证据"）。
EVIDENCE_DIR = pathlib.Path(r"D:\Incubator\temp") / f"_audit_channel_evidence_{os.getpid()}"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

#: 给证据文件编号：每次 `_make_evidence()` 都要一个新文件（见上面的去重口径）。
_EV_SEQ = [0]


def _evidence_text(auditor: str, scope: str, sha256: str) -> str:
    """证据正文。

    这四项不是装饰，是 `_evidence_cross_check` 逐条要核的东西（`H-1b`）：

    1. 审计者标识必须以独立词形态出现（`R1-AN-4` ①，词边界匹配）—— 证据与主体对得上；
    2. 所审版本的 sha 前缀 12 位必须出现（`R1-AN-4` ②）—— 证据与版本对得上；
    3. `scope` 里的符号必须出现（`R1-AN-4` ③）—— 证据覆盖了它自称覆盖的东西；
    4. 正文里必须能看见"负控"（`R1-AN-4` 负控侧）—— "每条都带负控"要留痕。

    写这四项的那一刻，夹具就从"构造一个对象"变成了"产出一份真的能被交叉核对的证据"。
    """
    return (
        f"审计者：{auditor}\n"
        f"审计范围（scope）：{scope}\n"
        f"被审版本：{sha256}\n"
        f"负控（negative control）：{NEGATIVE_CONTROL}\n"
    )


def _make_evidence(auditor: str, scope: str, sha256: str = SHA) -> tuple[str, str]:
    """落一份只属于这一条审计的证据文件；返回 `(绝对路径, sha256)`。

    给绝对路径是刻意的：证据文件在 `temp/`（仓库上一级），而 `evaluate_approval`
    默认的 `repo` 是 `project_root()`（= `agentflow/`）。相对路径两种给法（相对仓库根 /
    相对 cwd）写入侧都接受，核对侧也必须都接受，绝对路径是唯一无歧义的那种。
    """
    _EV_SEQ[0] += 1
    p = EVIDENCE_DIR / f"ev-{_EV_SEQ[0]:03d}-{auditor}-{scope}.txt"
    p.write_text(_evidence_text(auditor, scope, sha256), encoding="utf-8")
    return str(p), G.sha256_file(p)


#: 回执链夹具：一条真实的、可校验的链。
#:
#: 为什么正控也要它：加了回执链之后，机审通路要在两个外层锚上都通过才算批准
#: （证据文件 + 只增回执链）。所以"批准"这件事的夹具必须把两层都建起来 ——
#: 只建证据文件的夹具会让正控掉进 `unknown`，而那看起来像"实现坏了"，
#: 其实是"夹具没满足判据的前提"（本项目记过的形态：判据的前提没建立，结论就没有意义）。
#: 链用 `append_receipt()` 真的写一遍，不手搓 —— 手搓的链一旦与判据的规范化方式不一致，
#: 测的就是"我搓的对不对"而不是"门判得对不对"。
RECEIPT_LOG = EVIDENCE_DIR / "receipts.jsonl"
if RECEIPT_LOG.exists():
    RECEIPT_LOG.unlink()
G.append_receipt(action="record_audit", path=TARGET, entry_sha256=SHA,
                 detail="夹具：axes", log_path=RECEIPT_LOG)
RECEIPT_TAIL = G.check_receipt_chain(RECEIPT_LOG)["tail"]


def _entry(**kw):
    base = dict(path=TARGET, glob=TARGET,
                category="auth-audit", sha256=SHA, authored="ai-agent",
                authored_basis="inferred", change_note="（测试夹具）")
    base.update(kw)
    return G.LedgerEntry(**base)


#: "刻意不给 scope" 的哨兵。为什么需要一个哨兵：`scope` 有三个不同的意思 ——
#: (1) 没给 ⇒ 按维度自动配一个互不相同的观察面；(2) 显式给了一个值 ⇒ 用那个值；
#: (3) 显式给空 ⇒ 这一条没有合规 scope（负控要的正是第 (3) 种）。
#: 用默认参数 `scope=""` 无法区分 (1) 与 (3)，用 `None` 也无法区分（它还是个"给了假值"），
#: 于是负控会悄悄退回 (1) 而测不出东西 —— 本文件第一版就是这样自己骗自己的。
_UNSET = object()


def _audit(auditor: str, dimension: str, scope: object = _UNSET, **kw):
    """一条合规的审计记录。

    `scope` 不给（`_UNSET`）时按维度在 `SCOPES`/`DIMENSIONS` 里的位置取一个不同的观察面；
    显式传 `""` / `"   "` / `None` 就落成空串 —— 负控要的正是"这一条没有合规 scope"。
    """
    scope = SCOPES[DIMENSIONS.index(dimension) % len(SCOPES)] if scope is _UNSET \
        else ("" if scope is None else str(scope))
    sha = kw.pop("sha256", SHA)
    ev_path = kw.pop("evidence_path", None)
    ev_sha = kw.pop("evidence_sha256", _UNSET)
    # 顺序很重要（这里踩过一次）：`_make_evidence()` 的返回值不能无条件覆盖
    # 调用方显式给的 `evidence_sha256` —— 负控(12) 要的正是"有路径、但锚是空的"，
    # 覆盖掉它，那一条就会从"不计数"变成"计数"，而用例照样是绿的（自己骗自己）。
    if ev_path is None:
        ev_path, made_sha = _make_evidence(auditor, scope, sha)
        if ev_sha is _UNSET:
            ev_sha = made_sha
    elif ev_sha is _UNSET or ev_sha is None:
        # 路径可能是刻意不存在的那种（负控(10)）：那时 hash 由调用方给死，
        # 这里不去算它（算了会抛 `LedgerError`，那是 `sha256_file` 的正确行为）。
        ev_sha = G.sha256_file(ev_path)
    if ev_sha is _UNSET:
        ev_sha = ""
    return G.ReviewAudit(auditor=auditor, dimension=dimension, at=kw.pop("at", _AT),
                         sha256=sha, evidence=kw.pop("evidence", "temp/x.md"),
                         negative_control=kw.pop("negative_control", NEGATIVE_CONTROL),
                         scope=scope,
                         evidence_path=str(ev_path), evidence_sha256=ev_sha,
                         audit_started_sha256=kw.pop("audit_started_sha256", sha),
                         independence=kw.pop("independence", _independence(auditor)),
                         **kw)


def _six_clean_audits():
    """3 名审计者 × 6 个维度、6 个互不相同的观察面、每条都清白。

    为什么是 3 名而不是 2 名（`R6-R1d-4` 之后必须改的一处夹具）：判据 0 现在直接判
    "贡献最多的那一名审计者是否超过 `max_share = max(1, (require+1)//2)`"（`require = 3`
    ⇒ 上限 2）。旧夹具把 6 个维度按 3/3 分给 2 名审计者，放在新判据下是不合规的
    （每人都超过上限）—— 那不是判据变坏，而是旧夹具本身就是判据 0 要挡的形态
    （一名审计者供给 3 个计入维度 = 门槛的全部）。改成 2/2/2 之后，6 个维度、
    6 个观察面、3 名审计者都在，而每名审计者的贡献都在上限之内。
    """
    return tuple(
        _audit(auditor, dim, scope)
        for auditor, dim, scope in zip(
            ("subagent-A", "subagent-A",
             "subagent-B", "subagent-B",
             "subagent-C", "subagent-C"),
            DIMENSIONS, SCOPES)
    )


def _ledger(entry):
    return G.Ledger(ledger_version=G.LEDGER_VERSION, generated_at="2026-09-26T00:00:00+08:00",
                    entries=(entry,))


def _eval(entry, current: str = SHA, *, receipt_log: pathlib.Path | None = RECEIPT_LOG) -> dict:
    """调真实签名（`evaluate_approval(path, *, entry, current_sha256, is_ledger_itself, ...)`）。

    `receipt_log` 默认给夹具里那条真链；要测"链缺失/断链"的用例显式传别的路径。
    """
    return G.evaluate_approval(entry.path, entry=entry, current_sha256=current,
                               is_ledger_itself=entry.path == G.LEDGER_NAME,
                               receipt_log=receipt_log)


# ============================================================ 正控：通路能通过

def test_scope_tokens_are_real_symbols_of_the_target() -> None:
    """夹具自检：`SCOPES` 里的每个名字都必须真的是被审对象里定义着的标识符。

    这一条是夹具的判据，不是门的判据。它守的是本文件最容易悄悄退化的一处：
    门只要求"至少一个 token 落在被审对象的标识符集合上"（`dimension_independence_problem`
    判据 3），而写入侧才逐条要求。夹具若图省事写成 `scope="全文"` 这类短词，
    读侧用例仍可能变绿，而"这次审计覆盖了哪些符号"这句话就重新变成了空话。
    """
    text = (GATE.resolve().parents[1] / TARGET).read_text(encoding="utf-8", errors="replace")
    idents = G._identifiers_of(text)
    assert idents, "被审对象读不到 ⇒ 下面这条断言没有意义（判据的前提没建立）"
    missing = [s for s in SCOPES if s not in idents]
    assert not missing, f"夹具的 scope 里有不是被审对象标识符的：{missing}"
    # 每个 scope 归一化后必须两两不同，否则 `R5-R1b-1` 判据 1 会（正确地）报红
    keys = [G._observation_key(s) for s in SCOPES]
    assert len(set(keys)) == len(keys), keys


def test_three_auditors_six_dimensions_all_clean_is_approved() -> None:
    """正控：≥2 名不同审计者 × ≥3 个维度、每条都清白且带负控 ⇒ approved（通路 = 多维独立审计）。

    夹具用 3 名审计者：`R6-R1d-4` 之后判据 0 直接判「一名审计者供给了太多计入维度」
    （2 名 × 各 3 个维度就超过 `max_share = 2`），所以"应当通过"的形态必须是
    "没有任何一名审计者供给超过门槛一半的维度"。
    """
    e = _entry(audits=_six_clean_audits())
    out = _eval(e)
    assert out["approval_status"] == "approved", out
    assert out["distinct_auditors"] == 3
    assert len(out["distinct_dimensions"]) == 6
    assert "多维独立审计" in out["detail"]
    # 关键：报告必须点明没有人签过字 —— 否则读门的报告会把机审读成人签
    assert "没有任何人类 reviewer 签过字" in out["detail"], out["detail"]
    assert out["reviewers"] == []
    # 两层外层锚都必须在报告里留下痕迹（不然读的人不知道门查了什么）
    assert out["receipt_chain"]["records"] >= 1, out["receipt_chain"]
    assert all(c["status"] == "ok" for c in out["evidence_checked"]), out["evidence_checked"]
    # `R5-R1b-1`：6 个维度背后必须是 6 个互不相同的观察面（否则是同一份观察换标签）
    assert len({G._observation_key(a.scope) for a in e.counted_audits}) == 6


def test_human_channel_still_works_and_says_so() -> None:
    """两条通路并存：人审够 2 名 ⇒ approved，且理由里写的是人审。"""
    e = _entry(reviewers=(
        G.Reviewer(name="张三", at="2026-09-26T00:00:00+08:00", scope="逐行"),
        G.Reviewer(name="李四", at="2026-09-26T00:00:00+08:00", scope="逐行"),
    ))
    out = _eval(e)
    assert out["approval_status"] == "approved"
    assert "人审" in out["detail"]


# ============================================================ 负控

def test_a_finding_blocks_the_audit_channel() -> None:
    """负控(1)：审计报了问题 ⇒ 不放行，且 finding 原文必须出现在理由里。"""
    audits = list(_six_clean_audits())
    audits[3] = _audit("subagent-B", "contract", SCOPES[3],
                       findings=("REAL PROBLEM: 拒绝分支少一个键",))
    e = _entry(audits=tuple(audits))
    out = _eval(e)
    assert out["approval_status"] == "unapproved"
    assert "REAL PROBLEM" in out["detail"], out["detail"]
    assert len(out["dirty_audits"]) == 1


def test_an_audit_of_a_different_revision_does_not_count() -> None:
    """负控(2)：审计的 sha256 与台账条目不一致 ⇒ 不计数（防"改了之后再补旧版审计"）。"""
    e = _entry(audits=tuple(
        _audit(a, d, s, sha256="b" * 64)
        for a, d, s in zip(("subagent-A",) * 3 + ("subagent-B",) * 3, DIMENSIONS, SCOPES)
    ))
    out = _eval(e)
    assert out["approval_status"] == "unapproved", out
    assert out["distinct_auditors"] == 0 and out["clean_audits"] == []


def test_an_audit_without_negative_control_does_not_count() -> None:
    """负控(3)：没有负控的审计不计数 —— 要设计成"去掉它就掉到门槛以下"，否则测不出东西。

    (注意) 第一版我把 6 条审计里只挖空 1 条 ⇒ 还剩 2 名 × 5 个维度，门槛照样满足、判成 approved。
    那不是实现错，是我的夹具没把门槛压到线下（"判据的前提没建立，结论就没有意义"）。
    本版：让审计者 A 的三条全都没有负控 ⇒ A 贡献 0 条清白审计 ⇒ 只剩 B 一名审计者。
    """
    e = _entry(audits=(
        _audit("subagent-A", "axes", SCOPES[0], negative_control="   "),
        _audit("subagent-A", "roles", SCOPES[1], negative_control=""),
        _audit("subagent-A", "errors", SCOPES[2], negative_control="  "),
        _audit("subagent-B", "contract", SCOPES[3]), _audit("subagent-B", "docs", SCOPES[4]),
        _audit("subagent-B", "tests", SCOPES[5]),
    ))
    out = _eval(e)
    assert out["approval_status"] == "unapproved", out
    assert len(out["clean_audits"]) == 3, out["clean_audits"]   # 只剩 B 的三条
    assert out["distinct_auditors"] == 1


@pytest.mark.parametrize(
    "audits",
    [
        # 只有 1 名审计者（6 个维度也不行）
        tuple(_audit("subagent-A", d, s) for d, s in zip(DIMENSIONS, SCOPES)),
        # 2 名审计者但只有 2 个维度
        (_audit("subagent-A", "axes", SCOPES[0]), _audit("subagent-B", "axes", SCOPES[1])),
    ],
)
def test_the_thresholds_are_real(audits) -> None:
    """负控(4)：审计者数或维度数不够 ⇒ 不放行（门槛必须是真的在判）。"""
    out = _eval(_entry(audits=audits))
    assert out["approval_status"] == "unapproved", out


def test_stale_hash_still_beats_both_channels() -> None:
    """负控(5)：内容变了（stale）⇒ 无论审计多齐都不放行（这一条优先于两条通路）。"""
    e = _entry(audits=_six_clean_audits())
    out = _eval(e, "c" * 64)
    assert out["approval_status"] == "unapproved"
    assert out["approval_reason"] == G.REASON_STALE


def test_an_audit_without_a_scope_does_not_count() -> None:
    """负控(5b)：字段层 —— 没有 `scope` 的审计不计数（`H-1d`）。

    这一条是本批新增的：`scope` 从"可以不给"变成"必须说清覆盖了哪些符号"，
    而夹具与判据同时改，很容易把这件事测丢（两边一起改，红的那条没了）。
    挖空审计者 A 的三条 ⇒ A 贡献 0 条 ⇒ 只剩 B 一名审计者 ⇒ unapproved。
    """
    e = _entry(audits=(
        # scope 的三种"空"：None / 空串 / 纯空白 —— 都必须落成"没有 scope"
        _audit("subagent-A", "axes", scope=None),
        _audit("subagent-A", "roles", scope=""),
        _audit("subagent-A", "errors", scope="   "),        _audit("subagent-B", "contract", SCOPES[3]), _audit("subagent-B", "docs", SCOPES[4]),
        _audit("subagent-B", "tests", SCOPES[5]),
    ))
    out = _eval(e)
    assert out["approval_status"] == "unapproved", out
    assert len(out["clean_audits"]) == 3, out["clean_audits"]
    assert out["distinct_auditors"] == 1


def test_audits_sharing_one_observation_surface_do_not_count_as_dimensions() -> None:
    """负控(5c)：6 条 `scope` 全一样的审计 ⇒ 观察面只有 1 个 ⇒ 不放行（`R5-R1b-1`）。

    这是"同一份观察换 `dimension` 标签"的形态：维度字符串有 6 个、审计者有 2 名、
    记录条条合规，但 `_observation_key` 归一化后全是同一个面。
    """
    e = _entry(audits=tuple(
        _audit(a, d, SCOPES[0])
        for a, d in zip(("subagent-A",) * 3 + ("subagent-B",) * 3, DIMENSIONS)
    ))
    out = _eval(e)
    assert out["approval_status"] == "unapproved", out
    assert out["approval_reason"] == G.REASON_DIMENSION_SURFACE, out


def test_a_scope_of_unreal_symbols_does_not_count() -> None:
    """负控(5d)：`scope` 里的符号不是被审对象里真实存在的标识符 ⇒ 不放行（`R5-R1b-5`）。

    形态：`--audit-scope 'import return int'` —— 这三个词每个 `.py` 文件里都有，
    与"这次审计覆盖了哪些符号"毫无关系。判据要求 token 落在那个文件定义的名字上。
    """
    e = _entry(audits=(
        _audit("subagent-A", "axes", scope="import return int"),
        _audit("subagent-A", "roles", scope="import return int"),
        _audit("subagent-A", "errors", scope="import return int"),
        _audit("subagent-B", "contract", scope="import return int"),
        _audit("subagent-B", "docs", scope="import return int"),
        _audit("subagent-B", "tests", scope="import return int"),
    ))
    out = _eval(e)
    assert out["approval_status"] == "unapproved", out
    assert out["approval_reason"] == G.REASON_DIMENSION_SURFACE, out


def test_a_missing_evidence_file_makes_the_verdict_unknown() -> None:
    """负控(10)：证据文件读不到 ⇒ `unknown`（没查成），不是 `unapproved`。

    这一条是 `temp/verify-audit-forge.txt` 那次伪造复现的直接回归：
    改前 `evidence` 只查"非空"，于是编一个不存在的路径也能让门报 `clean(0)`。
    现在读不到证据文件 ⇒ 判 `unknown(2)`：三态纪律里"没查成"既不是"批准"也不是"未批准"。
    """
    audits = list(_six_clean_audits())
    audits[0] = _audit("subagent-A", "axes", SCOPES[0],
                       evidence_path=r"D:\Incubator\temp\不存在-不要建这个文件.json",
                       evidence_sha256="f" * 64)
    e = _entry(audits=tuple(audits))
    out = _eval(e)
    assert out["approval_status"] == "unknown", out
    assert out["approval_reason"] == G.REASON_AUDIT_EVIDENCE
    assert "读不到" in out["detail"], out["detail"]


def test_an_evidence_file_whose_content_changed_makes_the_verdict_unknown(tmp_path) -> None:
    """负控(11)：证据文件被换过（hash 对不上）⇒ `unknown`，不许按"审计通过"放行。

    这是"把一次性的观察当成持续的事实"那道口子：写入时证据在、hash 也对，
    但判定时文件已被重写（`temp/` 会被清理、会被重跑覆盖）。
    """
    f = tmp_path / "ev.json"
    f.write_text("原来是这份证据\n", encoding="utf-8")
    good = G.sha256_file(f)
    f.write_text("换成了另一份内容\n", encoding="utf-8")  # 换过之后 hash 不再等于 good
    audits = list(_six_clean_audits())
    audits[0] = _audit("subagent-A", "axes", SCOPES[0],
                       evidence_path=str(f), evidence_sha256=good)
    e = _entry(audits=tuple(audits))
    out = _eval(e)
    assert out["approval_status"] == "unknown", out
    assert out["approval_reason"] == G.REASON_AUDIT_EVIDENCE
    assert "与登记不符" in out["detail"], out["detail"]


def test_an_evidence_file_that_does_not_match_the_declaration_is_unknown(tmp_path) -> None:
    """负控(11b)：hash 对得上，但内容与声明对不上 ⇒ `unknown`（`H-1b` / `R1-AN-4`）。

    hash 只证明"这个文件没被换过"，不证明"这个文件是这个主体审这一版产出的"。
    这里造一份 hash 完全正确、但正文里没有审计者标识的证据 ⇒ 交叉核对必须报出来。
    这一条也是本批的直接产物：夹具的证据正文原来只是一句 `fixture: ...`，
    正是被这条判据（③ scope 必须出现在证据里）挡住的。
    """
    f = tmp_path / "ev-no-auditor.txt"
    f.write_text(f"审计范围（scope）：{SCOPES[0]}\n被审版本：{SHA}\n负控：改前\n",
                 encoding="utf-8")
    audits = list(_six_clean_audits())
    audits[0] = _audit("subagent-A", "axes", SCOPES[0],
                       evidence_path=str(f), evidence_sha256=G.sha256_file(f))
    e = _entry(audits=tuple(audits))
    out = _eval(e)
    assert out["approval_status"] == "unknown", out
    assert out["approval_reason"] == G.REASON_AUDIT_EVIDENCE
    assert "证据文件里没有以**独立词**形态出现审计者标识" in out["detail"], out["detail"]


def test_an_audit_without_an_evidence_anchor_does_not_count() -> None:
    """负控(12)：记录里没有 `evidence_sha256`（只有一句 `evidence` 文本）⇒ 不计数。

    与缺负控那一档同族：没有证据锚的"未发现问题"与"没人审过"在机器眼里无法区分。
    """
    e = _entry(audits=tuple(
        _audit(a, d, s, evidence_sha256="")
        for a, d, s in zip(("subagent-A",) * 3 + ("subagent-B",) * 3, DIMENSIONS, SCOPES)
    ))
    out = _eval(e)
    assert out["approval_status"] == "unapproved", out
    assert out["clean_audits"] == [], out["clean_audits"]
    assert out["distinct_auditors"] == 0


def test_an_audit_without_an_audit_started_sha_does_not_count() -> None:
    """负控(12b)：没有 `audit_started_sha256` 的审计不计数（`c-20`）。

    没有它，"审的是 A 版、记账时台账已被 `--baseline` 刷成 B 版"在结构上是通的，
    而门照样报 clean。挖空审计者 A 的三条 ⇒ A 贡献 0 条 ⇒ 只剩 B 一名审计者。
    """
    e = _entry(audits=(
        _audit("subagent-A", "axes", SCOPES[0], audit_started_sha256=""),
        _audit("subagent-A", "roles", SCOPES[1], audit_started_sha256=""),
        _audit("subagent-A", "errors", SCOPES[2], audit_started_sha256=""),
        _audit("subagent-B", "contract", SCOPES[3]), _audit("subagent-B", "docs", SCOPES[4]),
        _audit("subagent-B", "tests", SCOPES[5]),
    ))
    out = _eval(e)
    assert out["approval_status"] == "unapproved", out
    assert out["distinct_auditors"] == 1


def test_an_audit_with_a_future_or_unparseable_timestamp_is_unknown() -> None:
    """负控(12c)：`at` 不可解析 / 落在未来 ⇒ 不计数（`R5-R1b-7`）。

    `at` 曾经是整条通路里唯一"写了就信、读回不校验"的字段（实测：把门的时钟拨到 2099
    写进去，`record_audit` 照收，判定侧从不读它）。夹具的 `at` 因此必须是合规 ISO-8601。
    """
    e = _entry(audits=(
        _audit("subagent-A", "axes", SCOPES[0], at="2099-01-01T00:00:00+08:00"),
        _audit("subagent-A", "roles", SCOPES[1], at="now"),
        _audit("subagent-A", "errors", SCOPES[2], at=""),
        _audit("subagent-B", "contract", SCOPES[3]), _audit("subagent-B", "docs", SCOPES[4]),
        _audit("subagent-B", "tests", SCOPES[5]),
    ))
    out = _eval(e)
    assert out["approval_status"] == "unapproved", out
    assert out["distinct_auditors"] == 1
    # 逐档确认这三条各自失败的理由就是时间戳（不是别的字段顺带把它拦了）
    assert "落在**未来**" in G.audit_timestamp_problem("2099-01-01T00:00:00+08:00")
    assert "ISO-8601" in G.audit_timestamp_problem("now")
    assert "为空" in G.audit_timestamp_problem("")
    # 正控对照：夹具默认那个 `at` 是合规的（可解析、不在未来）
    assert G.audit_timestamp_problem("2026-09-26T00:00:00+08:00") == ""

# ------------------------------------------------- 回执链（外层锚）：只增、可重算


def test_a_missing_receipt_chain_makes_the_verdict_unknown(tmp_path: pathlib.Path) -> None:
    """负控(15)：回执链不存在 ⇒ `unknown`（没有外层锚，这次"没查成"）。"""
    e = _entry(audits=_six_clean_audits())
    out = _eval(e, receipt_log=tmp_path / "没有这条链.jsonl")
    assert out["approval_status"] == "unknown", out
    assert out["approval_reason"] == G.REASON_AUDIT_RECEIPT
    assert "回执链不存在" in out["detail"], out["detail"]


def test_a_tampered_receipt_chain_is_detected(tmp_path: pathlib.Path) -> None:
    """负控(16)：链里改一个字节 ⇒ 重算就对不上 ⇒ 判 `unknown`（这就是"只增"的用处）。

    造法：把链里那条记录的 `detail` 改掉，不动它的 `hash` —— 这正是"事后悄悄改一条记录"
    的形态。旧形态（只看"有没有这条记录"）发现不了它。
    """
    log = tmp_path / "receipts.jsonl"
    G.append_receipt(action="record_audit", path=TARGET,
                     entry_sha256=SHA, detail="原来的备注", log_path=log)
    raw = log.read_text(encoding="utf-8")
    log.write_text(raw.replace("原来的备注", "改过的备注"), encoding="utf-8")
    e = _entry(audits=_six_clean_audits())
    out = _eval(e, receipt_log=log)
    assert out["approval_status"] == "unknown", out
    assert out["approval_reason"] == G.REASON_AUDIT_RECEIPT
    assert "被改过" in out["detail"], out["detail"]


def test_a_removed_receipt_ring_breaks_the_chain(tmp_path: pathlib.Path) -> None:
    """负控(17)：把中间那一环删掉 ⇒ 后一环的 `prev` 对不上 ⇒ 断链 ⇒ `unknown`。

    这是回执链要挡的主要形态：删掉一条对自己不利的记录。
    """
    log = tmp_path / "receipts.jsonl"
    for i in (1, 2, 3):
        G.append_receipt(action="record_audit", path=TARGET,
                         entry_sha256=SHA, detail=f"第 {i} 环", log_path=log)
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    log.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")  # 抽掉中间那环
    e = _entry(audits=_six_clean_audits())
    out = _eval(e, receipt_log=log)
    assert out["approval_status"] == "unknown", out
    assert "断" in out["detail"], out["detail"]


def test_a_chain_that_never_recorded_this_revision_is_unknown(tmp_path: pathlib.Path) -> None:
    """负控(18)：链是好的，但里面没有这一版的记录 ⇒ 仍判 `unknown`。

    这一档防的是"拿别处的旧回执充当这一版的回执"：
    链再完整，只要 `(path, sha256)` 这一对没出现过，就不能说这一版被记下来过。
    """
    log = tmp_path / "receipts.jsonl"
    G.append_receipt(action="record_audit", path=TARGET,
                     entry_sha256="e" * 64, detail="另一版", log_path=log)
    e = _entry(audits=_six_clean_audits())
    out = _eval(e, receipt_log=log)
    assert out["approval_status"] == "unknown", out
    assert "没有这一版" in out["detail"], out["detail"]


def test_append_receipt_refuses_to_extend_a_broken_chain(tmp_path: pathlib.Path) -> None:
    """负控(19)：链已经断了 ⇒ 拒绝继续追加，而不是把新记录挂到断链后面。

    为什么这是判据而不是洁癖：断链后面续写出来的链，只看尾部是"正常"的，
    于是"链断过"这件事会被永久掩盖。断链的正确处置是人看过之后决定重建。
    """
    log = tmp_path / "receipts.jsonl"
    G.append_receipt(action="record_audit", path=TARGET,
                     entry_sha256=SHA, detail="第一环", log_path=log)
    log.write_text(log.read_text(encoding="utf-8").replace("第一环", "被改过"), encoding="utf-8")
    with pytest.raises(G.LedgerError) as e:
        G.append_receipt(action="record_audit", path=TARGET,
                         entry_sha256=SHA, detail="第二环", log_path=log)
    assert "断链" in str(e.value) or "不通过校验" in str(e.value)


# ============================================================ 写入侧的校验

def _write_ledger(tmp: pathlib.Path) -> pathlib.Path:
    target = tmp / "src" / "agentflow" / "tools"
    target.mkdir(parents=True)
    f = target / "base.py"
    # 目标里要有真实定义的标识符：写入侧逐条要求 `scope` 的 token 落在
    # `_identifiers_of(目标)` 上（`_evidence_cross_check` ③）。写 `x = 1` 时标识符集合
    # 只有 `{"x"}`（长度 <3 直接不算 token）⇒ 任何合规 scope 都会被判"不真实"。
    f.write_text(
        "SIDE_EFFECTS = (\"none\", \"read\", \"write_local\")\n\n\n"
        "def validate_params(schema, params):\n"
        "    return None\n",
        encoding="utf-8",
    )
    # 清单也必须真的存在：`register_baseline` 会去读它（读不到是 unknown，不是"没有禁改区"）
    (tmp / G.MANIFEST_NAME).write_text(
        "[category: auth-audit] 夹具用的禁改区分组\n\n"
        "src/agentflow/tools/base.py  [category: auth-audit]  夹具用的禁改区条目\n",
        encoding="utf-8",
    )
    p = tmp / G.LEDGER_NAME
    p.write_text(json.dumps({
        "ledger_version": G.LEDGER_VERSION, "generated_at": "2026-09-26T00:00:00+08:00",
        "entries": [{"path": TARGET, "glob": TARGET,
                     "category": "auth-audit", "sha256": G.sha256_file(f),
                     "authored": "ai-agent", "authored_basis": "inferred",
                     "change_note": "（夹具）", "reviewers": [], "audits": []}],
    }, ensure_ascii=False), encoding="utf-8")
    return p


def _write_side_audit(tmp: pathlib.Path, ledger, *, auditor: str = "subagent-A",
                      dimension: str = "axes", scope: str = "validate_params", **kw):
    """在 `tmp` 这个假仓库里记录一条审计；返回 `(ledger, info)`。

    写入侧要凑齐的（缺一条就被拒，且每条都对应一处判据）：
    `evidence_path` 读得到、`evidence_sha256` 与盘上一致、`audit_started_sha256`
    与台账同版、`scope` 是被审对象里真实存在的标识符、`negative_control` 合格、
    署名者已知时 `independence` 可不给（这里都给）。
    """
    sha = G.sha256_file(tmp / TARGET)
    ev = kw.pop("evidence_path", None)
    if ev is None:
        ev = tmp / "evidence.json"
        ev.write_text(_evidence_text(auditor, scope, sha), encoding="utf-8")
    return G.record_audit(
        ledger, TARGET, auditor=auditor, dimension=dimension,
        evidence=kw.pop("evidence", "temp/x.md"),
        negative_control=kw.pop("negative_control", NEGATIVE_CONTROL), scope=scope,
        evidence_path=str(ev), audit_started_sha256=kw.pop("audit_started_sha256", sha),
        root=tmp, independence=_independence(auditor), **kw)


def test_record_audit_refuses_without_negative_control(tmp_path: pathlib.Path) -> None:
    """负控(6)：写入侧也挡 —— 空负控 / 空证据 / 非法维度 / 空审计者 / 空 scope 一律拒绝写入。"""
    p = _write_ledger(tmp_path)
    led = G.load_ledger(p)
    # 正控：合法的一次能写进去（证明下面五档拦的是"错的那种"，不是"全都拦"）
    led, info = _write_side_audit(tmp_path, led)
    assert info["clean_audits"] == 1
    assert info["audits"] == 1
    assert info["evidence_sha256"] == G.sha256_file(tmp_path / "evidence.json")

    for bad in (
        {"negative_control": "  "},
        {"evidence": ""},
        {"auditor": " "},
        {"dimension": "not-a-dimension"},
        {"scope": ""},
        {"scope": "   "},
        # `c-20`：写入侧也要求写清"开审那一刻是哪一版"
        {"audit_started_sha256": ""},
        # `c-20`：写的必须是这一版，不能是别的版本
        {"audit_started_sha256": "b" * 64},
    ):
        with pytest.raises(G.LedgerError):
            _write_side_audit(tmp_path, led, **bad)


def test_record_audit_refuses_a_missing_or_mismatched_evidence_file(tmp_path: pathlib.Path) -> None:
    """负控(13)：写入侧的证据锚 —— 文件不存在 / hash 对不上 / 没给路径 / 格式非法，四档都拒绝。"""
    p = _write_ledger(tmp_path)
    led = G.load_ledger(p)
    sha = G.sha256_file(tmp_path / TARGET)
    ev = tmp_path / "evidence.json"
    ev.write_text(_evidence_text("subagent-A", "validate_params", sha), encoding="utf-8")
    good = G.sha256_file(ev)
    base = dict(auditor="subagent-A", dimension="axes", evidence="temp/x.md",
                negative_control=NEGATIVE_CONTROL, scope="validate_params", root=tmp_path,
                audit_started_sha256=sha, independence=_independence("subagent-A"))

    # ① 没给 `evidence_path` ⇒ 拒绝（旧版这一档能写进去，而 `evidence` 只是一句话）
    with pytest.raises(G.LedgerError) as e1:
        G.record_audit(led, TARGET, **base)
    assert "evidence-path" in str(e1.value)

    # ② 路径指向一个不存在的文件 ⇒ 拒绝
    with pytest.raises(G.LedgerError) as e2:
        G.record_audit(led, TARGET, evidence_path=str(tmp_path / "没有这个文件.json"), **base)
    assert "读不到" in str(e2.value)

    # ③ 给了 `evidence_sha256` 但与盘上不符 ⇒ 拒绝（防"登记一个别处的 hash"）
    with pytest.raises(G.LedgerError) as e3:
        G.record_audit(led, TARGET, evidence_path=str(ev),
                       evidence_sha256="b" * 64, **base)
    assert "不一致" in str(e3.value)

    # ④ 给的 hash 不是 64 位小写十六进制 ⇒ 拒绝
    with pytest.raises(G.LedgerError) as e4:
        G.record_audit(led, TARGET, evidence_path=str(ev),
                       evidence_sha256="NOT-A-HASH", **base)
    assert "十六进制" in str(e4.value)

    # ⑤ 证据与声明对不上（正文里没有审计者标识）⇒ 拒绝（`H-1b` 交叉核对，写入侧也跑）
    f5 = tmp_path / "ev-cross.json"
    f5.write_text(f"审计范围（scope）：validate_params\n被审版本：{sha}\n负控：改前\n",
                  encoding="utf-8")
    with pytest.raises(G.LedgerError) as e5:
        G.record_audit(led, TARGET, evidence_path=str(f5),
                       evidence_sha256=G.sha256_file(f5), **base)
    assert "证据与声明对不上" in str(e5.value)

    # ⑥ `scope` 不是被审对象里的标识符 ⇒ 拒绝（`R5-R1b-5`）
    with pytest.raises(G.LedgerError) as e6:
        G.record_audit(led, TARGET, evidence_path=str(ev), **{**base, "scope": "import return int"})
    assert "真实存在的标识符" in str(e6.value)

    # 正控对照：给对的 hash ⇒ 写得进去（证明上面六档拦的是"错的那种"，不是"全都拦"）
    _, info = G.record_audit(led, TARGET, evidence_path=str(ev),
                             evidence_sha256=good, **base)
    assert info["evidence_sha256"] == good


def test_record_audit_never_touches_reviewers(tmp_path: pathlib.Path) -> None:
    """负控(7)：写审计绝不写 `reviewers`（两条通路分列，机器审计不冒充人）。"""
    p = _write_ledger(tmp_path)
    led = G.load_ledger(p)
    new, _info = _write_side_audit(tmp_path, led)
    e = new.entry_for(TARGET)
    assert e.reviewers == (), "审计通路写脏了 reviewers ⇒ 人审与机审的分别就没了"
    assert len(e.audits) == 1


def test_add_approval_keeps_the_recorded_audits(tmp_path: pathlib.Path) -> None:
    """负控(14)：人签一次字不许把机审记录清空。

    这是 `add_approval` 里重建 `LedgerEntry` 时漏掉 `audits=entry.audits` 的回归判据：
    改前那一刻，`--approve` 会把该条已记录的审计静默丢掉（默认值 `()`），
    而台账照样是合法 JSON —— 没有任何地方会报错。
    """
    p = _write_ledger(tmp_path)
    led = G.load_ledger(p)
    led, _ = _write_side_audit(tmp_path, led)
    led2, info = G.add_approval(
        led, TARGET, reviewer="张三", scope="逐行", root=tmp_path,
    )
    e = led2.entry_for(TARGET)
    assert len(e.audits) == 1, "人签字把机审记录清空了 ⇒ 两条通路分列这件事被破坏"
    assert e.audits[0].auditor == "subagent-A"
    assert info["audits_kept"] == 1, info
    assert len(e.reviewers) == 1


def test_baseline_clears_audits_when_content_changes(tmp_path: pathlib.Path) -> None:
    """负控(8)：内容变了 ⇒ `--baseline` 必须同时清空 `reviewers` 与 `audits`。"""
    p = _write_ledger(tmp_path)
    led = G.load_ledger(p)
    led, _ = _write_side_audit(tmp_path, led)
    led, _ = G.add_approval(
        led, TARGET, reviewer="张三", scope="逐行", root=tmp_path,
    )
    (tmp_path / TARGET).write_text("SIDE_EFFECTS = ()\n", encoding="utf-8")
    new, _results = G.register_baseline(
        [TARGET], root=tmp_path, ledger=led,
        manifest=tmp_path / G.MANIFEST_NAME, default_authored_basis="inferred",
    )
    e = new.entry_for(TARGET)
    assert e.audits == (), "内容变了 ⇒ 旧审计必须清空（它审的是旧那一版）"
    assert e.reviewers == (), "内容变了 ⇒ 旧签名也必须清空"


def test_dimension_vocabulary_is_enforced_on_parse() -> None:
    """负控(9)：手工往台账里塞一个词表外的维度 ⇒ 解析就抛 `LedgerError`（⇒ unknown，不是"没审计"）。"""
    good = {"auditor": "x", "dimension": "axes", "at": "2026-09-26T00:00:00+08:00", "sha256": SHA,
            "evidence": "e", "negative_control": NEGATIVE_CONTROL,
            "evidence_sha256": "d" * 64, "evidence_path": "temp/e.json",
            "scope": SCOPES[0], "audit_started_sha256": SHA,
            "independence": _independence("x")}
    # 正控：齐全的记录能解析
    assert G._parse_audit(good, where="t").dimension == "axes"
    with pytest.raises(G.LedgerError):
        G._parse_audit({**good, "dimension": "whatever"}, where="t")
    with pytest.raises(G.LedgerError):
        G._parse_audit({k: v for k, v in good.items() if k != "negative_control"}, where="t")
    # 缺证据锚也必须在解析这一层就被挡住（不是等判定时才发现）
    with pytest.raises(G.LedgerError):
        G._parse_audit({k: v for k, v in good.items() if k != "evidence_sha256"}, where="t")
    with pytest.raises(G.LedgerError):
        G._parse_audit({**good, "evidence_sha256": "太短"}, where="t")
    # 缺 `sha256` / `evidence` / `at` 同样在解析层抛（它们是 `_req` 的必需字段）
    for missing in ("sha256", "evidence", "at", "auditor"):
        with pytest.raises(G.LedgerError):
            G._parse_audit({k: v for k, v in good.items() if k != missing}, where="t")


def test_empty_scope_and_audit_started_sha_are_caught_at_the_field_layer() -> None:
    """负控(9b)：`scope` 与 `audit_started_sha256` 为空时，拦在字段层而不是解析层。

    这条是刻意写下来的口径记录：`_parse_audit` 只查结构性字段（必需字段非空 + 维度在
    受控词表里 + hash 形态），`scope` 空、`audit_started_sha256` 空它不抛 ——
    它们由 `LedgerEntry.clean_audits` 的字段层过滤掉，报文是 `unapproved`
    （"这条审计本身不合规"），而不是 `unknown`（"没查成"）。
    两层分开是刻意的：处置不同。谁把这两层折叠，谁就把"没查成"读成了"查过了没问题"。
    """
    text = (GATE.resolve().parents[1] / TARGET).read_text(encoding="utf-8", errors="replace")
    assert G._identifiers_of(text), "被审对象读不到 ⇒ 判据的前提没建立"
    for label, kw in (("scope", {"scope": ""}),
                      ("audit_started_sha256", {"audit_started_sha256": ""})):
        # 解析层：不抛（它不认识这两个字段，它们不是结构性的）
        parsed = G._parse_audit({
            "auditor": "x", "dimension": "axes", "at": "2026-09-26T00:00:00+08:00",
            "sha256": SHA, "evidence": "e", "negative_control": NEGATIVE_CONTROL,
            "evidence_sha256": "d" * 64, "evidence_path": "temp/e.json",
            "scope": SCOPES[0], "audit_started_sha256": SHA,
            "independence": _independence("x"), **kw,
        }, where="t")
        assert parsed is not None
        # 字段层：收录为 0 条 ⇒ 门槛不满足 ⇒ unapproved
        mutated = dict(kw)
        if "scope" in mutated:
            mutated["scope"] = None      # 走 `_audit(scope=...)` 这一个入口，不能重复给
        e = _entry(audits=(_audit("subagent-A", "axes", **mutated),))
        assert len(e.clean_audits) == 0, (label, e.clean_audits)
        # 把这一条放回一个"刚好够门槛"的集合里（3 条审计、3 个维度、3 名审计者），
        # 让它不计数这件事真的把门槛压到线下 ⇒ unapproved。
        # 手写 `[3:]` 那种下标切片不能用：夹具改成 3 名审计者 × 2 个维度之后，
        # 切片剩下的那些自己就够门槛（3 名审计者 × 4 个维度），这条负控会假绿 ——
        # 判据在跑，但读数是"别的原因过了"，与被测的那一条无关。
        trio = tuple(_audit(f"subagent-{who}", dim, scope)
                     for who, dim, scope in (("A", "axes", SCOPES[0]),
                                             ("B", "roles", SCOPES[1]),
                                             ("C", "errors", SCOPES[2])))
        first = dict(_six_clean_audits()[0].to_dict())
        # `mutated["scope"]` 是 `None`（那是走 `_audit(scope=...)` 入口时的哨兵）；
        # 这里是在字段层复现"scope 空"，所以换成空串（`ReviewAudit` 的字段是 `str`）。
        first.update({k: ("" if v is None else v) for k, v in mutated.items()})
        # 这一条与 `trio[0]` 是同一名审计者 + 同一份证据身份
        # （`counted_audits` 的键 = 归一化路径 + 内容 hash）。所以它不被收录时，
        # 那个"维度 + 证据身份"一起消失：剩下的 2 条落在 2 名审计者 × 2 个维度上
        # ⇒ 门槛（≥2 名 × ≥3 个维度）不满足。若给它换一份证据、或换一个审计者名，
        # 剩下的三条自己就够门槛 ⇒ 这条负控会假绿（判据在跑，但读数与它无关）。
        ev = trio[0].to_dict()
        first["evidence_path"] = ev["evidence_path"]
        first["evidence_sha256"] = ev["evidence_sha256"]
        first["auditor"] = ev["auditor"]
        out = _eval(_entry(audits=trio + (G.ReviewAudit(**first),)))
        # 断言钉在"这一条没被收录"上，而不是钉在整体 verdict 上：
        # 整体 verdict 会随夹具一起漂（夹具从 2 名审计者改成 3 名之后，剩下的
        # 3 名 × 3 个维度自己就够门槛，于是整体照样 approved，而这一条其实
        # 根本没被收录 —— 那种写法会让这条负控变成一句假话）。
        # 这个集合是"差这一条就不够"的形态：3 名审计者 × 3 个维度（正好够门槛）
        # 再加这一条的唯一贡献者 —— 它不被收录时，`counted_audits` 与
        # `distinct_dimensions` 里都不会有它。
        assert [a["dimension"] for a in out["clean_audits"]] == ["axes", "roles", "errors"], (label, out)
        assert "axes" in out["distinct_dimensions"], (label, out["distinct_dimensions"])


def test_mutating_the_fixture_makes_the_gate_reject_it() -> None:
    """夹具的变异自检：把夹具的关键字段一个个改坏 ⇒ 门必须拒绝（负控真的在跑）。

    为什么这条必须存在（本批的教训）：修夹具最大的风险是"改到门看不见为止" ——
    夹具与判据一起改，红的那条没了，而门其实已经不再检查那件事。
    这里不做假设，直接做变异：每改坏一处，读数必须从"收录"变成"不收录"。

    覆盖：`scope` 空 / `scope` 不真实 / 观察面重复 / `evidence_sha256` 空 /
    `audit_started_sha256` 空或不同版 / `negative_control` 空 / `at` 在未来。
    """
    baseline = _entry(audits=_six_clean_audits())
    assert len(baseline.clean_audits) == 6, "前提：合规夹具必须全数收录（否则变异测不出东西）"
    sane = _six_clean_audits()

    # 变异 ①：`scope` 的三种空写法 ⇒ 字段层就不收录（`H-1d`）
    for bad_scope in (None, "", "   "):
        e = _entry(audits=(
            _audit("subagent-A", "axes", scope=bad_scope),) + sane[1:])
        assert len(e.clean_audits) == 5, (bad_scope, e.clean_audits)

    # 变异 ②：`scope` 里是被审对象里不存在的符号（语言关键字 / 内建名 / 随便一个词）。
    # (注意) 这一档不是字段层拦的 —— `clean_audits` 只看"非空"，不看"真不真"。
    # 拦它的是判定层的 `dimension_independence_problem`（判据 3 落点真实）：
    # 记录本身合规、2 名审计者 × 6 个维度都够，但 scope 的符号一个都不在那个文件里。
    # 把这一档写成"字段层会掉到 5"是错的（第一版就是这么错的）：它记录数照样是 6，
    # 被拦在更外面 —— 两层的分工必须在这里写清楚，否则下一个人会以为字段层漏了。
    for bad_scope in ("import return int", "the and for", "whatever"):
        e = _entry(audits=(
            _audit("subagent-A", "axes", bad_scope),) + sane[1:])
        assert len(e.clean_audits) == 6, (bad_scope, e.clean_audits)
        out = _eval(_entry(audits=tuple(
            _audit(a, d, bad_scope) for a, d in
            zip(("subagent-A",) * 3 + ("subagent-B",) * 3, DIMENSIONS))))
        assert out["approval_status"] == "unapproved", (bad_scope, out)
        assert out["approval_reason"] == G.REASON_DIMENSION_SURFACE, (bad_scope, out)

    # 变异 ③：观察面重复（6 条共用同一个 scope）⇒ 只有 1 个独立观察面
    e = _entry(audits=tuple(
        _audit(a, d, SCOPES[0]) for a, d in
        zip(("subagent-A",) * 3 + ("subagent-B",) * 3, DIMENSIONS)))
    assert len({G._observation_key(a.scope) for a in e.counted_audits}) == 1
    assert e.distinct_dimensions() and len(e.distinct_dimensions()) == 6

    # 变异 ④：`evidence_sha256` 空 ⇒ 字段层不收录（`temp/verify-audit-forge.txt` 那一族）
    e = _entry(audits=(
        _audit("subagent-A", "axes", evidence_sha256=""),) + sane[1:])
    assert len(e.clean_audits) == 5

    # 变异 ⑤：`audit_started_sha256` 空 / 不是这一版（`c-20`）⇒ 字段层不收录
    for bad_started in ("", "b" * 64):
        e = _entry(audits=(
            _audit("subagent-A", "axes", audit_started_sha256=bad_started),) + sane[1:])
        assert len(e.clean_audits) == 5, (bad_started, e.clean_audits)

    # 变异 ⑥：`negative_control` 空 ⇒ 字段层不收录
    e = _entry(audits=(
        _audit("subagent-A", "axes", negative_control=""),) + sane[1:])
    assert len(e.clean_audits) == 5

    # 变异 ⑦：`at` 在未来 / 不可解析 / 为空 ⇒ 字段层不收录（`R5-R1b-7`）
    for bad_at in ("2099-01-01T00:00:00+08:00", "now", ""):
        e = _entry(audits=(
            _audit("subagent-A", "axes", at=bad_at),) + sane[1:])
        assert len(e.clean_audits) == 5, (bad_at, e.clean_audits)

    # 变异 ⑧：`evidence_path` 指向不存在的文件 ⇒ 盘上层判 `unknown`（不是 unapproved）
    e = _entry(audits=(
        _audit("subagent-A", "axes",
               evidence_path=r"D:\Incubator\temp\batchR6ac-变异-这个文件不该存在.json",
               evidence_sha256="f" * 64),) + sane[1:])
    assert len(e.clean_audits) == 6, "盘上层的问题不该在字段层就被拦掉"
    out = _eval(e)
    assert out["approval_status"] == "unknown", out
    assert out["approval_reason"] == G.REASON_AUDIT_EVIDENCE, out


def test_the_gate_criteria_the_fixture_was_built_against_are_still_what_we_assume() -> None:
    """指纹：把本夹具赖以成立的那几个判据常量钉住。

    为什么值得一条独占的用例：本批修的是夹具，而夹具与判据是"前提—结论"的关系。
    判据一旦变严（例如 `NEGCTL_MIN_CHARS` 再往上抬、`MIN_DISTINCT_DIMENSIONS` 加一），
    这些夹具会一夜之间从"合规"变成"不合规"，而失败信息会是"正控没过" ——
    看起来像实现坏了，其实是夹具的前提不成立。这条用例把那个前提显式写下来：
    常量对不上时，红的是这一条，读的人立刻知道要修的是夹具而不是门。

    它不检查门的任何行为（那是别的用例的事），只检查前提。
    """
    assert G.MIN_INDEPENDENT_AUDITORS == 2
    assert G.MIN_DISTINCT_DIMENSIONS == 3
    assert G.NEGCTL_MIN_CHARS == 40
    # 夹具的负控与独立性声明必须过判据（这里直接问门，而不是自己数字符）
    assert G.negative_control_problem(NEGATIVE_CONTROL) == ""
    assert G._independence_problem(_independence("subagent-A")) == ""
    # `at` 必须可解析且不在未来
    assert G.audit_timestamp_problem(_AT) == ""
    # 夹具用到的 6 个维度必须在受控词表里
    assert set(DIMENSIONS) <= set(G.AUDIT_DIMENSIONS), set(DIMENSIONS) - set(G.AUDIT_DIMENSIONS)
    # 6 个观察面必须两两不同（`R5-R1b-1` 判据 1），否则正控的前提不成立
    assert len({G._observation_key(s) for s in SCOPES}) == len(SCOPES)


def test_the_evidence_files_are_real_files_with_matching_hashes() -> None:
    """夹具自检：每条审计的 `evidence_sha256` 必须与盘上那份证据文件真的对得上。

    这一条把"夹具自己有没有骗自己"变成一个可执行的判据：证据是落盘的文件，
    不是构造出来的一个字符串。`evaluate_approval` 会在判定时重算它 ——
    夹具若在这里就已经对不上，读侧用例测的就不是门，而是夹具的 bug。
    """
    for a in _six_clean_audits():
        p = pathlib.Path(a.evidence_path)
        assert p.is_file(), f"证据文件不在盘上：{p}"
        # 用与门无关的算法固化一份独立读数：读侧重算必须与之一致
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        assert actual == a.evidence_sha256, (p, actual, a.evidence_sha256)
        text = p.read_text(encoding="utf-8")
        assert a.auditor in text and a.scope in text and SHA[:12] in text, text
        assert "负控" in text

# -*- coding: utf-8 -*-
"""工作区目录与文件名的三级规范（A 系统固定 / B 系统生成名 / C 有限自由）。

## 这一层回答什么问题

业主口径（2026-11-25）：「你要看这些文件夹命名是不是系统定好的，还是随便起的，要钉住
一套规范，只允许少量自由发挥。」

盘上的实情是：绝大多数目录名与文件名是「代码常量」（`out/steps/` 由
`conductor.STEPS_DIR` 拼、`out/vsigns/<sha>.json` 由 `vsigns.SIGNS_DIR` 拼），另有一批是
「框架按 id / 6 位号 / sha / 日期生成」的（`out/exp-logs/<实验号>.log`、
`out/roster/<父>-retired.jsonl`），真正留给模型起名的只有几处（`code/` 下的 `.py`、
`notes/<角色>-<实例>.md`、`work/<角色>/*.md`、`code/formal/<声明名>.lean`）。三者混在
一起，读者没法从盘上看出来哪一个是系统定的、哪一个是随手起的 —— 于是同一个工作区里能
同时住着 `notes/A-A1.md`（实例草稿本）与 `notes/probe.md`（无主便签），而没有任何东西会响。

本模块把这三档写成一张表（``A_TOP_DIRS`` / ``OUT_DIRS`` / ``ROOT_FILES`` /
:func:`naming_of`），并让读侧按同一张表判。规范正文见 `docs/WORKSPACE-LAYOUT.md` ——
那一份讲为什么，这一份是它的执行体；两者不一致时判据会红
（`tests/test_workspace_layout_naming.py::test_c12_the_doc_names_every_fixed_dir`）。

## 三档与严重度（为什么不折平）

| 档 | 形式 | 违反时的严重度 | 读者看到什么 |
|---|---|---|---|
| 「A 系统固定」 | 目录名与文件名都是代码常量（`data/`、`out/clock/state.json`） | `error` | 这一格被改名了/被顶替了 —— 读侧按常量找它，找不到就当成「没有」 |
| 「B 系统生成名」 | 目录固定、名字由框架按 id/hash 生成（`out/vsigns/<sha>.json`） | `error` | 这份产物的名字不是框架会产出的形态 —— 它进不了按名字认领的那条链 |
| 「C 有限自由」 | 模型起名，但必须落指定目录、匹配模式、不新建层级（`code/exp/x.py`） | `error` | 这个自由档越界了 —— 要么越层，要么前缀/后缀/字符集不对 |
| 「未知条目」 | 不在这张表里的顶层目录 / 顶层文件 / `out/` 子目录 | `warning` | 盘上多了一样系统不认识的东西 —— 可能不是缺陷，但它没有归属 |
| 「工具链缓存」 | `.miktex/`、`__pycache__/`、`.lake/` | `warning` | 某个外部工具把缓存落进了工作区 —— 不归框架管，但会跟着工作区一起被打包 |

`warning` 与 `error` 都翻三态（`driver._state_of`），所以「多了一个 `out/foo/`」与
「`REPORT.md` 被改名」在读数上分得开：前者是系统不认识的自由发挥，后者是系统固定的那一格
被动了。`legacy` 一档在这里只用于 `-vN` 后缀（`manuscriptfamily` 认它是历史名：读得通、
可列出、不可签）。

## 为什么只判名字、不判内容

内容归各产物自己的规则（`wellformed/ledger.py` 判行、`proofs.py` 判证明稿）。这一层只看
这一份叫什么、住在哪一层；两轴分开，红的时候才能一眼看出是哪一轴坏了。所以它对
`library/` 的内部命名只判结构（`<6位号>/<名>` 或扁平一段），名字本身归
`wellformed/literature.py`（LIB-LAYOUT 路）；`reference/`、`source/`、`downloads/` 的
文件名是用户或下载器给的，这里一个字节都不判。

## 它与写侧的关系

没有关系，而且这是刻意的：本模块不拦写入（写侧的落点闸在 `tools/fs_tools.py` 的保留
表里）。它只回答盘上现在的名字合不合规范。发现写侧自由过头的地方（例如某处文件名由模型
任意拼），处置是收窄那一处的写口，不是在这里加一道闸 —— 先看得见，再决定收不收。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .. import schema as S
from .predicates import _Unchecked, _rel
from .registry import _Ctx, _rule
from .states import Finding

#: 这一类在 `states.KINDS` 里的名字（CLI 用 `--kind workspace_layout`）。
KIND = "workspace_layout"

# ---------------------------------------------------------------- 三档词表（唯一真身）

#: A 类：工作区根上的固定目录（系统自己建、系统自己读）。
#:
#: 这张表是 `store._WORKSPACE_ROOT_ENTRIES` 的「超集」：后者只是 `init()` 的外来条目守卫，
#: 它没列 `sessions/` / `out/` / `code/` / `notes/` / `verifications/` / `doc-signatures/` /
#: `index/` / `source/` / `downloads/`（那些目录是工作区跑起来之后才出现的，`init` 那一刻
#: 还没有）。两处不能互相顶替：守卫要少拦正常部署，本表要多认系统落点。漂移由
#: `tests/test_workspace_layout_naming.py` 的 `test_the_root_table_covers_the_init_whitelist`
#: 钉住（白名单里的每一项都必须在这里）。
A_TOP_DIRS: tuple[str, ...] = (
    "data",            # 台账表（store.py:868）
    "sessions",        # 会话事件流（sessionnames.py:28）
    "runs",            # 每趟记录 / 缓存档位 / 停历史（cacheface.py:222 等）
    "library",         # 已登记书架（schema.LIT_PATH_PREFIX）
    "manuscripts",     # 正文手稿（manuscriptfamily.MANUSCRIPT_ROOT）
    "work",            # 草稿区与交接账本（layout.WORK_DIR）
    "notes",           # 草稿本（agent_loop.NOTES_DIR_NAME）
    "code",            # 脚本与 Lean 源码（agent_skills 的产出面）
    "out",             # 框架产物区（各子系统见 OUT_DIRS）
    "reference",       # 用户投放的可靠参考文献（seedinject.SEED_REL）
    "source",          # 用户给的论文源（agent_b.run_once.MANUSCRIPT_RELS 的 source/main.tex）
    "downloads",       # 下载中间态（search_tools 的 workspace / downloads）
    "verifications",   # V 的复核台账（v_vocab.VERIFICATIONS_DIR）
    "doc-signatures",  # H 的文档签名快照（signatures.EVIDENCE_DIR）
    "index",           # 派生索引（sessions.RUN_INDEX_NAME）
    "projects",        # 多项目根布局（projects.projects_dir）
)

#: A 类：工作区根上的固定文件（一份一个常量）。
ROOT_FILES: tuple[str, ...] = (
    "ARTIFACTS.jsonl",           # artifacts.LEDGER_NAME
    "DOC-SIGNATURES.jsonl",      # signatures.LEDGER_NAME
    "RELIABLE-REFERENCES.json",  # locallib.DECLARATION_NAME / seedinject.DECLARATION_NAME
    "budget.json",               # budget.REGISTER_NAME
    "web-actions.jsonl",         # webui.audit.LEDGER_NAME
    "AGENT-PROFILES.md",         # agent_prompts.PROFILES_FILE
    ".agentflow-workspace",      # projects.classify 的工作区标记
    ".agentflow-stop",           # stopctl 的停止信号
)

#: A 类：`out/` 下的固定子系统目录（每一个都有唯一的拼点）。
OUT_DIRS: tuple[str, ...] = (
    "clock",        # clockbase / clockwaitany
    "exp-logs",     # agent_e.run_experiment:521
    "experiments",  # exhaustionreport.REPORT_DIR
    "invalid",      # agent_loop:1112
    "package",      # papercompile.package_dir
    "report",       # review_tools.DEFAULT_REPORT_SUBDIR / cli.DEFAULT_REPORT_REL
    "roster",       # secretary_ledger.ROSTER_DIR
    "secretary",    # secretary_ledger.SECRETARY_DIR
    "steps",        # conductor.STEPS_DIR
    "surfaces",     # secretary_ledger.SURFACES_DIR
    "sysguard",     # sysguard.LEDGER_DIR
    "tasks",        # conductor:10449
    "texts",        # tools.text_tools:437
    "vsigns",       # vsigns.SIGNS_DIR
)

#: 已退役的旧布局目录（`reports/` / `documents/`）：本层不判。
#:
#: 它们的判词在 `wellformed/layout.py`（业主 2026-11-22 裁定：旧工作区不必兼容 ⇒ 报
#: `error`）。本层再报一次会把「旧布局」读成两条读数，也会让 `layout` 那一类的读数被
#: 另一类的 warning 顶掉 —— 同一件事只能有一个判据，所以这里只认"这是已知的历史目录"。
RETIRED_TOP_DIRS: tuple[str, ...] = ("reports", "documents")

#: 工具链缓存目录：外部程序落进来的，不归框架管，但跟着工作区一起被打包。
#: 判 `warning` 而不是 `error`：它不是名字起错了，是别人的缓存落在这里了。
CACHE_NAMES: tuple[str, ...] = (".miktex", "__pycache__", ".lake")

#: A 类：`out/clock/` 下的固定文件（五个拼点各一个）。
CLOCK_FILES: tuple[str, ...] = (
    "state.json",      # clockbase.STATE_REL
    "wake.json",       # clockbase.WAKE_REL
    "waits.json",      # clockbase.WAITS_REL
    "wait_any.json",   # clockwaitany.WAIT_ANY_REL
    "handoffs.json",   # clockwaitany.HANDOFF_REL
)

#: A 类：`out/report/` 下的固定文件名。
REPORT_FILES: tuple[str, ...] = (
    "REPORT.md",          # cli.DEFAULT_REPORT_REL
    "NO-GATE.json",       # agent_loop.NO_GATE_DECLARATION_NAME
    "REPORT-STYLE.json",  # closing.REPORT_STYLE_NAME
    "m-verdicts.jsonl",   # closing.M_VERDICT_FILE
)

#: A 类：`out/package/` 下的固定文件名（论文包的七份）。
PACKAGE_FILES: tuple[str, ...] = (
    "main.tex",                 # papercompile.TEX_NAME
    "main.pdf",                 # papercompile.PDF_NAME
    "mapping-appendix.tex",     # papermapping.render_appendix
    "MAPPING.json",             # papermapping.MAPPING_JSON_NAME
    "MAPPING.md",               # papermapping.MAPPING_MD_NAME
    "ACCEPTANCE-TARGETS.json",  # closing.ACCEPTANCE_TARGETS_NAME
    "COMPILE-RECEIPT.json",     # papercompile.RECEIPT_NAME
)

#: A 类：`out/secretary/` 下的固定台账（不是按角色/实例分片的那一批）。
SECRETARY_LEDGERS: tuple[str, ...] = (
    "relay.jsonl",                 # secretary_ledger.RELAY_LEDGER
    "nontriviality.jsonl",         # secretary_ledger.NONTRIVIALITY_LEDGER
    "proposition_form.jsonl",      # secretary_ledger.PROPOSITION_FORM_LEDGER
    "proposition_verdicts.jsonl",  # secretary_ledger.PROPOSITION_VERDICT_LEDGER
    "statement_same.jsonl",        # secretary_ledger.STATEMENT_SAME_LEDGER
    "dispatch_fit.jsonl",          # secretary_ledger.DISPATCH_FIT_LEDGER
    "refusals.jsonl",              # refusals.REFUSAL_LEDGER_NAME
)

#: A 类：`data/` 下的文件名（`schema.TABLES` 之外的那几个账本）。
#: 表自己的名字从 `schema.TABLES` 取，不在这里再抄一份。
DATA_LEDGERS: tuple[str, ...] = (
    "events.jsonl",                  # store.events_path
    "counters.json",                 # manuscriptids.COUNTERS_REL
    "lit_availability.jsonl",        # litavail.LEDGER_NAME
    "lit_reads.jsonl",               # litavail.READ_LEDGER_NAME
    "lit_readbacks.jsonl",           # litstage.READBACK_LEDGER_NAME
    "lit_url_origins.jsonl",         # search_tools._URL_ORIGIN_LEDGER_NAME
    "research_request_ledger.json",  # verify.py:1469
)

#: 角色名（`schema.ROLES` + 主控）：`manuscripts/<角色>/`、`work/<角色>/` 的第二段只认它们。
ROLE_NAMES: tuple[str, ...] = tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)

#: B 类：每个角色在 `manuscripts/<角色>/` 下会产出的文件名形态。
#:
#: 为什么逐角色列而不是一条通用正则：四族的号来源不同（B/F/E 是手稿号、D 是问题号、
#: G 是文档号），而 `manuscriptfamily.relpath` 已经按族拼名 —— 这里的是它的读侧镜像，
#: 漂移由 `test_the_manuscript_patterns_follow_the_primary_source` 钉住。
MANUSCRIPT_PATTERNS: dict[str, re.Pattern[str]] = {
    "B": re.compile(r"^b-proof-\d{4,6}\.md$"),
    "F": re.compile(r"^f-proof-\d{4,6}\.md$"),
    "E": re.compile(r"^e-proof-\d{4,6}\.md$"),
    "D": re.compile(r"^(RESEARCH|\d{4,6}-research)\.md$"),
    "G": re.compile(r"^\d{4,6}\.md$"),
}

#: `manuscriptfamily` 认作历史名的 `-vN` 后缀：读得通、可列出、不可签。
LEGACY_SUFFIX_RE = re.compile(r"^[a-z]+-proof-\d{4,6}-v\d+\.md$")

#: 没有声明正文族的角色目录下，只认"手稿形"名字（`<族>-proof-<号>.md`）。
_GENERIC_PROOF_RE = re.compile(r"^[a-z]+-proof-\d{4,6}\.md$")

# ---------------------------------------------------------------- 单条形状

_RE_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_RE_SIX = re.compile(r"^\d{4,6}$")
_RE_OWNER = re.compile(r"^t-\d{6}$")
_RE_ROSTER_FILE = re.compile(r"^t-\d{6}(?:-(?:index|surfaces|retired))?\.jsonl$")
_RE_SLOT = re.compile(r"^S\d{2}$")
_RE_STATUS = re.compile(r"^STATUS-\d{8}-\d{4}\.(?:md|json)$")
_RE_REVIEW = re.compile(r"^\d{4,6}-review\.md$")
_RE_COMPILE_LOG = re.compile(r"^compile-\d{8}-\d{6}(?:\.stderr)?\.log$")
_RE_TEX_AUX = re.compile(r"^main\.(?:aux|log|out|toc|bbl|blg|fls|fdb_latexmk|synctex\.gz|pdf)$")
_RE_SIGN_SNAPSHOT = re.compile(r"^\d{4,6}-[0-9a-f]{16}-\d{3}\.json$")
_RE_VREVIEW = re.compile(r"^v-review-\d{6}\.md$")
_RE_INVALID = re.compile(r"^[A-Za-z0-9_.-]+-step\d+\.txt$")
_RE_SESSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.jsonl$")
_RE_RUN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.(?:json|jsonl)$")
_RE_EXP_LOG = re.compile(r"^\d{4,6}\.log$")
_RE_TASK_STEP = re.compile(r"^t-\d{6}\.jsonl$")
_RE_TASK_JSON = re.compile(r"^t-\d{6}\.json$")
_RE_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.txt$")
#: C 类：`work/<角色>/` 下的一层文件（草稿区，自由起名，只许 `.md`）。
_RE_WORK_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.md$")
#: C 类：`notes/<角色>[-<实例>].md` 的标签段（实例号由 identity 给）。
_RE_NOTE_INSTANCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
#: C 类：`code/` 下叶子名的形态（脚本 / Lean 源码 / Lean 逐步对照）。
#: 名字段刻意不限制 ASCII：自由档要真的自由（`code/exp/任意名.py` 合规范），只排除
#: 路径分隔符与 Windows 非法字符、并且不许以空白/点开头（免得造出隐藏文件）。
_RE_CODE_LEAF = re.compile(
    r"^[^\s./\\:*?\"<>|][^\r\n/\\:*?\"<>|]{0,118}\.(?:py|lean|steps\.jsonl)$")
_RE_CODE_DIR = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,39}$")

#: 一个工作区最多逐条列出多少条（`out/` 被塞满时读数不能被一份长数组拖死）。
SCAN_LIMIT = 200


@dataclass(frozen=True)
class Verdict:
    """一条工作区相对路径的命名判词（:func:`naming_of` 的返回值）。

    `level` 为空串 = 合规范（不出 Finding）。`code` 是 finding code，`why` 是逐字读数。
    """

    level: str = ""
    code: str = ""
    why: str = ""

    @property
    def clean(self) -> bool:
        """这一份合规范（不出 Finding）。"""
        return not self.level


OK = Verdict()


def _bad(code: str, why: str, level: str = "error") -> Verdict:
    """造一条不合规范的判词（默认 `error`：名字落进了系统固定的那一格）。"""
    return Verdict(level, code, why)


def _warn(code: str, why: str) -> Verdict:
    """造一条 `warning`（系统不认识，但不一定是缺陷）。"""
    return Verdict("warning", code, why)


# ---------------------------------------------------------------- 分类

def _parts(rel: Any) -> list[str]:
    """相对路径 ⇒ 段列表（`/` 分隔、抹掉空段与 `.`；不做 `projects/<p>/` 前缀剥离）。"""
    return [p for p in str(rel or "").replace("\\", "/").split("/") if p not in ("", ".")]


def _role_of(segment: str) -> str:
    """这一段是不是角色名（大小写不敏感）⇒ 规范写法；不是 ⇒ 空串。"""
    low = str(segment or "").strip().casefold()
    if not low:
        return ""
    for name in ROLE_NAMES:
        if low == name.casefold():
            return name
    return ""


def _unknown_in(where: str, name: str, expected: str) -> Verdict:
    """固定目录里出现了不认识的条目：`error`（那一格只认常量或框架会产出的形态）。"""
    return _bad("naming_unknown_name",
                f"`{where}` 里只认 {expected}，读到 `{name}` ⇒ 这一份没有归属"
                f"（系统按固定的名字找它，找不到就当它不存在）")


def _too_deep(where: str, rel: str, allowed: int) -> Verdict:
    """C 类越层：自由档只许到给定的层级，再往下就是模型自己开了目录。"""
    return _bad("naming_c_too_deep",
                f"`{rel}` 比允许的层级多（`{where}` 下只许 {allowed} 层）⇒ 自由发挥不许新建"
                f"目录层级；要放多份就摊在同一层，用名字区分")


# ---------------------------------------------------------------- 各区的判词

def _judge_out(parts: list[str], is_dir: bool) -> Verdict:
    """`out/` 下每一个子系统各一档（见 `OUT_DIRS`）。"""
    if len(parts) == 1:
        return Verdict() if is_dir else _warn(
            "naming_stray_in_out",
            "`out/` 根上直接放文件 ⇒ `out/` 只装子系统目录（`out/<子系统>/`），"
            "文件要落到某一个子系统里")
    sub = parts[1]
    if sub not in OUT_DIRS:
        if len(parts) > 2:
            # 未知子目录里面的东西不归本规范判：一条 warning 点到那个目录为止，逐份再报
            # 会把「多了一个目录」读成「多了几十条畸形」。
            return Verdict()
        return _warn("naming_unknown_out_dir",
                     f"`out/{sub}` 不是本框架的子系统（`out/` 下只认 "
                     f"{', '.join(OUT_DIRS)}）⇒ 系统不认识它，读侧不会去那里找东西")
    rest = parts[2:]
    if not rest:
        return Verdict()
    name = rest[0]
    if sub == "clock":
        if len(rest) == 1 and name in CLOCK_FILES:
            return Verdict()
        return _unknown_in("out/clock", name, "、".join(f"`{n}`" for n in CLOCK_FILES))
    if sub == "exp-logs":
        if len(rest) == 1 and _RE_EXP_LOG.fullmatch(name):
            return Verdict()
        return _unknown_in("out/exp-logs", name, "`<实验号>.log`（4-6 位十进制）")
    if sub == "experiments":
        if len(rest) == 2 and _RE_SIX.fullmatch(name) and rest[1] == "exhaustion.md":
            return Verdict()
        return _unknown_in("out/experiments", "/".join(rest), "`<实验号>/exhaustion.md`")
    if sub == "invalid":
        if len(rest) == 1 and _RE_INVALID.fullmatch(name):
            return Verdict()
        return _unknown_in("out/invalid", name, "`<会话号>-<角色>-step<N>.txt`")
    if sub == "package":
        if len(rest) != 1:
            return _too_deep("out/package", f"out/package/{'/'.join(rest)}", 1)
        if name in PACKAGE_FILES or _RE_COMPILE_LOG.fullmatch(name) \
                or _RE_TEX_AUX.fullmatch(name):
            return Verdict()
        return _unknown_in("out/package", name,
                           "、".join(f"`{n}`" for n in PACKAGE_FILES)
                           + "、`compile-<时间戳>.log`、`main.<引擎后缀>`")
    if sub == "report":
        if len(rest) != 1:
            return _too_deep("out/report", f"out/report/{'/'.join(rest)}", 1)
        if name in REPORT_FILES or _RE_STATUS.fullmatch(name) or _RE_REVIEW.fullmatch(name):
            return Verdict()
        return _unknown_in("out/report", name,
                           "、".join(f"`{n}`" for n in REPORT_FILES)
                           + "、`STATUS-<时间戳>.{md,json}`、`<文档号>-review.md`"
                           "（把 `REPORT.md` 改个名，落到的就是这一条）")
    if sub == "roster":
        if len(rest) == 1 and _RE_ROSTER_FILE.fullmatch(name):
            return Verdict()
        if len(rest) == 1 and is_dir and name == "refusals":
            return Verdict()
        if len(rest) == 2 and name == "refusals":
            if rest[1].endswith(".jsonl") and _RE_OWNER.fullmatch(rest[1][:-6]):
                return Verdict()
            return _unknown_in("out/roster/refusals", rest[1], "`<父>.jsonl`")
        return _unknown_in("out/roster", "/".join(rest),
                           "`<父>.jsonl` / `<父>-index.jsonl` / `<父>-surfaces.jsonl` / "
                           "`<父>-retired.jsonl`（父 = `t-<6位>`）与 `refusals/<父>.jsonl`")
    if sub == "secretary":
        if len(rest) != 1:
            return _too_deep("out/secretary", f"out/secretary/{'/'.join(rest)}", 1)
        if name in SECRETARY_LEDGERS:
            return Verdict()
        stem = name[:-6] if name.endswith(".jsonl") else ""
        role = _role_of(stem.split("-", 1)[0]) if stem else ""
        if role and (stem == role or re.fullmatch(rf"{role}-t-\d{{6}}", stem)):
            return Verdict()
        return _unknown_in("out/secretary", name,
                           "、".join(f"`{n}`" for n in SECRETARY_LEDGERS)
                           + "、`<角色>.jsonl`、`<角色>-t-<6位>.jsonl`")
    if sub == "steps":
        if len(rest) == 1 and _RE_TASK_STEP.fullmatch(name):
            return Verdict()
        return _unknown_in("out/steps", name, "`<台账号>.jsonl`（`t-<6位>`）")
    if sub == "tasks":
        if len(rest) == 1 and _RE_TASK_JSON.fullmatch(name):
            return Verdict()
        return _unknown_in("out/tasks", name, "`<台账号>.json`（`t-<6位>`）")
    if sub == "texts":
        if len(rest) == 1 and _RE_TEXT.fullmatch(name):
            return Verdict()
        return _unknown_in("out/texts", name,
                           "`<名>.txt`（`cand-<槽位>.txt` 是候选期那一档）")
    if sub == "vsigns":
        if len(rest) == 1 and (name == "issued.json"
                               or (name.endswith(".json") and _RE_SHA64.fullmatch(name[:-5]))):
            return Verdict()
        return _unknown_in("out/vsigns", name,
                           "`issued.json`、`<正文 sha>.json`（64 位小写 hex）")
    if sub == "sysguard":
        if len(rest) == 1 and name == "write-readings.jsonl":
            return Verdict()
        return _unknown_in("out/sysguard", name, "`write-readings.jsonl`")
    if sub == "surfaces":
        if len(rest) == 1:
            if _RE_OWNER.fullmatch(name) or (is_dir and name == "archive"):
                return Verdict()
            return _unknown_in(
                "out/surfaces", name, "`<父>`（`t-<6位>`）或 `archive/`")
        if name == "archive":
            return Verdict()
        if not _RE_OWNER.fullmatch(name):
            return _unknown_in("out/surfaces", name, "`<父>`（`t-<6位>`）")
        if len(rest) >= 2 and not _RE_SLOT.fullmatch(rest[1]):
            return _unknown_in(f"out/surfaces/{name}", rest[1], "`S<两位>`（池里发的槽位号）")
        return Verdict()
    return Verdict()  # pragma: no cover —— OUT_DIRS 已穷举


def _judge_manuscripts(parts: list[str], is_dir: bool) -> Verdict:
    """`manuscripts/<角色>/`：第二段必须是角色，文件名按族（B 类）。

    `manuscripts/handoffs.jsonl` 是「旧落点里的交接账本」：它还在 `manuscripts/` 里这件事
    由 `layout.py` 判（`CODE_HANDOFFS_LEDGER`，`error`）。本层只认"这是一个已知的历史
    名字"，不重复判 —— 同一件事两个判据会让同一份旧账本出两条读数。

    没有正文族的角色（A / C / H / L / M / V）下面出现 `<族>-proof-<号>.md` 时按通用形态
    放行：那是写侧该拒的（`fs_tools` 保留表），盘上的存量是历史产物；命名层只判
    "它像不像一份手稿"，不判"它该不该由这个角色写"。
    """
    if len(parts) == 1:
        return Verdict() if is_dir else _unknown_in("manuscripts", parts[0], "`<角色>/`")
    if len(parts) == 2 and parts[1] == "handoffs.jsonl":
        return Verdict()
    role = _role_of(parts[1])
    if not role:
        return _bad("naming_unknown_role_dir",
                    f"`manuscripts/{parts[1]}` 的第二段不是角色名 ⇒ `manuscripts/` 下只认 "
                    f"{'/'.join(ROLE_NAMES)} 这几档与 `handoffs.jsonl`")
    if len(parts) == 2:
        return Verdict() if is_dir else _unknown_in(
            f"manuscripts/{role}", parts[1], "`<族>-<号>.md`")
    if len(parts) > 3:
        return _too_deep(f"manuscripts/{role}",
                         f"manuscripts/{'/'.join(parts[1:])}", 1)
    name = parts[2]
    pattern = MANUSCRIPT_PATTERNS.get(role)
    if pattern is None:
        if LEGACY_SUFFIX_RE.fullmatch(name):
            return Verdict("legacy", "naming_legacy_suffix",
                           f"`{name}` 是历史名（`-vN` 后缀）⇒ 读得通、可列出，不可签、不可收录；"
                           f"新写产出的规范名不带 `-vN`")
        return Verdict() if _GENERIC_PROOF_RE.fullmatch(name) else _bad(
            "naming_c_bad_pattern",
            f"`manuscripts/{role}/{name}` 不像一份手稿（`<族>-proof-<号>.md`）⇒ "
            f"`manuscripts/<角色>/` 下只收手稿形文件名")
    if pattern.fullmatch(name):
        return Verdict()
    if LEGACY_SUFFIX_RE.fullmatch(name):
        return Verdict("legacy", "naming_legacy_suffix",
                       f"`{name}` 是历史名（`-vN` 后缀）⇒ 读得通、可列出，不可签、不可收录；"
                       f"新写产出的规范名不带 `-vN`")
    return _bad("naming_c_bad_pattern",
                f"`manuscripts/{role}/{name}` 不合 `{role}` 那一族的形态"
                f"（`{pattern.pattern}`）⇒ B 的收录与签的认领按族名找稿，这个名字到不了"
                f"那一步")


def _judge_work(parts: list[str], is_dir: bool) -> Verdict:
    """`work/`：`handoffs.jsonl` 是 A 类；`work/<角色>/` 下是 C 类（一层、`.md`）。"""
    if len(parts) == 1:
        return Verdict() if is_dir else _unknown_in(
            "work", parts[0], "`<角色>/` 或 `handoffs.jsonl`")
    if parts[1] == "handoffs.jsonl":
        return Verdict() if len(parts) == 2 else _bad(
            "naming_c_too_deep",
            f"`work/handoffs.jsonl` 是文件，下面不该有 `{'/'.join(parts[2:])}`")
    role = _role_of(parts[1])
    if not role:
        return _bad("naming_unknown_role_dir",
                    f"`work/{parts[1]}` 的第二段不是角色名 ⇒ `work/` 下只认 "
                    f"{'/'.join(ROLE_NAMES)} 与 `handoffs.jsonl`")
    if len(parts) == 2:
        return Verdict() if is_dir else _unknown_in(f"work/{role}", parts[1], "`<角色>/`")
    if len(parts) > 3:
        return _too_deep(f"work/{role}", f"work/{'/'.join(parts[1:])}", 1)
    if is_dir:
        # 目录：`work/<角色>/` 下面不许再开一层（草稿摊平放）。
        return _too_deep(f"work/{role}", f"work/{'/'.join(parts[1:])}", 1)
    name = parts[2]
    if _RE_WORK_FILE.fullmatch(name):
        return Verdict()
    return _bad("naming_c_bad_pattern",
                f"`work/{role}/{name}` 不合草稿区的形态（一层、`.md`、名字只用 "
                f"`A-Za-z0-9._-`、≤120 字）⇒ 草稿区只收草稿，别的东西各有各的落点")


def _judge_notes(parts: list[str], is_dir: bool) -> Verdict:
    """`notes/<角色>[-<实例>].md`：C 类里最窄的一档（前缀是角色，标签是实例）。"""
    if len(parts) == 1:
        return Verdict() if is_dir else _unknown_in(
            "notes", parts[0], "`<角色>[-<实例>].md`")
    if len(parts) > 2:
        return _too_deep("notes", f"notes/{'/'.join(parts[1:])}", 1)
    name = parts[1]
    if not name.endswith(".md"):
        return _bad("naming_c_bad_pattern",
                    f"`notes/{name}` 不是 `.md` ⇒ 草稿本只收 markdown"
                    f"（`notes/<角色>[-<实例>].md`）")
    stem = name[:-3]
    head, _, tail = stem.partition("-")
    if not _role_of(head):
        return _bad("naming_c_bad_pattern",
                    f"`notes/{name}` 的名字不以角色开头 ⇒ 草稿本按角色分桶："
                    f"`notes/<角色>.md` 或 `notes/<角色>-<实例>.md`（角色是 "
                    f"{'/'.join(ROLE_NAMES)}）")
    if tail and not _RE_NOTE_INSTANCE.fullmatch(tail):
        return _bad("naming_c_bad_pattern",
                    f"`notes/{name}` 的实例标签 `{tail}` 不合形态（`A-Za-z0-9._-`，≤40 字）"
                    f"⇒ 实例标签由身份给，不是你随手起的题目")
    return Verdict()


def _judge_code(parts: list[str], is_dir: bool) -> Verdict:
    """`code/`：C 类里唯一允许一层子目录的那档（`code/<目录>/<名>.py`）。"""
    if len(parts) == 1:
        return Verdict() if is_dir else _bad(
            "naming_c_bad_pattern", "`code` 是目录，不该是一份文件")
    for seg in parts[1:-1]:
        if not _RE_CODE_DIR.fullmatch(seg):
            return _bad("naming_c_bad_pattern",
                        f"`code/{seg}` 这一段不合形态（`A-Za-z0-9._-`，≤40 字）⇒ "
                        f"脚本目录名只用小写短名（`exp` / `formal` 这类）")
    if len(parts) > 3:
        return _too_deep("code", f"code/{'/'.join(parts[1:])}", 2)
    if is_dir:
        return Verdict()
    name = parts[-1]
    if _RE_CODE_LEAF.fullmatch(name):
        return Verdict()
    return _bad("naming_c_bad_pattern",
                f"`code/{'/'.join(parts[1:])}` 的叶子名不合形态（`<名>.py` / `<名>.lean` / "
                f"`<名>.steps.jsonl`，名字只用 `A-Za-z0-9_.-`）⇒ 自由发挥只到起名为止")


def _judge_data(rest: list[str], is_dir: bool = False) -> Verdict:
    """`data/` 下的文件名只许是表名或已登记的账本（A 类里最硬的一档）。"""
    first = rest[0]
    if first == ".locks":
        return Verdict()
    if first == "archive":
        if len(rest) == 1 and is_dir:
            return Verdict()
        if len(rest) == 2 and is_dir and rest[1] == "lit_candidates":
            return Verdict()
        if len(rest) == 3 and rest[1] == "lit_candidates" \
                and re.fullmatch(r"archive-r-\d{4,6}\.jsonl", rest[2]):
            return Verdict()
        return _unknown_in("data/archive", "/".join(rest[1:]) or first,
                           "`lit_candidates/archive-<请求号>.jsonl`")
    if len(rest) != 1:
        return _too_deep("data", f"data/{'/'.join(rest)}", 1)
    if first in DATA_LEDGERS:
        return Verdict()
    if first.endswith(".json") and first[:-5] in S.TABLES:
        return Verdict()
    return _bad("naming_unknown_data_file",
                f"`data/{first}` 不是一张表也不是已登记的账本 ⇒ `data/` 只装 "
                f"`schema.TABLES` 里的表与 {', '.join(DATA_LEDGERS)}；"
                f"别的账要落各自子系统（`out/...` / `runs/` / `verifications/`）")


def _judge_flat(top: str, parts: list[str], is_dir: bool = False) -> Verdict:
    """`sessions/` `runs/` `library/` `verifications/` 等框架自有目录。"""
    rest = parts[1:]
    if not rest:
        return Verdict()
    if top == "sessions":
        if len(rest) == 1 and _RE_SESSION.fullmatch(rest[0]):
            return Verdict()
        return _unknown_in("sessions", "/".join(rest), "`<会话号>.jsonl`（一层）") \
            if len(rest) == 1 else _too_deep("sessions", f"sessions/{'/'.join(rest)}", 1)
    if top == "runs":
        if len(rest) == 1 and _RE_RUN.fullmatch(rest[0]):
            return Verdict()
        return _unknown_in("runs", "/".join(rest), "`<名>.json` / `<名>.jsonl`（一层）") \
            if len(rest) == 1 else _too_deep("runs", f"runs/{'/'.join(rest)}", 1)
    if top == "library":
        if len(rest) == 1:
            return Verdict()  # 扁平落点（历史形态；名字归 literature.py 判）
        if len(rest) == 2 and _RE_SIX.fullmatch(rest[0]):
            return Verdict()  # 规范形态 `<6位号>/<名>`（名字归 literature.py）
        return _bad("naming_unknown_name",
                    f"`library/{'/'.join(rest)}` 不合结构 ⇒ `library/` 只认 "
                    f"`<6位号>/<名>` 与扁平一段（名字本身归 wellformed/literature.py 判）")
    if top == "verifications":
        if len(rest) == 1:
            if is_dir and rest[0] in ("pending", "reviews"):
                return Verdict()
            return Verdict() if re.fullmatch(r"\d{4,6}\.jsonl", rest[0]) else _unknown_in(
                "verifications", rest[0], "`<命题号>.jsonl`")
        if len(rest) == 2 and rest[0] == "pending":
            if rest[1].endswith(".jsonl") and _RE_SHA64.fullmatch(rest[1][:-6]):
                return Verdict()
            return _unknown_in("verifications/pending", rest[1], "`<载体 sha>.jsonl`")
        if len(rest) == 2 and rest[0] == "reviews":
            if rest[1] == "index.jsonl" or _RE_VREVIEW.fullmatch(rest[1]):
                return Verdict()
            return _unknown_in("verifications/reviews", rest[1],
                               "`index.jsonl`、`v-review-<6位>.md`")
        return _too_deep("verifications", f"verifications/{'/'.join(rest)}", 2)
    if top == "doc-signatures":
        if len(rest) == 1 and _RE_SIGN_SNAPSHOT.fullmatch(rest[0]):
            return Verdict()
        return _unknown_in("doc-signatures", "/".join(rest),
                           "`<文档号>-<16位hash>-<序号>.json`")
    if top == "index":
        if len(rest) == 1 and rest[0] == "run-index.json":
            return Verdict()
        return _unknown_in("index", "/".join(rest), "`run-index.json`")
    if top in ("reference", "source", "downloads"):
        # 文件名是用户或下载器给的（投放处 / 中间态），本层不判；只判层级。
        return Verdict() if len(rest) <= 2 else _warn(
            "naming_too_deep",
            f"`{top}/{'/'.join(rest)}` 有 {len(rest)} 层 ⇒ `{top}/` 只当一层投放处用")
    if top == "projects":
        return Verdict() if len(rest) <= 2 else _warn(
            "naming_too_deep",
            f"`projects/{'/'.join(rest)}` 超过两层 ⇒ 多项目根只该有 `projects/<项目名>/`")
    return Verdict()


def naming_of(rel: Any, *, is_dir: bool = False) -> Verdict:
    """一份工作区相对路径的命名判词（唯一分类：文档、规则、判据都读它）。

    `is_dir` 只说这一条是目录还是文件 —— 同一段名字当目录合法、当文件不合法的地方
    （`out/clock` 是子系统目录，`notes/x` 是文件）要靠它分。
    """
    parts = _parts(rel)
    if not parts:
        return OK
    for seg in parts:
        if seg.casefold() in {name.casefold() for name in CACHE_NAMES}:
            return _warn("naming_cache_dir",
                         f"`{'/'.join(parts[:parts.index(seg) + 1])}/` 是工具链缓存"
                         f"（不是框架产物）⇒ 它跟着工作区一起被打包；不归本规范管，"
                         f"但读的人要知道它为什么在盘上")
    top = parts[0]
    if top in RETIRED_TOP_DIRS:
        # 旧布局（`reports/` / `documents/`）：判词归 `layout.py`，本层不重复判。
        return Verdict()
    if len(parts) == 1:
        low = top.casefold()
        if low in {name.casefold() for name in A_TOP_DIRS}:
            return Verdict() if is_dir else _bad(
                "naming_unknown_top_file",
                f"`{top}` 是框架的目录名，读到的是文件 ⇒ 目录被一份同名文件顶替了")
        if top in ROOT_FILES:
            return Verdict() if not is_dir else _bad(
                "naming_unknown_top_dir",
                f"`{top}` 是框架的固定文件，读到的是目录 ⇒ 那一格被顶替了")
        if is_dir:
            return _warn("naming_unknown_top_dir",
                         f"`{top}/` 不是本框架的顶层目录（只认 {', '.join(A_TOP_DIRS)}）⇒ "
                         f"系统不认识它，它也不在任何读侧的扫描面里")
        return _warn("naming_unknown_top_file",
                     f"`{top}` 不是本框架的顶层文件（只认 {', '.join(ROOT_FILES)}）⇒ "
                     f"一份没有归属的文件落在工作区根上")
    if top == "out":
        return _judge_out(parts, is_dir)
    if top == "manuscripts":
        return _judge_manuscripts(parts, is_dir)
    if top == "work":
        return _judge_work(parts, is_dir)
    if top == "notes":
        return _judge_notes(parts, is_dir)
    if top == "code":
        return _judge_code(parts, is_dir)
    if top == "data":
        return _judge_data(parts[1:], is_dir)
    if top in ("sessions", "runs", "library", "verifications", "doc-signatures",
               "index", "reference", "source", "downloads", "projects"):
        return _judge_flat(top, parts, is_dir)
    if len(parts) > 1:
        # 未知顶层目录里面的东西不归本规范判：warning 点到那个目录为止（上面 len==1 那一支）。
        return Verdict()
    return _warn("naming_unknown_top_dir",
                 f"`{top}/` 不是本框架的顶层目录 ⇒ 这一份不归本规范管，也不在任何扫描面里")


# ---------------------------------------------------------------- 扫一棵树

def _walk(root: Path) -> Iterator[tuple[str, bool]]:
    """逐条吐出 `(工作区相对路径, 是不是目录)`；缓存目录与 `projects/` 只报目录本身。

    为什么在 `__pycache__` 上剪枝而不是逐份报：一份 Python 缓存可以有几十个 `.pyc`，
    逐份报会把"某处漏了一个缓存"读成几十条畸形。剪枝之后一条 warning 就够 —— 读者要
    知道的是这里有个缓存，不是缓存里有几个文件。
    """
    stack: list[Path] = [root]
    while stack:
        base = stack.pop()
        try:
            entries = sorted(base.iterdir(), key=lambda p: p.name)
        except OSError as exc:
            raise _Unchecked(f"读不到 {base}（{type(exc).__name__}: {exc}）") from exc
        for path in entries:
            if path.name == ".git":
                continue
            rel = _rel(root, path)
            is_dir = path.is_dir()
            yield rel, is_dir
            if not is_dir:
                continue
            if path.name in CACHE_NAMES or rel == "projects":
                continue
            stack.append(path)


def _reported_ancestor(rel: str, code: str, reported: dict[str, str]) -> bool:
    """这一条的某一级祖先是不是已经用同一个 code 报过了（同一件事只报最浅的那一条）。"""
    parts = rel.split("/")
    for i in range(1, len(parts)):
        if reported.get("/".join(parts[:i])) == code:
            return True
    return False


@_rule(KIND, "names")
def _rule_names(ctx: _Ctx) -> list[Finding]:
    """整棵树逐份判名字：A 类被改名 ⇒ `error`；未知顶层 / `out/` 子目录 ⇒ `warning`。

    规则自己摊开清单（`driver._check_tree`）：命名是整棵树的属性 —— 同一段名字在 `out/`
    下是子系统、在根上是自由发挥，单份文件判不出它住在哪一层。
    """
    root = ctx.root
    if root is None:
        raise _Unchecked("没有工作区根 ⇒ 判不了目录与文件名")
    findings: list[Finding] = []
    #: 已经报过的 `路径 -> code`：同一支里"越层"只报最浅的那一条。`work/A/sub` 已经报了
    #: `naming_c_too_deep` 之后，`work/A/sub/x.md` 再报一次只是同一件事的第二个读数。
    reported: dict[str, str] = {}
    dropped = 0
    for rel, is_dir in _walk(root):
        got = naming_of(rel, is_dir=is_dir)
        if got.clean:
            continue
        if _reported_ancestor(rel, got.code, reported):
            continue
        if len(findings) >= SCAN_LIMIT:
            dropped += 1
            continue
        reported[rel] = got.code
        findings.append(Finding(kind=ctx.kind, where=rel, detail=got.why,
                                severity=got.level, code=got.code))
    if dropped:
        ctx.notes.append(
            f"另有 {dropped} 条同档读数没逐条列出（上限 {SCAN_LIMIT}，见 "
            f"`naming.SCAN_LIMIT`）⇒ 这不是「只有这么多」")
    # 顺带读数（不改三态）：整棵树各档各多少条。第二次走盘只为这一句 —— 它让读数面上
    # "查过多少条"与逐条 finding 同源，而不是另算一份。
    counts = _counts_of(root)
    ctx.notes.append(
        f"逐条判了 {sum(counts.values())} 条：ok={counts['ok']} / "
        f"warning={counts['warning']} / error={counts['error']} / "
        f"legacy={counts['legacy']}（同一份分类 `naming_of`）")
    return findings


def _counts_of(root: Path) -> dict[str, int]:
    """只读计数：合规范 / `warning` / `error` / `legacy` 各多少条（规则与探针共用）。

    读不到目录 ⇒ 抛 `_Unchecked`（调用方按没查成处理，不许折成零）。
    """
    counts = {"ok": 0, "warning": 0, "error": 0, "legacy": 0}
    for rel, is_dir in _walk(root):
        got = naming_of(rel, is_dir=is_dir)
        counts[got.level or "ok"] = counts.get(got.level or "ok", 0) + 1
    return counts

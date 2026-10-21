#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""FC-27 禁 AI 区门禁 —— 机器可执行的检查器。

它检查什么：`.noai-paths` 是一份 glob 清单（FC-27 的"机器可读禁改区清单"）。本模块：:func:`load_manifest` —— 解析 `.noai-paths` ⇒ `list[Rule]`。2.
:func:`parse_agents_block` —— 解析 `AGENTS.md` 里 `<!-- NOAI-MANIFEST:BEGIN -->`…
`<!-- NOAI-MANIFEST:END -->` 之间的同一份清单。3. :func:`check_manifest_consistency` —— 两处逐条比对，返回差异列表（空 = 一致）。这是 FC-27 判据(1)
"两处落地、逐条一致"（符合 FC-03）的实现。4. :func:`check_paths` —— 判定一批改动路径是否命中禁改区，给出`verdict` + `required_approvals`。5. :
func:`check_approvals` —— 在命中之后用 hash 台账（`.noai-approvals.json`）判定"被批准的版本"是不是"盘上这一版"。hash 钉住的批准台账（为什么没有 git 也能查）：本仓库
`D:\\Incubator\\agentflow` 不是 git 仓库，所以 `--git` 永远 `unknown`。但"这次改了哪些文件"并不是唯一的可用判据 —— 内容 hash 就是版本：台账里每条记录一个仓库相对路径 +
该文件当前内容的 sha256+ 变更摘要（谁写的、改了什么）+ 已完成的人工逐行走查记录（`reviewers`）；- 命中禁改区后，逐条比对"台账里的 sha256"与"磁盘上的 sha256"：不一致 ⇒ `stale`，
含义是被批准的那一版与现在这一版不是同一版；- 这比 `git diff` 更强：git 只知道"文件变了"，抓不到"批准之后又被悄悄改了"。台账记的是被批准的那一版的内容，所以批准后任何一次改动都会让它重新变成未批准。
两条不许越过的线：登记 ≠ 批准。 `--baseline` 只写 hash / glob / category，`reviewers` 永远是空数组；只有人跑 `--approve` 才写走查记录。- 台账不能批准自己。
若命中集里出现台账文件本身，永远判 `unapproved`（理由码 `ledger_self_approval`）—— 它堵的是"AI 把自己的改动写进台账并声称已批准"。台账读不到 / 不是合法 JSON / 结构不合规 ⇒
`unknown`(2)，不是 `clean`：三态纪律在台账上同样成立 —— "没查成"与"查过了没问题"是两件事。三态纪律（本模块最重要的一条）：`check_paths` 有三个结论，不是一个布尔：``clean``
—— 查过了，没有命中 ⇒ 批准数 0。- ``requires_human`` —— 查过了，命中 ⇒ 批准数 2（FC-27 的 =2）。- ``unknown``        —— 没查成（清单不在 / 清单解析失败 /
`--git` 但不在 git 仓库）⇒ 批准数 0，但绝不能读成"没问题"。`unknown` 与 `clean` 的合并是本领域被反复证明最危险的静默兜底："没检查"被读成"检查过了没问题"。所以
``unknown`` 单独占一个退出码（2）。退出码（`17-正式文稿体例（参考投影度量论）.md:675-676, 681`）："多数脚本不设退出码，只打印"；"'未报错'曾被误读为'无问题'"（假阴性）。教训很直接：
门必须返回退出码，否则 CI 里"没报错"就等于"通过"。``clean``          ⇒ 0- ``requires_human`` ⇒ 1- ``unknown``        ⇒ 2
"""

from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

# --------------------------------------------------------------------------- FC-27 的七类

#: FC-27 判据(3)：把"认证/授权/支付/加密/迁移/CI 配置/对外 API 破坏性变更"七类
#: 平移到本领域（面向数学研究的多智能体协同框架）后的完整类别清单。
#:
#: 这里是单一来源：`.noai-paths` 的分组头、`AGENTS.md` 的清单、测试里的
#: "七类齐全"断言都指向它，不各写一份（FC-03）。
CATEGORY_TITLES: dict[str, str] = {
    "solver-core": "一、数值求解器的核心算法（检索/抽取/判重的算法主通道）",
    "prover-bridge": "二、证明检查器的桥接层（与外部检查器交互的部分）",
    "provenance-dedup": "三、来源解析与去重键（同一篇文献必须只有一个键）",
    "schema-migration": "四、schema 迁移（存储布局与 ID 分配）",
    "eval-criteria": "五、评测口径的定义（一个数字是什么，由口径决定）",
    "release-deploy": "六、发布与部署脚本（发出去就收不回来）",
    "auth-audit": "七、权限与审计（谁能做什么，以及谁做过了什么）",
}

#: 类别的规范顺序（不是集合 —— 顺序本身携带信息：与 FC-27 判据(3)的列举同序，FC-05）。
CATEGORY_ORDER: tuple[str, ...] = tuple(CATEGORY_TITLES)

#: 命中禁改区后额外要求的 reviewer 批准数。FC-27 写死为 2，不是可配置项：
#: 可配置的准入门槛等于没有门槛（下一个人会把它改成 0）。
REQUIRED_APPROVALS_ON_HIT = 2

#: 与"2 名人审"并行的第二条通路（口径变更，2026-09-26 由所有者批准）：
#: 多个子代理 × 多个维度独立审计、全部未发现问题 ⇒ 视为通过。
#:
#: 为什么仍然要求"多个"与"多维度"：
#:   - 1 个审计者与"作者自己再看一遍"在结构上无法区分（与"为什么人审要 2 名"同一条理由）；
#:   - 单一维度的"没发现问题"只证明这个维度看不见问题 —— 而缺陷恰恰长在
#:     没人看的那个维度上（本项目 75 条登记里有大量实例）。
MIN_INDEPENDENT_AUDITORS = 2
MIN_DISTINCT_DIMENSIONS = 3

#: 审计维度的受控词表。"多维度"必须是可数的，否则与"多看两眼"不可区分。
AUDIT_DIMENSIONS: tuple[str, ...] = (
    "axes",            # 两根轴（effect × external）与只读角色权限面
    "roles",           # 角色装配、for_role 过滤面、调用期角色强制
    "errors",          # 异常类型是否落在受控类型上、三态位是否可分
    "contract",        # 返回值键集合与声明字符串是否逐字一致
    "schema",          # 磁盘格式、表结构、ID 分配与迁移
    "concurrency",     # 加锁顺序、并发写、原子落盘
    "eval",            # 评测口径字段与比率口径
    "dedupe",          # 来源归一化与判重键
    "release",         # 发布门强度、门产物是否改仓库、退出码三态
    "audit-ledger",    # 台账与禁改区清单自身（含"不能批准自己"）
    "docs",            # 声明（docstring/文档）与实现是否一致
    "tests",           # 判据是否可能失败（负控/真空真）
)

REASON_FEW_AUDITS = "insufficient_clean_audits"

MANIFEST_NAME = ".noai-paths"
AGENTS_NAME = "AGENTS.md"
BLOCK_BEGIN = "<!-- NOAI-MANIFEST:BEGIN -->"
BLOCK_END = "<!-- NOAI-MANIFEST:END -->"

#: hash 台账的文件名（它自己也在 `.noai-paths` 的 auth-audit 类里）。
LEDGER_NAME = ".noai-approvals.json"

#: 台账结构版本。不认识的版本一律判 `unknown`：版本号是"用哪套结构解读"的声明，
#: 不认识它就不能假装按老结构读得懂（那正是"没查成"被读成"没问题"的入口）。
LEDGER_VERSION = 1

#: 回执链的文件名。每写一次批准 / 一次审计就追加一行，每行带前一条的 hash。
#:
#: 为什么需要它（不是形式主义）：`temp/verify-audit-forge.txt` 那次复现证明
#: "谁能写 `.noai-approvals.json`，谁就能让门给清单自己报 clean"。给审计加证据锚之后，
#: 顺手编一句证据被挡住了（见 `temp/verify-audit-forge-after.txt` 的 ① ②），
#: 但最强者仍能过：编造者自己造一个证据文件、把它的 hash 写进台账即可（③）。
#: 单靠台账，这件事在文件层面无法与"真的审计过"区分 —— 台账是自证的。
#:
#: 回执链改变的是代价的形态：它是只增的，且每条记录把前一条的 hash 写进自己
#: 参与 hash 的内容里。于是"事后删掉一条"或"改一条再补上"都会让链在某处断开，
#: 而门每次判定都重算整条链。它仍然不是签名（能改台账的人也能重算整条链），
#: 但它把"悄悄改一条记录"变成了"必须重写整条链"—— 后者是可见的、需要解释的动作。
#:  本文件也因此必须登记进 `.noai-paths`（否则"改宽这条链"这件事本身不需要人审）。
AUDIT_RECEIPT_NAME = ".noai-audit-receipts.jsonl"

#: `authored` 的合法取值。第三个取值是刻意的：仓库里经常查不出
#: "这一段是谁写的"，此时不许猜 —— 猜成 `human` 会把 AI 的改动洗成人写的，
#: 猜成 `ai-agent` 会把人的署名抹掉。三态纪律的用法就是：判不了就说判不了。
AUTHORED_VALUES: tuple[str, ...] = ("human", "ai-agent", "unknown")

#: `authored` 的依据（受控二选一）。把"结论"与"依据"分开写，是因为二者强弱完全不同：
#:
#: - ``attested`` —— 有直接证据：改动者自己声明，或人签字时声明。
#:   这个取值无法被门机械验证：它依赖签名者诚实（与"`--approve` 拦不住一个
#:   不诚实的人"同族）。门能做的是强迫它被写下来，而不是证明它。
#: - ``inferred`` —— 从 mtime + 会话边界推断出来的（例如"这一轮的 mtime 落在
#:   本会话窗口内 ⇒ 本轮是 AI 在写"）。它是推断，不是独立证据。
#:
#: 所以读台账的人必须能一眼看出手里这条是哪种 —— `--check-approvals` 的输出里
#: `inferred` 的条目会显式带上"归属为推断，非独立证据"。
AUTHORED_BASIS_VALUES: tuple[str, ...] = ("attested", "inferred")

_VERDICT_EXIT_CODES = {"clean": 0, "requires_human": 1, "unknown": 2}

#: 台账条目的批准判定状态（与 `GateResult.verdict` 的三态不是同一层：
#: 这里说的是单条路径，`verdict` 说的是整批）。
APPROVAL_STATUSES: tuple[str, ...] = ("approved", "unapproved", "unknown")

#: `approval_reason` 的理由码。`unregistered` 与 `stale` 必须分开：
#: 前者是"从没登记过"，后者是"登记过、但批准的那一版不是现在这一版"。
#: 把两者折叠成一个"未批准"，人就分不清该跑 `--baseline` 还是该重新走查。
REASON_SELF = "ledger_self_approval"
REASON_UNREGISTERED = "unregistered"
REASON_STALE = "stale"
REASON_FEW_REVIEWERS = "insufficient_reviewers"
REASON_APPROVED = "approved"
REASON_HASH_UNAVAILABLE = "hash_unavailable"
#: 人审记录带了证据锚、但锚核对不过（`FINAL-R1d-04`）：文件不在盘上或内容变了。
#: 与 `insufficient_reviewers` 分开：前者要"先弄清那份走查记录还在不在"，
#: 后者要"再找人走查一次"。折成一个码会让人做错处置。
REASON_REVIEW_ANCHOR = "reviewer_evidence_anchor_unverifiable"
#: 警告：这里曾有 `REASON_STRUCTURE = "ledger_structure"` —— 已删（`R1-3`）。
#: 它是个死常量：全仓库没有任何一处赋值点（台账结构性错误是整体 `unknown`，
#: 见 `check_approvals` 里 `load_ledger` 抛 `LedgerError` 那一支：那时连逐条
#: `approvals` 都构造不出来，没有一个"这一条的理由码"可以承载它）。
#: 留着它的代价不是"多了四行"，而是读代码的人会以为门会报这个码，
#: 进而在日志里找不到它时以为自己漏看了报表。要恢复它，先让那一支真的发得出这个码。
#: 机审通路的证据锚核对不上（文件读不到 / hash 与登记值不一致）⇒ unknown。
#: 与 `insufficient_reviewers` 分开是刻意的：那一条是"查过了、没批准"，
#: 这一条是"没查成"（证据在不在都还没弄明白）。
REASON_AUDIT_EVIDENCE = "audit_evidence_unverifiable"
#: 机审通路的回执链这一层没通过（链缺失 / 断链 / 没有这一版的记录）⇒ unknown。
#: 同样与"未批准"分开：链不可信时，连"这份台账值不值得读"都还没结论。
REASON_AUDIT_RECEIPT = "audit_receipt_chain_unverifiable"
#: `R5-R1b-1`：维度数够了，但那些维度不是各自独立的观察面 —— 同一份观察复制 N 份、
#: 每份换一个 `dimension` 字符串就能凑出 3 个"维度"。这一条与 `REASON_FEW_AUDITS`
#: 分开：那一条是"条数不够"，这一条是"条数够了、但它们其实是同一双眼睛看的"。
REASON_DIMENSION_SURFACE = "insufficient_independent_dimensions"
#: `R5-R1b-7`：`at` 读不出 ISO-8601 时间戳，或落在未来 ⇒ 没查成（时间戳不可信时，
#: "这一次走查/审计发生在什么时候"就没有可判定的答案）。
REASON_AUDIT_TIMESTAMP = "audit_timestamp_unverifiable"
#: `R6-R1d-3`：每条 `at` 都合格，但整串倒挂（后写的早于先写的）⇒ 不放行。
#: 与 `REASON_AUDIT_TIMESTAMP`（单条读不出/来自未来）分开是刻意的：两者的处置不同 ——
#: 那一条要修时间戳本身，这一条要弄清楚这几条审计的真实先后（必要时重跑并重记）。
REASON_AUDIT_TIMESTAMPS_ORDER = "audit_timestamps_not_monotonic"

#: 清单与台账对账（`H-11`）差集的两个类别。分开是刻意的，两者的处置完全不同：
#: ``pre_registered`` 是清单开头那句"先登记路径"纪律的落地形态（文件还没建），
#: 它今天是一条正常状态；``missing_registration`` 是"清单里写着、盘上也有、
#: 台账里却没有条目" —— 那意味着这条禁改区条目一次都没有被登记过，
#: 于是"改它要 2 名 reviewer"这句话在台账这一层找不到可比的版本。
#:
#: 把两者折叠成一个"差集非空"会让今天这条可解释的差集常驻报红，
#: 而一条永远红的门与一条永远绿的门一样没有信息量。
RECON_PRE_REGISTERED = "pre_registered"
RECON_MISSING_REGISTRATION = "missing_registration"


class NoaiError(Exception):
    """清单相关的错误。``line_no`` 为 1 起算的行号（无行号时为 None）。

    为什么异常里要带行号：清单解析失败时，人必须能直接跳到那一行。
    "解析失败"而不说在哪一行，等于把排查成本转嫁给下一个读到这条日志的人。
    """

    def __init__(self, message: str, line_no: int | None = None) -> None:
        self.line_no = line_no
        super().__init__(message if line_no is None else f"第 {line_no} 行：{message}")


class LedgerError(Exception):
    """台账相关的错误：读不到 / 不是合法 JSON / 结构不合规 / 拒绝写入。

    它一律对应 `unknown`（"没查成"），不是"没问题"。 本模块里
    "拒绝写入"（例如 `--approve` 发现 hash 与磁盘不一致）也走这个类型：
    动作没做成，绝不能返回 0。
    """


@dataclass(frozen=True)
class Rule:
    """一条禁改区条目。字段名 `glob` 是 FC-27 判据(1)的用语（"glob 列表"）。"""

    glob: str
    reason: str
    category: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GateResult:
    """一次门禁判定的结果。``required_approvals`` 只在 ``requires_human`` 时为 2。

    ``approvals`` 是台账判定这一层的逐路径明细（`check_paths` 不用它，
    所以默认空列表）：每条含 `path` / `approval_status` / `approval_reason` / `detail`。
    它存在的理由：`clean` 也可能来自台账（命中但已批准），此时 `violations` 是空的，
    没有它就看不出"这个 clean 是靠什么判出来的"。
    """

    verdict: str
    violations: list[dict] = field(default_factory=list)
    required_approvals: int = 0
    explanation: str = ""
    manifest_issues: list[str] = field(default_factory=list)
    approvals: list[dict] = field(default_factory=list)
    ledger: str = ""

    @property
    def exit_code(self) -> int:
        return _VERDICT_EXIT_CODES[self.verdict]

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "violations": [dict(v) for v in self.violations],
            "required_approvals": self.required_approvals,
            "explanation": self.explanation,
            "manifest_issues": list(self.manifest_issues),
            "approvals": [dict(a) for a in self.approvals],
            "ledger": self.ledger,
            "exit_code": self.exit_code,
        }


# --------------------------------------------------------------------------- 定位仓库根


def _looks_like_root(path: Path) -> bool:
    return (path / MANIFEST_NAME).is_file() or (path / "pyproject.toml").is_file()


def project_root(start: Path | None = None) -> Path:
    """仓库根：从 `start`（默认本文件所在目录）向上找 `.noai-paths` / `pyproject.toml`。

    找不到就退回 `scripts/` 的父目录。不抛异常 —— 根目录猜错时，
    由 `load_manifest` 以"文件读不到"的形式显式失败（⇒ unknown），
    而不是在这里静默编一个路径出来。
    """
    here = (start or Path(__file__).resolve()).resolve()
    for cand in (here, *here.parents):
        if _looks_like_root(cand):
            return cand
    return Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- 清单解析


def _strip_inline_comment(line: str) -> str:
    """去掉行内注释：`#` 只有出现在行首或空白之后才算注释起点。

    这样 `glob[seq]` 一类的字符类不会被误当成注释，而
    `path  [category: x]  理由   # 那句话` 又能正常裁掉尾巴。
    """
    out = []
    prev = ""
    for ch in line:
        if ch == "#" and (prev == "" or prev.isspace()):
            break
        out.append(ch)
        prev = ch
    return "".join(out)


def _parse_entries(
    lines: Iterable[tuple[int, str]],
    *,
    source: str,
    require_section: bool,
) -> list[Rule]:
    """清单正文的解析核心。`.noai-paths` 与 `AGENTS.md` 的标记区块共用它。

    共用不是图省事：两处清单要"逐条一致"，如果两处各写一个解析器，
    那么"不一致"的差异清单里就会混进解析器的差异 —— 于是没人能判断
    到底是清单不一致，还是解析器不一致（判据(1)立刻失效）。

    格式：
      - `#` 注释 / 空行                       —— 忽略
      - `[category: <id>] <中文名>`            —— 分组头，声明后续条目的类别
      - `<glob>  [category: <id>]  <理由>`     —— 条目行
    """
    rules: list[Rule] = []
    section: str | None = None

    for line_no, raw in lines:
        text = _strip_inline_comment(raw).rstrip()
        if not text.strip():
            continue
        stripped = text.strip()

        if stripped.startswith("```"):
            # `AGENTS.md` 里的清单被一对 ``` 围栏包着（人读时为等宽、可复制）。
            # 围栏本身不是条目，也不该逼着人给它写 category。
            continue

        if stripped.startswith("[category:"):
            head, _, title = stripped.partition("]")
            cat = head[len("[category:") :].strip()
            if not cat:
                raise NoaiError(f"分组头缺少类别 id：{raw.strip()!r}", line_no)
            if cat not in CATEGORY_TITLES:
                raise NoaiError(
                    f"未知类别 {cat!r}；合法类别只有 {list(CATEGORY_ORDER)}（FC-27 七类）",
                    line_no,
                )
            if not title.strip():
                raise NoaiError(
                    "分组头缺少中文名；分组头形如 `[category: solver-core] 一、数值求解器的核心算法`",
                    line_no,
                )
            section = cat
            continue

        if stripped.startswith("|"):
            # `AGENTS.md` 里的表格：`| glob | 类别 | 理由 |`。
            # `|---|` 分隔行与表头行在这里被识别并跳过。
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if len(cells) < 3:
                raise NoaiError(
                    f"表格行的列数不足（需要 `| glob | 类别 | 理由 |`，收到 {len(cells)} 列）：{raw.strip()!r}",
                    line_no,
                )
            glob_cell, cat_cell, reason_cell = cells[0], cells[1], "|".join(cells[2:]).strip()
            if set(glob_cell) <= {"-", ":"} or glob_cell in ("路径 glob", "glob", "路径"):
                continue
            if "[" in cat_cell:
                cat_cell = cat_cell.split("[", 1)[1].split("]", 1)[0]
            cat_cell = cat_cell.replace("category:", "").strip()
            if not cat_cell:
                raise NoaiError(
                    f"表格行的 `category` 为空：{raw.strip()!r}",
                    line_no,
                )
            if cat_cell not in CATEGORY_TITLES:
                raise NoaiError(
                    f"未知类别 {cat_cell!r}；合法类别只有 {list(CATEGORY_ORDER)}（FC-27 七类）",
                    line_no,
                )
            if not reason_cell or reason_cell in ("理由",):
                raise NoaiError(f"表格行缺少理由：{raw.strip()!r}", line_no)
            rules.append(Rule(glob=glob_cell, reason=reason_cell, category=cat_cell))
            continue

        # ---- 纯文本条目行
        glob_text, tag, rest = stripped.partition("[category:")
        if not tag:
            where = (
                f"（所属分组 {section!r}）" if section else "（且不在任何 `[category: ...]` 分组内）"
            )
            raise NoaiError(
                f"条目行缺少 `[category: <id>]` 标记 —— 类别必须显式写出{where}：{raw.strip()!r}",
                line_no,
            )
        cat, close, reason = rest.partition("]")
        if not close:
            raise NoaiError(f"`[category:` 缺少配对的 `]`：{raw.strip()!r}", line_no)
        cat = cat.strip()
        reason = reason.strip()
        glob_text = glob_text.strip()

        if not glob_text:
            raise NoaiError(f"条目行缺少 glob（glob 里有空格就必须写成表格行）：{raw.strip()!r}", line_no)
        if not cat:
            raise NoaiError(f"条目行的 `category` 为空：{raw.strip()!r}", line_no)
        if cat not in CATEGORY_TITLES:
            raise NoaiError(
                f"未知类别 {cat!r}；合法类别只有 {list(CATEGORY_ORDER)}（FC-27 七类）", line_no
            )
        if require_section and section is None:
            raise NoaiError(
                "条目行出现在任何 `[category: ...]` 分组之前；分组头不可省略", line_no
            )
        if section is not None and cat != section:
            raise NoaiError(
                f"条目声明的类别 {cat!r} 与所属分组 {section!r} 不一致 —— "
                "一个条目的类别只能有一处声明（FC-03）",
                line_no,
            )
        if not reason:
            raise NoaiError(f"条目行缺少理由（为什么它属于禁改区）：{raw.strip()!r}", line_no)
        rules.append(Rule(glob=glob_text, reason=reason, category=cat))

    if not rules:
        raise NoaiError(f"{source} 里没有任何条目 —— 空清单等于没有门", None)
    return rules


def load_manifest(path: str | Path | None = None) -> list[Rule]:
    """解析 `.noai-paths` ⇒ `list[Rule]`。

    - 文件读不到（不存在 / 无权限 / 是目录）⇒ :class:`NoaiError`（调用方据此判 ``unknown``）。
    - 任一行不合格式 ⇒ :class:`NoaiError`，消息带行号。
    - 绝不静默跳过看不懂的行：跳过一行就是放过一个禁改区。
    """
    p = Path(path) if path is not None else project_root() / MANIFEST_NAME
    if not p.is_file():
        raise NoaiError(
            f"禁改区清单不是一个可读文件：{p}"
            + ("（是目录）" if p.is_dir() else "（不存在）"),
            None,
        )
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise NoaiError(f"禁改区清单读不到：{p}（{type(exc).__name__}: {exc}）", None) from None

    return _parse_entries(
        ((i, ln) for i, ln in enumerate(raw.splitlines(), start=1)),
        source=str(p),
        require_section=True,
    )


def parse_agents_block(agents_md: str | Path | None = None) -> list[Rule]:
    """解析 `AGENTS.md` 标记区块里的清单。

    `agents_md` 可以是文件路径，也可以是文件内容的字符串
    （后者是为了负控用例能在内存里改一行再断言差异，而不必真改文件）。
    """
    if isinstance(agents_md, Path) or agents_md is None:
        p = Path(agents_md) if agents_md is not None else project_root() / AGENTS_NAME
        try:
            text = p.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise NoaiError(f"{AGENTS_NAME} 不存在：{p}", None) from None
        except OSError as exc:
            raise NoaiError(f"{AGENTS_NAME} 读不到：{p}（{type(exc).__name__}: {exc}）", None) from None
        source = str(p)
    else:
        text = agents_md
        source = f"{AGENTS_NAME}（内存字符串）"

    lines = text.splitlines()
    begins = [i for i, ln in enumerate(lines) if BLOCK_BEGIN in ln]
    ends = [i for i, ln in enumerate(lines) if BLOCK_END in ln]
    if not begins:
        raise NoaiError(f"没有找到标记 {BLOCK_BEGIN}", None)
    if not ends:
        raise NoaiError(f"没有找到标记 {BLOCK_END}", None)
    if len(begins) > 1 or len(ends) > 1:
        raise NoaiError(
            f"标记区块必须**恰好一个**（收到 {len(begins)} 个 BEGIN / {len(ends)} 个 END）—— "
            "两处清单只能有一处正文，多出来的那一处没人会维护",
            None,
        )
    if begins[0] > ends[0]:
        raise NoaiError(f"标记顺序反了：{BLOCK_BEGIN} 出现在 {BLOCK_END} 之后", begins[0] + 1)

    body = ((i, lines[i - 1]) for i in range(begins[0] + 2, ends[0] + 1))
    return _parse_entries(body, source=source, require_section=False)


# --------------------------------------------------------------------------- 一致性（判据(1)）


def _key(rule: Rule) -> tuple[str, str, str]:
    return (rule.glob.strip(), rule.category.strip(), rule.reason.strip())


def check_manifest_consistency(
    *,
    manifest_path: str | Path | None = None,
    agents_md: str | Path | None = None,
) -> list[str]:
    """`.noai-paths` 与 `AGENTS.md` 标记区块是否逐条一致。

    返回差异列表（空 = 一致）。顺序也算：清单的顺序是刻意的
    （FC-05：顺序本身携带信息），所以本函数按位比对，而不是当集合比对。
    比对键是三元组 `(glob, category, reason)` —— 理由也必须一致：
    只在一边写理由，等价于另一边没有理由。
    """
    diffs: list[str] = []
    try:
        manifest = load_manifest(manifest_path)
    except NoaiError as exc:
        return [f"{MANIFEST_NAME} 解析失败：{exc}"]
    try:
        agents = parse_agents_block(agents_md)
    except NoaiError as exc:
        return [f"{AGENTS_NAME} 标记区块解析失败：{exc}"]

    n, m = len(manifest), len(agents)
    if n != m:
        diffs.append(f"条目数不一致：{MANIFEST_NAME} 有 {n} 条，{AGENTS_NAME} 有 {m} 条")

    for i in range(min(n, m)):
        a, b = _key(manifest[i]), _key(agents[i])
        if a != b:
            diffs.append(f"第 {i + 1} 条不一致：{MANIFEST_NAME}={a} ≠ {AGENTS_NAME}={b}")
    for i in range(min(n, m), n):
        diffs.append(f"第 {i + 1} 条只存在于 {MANIFEST_NAME}：{_key(manifest[i])}")
    for i in range(min(n, m), m):
        diffs.append(f"第 {i + 1} 条只存在于 {AGENTS_NAME}：{_key(agents[i])}")

    # 类别覆盖：两处都必须覆盖 FC-27 的七类（一处漏一类，另一处一致也没用）。
    for label, rules in ((MANIFEST_NAME, manifest), (AGENTS_NAME, agents)):
        missing = [c for c in CATEGORY_ORDER if c not in {r.category for r in rules}]
        if missing:
            diffs.append(f"{label} 未覆盖类别：{missing}")
    return diffs


# --------------------------------------------------------------------------- 清单 ↔ 台账对账（H-11）
#
# 三件套里"清单 ↔ 台账"这一对在 `H-11` 之前没有任何命令校验：
# `check_manifest_consistency` 只比对清单的两个落位（`.noai-paths` 与 `AGENTS.md`），
# `check_approvals` 只在命中禁改区之后、且只针对本次改动集逐条判。
# 于是"清单里有一条路径从来没有被登记过"这件事没有任何地方会响 ——
# 而它正是"改它要 2 名 reviewer"这句话失去对象的那种状态。


@dataclass(frozen=True)
class LedgerReconciliation:
    """    清单与台账的差集对账结果（只读，由 `--check-ledger` 呈现）。

    字段分成三组：两个集合的读数（`manifest_paths` / `ledger_entries`）、两个方向的差集（`pre_registered` +
    `missing_registration` 是"清单有而台账无"，`ledger_only` 是"台账有而清单无"）、以及给人读的 `explanation`。

    为什么反方向的差集只是一个字段而不是一个判据：台账是只增的历史记录，清单是今天的保护范围，两者本来就不该相等（理由逐条写在`check_manifest_ledger` 的 docstring 里）。

    `verdict` 只有三档，与 `GateResult` 同码表：`clean`(0) /`requires_human`(1，有漏登记) / `unknown`(2，没查成)。
    """

    verdict: str
    manifest_paths: tuple[str, ...] = ()
    ledger_entries: tuple[str, ...] = ()
    pre_registered: tuple[dict, ...] = ()
    missing_registration: tuple[dict, ...] = ()
    ledger_only: tuple[str, ...] = ()
    explanation: str = ""
    ledger: str = ""

    @property
    def exit_code(self) -> int:
        return _VERDICT_EXIT_CODES[self.verdict]

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "exit_code": self.exit_code,
            "manifest_paths": list(self.manifest_paths),
            "ledger_entries": list(self.ledger_entries),
            "pre_registered": [dict(r) for r in self.pre_registered],
            "missing_registration": [dict(r) for r in self.missing_registration],
            "ledger_only": list(self.ledger_only),
            "explanation": self.explanation,
            "ledger": self.ledger,
        }


def _ledger_has_entry(ledger: Ledger, glob: str) -> bool:
    """台账里有没有这条清单路径的条目（只按条目的 `path` 键比，按 :func:`_norm_rel` 归一）。

    为什么不再退一步按条目里的 `glob` 字段比：那会造出一条假绿。台账条目的 `path`
    是权威键（`--baseline` 登记时相对化后的形态），`glob` 只是登记当时清单里的写法；
    有人改了清单路径、忘了刷新台账时，一条陈旧的 `glob` 恰好还能对上，
    于是"漏登记"被判成已覆盖 —— 而假绿是不可恢复的方向（本项目在 `sha256_file`
    的 docstring 里写着这条取舍：假 stale 可恢复，假 approved 不可恢复）。

    只做词法归一（斜杠、前导 `./`、首尾空白）：`_norm_rel` 是这一层的单一实现，
    清单侧与台账侧共用它，所以"同一条路径的两种写法"不会被读成两条路径。
    """
    key = _norm_rel(glob)
    return any(e.path == key for e in ledger.entries)


def check_manifest_ledger(
    *,
    manifest_path: str | Path | None = None,
    ledger_path: str | Path | None = None,
    root: str | Path | None = None,
) -> LedgerReconciliation:
    """    只读对账：清单里的每条唯一路径，台账里都要有对应条目。

    为什么只查一个方向（刻意不要求对称）：台账是只增的历史记录，清单是今天的保护范围。台账里有而清单里没有的条目是正常的：路径可以退出清单（保护范围收窄）、也可以改名，而历史记录照实留着才是对的。要求两个集合相等，
    会把"保护范围收窄"这件正常的事报成缺陷，而它给出的处置动作（删历史条目）反而是破坏性的。所以那个方向只作信息打印。差集的两个类别（`H-11` 要的机械判据）：盘上没有这个文件 ⇒
    ``pre_registered``（刻意预登记）。清单开头那句纪律是"先登记路径，一旦有人在这里新建它，它会自动落入本清单而不是绕过门"，所以它是正常状态；- 盘上有这个文件 ⇒
    ``missing_registration``（漏登记）：台账里一次都没有登记过这一版。这一档非零退出 —— 它是一条判据，不是一行打印。唯一路径（不是条目数）：同一条路径可以在清单里出现多次（`dedup.py` /
    `providers.py` / `schema.py`各在两个类别里各有一条，是刻意的重复，`.noai-paths` 顶部写着理由）。对账问的是"这条路径有没有被登记过"，所以按唯一路径走。台账那一侧按条目的
    `path` 键比（唯一权威键），也刻意不比 `category`：一条路径出现在两类里时，台账的一条条目只能记一个 `category`，逐条比对会造出结构性的假红。三态与退出码：``clean`` ⇒ 0：
    差集里只剩刻意预登记（或差集为空）；- ``requires_human`` ⇒ 1：有漏登记。1 是"查过了、结论是坏的，必须人去改"那一档（与 `--check-consistency` 报不一致时同码表），
    不是"没查成"；- ``unknown`` ⇒ 2：清单或台账读不到 / 解析不了。没查成不是干净。这套码只属于本命令：改动集判定模式的 0 / 1 / 2 一个都没有动。
    """
    repo = Path(root) if root is not None else project_root()
    ledger_p = Path(ledger_path) if ledger_path is not None else ledger_default_path(repo)

    try:
        rules = load_manifest(manifest_path if manifest_path is not None else repo / MANIFEST_NAME)
    except NoaiError as exc:
        return LedgerReconciliation(
            verdict="unknown",
            explanation=(
                f"unknown：禁改区清单读不到或解析失败 ⇒ 本次没有对账，不代表没问题。原因：{exc}"
            ),
            ledger=str(ledger_p),
        )
    try:
        ledger = load_ledger(ledger_p, root=repo)
    except LedgerError as exc:
        return LedgerReconciliation(
            verdict="unknown",
            explanation=(
                f"unknown：批准台账读不到或解析失败 ⇒ 本次没有对账，不代表没问题。原因：{exc}"
            ),
            ledger=str(ledger_p),
        )

    unique: list[str] = []
    for r in rules:
        g = _norm_rel(r.glob)
        if g not in unique:
            unique.append(g)
    category_of = {_norm_rel(r.glob): r.category for r in rules}

    pre: list[dict] = []
    missing: list[dict] = []
    for glob in unique:
        if _ledger_has_entry(ledger, glob):
            continue
        target = _target_path(glob, repo)
        on_disk = target.is_file()
        row = {
            "path": glob,
            "category": category_of.get(glob, ""),
            "resolved": str(target),
            "on_disk": on_disk,
            "kind": RECON_PRE_REGISTERED if not on_disk else RECON_MISSING_REGISTRATION,
        }
        (pre if not on_disk else missing).append(row)

    ledger_only = tuple(sorted({e.path for e in ledger.entries} - set(unique)))
    manifest_paths = tuple(unique)
    ledger_entries = tuple(sorted(e.path for e in ledger.entries))

    if missing:
        head = "、".join(r["path"] for r in missing[:5])
        tail = "" if len(missing) <= 5 else f"（另有 {len(missing) - 5} 条，见 --json）"
        explanation = (
            f"requires_human：清单 {len(unique)} 条唯一路径里有 {len(missing)} 条"
            f"在台账里找不到条目 ⇒ 这些路径一次都没有被登记过，"
            f"盘上有文件而台账里没有它的版本：{head}{tail}。"
            "处置：`--baseline --paths <路径>` 登记这一版，再走查签字 / 记审计。"
        )
        verdict = "requires_human"
    else:
        verdict = "clean"
        parts = [
            f"clean：清单 {len(unique)} 条唯一路径全部在台账里有条目"
            f"（台账 {len(ledger.entries)} 条）"
        ]
        if pre:
            parts.append(
                f"；其中 {len(pre)} 条是刻意预登记（盘上还没有这个文件）："
                + "、".join(r["path"] for r in pre)
            )
        parts.append(
            f"。台账另有 {len(ledger_only)} 条清单外的历史条目 —— 本命令不要求对称"
            "（台账是只增的历史记录，清单是今天的保护范围）。"
        )
        explanation = "".join(parts)

    return LedgerReconciliation(
        verdict=verdict,
        manifest_paths=manifest_paths,
        ledger_entries=ledger_entries,
        pre_registered=tuple(pre),
        missing_registration=tuple(missing),
        ledger_only=ledger_only,
        explanation=explanation,
        ledger=str(ledger_p),
    )


# --------------------------------------------------------------------------- 路径判定


def _path_candidates(path: str, root: Path | None) -> list[str]:
    """    把一条改动路径化成若干"可拿来与 glob 比"的候选串。

    为什么需要多条候选：调用方给的可能是绝对路径（`D:/repo/src/a.py`），而清单里的 glob 是仓库相对的（`src/*.py`）。如果只比原样，绝对路径永远不命中 ——
    那是一个静默的假阴性（"没命中"读成"没问题"）。

    另外，glob 可能不带前导目录（`*.toml`），所以要给出各级后缀。

    `FINAL-R1d-03`：相对路径必须按 `--root` 解析，不是按进程 CWD。改前这里只做 `Path(path).resolve()`（CWD 相对）再 `relative_to(root)`，于是
    `--root <仓库>` 而 CWD 在别处时，`--paths SRC/AGENTFLOW/PROVIDERS.PY`这种大小写变体会判"均未命中禁改区"（假绿）；CWD 恰好等于 root 时才命中。现在先试
    `root / path`（那才是"这条路径相对哪个根"的正解），再退回原样。
    """
    raw = str(path).replace("\\", "/").strip()
    out: list[str] = []
    if raw:
        out.append(raw)
    if root is not None:
        root_resolved = None
        try:
            root_resolved = root.resolve()
        except (OSError, ValueError):
            root_resolved = None
        if root_resolved is not None:
            # ① `root / path`：相对路径的正解（`--root` 说了算，不是 CWD）。
            try:
                joined = (root_resolved / raw).resolve()
                try:
                    out.append(joined.relative_to(root_resolved).as_posix())
                except ValueError:
                    pass
                out.append(joined.as_posix())
            except (OSError, ValueError):
                pass
            # ② 绝对路径 / CWD 相对的兜底（保持既有行为，只增不减）。
            try:
                abs_p = Path(path).resolve()
                try:
                    out.append(abs_p.relative_to(root_resolved).as_posix())
                except ValueError:
                    pass
            except (OSError, ValueError):
                pass

    for base in list(out):
        parts = [seg for seg in base.split("/") if seg not in ("", ".")]
        for i in range(len(parts)):
            out.append("/".join(parts[i:]))
    seen: list[str] = []
    for cand in out:
        if cand and cand not in seen:
            seen.append(cand)
    return seen


def _glob_matches(candidates: Sequence[str], glob: str) -> str | None:
    """返回第一个命中的候选串（没命中返回 None）。"""
    g = glob.replace("\\", "/").strip().lstrip("./")
    if not g:
        return None
    for cand in candidates:
        c = cand.lstrip("./")
        if fnmatch.fnmatchcase(c, g):
            return c
        # 目录形态的 glob（以 `/` 结尾，或本身就是一个目录前缀）也要能命中其下的文件。
        if g.endswith("/") and (c == g.rstrip("/") or c.startswith(g)):
            return c
        # `` 与 fnmatch 的 `*` 在跨目录语义上不同：显式支持 `a//b` 与 `a/`。
        if "**" in g:
            head, _, tail = g.partition("**")
            head = head.rstrip("/")
            tail = tail.lstrip("/")
            if c.startswith(head) and (not tail or fnmatch.fnmatchcase(c, f"*{tail}")):
                return c
    return None


def check_paths(
    changed: Sequence[str],
    *,
    manifest: str | Path | Sequence[Rule] | None = None,
    root: str | Path | None = None,
) -> GateResult:
    """判定 `changed` 是否命中禁改区。

    `manifest` 可以是：
      - ``None`` ⇒ 用 `root`（默认仓库根）下的 `.noai-paths`；
      - 路径    ⇒ 用该文件；
      - `Rule` 序列 ⇒ 直接用（测试里构造清单用）。

    返回 :class:`GateResult`。读清单失败一律 ``unknown``，不是 ``clean``。
    """
    repo = Path(root) if root is not None else project_root()

    if isinstance(manifest, (str, Path)) or manifest is None:
        try:
            # `manifest is None` ⇒ 用 `root` 下的清单。这里必须显式拼 `repo`，
            # 不能交给 `load_manifest(None)` —— 后者走 `project_root()`，那是
            # "这个脚本恰好在哪个目录"，与 `--root` 无关。实测过它的后果：
            # 用 `--root` 指向另一个工作区时，判据用的是本仓库的清单，
            # 于是"在那个工作区里改了一个它自己登记过的禁改区文件"被判成 clean。
            rules = load_manifest(manifest if manifest is not None else repo / MANIFEST_NAME)
        except NoaiError as exc:
            return GateResult(
                verdict="unknown",
                violations=[],
                required_approvals=0,
                explanation=(
                    f"unknown：禁改区清单读不到或解析失败 ⇒ **本次没有检查**，"
                    f"不代表没问题。原因：{exc}"
                ),
                manifest_issues=[str(exc)],
            )
    else:
        rules = list(manifest)
        if not rules:
            return GateResult(
                verdict="unknown",
                violations=[],
                required_approvals=0,
                explanation="unknown：传入的清单为空 ⇒ **本次没有检查**，不代表没问题。",
                manifest_issues=["空清单"],
            )

    violations: list[dict] = []
    for raw_path in changed:
        candidates = _path_candidates(str(raw_path), repo)
        for rule in rules:
            if _glob_matches(candidates, rule.glob) is None:
                continue
            violations.append(
                {
                    "path": str(raw_path).replace("\\", "/"),
                    "glob": rule.glob,
                    "category": rule.category,
                    "reason": rule.reason,
                }
            )

    if not violations:
        return GateResult(
            verdict="clean",
            violations=[],
            required_approvals=0,
            explanation=(
                f"clean：{len(list(changed))} 条改动路径均未命中禁改区"
                f"（清单 {len(rules)} 条）⇒ 无需额外人工批准。"
            ),
        )

    hit_paths = sorted({v["path"] for v in violations})
    cats = sorted({v["category"] for v in violations})
    explanation = (
        f"requires_human：{len(hit_paths)} 条改动落在 **FC-27 禁 AI 区**"
        f"（类别：{'、'.join(cats)}）⇒ 必须由人编写或人逐行走查，"
        f"并需要 {REQUIRED_APPROVALS_ON_HIT} 名 reviewer 批准。"
        f"命中：{', '.join(hit_paths)}"
    )
    # ---- `R-62`（`draft/28` §164 咬出）：默认路径也要报 `stale`
    #
    # `stale`（台账里钉的那一版与盘上不是同一版）原来只在 `--check-approvals`
    # 那一支里算，而 CI 跑的是 `--git --since <ref>` ⇒ 走的是本函数这一支
    # ⇒ 台账漂移在 CI 的路径上一句话都看不到。
    #
    # 而"钉住的不是提交进去的那一版"恰恰是这条台账唯一要防的事（实测：HEAD 版台账把
    # `capabilities.py` 钉在 `5d245fe7…`，盘上是 `ac8a0f41…`）。所以这里补一句只读的
    # 台账对账：不改 verdict、不改退出码（命中禁改区本来就要求人），只把"漂了几条、
    # 哪几条"写进 explanation —— 让默认路径与 CI 也能看见它。
    stale_note = ""
    try:
        # `repo` 已经在本函数开头解析过（`root` 可能是 None）⇒ 复用它，别再造一个 `Path(None)`。
        ledger_file = ledger_default_path(repo)
        if ledger_file.is_file():
            _ledger = load_ledger(ledger_file)
            stale: list[str] = []
            for rel in hit_paths:
                # `ledger.entry_for` 是台账查条目的单一实现（`check_approvals` 也用它）——
                # 这里不另写一份"怎么在台账里找一条"的逻辑（否则 `stale` 会判在错的那一条上）。
                entry = _ledger.entry_for(_norm_rel(rel))
                if entry is None:
                    continue
                cur = sha256_file(repo / rel)
                if str(entry.sha256) != cur:
                    stale.append(f"{rel}（台账 {str(entry.sha256)[:12]} ≠ 盘上 {cur[:12]}）")
            if stale:
                stale_note = (
                    f"\n⚠️ 台账 **stale** {len(stale)} 条（被批准的那一版与盘上不是同一版 ⇒"
                    " 旧批准不许沿用；`--check-approvals` 会给出逐条结论）："
                    + "；".join(stale)
                )
    except (OSError, LedgerError, ValueError) as exc:  # noqa: BLE001 - 这里只是补一句读数
        stale_note = f"\n（台账对账没做成：{type(exc).__name__}: {exc} —— 没查成，不是'没有 stale'）"
    return GateResult(
        verdict="requires_human",
        violations=violations,
        required_approvals=REQUIRED_APPROVALS_ON_HIT,
        explanation=explanation + stale_note,
    )


# --------------------------------------------------------------------------- hash 台账（批准记录）
#
# 台账是 FC-27 在没有 git 的环境里的可执行判据：内容 hash 就是版本。
# 本节的每个"判据"都只有一处实现（FC-03）：hash 计算 `sha256_file`、
# 结构解析 `load_ledger` / `_parse_entry`、批准数判定 `evaluate_approval`。


def _now_iso(now: _dt.datetime | None = None) -> str:
    """ISO 时间戳（秒精度，带时区）。

    「谁在什么时候签的字」是这份台账的主要内容，所以时间戳不许省：
    没有时区的时间戳在跨时区复核时会歧义，而歧义会被读成"反正是同一轮"。
    """
    t = now if now is not None else _dt.datetime.now().astimezone()
    if t.tzinfo is None:
        t = t.astimezone()
    return t.replace(microsecond=0).isoformat()


def _norm_rel(path: str | Path) -> str:
    """把一条路径化成台账里的键：正斜杠、去掉前导 `./`、去首尾空白。

    为什么它必须只有一份实现：否则 `src\\a.py`、`./src/a.py`、`src/a.py`
    会变成三条互不相认的记录，而"命中路径在台账里没有条目"就会出现假命中
    （看起来没登记，其实登记了）—— 反过来也会：`stale` 判在错的那一条上。
    """
    s = str(path).replace("\\", "/").strip()
    while s.startswith("./"):
        s = s[2:]
    return s


def _is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def sha256_file(path: str | Path) -> str:
    """磁盘当前内容的 sha256（十六进制小写）。字节级，不做任何归一化。

    刻意不归一化行尾/编码：本项目在 Windows 上被多个 agent 并行编辑，
    CRLF 与 LF 的差别是内容差别。归一化会造出一条"内容变了但 hash 没变"的路 ——
    那正是本台账存在的理由要堵的形态。两个方向的代价不对称：

    - 假 `stale`：人多走查一次，可恢复；
    - 假 `approved`：没走查的版本被当成走查过的版本，不可恢复。
    """
    p = Path(path)
    if not p.is_file():
        raise LedgerError(
            f"要计算 hash 的对象不是一个可读文件：{p}"
            + ("（是目录）" if p.is_dir() else "（不存在）")
        )
    digest = hashlib.sha256()
    try:
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
    except OSError as exc:
        # 打开/读取失败不吞：拿不到 hash 就判不了"这是不是被批准的那一版"，
        # 调用方必须把这一条读成"没查成"（unknown），而不是"没问题"。
        raise LedgerError(
            f"读不到内容，无法计算 sha256：{p}（{type(exc).__name__}: {exc}）"
        ) from None
    return digest.hexdigest()


def ledger_default_path(root: str | Path | None = None) -> Path:
    """台账的默认位置：`<root>/.noai-approvals.json`。"""
    return (Path(root) if root is not None else project_root()) / LEDGER_NAME


def _target_path(changed: str | Path, repo: Path) -> Path:
    """改动路径 ⇒ 磁盘上的真实文件。相对路径按仓库根解析（不是按当前工作目录）。

    还要处理伞形仓库前缀：本仓库的 `.git` 在上一级，所以 `git diff --name-only`
    给出的路径形如 `agentflow/.noai-paths`（仓库根相对），而 `repo` 是 `agentflow/`。
    直接 `repo / "agentflow/.noai-paths"` 会指向 `agentflow/agentflow/...`（不存在），
    于是同一条路径在"命中判定"里对、在"台账查键"里错。

    为什么在这里做（而不是在 `_repo_rel_key` 里）：所有需要"路径 ⇒ 盘上文件"的地方
    （读 hash、核 evidence）都得同意同一个答案。修一处、另一处继续错，正是本项目记过的
    "同一个概念两份实现"形态。
    """
    p = Path(changed)
    if p.is_absolute():
        return p
    direct = repo / p
    if direct.exists():
        return direct
    # 去掉伞形前缀再试（只去掉一层，且只在那一层恰好是仓库目录名时）。
    parts = p.parts
    if len(parts) > 1 and parts[0] == repo.name:
        stripped = repo / Path(*parts[1:])
        if stripped.exists():
            return stripped
    return direct


def _repo_rel_key(changed: str | Path, repo: Path) -> str:
    """改动路径 ⇒ 台账的键（仓库相对、正斜杠）。

    绝对路径先相对化；相对化不成（在仓库之外）就退回归一化的原样 ——
    这不是静默兜底：键仍然唯一且可比较，`check_paths` 的命中判定另有一套候选串逻辑。

    `R2-N2`（2026-09-26 实测）：旧版对 `agentflow/.noai-paths` 这样的伞形前缀路径
    给出 `agentflow/.noai-paths` 这个不存在的键 ⇒ 台账明明登记过，门却报
    `unregistered`（"从没登记"）。那不是"未批准"，是键错了。
    现在先试"去掉一层仓库目录名"，命中就用仓库相对键。
    """
    try:
        rel = _target_path(changed, repo).resolve().relative_to(repo.resolve())
        return _norm_rel(rel.as_posix())
    except (OSError, ValueError):
        pass
    # 盘上那个文件不存在时（例如只为查键而给的路径），退到纯字符串归一：
    # 去掉一层与仓库目录同名的前缀，让键与登记时用的写法一致。
    p = Path(str(changed))
    parts = p.parts
    if not p.is_absolute() and len(parts) > 1 and parts[0] == repo.name:
        return _norm_rel(Path(*parts[1:]).as_posix())
    return _norm_rel(changed)


def _receipt_log_default_path(root: str | Path | None = None) -> Path:
    """回执链的默认位置：`<root>/.noai-audit-receipts.jsonl`。"""
    return (Path(root) if root is not None else project_root()) / AUDIT_RECEIPT_NAME


def _resolve_evidence_file(rel: str, base: Path) -> Path:
    """证据/回执路径 ⇒ 磁盘上的文件。相对路径先按仓库根，再按当前工作目录。

    两种给法都要接受，且顺序必须确定：写入侧与核对侧用同一个函数，
    否则会出现"写得进去、核不出来"（`temp/verify-audit-forge.txt` 之后的核对层就是这样来的）。
    """
    p = Path(rel)
    if p.is_absolute():
        return p
    cand = base / rel
    return cand if cand.exists() else (Path.cwd() / rel)


def _receipt_digest(record_without_hash: dict) -> str:
    """    一条回执的自身 hash：对它除 `hash` 之外的规范化 JSON 求 sha256。

    ## 为什么这里不 import `agentflow.canonical`（`R-33` 的最终口径）

    规范 JSON 的口径在包里只有一份实现（`src/agentflow/canonical.py`），但门不能依赖它：门必须能在被单独复制的情况下跑。证据不是推断 —— `R-33` 的第一版让门按路径
    加载 `canonical.py`，结果 `tests/test_noai_gate_record_audit_cli.py` 的两条负控（把门脚本单独复制到临时目录、注入一处缺陷，证明回执链核对会红）当场变红：副本旁边没有
    `canonical.py`。那两条负控测的是"门自己坏了会不会被抓到"，而"门必须先有邻居文件才能跑"会让这条判据无处安放。
    - `import agentflow.canonical` 更不行：那会把门的可运行性押在被它审计的那棵树上。所以这里保留一份字节（`sort_keys=True` / `ensure_ascii=False` /
    `separators=(",", ":")`），并由 :func:`check_canonical_consistency`（CLI `--check-canonical`）把它与 `signatures`那一份钉在一起：
    同一载荷两侧哈希必须逐字相等，否则报 `divergent(1)`。"两处字节 + 一条机器判据相连"是本仓在"结构上无法共用"时的既定形态（`[5c]` 同族）；真正被禁掉的是没人看着的第二份口径，不是第二份字节。
    """
    body = json.dumps(record_without_hash, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def check_canonical_consistency() -> dict:
    """本门用的规范哈希与 `signatures` 用的是不是同一份口径（`R-33` 的机器判据）。

    返回 `{"status": "consistent" | "divergent" | "unknown", "detail": str, ...}`：

    - `consistent`：同一载荷在门侧与 `signatures` 侧算出的哈希逐字相等；
    - `divergent`：不相等 ⇒ 至少一处改了自己的规范口径（这正是 `R-33` 的形态）；
    - `unknown`：本包 import 不了 ⇒ 没查成，不许读成一致。

    为什么这条判据是"允许两份字节"的唯一理由：它把"又分叉了"变成一次可复现的红灯。
    门为什么不能共用那一份实现，见 :func:`_receipt_digest` 的 docstring（它记着那条
    被负控推翻的第一版方案）。
    """
    probe = {"b": [1, 2, {"nested": True}], "a": "中文与 ASCII 混排", "c": 3.5}
    payload = list(probe["b"]) + [probe["a"]]
    gate_hash = _receipt_digest(payload)
    try:
        src = Path(__file__).resolve().parents[1] / "src"
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
        from agentflow import signatures as SIG  # noqa: PLC0415 - 可选依赖：包 import 不了就是 unknown
        # 两侧算同一个问题：`claims_hash_of({"claims": X})` 哈希的就是 `X` 本身，
        # 与门侧 `_receipt_digest(X)` 的输入逐字相同 ⇒ 结果必须逐字相等。
        sig_hash = SIG.claims_hash_of({"claims": payload})
    except Exception as exc:  # noqa: BLE001 - 包 import 不了 ⇒ unknown，不是 divergent
        return {"status": "unknown",
                "detail": f"本包 import 不了（{type(exc).__name__}: {exc}）⇒ 没查成",
                "gate_hash": gate_hash}
    if gate_hash == sig_hash:
        return {"status": "consistent", "detail": "同一份口径：同一载荷的哈希逐字相等",
                "gate_hash": gate_hash, "signatures_hash": sig_hash}
    return {"status": "divergent",
            "detail": f"门侧 {gate_hash[:16]}… ≠ signatures 侧 {sig_hash[:16]}… ⇒ "
                      "至少有一处改了自己的规范口径（`R-33`）",
            "gate_hash": gate_hash, "signatures_hash": sig_hash}


def check_receipt_chain(
    log_path: str | Path | None = None,
    *,
    root: str | Path | None = None,
    expect: Sequence[tuple[str, str]] = (),
) -> dict:
    """    读回执链并重算整条链。返回 `{"exists", "records", "problems", "tail", "covered"}`。

    `expect` 是 `(path, sha256)` 对：每一条都必须在链里出现过一次（精确到"批准/审计的是这一版"），否则 `covered` 为 False。

    ## 判据（任何一条不成立都进 `problems`）

    1. 每条必须是合法 JSON 对象，且带 `hash` 与 `prev`；
    2. `prev` 必须逐字等于上一条的 `hash`（第一条是 64 个 0）；
    3. `hash` 必须等于按同一规则重算出来的值 ⇒ 改一个字节就断链。链断了 ⇒ 调用方判 `unknown`（没查成），不是"未批准"：它说明这份记录已经不可信，而不可信的记录既不能用来放行、也不能用来定罪。
    """
    p = Path(log_path) if log_path is not None else _receipt_log_default_path(root)
    out: dict = {"log": str(p), "exists": p.is_file(), "records": 0,
                 "problems": [], "tail": "", "covered": False}
    if not out["exists"]:
        out["problems"].append(f"回执链不存在：{p}")
        return out
    try:
        lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except (OSError, UnicodeDecodeError) as exc:
        out["problems"].append(f"回执链读不到或不是 UTF-8：{p}（{type(exc).__name__}: {exc}）")
        return out

    prev = "0" * 64
    seen: list[tuple[str, str]] = []
    for i, line in enumerate(lines, 1):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            out["problems"].append(f"第 {i} 行不是合法 JSON：{exc}")
            return out
        if not isinstance(rec, dict):
            out["problems"].append(f"第 {i} 行不是 JSON 对象")
            return out
        got_prev = str(rec.get("prev", ""))
        if got_prev != prev:
            out["problems"].append(
                f"第 {i} 行的 `prev` 与上一条的 `hash` 不一致：链在这里断了"
                f"（上一环 {prev[:12]}，本行写的是 {got_prev[:12]}）"
            )
            return out
        claimed = str(rec.get("hash", ""))
        body = {k: v for k, v in rec.items() if k != "hash"}
        actual = _receipt_digest(body)
        if claimed != actual:
            out["problems"].append(
                f"第 {i} 行的内容与它自己的 `hash` 不符（重算 {actual[:12]}，记录 {claimed[:12]}）"
                " ⇒ 这一行被改过"
            )
            return out
        seen.append((str(rec.get("path", "")), str(rec.get("entry_sha256", ""))))
        prev = claimed
    out["records"] = len(lines)
    out["tail"] = prev
    want = set(expect)
    out["covered"] = bool(want) and want.issubset(set(seen))
    if want and not out["covered"]:
        missing = sorted(f"{a}@{b[:12]}" for a, b in (want - set(seen)))
        out["problems"].append(
            "回执链里没有这一版被批准/审计过的记录："
            + "、".join(missing)
            + "（回执链是只增的：它没有，就说明这一版的那次动作**没被记下来**）"
        )
    return out


def append_receipt(
    *,
    action: str,
    path: str,
    entry_sha256: str,
    detail: str = "",
    log_path: str | Path | None = None,
    root: str | Path | None = None,
) -> dict:
    """往回执链追加一条，返回那条记录。

     先校验整条链再追加：链已经断了就拒绝追加（`LedgerError`）。
    理由：在一条断链后面接着写，等于把新记录也挂到不可信的历史上，
    而报告里会显示"链正常"（只看尾部的实现会这样）。断链的处置只有一个：
    由人看过之后决定重建，而不是由写入方悄悄续上。
    """
    p = Path(log_path) if log_path is not None else _receipt_log_default_path(root)
    prior = check_receipt_chain(p)
    if prior["exists"] and prior["problems"]:
        raise LedgerError(
            f"拒绝追加回执：现有回执链自身不通过校验（{p}）—— {'；'.join(prior['problems'])}。"
            "先由人确认这条链的现状，再决定是否重建（不许在断链后面续写）。"
        )
    prev = prior["tail"] if prior["records"] else "0" * 64
    body = {
        "at": _now_iso(),
        "action": action,
        "path": _norm_rel(path),
        "entry_sha256": entry_sha256,
        "prev": prev,
        "detail": detail,
    }
    rec = {**body, "hash": _receipt_digest(body)}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8", newline="") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")) + "\n")
    except OSError as exc:
        raise LedgerError(f"回执链写不进去：{p}（{type(exc).__name__}: {exc}）") from None
    return rec


def _check_audit_evidence(
    audits: Sequence["ReviewAudit"], repo: str | Path | None, target_text: str = ""
) -> dict:
    """    逐条核对机审的证据锚：证据文件在不在、内容 hash 对不对。返回值 `{"checked": [...], "problems": [...]}`，`problems` 非空 ⇒ 调用方判 `unknown`。

    ## 为什么这一层必须在判定时再跑一次

    `record_audit` 写入时已经核过一次（那时文件在、hash 对）。但写入与判定之间可能隔着很久，而证据文件在 `temp/` 里（会被清理、会被重跑覆盖）。若判定时不再核，
    "证据还在不在"这件事就退化成"当时它在"。本项目记过的形态正是这个：把一次性的观察当成持续的事实。

    ## 相对路径按仓库根解析

    与 `_target_path` 同口径：`repo` 优先，其次当前工作目录（写入时接受两种给法，核对时也必须接受同两种，否则"能写进去、核不出来"）。
    """
    base = Path(repo) if repo is not None else project_root()
    checked: list[dict] = []
    problems: list[str] = []
    for a in audits:
        rel = a.evidence_path.strip()
        rec = {"auditor": a.auditor, "dimension": a.dimension, "evidence_path": rel,
               "expected_sha256": a.evidence_sha256}
        if not rel:
            rec["status"] = "no_path"
            checked.append(rec)
            problems.append(
                f"[{a.auditor}/{a.dimension}] 记录里没有 `evidence_path`（只有一句话的证据）"
            )
            continue
        p = _resolve_evidence_file(rel, base)
        rec["resolved"] = str(p)
        try:
            actual = sha256_file(p)
        except LedgerError as exc:
            rec["status"] = "unreadable"
            checked.append(rec)
            problems.append(f"[{a.auditor}/{a.dimension}] 证据文件读不到：{p}（{exc}）")
            continue
        rec["actual_sha256"] = actual
        if actual != a.evidence_sha256:
            rec["status"] = "hash_mismatch"
            checked.append(rec)
            problems.append(
                f"[{a.auditor}/{a.dimension}] 证据文件 {p} 的内容与登记不符："
                f"盘上 {actual[:12]}，登记 {a.evidence_sha256[:12]}"
            )
            continue
        # 内容交叉核对（`H-1b`）：hash 对得上只证明"这个文件没被换过"，
        # 不证明"这个文件是这个主体审这一版产出的"。台账是可以手改的
        # （谁能写 `.noai-approvals.json`，谁就能补一条审计记录），所以判定侧
        # 必须和写入侧做同一组核对 —— 两处共用 `_evidence_cross_check` 一处实现。
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            rec["status"] = "unreadable"
            checked.append(rec)
            problems.append(f"[{a.auditor}/{a.dimension}] 证据文件读不出文本：{p}（{exc}）")
            continue
        cross = _evidence_cross_check(a, text, a.sha256, target_text)
        if cross:
            rec["status"] = "content_mismatch"
            rec["cross_check"] = cross
            checked.append(rec)
            problems.extend(cross)
            continue
        rec["status"] = "ok"
        checked.append(rec)
    return {"checked": checked, "problems": problems}


@dataclass(frozen=True)
class Reviewer:
    """    一次已完成的人工逐行走查。`scope` 必须具体到符号或行区间。

    「写"看过了"等于没看」—— 与清单理由"只在一边写理由，等价于另一边没有理由"同一个道理。

    `FINAL-R1d-04`：人审通路此前没有任何内容锚 —— 判定只看台账 JSON 里的名字字符串与"名字去重"，于是"改受保护文件 + 改台账 sha +
    编两个名字"就能拿到`[clean]`（副本实测：`temp/r1d-final-ws/F2c-forge-full.txt`）。现在每条人审记录可以带一个证据锚（`evidence_path` +
    `evidence_sha256`）：`--approve --evidence-path <走查记录>` 会把那份记录的 sha256 一起写进台账，判定时核对文件仍在盘上且逐字节未变；核对不过 ⇒ 这条批准不算数。
    老记录（本字段为空）仍然有效（否则现存全部批准会一次性作废），但它们会被逐条标成"无内容锚"，并在 approved 那一行带上固定保留 ——读的人因此知道每一条批准的实际强度是什么。
    """

    name: str
    at: str
    scope: str
    note: str = ""
    verdict: str = "逐行走查通过"
    evidence_path: str = ""
    evidence_sha256: str = ""

    @property
    def anchored(self) -> bool:
        """这条批准有没有内容锚（`FINAL-R1d-04`）。"""
        return bool(str(self.evidence_path).strip() and str(self.evidence_sha256).strip())

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "at": self.at,
            "scope": self.scope,
            "note": self.note,
            "verdict": self.verdict,
            "evidence_path": self.evidence_path,
            "evidence_sha256": self.evidence_sha256,
        }


def reviewer_anchor_problem(reviewer: Mapping[str, Any] | Reviewer, *, repo: Path | None = None) -> str:
    """核对一条人审记录的证据锚；返回空串 = 没问题（或本来就没有锚）。

    三态（`FINAL-R1d-04`）：没有锚 ⇒ 返回空串（不在这里判它不合格，
    由输出侧的固定保留说明强度）；有锚但文件不在/内容变了/路径读不到 ⇒ 返回理由。
    """
    if isinstance(reviewer, Reviewer):
        path_text, want = reviewer.evidence_path, reviewer.evidence_sha256
    else:
        path_text = str(reviewer.get("evidence_path") or "")
        want = str(reviewer.get("evidence_sha256") or "")
    if not path_text and not want:
        return ""
    if not path_text or not want:
        return "证据锚不完整（`evidence_path` 与 `evidence_sha256` 必须成对）"
    base = repo if repo is not None else Path.cwd()
    candidate = Path(path_text)
    if not candidate.is_absolute():
        candidate = base / path_text
    if not candidate.is_file():
        return f"证据锚指向的文件不在盘上：{path_text}"
    got = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if got != want:
        return f"证据锚的内容变了：{path_text}（台账 {want[:12]}… / 盘上 {got[:12]}…）"
    return ""


@dataclass(frozen=True)
class ReviewAudit:
    """    一次机器审计的记录（与 `Reviewer` 平行的那条通路，两者永不混写）。
    ## 为什么要有这个类型（口径变更，2026-09-26 由所有者批准）
    FC-27 原本只认"2 名人逐行走查"（`Reviewer`）。所有者批准了一条并行通路：多个子代理从多个维度独立审计、全部未发现任何问题 ⇒ 视为通过。这条通路不是"AI
    代替人签字"：`reviewers` 数组仍然只能由人写，审计记录写进 `audits` 数组，两者在台账里分列、在输出里分行，读门的报告永远能看出"这一条是靠人签的、还是靠机审的"。
    ## 四个不许省掉的字段（防"没发现问题"变成一句空话）
    1. `dimension`：受控词表里的一个维度（`AUDIT_DIMENSIONS`）。"多维度"必须是可数的，否则"多个维度"与"多看两眼"不可区分。2. `evidence`：证据的位置（人读的那一句）。3.
    `evidence_sha256`：证据文件的内容 hash。这一条是`temp/verify-audit-forge.txt` 那次伪造复现之后加的：在那之前`evidence` 只被检查"非空"，
    于是编一个不存在的路径也算通过 ——谁能写 `.noai-approvals.json`，谁就能给清单自己报 clean。有了它，"证据存在且没被换过"至少变成一件可机器核对的事：门在判定时会重算那个文件的 sha256，
    不一致 ⇒ 这一条判 `unknown`（没查成）。它不是签名：能改台账的人一样能把 hash 改成新值。它挡住的是"顺手编一句证据"，挡不住"有权限的人蓄意伪造"（后者需要外部锚，见 §6.1）。4. `sha256`：
    审的是哪一版。与台账条目不一致的审计一律不算数 ——否则"改了之后再补一次审计"就能批准一版没人看过的内容。
    """

    auditor: str
    dimension: str
    at: str
    sha256: str
    evidence: str
    negative_control: str
    findings: tuple[str, ...] = ()
    scope: str = ""
    #: 证据文件的内容 hash（相对仓库根或绝对路径由 `evidence` 指）。必需，理由见类 docstring。
    evidence_sha256: str = ""
    #: 证据文件的落点（相对仓库根优先）。空 = 只认 `evidence` 里的那句话（不再放行）。
    evidence_path: str = ""
    #: 开审那一刻被审对象的 sha（`c-20`）：没有它，"审的是 A 版、记账时台账已被刷成 B 版"
    #: 在结构上是通的，而门照样报 clean。写入时要求它与台账条目同版。
    audit_started_sha256: str = ""
    #: 独立性声明（`H-1e` / `c-16`）：`authored` 是空或 `unknown` 时，"审计者不能是署名者"
    #: 这条判据无从适用，于是要求审计者显式写下"我与该条目的作者不是同一主体"。
    #: 它是自述、比不上一张受控主体名册，但它把"什么都没说"变成了"说了什么"。
    independence: str = ""

    @property
    def clean(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict:
        return {
            "auditor": self.auditor,
            "dimension": self.dimension,
            "at": self.at,
            "sha256": self.sha256,
            "evidence": self.evidence,
            "negative_control": self.negative_control,
            "findings": list(self.findings),
            "scope": self.scope,
            "evidence_sha256": self.evidence_sha256,
            "evidence_path": self.evidence_path,
            "audit_started_sha256": self.audit_started_sha256,
            "independence": self.independence,
        }


@dataclass(frozen=True)
class LedgerEntry:
    """台账里的一条：某个路径某一版内容的 hash + 变更摘要 + 走查记录。

    `authored` 与 `authored_basis` 必须成对出现（构造时无默认值 ⇒ 写代码的人
    无法"忘了写依据"）：前者是结论，后者是这个结论有多强
    （`attested` = 有直接证据 / `inferred` = 推断）。
    """

    path: str
    glob: str
    category: str
    sha256: str
    authored: str
    authored_basis: str
    change_note: str
    reviewers: tuple[Reviewer, ...] = ()
    #: 机器审计记录（第二条通路）。与 `reviewers` 分列存放，永不混写。
    audits: tuple[ReviewAudit, ...] = ()
    changed_this_session: bool | None = None
    also_hits: tuple[dict, ...] = ()

    @property
    def clean_audits(self) -> tuple[ReviewAudit, ...]:
        """        清白的审计：无 finding、且 sha256 与本条一致、且负控与独立性声明合格、且证据 hash 非空。

        六项缺一不可：`sha256` 不对 = 审的不是这一版；负控为空 = 没证明有能力发现问题；有 finding = 它其实发现了问题（那这条通路就不该放行）；`evidence_sha256` 为空 =
        这条记录没法核对证据（`temp/verify-audit-forge.txt`那次伪造复现就发生在只检查"非空"的版本上）；`at` 读不出 / 落在未来 = 时间戳不可信（`R5-R1b-7`）；署名者未知时
        `independence` 必须是一段真声明，不是一个 `x`（`R5-R1b-4`）。

        这里只查"字段齐不齐 / 字段本身合不合格"，不查证据文件在不在、对不对 ——那是 `evaluate_approval` 的事（要读盘，而这里只是台账对象的一个属性）。分成两层是刻意的：字段层失败是
        `unapproved`（这条审计本身不合规），盘上层失败是 `unknown`（没查成）。两者处置不同，不能折叠。
        """
        need_independence = normalize_subject(self.authored) in ("", "unknown")
        return tuple(
            a for a in self.audits
            if a.clean and a.sha256 == self.sha256 and a.negative_control.strip()
            and a.evidence_sha256.strip()
            # `c-20`：审计必须声明"开审那一版"，且与台账这一版同版
            and a.audit_started_sha256.strip() == self.sha256
            # `H-1c` / `R5-R1b-6`：负控要有内容（长度 + "怎么比" + "比出来什么"），不是只非空
            and not negative_control_problem(a.negative_control)
            # `H-1d`：`scope` 必须说清这次覆盖了哪些符号
            and bool(a.scope.strip())
            # `R5-R1b-7`：`at` 必须可解析且不在未来（它此前是唯一"写了就信"的字段）
            and not audit_timestamp_problem(a.at)
            # `H-1e` / `c-16` / `R5-R1b-4`：署名者未知时，"我不是作者"这句话必须
            # 由审计者说出来，而且必须是一句话（一个 `x` 与一段声明不可区分）
            and (not need_independence or not _independence_problem(a.independence))
        )

    @property
    def counted_audits(self) -> tuple["ReviewAudit", ...]:
        """计入门槛的审计：在 `clean_audits` 之上再按证据身份去重（`c-17`）。

        没有这一步，同一个证据文件复制 N 条、每条换一个 `dimension` 字符串，
        就能凑出"≥3 个维度" —— 而那三"个"维度其实是同一次观察，
        与"多看两眼"不可区分（`MIN_DISTINCT_DIMENSIONS` 的注释正是为区分这两者写的）。
        证据身份 = `(evidence_path, evidence_sha256)` 归一化之后的值。
        """
        seen: set[tuple[str, str]] = set()
        out: list[ReviewAudit] = []
        for a in self.clean_audits:
            # `R1-AN-2`：键用词法归一后的路径，不是原始字符串
            ident = (_norm_evidence_rel(a.evidence_path), a.evidence_sha256.strip().casefold())
            if ident in seen:
                continue
            seen.add(ident)
            out.append(a)
        return tuple(out)

    @property
    def audit_dirty(self) -> tuple[ReviewAudit, ...]:
        """报了 finding 的审计（无论 sha 对不对）—— 用来把"审计发现了东西"说清楚。"""
        return tuple(a for a in self.audits if not a.clean)

    def distinct_auditors(self) -> tuple[str, ...]:
        """不同审计者 —— 按归一化后的标识去重（`H-1a`），且只数计入门槛的那些（`c-17`）。"""
        out: list[str] = []
        for a in self.counted_audits:
            key = normalize_subject(a.auditor)
            if key and key not in out:
                out.append(key)
        return tuple(out)

    def distinct_dimensions(self) -> tuple[str, ...]:
        """不同维度 —— 只数证据互不相同的那些（`c-17`）。"""
        out: list[str] = []
        for a in self.counted_audits:
            if a.dimension not in out:
                out.append(a.dimension)
        return tuple(out)

    @property
    def distinct_reviewers(self) -> tuple[str, ...]:
        """        不同姓名的 reviewer —— 按 :func:`normalize_subject` 归一后去重计。

        批准数按不同姓名计，不按记录条数计：同一个人签两次不是"2 名 reviewer"，而 FC-27 要求 2 名正是为了拿到互相独立的复核（1 名 reviewer 与"作者自己再看一遍"在结构上无法区分）。
        重复的签名记录照实保留（它是事实），只是不增加批准数。

        `R5-R1b-3`：这里曾经用 `r.name not in out` 做原始字符串比较，一处归一化都没有 —— 与 `H-1a` 给审计者标识加的那一套不对称，也与 `_parse_reviewer`会
        strip 首尾空白不一致。实测：同一条台账的 `reviewers` 手写成`reviewer-甲` / `ｒｅｖｉｅｗｅｒ－甲` / `reviewer-甲\\u200b` 三种写法（同一个人），门打印"已有 3
        名不同 reviewer 完成逐行走查（通路 = 人审）"并 approved。判据五的核心恰恰是"人必须亲自签字"，所以人审通路必须与机审通路用同一把刀（`normalize_subject`，
        见它的模块级契约注释）。
        """
        out: list[str] = []
        for r in self.reviewers:
            key = normalize_subject(r.name)
            if key and key not in out:
                out.append(key)
        return tuple(out)

    @property
    def attribution_caveat(self) -> str:
        """`authored` 这个结论有多强，用一句人话写出来（空串 = 无需提示）。

        为什么它必须出现在 `--check-approvals` 的输出里：读台账的人不该
        把推断当事实。一条只有 `authored: "ai-agent"` 的记录看起来像事实，
        而它可能只是"mtime 落在本会话窗口内"推出来的。
        """
        if self.authored_basis == "inferred":
            return "（署名归属为**推断**，据 mtime 与会话边界得出，非独立证据）"
        if self.authored_basis == "attested":
            # 这一档无法机械验证：它依赖签名者诚实。门能做的是强迫它被写下来。
            return "（署名归属由改动者/签字人**声明**：attested，门无法机械验证该声明）"
        return ""

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "glob": self.glob,
            "category": self.category,
            "sha256": self.sha256,
            "authored": self.authored,
            "authored_basis": self.authored_basis,
            "change_note": self.change_note,
            "changed_this_session": self.changed_this_session,
            "reviewers": [r.to_dict() for r in self.reviewers],
            "audits": [a.to_dict() for a in self.audits],
            "also_hits": [dict(h) for h in self.also_hits],
        }


@dataclass(frozen=True)
class Ledger:
    """整份台账。`entries` 按 `path` 排序 —— 稳定顺序让 `--baseline` 的 diff 可读。"""

    ledger_version: int
    generated_at: str
    entries: tuple[LedgerEntry, ...] = ()

    def entry_for(self, path: str | Path) -> LedgerEntry | None:
        key = _norm_rel(path)
        for e in self.entries:
            if e.path == key:
                return e
        return None

    def to_dict(self) -> dict:
        return {
            "ledger_version": self.ledger_version,
            "generated_at": self.generated_at,
            "entries": [e.to_dict() for e in self.entries],
        }


def _parse_reviewer(item: object, *, where: str) -> Reviewer:
    if not isinstance(item, dict):
        raise LedgerError(f"{where} 不是一个 JSON 对象（收到 {type(item).__name__}）")
    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        raise LedgerError(f"{where} 缺少非空的 `name`（谁走查的必须有名字）")
    def _s(key: str) -> str:
        v = item.get(key, "")
        return v if isinstance(v, str) else ""
    return Reviewer(
        name=name.strip(),
        at=_s("at"),
        scope=_s("scope"),
        note=_s("note"),
        verdict=_s("verdict") or "逐行走查通过",
        # `FINAL-R1d-04`：证据锚两格必须一起读回来 —— 只写不读会让
        # "带锚的批准"在门里退化成"没有锚的批准"（而这正是这一条要修的东西）。
        evidence_path=_s("evidence_path"),
        evidence_sha256=_s("evidence_sha256"),
    )


#: 负控的内容下限（`H-1c`）：只查"非空"时 `'n/a'` 也是合法字符串。
NEGCTL_MIN_CHARS = 40
#: 负控里必须出现其中之一 —— 它回答的是"拿什么去比"（改前那一版 / 已知坏样本 / 注入）。
NEGCTL_MARKERS = ("改前", "HEAD", "坏样本", "注入", "git show", "旧版", "before", "negative")
#: `R5-R1b-6`：负控还必须写出看见了什么 —— 只写"拿改前那一版去比"是半句话。
#: 旧判据只剩"长度 ≥ 40 + 出现标记词"，于是 `'改前' + '啊'*60`、`'negative ' + 'x'*60`、
#: `'负控：（此栏无内容）' + '占位'*20 + ' 改前'` 三种空话全部通过 —— 而"负控真的跑过一次"
#: 与"只写了标记词"在字符串上仍然不可区分（代码注释自己承认 `n/a` 不可区分，这一条把
#: 范围说全：受控词表 + 长度同样不可区分）。
NEGCTL_OBSERVED_MARKERS = (
    "报红", "报出", "报错", "失败", "被拒", "拒绝", "不放行", "不通过", "红", "退出码",
    "failed", "fails", "fail", "reject", "red", "error", "detected", "caught",
)
#: `R5-R1b-6`：负控里至少要有这么多个互不相同的内容片段（词 + 中文二元组）。
#: `'改前会报出 network'` 有 6 个；`'改前' + '啊'*60` 只有 2 个。
NEGCTL_MIN_DISTINCT_CHUNKS = 6
#: `R5-R1b-6`：同一片段最多允许出现几次。超过它 ⇒ 这段文字是"同一段占位字重复出来的"。
NEGCTL_MAX_CHUNK_REPEATS = 3
#: `R5-R1b-6`：不同片段占全部片段的比例下限。堆长度的文字这一比值很低
#: （`'占位'*30` ⇒ 1/31）。
NEGCTL_MIN_CHUNK_RATIO = 0.5


def _content_chunks(text: str) -> tuple[set[str], int, int]:
    """把一段人话拆成"内容片段"。返回 `(不同片段集合, 片段总数, 出现最多的片段次数)`。

    为什么要拆"词 + 中文二元组"：`re.findall(r"\\w+", '改前会报出 network')` 只会给出
    两个片段（`改前会报出` / `network`）—— 中文没有空格，整句话会变成一个片段，
    于是"片段种类数"对中文文本几乎不成立。加上二元组之后，一句话有多少种说法就有
    多少个片段，而 `'啊'*60` 这种重复填充仍然只有 2 个（整串 + 一个二元组）。
    """
    import re as _re

    toks = _re.findall(r"\w+", text or "")
    chunks: list[str] = list(toks)
    for tok in toks:
        if len(tok) >= 3 and any("\u4e00" <= ch <= "\u9fff" for ch in tok):
            chunks.extend(tok[i:i + 2] for i in range(len(tok) - 1))
    if not chunks:
        return set(), 0, 0
    counts: dict[str, int] = {}
    for c in chunks:
        counts[c] = counts.get(c, 0) + 1
    return set(counts), len(chunks), max(counts.values())


def negative_control_problem(text: str) -> str:
    """    负控内容的判据：合格返回空串，否则返回"为什么不合格"。写入侧（`record_audit`）与判定侧（`clean_audits`）共用这一处实现 ——两处各写一份就会出现"写得进去、判不出来"，那是本项目记过的老毛病。
    判据（`R5-R1b-6` 改的就是这里）——四条都要满足：长度 ≥ :data:`NEGCTL_MIN_CHARS`（`H-1c` 的原始门，保留）；2. 出现 :data:`NEGCTL_MARKERS` 之一：拿什么去比（改前那一版 / 坏样本
    / 注入）；3. 出现 :data:`NEGCTL_OBSERVED_MARKERS` 之一：比出来看到了什么（`报红` / `被拒` / `失败` / `退出码`…）；4. 这段文字不是重复堆出来的（`_content_chunks`：不同片段 ≥:
    data:`NEGCTL_MIN_DISTINCT_CHUNKS`、同一片段重复 ≤:data:`NEGCTL_MAX_CHUNK_REPEATS` 次、不同片段占比 ≥ :data:`NEGCTL_MIN_CHUNK_RATIO`）。为什么第 1、2
    条之上还要第 3、4 条：旧判据只剩"长度 ≥ :data:`NEGCTL_MIN_CHARS` +标记词"，于是 `'改前' + '啊'*60`、`'negative ' + 'x'*60`、`'负控：（此栏无内容）' + '占位'*20 + ' 改前'`
    三种空话全部通过 —— 而"负控真的跑过一次"与"只写了标记词"在字符串上仍然不可区分。第 3 条要求写清"比出了什么"；第 4 条挡住"同一段占位字重复到够长"。门只加不减：四条缺一不可。口径说明（口径裁决②，2026-09-27）：
    本函数一度去掉过"长度 ≥ 40"这条门（为了让 `tests/test_noai_gate_audit_channel.py` 里那句 13 字符的夹具负控`'改前会报出 network'` 能写进去）。那个理由不成立：那个测试文件今天已经有 13
    条红（根因是它的写入侧夹具没给 `--audit-scope`，与负控判据无关；实测对着改前那一版`noai_gate.py` 跑也是 13 failed）。为一个本来就在红的夹具放宽判据，等于拿门的强度换一个假绿，所以长度门已恢复。代价如实登记：
    那个夹具现在连"负控不合格"这一层也过不去，预期由专门修 `tests/test_noai_gate_audit_channel.py` 的批次把夹具连同样例一起改成合规写法。残余（如实登记）：负控仍然只是自述 —— 写足这四条的人一样可以没跑过。
    判据能把"看起来像负控的空话"与"说清了怎么比、比出了什么"分开，不能证明它真跑过。
    """
    t = str(text or "").strip()
    low = t.casefold()
    has_how = any(m.casefold() in low for m in NEGCTL_MARKERS)
    has_seen = any(m.casefold() in low for m in NEGCTL_OBSERVED_MARKERS)
    distinct, total, top = _content_chunks(t)
    if len(t) < NEGCTL_MIN_CHARS:
        return (
            f"负控太短（{len(t)} < {NEGCTL_MIN_CHARS} 字符）：『未发现问题』只说明这个方法看不见问题。"
            "负控必须写清拿哪一条判据、去审改前那一版（`git show HEAD:<路径>`）或一个已知坏样本、"
            "以及看到了什么 —— 而 `n/a` 与真跑过一次负控在字符串上不可区分。"
        )
    if not has_how:
        return (
            "负控里没有任何『怎么比』的字样（必须出现 "
            + " / ".join(NEGCTL_MARKERS)
            + " 之一）：光说『没发现问题』不能证明这条判据有能力发现问题。"
        )
    if not has_seen:
        return (
            "负控里没有写出**比出来看到了什么**（必须出现 "
            + " / ".join(NEGCTL_OBSERVED_MARKERS)
            + " 之一）：『拿改前那一版去审』只是半句话，还得说清那个判据在改前那一版上"
            "报出了什么（`报红` / `缺失` / `被拒` / `退出码`…）。`R5-R1b-6` 实测："
            "`'改前' + 60 个占位字` 在只有『长度 + 标记词』两关的版本上通过。"
        )
    if not (len(distinct) >= NEGCTL_MIN_DISTINCT_CHUNKS
            and top <= NEGCTL_MAX_CHUNK_REPEATS
            and len(distinct) / max(1, total) >= NEGCTL_MIN_CHUNK_RATIO):
        return (
            f"负控只有 {len(t)} 字符，而且内容是重复堆出来的：不同片段 {len(distinct)} 种"
            f"（需要 ≥ {NEGCTL_MIN_DISTINCT_CHUNKS}）、同一片段最多出现 {top} 次"
            f"（上限 {NEGCTL_MAX_CHUNK_REPEATS}）、不同片段占比 {len(distinct)}/{total} —— "
            "这个形态就是 `'占位'*30` / `'x'*60` / `'负控：（此栏无内容）'+'占位'*20`："
            "长度够、信息量为零。负控要写清改前那一版被**哪一条判据**、以**什么读数**报红。"
        )
    return ""


def _norm_evidence_rel(rel: str) -> str:
    """`evidence_path` 的词法归一（`R1-AN-2`）：同一份证据的不同写法必须算同一份。

    实测的绕过（第 5 轮独立重审的攻击 1）：盘上物理只有一个证据文件，
    三次记录分别写 `temp/one.txt` / `./temp/one.txt` / `temp/./one.txt`（非指代：这三个都是示意路径）——
    三种写法解析到同一个文件、`evidence_sha256` 也相同，但旧的比较键是原始字符串
    （只 strip+casefold）⇒ 三条都算独立证据 ⇒ `distinct_dimensions` 从 1 变 3 ⇒ 门判 approved。

    这里做的是词法归一（不碰文件系统，因为 `LedgerEntry` 是纯数据、没有 repo）：
    反斜杠折成正斜杠、`posixpath.normpath` 折掉 `./` 与 `a/../`、去前导 `./`、casefold。
    真正的"盘上是不是同一个文件"由 `_check_audit_evidence` 用 `_resolve_evidence_file` 判定 ——
    两层分工：这一层保证计数不重复，那一层保证文件真的在。
    """
    import posixpath

    s = str(rel or "").strip().replace("\\", "/").replace("\\", "/")
    s = posixpath.normpath(s) if s else ""
    while s.startswith("./"):
        s = s[2:]
    return s.casefold()


# ------------------------------------------------------------------ 身份归一化：唯一一处 「这两个名字是不是同一个主体」在本模块里有且只有一处实现：`normalize_subject`。必须用它的五处：
# `LedgerEntry.distinct_auditors()`（机审的"不同审计者"数）、`LedgerEntry.distinct_reviewers`（人审的
# "不同 reviewer"数，`R5-R1b-3`：这里曾用原始字符串比较，于是把名字写成全角 / 带零宽 / 带尾空格就能
# 顶 2 名 reviewer 批准）、`record_audit` 的 `same_author` 判据（`c-16`）、`add_approval` 的重复签名提示、
# `_reviewer_identity_problem`（人审姓名的判据："归一化后还要剩字母/数字"）。
# 为什么是"唯一一处"（FC-03）：`H-1a` 给审计者标识加了归一化而人审通路一处都没有 ⇒ 同一个"两条通路必须 对称"的事实被写成两份实现，较松的那份成了绕过口；再写第三处也会以同样的方式松掉。
# 残余（如实登记，见 `temp/batchR1c-evidence.md` §残余）：跨文字系统的同形字（西里尔 `а` U+0430 vs 拉丁
# `a` U+0061）。刻意不做"只允许 ASCII"的限制 —— `reviewers` 姓名是人写的（中文姓名是正常形态），而判据五 的核心恰恰是"人必须亲自签字"；把真姓名判成非法是比同形字更坏的错。


#: `R6-R1d-7`：`R5-R1b-2` 的残余收口 —— 这些码位字形是空白（或干脆没有字形），却既不在 `Cf`/`Cc` 里、也不在
#: `Zs`/`Zl`/`Zp` 里，于是能原样贴在真名字后面：肉眼是同一个名字、归一化后是两个串，`_mentions_word` 的词边界
#: 也一律放行。逐条：`U+115F`/`U+1160` HANGUL CHOSEONG/JUNGSEONG FILLER（`Lo`，视觉宽度等于一个汉字、渲染为
#: 空）、`U+3164` HANGUL FILLER（同上，最常用的形态）、`U+FFA0` HALFWIDTH HANGUL FILLER（`NFKC` 之后折成
#: `U+1160`）、`U+2800` BRAILLE PATTERN BLANK（`So`，视觉上一个空位）、`U+00AD` SOFT HYPHEN（`Cf`，本来就
#: 折，列在这里是为了让清单自足）。口径边界：这是一份列举、不是"对所有不可见字符的判定"（真正的可见性判定
#: 要 Unicode 属性库，如 `East_Asian_Width` / `Default_Ignorable_Code_Point`，而本模块只用标准库
#: `unicodedata.category`）；列举可判定可复核，代价是以后可能出现新的同类码位（那时往元组里加一条即可， 判据仍是同一条）。它不做"只允许 ASCII"（那会误伤中文真姓名，见上一段注释）。
_INVISIBLE_FILLERS = ("\u115f", "\u1160", "\u3164", "\uffa0", "\u2800", "\u00ad")


def normalize_subject(name: str) -> str:
    """    身份字符串的归一化（`H-1a` / `R5-R1b-2` / `R5-R1b-3` / `R6-R1d-7`）：唯一一处实现。做五件事，每一件都对应一条实测过的绕过：`NFKC` ——
    全角/半角同形字（`ＲＥＡＵＤＩＴ５` ⇒ `REAUDIT5`）；2. 去掉 `Cf`（零宽/方向控制/BOM）与 `Mn` / `Me`（组合记号：变体选择符`U+FE0F`/`U+FE0E`、组合用圈
    `U+20E3`、组合用重音 `U+0301`）—— `R5-R1b-2`：只去 `Cf` 时，`reaudit5-H` 与 `reaudit5-H`+`U+FE0F` 是肉眼同一个名字却算出两名审计者，而
    `_mentions_word` 又认它们（`U+FE0F` 不属于 `[0-9a-z_]`）⇒写入侧不拒、判定侧把一个人算成两名；3. 控制字符（`Cc`）直接丢掉，`Zs`/`Zl`/`Zp`（各种空白与分隔符）
    折成空格；4. `R6-R1d-7`：再折掉 `_INVISIBLE_FILLERS` 里那组"有类别、没字形"的填充码位（`U+3164` HANGUL FILLER 一类）—— `R5-R1b-2` 的残余只是被收窄、
    没被收掉：`Cf`/`Mn`/`Me` 折得了，而 `Lo`/`So` 里的空字形码位仍原样保留 ⇒同一个可见名字后面贴一个 `U+3164` 仍旧算两名审计者。折掉它们是变严：两个原本"不等"的串并成一个，
    正是"同一个人不许自足门槛"要的效果；反向（把两个真名字并成一个）只可能发生在其中一个名字完全由这些空字形码位构成时，而那时归一化结果是空串，`_reviewer_identity_problem`与
    `record_audit` 的非空判据会把它拒掉（不是静默合并）；5. 空白折叠 + `casefold`（`'H'` / `'h '` / `'Ｈ'` 只能算一名）。

    只做这些可判定的字符级规则，不做"模糊匹配"（编辑距离、同形字表一类）——归一化必须是一条能一眼看懂的规则，否则"两名审计者"又变成一句可以商量的话。它挡不住跨文字系统的同形字（残余，缘由见上面那段注释）。
    """
    import unicodedata

    s = unicodedata.normalize("NFKC", str(name or ""))
    kept: list[str] = []
    for ch in s:
        cat = unicodedata.category(ch)
        # `Cf` = 零宽/方向控制/BOM；`Mn` = 非间距组合记号；`Me` = 包围组合记号；
        # `Cc` = C0/C1 控制字符。前三者都是"看得见的名字里看不见的东西"。
        if cat in ("Cf", "Mn", "Me", "Cc"):
            continue
        # `R6-R1d-7`：类别是 `Lo`/`So`、字形却是空的填充码位（清单见上面那个常量）。
        if ch in _INVISIBLE_FILLERS:
            continue
        kept.append(" " if cat in ("Zs", "Zl", "Zp") else ch)
    return " ".join("".join(kept).split()).casefold()


def _reviewer_identity_problem(name: str) -> str:
    """`Reviewer.name` 的判据：这个姓名能不能作为一个"人"的标识（合格 ⇒ 空串）。

    `R5-R1b-3`：人审通路的 `--reviewer` 曾经只查"非空"，于是同一个人把名字写成
    全角 / 带零宽 / 带尾空格，门就会打印"已有 3 名不同 reviewer 完成逐行走查"并批准。

    为什么是"至少要有一个字母或数字"而不是"只允许 ASCII"：`.noai-approvals.json`
    里的 `reviewers` 姓名是人写的，中文姓名是正常形态。要求 ASCII 会把真姓名
    判成非法（比它要挡的东西更坏）。这两个字符里任意一个不是 `Mn`/`Me`/`Cf`/空白/
    控制字符就够 —— 名字写成 `'​'`（只有一个零宽空格）那种形态仍然被拒。
    """
    key = normalize_subject(name)
    if not key:
        return (
            "姓名归一化后是空的（只剩零宽字符 / 组合记号 / 空白 / 控制字符）——"
            "这样的名字不是一个「人」的标识：它既不能与匿名区分，也不能与另一个人的同形写法区分"
        )
    if not any(ch.isalnum() for ch in key):
        return (
            f"姓名归一化后（{key!r}）不含任何字母或数字 —— 一个「人」的标识至少要有一个"
            "可读的字符，否则它无法与标点/符号噪声区分"
        )
    return ""


def _identity_same(a: str, b: str) -> bool:
    """两个身份字符串是不是同一个主体（用上面那唯一一处归一化）。

    空值（`''` / `'unknown'`）永远不算"同一个主体"：署名者未知时"审计者不能是署名者"
    这条判据无从适用，必须由 `H-1e` 的独立性声明接手，而不是在这里误命中。
    """
    ka, kb = normalize_subject(a), normalize_subject(b)
    if not ka or not kb or ka == "unknown" or kb == "unknown":
        return False
    return ka == kb


def _identity_word_set(name: str) -> frozenset[str]:
    """身份字符串的词集合：用来把 `'我是A'` 与 `'我是 A'` 认成同一句声明。

    为什么需要它：`normalize_subject` 折的是字符级形态，不折"分词"。
    `'我是子代理X'` 与 `'我是子代理 X'`（多一个空格）在字符层面是两串不同的字，
    在人读的那一层是同一句话。独立性声明是给人读的，所以这里按词比。
    """
    return frozenset(normalize_subject(name).split())


#: `R5-R1b-4`：独立性声明的内容下限 —— 与负控（`NEGCTL_MIN_CHARS`）同族的判定。
#: 旧判据只有 `bool(a.independence.strip())`，于是 `--independence x` 三条全过、approved。
INDEPENDENCE_MIN_CHARS = 10
#: 独立性声明里必须出现其中之一 —— 它回答的是"我相对于谁是独立的"。
INDEPENDENCE_MARKERS = (
    "不是同一主体", "非同一主体", "与作者无关", "未参与", "没有参与", "独立于", "独立性",
    "不是我写的", "非本次作者", "independent", "not the author", "did not write",
)


def _independence_problem(text: str) -> str:
    """`independence` 的判据（`R5-R1b-4` / `H-1e`）：合格返回空串。

    为什么不能只判 non-empty：`H-1e` 的设计目标是"把什么都没说变成说了什么"，
    但 `bool(s.strip())` 让 `'x'` 与一段真声明不可区分（实测：`--independence x`
    三条全部 `exit=0` 写进去，判定侧 approved/approved）。

    判据两条（都可判定）：长度 ≥ :data:`INDEPENDENCE_MIN_CHARS`，
    且出现 :data:`INDEPENDENCE_MARKERS` 之一（说清"我相对于谁是独立的"）。

    它仍然是自述：写下这句话的人一样可以说谎。判据能做的只是让"说了什么"
    变成"说清了对谁独立" —— 强度上限如实登记在 `temp/batchR1c-evidence.md`。
    """
    t = str(text or "").strip()
    if len(t) < INDEPENDENCE_MIN_CHARS:
        return (
            f"独立性声明太短（{len(t)} < {INDEPENDENCE_MIN_CHARS} 字符）："
            "`H-1e` 要的是『把什么都没说变成说了什么』，而一个 `x` 与一段真声明不可区分。"
            "写清『我是谁、相对于**谁**独立』（例如『我是子代理 X，与该条目的作者"
            "不是同一主体』）。"
        )
    low = t.casefold()
    if not any(m.casefold() in low for m in INDEPENDENCE_MARKERS):
        return (
            "独立性声明里没有说清**相对于谁**独立（必须出现 "
            + " / ".join(INDEPENDENCE_MARKERS)
            + " 之一）：『我审过了』不是独立性声明。"
        )
    return ""


#: 从被审对象源码里抽标识符（`R1-AN-4` ③）：scope 里的 token 必须真的是"这个文件里的符号"
_IDENT_RE = None


def _assignment_target_names(node: object) -> set[str]:
    """`a = …` / `x, y = …` / `self.z = …` 左侧出现的名字（递归，`ast` 节点入参）。"""
    import ast as _ast

    if isinstance(node, _ast.Name):
        return {node.id}
    if isinstance(node, _ast.Attribute):
        return _assignment_target_names(node.value)
    if isinstance(node, _ast.Subscript):
        return _assignment_target_names(node.value)
    if isinstance(node, (_ast.Tuple, _ast.List)):
        out: set[str] = set()
        for elt in node.elts:
            out |= _assignment_target_names(elt)
        return out
    return set()


def _identifiers_of(text: str) -> set[str]:
    """    被审对象里出现的标识符集合（`R5-R1b-5` 修正后的口径）。修的是什么：这里曾经是纯词法扫描——`re.finditer(r"[A-Za-z_][A-Za-z0-9_.]{2,}")`把 Python
    关键字与内建名也算成标识符（实测 `import` / `return` / `int` / `def` /`math` 全算），于是
    `--audit-scope 'import return int'` 能过`_evidence_cross_check` ③ —— 那三个词与"这次审计覆盖了哪些符号"毫无关系，而每个 `.py` 文件里都有它们。
    判据的强度因此从"自称覆盖的符号必须落在那个文件上"退化成"必须落在那类文件都会有的词上"。现在的口径分两层：被审对象是能被 `ast` 解析的 Python ⇒ 取定义处的名字：`def` / `class` /
    `import` / `import … as` / 赋值目标（含 `self.z` 的属性名）。`scope` 里要求"这个文件真的定义了它"比"这个文件反正有这个词"强得多。
    2. 解析不了（非 `.py`、或语法不完整）⇒ 退回词法扫描，但排除
    `keyword.kwlist` 与 `builtins`。它比第 1 层弱，却比原来那版强：至少 `import` / `return` / `int` 不再算标识符。

    调用方（`_evidence_cross_check` ③ 与 `dimension_independence_problem` 判据 2）仍然只要求"至少一个 token 落在这个集合上"—— 逐条要求会把
    `scope`写成"全文"/"小节名"的合规形态一并拒掉。
    """
    import ast as _ast
    import builtins as _builtins
    import keyword as _keyword
    import re as _re

    src = text or ""
    try:
        tree = _ast.parse(src)
    except (SyntaxError, ValueError):
        tree = None
    if tree is not None:
        names: set[str] = set()
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
                names.add(node.name)
                args = getattr(node, "args", None)
                if args is not None:
                    for a in (*args.posonlyargs, *args.args, *args.kwonlyargs):
                        names.add(a.arg)
                    if args.vararg is not None:
                        names.add(args.vararg.arg)
                    if args.kwarg is not None:
                        names.add(args.kwarg.arg)
            elif isinstance(node, _ast.Import):
                for alias in node.names:
                    names.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, _ast.ImportFrom):
                for alias in node.names:
                    names.add(alias.asname or alias.name)
            elif isinstance(node, _ast.Assign):
                for tgt in node.targets:
                    names |= _assignment_target_names(tgt)
            elif isinstance(node, (_ast.AnnAssign, _ast.AugAssign)):
                names |= _assignment_target_names(node.target)
            elif isinstance(node, _ast.arg):
                names.add(node.arg)
        return names

    banned = set(_keyword.kwlist) | set(dir(_builtins))
    return {
        m.group(0)
        for m in _re.finditer(r"[A-Za-z_][A-Za-z0-9_.]{2,}", src)
        if m.group(0) not in banned
    }


#: `scope` 里被当作"文件名"而不是"符号名"的 token 后缀。
#: `--audit-scope 'target.py VALUE bump'` 这种写法里，`target.py` 是被审对象的落点，
#: 不是"这次覆盖了哪个符号" —— 它不该参与"观察面是否独立"的判定。
_SCOPE_PATH_SUFFIXES = (".py", ".json", ".md", ".txt", ".jsonl", ".toml", ".cfg", ".ini")


def _scope_tokens(scope: str) -> list[str]:
    """`scope` 里的符号 token（长度 ≥3、逗号折空格）—— 与 `_evidence_cross_check` ③ 同口径。"""
    return [t for t in str(scope or "").replace(",", " ").split() if len(t) >= 3]


def _observation_tokens(
    scope: str,
    target_text: str = "",
    *,
    reuse_across: Sequence[str] | None = None,
    drop_self_scope: bool = False,
) -> list[str]:
    """    一条 `scope` 里算作"观察面"的 token（`R6-R1d-5` 修正后的口径）。

    两层过滤，两层都是变严：丢掉以文件后缀结尾的 token（`target.py` 是"被审对象的落点"，不是"覆盖了哪个
    符号"）—— 原口径，见 `_SCOPE_PATH_SUFFIXES`；
    2. `target_text` 给得出时，只保留落在被审对象标识符集合上的 token
    （`_identifiers_of(target_text)`）：与观察对象无关的自由文本（例如审计者把自己上传的标识写进 `scope`）从此不参与"观察面是否两两不相交"的计数。为什么第 2 层必须有：
    原口径下"两两不相交"可以由与观察对象无关的 token 撑开（实测 `R6-R1d-5` 的 N2 段：三条 `scope` 写成 `target.py alpha R1d-N2a` /`... R1d-N2b` /
    `... R1d-N2c`，每个名字 token 都是审计者自己的标识 ⇒`independent_observation_surfaces = 3`、approved；把名字 token 去掉后同一份台账的观察面数掉到
    1）。判据 3（`dimension_independence_problem`）与写侧的`_evidence_cross_check` ③ 仍各要求"至少一个 token 真实"，所以第 2 层不会放过不合规的
    `scope`，它只是让报数不再被无关 token 撑大。`target_text` 为空时（例如只拿到几条审计对象、没读盘）退回一个自指的弱口径：只保留出现在 `reuse_across`（兄弟 `scope` 的并集）
    里的 token。依据是"至少一个token 落在被审对象上"这条判据在判定口径下对每一条审计都要成立 ——一个 token 如果连任何一条审计都没复用，它就不是一个可比的观察落点，凭什么用它去撑开"两两不相交"。
    为什么不能"读不到就不过滤"：那会让报数与判定用两套口径，而本仓反复记过"同一个概念两份实现"的代价。

    `drop_self_scope=True`（`R7-R1d-1`）：先把本条自己的 `scope` 从`reuse_across` 里剔掉，再算复用集合。这一条是必需的，否则那支退路是恒等不过滤—— 调用点传进去的
    `reuse_across` 都含本条自己的 `scope`（它们是从 `counted_audits`的 `a.scope` 现取的），于是 `toks & reused == toks`，
    "只保留被别的审计也用到的token"这句承诺永远是空话（`R7-R1d-1` 实测：`reuse_across` 只给兄弟时是 `[]`，含自己时是 `['alpha', 'r7-name-1']`）。剔的判据是按串相等：
    同一条 `scope` 字符串出现两次时（两条审计逐字相同）也一并剔掉 —— 那种形态下"另一个 token 来自谁"本来就分不清，剔掉是保守的那一侧（它只会让面数变小，而判据 2 是"不足才报红"）。
    """
    toks = {
        t.casefold() for t in _scope_tokens(scope)
        if not t.casefold().endswith(_SCOPE_PATH_SUFFIXES)
    }
    if target_text:
        # 一次 `_identifiers_of`、一次 casefold（逐 token 重算是 O(n*m)，而这里只是集合过滤）
        idents = {i.casefold() for i in _identifiers_of(target_text)}
        return sorted(t for t in toks if t in idents)
    if reuse_across is None:
        return sorted(toks)
    if drop_self_scope:
        reuse_across = [s for s in reuse_across if str(s) != str(scope)]
    reused = {
        t.casefold() for other in reuse_across for t in _scope_tokens(other)
        if not t.casefold().endswith(_SCOPE_PATH_SUFFIXES)
    }
    return sorted(toks & reused)


def _read_target_text(path: str, repo: str | Path | None) -> str:
    """把被审对象读成文本；读不到 ⇒ 空串（`R7-R1d-1`）。

    为什么要抽成一个函数、并在 `evaluate_approval` 里提前调一次：那几处
    "观察面报数"此前用的是没有目标文本的弱口径（`reuse_across` 自指），而判定口径用的是
    读到的文本 ⇒ 同一份报告里两个分支两种口径（能批准的那一支过滤、未批准的那一支不过滤）。
    读到一次、两处共用，是"同一个概念只有一处实现"的落地。

    读不到不抛：判定侧把它当"没查成"（判据 3 会因为标识符集合为空报红），
    不在这里折叠成"没问题"。
    """
    try:
        return _target_path(path, Path(repo) if repo is not None else project_root()).read_text(
            encoding="utf-8", errors="replace"
        )
    except (OSError, LedgerError):
        return ""


def _observation_key(
    scope: str,
    target_text: str = "",
    *,
    reuse_across: Sequence[str] | None = None,
    drop_self_scope: bool = False,
) -> str:
    """    一条审计的观察面标识（`R5-R1b-1`）：归一化后排序去重的符号 token 字符串。

    为什么需要它：`counted_audits` 的键 `(evidence_path, evidence_sha256)` 只能证明"这不是同一个文件"，挡不住"同一份观察复制成 N 份、每份改一个字节"（实测：
    一名审计者用三份只差尾部空格的副本 + 3 个自填 `dimension` 就凑够了 3 个"维度"）。

    "观察面"是这条通路里唯一能机器判定的独立声明 —— `scope`。同一名审计者、同一次观察、同一个 `scope`，换一个 `dimension` 字符串不产生第二次独立观察。只把 token
    集合当签名（顺序无关），`VALUE bump` 与 `bump VALUE` 是同一个面。

    `target_text` / `reuse_across` / `drop_self_scope`：口径与理由见`_observation_tokens`（`R6-R1d-5` / `R7-R1d-1`）。
    """
    return " ".join(_observation_tokens(scope, target_text, reuse_across=reuse_across,
                                        drop_self_scope=drop_self_scope))


def _disjoint_face_count(
    audits: Sequence["ReviewAudit"],
    target_text: str = "",
    *,
    reuse_across: bool = False,
) -> int:
    """    计入门槛的审计里，两两不相交的观察面最多能挑出几个（口径裁决①）。

    这就是"几次独立观察"的可判定读数。为什么不能只数"不同的观察面字符串"：`VALUE bump` 与 `VALUE` 是两个不同的字符串，却是两个相交的集合（后者是前者的子集）—— 它们是同一批符号的两种写法，
    不是两次独立观察。

    贪心按集合大小升序取（升序贪心对"最大两两不相交子族"是可行的启发式：小集合更不容易与后面相交）。它只用于报数与判定阈值，不追求最优性 ——判据要的是"能不能挑出 ≥ 维度数 个"，贪心给出的下界对拒/放两侧都是保守的：
    挑不出来 ⇒ 确实不够；挑出来了 ⇒ 至少这么多。

    `target_text`（可选）：观察面只由被审对象里真实存在的标识符构成（`R6-R1d-5`）。`reuse_across=True`：目标读不到时启用"自指"弱口径（见 `_observation_tokens`）
    ——此时本条自己的 `scope` 会被剔掉（`R7-R1d-1`：不剔就等于恒等不过滤）。
    """
    seq = list(audits)
    scopes = [a.scope for a in seq]
    faces = {
        frozenset(k.split())
        for k in (
            _observation_key(a.scope, target_text, reuse_across=scopes, drop_self_scope=True)
            for a in seq
        )
        if k
    }
    chosen: list[frozenset] = []
    # 排序键 `(大小, 集合本身)`：确定性（不依赖输入的遍历顺序），且小集合优先。
    # `chosen` 里放的是具体的 face 而不是散列的 key —— 精确、且与重复 face 无关。
    for face in sorted(faces, key=lambda f: (len(f), sorted(f))):
        if not any(face & c for c in chosen):
            chosen.append(face)
    return len(chosen)


def dimension_independence_problem(
    audits: Sequence["ReviewAudit"],
    target_text: str,
    *,
    require: int = MIN_DISTINCT_DIMENSIONS,
) -> str:
    """    `MIN_DISTINCT_DIMENSIONS` 的判据：那几个"维度"必须来自各自独立的观察面。
    它修的是 `R5-R1b-1`：`MIN_DISTINCT_DIMENSIONS` 数的是提交者自填的 `dimension`（受控词表里的一员），`c-17` 的 `counted_audits` 只挡"同一份文件重复计数"（键 = 归一化路径 + 内容
    hash），挡不住"同一份观察复制 N 份、每份改一个字节"（hash 各不相同）⇒ 一名审计者单独就能供满 3 个维度（`temp/reaudit5-R1b-solo.txt` 对照 B ⇒ approved），门槛退化成"≥2 个不同名字的字符串"。
    四条判据都机器可判定（合格返回空串）。0 一名审计者不能独占门槛：贡献维度最多的那一名，它的维度数超过 `max_share = max(1, ceil(require / 2))` ⇒ 报红（`require = 3` 时一人至多 2 个 ⇒ 3
    个维度必须来自 ≥2 名审计者；理由同"人审为什么要 2 名 reviewer"）。`R6-R1d-4` 修正：此前只挡完全独占（`len(owned) == len(dims)`）；现在直接判 `len(owned) > max_share` ——
    这是变严。
    1 同一名审计者的多条记录不许共用同一个观察面：观察面 = `_observation_key(scope)`（`scope` 归一化后的符号 token 集合）—— 同一个人、同一批符号、换一个 `dimension` 字符串不产生第二次独立观察。
    2 计数的维度必须落在两两不相交的观察面上（口径裁决①，2026-09-27）：把每个 `scope` 归一化成符号集合，数出最多能挑出多少个两两不相交的观察面（贪心、按集合大小升序），要求 ≥ 维度数 —— 比"数不同字符串"强：`VALUE bump` 与
    `VALUE` 是两个字符串、两个相交集合，算一次。`R6-R1d-5` 修正：观察面只由被审对象里真实存在的标识符构成（`_observation_tokens(scope, target_text)`）——
    否则与观察对象无关的自由文本就能把"两两不相交"撑开，报数 `independent_observation_surfaces` 会照那个虚高的面数说话。
    3 落点真实：至少一条记录的 `scope` token 是被审对象里真实存在的标识符（`_identifiers_of(target_text)`）；只要求至少一条（逐条会把 `scope` 只有"全文"这类短词的合规写法拒掉，而写入侧
    `_evidence_cross_check` ③ 已逐条要求）。目标文本读不到时（`target_text=""`）这里报红 ⇒ 整体 `unknown`，而不是"集合为空所以没人违规"。
    `scope` 全空的记录不参与 1/2/3（没有声明就没有"共用观察面"这回事，那三条此时真空，既不该红也不该放行 —— 写侧 `--audit-scope` 必填，全部为空只可能出现在手改台账里）；判据 0 不依赖 `scope`，始终生效。新正控是
    `temp/batchR1c-pos2.py`；`temp/reaudit5-R1b-pos.py` 原样保留（R1b 的历史证据），但它现在是弱场景、被判 unapproved 是预期。
    """
    counted = list(audits)
    dims = {a.dimension for a in counted}
    if len(dims) <= 1:
        return ""   # 只有一个维度：没有"两个维度是否独立"这个问题（门槛那一条另判）

    # ---- 0. 一名审计者不能独占门槛（`R6-R1d-4`：直接判 `owned` 是否超过上限）
    #
    # 上限 `max_share` 与文案里承诺的那个数是同一个：`require = 3` ⇒ 每名审计者至多 2 个。
    # 这里刻意不先判 `len(dims) > max_share` 再回头比 `owned` —— 那个前置条件
    # 在 `require=3` 时恒真（3 > 2），于是"算出来的上限"从没用在判定上。
    max_share = max(1, (require + 1) // 2)
    by_auditor: dict[str, set[str]] = {}
    for a in counted:
        if a.dimension:
            by_auditor.setdefault(normalize_subject(a.auditor), set()).add(a.dimension)
    if by_auditor:
        owner, owned = max(by_auditor.items(), key=lambda kv: (len(kv[1]), kv[0]))
        if len(owned) > max_share:
            # 两档文案：完全独占（`R5-R1b-1` 的形态）与"超过上限但没独占"（`R6-R1d-4`）
            # 是同一条判据的两种读数，分开说清楚，但用同一个理由码。
            if len(owned) == len(dims):
                shape = (
                    f"计入门槛的 {len(counted)} 条审计覆盖了 {len(dims)} 个不同 `dimension`，"
                    f"但它们**全部来自同一名审计者**（{owner!r}）—— 门槛是 {require} 个维度，"
                    "而 1 名审计者与『作者自己再看一遍』在结构上无法区分（与『人审为什么要 2 名 "
                    "reviewer』同一条理由）。实测（`R5-R1b-1`）：一名审计者用三份只差尾部空格的"
                    "证据副本 + 3 个 `dimension` 就供满了『≥3 个维度』，再补一名只交 1 条的"
                    "审计者即可 2×3 放行。"
                )
            else:
                shape = (
                    f"计入门槛的 {len(counted)} 条审计覆盖了 {len(dims)} 个不同 `dimension`，"
                    f"但其中 {len(owned)} 个来自同一名审计者（{owner!r}）—— "
                    "把维度分摊给多名审计者、只要另一名拿到至少一个维度，这条就曾经永不触发"
                    "（`R6-R1d-4` 的最小复现：2 名审计者 × 4 个维度、每人 2 个、scope 两两"
                    "不相交 ⇒ 改前 approved）。"
                )
            return (
                f"同一名审计者供给了太多计入维度：{shape}要求：每一名审计者至多贡献 "
                f"{max_share} 个计入维度 ⇒ {require} 个维度必须来自 ≥2 名审计者，"
                "且没有任何一名超过这个上限。"
            )

    # ---- 1. 同一名审计者的多条记录不许共用同一个观察面
    by_auditor_surfaces: dict[str, list[str]] = {}
    scopes_all = [a.scope for a in counted]
    for a in counted:
        key = _observation_key(a.scope, target_text, reuse_across=scopes_all,
                               drop_self_scope=True)
        if key:
            by_auditor_surfaces.setdefault(normalize_subject(a.auditor), []).append(key)
    for who, keys in by_auditor_surfaces.items():
        dup = sorted({k for k in keys if keys.count(k) > 1})
        if dup:
            return (
                f"审计者 {who!r} 的 {len(keys)} 条计入记录共用了同一个观察面"
                f"（`scope` 归一化后都是 {dup[0]!r}）—— `dimension` 是自填标签，"
                "同一次观察换一个标签不产生第二次独立观察。实测（`R5-R1b-1`）："
                "一名审计者用三份只差尾部空格的证据副本 + 3 个 `dimension` 就凑满了"
                "『≥3 个维度』。要求：同一名审计者每个计数的维度都要有自己的 `scope` 落点"
                "（两两不同的符号集合）。"
            )

    # ---- 2. 计数的维度必须落在两两不相交的观察面上（口径裁决①） # 判据 1 只看同一名审计者内部的重复；这一条看整体、且比"数不同的 face"更强：它数的是"能挑出多少个
    # 两两不相交的观察面"（贪心：按 face 大小升序取，与已选集合相交就跳过），并要求这个数 ≥ 计数的维度数。
    # 不能只数"不同的 face"：`VALUE bump` 与 `VALUE` 是两个不同字符串，却是两个相交的观察面（后者是前者的
    # 子集）—— 只数字符串个数会把"同一批符号换个写法"算成两个独立观察。逐字落实裁决例子里"三条 scope 的 # 标识符集合两两不相交"：把每个 face 当成符号集合，3 个计数维度要撑起一个反链，相交的观察面不算两次
    # 独立观察、与它的大小无关。代价（裁决① 明确接受）：`temp/reaudit5-R1b-pos.py` 那条弱正控（3 名审计者
    # 共用同一句 scope）只给出 1 个观察面 ⇒ 判 unapproved（三条审计其实是同一个面数了三次）；新正控
    # `temp/batchR1c-pos2.py` 的 3 条各有两两不相交的落点。`R6-R1d-5`：观察面只由被审对象里真实存在的
    # 标识符构成 —— 无关 token 不许把"两两不相交"撑开（口径与实测见 `_observation_tokens`）。
    face_sets = [
        frozenset(k.split())
        for k in (
            _observation_key(a.scope, target_text, reuse_across=[b.scope for b in counted],
                             drop_self_scope=True)
            for a in counted
        )
        if k
    ]
    if face_sets:
        chosen = _disjoint_face_count(counted, target_text, reuse_across=True)
        if chosen < len(dims):
            return (
                f"计入门槛的 {len(counted)} 条审计覆盖了 {len(dims)} 个不同 `dimension`，"
                f"但它们只给出 {len(face_sets)} 个观察面、其中**两两不相交的只有 {chosen} 个**"
                f"（{sorted(' '.join(sorted(f)) for f in face_sets)}）—— `dimension` 是自填标签，"
                "同一批符号换一个写法（`VALUE bump` 与 `VALUE`）不产生第二次独立观察，"
                "把维度分摊给多名审计者也一样。实测（`R5-R1b-1`）：一名审计者用三份只差尾部"
                "空格的证据副本 + 3 个 `dimension` 就凑满了『≥3 个维度』。要求：每个计数的维度"
                "都要有自己的 `scope` 落点，且这些落点**两两不相交**，至少 "
                f"{len(dims)} 个。"
            )

    # ---- 3. scope 的落点必须是被审对象里真实存在的符号
    toks = [t for a in counted for t in _scope_tokens(a.scope)]
    if toks:
        idents = _identifiers_of(target_text)
        if not any(t in idents for t in toks):
            shown = ", ".join(sorted(set(toks))[:4])
            return (
                f"`scope` 里的符号（{shown}…）没有一个是被审对象里真实存在的标识符 —— "
                "『这次审计覆盖了哪些符号』必须落在**那个文件**上，不是落在语言关键字"
                "（`import` / `return`）或内建名（`int`）上（`R5-R1b-5`）。"
                + ("（判定时读不到被审对象 ⇒ 标识符集合为空 ⇒ 没查成）" if not target_text else "")
            )
    return ""


def _parse_audit_at(at: str) -> _dt.datetime | None:
    """`at` 字符串 ⇒ 带时区的 `datetime`；读不出 ⇒ `None`（唯一一处解析实现）。

    与 `audit_timestamp_problem` 的"可解析"那一档共用同一段规则，
    这样"单条能不能解析"与"整串是不是非递减"（`R6-R1d-3`）不会在两处各有一套口径
    —— 本仓记过的形态就是"同一个概念两份实现"：改了一处、另一处继续按旧口径走。

    无时区的串按 UTC 读（不猜本地时区）：与 `audit_timestamp_problem` 逐字一致。
    """
    raw = str(at or "").strip()
    if not raw:
        return None
    text = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=_dt.timezone.utc)


def audit_timestamp_problem(at: str, *, now: _dt.datetime | None = None) -> str:
    """    `at` 的判据（`R5-R1b-7`）：时间戳必须可解析、且不许来自未来。合格 ⇒ 空串。

    为什么要有它：`at` 曾经是整个通路里唯一一个"写了就信、读回不校验"的字段（实测：把门的时钟拨到 2099 写进去，`record_audit` 照收，判定侧从不读它）。
    台账里"谁在什么时候走查的"这句话因此在时间维度上没有下限 —— 对"这次审计是否发生在本轮冻结窗口内"这类问题，台账给不出可判定的答案。判据刻意只有两条（其余窗口留给外部锚，不在这里造）：必须能被
    `datetime.fromisoformat` 解析（ISO-8601；容忍末尾 `Z`）；
    - 不许晚于 `now`（判定时刻）—— 未来时间戳只可能来自时钟错乱或手改台账，
    两种都不该被读成"这次走查确实发生过"。刻意不设"多久算太旧"：台账最早的一批是项目开工时写的，`now - at` 是多少"合理"没有外部锚可依（`git` 提交时间也不覆盖手写台账），
    硬定一个窗口会造出"老记录一夜之间全部变红"的假警报，而真实处置（重跑一次走查）毫无必要。所以这里只判"能不能读、是不是未来"，并在 `--check-approvals` 的输出里把
    `at`如实报出来（读报告的人自己看时间）。`R6-R1d-3`：单条判据管不到次序 —— 三条审计的 `at` 可以整体倒挂（先记 03:00、再记 02:00、最后记 01:00）而每一条都"可解析且不在未来"。
    次序那一半在 :func:`audit_timestamps_not_monotonic`（对整串 `audits` 判），并在输出里用"审计者自报的时间戳"这个措辞说清它是什么。
    """
    raw = str(at or "").strip()
    if not raw:
        return "`at` 为空 —— 没有时间戳的走查记录无法回答『这是什么时候发生的』"
    parsed = _parse_audit_at(raw)
    if parsed is None:
        return (
            f"`at` 不是一个可解析的 ISO-8601 时间戳：{raw!r}"
            "（例如 `2026-09-27T00:55:36+08:00`）—— 解析不了就没法核对它是不是本轮发生的"
        )
    reference = now if now is not None else _dt.datetime.now().astimezone()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=_dt.timezone.utc)
    if parsed > reference:
        return (
            f"`at`（{raw}）落在**未来**（判定时刻 {_now_iso(reference)}）——"
            "未来时间戳只可能来自时钟错乱或手改台账，两者都不该被读成"
            "『这次走查/审计确实发生过』。`R5-R1b-7` 实测：把门的时钟拨到 2099 照收。"
        )
    return ""


def audit_timestamps_not_monotonic(
    audits: Sequence["ReviewAudit"],
    *,
    now: _dt.datetime | None = None,
) -> str:
    """    一串审计的时间戳必须非递减（按盘上顺序）。合格 ⇒ 空串（`R6-R1d-3`）。

    为什么单条判据不够（`audit_timestamp_problem` 只管"能不能解析 / 是不是未来"）：三条审计的时间戳可以整体倒挂（先记 03:00、再记 02:00、最后记 01:00）而每一条都合规 —— 门照样
    `approved`，而输出里那串 `audit_timestamps` 会按写入顺序打成递减。对"这些审计是不是各自独立发生在本轮冻结窗口内"这类问题，倒挂的时间戳给不出可判定的答案（三条都在窗口内、
    却不必发生在任何真实次序上）。

    口径（写清楚，因为它决定了这条判据能说什么）：判的是记录在台账里的次序，而记录次序就是写入次序（`record_audit` 只追加）。所以"非递减" = "后写的那一条不早于先写的那一条"。
    它不证明这些时间戳真的发生过（那是自报字段），它只让"整体倒挂"这个形态不再无声通过。判断不了的记录（`at` 读不出）跳过：那是 `audit_timestamp_problem` 那一层的事，两层各报各的，
    不在这一层折叠成"乱序"。
    """
    ordered = list(audits)
    ref = now if now is not None else _dt.datetime.now().astimezone()
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=_dt.timezone.utc)
    parsed: list[_dt.datetime] = []
    for a in ordered:
        t = _parse_audit_at(a.at)
        if t is None:
            continue
        parsed.append(t if t.tzinfo is not None else t.replace(tzinfo=_dt.timezone.utc))
    for prev, cur in zip(parsed, parsed[1:]):
        if cur < prev:
            return (
                f"审计时间戳在台账里的次序**倒挂**：`{_now_iso(prev)}` 之后又记了 "
                f"`{_now_iso(cur)}`（同一套 `--record-audit` 通路只追加，后写的理应不早于"
                "先写的）—— 时间戳是审计者**自报**的，倒挂说明它们不能当作"
                "『各自独立发生在本轮窗口内』的次序证据（`R6-R1d-3`）。"
                "处理：确认这几条审计的真实先后 ⇒ 必要时重跑审计并重新 `--record-audit`。"
            )
    return ""


def audit_timestamp_report(audits: Sequence["ReviewAudit"]) -> list[dict]:
    """`--check-approvals` 输出的 `audit_timestamps`：自报时间戳 + 门判到了什么。

    `R6-R1d-3` 的修法 (b) 落在这一处：只给一串裸时间戳，读报告的人会以为
    "谁在什么时候走查的"从此可核；实际能核的只有"可解析、不在未来、次序不倒挂"。
    所以每个元素都带 `basis`（这一条永远是 `self_reported`）与 `gate_checked`
    （门真的判了哪三件事），措辞与 `authored_basis=inferred` 那套 caveat 同族。

    为什么是"列表"而不是"改成一句更长的话"：`audit_timestamps` 已经是 JSON 字段，
    读它的是脚本（`REAUDIT5-R1b` 的探针就按列表读）。改类型会打断那些读数，
    所以保留列表形态、把 caveat 放进每个元素里。
    """
    return [
        {
            "at": a.at,
            "basis": "self_reported",
            "gate_checked": "parseable + not_in_future + non_decreasing_order",
        }
        for a in audits
    ]


def _mentions_word(haystack_low: str, needle_low: str) -> bool:
    """词边界包含判定（`R1-AN-4` ①）。

    裸 `in` 会把 `auditor='A1'` 判成"证据里提到了 A1" —— 因为 `a1` 恰好出现在
    sha256 十六进制串 `3225fbda26b1cbba…` 里。用 `\b` 边界就不会：
    那一长串十六进制是一个词，里面没有词边界。
    """
    import re as _re

    if not needle_low:
        return False
    return _re.search(r"(?<![0-9a-z_])" + _re.escape(needle_low) + r"(?![0-9a-z_])",
                      haystack_low) is not None


def _evidence_cross_check(a: "ReviewAudit", text: str, entry_sha: str,
                          target_text: str = "") -> list[str]:
    """把一条审计的声明与证据文件的内容交叉核对（`H-1b`）。

    三项缺一不可，因为它们是这条通路剩下的全部信用来源：
    ① auditor 标识出现在证据里（这条证据是这个主体产出的）；
    ② 所审版本的 sha（或其 12 位前缀）出现在证据里（这条证据是审这一版产出的）；
    ③ `scope` 里的某个符号出现在证据里（这条证据覆盖了它自称覆盖的东西）。
    """
    problems: list[str] = []
    low = text.casefold()

    who = normalize_subject(a.auditor)
    # `R1-AN-4` ①：词边界匹配，不是裸子串（`A1` 不许被 sha 十六进制偶然满足）
    if who and not _mentions_word(low, who):
        problems.append(
            f"[{a.auditor}/{a.dimension}] 证据文件里没有以**独立词**形态出现审计者标识 {a.auditor!r}"
            " —— 证据与主体对不上（裸子串还会被 sha 十六进制串偶然满足）"
        )

    sha = str(a.audit_started_sha256 or a.sha256 or "").strip().casefold()
    if sha and sha[:12] not in low:
        problems.append(
            f"[{a.auditor}/{a.dimension}] 证据文件里没有出现所审版本的 sha 前缀 {sha[:12]}"
            " —— 证据与版本对不上（『审的是 A 版、记账时盘上已是 B 版』正是这条要堵的）"
        )

    # `R1-AN-4` ③：scope 的 token 必须真的是被审对象里的符号，而不是"到处都有的短词"。
    # 旧判据只要求 token 出现在证据里 ⇒ `scope='the'` 也能过（因为证据正文里几乎一定有 the）。
    tokens = [t for t in str(a.scope or "").replace(",", " ").split() if len(t) >= 3]
    if not tokens:
        problems.append(f"[{a.auditor}/{a.dimension}] `scope` 里没有一个长度 ≥3 的符号名")
    else:
        idents = _identifiers_of(target_text)
        hit_target = [t for t in tokens if t in idents]
        if not hit_target:
            problems.append(
                f"[{a.auditor}/{a.dimension}] `scope` 里的符号（{', '.join(tokens[:4])}…）"
                "没有一个是被审对象里真实存在的标识符 —— 自称覆盖了什么必须落在**那个文件**上，"
                "不是落在证据正文里（`the` 这种词到处都是，等于没说）"
            )
        elif not any(t.casefold() in low for t in tokens):
            problems.append(
                f"[{a.auditor}/{a.dimension}] `scope` 里的符号（{', '.join(tokens[:4])}…）"
                "没有一个出现在证据文件里 —— 自称覆盖的东西在证据里找不到"
            )

    # `R1-AN-4`（负控侧）：证据正文必须提到负控，否则"每条都带负控"没有留痕
    # （`'n/a' + 填充 + 'HEAD'` 凑够 40 字符就能过 `negative_control_problem`，
    #  这一条要求审计者的原始输出里真的能看见负控那一跑）。
    if not any(k in low for k in ("negative control", "negative_control", "负控", "改前",
                                  "injected", "注入")):
        problems.append(
            f"[{a.auditor}/{a.dimension}] 证据正文里没有提到负控（`negative control` / `负控` / "
            "`改前` / `注入` 之一）—— 『每条都带负控』必须在那份原始输出里看得见"
        )
    return problems


def _parse_audit(item: object, *, where: str) -> ReviewAudit:
    """解析一条审计记录。结构不合规一律抛 `LedgerError`（⇒ unknown）。

    与 `_parse_reviewer` 的对称之处：必需字段缺了就抛，不猜。
    审计记录少一个必需字段（尤其 `negative_control` 与 `sha256`）会让"未发现问题"变成空话，
    那正是这条通路最危险的失败形态 —— 所以它比 `Reviewer` 校验得更严。
    """
    if not isinstance(item, dict):
        raise LedgerError(f"{where} 不是一个 JSON 对象（收到 {type(item).__name__}）")

    def _req(field: str) -> str:
        v = item.get(field)
        if not isinstance(v, str) or not v.strip():
            raise LedgerError(
                f"{where} 缺少非空的 `{field}` —— "
                "审计记录的 `auditor`/`dimension`/`sha256`/`evidence`/`negative_control` 都是必需字段"
            )
        return v.strip()

    dim = _req("dimension")
    if dim not in AUDIT_DIMENSIONS:
        raise LedgerError(
            f"{where} 的 `dimension` 不在受控词表里：{dim!r}（合法：{list(AUDIT_DIMENSIONS)}）"
            "—— 『多维度』必须是可数的，否则与『多看两眼』不可区分"
        )
    sha = _req("sha256")
    if not _is_sha256_hex(sha):
        raise LedgerError(f"{where} 的 `sha256` 不是 64 位小写十六进制：{sha!r}")
    # `evidence_sha256` 与 `sha256` 一样是必需字段：没有它，`evidence` 就只是一句话，
    # 而"一句话"谁都能写（`temp/verify-audit-forge.txt` 实测过：编一个不存在的路径也通过）。
    ev_sha = _req("evidence_sha256")
    if not _is_sha256_hex(ev_sha):
        raise LedgerError(
            f"{where} 的 `evidence_sha256` 不是 64 位小写十六进制：{ev_sha!r}"
            "（它是证据文件内容的 hash，门在判定时会重算那个文件来核对）"
        )
    findings_raw = item.get("findings", [])
    if not isinstance(findings_raw, list):
        raise LedgerError(f"{where} 的 `findings` 不是数组（收到 {type(findings_raw).__name__}）")
    return ReviewAudit(
        auditor=_req("auditor"),
        dimension=dim,
        at=_req("at"),
        sha256=sha,
        evidence=_req("evidence"),
        negative_control=_req("negative_control"),
        findings=tuple(str(f) for f in findings_raw),
        scope=str(item.get("scope", "") or ""),
        evidence_sha256=ev_sha,
        evidence_path=str(item.get("evidence_path", "") or ""),
        # `R1-AN-1`（第 5 轮独立重审报出，high）：这两个字段必须在这里读回来。
        # 批 O 加了它们、也写进了 `to_dict()`，但漏了解析侧 ⇒ 从盘上读回的每条审计
        # 这两项永远是空串 ⇒ `clean_audits` 恒为 0 ⇒ 整条机审通路在生产路径上
        # （`--record-audit` 落盘 → `--check-approvals` 读盘）永远不可能通过。
        # 这是"写入侧有牙、判定侧却读不到"的典型形态：写的人只测了内存对象，没测跨盘往返。
        audit_started_sha256=str(item.get("audit_started_sha256", "") or ""),
        independence=str(item.get("independence", "") or ""),
    )


def _parse_entry(item: object, *, index: int, source: str) -> LedgerEntry:
    """解析并校验一条台账条目。结构不合规一律抛 `LedgerError`（⇒ unknown）。

    判据只校验"判定所依赖的字段"：`path` / `sha256` / `reviewers` / `audits`。
    其余字段（`glob` / `category` / `authored` / `change_note` / `changed_this_session`）
    缺失时给显式默认值而不是抛错 —— 它们缺失不改变"hash 是不是同一版"这个结论，
    但出现时必须合法（例如 `category` 必须是 FC-27 七类之一）。
    """
    where = f"{source} 的第 {index} 条条目"
    if not isinstance(item, dict):
        raise LedgerError(f"{where}不是一个 JSON 对象（收到 {type(item).__name__}）—— 结构不合规 ⇒ 没查成")

    raw_path = item.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise LedgerError(f"{where}缺少非空的 `path` 字段 —— 没有路径的批准记录无法与任何改动对应")
    key = _norm_rel(raw_path)

    sha = item.get("sha256")
    if not isinstance(sha, str) or not _is_sha256_hex(sha):
        raise LedgerError(f"{where}（{key}）的 `sha256` 不是 64 位小写十六进制：{sha!r}")

    reviewers_raw = item.get("reviewers")
    if not isinstance(reviewers_raw, list):
        raise LedgerError(
            f"{where}（{key}）的 `reviewers` 不是数组（收到 {type(reviewers_raw).__name__}）—— "
            "走查记录读不到，就不能当成'没人走查'，只能判 unknown"
        )
    reviewers = tuple(
        _parse_reviewer(r, where=f"{where}（{key}）的 reviewers[{i}]")
        for i, r in enumerate(reviewers_raw)
    )

    audits_raw = item.get("audits", [])
    if not isinstance(audits_raw, list):
        raise LedgerError(
            f"{where}（{key}）的 `audits` 不是数组（收到 {type(audits_raw).__name__}）—— "
            "审计记录读不到，就不能当成'没有审计'，只能判 unknown"
        )
    audits = tuple(
        _parse_audit(a, where=f"{where}（{key}）的 audits[{i}]")
        for i, a in enumerate(audits_raw)
    )

    authored = item.get("authored", "unknown")
    if not isinstance(authored, str) or authored not in AUTHORED_VALUES:
        raise LedgerError(
            f"{where}（{key}）的 `authored` 只能是 {list(AUTHORED_VALUES)}（或省略）：{authored!r} —— "
            "署名不认识就不能替它解读成'人写的'或'AI 写的'"
        )

    # `authored_basis` 必须显式写出，缺了就是结构不合规 ⇒ unknown(2)。
    # 为什么不给默认值：默认值会把"我没写依据"静默变成"依据是推断"——
    # 三态纪律在这里的用法是："没写依据"与"依据是推断"不是同一种东西。
    # 一条只有一个 `authored` 字段的记录，看起来像事实，而它可能只是推断；
    # 读台账的人不该被迫去猜。
    basis = item.get("authored_basis")
    if not isinstance(basis, str) or basis not in AUTHORED_BASIS_VALUES:
        raise LedgerError(
            f"{where}（{key}）的 `authored_basis` 缺失或非法：{basis!r} —— "
            f"它必须显式写成 {list(AUTHORED_BASIS_VALUES)} 之一"
            "（`attested` = 有直接证据；`inferred` = 从 mtime/会话边界推断）。"
            "『没写依据』与『依据是推断』不是同一种东西，所以这里不给默认值"
        )

    cts = item.get("changed_this_session", None)
    if cts is not None and not isinstance(cts, bool):
        raise LedgerError(
            f"{where}（{key}）的 `changed_this_session` 只能是 true / false / null（判不了就写 null，不许猜）：{cts!r}"
        )

    def _opt_str(field: str) -> str:
        v = item.get(field, "")
        if not isinstance(v, str):
            raise LedgerError(f"{where}（{key}）的 `{field}` 不是字符串：{v!r}")
        return v

    glob = _opt_str("glob")
    category = _opt_str("category")
    if category and category not in CATEGORY_TITLES:
        raise LedgerError(
            f"{where}（{key}）的 `category` 不是 FC-27 的七类之一：{category!r}"
            f"（合法：{list(CATEGORY_ORDER)}）"
        )
    change_note = _opt_str("change_note")

    also_raw = item.get("also_hits", [])
    if not isinstance(also_raw, list):
        raise LedgerError(f"{where}（{key}）的 `also_hits` 不是数组：{type(also_raw).__name__}")
    also: list[dict] = []
    for h in also_raw:
        if not isinstance(h, dict):
            raise LedgerError(f"{where}（{key}）的 `also_hits` 里有非对象元素：{type(h).__name__}")
        hg, hc = str(h.get("glob", "")), str(h.get("category", ""))
        if hc and hc not in CATEGORY_TITLES:
            raise LedgerError(f"{where}（{key}）的 `also_hits` 里有未知类别：{hc!r}")
        also.append({"glob": hg, "category": hc, "reason": str(h.get("reason", ""))})

    return LedgerEntry(
        path=key,
        glob=glob,
        category=category,
        sha256=sha,
        authored=authored,
        authored_basis=basis,
        change_note=change_note,
        reviewers=reviewers,
        audits=audits,
        changed_this_session=cts,
        also_hits=tuple(also),
    )


def load_ledger(path: str | Path | None = None, *, root: str | Path | None = None) -> Ledger:
    """读并解析台账。任何"读不到 / 解析不了 / 结构不对"都抛 `LedgerError`。

    三态纪律在这里最容易写错的一步是"文件不存在就当没有批准记录 ⇒ 报未批准" ——
    那是把"没查成"折成"查过了、结论是不批准"。本函数一律抛错，由调用方判 `unknown`。
    """
    p = Path(path) if path is not None else ledger_default_path(root)
    if not p.is_file():
        raise LedgerError(
            f"台账不是一个可读文件：{p}"
            + ("（是目录）" if p.is_dir() else "（不存在）")
            + " —— 命中禁改区时必须查台账，读不到就是没查成"
        )
    try:
        raw = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LedgerError(f"台账读不到或不是 UTF-8 文本：{p}（{type(exc).__name__}: {exc}）") from None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LedgerError(
            f"台账不是合法 JSON：{p}（第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}）"
        ) from None
    if not isinstance(data, dict):
        raise LedgerError(f"台账顶层必须是一个 JSON 对象（收到 {type(data).__name__}）：{p}")

    ver = data.get("ledger_version")
    if ver != LEDGER_VERSION:
        raise LedgerError(
            f"台账版本不认识：{p} 里是 {ver!r}，本门只认 {LEDGER_VERSION} —— "
            "不认识的版本不能按老结构硬读（那会把新字段读成缺失、把缺失读成没问题）"
        )
    entries_raw = data.get("entries")
    if not isinstance(entries_raw, list):
        raise LedgerError(f"台账的 `entries` 不是数组（收到 {type(entries_raw).__name__}）：{p}")

    entries: list[LedgerEntry] = []
    seen: set[str] = set()
    for i, item in enumerate(entries_raw, start=1):
        entry = _parse_entry(item, index=i, source=str(p))
        if entry.path in seen:
            # 同一路径两条记录 ⇒ "该信哪一份"没有答案。判 unknown，而不是取后一条。
            raise LedgerError(f"台账里 `{entry.path}` 有两条条目 —— 同一路径只能有一条记录：{p}")
        seen.add(entry.path)
        entries.append(entry)

    return Ledger(
        ledger_version=ver,
        generated_at=str(data.get("generated_at") or ""),
        entries=tuple(entries),
    )


def _write_ledger_atomic(ledger: Ledger, path: str | Path) -> None:
    """原子写台账（同目录临时文件 + `os.replace`）。

    为什么要原子：本仓库有并发编辑者。写到一半被打断的台账 = 非法 JSON =
    门从此恒为 `unknown`（fail-safe，但会让人失去可比对的基线，
    而"基线不可用"会被读成"这机制没用"）。
    """
    p = Path(path)
    payload = json.dumps(ledger.to_dict(), ensure_ascii=False, indent=2) + "\n"
    tmp = ""
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=str(p.parent))
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
        os.replace(tmp, p)
        tmp = ""
    except OSError as exc:
        raise LedgerError(f"台账写入失败：{p}（{type(exc).__name__}: {exc}）") from None
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                # 临时文件删不掉不影响台账本身（它不叫台账的名字，门读不到它）。
                pass


def evaluate_approval(
    path: str,
    *,
    entry: LedgerEntry | None,
    current_sha256: str | None,
    is_ledger_itself: bool,
    glob: str = "",
    category: str = "",
    reason: str = "",
    repo: str | Path | None = None,
    receipt_log: str | Path | None = None,
) -> dict:
    """    一条命中路径的批准判定。这是批准判据的唯一实现（FC-03）。判定顺序是刻意的（前一条胜过后一条）：台账自指 ⇒ `unapproved`（理由码 `ledger_self_approval`）——
    台账不能批准自己，哪怕它的 hash 一致、reviewers 也够。
    2. 台账里没有条目 ⇒ `unapproved` / `unregistered`（"从没登记"，与"登记过但版本漂了"分开）。
    3. 磁盘 hash 拿不到 ⇒ `unknown`（没查成；不猜）。
    4. hash 不一致 ⇒ `unapproved` / `stale`，两个 hash 都打出来（前 12 位）。
    5. 不同姓名的 reviewer 不足 2 ⇒ 继续看第二条通路（多维独立审计）。
    6. 机审通路的证据锚核对不上（文件读不到、或 hash 与登记值不一致）⇒ `unknown`：
    那是"没查成"，不是"查过了没批准"。三态纪律在这一条上尤其重要 ——把"证据核对不了"读成"未批准"会让人以为去补一次审计就行，而真实处置是"先弄清那份证据还在不在"。
    7. 否则 ⇒ `approved`（并写明是靠人审还是靠机审）。
    """
    out = {
        "path": path,
        "glob": glob,
        "category": category,
        "reason": reason,
        "approval_status": "unapproved",
        "approval_reason": REASON_UNREGISTERED,
        "detail": "",
    }

    if is_ledger_itself:
        out["approval_reason"] = REASON_SELF
        out["detail"] = (
            "台账不能批准自己：本文件就是 hash 台账本身，它的内容随时会因为写入一条记录而变化。"
            "允许它自批准，等于允许『AI 把自己的改动写进台账并声称已批准』——"
            "所以这条**永远**是 unapproved，与 hash 是否一致、reviewers 有几个无关。"
        )
        return out

    if entry is None:
        out["approval_reason"] = REASON_UNREGISTERED
        out["detail"] = (
            "台账里没有这个路径的条目（**从没登记**，不是登记过之后漂了）："
            "先跑 `--baseline` 登记 hash，再由人 `--approve` 走查。"
        )
        return out

    out["entry_sha256"] = entry.sha256
    out["authored"] = entry.authored
    out["authored_basis"] = entry.authored_basis
    out["reviewers"] = [r.to_dict() for r in entry.reviewers]
    out["distinct_reviewers"] = len(entry.distinct_reviewers)

    def _done(status: str, code: str, detail: str) -> dict:
        """收尾：署名依据那句提示必须出现在每一条理由行里。

        为什么不能只在 JSON 字段里给：读台账的人是在终端上读那一行的。
        `authored_basis` 是 `inferred` 时，`authored` 只是推断；
        让它在人读的那一行里露出来，才不至于"推断被当成事实"。
        """
        out["approval_status"] = status
        out["approval_reason"] = code
        caveat = entry.attribution_caveat
        out["detail"] = f"{detail}{caveat}" if caveat else detail
        return out

    if current_sha256 is None:
        return _done(
            "unknown",
            REASON_HASH_UNAVAILABLE,
            f"拿不到磁盘当前内容的 sha256（台账里记的是 {entry.sha256[:12]}）—— "
            "没查成，既不能判 approved、也不能判 stale。",
        )

    out["current_sha256"] = current_sha256

    if entry.sha256 != current_sha256:
        return _done(
            "unapproved",
            REASON_STALE,
            f"**stale**：台账里被批准的那一版是 {entry.sha256[:12]}，"
            f"盘上现在这一版是 {current_sha256[:12]} —— 两者不是同一版。"
            "这正是 git 抓不到的那种形态：git 只会说'文件变了'，"
            "而这里能说出'变的是**不是被批准的那一版**'。"
            "处理：确认以哪一版为复核对象 ⇒ 必要时重跑 `--baseline`（会清空该条的批准语义）"
            "⇒ 再 `--approve`。",
        )

    need = REQUIRED_APPROVALS_ON_HIT
    got = len(entry.distinct_reviewers)
    out["clean_audits"] = [a.to_dict() for a in entry.clean_audits]
    out["dirty_audits"] = [a.to_dict() for a in entry.audit_dirty]
    out["distinct_auditors"] = len(entry.distinct_auditors())
    out["distinct_dimensions"] = list(entry.distinct_dimensions())
    # `R7-R1d-1`：被审对象在这里就读（此前它只在下面机审通路那一支里读）——
    # 理由：观察面报数必须在所有分支都用同一处口径。此前那两处报数发生在读对象之前，
    # 只能退回"自指"弱口径（`reuse_across`），于是同一份报告里出现两种口径：
    # 能批准的那一支过滤掉无关 token、未批准的那一支不过滤（未批准才是操作者
    # 真正要去处理的那一档）。读到一次、分支共用，是 `R6-R1d-5` 想修的那件事的完整版。
    # 读不到 ⇒ 空串 ⇒ 判据 3 会报"没查成"，不在这里折叠成"没问题"。
    target_text = _read_target_text(entry.path, repo)
    # 这两个字段描述的是"记录本身写了什么"，必须在每一条输出里都出现（无论
    # 判定走到哪一支）：读报告的人要能自己看到"几个互不相同的观察面"与
    # "这些审计是什么时候的"，而不是只被告知"审计过了"（`R5-R1b-1` / `R5-R1b-7`）。
    out["observation_surfaces"] = sorted(
        {_observation_key(a.scope, target_text) for a in entry.counted_audits} - {""}
    )
    # `R5-R1b-1` / 口径裁决①：这些观察面里两两不相交的能挑出几个 —— 那才是
    # "几次独立观察"的读数（`VALUE bump` 与 `VALUE` 是两个不同字符串，却是相交的集合）。
    out["independent_observation_surfaces"] = _disjoint_face_count(
        entry.counted_audits, target_text
    )
    # `R6-R1d-3`：措辞用"审计者自报的时间戳"，并逐条带上门真的判了哪三件事
    # （可解析 / 不在未来 / 次序非递减）—— 只给一串裸时间戳会让读报告的人以为
    # "谁在什么时候走查的"从此可核。这里仍保留列表形态：读它的探针（`R1d`/`R5`）
    # 按列表取值，改类型会打断那些读数（见 `audit_timestamp_report` 的 docstring）。
    out["audit_timestamps"] = audit_timestamp_report(entry.counted_audits)

    if got >= need:
        # `FINAL-R1d-04` / `FINAL-R1d-05`：人审通路此前没有内容锚，而且输出只说
        # "N 名不同 reviewer" —— 读的人无从知道这 N 个名字是不是同一个主体、
        # 也看不出这条批准有没有可核的走查记录。这里把两件事一次说清：
        # 逐条核证据锚（有锚但文件不在/内容变了 ⇒ 这一条不算数，落到下面重算），
        # 并在 approved 那一行带上固定保留。
        reviewers = list(entry.reviewers)
        broken: list[str] = []
        anchor_repo = Path(repo) if repo is not None else None
        for r in reviewers:
            why = reviewer_anchor_problem(r, repo=anchor_repo)
            if why:
                broken.append(f"{getattr(r, 'name', '?')}: {why}")
        if broken:
            return _done(
                "unapproved",
                REASON_REVIEW_ANCHOR,
                "人审记录的证据锚核对不过 ⇒ 这几条批准不算数："
                + "；".join(broken)
                + "。处理：确认那份走查记录还在、内容没变，或重新"
                "`--approve --evidence-path <它>`（没有锚的老记录不受影响，"
                "但它们的强度只在 approved 那一行的保留里说明）。",
            )
        anchored = sum(1 for r in reviewers
                       if str(getattr(r, "evidence_path", "") or "").strip())
        return _done(
            "approved",
            REASON_APPROVED,
            f"hash 一致（{entry.sha256[:12]}）且已有 {got} 名不同 reviewer 完成逐行走查"
            f"（通路 = **人审**）。"
            f"⚠️ 门只能证明台账里有 {got} 个**不同字符串**的名字、"
            f"以及其中 {anchored}/{got} 条带**内容锚**（走查记录的 sha256 逐字节对得上）；"
            "它证明不了这几个人/这几次走查真的互相独立 ——"
            "把代记名或同一主体的多次签名读成'多人复核'是**误读**。",
        )

    # ---- `R6-R1d-3`：时间戳次序（与人审通路无关，先判它）
    #
    # 单条的 `audit_timestamp_problem` 只判"能不能解析 / 是不是未来"（那一层在
    # `clean_audits` 里已经生效）；整串倒挂（先记 03:00、再记 02:00、最后记 01:00）
    # 此前没有任何一层看得见 —— 门照样 approved，而输出会把时间戳按写入顺序打成递减。
    # 放在这里而不是 `clean_audits` 里是刻意的：`clean_audits` 是逐条的字段判据，
    # 次序是整串的性质，混进那一层会让"这一条本身合不合规"这句话变得不可判定。
    order_problem = audit_timestamps_not_monotonic(entry.counted_audits)
    if order_problem:
        return _done("unapproved", REASON_AUDIT_TIMESTAMPS_ORDER, order_problem)

    # ---- 第二条通路：多维独立审计
    #
    # 判据（三条同时成立）：≥2 名不同审计者、≥3 个不同维度、每一条审计都清白
    # 且带负控、且 sha256 与本条一致。任一 finding ⇒ 不放行，并把 finding 原文列出来。
    dirty = entry.audit_dirty
    if dirty:
        lines = "；".join(f"[{a.auditor}/{a.dimension}] {f}" for a in dirty for f in a.findings)
        return _done(
            "unapproved",
            REASON_FEW_AUDITS,
            f"审计通路**报了问题**，因此不放行：{lines}。"
            "（报告问题是审计该做的事；处理掉之后重新审计同一版，再记录一次。）",
        )

    auditors = entry.distinct_auditors()
    dims = entry.distinct_dimensions()
    if len(auditors) >= MIN_INDEPENDENT_AUDITORS and len(dims) >= MIN_DISTINCT_DIMENSIONS:
        # ---- `R5-R1b-1`：那几个"维度"必须来自各自独立的观察面
        #
        # 进到这一支说明"记录本身合规且够 2×3"。但 `dimension` 是提交者自填的标签，
        # `counted_audits` 只挡住了"同一份文件重复计数"（键 = 路径 + 内容 hash），
        # 挡不住"同一份观察复制 N 份、每份改一个字节" —— 实测一名审计者 3 份副本
        # 就能供满 3 个维度、再加一名只交 1 条即可 2×3 放行。
        #
        # 判据 = `dimension_independence_problem`（唯一一处实现，写入侧也用它）。
        # 被审对象已在上面读过一次（`_read_target_text`，`R7-R1d-1`）：
        # 判据要用 target 的标识符集合，而"读不到被审对象"必须报红
        # （⇒ 那条判据自己会报 ⇒ 这里判 unapproved），不能静默放行。
        counted = entry.counted_audits
        # `R6-R1d-5` / `R7-R1d-1`：观察面只由被审对象里真实存在的标识符构成 ——
        # 无关的 scope token 不许把"两两不相交"的报数撑大。这两处与上面那两处
        # 用的是同一个 `target_text`、同一处实现 ⇒ 同一份报告里没有两种口径
        # （此前这里"覆盖"上面那一处，未批准的那一支就没有覆盖到）。
        surfaces = sorted({_observation_key(a.scope, target_text) for a in counted} - {""})
        out["observation_surfaces"] = surfaces
        out["independent_observation_surfaces"] = _disjoint_face_count(counted, target_text)
        dim_problem = dimension_independence_problem(counted, target_text)
        if dim_problem:
            return _done(
                "unapproved",
                REASON_DIMENSION_SURFACE,
                f"hash 一致、记录也够（{len(auditors)} 名不同审计者 × {len(dims)} 个维度），"
                f"但**这些维度不是各自独立的观察面**"
                f"（观察面 {len(surfaces)} 个、其中两两不相交的 "
                f"{_disjoint_face_count(counted, target_text)} 个）⇒ 不放行：" + dim_problem,
            )
        # ---- 证据锚核对（`temp/verify-audit-forge.txt` 那次伪造复现的修法）
        #
        # 进到这一支说明"记录本身合规且够 2×3、维度各有独立观察面"。但记录合规 ≠ 证据在。
        # 旧版只检查 `evidence` 非空，于是编一个不存在的路径也走得到 `approved`。
        # 现在逐条重算证据文件的 sha256：读不到、或与登记值不一致 ⇒ 整体 unknown。
        #
        # `R1-AN-4` 的延伸（第 5 轮重审的真 CLI 正控当场撞出来的同一类错误）：交叉核对里那条
        # "scope 的符号必须是被审对象里真实存在的标识符"要用到被审对象的文本，
        # 而判定侧这里原来没读它、没传下去 ⇒ `target_text` 默认空串 ⇒ 标识符集合恒为空 ⇒
        # 每一条合规审计都被判 `unknown / audit_evidence_unverifiable`
        # （写入侧有牙、判定侧读不到 —— 与 `R1-AN-1` 是同一个毛病：改了一侧，另一侧没接）。
        ev_problems = _check_audit_evidence(entry.clean_audits, repo, target_text)
        out["evidence_checked"] = ev_problems["checked"]
        out["evidence_problems"] = ev_problems["problems"]
        if ev_problems["problems"]:
            return _done(
                "unknown",
                REASON_AUDIT_EVIDENCE,
                "审计记录本身合规（"
                f"{len(auditors)} 名不同审计者 × {len(dims)} 个维度），"
                "但**证据锚核对不上** ⇒ 没查成，不给结论："
                + "；".join(ev_problems["problems"])
                + "。处理：确认那些证据文件还在盘上、内容没被换过；"
                "换过就重跑审计并重新 `--record-audit`（登记的是新 hash）。",
            )
        # ---- 回执链（外层锚）：这一版有没有被记在一次只增的追加里
        #
        # 证据锚挡的是"顺手编一句证据"；回执链挡的是"事后把记录删掉或改掉"。
        # 链缺失 / 断链 / 没有这一版的记录 ⇒ 一律 unknown（没查成），
        # 因为此时"这份台账可信不可信"本身就没查成。
        chain = check_receipt_chain(receipt_log, root=repo, expect=[(path, entry.sha256)])
        out["receipt_chain"] = chain
        if chain["problems"]:
            return _done(
                "unknown",
                REASON_AUDIT_RECEIPT,
                "审计记录与证据锚都合规，但**回执链**这一层没通过 ⇒ 没查成，不给结论："
                + "；".join(chain["problems"])
                + "。回执链是只增的追加记录（每条把前一条的 hash 写进自己参与 hash 的内容），"
                "所以『删掉一条』与『改一条』都会让它断开。处理：先弄明白链为什么少了一段，"
                "再决定是否由人重建 —— 不许由写入方在不明白原因的情况下续写。",
            )
        return _done(
            "approved",
            REASON_APPROVED,
            f"hash 一致（{entry.sha256[:12]}）；通路 = **多维独立审计**："
            f"{len(auditors)} 名不同审计者 × {len(dims)} 个维度（{', '.join(dims)}）、"
            f"{len(surfaces)} 个互不相同的观察面（{', '.join(surfaces) or '无'}；"
            "`R5-R1b-1`：维度必须各有独立落点，不是同一份观察换标签），"
            "全部未发现问题、每条都带负控，**各条的证据文件已按登记的 sha256 复核通过**，"
            f"且回执链里能查到这一版（链长 {chain['records']}，"
            f"环尾 {chain['tail'][:12]}）；审计时间戳（`R5-R1b-7` / `R6-R1d-3`，"
            "这些是审计者**自报**的时间戳：门只判『可解析、不在未来、按台账次序非递减』，"
            "它**不**证明这些时刻真的发生过）："
            f"{'、'.join(t['at'] for t in out['audit_timestamps'])}。"
            "⚠️ 这一条**没有任何人类 reviewer 签过字**（`reviewers` 仍为空）—— "
            "读发布结论时请把这一点一起读。"
            "⚠️ 回执链**不是签名**：能同时改台账与重算整条链的人仍然能伪造它。"
            "它挡住的是『悄悄改一条』，不是『有权限的人蓄意伪造』（残余风险见 draft/28 §6.1）。",
        )

    # ---- 两条都不够
    miss: list[str] = []
    if got < need:
        dup = len(entry.reviewers) - got
        extra = f"（另有 {dup} 条同一姓名的重复签名记录，不增加批准数）" if dup else ""
        miss.append(f"人审 {got}/{need} 名不同 reviewer{extra}")
    miss.append(
        f"机审 {len(auditors)}/{MIN_INDEPENDENT_AUDITORS} 名不同审计者、"
        f"{len(dims)}/{MIN_DISTINCT_DIMENSIONS} 个不同维度"
        f"（已有维度：{', '.join(dims) or '无'}）"
    )
    return _done(
        "unapproved",
        REASON_FEW_REVIEWERS,
        "hash 一致，但两条通路都不够：" + "；".join(miss) + "。"
        "人审通路：批准是**人**的动作，AI 不许代填 `reviewers`。"
        "机审通路：`--record-audit` 记录的审计必须带 `--negative-control`（证明它有能力发现问题）"
        "且 sha256 与被审那一版一致。",
    )


def check_approvals(
    changed: Sequence[str],
    *,
    manifest: str | Path | Sequence[Rule] | None = None,
    ledger_path: str | Path | None = None,
    root: str | Path | None = None,
    receipt_log: str | Path | None = None,
) -> GateResult:
    """    命中禁改区之后，用 hash 台账判定"批准的是不是盘上这一版"。

    判定逻辑（与 :func:`check_paths` 并列，不是它的替代）：先按 `check_paths` 取命中集。没有命中 ⇒ 原样返回 `clean`：
    台账读不读都不影响这个结论（台账只在需要它的时候才是必需的）。
    - 有命中 ⇒ 必须读台账。台账不存在 / 非法 JSON / 结构不合规 ⇒ `unknown`(2)。
    - 逐条判：自指 ⇒ unapproved；无条目 ⇒ unapproved(`unregistered`)；
    hash 不一致 ⇒ unapproved(`stale`)；reviewer 不足 2 名 ⇒ unapproved；全部一致且各 ≥2 名 ⇒ `approved`。
    - 只要有一条不是 `approved` ⇒ 整体 `requires_human`(1)；
    全部 `approved` ⇒ `clean`(0)，且 `explanation` 会写明这个 clean 来自台账，不是来自 git。
    - 任一命中路径的内容读不到 ⇒ 整体 `unknown`(2)：没查全就不能给结论。
    """
    repo = Path(root) if root is not None else project_root()
    base = check_paths(changed, manifest=manifest, root=repo)
    if base.verdict != "requires_human":
        # clean / unknown 原样透出。台账读不读都不影响这个结论：
        # 没命中就是没事；清单读不到就是没查成 —— 两者都与台账无关。
        return base

    resolved_ledger = Path(ledger_path) if ledger_path is not None else ledger_default_path(repo)
    try:
        ledger = load_ledger(resolved_ledger)
    except LedgerError as exc:
        return GateResult(
            verdict="unknown",
            violations=[],
            required_approvals=0,
            explanation=(
                "unknown：命中禁改区，**但台账读不到或解析不了 ⇒ 本次没有查成**，"
                "不代表没问题（三态纪律：这里绝不能折叠成 clean）。"
                f"原因：{exc}"
            ),
            manifest_issues=[str(exc)],
            ledger=str(resolved_ledger),
        )

    # 一个命中路径可能命中多条 glob（`dedup.py` 刻意同时在 solver-core 与
    # provenance-dedup 里）：按路径聚合，第一条 glob 作主记录，其余进 `also_hits`。
    #
    # 键必须是仓库相对的（`_repo_rel_key`），不能直接用 `v["path"]`：
    # 调用方给的是绝对路径时（`D:/repo/src/a.py`），台账里的键仍是 `src/a.py`，
    # 拿原样去查会假报 `unregistered`（明明登记过，却说从没登记）。
    by_path: dict[str, list[dict]] = {}
    for v in base.violations:
        key = _repo_rel_key(v["path"], repo)
        by_path.setdefault(key, []).append(v)

    ledger_resolved = resolved_ledger.resolve()
    approvals: list[dict] = []
    for key in sorted(by_path):
        hits = by_path[key]
        target = _target_path(key, repo)
        try:
            is_self = target.resolve() == ledger_resolved or key == LEDGER_NAME
        except OSError:
            # `resolve()` 在个别文件系统错误上会抛；此时按名字判自指
            # （台账的名字是固定的，名字相同就已经足够判"这是台账自己"）。
            is_self = key == LEDGER_NAME
        try:
            current = sha256_file(target)
        except LedgerError:
            # 拿不到 hash ⇒ 这一条判 unknown（下面统一升级整体结论）。
            current = None
        approvals.append(
            evaluate_approval(
                key,
                entry=ledger.entry_for(key),
                current_sha256=current,
                is_ledger_itself=is_self,
                glob=hits[0]["glob"],
                category=hits[0]["category"],
                reason=hits[0]["reason"],
                repo=repo,
                receipt_log=receipt_log,
            )
        )

    unapproved = [a for a in approvals if a["approval_status"] == "unapproved"]
    unknown_items = [a for a in approvals if a["approval_status"] == "unknown"]
    counts: dict[str, int] = {}
    for a in approvals:
        counts[a["approval_reason"]] = counts.get(a["approval_reason"], 0) + 1
    summary = "、".join(f"{k} {v} 条" for k, v in sorted(counts.items()))

    if unknown_items:
        return GateResult(
            verdict="unknown",
            violations=unapproved,
            required_approvals=0,
            explanation=(
                f"unknown：命中 {len(approvals)} 条路径，其中 {len(unknown_items)} 条**没能查成**"
                f"（{summary}）⇒ 本次检查不完整，不给结论。"
                f"没查成 ≠ 没问题。台账：{resolved_ledger}"
            ),
            approvals=approvals,
            ledger=str(resolved_ledger),
        )

    if unapproved:
        return GateResult(
            verdict="requires_human",
            violations=unapproved,
            required_approvals=REQUIRED_APPROVALS_ON_HIT,
            explanation=(
                f"requires_human：命中 {len(approvals)} 条禁改区路径，"
                f"其中 **{len(unapproved)} 条未获批准**（{summary}）⇒ "
                f"必须由人编写或人逐行走查，并需要 {REQUIRED_APPROVALS_ON_HIT} 名 reviewer 批准。"
                f"台账：{resolved_ledger}"
            ),
            approvals=approvals,
            ledger=str(resolved_ledger),
        )

    # ---- clean 的措辞必须与这一批实际的通路一致
    #
    # 旧版无论哪条通路放行都逐字写"各 ≥2 名不同 reviewer 完成逐行走查"，而机审放行时
    # `reviewers` 是空的 —— 于是报告在说假话（`temp/verify-audit-forge.txt` 那次复现里，
    # 两个假 auditor 名就让门打印了那句"逐行走查"）。
    # 下一条是"本仓库不是 git 仓库"：那是上一版留下的错误事实（本仓库的 `.git` 在上一级，
    # `--git` 能正常返回改动集），留着它会让人以为 `--git` 不可用。
    by_human = [a for a in approvals if a.get("approval_reason") == REASON_APPROVED
                and a.get("distinct_reviewers", 0) >= REQUIRED_APPROVALS_ON_HIT]
    by_audit = [a for a in approvals if a.get("approval_reason") == REASON_APPROVED
                and a.get("distinct_reviewers", 0) < REQUIRED_APPROVALS_ON_HIT]
    paths: list[str] = []
    if by_human:
        paths.append(f"{len(by_human)} 条靠**人审**（各 ≥{REQUIRED_APPROVALS_ON_HIT} 名不同 reviewer）")
    if by_audit:
        paths.append(
            f"{len(by_audit)} 条靠**多维独立审计**（≥{MIN_INDEPENDENT_AUDITORS} 名不同审计者 × "
            f"≥{MIN_DISTINCT_DIMENSIONS} 个维度，**无人类 reviewer 签字**）"
        )
    return GateResult(
        verdict="clean",
        violations=[],
        required_approvals=0,
        explanation=(
            f"clean：{len(approvals)} 条命中路径**全部**已在台账里获批准"
            f"（hash 与磁盘一致；通路：" + "、".join(paths) + "）。"
            "⚠️ 这个 clean 是**靠台账判定的，不是靠 git 历史的整洁** —— "
            f"`--git` 能给出改动集（本仓库的 `.git` 在上一级），但它只说'文件变了'，"
            f"说不出'变的是不是被批准的那一版'；结论来源是 {resolved_ledger} 里的 sha256"
            "与 reviewers/audits。"
        ),
        approvals=approvals,
        ledger=str(resolved_ledger),
    )


def register_baseline(
    changed: Sequence[str],
    *,
    manifest: str | Path | Sequence[Rule] | None = None,
    root: str | Path | None = None,
    ledger: Ledger | None = None,
    notes: Mapping[str, str] | None = None,
    authored: Mapping[str, str] | None = None,
    authored_basis: Mapping[str, str] | None = None,
    changed_this_session: Mapping[str, bool | None] | None = None,
    default_authored: str = "unknown",
    default_authored_basis: str = "inferred",
    now: _dt.datetime | None = None,
) -> tuple[Ledger, list[dict]]:
    """    登记基线与刷新：写 `sha256` / `glob` / `category` / 摘要。绝不写 `reviewers`。

    「登记」与「批准」是两个动作，不许合并（合并等于让 AI 自己给自己发批准）。本函数是登记路径的唯一实现：CLI 的 `--baseline` 与脚本化的基线建立都走它。刷新时的两条规则：内容 hash 变了 ⇒
    `reviewers` 清空。旧签名批准的是旧那一版，
    把它留在新 hash 上，正是本台账要堵的"批准之后又被悄悄改了"。
    - 内容 hash 没变 ⇒ 保留已有 `reviewers`。台账钉住的对象是内容版本，
    不是"某一次登记动作"：hash 没变 ⇒ 被批准的那一版就是盘上这一版，签名依然指向同一个对象。若任何一次 `--baseline` 都清空签名，会产生一个反向激励 —— 人越勤快地重跑基线，人工记录越容易被摧毁，
    而"勤快"恰恰是希望鼓励的行为。判据要让人更愿意跑它，而不是更不敢跑它。返回 `(新台账, 逐路径结果)`。结果里 `status` ∈`created` / `unchanged` / `refreshed` /
    `not_in_manifest` / `hash_unavailable`。`authored` / `authored_basis` 的取舍：显式给了就写（哪怕 hash 未变）——对同一版内容给出更强的归属声明是改进，
    不是换对象。没给的话：hash 未变 ⇒ 保留原值；hash 变了的新条目 ⇒ 用 `default_*`。
    """
    if default_authored not in AUTHORED_VALUES:
        raise LedgerError(f"default_authored 只能是 {list(AUTHORED_VALUES)}：{default_authored!r}")
    if default_authored_basis not in AUTHORED_BASIS_VALUES:
        raise LedgerError(
            f"default_authored_basis 只能是 {list(AUTHORED_BASIS_VALUES)}：{default_authored_basis!r}"
        )

    repo = Path(root) if root is not None else project_root()
    if isinstance(manifest, (str, Path)) or manifest is None:
        # 与 `check_paths` 同一处口径：`manifest is None` ⇒ 用 `root` 下的清单。
        rules = load_manifest(manifest if manifest is not None else repo / MANIFEST_NAME)
    else:
        rules = list(manifest)
    if not rules:
        raise NoaiError("空清单：登记基线时无法判断哪些路径属于禁改区 ⇒ 没查成")

    old_entries = {e.path: e for e in (ledger.entries if ledger is not None else ())}
    notes = notes or {}
    authored_map = authored or {}
    basis_map = authored_basis or {}
    cts_map = changed_this_session or {}

    results: list[dict] = []
    new_entries: dict[str, LedgerEntry] = dict(old_entries)

    for raw in changed:
        key = _repo_rel_key(raw, repo)
        matched = [
            rule for rule in rules
            if _glob_matches(_path_candidates(str(raw), repo), rule.glob) is not None
        ]
        if not matched:
            results.append({
                "path": key, "status": "not_in_manifest", "sha256": "",
                "glob": "", "category": "",
                "detail": "不命中禁改区 ⇒ 没有 glob / category 可登记，未写入台账",
            })
            continue

        target = _target_path(raw, repo)
        try:
            current = sha256_file(target)
        except LedgerError as exc:
            results.append({
                "path": key, "status": "hash_unavailable", "sha256": "",
                "glob": matched[0].glob, "category": matched[0].category,
                "detail": f"拿不到内容 hash ⇒ 未写入台账：{exc}",
            })
            continue

        old = old_entries.get(key)
        unchanged = old is not None and old.sha256 == current
        if unchanged:
            reviewers = tuple(old.reviewers)
            # 审计记录同理：内容没变 ⇒ 保留（它审的就是这一版，sha256 逐位相同）
            audits = tuple(old.audits)
            note = notes.get(key) or old.change_note
            auth = authored_map.get(key, old.authored)
            basis = basis_map.get(key, old.authored_basis)
            cts = cts_map.get(key, old.changed_this_session)
            status = "unchanged"
            detail = (
                f"hash 未变（{current[:12]}）⇒ 保留已有 {len(reviewers)} 条走查记录"
                f"、{len(audits)} 条审计记录"
            )
        else:
            reviewers = ()
            # 内容变了 ⇒ 审计记录也清空：它审的是旧那一版。
            # 这条与 `reviewers` 的处置必须一致 —— 否则"改了之后再补一次旧版审计"
            # 会让一条没人看过的内容凭旧审计通过（`ReviewAudit` 的 sha256 判据也拦，
            # 但在这里清掉更干净：台账里不留会对不上盘的记录）。
            audits = ()
            if key in notes:
                note = notes[key]
            elif old is not None:
                note = (
                    f"（未提供变更说明：内容 hash 从 {old.sha256[:12]} 变为 {current[:12]}，"
                    "改动内容需人补 —— 登记只记 hash，不假装知道改了什么）"
                )
            else:
                note = notes.get(key, "（未提供变更说明）")
            auth = authored_map.get(key, default_authored)
            basis = basis_map.get(key, default_authored_basis)
            cts = cts_map.get(key, None)
            status = "refreshed" if old is not None else "created"
            detail = (
                f"登记 hash {current[:12]}"
                + (
                    f"；内容已变，旧签名（{len(old.reviewers)} 条）与旧审计（{len(old.audits)} 条）"
                    "**清空** —— 它们批准/审计的是旧那一版"
                    if old is not None and (old.reviewers or old.audits)
                    else ""
                )
            )

        if auth not in AUTHORED_VALUES:
            raise LedgerError(f"{key} 的 authored 只能是 {list(AUTHORED_VALUES)}：{auth!r}")
        if basis not in AUTHORED_BASIS_VALUES:
            raise LedgerError(
                f"{key} 的 authored_basis 只能是 {list(AUTHORED_BASIS_VALUES)}：{basis!r}"
            )

        new_entries[key] = LedgerEntry(
            path=key,
            glob=matched[0].glob,
            category=matched[0].category,
            sha256=current,
            authored=auth,
            authored_basis=basis,
            change_note=note,
            reviewers=reviewers,
            audits=audits,
            changed_this_session=cts,
            also_hits=tuple(
                {"glob": r.glob, "category": r.category, "reason": r.reason} for r in matched[1:]
            ),
        )
        results.append({
            "path": key, "status": status, "sha256": current,
            "glob": matched[0].glob, "category": matched[0].category,
            "reviewers": len(reviewers),
            "authored": auth, "authored_basis": basis,
            "reviewers_cleared": bool(old is not None and not unchanged and old.reviewers),
            "detail": detail,
        })

    # 未在本次 `changed` 里的旧条目原样保留：登记是增量的，
    # 一次 `--baseline --paths A` 不该把 B..M 的记录删掉（那会静默丢失走查记录）。
    ordered = tuple(new_entries[k] for k in sorted(new_entries))
    return Ledger(ledger_version=LEDGER_VERSION, generated_at=_now_iso(now), entries=ordered), results


def add_approval(
    ledger: Ledger,
    path: str | Path,
    *,
    reviewer: str,
    scope: str,
    note: str = "",
    verdict: str = "逐行走查通过",
    evidence_path: str = "",
    evidence_sha256: str = "",
    root: str | Path | None = None,
    now: _dt.datetime | None = None,
) -> tuple[Ledger, dict]:
    """给某一条追加一个 reviewer 记录（人跑 `--approve`）。

    任何一条前置条件不满足都抛 `LedgerError`（不写入），其中最关键的一条：

    > 必须先断言该条目的 hash 与磁盘当前内容一致 —— 不一致就拒绝写入。

    否则你批准的是一个不在盘上的版本，而台账会显示"已批准"。
    CLI 把这个异常读成退出码 2（"没做成"），不是 1（"查了，未批准"）。
    """
    repo = Path(root) if root is not None else project_root()
    key = _repo_rel_key(path, repo)

    if key == LEDGER_NAME:
        raise LedgerError(
            f"拒绝写入：{LEDGER_NAME} 不能批准自己（台账自指）。"
            "台账的内容会因为写入记录而变化，允许它自批准等于让门自己给自己盖章。"
        )
    if not str(reviewer).strip():
        raise LedgerError("拒绝写入：`--reviewer` 为空 —— 匿名签字等于没有人签字")
    # `R5-R1b-3`：姓名的判据必须与"怎么算同一个姓名"共用一处实现。
    # 只查"非空"时，同一个人把名字写成 `ｒｅｖｉｅｗｅｒ－甲` 就能顶第二名 reviewer。
    who_problem = _reviewer_identity_problem(reviewer)
    if who_problem:
        raise LedgerError(f"拒绝写入：`--reviewer` 不合格 —— {who_problem}（`R5-R1b-3`）")
    if not str(scope).strip():
        raise LedgerError(
            "拒绝写入：`--scope` 为空 —— scope 必须具体到符号或行区间，"
            "写『看过了』等于没看"
        )

    entry = ledger.entry_for(key)
    if entry is None:
        raise LedgerError(
            f"拒绝写入：台账里没有 {key} 的条目 —— 先 `--baseline` 登记这一版，"
            "再由人走查后签字。『批准』不是『登记』的替代品。"
        )

    target = _target_path(path, repo)
    current = sha256_file(target)
    if entry.sha256 != current:
        raise LedgerError(
            f"拒绝写入：{key} 的台账 hash {entry.sha256[:12]} 与磁盘当前内容 {current[:12]} **不一致** —— "
            "你正要批准的那一版不在盘上。先确认以哪一版为复核对象："
            "必要时重跑 `--baseline`（会清空该条已有的批准语义），再重新走查签字。"
        )

    same_name = [r for r in entry.reviewers if _identity_same(r.name, reviewer)]
    # `FINAL-R1d-04`：证据锚（可选）。给了就当场把那份走查记录的 sha256 算出来写进台账，
    # 判定侧再逐字节核对 —— 于是"人审"这一支也有了与机审同构的内容锚。
    evidence_path = str(evidence_path or "").strip()
    evidence_sha = ""
    if evidence_path:
        ev = Path(evidence_path)
        if not ev.is_absolute():
            ev = repo / evidence_path
        if not ev.is_file():
            raise LedgerError(
                f"拒绝写入：`--evidence-path` 指向的文件不在盘上：{evidence_path} —— "
                "证据锚的价值就在于它指向一份**真的存在**的走查记录"
            )
        evidence_sha = hashlib.sha256(ev.read_bytes()).hexdigest()
    elif str(evidence_sha256 or "").strip():
        raise LedgerError(
            "拒绝写入：只给 `--evidence-sha256` 而不给 `--evidence-path` —— "
            "没有路径的 hash 核对不了任何东西（门不接受自己算不出来的锚）"
        )
    record = Reviewer(
        name=str(reviewer).strip(),
        at=_now_iso(now),
        scope=str(scope).strip(),
        note=str(note).strip(),
        verdict=str(verdict).strip() or "逐行走查通过",
        evidence_path=evidence_path,
        evidence_sha256=evidence_sha,
    )
    updated = LedgerEntry(
        path=entry.path,
        glob=entry.glob,
        category=entry.category,
        sha256=entry.sha256,
        authored=entry.authored,
        authored_basis=entry.authored_basis,
        change_note=entry.change_note,
        reviewers=(*entry.reviewers, record),
        #  `audits` 必须原样带过去。旧版在这里漏了它，而 `LedgerEntry` 的默认值是 `()` ⇒
        # `--approve` 会把该条已记录的机审静默清空（人签一次字，机审记录就没了）。
        # 这类"重建对象时漏一个字段"的缺陷不会报错：台账照样是合法 JSON。
        audits=entry.audits,
        changed_this_session=entry.changed_this_session,
        also_hits=entry.also_hits,
    )
    entries = tuple(updated if e.path == key else e for e in ledger.entries)
    info = {
        "path": key,
        "appended": record.to_dict(),
        "reviewers": len(updated.reviewers),
        "distinct_reviewers": len(updated.distinct_reviewers),
        "required": REQUIRED_APPROVALS_ON_HIT,
        "duplicate_name": bool(same_name),
        # 把"机审记录还在"写进回执：这条回执本身就是"没被清空"的证据。
        "audits_kept": len(updated.audits),
    }
    return Ledger(
        ledger_version=LEDGER_VERSION, generated_at=_now_iso(now), entries=entries
    ), info


def record_audit(
    ledger: Ledger,
    path: str | Path,
    *,
    auditor: str,
    dimension: str,
    evidence: str,
    negative_control: str,
    evidence_sha256: str = "",
    evidence_path: str = "",
    audit_started_sha256: str = "",
    independence: str = "",
    findings: Sequence[str] = (),
    scope: str = "",
    root: str | Path | None = None,
    receipt_log: str | Path | None = None,
    now: _dt.datetime | None = None,
) -> tuple[Ledger, dict]:
    """    给某一条追加一个机器审计记录（第二条通路）。与 `add_approval` 的三处刻意不同：不校验 `--scope` 非空（审计有 `dimension` 就够具体了）；但仍然要求 `evidence` 与
    `negative_control` 非空 —— 后两者才是这条通路的信用来源。2. 允许记 `findings`：审计发现了问题就如实记下来，门会把这一条判成"不放行"并把 finding 原文列出来。不许把 finding 藏掉只记一次"通过"。
    3. 仍然绝不写 `reviewers`：两条通路分列，机器审计永远不冒充人。台账自指：与 `add_approval` 一样的拒绝（`c-19`）：目标路径就是台账自己时，本函数与 :
    func:`add_approval` 一样拒绝写入（`LedgerError`）。此前这条拒绝只有 `add_approval` 有，于是"往台账自己那条记录里追加一次审计"写得进去 —— 放行确实仍被
    `evaluate_approval` 的自指分支挡住，所以它不是一条提权路径；但两条通路的前置条件不对称本身就是缺陷：下一次有人把 `evaluate_approval`那一层兜底拿掉时，能写进去的那一条就会变成真的口子。修法取对称的那三行，
    而不是给两条通路各写一套判据。证据锚（`evidence_path` + `evidence_sha256`）为什么是必需的：这一条是 2026-09-26 那次伪造复现（`temp/verify-audit-forge.txt`）之后加的：旧版只检查
    `evidence` 非空，于是编一个不存在的路径也能让门报 clean。现在写入时就要满足：`evidence_path` 相对仓库根（也接受绝对路径）能读到；- 它的内容 hash 与 `evidence_sha256` 一致（不给
    `evidence_sha256` 时由本函数算）。并且若 `evidence` 这句描述指向的是一个读不到的文件，本函数也会拒绝 ——那是"证据写在别处"的常见形态，让它在写入时就暴露，而不是等门在判定时才发现（那时报的是 unknown，
    处置却发生在很久以后）。回执链：写入成功后本函数会 `append_receipt()` 追加一环（只增、带前环 hash）。链自身不通过校验时拒绝写入 —— "记不下来的一次审计"不该进台账，否则台账会先显示一条没有回执的记录，
    而回执链的缺失要等到判定时才发现。
    """
    repo = Path(root) if root is not None else project_root()
    key = _repo_rel_key(path, repo)

    if key == LEDGER_NAME:
        raise LedgerError(
            f"拒绝写入：{LEDGER_NAME} 不能给自己记审计（台账自指）—— 这条拒绝与 `add_approval` 逐字对称，"
            "两条通路的前置条件必须一样。允许往台账自己那条记录里追加一次审计，"
            "等于让记录审计的那一层自己给自己盖章"
            "（`c-19`：这一条此前只有 `add_approval` 有，`record_audit` 缺）。"
        )
    if not str(auditor).strip():
        raise LedgerError("拒绝写入：`--auditor` 为空 —— 匿名的'我审过了'无法与'没人审'区分")
    if dimension not in AUDIT_DIMENSIONS:
        raise LedgerError(
            f"拒绝写入：`--dimension` 必须是受控词表里的一员 {list(AUDIT_DIMENSIONS)}，收到 {dimension!r}"
        )
    if not str(evidence).strip():
        raise LedgerError(
            "拒绝写入：`--evidence` 为空 —— 审计结论必须指向可复核的原始输出"
            "（『我看过了』不是证据）"
        )
    nc_problem = negative_control_problem(negative_control)
    if nc_problem:
        raise LedgerError(
            "拒绝写入：`--negative-control` 不合格 —— " + nc_problem
            + "（`H-1c`：只查非空时 `n/a` 也是合法字符串，于是『每条都带负控』成了一句空话）"
        )
    if not str(scope).strip():
        raise LedgerError(
            "拒绝写入：`--audit-scope` 为空 —— 审计必须说清这次覆盖了哪些符号"
            "（`H-1d`）：一个空 scope 意味着『我审过什么』不可复核。"
            "写符号名或小节名，至少一个长度 ≥3 的名字要能在证据文件里找到。"
        )
    if not str(evidence_path).strip():
        raise LedgerError(
            "拒绝写入：`--evidence-path` 为空 —— 审计结论必须落在**盘上的一个文件**里，"
            "否则 `--evidence` 只是一句话，谁都能写（实测：编一个不存在的路径曾让门报 clean）。"
            "给相对仓库根的路径（例如 `temp/AUDIT-A.json`）。"
        )

    entry = ledger.entry_for(key)
    if entry is None:
        raise LedgerError(
            f"拒绝写入：台账里没有 {key} 的条目 —— 先 `--baseline` 登记这一版，再审计。"
        )

    target = _target_path(path, repo)
    current = sha256_file(target)
    if entry.sha256 != current:
        raise LedgerError(
            f"拒绝写入：{key} 的台账 hash {entry.sha256[:12]} 与磁盘当前内容 {current[:12]} **不一致** —— "
            "你正要审计的那一版不在盘上。先确认以哪一版为审计对象，必要时重跑 `--baseline`。"
        )

    # ---- 证据锚：文件必须存在，hash 必须对得上（不给 hash 就现场算）
    ev_rel = str(evidence_path).strip()
    # `R1-4`：解析规则只有 `_resolve_evidence_file` 一处实现 —— 写入侧与核对侧
    # 必须走同一个函数。这里原先内联了同一段"仓库根优先、其次 cwd"的逻辑，
    # 两份实现当时行为一致，但改一份漏一份就会出现"写得进去、核不出来"，
    # 而那种分裂没有任何测试会响（正是 `temp/verify-audit-forge.txt` 那一族）。
    ev_file = _resolve_evidence_file(ev_rel, repo)
    if not ev_file.is_file():
        raise LedgerError(
            f"拒绝写入：证据文件读不到：{ev_file}（`--evidence-path` 给的是 {ev_rel!r}）—— "
            "『证据在别处』不能靠一句话，必须是盘上这个文件。"
        )
    actual_ev_sha = sha256_file(ev_file)
    if str(evidence_sha256).strip():
        got = str(evidence_sha256).strip().lower()
        if not _is_sha256_hex(got):
            raise LedgerError(
                f"拒绝写入：`--evidence-sha256` 不是 64 位小写十六进制：{got!r}"
            )
        if got != actual_ev_sha:
            raise LedgerError(
                "拒绝写入：证据文件的 hash 与 `--evidence-sha256` 不一致 —— "
                f"盘上 {actual_ev_sha[:12]}，登记 {got[:12]}。"
                "要么你给错了文件，要么这个文件被换过；两种都不该写成一条审计记录。"
            )

    # ---- `c-20`：审计必须声明"开审那一刻是哪一版" ----
    started = str(audit_started_sha256).strip().lower()
    if not started:
        raise LedgerError(
            "拒绝写入：`--audit-started-sha256` 为空 —— 审计记录必须写清**开审时被审对象是哪一版**。"
            "没有它，『审的是 A 版、记账时台账已被 `--baseline` 刷成 B 版』在结构上是通的，"
            "而门照样报 clean（`c-20` 的实测形态）。开审时自己算一次："
            "`python -c \"import hashlib;print(hashlib.sha256(open(PATH,'rb').read()).hexdigest())\"`"
        )
    if not _is_sha256_hex(started):
        raise LedgerError(f"拒绝写入：`--audit-started-sha256` 不是 64 位小写十六进制：{started!r}")
    if started != entry.sha256:
        raise LedgerError(
            f"拒绝写入：开审版本 {started[:12]} 与台账这一版 {entry.sha256[:12]} **不是同一版** —— "
            "你审的不是盘上这一版（或者在审计期间这一版被改过、台账被 `--baseline` 刷过）。"
            "先确认以哪一版为审计对象：重新审这一版，或让台账回到你审的那一版。"
        )
    if started != current:
        raise LedgerError(
            f"拒绝写入：开审版本 {started[:12]} 与磁盘当前内容 {current[:12]} 不一致。"
        )

    # ---- `c-16` / `H-1e`：审计者不能是该条目的署名者 ----
    # 两处身份比较都走同一处归一化（`_identity_same` / `normalize_subject`）：
    # `H-1a` 加的那套规则若只用在"计数"上、不在这里用，同形字署名者就绕过了 `c-16`。
    author_known = normalize_subject(entry.authored) not in ("", "unknown")
    same_author = author_known and _identity_same(auditor, entry.authored)
    if same_author:
        raise LedgerError(
            f"拒绝写入：`--auditor`（{auditor}）与台账里这条的署名者（{entry.authored}）是同一主体 —— "
            "自己审自己不算独立复核（`c-16` 的 docstring 早就这么写了，但代码以前只打印一行警告）。"
        )
    if not author_known and not str(independence).strip():
        raise LedgerError(
            f"拒绝写入：台账里这条的署名者是 {entry.authored!r} ⇒ 「审计者不能是署名者」这条判据"
            "**无从适用**，于是必须由审计者显式声明独立性（`--independence`，例如"
            "『我是子代理 X，与该条目的作者不是同一主体；署名者未知时这条声明是唯一可留痕的东西』）。"
            "（`H-1e`：实测 16 条里有 13 条 `authored=unknown`，旧代码在那种情况下永不触发。）"
        )
    # `R5-R1b-4`：独立性声明的内容判据与判定侧共用 `_independence_problem` 一处实现
    # （曾经只判 non-empty ⇒ `--independence x` 三条全过）。
    if not author_known:
        ind_problem = _independence_problem(independence)
        if ind_problem:
            raise LedgerError(
                f"拒绝写入：`--independence` 不合格 —— {ind_problem}"
                "（`H-1e`：署名者未知时这条声明是机审通路上唯一的独立性留痕）"
            )
    # `R5-R1b-7`：`at` 也在此处校验一次 —— 时钟被拨到未来时，写进去的时间戳
    # 在判定侧会被判 `audit_timestamp_unverifiable`。写侧先拒一次，
    # 免得落一条注定读不回来的记录（写入侧与判定侧共用同一处判据）。
    at_problem = audit_timestamp_problem(_now_iso(now))
    if at_problem:
        raise LedgerError(
            f"拒绝写入：时间戳不合格 —— {at_problem}"
            "（`R5-R1b-7`：`at` 曾经是唯一一个『写了就信』的字段）"
        )

    record = ReviewAudit(
        auditor=str(auditor).strip(),
        dimension=dimension,
        at=_now_iso(now),
        sha256=entry.sha256,
        evidence=str(evidence).strip(),
        negative_control=str(negative_control).strip(),
        findings=tuple(str(f).strip() for f in findings if str(f).strip()),
        scope=str(scope).strip(),
        evidence_sha256=actual_ev_sha,
        evidence_path=_norm_evidence_rel(ev_rel),   # `R1-AN-2`：写入侧就存归一化后的形态
        audit_started_sha256=started,
        independence=str(independence).strip(),
    )

    # ---- `H-1b`：把声明与证据文件的内容交叉核对（写入侧）----
    try:
        ev_text = ev_file.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise LedgerError(f"拒绝写入：证据文件读不出文本：{ev_file}（{exc}）") from exc
    try:
        target_text = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        target_text = ""
    cross = _evidence_cross_check(record, ev_text, entry.sha256, target_text)
    if cross:
        raise LedgerError("拒绝写入：证据与声明对不上 ——\n  - " + "\n  - ".join(cross))
    # `R6-R1d-3`：追加之前先与上一条比一次 —— 台账的 `audits` 是只增的，
    # 后写的理应不早于先写的。判定侧对整串判同一件事
    # （`audit_timestamps_not_monotonic`）；写侧先拒一次，免得落一条注定让这一条整体
    # 判红的记录（与 `R5-R1b-7` 同一条纪律：写侧与判定侧共用同一处口径，
    # 不在两侧各写一套）。
    if entry.audits:
        order_problem = audit_timestamps_not_monotonic((entry.audits[-1], record))
        if order_problem:
            raise LedgerError(
                f"拒绝写入：{order_problem}"
                "（`R6-R1d-3`：`at` 是由调用方自报的 —— `record_audit` 的 `now` 可以显式给 —— "
                "所以这里判的是『你报的这一条是不是早于台账里最后一条』）"
            )
    updated = LedgerEntry(
        path=entry.path,
        glob=entry.glob,
        category=entry.category,
        sha256=entry.sha256,
        authored=entry.authored,
        authored_basis=entry.authored_basis,
        change_note=entry.change_note,
        reviewers=entry.reviewers,
        audits=(*entry.audits, record),
        changed_this_session=entry.changed_this_session,
        also_hits=entry.also_hits,
    )
    entries = tuple(updated if e.path == key else e for e in ledger.entries)
    # 回执：先追加到只增链上（链自身不通过校验时 `append_receipt` 抛 `LedgerError`，
    # 于是这次审计不会被写进台账 —— "记不下来的一次审计"不该进台账，
    # 否则台账会显示一条没有回执的记录，而回执链的缺失要等到判定时才发现）。
    receipt = append_receipt(
        action="record_audit",
        path=key,
        entry_sha256=entry.sha256,
        detail=f"{record.auditor}/{record.dimension}",
        log_path=receipt_log,
        root=repo,
    )
    info = {
        "path": key,
        "appended": record.to_dict(),
        "audits": len(updated.audits),
        "clean_audits": len(updated.clean_audits),
        "distinct_auditors": len(updated.distinct_auditors()),
        # `R6-R1d-6`：这里的口径与 `evaluate_approval` 的输出必须同类型同值 ——
        # 两处都报"这次记录之后有哪些维度"：这里给列表，另给一个显式的计数名，
        # 免得调用方（与读报告的人）把 `len(...)` 当成字段本身（曾经 CLI 打的是
        # `len(info['distinct_dimensions'])`，而 JSON 里同名字段是列表）。
        "distinct_dimensions": list(updated.distinct_dimensions()),
        "distinct_dimension_count": len(updated.distinct_dimensions()),
        # `R5-R1b-1`：这几个"维度"背后有几个不同的观察面（`scope` 归一化后的符号集合）。
        # 它必须与维度数一起报出来：`distinct_dimensions` 是自填标签，光看它会以为
        # "3 个维度"就是"三次独立观察"（实测：一名审计者三份副本即可凑满 3）。
        # `R6-R1d-5`：观察面只由被审对象里真实存在的标识符构成（与判定侧同一处口径）。
        # `R7-R1d-1`：退路那一支要剔掉本条自己的 `scope`（否则它是恒等不过滤）。
        "observation_surfaces": sorted(
            {_observation_key(a.scope, target_text,
                              reuse_across=[b.scope for b in updated.counted_audits],
                              drop_self_scope=True)
             for a in updated.counted_audits} - {""}
        ),
        "required_auditors": MIN_INDEPENDENT_AUDITORS,
        "required_dimensions": MIN_DISTINCT_DIMENSIONS,
        "findings": list(record.findings),
        "auditor_is_author": same_author,
        "audit_started_sha256": started,
        "evidence_file": str(ev_file),
        "evidence_sha256": actual_ev_sha,
        "receipt": receipt,
    }
    # `R6-R1d-6`：这里曾经多一个 `"_target_text": target_text` —— 一个只给 CLI 一层用的
    # 私有中间量塞在公开返回值里（注释自己写着"内部用"）。后果不是"多一个键"，
    # 而是 `info` 同时承担"给人看的报告 / 给调用方的读数 / 给写侧判据的中间量"三种职责，
    # 于是 `_run_record_audit` 改签名时漏改接收变量就变成 `R6-R1d-1`（整条 CLI 通路 NameError）。
    # 现在 `_run_record_audit` 自己读被审对象（与判定侧同构），这个私有键不再存在。
    return Ledger(
        ledger_version=LEDGER_VERSION, generated_at=_now_iso(now), entries=entries
    ), info


# --------------------------------------------------------------------------- git
def _git_lines(repo: Path, argv: list[str]) -> tuple[list[str] | None, str]:
    """跑一条 git 命令并返回 `(paths, "")`；取不到时返回 `(None, 原因)`。"""
    try:
        proc = subprocess.run(
            ["git", *argv],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        return None, "环境里没有 `git` 可执行文件"
    except subprocess.TimeoutExpired:
        # 必须在 OSError 之前：TimeoutExpired 继承自 SubprocessError。
        return None, f"`git {' '.join(argv)}` 超时（30s）"
    except OSError as exc:
        return None, f"调用 git 失败：{type(exc).__name__}: {exc}"

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        first = detail[0] if detail else "（无输出）"
        return None, f"`git {' '.join(argv)}` 退出码 {proc.returncode}：{first}"

    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()], ""


def git_changed_paths(root: str | Path | None = None, *, since: str | None = None) -> tuple[list[str] | None, str]:
    """    取改动集：已提交的 `since..HEAD` ∪ 未提交改动 ∪ 未跟踪新文件。
    `paths is None` ⇒ 取不到（不在 git 仓库 / 没有 git / 命令失败）。调用方必须据此判 ``unknown``：取不到就是没查成，不是干净。
    ## 为什么不能只用 `git diff --name-only HEAD`（实测的两条绕过路径）
    1. 提交即隐身：它比的是"工作区/索引 vs HEAD" ⇒ 把禁改区改动提交掉之后
    就再也看不见了。临时仓库实测：改禁改区文件不提交 ⇒ `requires_human`(1)；把同一改动提交 ⇒ `clean`(0)，而 `git log --name-only` 显示它就在那条 commit 里。
    2. 新建即隐身：`git diff` 只报已跟踪文件 ⇒ 在清单登记过的路径上新建一个
    文件同样看不见。临时仓库实测：新建后 ⇒ `clean`(0)，`git add` 后 ⇒ `requires_human`(1)。而清单里
    `src/agentflow/release_check.py` 的登记理由逐字就是"一旦有人在这里新建它，会自动落入清单" —— 这条绕过路径打掉的正是它自己要防的那件事。
    所以路径集合是三者之并（去重），且范围写进 `reason`："查了哪些东西"与"结论是什么"同等重要。`since` 给定时才覆盖已提交改动；不给则调用方必须把"空改动集"判成 `unknown` 而不是
    `clean`（见 `main` 里的真空保护）。
    """
    repo = Path(root) if root is not None else project_root()
    if since:
        # 退化基线（`F-R1d-01`，最后一次集中审查的 high）：`--since HEAD` 的
        # `HEAD..HEAD` 恒为空，于是"已提交的禁改区改动"在这一跑里整体隐身 ——
        # 而 `release_all --since HEAD`（本仓的标准起跑方式）会把这种状态下的
        # `noai` 记成 pass。判据：把 `since` 与 `HEAD` 都交给 git 解析，
        # 解析到同一个提交就判"没查成"（返回 None ⇒ 调用方落 unknown(2)），
        # 绝不返回一个空改动集让上层读成 clean。
        head_sha, head_err = _git_lines(repo, ["rev-parse", "HEAD"])
        since_sha, since_err = _git_lines(repo, ["rev-parse", since])
        if head_sha is None or since_sha is None:
            return None, (f"退化基线检查取不到 ref（HEAD：{head_err or 'ok'}；"
                          f"{since}：{since_err or 'ok'}）")
        if head_sha and since_sha and head_sha[0] == since_sha[0]:
            return None, (
                f"退化基线：`--since {since}` 与 HEAD 解析到同一个提交"
                f"（{head_sha[0][:12]}…）⇒ `{since}..HEAD` 恒为空，"
                "已提交的禁改区改动会整体隐身（`git diff HEAD` 只看未提交与未跟踪）。"
                "请给一个真正的基线 ref（上一个里程碑的提交 / tag），"
                "否则这一跑判 unknown，不判 clean"
            )
    scopes: list[tuple[str, list[str]]] = []
    if since:
        scopes.append((f"已提交 {since}..HEAD", ["diff", "--name-only", f"{since}..HEAD"]))
    scopes.append(("未提交改动", ["diff", "--name-only", "HEAD"]))
    scopes.append(("未跟踪新文件", ["ls-files", "--others", "--exclude-standard"]))

    seen: dict[str, None] = {}
    for _label, argv in scopes:
        got, err = _git_lines(repo, argv)
        if got is None:
            return None, err
        for p in got:
            seen[p] = None
    paths = list(seen)
    scope_text = " + ".join(label for label, _ in scopes)
    return paths, f"git 报告 {len(paths)} 条改动路径（范围：{scope_text}）"



# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="noai_gate",
        description=(
            "FC-27 禁 AI 区门禁：判定改动是否落在人类专属区。"
            "退出码 0=clean，1=requires_human，2=unknown（**没检查成**，不是没问题）。"
        ),
    )
    p.add_argument("--paths", nargs="*", default=None, metavar="PATH", help="要判定的改动路径（可多条）")
    p.add_argument("--stdin", action="store_true", help="从 stdin 逐行读改动路径")
    p.add_argument(
        "--git",
        action="store_true",
        help=(
            "取改动路径：已提交的 `--since <ref>..HEAD`（给了 --since 时）"
            " ∪ 未提交改动 ∪ **未跟踪的新文件**"
        ),
    )
    p.add_argument(
        "--since",
        default=None,
        metavar="REF",
        help=(
            "与 `--git` 配合的基线 ref：改动集 = `git diff --name-only REF..HEAD` ∪ 未提交"
            " ∪ 未跟踪。**CI 必须给这个**：不给时本门看不见已提交的改动，"
            "改动集为空会判 unknown(2) 而不是 clean。"
        ),
    )
    p.add_argument("--json", action="store_true", help="以 JSON 输出 GateResult")
    p.add_argument("-q", "--quiet", action="store_true", help="只返回退出码，不打印")
    p.add_argument("--manifest", default=None, help=f"清单路径（默认 <root>/{MANIFEST_NAME}）")
    p.add_argument(
        "--agents-md",
        default=None,
        type=Path,
        help=f"{AGENTS_NAME} 路径（仅用于 --check-consistency；默认 <root>/{AGENTS_NAME}）",
    )
    p.add_argument("--root", default=None, help="仓库根（默认自动探测）")
    p.add_argument(
        "--print-changed",
        action="store_true",
        help=(
            "把改动集逐行打到 stdout（供编排层喂给别的门）。取不到 ⇒ 退出码 2 并把原因写到 stderr。"
            "改动集的唯一实现就在这里，编排层不许自己再写一份 git 口径。"
        ),
    )
    p.add_argument(
        "--check-consistency",
        action="store_true",
        help=(
            f"检查 {MANIFEST_NAME} 与 {AGENTS_NAME} 是否逐条一致。"
            "退出码：0=一致；1=不一致（门坏了，必须人改清单）；2=没查成（读不到清单/AGENTS.md）。"
            "这套码只属于本命令：改动集判定模式下的 1 是 requires_human。"
        ),
    )
    p.add_argument(
        "--check-ledger",
        action="store_true",
        help=(
            f"只读对账（`H-11`）：{MANIFEST_NAME} 里的每条唯一路径，{LEDGER_NAME} 里是否都有条目。"
            "只查这一个方向：台账里那些清单外的历史条目不算缺陷（不要求对称）。"
            "差集分两类 —— 盘上不存在的标『刻意预登记』，其余标『漏登记』；漏登记 ⇒ 非零退出。"
            "退出码：0=干净（差集只剩刻意预登记）；1=有漏登记（人去补登记）；"
            "2=没查成（清单或台账读不到 / 解析不了）。这套码只属于本命令，"
            "不改改动集判定模式的码表。本命令只读，不写任何文件。"
        ),
    )
    # ---- hash 台账（批准记录）
    p.add_argument(
        "--check-approvals",
        action="store_true",
        help=(
            "与 `--paths`/`--stdin`/`--git` 之一配合：命中禁改区后**用台账判定**"
            "『被批准的那一版是不是盘上这一版』。台账读不到/解析不了 ⇒ unknown(2)。"
        ),
    )
    p.add_argument(
        "--check-canonical",
        action="store_true",
        help=(
            "只查一件事：本门用的规范哈希与 `agentflow.signatures` 用的是不是**同一份口径**"
            "（`R-33`）。一致 ⇒ 0；不一致 ⇒ 1（有人又写了一份内联实现）；"
            "本包 import 不了 ⇒ 2（没查成，**不许**读成一致）。不需要 `--paths`。"
        ),
    )
    p.add_argument(
        "--ledger",
        default=None,
        metavar="PATH",
        help=f"台账路径（默认 <root>/{LEDGER_NAME}）",
    )
    p.add_argument(
        "--baseline",
        action="store_true",
        help=(
            "为 `--paths` 给的路径**登记/刷新**台账条目（写 sha256 + glob + category）。"
            "⚠️ **登记 ≠ 批准**：本动作**绝不写 reviewers**（走查记录只能由人 `--approve` 追加）。"
        ),
    )
    p.add_argument(
        "--note",
        default="",
        help="`--baseline` 的变更摘要，或 `--approve` 的走查结论（记进台账，便于下次比对）",
    )
    p.add_argument(
        "--authored",
        choices=AUTHORED_VALUES,
        default=None,
        help=(
            "仅 `--baseline`：登记的署名（谁写的这一段）。"
            "**判不出来就别给**（新条目落 `unknown`，已有条目保留原值），不许猜"
        ),
    )
    p.add_argument(
        "--authored-basis",
        choices=AUTHORED_BASIS_VALUES,
        default=None,
        help=(
            "仅 `--baseline`：`authored` 这个结论的**依据**（台账里必填，缺了就是结构不合规）。"
            "`attested` = 有直接证据（改动者/签字人声明，门无法机械验证）；"
            "`inferred` = 从 mtime 与会话边界**推断**（默认）。"
            "结论与依据必须分开写：`inferred` 的条目在输出里会显式标注『非独立证据』"
        ),
    )
    p.add_argument(
        "--this-session",
        choices=("changed", "unchanged", "unknown"),
        default="unknown",
        help=(
            "仅 `--baseline`：本轮是否改过这个文件。`unknown` = **无法从仓库判定**"
            "（三态：『登记了它』与『它被改过』是两件事，台账必须能分开表达）"
        ),
    )
    p.add_argument(
        "--approve",
        default=None,
        metavar="PATH",
        help=(
            "给人用：为某一条追加一个 reviewer 记录（**AI 不得运行本命令** —— "
            "批准是人的动作，AI 代签等于自己给自己发批准）。"
            "会先断言该条 hash 与磁盘一致，不一致就拒绝写入并以退出码 2 结束。"
        ),
    )
    p.add_argument("--reviewer", default="", metavar="NAME", help="仅 `--approve`：走查人姓名（**必须是人**）")
    p.add_argument(
        "--scope",
        default="",
        metavar="TEXT",
        help="仅 `--approve`：走了哪些行/函数（必须具体到符号或行区间；写『看过了』等于没看）",
    )
    p.add_argument(
        "--verdict",
        default="逐行走查通过",
        help="仅 `--approve`：走查结论",
    )
    p.add_argument(
        "--record-audit",
        default=None,
        metavar="PATH",
        help=(
            "记录一次**机器审计**（第二条通路，口径由所有者于 2026-09-26 批准）："
            "多个子代理 × 多个维度独立审计、全部未发现问题 ⇒ 视为通过。"
            "**绝不写 `reviewers`**：两条通路在台账里分列。"
            "会先断言该条 hash 与磁盘一致；不一致就拒绝写入并以退出码 2 结束。"
            "必须同时给 `--auditor` / `--dimension` / `--evidence` / `--negative-control` / "
            "`--evidence-path`（证据必须是盘上的一个文件；只给一句话会被拒 —— "
            "`temp/verify-audit-forge.txt` 实测过编一个不存在的路径也曾让门报 clean）。"
        ),
    )
    p.add_argument("--auditor", default="", metavar="NAME", help="仅 `--record-audit`：审计者标识（不得是该条目的署名者）")
    p.add_argument(
        "--dimension",
        default="",
        metavar="DIM",
        help=f"仅 `--record-audit`：受控词表里的一个维度（{list(AUDIT_DIMENSIONS)}）",
    )
    p.add_argument("--evidence", default="", metavar="PATH_OR_TEXT", help="仅 `--record-audit`：可复核的原始输出位置（人读的那句话）")
    p.add_argument(
        "--evidence-path",
        default="",
        metavar="PATH",
        help=(
            "`--record-audit` 必需 / `--approve` 可选：证据**文件**（相对仓库根或绝对路径）。"
            "写入时读它并算 sha256 存进台账，门每次判定时重算核对；读不到 ⇒ 拒绝写入。"
            "`FINAL-R1d-04` 之后 `--approve` 也吃它：人审通路从此可以有与机审同构的内容锚"
            "（不给也仍然能签，但 approved 那一行会写明有几条带锚）。"
        ),
    )
    p.add_argument(
        "--evidence-sha256",
        default="",
        metavar="HEX64",
        help=(
            "仅 `--record-audit`：证据文件的 sha256（不给就现场算）。给了但与盘上不一致 ⇒ "
            "拒绝写入 —— 那一档防的是'登记一个别处的 hash'。"
        ),
    )
    p.add_argument(
        "--receipt-log",
        default=None,
        metavar="PATH",
        help=(
            f"回执链的落点（默认 `<root>/{AUDIT_RECEIPT_NAME}`）。每写一次审计就追加一环，"
            "每条把前一条的 hash 写进自己参与 hash 的内容里 ⇒ 事后删/改一条都会断链。"
            "门在判定机审通路时会重算整条链；链缺失/断链/没有这一版的记录 ⇒ unknown。"
            "此参数主要给核验与测试用（生产路径恒用仓库默认落点）。"
        ),
    )
    p.add_argument(
        "--negative-control",
        default="",
        metavar="TEXT",
        help=(
            "仅 `--record-audit`：**证明这次审计有能力发现问题** —— "
            "拿同一套判据去审改前那一版（`git show HEAD:<path>`）或已知坏样本，"
            "它必须报出这次修掉的那个缺陷。空 ⇒ 拒绝写入（否则'未发现问题'是真空的）。"
        ),
    )
    p.add_argument(
        "--finding",
        action="append",
        default=None,
        metavar="TEXT",
        help="仅 `--record-audit`：审计**发现了**的问题（可多次）。有 finding ⇒ 这一条不放行并列出原文。",
    )
    p.add_argument("--audit-scope", default="", metavar="TEXT", help="仅 `--record-audit`：这次审计覆盖了哪些符号/文件（必填；至少一个符号名要能在证据文件里找到）")
    p.add_argument("--audit-started-sha256", default="", metavar="HEX",
                   help="仅 `--record-audit`：**开审那一刻**被审对象的 sha256（必填，且必须与台账这一版一致）—— `c-20`")
    p.add_argument("--independence", default="", metavar="TEXT",
                   help="仅 `--record-audit`：台账署名者为空/unknown 时的独立性声明（必填）—— `H-1e`")
    return p


def _say(args: argparse.Namespace, text: str) -> None:
    if not args.quiet:
        print(text)


def _fail(args: argparse.Namespace, action: str, message: str) -> int:
    """写动作失败 ⇒ 退出码 2（"没做成"），不是 1（"查了，未批准"）。"""
    _say(args, f"[{action}] unknown(2)：{message}")
    return 2


def _write_action_paths(args: argparse.Namespace, root: Path) -> tuple[Path, Path]:
    """`--baseline` / `--approve` 用的 `(清单路径, 台账路径)`。

    与 `check_paths` 的默认解析略有不同是刻意的：这两个动作是写动作，
    写错地方（把 A 的基线写进 B 的台账）不可逆，所以按显式 `--root` 走，
    而不是按"这个脚本恰好在哪个目录"猜。默认 `--root` 就是仓库根 ⇒ 两者一致。
    """
    manifest_p = Path(args.manifest) if args.manifest else (root / MANIFEST_NAME)
    ledger_p = Path(args.ledger) if args.ledger else (root / LEDGER_NAME)
    return manifest_p, ledger_p


def _run_baseline(args: argparse.Namespace, root: Path) -> int:
    """`--baseline`：登记/刷新 hash。不写 reviewers（登记 ≠ 批准）。"""
    paths = [p for p in (args.paths or []) if str(p).strip()]
    if not paths:
        return _fail(args, "baseline", "没有给 `--paths` ⇒ 没有要登记的东西（没有输入就没有登记）")

    manifest_p, ledger_p = _write_action_paths(args, root)
    try:
        # 台账不存在 ⇒ 从空台账开始（这是"写"动作，空是字面意义上的没有记录）。
        # 注意这与 `--check-approvals` 的读路径相反：那里"读不到"必须是 unknown。
        ledger = load_ledger(ledger_p) if ledger_p.is_file() else Ledger(LEDGER_VERSION, _now_iso(), ())
    except LedgerError as exc:
        return _fail(args, "baseline", f"已有台账读不了，不能拿它当基础刷新：{exc}")

    keys = [_repo_rel_key(p, root) for p in paths]
    cts = {"changed": True, "unchanged": False, "unknown": None}[args.this_session]
    try:
        new_ledger, results = register_baseline(
            paths,
            manifest=manifest_p,
            root=root,
            ledger=ledger,
            notes={k: args.note for k in keys} if args.note.strip() else {},
            # `--authored` / `--authored-basis` 显式给了就写（hash 未变也写）：
            # 对同一版内容给出更强的归属声明是改进，不是换对象；两者的行为必须对称
            # （否则"署名改了、依据没改"这种半截状态会静默出现）。
            authored={k: args.authored for k in keys} if args.authored else {},
            default_authored=args.authored or "unknown",
            authored_basis={k: args.authored_basis for k in keys} if args.authored_basis else {},
            default_authored_basis=args.authored_basis or "inferred",
            changed_this_session={k: cts for k in keys},
        )
    except (NoaiError, LedgerError) as exc:
        return _fail(args, "baseline", f"登记没能完成：{exc}")

    try:
        _write_ledger_atomic(new_ledger, ledger_p)
    except LedgerError as exc:
        return _fail(args, "baseline", f"台账写入失败（**没有登记成功**）：{exc}")

    bad = [r for r in results if r["status"] in ("not_in_manifest", "hash_unavailable")]
    _say(args, f"[baseline] 登记 {len(results) - len(bad)} 条 / 未登记 {len(bad)} 条；台账：{ledger_p}")
    for r in results:
        if r["status"] in ("not_in_manifest", "hash_unavailable"):
            _say(args, f"  ! {r['path']}  {r['status']}：{r['detail']}")
        else:
            _say(
                args,
                f"  · {r['path']}  {r['status']}  sha256 {r['sha256'][:12]}  "
                f"[{r['category']}]  authored={r.get('authored', '')}"
                f"/{r.get('authored_basis', '')}  reviewers={r.get('reviewers', 0)}"
                "（**登记 ≠ 批准**，reviewers 只能由人 `--approve` 追加）",
            )
    return 2 if bad else 0


def _run_approve(args: argparse.Namespace, root: Path) -> int:
    """`--approve`：人追加一条走查记录。hash 不一致 ⇒ 拒绝写入 + 退出码 2。"""
    target = args.approve
    if not target or not str(target).strip():
        return _fail(args, "approve", "`--approve` 后面要给一个路径")
    _manifest_p, ledger_p = _write_action_paths(args, root)
    if not ledger_p.is_file():
        return _fail(
            args, "approve", f"台账不存在：{ledger_p} —— 先 `--baseline` 登记这一版，再走查签字"
        )
    try:
        ledger = load_ledger(ledger_p)
    except LedgerError as exc:
        return _fail(args, "approve", f"台账读不了，不能往一份读不懂的台账里签字：{exc}")
    try:
        new_ledger, info = add_approval(
            ledger,
            target,
            reviewer=args.reviewer,
            scope=args.scope,
            note=args.note,
            verdict=args.verdict,
            evidence_path=getattr(args, "evidence_path", "") or "",
            root=root,
        )
    except LedgerError as exc:
        return _fail(args, "approve", str(exc))
    try:
        _write_ledger_atomic(new_ledger, ledger_p)
    except LedgerError as exc:
        return _fail(args, "approve", f"台账写入失败（**签字没有落盘**）：{exc}")

    _say(
        args,
        f"[approve] {info['path']} 已追加 reviewer「{info['appended']['name']}」—— "
        f"不同 reviewer {info['distinct_reviewers']}/{info['required']}"
        f"（记录 {info['reviewers']} 条）",
    )
    _say(args, f"  at: {info['appended']['at']}")
    _say(args, f"  scope: {info['appended']['scope']}")
    _say(args, f"  verdict: {info['appended']['verdict']}")
    if info["duplicate_name"]:
        _say(
            args,
            "  ⚠️ 这个名字已经签过这一条（按归一化后的姓名判重：全角/零宽/尾空格算同一个）—— "
            "记录照实保留，但**批准数按不同姓名计**，"
            "所以它没有让 2 名 reviewer 的门槛前进（同一个人签两次不是两名 reviewer）",
        )
    if info["distinct_reviewers"] < info["required"]:
        _say(args, f"  ⇒ 还差 {info['required'] - info['distinct_reviewers']} 名不同 reviewer 才算批准")
    return 0


def _run_record_audit(args: argparse.Namespace, root: Path) -> int:
    """`--record-audit`：记录一次机器审计（第二条通路）。hash 不一致 ⇒ 拒绝写入 + 退出码 2。"""
    target = args.record_audit
    if not target or not str(target).strip():
        return _fail(args, "record-audit", "`--record-audit` 后面要给一个路径")
    _manifest_p, ledger_p = _write_action_paths(args, root)
    if not ledger_p.is_file():
        return _fail(
            args, "record-audit", f"台账不存在：{ledger_p} —— 先 `--baseline` 登记这一版，再审计"
        )
    try:
        ledger = load_ledger(ledger_p)
    except LedgerError as exc:
        return _fail(args, "record-audit", f"台账读不了，不能往一份读不懂的台账里写审计：{exc}")
    try:
        new_ledger, info = record_audit(
            ledger,
            target,
            auditor=args.auditor,
            dimension=args.dimension,
            evidence=args.evidence,
            negative_control=args.negative_control,
            evidence_path=args.evidence_path,
            evidence_sha256=args.evidence_sha256,
            findings=tuple(args.finding or ()),
            scope=args.audit_scope,
            audit_started_sha256=getattr(args, "audit_started_sha256", "") or "",
            independence=getattr(args, "independence", "") or "",
            root=root,
            receipt_log=args.receipt_log,
        )
    except LedgerError as exc:
        return _fail(args, "record-audit", str(exc))
    try:
        _write_ledger_atomic(new_ledger, ledger_p)
    except LedgerError as exc:
        return _fail(args, "record-audit", f"台账写入失败（**审计没有落盘**）：{exc}")

    a = info["appended"]
    # `R6-R1d-6`：这里曾经用 `len(info['distinct_dimensions'])`（先取长度再格式化），
    # 而 `evaluate_approval` 的 JSON 里同名字段是列表 —— 同一条通路的同名字段
    # 两处口径不一致。现在用写入侧显式给出的计数名，两处口径逐字相同。
    dimension_count = info["distinct_dimension_count"]
    _say(
        args,
        f"[record-audit] {info['path']} 已记录审计「{a['auditor']}」维度 {a['dimension']} —— "
        f"清白审计 {info['clean_audits']} 条 / 不同审计者 {info['distinct_auditors']}"
        f"/{info['required_auditors']} / 不同维度 {dimension_count}"
        f"/{info['required_dimensions']}（{', '.join(info['distinct_dimensions']) or '无'}）",
    )
    surfaces = info["observation_surfaces"]
    _say(
        args,
        f"  观察面 {len(surfaces)} 个（{', '.join(surfaces) or '无'}）—— "
        "`dimension` 是自填标签，判定侧还要问『这些维度背后有几个**不同的 scope 落点**、"
        "是不是同一名审计者独占』（`R5-R1b-1`）",
    )
    # `R6-R1d-1` / `R6-R1d-6`：写入侧这一处判据要自己读被审对象 ——
    # 此前它读的是 `info["_target_text"]`（`record_audit` 的内部中间量：
    # 变量名从 `updated` 换成 `new_ledger` 时那一行被漏改 ⇒ 整条 CLI 通路
    # 以未捕获的 `NameError` 结束）。现在与判定侧同构：自己 `_target_path()` + 读文本。
    target_text = ""
    try:
        target_text = _target_path(target, root).read_text(encoding="utf-8", errors="replace")
    except (OSError, LedgerError):
        # 读不到被审对象 ⇒ 下面那条判据会因为"标识符集合为空"直接报出来，
        # 不在这里吞成"没问题"（与判定侧 `evaluate_approval` 的那一支逐字同构）。
        target_text = ""
    dim_problem = dimension_independence_problem(
        new_ledger.entry_for(info["path"]).counted_audits, target_text
    )
    if dim_problem:
        _say(
            args,
            "  ⚠️ 维度独立性这一条**现在还不满足** ⇒ 判定侧不会放行：" + dim_problem,
        )
    _say(args, f"  sha256 钉住：{a['sha256'][:12]}（与台账条目一致才计数）")
    _say(
        args,
        f"  at：{a['at']}（审计者**自报**的时间戳：判定侧只核对它能否解析、"
        "是否落在未来、以及整串次序是否非递减 —— `R5-R1b-7` / `R6-R1d-3`）",
    )
    _say(args, f"  负控：{a['negative_control']}")
    _say(args, f"  证据：{a['evidence']}")
    _say(
        args,
        f"  证据锚：{info['evidence_file']} ⇒ sha256 {info['evidence_sha256'][:12]}"
        "（门每次判定都会重算它；对不上 ⇒ unknown）",
    )
    _say(
        args,
        f"  回执链：已追加第 {info['receipt']['hash'][:12]} 环"
        "（只增；链断或没有这一版 ⇒ 判 unknown）",
    )
    if info["auditor_is_author"]:
        _say(
            args,
            "  ⚠️ 这个 auditor 与该条目的署名者同名 —— 自己审自己不算独立复核，"
            "请换一个**没有写过这些文件**的审计者，并在证据里写明独立性来源",
        )
    if info["findings"]:
        _say(args, f"  ⚠️ 这次审计**报了 {len(info['findings'])} 条 finding** ⇒ 该条不放行：")
        for f in info["findings"]:
            _say(args, f"      - {f}")
    elif (
        info["distinct_auditors"] >= info["required_auditors"]
        and dimension_count >= info["required_dimensions"]
        and not dim_problem
    ):
        _say(
            args,
            "  ⇒ 机审通路**已满足**（≥2 名不同审计者 × ≥3 个维度、维度各有独立落点且不"
            "由同一名审计者独占、全部清白且带负控）",
        )
    else:
        miss = (
            f"不同审计者 {max(0, info['required_auditors'] - info['distinct_auditors'])} 名"
            f"、不同维度 {max(0, info['required_dimensions'] - dimension_count)} 个"
        )
        if dim_problem:
            miss += "、维度独立性（见上面那条 ⚠️）"
        _say(args, f"  ⇒ 还差：{miss}")
    return 0


def _run_check_ledger(args: argparse.Namespace, root: Path) -> int:
    """`--check-ledger`：只读对账，一个字节都不写。

    退出码：0 = 差集里只剩刻意预登记（或差集为空）；1 = 有漏登记（人去补登记）；
    2 = 没查成（清单或台账读不到 / 解析不了）。本命令没有写动作，
    所以"做成了没有"这一档（写动作的 2）在这里不存在，2 只表示没查成。
    """
    rec = check_manifest_ledger(
        manifest_path=args.manifest,
        ledger_path=args.ledger,
        root=root,
    )
    if args.quiet:
        return rec.exit_code
    if args.json:
        print(json.dumps(rec.to_dict(), ensure_ascii=False, indent=2))
        return rec.exit_code

    print(f"[{rec.verdict}] check-ledger")
    print(rec.explanation)
    for row in rec.pre_registered:
        print(
            f"  · 刻意预登记（盘上不存在，先登记路径）：{row['path']}"
            f"  [{row['category']}]"
        )
    for row in rec.missing_registration:
        print(
            f"  ! 漏登记（盘上存在、台账里没有条目）：{row['path']}"
            f"  [{row['category']}]"
        )
    if rec.ledger_only:
        print(
            f"  · 台账里另有 {len(rec.ledger_only)} 条清单外的历史条目"
            "（本命令不要求对称，它们不是缺陷）：" + "、".join(rec.ledger_only)
        )
    print(f"  台账：{rec.ledger}")
    return rec.exit_code


def _pin_utf8() -> None:
    """钉住 stdout/stderr 的编码。

    内联的理由与 `scripts/lint_rules.py` / `tools/coverage_zero_test.py` 同：门脚本必须
    在本包 import 不了时也能跑。规范实现见 `src/agentflow/console.py::pin_utf8`。

    对本门尤其要紧：`_emit` 会打印含 `⇒` 的行，而不钉编码时 GBK 重定向下会抛
    UnicodeEncodeError ⇒ 进程以 1 结束 ⇒ "崩了"与"requires_human"同码（都是 1），
    调用方再也分不出"要人走查"和"门自己坏了"。`--quiet` 恰好绕开这个坑，这本身就说明
    问题——不该只有 quiet 模式是可信通道。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # 可以忽略：被重定向或被替换过的流可能没有 reconfigure，不该让门崩掉。
            pass


def _suspect_paths_values(paths: Sequence[str] | None) -> list[str]:
    """    挑出 `--paths` 里含逗号或换行的取值（`G-46`：它们会被静默读成一条路径）。
    ## 为什么这是一个假 clean 的入口（`G-38` 同族）
    `--paths` 是 `nargs="*"` ⇒ 逗号不是分隔符。整串 `"a.py,b.py"` 被当成一条路径，不匹配任何 glob ⇒ 门报 `clean(0)`。实测（`temp/G46-evidence.md`）：
    --paths "src/agentflow/schema.py,src/agentflow/verify.py"   → [clean] exit=0   ← 假 clean
    --paths "src/agentflow/schema.py" "src/agentflow/verify.py" → [requires_human] exit=1
    这与 `G-38` 同族：门的输入管线能把"我查了 N 条"变成"我查了别的"，而结论照样是绿的。
    ## 为什么拒绝而不是自动按逗号切分
    逗号在 Windows 文件名里合法。按逗号切分同样是假话：它把一次"输入写错了"静默改写成"我替你查了这几条"，而且当真有一个文件名带逗号时会把一条路径切成两条错的。所以这里 fail-closed：可疑形态 ⇒ `unknown(2)`（没查成），
    并原样回显那个取值。
    换行同理：命令替换/多行变量传进来时会变成一条含换行的路径，同样不匹配任何 glob。
    """
    out: list[str] = []
    for p in paths or ():
        text = str(p)
        if "," in text or "\n" in text or "\r" in text:
            out.append(text)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口。返回退出码（不是 None）—— 门必须有退出码。"""
    _pin_utf8()
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    root = Path(args.root) if args.root else project_root()

    # ---- 编排层要的"只把改动集打出来"模式：先于一切判定动作处理。
    if args.print_changed:
        paths, reason = git_changed_paths(root, since=args.since)
        if paths is None:
            print(f"[unknown] {reason}", file=sys.stderr)
            return 2
        for p in paths:
            print(p)
        return 0

    if args.check_consistency:
        # 两个落点都按 `--root` 显式解析出来，不交给 `load_manifest(None)` /
        # `parse_agents_block(None)`：那两条路走 `project_root()`，是"这个脚本恰好
        # 在哪个目录"，与 `--root` 无关（`check_paths` 的注释与 `--check-ledger`
        # 都是显式拼 `repo`，一致性检查此前是唯一没跟上的）。
        manifest_p = Path(args.manifest) if args.manifest else (root / MANIFEST_NAME)
        agents_p = Path(args.agents_md) if args.agents_md else (root / AGENTS_NAME)

        # "读不到"必须自成一档（2 = 没查成），不许折进 1（"查过了、结论是不一致"）
        # —— 把"没查成"读成"有人只改了一处"正是三态纪律要防的折叠。这里先对两个
        # 已解析出的路径各探一次读；`OSError` ⇒ 打印 unknown 并返回 2。
        # 刻意不动 `check_manifest_consistency` 的函数级契约：它按设计把 parse 级
        # 错误当差异返回（既有用例依赖这一点），所以 parse 级失败仍走 diffs ⇒ 1。
        for label, probe in ((MANIFEST_NAME, manifest_p), (AGENTS_NAME, agents_p)):
            try:
                probe.read_text(encoding="utf-8")
            except OSError as exc:
                _say(
                    args,
                    f"unknown：一致性检查没查成（{label} 读不到）⇒ 不代表两处一致。"
                    f"原因：{type(exc).__name__}: {exc}",
                )
                return 2

        diffs = check_manifest_consistency(manifest_path=manifest_p, agents_md=agents_p)
        if args.quiet:
            pass
        elif args.json:
            print(json.dumps({"consistent": not diffs, "diffs": diffs}, ensure_ascii=False, indent=2))
        elif diffs:
            print(f"不一致：{MANIFEST_NAME} 与 {AGENTS_NAME} 的清单有 {len(diffs)} 处差异")
            for d in diffs:
                print(f"  - {d}")
        else:
            print(f"一致：{MANIFEST_NAME} 与 {AGENTS_NAME} 的清单逐条相同")
        # 一致性检查是前置门，但它有自己的码表（与改动集判定模式不是同一套）：
        # 0 = 一致；1 = 不一致（门坏了，必须人改清单）；2 = 没查成（读不到清单/AGENTS.md）。
        # 原来这里把"不一致"返回 2，而 2 在本项目里是 unknown（没查成）—— 同一个码背两个
        # 互相排斥的含义，调用方就没法据码行事。
        return 0 if not diffs else 1

    if args.check_ledger:
        # 只读对账：与 `--check-consistency` 同属"清单级"检查，所以同样先于改动集判定，
        # 也先于 `G-46` 那条可疑 `--paths` 拒绝（本命令不看 `--paths`，
        # 不该因为别处给了一串带逗号的路径而判成没查成）。
        return _run_check_ledger(args, root)

    # ---- `--check-canonical`（`R-33`）：只查"规范哈希是不是只有一份口径"。
    #
    # 为什么排在 `--paths` 那些动作之前：它不看改动集，也不写任何东西 ——
    # 它问的是一个全局事实（门与 signatures 的口径是否同一份）。
    # 让一串可疑的 `--paths` 把它拦下来，会把"口径分叉了吗"答成"你的路径写得不对"。
    if args.check_canonical:
        report = check_canonical_consistency()
        status = str(report.get("status") or "unknown")
        if status == "consistent":
            print(f"[canonical] consistent：{report['detail']}")
            print(f"            门侧 …{str(report.get('gate_hash'))[:16]} ／ "
                  f"signatures 侧 …{str(report.get('signatures_hash'))[:16]}")
            return 0
        if status == "divergent":
            print(f"[canonical] DIVERGENT（exit 1）：{report['detail']}", file=sys.stderr)
            return 1
        print(f"[canonical] unknown（exit 2）：{report['detail']}", file=sys.stderr)
        return 2

    # ---- `G-46`：可疑的 `--paths` 取值先于一切动作处理（含 `--baseline` / `--approve`）。
    #
    # 为什么必须在写动作之前：`--baseline --paths "a.py,b.py"` 会把那整串当成一条
    # glob 登记进台账 —— 于是台账里多一条永远匹配不到任何东西的记录，而没有任何东西会红。
    # 那比一次假 clean 更难发现（假 clean 至少只影响这一次判定，脏台账会一直在）。
    suspect = _suspect_paths_values(args.paths)
    if suspect:
        shown = " | ".join(repr(s) for s in suspect)
        result = GateResult(
            verdict="unknown",
            explanation=(
                f"unknown：`--paths` 里有 {len(suspect)} 个取值含逗号或换行，"
                f"而逗号/换行**不是**本门的分隔符 ⇒ 整串会被当成**一条**路径，"
                f"不匹配任何 glob 时就会报 clean（假绿）。"
                f"可疑取值（原样回显）：{shown}\n"
                "正确用法：`--paths a b c`（**空格分隔**多条）或 `--stdin`（每行一条路径）"
                "或 `--git`（按 git 改动集）。\n"
                "刻意**不**自动按逗号切分：逗号在 Windows 文件名里合法，切分同样是假话。"
            ),
            manifest_issues=["suspect --paths value (comma or newline)"],
        )
        _emit(result, args.json, args.quiet)
        return result.exit_code

    # ---- 写动作（登记 / 签字）先于判定动作处理：它们的退出码语义是"做成了没有"。
    if args.baseline:
        return _run_baseline(args, root)
    if args.approve is not None:
        return _run_approve(args, root)
    if args.record_audit is not None:
        return _run_record_audit(args, root)

    sources = [bool(args.paths is not None), bool(args.stdin), bool(args.git)]
    if sum(sources) == 0:
        result = GateResult(
            verdict="unknown",
            explanation=(
                "unknown：没有给出改动集（请用 `--paths` / `--stdin` / `--git`）—— "
                "**没有输入就没有检查**，不能读成 clean。"
            ),
            manifest_issues=["no input"],
        )
        _emit(result, args.json, args.quiet)
        return result.exit_code
    if sum(sources) > 1:
        result = GateResult(
            verdict="unknown",
            explanation=(
                "unknown：`--paths` / `--stdin` / `--git` 只能给一个 —— "
                "两个来源混在一起时无法判断『这次到底检查了哪些路径』，所以不给结论。"
            ),
            manifest_issues=["ambiguous input"],
        )
        _emit(result, args.json, args.quiet)
        return result.exit_code

    if args.git:
        paths, reason = git_changed_paths(root, since=args.since)
        if paths is None:
            result = GateResult(
                verdict="unknown",
                explanation=(
                    f"unknown：无法从 git 取到改动集 ⇒ **本次没有检查**，不代表没问题。原因：{reason}"
                ),
                manifest_issues=[reason],
            )
            _emit(result, args.json, args.quiet)
            return result.exit_code
        if not paths and not args.since:
            # 真空保护：空改动集不是 clean。本命令没有基线就看不见已提交的改动，
            # 而"把禁改区改动提交掉"正是实测过的一条绕过路径（见 git_changed_paths）。
            result = GateResult(
                verdict="unknown",
                explanation=(
                    "unknown：改动集为空，而本次没有声明基线（`--since <ref>`）—— "
                    "本门只看未提交改动与未跟踪新文件，**看不见已经提交的改动**，"
                    f"所以『0 条路径』不等于 clean。要判定请给 `--since <ref>`（CI 用）"
                    f"或显式 `--paths`。范围：{reason}"
                ),
                manifest_issues=["no baseline; empty change set"],
            )
            _emit(result, args.json, args.quiet)
            return result.exit_code
    elif args.stdin:
        paths = [ln.strip() for ln in sys.stdin.read().splitlines() if ln.strip()]
    else:
        paths = list(args.paths or [])

    if args.check_approvals:
        result = check_approvals(
            paths,
            manifest=args.manifest,
            ledger_path=args.ledger,
            root=root,
            receipt_log=args.receipt_log,
        )
    else:
        result = check_paths(paths, manifest=args.manifest, root=root)
    _emit(result, args.json, args.quiet)
    return result.exit_code


def _emit(result: GateResult, as_json: bool, quiet: bool = False) -> None:
    if quiet:
        return
    if as_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return
    print(f"[{result.verdict}] required_approvals={result.required_approvals}")
    print(result.explanation)
    for v in result.violations:
        print(f"  - {v['path']}  命中 {v['glob']}  [{v['category']}]  {v['reason']}")
        if v.get("approval_reason"):
            # 台账判定这一层的理由码必须单独打出来：`unregistered`（从没登记）与
            # `stale`（登记过但版本漂了）的处置动作不同，折叠成一个"未批准"就没法动作。
            print(f"      ⇒ [{v['approval_status']}] {v['approval_reason']}：{v.get('detail', '')}")
    for a in result.approvals:
        if a["approval_status"] != "unapproved":
            print(f"  - {a['path']}  [{a['approval_status']}] {a['approval_reason']}：{a.get('detail', '')}")
    if result.ledger:
        print(f"  台账（批准记录的权威副本）：{result.ledger}")


if __name__ == "__main__":  # pragma: no cover - 由 tests 直接调 main()，这里只为手工运行
    raise SystemExit(main())

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""FC-27 禁 AI 区门禁 —— 机器可执行的检查器。

## 它检查什么

`.noai-paths` 是一份 glob 清单（FC-27 的"机器可读禁改区清单"）。本模块：

1. :func:`load_manifest` —— 解析 `.noai-paths` ⇒ `list[Rule]`。
2. :func:`parse_agents_block` —— 解析 `AGENTS.md` 里 `<!-- NOAI-MANIFEST:BEGIN -->`
   … `<!-- NOAI-MANIFEST:END -->` 之间的同一份清单。
3. :func:`check_manifest_consistency` —— 两处逐条比对，返回差异列表
   （空 = 一致）。这是 FC-27 判据①"两处落地、逐条一致"（符合 FC-03）的实现。
4. :func:`check_paths` —— 判定一批改动路径是否命中禁改区，给出
   `verdict` + `required_approvals`。
5. :func:`check_approvals` —— 在命中之后用 hash 台账
   （`.noai-approvals.json`）判定"被批准的版本"是不是"盘上这一版"。

## hash 钉住的批准台账（为什么没有 git 也能查）

本仓库 `D:\\Incubator\\agentflow` 不是 git 仓库，所以 `--git` 永远 `unknown`。
但"这次改了哪些文件"并不是唯一的可用判据 —— 内容 hash 就是版本：

- 台账里每条记录一个仓库相对路径 + 该文件当前内容的 sha256
  + 变更摘要（谁写的、改了什么）+ 已完成的人工逐行走查记录（`reviewers`）；
- 命中禁改区后，逐条比对"台账里的 sha256"与"磁盘上的 sha256"：
  不一致 ⇒ `stale`，含义是被批准的那一版与现在这一版不是同一版；
- 这比 `git diff` 更强：git 只知道"文件变了"，抓不到"批准之后又被悄悄改了"。
  台账记的是被批准的那一版的内容，所以批准后任何一次改动都会让它重新变成未批准。

两条不许越过的线：

- 登记 ≠ 批准。 `--baseline` 只写 hash / glob / category，
  `reviewers` 永远是空数组；只有人跑 `--approve` 才写走查记录。
- 台账不能批准自己。 若命中集里出现台账文件本身，永远判 `unapproved`
  （理由码 `ledger_self_approval`）—— 它堵的是"AI 把自己的改动写进台账并声称已批准"。

台账读不到 / 不是合法 JSON / 结构不合规 ⇒ `unknown`(2)，不是 `clean`：
三态纪律在台账上同样成立 —— "没查成"与"查过了没问题"是两件事。

## 三态纪律（本模块最重要的一条）

`check_paths` 有三个结论，不是一个布尔：

- ``clean``          —— 查过了，没有命中 ⇒ 批准数 0。
- ``requires_human`` —— 查过了，命中 ⇒ 批准数 2（FC-27 的 =2）。
- ``unknown``        —— 没查成（清单不在 / 清单解析失败 / `--git` 但不在 git 仓库）
                        ⇒ 批准数 0，但绝不能读成"没问题"。

`unknown` 与 `clean` 的合并是本领域被反复证明最危险的静默兜底：
"没检查"被读成"检查过了没问题"。所以 ``unknown`` 单独占一个退出码（2）。

## 退出码（`17-正式文稿体例（参考投影度量论）.md:675-676, 681`）

> "多数脚本不设退出码，只打印"；"'未报错'曾被误读为'无问题'"（假阴性）。

教训很直接：门必须返回退出码，否则 CI 里"没报错"就等于"通过"。

- ``clean``          ⇒ 0
- ``requires_human`` ⇒ 1
- ``unknown``        ⇒ 2
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

#: FC-27 判据③：把"认证/授权/支付/加密/迁移/CI 配置/对外 API 破坏性变更"七类
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

#: 类别的规范顺序（不是集合 —— 顺序本身携带信息：与 FC-27 判据③的列举同序，FC-05）。
CATEGORY_ORDER: tuple[str, ...] = tuple(CATEGORY_TITLES)

#: 命中禁改区后额外要求的 reviewer 批准数。FC-27 写死为 2，不是可配置项：
#: 可配置的准入门槛等于没有门槛（下一个人会把它改成 0）。
REQUIRED_APPROVALS_ON_HIT = 2

MANIFEST_NAME = ".noai-paths"
AGENTS_NAME = "AGENTS.md"
BLOCK_BEGIN = "<!-- NOAI-MANIFEST:BEGIN -->"
BLOCK_END = "<!-- NOAI-MANIFEST:END -->"

#: hash 台账的文件名（它自己也在 `.noai-paths` 的 auth-audit 类里）。
LEDGER_NAME = ".noai-approvals.json"

#: 台账结构版本。不认识的版本一律判 `unknown`：版本号是"用哪套结构解读"的声明，
#: 不认识它就不能假装按老结构读得懂（那正是"没查成"被读成"没问题"的入口）。
LEDGER_VERSION = 1

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
REASON_STRUCTURE = "ledger_structure"


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
    """一条禁改区条目。字段名 `glob` 是 FC-27 判据①的用语（"glob 列表"）。"""

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
    到底是清单不一致，还是解析器不一致（判据①立刻失效）。

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


# --------------------------------------------------------------------------- 一致性（判据①）


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


# --------------------------------------------------------------------------- 路径判定


def _path_candidates(path: str, root: Path | None) -> list[str]:
    """把一条改动路径化成若干"可拿来与 glob 比"的候选串。

    为什么需要多条候选：调用方给的可能是绝对路径（`D:/repo/src/a.py`），
    而清单里的 glob 是仓库相对的（`src/*.py`）。如果只比原样，
    绝对路径永远不命中 —— 那是一个静默的假阴性（"没命中"读成"没问题"）。

    另外，glob 可能不带前导目录（`*.toml`），所以要给出各级后缀。
    """
    raw = str(path).replace("\\", "/").strip()
    out: list[str] = []
    if raw:
        out.append(raw)

    if root is not None:
        try:
            abs_p = Path(path).resolve()
            try:
                out.append(abs_p.relative_to(root.resolve()).as_posix())
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
        # `**` 与 fnmatch 的 `*` 在跨目录语义上不同：显式支持 `a/**/b` 与 `a/**`。
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
            rules = load_manifest(manifest)
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
    return GateResult(
        verdict="requires_human",
        violations=violations,
        required_approvals=REQUIRED_APPROVALS_ON_HIT,
        explanation=(
            f"requires_human：{len(hit_paths)} 条改动落在 **FC-27 禁 AI 区**"
            f"（类别：{'、'.join(cats)}）⇒ 必须由人编写或人逐行走查，"
            f"并需要 {REQUIRED_APPROVALS_ON_HIT} 名 reviewer 批准。"
            f"命中：{', '.join(hit_paths)}"
        ),
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
    """改动路径 ⇒ 磁盘上的真实文件。相对路径按仓库根解析（不是按当前工作目录）。"""
    p = Path(changed)
    return p if p.is_absolute() else (repo / p)


def _repo_rel_key(changed: str | Path, repo: Path) -> str:
    """改动路径 ⇒ 台账的键（仓库相对、正斜杠）。

    绝对路径先相对化；相对化不成（在仓库之外）就退回归一化的原样 ——
    这不是静默兜底：键仍然唯一且可比较，`check_paths` 的命中判定另有一套候选串逻辑。
    """
    try:
        rel = _target_path(changed, repo).resolve().relative_to(repo.resolve())
        return _norm_rel(rel.as_posix())
    except (OSError, ValueError):
        return _norm_rel(changed)


@dataclass(frozen=True)
class Reviewer:
    """一次已完成的人工逐行走查。`scope` 必须具体到符号或行区间。

    「写"看过了"等于没看」—— 与清单理由"只在一边写理由，等价于另一边没有理由"同一个道理。
    """

    name: str
    at: str
    scope: str
    note: str = ""
    verdict: str = "逐行走查通过"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "at": self.at,
            "scope": self.scope,
            "note": self.note,
            "verdict": self.verdict,
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
    changed_this_session: bool | None = None
    also_hits: tuple[dict, ...] = ()

    @property
    def distinct_reviewers(self) -> tuple[str, ...]:
        """不同姓名的 reviewer。

        批准数按不同姓名计，不按记录条数计：同一个人签两次不是"2 名 reviewer"，
        而 FC-27 要求 2 名正是为了拿到互相独立的复核
        （1 名 reviewer 与"作者自己再看一遍"在结构上无法区分）。
        重复的签名记录照实保留（它是事实），只是不增加批准数。
        """
        out: list[str] = []
        for r in self.reviewers:
            if r.name not in out:
                out.append(r.name)
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
    )


def _parse_entry(item: object, *, index: int, source: str) -> LedgerEntry:
    """解析并校验一条台账条目。结构不合规一律抛 `LedgerError`（⇒ unknown）。

    判据只校验"判定所依赖的字段"：`path` / `sha256` / `reviewers`。
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
) -> dict:
    """一条命中路径的批准判定。这是批准判据的唯一实现（FC-03）。

    判定顺序是刻意的（前一条胜过后一条）：

    1. 台账自指 ⇒ `unapproved`（理由码 `ledger_self_approval`）——
       台账不能批准自己，哪怕它的 hash 一致、reviewers 也够。
    2. 台账里没有条目 ⇒ `unapproved` / `unregistered`（"从没登记"，与"登记过但版本漂了"分开）。
    3. 磁盘 hash 拿不到 ⇒ `unknown`（没查成；不猜）。
    4. hash 不一致 ⇒ `unapproved` / `stale`，两个 hash 都打出来（前 12 位）。
    5. 不同姓名的 reviewer 不足 2 ⇒ `unapproved` / `insufficient_reviewers`（附"已有 N/2"）。
    6. 否则 ⇒ `approved`。
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
    if got < need:
        dup = len(entry.reviewers) - got
        extra = f"（另有 {dup} 条同一姓名的重复签名记录，不增加批准数）" if dup else ""
        return _done(
            "unapproved",
            REASON_FEW_REVIEWERS,
            f"hash 一致，但已完成的人工走查只有 {got}/{need} 名不同 reviewer{extra}。"
            "批准是**人**的动作，AI 不许代填 `reviewers`。",
        )

    return _done(
        "approved",
        REASON_APPROVED,
        f"hash 一致（{entry.sha256[:12]}）且已有 {got} 名不同 reviewer 完成逐行走查。",
    )


def check_approvals(
    changed: Sequence[str],
    *,
    manifest: str | Path | Sequence[Rule] | None = None,
    ledger_path: str | Path | None = None,
    root: str | Path | None = None,
) -> GateResult:
    """命中禁改区之后，用 hash 台账判定"批准的是不是盘上这一版"。

    判定逻辑（与 :func:`check_paths` 并列，不是它的替代）：

    - 先按 `check_paths` 取命中集。没有命中 ⇒ 原样返回 `clean`：
      台账读不读都不影响这个结论（台账只在需要它的时候才是必需的）。
    - 有命中 ⇒ 必须读台账。台账不存在 / 非法 JSON / 结构不合规 ⇒ `unknown`(2)。
    - 逐条判：自指 ⇒ unapproved；无条目 ⇒ unapproved(`unregistered`)；
      hash 不一致 ⇒ unapproved(`stale`)；reviewer 不足 2 名 ⇒ unapproved；
      全部一致且各 ≥2 名 ⇒ `approved`。
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

    return GateResult(
        verdict="clean",
        violations=[],
        required_approvals=0,
        explanation=(
            f"clean：{len(approvals)} 条命中路径**全部**已在台账里获批准"
            f"（hash 与磁盘一致，且各 ≥{REQUIRED_APPROVALS_ON_HIT} 名不同 reviewer 完成逐行走查）。"
            f"⚠️ 这个 clean 是**靠台账判定的，不是靠 git** —— 本仓库不是 git 仓库，"
            f"`--git` 只会返回 unknown；结论来源是 {resolved_ledger} 里的 sha256 与 reviewers。"
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
    """登记基线与刷新：写 `sha256` / `glob` / `category` / 摘要。绝不写 `reviewers`。

    「登记」与「批准」是两个动作，不许合并（合并等于让 AI 自己给自己发批准）。
    本函数是登记路径的唯一实现：CLI 的 `--baseline` 与脚本化的基线建立都走它。

    刷新时的两条规则：

    - 内容 hash 变了 ⇒ `reviewers` 清空。旧签名批准的是旧那一版，
      把它留在新 hash 上，正是本台账要堵的"批准之后又被悄悄改了"。
    - 内容 hash 没变 ⇒ 保留已有 `reviewers`。台账钉住的对象是内容版本，
      不是"某一次登记动作"：hash 没变 ⇒ 被批准的那一版就是盘上这一版，
      签名依然指向同一个对象。若任何一次 `--baseline` 都清空签名，会产生一个
      反向激励 —— 人越勤快地重跑基线，人工记录越容易被摧毁，
      而"勤快"恰恰是希望鼓励的行为。判据要让人更愿意跑它，而不是更不敢跑它。

    返回 `(新台账, 逐路径结果)`。结果里 `status` ∈
    `created` / `unchanged` / `refreshed` / `not_in_manifest` / `hash_unavailable`。

    `authored` / `authored_basis` 的取舍：显式给了就写（哪怕 hash 未变）——
    对同一版内容给出更强的归属声明是改进，不是换对象。没给的话：
    hash 未变 ⇒ 保留原值；hash 变了的新条目 ⇒ 用 `default_*`。
    """
    if default_authored not in AUTHORED_VALUES:
        raise LedgerError(f"default_authored 只能是 {list(AUTHORED_VALUES)}：{default_authored!r}")
    if default_authored_basis not in AUTHORED_BASIS_VALUES:
        raise LedgerError(
            f"default_authored_basis 只能是 {list(AUTHORED_BASIS_VALUES)}：{default_authored_basis!r}"
        )

    if isinstance(manifest, (str, Path)) or manifest is None:
        rules = load_manifest(manifest)
    else:
        rules = list(manifest)
    if not rules:
        raise NoaiError("空清单：登记基线时无法判断哪些路径属于禁改区 ⇒ 没查成")

    repo = Path(root) if root is not None else project_root()
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
            note = notes.get(key) or old.change_note
            auth = authored_map.get(key, old.authored)
            basis = basis_map.get(key, old.authored_basis)
            cts = cts_map.get(key, old.changed_this_session)
            status = "unchanged"
            detail = f"hash 未变（{current[:12]}）⇒ 保留已有 {len(reviewers)} 条走查记录"
        else:
            reviewers = ()
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
                    f"；内容已变，旧签名（{len(old.reviewers)} 条）**清空**"
                    "—— 它批准的是旧那一版"
                    if old is not None and old.reviewers
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

    same_name = [r for r in entry.reviewers if r.name == str(reviewer).strip()]
    record = Reviewer(
        name=str(reviewer).strip(),
        at=_now_iso(now),
        scope=str(scope).strip(),
        note=str(note).strip(),
        verdict=str(verdict).strip() or "逐行走查通过",
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
    }
    return Ledger(
        ledger_version=LEDGER_VERSION, generated_at=_now_iso(now), entries=entries
    ), info


# --------------------------------------------------------------------------- git


def git_changed_paths(root: str | Path | None = None) -> tuple[list[str] | None, str]:
    """`git diff --name-only HEAD`。返回 `(paths, reason)`。

    `paths is None` ⇒ 取不到（不在 git 仓库 / 没有 git / 命令失败）。
    调用方必须据此判 ``unknown``：本项目 `D:\\Incubator\\agentflow` 与
    `test/test1` 都不是 git 仓库，所以 `--git` 在这个环境里
    注定取不到改动集 —— 它必须如实报 unknown，而不是假装干净。
    """
    repo = Path(root) if root is not None else project_root()
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        return None, "环境里没有 `git` 可执行文件"
    except subprocess.TimeoutExpired:
        # 必须在 OSError 之前：TimeoutExpired 继承自 SubprocessError。
        return None, "`git diff` 超时（30s）"
    except OSError as exc:
        return None, f"调用 git 失败：{type(exc).__name__}: {exc}"

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        first = detail[0] if detail else "（无输出）"
        return None, f"`git diff --name-only HEAD` 退出码 {proc.returncode}：{first}"

    paths = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    return paths, f"git 报告 {len(paths)} 条改动路径"


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
    p.add_argument("--git", action="store_true", help="用 `git diff --name-only HEAD` 取改动路径")
    p.add_argument("--json", action="store_true", help="以 JSON 输出 GateResult")
    p.add_argument("-q", "--quiet", action="store_true", help="只返回退出码，不打印")
    p.add_argument("--manifest", default=None, help=f"清单路径（默认 <root>/{MANIFEST_NAME}）")
    p.add_argument(
        "--agents-md",
        default=None,
        help=f"{AGENTS_NAME} 路径（仅用于 --check-consistency；默认 <root>/{AGENTS_NAME}）",
    )
    p.add_argument("--root", default=None, help="仓库根（默认自动探测）")
    p.add_argument("--check-consistency", action="store_true", help=f"检查 {MANIFEST_NAME} 与 {AGENTS_NAME} 是否逐条一致")
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
            "  ⚠️ 这个名字已经签过这一条 —— 记录照实保留，但**批准数按不同姓名计**，"
            "所以它没有让 2 名 reviewer 的门槛前进（同一个人签两次不是两名 reviewer）",
        )
    if info["distinct_reviewers"] < info["required"]:
        _say(args, f"  ⇒ 还差 {info['required'] - info['distinct_reviewers']} 名不同 reviewer 才算批准")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口。返回退出码（不是 None）—— 门必须有退出码。"""
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    root = Path(args.root) if args.root else project_root()

    if args.check_consistency:
        diffs = check_manifest_consistency(
            manifest_path=args.manifest,
            agents_md=args.agents_md if args.agents_md else ((root / AGENTS_NAME) if args.manifest else None),
        )
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
        # 一致性检查是"前置门"：不一致 ⇒ 门本身失效 ⇒ 报 unknown（2）。
        return 0 if not diffs else 2

    # ---- 写动作（登记 / 签字）先于判定动作处理：它们的退出码语义是"做成了没有"。
    if args.baseline:
        return _run_baseline(args, root)
    if args.approve is not None:
        return _run_approve(args, root)

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
        paths, reason = git_changed_paths(root)
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

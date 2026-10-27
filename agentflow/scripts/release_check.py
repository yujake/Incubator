"""发布前的一键检查（`python scripts/release_check.py`）。

##  本文件落在禁 AI 区里

`.noai-paths` 的 `[category: release-deploy]` 登记了 `scripts/release_check.py`。
按 FC-27，改这个文件需要「人编写或人逐行走查 + 2 名 reviewer 批准」。

本文件当前的作者状态必须如实登记：

    authored_by: AI agent（本框架的构建者），尚未经人逐行走查
    required_approvals: 2（尚未取得）

也就是说：这个门现在是"未批准"状态，它跑出来的绿灯不构成发布许可。
把这句话写进 docstring 而不是写进某个聊天记录里，是因为它是这个文件最重要的属性 ——
一个"看起来在把关、其实自己还没被审过"的发布脚本，正是 FC-27 说的那种
"测试全绿、上线即越权"的形态。

## 它做什么

按固定顺序跑八项，每项给三档结论（`pass` / `fail` / `unknown`），
最后给一个总判定与退出码：

    0 = 全部 pass
    1 = 有 fail
    2 = 有 unknown（没跑成 ≠ 通过）、有项被 `--skip` 关掉，或检查器自身出错

`unknown` 与 `fail` 分开，且都不等于 `pass`。 这是三态纪律在发布门上的落地：
"pytest 因为收集错误没跑起来"既不是"测试通过"，也不是"测试失败"，
把它算成任何一档都会掩盖真相。

`--skip` 关掉的项也记 `unknown`（`I-3`），不是"不参与判定"。
理由：`--skip` 是调试开关，而"调试时跳过七项"与"八项都通过"在旧输出里长得一模一样
（旧版逐字打印 `发布检查总判定：PASS    pass=1 fail=0 unknown=0` 且全文不出现"跳过"）。
被跳过的项以名字进 `skipped` 列表与 `--json-out` 产出的报告，总判定按 `unknown` 记 ⇒ 退出码 2。
这与编排层 `tools/release_all.py` 的口径逐字一致（那条有测试钉死）。

## 八项

| # | 项 | 判据 | 为什么它在发布门里 |
|---|---|---|---|
| 1 | 全量测试 | `pytest -q` 退出码 0，且 0 failed | 最基础的一层；但它单独不构成发布许可（见下） |
| 2 | 模块自检 | 自检块（`__main__`）存在且 `python -m agentflow.<x>` 退出码 0；没有自检块 ⇒ `unknown`（不是 fail、更不是 pass） | 自检覆盖的是"端到端能不能跑通"，而单测覆盖的是"判据对不对" —— 两者不重叠 |
| 3 | 工具普查 | 工具数与角色工具数可复现；只读角色（C/H）的写工具泄漏 = 0 | 权限面是设计的一部分，且它默认是隐式的 —— 只有普查才让它成为事实 |
| 4 | 全库校验 | `verify_all` 的 error = 0 | 跨表不变量（悬空引用、依赖闭合、三态一致性）只有它查 |
| 5 | linter | `scripts/lint_rules.py` 的 error = 0 | 形态类规则（第二份名单、静默失败、脚本无退出码） |
| 6 | 禁 AI 区门 | `scripts/noai_gate.py --check-consistency` 一致，且本次改动集判定明确 | FC-27；`unknown` 必须显式暴露 |
| 7 | 契约版本 | `agentflow.CONTRACT_VERSION` 与 `interactions.CONTRACT_VERSION` 一致，且 `schema.SCHEMA_VERSION` 与 `__schema_version__` 一致 | "两份契约各按各的理解跑"是没有任何报错的分裂 |
| 8 | 源码树可导入 | 每个模块都能被单独 import（循环依赖会在这里炸） | `python -m agentflow.X` 是接口的一部分 |

## 为什么"测试全绿"进不了这一项

第 1 项全绿不能推出可以发布，理由是本项目自己的一手教训：
9 条已交付缺陷里 0 条能被 happy-path 抓到（`10-…md` §10.10 结论①）。
所以发布门不只看"测试过没过"，还看门本身有没有被校准过（第 3/4/5/6 项）
与契约版本有没有对齐（第 7 项）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

# ------------------------------------------------------------------ 常量

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"

#: 门的产物落点（`X-1`）：`REPO_ROOT.parent / "temp"`。
#:
#: 为什么不是仓库根：第 5 项（linter）会把 linter 的结果写成 JSON。此前它写的是
#: `<repo>/.release-lint.json` —— 那是被 git 跟踪的文件，于是"跑一次发布门"
#: 这件只读的事会把工作区改脏，而脏工作区又会反过来污染别的门的判据
#: （例如"本次改动的文件集"）。实测：`python scripts/release_check.py --skip ...`
#: 跑完 `.release-lint.json` 的 sha256 从 `B625A5B9…` 变成 `E25FCCA4…`。
#:
#: 口径（不是"不产生产物"—— 产物本身是证据）：产物搬到被 `.gitignore`
#: 排除的 `temp/` 里。`.gitignore` 的 `/temp/` 前导斜杠锚定在上一级
#: 仓库根，而本文件的 `REPO_ROOT` 是 `agentflow/`，所以落点是 `REPO_ROOT.parent / "temp"`。
#: 这与编排层 `tools/release_all.py` 取验收目录用的 `root.parent / "test" / "test2"`
#: 是同一个伞形仓库约定。
GATE_ARTIFACT_DIR = REPO_ROOT.parent / "temp"

#: 三档结论。`unknown` 必须与 `fail` 分开 —— 见模块 docstring。
VERDICTS = ("pass", "fail", "unknown")

#: 需要跑自检的模块（`python -m agentflow.<x>`，在 `src/` 下跑）。
SELFTEST_MODULES = (
    "agent_a", "agent_b", "agent_c", "agent_d",
    "agent_e", "agent_f", "agent_g", "agent_h", "pipeline",
)

#: 每个角色期望的工具数下界。写成下界而不是等值：
#: 新增工具是正常的演进，而静默少工具才是要抓的（所以下界 + 泄漏必须为 0）。
#:  这些数字是观测值（`cli tools`/普查脚本），不是设计目标 ——
#: 把它们写在这里的价值是"变化时必须有人看一眼"，而不是"必须恰好这么多"。
ROLE_TOOL_FLOOR: dict[str, int] = {"A": 18, "B": 16, "C": 15, "D": 30, "E": 18, "F": 28, "G": 28, "H": 20}

READ_ONLY_ROLES = ("C", "H")

#: `item_selftests` 的四条判据（`D9`）。这是那一项判据的唯一出处：
#: 模块 docstring 的八项表第 2 行必须与它逐条对应，`tests/test_release_check_items.py`
#: 把两处铆在一起（改写判据而不同步这两处 ⇒ 测试必红）。
#:
#: 为什么要写成数据而不是只写在 docstring 里（`D9` 的实测）：表格第 2 行原写
#: "8 个 agent + pipeline 自检全部退出码 0"，而 `item_selftests` 实际多一道
#: `has_selftest` 门（没有 `__main__` 块 ⇒ `unknown`）。按 docstring 读会以为
#: 没有自检块的那两个模块"应该 pass 或 fail"。实现更严且更符合三态纪律，
#: 是文档该改 —— 但只把文档改对，下一次漂移没人看得见，所以这里留一份可断言的原文。
SELFTEST_CRITERIA: tuple[tuple[str, str], ...] = (
    ("no_selftest_block",
     "自检块（`__main__`）存在且 `python -m agentflow.<x>` 退出码 0；"
     "没有自检块 ⇒ `unknown`（不是 fail、更不是 pass）"),
    ("start_failed_or_timeout", "起不来或超时 ⇒ `unknown`（没有证据说它错）"),
    ("non_zero_exit", "自检块存在而退出码非 0 ⇒ `fail`"),
    ("all_ok", "自检块存在且退出码 0 ⇒ `pass`"),
)


def _selftest_verdict(has_selftest: bool, started: bool, timed_out: bool, exit_code: int | None) -> str:
    """单个模块自检的三态判定（`D9`：把"没有自检块"这一支变成可单测的函数）。

    分支顺序就是判据本身，与 `SELFTEST_CRITERIA` 逐条对应 ——
    `tests/test_release_check_items.py` 对四条分支各给一个输入，
    删掉任何一支都会让那条测试红（负控见该文件）。
    """
    if not has_selftest:
        return "unknown"
    if not started or timed_out:
        return "unknown"
    if exit_code != 0:
        return "fail"
    return "pass"

#: `noai_gate.evaluate_approval` 的理由码 → 一句人话（`P-3`：写清缺的是哪一条）。
#: 键取自 `noai_gate` 的 `REASON_*` 常量（那份判据只有一处实现，这里只做翻译，
#: 不复制判据）；键缺失时按原样打印理由码，宁可露出一个陌生的码也不编一句解释。
_APPROVAL_REASON_TEXT: dict[str, str] = {
    "unregistered": "台账里**没有**这个路径的条目（从没登记，不是登记过之后漂了）",
    "stale": "台账里的 `sha256` 与**盘上这一版不一致**（被批准的不是这一版 ⇒ 登记 ≠ 批准）",
    "insufficient_reviewers": "人工逐行走查**不足 2 名不同 reviewer**（签字不足）",
    "ledger_self_approval": "台账不能批准自己（本文件就是台账本体）",
    "hash_unavailable": "拿不到盘上内容的 `sha256` ⇒ 这一条**没查成**",
    #: `approved` 在 `exit_code == 0` 那一支被显式读走（`by_human` / `by_audit`）。
    #: 它出现在这张表里的理由：`REAUDIT2-R1-2` 指出这张表少了它 ——
    #: 一旦有别的读法（例如把 approvals 全量打印出来）碰到这个码，
    #: 缺键就会把 `approved` 原样打成裸码，读的人分不清"没批准"与"批准了"。
    "approved": "已获批准（**通路按 `distinct_reviewers` 分流**：≥2 名不同 reviewer = 人审；"
                "否则是多维独立审计 —— 机审通路**没有任何人类 reviewer 签字**）",
    "insufficient_clean_audits": (
        "审计通路**报了问题**、或审计本身不够（不同审计者 / 维度 / 负控 / sha256 对不上）"
        "⇒ 这一条**未批准**：先把它报的那些问题处理掉，再对同一版重新审计并登记"
    ),
    "audit_receipt_chain_unverifiable": (
        "审计记录与证据锚都合规，但**回执链核对不上**（链缺失 / 断链 / 没有这一版的记录）"
        "⇒ 这一条**没查成**：先把『链为什么少了一段』弄明白，不许由写入方在不明白原因的情况下续写"
    ),
    "audit_evidence_unverifiable": (
        "机审的记录合规，但**证据锚核对不上**（证据文件读不到、或内容与登记的 `sha256` 不一致）"
        "⇒ 这一条**没查成**：先确认证据还在不在，别把它读成『审计没过』"
    ),
    #: 以下两条是门口新加的两道机审判据（另一个批次落在 `scripts/noai_gate.py` 的
    #: `REASON_*` 里）。翻译必须跟上：`REAUDIT2-R1-2` 之后有一条交叉断言
    #: （`tests/test_release_check_noai.py::test_every_reason_code_the_gate_can_return_has_a_translation`）
    #: 要求"门能发出的每一个码都在这里有解释"——缺键会把裸码打给读报告的人。
    "insufficient_independent_dimensions": (
        "机审通路「维度不足」（不同审计维度少于门槛，或维度取自同一份表面）"
        "⇒ 这一条未批准：多维独立审计的意义就在'互相看不见的证据'，"
        "同一维度的第二遍不构成复核"
    ),
    "audit_timestamp_unverifiable": (
        "机审记录里的「时间戳核对不上」（缺失 / 不可解析 / 与证据锚上的时间不一致）"
        "⇒ 这一条没查成：先弄清时间对不上的原因，别把它读成『审计没过』"
    ),
    #: `F1-FOUND-1`（第 6 轮 F1 批实测补上的一处）：F1 为 `R6-R1d-3` 在
    #: `scripts/noai_gate.py` 新加了 `REASON_AUDIT_TIMESTAMPS_ORDER`，但没同步这张表
    #: ——`tests/test_release_check_noai.py::test_every_reason_code_the_gate_can_return_has_a_translation`
    #: 当场报了 `missing == ['audit_timestamps_not_monotonic']`。交叉断言就是在等这一处，
    #: 所以补的是翻译，不是判据。
    "audit_timestamps_not_monotonic": (
        "机审记录里的「审计时间戳次序倒挂」（后写的那一条不早于先写的）"
        "⇒ 这一条未批准：那串时间是审计者自报的，门只判『可解析、不在未来、按台账次序"
        "非递减』，不判内容真伪 —— 倒挂说明它不能当作『各自独立发生在本轮窗口内』的次序证据"
    ),
    #: `FINAL-R1d-04` 那一批（2026-09-28 修复窗口）给 `scripts/noai_gate.py` 新加了
    #: `REASON_REVIEW_ANCHOR`，但没同步这张表 ⇒ 与本文件上面 `F1-FOUND-1` 同族的缺口，
    #: 同一条交叉断言（`tests/test_release_check_noai.py`，全量里绿、单独跑不过）
    #: 当场报 `missing == ['reviewer_evidence_anchor_unverifiable']`。
    #: 所以补的是翻译，不是判据。
    "reviewer_evidence_anchor_unverifiable": (
        "人审记录**带了**证据锚，但锚核对不上（指向的文件不在盘上 / 内容与登记的 `sha256` "
        "不一致 / `evidence_path` 与 `evidence_sha256` 不成对）"
        "⇒ 这一条**没查成**：先弄清走查记录还在不在、动过没有，**别**把它读成『人审没过』"
        "（没有锚是另一档：锚本来可选，那一档由门输出的固定保留说明强度）"
    ),
}


@dataclass
class Item:
    key: str
    title: str
    verdict: str = "unknown"
    detail: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"key": self.key, "title": self.title, "verdict": self.verdict,
                "detail": self.detail, "notes": self.notes}


@dataclass
class Report:
    items: list[Item] = field(default_factory=list)
    #: 被 `--skip` 关掉的项（`I-3`）。必须单独记，理由见 `counts()` / `overall()`。
    skipped: list[str] = field(default_factory=list)

    def add(self, item: Item) -> Item:
        self.items.append(item)
        return item

    def counts(self) -> dict[str, int]:
        """三档计数 + `skipped`（第四个数，不属于 `VERDICTS`）。

        为什么 `skipped` 不并进 `unknown`：它是"这一次没让它跑"，不是"它跑了没跑成"。
        两者在处置上不同（前者要人重新跑一次门，后者要人修东西），所以分开报；
        但两者在总判定上的后果相同 —— 都不能当通过（见 `overall()`）。
        """
        c = {v: sum(1 for i in self.items if i.verdict == v) for v in VERDICTS}
        c["skipped"] = len(self.skipped)
        return c

    def overall(self) -> str:
        """总判定。

         `I-3`（复现过）：旧实现只在这三项上算 —— `fail` ⇒ fail、`unknown` ⇒ unknown、
        其余 ⇒ `pass`。而被 `--skip` 关掉的项根本不进 `items`，于是
        `--skip tests selftests tools verify lint contract imports`（八项关掉七项）
        得到 `pass=1 fail=0 unknown=0` ⇒ `overall="pass"`、退出码 0，
        而且报告里「跳过」两个字都不出现。

        实测（改前）逐字：`发布检查总判定：PASS    pass=1 fail=0 unknown=0`，
        紧接着那句「 overall=pass 只说明这八项都通过了」在本次运行里是假的
        —— 七项没跑。这正是本项目最忌的形态：把"没查"折叠进"通过"。

        现在的口径：有任何一项被跳过 ⇒ 总判定是 `unknown`（退出码 2），
        与编排层 `tools/release_all.py` 把"跳过的步骤记 unknown"逐字一致
        （那条口径有测试钉死：`tests/test_release_all.py` 里 `by_key["per-file"] == "unknown"`）。
        这与"跳过的项记成 pass"的差别就是"发布门能不能被 `--skip` 绕过"。

         `H-5` / `H-2`（本轮修）：空 `items` 也给 `unknown`，不再给 `pass`。
        旧实现在空表上走"三项都是 0 ⇒ 其余 ⇒ pass"，于是 `Report().overall()` 返回
        `"pass"`，而姊妹实现 `tools/release_all.py::verdict_from_subitems([])` 返回 `None`
        （那句 docstring 逐字写着"空列表 ⇒ `None`，调用方应退回用退出码判定，
        而不是凭空得出 `pass`"）。两份实现只在非空时相同 ⇒ "编排层独立重算一遍"
        这条防线在空集这一档整个失效。空集的含义是这一份报告没有可判的项
        （`main()` 只有八个 runner 全被跳过时才会走到这里，而那时 `skipped` 非空、
        本来就是 `unknown`）—— "没有可判的项"绝不是"全过"。
        """
        c = self.counts()
        if c["fail"]:
            return "fail"
        if c["unknown"] or c["skipped"]:
            return "unknown"
        if not self.items:
            # 没有可判的项 ⇒ 没查成（不是 pass）。理由见上面 `H-5` 那一段。
            return "unknown"
        return "pass"

    def to_dict(self) -> dict:
        d = {
            "overall": self.overall(),
            "counts": self.counts(),
            "items": [i.to_dict() for i in self.items],
            "authored_by": "AI agent（尚未经人逐行走查；本文件在禁 AI 区内）",
        }
        # 被跳过的项要以名字进报告：只报一个计数，读的人不知道少的是哪一项
        # （`I-3` 的另一半：`--json-out` 产物里此前连跳过这件事都没有）。
        if self.skipped:
            d["skipped"] = list(self.skipped)
        d["note"] = self._note()
        return d

    def _note(self) -> str:
        #  `REAUDIT2-R1-3`：这句话必须随本次运行的事实变。
        # 旧版只按 `skipped` 分流，于是"没有跳过但有一项 fail"时，
        # 报告与 JSON 仍然逐字写着"overall=pass 只表示这八项检查都通过了" ——
        # 本次运行里 overall 根本不是 pass，那句话是假的。
        c = self.counts()
        tail = (
            "本脚本自身位于禁 AI 区（`.noai-paths` 的 release-deploy 类），"
            "按 FC-27 仍需人逐行走查 + 2 名 reviewer 批准。"
        )
        if self.skipped:
            return (
                f"overall 不可能是 pass：本次有 {len(self.skipped)} 项被 `--skip` 关掉"
                f"（{', '.join(self.skipped)}）⇒ 按三态纪律记 unknown，"
                f"本次实际记到的项：pass={c['pass']} fail={c['fail']} unknown={c['unknown']}。"
                "「没让某几项跑」与「某几项跑了都通过」是两件事，不能折叠。" + tail
            )
        if c["fail"]:
            return (
                f"overall=fail：本次有 {c['fail']} 项**没通过**"
                f"（pass={c['pass']} unknown={c['unknown']}）⇒ 不构成发布许可。"
                "这一句不写『这八项检查都通过了』：本次就没有。" + tail
            )
        if c["unknown"]:
            return (
                f"overall=unknown：本次有 {c['unknown']} 项**没查成**"
                f"（pass={c['pass']} fail={c['fail']}）⇒ 不构成发布许可。"
                "没查成绝不是通过。" + tail
            )
        if not self.items:
            # `H-5`：空表不是 pass。这一支必须与 `overall()` 的空表分支同口径，
            # 否则报告正文会比总判定更乐观（那种不一致本身就是缺陷）。
            return (
                "overall=unknown：本次**一项都没有判到**（items 为空、也没有 skipped 记录）"
                "⇒ 没有可判的项不等于全过。" + tail
            )
        return (
            f"overall=pass 只表示**本次跑到的那 {c['pass']} 项**都通过了"
            f"（fail=0 unknown=0 skipped=0），不构成发布许可：" + tail
        )


def _ensure_utf8_console() -> None:
    """把本进程的 stdout/stderr 显式钉在 UTF-8 上（输出不依赖调用方的 locale）。

    为什么发布门必须自己管这件事：本脚本会打印中文与 `` 这类符号，而
    cp936(GBK) 控制台下 Python 的默认编码会让 `print` 直接抛 `UnicodeEncodeError`
    —— 那不是"发现了问题"的退出码 1，而是发布门自己没跑成，而"没跑成"
    与"通过"在调用方眼里极易混淆（三态纪律）。口径与编排层 `tools/release_all.py`
    上一轮采用的写法相同：`reconfigure(encoding="utf-8", errors="replace")`。
    """
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # 被重定向或被测试替换过的流可能没有 reconfigure（或已关闭）。
            # 此时不能因此崩掉发布门：这一句是加固，不是判据本身。
            pass


def _run(cmd: Sequence[str], *, cwd: Path, timeout: float = 1800.0, env_extra: dict | None = None) -> dict:
    """跑一个子进程，三态返回。

     超时 / 起不来 / 非零退出码是三件不同的事，这里必须分开报：
    - `started=False` ⇒ 它根本没跑成（`unknown`）
    - `timed_out=True` ⇒ 它跑到一半被砍（`unknown`，且不是 fail —— 我们没有证据说它错）
    - 否则按 `exit_code` 判

     解码也必须显式 `encoding="utf-8"`：子进程的输出里有中文，默认走
    locale 编码时 `text=True` 会在读回那一侧抛 `UnicodeDecodeError`，
    于是一个正常结束的子进程被判成"没跑成"—— 判据没变，错的是读它的方式。

     同理，子进程的输出编码必须被显式覆盖，不能用 `setdefault`。
    实测（cp936 控制台）：父进程被调用方设成 `PYTHONIOENCODING=cp936` 时，
    `setdefault` 会把这一个值原样传给子进程 —— 于是 `lint_rules.py` 在打印
    含 `⇒` 的行时自己抛 `UnicodeEncodeError` 并以退出码 1 结束。而本脚本第 5 项
    把退出码 1 读成"linter 发现问题"，于是一次投递问题被报成"代码有问题"，
    方向完全反了。覆盖成 utf-8 之后，子进程打印什么都不会因此崩。
    """
    env = dict(os.environ)
    # 覆盖而不是补默认值：理由见上面那一段（这与 `tools/release_all.py` 里
    # `{os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", extra}` 同一写法）。
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if env_extra:
        env.update(env_extra)
    try:
        p = subprocess.run(list(cmd), cwd=str(cwd), capture_output=True, text=True,
                           timeout=timeout, env=env, errors="replace", encoding="utf-8")
    except subprocess.TimeoutExpired as e:
        return {"started": True, "timed_out": True, "exit_code": None,
                "stdout": (e.stdout or ""), "stderr": (e.stderr or ""),
                "cmd": " ".join(cmd)}
    except OSError as e:
        return {"started": False, "timed_out": False, "exit_code": None,
                "stdout": "", "stderr": f"{type(e).__name__}: {e}", "cmd": " ".join(cmd)}
    return {"started": True, "timed_out": False, "exit_code": p.returncode,
            "stdout": p.stdout, "stderr": p.stderr, "cmd": " ".join(cmd)}


def _tail(text: str, n: int = 12) -> list[str]:
    lines = [x for x in (text or "").splitlines() if x.strip()]
    return lines[-n:]


# ------------------------------------------------------------------ 八项检查


def item_test_suite(rep: Report) -> Item:
    it = rep.add(Item("tests", "全量测试（pytest -q）"))
    r = _run([sys.executable, "-m", "pytest", "-q"], cwd=REPO_ROOT)
    if not r["started"]:
        it.verdict = "unknown"
        it.notes.append(f"**根本没跑起来**：{r['stderr'][:200]}")
        return it
    if r["timed_out"]:
        it.verdict = "unknown"
        it.notes.append("超时被砍 —— **没有证据说它错**，所以是 unknown 而不是 fail")
        return it
    out = r["stdout"] + r["stderr"]
    it.detail = {"exit_code": r["exit_code"], "tail": _tail(out)}
    # 解析 "N passed, M failed, K deselected" 这类摘要。
    import re

    passed = re.search(r"(\d+) passed", out)
    failed = re.search(r"(\d+) failed", out)
    errors = re.search(r"(\d+) error", out)
    it.detail["passed"] = int(passed.group(1)) if passed else None
    it.detail["failed"] = int(failed.group(1)) if failed else 0
    it.detail["errors"] = int(errors.group(1)) if errors else 0
    if it.detail["passed"] is None:
        it.verdict = "unknown"
        it.notes.append("**解析不出 passed 计数** ⇒ 可能没跑到收集完成（收集错误）⇒ unknown，不是 pass")
        return it
    if r["exit_code"] != 0 or it.detail["failed"] or it.detail["errors"]:
        it.verdict = "fail"
        # `REAUDIT2-R1-4`：这一句旧版是无条件的"这一项全绿不构成发布许可"，
        # 于是 fail 档也在说"全绿" —— 与本文件自己的三态纪律相矛盾。
        it.notes.append(
            f"本次**不是**全绿：passed={it.detail['passed']} failed={it.detail['failed']} "
            f"errors={it.detail['errors']} exit={r['exit_code']} ⇒ 这一项 fail，"
            "不构成发布许可（9 条已交付缺陷里 0 条能被 happy-path 抓到）"
        )
    else:
        it.verdict = "pass"
        it.notes.append("⚠️ 这一项全绿**不构成**发布许可：9 条已交付缺陷里 0 条能被 happy-path 抓到")
    return it


def item_selftests(rep: Report) -> Item:
    """第 2 项：模块自检。四条判据见 `SELFTEST_CRITERIA`（唯一出处）—— 逐条点名如下：

    - `no_selftest_block`：模块里没有 `__main__` 块 ⇒ `unknown`（不是 pass）；
    - `start_failed_or_timeout`：进程起不来或超时 ⇒ `unknown`；
    - `non_zero_exit`：有自检块而退出码非 0 ⇒ `fail`；
    - `all_ok`：有自检块且退出码 0 ⇒ `pass`。

    `D9` 的实测：模块 docstring 的八项表第 2 行原写"8 个 agent + pipeline 自检全部
    退出码 0"，漏了 `no_selftest_block` 那一支，而实现多这道门（更严、更符合
    三态纪律）。表格那一行现在与上面四条逐条对应，`tests/test_release_check_items.py`
    把两处铆在一起（改判据而不同步文档 ⇒ 测试必红）。
    """
    it = rep.add(Item("selftests", "模块自检（8 个 agent + pipeline）"))
    results: dict[str, dict] = {}
    for mod in SELFTEST_MODULES:
        src = SRC / "agentflow" / f"{mod}.py"
        text = src.read_text(encoding="utf-8") if src.exists() else ""
        if not src.exists():
            # `goal-7f5116c1` M6/M7：八个角色模块改成了包，`__main__` 自检块搬到
            # `<角色>/__main__.py`（`python -m agentflow.<角色>` 在包形态下执行的正是它）。
            # 不认这个落点的话，"有自检块"会被读成"没有" ⇒ 判据从 pass 掉成 unknown。
            pkg_main = SRC / "agentflow" / mod / "__main__.py"
            text = pkg_main.read_text(encoding="utf-8") if pkg_main.exists() else ""
        #  "没有自检块"不是"自检通过"（三态纪律）。
        # 这条判据写下来的当时（`D5`）：`agent_a` / `agent_b` 没有 `__main__` 块，
        # 于是 `python -m agentflow.agent_a` 退出码 0 且输出 0 行 —— 旧判据会把它记成 PASS，
        # 而它其实什么都没检查。这正是本项目最忌讳的"把没做读成通过"。
        # 现在：没有自检块 ⇒ `unknown`，并把这件事报出来（它是待补的缺口，不是通过）。
        #
        # `REAUDIT2-R1-6`（第二轮复审实测）：上面那句曾经是现在时，而
        # `DEVELOPMENT.md:1237` 已把 D5 记为"已关闭（S2）"，实测两个模块现在都有真守卫
        # （`agent_a` L830 / `agent_b` L1721）。注释引用一个已经关闭的历史状态、却用现在时写，
        # 会让后来的人以为缺口还在。所以这里改成过去时并点名"已关闭"。
        has_selftest = "__main__" in text
        r = _run([sys.executable, "-m", f"agentflow.{mod}"], cwd=SRC, timeout=900.0)
        entry = {"started": r["started"], "timed_out": r["timed_out"],
                 "exit_code": r["exit_code"], "has_selftest": has_selftest,
                 "tail": _tail(r["stdout"] + r["stderr"], 3)}
        # 判据只此一处：`_selftest_verdict`（`D9`）。四条分支与 `SELFTEST_CRITERIA`
        # 逐条对应，模块 docstring 的八项表第 2 行照抄那一条 —— 三处一起漂不了。
        entry["verdict"] = _selftest_verdict(has_selftest, r["started"], r["timed_out"],
                                             r["exit_code"])
        if entry["verdict"] == "unknown" and not has_selftest:
            entry["why"] = "该模块没有自检块（`__main__`）⇒ **没自检**，不是'自检通过'"
        results[mod] = entry
    it.detail = results
    bad = [m for m, v in results.items() if v["verdict"] == "fail"]
    unknown = [m for m, v in results.items() if v["verdict"] == "unknown"]
    if bad:
        it.verdict = "fail"
        it.notes.append(f"这些自检**没通过**：{bad}")
    elif unknown:
        it.verdict = "unknown"
        it.notes.append(
            f"这些模块**没有自检块**（不是'通过'）：{unknown} ⇒ "
            "要么给它们补一个 `__main__` 自检，要么在 `SELFTEST_MODULES` 里说明为什么不需要"
        )
    else:
        it.verdict = "pass"
    return it


def item_tool_census(rep: Report) -> Item:
    it = rep.add(Item("tools", "工具普查（数量可复现 + 只读角色 0 泄漏）"))
    code = (
        "import json, tempfile, pathlib\n"
        "from agentflow.tools import build_registry, ROLES, READ_ONLY_ROLES, SIDE_EFFECTS_WRITE\n"
        "from agentflow.store import Store\n"
        "d = pathlib.Path(tempfile.mkdtemp()); s = Store(d); s.init()\n"
        "b = build_registry(store=s, workspace_root=d, strict=True)\n"
        "by_role = {r: len(b.registry.for_role(r)) for r in ROLES}\n"
        "leaks = {r: [x.name for x in b.registry.for_role(r) if x.side_effect in SIDE_EFFECTS_WRITE]\n"
        "         for r in READ_ONLY_ROLES}\n"
        "se = {}\n"
        "for x in b.registry._specs.values(): se[x.side_effect] = se.get(x.side_effect, 0) + 1\n"
        "print(json.dumps({'total': len(b.registry), 'by_role': by_role, 'leaks': leaks,\n"
        "                  'side_effects': se, 'skipped': b.skipped,\n"
        "                  'role_filter_notes': b.registry.role_filter_notes}, ensure_ascii=False))\n"
    )
    r = _run([sys.executable, "-c", code], cwd=SRC, timeout=300.0)
    if not r["started"] or r["timed_out"]:
        it.verdict = "unknown"
        it.notes.append("普查脚本没跑成")
        return it
    if r["exit_code"] != 0:
        # `REAUDIT2-R1-5`：普查脚本自己崩了 ⇒ 这一次普查没查成，不是"查了有问题"。
        # 旧版判 fail 且 `notes` 空（只把 stderr 塞进 detail），于是报告上出现
        # 一条没有理由的 fail；同一文件里 `item_linter` 对同类形态判的是 unknown
        # （"脚本没跑成 ⇒ 没查成"）。两处口径必须一致。
        it.verdict = "unknown"
        it.detail = {"exit_code": r["exit_code"], "stderr": _tail(r["stderr"], 6)}
        it.notes.append(
            f"普查脚本以退出码 {r['exit_code']} 结束 ⇒ 这一次**没查成**（unknown，不是 fail）："
            "退出码非 0 说明脚本自己崩了（例如导入失败 / 依赖缺失 / 注册表构造抛错），"
            "而不是『查到了问题』。原因见 detail.stderr。"
        )
        return it
    try:
        data = json.loads(r["stdout"].strip().splitlines()[-1])
    except (ValueError, IndexError) as e:
        it.verdict = "unknown"
        it.notes.append(f"普查输出解析失败：{e}")
        return it
    it.detail = data
    problems: list[str] = []
    if data["skipped"]:
        problems.append(f"有模块被跳过：{data['skipped']}")
    for role, leaks in data["leaks"].items():
        if leaks:
            problems.append(f"**只读角色 {role} 有写工具泄漏**：{leaks}")
    for role, floor in ROLE_TOOL_FLOOR.items():
        got = data["by_role"].get(role, 0)
        if got < floor:
            problems.append(f"角色 {role} 只有 {got} 个工具（下界 {floor}）⇒ 可能有工具静默没装上")
    if data["role_filter_notes"]:
        problems.append(f"有工具的 roles 声明把写工具给了只读角色（行为已被拦下，但声明要改）：{data['role_filter_notes']}")
    it.verdict = "pass" if not problems else "fail"
    it.notes.extend(problems)
    return it


def item_verify(rep: Report) -> Item:
    it = rep.add(Item("verify", "全库校验（verify_all error = 0）"))
    code = (
        "import json, tempfile, pathlib\n"
        "from agentflow.verify import verify_all\n"
        "from agentflow.store import Store\n"
        "d = pathlib.Path(tempfile.mkdtemp()); s = Store(d); s.init()\n"
        "r = verify_all(s).to_dict()\n"
        "print(json.dumps({'error_count': r['error_count'], 'warning_count': r['warning_count'],\n"
        "                  'errors': [i['code'] for i in r['errors']], 'checked': r['checked']},\n"
        "                 ensure_ascii=False))\n"
    )
    r = _run([sys.executable, "-c", code], cwd=SRC, timeout=300.0)
    if not r["started"] or r["timed_out"] or r["exit_code"] != 0:
        it.verdict = "unknown"
        it.notes.append(f"**校验器自身没跑成**（不是'库有问题'）：{_tail(r['stderr'], 4)}")
        return it
    data = json.loads(r["stdout"].strip().splitlines()[-1])
    it.detail = data
    it.verdict = "pass" if data["error_count"] == 0 else "fail"
    it.notes.append(
        "注意：这里查的是**空库**。空库 0 error 只说明'校验器能跑'，"
        "不说明真实库干净 —— 真实库的校验在验收测试里（`test/test2/run_acceptance.py` 的 P8）"
    )
    return it


def _parse_skip_values(raw: Sequence[str] | None, _depth: int = 0) -> set[str]:
    """把 `--skip` 的取值摊平成集合（`c-10`）。

    ## 为什么不是 `nargs="*"`

    旧定义是 `nargs="*"`。argparse 对同名选项是覆盖：实测
    `parse_args(["--skip", "x", "--skip", "y"]).skip == ["y"]` ——
    也就是说按最自然的重复写法传 7 个 `--skip`，实际只有最后一个生效，
    其余七项真的跑了，而调用方以为跳过了它们。这是发布门上的"声明与行为不符"。

    ## 现在的口径（三种写法等价）

    - `--skip a,b`（逗号分隔）
    - `--skip a --skip b`（重复 flag）
    - `--skip a b`（空格分隔，兼容旧写法）

    第三种要求 `action="append"` 与 `nargs="+"` 同时给：只给 `append` 时
    `--skip a b` 里的 `b` 会被当成位置参数而报错，于是旧写法的调用方在升级后
    会拿到"用法错误"（那是可见的失败，不是静默改行为，但仍是一次破坏）。

    注意那两行合在一起的结果是嵌套列表：`--skip a b` 给的是
    `[["a", "b"]]`、`--skip a --skip b` 给的是 `[["a"], ["b"]]`。
    所以这里必须递归摊平 —— 第一版对每个 chunk 直接 `str(...)`，
    于是 `--skip a b` 被读成 `{"['a'", "'b']"}` 这种谁也不认识的 key，
    结果是"没有任何一项被跳过"（一次静默的空跳，比旧缺陷更坏）。
    这条路径由 `tests/test_release_check_items.py` 的三写法等价用例钉住。
    """
    out: set[str] = set()
    for chunk in raw or []:
        if isinstance(chunk, (list, tuple)):
            if _depth > 4:  # pragma: no cover —— 防御：畸形输入不许把门挂死
                continue
            out |= _parse_skip_values(chunk, _depth + 1)
            continue
        for part in str(chunk).split(","):
            part = part.strip()
            if part:
                out.add(part)
    return out


def item_linter(rep: Report) -> Item:
    """第 5 项：linter，严格档 + 三态映射（`H-6`）+ 产物落临时目录（`c-11`）。

    ## 为什么必须带 `--strict`（`H-6`）

    旧命令是 `[lint_rules.py, --json-out, <artifact>]`，没有 `--strict` ——
    于是 `warning` 全被丢掉，而文档（`DEVELOPMENT.md` §2.4 / §8.4）声称发布级用严格档。
    实测：日常 `error 0 / warning 0 / info 21` 退出码 0；`--strict`
    `error 0 / warning 39 / info 20` 退出码 1。也就是说 R007 那类"成文规则配不上一条门"
    的缺口在发布链上永远不可见。

    ## 严格档之后，这一项的判据是「逐项读 error 与 warning」，不是「退出码 == 0」

    这是关键的一半：只把 `--strict` 加上、判据仍写 `exit_code == 0`，会让这一项
    立刻变成 `fail`（因为 `lint_rules.py --strict` 在 warning 非空时退 1），
    而 `error` 明明是 0 —— 那是"把 warning 读成了 fail"，判别力反而下降
    （读的人分不清"有一处确定违规"与"有一堆待补的 docstring"）。
    所以判据改成三态映射，且先把 error 与 warning 分开读：

    | linter 的实测 | 这一项 |
    |---|---|
    | `error_count > 0` | `fail`（确定违规） |
    | `error_count == 0`、`warning_count > 0` | `pass`，但 `detail.errors_zero_warnings_present = True`，并在 `notes` 里把"严格档下仍有 N 条 warning"逐字报出来 |
    | 退出码 2（读不到源码树 / linter 自己炸） | `unknown`（这是检查器的问题，不是被检对象的） |
    | 拿不到 JSON 或读不出计数 | `unknown`（没查成，不许按退出码猜） |

     这一档是加严：`warning` 从此在发布报告里有了名字与计数（此前一个字都不出现）。
    它没有把"warning 非空"升成门失败，理由见 `H-6` 的裁决：门失败的含义是
    "有确定违规"，而把 39 条待补 docstring 说成"发布门失败"会让这一项长期变红并被忽略
    （本文件 R009 对禁改区用的是同一条理由）。要让 warning 参与阻断，改的是
    `error_count > 0` 那一行 —— 那是一次口径变更，需要人裁。

    ## 产物路径（`c-11`）

    正常落点 `GATE_ARTIFACT_DIR`（被 `.gitignore` 排除的 `temp/`，`X-1`）；
    连它都建不出来时回退到系统临时目录，绝不回退到仓库根 ——
    仓库根的 `.release-lint.json` 是禁改区门的输入面（`F8` 之后它已从版控删除，
    但只要有人在仓库根写下这个名字，它就会作为新增文件进入"本次改动集"——
    被跟踪与被新建在这一点上后果相同），回退写它等于
    "跑一次门就改一次改动集"，而"本次改动集"正是禁改区门的输入（自我污染）。
    `c-11` 的机器判据：`tests/test_release_check_noai.py` 里那条"回退产物不在仓库里、
    且跑完 `git status` 不多出被跟踪文件的改动"。
    """
    it = rep.add(Item("lint", "linter（严格档：error = 0；warning 逐条报数）"))
    artifact, why = _artifact_path()
    if why:
        it.notes.append(why)
    r = _run([sys.executable, str(REPO_ROOT / "scripts" / "lint_rules.py"), "--strict",
              "--json-out", str(artifact)], cwd=REPO_ROOT, timeout=600.0)
    it.detail["artifact"] = str(artifact)
    it.detail["strict"] = True
    it.detail["strict_command_has_flag"] = "--strict" in r["cmd"].split()
    if not r["started"] or r["timed_out"]:
        it.verdict = "unknown"
        it.notes.append("linter 没跑成")
        return it
    # 退出码 2 是"linter 自己没跑成"（读不到源码树 / 自身抛异常），与"被检对象有问题"是两件事。
    if r["exit_code"] == 2:
        it.verdict = "unknown"
        it.notes.append("linter 自身失败（退出码 2）——这是检查器的问题，不是被检对象的")
        return it
    # 判据读的是它写下的那份 JSON（error 与 warning 分开），而不是只读退出码。
    counts = _read_lint_counts(artifact)
    it.detail["exit_code"] = r["exit_code"]
    it.detail["tail"] = _tail(r["stdout"] + r["stderr"], 6)
    if counts is None:
        it.verdict = "unknown"
        it.notes.append(
            f"读不出 linter 的逐项计数（退出码 {r['exit_code']}，产物 {artifact}）"
            "⇒ 没查成：不许按退出码猜它是哪一档"
        )
        return it
    it.detail.update(counts)
    errors = int(counts.get("error_count") or 0)
    warnings = int(counts.get("warning_count") or 0)
    it.detail["errors_zero_warnings_present"] = bool(errors == 0 and warnings)
    # `FINAL-R7-11`：R011 有两条"没查成"退路（读不到 `tools/vocab_census.py`、
    # 或普查 `checked=False`），它们按设计报 warning —— 而本项的判据是
    # `error_count > 0`，于是"R011 一次都没判"与"判过、干净"在发布报告里同形。
    # 这里把那个仪器状态单独提出来做成一个可见的位（不改判据强度：
    # 仍是 pass，但报告里多一行明确的"没查成"，而不是让它淹在 warning 计数里）。
    it.detail["r011_checked"] = _r011_was_checked(artifact)
    if it.detail["r011_checked"] is False:
        it.notes.append(
            "⚠️ R011（受控词表死取值）这一轮没查成 —— 词表普查的仪器状态是"
            "『读不到普查工具』或 `checked=False`（见 lint 规则 R011 的两条 warning 退路）。"
            "它按设计不升成 error（常驻仪器状态不是被检对象的缺口），"
            "但不许被读成『词表很干净』：这一项 pass 的含义只是『没有确定违规』。"
        )
    if errors:
        it.verdict = "fail"
        it.notes.append(
            f"linter 报了 {errors} 条 **error**（确定违规）⇒ 这一项 fail；"
            f"另有 {warnings} 条 warning（严格档）"
        )
        return it
    it.verdict = "pass"
    if warnings:
        it.notes.append(
            f"error = 0 ⇒ 这一项 pass。但严格档下仍有 {warnings} 条 warning（非 error）——"
            "它们此前一个字都不出现在发布报告里（`H-6` 的缺口：发布门不带 `--strict`）。"
            "这条 pass 的含义是『没有确定违规』，不是『严格档干净』："
            "要看的 warning 在 JSON 的 `warnings[]` 里，逐条带路径与行号。"
        )
    else:
        it.notes.append("error = 0 且严格档 warning = 0 ⇒ 严格档干净")
    return it


def _artifact_path() -> tuple[Path, str]:
    """选一个不落在仓库里的产物路径（`c-11` 的根除口径）。

    两条路都是临时目录：
    1. 首选 `GATE_ARTIFACT_DIR`（`REPO_ROOT.parent / "temp"`，被 `.gitignore` 排除，
       与 `X-1` / `D-2.3` 同一条口径）；
    2. 它建不出来（权限 / 磁盘 / 只读文件系统）⇒ 回退到 `tempfile.mkdtemp()`。

    绝不回退到 `REPO_ROOT/.release-lint.json`：那个文件被 git 跟踪
    （`git ls-files --error-unmatch .release-lint.json` 在改前是成功的），
    回退写它等于"跑一次门就改一次仓库状态"，而"本次改动集"正是禁改区门的输入。
    产物位置不固定不是问题：它写进 `Item.detail["artifact"]` 与 `notes` 里，
    读报告的人照样找得到（"产物在哪"与"仓库有没有被改"相比，后者是不可逆的）。
    """
    try:
        GATE_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError) as exc:
        # `ValueError` 也要捕：Windows 上路径里带 NUL 的 `mkdir` 抛的是
        # `ValueError: embedded null character in path`，不是 `OSError` ——
        # 只捕 OSError 会让"建不出目录"这条回退路径自己崩掉，
        # 于是"产物落在哪"这个次要问题变成一个不属于三态的崩溃。
        fallback = Path(tempfile.mkdtemp(prefix="agentflow-release-lint-"))
        return fallback / "release-lint.json", (
            f"temp/ 建不出来（{type(exc).__name__}: {exc}）⇒ 产物回退到系统临时目录 "
            f"{fallback}（不回退到仓库根：在那里写下 `.release-lint.json` 会进"
            "『本次改动集』，而跑一次门就改一次改动集等于自我污染）"
        )
    return GATE_ARTIFACT_DIR / "release-lint.json", ""


def _read_lint_counts(artifact: Path) -> dict | None:
    """读 linter 写下的 JSON 里的三档计数（读不到 ⇒ `None`，不许猜）。"""
    try:
        data = json.loads(Path(artifact).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    out = {k: data.get(k) for k in ("error_count", "warning_count", "info_count")}
    if any(not isinstance(v, int) for v in out.values()):
        return None
    return out


def _r011_was_checked(artifact: Path) -> bool | None:
    """R011 这一轮到底判没判（`FINAL-R7-11`）：`True`/`False`/`None`（读不出来）。

    判据：在 linter 的 JSON 里找 `rule == "R011"` 且 `level == "warning"` 的条目，
    它们的文案是那两条"没查成"退路（读不到普查工具 / `checked=False`）。
    读不出 JSON ⇒ `None`（没查成，不猜）。为什么按文字匹配而不是新加一个字段：
    那两条 Finding 是唯一实现里现有的出口，改它们的 `rule`/`level` 会动 lint 的判据本体
    （那是另一次口径变更）；这里只做"把它从 warning 计数里提出来、单独可见"。
    """
    try:
        data = json.loads(Path(artifact).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    warnings = data.get("warnings")
    if not isinstance(warnings, list):
        return None
    checked = True
    for w in warnings:
        if not isinstance(w, dict) or str(w.get("rule") or "") != "R011":
            continue
        text = str(w.get("message") or "")
        if "没查成" in text or "读不到词表普查工具" in text:
            checked = False
    return checked


def item_noai(rep: Report, changed: Sequence[str] | None, *, ledger: str | None = None) -> Item:
    """禁 AI 区门。`changed is None`（没给）与 `changed == []`（给了且为空）不是同一件事。

    前者是"没查成"（unknown），后者是"查过了、相对基线没有改动"（pass）。第一版用
    `default=[]` 把两者折叠成一个 `if not changed`，于是编排层不传 `--changed` 时这一项
    永远是 unknown（实测 `UNKNOWN pass=7 fail=0 unknown=1`）—— 也就是说这道门在发布链上
    从来没有真的生效过。空集与缺输入必须分开。

    ## 命中之后按台账判定，而不是"命中即 fail"（`P-3`）

    上一版是"命中禁改区 ⇒ fail，永远无法转绿"：登记过的改动（`--baseline` 写了 sha256）
    与人走查过的改动（`--approve` 写了 reviewers）在它眼里与"从来没人看过"一样
    —— 于是这道门给不出真实状态（它只会说"这里有人动过"，不会说"动过的那一版
    有没有被批准"）。现在它调的是门自己的 `--check-approvals`：

    | 判据（`noai_gate.evaluate_approval`，唯一实现） | 这一项的结论 |
    |---|---|
    | 台账里有该路径、`sha256` 与当前文件一致，且通路是人审（≥2 名不同 reviewer 逐行走查） | `pass`，说明里写明"通路 = 人审" |
    | 同上，且通路是多维独立审计（≥2 名不同审计者 × ≥3 个维度、无 finding、每条带负控、证据锚与回执链都对得上） | `pass`，说明里逐字写明"无人类 reviewer 签字" |
    | 台账里没有条目 / `sha256` 漂了 / 两条通路都不够 | `fail`（并写清缺的是哪一条） |
    | 台账读不到或解析不了 / 拿不到盘上内容的 sha256 / 证据锚或回执链核对不上 | `unknown`（没查成） |

     本表第一版漏了机审那一行（`R1-1`）：于是 `pass` 说明无条件写"各有 ≥2 名不同
    reviewer 完成逐行走查"，而机审放行走廊里 `reviewers` 是空的 —— 发布报告在
    替一个没有人签过字的通路宣称"人走过查了"。这正是 FC-27 最忌讳的形态（`noai_gate`
    自己在 clean 抬头里已经按通路分流，发布门这一侧当时没跟上）。

    这一项永远不写 `reviewers`：批准是人的动作。这一项只读台账、只报状态。

    ## 清单一致性那一半（`--check-consistency`）也是三态（`Y-3`）

    这一项先跑门的一致性检查，再跑改动集判定。一致性检查自己有三个退出码，
    而它们是三个不同的事实（码表由门定义，负控见
    `tests/test_noai_gate.py::test_check_consistency_read_failure_is_unknown_not_disagreement`）：

    | 退出码 | 事实 | 这一项的结论 |
    |---|---|---|
    | `0` | 两个落位逐条一致 | 继续往下判改动集 |
    | `1` | 查过了：两处清单不一致 | `fail`（两处会按不同清单行事） |
    | `2` | 没查成：清单读不到 / 不在 git 仓库 / 解析失败 | `unknown`，不许写成"不一致" |

    旧版用一句 `if exit_code != 0 ⇒ fail` 把后两档折成一个结论：一次根本没做成的比对
    会被报告成"两处清单不一致"这个具体断言。那是"把 `unknown` 当 `pass`"的镜像，
    同属三态纪律（`Y-3`）。

    ## `ledger` 参数（默认 None ⇒ 生产路径恒用仓库默认台账）

    它存在的唯一理由是让核验能把三条分支都在临时台账上跑一遍（正控：两个
    合成 reviewer ⇒ pass；负控：清空 reviewers ⇒ fail；负控：sha 漂掉 ⇒ fail），
    而不必往真实台账里写任何一条批准记录。发布链上（`main`）永远不传它。
    """
    it = rep.add(Item("noai", "禁 AI 区门（清单一致 + 改动集判定）"))
    gate = REPO_ROOT / "scripts" / "noai_gate.py"
    if not gate.exists():
        it.verdict = "unknown"
        it.notes.append("`scripts/noai_gate.py` 不存在 ⇒ **门还没接线**（不是'没有禁改区'）")
        return it
    r1 = _run([sys.executable, str(gate), "--check-consistency"], cwd=REPO_ROOT, timeout=120.0)
    if not r1["started"] or r1["timed_out"]:
        it.verdict = "unknown"
        it.notes.append("一致性检查没跑成")
        return it
    it.detail["consistency_exit"] = r1["exit_code"]
    it.notes.extend(_tail(r1["stdout"] + r1["stderr"], 4))
    if r1["exit_code"] == 2:
        # `Y-3`：`--check-consistency` 的 `2` 是没查成（清单读不到 / 不在 git 仓库…），
        # 不是"两处清单不一致"（那是 `1`）。旧版用 `if exit_code != 0 ⇒ fail` 把两个码
        # 折成一个结论，于是报告替一次根本没做成的比对写下"两处会按不同清单行事"
        # 这个具体断言 —— 那是"把 unknown 当 fail"的镜像，与本项目反复踩的
        # "把没检查读成检查过了没问题"是同一条三态纪律的两面。
        it.verdict = "unknown"
        it.notes.append(
            "清单一致性检查**没查成**（退出码 2：清单读不到 / 不在 git 仓库 / 解析失败之一）"
            "⇒ `unknown` 绝不是「两处清单一致」，也绝不是「两处不一致」。"
            "三态纪律：把「没检查」与「检查过了没问题」折叠成同一个通过，是本项目反复踩过的坑"
            "（`Y-3`；门的码表：0=一致 / 1=查过了、不一致 / 2=没查成）。"
        )
        return it
    if r1["exit_code"] != 0:
        it.verdict = "fail"
        it.notes.append("`.noai-paths` 与 `AGENTS.md` 的清单**不一致** ⇒ 两处会按不同清单行事")
        return it
    if changed is None:
        it.verdict = "unknown"
        it.notes.append(
            "没给改动集（`--changed` / `--changed-file`）⇒ 没查成。三态纪律：`unknown` 绝不是 `clean`。"
            "用法：`python scripts/release_check.py --changed src/agentflow/dedup.py`；"
            "编排层应当给基线：`--changed-file <每行一条路径>`（空文件 = 已声明且改动集为空 ⇒ pass）。"
        )
        return it
    if not changed:
        it.verdict = "pass"
        it.detail["gate_exit"] = None
        it.notes.append(
            "给了改动集，而它为空 ⇒ 相对所声明的基线没有改动，禁 AI 区门这一项没有对象可判 ⇒ pass。"
            "这与没给改动集是两件事：前者是查过了、确实没有改动；后者是没查成。"
        )
        return it
    cmd = [sys.executable, str(gate), "--check-approvals", "--paths", *changed, "--json"]
    if ledger:
        # 只给核验用（见 docstring）：生产路径上恒为 None ⇒ 用仓库默认台账。
        cmd += ["--ledger", str(ledger)]
        it.detail["ledger_override"] = str(ledger)
    r2 = _run(cmd, cwd=REPO_ROOT, timeout=120.0)
    it.detail["gate_exit"] = r2["exit_code"]
    if not r2["started"] or r2["timed_out"]:
        it.verdict = "unknown"
        it.notes.append("门的台账判定没跑成（起不来或超时）⇒ 没查成，不是'通过'")
        return it
    try:
        gate_result = json.loads(r2["stdout"])
    except (ValueError, TypeError) as exc:
        # 读不出结构化结论 ⇒ 没查成。绝不按退出码猜它是哪一档。
        it.verdict = "unknown"
        it.notes.append(f"门的 `--json` 输出解析不了（{type(exc).__name__}: {exc}）⇒ 没查成")
        return it
    it.detail["gate_verdict"] = gate_result.get("verdict")
    it.detail["approvals"] = gate_result.get("approvals")
    it.detail["ledger"] = gate_result.get("ledger")
    it.notes.extend(_tail(r2["stdout"] + r2["stderr"], 4))
    if r2["exit_code"] == 0:
        it.verdict = "pass"
        # 通路分流（`R1-1`）：`noai_gate` 的 `approved` 有两条通路，这里必须照实说清是哪一条。
        # 旧版无条件写"各 ≥2 名不同 reviewer 完成逐行走查" —— 机审通行走廊里 `reviewers`
        # 是空的，那句话就是假的（同族缺陷在 `noai_gate` 的 clean 抬头里已经修过，
        # 见 noai_gate.py 里 by_human/by_audit 那一段）。
        #
        #  `REAUDIT2-R1-1`（第二轮复审实测）：只有 when_clean 且 `approvals` 非空
        # 才配说"命中路径全部已获批准"。无命中时门返回 `clean` + `approvals == []` +
        # `ledger == ""`，旧版（本轮第一版）会落到 `else` 那一支，宣称
        # "通路=多维独立审计……没有任何人类 reviewer 签过字" —— 那是替不存在的台账判定
        # 与不存在的审计流程作证。所以现在分三支，并且"无命中"那一支不许提批准。
        approvals = gate_result.get("approvals")
        approval_list = [a for a in (approvals or []) if isinstance(a, dict)]
        when_clean = gate_result.get("verdict") == "clean"
        by_human = [a for a in approval_list
                    if a.get("approval_reason") == "approved"
                    and int(a.get("distinct_reviewers") or 0) >= 2]
        by_audit = [a for a in approval_list
                    if a.get("approval_reason") == "approved" and a not in by_human]
        if when_clean and approval_list:
            if by_human:
                it.detail["pass_path"] = "human"
                it.notes.append(
                    "命中路径**全部**已在台账里获批准（`sha256` 与盘上这一版一致；"
                    f"{len(by_human)} 条通路 = **人审**，各 ≥2 名不同 reviewer 完成逐行走查）"
                    "⇒ 这一项 pass。"
                    "注意这个 pass 是**靠台账判定的**，不是靠'没人动过'。"
                )
            elif by_audit:
                it.detail["pass_path"] = "audit"
                it.notes.append(
                    "命中路径**全部**已在台账里获批准（`sha256` 与盘上这一版一致；通路 = "
                    "**多维独立审计**：≥2 名不同审计者 × ≥3 个维度、无 finding、每条带负控、"
                    "证据锚与回执链都核对过）⇒ 这一项 pass。"
                    "⚠️ 这一档**没有任何人类 reviewer 签过字**（`reviewers` 是空的）——"
                    "读这条 pass 时请把这一点一起读。"
                    "注意这个 pass 是**靠台账判定的**，不是靠'没人动过'。"
                )
            else:
                # 门说 clean、也有 approvals，但一条都不是 `approved`：这是判据漂了
                # （门与这一项的读法对不上），不许当成"已获批准"。
                it.detail["pass_path"] = "unexplained"
                it.verdict = "unknown"
                it.notes.append(
                    "门报了 `clean` 且给出了批准记录，但**没有任何一条的理由码是 `approved`**"
                    "（实测理由码：" + "、".join(sorted({str(a.get("approval_reason"))
                                                        for a in approval_list})) + "）"
                    "⇒ 这一项按'没查成'记（unknown）：门与发布门这一侧的读法已经对不上，"
                    "不许把它读成'已获批准'。"
                )
        elif when_clean:
            # 门查过了、没有命中禁改区。没有台账判定与审计流程可宣称。
            it.detail["pass_path"] = "no_hits"
            it.notes.append(
                "门查过了：本次改动的路径**一条都没有命中禁改区** ⇒ 这一项 pass。"
                "注意这个 pass 说的是'没有对象可判'，**不是**'已在台账里获批准'——"
                "本次运行里根本没有批准记录（`approvals` 为空），"
                "所以这里不写任何关于 reviewer 或审计通路的话。"
            )
        else:
            it.verdict = "unknown"
            it.detail["pass_path"] = "unknown"
            it.notes.append(
                "门的退出码是 0，但它的结构化结论不是 `clean`（实测 verdict="
                f"{gate_result.get('verdict')!r}）⇒ 两边对不上，按'没查成'记（unknown），"
                "不许按退出码猜它是哪一档。"
            )
    elif r2["exit_code"] == 1:
        it.verdict = "fail"
        unapproved = [
            a for a in (gate_result.get("approvals") or [])
            if a.get("approval_status") == "unapproved"
        ]
        for a in unapproved:
            code = str(a.get("approval_reason") or "unknown")
            it.notes.append(
                f"{a.get('path')}：{_APPROVAL_REASON_TEXT.get(code, code)}"
                f"（台账判定 `{a.get('approval_status')}`/`{code}`）"
            )
        # `FINAL-R7-03`：`ledger_self_approval` 这一档的处置指示必须做得到 ——
        # 台账本体按设计永远不可批准（门对 `.noai-approvals.json` 恒判 unapproved），
        # 所以对那一档说"去凑 2 名 reviewer"是一句做不到的话，会让人白跑。
        has_ledger_self = any(
            str(a.get("approval_reason") or "") == "ledger_self_approval" for a in unapproved
        )
        if has_ledger_self:
            it.notes.append(
                "其中 `.noai-approvals.json` 这一条**按设计永远不可批准**（台账不能批准自己）——"
                "对它不要去找 reviewer；可行动作只有两个：让台账与基线保持一致（把它排除出改动集），"
                "或换一个真基线 ref（`--since <上一个里程碑>` / 显式 `--changed-file`）。"
            )
        other_unapproved = [
            a for a in unapproved
            if str(a.get("approval_reason") or "") != "ledger_self_approval"
        ]
        if other_unapproved:
            it.notes.append(
                "其余未获批准的条目 ⇒ 需人编写或人逐行走查 + **2 名 reviewer 批准**（FC-27）。"
                "⚠️ 这一项与门都不会代写 `reviewers`：批准只能由人 "
                "`noai_gate.py --approve [--evidence-path <走查记录>]` 追加。"
            )
    else:
        it.verdict = "unknown"
        it.notes.append(
            "台账判定给的是 unknown（没查成）—— 例如台账读不到/结构不合规、"
            "或拿不到盘上内容的 sha256。**没查成绝不是通过**：先修台账或文件可读性。"
        )
    return it


def item_contract(rep: Report) -> Item:
    it = rep.add(Item("contract", "契约版本与 schema 版本一致"))
    code = (
        "import json, agentflow\n"
        "from agentflow import interactions as I, schema as S\n"
        "print(json.dumps({'pkg_version': agentflow.__version__,\n"
        "                  'schema_version_pkg': agentflow.__schema_version__,\n"
        "                  'schema_version_mod': S.SCHEMA_VERSION,\n"
        "                  'contract_pkg': agentflow.CONTRACT_VERSION,\n"
        "                  'contract_mod': I.CONTRACT_VERSION}))\n"
    )
    r = _run([sys.executable, "-c", code], cwd=SRC, timeout=120.0)
    if not r["started"] or r["timed_out"] or r["exit_code"] != 0:
        it.verdict = "unknown"
        it.notes.append(f"读版本号失败：{_tail(r['stderr'], 4)}")
        return it
    d = json.loads(r["stdout"].strip().splitlines()[-1])
    it.detail = d
    problems = []
    if d["schema_version_pkg"] != d["schema_version_mod"]:
        problems.append("`__schema_version__` 与 `schema.SCHEMA_VERSION` 不一致")
    if d["contract_pkg"] != d["contract_mod"]:
        problems.append("`CONTRACT_VERSION` 的两处定义不一致")
    it.verdict = "pass" if not problems else "fail"
    it.notes.extend(problems)
    it.notes.append("数据格式版本与函数契约版本是**两件事**，必须能分别升（本项目真的发生过：判据语义变了而格式没变）")
    return it


def item_imports(rep: Report) -> Item:
    """源码树可导入 + 能力表自检被显式触发（`P-2`，2026-10-27 改成显式）。

    ## 为什么"导入普查"之外还要单独跑一次能力表审计

    2026-10-27 之前 `capabilities.assert_capabilities()` 挂在导入期（"不可能忘记跑"是
    当时的理由）。代价是两条实测：① 它给**每一次** CLI 启动加 1.2 秒；② 任何一格的
    登记过期都会让所有命令 exit 1（当天真实发生过：一条并行 lane 收尾没做完就让
    `agentflow --help` 也炸）。业主当批把它摘出导入期。

    摘出来之后，"不可能忘记跑"这句话就落在**本项**与
    `tests/test_capabilities_audit_is_explicit.py` 上 —— 所以这里的调用是硬的：
    `import agentflow.capabilities` 本身**不再**跑审计，本项必须显式调
    `run_capability_audit()`，否则这一项会绿着、而审计一次都没跑（那正是三态纪律
    要挡的"没查 ≠ 查过了没问题"）。

    子项自己的成败与普查的成败分开报 —— 两个都在，才是"我知道哪一条查了"。
    代价（照实写）：显式跑一趟实测约 1.4 秒（三个源码读取器在进程内有缓存，
    `tests/test_capabilities_readers_parse_once.py` 钉着这一点）。
    """
    it = rep.add(Item("imports", "源码树可导入（无循环依赖）+ 能力表自检"))
    code = (
        "import importlib, json, pkgutil, agentflow\n"
        "bad = {}\n"
        "mods = [m.name for m in pkgutil.walk_packages(agentflow.__path__, 'agentflow.')]\n"
        "for name in mods:\n"
        "    try:\n"
        "        importlib.import_module(name)\n"
        "    except Exception as e:\n"
        "        bad[name] = f'{type(e).__name__}: {e}'\n"
        "print(json.dumps({'total': len(mods), 'bad': bad}, ensure_ascii=False))\n"
    )
    r = _run([sys.executable, "-c", code], cwd=SRC, timeout=300.0)
    if not r["started"] or r["timed_out"] or r["exit_code"] != 0:
        it.verdict = "unknown"
        it.notes.append(f"导入普查没跑成：{_tail(r['stderr'], 4)}")
        return it
    d = json.loads(r["stdout"].strip().splitlines()[-1])
    it.detail = d
    # ---- 子检查①：能力表自检（`P-2`）—— 显式调用，不依赖"导入期"或"普查碰巧走到它"
    r2 = _run([sys.executable, "-c",
               "import agentflow.capabilities as C; C.run_capability_audit()"],
              cwd=SRC, timeout=300.0)
    if not r2["started"] or r2["timed_out"]:
        it.detail["capability_selfcheck"] = {"verdict": "unknown", "exit_code": None}
        it.verdict = "unknown"
        it.notes.append(
            "能力表自检（`capabilities.run_capability_audit()`）**没跑成**（起不来或超时）⇒ "
            "这一项不能判 pass：那次审计本次没有运行"
        )
        return it
    it.detail["capability_selfcheck"] = {
        "verdict": "pass" if r2["exit_code"] == 0 else "fail",
        "exit_code": r2["exit_code"],
        "tail": _tail(r2["stdout"] + r2["stderr"], 6),
    }
    if r2["exit_code"] != 0:
        it.verdict = "fail"
        it.notes.append(
            "能力表自检**失败**（`C.run_capability_audit()` 退出码 "
            f"{r2['exit_code']}）—— 那是 `assert_capabilities()` 在说"
            "『能力表与实现已经漂移』（写集 ↔ 效果轴、两层声明对账、handler 存在性、"
            "词表单一来源等）。这不是「没查成」，是一件真实的违约。"
        )
        it.notes.extend(_tail(r2["stdout"] + r2["stderr"], 6))
        return it
    # ---- 子检查②：导入普查
    it.verdict = "pass" if not d["bad"] else "fail"
    if d["bad"]:
        it.notes.append(f"这些模块导入失败（**循环依赖会在这里炸**）：{sorted(d['bad'])}")
    it.notes.append(
        "能力表自检已由本项显式触发（2026-10-27 起 `assert_capabilities()` 不再挂在"
        "导入期：本项是它在发布门上的唯一触发器，日常判据侧由 "
        "`tests/test_capabilities_audit_is_explicit.py` 承担）"
    )
    return it


# ------------------------------------------------------------------ main


def main(argv: Sequence[str] | None = None) -> int:
    # 注意（`I-3` / 三态纪律）：没跑完不许给 0。
    # Ctrl-C（`KeyboardInterrupt` 是 `BaseException`，八个 runner 的
    # `except Exception` 兜不住它）此前会让本脚本带 traceback 结束，退出码由
    # Python 决定（130/1），既不是 0/1/2 中的任何一档 —— 调用方（编排层 / CI）
    # 只能靠猜。这里显式记 `unknown`（2）并打印已经判到的那几项：
    # "没查完"与"查过没问题"必须分得开，而中断恰恰是最容易把两者混起来的一刻。
    try:
        return _main(argv)
    except KeyboardInterrupt:
        print(
            "\n[release] 被中断（KeyboardInterrupt）⇒ 本次**没查完**："
            "按三态纪律记 unknown（退出码 2），不构成发布许可，也不等于任何一项通过。",
            file=sys.stderr,
        )
        return 2


def _main(argv: Sequence[str] | None = None) -> int:
    # 先把输出编码钉在 UTF-8 上再做任何事：总判定的那几行是本脚本的最终产物，
    # 而它们在 cp936 控制台上会抛 UnicodeEncodeError（见 `_ensure_utf8_console`）。
    _ensure_utf8_console()
    # `allow_abbrev=False`：理由同 `lint_rules.py` —— `--json` 是 `--json-out` 的前缀，
    # 不关掉缩写，旧写法会被 argparse 静默当成新名字（那等于同一个名字还是两套语义）。
    ap = argparse.ArgumentParser(description="agentflow 发布前检查（八项，三档判定）",
                                 allow_abbrev=False)
    ap.add_argument(
        "--changed",
        nargs="*",
        default=None,
        help="本次改动的文件（给禁 AI 区门用）。不给 ⇒ 那一项如实报 unknown；给空列表 ⇒ 改动集为空 ⇒ pass",
    )
    ap.add_argument(
        "--changed-file",
        default="",
        help="改动集文件（每行一条路径，空行忽略）。空文件 = 已声明且为空；读不到 ⇒ 保留 unknown",
    )
    ap.add_argument("--json-out", default="", help="把结果写到该 JSON 路径（产物恒为纯 LF，见 `c-12`）")
    # `c-10`：三种写法必须等价 —— `--skip a,b` / `--skip a --skip b` / `--skip a b`。
    # `action="append"` 保证重复 flag 不被覆盖；`nargs="+"` 保住旧写法的兼容
    # （只给 `append` 会让 `--skip a b` 里的 `b` 变成非法位置参数 ⇒ 一次可见的用法错误）。
    ap.add_argument(
        "--skip",
        action="append",
        nargs="+",
        default=[],
        metavar="KEY",
        help=(
            "跳过某些项（key），调试用。可重复给、可用逗号分隔，也可一次给多个："
            "`--skip a,b` == `--skip a --skip b` == `--skip a b`"
            "（跳过的项记 unknown，不是 pass）"
        ),
    )
    args = ap.parse_args(argv)
    skip_keys = _parse_skip_values(args.skip)

    changed: list[str] | None
    if args.changed_file:
        try:
            lines = Path(args.changed_file).read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            print(
                f"[release] 改动集文件读不到（{type(exc).__name__}: {exc}）⇒ 这一项保持 unknown",
                file=sys.stderr,
            )
            changed = None
        else:
            changed = [ln.strip() for ln in lines if ln.strip()]
    else:
        changed = list(args.changed) if args.changed is not None else None

    if not (SRC / "agentflow").exists():
        print(f"[release] 读不到源码树 {SRC / 'agentflow'} —— **检查器自身失败**（退出码 2）", file=sys.stderr)
        return 2

    rep = Report()
    runners = (
        ("tests", lambda: item_test_suite(rep)),
        ("selftests", lambda: item_selftests(rep)),
        ("tools", lambda: item_tool_census(rep)),
        ("verify", lambda: item_verify(rep)),
        ("lint", lambda: item_linter(rep)),
        ("noai", lambda: item_noai(rep, changed)),
        ("contract", lambda: item_contract(rep)),
        ("imports", lambda: item_imports(rep)),
    )
    for key, fn in runners:
        if key in skip_keys:
            # `I-3`：跳过的项必须留痕（进 `rep.skipped`），否则"没跑"在报告里
            # 与"跑了没问题"长得一模一样。这里同时打一行，让 stdout 上也看得见。
            rep.skipped.append(key)
            print(f"\n===== [{key}] =====", flush=True)
            print(f"  [SKIP] 被 `--skip` 关掉，本次没有跑 ⇒ 总判定按 unknown 记（不是 pass）")
            continue
        print(f"\n===== [{key}] =====", flush=True)
        try:
            item = fn()
        except Exception as e:  # noqa: BLE001
            item = Item(key, key, "unknown", {}, [f"检查项自身抛异常：{type(e).__name__}: {e}"])
            rep.add(item)
        mark = {"pass": "PASS", "fail": "FAIL", "unknown": "????"}[item.verdict]
        print(f"  [{mark}] {item.title}")
        for n in item.notes:
            print(f"        · {n}")

    d = rep.to_dict()
    if args.json_out:
        # `c-12`（`G-42` 的换行纪律）：产物必须是纯 LF。`Path.write_text` 在 Windows 上
        # 会把每个 `\n` 刷成 `\r\n` ⇒ 产物的 `sha256` 与"盘上那一版"对不上，
        # 而禁改区批准台账钉住的正是 `sha256`（`draft/22` §12.15.2 记过那次事故）。
        # 这条纪律本身有机器判据：`scripts/lint_rules.py::rule_R012_write_text_newline`。
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8", newline="") as fh:
            fh.write(json.dumps(d, ensure_ascii=False, indent=2))

    c = rep.counts()
    overall = rep.overall()
    print("\n" + "=" * 72)
    print(f"发布检查总判定：{overall.upper()}    pass={c['pass']} fail={c['fail']} "
          f"unknown={c['unknown']} skip={c['skipped']}")
    if c["skipped"]:
        # 这句话必须随本次运行的事实变：旧版无论跳过几项都逐字打印"这八项都通过了"，
        # 于是"七项没跑"的运行也挂着那句假话（`I-3` 复现记录见 `Report.overall`）。
        print(f"⚠️ 本次有 {c['skipped']} 项被 `--skip` 关掉（{', '.join(rep.skipped)}）⇒")
        print("   总判定记 unknown（退出码 2）。「没让某几项跑」不等于「某几项都通过」。")
    elif c["fail"]:
        # `REAUDIT2-R1-3`：fail 档也不许说"八项都通过了"。
        print(f"⚠️ 本次有 {c['fail']} 项**没通过** ⇒ 不构成发布许可：")
    elif c["unknown"]:
        print(f"⚠️ 本次有 {c['unknown']} 项**没查成**（unknown ≠ 通过）⇒ 不构成发布许可：")
    else:
        print(f"⚠️ overall=pass 只说明本次跑到的那 {c['pass']} 项都通过了，**不构成发布许可**：")
    print("   本脚本自身在禁 AI 区（`.noai-paths` 的 release-deploy 类），按 FC-27 仍需人逐行走查 + 2 名 reviewer 批准。")
    if args.json_out:
        print(f"结果 JSON: {args.json_out}")

    if overall == "fail":
        return 1
    if overall == "unknown":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

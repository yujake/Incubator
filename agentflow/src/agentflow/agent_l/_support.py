# -*- coding: utf-8 -*-
"""L（Lean 形式化者）用到的受控词表与小工具。

## 这里的东西从哪来

业主 2026-10-22 的施工单：照 E 的 Lean 面复制出 L，E 的代码一行不删、行为不改。
所以受控词表不复制，而是从 E 的实现包里 import 过来（`agent_e._support`）：

- `FORMAL_REASONS` 与 `_FORMAL_REASON_BY_TOOL_REASON`（桥接层理由的收口表）是
  E 那一侧的唯一落点。抄一份到这里就等于埋下"两份词表各自漂移、而没有任何地方报"
  的隐患（FC-03 的形态）。L 只在这张表外面追加自己的三个理由码；
- `ExperimentError` / `_relpath`：路径守卫与相对路径口径，与 E 逐字同一份实现。

## L 自己那三个理由码

自检（`leantoolchain`）不是 `usable` 时，L 的形式化结论一律记 `unknown`。三种原因
各自有码，因为它们该被分开处置：

| 理由码 | 自检状态 | 处置 |
|---|---|---|
| `lean_selfcheck_off` | `off`（`toolchain.lean_enabled=false`） | 用户关掉了这条路：改走逐行审阅，别去查环境 |
| `lean_selfcheck_unusable` | `unusable`（找不到 / 版本不符 / 正样例不过 / 反控没失败） | 查过了：这台机器上的 lean 不构成检查器（去查 `AGENTFLOW_LEAN_BIN`） |
| `lean_selfcheck_unknown` | `unknown`（没查成） | 我们没查成：既不是通过、也不是不可用 |

三档都不是 `failed`：`failed` 是"检查器说话了、说不行"；这三档是"检查器没说话"。

## 三态（本项目最贵的一条纪律）

`THREE_STATES` 是 L 的结论面：`verified`（检查器说了通过）/ `failed`（检查器说了不通过）
/ `unknown`（没查成）。`unknown` 永远带有原因，且永远不许被折进另外两档 ——
判据见 `tests/test_l_formalizes_what_b_says.py` 与 E 那一侧的 `FORMAL_REASONS`。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from ..agent_e._support import (  # noqa: F401 - 别名再导出：L 与 E 共用同一份实现
    FORMAL_REASONS,
    _FORMAL_REASON_BY_TOOL_REASON,
    _relpath,
    ExperimentError,
)

#: E 那一侧的收口表也再导出一份（L 的 `check_formal` 直接用它，不另抄一份）。
FORMAL_REASON_BY_TOOL_REASON = _FORMAL_REASON_BY_TOOL_REASON

#: L 的结论三态（顺序即严重性：verified 最强，unknown 最弱）。
THREE_STATES: tuple[str, ...] = ("verified", "failed", "unknown")

#: "检查器说了不通过"那一族理由（这几个才是 `failed`）。
FAILED_REASONS: tuple[str, ...] = (
    "compile_error",
    "uses_sorry",
    "extra_axioms",
    "decl_mismatch",
)

#: L 自己追加的三个理由码（自检不是 usable 时用；三个都要能说出"该去改哪儿"）。
SELFCHECK_REASONS: dict[str, str] = {
    "off": "lean_selfcheck_off",
    "unusable": "lean_selfcheck_unusable",
    "unknown": "lean_selfcheck_unknown",
}

#: `record`（把一次形式化检查登记成一行 `experiments`）自己的受控拒绝理由。
#:
#: 为什么要单独一组：`record` 的四条拒绝都不是"检查器说了什么"，而是"这次登记
#: 不成立" —— 命题不在台账里、命题没有正文、产物不是工作区里的 `.lean`、
#: 调用方口述的读数与刚才现跑出来的那一份对不上。把它们折进 `unknown` 会让
#: "登记被拒"与"没查成"变成同一句话（三态纪律在这里的落点：拒绝是第三态位）。
#:
#: 2026-10-22 晚追加三条（业主裁定「要指明对哪个路径做了形式化验证」）：
#: `proof_path_not_found`（号不在册）/ `proof_path_unspecified`（多路径未给号）/
#: `proof_path_artifact_mismatch`（产物文件名与号对不上：`#p2` 的产物必须是
#: `..._p2.lean`，否则登记进去的就是另一条路径的源码）/ `bad_path_source`
#: （`path_source` 不在受控三值里）。
RECORD_REASONS: tuple[str, ...] = (
    "statement_not_found",
    "statement_body_empty",
    "reading_mismatch",
    "artifact_not_lean",
    "proof_path_not_found",
    "proof_path_unspecified",
    "proof_path_artifact_mismatch",
    "bad_path_source",
)

#: L 的受控理由表 = E 的那张表 + 自检三档 + `record` 四条（追加，不改 E 的取值）。
#:
#: 为什么用"追加"而不是"复制一份再改"：复制一份之后，E 那边新增一个状态时
#: 这里不会跟着变，而"两份词表不一致"没有任何地方会报（FC-03）。
FORMAL_REASONS_L: tuple[str, ...] = (tuple(FORMAL_REASONS)
                                     + tuple(SELFCHECK_REASONS.values())
                                     + RECORD_REASONS)

assert set(FORMAL_REASONS) <= set(FORMAL_REASONS_L), (
    "L 的理由表必须包含 E 的全部取值 —— 否则同一个桥接层状态在两侧有两个名字"
)

#: 声明名的合法形态：Lean 标识符的一个保守子集（也当文件名用）。
#:
#: 为什么自己判而不交给 Lean：这个名字同时是盘上的文件名，`../` 之类的输入
#: 必须在写盘之前被拒（写盘之后才由 Lean 报错，那条路径已经越界了）。
DECLARATION_NAME_RX = re.compile(r"^[A-Za-z_][A-Za-z0-9_']{0,63}$")

#: 落到工作区的哪一个目录（E 的 policy 写的是 `code/lean/`；L 用自己的目录，
#: 理由是"谁的产物在哪儿"要一眼看得出来，而两个角色写同一个目录会让
#: "这个 .lean 是谁写的"只能靠猜）。
#:
#: 2026-10-25（审计 G/H/V/L 第 4 条）：这一格是 `lean_file` 那一格三个落点里
#: 「源码真实在哪」的唯一真身 —— `papermapping.LEAN_ARTIFACT_DIRS` 把 `code/formal`
#: 加进扫描面，而 `lean_file` 收的就是这个前缀的项目根相对路径
#: （`code/formal/<声明名>.lean`）。此前 G 的提示词说"论文包内相对路径"、扫描面只有
#: 包内 + `out/formal`、而全仓没有一步把这里拷进包 ⇒ 这一份源码填不进对应表。
FORMAL_DIR = "code/formal"

#: 一条形式化实验行的机器可读键：`experiments.claim_key` 取这个形态。
#:
#: 为什么不是人给的任意串：`formal.record` 的绑定对象是台账里的一条命题
#: （`statements` 那一行），所以"这条检查器输出管的是哪个命题"这件事必须由
#: 命题号现算 —— 让调用方自己填一个 key 就等于允许它把 A 的输出贴到 B 上
#: （`schema.Experiment` 的硬约束 2b 挡的正是那个，但它只能比"两个 key 相等"，
#: 比不出"这个 key 是不是这条命题的"）。
STATEMENT_CLAIM_KEY_PREFIX = "stmt:"


def one_line(text: Any, limit: int = 400) -> str:
    """把一个可能多行的说明压成一行（"同一条失败只报一行"的落点）。

    为什么必须压：自检的 `problems` 是一个列表，原样塞进结论就会让一次失败在
    下游展开成十几行 —— 而模型的处置动作由第一行决定，后面的行只是噪音
    （真机读数：8 次 `check_formal` 全撞在同一件事上，因为理由那一段太长，
    模型每次都只读到开头）。
    """
    flat = " ".join(str(text or "").split())
    return flat[:limit]


def sha256_of_bytes(payload: bytes) -> str:
    """盘上那份源码的 sha256（十六进制）。"""
    return hashlib.sha256(payload).hexdigest()


def normalize_source(source: str) -> str:
    """源码的行尾统一成 `\\n`（Windows 上的 `\\r\\n` 会让同一份源码算出两个哈希）。"""
    return str(source).replace("\r\n", "\n").replace("\r", "\n")


__all__ = [
    "DECLARATION_NAME_RX",
    "FAILED_REASONS",
    "FORMAL_DIR",
    "FORMAL_REASONS",
    "FORMAL_REASONS_L",
    "FORMAL_REASON_BY_TOOL_REASON",
    "RECORD_REASONS",
    "SELFCHECK_REASONS",
    "STATEMENT_CLAIM_KEY_PREFIX",
    "THREE_STATES",
    "ExperimentError",
    "normalize_source",
    "one_line",
    "sha256_of_bytes",
]

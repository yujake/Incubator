"""端到端一条命令：给一个主题、一个美元上限，产出一份可复核的完整运行记录。

## 为什么要有它

本轮之前，仓库里能跑的东西是"分段的"：`modelgw` 能调模型、`tokenmeter` 能记账，
但没有任何一条命令把"配 key → 调模型 → 记账 → 熔断 → 落产物"串起来。
分段能跑与端到端能跑是两件事：前者永远发现不了"记账没接上""预算拦不住"
"清单里写着一份配置、实际用的是另一份"这类缺口，因为缺口恰恰在段与段之间。

`run_topic` 就是那一条：一次调用一条账、一次运行六件产物、一个退出码。
不需要 key 也能跑（会明确以退出码 2 + 清单里的 `no_key` 结束）。

## 流程：先检索、再取全文、再作答、再逐字回验

1. `evidence.retrieve` 按主题检索（多源：OpenAlex + Crossref），拿到带 provenance 的来源
   （查到什么、用什么查询、什么时候，全写进 `evidence.json`）；
2. `evidence.acquire_fulltext`（`fulltext=True` 时）逐条拿开放全文并六态化记账
   （`ok` / `no_pdf` / `download_failed` / `no_text_layer` / `extract_failed` /
   `not_configured`），拿到全文的来源会被逐字回验用到全文级；
3. 把检索到的摘要拼进 prompt，并要求模型"只用给定材料作答、每条结论附一条
   逐字复制的原文引文"；
4. `claims.split_claims` 把每一条成功答复拆成原子断言（先按模型写的 `||`
   切，再按列表标记，最后按句末标点兜底；三态 `parsed` / `no_claims` /
   `unparsable`，超上限的截断数逐条写明），`claims.ledger_rows` 把拆分结果与
   判决合成台账；
5. `evidence.verify_claims` 逐条回验：引文在来源文本里逐字存在才算 `verified`，
   否则落 `not_found`（编造的引文只能落在这一档）；每条通过都带
   `level`（`abstract` / `fulltext`）与 `locator`（字符偏移或页号）；
6. 落产物：`evidence.json` 记检索三态、逐源状态与全文获取六态，`claims.json` 是
   带判决与级别的原子断言台账（外加 `claims_ledger` 段说明怎么拆的），
   `report.md` 里有一段人读的证据摘要。

检索没查成（`retrieval_failed` / `not_configured`）时不调模型：这次的产物本该由
"材料 + 逐字引文"支撑，材料没拿到还去问模型，只会把一堆无法回验的结论印成报告。

## 六件产物（缺任何一件都算没跑成）

| 文件 | 它回答的问题 |
|---|---|
| `run-manifest.json` | 这次到底做了什么（配置、每次调用、总额、退出原因、未接线清单） |
| `model-transcript.jsonl` | 模型逐次回了什么（每行一条 `reply.to_dict()`） |
| `evidence.json` | 检索到哪些来源、每条来自哪个库/什么查询/什么时候、逐源状态与全文获取六态 |
| `claims.json` | 原子断言台账（每条的断言、引文、判决、级别、命中位置与来源，外加 `claims_ledger` 段：拆出多少条、按什么依据拆、截断多少条）；`--lean` 时另有每段 Lean 片段的检查结论与实际到达的证据等级 |
| `cost.json` | 花了多少。必须与 `usage_ledger` 的汇总一致 |
| `report.md` | 人读的报告，含证据段与 unknowns 段 |

`claims.json` 里的每一条都带一个判决：`verdict` 只取
`verified` / `not_found` / `known_unverifiable` / `unknown` 四值。
"没查成"（`unknown`）与"查了、找不到"（`not_found`）必须分得开 ——
把前者读成后者，会把一次基础设施故障记成一次学术不端。

没有引文的断言不会被丢弃：它们以 `known_unverifiable` 落在台账里。
丢弃会让"我们没验这一条"看起来像"这条断言不存在"，而台账的条数正是
"这篇产出有多少条可回验的原子断言"这个问题的答案。

`claims_ledger` 的摘牌判据只有一条：这一次真的拆过（`split_claims` 给了
`parsed`）。没拆成（`no_claims` / `unparsable`，或压根没成功的模型答复）时
它会被加回未接线清单并写明是哪一种没拆成 —— "拆过了、答复里没有断言"
与"我们没拆成"是两句不同的话。

## 退出三态（与 `lint_rules` / `noai_gate` 同一口径）

- 0 = 成功产出（走到 `max_calls` 为止，且没有任何一次调用失败）；
- 1 = 查过了、确实失败（认证失败、预算耗尽）——预算耗尽一律是 1，
  哪怕前面已经有几次成功：跑飞被熔断这件事必须能从退出码看见；
- 2 = 没查成（`no_key` / 检索没查成 / 超时 / 网络 / 未接线）。

把 2 读成 1，会让"key 没配好"看起来像"模型答错了"；把 2 读成 0，
就是本项目反复记过的那种最贵的错误。检索失败也走 2：本质是"这次没查成"，
而不是"查过了、结论是错的" —— 本次连模型都没调。

## 熔断是 fail-closed 的：先查钱，再花钱

每一轮调用之前判"本次运行已花是否已达 budget_usd"，达了就停并落 `budget_exhausted`。
顺序不能反：先调用后检查意味着最后一次调用可以任意超预算，而"预算"这个词
在那一次上就变成了"建议"。

口径是"这一次运行"（`G-4`），不是整本台账的累计值：`budget_usd` 是调用方给
这一次运行的额度，而 `usage_ledger` 属于工作区、跨运行累计（见 `run_topic` 的
docstring）。改前用的是后者，于是同一工作区里第二次运行会被第一次的花销提前熔断：
`calls=0` 而 `spent_usd` 报的是上一次的钱。两个数字现在都在产物里，且各自标注
口径（`cost.json` 的 `spent_usd_this_run` 与 `usage_ledger.usd`）。

## 回验未通过不改退出码（刻意的取舍）

一条断言被判 `not_found` 说明它没有来源支持，但这不改退出码：
退出码说的是"这次运行有没有做成"，而不是"结论对不对"。
把两者混起来，0 与 1 就再也说不清 —— 想表达"证据不足"的地方是
`claims.json` 的 `verdict`、报告的证据段与清单里的 unknowns，
所以那三处必须说清楚。

## 测试接缝只有七个：transport / search_fn / quote_fn / fetch_fn / extract_fn / lean_run_fn / claims_parse_fn

每个动作各一个：生产为 `None`（分别走 `urllib` / 禁改区里的 `providers` 与
`quoteverify` / `fetch` / `extract` / 探测到的 Lean 后端 / 纯启发式拆分），测试注入假实现
（`lean_run_fn` 见 `formalgw.check_lean` 的接缝说明；`claims_parse_fn` 是
`claims.split_claims` 的"让模型协助拆分"接缝，注入与否都记进
`claims_ledger.parse_fn_used` 与拆分指纹）。刻意不加 `AGENTFLOW_MODEL_FAKE`
之类的环境变量后门：那种开关一旦存在，就会在生产上被误设成"假装调过模型"，
而产物里的每一行看起来都还是一样可信。

`from typing import Any, Mapping` 之外不再 import 别的东西：拆分层的类型来自
`claims` 模块，这里只透传。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import schema as S
from . import claims as claims_mod
from .evidence import (
    CHECKED_STATUSES,
    acquire_fulltext,
    materials_block,
    not_attempted,
    parse_claims,
    retrieve,
    verify_claims,
)
from .modelcost import charge_reply, idempotency_key, price_of
from .modelgw import (
    ModelGateway,
    ModelReply,
    ModelSpec,
    Transport,
    spec_from_env,
)
# `_reply_failure` 是"失败/没查成结局"的唯一构造点（`modelgw.py` 里逐字写着
# "防止 ok 与 error_kind 不一致"）。`G-7` 要在调用点把"网关抛出来的异常"
# 折成三态结局，而折出来的那条结局必须走同一个构造点 —— 在这里自己 new 一个
# `ModelReply(ok=False, ...)` 就等于开了第二个构造点，两处迟早不一致。
from .modelgw import _reply_failure
from .formalgw import check_lean, lean_snippets
from .tokenmeter import TokenMeter

__all__ = ["ARTIFACTS", "NOT_WIRED_ITEMS", "prompt_for", "run_topic", "selftest"]

#: 一次运行必须产出的六件东西。为什么写成常量：它是判据（缺一件就是没跑成），
#: 而写在两处（这里与测试里）的判据早晚会漂移。
ARTIFACTS: tuple[str, ...] = (
    "run-manifest.json",
    "model-transcript.jsonl",
    "evidence.json",
    "claims.json",
    "cost.json",
    "report.md",
)

#: 本轮确定没有接线的东西。为什么要显式列出来：不写下来，
#: 读者会把"报告里没有检索结果"读成"检索了、什么都没找到" ——
#: 那正是"把没做当成做了"的最贵形态。
#:
#: 这个元组是清单而不是某次运行的结论：`run_topic` 会在检索真的跑过
#: （`evidence.CHECKED_STATUSES`）时把 `retrieval` 与 `quote_verify` 摘掉，
#: 没跑成时则据实改写它们的理由（"没接进本流程"与"接了、这次没查成"不是一句话）。
#:
#: `claims_ledger` 同样按"这次真的做了没有"摘牌：`claims.split_claims` 已经接进
#: `run_topic`，所以拆出 `parsed` 时这一项被摘掉；答复拆成 `no_claims` /
#: `unparsable`（或压根没有成功的模型答复）时它留在清单里，理由改成拆分层的
#: 实际结论 —— "拆过了、答复里没有断言"与"我们没拆成"是两句不同的话，
#: 而常量里那句写的是后者（fail-closed：默认状态是"没拆成"）。
NOT_WIRED_ITEMS: tuple[tuple[str, str], ...] = (
    ("retrieval", "文献检索（providers/A）没有接进本流程 ⇒ 本次没有任何外部文献证据"),
    ("fulltext", "开放全文获取（fetch/extract）没有接进本流程 ⇒ "
                 "本次的逐字回验最多只能到达摘要级，不是全文级"),
    ("lean", "证明检查器（Lean/Coq/Isabelle）没有接线 ⇒ 本次没有任何形式化验证证据"),
    ("claims_ledger", "把模型答复拆成完整断言台账的那一层本次没有拆成 ⇒ "
                      "claims.json 里那份台账不覆盖这次答复的结论"
                      "（拆分层已接进 run_topic，没拆成时这一项会带上具体理由）"),
    ("quote_verify", "逐字引文回验没有接进本流程 ⇒ 本次的模型答复没有任何引文级证据"),
)

#: prompt 模板的版本名。写进清单，因为"报告是哪个版本问出来的"决定它能不能与
#: 别的报告比较 —— 不记版本的产物在两周后就无法解释。
#:
#: `v1`      —— 只要实质结论（三句以内），不要求形式化；
#: `v2-lean` —— 在 `v1` 的基础上额外要求一个自包含的 Lean 4 代码块。
#: 为什么需要有这一版：`--lean` 的 proof 级证据只能来自模型答复里的 ```lean 代码块
#: （`formalgw._FENCE`，约定见 `runflow.py` 里 `lean_snippets` 那段），而 `v1` 从不要求它
#: ⇒ 用 `v1` + `--lean` 跑出来的永远是"开启=是、跑过=否、没有可检查的代码"。
PROMPT_VERSIONS: tuple[str, ...] = ("v1", "v2-lean")

#: 本流程里"作答"这一步的用途归口（`schema.USAGE_SCOPES` 之一）。
#:
#: 为什么写成常量而不是在调用点写字符串字面量：G-20 的纪律是"每一次 modelgw 调用
#: 都带一个显式 scope"，而显式不等于随便写一个 —— 它要能被读的人一眼看出
#: "这一步是整条流程的哪一段"。写成常量之后，改它只有一处，而
#: `cost.json` 的 `by_scope` 会立刻反映出来。
SCOPE_ANSWER = "reason"

#: 一次 `agentflow run` 在 `tasks` 表里的动作名。占位行（`run_topic` 里取号那一段）
#: 与收工改写（`_settle_run_task`）两处必须用同一个值 —— 它同时是"这一行是谁写的"
#: 这条审计线索的一部分，分成两处写就会漂移。
TASK_RUN_ACTION = "run"


def prompt_for(topic: str, version: str = "v1") -> str:
    """按版本号造 prompt。未知版本号不是回退到默认，而是显式拒绝。

    为什么：静默回退会让清单里的 `prompt_version` 与真实用的 prompt 不一致 ——
    那是一份说谎的运行记录，比没有记录更坏。
    """
    if version not in PROMPT_VERSIONS:
        raise ValueError(f"未知 prompt 版本 {version!r}（已知 {PROMPT_VERSIONS}）")
    if version == "v2-lean":
        return (
            f"主题：{topic}\n\n"
            "请按两段作答。\n"
            "第一段：只陈述你确知的实质结论，最多三句，不要罗列参考文献，"
            "无法确知的部分明确写“不确定”。\n"
            "第二段：给出一个 ```lean4 代码块，把第一段里一条可机械检查的断言"
            "写成最小形式化。硬要求：① 自包含，只用 Lean 4 核心语法，"
            "不要 import Mathlib 或任何第三方库；② 只用核心策略"
            "（`rfl` / `decide` / `simp` / `exact` / `norm_num` 之一）；"
            "③ 代码块必须能被 `lean` 单独编译通过，所以宁可把断言化成具体的有限计算，"
            "不要写需要大量库引理的抽象命题；④ 若你无法给出能通过的代码块，"
            "就明确写“无法给出可检查的形式化”，不要写通不过的代码。"
        )
    return (
        f"主题：{topic}\n\n"
        "请只陈述你确知的实质结论，最多三句，不要罗列参考文献，"
        "无法确知的部分明确写“不确定”。"
    )


SYSTEM_PROMPT = (
    "你是一个严谨的研究助理。只说你确知的；不确定就说不确定；不要编造引用。"
)


@dataclass
class CallRecord:
    """一次调用的全部事实：结局、记账、以及它在预算里的位置。

    为什么要把它单独成一个对象：清单、transcript、cost.json 三件产物
    说的必须是同一次调用的同一份事实。各写各的（例如清单里记一次、账里记另一次）
    正是"两处各算一遍但愿它们相等"的形态。
    """

    index: int
    reply: ModelReply
    charge: dict
    usd: float
    spent_after_usd: float

    def to_dict(self) -> dict[str, Any]:
        """落清单用的扁平结构（reply 走它自己的 `to_dict()`，不另抄一份字段）。"""
        return {
            "call_index": self.index,
            "idempotency_key": idempotency_key(self.idem_scope or self.task_id,
                                              self.index),
            "reply": self.reply.to_dict(),
            "charge": dict(self.charge),
            "usd": self.usd,
            "spent_after_usd": self.spent_after_usd,
        }

    #: 由 `run_topic` 在构造后设置：同一次运行的所有调用共享一个 task_id。
    task_id: str = ""

    #: 幂等键的命名空间（`G-2` 的运行标识）。与 `task_id` 分开的理由：
    #: `task_id` 每一跑都必须新（`t-NNNN` 契约），而幂等键问的是"是不是同一次
    #: 逻辑运行的同一笔"，那个身份由 `_run_scope()` 按「主题摘要 + `now`」算。
    #: `R5-F5` 之后生产形态（不给 `now`）还会带一个每次调用都不同的随机后缀 ——
    #: 于是"同一秒内两次真运行"不再被折叠成一次（那是 `G-2` 的残余缺陷），
    #: 而显式传同一个 `now` 仍然是"同一次逻辑运行"（测试与复现靠它）。
    idem_scope: str = ""


def _write_json(path: Path, doc: Any) -> None:
    """写一件 JSON 产物（utf-8、不转义中文、末尾换行便于 diff）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    """写一件文本产物。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _budget_left(budget_usd: float, spent_usd: float) -> float:
    """还剩多少预算（按 6 位小数收口，与账本精度一致，避免浮点尾巴）。"""
    return round(float(budget_usd) - float(spent_usd), 6)


def _spent_this_run(meter: TokenMeter, task_id: str) -> float:
    """本次运行已经花掉多少（`G-4` / `F5-FOUND-1`）。

    ## 口径：按 `task_id` 过滤账本，不是工作区增量

    账本里每一行都带 `task_id`（这次运行所有调用的共同挂点），所以"本次运行
    已经花掉多少"这个问题有精确解：把该 `task_id` 的那些行加起来
    （`TokenMeter.usd_for` 就是这件事）。

    改前用的是工作区增量：开跑时取一次 `TokenMeter.spent()`（整本台账求和）
    当基线，之后判 `spent() - baseline`。那个近似只在"同一个工作区里两次运行
    不可能重叠"时等价于本次花销 —— 而它从未被写下来过，只是成立过。
    并发修通（`R5-AN-1`）之后它就不成立了：另一个进程在我取基线之后入账，
    它的钱会落进我的差额里。实测（两真进程、A 的传输层睡 3s）：
    A 的 `spent_usd_this_run=6e-06`（正确），B 的 `spent_usd_this_run=1.2e-05`
    （= 自己那一笔 6e-06 + A 在我基线之后提交的 6e-06），而 B 自己的
    `calls_usd` 是 6e-06 ⇒ B 那一跑被判"账本对不上"（其实它一分钱都没漏）。
    同一个位还喂预算熔断：并发下别人的花销会算进自己的额度、可能提前熔断。

    为什么这是"照 intended semantics 修"而不是"改口径"：基线的存在本身就说明
    意图是"本次运行的花销"；工作区增量只是它在不可重叠前提下的一种实现。
    `G-4` 的 docstring（`run_topic`）已按新口径逐字改写。

    为什么把这一步做成函数而不是在循环里内联：口径必须是一处，且负控要能
    "改回工作区增量"看到读数变坏（负控变体 `V8-found1-workspace-delta`）。
    """
    return round(float(meter.usd_for(task_id)), 6)


def _run_entry_count(meter: TokenMeter, task_id: str) -> int:
    """本次运行在账本里落了几行（口径与 `_spent_this_run` 同：按 `task_id` 过滤）。

    为什么必须与花销同一个口径：产物里 `entries_this_run` 与
    `spent_usd_this_run` 并排给出，两个数各说一件事（"花了几行账"与"花了多少钱"）
    —— 一个按本次运行过滤、另一个按工作区增量算，读者会把它们的差当成事实。
    """
    rows = meter.store.rows("usage_ledger")
    return sum(1 for r in rows if str(r.get("task_id")) == str(task_id))


def _is_exhausted(budget_usd: float, spent_usd: float) -> bool:
    """已花是否已达预算。

    判据取 `>=` 而不是 `>`：预算为 0 时必须是"一次都不许调"，
    而 `>` 会让 0 预算放行第一次调用 —— 那是把"预算为零"读成"预算不限"。
    """
    return float(spent_usd) >= float(budget_usd)


def _exit_code_for(reason: str, *, successes: int) -> int:
    """把"为什么停下"映射成退出码（三态的唯一映射点）。

    - `budget_exhausted` ⇒ 1（钱是硬约束，停在这里必须能从退出码看见，
      哪怕前面已经有几次成功了 —— 否则"跑飞被熔断"在脚本里看起来与成功一样）；
    - `no_key` / `retrieval_failed` / `retrieval_not_configured` ⇒ 2
      （没查成，与"查了失败"分处两档）。检索失败必须显式写在这里：
      它不在 `modelgw.NOT_CHECKED` 里（那是模型结局的词表），
      漏掉的话"这次根本没查成"会掉进默认分支变成 1。
    - 有成功的调用 ⇒ 0（这次运行确实产出了东西，哪怕最后一轮是超时）；
    - 其余：`NOT_CHECKED` 里的结局 ⇒ 2，别的 ⇒ 1。
    """
    if reason == "budget_exhausted":
        return 1
    if reason in ("no_key", "retrieval_failed", "retrieval_not_configured"):
        return 2
    if successes > 0:
        return 0
    from .modelgw import NOT_CHECKED

    return 2 if reason in NOT_CHECKED else 1


def _complete_or_not_checked(gw: ModelGateway, prompt: str, *, scope: str,
                             system: str = SYSTEM_PROMPT,
                             model: str = "") -> ModelReply:
    """调一次模型，并把"网关自己抛出来了"折回三态里的"没查成"（`G-7`）。

    ## 缺陷（2026-09-26 全面体检 · 子代理 G 实测）

    `ModelGateway.complete` 的 docstring 承诺"返回三态结局，从不抛异常"，
    而 `modelgw._once` 只捕 `TimeoutError` / `ConnectionError`。实测
    （`temp/auditG-probe1.txt` P6 段）：传输层抛 `ValueError` ⇒ `complete` 原样抛出；
    `urllib_transport` 把 `urllib.request.Request(...)` 建在 `try` 之外，于是
    `AGENTFLOW_MODEL_BASE_URL` 写错时抛 `ValueError: unknown url type`。
    调用点没有 `try` ⇒ 一个配置错误让整条 run 崩在这一次调用上：六件产物一件都不写、
    账本一行都没有、预算熔断完全不生效，而"没查成"与"代码崩了"在下游无法区分。

    ## 这里堵的是调用点（口径二），不是网关（口径一）

    折成的结局是 `error_kind="unknown"`：它在 `modelgw.NOT_CHECKED` 里，
    因此这次运行按"没查成"记（退出码 2），而不是被记成"查了、结论是失败"。
    `G-7` 的口径一（在 `complete` 里套一层 `except Exception`，并把 `urllib_transport`
    里 `Request(...)` 的构造挪进 `try`）落点在 `modelgw.py`，不在本文件 ——
    所以这里只保证本调用点不崩栈，别的调用方仍然会崩，这一点如实写在这里，
    不假装整条路径已经被彻底修好。两句都成立时口径一才是根治，本函数可以原样留着：
    它是"网关违约时的最后一道兜底"，而不是"网关应该抛"的许可。
    """
    try:
        return gw.complete(prompt, system=system, scope=scope)
    except Exception as exc:  # noqa: BLE001 —— 见 docstring：任何异常都折成『没查成』
        return _reply_failure(
            "unknown",
            f"网关抛出了 {type(exc).__name__}：{exc}"
            "（`ModelGateway.complete` 承诺从不抛异常，`G-7` 登记了这个缺口；"
            "已按『没查成』处置，但异常本身仍需在 modelgw 侧收口）",
            model=model, scope=scope,
        )


def _ledger_view(meter: TokenMeter) -> dict[str, Any]:
    """账本汇总 + 按角色归口 + 按用途归口（`cost.json` 必须与它一致，所以只算一次）。

    `by_scope` 是 G-20 的产物：没有它，"搜索/抽取/审校各花了多少"这个问题
    在产物里没有位置可放。它每一档都在（含零值），所以"某档归零"是可见的。
    """
    spent = meter.spent()
    return {
        "entries": int(spent["entries"]),
        "tokens": int(spent["tokens"]),
        "usd": round(float(spent["usd"]), 6),
        "attempts": int(spent["attempts"]),
        "by_role": meter.by_role(),
        "by_scope": meter.by_scope(),
        "retry_overhead": meter.retry_overhead(),
    }


def _new_task_row(*, task_id: str, topic: str, status: str, outcome: str | None,
                  detail: str, started_at: str, ended_at: str | None, tokens: int,
                  usd: float, error: str = "") -> dict:
    """一次 `agentflow run` 的 `tasks` 行的唯一构造点（`G-3`）。

    为什么把构造与写入分开、但构造只有一份：这一行有两个写入点 ——
    开跑时的占位行（`run_topic` 里取号那一段，`status="running"`）与收工时
    的终态行（`_settle_run_task`）。两处各拼一份 dict 的话，"这次运行是哪一次"
    （`role` / `action` / `called_by` / `depth` / `input_key`）与
    "哪些字段该留空"（`artifacts`）这两组决定就会漂移 ——
    而漂移的表现是同一张表里两种形状的行，没有任何判据会响。

    `task_id` 是返回 dict 的第一个键：快照按 dict 的键顺序序列化，而
    `rebuild()` 用 `Task.to_dict()`（dataclass 字段顺序，`task_id` 在最前）
    重建行。第一次落盘时把它排在后面，`rebuild()` 之后键顺序会变，
    于是 `tasks.json` 逐字节不一致（I-9 直接失败）—— 数据没错，但
    "可重建"这条承诺破了。同一纪律写在 `conductor._write_new_row` 的 docstring 里。

    `I-9` 还有更强的一半（本批实测踩到）：返回的 dict 必须是 `Task.to_dict()`，
    而不是"我手动列的字段"。手工列全十八个字段是不可能长期守住的承诺 ——
    第一版只列了十五个（少了 `parent_task_id` / `refusal_reason` / `error`），
    盘上的 `tasks.json` 于是缺三列，而 `rebuild()` 从 dataclass 重建会补上它们
    ⇒ 前后 1091 与 1172 字节、逐字节不一致，而数据一个字段都没错
    （读数 `temp/fix6_f5-shape.txt`）。让 dataclass 自己产出之后，
    这条承诺由构造保证。
    """
    row = S.Task(
        task_id=task_id,
        role="M",
        action=TASK_RUN_ACTION,
        called_by="cli",
        # `Task.validate` 要求 `depth >= 1`（`depth` 从 1 开始 = 主控发起）。
        # 这一行是最外层的那一次召唤（CLI 让主控跑一次），所以是 1。
        depth=1,
        input_key=topic[:120],
        status=status,
        outcome=outcome,
        detail=detail,
        # `FINAL-R5-01`（最后一次集中审查抓到的）：这一行改前从不设 `error`，
        # 而 `schema.Task.validate` 要求 `status="failed"` 必须带非空 `error`
        # 且 `outcome="failed"`。于是 `_settle_run_task` 里那次 validate 抛异常、
        # `written=False`，占位行永远停在 `running` —— 受害面正是
        # `modelgw.MODEL_ERROR_KINDS` 里不在 `NOT_CHECKED` 的那三个码
        # （`auth_failed` / `rate_limited` / `bad_response`）。
        # 为什么把参数默认成空串而不是 None：调用方（开跑时的占位行）不需要知道
        # 这个字段；只有终态是 failed 的那条路径才必须给。
        error=(error or None),
        started_at=started_at,
        ended_at=ended_at,
        tokens=int(tokens),
        usd=round(float(usd), 6),
        # `R5-F3`（第一次重审实测的修法）：`tasks.artifacts` 的契约是
        # `verify.py` 里那一条 —— 每一项形如 `"<表名>:<行 id>"`，指向
        # 库里真的存在的一行。旧版把六个文件名塞进这个字段，
        # 于是每跑一次 `agentflow run` 都新增 6 条
        # `unknown_artifact_kind` warning（测试只断言 `errors`，所以完全不可见）。
        # 一次 `run` 产出的六件东西是磁盘文件，不是表里的行 ——
        # 它不该占用这个字段。所以这里留空，把那六个名字放进 `detail`
        # （人读的说明），并把"留空"这件事写清楚，免得读的人以为是漏了。
        artifacts=[],
        # `inputs` 与 `artifacts` 是同一条纪律：声明为集合的字段必须升序去重
        # （`Task.validate` 实测会拒"未升序"）。所以这里也过 `sorted_unique`。
        inputs=S.sorted_unique([
            f"topic={topic}",
            "budget_usd=<见 cost.json>",
            "prompt_version=<见 run-manifest.json>",
        ]),
    )
    return row.to_dict()


def _settle_run_task(store: Any, *, task_id: str, topic: str, reason: str, exit_code: int,
                     records: Sequence[CallRecord],
                     meter: TokenMeter, started_at: str, stamp: str) -> dict:
    """把这次 `run_topic` 的 `tasks` 行改写成终态（`G-3` / `R5-AN-1`）。

    ## 为什么必须有这一行（而不是把 usage 行的 task_id 置 None）

    `usage_ledger.task_id` 是审计的挂点：`verify` 有一条 `dangling_usage_task` 检查
    （账本行指向的任务不在 `tasks` 表里）。`run_topic` 一直是给了 task_id 但没建任务行，
    于是每跑一次 `agentflow run` 就让全库审计多两条 error 级发现 ——
    而 error 永远红就等于 error 没有区分力。

    另一个口径（把 task_id 置 None）改动更小，但它把"这次花了多少"从审计面里摘出去：
    账本会干净，事实会少一份。这里选补任务行。

    ## 它写的是"改写"，不是"新写"（`R5-AN-1` 之后的口径）

    这一行在开跑时就已经由取号那一段以 `status="running"` 落库了（号必须当场
    占住，否则并发的第二次运行会拿到同一个 `t-NNNN`）。本函数按同一个
    `task_id` 整行改写它 —— 所以"每个 start 恰好一个 end"这条口径是由
    "先占号、后收工"两步共同保证的，而不是由本函数单独保证。
    本函数仍然不依赖那一行存在：它对同一个 `task_id` 做整行 upsert，占位行丢了也能补写。

    ## 六条口径与 `conductor._charge_and_settle` 对齐

    - `role="M"`：这次运行是主控发起的（`agentflow run` 就是主控自己跑一遍）；
    - `status`：`done` / `failed`（可被取消的调用方还会拿到 `cancelled`）——
      与 `exit_code` 的三态不是同一件事，所以按 `reason` 映射而不是按退出码。
      `R5-F4`：这条通路上可达的只有 `done`（跑完了）与 `failed`（模型侧
      查过了、确实不行，例如 `auth_failed` / `rate_limited` / `bad_response`）；
      `cancelled` 只有将来接进取消面的调用方才拿得到。逐条依据见
      `_run_task_verdict` 的 docstring 与 `RUN_TOPIC_REASON_LITERALS`；
    - `outcome`：`ok` / `no_result`（跑完了但没拿到模型结论）/ `failed`；
    - `tokens` / `usd`：用 `meter.tokens_for(task_id)` / `usd_for(task_id)`
      —— 与账本同一条口径（同一个 task_id），不是第二份计算；
    - `artifacts`：留空。那六件产物是磁盘文件（不是表里的行），所以不占这个
      字段（它的契约是 `"<表名>:<行 id>"`）；六个名字写在 `detail` 里。
      `R5-AN-5`：这句 docstring 此前把 `artifacts` 写成"本运行承诺的
      六件产物"，与同一屏里的实现（`artifacts=[]`）互相矛盾 —— 那是 `R5-F3`
      已经改掉的旧形态，照着旧文写回去会立刻新增 6 条
      `unknown_artifact_kind` warning；
      `inputs`：主题与预算（同样只写形状，具体数字在产物里）；
    - `detail`：写清"这一行是谁写的、为什么"（读台账的人不该去猜）。
    - `error`：只在 `status="failed"` 时非空 —— `schema.Task.validate` 的硬要求
      （`FINAL-R5-01`：改前这里不给 `error`，于是失败那三个码的行写不进去，
      占位行永远停在 `running`；这条不是措辞问题，是台账缺行）。

    ## 三态纪律

    写失败不吞：返回值里 `written=False` 与 `error`，而 `run_topic` 会把它落进
    `run-manifest.json` 的 `task_row` 段、并往 `unknowns` 加一行（`R5-F6`：
    这句 docstring 此前写的是"让这一项在返回值里可见"，而那个返回值从未被读过
    —— 写失败恰恰意味着那一行 `tasks` 不存在，于是连 `detail` 都留不下来，
    产物与退出码一字不变，消费者完全看不出来）。
    退出码仍然不改 —— 产物已经落盘了，而那才是这次运行的结果；
    账本挂点缺失是审计面的问题，把它折叠成"运行失败"会让读者以为结论不可用。

    `R5-AN-5` 的另一半：本函数此前还收着 `out` 与 `ledger` 两个形参，
    而函数体里一次都没用过它们（AST 读数见 `temp/reaudit6-R5-p4.txt`）。
    形参也是接口面 —— 列着不用的形参，会让读 docstring 的人以为
    "产物目录与账本汇总参与了这一行的构造"。它们已经删掉：
    产物目录由调用方自己用，账本汇总由 `meter` 现算（`tokens_for` / `usd_for`），
    本函数不需要第二份输入。
    """
    tokens = int(meter.tokens_for(task_id))
    usd = round(float(meter.usd_for(task_id)), 6)
    ok_calls = sum(1 for r in records if r.reply.ok)
    status, outcome = _run_task_verdict(reason=reason, exit_code=exit_code)
    # `FINAL-R5-01`：`schema.Task.validate` 对 `status="failed"` 有两条硬要求 ——
    # `error` 非空、`outcome == "failed"`。改前这一行只给 status/outcome，
    # 于是"模型侧确实失败了"这三个码在台账上永远停在 `running`（占位行）。
    # 理由串逐字就是这一跑的 `reason`，加上退出码，便于人顺着追。
    task_error = (f"模型侧结局 {reason!r}（exit_code={exit_code}）"
                  if status == "failed" else "")
    detail = (
        f"`agentflow run` 的一次运行：主题「{topic[:60]}」，{len(records)} 次模型调用"
        f"（成功 {ok_calls}），退出码 {exit_code}，理由 {reason!r}。"
        "这次运行产出的磁盘文件（不是表里的行，所以不进 `artifacts`）："
        + "、".join(str(a) for a in ARTIFACTS) + "。"
        "这一行由 `runflow._settle_run_task` 写（`G-3`）：在此之前 `run_topic` 只写账本、"
        "不建任务行，于是账本上的钱挂不到任何一次召唤上，`verify` 每次运行都报 error。"
    )
    try:
        with store.tx("tasks", actor="agent-M", note=f"runflow settle {task_id}") as tx:
            row = _new_task_row(
                task_id=task_id, topic=topic, status=status, outcome=outcome,
                detail=detail, started_at=started_at, ended_at=stamp,
                tokens=tokens, usd=usd, error=task_error,
            )
            S.Task(
                **{k: v for k, v in row.items() if k in S.Task.__dataclass_fields__}
            ).validate()
            tx.upsert("tasks", row, note=f"runflow settle {task_id}")
        written = True
        err = ""
    except Exception as exc:  # noqa: BLE001 - 写不进去要说出来，但不改退出码
        written = False
        err = f"{type(exc).__name__}: {exc}"
    return {"task_id": task_id, "written": written, "error": err,
            "status": status, "outcome": outcome, "tokens": tokens, "usd": usd}


#: `tasks.status` 的三档（`R5-F4`）：`_run_task_verdict` 只许返回它们。
TASK_STATUSES: frozenset[str] = frozenset({"done", "failed", "cancelled"})

#: `run_topic` 今天真的会赋给 `reason` 的字面量（`R5-F4` 的可达性判据）。
#:
#: 逐字对应 `run_topic` 里的赋值点：没 key / 检索没查成两档 / 预算熔断 /
#: 跑满 max_calls（`success` 或 `no_call`）。模型侧的错误码不在这张表里 ——
#: 那些来自 `reply.error_kind`（`modelgw.MODEL_ERROR_KINDS`），是运行时值不是字面量，
#: 由 `_run_task_verdict` 按 `NOT_CHECKED` 分档。
#:
#: 这里刻意没有 `cancelled`，也没有任何取消入口：`run_topic` 不收 CancelToken，
#: `cli.py` 里也没有 signal / KeyboardInterrupt 处理 ⇒
#: "`agentflow run` 能产出 status=cancelled"这句话今天是假的。
#: 判据在 `tests/test_r5_orchestration_cost.py`：它对 `run_topic` 做 AST 扫描，
#: 断言字面量集合与本表一致 —— 往 `run_topic` 里加一个新的 `reason = "…"`
#: 而不在这里分档，那条用例会红。
RUN_TOPIC_REASON_LITERALS: frozenset[str] = frozenset({
    # `""` 是初值：`run_topic` 里 `reason = ""` 那一句。它到不了 `_settle_run_task`
    # （每条路径都会赋一个真结局），但它是"赋给 reason 的字面量"之一，
    # 而这张表的判据就是"声明 == 源码里赋的字面量"（见测试里的 AST 扫描）。
    "",
    "success", "no_key", "no_call",
    "retrieval_failed", "retrieval_not_configured",
    "budget_exhausted",
})

#: 本函数显式判成 `done` 的理由：`run_topic` 那张表，外加老版本留下的三条
#: （`retrieval_not_measured` / `no_claims` / `unparsable`）—— 它们在
#: `run_topic` 的赋值点上已经不存在了，但它们曾是本函数的接口面，
#: 别的调用方（测试夹具、将来的编排层）可能还在传。留着是兼容，
#: 而"它们今天不再由 `run_topic` 产出"这件事由 `RUN_TOPIC_REASON_LITERALS` 如实表达。
TASK_DONE_REASONS: frozenset[str] = RUN_TOPIC_REASON_LITERALS | frozenset({
    "retrieval_not_measured", "no_claims", "unparsable",
})


def _run_task_verdict(*, reason: str, exit_code: int) -> tuple[str, str]:
    """`(tasks.status, tasks.outcome)`（`G-3`）。

    为什么不直接按 `exit_code` 映射：退出码是三态（0/1/2 = 有结论/有问题/没查成），
    而 `tasks.status` 说的是"这次召唤的终态"。两者有交集但不是同一件事：
    一次 `no_key` 的运行退出码是 2（没查成），而它在任务台账里的终态是
    `done`（这一行确实跑完了、结论是"没有 key 所以没调模型"）。
    把它写成 `failed` 会让"环境缺 key"看起来像"这次召唤崩了"。

    ## 可达性（`R5-F4`：这里原先有三处与事实不符）

    1. `cancelled` 一档在 `run_topic` 这条通路上到不了 —— 它没有取消入口
       （不收 CancelToken，`cli.py` 里也没有 signal / KeyboardInterrupt 处理）。
       这一档留着是因为本函数是纯映射，将来接进取消面的调用方要用它；
       但"`agentflow run` 会产出 status=cancelled"是假的，不许这么读。
    2. `failed` 曾经也不可达：旧实现只认字面量 `"error"`，而 `run_topic` 赋给
       `reason` 的是 `reply.error_kind`（`timeout` / `auth_failed` / `rate_limited`
       这些），于是"模型调用确实失败了"被静默记成 `done` / `no_result`。
       现在按 `modelgw` 的两张词表分档（见下）。
    3. 旧实现里有一段 `if reason in (…7 个常量…): pass` —— 一个空块。
       它看起来在分档、实际什么都没做（`success` 由下面单独判、其余走兜底）。
       现在那张名单是 `TASK_DONE_REASONS`，而且是真被用来判定的。

    ## 模型侧结局怎么分档（与 `modelgw.NOT_CHECKED` 同一口径）

    - `reason in NOT_CHECKED`（`no_key` / `timeout` / `network` / `server_error` /
      `unknown`）：这是"没查成"，不是"查了没通过" ⇒ 这一行跑完了，`done` /
      `no_result`；
    - 其余 `MODEL_ERROR_KINDS`（`auth_failed` / `rate_limited` / `bad_response`…）：
      查过了、确实不行 ⇒ `failed` / `failed`。
    把第 2 类读成第 1 类，正是 `G-7` 那一族"把失败折叠成没有结论"的形态。
    """
    from .modelgw import MODEL_ERROR_KINDS, NOT_CHECKED

    if reason == "cancelled":
        # 见上面第 1 条：`run_topic` 到不了这里，只有接进取消面的调用方才用得上。
        return "cancelled", "cancelled"
    if reason == "success":
        return "done", "ok"
    if reason == "error":
        # 老接口面留下的字面量：`run_topic` 今天不产出它（模型结局走 `error_kind`），
        # 但它曾经是本函数的输入之一 —— 去掉这一支会把一个"失败"悄悄变成
        # "没有结论"，而那是本条目要修的同一族方向。
        return "failed", "failed"
    if reason in TASK_DONE_REASONS:
        # 显式列出"落进 done"的那些理由：读的人不必去猜默认分支覆盖了谁。
        return "done", "no_result"
    if reason in MODEL_ERROR_KINDS:
        if reason in NOT_CHECKED:
            return "done", "no_result"
        return "failed", "failed"
    # 认不出的理由：如实落"跑完了、没有结论"，并把这件事留给读者
    # （`unknowns` 里已经有一行写着"本次以 <reason> 结束 ⇒ 结论不完整"）。
    return "done", "no_result"


def _lean_md(lean: Mapping[str, Any] | None) -> list[str]:
    """报告证据段里的 Lean 小节。没开这一层时返回空列表（不占版面）。

    为什么必须逐条写出结论而不是只写一句"跑了 Lean"：`uses_sorry`、
    `extra_axioms`、`decl_mismatch` 三者在人读的报告里长得一样（都是"没过"），
    而它们要的处置完全不同 —— 一个是被跳过的证明，一个是假设了结论，
    一个是文件里压根没有那个声明。
    """
    if not lean or not lean.get("enabled"):
        return []
    lines = [
        "",
        "### 形式化验证（Lean）",
        "",
        f"- 本次是否开启：{'是' if lean.get('enabled') else '否'}",
        f"- 结论：{lean.get('reason')}",
        f"- 本次到达的证据等级：{lean.get('evidence_kind') or '无（没有任何一条通过 Lean 检查）'}",
    ]
    for c in lean.get("checks") or []:
        lines.append(
            f"- 片段 {c.get('name') or '(无名)'}：{c.get('status')}；"
            f"证据等级 {c.get('evidence_kind') or '无'}；{c.get('reason')}"
        )
    lines.append(
        "- 只有 `verified` 才等于 proof 级证据：含 `sorry` 的文件在 Lean 里"
        "会正常编译通过，所以退出码 0 不是证明。"
    )
    return lines


def _lean_stage(records: list[CallRecord], *, enabled: bool, run_fn: Any = None) -> dict[str, Any]:
    """Lean 检查段：只有真的跑过检查器，才允许说"这一层接上了"。

    ## 为什么"跑了"与"没跑成"必须分开记

    `NOT_WIRED_ITEMS` 里那条 lean 是"本流程确定没做的事"的登记。
    判断它能不能摘掉，唯一算数的证据是"检查器真的回过话"：
    开了开关但后端不存在、或答复里根本没有 Lean 片段，都仍然是"没有形式化验证证据"。
    把"开了开关"当成"接上了"，就会让报告里那句"已接线"变成谎话。

    ## 片段与断言的绑定

    约定 `` ```lean `` 代码块是模型侧唯一可机械识别的形式化片段（`lean_snippets`）。
    片段与断言按"同一条答复"绑定（`call_index` 与同一条答复里解析出的断言文本都记进产物）：
    格式约定里没有"这块代码属于哪一条断言"的位置，硬猜一个对应关系，
    判的就变成解析器聪不聪明，而不是证明成不成立。

    `run_fn` 是 `formalgw.check_lean` 的运行接缝，原样透传（测试注入后全程离线）。
    """
    doc: dict[str, Any] = {
        "enabled": bool(enabled),
        "attempted": False,
        "ran": False,
        "snippets": 0,
        "checks": [],
        "proved": 0,
        "evidence_kind": None,
        "statuses": [],
        "reason": "",
    }
    if not enabled:
        doc["reason"] = ("本次没有开启 Lean 检查（`--lean` 默认关）"
                         "⇒ 本次没有任何形式化验证证据")
        return doc

    answered = 0
    for rec in records:
        if not rec.reply.ok:
            continue
        answered += 1
        found = lean_snippets(rec.reply.text)
        if not found:
            continue
        doc["attempted"] = True
        claim_texts = [str(c.get("text") or "") for c in parse_claims(rec.reply.text)]
        for sn in found:
            doc["snippets"] += 1
            if not sn["name"]:
                # 无名片段（`example` 之类）：公理审计与声明名核对都没有对象，
                # 所以它永远不可能是 proof 级证据。这里如实落 `decl_mismatch`
                # 而不是"跳过不记"—— 后者会让"检查过几条"这个数字变小。
                doc["checks"].append({
                    "call_index": rec.index, "claim_texts": claim_texts, "name": "",
                    "status": "decl_mismatch", "evidence_kind": None, "proved": False,
                    # 静态结论：检查器一次也没起过，所以它不是"这一层跑通了"。
                    "checker_invoked": False,
                    "reason": "Lean 片段里没有具名声明（例如只有 example）"
                              "⇒ 无法审计公理、也无法核对声明名 ⇒ 不构成证明",
                })
                continue
            res = check_lean(sn["source"], name=sn["name"], imports=(), run_fn=run_fn)
            doc["checks"].append({
                "call_index": rec.index, "claim_texts": claim_texts, "name": res["name"],
                "status": res["status"], "exit_code": res["exit_code"],
                "elapsed_sec": res["elapsed_sec"], "backend_version": res["backend_version"],
                "source_sha256": res["source_sha256"], "axioms": list(res["axioms"]),
                "sorry_count": res["sorry_count"], "decl_matches": res["decl_matches"],
                # 证据等级直接取 `check_lean` 已经算好的那一份口径，
                # 不在这里再写一遍 "status == verified 就是 proof"。
                "evidence_kind": res["evidence"]["evidence_kind"],
                "proved": res["evidence"]["proved"],
                "checker_invoked": bool(res["ran"]),
                "stdout_excerpt": str(res["stdout"] or "")[:400],
                "reason": res["reason"],
            })

    checks = doc["checks"]
    doc["statuses"] = [str(c["status"]) for c in checks]
    doc["proved"] = sum(1 for c in checks if c["proved"])
    # "这一层算不算接上了"的判据只有一条：检查器真的回了一个可用结论。
    # 不用"状态属于哪几个"来推 —— 静态判据（声明名不在文件里、源码里有 sorry）
    # 同样会给出 `decl_mismatch` / `uses_sorry`，但那时检查器一次也没起过；
    # 超时与后端不在同理。
    doc["ran"] = any(bool(c.get("checker_invoked")) for c in checks)
    doc["evidence_kind"] = "proof" if doc["proved"] else None
    if not checks:
        if not answered:
            # 没有成功的答复时"答复里没有 Lean 片段"是一句误导：真相是这次根本没答复。
            doc["reason"] = ("本次没有成功的模型答复 ⇒ 没有任何 Lean 片段可查"
                             "（这是'没做'，不是'查了、没有'）")
        else:
            doc["reason"] = ("本次的模型答复里没有任何 Lean 代码块（```lean）"
                             "⇒ 没有可检查的形式化代码")
    elif doc["ran"]:
        doc["reason"] = (f"Lean 检查跑过 {len(checks)} 段片段，结论分别为 {doc['statuses']}；"
                         f"产出 proof 级证据的有 {doc['proved']} 条")
    else:
        doc["reason"] = (f"Lean 检查没有跑出结论（结论 {doc['statuses']}）"
                         "⇒ 本次没有得到任何形式化验证结论"
                         "（注意：这不是'证明失败'，也不等于证明不存在）")
    return doc


def _evidence_md(evidence: Mapping[str, Any] | None,
                 verification: Mapping[str, Any] | None,
                 lean: Mapping[str, Any] | None = None) -> list[str]:
    """报告里的证据段：逐源状态、来源与全文获取、两级通过条数、未通过与未知。

    为什么数字只从 `evidence` / `verification` 里取而不再算一遍：
    报告与 `claims.json` 上的同一件事必须逐字一致。第二处计算就是第二份口径，
    而"两处各算一遍但愿它们相等"正是本仓库反复记过的形态。

    这一段的判据是"不许让读者以为全文验过而实际只验了摘要"，所以三级数字
    分开给（摘要级 / 全文级 / 未通过 / 未知），并逐字写出本次到达的级别。

    断言那几行的口径（本工作包接线后的形态）：台账现在覆盖"模型答复里
     可原子化的那些断言"，所以这一段必须同时给出拆出多少条、其中逐字
     通过多少条（分摘要级/全文级）、未通过多少条、没有可回验依据多少条
     与被截断多少条。少任何一个数字，读者都会把"台账里有 N 条"读成
    "这次一共只有 N 条结论"。
    """
    lines = ["", "## 证据（检索 + 全文 + 逐字回验）", ""]
    if evidence is None or verification is None:
        lines.append("- 本次运行没有检索记录（证据段未接入）⇒ 本次没有任何外部文献证据。")
        return lines + _lean_md(lean)

    sources = list(evidence.get("sources") or [])
    providers: dict[str, int] = {}
    for s in sources:
        name = str((s or {}).get("source") or "?")
        providers[name] = providers.get(name, 0) + 1
    by_provider = "、".join(f"{k}×{v}" for k, v in sorted(providers.items())) or "无"
    status_map = dict(evidence.get("sources_status") or {})
    if status_map:
        consulted = "、".join(f"{k}={v}" for k, v in status_map.items())
    else:
        # 逐源信息为空说明这次是单函数路径（不是"一个源都没问"），必须写出来，
        # 否则读者会把"没有逐源台账"读成"没问过任何源"。
        consulted = "（本次没有逐源台账：走的是单检索器路径）"
    counts = dict(verification.get("counts") or {})
    total = int(counts.get("total") or 0)
    passed = int(counts.get("verified") or 0)
    unverified = int(counts.get("unverified") or 0)
    abstract_level = int(counts.get("verified_abstract") or 0)
    fulltext_level = int(counts.get("verified_fulltext") or 0)
    no_basis = int(counts.get("known_unverifiable") or 0)
    # 拆分层的数字取自 `verification.check.splitting`（`run_topic` 写进去的那一份），
    # 不在这里重数：报告与 `claims_ledger` 必须是同一份数字的两个出口。
    splitting = dict((verification.get("check") or {}).get("splitting") or {})
    split_status = str(splitting.get("status") or "（未记录）")
    found = int(splitting.get("total_found") or total)
    truncated = int(splitting.get("truncated") or 0)
    registered = int(splitting.get("claim_count") or total)
    basis_map = {k: int(v) for k, v in dict(splitting.get("basis_counts") or {}).items() if v}
    basis_text = "、".join(f"{k}×{v}" for k, v in sorted(basis_map.items())) or "无"

    fulltext_doc = evidence.get("fulltext_acquisition") or {}
    lines += [
        f"- 检索状态：{evidence.get('status')}（{evidence.get('reason')}）；"
        f"查询「{evidence.get('query')}」；时间 {evidence.get('retrieved_at')}",
        f"- 咨询的源与各自状态：{consulted}",
        f"- 来源：{len(sources)} 条（去重后；{by_provider}）",
        (f"- 全文获取：{fulltext_doc.get('reason')}" if fulltext_doc else
         "- 全文获取：本次没有发起（`fulltext=False`）⇒ 逐字回验最多到达摘要级"),
        f"- 断言拆分：{split_status}；共拆出 {found} 条；登记 {registered} 条；"
        f"被截断 {truncated} 条（拆分依据：{basis_text}）",
        f"- 断言：{total} 条；逐字通过 {passed} 条；未通过 {unverified} 条",
        f"- 逐字通过的分级：摘要级 {abstract_level} 条；全文级 {fulltext_level} 条",
        f"- 无可回验依据（没有引文，按 known_unverifiable 登记，不会被丢弃）：{no_basis} 条",
        f"- 未通过/未知明细：not_found {int(counts.get('not_found') or 0)} / "
        f"known_unverifiable {no_basis} / "
        f"unknown {int(counts.get('unknown') or 0)}",
        f"- 本次回验到达的级别：{verification.get('reason')}",
        "- 未验证的断言不得作为证据：逐字回验没通过的结论只是模型的话，不是外部证据。",
        "- 摘要级与全文级不是一件事：摘要级通过只说明引文在摘要里逐字存在，"
        "不说明它在正文里存在（正文若已获取会单独计进全文级）。",
        "- 拆出条数与登记条数不等时，差额就是被截断的那些：它们既没被回验，"
        "也不在任何计数里（台账的上限写在 `claims_ledger` 段）。",
    ]
    return lines + _lean_md(lean)


def _report_md(*, topic: str, reason: str, exit_code: int, price: tuple[float, float],
               records: list[CallRecord], ledger: dict[str, Any],
               budget_usd: float, prompt_version: str, not_wired: list[dict],
               unknowns: list[str], evidence: Mapping[str, Any] | None = None,
               verification: Mapping[str, Any] | None = None,
               lean: Mapping[str, Any] | None = None,
               run_spent_usd: float | None = None) -> str:
    """人读报告。unknowns 段永远存在（没有未知项时也要显式写"本次无未知项"）。

    为什么这是一个独立的函数而不是塞在 `run_topic` 里：这一段是给人读的那一份事实，
    而"没有未知项"这种形态很难在端到端里造出来（本流程总会至少列一条未接线）——
    独立成函数才好在测试里直接把它钉住。

    `evidence` / `verification` 缺省为 `None`：证据段始终出现（哪怕只写一句
    "本次运行没有检索记录"）。段落存在与否是判据，而不能靠"某次运行刚好没有"。
    `lean` 缺省为 `None`：形式化验证小节只在真的开了这一层时出现
    （关着的时候写一整段"没用 Lean"会把证据段变成公告栏）。

    `run_spent_usd` 是"这一次运行"花掉的钱（`G-4`），缺省 `None` 表示调用方没给
    （那时退回账本累计值，与改前的行为逐字相同）。预算那一行必须同时印两个数：
    只印累计值时，"这次运行花了多少"与"这个工作区一共花了多少"是同一个数字，
    而预算判的只是前者。
    """
    spent_for_budget = (round(float(ledger["usd"]), 6) if run_spent_usd is None
                        else round(float(run_spent_usd), 6))
    lines = [
        f"# 运行报告：{topic}",
        "",
        f"- 退出码：{exit_code}（0=成功产出 / 1=查过了失败 / 2=没查成）",
        f"- 退出原因：{reason}",
        f"- prompt 版本：{prompt_version}",
        f"- 单价（美元每百万 token）：输入 {price[0]} / 输出 {price[1]}",
        f"- 预算：{budget_usd} 美元（本次运行口径）；本次已花：{spent_for_budget} 美元；"
        f"余：{_budget_left(budget_usd, spent_for_budget)} 美元",
        f"- 该工作区账本累计：{ledger['usd']} 美元（跨运行累计，不是本次预算的口径）",
        f"- 调用次数：{len(records)}（成功 {sum(1 for r in records if r.reply.ok)}）",
        f"- 账本行数：{ledger['entries']}；token 合计：{ledger['tokens']}；"
        f"重试额外开销：{ledger['retry_overhead']['extra_tokens']} token",
        "",
        "## 逐次调用",
        "",
        "| 序号 | 结局 | 未查成 | tokens_in | tokens_out | 美元 | 本次累计美元 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in records:
        d = r.reply.to_dict()
        lines.append(
            f"| {r.index} | {d['error_kind'] or 'ok'} | {'是' if d['not_checked'] else '否'} | "
            f"{d['tokens_in']} | {d['tokens_out']} | {r.usd} | {r.spent_after_usd} |"
        )
    lines += _evidence_md(evidence, verification, lean)
    lines += ["", "## 未接线（本次确定没有做的事）", ""]
    for item in not_wired:
        lines.append(f"- {item['name']}：{item['reason']}")
    lines += ["", "## unknowns（本次的未知项）", ""]
    if unknowns:
        lines += [f"- {u}" for u in unknowns]
    else:
        lines.append("- 本次无未知项")
    lines += [
        "",
        "## 产物",
        "",
        "本次运行的事实来源是 `run-manifest.json`（机器可读）与本文件（人读）；"
        "`cost.json` 的汇总与 `usage_ledger` 是同一份口径，"
        "`evidence.json` 与 `claims.json` 记的是同一批来源与同一次回验，都不作第二份计算。",
        "",
    ]
    return "\n".join(lines)


def _why_not_full_ledger(verification: Mapping[str, Any],
                         records: list[CallRecord],
                         split: Mapping[str, Any] | None = None) -> str:
    """写清 `claims.json` 的台账覆盖到了什么、没覆盖到什么。

    为什么这件事必须写下来：台账里"有 3 条断言"与"模型只说了 3 条"是两件事。
    没有这句话，读者会把"只登记了一部分"读成"这次一共就这些结论" ——
    那正是把"没登记"读成"没有"，而这一层存在的理由就是不许这种读法。

     接线之后这句话仍然必须存在，只是内容变了：现在断言是拆出来的
    （`claims.split_claims`），所以覆盖面的缺口不再是"没有引文的结论被丢弃"，
    而是三件具体的事 —— 拆分没成（`unparsable`）、拆出来超过上限被截断、
    以及拆出来的那些里有没通过逐字回验的。三件都在这里逐条写明。
    """
    counts = dict(verification.get("counts") or {})
    total = int(counts.get("total") or 0)
    split = dict(split or {})
    status = str(split.get("status") or "")
    truncated = int(split.get("truncated") or 0)
    found = int(split.get("total_found") or total)
    if total:
        return (
            f"本次登记了 {total} 条原子断言（共拆出 {found} 条；逐字通过 "
            f"{counts.get('verified')} 条；未通过 {counts.get('unverified')} 条；"
            f"无可回验依据（known_unverifiable）{counts.get('known_unverifiable', 0)} 条；"
            f"被截断 {truncated} 条）。"
             "台账覆盖的是模型答复里可原子化的那些断言：代码围栏内的内容与标题行"
            "不在断言范围内，超过上限的按截断数逐条写明；"
            "没有引文的断言不会被丢弃，而是以 known_unverifiable 落在台账里。"
        )
    if not any(r.reply.ok for r in records):
        return (
            "本次没有成功的模型调用 ⇒ 一条断言都没有登记（这是'没做'，不是'做了没有'）。"
            "空数组说的是'这一层没有跑或没有产出'，不是'结论里没有断言'。"
        )
    if status == "no_claims":
        return (
            "本次的模型答复里确实没有可断言的句子（拆分为 no_claims）⇒ 一条断言都没有登记。"
            f"理由：{split.get('reason') or '（未记录理由）'}"
            "空数组说的是'读过了、没有任何可断言的内容'，不是'登记了、内容为空'。"
        )
    if status == "unparsable":
        return (
             "把模型答复拆成断言这一步本次没查成（拆分为 unparsable）⇒ "
            "一条断言都没有登记 —— 这是'我们没拆成'，不是'答复里没有断言'。"
            f"理由：{split.get('reason') or '（未记录理由）'}"
        )
    return (
        "模型答复里没有拆出任何一条断言，而拆分的结论既不是 no_claims 也不是 "
        "unparsable ⇒ 这条路径不该出现（拆分层三态被绕过）。"
        "空数组在这里意味着'拆分层没给出可判定的结论'，不是'答复里没有断言'。"
    )


def _verification_from_ledger(rows: Sequence[Mapping[str, Any]], split: Any,
                              evidence: Mapping[str, Any], *,
                              quote_fn_name: str = "quoteverify.check_quote",
                              text_ref_problems: Sequence[str] = ()) -> dict[str, Any]:
    """把原子断言台账折成 `verify_claims` 同形的返回值（下游读数字的唯一入口）。

    为什么要这一层：下游（报告证据段、`run-manifest.json` 的 `claims`、
    `evidence.json` 的 `claims`）此前读的是 `verify_claims` 的返回。台账现在是
    `claims.ledger_rows` 给的（多带 `claim_id` / `basis` / 没有引文也必须落一行），
    所以这里做一次投影，而不是让每个读点各算一遍计数 —— 各算一遍就是第二份口径，
    而"报告与台账数字不一致"正是这一层最该防的形态。

    计数口径与 `evidence.verify_claims` 逐字一致，便于两边对照：
    `total` 是台账行数；每一档判决各一个数字；`unverified` 是"没通过"的总数；
    `verified_abstract` / `verified_fulltext` 两级分开数（合成一个是错的读法）。
    台账行的判决只许来自 `claims.VERDICTS`，出现别的值按 `unknown` 计 ——
    不让一个没登记的判决悄悄消失。
    """
    verdicts = claims_mod.VERDICTS
    counts: dict[str, int] = {"total": len(rows)}
    for name in verdicts:
        counts[name] = sum(1 for r in rows if str(r.get("verdict")) == name)
    unknown_like = len(rows) - sum(counts[n] for n in verdicts)
    counts["unknown"] = counts["unknown"] + unknown_like
    counts["unverified"] = counts["total"] - counts["verified"]
    for level in ("abstract", "fulltext"):
        counts[f"verified_{level}"] = sum(
            1 for r in rows if str(r.get("verdict")) == "verified"
            and str(r.get("level")) == level
        )
    levels_reached = sorted({str(r.get("level")) for r in rows
                             if str(r.get("verdict")) == "verified" and r.get("level")})
    checked = bool(evidence.get("checked"))
    if not any(r.get("verdict") == "verified" for r in rows):
        reason = (f"对 {len(rows)} 条原子断言做了逐字比对，本次没有一条通过"
                  "（未通过的判决见 counts 的 not_found / known_unverifiable / unknown）")
    else:
        reason = (f"对 {len(rows)} 条原子断言做了逐字比对；本次回验到达的级别："
                  f"{'／'.join(levels_reached) or '无'}")
    # 全文引用取不到的那些来源（`draft/30` §T0-5）：必须进产物，否则"降级到摘要级"
    # 会被读成"这篇没有全文"。键只在真出问题时出现 —— 常驻空列表会被读成"永远没问题"。
    if text_ref_problems:
        counts["fulltext_text_unavailable"] = len(text_ref_problems)
        reason += (f"；另有 {len(text_ref_problems)} 条来源声称拿到全文，但逐页文本引用取不到 ⇒ "
                   "那几条没做成全文级回验（不是'这篇没有全文'）")
    return {
        "claims": [dict(r) for r in rows],
        "counts": counts,
        "check": {
            "checked": checked,
            "reason": reason,
            "quote_fn": quote_fn_name,
            "levels_reached": levels_reached,
            # 拆分层的结论与台账一起落进 `verification`：读者要能一眼看出
            # "这次拆出多少条、有没有被截断、依据是哪一层"，而不是从台账行数反推。
            "splitting": split.to_dict() if hasattr(split, "to_dict") else dict(split or {}),
            **({"fulltext_text_unavailable": list(text_ref_problems)} if text_ref_problems else {}),
        },
        "checked": checked,
        "reason": reason,
    }


def _phase_1(max_calls, now, out_dir, spec, store, topic):
    """`run_topic` 的第 1 段（行 1164–1264）。

    由 `temp/_split_any.py` 逐字搬移而来：判据与行为一条没改，只是换了个位置。
    入参 / 出参见脚本的 dry-run 输出。
    """
    if int(max_calls) < 0:
        raise ValueError(f"max_calls 不能为负（收到 {max_calls}）")

    cfg = spec if spec is not None else spec_from_env()
    price = price_of(cfg)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = now or S.now_iso()
    started_at = stamp
    # `G-2`：幂等键必须按这一次运行命名，不能只按主题。
    #
    # 缺陷（2026-09-26 全面体检 · 子代理 G 实测，`temp/auditG-probe4.txt` A 段）：
    # 旧版是 `"run-" + topic[:110]`，于是同一工作区里同一主题跑第二遍时，
    # 每一次调用的幂等键都与第一遍相同 ⇒ `charge_reply` 走 duplicate 快速通道，
    # 第 2 次的 `per_call` 全部变成 `{charged: false, reason: 'duplicate'}`
    # 却仍然带着第 1 次那一行的 usd/tokens，`spent_usd` 也报第 1 次的钱。
    # 两个方向同时错：① 账本少记整整一轮真实花费（生产里每次调用都是真计费的
    # HTTP 请求）⇒ 预算熔断看不到这部分钱；② 第 2 次的 cost.json / run-manifest
    # 把第 1 次的花费记在自己名下。没有任何断言会响。
    #
    # 两个口径各管一件事，谁也不复用谁（2026-09-26 所有者裁定，`draft/28` §24）：
    #
    # ① task_id 走契约：`schema.Task.validate` 要求 `t-NNNN`
    #    （`PROCESS_ID_PREFIXES["task"] = "t"`，即 `P-17`）。此前这里造的是
    #    `run-<主题>-<时刻>`，写入时被 `require_process_id` 拒掉；而
    #    `_settle_run_task` 把写失败收进 detail 不抛，于是 `tasks` 表恒 0 行
    #    —— 静默失败。取号算法与 `conductor._write_new_row` 同一做法
    #    （读现有行取 max+1）；`R5-AN-1` 之后连临界区也同一做法
    #    （取号与建行在同一个 `store.tx` 里，见下面那一段的说明）。
    # ② 幂等键走运行标识：键是 `(运行标识, call_index)` 的摘要。运行标识取
    #    「主题的摘要 + `now`（+ 生产形态下的随机后缀，见 `R5-F5`）」——
    #    同一次运行的多次调用共享同一个运行标识（`call_index` 区分）⇒ `FC-19`
    #    （重试也计入）不受影响；它仍会拿到自己的 `t-NNNN` 行，
    #    所以审计面 `usage_ledger.task_id → tasks` 不会悬空。
    #    显式传同一个 `now` 的第二跑算出同一个键 ⇒ 判 duplicate
    #    （`test_cli_run.py` 的 `test_rerunning_the_same_topic_does_not_double_charge`
    #    要的正是这个：显式 `now` = "这是同一次逻辑运行"）。
    #
    # ---- `R5-F5`（重审实测）：那条"秒粒度是代价"的说法里有两处不是代价、是缺陷 ----
    #
    # (a) `topic[:100]` 是截断：两个前 100 字相同、后缀不同的主题在同一个
    #     `now` 下算出同一个运行标识 ⇒ 第二个主题被整轮判重放。不同的主题
    #     本来就该是不同的逻辑运行，这与"同一主题跑第二次"不是一回事。
    #     修法是拿整个主题的 sha256 摘要（不再截断）。
    # (b) 默认路径（不给 `now`，也就是生产形态）的运行标识只由
    #     `now`（`S.now_iso()`，秒粒度）决定 ⇒ 同一秒内两次真运行撞同一个键，
    #     第二次真发出去的 HTTP 花销在账上完全不存在（重审实测：两次默认路径
    #     运行共 0.099s，`usage_ledger` 只有 1 行、`per_call` 全是 duplicate）。
    #     修法：`now is None`（生产形态）时给运行标识加一个每次调用都不同的
    #     随机后缀 —— 运行标识的职责就是"标识这一次运行"，而每一次调用都是一次
    #     独立的运行。显式给了 `now` 时不给后缀（见上：那是"同一次逻辑运行"的声明）。
    # 两处都改了之后，"同一主题同一秒跑两次"仍然可以复现成同一次逻辑运行 ——
    # 只要你显式传同一个 `now`；不传时它们就是两次运行，各记各的账。
    _run_stamp = (stamp or "").replace(":", "").replace("+", "").replace("-", "")[:15]
    _topic_digest = hashlib.sha256(topic.encode("utf-8")).hexdigest()[:16]
    _run_nonce = "" if now is not None else "-" + uuid.uuid4().hex[:8]
    _idem_scope = "run-" + _topic_digest + "-" + (_run_stamp or "nostamp") + _run_nonce
    from .interactions import next_prefixed_id
    # `R5-AN-1`（第 6 轮重审实测的修法）：取号必须与建行在同一个临界区里。
    #
    # 缺陷形态（两个真进程并发 `agentflow run`，读数见 `temp/reaudit6-R5-p6.txt`）：
    # 旧版在 `store.tx` 之外读一份无锁快照取号，行却在整条 run 结束时的另一个
    # tx 里才写 ⇒ 两个进程都拿到 `t-0001`；`tasks` 表最后只剩 1 行，而存活
    # 那一行的 `tokens` 是两跑之和；两条 `usage_ledger` 都挂 `t-0001`；
    # 而 `verify_all` 的 code 集合是 []（一条都不报）—— 静默丢行。
    #
    # 为什么"把取号搬进 tx"不够（本条修法的必要性来自读数，不是来自与
    # `conductor._write_new_row` 同形）：`next_prefixed_id` 是纯函数（读现有行取
    # max+1），它没有计数器；只把取号搬进 tx、行仍然等到收工才写，第二个进程
    # 在第一个进程写行之前进 tx，读到的还是同一份快照 ⇒ 照样撞号。
    # 我按条件 1 实测过这条最小修法（`temp/fix6_f5-minimal.txt`，两真进程）：
    # E1/E2/E3/E5 四条判据全部仍为 False（症状一个都没消失）。
    # 所以"取号"这一步必须同时落一行才算占住号：号只有在盘上可见时
    # 才对下一个进程有意义。`store.insert_unique` 的 docstring 讲的是同一条纪律
    # （唯一性只在"读与写同一个临界区"内成立）。
    #
    # 为什么占位行的 `status` 只能是 `running`：`schema.Task.validate` 要求
    # 终态（done/cancelled/failed）必须带 `ended_at`，而这次运行还没结束、结局
    # 还不知道。写一个假终态就是往台账里塞一句还没发生的事实。
    # 它的 `tokens`/`usd` 是 0 且 `outcome=None`：占位行只声明"这个号被占了、
    # 有人在这儿跑"，收工时由 `_settle_run_task` 整行改写（同一个 task_id）。
    # 崩在收工之前会留下一行 `running` —— `verify_all` 有专门的
    # `task_still_running` 把它报成 warning（这是刻意的：僵尸行是事实，
    # 不是噪音）。
    with store.tx("tasks", actor="agent-M", note="runflow allocate") as tx:
        task_id = next_prefixed_id(tx.rows("tasks"), "task_id", "t")
        reserved = _new_task_row(
            task_id=task_id, topic=topic, status="running", outcome=None,
            detail=(
                f"`agentflow run` 占位行：这次运行（主题「{topic[:60]}」）已经开始，"
                "结局还不知道。"
                "这一行在取号与建行同一个临界区内写下（`R5-AN-1`）—— "
                "号只有在盘上可见时才对下一个并发进程有意义。"
                "收工时 `runflow._settle_run_task` 会整行改写成终态。"
            ),
            started_at=started_at, ended_at=None, tokens=0, usd=0.0,
        )
        S.Task(
            **{k: v for k, v in reserved.items() if k in S.Task.__dataclass_fields__}
        ).validate()
        tx.upsert("tasks", reserved, note=f"runflow allocate {task_id}")

    return _idem_scope, cfg, out, price, stamp, started_at, task_id




def _phase_2(budget_usd, prompt_version, store, topic):
    """`run_topic` 的第 2 段（行 1265–1289）。

    由 `temp/_split_any.py` 逐字搬移而来：判据与行为一条没改，只是换了个位置。
    入参 / 出参见脚本的 dry-run 输出。
    """
    not_wired: list[dict[str, str]] = [
        {"name": name, "reason": why} for name, why in NOT_WIRED_ITEMS
    ]
    base_prompt = prompt_for(topic, prompt_version)
    # 本次实际发出去的 prompt（含材料段）。没发出去就是空串：
    # 清单里存模板会让"这次没问过"看起来像"问过了"。
    sent_prompt = ""
    # 全文获取的台账：没打开时保持 None，写进产物时如实说"没做"。
    acquisition: dict[str, Any] | None = None

    # 记账接线：无论有没有 key 都建 meter —— 账本本身就是产物之一（cost.json）
    # 的一部分，而"因为没 key 所以连账本口径都不给"会让 cost.json 无从解释。
    meter = TokenMeter(store, budget_usd=float(budget_usd))
    # `G-4` / `F5-FOUND-1`：预算熔断看的是"这一次运行"的量，口径是
    # 按 `task_id` 过滤账本（见 `_spent_this_run` 的 docstring）。
    #
    # 为什么不再取"开跑时的账本基线"：基线口径（工作区增量）只在"同一工作区里
    # 两次运行不可能重叠"时等于本次花销，而 `R5-AN-1` 把并发修通之后这个前提
    # 没了 —— 另一个进程在我取基线之后入账，它的钱会落进我的差额，先污染
    # 熔断、再污染对账自检。`task_id` 在开跑时已经存在（取号那一段落的就是它），
    # 所以这里不需要任何基线。
    records: list[CallRecord] = []
    transcript: list[dict] = []
    reason = ""
    stopped_by = ""

    return acquisition, base_prompt, meter, not_wired, reason, records, sent_prompt, stopped_by, transcript




def _phase_3(_idem_scope, acquisition, base_prompt, budget_usd, cfg, claims_max, claims_parse_fn,
    extract_fn, fetch_fn, fulltext, lean, lean_run_fn, max_calls, meter, not_wired, out, quote_fn,
    reason, records, retrieval_limit, retrieval_timeout_sec, search_fn, sent_prompt, stamp,
    stopped_by, task_id, text_store_dir, topic, transcript, transport):
    """`run_topic` 的第 3 段（行 1291–1469）。

    由 `temp/_split_any.py` 逐字搬移而来：判据与行为一条没改，只是换了个位置。
    入参 / 出参见脚本的 dry-run 输出。
    """
    if not cfg.configured:
        # 没 key 时一次网络请求都不许发（网关自己也拦，这里再拦一次是为了
        # 让"没查成"这件事在产物里就写下来，而不是等网关返回 no_key 再推断）。
        # 检索也一并跳过：检索结果是喂给模型的材料，没有模型可喂时打这次
        # 网络请求没有消费者（顺带让没 key 的路径完全不碰网络）。
        evidence = not_attempted(
            "环境里没有模型 key ⇒ 本次没有发起检索（检索到的材料没有消费者）",
            query=topic, now=stamp,
        )
        reason = "no_key"
        stopped_by = "no_key"
        not_wired.append({
            "name": "model",
            "reason": "环境里没有模型 key ⇒ 本次没有调用模型，没有任何模型结论",
        })
    else:
        # 第一步是检索：先有材料，模型才谈得上"只能依据材料"。
        # 先调模型再补检索，等于让模型先凭记忆写一遍、再拿检索结果替它找依据。
        evidence = retrieve(topic, limit=int(retrieval_limit), search_fn=search_fn,
                            timeout_sec=float(retrieval_timeout_sec), now=stamp)
        if evidence["status"] not in CHECKED_STATUSES:
            # 检索没查成 ⇒ 不调模型（见 docstring）。刻意不提供"缺材料也硬答"的
            # 选项：那会产出看起来完整、却一条也回验不了的报告。
            reason = ("retrieval_failed" if evidence["status"] == "retrieval_failed"
                      else "retrieval_not_configured")
            stopped_by = "retrieval"
        else:
            # 检索真的跑过 ⇒ 把 retrieval 与 quote_verify 从"未接线"里摘掉。
            # 判据只看 status 是否属于"查过了"，不看查到几条：查过而没有结果
            # 也是一次有效结论（"这个主题没有文献"），与"根本没查"是两回事。
            not_wired = [n for n in not_wired
                         if n["name"] not in ("retrieval", "quote_verify")]
            # 全文获取排在"作答"之前：有全文时，回验才能到全文级；
            # 放在作答之后会让 prompt 里的材料与回验用的文本不是同一批。
            if fulltext:
                acquisition = acquire_fulltext(
                    evidence["sources"], fetch_fn=fetch_fn, extract_fn=extract_fn,
                    dest_dir=out / "fulltext", limit=int(retrieval_limit),
                    text_store_dir=text_store_dir,
                )
                not_wired = [n for n in not_wired if n["name"] != "fulltext"]
            sent_prompt = base_prompt + materials_block(evidence["sources"])
            gw = ModelGateway(cfg, transport=transport)
            for i in range(int(max_calls)):
                # `G-4` / `F5-FOUND-1`：只算本次运行（同一个 `task_id`）已经花了多少。
                # 改前这里减的是"开跑时的账本基线"（工作区增量）：那样同一个工作区里
                # 并发的另一次运行在基线之后入的账会被算进我的额度，可能让我提前熔断。
                spent_before = _spent_this_run(meter, task_id)
                # 熔断在调用之前：达线就停，一次都不多花。
                if _is_exhausted(budget_usd, spent_before):
                    reason = "budget_exhausted"
                    stopped_by = "budget"
                    break
                # `G-7`：调用点不让异常穿出去（网关承诺不抛，但今天会抛）。
                reply = _complete_or_not_checked(gw, sent_prompt, scope=SCOPE_ANSWER,
                                                 model=cfg.model)
                charge = charge_reply(
                    meter, reply, role="modelgw", task_id=task_id,
                    scope=SCOPE_ANSWER, call_index=i,
                    extra_note=f"run_topic:{topic}"[:120], now=stamp,
                    idem_scope=_idem_scope,
                )
                spent_after = _spent_this_run(meter, task_id)
                rec = CallRecord(index=i, reply=reply, charge=charge,
                                 usd=float(charge["usd"]),
                                 spent_after_usd=round(float(spent_after), 6))
                rec.task_id = task_id
                rec.idem_scope = _idem_scope
                records.append(rec)
                transcript.append({"call_index": i, **reply.to_dict()})
                if not reply.ok:
                    reason = reply.error_kind
                    stopped_by = "error"
                    break
            else:
                reason = "success" if records else "no_call"
                stopped_by = "max_calls"

    # 没查成 / 没 key 时，"未接线"那两条的措辞要据实改写：常量里写的是
    # "没有接进本流程"，而这里的真相是"接了、但这次没查成" —— 两句话不能混用。
    if evidence["status"] not in CHECKED_STATUSES:
        for item in not_wired:
            if item["name"] == "retrieval":
                item["reason"] = (
                    f"文献检索本次没查成（{evidence['status']}：{evidence['reason']}）"
                    "⇒ 本次没有任何外部文献证据"
                )
            elif item["name"] == "quote_verify":
                item["reason"] = (
                    "逐字引文回验本次没有跑（没有可回验的来源文本）"
                    "⇒ 本次的模型答复没有任何引文级证据"
                )
            elif item["name"] == "fulltext" and fulltext:
                # `fulltext=True` 说明全文获取「接了」，只是没有来源可获取 ——
                # 这与"没接进本流程"不是一句话，措辞必须据实。
                item["reason"] = (
                    f"开放全文获取本次没有对象（检索没查成：{evidence['status']}）"
                    "⇒ 本次的逐字回验最多只能到达摘要级"
                )

    # 全文获取段的按次改写（`X-NEW-2` / `T15-RECON-1`，`draft/28` §98.4）：
    # 与上面 `lean` 那一段同形 —— 常量里那句写的是"开放全文获取（fetch/extract）
    # 没有接进本流程"，那是关于流程的断言；而真相是"接了（`cli.py`
    # 有 `--fulltext` 开关、`run_topic` 在 `fulltext=True` 时真的调
    # `acquire_fulltext`，见上面 `if fulltext:` 那一段）、本次没要"。
    # 后果是可验证的：读者把"存在但未启用"读成"不存在" —— §98.4 记的那次，
    # 受害的正是本轮 goal 文本（它据此把"接 fulltext"排成了一件工程活）。
    #
    # 判据是"这一次有没有发起"（`fulltext` 这个形参本身），不是"这一层在不在"：
    #   * `fulltext=True` ⇒ 这一项已在 `if fulltext:` 那一段被摘牌；检索没查成时
    #     上面那段会把它改写成"本次没有对象"；
    #   * `fulltext=False` ⇒ 留在这里并改写成按次口径（与 `lean` 同形的第三态）。
    if not fulltext:
        for item in not_wired:
            if item["name"] == "fulltext":
                item["reason"] = (
                    "本次没有发起全文获取（`--fulltext` 默认关）"
                    "⇒ 本次的逐字回验最多只能到达摘要级，不是全文级"
                )

     # 断言台账：把每一条成功答复拆成原子断言（`claims.split_claims`：先按
    # 模型自己写的 `||` 切，再按列表标记，最后按句末标点兜底），跨次调用去重，
    # 再逐条回验。为什么拆分与回验分两步：拆分判的是"这段话里有几条断言"，
    # 回验判的是"这条断言的引文在不在" —— 前者不需要材料，后者必须有材料。
    # 合在一起写，"没有材料"会顺带把拆分也停掉，于是产物里连
    # "这次本来拆出了几条"都没有答案。
    splits: list[Any] = []
    for rec_item in records:
        if not rec_item.reply.ok:
            continue
        splits.append(claims_mod.split_claims(rec_item.reply.text,
                                              max_claims=int(claims_max),
                                              parse_fn=claims_parse_fn))
    split_result = claims_mod.merge_splits(splits, max_claims=int(claims_max))
    # 回验结果整份留着：`claims` 给台账，`check` 里的"全文引用取不到"要一起带进产物
    # （`draft/30` §T0-5）。只取 `["claims"]` 会把那条缺陷丢掉。
    verify_result = verify_claims([c.to_dict() for c in split_result.claims],
                                  evidence["sources"], quote_fn=quote_fn)
    claims_ledger = claims_mod.ledger_rows(
        split_result,
        verify_result["claims"],
    )
    # 这一份台账的形状与 `verify_claims` 的返回值同形（`claims` / `counts` /
    # `check`），所以下游（报告、清单、evidence.json）读数字的代码不用改，
    # 但"判决从哪来"必须写下来：`ledger_rows` 给的判决，不是另算一遍。
    verification = _verification_from_ledger(
        claims_ledger, split_result, evidence,
        quote_fn_name=("injected" if quote_fn is not None else "quoteverify.check_quote"),
        text_ref_problems=tuple(verify_result["check"].get("fulltext_text_unavailable") or ()),
    )

    # 摘牌判据：`claims_ledger` 只有在真的拆过（`parsed`）之后才从"未接线"
    # 里消失。没拆成时改写的不是"加不加"，而是理由 —— 常量里那句写的是
    # "没有拆成"，而这里的真相可能是"拆过了、答复里确实没有可断言的句子"，
    # 两句话的处置不同（一句要去修拆分层，一句要去问模型为什么没给结论）。
    if split_result.status == "parsed":
        not_wired = [n for n in not_wired if n["name"] != "claims_ledger"]
    else:
        for item in not_wired:
            if item["name"] == "claims_ledger":
                item["reason"] = (
                    f"拆分层本次给的结论是 {split_result.status} ⇒ {split_result.reason}"
                )

    # 形式化验证段（`--lean`，默认关）。放在这里是因为它需要"答复文本"，
    # 而"某条断言带 Lean 片段"这件事只能从答复里读出来。
    #
    # 只有真的跑过检查器（`ran`）才把 lean 从"未接线"清单里摘掉；
    # 没跑成时把那一项的措辞改成具体的没查成原因 —— 留着常量文案
    # （"没有接线"）会与"接了、这次没查成"混为一谈，而两者要的处置不同。
    lean_doc = _lean_stage(records, enabled=lean, run_fn=lean_run_fn)
    if lean_doc["ran"]:
        not_wired = [n for n in not_wired if n["name"] != "lean"]
    else:
        for item in not_wired:
            if item["name"] == "lean":
                item["reason"] = lean_doc["reason"]

    successes = sum(1 for r in records if r.reply.ok)

    return acquisition, evidence, lean_doc, not_wired, reason, sent_prompt, split_result, stopped_by, successes, verification




def _phase_4(meter, reason, records, stamp, started_at, store, successes, task_id, topic):
    """`run_topic` 的第 4 段（行 1470–1525）。

    由 `temp/_split_any.py` 逐字搬移而来：判据与行为一条没改，只是换了个位置。
    入参 / 出参见脚本的 dry-run 输出。
    """
    exit_code = _exit_code_for(reason, successes=successes)
    ledger = _ledger_view(meter)

    # `G-4` / `F5-FOUND-1`：三个 `run_*` 都是"本次运行"的口径，按 `task_id`
    # 过滤账本算出来（不是工作区增量）。`ledger` 是工作区累计（跨运行，权威账本）。
    run_spent_usd = _spent_this_run(meter, task_id)
    run_tokens = int(meter.tokens_for(task_id))
    run_entries = _run_entry_count(meter, task_id)

    # 产物之间必须自洽：本次实际花掉的（逐次相加）与账本汇总不等，
    # 就说明有一条调用没进账 —— 那正是这一层要抓的形态，不许静默写两份数字。
    #
    # `R5-AN-3`（第 6 轮重审实测的修法）：只累加真的入账的那些调用。
    # 只写 `sum(r.usd for r in records)` 会把重放路径上继承来的 usd 也算进来：
    # `charge_reply` 判 duplicate 时返回的是上一次那一行的 usd（那样调用方还能
    # 读出"这笔账本来是多少"），而本次的真实增量是 0 ⇒ 一次完全正常、被刻意
    # 支持的重放被这个自检位判成"账本对不上"（实测
    # `spent_usd_this_run=0.0 calls_usd=6e-06 reconciled=False`）。
    # 自检位在正常操作上翻红就等于它失去区分力（本项目自己的纪律：
    # "error 永远红就等于 error 没有区分力"）。
    # 过滤之后"重放 ⇒ 0 == 0"成立，而"有一次 charged=True 的调用却没进账"
    # 这条判据对真漏账的分辨力一点没少（那种调用仍然被算进来）。
    calls_usd = round(sum(r.usd for r in records if r.charge.get("charged")), 6)
    # 判据用增量：`records` 只含本次的调用，与整本台账比会永远不等（工作区里有历史）。
    reconciled = abs(calls_usd - run_spent_usd) < 1e-9

    # ---- `G-3`：给这次运行补一行 `tasks`，否则账本上的钱挂不到任何一次召唤上
    #
    # 缺陷（2026-09-26 全面体检 · 子代理 G 实测，`temp/auditG-probe2.txt` S1 段）：
    # `run_topic` 写 `usage_ledger` 行时给了 `task_id='run-<主题>'`，但全文件没有任何
    # `store.tx("tasks")` 或 `Task(...)` 写入（跨行的两个星号在源码里不算强调，
    # R009 会照报 —— 这是本轮第三次踩到它）⇒ `tasks` 表行数为 0。
    # 后果：`verify_all` 每跑一次 `agentflow run` 就报 2 条 error 级
    # `dangling_usage_task`（"这笔花销挂不到任何一次召唤上"）+ 1 条 warning
    # `usage_task_total_mismatch`。error 信号因此失去区分力（它永远红），
    # 而"按召唤/按角色归口花了多少"这条账在 run 路径上答不出来。
    #
    # 口径选的是"补一行 tasks"（而不是把 usage 行的 task_id 置 None）：
    # 前者信息多——读者能看出"这一次运行花了多少、跑到哪一步"，
    # 后者只是把那条账从审计面里摘出去（看着更干净，但少了一份事实）。
    #
    # `R5-F6`（重审实测）：`_settle_run_task` 的返回值此前赋值给 `task_row` 之后
    # 从未被读过，而它的 docstring 逐字说"写失败不吞：它会被记进 `detail` 并让
    # 这一项在返回值里可见" —— 两件都不成立：写失败时恰恰没有那一行 tasks，
    # 于是 detail 也不存在；产物与退出码一字不变，消费者看不出来。
    # 现在两个出口都接上：
    #   - `manifest["task_row"]` 把 written / error 落进产物（谁都能查）；
    #   - 没写成时往 `unknowns` 加一行（"这笔花销挂不到召唤上"是本次运行的未知项）。
    # 退出码仍然不改：结论与六件产物已经落盘，账本挂点缺失是审计面的事
    # （把它折叠成"运行失败"会让读者以为结论不可用）。
    task_row = _settle_run_task(store, task_id=task_id, topic=topic, reason=reason,
                                exit_code=exit_code,
                                records=records, meter=meter,
                                started_at=started_at, stamp=stamp)
    task_row_written = bool(task_row.get("written"))
    task_row_error = str(task_row.get("error") or "")

    return calls_usd, exit_code, ledger, reconciled, run_entries, run_spent_usd, run_tokens, task_row_error, task_row_written




def _phase_5(acquisition, base_prompt, budget_usd, calls_usd, cfg, evidence, exit_code, fulltext,
    lean_doc, ledger, max_calls, not_wired, price, prompt_version, reason, reconciled, records,
    run_entries, run_spent_usd, run_tokens, sent_prompt, split_result, stamp, started_at,
    stopped_by, successes, task_id, task_row_error, task_row_written, topic, verification):
    """`run_topic` 的第 5 段（行 1527–1743）。

    由 `temp/_split_any.py` 逐字搬移而来：判据与行为一条没改，只是换了个位置。
    入参 / 出参见脚本的 dry-run 输出。
    """
    unknowns: list[str] = [f"{n['name']}：{n['reason']}" for n in not_wired]
    if not task_row_written:
        unknowns.append(
            f"本次运行的 `tasks` 行没写成（{task_row_error or '原因未记录'}）⇒ "
            "usage_ledger 上这次运行的钱挂不到任何一次召唤上，"
            "`verify` 会报 dangling_usage_task；产物与退出码不受影响"
        )
    if reason != "success":
        unknowns.append(f"本次以 {reason} 结束 ⇒ 主题的结论不完整，未知项比上面列出的更多")
    if split_result.truncated:
        unknowns.append(
            f"有 {split_result.truncated} 条断言因为超过上限 {split_result.max_claims} "
            f"没有进台账（共拆出 {split_result.total_found} 条）⇒ 它们既没被回验，也不在计数里"
        )
    if verification["counts"]["unverified"] and verification["checked"]:
        unknowns.append(
            f"有 {verification['counts']['unverified']} 条断言没有通过逐字回验"
            f"（其中 not_found {verification['counts']['not_found']} 条、"
            f"known_unverifiable {verification['counts']['known_unverifiable']} 条）"
            "⇒ 它们不得作为证据"
        )
    if lean_doc["ran"] and not lean_doc["proved"]:
        unknowns.append(
            f"Lean 检查跑过了，但没有一条 verified（{lean_doc['statuses']}）"
            "⇒ 本次没有任何 proof 级证据"
        )

    manifest = {
        "schema_version": S.SCHEMA_VERSION,
        "topic": topic,
        "prompt_version": prompt_version,
        # 清单里存的必须是真正发出去的那份文本（含材料段）：存模板而实际
        # 发的是另一份，就是一份说谎的运行记录，比没有记录更坏。
        "prompt": sent_prompt,
        "prompt_template": base_prompt,
        "materials_included": bool(evidence["sources"]),
        "spec": cfg.redacted(),
        "started_at": started_at,
        "finished_at": stamp,
        "budget_usd": float(budget_usd),
        "max_calls": int(max_calls),
        "price_usd_per_m": {"in": price[0], "out": price[1]},
        "calls": [r.to_dict() for r in records],
        "call_count": len(records),
        "success_count": successes,
        "retrieval": {
            "status": evidence["status"],
            "checked": evidence["checked"],
            "reason": evidence["reason"],
            "sources": len(evidence["sources"]),
            "query": evidence["query"],
            "retrieved_at": evidence["retrieved_at"],
            # 逐源状态也要进清单：`evidence.json` 是明细，清单是"这次做了什么"的入口。
            "sources_status": dict(evidence.get("sources_status") or {}),
        },
        "fulltext": {
            "attempted": bool(fulltext),
            "checked": bool(acquisition and acquisition["checked"]),
            "counts": dict(acquisition["counts"]) if acquisition else {},
            "reason": (acquisition["reason"] if acquisition
                       else "本次没有发起全文获取（fulltext=False）⇒ 回验最多到达摘要级"),
        },
        "claims": dict(verification["counts"]),
        "claims_checked": verification["checked"],
        # 拆分层的摘要也进清单：清单是"这次做了什么"的入口，
        # 而"拆出多少条、有没有被截断"正是这次做了什么的一部分。
        # 明细（每条断言与它的依据）在 `claims.json` 的 `claims_ledger` 段。
        "claims_ledger": {
            "status": split_result.status,
            "count": len(split_result.claims),
            "total_found": split_result.total_found,
            "truncated": split_result.truncated,
            "max_claims": split_result.max_claims,
            "basis_counts": dict(split_result.basis_counts),
            "fingerprint": split_result.fingerprint,
            "reason": split_result.reason,
        },
        # 形式化验证段在清单里给一份摘要（明细在 claims.json 的 lean 段）：
        # "这次到底有没有真的跑过 Lean"是清单要回答的问题之一。
        "lean": {
            "enabled": lean_doc["enabled"],
            "ran": lean_doc["ran"],
            "snippets": lean_doc["snippets"],
            "statuses": list(lean_doc["statuses"]),
            "proved": lean_doc["proved"],
            "evidence_kind": lean_doc["evidence_kind"],
            "reason": lean_doc["reason"],
        },
        "totals": {
            "calls_usd": calls_usd,
            "ledger_usd": ledger["usd"],
            "tokens": ledger["tokens"],
            "entries": ledger["entries"],
            # `G-4`：本次运行的口径与账本累计口径同时给出（见 cost.json 的同名字段）。
            "spent_usd_this_run": run_spent_usd,
            "tokens_this_run": run_tokens,
            "entries_this_run": run_entries,
            "budget_usd": float(budget_usd),
            "budget_exhausted": _is_exhausted(budget_usd, run_spent_usd),
            # `FINAL-R5-07`：熔断只在每次调用之前检查 ⇒ 单跑可能超出预算至多一次调用的钱。
            # 这个字段把"超了多少"显式写出来（不超就是 0.0），免得读者以为
            # `budget_usd` 是一次运行花销的硬上界 —— 它是一条"调用前检查线"。
            "budget_overshoot_usd": round(max(0.0, float(run_spent_usd) - float(budget_usd)), 9),
            "reconciled_with_usage_ledger": reconciled,
        },
        "exit_reason": reason,
        "exit_code": exit_code,
        "stopped_by": stopped_by,
        # `R5-F6`：这次运行的 `tasks` 行写成了没有。写失败时它是本次运行唯一的
        # 结构化出口（那一行 tasks 本身写不进去，所以不能指望从表里读出来），
        # 读者据此判断"账本挂点缺失"是不是这一次的已知事实。
        "task_row": {"task_id": task_id, "written": task_row_written,
                     "error": task_row_error},
        "not_wired": not_wired,
        "unknowns": unknowns,
        "artifacts": list(ARTIFACTS),
    }
    claims = {
        "claims": verification["claims"],
        "counts": dict(verification["counts"]),
        # 与 `evidence.json` 用同一个键名（`verification`）：同一件事实在两件产物里
        # 叫两个名字，读的人迟早会以为是两件事。
        "verification": dict(verification["check"]),
        # 保留 why_empty 这个键名是因为既有用例按它断言；它的内容现在是"这份台账
        # 覆盖到什么、没覆盖到什么"（接线之后不再是"为什么空"）。
        "why_empty": _why_not_full_ledger(verification, records, split_result.to_dict()),
        # 拆分层的完整台账：三态、条数、截断、依据分布与指纹。
        # 为什么与 `claims` 分开：`claims` 是逐条判决，这一段是"怎么拆的"。
        # 两者写在一起会让"拆出多少条"与"验过多少条"变成一个数字 ——
        # 而它们不是一件事（没有引文的断言拆出来了、也验不了）。
        "claims_ledger": split_result.to_dict(),
        # 未接线清单在本次运行里是动态的：真的拆过之后 `claims_ledger` 就不在这里。
        "not_wired": [n["name"] for n in not_wired if n["name"] == "claims_ledger"],
        # 形式化验证的逐条结果与实际到达的证据等级。只有 `verified` 的那几条
        # 才带 `evidence_kind="proof"` —— 这一层决定 `proof` 是不是谎话，
        # 所以它必须落在产物里，而不是只存在于某次运行的日志里。
        "lean": dict(lean_doc),
        "produced_at": stamp,
    }
    evidence_doc = {
        "topic": topic,
        "status": evidence["status"],
        "checked": evidence["checked"],
        "reason": evidence["reason"],
        "query": evidence["query"],
        "retrieved_at": evidence["retrieved_at"],
        "limit": evidence["limit"],
        "source_count": len(evidence["sources"]),
        "sources": evidence["sources"],
        "rejected": evidence["rejected"],
        # 问过哪几个源、各自什么状态：这两个字段就是"这次检索到底问到了什么"的答案，
        # 缺了它们，读者只能凭来源里的库名反推，而反推不出"哪个源失败了"。
        "sources_status": dict(evidence.get("sources_status") or {}),
        "sources_detail": list(evidence.get("sources_detail") or []),
        "fulltext_acquisition": ({
            "attempted": True,
            "configured": acquisition["configured"],
            "checked": acquisition["checked"],
            "limit": acquisition["limit"],
            "counts": dict(acquisition["counts"]),
            "results": list(acquisition["results"]),
            "ok_sources": acquisition["ok_sources"],
            "reason": acquisition["reason"],
        } if acquisition else {
            "attempted": False,
            "checked": False,
            "reason": "本次没有发起全文获取（fulltext=False）⇒ 逐字回验最多到达摘要级",
        }),
        "claims": dict(verification["counts"]),
        # 与 `claims.json` 同源：`evidence.json` 也要能回答"这次拆出多少条"，
        # 否则读证据的人只能去翻另一件产物，而两件产物的一致性就没人核。
        "claims_ledger": {
            "status": split_result.status,
            "count": len(split_result.claims),
            "total_found": split_result.total_found,
            "truncated": split_result.truncated,
            "reason": split_result.reason,
        },
        "verification": dict(verification["check"]),
        "produced_at": stamp,
    }
    cost = {
        "budget_usd": float(budget_usd),
        # `G-4`：两个口径各自标注，名字里就写着是哪一个。
        # `spent_usd` 保持"与 `usage_ledger` 同口径"（跨运行累计），因为
        # `tests/test_cli_run.py` 断言 `cost["usage_ledger"]["usd"] == cost["spent_usd"]`；
        # 判预算的那个数字是 `spent_usd_this_run`（本次运行增量）。
        "spent_usd": ledger["usd"],
        "spent_usd_this_run": run_spent_usd,
        "tokens_this_run": run_tokens,
        "entries_this_run": run_entries,
        "remaining_usd": _budget_left(budget_usd, run_spent_usd),
        "remaining_usd_ledger": _budget_left(budget_usd, ledger["usd"]),
        "budget_exhausted": _is_exhausted(budget_usd, run_spent_usd),
        "budget_scope": "this_run",
        "price_usd_per_m": {"in": price[0], "out": price[1], "source": "modelcost.price_of"},
        "per_call": [
            {"call_index": r.index, "usage_id": r.charge["usage_id"], "usd": r.usd,
             "tokens_in": r.charge["tokens_in"], "tokens_out": r.charge["tokens_out"],
             "charged": r.charge["charged"], "reason": r.charge["reason"],
             # 这一笔是为了什么（G-20）。与 `usage_ledger.by_scope` 同源：
             # 逐笔看得见归口，汇总才对得上账。
             "scope": r.charge.get("scope") or ""}
            for r in records
        ],
        "calls_usd": calls_usd,
        "usage_ledger": ledger,
        "reconciled_with_usage_ledger": reconciled,
        "produced_at": stamp,
    }
    report = _report_md(
        topic=topic, reason=reason, exit_code=exit_code, price=price, records=records,
        ledger=ledger, budget_usd=float(budget_usd), prompt_version=prompt_version,
        not_wired=not_wired, unknowns=unknowns,
        evidence=evidence_doc, verification=verification, lean=lean_doc,
        run_spent_usd=run_spent_usd,
    )

    return claims, cost, evidence_doc, manifest, report




def _phase_6(claims, cost, evidence_doc, manifest, out, report, transcript):
    """`run_topic` 的第 6 段（行 1745–1753）。

    由 `temp/_split_any.py` 逐字搬移而来：判据与行为一条没改，只是换了个位置。
    入参 / 出参见脚本的 dry-run 输出。
    """
    # 落盘顺序：先写"事实"（清单/抄本/证据/台账/账），最后写人读报告 —— 报告里引用的
    # 数字全部来自前面几件，任何一件写失败时都不会留下一份引用不存在数字的报告。
    _write_json(out / "run-manifest.json", manifest)
    _write_text(out / "model-transcript.jsonl",
                "".join(json.dumps(t, ensure_ascii=False) + "\n" for t in transcript))
    _write_json(out / "evidence.json", evidence_doc)
    _write_json(out / "claims.json", claims)
    _write_json(out / "cost.json", cost)
    _write_text(out / "report.md", report)


def run_topic(store: Any, *, topic: str, budget_usd: float, out_dir: str | Path,
              transport: Transport | None = None, spec: ModelSpec | None = None,
              max_calls: int = 3, prompt_version: str = "v1",
              now: str | None = None, search_fn: Any = None, quote_fn: Any = None,
              retrieval_limit: int = 5, retrieval_timeout_sec: float = 30.0,
              fulltext: bool = False, fetch_fn: Any = None,
              extract_fn: Any = None, lean: bool = False,
              lean_run_fn: Any = None, claims_parse_fn: Any = None,
              claims_max: int = claims_mod.DEFAULT_MAX_CLAIMS,
              text_store_dir: str | Path | None = None) -> dict:
    """跑一次端到端：检索 → 取全文 → 作答 → 逐字回验 → 记账 → 熔断 → 六件产物 → 退出三态。

    返回 ``{"exit_code", "reason", "out_dir", "artifacts", "calls", "spent_usd",
    "spent_usd_this_run"}``。

    无论走到哪一步都产出六件产物：一份"因为没 key 所以什么都没写"的目录，
    与"根本没跑"在磁盘上长得一样 —— 而它们必须能分辨。

    `FINAL-R5-02` 的边界（这一条不能靠 docstring 之外的任何东西兜）：被中断的那一跑例外。
    这条通路今天没有取消面（`run_topic` 不收 `CancelToken`），`KeyboardInterrupt` 是
    `BaseException`，会穿出本函数的 `except Exception` 兜底 —— 磁盘上留下的是"部分产物"，
    与"从来没跑过"和"跑了但没 key"三者不同形但都不可消费。所以 `cli.main` 把
    `KeyboardInterrupt` 折成退出码 2（没查成） 并打印一句显式说明；
    真正的修法（走完六件产物 + `status=cancelled`）要接进取消面，属于第 3 层。

    `store` 是工作区（`usage_ledger` 的落点）；`out_dir` 是产物的落点。
    两者刻意分开：账本属于工作区（跨运行累计），产物属于这一次运行。

    `budget_usd` 是"这一次运行"的额度（`G-4`），不是工作区的累计额度。
    本次花销的口径（`F5-FOUND-1` 之后）：按 `task_id` 过滤 `usage_ledger`
    （这次运行的所有调用共享开跑时取到的那个 `task_id`），所以同一个工作区里
    并发的另一次运行不会被算进我的额度，历史花销也不会。

    改前的口径是"工作区增量"：开跑时取一次整本台账的和当基线，之后判
    `spent() - baseline`。那个近似只在"同一工作区里两次运行不可能重叠"时
    等于本次花销 —— `R5-AN-1` 把并发修通之后它不再成立（别人的钱落进我的差额，
    既可能让我提前熔断，也会让对账自检误报）。逐字读数与论证见
    `_spent_this_run` 的 docstring。

    两个口径都在产物里：`spent_usd_this_run` 是本次运行（按 `task_id` 过滤），
    `cost.json` 的 `usage_ledger.usd` 与返回值里的 `spent_usd` 是工作区累计。
    只印一个数会让"这次花了多少"与"这个工作区一共花了多少"无法分辨。

    `now` 只为测试注入固定时间戳（不注入就是当前时间）：可复现的产物才好逐字断言。
    `search_fn` / `quote_fn` / `fetch_fn` / `extract_fn` 是四个动作的测试接缝
    （生产为 `None`，分别走禁改区里的 `providers` / `quoteverify` / `fetch` / `extract`）；
    `retrieval_limit` 与 `retrieval_timeout_sec` 只影响检索本身，不改变三态判定。

    `fulltext` 控制要不要拿开放全文，缺省关闭：全文获取是逐条的网络下载，
    默认打开会让每一次运行都变成一次批量下载。关闭时 `fulltext` 会如实写进
    未接线清单，且理由串按"这一次"改写（"本次没有发起全文获取（`--fulltext` 默认关）"，
    与 `lean` 那条同形）—— 常量里那句"没有接进本流程"是关于流程的断言，
    而真相是"接了、本次没要"，两句话的处置不同（`X-NEW-2` / `draft/28` §98.4）；
    它也与打开后逐条六态记录（`no_pdf` / `download_failed` / ...）是两件事。

    `lean` 控制要不要真的跑 Lean 检查，缺省关闭。打开后：模型答复里每一个
    `` ```lean `` 代码块都会被交给 `formalgw.check_lean` 真跑一次，逐条结论与
    实际到达的证据等级写进 `claims.json` 的 `lean` 段与报告的形式化验证小节。
    这一层是 `evidence_kind="proof"` 的唯一来源 —— 所以它默认关、并且在真的
    跑过之前不许把 lean 从"未接线"清单里摘掉。`lean_run_fn` 是它唯一的测试接缝。

    `claims_parse_fn` 与 `claims_max` 是拆分层的两个旋钮。`claims_parse_fn`
    缺省 `None`（纯启发式拆分，同一答复必得同一结论）；注入它是"让模型协助
    拆分"，但注入的那个函数只提供候选 —— 编号、去重、截断与指纹仍由
    `claims.split_claims` 决定，且用没用它写进产物。`claims_max` 是断言上限，
     超出部分会被截断，而截掉的条数会写进 `claims.json`、清单与 unknowns。
    为什么上限要能被调用方收紧：一次运行里"只看前 N 条"是常见需求，
    而静默截断会让"登记了 200 条"读成"一共只有 200 条"。

    两种"没查成"都不调模型、直接以退出码 2 结束：环境里没有模型 key，
    或检索没查成。理由是同一条 —— 这次运行的产物本该由"材料 + 逐字引文"支撑，
    缺了其中任何一半，跑下去只会得到无法回验的结论。全文获取失败「不改」退出码：
    摘要在手上就还能回验（只是级别停在摘要级），那是一次有效产出。
    拆分没成（`no_claims` / `unparsable`）同样不改退出码：它说的是
    "这一层没查成"，处置写在 `claims.json` 与未接线清单里 ——
    与"结论对不对"不是一件事。
    """
    if prompt_version not in PROMPT_VERSIONS:
        raise ValueError(f"未知 prompt 版本 {prompt_version!r}（已知 {PROMPT_VERSIONS}）")
    # `T-7`：本函数的函数体已按段搬进 `_phase_1..6`（只搬位置，一行判据都没改；
    # 等价判据是 `tests/test_runflow_snapshot.py` 的冻结快照 + `temp/_t7_verify.py`
    # 的"代码行多重集相同"）。这六段的对应关系就是"取材料 / 跑模型 / 落产物"三段的细分：
    #   1 定工作区与这一次的账（出目录 / 时间戳 / 取号 / 价格表）
    #   2 起手：系统提示词、计量器、未接线清单、调用记录表
    #   3 取材料 → 跑模型 → 逐字回验（最长的一段，含"没 key / 检索没查成"两条早退）
    #   4 收工：`tasks` 行写终态 + 与 `usage_ledger` 对账
    #   5 拢出六件产物的内容（清单 / 抄本 / 证据 / 断言 / 账 / 报告）
    #   6 写盘：先写"事实"，最后写人读报告
    _idem_scope, cfg, out, price, stamp, started_at, task_id = _phase_1(max_calls, now, out_dir,
        spec, store, topic)
    acquisition, base_prompt, meter, not_wired, reason, records, sent_prompt, stopped_by, transcript = _phase_2(budget_usd,
        prompt_version, store, topic)
    acquisition, evidence, lean_doc, not_wired, reason, sent_prompt, split_result, stopped_by, successes, verification = _phase_3(_idem_scope,
        acquisition, base_prompt, budget_usd, cfg, claims_max, claims_parse_fn, extract_fn,
        fetch_fn, fulltext, lean, lean_run_fn, max_calls, meter, not_wired, out, quote_fn, reason,
        records, retrieval_limit, retrieval_timeout_sec, search_fn, sent_prompt, stamp, stopped_by,
        task_id, text_store_dir, topic, transcript, transport)
    calls_usd, exit_code, ledger, reconciled, run_entries, run_spent_usd, run_tokens, task_row_error, task_row_written = _phase_4(meter,
        reason, records, stamp, started_at, store, successes, task_id, topic)
    claims, cost, evidence_doc, manifest, report = _phase_5(acquisition, base_prompt, budget_usd,
        calls_usd, cfg, evidence, exit_code, fulltext, lean_doc, ledger, max_calls, not_wired,
        price, prompt_version, reason, reconciled, records, run_entries, run_spent_usd, run_tokens,
        sent_prompt, split_result, stamp, started_at, stopped_by, successes, task_id,
        task_row_error, task_row_written, topic, verification)
    _phase_6(claims, cost, evidence_doc, manifest, out, report, transcript)
    return {
        "exit_code": exit_code,
        "reason": reason,
        "out_dir": str(out),
        "artifacts": list(ARTIFACTS),
        "calls": len(records),
        "spent_usd": ledger["usd"],
        # `G-4`：本次运行的增量（预算判的是它）。`spent_usd` 保留累计口径，
        # 两个键并存是刻意的 —— 调用方要能分辨"这次花了多少"与"这个工作区一共花了多少"。
        "spent_usd_this_run": run_spent_usd,
        "budget_exhausted": _is_exhausted(budget_usd, run_spent_usd),
        "reconciled_with_usage_ledger": reconciled,
        # 三态与台账摘要也回传一份：调用方（CLI/脚本）不必再去读产物文件才能
        # 知道"这次检索到底查了没有"。它们是同一份事实的第二个出口，不是第二份计算。
        "retrieval_status": evidence["status"],
        "claims": dict(verification["counts"]),
        # 形式化验证的摘要（与清单里的那一份同源）。
        "lean": {
            "enabled": lean_doc["enabled"],
            "ran": lean_doc["ran"],
            "proved": lean_doc["proved"],
            "evidence_kind": lean_doc["evidence_kind"],
            "reason": lean_doc["reason"],
        },
    }


# ---------------------------------------------------------------------- 自检


def _reply_body(text: str = "4", tokens_in: int = 11, tokens_out: int = 3) -> str:
    """OpenAI 兼容的成功应答（离线自检用）。"""
    return json.dumps({
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out},
    }, ensure_ascii=False)


def selftest() -> int:
    """离线自检：六件产物齐备、记账与账本一致、没 key 时退出码 2、回验负控成立。

    为什么要有它：端到端的"跑通了"最容易变成一句口号 ——
    这里用 tempfile 里的一次真实运行（假传输层 + 假检索 + 假回验，全程不联网）
    把它变成可判定的断言。检索与回验必须也注入假的：不注入就会去打真实网络，
    而"自检"这个词的全部意义就是它能在没有网络、没有 key 的机器上跑。

    第三条运行是回验的负控：模型给的引文在材料里不存在 ⇒ 台账必须是 not_found。
    一条编造的引文如果能从这条自检底下走过去，那么"逐字回验"就只是报告里的一句话。
    """
    import tempfile

    from .store import Store

    problems: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        st = Store(root / "ws")
        st.init()

        def _fake(status: int, body: str):
            def _t(url: str, headers: Mapping[str, str], data: bytes, timeout_sec: float):
                return status, body

            return _t

        abstract = "An abelian group is a group in which the commutative law holds."

        def _search(topic: str, *, limit: int, timeout_sec: float):
            return [{"source": "selftest", "title": "Abelian groups", "year": 1930,
                     "doi": "10.1000/selftest", "abstract": abstract}]

        ok = run_topic(
            st, topic="阿贝尔群", budget_usd=1.0, out_dir=root / "ok",
            transport=_fake(200, _reply_body(
                f"- 阿贝尔群是交换群 || {abstract}")),
            spec=ModelSpec(api_key="selftest-key"), max_calls=1,
            search_fn=_search, now="2026-01-01T00:00:00+00:00",
        )
        if ok["exit_code"] != 0:
            problems.append(f"成功路径的退出码应为 0：{ok}")
        missing = [a for a in ARTIFACTS if not (root / "ok" / a).exists()]
        if missing:
            problems.append(f"成功路径缺少产物：{missing}")
        cost = json.loads((root / "ok" / "cost.json").read_text(encoding="utf-8"))
        if not cost["reconciled_with_usage_ledger"]:
            problems.append(f"cost.json 与 usage_ledger 对不上：{cost['calls_usd']} vs "
                            f"{cost['usage_ledger']['usd']}")
        # G-20 正控：这一跑真的把花销归了口，且归口在产物里读得出来。
        by_scope = cost["usage_ledger"]["by_scope"]
        if by_scope[SCOPE_ANSWER]["entries"] < 1:
            problems.append(f"这一次调用必须落在 {SCOPE_ANSWER!r} 档：{by_scope}")
        if by_scope["search"]["entries"] != 0:
            problems.append("没花过钱的档必须以零值出现（不是缺席）："
                            f"{sorted(by_scope)}")
        if cost["per_call"] and cost["per_call"][0]["scope"] != SCOPE_ANSWER:
            problems.append(f"逐笔也要看得见归口：{cost['per_call']}")
        # 归口只改"分档"，不改"总额"：三档相加必须等于账本总额。
        summed = sum(int(v["tokens"]) for v in by_scope.values())
        if summed != int(cost["usage_ledger"]["tokens"]):
            problems.append(f"分档之和必须等于总额：{summed} != {cost['usage_ledger']['tokens']}")
        led = json.loads((root / "ok" / "claims.json").read_text(encoding="utf-8"))
        if [c["verdict"] for c in led["claims"]] != ["verified"]:
            problems.append(f"存在材料里的引文必须 verified：{led['claims']}")
        if any(n["name"] in ("retrieval", "quote_verify") for n in
               json.loads((root / "ok" / "run-manifest.json").read_text(encoding="utf-8"))["not_wired"]):
            problems.append("检索真的跑过了 ⇒ retrieval/quote_verify 必须从未接线里摘掉")

        # 全文路径的正控与关键负控：正文里有的引文落全文级，只在摘要里的落摘要级。
        in_body = "the identity element is unique"
        body_text = f"In this paper we recall that {in_body} in every group."

        def _fetch(url: str, dest_dir: Path, filename_hint: str):
            path = Path(dest_dir) / "selftest.pdf"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body_text, encoding="utf-8")
            return {"ok": True, "path": str(path), "bytes": len(body_text), "error": None}

        def _extract(path: str):
            text = Path(path).read_text(encoding="utf-8")
            return {"text": text, "pages": [text], "source_kind": "pdf", "encoding": None}

        def _search_ft(topic: str, *, limit: int, timeout_sec: float):
            return [{"source": "selftest", "title": "Abelian groups", "year": 1930,
                     "doi": "10.1000/selftest", "abstract": abstract,
                     "pdf_url": "https://example.invalid/paper.pdf"}]

        ft = run_topic(
            st, topic="阿贝尔群全文", budget_usd=1.0, out_dir=root / "ft", fulltext=True,
            transport=_fake(200, _reply_body(
                f"- 阿贝尔群是交换群 || {abstract}\n- 单位元唯一 || {in_body}")),
            spec=ModelSpec(api_key="selftest-key"), max_calls=1,
            search_fn=_search_ft, fetch_fn=_fetch, extract_fn=_extract,
            now="2026-01-01T00:00:00+00:00",
        )
        ft_led = json.loads((root / "ft" / "claims.json").read_text(encoding="utf-8"))
        levels = [c["level"] for c in ft_led["claims"]]
        if ft["exit_code"] != 0 or levels != ["abstract", "fulltext"]:
            problems.append(f"摘要/全文两级必须分开：{levels} / 退出码 {ft['exit_code']}")
        ft_ev = json.loads((root / "ft" / "evidence.json").read_text(encoding="utf-8"))
        if ft_ev["fulltext_acquisition"]["counts"]["ok"] != 1:
            problems.append(f"全文获取必须记成 ok：{ft_ev['fulltext_acquisition']}")
        ft_md = (root / "ft" / "report.md").read_text(encoding="utf-8")
        if "摘要级 1 条；全文级 1 条" not in ft_md:
            problems.append("报告证据段必须分别给出摘要级与全文级的条数")
        if any(n["name"] == "fulltext" for n in
               json.loads((root / "ft" / "run-manifest.json").read_text(encoding="utf-8"))["not_wired"]):
            problems.append("全文获取真的跑过了 ⇒ fulltext 必须从未接线里摘掉")

        fake = run_topic(
            st, topic="编造引文", budget_usd=1.0, out_dir=root / "fake",
            transport=_fake(200, _reply_body("- 这句是编的 || 材料里根本没有这句话")),
            spec=ModelSpec(api_key="selftest-key"), max_calls=1,
            search_fn=_search, now="2026-01-01T00:00:00+00:00",
        )
        bad = json.loads((root / "fake" / "claims.json").read_text(encoding="utf-8"))
        if fake["exit_code"] != 0 or [c["verdict"] for c in bad["claims"]] != ["not_found"]:
            problems.append(f"编造的引文必须 not_found：{bad['claims']}")

        nk = run_topic(
            st, topic="没有 key", budget_usd=1.0, out_dir=root / "nk",
            transport=_fake(200, _reply_body()), spec=ModelSpec(api_key=""), max_calls=3,
        )
        if nk["exit_code"] != 2 or nk["reason"] != "no_key":
            problems.append(f"没 key 时应当是 2/no_key：{nk}")
        man = json.loads((root / "nk" / "run-manifest.json").read_text(encoding="utf-8"))
        if not any(n["name"] == "model" for n in man["not_wired"]):
            problems.append("没 key 时清单里必须把 model 列进 not_wired")
        if not any(n["name"] == "retrieval" for n in man["not_wired"]):
            problems.append("没 key 时没有发起检索 ⇒ retrieval 必须仍在未接线清单里")

    for p in problems:
        print(f"  [FAIL] {p}")
    print(f"[runflow] 自检：成功={ok['exit_code']} / 编造引文={fake['exit_code']} / "
          f"没 key={nk['exit_code']}（{nk['reason']}）/ 全文={ft['exit_code']}"
          f"（级别 {[c['level'] for c in ft_led['claims']]}）")
    if problems:
        return 1
    print("[runflow] 六件产物齐备，账本自洽，编造的引文落 not_found，"
          "摘要级与全文级分得开，没 key 时如实退出码 2")
    return 0


def flow_main(argv: Any = None) -> int:
    """入口：目前只有自检。刻意不叫 `main`（`cli.main` 才是对外的唯一命令入口）。"""
    return selftest()


if __name__ == "__main__":
    raise SystemExit(flow_main())

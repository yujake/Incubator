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

每一轮调用之前判"已花是否已达 budget_usd"，达了就停并落 `budget_exhausted`。
顺序不能反：先调用后检查意味着最后一次调用可以任意超预算，而"预算"这个词
在那一次上就变成了"建议"。

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

import json
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
PROMPT_VERSIONS: tuple[str, ...] = ("v1",)


def prompt_for(topic: str, version: str = "v1") -> str:
    """按版本号造 prompt。未知版本号不是回退到默认，而是显式拒绝。

    为什么：静默回退会让清单里的 `prompt_version` 与真实用的 prompt 不一致 ——
    那是一份说谎的运行记录，比没有记录更坏。
    """
    if version not in PROMPT_VERSIONS:
        raise ValueError(f"未知 prompt 版本 {version!r}（已知 {PROMPT_VERSIONS}）")
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
            "idempotency_key": idempotency_key(self.task_id, self.index),
            "reply": self.reply.to_dict(),
            "charge": dict(self.charge),
            "usd": self.usd,
            "spent_after_usd": self.spent_after_usd,
        }

    #: 由 `run_topic` 在构造后设置：同一次运行的所有调用共享一个 task_id。
    task_id: str = ""


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


def _ledger_view(meter: TokenMeter) -> dict[str, Any]:
    """账本汇总 + 按角色归口（`cost.json` 必须与它一致，所以只算一次）。"""
    spent = meter.spent()
    return {
        "entries": int(spent["entries"]),
        "tokens": int(spent["tokens"]),
        "usd": round(float(spent["usd"]), 6),
        "attempts": int(spent["attempts"]),
        "by_role": meter.by_role(),
        "retry_overhead": meter.retry_overhead(),
    }


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
               lean: Mapping[str, Any] | None = None) -> str:
    """人读报告。unknowns 段永远存在（没有未知项时也要显式写"本次无未知项"）。

    为什么这是一个独立的函数而不是塞在 `run_topic` 里：这一段是给人读的那一份事实，
    而"没有未知项"这种形态很难在端到端里造出来（本流程总会至少列一条未接线）——
    独立成函数才好在测试里直接把它钉住。

    `evidence` / `verification` 缺省为 `None`：证据段始终出现（哪怕只写一句
    "本次运行没有检索记录"）。段落存在与否是判据，而不能靠"某次运行刚好没有"。
    `lean` 缺省为 `None`：形式化验证小节只在真的开了这一层时出现
    （关着的时候写一整段"没用 Lean"会把证据段变成公告栏）。
    """
    lines = [
        f"# 运行报告：{topic}",
        "",
        f"- 退出码：{exit_code}（0=成功产出 / 1=查过了失败 / 2=没查成）",
        f"- 退出原因：{reason}",
        f"- prompt 版本：{prompt_version}",
        f"- 单价（美元每百万 token）：输入 {price[0]} / 输出 {price[1]}",
        f"- 预算：{budget_usd} 美元；已花：{ledger['usd']} 美元；"
        f"余：{_budget_left(budget_usd, ledger['usd'])} 美元",
        f"- 调用次数：{len(records)}（成功 {sum(1 for r in records if r.reply.ok)}）",
        f"- 账本行数：{ledger['entries']}；token 合计：{ledger['tokens']}；"
        f"重试额外开销：{ledger['retry_overhead']['extra_tokens']} token",
        "",
        "## 逐次调用",
        "",
        "| 序号 | 结局 | 未查成 | tokens_in | tokens_out | 美元 | 累计美元 |",
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
                              quote_fn_name: str = "quoteverify.check_quote") -> dict[str, Any]:
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
        },
        "checked": checked,
        "reason": reason,
    }


def run_topic(store: Any, *, topic: str, budget_usd: float, out_dir: str | Path,
              transport: Transport | None = None, spec: ModelSpec | None = None,
              max_calls: int = 3, prompt_version: str = "v1",
              now: str | None = None, search_fn: Any = None, quote_fn: Any = None,
              retrieval_limit: int = 5, retrieval_timeout_sec: float = 30.0,
              fulltext: bool = False, fetch_fn: Any = None,
              extract_fn: Any = None, lean: bool = False,
              lean_run_fn: Any = None, claims_parse_fn: Any = None,
              claims_max: int = claims_mod.DEFAULT_MAX_CLAIMS) -> dict:
    """跑一次端到端：检索 → 取全文 → 作答 → 逐字回验 → 记账 → 熔断 → 六件产物 → 退出三态。

    返回 ``{"exit_code", "reason", "out_dir", "artifacts", "calls", "spent_usd"}``。

    无论走到哪一步都产出六件产物：一份"因为没 key 所以什么都没写"的目录，
    与"根本没跑"在磁盘上长得一样 —— 而它们必须能分辨。

    `store` 是工作区（`usage_ledger` 的落点）；`out_dir` 是产物的落点。
    两者刻意分开：账本属于工作区（跨运行累计），产物属于这一次运行。

    `now` 只为测试注入固定时间戳（不注入就是当前时间）：可复现的产物才好逐字断言。
    `search_fn` / `quote_fn` / `fetch_fn` / `extract_fn` 是四个动作的测试接缝
    （生产为 `None`，分别走禁改区里的 `providers` / `quoteverify` / `fetch` / `extract`）；
    `retrieval_limit` 与 `retrieval_timeout_sec` 只影响检索本身，不改变三态判定。

    `fulltext` 控制要不要拿开放全文，缺省关闭：全文获取是逐条的网络下载，
    默认打开会让每一次运行都变成一次批量下载。关闭时 `fulltext` 会如实写进
    未接线清单（"没有接进本流程"），而不是让读者以为"取了但没有全文" ——
    它与打开后逐条六态记录（`no_pdf` / `download_failed` / ...）是两件事。

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
    if int(max_calls) < 0:
        raise ValueError(f"max_calls 不能为负（收到 {max_calls}）")

    cfg = spec if spec is not None else spec_from_env()
    price = price_of(cfg)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = now or S.now_iso()
    started_at = stamp
    # 先截断再加前缀：反过来写会把 "run-" 三个字符也吃掉，而 task_id 是幂等键的
    # 输入（同一主题必须永远派生出同一个 task_id，否则幂等会在长主题上静默失效）。
    task_id = "run-" + topic[:110]
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
    records: list[CallRecord] = []
    transcript: list[dict] = []
    reason = ""
    stopped_by = ""

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
                )
                not_wired = [n for n in not_wired if n["name"] != "fulltext"]
            sent_prompt = base_prompt + materials_block(evidence["sources"])
            gw = ModelGateway(cfg, transport=transport)
            for i in range(int(max_calls)):
                spent_before = meter.spent()["usd"]
                # 熔断在调用之前：达线就停，一次都不多花。
                if _is_exhausted(budget_usd, spent_before):
                    reason = "budget_exhausted"
                    stopped_by = "budget"
                    break
                reply = gw.complete(sent_prompt, system=SYSTEM_PROMPT)
                charge = charge_reply(
                    meter, reply, role="modelgw", task_id=task_id,
                    scope="reason", call_index=i,
                    extra_note=f"run_topic:{topic}"[:120], now=stamp,
                )
                spent_after = meter.spent()["usd"]
                rec = CallRecord(index=i, reply=reply, charge=charge,
                                 usd=float(charge["usd"]),
                                 spent_after_usd=round(float(spent_after), 6))
                rec.task_id = task_id
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
    claims_ledger = claims_mod.ledger_rows(
        split_result,
        verify_claims([c.to_dict() for c in split_result.claims],
                      evidence["sources"], quote_fn=quote_fn)["claims"],
    )
    # 这一份台账的形状与 `verify_claims` 的返回值同形（`claims` / `counts` /
    # `check`），所以下游（报告、清单、evidence.json）读数字的代码不用改，
    # 但"判决从哪来"必须写下来：`ledger_rows` 给的判决，不是另算一遍。
    verification = _verification_from_ledger(
        claims_ledger, split_result, evidence,
        quote_fn_name=("injected" if quote_fn is not None else "quoteverify.check_quote"),
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
    exit_code = _exit_code_for(reason, successes=successes)
    ledger = _ledger_view(meter)

    # 产物之间必须自洽：本次实际花掉的（逐次相加）与账本汇总不等，
    # 就说明有一条调用没进账 —— 那正是这一层要抓的形态，不许静默写两份数字。
    calls_usd = round(sum(r.usd for r in records), 6)
    reconciled = abs(calls_usd - ledger["usd"]) < 1e-9

    unknowns: list[str] = [f"{n['name']}：{n['reason']}" for n in not_wired]
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
            "reconciled_with_usage_ledger": reconciled,
        },
        "exit_reason": reason,
        "exit_code": exit_code,
        "stopped_by": stopped_by,
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
        "spent_usd": ledger["usd"],
        "remaining_usd": _budget_left(budget_usd, ledger["usd"]),
        "budget_exhausted": _is_exhausted(budget_usd, ledger["usd"]),
        "price_usd_per_m": {"in": price[0], "out": price[1], "source": "modelcost.price_of"},
        "per_call": [
            {"call_index": r.index, "usage_id": r.charge["usage_id"], "usd": r.usd,
             "tokens_in": r.charge["tokens_in"], "tokens_out": r.charge["tokens_out"],
             "charged": r.charge["charged"], "reason": r.charge["reason"]}
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
    )

    # 落盘顺序：先写"事实"（清单/抄本/证据/台账/账），最后写人读报告 —— 报告里引用的
    # 数字全部来自前面几件，任何一件写失败时都不会留下一份引用不存在数字的报告。
    _write_json(out / "run-manifest.json", manifest)
    _write_text(out / "model-transcript.jsonl",
                "".join(json.dumps(t, ensure_ascii=False) + "\n" for t in transcript))
    _write_json(out / "evidence.json", evidence_doc)
    _write_json(out / "claims.json", claims)
    _write_json(out / "cost.json", cost)
    _write_text(out / "report.md", report)

    return {
        "exit_code": exit_code,
        "reason": reason,
        "out_dir": str(out),
        "artifacts": list(ARTIFACTS),
        "calls": len(records),
        "spent_usd": ledger["usd"],
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

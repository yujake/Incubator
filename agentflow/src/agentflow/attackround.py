# -*- coding: utf-8 -*-
"""F 的"一轮真推理"形态（`draft/39` §3.16 + §3.19 已批准项）—— 纯判定层。

## 这一层解决什么（D15 的根）

真机读数（p6e/p6f）：`attack.step` 第 1 轮逐字返回 `no_change`（"本框架尚未接线自动推理"），
于是 `attack_plans.history` 有行、计划永远推不动。修法是给一轮定死形态：

- 一轮 = 一次全新的 LLM 会话（种子只给：子目标 + history + `best_partial` + 证据包 +
  上一个 `dead_end` 清单）；
- 每轮只能以四种产物之一收尾（不许 `no_change`）：
  `reduction` / `proof` / `counterexample_request` / `dead_end`；
- 每轮必须填策略名（通用数学工具箱里的一个：归约/反证/极值与双重计数/对称性与去同构/
  构造参数族/局部—整体/编码为 SAT-ILP/套用已知定理/小情形搜索找模式）+ "为什么用它"；
- 确实什么都做不了时，也必须落成 `dead_end` 或"缺什么"——那就是三态（`null` + 理由），
  不是 `no_change`。

已批准的加强项（§3.19）在这一层的落点：

| 条 | 落法 |
|---|---|
| 3 反例优先 / 便宜证伪 | `pre_spend_gate()` 先跑一遍确定性检查（I9）：子目标良定义吗、引的引理是不是已作废、预算还剩吗、这条路是不是已经死过 —— 全过才允许花钱 |
| 6 多路并行 | `pick_parallel_routes(n)` 给出 n 个不同策略名（同轮对多个子目标并发派活用） |
| 8 部分结果进台账 | `dead_end` 的 `best_partial` 必填（已证的引理／缩小的范围／排除的法，逐条带 id）—— 只写在散文里不算 |
| #5 禁止项 | F 的证明步骤不许用"易证/显然/trivial/clearly…"这类缝；两条合法出口：写出那一步，或显式声明 `assumption` |
| I16 超预算的诚实阻塞 | `budget_decision()` 在超过上限时给 `too_large`（不许静默截断）；拆子目标是编排方的活，这一层不自己切 |
| I11 依赖的缺陷继承 | `proof` 的每一步引到的命题必须在 `clean_ids` 里（不在 ⇒ 那一步继承缺陷，error） |

## 为什么它是一层纯函数

"一轮该收什么、什么时候才允许花钱、哪一步继承了缺陷"这三件事都不需要模型：
它们是形态与判据。把它们做成纯函数，才能离线、确定性地判（E11/E12/E13 就是这么跑的），
而模型只负责往里填内容。
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, Mapping, Sequence

from . import schema as _S

#: 一轮的四种产物（`draft/39` §3.16）：没有 `no_change` 这一档，它是被修掉的那个形态。
PRODUCTS: tuple[str, ...] = ("reduction", "proof", "counterexample_request", "dead_end")
#: 通用数学工具箱（方法名，不含任何本题的构造或结论）：每轮必填一个。
STRATEGIES: tuple[str, ...] = (
    "归约", "反证", "极值与双重计数", "对称性与去同构", "构造参数族",
    "局部—整体", "编码为 SAT/ILP", "套用已知定理", "小情形搜索找模式",
)
#: F 不许写的"缝"（用户 2026-10-05 口径：F 禁止写"易证/显然/trivial/clearly/it is easy to see"）。
F_BANNED_MARKERS: tuple[str, ...] = (
    "易证", "显然", "trivial", "clearly", "it is easy to see", "无须证明", "显然成立",
)
#: `dead_end` 的受控理由（"这条路死了"也要说清是哪一种死法）。
DEAD_END_REASONS: tuple[str, ...] = (
    "反例", "方法不适用", "缺定义", "缺文献", "缺工具", "超出本轮预算", "需要先证别的命题",
)
#: 一轮里"每一条新子目标"必须带的东西（给不出可检验形式的就是没归约成功）。
SUBGOAL_FIELDS: tuple[str, ...] = ("goal", "testable")

#: 四种产物各自"必填字段"的那一句（提示词直接印它；判据那边 `parse_round` 与它是同一份口径）。
#:
#: 为什么把这几句搬到这里（2026-10-19，mp4-6 的真机读数）：提示词里那四段从前是
#: `agent_f/core.py` 手写的一段字面量，而受控值本身在 `attackround` —— 两处漂了之后
#: 的形态是"模型按提示词写、判据按常量拒"（本模块原来就在注释里写着这条风险）。
#: 现在四档的名字与必填字段都只在这里定义，提示词与重问、拒收消息全部引用它。
#:
#: 顺序是给人的阅读顺序（`reduction` 在最前：它是"这一轮造出新东西"的主档），
#: 与 `PRODUCTS` 的元组顺序不必相同 —— "成员完全一样"由 `selftest()` 与判据钉住。
PRODUCT_SPECS: dict[str, str] = {
    "reduction": (
        "把难题归约成 1–3 条新的、可检验的子目标。要给 `new_subgoals`"
        "（每条 {goal, testable}，两个都非空）与 `reason`。"),
    "counterexample_request": (
        "给一个能判决这条命题的实验请求。要给 `script_spec`"
        "（{criterion, params, expected_bound} 三项都非空）与 `why_it_decides`。"),
    "proof": (
        "给出逐步论证。要给 `steps`（非空数组，每步 {text, cites, assumption}）—— "
        "`text` 是这一步说了什么，`cites` 是它引到的**在册 id**（只许引这一轮列出的那些），"
        "确实没有依据可引时必须把这一步显式声明成前提（`assumption: true`）："
        "**缝是正确的事实变成错误证明的地方**，不许用措辞跳过去。"),
    "dead_end": (
        "这一轮走不下去。要给受控 `reason`（" + "、".join(DEAD_END_REASONS) + " 之一）、"
        "`evidence`（哪一步不行）、`best_partial`（已证的引理／缩小的范围／排除的法，"
        "逐条带 what/ids/why_partial）。"),
}

#: 四种产物在提示词 / 重问 / 拒收消息里的"四选一"写法。
#:
#: 一处定义：成员由 `PRODUCT_SPECS` 的键给出（不另抄一串字面量 —— 抄一遍就多一处会漂，
#: 而这一处漂了的后果正是"提示词说四选一、判据按另外四个值拒"）。
PRODUCT_MENU: str = " / ".join(f"`{name}`" for name in PRODUCT_SPECS)

#: 提示词里的引用纪律（提示词与拒收消息共用这一处口径）。
#:
#: 真机读数（`projects/mp4` 的 `mp4-6` 那趟，计划 `000001` 第 1 轮）：
#: 模型给 `proof` 的一步写了 `cites=["reports/attack-000000.md §A5"]` —— 台账里没有这条
#: （`reports/…md` 是 F 自己写的产物文件，不是台账 id），判据当场拒收（R-03）。
#: 拒收拦得住，但它为什么编没治：`_evidence_digest` 里那句"不在册"只是一条旁注，
#: 而提示词从没把"能引的 id 就这些"摆到它眼前。所以纪律写在这里、id 列表紧挨着它。
#:
#: 前缀清单从 `schema.CITATION_PREFIXES` 现算（2026-10-25）：手抄的那一份里有
#: `conj:` / `plan:` / `req:` 三个假前缀 —— 模型照着写会被写入期拒（`bad_citation_prefix`），
#: 而"提示词教一个判据不认的前缀"不会有任何读数报出来。
_CITATION_PREFIX_LINE: str = " / ".join(f"`{prefix}:`" for prefix in _S.CITATION_PREFIXES)
CITE_DISCIPLINE = (
    "只许引用下面列出的 id（它们现算自台账）—— **没有可引的就不要引**；"
    "要声明前提，就把这一步写成 `assumption: true`。"
    # 2026-10-25（审计 G/H/V/L 其余条）：前缀清单此前手抄了一份
    # （`conj:` / `plan:` / `req:` 三个都不在 `schema.CITATION_PREFIXES` 里）——
    # 现在按真身现算，写死的那一份不再存在。
    "带前缀的写法：" + _CITATION_PREFIX_LINE + "。"
    "**禁止**写 `reports/attack-<plan_id>.md §A5` 这类定位："
    "`reports/…md` 是产物文件，不是台账 id，不许当 id 引（引了就算伪造引用，这一轮当场拒收）"
)

#: 重问提示词里"上一次原文"最多引多少字（超出截断并写明原长 —— 不许静默截断）。
RETRY_QUOTE_CHARS = 400

#: 什么时候该交 `proof`（而不是又交一次 `reduction`）—— 提示词里那一节的唯一正文。
#:
#: ## 为什么需要这一节（真机 sylow3–sylow6 的读数，2026-10-26）
#:
#: 四趟真机里 `attack.step` 的 `action` 一次都不是 `proof`：10 个计划各 1 轮、每轮都是
#: `dead_end`，而 `reports/f-proof-*.md` 0 份、会话里 `## 依赖` 0 次。追下去是两层：
#:
#: ① 工具路径上 F 的推理缝是 `None`（那 10 条 `dead_end` 的 detail 逐字就是
#:    `core.py` 里"本框架尚未接线自动推理"那一支的文案），模型根本没被问过 ——
#:    这一层是装配开关（`--attack-reasoning`），不是判据；
#: ② 即使缝接上了，提示词里也只有"四种产物之一"的清单，没有一条话说清
#:    "论证到什么程度就该交 `proof`"。而第 2 段（每轮至少 3 条新事实）在措辞上只
#:    点名了 reduction 那一类动作，`proof` 又不关闭子目标（FC-22）—— 模型读到的是
#:    "交论证不算推进"。两层叠起来的形态，就是 proof 档从来没有被走过。
#:
#: 所以这一节把出口写成可判定的三条，并显式说明"论证成形就交 proof，别为了凑条数改交
#: reduction"。它是嘱托（不是解析层的门）：门仍然只有 `parse_round` 的必填栏。
PROOF_EXIT_CRITERIA: tuple[str, ...] = (
    "论证已经成形：子目标要的那件事，这一轮能一步步写出来 —— 每一步要么引到本轮可引的"
    "在册 id（写进 `cites`），要么显式声明成前提（`assumption: true`）；不许出现"
    "「易证 / 显然 / trivial」那类缝。",
    "不需要再借一条新引理：如果还缺一条中间命题，那是归约（`reduction`）该交的东西；"
    "已经不缺了，就交 `proof`。",
    "这一轮交 `proof` 本身就算推进：它会被落成 `statements` 一行、写成一份证明手稿"
    "（手稿里那一节 `## 依赖` 由框架按每一步的 `cites` 现渲染，你不必手抄），"
    "不关闭子目标（FC-22）是刻意的 —— 关闭要等 V 的复核。不许为了凑够「3 条新事实」"
    "把一份已经写好的论证降级成又一次归约。",
)


def citable_ids_line(ids: Sequence[str]) -> str:
    """把"本轮可引用的 id"渲染成一句（提示词与拒收消息共用；空列表也要说清"没有"）。

    一处实现的原因：提示词说"只许引这些"、拒收消息说"合法 id 有…" —— 两句话必须指
    同一个列表。各渲染一遍就会漂，而漂的后果是模型照着拒收消息改、下一轮又被拒。
    """
    got = [str(x) for x in dict.fromkeys(str(x).strip() for x in ids) if x]
    if not got:
        return "（本轮一个可引的 id 都没有 —— 不要引；要声明前提就写 `assumption: true`）"
    return "、".join(f"`{x}`" for x in got)


class RoundError(ValueError):
    """这一轮没成形（不是"推理失败"）：产物不在四种里、缺策略名、缺必填栏。

    `illegal` / `controlled` 两格是给调用方的（重问那一层要把"你给的是 X"与
    "只能从这四个里选"逐字带回下一问）：只写在错误消息里的话，调用方拿到的是一段散文，
    没法把它拼成一句"把 X 换成上述四个之一"。
    """

    def __init__(self, message: str, *, illegal: str = "",
                 controlled: Sequence[str] = PRODUCTS) -> None:
        super().__init__(message)
        self.illegal = str(illegal or "")
        self.controlled = tuple(controlled)


def _product_error(shown: str) -> RoundError:
    """`product` 不在四档里 ⇒ 一条可动作的错误：四个合法值 + "你给的是 X" + 唯一出口。

    改前这一处只说 `product 必须是 (...) 之一，收到 'x'`（`no_change` 另有一支只说
    "它正是 D15 要根除的形态"）—— 于是模型知道"错了"、不知道该写什么，重问三次仍然
    交 `{"outcome": "no_change"}`（真机 mp4-6 计划 000002 第 1 轮）。现在四档逐字列出、
    点名它给的是哪个值、并给出唯一出口（`dead_end`）。
    """
    got = str(shown or "").strip()
    what = f"`{got}`" if got else "（空：`product` 字段缺失或为空）"
    subject = f"`{got}`" if got else "那个取值"
    return RoundError(
        f"`product` 只能是四种产物之一：{PRODUCT_MENU} —— 你给的是 {what}。"
        "`no_change` 不是产物、`ok` / `success` / `done` 也不是；"
        "什么都做不了时也要落 `dead_end`（受控理由 + 证据 + `best_partial`）。"
        f"把 {subject} 换成上述四个之一。",
        illegal=got)


#: `product` 缺字段时，从这些键里挑一个"它以为自己在填的产物名"念给调用方（只用于报错文案）。
_PRODUCT_ALIAS_KEYS: tuple[str, ...] = ("outcome", "action", "result", "status")


def _alias_of(got: Mapping[str, Any]) -> str:
    """`product` 缺失时，模型把它写在哪个键上了（`{"outcome": "no_change"}` 就是真机那一份）。"""
    for key in _PRODUCT_ALIAS_KEYS:
        value = str(got.get(key) or "").strip()
        if value:
            return value
    return ""


def retry_note(previous: str, error: str, *, illegal: str = "",
               limit: int = RETRY_QUOTE_CHARS) -> str:
    """不成形之后重问时带给模型的那一段（P3-5 的加强版；真机 mp4-6 的读数）。

    ## 为什么要三件事一起给（缺一件都还是"重问三次仍交 `no_change`"）

    真机读数（`projects/mp4` 的 `mp4-6` 那趟，`--attack-reasoning` 开着）：
    `attack_plans` 计划 `000002` 第 1 轮重问了 3 次，模型每次都交
    `{"outcome": "no_change"}`。这不是"它没读到那句话"—— 判据原话确实在重问提示词里
    （`retry_note = str(exc)`）。缺的是三件别的事：

    1. 受控四档在提示词末尾（先上下文、后词表），重问那一段也不复述它们；
    2. 它看不见自己写了什么（"你上一次不成形"没有指代对象，模型无从对照）；
    3. 没人把"把 `no_change` 换成这四个之一"说成一句可执行的替换动作。

    所以这一段三件事都在：复述四档、逐字引用上一次的原文（截断并写明原长）、
    指名要把那个取值换成四者之一。`illegal` 由 :class:`RoundError` 从解析现场带出来
    （不是回头再解析一遍散文 —— 那样只能是猜）。
    """
    picked = str(illegal or "").strip()
    raw = " ".join(str(previous or "").split())
    if len(raw) > int(limit):
        raw = raw[: max(0, int(limit) - 1)] + f"…（已截断，原长 {len(raw)} 字）"
    subject = f"`{picked}`" if picked else "那个不在四种里的取值"
    return "\n".join([
        f"复述受控词表：这一轮**只能**输出四种产物之一 —— {PRODUCT_MENU}"
        "（`no_change` 不是产物、`ok` / `success` / `done` 也不是）。",
        # 业主 2026-10-19：这一句与主提示词第 2 段同一口径，但同样只是嘱托（不是门）。
        # 为什么要在这里再说一遍：真机上重问 3 次仍交旧形态 —— 只改主提示词那一处，
        # 重问时模型拿到的仍是"换个措辞"的许可。
        "复述推进口径：这一轮**必须产出一批新事实（至少 3 条）**（新的引理/命题、"
        "新的反例族、新的数值界、或一步新的归约）；**只整理不算推进**"
        "（复述已知 / 换措辞 / 重排章节 / 罗列「还需要什么」/ 同一脚本再跑一遍）；"
        "产不出这一批就交 `dead_end` 并写清缺什么。",
        f"你上一次交出来的原文（框架收到的就是这一份，逐字引用）：{raw or '（空）'}",
        f"把 {subject} 换成上述四个之一（{PRODUCT_MENU}）—— 确实什么都做不了就交 "
        "`dead_end`（受控理由 + `evidence` + `best_partial`）。",
        f"上一次不成形的判据原话：{str(error or '').strip()}",
    ])


def parse_round(text: str) -> dict[str, Any]:
    """把 F 那一轮的输出解析成一份成形产物；不成形 ⇒ 抛 `RoundError`（交回重说）。

    三态在这里："这一轮什么都没做出来"必须是 `dead_end`（带理由）——
    旧形态的 `no_change` 会被当不成形打回（它正是 D15 要根除的那个返回值）。

    非法 `product` 的那一档给的是可动作的纠正指引（四个合法值 + "你给的是 X" +
    "把 X 换成上述四个之一"），并把那个值挂在 `RoundError.illegal` 上 ——
    重问那一层要拿它拼"把 `<X>` 换成上述四个之一"（`retry_note`），
    而"再解析一遍错误消息猜它是哪个值"只能是猜（真机 mp4-6：模型把 `no_change`
    填在 `outcome` 里，`product` 整个缺失）。
    """
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?|```$", "", raw).strip()
    start, end = raw.find("{"), raw.rfind("}")
    body = raw[start:end + 1] if (start >= 0 and end > start) else raw
    try:
        got = json.loads(body)
    except ValueError as exc:
        raise RoundError(f"这一轮的输出不是合法 JSON（{type(exc).__name__}: {exc}）") from exc
    if not isinstance(got, Mapping):
        raise RoundError("这一轮的输出必须是对象")
    product = str(got.get("product") or "").strip()
    if product == "no_change":
        raise _product_error("no_change")
    if product not in PRODUCTS:
        # `product` 缺失/写错时，模型常把它填在 `outcome` / `action` 上（`{"outcome": "no_change"}`
        # 就是真机那一份）；两种写法都归到同一档，并把"你给的是哪个值"念出来。
        # 注意：只有在 `product` 本身不合法时才用 `"no_change" in raw` 这条兜底 ——
        # 一份成形的产物里出现这个词（例如 evidence 里引述本提示词）不该被误杀。
        if "no_change" in raw:
            raise _product_error("no_change")
        raise _product_error(product or _alias_of(got))
    strategy = str(got.get("strategy") or "").strip()
    if strategy not in STRATEGIES:
        raise RoundError(f"strategy 必须是通用工具箱里的一个 {STRATEGIES}，收到 {strategy!r}")
    why = str(got.get("why_strategy") or "").strip()
    if not why:
        raise RoundError("why_strategy 必填（这一轮为什么用这一招）—— 只写方法名等于没交代")
    out: dict[str, Any] = {"product": product, "strategy": strategy, "why_strategy": why}

    if product == "reduction":
        goals = got.get("new_subgoals")
        if not isinstance(goals, (list, tuple)) or not (1 <= len(goals) <= 3):
            raise RoundError("reduction 要给 1–3 条新子目标（不多不少：超过三条就是没归约）")
        clean: list[dict[str, str]] = []
        for i, g in enumerate(goals, 1):
            if not isinstance(g, Mapping):
                raise RoundError(f"new_subgoals[{i}] 必须是对象（{SUBGOAL_FIELDS}）")
            missing = [k for k in SUBGOAL_FIELDS if not str(g.get(k) or "").strip()]
            if missing:
                raise RoundError(
                    f"new_subgoals[{i}] 缺 {missing}：给不出可检验形式的新子目标，"
                    "不是一条归约（那种情形落 `dead_end` 并写清缺什么）")
            clean.append({"goal": str(g["goal"]).strip(), "testable": str(g["testable"]).strip()})
        out["new_subgoals"] = clean
        out["reason"] = str(got.get("reason") or "").strip()
    elif product == "proof":
        steps = got.get("steps")
        if not isinstance(steps, (list, tuple)) or not steps:
            raise RoundError("proof 要给逐步论证（steps 非空）")
        out["steps"] = [_clean_step(s, i) for i, s in enumerate(steps, 1)]
    elif product == "counterexample_request":
        spec = got.get("script_spec")
        if not isinstance(spec, Mapping):
            raise RoundError("counterexample_request 要给 script_spec（判据/参数/界的期望）")
        need = ("criterion", "params", "expected_bound")
        missing = [k for k in need if not str(spec.get(k) or "").strip()]
        if missing:
            raise RoundError(f"script_spec 缺 {missing}：没有判据的实验请求，E 没法跑")
        if not str(got.get("why_it_decides") or "").strip():
            raise RoundError("why_it_decides 必填（这个实验凭什么能判这条命题）")
        out["script_spec"] = {k: str(spec[k]) for k in need}
        out["why_it_decides"] = str(got["why_it_decides"]).strip()
    else:  # dead_end
        reason = str(got.get("reason") or "").strip()
        if reason not in DEAD_END_REASONS:
            raise RoundError(f"dead_end 的理由必须是受控值 {DEAD_END_REASONS}，收到 {reason!r}")
        if not str(got.get("evidence") or "").strip():
            raise RoundError("dead_end 必须给证据（哪一步不行）—— 只说'不行'等于没交代")
        partial = got.get("best_partial")
        if not isinstance(partial, (list, tuple)) or not partial:
            raise RoundError(
                "dead_end 的 best_partial 必填（已证的引理／缩小的范围／排除的法，逐条带 id）"
                "—— §3.19 第 8 条：部分结果不许只写在散文里"
            )
        clean_p: list[dict[str, str]] = []
        for i, item in enumerate(partial, 1):
            if not isinstance(item, Mapping) or not str(item.get("what") or "").strip():
                raise RoundError(f"best_partial[{i}] 要有 what（做了什么）")
            clean_p.append({"what": str(item["what"]).strip(),
                            "ids": [str(x) for x in (item.get("ids") or [])],
                            "why_partial": str(item.get("why_partial") or "").strip()})
        out["reason"] = reason
        out["evidence"] = str(got["evidence"]).strip()
        out["best_partial"] = clean_p
    return out


def _clean_step(step: Any, n: int) -> dict[str, Any]:
    """规范化一步证明，并把 #5 的硬禁令与"同段依据"判在这里。"""
    if not isinstance(step, Mapping):
        raise RoundError(f"steps[{n}] 必须是对象")
    text = str(step.get("text") or "").strip()
    if not text:
        raise RoundError(f"steps[{n}] 的 text 为空")
    cites = [str(x) for x in (step.get("cites") or [])]
    is_assumption = step.get("assumption") is True
    hit = [m for m in F_BANNED_MARKERS if m in text]
    if hit and not is_assumption:
        raise RoundError(
            f"steps[{n}] 出现「{'、'.join(hit)}」这类缝。两条**合法出口**（选一条）："
            "① 把这一步**写出来**（给出推导或引到在册的 id）；"
            "② 显式把它声明成前提（`assumption: true`）—— 缝是正确的事实变成错误证明的地方，"
            "不许用措辞跳过去"
        )
    if not cites and not is_assumption:
        # 报错文本只说本层判得到的那件事（`cites` 空不空）。这一层拿不到 store，
        # 判不了"那个 id 在不在册" —— 存在性判据在 `agent_f/core.py` 的 `_foreign_cites`
        # （引用台账里没有的 id ⇒ 那一轮当场拒收，理由里会点名是哪个 id）。
        # 从前这里写的是"既没有引到在册的 id"，那等于承诺了本层没做的判据（CS-4）。
        raise RoundError(
            f"steps[{n}] 既没有给 `cites`（一个引用的 id 都没有），也没有声明成前提"
            "（`assumption: true`）—— 「每一步都要指出依据」是 I10 的最小形态"
            "（引用的 id 在不在册由框架核：查不到时这一轮会被拒收并点名那个 id）"
        )
    return {"n": n, "text": text, "cites": cites, "assumption": is_assumption}


def inherit_defects(round_row: Mapping[str, Any], *, clean_ids: Iterable[str]) -> list[dict[str, Any]]:
    """I11：`proof` 的每一步引到的命题必须在 `clean_ids` 里，否则那一步继承缺陷。

    返回逐条缺陷（空列表 = 干净）。"干净"的口径由调用方给（五元位第 2/3 位为真，或显式
    `assumption`）—— 这一层只做"引用是否落在干净集合里"这一件事，不重复判五元位。
    """
    clean = {str(x) for x in clean_ids}
    out: list[dict[str, Any]] = []
    for step in (round_row.get("steps") or []):
        for cid in (step.get("cites") or []):
            if str(cid) not in clean and not step.get("assumption"):
                out.append({"step": step.get("n"), "ref": str(cid), "kind": "inherited_defect",
                            "detail": f"第 {step.get('n')} 步引了 {cid}，而它不在干净集合里 "
                                      "⇒ 这一步继承那个缺陷（I11）"})
    return out


#: 预算读数读不到时要说的话（P-09 的代码那一半，`draft/44:60`）。
#:
#: 它是"一处口径"而不是"两处措辞"：代码侧（F 写进 `why_strategy` 与返回值的
#: `budget_reading.why`）与提示词侧（`agent_prompts.ROLE_BRIEFS["E"].policy`）
#: 引用的是这一个常量 —— 哪一处被改成别的说法，
#: `tests/test_agent_f_inference.py::test_p09_the_framework_written_why_strategy_carries_the_same_sentence`
#: 就会红。
#:
#: 为什么不能写成"那时按最保守的做法办"（本仓库此前在提示词里就是那个方向）：
#: 读不到不等于不许花。把"读数缺失"折成"全局停摆"是相反的方向，
#: 而且那正是本项目最贵的缺陷形态（把 null 与 0 折成同一个值）。
BUDGET_UNREADABLE_NOTE = (
    "代价读数读不到时如实说读不到；那是「读不到」，不是「没有代价」，"
    "也不因此把所有的路都堵死"
)

#: 读数读不到时，钱由谁管（file:line 证据写成常量，好让"证据"本身可被引用与断言）。
#:
#: - `conductor.py:1063-1077`：`[4a]` FC-19 预算守卫 —— `self._meter_guard(role, budget)`
#:   在写 `running` 行之前跑（顺序是判据的一部分：干完再拒不是同一个功能）；
#: - `policy.py:338-343`：`Refusal("budget_exceeded", …, "usd_budget")` 那一档。
BUDGET_GUARD_NOTE = (
    "钱仍由全局预算守卫管：conductor.py:1063-1077 的 [4a] 开工前守卫"
    "（guard() 在写 running 行之前跑）与 policy.py:338-343 的 usd_budget 判据"
)

#: 预算读数的真源为什么还没接上（缺口登记：不许"永远 unknown 但没人说"）。
#:
#: 缺的上下文是当前这一次召唤的 `task_id`：`conductor.py:1140-1144` 把它交给了后端，
#: `agent_loop.py:2652-2656` 的循环也拿得到，但工具层拿不到 ——
#: `tools/base.py:1304-1313` 的 `ToolRegistry.call` 没有任务上下文的形参，
#: 于是 `tools/attack_tools.py:281-300` 的 `_agent_for(store)` 只有 `store`。
BUDGET_GAP_NOTE = (
    "真源还没接上：工具路径拿不到当前这一次召唤的 task_id"
    "（缺的是这个上下文：tools/base.py:1304 的 ToolRegistry.call 没有任务上下文的形参，"
    "tools/attack_tools.py:281-300 的 _agent_for(store) 只能拿到 store）"
    "⇒ 注入点暂时没有值可注入；它是残余集 R1 的「P-09 粒度口径」的前置"
    "（记账粒度是召唤级：tokenmeter.py:250-286 的 usd_for / usd_reading 都以 task_id 为键）"
)


def pre_spend_gate(*, goal: str, testable: str = "", deps_refuted: Sequence[str] = (),
                   tried_strategies: Sequence[str] = (), budget_left_usd: float | None = None,
                   ) -> dict[str, Any]:
    """花钱之前的确定性闸门（I9 + 已批准的第 3 条：先做便宜的证伪）。

    返回 `{"spend": bool, "reasons": [...], "checks": {...}}`：`spend=False` 时调用方
    不许发模型调用（省下的钱正是这一层要省的）。每一条都是盘上/参数里就有的事实，
    不需要模型参与。
    """
    checks: dict[str, Any] = {}
    reasons: list[str] = []
    checks["goal_nonempty"] = bool(str(goal or "").strip())
    if not checks["goal_nonempty"]:
        reasons.append("子目标为空 ⇒ 先让 D/M 把它说清楚（这一轮不该花钱）")
    checks["testable_given"] = bool(str(testable or "").strip())
    if not checks["testable_given"]:
        reasons.append("子目标没有可检验形式（`testable` 空）⇒ 先落 `needs_evidence` 并写清为什么")
    refuted = [str(x) for x in deps_refuted]
    checks["deps_refuted"] = refuted
    if refuted:
        reasons.append(f"引到的命题里有已被作废/反驳的：{refuted} ⇒ 先把依赖换掉再花这一轮的钱")
    tried = [str(x) for x in tried_strategies]
    remaining = [s for s in STRATEGIES if s not in set(tried)]
    checks["strategies_tried"] = {
        "tried": sorted(set(tried)), "remaining": remaining, "exhausted": not remaining,
        # 代价读数（P-09）：这句话是读数，不是否决 —— 见下面那段边界说明。
        "note": (f"{len(STRATEGIES)} 招里试过 {len(set(tried))} 招、还剩 {len(remaining)} 招"
                 + ("（已穷尽：再试只能是同一批招）" if not remaining else "")),
    }
    # ---- P-09（`draft/44:60`）：计数不否决花钱。
    #
    # 此前这里是 `checks["all_strategies_tried"] = len(set(tried)) >= len(STRATEGIES)`
    # 并把它写进 `reasons` ⇒ `spend=False`。那是"该模型抉择的事被写死成一个死旋钮"：
    # 九招试完该不该再花一轮（换子目标 vs 再试同一批招）是代价判断，不是事实。
    # 现在它只是一条读数（`strategies_tried`：试过哪几招 / 还剩哪几招 / 是否穷尽、
    # 以及一句代价读数），由 F 自己按代价裁量并把裁量写进 `why_strategy`（留痕）。
    #
    # 上面四条检查（空目标 / 没有可检验形式 / 引到已作废的命题 / 预算耗尽）照旧是事实，
    # 仍然 `spend=False` —— 删它们会让"缺定义也去花钱"，那不是同一条裁定管的事。
    checks["budget_known"] = budget_left_usd is not None
    if budget_left_usd is not None:
        checks["budget_ok"] = float(budget_left_usd) > 0
        if not checks["budget_ok"]:
            reasons.append("预算已耗尽 ⇒ 一轮都不许再开（如实写进交付，不许静默截断）")
    return {"spend": not reasons, "reasons": reasons, "checks": checks}


def budget_decision(*, cost_usd: float, cap_usd: float | None, spent_usd: float = 0.0) -> dict[str, Any]:
    """I16：超上限的一轮要显式阻塞（`too_large`），不许静默截断。

    "拆子目标"是编排方（M/D）的活，这一层不自己切 —— 所以它只回一个状态与一句人话，
    让调用方把它如实写进计划历史。
    """
    if cap_usd is None:
        return {"status": "unbounded", "note": "没有上限：按调用方自己的预算四键管"}
    projected = float(spent_usd) + float(cost_usd)
    if projected > float(cap_usd):
        return {"status": "too_large",
                "note": (f"这一轮预计 ${projected:.4f} 超过上限 ${float(cap_usd):.4f} ⇒ "
                         "如实阻塞（`too_large`），**不截断**这一轮；要拆子目标请找 M/D —— "
                         "拆解是编排方的活，不是 F 的"),
                "projected_usd": round(projected, 6)}
    return {"status": "ok", "projected_usd": round(projected, 6)}


def pick_parallel_routes(n: int, *, tried: Sequence[str] = ()) -> list[str]:
    """已批准的第 6 条：同轮跑不同策略的多路（先挑没试过的），避免"多路=同一招三遍"。"""
    want = max(0, int(n))
    tried_set = {str(x) for x in tried}
    fresh = [s for s in STRATEGIES if s not in tried_set]
    return (fresh or list(STRATEGIES))[:want]


def dead_end_row(*, strategy: str, reason: str, evidence: str,
                 best_partial: Sequence[Mapping[str, Any]],
                 why_strategy: str = "") -> dict[str, Any]:
    """造一条成形的 `dead_end` 产物（走同一套判据 —— 一处校验，不手搓 dict）。

    为什么要有这个构造器（`draft/39` §6.14 的接线）：F 的 `step` 里有几条收尾路径
    （没有 owner 侧的推理入口、没有可推进的子目标、预算用尽）本来就是"这一轮没有新事实"，
    而它们此前只写一个 `outcome="no_change"` —— 没有产物。按 §3.16，那种情形必须落成
    `dead_end`（受控理由 + 证据 + `best_partial`），于是"这一轮到底交了什么"可查。
    """
    payload = {"product": "dead_end", "strategy": strategy,
               "why_strategy": (why_strategy
                                or "这一步走不下去：没有可调用的推理入口或没有可推进的子目标"),
               "reason": reason, "evidence": evidence,
               "best_partial": [dict(x) for x in best_partial]}
    return parse_round(json.dumps(payload, ensure_ascii=False, default=str))


def selftest() -> int:
    """最小自检：四产物可解析、`no_change` 打回（含写在 `outcome` 里的那一份）、
    #5 两条合法出口、闸门与预算阻塞、以及"提示词/重问/报错共用同一份四档口径"。"""
    checks: list[tuple[str, bool]] = []
    red = parse_round(json.dumps({"product": "reduction", "strategy": "归约",
                                  "why_strategy": "先缩小范围",
                                  "new_subgoals": [{"goal": "证 n=3", "testable": "枚举"}]}, default=str))
    checks.append(("reduction 成形", red["product"] == "reduction"))
    checks.append(("四档口径一致（PRODUCT_SPECS 与 PRODUCTS 同一组成员）",
                   set(PRODUCT_SPECS) == set(PRODUCTS)))
    try:
        parse_round('{"product": "no_change", "strategy": "归约", "why_strategy": "x"}')
        checks.append(("no_change 被打回", False))
    except RoundError:
        checks.append(("no_change 被打回", True))
    try:
        parse_round('{"outcome": "no_change"}')
        checks.append(("no_change（写在 outcome 里）被打回并给出四档", False))
    except RoundError as exc:
        checks.append(("no_change（写在 outcome 里）被打回并给出四档",
                       all(f"`{p}`" in str(exc) for p in PRODUCTS)
                       and "你给的是" in str(exc) and exc.illegal == "no_change"))
    note = retry_note('{"outcome": "no_change"}', str(RoundError("x")), illegal="no_change")
    checks.append(("重问复述四档 + 引用上一次原文 + 指名替换",
                   all(p in note for p in PRODUCTS)
                   and '{"outcome": "no_change"}' in note
                   and "换成上述四个之一" in note))
    checks.append(("可引用 id 的空列表也有话说（反真空）",
                   "不要引" in citable_ids_line([]) and "`exp:1`" in citable_ids_line(["exp:1"])))
    bad = json.dumps({"product": "proof", "strategy": "反证", "why_strategy": "反设",
                      "steps": [{"text": "显然成立"}]}, default=str)
    try:
        parse_round(bad)
        checks.append(("#5 缝被打回", False))
    except RoundError as exc:
        checks.append(("#5 缝被打回（并给两条出口）", "合法出口" in str(exc)))
    ok = parse_round(json.dumps({"product": "proof", "strategy": "反证", "why_strategy": "反设",
                                 "steps": [{"text": "显然成立", "assumption": True}]}, default=str))
    checks.append(("声明成前提即合法", ok["steps"][0]["assumption"] is True))
    gate = pre_spend_gate(goal="证 n=3", testable="枚举", deps_refuted=["stmt:0007"])
    checks.append(("作废依赖 ⇒ 不花钱", gate["spend"] is False and gate["reasons"]))
    checks.append(("超预算 ⇒ too_large",
                   budget_decision(cost_usd=2.0, cap_usd=1.0)["status"] == "too_large"))
    checks.append(("多路挑没试过的", pick_parallel_routes(2, tried=["归约"])[:2] != ["归约", "归约"]))
    for name, good in checks:
        print(f"  [{'PASS' if good else 'FAIL'}] {name}")
    return 0 if all(g for _, g in checks) else 1


if __name__ == "__main__":  # pragma: no cover - 自检入口
    raise SystemExit(selftest())

"""LLM 驱动的角色循环：模型决定调哪个工具、唤起谁、给谁留言，框架负责执行与留痕。

## 这一层补的是哪一个洞

`draft/28` §178 的实测：A-H 里六个角色一份提示词都没有，C 两处、D 一处钩子；
更根本的是，角色之间没有一条"由模型决定"的协作路径 —— `Conductor.summon`
是给编排层用的（`run_plan` 拿一份写死的计划去跑），而不是给模型用的。
于是"互相唤起"这件事在系统里从来没有发生过：它只发生在脚本里。

这一层把三件事接起来：

1. 提示词（`agent_prompts`）：模型知道自己有哪些工具、该做什么、能跟谁协作；
2. 模型缝（`llmseam`）：每次调用都带版本与哈希落档，没接线/超预算/坏 JSON 分得开；
3. 工具与召唤（`ToolRegistry.call` 与 `Conductor.summon`）：模型说的每个动作都过既有的
   权限面与策略闸门，被拒的理由原样回到模型手里。

## 四种形状（与提示词里的循环协议逐字对应）

- `{"tool": ...}`   → 走 `ToolRegistry.call(name, role=...)`，角色面不对就 `role_denied`；
- `{"summon": ...}` → 走 `Conductor.summon(..., by=<本角色>)`，边/深度/扇出/预算全由策略判；
- `{"message": ...}` → 追加一条 `agent_message` 事件（持久），收件人下次运行时在收件箱里看到；
- `{"final": ...}`  → 收工，带它自报的证据 id。

## 三态与"不许静默"

- 没接线（没有 key）：整个循环不发起任何请求，`stop_reason="not_wired"`，并落一条记录；
- 模型返回坏 JSON：计数，「连击」超过上限就停（`stop_reason="bad_json_limit"`），不静默当空；
  总数（`run.bad_json`）与连击（`run.bad_json_streak`）分开记 —— 停不停的判据是连击（§68）；
- 工具参数不是合法 JSON（`judge_bad_args`）：「另计一个数」（`run.bad_args`），
  连击超过上限停成 `bad_args_limit`（§65）—— 它交回工具层就能改对，不是"形状漂移"；
- 工具被拒 / 召唤被拒：结果里带原因码，并且原样回给模型（那是一次纠正，不是失败）；
- 步数或预算耗尽：停，并把 `stop_reason` 如实写进运行记录。

## 消息传递的投递语义

消息落进项目会话记录（`sessions.append`，不新增表）。收件人"读过哪些"用一个
`agent_inbox` 事件登记（append-only）：某条消息只要出现在过任何一条针对该角色的
`agent_inbox` 事件里，就算已投递。于是"投递"是可复算的，而不是靠内存里的一个集合。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import agent_prompts as AP
from . import capabilities as C
from . import policy as P
from . import schema as S
from . import sessions as SS
from . import userio as U
from . import llmseam as LL
from .llmseam import LlmSeam

#: 循环允许的形状（与 `LOOP_PROTOCOL` 逐字对应；多一个少一个都要改两处）。
#:
#: `summon_many`（2026-09-30 加）是并发派活：一次说一批目标，框架按写集分波、
#: 同波并发跑（`Conductor.run_plan` → `scheduler.run_waves`），结果按输入顺序回来。
#: 为什么让它进协议而不是只做一个 M 的工具：真机实测里模型自己就试过
#: `{"summon_many": …}`（被判"认不出的形状"，白扔两步），而且"像主控的 subagent"
#: 这句话对角色同样成立 —— 一批文献分给几个自己去读，是每个角色都会遇到的事。
SHAPES = ("tool", "summon", "summon_many", "message", "handoff", "note", "ask_user", "final")

#: 扁平形态的别名表：`(规范形状, 必须同时出现的键, 留痕标签)`（`draft/37` §68）。
#:
#: 这些键集来自「提示词里那个原生函数面」（`framework_summon(role=…, action=…, params=…)`、
#: `framework_summon_many(targets=[…])`）。第十二趟真机第 13 步里，模型把 `framework_summon`
#: 的实参直接当成一句话写了出来 —— 没有 `summon` 这个外层键 —— 整趟运行因此以
#: `bad_json_limit` 收场。收下它的判据与 §61 逐字相同：「这组键没有第二种含义」
#: （`role`+`action` 只可能是召唤；`targets` 只可能是批量召唤），而拒收的代价是整趟作废。
#:
#: 只登记这两个：`ask_user` / `note` / `message` 的扁平形态今天没有真机证据，
#: 而且它们的键（`question` / `text` / `to`）更容易与将来的工具参数撞名 ——
#: 有读数再加，不预先放宽。
FLAT_SHAPE_ALIASES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("summon", ("role", "action"), "role"),
    ("summon_many", ("targets",), "targets"),
)

#: 这些拒绝理由 ⇒ 自动转成"请主控代唤"的申请（2026-09-30）。
#:
#: `forbidden_edge`：目标不在 `capabilities.ALLOWED_EDGES` 里（例如 G 想找 A 要文献）；
#: `depth_exceeded`：召唤链已经到 `policy.max_depth`。两者都是"这条路今天不通"，
#: 而不是"我参数写错了" —— 参数错（`invalid_params`）该自己改，越权不该重试。
RELAY_REFUSALS: frozenset[str] = frozenset({"forbidden_edge", "depth_exceeded"})

#: 代唤申请的留言标题（机器可识别的那一位；改它要同时改提示词里的同一句）。
RELAY_SUBJECT = "请代唤"

#: 每一步最后读到的那段输出契约（`draft/28` §195）。
#:
#: 为什么要在最后一行重述一遍：系统提示词有 6k+ token，循环协议埋在中间；
#: 真机实测（2026-09-30，M 做"核验定理与引理的证明"）—— 模型连着三次回 1400–2400 字的散文，
#: `judge_bad_json` × 3 ⇒ `bad_json_limit`，那次运行对交付物零贡献。
#: 它不是不听指令，是没读到：中间那句"请只输出一个 JSON 对象"离它的回答太远了。
JSON_TAIL = (
    "只回一行 JSON（不要解释、不要 Markdown 围栏、不要前后缀）。形状取其一"
    "（键名与嵌套层级照抄，`<...>` 是占位符）。**括号数看最后两行**："
    "`tool` 那行只以一个 `}` 结尾；`summon` / `summon_many` / `message` / `ask_user` / "
    "`final` 这几行**本来就以 `}}` 结尾**（嵌套两层）—— 照抄时别再多补一个，"
    "实测最常见的坏 JSON 就是多补一个 `}`：\n"
    '{"tool": "<工具名>", "args": {...}}\n'
    '{"summon": {"role": "A-H", "action": "<动作名>", "params": {...}}}\n'
    '{"summon_many": {"targets": [{"role": "A-H", "action": "<动作名>", "instance": "<可选>"}],'
    ' "why": "<为什么一次派这一批>"}}\n'
    '{"message": {"to": "<伙伴或 #public>", "subject": "...", "body": "..."}}\n'
    '{"handoff": {"to": "<伙伴/M/ALL>", "title": "...", "body": "<markdown 正文>",'
    ' "brief": "<一句话描述>", "refs": ["<前序手稿编号>"]}}\n'
    '{"note": "一句话"}\n'
    '{"ask_user": {"question": "...", "options": ["..."]}}\n'
    '{"final": {"final": "<结论>", "evidence": []}}'
)

#: 公共频道。`message.to` 写它 = 所有人都能收到（说话，而不是派活）。
PUBLIC = "#public"

#: 草稿本目录名：`<项目根>/notes/<角色>.md`。它刻意不在数据面里 ——
#: 于是只读角色（C / H）也能"有手"：写自己的思考不算写数据。
NOTES_DIR_NAME = "notes"

#: 子循环的完整产出落点：`<项目根>/runs/<角色>-<时间戳>-<序号>.json`。
#:
#: 为什么必须落盘而不是塞进召唤结果：真机实测（2026-09-29）M 拿到的 D 的结论被摘要截断，
#: 于是它只能发留言去问 D"把结论正文回传" —— 而 D 的循环早已结束，问也问不回来。
#: 正确做法是把长产出放磁盘、把路径给上游：上游有眼睛（fs.read），自己去读全文。
RUNS_DIR_NAME = "runs"

#: 单个工具结果回给模型时的字符上限（超了按字段截断并写明截了多少）。#:
#: 1200 → 3000 是 2026-09-30 的真机读数逼出来的：三次运行里模型自己的抱怨逐字都是
#: "读数被观测层截断" —— 验收表 10 行、24 条断言台账、253 条 findings，没有一件
#: 装得进 1200 字，于是它把步数花在"换个姿势再读一遍"上。观测窗口比任务需要的读数小，
#: 表现不是"模型笨"，而是"它反复做同一件事"。
#:
#: 3000 → 6000（2026-10-03，第七趟真机的读数）：那一趟 45 步里有 20 步是
#: `fs.read out/paper/main.tex` —— 26 KB / 475 行的主稿按 160 行一段读（约 9 KB）装不进
#: 3000 字，于是它把窗口缩到 60–100 行反复重读，最后报告没写出来（步数用完了）。
#: 6000 = 两倍"一条定理切片"（`test_budget_knobs.STATEMENT_SLICE_CHARS` = 2600）：
#: 一次能装下半篇的连续正文，而代价（每步多一点 token）远小于"重读 20 次"的代价。
RESULT_CHARS = 6000
#: 模型自己那一步说了什么，回显时的上限（够长到能看见自己给的参数没被截成半截路径）。
ECHO_CHARS = 600


def _clip(value: Any, limit: int = RESULT_CHARS) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return text[:limit] + f"…（原文 {len(text)} 字，已截断）"


#: 观测层渲染单个字段时的下限（给最短的那个字段也不能给到 0 字）。
FIELD_CHARS_MIN = 120
#: 落进"审计记录/台账"的字符串上限。观测层给模型看的是预算内的视图，
#: 而记录要的是"他当时到底拿到了什么" —— 这个上限只防"一屏数据把会话文件撑爆"。
#:
#: 别拿会话记录量"模型看到的窗口有多大"（2026-10-03 我在这上面差点读错，
#: 见 `draft/37` §67）：记录里的 `data` 是「审计副本」，它被这一档切到 2000 字
#: （标记是"落档截断"），而模型看到的观测是 `RESULT_CHARS`/`_clip_fields` 那一份。
#: 两者的数不一样，量错了就会得出"RESULT_CHARS 太小"这种反向结论。
RECORD_CHARS = 2000


def _flatten_one_level(result: Mapping[str, Any]) -> dict[str, Any]:
    """把工具结果里那一层 `data` 字典摊平（`data.rows` 这样带前缀）。

    为什么要摊平：工具的 `data` 常常是一个十几个键的字典，而"按字段分配预算"
    只有在这一层才谈得上。摊平之前 `data` 是一个字段，它的尾巴（真机里正是
    `documents` 那一栏 —— 验收表背后的 doc_id）会被整段切掉，而切掉的部分
    恰好是"下一步该派谁"的读数。
    """
    top = list(result.items())
    flat: dict[str, Any] = {}
    for key, value in top:
        if isinstance(value, Mapping) and len(value) > 1:
            for sub, inner in value.items():
                flat[f"{key}.{sub}"] = inner
        else:
            flat[key] = value
    return flat


def _clip_fields(result: Mapping[str, Any], limit: int = RESULT_CHARS) -> str:
    """把一步的结果渲染出来，但逐字段限长，而不是整体切掉尾部。

    为什么不是 `_clip(result)`：真机实测（2026-09-30）E 拿到的是 17849 字节台账的前 1200 字，
    而 `meta`（里面有 `total_bytes` / 续读位置）与同批到达的 `新消息` 都在 JSON 的尾部，
    整体截断正好把它们切掉 ⇒ 模型只知道"内容很长"，不知道"怎么读剩下的"，
    于是连续 14 步重读同一个开头。逐字段限长保证每个键都在，代价是每个键都短一点。

    预算按"便宜的先给满、贵的再平分"来分，而不是等分：等分在两头都错 ——
    一个 `data` 独大的结果（`fs.read`）会被压到 1/5，而十几个键的结果（验收表）
    会把每一栏都压成 120 字。这里先让"放得下的小字段"整份通过，剩下的额度再给大字段平分。
    """
    flat = _flatten_one_level(result or {})
    rendered = {key: (value if isinstance(value, str)
                      else json.dumps(value, ensure_ascii=False, default=str))
                for key, value in flat.items()}
    cheap_cap = max(FIELD_CHARS_MIN, limit // 8)
    cheap = [key for key, text in rendered.items() if len(text) <= cheap_cap]
    big = [key for key, text in rendered.items() if len(text) > cheap_cap]
    left = max(FIELD_CHARS_MIN, limit - sum(len(rendered[key]) for key in cheap))
    per = max(FIELD_CHARS_MIN, left // len(big)) if big else 0
    out: dict[str, Any] = {}
    for key, value in flat.items():
        text = rendered[key]
        budget = len(text) if key in cheap else per
        if len(text) > budget:
            out[key] = (text[:budget] +
                        f"…（该字段原 {len(text)} 字，这里只给了前 {budget} 字 —— 这是**观测层**的截断，"
                        f"不是内容没了；要后面的部分见下面的续读办法）")
        else:
            # 没被截的字段保持原样（结构还在），只有被截的那个退化成"带说明的字符串"。
            out[key] = value
    text = json.dumps(out, ensure_ascii=False, default=str)
    return text if len(text) <= limit * 2 else _clip(text, limit * 2)


def _for_record(result: Mapping[str, Any]) -> dict[str, Any]:
    """落档用的结果视图（长字符串截到 `RECORD_CHARS`，其余原样）。"""
    out: dict[str, Any] = {}
    for key, value in (result or {}).items():
        if isinstance(value, str) and len(value) > RECORD_CHARS:
            out[key] = value[:RECORD_CHARS] + f"…（落档截断，原 {len(value)} 字）"
        else:
            out[key] = value
    return out


def _continue_hint(result: Mapping[str, Any]) -> str:
    """从结果里读出"还要更多怎么办"，写成一句可执行的话。

    没有续读办法时返回空串（不编造）。这是上一个坑的正面：截断必须附带出路，
    否则"少给一点并说清楚"仍然等于"给不出来"。
    """
    meta = result.get("meta")
    if not isinstance(meta, Mapping):
        return ""
    tool = str(result.get("tool") or "该工具")
    if meta.get("next_line") is not None:
        return (f"【续读】{tool} 本次到第 {meta.get('start_line')}–"
                f"{meta.get('start_line', 1) + max(0, int(meta.get('lines_read') or 0)) - 1} 行"
                f"（共 {meta.get('total_lines')} 行）：再调一次 {tool}(path=…, "
                f"start_line={meta['next_line']}) 接着读")
    if meta.get("truncated"):
        return (f"【没读完】{tool} 只读了前 {meta.get('bytes_read')} / {meta.get('total_bytes')} 字节："
                f"要剩余部分就再调一次并给更大的 max_bytes")
    if meta.get("total_lines") and not meta.get("windowed"):
        return (f"【分段】{tool} 这次给的是整段（共 {meta.get('total_lines')} 行）："
                f"要后面的部分再调一次 {tool}(path=…, start_line=N, max_lines=M) —— "
                f"别反复重读同一个开头")
    return ""


def _observe(result: Mapping[str, Any]) -> str:
    """一步的结果 → 模型看得见的那段文本（`data` 可截，`meta` 与续读提示必须到）。"""
    text = _clip_fields(result)
    hint = _continue_hint(result)
    return text + ("\n" + hint if hint else "")


# ---------------------------------------------------------------- 简报行的唯一拼法
#
# 下面四个函数是「一步在 transcript 里长什么样」的「唯一拼法」：循环里 `transcript +=`
# 用的是它们，`resume_transcript(...)`（从会话记录重建续跑用的 transcript）用的也是它们。
#
# 为什么必须只有一处（这是这一版最重要的一条结构要求）：续跑要写进 `run.transcript`
# 的那份简报，必须与当时那一趟逐字一致 —— 否则"续跑"会变成"换一段稍微不同的话
# 接着问"，而模型对同一件事的下一步会因此漂移，且没有任何判据看得见这个漂移。
# 两处各写一份 f-string 的形态，实测只会在第一次有人改文案时对不上（而那时没有测试）。
def _canonical(value: Any) -> Any:
    """把一份结构按键名递归排序（字典的键顺序在落档时被钉死）。

    为什么需要它：`SS.append` 写事件时用的是 `json.dumps(..., sort_keys=True)`，
    所以「从事件读回来」的那份 payload/result 是排好序的，而循环手里那份是模型
    JSON 的原始键序。`_step_line` 两边都要调 —— 于是它在"当时那一份"与"重建那一份"
    之间必须走同一条口径：按键排序。否则"逐字相等"永远差一个键序，
    而那种差异在读差异的人眼里看起来像"内容变了"（实测：重建出来的 `[第 1 步]`
    与当时那一行只是键序不同，判据报的是"没有接着上次那份对话"）。
    """
    if isinstance(value, Mapping):
        return {str(k): _canonical(value[k])
                for k in sorted(value, key=lambda k: str(k))}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


#: 指纹里不算调用身份的键（`draft/37` §140）：`why` 是"我为什么这么做"的自述，
#: 换个说法不该让同一次调用变成"新的"—— T2 第 5 趟 M 写了 14 条近乎相同的 note，
#: 只因为正文里带"第 N 步："这个前缀，§136 的活性判据一次也没响。
PROSE_KEYS: tuple[str, ...] = ("why",)
#: 正文里的"第 N 步"前缀（同上：它是自述里的时间戳，不是调用内容）。
_STEP_PREFIX_RE = re.compile(r"第\s*\d+\s*步[:：]?")


def _strip_step_prefixes(value: Any) -> Any:
    """把字符串里的"第 N 步"前缀抹平成 `第N步`（递归；只对正文形状用）。"""
    if isinstance(value, str):
        return _STEP_PREFIX_RE.sub("第N步", value)
    if isinstance(value, Mapping):
        return {k: _strip_step_prefixes(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_strip_step_prefixes(v) for v in value]
    return value


def _call_key(shape: str, payload: Mapping[str, Any]) -> str:
    """一次调用的"键"：形状 + 参数（规范化 JSON）。用于"这是不是同一次调用"。

    `default=str`：载荷里可能有非 JSON 值（工具层塞进去的对象），
    这一个是判据输入而不是交付面，所以只求"同样的载荷得到同样的键"。
    自述字段（`why`）与正文里的"第 N 步"前缀不参与（见 `PROSE_KEYS` 的理由）。
    """
    clean = {k: v for k, v in dict(payload or {}).items() if k not in PROSE_KEYS}
    if shape in ("note", "message", "handoff"):
        clean = _strip_step_prefixes(clean)
    return json.dumps([shape, clean], ensure_ascii=False, sort_keys=True, default=str)


def _call_reading(result: Mapping[str, Any]) -> str:
    """一步结果的"读数"：规范化 JSON。同样的调用 + 同样的读数 = 没有新事实。"""
    return json.dumps(_for_record(result or {}), ensure_ascii=False,
                      sort_keys=True, default=str)


#: 参数类拒绝的标记（出现在结果里的 `kind`/`refusal_reason`/`detail` 上）——
#: 命中的那一步要把声明的参数表原样回给模型（`draft/37` §140 的协作改进 A）。
_PARAM_REFUSAL_MARKERS: tuple[str, ...] = (
    "invalid_params", "param_error", "参数不合法", "validation_error", "missing_param",
    "unknown_param", "params_invalid", "budget_incomplete", "bad_params",
)


def render_params(schema: Any) -> str:
    """把一份参数 schema 渲染成一行可读的"参数表"（键 / 类型 / 必填 / 枚举 / 说明）。

    为什么要它：模型被拒时唯一能自救的信息就是声明的形状。T2 第 5 趟里
    `D.register_conjecture` 撞了 18 次参数错、`F.create_plan` 撞了 4 次 ——
    而 `testable` / `budget` 当时的声明只有 `{"type": "object"}`（子键一个字没写）。
    这里的渲染与那条修法是同一件事的两半：声明写清 + 被拒时原样回给模型。
    """
    if not isinstance(schema, Mapping):
        return ""
    props = schema.get("properties")
    if not isinstance(props, Mapping):
        return ""
    required = {str(x) for x in (schema.get("required") or [])}
    parts: list[str] = []
    for key, spec in props.items():
        if not isinstance(spec, Mapping):
            continue
        bits = [str(spec.get("type") or "?")]
        if str(key) in required:
            bits.append("必填")
        enum = spec.get("enum")
        if isinstance(enum, (list, tuple)) and enum:
            bits.append("枚举 [" + "/".join(str(x) for x in list(enum)[:8]) + "]")
        if spec.get("description"):
            bits.append(str(spec["description"])[:110])
        parts.append(f"{key}: " + "，".join(bits))
    tail = "（参数表是封闭集合：多传一个键会被拒）" if schema.get("additionalProperties") is False else ""
    return "；".join(parts) + tail


def looks_like_a_param_refusal(result: Any, *, depth: int = 4) -> bool:
    """这一步是不是"参数形状/取值不对"那一类拒绝（递归找标记，只找有限层）。"""
    if depth <= 0:
        return False
    if isinstance(result, Mapping):
        for key in ("kind", "refusal_reason", "detail", "error", "problem"):
            text = str(result.get(key) or "")
            if any(mark in text for mark in _PARAM_REFUSAL_MARKERS):
                return True
        return any(looks_like_a_param_refusal(v, depth=depth - 1) for v in result.values())
    if isinstance(result, (list, tuple)):
        return any(looks_like_a_param_refusal(v, depth=depth - 1) for v in result)
    return False


def _call_brief(shape: str, payload: Mapping[str, Any]) -> str:
    """一句话说清"这一次调用是什么"（给「原地打转」的提醒与收工语用）。"""
    if shape == "tool":
        return f"工具 {payload.get('name')}"
    if shape == "summon":
        return f"唤起 {payload.get('role')}.{payload.get('action')}"
    if shape == "summon_many":
        return f"一批唤起（{len(payload.get('targets') or [])} 项）"
    if shape in ("note", "message", "handoff"):
        return f"一条 {shape}"
    return shape


def _dead_loop_line(*, streak: int, same_reading: int, limit: int, what: str) -> str:
    """「原地打转」那一步的提醒：同调用 + 同读数 ⇒ 这一步没有新事实。

    为什么它必须能从句结果重建（`draft/37` §136 的实现约束）：transcript 有两条产路
    —— 循环里当场 `+=`，以及 `resume_transcript` 从会话记录重建。这段话由
    `_step_line` 渲染（它读的就是那一步的 `result`），所以两条产路逐字同一份；
    写成"循环里另加一句"的形态会在续跑时丢掉这一句，而没有任何判据看得见那个漂移。

    两种措辞分开（`same_reading == streak` 才算"没有新事实"）：读数在变的重问
    （轮询、等状态）是正当的 —— 它不该被说成"原地打转"，但也值得被问一句
    "它还会给你新东西吗"（那是三态纪律：把"没变"与"在变"写清楚，别折成一档）。
    """
    if same_reading >= streak:
        return (f"【没有新事实】同一个形状、同一份参数、同样的读数，这是连续第 {streak} 次"
                f"（{what}）。重复同一次调用不会产生新读数：换参数、换脚本、换子目标，"
                f"或者把「卡在哪」写进 final 收工。连续 {limit} 次这一趟会以 "
                f"`no_progress_limit` 收工 —— 那不是失败，是「这一趟没有往前走」。")
    return (f"【同一个调用】同一个形状、同一份参数连着第 {streak} 次（同一读数连着 "
            f"{same_reading} 次，{what}）—— 读数还在变，所以这不是原地打转。"
            f"但连着问同一件事三次之后，先问自己一句：它还会给你新东西吗？"
            f"不会再给就换做法，或者把「卡在哪」写进 final 收工。")


def _step_line(step: int, payload: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    """一个有效步的简报行：模型说了什么 + 框架执行结果（键序见 `_canonical`）。"""
    return (f"\n\n[第 {step + 1} 步] 你说了：{_clip(_canonical(payload), ECHO_CHARS)}\n"
            f"框架执行结果：{_observe(_canonical(result))}")


def _invalid_line(step: int, problem: str) -> str:
    """一个形状不合法（`_shape_of` 判不出来）的步：请它按协议重说一次。"""
    return f"\n\n[第 {step + 1} 步] 框架：{problem}。请按循环协议重说一次。"


def _payload_line(step: int, shape: str, problem: str) -> str:
    """形状说对了、某个值写错了的那一步（`draft/37` §140）：只改那个值，别换形状。

    为什么与 `_invalid_line` 分开：这两类的处置方向相反 ——
    "认不出形状"要请它回到协议（骨架就在提示词里），
    "值写错了"要请它别动形状、只改那一个字段（换形状会把好不容易走对的一步弄丢）。
    """
    return (f"\n\n[第 {step + 1} 步] 框架：形状我认出来了（`{shape}`），坏的是那个值："
            f"{problem}。请**只改那个字段**再发一次同样形状的一步 —— 不要换形状、"
            f"也不要写解释。")


def _bad_args_line(step: int, detail: str) -> str:
    """工具参数不是合法 JSON 的那一步（`draft/37` §65：交回工具层让它改参数）。"""
    return (f"\n\n[第 {step + 1} 步] 框架：{detail}。"
            "工具名我收到了，坏的是那个参数 —— 把参数写成一个合法"
            " JSON 对象再调用一次（别改调别的工具，也别写解释）。")


def _bad_json_line(step: int, problem: str, detail: str) -> str:
    """整条回复不是可解析 JSON 的那一步（重述输出契约，含骨架）。"""
    return (f"\n\n[第 {step + 1} 步] 框架：你上一条回复不是可解析的 JSON 对象"
            f"（{problem}；{_clip(detail, 240)}）。"
            f"**不要写分析、不要写方案、不要写 Markdown**："
            f"只回一行 JSON。骨架：\n{JSON_TAIL}")


def _opening_transcript(task: str, *, inbox: str, summoned_by: str, task_id: str,
                        depth: int) -> str:
    """一趟循环开头的简报（任务 / 收件箱 / 处境）。

    单独抽出来是为了让 `resume_transcript` 能重建同一段开头：当时那句话里的
    事实（谁发起的、深度多少、台账号）都在 `agent_run_start` 事件里，收件箱那一段
    则按当前盘上的状态现读（续跑本来就该听到新到的留言 —— 见 `resume_transcript` 的说明）。
    """
    return (f"你的任务：{task}\n\n"
            f"你的收件箱：{inbox}\n\n"
            f"你的处境：由 {summoned_by or '（顶层发起）'} 发起，"
            f"召唤链深度 {depth}，台账号 {task_id or '（本次运行未拿到台账号）'}。")


@dataclass(frozen=True)
class LoopStep:
    """循环里的一步：模型说了什么、框架做了什么、结果是什么。"""

    index: int
    shape: str
    payload: Mapping[str, Any]
    result: Mapping[str, Any]
    problem: str = ""

    def to_dict(self) -> dict[str, Any]:
        """落会话记录用的扁平结构（模型说了什么、框架做了什么、结果是什么）。"""
        return {"index": self.index, "shape": self.shape, "payload": dict(self.payload),
                "result": dict(self.result), "problem": self.problem}


@dataclass
class LoopRun:
    """一次角色运行的完整记录（含每一步与提示词审计读数）。"""

    role: str
    task: str
    steps: list[LoopStep] = field(default_factory=list)
    final: str = ""
    evidence: list[str] = field(default_factory=list)
    stop_reason: str = "final"
    prompt_audit: dict[str, Any] = field(default_factory=dict)
    spend: dict[str, Any] = field(default_factory=dict)
    #: 坏 JSON 的「总数」（审计读数：这一趟一共说了几次不是 JSON 的话）。
    bad_json: int = 0
    #: 坏 JSON 的「连击数」：停不停的判据，任何一个有效步都会把它清零。
    #:
    #: 为什么要有这个数（`draft/37` §68 的第十二趟真机）：`max_bad_json` 这条闸门
    #: 一直写着"连续 N 次"，而实现数的是「总数」 —— 于是三次坏回复「散布在 14 步里」
    #: （第 7、11、13 步，中间第 8–10、12 步都成功）也照样把整趟判死，
    #: 而那一趟的模型其实在恢复（坏一次、下一次就写对）。判"它在原地打转"
    #: 需要的读数本来就是连击。措辞与实现必须说同一件事。
    bad_json_streak: int = 0
    #: 参数坏（`judge_bad_args`）的总数与连击数 —— 与 `bad_json` 「分开计」（`draft/37` §65）。
    #:
    #: 为什么分开：DSH 的 `ToolArgsError` 口径是"参数错交回工具层"，
    #: 不是"模型没给出可解析的形状"。折叠成一个计数会让两件处置方向不同的事
    #: 共用一个停止理由：形状漂移要收紧协议（改提示词/骨架构型），
    #: 参数写坏只要把错误交回去让它重说一次 —— 真机里两次 `judge_bad_args`
    #: 就把一趟运行判成 `bad_json_limit` 收场，而它离"改对参数"只差一步。
    bad_args: int = 0
    bad_args_streak: int = 0
    #: 「原地打转」的读数（`draft/37` §136）：这一趟最长的一次
    #: 「同调用 + 同读数」连击（`dead_loop_max`）与"同调用"连击（`same_call_max`）。
    #:
    #: 为什么两个都要：`dead_loop` 是"没有新事实"（判停的判据），
    #: `same_call` 是"一直在问同一件事"（读数不是判据）—— 轮询是正当的
    #: （读数每次都在变），但"同一件事问了 9 遍"这件事应该看得见。
    dead_loop_max: int = 0
    same_call_max: int = 0
    elapsed_sec: float = 0.0
    notes: list[str] = field(default_factory=list)
    #: 这一趟停在等哪个问题（`stop_reason="waiting_for_user"` 时非空）。
    #:
    #: 为什么它是一个独立的字段而不是塞进 `final` 的一句话：人/界面要拿它去对
    #: 待答清单与回答入口（`agentflow answer <qid>`），从一句话里正则抠一个号
    #: 是"看起来能用、迟早漂移"的那类做法。
    waiting_for: str = ""
    #: 这一趟是从第几步接着跑的（0 = 全新开始，>0 = `--resume` 续跑的第几步）。
    resumed_from: int = 0
    #: 这一趟是什么时候开始的（`S.now_iso()` 的形态）。
    #:
    #: 为什么要有它（`draft/37` §125）：`user_stop` 那条判据要的是"本次运行「开始之后」
    #: 收到的那条回答里有没有 STOP" —— 回答是 append-only 的审计面，
    #: 翻到一条上一次留下的 STOP 就停会把之后每一趟都判死。刻意不进 `to_dict()`：
    #: 它是运行内判据的输入，不是交付面（`agent_run_start` 事件里已经有时间）。
    started_at: str = ""
    #: 这一趟最终的那份简报（重建续跑时的逐字对照物）。
    #:
    #: 刻意「不进 `to_dict()`」：那份记录会写成 `runs/*.json` 的产出文件，
    #: 而简报里有整段观测文本（单字段上限 6000 字 × 步数）—— 把它抄进去会让
    #: 审计文件翻几倍，而它本来就是 `agent_step` 事件重算得出来的东西。
    transcript: str = ""

    @property
    def summons(self) -> list[str]:
        """这次运行真的唤起过哪些角色（按发生顺序，可重复）。"""
        return [str(s.payload.get("role") or "") for s in self.steps if s.shape == "summon"]

    @property
    def messages_sent(self) -> list[str]:
        """这次运行给谁发过留言（按发生顺序，可重复）。"""
        return [str(s.payload.get("to") or "") for s in self.steps if s.shape == "message"]

    def to_dict(self) -> dict[str, Any]:
        """一次运行的完整记录（每一步 + 提示词审计 + 用量 + 停止原因）。"""
        return {
            "role": self.role, "task": self.task,
            "steps": [s.to_dict() for s in self.steps],
            "final": self.final, "evidence": list(self.evidence),
            "stop_reason": self.stop_reason, "bad_json": self.bad_json,
            "bad_json_streak": self.bad_json_streak,
            "bad_args": self.bad_args, "bad_args_streak": self.bad_args_streak,
            "dead_loop_max": self.dead_loop_max, "same_call_max": self.same_call_max,
            "waiting_for": self.waiting_for, "resumed_from": self.resumed_from,
            "summons": self.summons, "messages_sent": self.messages_sent,
            "prompt_audit": dict(self.prompt_audit), "spend": dict(self.spend),
            "elapsed_sec": round(self.elapsed_sec, 3), "notes": list(self.notes),
        }


# ------------------------------------------------------------------ 消息
def read_messages(session_root: Path, role: str, *, sid: str | None = None,
                  ) -> tuple[list[dict[str, Any]], list[str]]:
    """读某个角色的收件箱（含未投递标记）。返回 `(消息, 问题)`。"""
    events, problems = SS.read_session(session_root, sid=sid)
    delivered: set[str] = set()
    for event in events:
        if event.get("kind") == "agent_inbox" and str(event.get("role")) == role:
            delivered.update(str(x) for x in (event.get("delivered") or []))
    out: list[dict[str, Any]] = []
    for i, event in enumerate(events, 1):
        if event.get("kind") != "agent_message":
            continue
        to = str(event.get("to"))
        if to != role and to != PUBLIC:
            continue
        if str(event.get("from")) == role:
            continue                     # 自己说的不用再听一遍
        msg_id = str(event.get("msg_id") or f"m{i:04d}")
        out.append({**event, "msg_id": msg_id, "delivered": msg_id in delivered})
    return out, problems


def send_message(session_root: Path, *, sender: str, to: str, subject: str, body: str,
                 reply_to: str = "", sid: str | None = None) -> tuple[str, str]:
    """发一条消息（append-only）。`to=PUBLIC` 是公共频道。返回 `(msg_id, 问题)`。"""
    events, _problems = SS.read_session(session_root, sid=sid)
    seq = sum(1 for e in events if e.get("kind") == "agent_message") + 1
    msg_id = f"m{seq:04d}"
    _path, problem = SS.append(session_root, {
        "kind": "agent_message", "msg_id": msg_id, "from": sender, "to": to,
        "subject": subject, "body": body, "reply_to": reply_to,
        "channel": "public" if to == PUBLIC else "private",
    }, sid=sid)
    return msg_id, problem


def mark_delivered(session_root: Path, role: str, ids: Sequence[str], *,
                   sid: str | None = None) -> str:
    """登记"这些消息已经在这个角色的收件箱里投递过"。返回问题（空串 = 落成）。"""
    if not ids:
        return ""
    _path, problem = SS.append(session_root, {
        "kind": "agent_inbox", "role": role, "delivered": sorted(set(ids)),
    }, sid=sid)
    return problem


def note_path(session_root: Path, role: str) -> Path:
    """这个角色的草稿本路径：`<项目根>/notes/<角色>.md`。"""
    return session_root / NOTES_DIR_NAME / f"{role}.md"


def write_note(session_root: Path, role: str, text: str, *,
               sid: str | None = None) -> tuple[str, str]:
    """往草稿本追加一行。返回 `(路径, 问题)`；问题非空表示没写成。"""
    path = note_path(session_root, role)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"- [{stamp}] {text.strip()}\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)
    except OSError as exc:
        return str(path), f"{type(exc).__name__}: {exc}"
    _p, problem = SS.append(session_root, {"kind": "agent_note", "role": role,
                                           "text": text.strip(), "path": str(path)}, sid=sid)
    return str(path), problem


def notebook_digest(session_root: Path, role: str, limit: int = 6) -> str:
    """草稿本最近几条（进提示词，让"我上一步想过什么"不必靠记忆）。"""
    path = note_path(session_root, role)
    if not path.is_file():
        return "（草稿本还是空的）"
    try:
        lines = [ln.rstrip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError as exc:
        return f"（草稿本读不出来：{type(exc).__name__}: {exc}）"
    return "\n".join(lines[-limit:]) if lines else "（草稿本还是空的）"


def inbox_digest(session_root: Path, role: str, *, sid: str | None = None) -> tuple[str, list[str], list[str]]:
    """收件箱摘要：`(文本, 未投递的 id, 读会话时的问题)`。"""
    messages, problems = read_messages(session_root, role, sid=sid)
    fresh = [m for m in messages if not m.get("delivered")]
    if not messages:
        return "（没有收到留言）", [], problems
    lines: list[str] = []
    for m in messages[-8:]:
        mark = "" if m.get("delivered") else "（新）"
        lines.append(f"- {mark}[{m['msg_id']}] 来自 {m.get('from')}：{m.get('subject')} —— "
                     f"{_clip(m.get('body'), 300)}")
    return "\n".join(lines), [str(m["msg_id"]) for m in fresh], problems


# ------------------------------------------------------------------ 循环
def _sha(text: str) -> str:
    """文本的 sha256（会话记录里给交付物留指纹用；与 `llmseam._sha` 同一个口径）。"""
    import hashlib

    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _shape_of(data: Mapping[str, Any]) -> tuple[str, Mapping[str, Any], str]:
    """把模型的一句输出判成一个形状。判不出来时返回 `("", {}, 原因)`。

    ## 两个「别名形态」（都只改"从哪取键"，不放宽任何校验）

    1. `{"name": …, "args": …}` 是 `{"tool": …}` 的别名（2026-10-03，§61）。
       真机读数（第八、十趟）：模型有时把工具调用写成这个形状 —— 没有 `tool` 这个键。
       它此前被判"认不出的形状（键：['args','name']）"，与真·坏形状一起计进
       `bad_json`，第 3 次就 `bad_json_limit` 收场（第十趟的步 8/12/35）。
       （这与 §65 的 `judge_bad_args` 是两件事：这里坏的是「形状」，
       那里坏的是已被认出的那次调用的「参数」。）
    2. 「原生签名的扁平形态」（2026-10-03，§68 的第十二趟读数）：模型把
       `framework_summon` 的「实参」直接当成一句话写了出来 ——
       `{"role": …, "action": …, "params": {…}}`（那一趟的第 13 步就是这么死的）。
       提示词里那个函数的签名正是这几个键，而"哪些键同时出现"只有一种含义
       （见 `FLAT_SHAPE_ALIASES`）；拒收的代价是整趟作废。

    收下它们的理由同一条：这些键集没有第二种含义，而"名字/签名"这一层本来就有
    歧义空间（带点的真名 vs 广告名，见 `_do_tool`）—— 多认一个写法比让整趟作废便宜。
    留痕照旧：payload 里带 `shape_alias`，所以"这一趟用了别名"在台账上看得见
    （与 `_do_tool` 的 `aliased_from` 同一套做法）。
    """
    rewritten, alias = _unwrap_alias(data)
    if rewritten is not None:
        shape, payload, problem = _decode_shape(rewritten)
        if problem or not shape:
            return shape, payload, problem
        return shape, {**payload, "shape_alias": alias}, ""
    return _decode_shape(data)


def _unwrap_alias(data: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """把别名形态改写成规范形态；返回 `(改写后的 data, 别名标签)`，不是别名就 `(None, "")`。

    歧义一律「不收」：两个扁平别名同时命中（例如 `role`/`action` 与 `targets` 都在）
    返回 `(None, "")`，让它落回"认不出的形状"那条路 —— fail-closed，
    而不是按表里的先后顺序挑一个（那会让"先写哪个键"决定框架执行哪一件事）。
    """
    if [k for k in SHAPES if k in data]:
        return None, ""
    if "name" in data and isinstance(data.get("name"), str):
        # `{"name": …, "args": …}` ⇒ 规范形态 `{"tool": <名字>, "args": …, "why": …}`。
        # `args` 故意「原样」带过去（不做类型检查）：那条校验在 `_decode_shape` 里，
        # 别名不是第二条解码路径 —— 它只把键搬到规范位置。
        return ({"tool": str(data["name"]), "args": data.get("args") or {},
                 "why": str(data.get("why") or "")}, "name")
    matched = [t for t in FLAT_SHAPE_ALIASES if all(k in data for k in t[1])]
    if len(matched) == 1:
        target, _required, label = matched[0]
        return {target: dict(data)}, label
    return None, ""


def _decode_shape(data: Mapping[str, Any]) -> tuple[str, Mapping[str, Any], str]:
    """规范形态的解码：七种形状（`tool` / `summon` / `summon_many` / `message` /
    `ask_user` / `note` / `final`）取其一。别名只负责改写成这里认的形态。"""
    present = [k for k in SHAPES if k in data]
    if len(present) != 1:
        return "", {}, (f"一次只能说一件事：同时出现 {present}" if present
                        else f"认不出的形状（键：{sorted(data)}）")
    key = present[0]
    value = data[key]
    if key == "tool":
        if not isinstance(value, str) or not value:
            return "", {}, "tool 必须是一个工具名字符串"
        args = data.get("args") or {}
        if not isinstance(args, Mapping):
            return "", {}, "args 必须是一个对象"
        return key, {"name": value, "args": dict(args), "why": str(data.get("why") or "")}, ""
    if key == "summon":
        if not isinstance(value, Mapping):
            return "", {}, "summon 必须是一个对象"
        role = str(value.get("role") or "")
        action = str(value.get("action") or "")
        if role not in S.ROLES:
            return "", {}, f"角色名 {role!r} 不在 {S.ROLES} 里"
        params = value.get("params") or {}
        if not isinstance(params, Mapping):
            return "", {}, "summon.params 必须是一个对象"
        return key, {"role": role, "action": action, "params": dict(params),
                     "why": str(value.get("why") or "")}, ""
    if key == "summon_many":
        if not isinstance(value, Mapping):
            return "", {}, "summon_many 必须是一个对象（{\"targets\": [...]}）"
        targets = value.get("targets")
        if not isinstance(targets, (list, tuple)) or not targets:
            return "", {}, "summon_many.targets 必须是一个非空数组"
        clean: list[dict[str, Any]] = []
        for i, item in enumerate(targets):
            if not isinstance(item, Mapping):
                return "", {}, f"summon_many.targets[{i}] 必须是一个对象"
            role = str(item.get("role") or item.get("target_role") or "")
            action = str(item.get("action") or "")
            if role not in S.ROLES:
                return "", {}, f"summon_many.targets[{i}].role={role!r} 不在 {S.ROLES} 里"
            params = item.get("params") or {}
            if not isinstance(params, Mapping):
                return "", {}, f"summon_many.targets[{i}].params 必须是一个对象"
            clean.append({"role": role, "action": action, "params": dict(params),
                          "instance": str(item.get("instance") or ""),
                          "input_key": str(item.get("input_key") or "")})
        return key, {"targets": clean, "why": str(value.get("why") or "")}, ""
    if key == "ask_user":
        if not isinstance(value, Mapping):
            return "", {}, "ask_user 必须是一个对象"
        question = str(value.get("question") or "").strip()
        if not question:
            return "", {}, "ask_user 得有一个 question"
        options = value.get("options") or []
        if not isinstance(options, (list, tuple)):
            return "", {}, "ask_user.options 必须是数组"
        timeout = value.get("timeout_sec")
        if timeout is not None and not isinstance(timeout, (int, float)):
            return "", {}, "ask_user.timeout_sec 必须是数字"
        # 选项两种形状都收（`userio.coerce_option`）：裸字符串是旧形状，
        # 也是 `llmseam.META_FUNCTIONS` 那张函数面 schema 今天唯一广告的形状；
        # `{"label", "description"}` 是新形状（DSH 的选项形状）。
        # 归一化放在这里而不是留给 `ask_user`：这一步的 payload 会被原样落进
        # `agent_step` 事件，事件里当然要存规范形状，否则事后读不出"当时给了什么选项"。
        return key, {"question": question,
                     "header": str(value.get("header") or ""),
                     "options": [U.coerce_option(x).to_dict() for x in options],
                     "multi_select": bool(value.get("multiSelect")
                                          or value.get("multi_select")),
                     "timeout_sec": float(timeout) if timeout is not None else None}, ""
    if key == "note":
        text = value if isinstance(value, str) else str((value or {}).get("text") or "")
        if not text.strip():
            return "", {}, "note 得有一句话可写"
        return key, {"text": text.strip()}, ""
    if key == "message":
        if not isinstance(value, Mapping):
            return "", {}, "message 必须是一个对象"
        to = str(value.get("to") or "")
        # `to` 的合法集合 = 八个角色 ∪ 主控 M ∪ 公共频道。
        #
        # 为什么 M 必须在内（2026-09-30 真机修）：框架自己的代唤通道
        # `_request_relay` 就是用 `to=S.CONDUCTOR_ROLE`（= "M"）发的私聊，
        # 而这里原来只认 `S.ROLES`（A–H，不含 M）⇒ 提示词教角色"直接用 message
        # 发给 M"、角色照做、却被这一行判成 `invalid`。实测（场景 G）G 因此白扔一步：
        # `[5] invalid ⇒ 收件人 'M' 既不是角色也不是 #public`，下一步它改发 #public 才成。
        # 那一步的代价是"一条本来只该主控看到的申请被广播给所有人"，
        # 外加一次纠正 —— 而 `read_messages(role="M")` 本来就收 `to="M"` 的留言。
        #
        # `ALL` 也认（2026-10-05 真机修）：手稿那条通道的约定是"给所有人写 `to="ALL"`"
        # （用户口径：文件名 `…toALL.md`），而这里原来只认 `#public`。实测 T2 第 5 趟：
        # M 写了 `{"message": {"to": "ALL", …}}` ⇒ 被判形状不合法、连着三次
        # ⇒ 那一整段以 `bad_json_limit` 收场（60 秒、一步有效的活都没干）。
        # 同一个概念不许有两个写法：这里把 `ALL` 归一成公共频道，与 `handoff` 对齐。
        if to.strip().upper() == "ALL":
            to = PUBLIC
        if to != PUBLIC and to not in (*S.ROLES, S.CONDUCTOR_ROLE):
            return "", {}, (f"收件人 {to!r} 既不是角色（{S.ROLES}）、也不是主控 "
                            f"{S.CONDUCTOR_ROLE}、也不是公共频道 {PUBLIC}（写 ALL 也认）")
        return key, {"to": to, "subject": str(value.get("subject") or "（无标题）"),
                     "body": str(value.get("body") or ""),
                     "reply_to": str(value.get("reply_to") or "")}, ""
    if key == "handoff":
        # 交接手稿（`draft/37` §134，用户口径）：交接工作前「写一份手稿」（编号由脚本分配），
        # 留言只传编号 + 一句简要描述。
        #
        # 为什么做成一种「循环形状」而不是工具：手稿的文件名要写"谁给谁"
        # （`0007-DtoF.md`），而工具层拿不到调用者的身份（注入的 deps 是装配期的，
        # 不含 per-call 的 role）。循环自己知道 `self.role`，所以这条协议放在这里最自然；
        # 读/列仍然做成工具（不需要身份）。
        #
        # 为什么「由框架」把留言合出来（而不是让模型自己再发一条 message）：
        # 用户原话"就传个编号感觉有点尬，可以再附一句简要描述" —— 摘要取 `brief`
        # （没给就取标题），于是模型只写一次，收件人既知道编号又知道一句话是什么事。
        if not isinstance(value, Mapping):
            return "", {}, "handoff 必须是一个对象"
        to = str(value.get("to") or "")
        if to != PUBLIC and to not in (*S.ROLES, S.CONDUCTOR_ROLE):
            return "", {}, (f"收件人 {to!r} 既不是角色（{S.ROLES}）、也不是主控 "
                            f"{S.CONDUCTOR_ROLE}、也不是 {PUBLIC}（给所有人写 to=\"ALL\"）")
        title = str(value.get("title") or "").strip()
        body = str(value.get("body") or "").strip()
        if not title:
            return "", {}, "handoff 需要 title（索引里靠它认人）"
        if not body:
            return "", {}, ("handoff 需要 body（正文）—— 空手稿是「我交接了」的假证据，"
                            "而这一层存在的全部意义就是可溯源")
        refs = value.get("refs") or []
        if not isinstance(refs, (list, tuple)):
            return "", {}, "handoff 的 refs 必须是编号数组"
        return key, {"to": "ALL" if to == PUBLIC else to, "title": title, "body": body,
                     "brief": str(value.get("brief") or "").strip(),
                     "refs": [str(x) for x in refs],
                     "why": str(value.get("why") or "")}, ""
    final = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return key, {"final": final, "evidence": [str(x) for x in (data.get("evidence") or [])]}, ""


def _summon_key(action: str, params: Mapping[str, Any]) -> str:
    """角色没给 `input_key` 时派生一个确定性键。

    为什么必须有这个兜底（2026-09-30 真机）：角色自己发的 `summon` 形状里没有
    `input_key` 这个字段（形状只有 role / action / params / why），于是那一行落库时
    `input_key=""` ⇒ `verify_tasks` 报 `task_without_input_key`：这条召唤
    结构上无法参与循环检测。实测现场是场景 G 的 `t-0252`（G 自己派 A 去要文献）。

    键的语义是"同一件事"：同一份 `(action, params)` 再要一次就是同一个键 ——
    那正是循环检测要抓的形态（同一条三元组出现在祖先链上即判循环）。
    参数为空时退化成 action 本身（仍然非空、仍然稳定）。
    """
    raw = json.dumps({"action": action, "params": dict(params or {})},
                     ensure_ascii=False, sort_keys=True, default=str)
    return f"{action}@{_sha(raw)[:12]}"


@dataclass
class AgentLoop:
    """一个角色的一次循环。跑完即弃（没有可复用的状态，避免两次运行互相污染）。"""

    role: str
    session_root: Path
    registry: Any
    seam: LlmSeam
    conductor: Any = None
    #: 单次循环最多几步。默认 30（`draft/37` §1.2 的第一条读数）：定 6 的时候，
    #: 一个被驱动的动作连"读完一段正文"都不够 —— 真机实测（2026-10-01）G 的 151 步里
    #: 89 次在读、53 次在写自己的笔记，最后还是没能落盘一处改动；而框架给它的默认是 6。
    #: 步数是"能做完一件事"的最低门槛，不是省钱的旋钮：省钱靠 `usd_budget` 与墙钟。
    max_steps: int = 30
    #: 坏 JSON 的「连击」上限（不是总数 —— 见 `LoopRun.bad_json_streak` 的说明）。
    #: 第十二趟真机（§68）：三次坏回复散布在 14 步里，中间四次都成功，
    #: 而按总数判的那一版把整趟判死了。
    max_bad_json: int = 2
    #: 参数坏多少次才停（`judge_bad_args`，独立的停止理由 `bad_args_limit`）。
    #:
    #: 为什么比 `max_bad_json` 宽：形状漂移是"它没按协议说"，参数写坏是"它说对了
    #: 要调谁、只是那个 JSON 没写对" —— 后者交回工具层就能改对（DSH 的口径），
    #: 所以给它多一次机会，同时仍然保留上限（不设上限等于允许无限重说同一句）。
    max_bad_args: int = 3
    #: 「原地打转」的两道闸（`draft/37` §131 第 2 件事 / §136 的落地）：
    #: 同一个形状、同一份参数、同样的读数连着第几次时点名（提醒），第几次时收工。
    #:
    #: 为什么需要它：T2 第 4 趟真机（`projects/p6d-research-from-zero`）里，
    #: M 连着 9 次调 `conductor.ledger`、8 次调 `conductor.closing`、
    #: 6 次写同一份 `ACCEPTANCE.md`，全是"同调用同读数" —— 那 23 步一次也没有产生
    #: 新事实，而框架当时唯一的闸门是"步数/预算用尽"。步数与预算不是活性判据：
    #: 它们能把一趟跑完，但不能说"你在原地打转"。
    #:
    #: 为什么提醒在 3、收工在 6：3 是"已经重复到不像在办事了"的最低门槛（2 次可能是
    #: 读一遍再读一遍），而 6 给模型留三次改主意的机会。两个数都要能被 `AgentLoop`
    #: 覆盖（`run_role` 不收这两个旋钮 —— 它们是安全阀，不是常规调参面）。
    dead_loop_nudge: int = 3
    max_dead_loop: int = 6
    #: 单次回复的输出上限。网关缺省 4,096 token，而"写完一段 LaTeX + JSON 信封"
    #: 动辄几千 token ⇒ 写稿步会被静默截断（表现是 `judge_bad_json` 或半句话）。
    #: 8,192 是 `deepseek-chat` 一档的输出上限；要改就改这里，别在各处传不同的数。
    max_output_tokens: int = 8192
    workspace_root: str = ""
    sid: str | None = None
    token: Any = None
    store: Any = None
    #: 「用户叫停」的开关文件（`draft/37` §125）。空串 = 不在步循环里查这一条
    #: （多轮自主跑那条路由 `autonomy._stop_before_round` 在「每轮之间」查，
    #: 单趟 `run-agent` 没有那条路，所以由 CLI 把 `--stop-file` 接到这里）。
    stop_file: str = ""
    #: 问用户时等多久（秒）。「缺省 `None` = 一直等」（2026-10-03 用户裁定「就停着」）。
    #: `0` = 登记问题后立刻停（`run-agent --user-wait-sec 0` 那一档）。
    #:
    #: 旧缺省是 30.0：超时之后循环继续往下跑，于是"问了、没人答、模型自己把关键取舍
    #: 定了"这件事在读数上分不出来。语义与理由见 `userio` 的模块 docstring。
    user_timeout_sec: float | None = None
    #: 无人值守档（`userio.ASK_POLICY` 的显式覆盖）：`None` = 按模块级常量走，
    #: `"unattended"`（历史别名 `"never"`）= 问用户被确定性拒绝（不落问题、不停循环）。
#: CLI 的 `--no-ask` 走它，
    #: 而不是去改模块全局 —— 一个进程里跑第二趟时不该继承上一趟的档位。
    ask_policy: str | None = None
    #: 本次运行自己的台账号与深度（由 `run` 设置）。唤起下一环时必须把它当 parent 传下去，
    #: 否则链条在台账里会断成两段互不相干的记录。
    my_task_id: str = ""
    depth: int = 1

    def _prompt(self, transcript: str, *, step: int) -> str:
        last = step >= self.max_steps - 1
        tail = ("这是最后一步：不要再调用工具、不要再唤起伙伴，直接输出 "
                '{"final": "<结论>", "evidence": [...]}。' if last else
                "请按循环协议输出下一步（一个 JSON 对象，六种形状取其一）。")
        # 输出契约重述在最后一行（`draft/28` §195 实测）：
        # 系统提示词有 6k+ token，循环协议埋在中间；真机跑 M 做"核验证明"那种长任务时，
        # 模型连着三次回了 1400–2400 字的散文（`judge_bad_json` ⇒ `bad_json_limit`），
        # 而中间那句"请只输出一个 JSON 对象"它没听。把骨架放到它最后读到的那一行。
        #
        # 原生工具面在场时多一句（`draft/37` §52 的真机读数）：那一趟模型看到了函数面
        # （`tools` 里有 `fs_list`），却仍然按文本协议回了一行 JSON，并把广告名
        # （`fs_list`）写进了 `tool` 字段 —— 于是执行层报 `unknown_tool`。
        # 所以这一句要说清两条写法各自的名字从哪来（真名 vs 广告名）。
        face_note = ""
        if getattr(self, "_face", None) is not None:
            face_note = ("（本岗同时开了原生工具调用：你可以直接走函数调用接口；"
                         "若仍回一行 JSON，`tool` 字段要写真名（工具清册里那个，"
                         "例如 `fs.read`），不是函数名里的下划线写法。两种都可以。）\n")
        return (f"{transcript}\n\n---\n现在是第 {step + 1} 步（最多 {self.max_steps} 步）。{tail}\n"
                f"剩余花销预算：{self._budget_text()}\n"
                f"{face_note}"
                f"{JSON_TAIL}")

    def _wired_roles(self) -> list[str]:
        """后端登记表里真的能接活儿的角色（真身读数）。

        为什么不用 `host.wiring_status` 当唯一来源：那个函数在不给 providers 时会
        重新算一遍接线（`A` 需要 providers，不给就报 `no_provider`），而这一趟真正的
        接线是 `cli.cmd_run_agent` 建的（`--provider` → 配置 → `openalex`）。
        两边问的是同一个问题、答案却不同 —— 而模型只看得见后者（`draft/37` §106）。
        """
        backend = getattr(self.conductor, "backend", None)
        for cand in (backend, getattr(backend, "inner", None)):
            fn = getattr(cand, "known_roles", None)
            if not callable(fn):
                continue
            try:
                roles = [str(r) for r in fn()]
            except Exception:  # noqa: BLE001 —— 问不出来就当没这一路读数
                continue
            if roles:
                return sorted(set(roles))
        return []

    def _availability(self) -> dict[str, str] | None:
        """现在的接线态（哪个伙伴真的能被唤起）。拿不到就返回 None 并留一条 note。

        ## 2026-10-04 修正（`draft/37` §106）：这一栏此前会说谎，代价是整条检索路

        它原先只调 `host.wiring_status(store, ...)`。那个读数不带 providers，
        于是 A 被报成 `no_provider` —— 哪怕这一趟明明接了 openalex。
        真机后果（T1 第 14 趟）：M 的提示词里那栏写着"接线态（这一栏是事实）"
        `A -> no_provider`，它在第 22 步据此写下「A 未接线（no_provider）
        ⇒ 盘外引文放弃检索」，整趟没派过一次 A（而 A 的检索是通的：
        离线探针一次查询就登记了 9 行文献、含 Kuchment 那篇 DOI）。

        修法：先问真身（后端登记表里有哪些角色 ⇒ 它们真的能被唤起），
        再用主机读数补上其余角色（没接线的仍然如实报 —— 不是把这一栏变成永远"wired"）。
        """
        reg: dict[str, str] = {}
        if self.store is not None:
            try:
                from .host import wiring_status

                reg = dict(wiring_status(self.store, workspace_root=self.workspace_root))
            except Exception:  # noqa: BLE001 —— 主机读数拿不到就只给真身那一半
                reg = {}
        for role in self._wired_roles():
            reg[role] = "wired"
        return reg or None

    def _hear(self) -> list[dict[str, Any]]:
        """听一次新消息：把这次运行期间新到的消息取出来并登记投递。"""
        digest, fresh, problems = inbox_digest(self.session_root, self.role, sid=self.sid)
        if not fresh:
            return []
        problem = mark_delivered(self.session_root, self.role, fresh, sid=self.sid)
        heard: list[dict[str, Any]] = []
        messages, _ = read_messages(self.session_root, self.role, sid=self.sid)
        for m in messages:
            if str(m.get("msg_id")) in fresh:
                heard.append({"id": m.get("msg_id"), "from": m.get("from"),
                              "channel": m.get("channel"), "subject": m.get("subject"),
                              "body": _clip(m.get("body"), 400)})
        if problem:
            heard.append({"投递登记失败": problem})
        return heard

    def _budget_text(self) -> str:
        if self.seam.usd_budget is None:
            return f"未设置上限（已用 {self.seam.spend.usd:.6f} 美元）"
        left = max(0.0, self.seam.usd_budget - self.seam.spend.usd)
        return f"{left:.6f} 美元（上限 {self.seam.usd_budget:.6f}）"

    def run(self, task: str, *, summoned_by: str = "", my_task_id: str = "",
            depth: int = 1, resumed: tuple[str, int] | None = None,
            waiting_for: str = "") -> LoopRun:
        """跑一次循环。`task` 是这次要做的事（被召唤时就是调用方给的参数）。

        `resumed` 是 `(重建出来的 transcript, 从第几步接着跑)`（由 `run_role` 在
        `--resume` 那一趟里从检查点 + 会话记录算出来，见 `resume_transcript`）。
        给了它就「不再自己拼开头」 —— 那一趟要接着说的正是"它上次说过的那些话"，
        重拼一遍等于换一段话重新开始。收件箱那一段仍然现读（新到的留言本来就该听到），
        投递登记也照旧做（那两件事是"这一趟"的事实，不是"上一趟"的）。
        """
        t0 = time.monotonic()
        self.my_task_id = my_task_id
        self.depth = depth
        inbox, fresh_ids, inbox_problems = inbox_digest(self.session_root, self.role, sid=self.sid)
        notebook = notebook_digest(self.session_root, self.role)
        replies = AP.user_replies_digest(U.read_replies(self.session_root, role=self.role,
                                                       sid=self.sid))
        run = LoopRun(role=self.role, task=task)
        run.started_at = S.now_iso()
        # 登记"这一趟起的进程"（`draft/37` §128）：强制的 `agentflow stop --force`
        # 就是按这份登记去 `taskkill /T /F` —— 只杀父进程会留下子孙继续跑
        # （§127 的真机读数：包装进程被 kill 之后子进程又跑了 12 分钟）。
        try:
            from . import stopctl

            stopctl.register_pid(self.session_root, self.role, self.sid)
        except Exception as exc:  # noqa: BLE001 —— 登记不上不影响这一趟，但必须留痕
            SS.append(self.session_root, {
                "kind": "agent_note", "role": self.role,
                "note": f"进程登记没写成（{type(exc).__name__}: {exc}）⇒ "
                        "`agentflow stop --force` 找不到这个进程",
            }, sid=self.sid)
        run.notes.extend(f"收件箱读取：{p}" for p in inbox_problems)
        if fresh_ids:
            problem = mark_delivered(self.session_root, self.role, fresh_ids, sid=self.sid)
            if problem:
                run.notes.append(f"投递登记失败：{problem}")

        availability = self._availability()
        facts = dict(task=task, summoned_by=summoned_by, task_id=my_task_id, depth=depth,
                     budget_left=self._budget_text(), inbox=inbox,
                     workspace_root=self.workspace_root, availability=availability,
                     notebook=notebook, user_replies=replies,
                     # 这台机器能不能做形式化核验（现算一次，`draft/37` §89）：
                     # E 在 T1 第 3 趟把 6 次 check_formal 花在 `import Mathlib` 上，
                     # 而框架早就知道本机没装 Mathlib —— 事实必须进模型看得见的地方。
                     toolchain_facts=AP.toolchain_facts_text())
        run.prompt_audit = AP.prompt_audit(self.role, registry=self.registry, **facts)
        system = AP.system_prompt(self.role, registry=self.registry, **facts)
        if resumed is None:
            start_step = 0
            transcript = _opening_transcript(task, inbox=inbox, summoned_by=summoned_by,
                                             task_id=my_task_id, depth=depth)
        else:
            transcript, start_step = resumed
            run.resumed_from = start_step
            # 注意：这里「不」把"上一趟停在等谁"写进 `run.waiting_for`。
            # 那个字段的口径是"这一趟停在等谁"，而上一趟的值只进下面那条 start 事件
            # （它是续跑的输入面）。混用会让一趟收工（final）的 run_end 事件里
            # 挂着一个旧 qid —— 读的人会以为它停在等那个问题。

        SS.append(self.session_root, {
            "kind": "agent_run_start", "role": self.role, "task": task,
            "summoned_by": summoned_by, "task_id": my_task_id, "depth": depth,
            "prompt_version": run.prompt_audit.get("prompt_version"),
            "prompt_sha256": run.prompt_audit.get("prompt_sha256"),
            # 续跑那两栏：从第几步接着跑、上一趟停在等谁。两者都是"这一趟不是全新的"
            # 这件事的读数 —— 事后看会话记录时，"它是从第 5 步接上的"与"它从第 1 步
            # 重跑了一遍"在别处长得一模一样（步号都从 5 开始之后才分得开）。
            #
            # `resumed_from` 的口径逐字是「这一趟真的从第几步接着跑」（0 = 全新开始）。
            # 被拒的续跑（指纹不符 / 还在等）写的是另一个字段 `resume_attempted_from`
            # —— 它们一步都没跑，写 0 会被读成"它从第 0 步续的"（见 `_note_resume_refusal`）。
            "resumed_from": run.resumed_from, "waiting_for": str(waiting_for or ""),
        }, sid=self.sid)

        # 原生工具面（`draft/37` §49/§50）：广告这一岗的工具 + 循环的非工具形状。
        # 造不出来（比如一个没有 `for_role` 的注册表、或广告名撞车）不是致命：
        # 那就回落去文本 JSON 协议，并把原因留在会话记录里 —— 静默回落会让
        # "这一趟走的是哪条协议"在事前事后都不可读。
        face = None
        try:
            face = LL.build_tool_face(self.role, self.registry)
        except Exception as exc:  # noqa: BLE001 —— 造不出面就回落，不拖垮整趟
            SS.append(self.session_root, {
                "kind": "agent_note", "role": self.role,
                "note": f"原生工具面没造出来（{type(exc).__name__}: {exc}）⇒ 回落文本 JSON 协议",
            }, sid=self.sid)
        SS.append(self.session_root, {
            "kind": "agent_tool_face", "role": self.role,
            "advertised": len(face.functions) if face is not None else 0,
            "sha256": face.sha256 if face is not None else "",
        }, sid=self.sid)
        self._face = face          # `_prompt` 要用它决定"名字从哪来"那一句

        # 活性读数的游标（`draft/37` §136）：上一步的"调用键"与"读数"，以及连击数。
        # `same_call` = 连续同调用；`dead` = 连续同调用 + 同读数（后者才是"没有新事实"）。
        prev_key = ""
        prev_reading = ""
        same_call = 0

        for step in range(start_step, self.max_steps):
            stop_reason = self._user_stop_reason(run)
            if stop_reason:
                # 人叫停：把这一步之前做过的事「如实收尾」（不是把进程杀掉）。
                # `draft/37` §125 的真机读数：用户在单趟 `run-agent` 里叫停，
                # 那一趟继续跑了 60 多个任务、烧掉 $0.98，最后只能强杀 ——
                # 强杀的结果是台账里没有 `agent_run_end`、盘上没有步检查点，
                # "跑到哪儿了"事后无从回答。这条 break 就是补那一格。
                run.stop_reason = stop_reason
                run.final = run.final or self._stop_note(stop_reason, step)
                SS.append(self.session_root, {
                    "kind": "agent_note", "role": self.role,
                    "note": (f"用户叫停（{stop_reason}）⇒ 第 {step} 步之后收工；"
                             "已做过的事留在台账与会话记录里，步检查点由 run_role 落盘"),
                }, sid=self.sid)
                break
            if self.seam.usd_budget is not None and self.seam.spend.usd >= self.seam.usd_budget:
                run.stop_reason = "budget"
                run.final = run.final or "预算已耗尽，停止（没有继续调用模型）"
                break
            data, call = self.seam.ask_step(self._prompt(transcript, step=step),
                                            system=system, task_id=my_task_id,
                                            note=f"{self.role}.step{step}",
                                            max_tokens=self.max_output_tokens,
                                            face=face)
            if data is None:
                args_error = call.problem == "judge_bad_args"
                if args_error:
                    run.bad_args += 1
                    run.bad_args_streak += 1
                else:
                    run.bad_json += 1
                    run.bad_json_streak += 1
                # 把模型实际说了什么、以及「框架为什么不认」都留在这一步里（2026-09-30；
                # `draft/37` §68 补齐 `detail`）：只有 `problem` 时，"它为什么解析不出来"
                # 在台账上是不可回答的 —— 真机里 M 连着三次 `judge_bad_json`，我只能靠猜。
                # 第十二趟更糟：`problem` 是 `judge_bad_json`，而 `detail`（带解析报错
                # 与原文前 200 字）「根本没进记录」 —— 于是"为什么这两句 JSON 没解析出来"
                # 又一次只能靠猜。留 detail + raw_reply，两条判据（"说了什么"与
                # "框架怎么读的"）都在盘上。
                bad_result = {"problem": call.problem, "detail": _clip(call.detail, 600),
                              "raw_reply": _clip(call.text, 600)}
                run.steps.append(LoopStep(step, "invalid", {}, bad_result,
                                          problem=call.problem))
                SS.append(self.session_root, {
                    "kind": "agent_step", "role": self.role, "index": step, "shape": "invalid",
                    "payload": {}, "result": dict(bad_result),
                }, sid=self.sid)
                if call.problem == "judge_not_wired":
                    run.stop_reason = "not_wired"
                    run.final = ("没有接模型（judge_not_wired）：这次运行没有产生任何判断，"
                                 "也没有写任何数据")
                    break
                if args_error:
                    # 参数坏：「交回工具层」（`draft/37` §65，DSH 的 `ToolArgsError` 口径）。
                    # 反馈里点名"是哪个函数的参数坏了"（`call.detail` 带着工具名与原文），
                    # 这类错误是可纠正的，不该按"形状漂移"处置。
                    if run.bad_args_streak > self.max_bad_args:
                        run.stop_reason = "bad_args_limit"
                        run.final = (f"连续 {run.bad_args_streak} 次把工具参数写成不合法 JSON"
                                     f"（最后一次：{call.detail}），停止")
                        break
                    transcript += _bad_args_line(step, str(bad_result["detail"]))
                    continue
                if run.bad_json_streak > self.max_bad_json:
                    run.stop_reason = "bad_json_limit"
                    run.final = (f"连续 {run.bad_json_streak} 次没有给出可解析的 JSON"
                                 f"（最后一次：{call.problem}），停止")
                    break
                transcript += _bad_json_line(step, call.problem, str(bad_result["detail"]))
                continue
            shape, payload, problem = _shape_of(data)
            if problem:
                # 「形状认得出来、只是某个值写错了」与「形状认不出来」分开计
                # （`draft/37` §140 的真机读数）：前者交回模型改那个值就该能救活
                # （走 `bad_args` 那一档，与"工具参数不是合法 JSON"同一类），
                # 后者才是"没按协议说"（`bad_json` 那一档）。
                # 第 5 趟有一整段因为 `{"message":{"to":"ALL"}}` 被算进后者：连着三次
                # ⇒ 60 秒整段作废，而它离"把 to 改成 #public"只差一个词。
                recognized = (next((str(k) for k in data if str(k) in SHAPES), "")
                              if isinstance(data, Mapping) else "")
                if recognized:
                    run.bad_args += 1
                    run.bad_args_streak += 1
                else:
                    run.bad_json += 1
                    run.bad_json_streak += 1
                bad_result = {"problem": problem, "shape_recognized": recognized,
                              "raw_reply": _clip(json.dumps(data, ensure_ascii=False), 600)}
                run.steps.append(LoopStep(step, "invalid", payload, bad_result,
                                          problem=problem))
                SS.append(self.session_root, {
                    "kind": "agent_step", "role": self.role, "index": step, "shape": "invalid",
                    "payload": dict(payload), "result": dict(bad_result),
                }, sid=self.sid)
                if recognized and run.bad_args_streak > self.max_bad_args:
                    run.stop_reason = "bad_args_limit"
                    run.final = (f"连续 {run.bad_args_streak} 次形状说对了、值写错了"
                                 f"（形状 {recognized}；最后一次：{problem}），停止")
                    break
                if not recognized and run.bad_json_streak > self.max_bad_json:
                    run.stop_reason = "bad_json_limit"
                    run.final = (f"连续 {run.bad_json_streak} 次形状不合法"
                                 f"（最后一次：{problem}），停止")
                    break
                transcript += (_payload_line(step, recognized, problem) if recognized
                               else _invalid_line(step, problem))
                continue
            # 说对了一次 ⇒ 连击清零（`draft/37` §68）。清零的判据是"它按协议说出了一个形状"，
            # 不是"那件事办成了" —— 工具被拒、召唤被拒、参数不合法都算说对了协议，
            # 那些走的是各自的纠正路径（`RELAY_REFUSALS` / `invalid_params`）。
            run.bad_json_streak = 0
            run.bad_args_streak = 0
            if shape == "final":
                run.final = str(payload.get("final") or "")
                run.evidence = list(payload.get("evidence") or [])
                run.steps.append(LoopStep(step, shape, payload, {}))
                run.stop_reason = "final"
                break
            result = self._execute(shape, payload)
            # 耳朵一直开着：这一步做完先听一次新消息，把它并进这一步的结果里
            # （并进结果而不是只并进 transcript：台账与会话记录要能看到"他当时听到了什么"）。
            heard = self._hear()
            if heard:
                result = {**result, "新消息": heard}
            # ---- 活性读数（`draft/37` §136）：同形状 + 同参数 + 同读数 = 这一步没有新事实
            #
            # 为什么要"同读数"这一半：轮询是正当的（同一件事每隔一步问一次，读数在变），
            # 只有"同一件事问了又问、答案一个字都没变"才是原地打转。两个连击都记下来
            # （`same_call` 是读数，`dead` 是判据），因为"同一件事问了 9 遍"这件事
            # 本身也该被看见，而它不一定构成停下来的理由。
            key = _call_key(shape, payload)
            reading = _call_reading(result)
            same_call = same_call + 1 if key == prev_key else 1
            dead = same_call if (key == prev_key and reading == prev_reading) else 1
            prev_key, prev_reading = key, reading
            run.same_call_max = max(run.same_call_max, same_call)
            run.dead_loop_max = max(run.dead_loop_max, dead)
            if same_call == self.dead_loop_nudge:
                # 点名（不改结论、不停循环）：提醒写进这一步的结果里 ——
                # `_step_line` 读的就是它，于是"当时那一份"与"续跑重建那一份"逐字一致。
                result = {**result, "框架提醒": _dead_loop_line(
                    streak=same_call, same_reading=dead, limit=self.max_dead_loop,
                    what=_call_brief(shape, payload))}
            # ---- 参数类拒绝：把声明的参数表原样回给模型（`draft/37` §140 的协作改进）
            #
            # 为什么在这一层做（而不是每个工具各自写一段更好的拒信）：参数形状是声明面
            # 的事实，只有装配期读得到它；被拒的模型手上没有那份声明，于是只能猜 ——
            # T2 第 5 趟 47 次派活里 35 次被拒，绝大多数是"猜形状猜错"。
            # 这一句把"猜"换成"读"：同一步的结果里既有拒信、也有那张表。
            if shape in ("tool", "summon", "summon_many") and looks_like_a_param_refusal(result):
                hint = self._param_table(shape, payload)
                if hint:
                    result = {**result, "参数表": hint}
            step_obj = LoopStep(step, shape, payload, _for_record(result))
            run.steps.append(step_obj)
            SS.append(self.session_root, {
                "kind": "agent_step", "role": self.role, "index": step, "shape": shape,
                "payload": dict(payload), "result": dict(step_obj.result),
            }, sid=self.sid)
            transcript += _step_line(step, payload, result)
            # ---- 原地打转：同调用 + 同读数连着到上限 ⇒ 这一趟收在这里（不再是"步数用尽"）
            #
            # 为什么停下来是"如实"而不是"失败"：这一步确实做了（台账与会话记录里都有），
            # 只是它没有产生新事实 —— `no_progress_limit` 这个名字说的就是这件事。
            # 为什么不继续问模型：前面已经在第 `dead_loop_nudge` 次点过名，
            # 它连着又重复了 `max_dead_loop - dead_loop_nudge` 次同样的调用 ——
            # 剩下的步数买不到新读数，只会买更多同样的调用。
            if dead >= self.max_dead_loop:
                run.stop_reason = "no_progress_limit"
                run.final = (f"原地打转收工：{_call_brief(shape, payload)}——"
                             f"同一份参数、同样的读数连着 {dead} 次。"
                             f"没有新事实，所以停在这里（不是失败，是这一趟没有往前走）。"
                             f"要说的话在 final 里说清：卡在哪、下一步该换什么做法。")
                SS.append(self.session_root, {
                    "kind": "agent_note", "role": self.role,
                    "note": (f"原地打转：{_call_brief(shape, payload)} 连续 {dead} 次同参数同读数 "
                             f"⇒ 第 {step} 步之后以 no_progress_limit 收工"),
                }, sid=self.sid)
                break
            # ---- 问了用户、还停在等 ⇒ 这一趟停在这里，一步模型请求都不再发
            #
            # 为什么这个 break 写在"拼完简报"之后：`agent_step` 事件已经落了这一步，
            # 而 `resume_transcript` 是从那些事件重建简报的 —— 落事件与拼简报必须
            # 同时发生，否则续跑那一段会看到比当时多一步或少一步的对话。
            #
            # 为什么停了就等于"不烧钱"：等待期间等的是磁盘上的一条 `user_answer`
            # 事件（`userio.ask_user` 的轮询），一个 token 都不花；而"超时后继续"
            # 那一版会把剩下的步数继续喂给模型 —— 那笔钱买的是替用户做的决定。
            if shape == "ask_user" and result.get("state") in ("pending", "cancelled"):
                qid = str(result.get("asked") or "")
                question = _clip(str(payload.get("question") or ""), 120)
                if result.get("state") == "pending":
                    run.stop_reason = "waiting_for_user"
                    run.waiting_for = qid
                    sid_arg = f" --sid {self.sid}" if self.sid else ""
                    run.final = (f"停在等 {qid} 的回答：{question}；"
                                 f"用 `agentflow --root {self.session_root} inbox{sid_arg}` 看、"
                                 f"`agentflow --root {self.session_root} answer {qid} "
                                 f"\"<回答>\"{sid_arg}` 答、"
                                 f"`agentflow --root {self.session_root} run-agent --resume …"
                                 f"{sid_arg}` 续跑")
                else:
                    run.stop_reason = "ask_cancelled"
                    run.final = (f"第 {step + 1} 步问用户时被取消（{qid}）：这一趟停在这里。"
                                 f"问题还在待答清单里 —— 取消不等于用户答过了")
                break
        else:
            run.stop_reason = "max_steps"
            run.final = run.final or f"步数用尽（{self.max_steps} 步）仍未给出 final"

        run.spend = self.seam.spend.to_dict()
        run.elapsed_sec = time.monotonic() - t0
        run.transcript = transcript
        # 正常收工就注销进程登记（被杀时它自然留在盘上，`stopctl.live_pids` 会把死 pid 滤掉）。
        try:
            from . import stopctl as _sc

            _sc.unregister_pid(self.session_root, self.role, self.sid)
        except Exception:  # noqa: BLE001 —— 注销失败不影响这一趟的产出
            pass
        SS.append(self.session_root, {
            "kind": "agent_run_end", "role": self.role, "stop_reason": run.stop_reason,
            "steps": len(run.steps), "summons": run.summons, "messages": run.messages_sent,
            # 停在等谁（空 = 不是那一档）：界面与 `inbox` 要的就地读数，
            # 不必去解析 `final` 那句话里的 qid。
            "waiting_for": run.waiting_for,
            # `final` 是这一岗的交付物本身：只记长度的话，事后没人能核
            # "它到底与验收表对齐了没有"（实测：终点门槛 A 要逐条核交付说明，
            # 而会话记录里只有 `final_chars`）。文本与哈希一起留，长度保留是为了
            # 让"有没有被截断"一眼可见。
            "final": run.final, "final_sha256": _sha(run.final)[:16],
            "final_chars": len(run.final), "spend": dict(run.spend),
            "elapsed_sec": round(run.elapsed_sec, 3),
        }, sid=self.sid)
        return run

    # -------------------------------------------------------------- 执行
    def _user_stop_reason(self, run: "AgentLoop.LoopRun") -> str:
        """人叫停了吗（`draft/37` §125）。返回停止原因（空串 = 没叫停，继续跑）。

        两处来源，与 `autonomy._stop_before_round` 用的是「同一套词」：

        - `stop_file`：`--stop-file`（或这里给的路径）指向的那个文件存在于盘上；
        - `user_stop`：本次运行「开始之后」收到的那条回答里含 `autonomy.STOP_TOKEN`。

        为什么两处都要在「步循环里」查：`autonomy` 那套判据只在「每轮之间」跑，
        而单趟 `run-agent`（不 `--rounds`）根本不走那条路 —— 真机实测（2026-10-04）：
        用户叫停后那一趟继续跑了 60 多个任务、烧掉 $0.98，最后被强杀；
        强杀不留痕（没有 `agent_run_end`、没有步检查点），"跑到哪儿了"事后答不出来。

        为什么 `user_stop` 要比时间戳：回答是 append-only 的审计面，
        翻到一条「上一次」留下的 STOP 就停会把之后每一趟都判死。

        第三个来源（`draft/37` §128）：「工作区的停机开关」（`.agentflow-stop`，`stopctl`）
        —— 它是 M 的 `conductor.stop` 与 `agentflow stop` 写下的那一份，
        也是「唯一」能打断在飞工作的通道（广播做不到：收件箱是 `run()` 开头读一次的）。
        开关里 `force=true` ⇒ 走 `force_stop`（"直接停"，不等待收尾）。

        ## `draft/37` §140：开关是「一次性信号」（停一趟 → 记一笔 → 撤走）

        实测（`temp/_stop_probe.py`）：`conductor.stop` 停了一趟之后开关留在盘上，
        而紧接着的 `--resume` 在第 0 步就被同一把开关停掉（0 步、0 次模型调用）——
        同一个工具的产物里却写着"可续跑的步检查点 + 续跑简报"，两者互相拆台。
        处置：判定生效的这一刻调 `stopctl.consume_stop(...)`（审计进
        `runs/stop-history.jsonl`，开关撤走）。这样 E 的子进程、续跑、以及"用户第二次叫停"
        三条路都不再被一把旧开关卡住。
        """
        if self.stop_file and Path(self.stop_file).exists():
            # 显式给的路径也按同一套"停一次就消费"办（CLI 传的就是工作区那把开关）。
            try:
                from . import stopctl

                state = stopctl.read_stop(self.session_root, explicit=self.stop_file)
            except Exception:  # noqa: BLE001 —— 读不到开关不是"用户叫停"，如实不停
                state = None
            if state is not None:
                reason = "force_stop" if bool(state.get("force")) else "stop_file"
                try:
                    from . import stopctl

                    stopctl.consume_stop(self.session_root, sid=self.sid, level=reason,
                                         explicit=self.stop_file)
                except Exception:  # noqa: BLE001 —— 记账失败不让"停下"这件事失效
                    pass
                return reason
            return ""
        try:
            from . import stopctl

            state = stopctl.read_stop(self.session_root)
        except Exception:  # noqa: BLE001 —— 读不到开关不是"用户叫停"，如实不停
            state = None
        if state is not None:
            reason = "force_stop" if bool(state.get("force")) else "stop_file"
            try:
                from . import stopctl

                stopctl.consume_stop(self.session_root, sid=self.sid, level=reason)
            except Exception:  # noqa: BLE001 —— 记账失败不让"停下"这件事失效
                pass
            return reason
        started = str(getattr(run, "started_at", "") or "")
        if not started:
            return ""
        try:
            from . import autonomy as AU

            replies = U.read_replies(self.session_root, role=self.role, sid=self.sid)
        except Exception:  # noqa: BLE001 —— 读不到回答不是"用户叫停"，如实不停
            return ""
        for reply in reversed(list(replies or [])):
            if str(reply.get("ts") or "") < started:
                continue
            if AU.STOP_TOKEN in str(reply.get("answer") or ""):
                return "user_stop"
            break                      # 只看"开始之后最近的那一条"
        return ""

    def _stop_note(self, stop_reason: str, step: int) -> str:
        """人叫停时写进 `final` 的那句话（要能直接告诉人"停在哪儿、怎么接着跑"）。"""
        what = {"stop_file": f"用户叫停（开关文件 {self.stop_file or '.agentflow-stop'}）",
                "user_stop": "用户叫停（回答里有 STOP）",
                "force_stop": "用户强制停止（直接停，不等待收尾）"}.get(
                    stop_reason, f"用户叫停（{stop_reason}）")
        sid_arg = f" --sid {self.sid}" if self.sid else ""
        return (f"{what}：第 {step} 步之后收工。已经做过的事都留在台账与盘上；"
                f"要看这一趟做了什么用 `agentflow --root {self.session_root} runs`，"
                f"要接着跑用 `agentflow --root {self.session_root} run-agent --resume "
                f"--task \"<接着做什么>\"{sid_arg}`")

    def _param_table(self, shape: str, payload: Mapping[str, Any]) -> str:
        """被参数拒了的那一步：把声明面里的参数表渲染出来（读不到就返回空串，不编）。"""
        from . import capabilities as C

        lines: list[str] = []
        if shape == "tool":
            name = str(payload.get("name") or "")
            spec = None
            try:
                spec = self.registry.get(name) if self.registry is not None else None
            except Exception:  # noqa: BLE001 —— 拿不到工具声明就不给表（不编一张）
                spec = None
            if spec is not None:
                lines.append(f"{name} 的参数表：" + (render_params(spec.params) or "（声明里没有参数）"))
        else:
            targets = ([payload] if shape == "summon"
                       else list(payload.get("targets") or []))
            for t in targets:
                if not isinstance(t, Mapping):
                    continue
                role = str(t.get("role") or "")
                action = str(t.get("action") or "")
                spec = None
                try:
                    spec = next((s for s in C.actions_for(role) if s.action == action), None)
                except Exception:  # noqa: BLE001 —— 同上
                    spec = None
                if spec is not None:
                    lines.append(f"{role}.{action} 的参数表："
                                 + (render_params(spec.params) or "（声明里没有参数）"))
        if not lines:
            return ""
        return ("【参数表】被拒的是参数形状/取值，不是这件事不能做。照下面这张声明表重写一次"
                "（键名与类型都要对；表里没列的键一律不许传）：\n- " + "\n- ".join(lines))

    def _execute(self, shape: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if shape == "tool":
            return self._do_tool(payload)
        if shape == "summon":
            return self._do_summon(payload)
        if shape == "summon_many":
            return self._do_summon_many(payload)
        if shape == "note":
            return self._do_note(payload)
        if shape == "handoff":
            return self._do_handoff(payload)
        if shape == "ask_user":
            return self._do_ask_user(payload)
        return self._do_message(payload)

    def _do_summon_many(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """一次派一批活（并发）：走 `Conductor.run_plan`，按写集分波、同波并发。

        与 `_do_summon` 的区别只有两处，都是有意的：

        - 一次一批：`targets` 是数组，结果按输入顺序回来（长度恒等于输入长度）；
        - 同角色的多个实例要自己给 `instance`：不给时框架按 `summon_many`
          工具那条同一套规则自动补 `<角色>#N`（同角色在一批里出现多次时）——
          "并发几个 B"不该依赖模型记得写那个标签。

        三态纪律照旧：每一项都有自己的 `status`/`outcome`/`refusal_reason`；
        `waves` / `concurrent_peak` 是"到底并发了没有"的读数（不是墙钟）。
        """
        targets = payload.get("targets") or []
        if self.conductor is None:
            return {"summoned": [], "ok": False, "error": "本次运行没有接线主控（summon_many 不可用）"}
        if self.token is not None and getattr(self.token, "cancelled", False):
            return {"summoned": [], "ok": False, "error": "取消信号已置位：不再发起新的召唤"}
        from . import scheduler as SC

        c = self.conductor
        auto: dict[str, list[str]] = {}
        counted: dict[str, int] = {}
        for t in targets:
            if not str(t.get("instance") or ""):
                counted[str(t.get("role"))] = counted.get(str(t.get("role")), 0) + 1
        for role, n in counted.items():
            if n > 1:
                auto[role] = [f"{role}#{k}" for k in range(1, n + 1)]
        used: dict[str, int] = {}
        calls = []
        for t in targets:
            instance = str(t.get("instance") or "")
            if not instance and str(t.get("role")) in auto:
                used[str(t["role"])] = used.get(str(t["role"]), 0) + 1
                instance = auto[str(t["role"])][used[str(t["role"])] - 1]
            calls.append(SC.TaskCall(role=str(t.get("role")), action=str(t.get("action")),
                                     params=dict(t.get("params") or {}), by=self.role,
                                     parent_task_id=self.my_task_id or None,
                                     input_key=(str(t.get("input_key") or "")
                                                or _summon_key(str(t.get("action")),
                                                               dict(t.get("params") or {}))),
                                     instance=instance))
        results = c.run_plan(calls, token=self.token)
        probe = getattr(c, "_last_probe", None)
        waves = [len(w) for w in P.waves_of(calls,
                                            limit=getattr(c.policy, "max_concurrency", None))]
        items = []
        for r, call in zip(results, calls):
            items.append({"role": call.role, "action": call.action, "instance": call.instance,
                          "task_id": r.task_id, "status": r.status, "outcome": r.outcome,
                          "refusal_reason": r.refusal_reason, "detail": _clip(r.detail, 200)})
        out: dict[str, Any] = {
            "summoned": [f"{i['role']}.{i['action']}" for i in items],
            "count": len(items),
            "ok_count": sum(1 for i in items if i["outcome"] == "ok"),
            "refused_count": sum(1 for i in items if i["outcome"] == "refused"),
            "failed_count": sum(1 for i in items if i["status"] == "failed"),
            "waves": waves, "concurrent_peak": int(getattr(probe, "peak", 0) or 0),
            "results": items,
            "ok": True,
        }
        # 批量里的越权也要有出路（与 `_do_summon` 同一条纪律）：一次汇总成一条
        # 代唤申请，而不是每一项发一条（那会把主控的收件箱灌满，让信号贬值）。
        need = [i for i in items if self._needs_relay(str(i["role"]), str(i["refusal_reason"] or ""))]
        if need:
            want = "、".join(sorted({f"{i['role']}.{i['action']}" for i in need}))
            first = need[0]
            out["relay_requested"] = self._request_relay(
                str(first["role"]), str(first["action"]), {},
                f"{first['refusal_reason']}（批量共 {len(need)} 项）",
                f"这一批里 {len(need)} 项派不出去：{want}；明细见 results")
        return out

    def _do_tool(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """执行一步工具调用。

        ## 为什么这里要认"广告名"（`draft/37` §52 的真机读数）

        第四趟真机：本岗同时开着原生工具面（`tools` 里有 `fs_list` 这样的函数名 ——
        带点的真名 `fs.list` 不符合 function name 的字符集，所以广告时被归一化成下划线），
        而模型仍然按文本协议回了一行 JSON，并把广告名 `fs_list` 写进了 `tool` 字段
        ⇒ 执行层报 `unknown_tool`，29 步全白花。

        这不是模型的错：它看到的两个名字（工具清册里的 `fs.list` 与函数面里的 `fs_list`）
        都是我们给的。所以这一层逐次把广告名映回真名，并在结果里留一句
        `aliased_from` —— 认账，但不静默：谁在用别名、用了几次，读数上看得见。
        """
        raw = str(payload.get("name"))
        name, aliased_from = raw, ""
        face = getattr(self, "_face", None)
        known = set(self.registry.names()) if hasattr(self.registry, "names") else set()
        if raw not in known and face is not None:
            target = face.names.get(raw, "")
            if target.startswith("tool:"):
                real = target.split(":", 1)[1]
                if real in known:
                    name, aliased_from = real, raw
        args = dict(payload.get("args") or {})
        try:
            res = self.registry.call(name, role=self.role, **args)
        except Exception as exc:  # 工具层抛错也要变成"模型看得见的结果"
            return {"tool": name, "ok": False, "error": f"{type(exc).__name__}: {exc}",
                    **({"aliased_from": aliased_from} if aliased_from else {})}
        out = {"tool": name, "ok": bool(res.ok), "data": res.data,
               "error": res.error or "", "meta": dict(res.meta or {})}
        if aliased_from:
            out["aliased_from"] = aliased_from
        return out

    def _do_summon(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        role = str(payload.get("role"))
        action = str(payload.get("action"))
        out: dict[str, Any] = {"summoned": role, "action": action}
        if self.conductor is None:
            out.update(ok=False, error="本次运行没有接线主控（summon 不可用）")
            return out
        if self.token is not None and getattr(self.token, "cancelled", False):
            out.update(ok=False, error="取消信号已置位：不再发起新的召唤")
            return out
        budget: Mapping[str, Any] | None = None
        if self.seam.usd_budget is not None:
            budget = {"usd": max(0.0, self.seam.usd_budget - self.seam.spend.usd)}
        params = dict(payload.get("params") or {})
        # `input_key` 由形状给不出（形状里没有这个字段）⇒ 按同一件事派生一个确定性键，
        # 否则这一行落库时键为空、`verify_tasks` 会报 `task_without_input_key`
        # （真机实测：场景 G 的 t-0252）。模型若显式给了就用它给的。
        key = str(payload.get("input_key") or "") or _summon_key(action, params)
        try:
            res = self.conductor.summon(role, action, params,
                                        by=self.role, parent_task_id=self.my_task_id or None,
                                        budget=budget, token=self.token, input_key=key)
        except Exception as exc:
            out.update(ok=False, error=f"{type(exc).__name__}: {exc}")
            return out
        payload = res.payload
        path = str(payload.get("llm_run_path") or "") if isinstance(payload, Mapping) else ""
        out.update(
            ok=bool(res.ok), task_id=res.task_id, status=res.status, outcome=res.outcome,
            refusal_reason=res.refusal_reason, detail=_clip(res.detail, 400),
            children=list(res.children or []),
        )
        if not res.ok and self._needs_relay(role, str(res.refusal_reason or "")):
            # ---- 越权/超深不是"此路不通"，而是"要换一条路"（2026-09-30）
            #
            # 真机实测：被协同唤起的角色一次都没有向主控申请过代唤 ——
            # 因为它拿到的只是一句 `forbidden_edge`，然后就没有然后了
            # （17 个 review 会话里非 M 的 summon 只有 F→E 7 次）。
            # 用户的原话是"如果互相唤起困难，至少要能向主控申请唤起别的智能体做任务"，
            # 所以这里把"被拒绝"自动转成一次结构化的代唤申请：
            # 落一条 `agent_summon_request` 事件 + 给 M 发一条 `subject=请代唤` 的留言。
            # 注意它不是假装成功：`ok` 仍是 False，`relay_requested` 才是这次
            # 实际发生的事；申请有没有被受理由主控在它自己那一步决定。
            out["relay_requested"] = self._request_relay(role, action, payload,
                                                         str(res.refusal_reason or ""),
                                                         str(res.detail or ""))
        if path:
            # 伙伴是 LLM 循环驱动的：它的完整产出在磁盘上，这里只给路径 + 一段结论。
            out["llm_run_path"] = path
            out["final"] = _clip(payload.get("final") or "", 600)
            out["payload"] = _clip({k: v for k, v in payload.items() if k != "llm_run"}, 400)
        else:
            out["payload"] = _clip(payload, 800)
        return out

    def _needs_relay(self, role: str, reason: str) -> bool:
        """这次拒绝该不该转成"请主控代唤"。

        两档要转：

        - `forbidden_edge` / `depth_exceeded`：这条路今天不通（边表 / 深度），
          而重试不会让它通。
        - `invalid_params` 且目标不在我的伙伴表里：这是同一件事的另一种表现 ——
          我看不到他的动作表（伙伴表只列我能唤起的人），所以我给的参数必然是在猜；
          `Conductor.summon` 的顺序是"先查参数、再查边"，于是我会拿到 `invalid_params`，
          而真相是"我根本不该直接找他"。把这一档也算进来，代唤才不会因为
          "参数猜错"而永远发不出去（这是本轮实测出来的：第一次写这条判据时，
          真实场景恰恰落在这档上）。

        反过来，目标在我能唤起的伙伴里时 `invalid_params` 就只是"参数写错了"：
        那种情况该由模型自己改参数，不该占用主控的注意力。
        """
        if reason in RELAY_REFUSALS:
            return True
        return reason == "invalid_params" and role not in AP.partners_out(self.role)

    def _request_relay(self, role: str, action: str, params: Mapping[str, Any],
                       reason: str, detail: str) -> dict[str, Any]:
        """把一次被拒的越权召唤转成"请主控代唤"的申请（留言 + 结构化事件）。

        为什么是留言而不是新造一个形状：`message` 这条通道今天已经通到 M
        （`to="M"` 的私聊判据 `self.role in partners_out("M")` 对每个角色都成立），
        且 M 的循环下一步就会 `_hear()` 到它。新造形状要动循环协议、提示词、
        与会话格式三处，而这一条的用户诉求是"至少能申请"，留言 + 可识别 subject
        就够了；"M 必须受理"那一半只能靠提示词与审计（`verify.py` 是禁改区）。

        `subject` 用固定常量是为了让机器可识别（人读也一眼懂）；body 里逐项写清
        "要谁、做什么动作、什么参数、为什么"，让 M 不必回头问。
        """
        asked = {k: v for k, v in (params or {}).items() if not str(k).startswith("_")}
        body_lines = [f"要谁：{role}", f"做什么动作：{action}"]
        if asked:
            body_lines.append("参数：" + json.dumps(asked, ensure_ascii=False, default=str)[:600])
        else:
            body_lines.append("参数：（这次没有参数）")
        body_lines.append(f"为什么：我要做的这件事被策略拒了（{reason}）—— {detail[:300]}")
        if role not in AP.partners_out(self.role):
            body_lines.append("注意：他不在我的可唤起伙伴里，所以我**看不到他的参数表** —— "
                              "参数可能不合法，请用 conductor.role_spec 核一遍再派。")
        body_lines.append(f"申请方：{self.role}（台账号 {self.my_task_id or '未拿到'}）；"
                          f"批准与否由你决定，我这一步不会替你做。")
        body = "\n".join(body_lines)
        msg_id, problem = send_message(self.session_root, sender=self.role, to=S.CONDUCTOR_ROLE,
                                       subject=RELAY_SUBJECT, body=body, sid=self.sid)
        rec: dict[str, Any] = {"kind": "agent_summon_request", "role": self.role,
                               "wants_role": role, "wants_action": action, "params": asked,
                               "refusal_reason": reason, "message_id": msg_id}
        if problem:
            rec["problem"] = problem
        SS.append(self.session_root, rec, sid=self.sid)
        return {"to": S.CONDUCTOR_ROLE, "subject": RELAY_SUBJECT, "message_id": msg_id,
                "problem": problem,
                "note": ("越权的边不会因为重试而成立 ⇒ 已向主控申请代唤；"
                         "不要把这条申请当成'对方已经在做'。")}

    def _do_message(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        to = str(payload.get("to"))
        reply_to = str(payload.get("reply_to") or "")
        if to != PUBLIC:
            allowed = (to in AP.partners_out(self.role) or self.role in AP.partners_out(to)
                       or bool(reply_to))
            if not allowed:
                return {"message": "未发出", "to": to, "ok": False,
                        "error": f"{self.role} 与 {to} 之间没有协作边（{self.role} 能叫的是 "
                                 f"{sorted(AP.partners_out(self.role))}）⇒ 私聊不成立；"
                                 f"要么发到公共频道（to={PUBLIC}），要么先公开开口。"}
        msg_id, problem = send_message(self.session_root, sender=self.role, to=to,
                                       subject=str(payload.get("subject") or ""),
                                       body=str(payload.get("body") or ""),
                                       reply_to=reply_to, sid=self.sid)
        if problem:
            return {"message": "未发出", "to": to, "ok": False, "error": problem}
        where = "公共频道" if to == PUBLIC else f"给 {to} 的私聊"
        return {"message_sent": msg_id, "to": to, "channel": where, "ok": True,
                "note": "收件人下次运行时（或本步之后）会在收件箱里看到它"}

    def _do_handoff(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """写一份交接手稿 + 把"编号 + 一句简要描述"发给收件人（`draft/37` §134）。

        两件事一起做，是因为它们本来就是一件事的两半：手稿是「内容」，
        留言是「通知」。让模型分两步做，就会出现"写了手稿但对方不知道"（或反过来）
        的半截状态；而且用户点过名："就传个编号感觉有点尬，可以再附一句简要描述"。

        `to="ALL"` ⇒ 走公共频道（所有人收得到），文件名仍是 `NNNN-<From>toALL.md`。
        """
        from . import manuscripts as MS

        to = str(payload.get("to") or "")
        channel = PUBLIC if to == "ALL" else to
        brief = str(payload.get("brief") or "").strip()
        why = str(payload.get("why") or "").strip()
        try:
            rec = MS.write(self.session_root, sender=self.role, recipient=to,
                           title=str(payload.get("title") or ""),
                           body=str(payload.get("body") or ""),
                           refs=list(payload.get("refs") or []),
                           summary=brief, sid=self.sid or "")
        except ValueError as exc:
            return {"handoff": "未写成", "ok": False, "error": str(exc)}
        summary = brief or str(rec.get("title") or "")
        msg_id, problem = send_message(
            self.session_root, sender=self.role, to=channel,
            subject=f"手稿 {rec['id']}：{rec.get('title') or ''}",
            body=(f"[手稿 {rec['id']}] {summary}"
                  + (f"\n（为什么找你：{why}）" if why else "")
                  + f"\n全文：`manuscripts.read(id=\"{rec['id']}\")`"
                    f"（盘上 {rec['path']}）"),
            sid=self.sid)
        return {"handoff": rec["id"], "ok": not problem, "id": rec["id"],
                "path": rec["path"], "to": channel, "brief": summary,
                "notified": msg_id if not problem else "",
                "error": problem,
                "note": ("收件人下次运行时（或本步之后）会在收件箱里看到编号；"
                         "它用 `manuscripts.read` 读全文")}

    def _do_ask_user(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """问用户一个问题：默认「停着」等回答，而不是"超时之后继续"。

        ## 五档处置（每一档都在回答"这一步之后循环怎么办"）

        | `state` | 结果给模型 | 循环 |
        |---|---|---|
        | `answered` | 原样把那句回答给它（含 `selected` / `custom`） | 继续 |
        | `refused` | 无人值守档：确定性拒绝（fail-closed） | 「继续」（它是一次普通工具结果） |
        | `pending` | 还停在等（`user_no_answer` 的含义变了） | 「停」：`stop_reason="waiting_for_user"` |
        | `cancelled` | 等待被当前轮次的取消信号中止 | 「停」：`stop_reason="ask_cancelled"` |
        | `""`（问题没落档） | 通道没通 | 继续（没有 qid 就没有人能答） |

        为什么 `refused` 那一档「不许」停：它是"这次运行按无人值守的姿态跑"这个
        设定本身的结论，而不是"有人在等回答"。停了就等于把一个确定性的拒绝
        变成了停机 —— 而 CI 里没人会来续跑。

        为什么 `pending` 那一档必须停且「不许」再发模型请求：提问的全部意义是
        "这个取舍只有人能定"。继续往下跑等于替人定了（真机反复撞到的形态），
        而停下来不花钱（等的是磁盘上的一条回答事件，不产生 token 开销）。
        """
        if self.role != S.CONDUCTOR_ROLE:
            # 人机通道归主控 —— 这是「运行时」协作纪律，出处是我们自己的设计：
            # `DESIGN-CONDUCTOR.md` §1.1「它是用户唯一面对的东西」（用户只对主控说话，
            # 主控召唤 A–H、再把结果汇总成人看到的东西），而
            # `capabilities.NON_SUMMONABLE = {"M"}` 让它在结构上成立（主控不可被召唤
            # ⇒ 永远是顶层入口）。
            #
            # 判据是「角色是不是主控」，不是「深度多大 / 有没有父任务号」：
            # 旧写法只看"被召唤"（`depth > 1 and my_task_id`），于是人工直接驱动
            # 单个角色（`agentflow run-agent D`，那被标成 depth=2 但没有父任务号）
            # 被当成顶层、可以问人 —— 而那与 §1.1 冲突：那条路是运维/测试路径，
            # 不是用户通道。未决问题出现在结果里，由操作者读。
            return {"asked": "", "ok": False, "problem": U.ASK_NOT_CONDUCTOR,
                    "note": ("人机通道归主控：用户只对主控说话。你不是主控 ⇒ 不许当面问用户，"
                             "把未决问题写进你的最终结果交回召唤者，由主控汇总给人。")}
        timeout = payload.get("timeout_sec")
        outcome = U.ask_user(
            self.session_root, role=self.role,
            question=str(payload.get("question") or ""),
            options=payload.get("options") or (),
            timeout_sec=(self.user_timeout_sec if timeout is None else float(timeout)),
            sid=self.sid, header=str(payload.get("header") or ""),
            multi_select=bool(payload.get("multi_select")),
            policy=self.ask_policy,
            # 取消的判据来自「发起的这一趟运行」自己的取消令牌（`cancellation.py`
            # 的协作式取消：谁发起、谁置位），不引入第二个全局开关。
            cancel_check=(lambda: bool(getattr(self.token, "cancelled", False))
                          if self.token is not None else False))
        if outcome.state == U.STATE_ANSWERED:
            return {"asked": outcome.qid, "answer": outcome.answer, "by": outcome.by,
                    "selected": list(outcome.selected), "custom": outcome.custom,
                    "ok": True}
        if outcome.state == U.STATE_REFUSED:
            return {"asked": "", "ok": False, "problem": outcome.problem,
                    "state": outcome.state,
                    "note": (outcome.note or "无人值守档：问用户被确定性拒绝。")
                            + "按最保守的做法继续，并把「这件事本该问用户但没人可问」"
                              "写进你的结论（不许自己替用户定这个取舍）。"}
        if outcome.state == U.STATE_PENDING:
            return {"asked": outcome.qid, "ok": False, "problem": outcome.problem,
                    "state": outcome.state, "waited_sec": round(outcome.waited_sec, 3),
                    "note": (outcome.note or "还停在等用户回答。")
                            + " 框架会停下这一趟等人答完再续跑；"
                              "绝不许把它当成用户同意，也不许在结论里假装问过了。"}
        if outcome.state == U.STATE_CANCELLED:
            return {"asked": outcome.qid, "ok": False, "problem": outcome.problem,
                    "state": outcome.state, "waited_sec": round(outcome.waited_sec, 3),
                    "note": (outcome.note or "等待被取消。")
                            + " 这一趟停在这里；取消不等于用户答过了。"}
        # 问题没能落档：这不是"停在等回答"（没有 qid 就没有人能答），也不是用户的意见。
        return {"asked": outcome.qid, "ok": False, "problem": outcome.problem,
                "note": (outcome.note or "问题没能落进用户频道。")
                        + " 按最保守的做法继续，并把这件事写进结论。"}

    def _do_note(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        path, problem = write_note(self.session_root, self.role,
                                   str(payload.get("text") or ""), sid=self.sid)
        if problem:
            return {"note": "没写成", "ok": False, "error": problem}
        return {"note_written": path, "ok": True}


# ------------------------------------------------------------------ 后端
@dataclass
class LlmBackend:
    """把登记过的 (角色, 动作) 交给 LLM 循环，其余交给内层后端（`LocalBackend`）。

    为什么要"按动作登记"而不是"整个角色交给模型"：角色的确定性动作（算图、分配号、
    落一行表）不该被模型取代 —— 那正是本仓库反复守的那条线（模型只做语义判断）。
    于是接线表显式列出哪些动作由模型驱动，其余照旧走 Python 实现。
    """

    inner: Any
    loops: Mapping[tuple[str, str], Mapping[str, Any]]
    session_root: Path
    registry: Any = None
    conductor: Any = None
    seam_factory: Any = None
    max_steps: int = 30
    workspace_root: str = ""
    sid: str | None = None
    store: Any = None
    #: 用户叫停的开关文件（见 `AgentLoop.stop_file` 的同名注释）：由 CLI 在「单趟」
    #: `run-agent` 时接上；多轮的自主跑刻意留空（那一档的停机点在每轮之间）。
    stop_file: str = ""
    name = "llm"

    def known_roles(self) -> list[str]:
        """能接活儿的角色（模型驱动的那些 + 内层后端登记的那些）。"""
        return sorted({role for role, _action in self.loops} | set(self.inner.known_roles()))

    def resolve(self, role: str) -> Any:
        """本后端不提供实例（它按动作决定走哪条路），把问题交给内层。"""
        return self.inner.resolve(role)

    def call(self, role: str, action: str, params: Mapping[str, Any], *, token: Any,
             instance: str = "", task_id: str = "") -> Any:
        """登记过的 `(角色, 动作)` 走 LLM 循环；其余交给内层后端（确定性实现）。"""
        cfg = self.loops.get((role, action))
        if cfg is None:
            return self.inner.call(role, action, params, token=token, instance=instance,
                                   task_id=task_id)
        seam = self._seam(role)
        loop = AgentLoop(role=role, session_root=self.session_root, registry=self.registry,
                         seam=seam, conductor=self.conductor, max_steps=int(cfg.get("max_steps", self.max_steps)),
                         workspace_root=self.workspace_root, sid=self.sid, token=token,
                         store=self.store, stop_file=self.stop_file)
        row = self._running_row(role, task_id)
        run = loop.run(str(cfg.get("task_from_params") or "") or _task_text(params, role, action),
                       summoned_by=str(row.get("called_by") or params.get("_summoned_by")
                                       or S.CONDUCTOR_ROLE),
                       my_task_id=str(row.get("task_id") or params.get("_task_id") or ""),
                       depth=int(row.get("depth") or params.get("_depth") or 1))
        artifact = self._write_run_artifact(role, run)
        SS.append(self.session_root, {"kind": "agent_run_artifact", "role": role,
                                      "path": artifact, "stop_reason": run.stop_reason,
                                      "task_id": run.prompt_audit.get("task_id", "")}, sid=self.sid)
        out = {"llm_run_path": artifact, "final": run.final, "stop_reason": run.stop_reason,
               "steps": len(run.steps), "summons": run.summons, "messages": run.messages_sent}
        if not artifact:
            out["llm_run"] = run.to_dict()      # 落盘失败时退回内联，绝不静默丢产出
        return out

    def _seam(self, role: str) -> LlmSeam:
        if self.seam_factory is not None:
            return self.seam_factory(role)
        raise RuntimeError("LlmBackend 需要 seam_factory（一个按角色造模型缝的调用方）")

    def _write_run_artifact(self, role: str, run: LoopRun) -> str:
        """把这次循环的完整记录写成文件，返回路径（失败就返回空串并留 note）。"""
        try:
            d = self.session_root / RUNS_DIR_NAME
            d.mkdir(parents=True, exist_ok=True)
            n = len(list(d.glob(f"{role}-*.json"))) + 1
            path = d / f"{role}-{time.strftime('%Y%m%d-%H%M%S')}-{n:03d}.json"
            path.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")
            return str(path)
        except OSError as exc:
            run.notes.append(f"产出落盘失败：{type(exc).__name__}: {exc}")
            return ""

    def _running_row(self, role: str, task_id: str = "") -> dict[str, Any]:
        """找出"这次召唤那条 running 行"，整行返回。

        两条取材路径，按可靠性排序：

        1. 给了 `task_id`（`Conductor.summon` 现在会传，见 `conductor.py` 第 [6] 步）：
           直接按号取那一行 —— 并发多实例下这是唯一可靠的做法（按角色找会同时找到 N 条）。
        2. 没给号（旧调用方 / 直接建 `LlmBackend` 的单测）：退回"按角色找恰好一条"。

        为什么要找而不是让调用方传：`Conductor.summon` 先写 running 行、再调后端，
        所以后端天然不知道自己的台账号。三种"没拿到"必须分得开（没有台账 /
        读台账失败 / 恰好不是一条），所以返回值带 `checked` 与 `reason`，
        而不是给一个"看起来像没结果"的空字典。提示词据此如实写"本次运行未拿到台账号"。

        ## 为什么返回整行而不是只返回 `task_id`（2026-09-30 修的 bug）

        子循环的 `summoned_by` / `depth` 以前读 `params["_summoned_by"]` /
        `params["_depth"]`，而全仓没有任何地方生产这两个键 ⇒ 每一次被同伴
        唤起的角色都以为"是主控直接派的、深度 1"。实测（`temp/review-task-20260930-111332`）：
        台账里 `t-0260 E.run_experiment called_by=F parent=t-0259 depth=2`，
        而 E 自己的 `agent_run_start` 记的是 `summoned_by=M, depth=1` ——
        协同链在孩子自己的认知里断掉，"像主控的 subagent"这句话就不成立。
        权威来源本来就是台账那一行（`called_by` / `depth` 都在上面），直接读它。
        """
        store = self.store
        if store is None:
            return {"checked": False, "reason": "本次运行没有 store（读不到台账）"}
        want = str(task_id or "")
        try:
            rows = [dict(r) for r in store.rows("tasks")
                    if (str(r.get("task_id")) == want if want
                        else (str(r.get("role")) == role and str(r.get("status")) == "running"))]
        except Exception as exc:
            return {"checked": False, "reason": f"读 tasks 表失败：{type(exc).__name__}: {exc}"}
        if len(rows) != 1:
            why = (f"台账号 {want} 在 tasks 表里不是恰好一条（{len(rows)} 条）" if want
                   else f"running 行不是恰好一条（{len(rows)} 条）")
            return {"checked": False, "reason": why + "，不猜台账号"}
        row = dict(rows[0])
        row["checked"] = True
        return row


def _task_text(params: Mapping[str, Any], role: str, action: str) -> str:
    """把召唤参数渲染成给孩子看的任务描述（没有参数时如实说明）。"""
    given = {k: v for k, v in (params or {}).items() if not str(k).startswith("_")}
    if not given:
        return f"{role}.{action}：这次没有带参数（调用方只要求你按职责做这件事）。"
    return (f"{role}.{action}：调用方给了这些参数：\n"
            + "\n".join(f"- {k}：{_clip(v, 400)}" for k, v in given.items()))


# ---------------------------------------------------------------- 单趟的检查点与续跑
#
# ## 为什么需要它（`autonomy` 那一层已经有一份检查点，为什么还要第二份）
#
# `autonomy.checkpoint_path` 记的是"这一程跑到第几轮"（按轮粒度，文件名里没有 sid）。
# 而这一层要解决的是「轮内」的停与续：`ask_user` 让循环停在半路上（`waiting_for_user`），
# 人答完之后要接着「那一步之后」往下跑，而不是把这一轮从头再做一遍 ——
# 一轮可能已经写了数据、发了留言、花了几毛钱，重做一遍的代价与"两件事混成一条"
# 的风险都不小。于是这里按 (角色, 会话号) 记到「步」。
#
# 两份检查点不是同一件事的两处实现：轮的对账在 `autonomy`，步的对账在这儿。
def run_checkpoint_path(session_root: Path | str, role: str, sid: str | None = None) -> Path:
    """这一趟的检查点路径：`<根>/runs/agent-<角色>-<会话号>.json`。

    `runs` 这个目录名从 `autonomy.CHECKPOINT_DIR_NAME` 读（不在这里再写一份字面量）：
    两处各写一份，将来改目录名就会变成"一半的检查点落在旧目录里"——
    而那种漂移没有任何判据看得见（读不到 = 当成"没跑过"）。
    那个 import 写在函数里是因为 `autonomy` 在模块级 import 本模块（循环依赖）。
    """
    from . import autonomy as AU

    sid_text = str(sid or "") or SS.session_id()
    return Path(session_root) / AU.CHECKPOINT_DIR_NAME / f"agent-{role}-{sid_text}.json"


def save_run_checkpoint(session_root: Path | str, role: str, sid: str | None, *,
                        task: str, step: int, stop_reason: str,
                        waiting_for: str = "", spend: Mapping[str, Any] | None = None) -> str:
    """写这一趟的步检查点，返回问题串（空 = 写成了）。写入失败不许静默。

    指纹用 `autonomy.task_fingerprint(role, task)`（同一条口径，不另立一份）：
    续跑之前必须比对它 —— 拿 A 任务的检查点去续 B 任务，会把两件事的进度混成一条，
    而那条记录看起来完全正常。
    """
    from . import autonomy as AU

    path = run_checkpoint_path(session_root, role, sid)
    payload = {"role": role, "sid": str(sid or ""), "task": task,
               "fingerprint": AU.task_fingerprint(role, task),
               "step": int(step), "stop_reason": str(stop_reason),
               "waiting_for": str(waiting_for or ""),
               "spend": dict(spend or {}),
               "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"
    return ""


def load_run_checkpoint(session_root: Path | str, role: str,
                        sid: str | None = None) -> dict[str, Any] | None:
    """读步检查点；不存在或读不出来都返回 `None`（调用方据此如实报"没查成"）。"""
    path = run_checkpoint_path(session_root, role, sid)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _is_fresh_run_start(event: Mapping[str, Any]) -> bool:
    """这条 `agent_run_start` 是不是"从第 0 步开始的一趟"。

    为什么需要这个谓词：会话记录里同一个 (角色, 任务) 会有「多条」 run_start ——
    每次 `--resume` 都写一条（带着 `resumed_from`），每次「被拒的续跑」
    （指纹不符 / 还在等 / 已收工）也写一条（带着 `resume_refused`）。
    重建 transcript 要找的是"这一趟对话的起点"，也就是最后一条「全新开始」的那条；
    把"被拒的续跑"误当成起点，会让重建读到一段空对话（真机撞到过：问了 → 又跑了一次
    还是没人答 → 人答了 → 续跑却说"没有转录"，而能续的那一段其实还在盘上）。
    """
    if event.get("resume_refused"):
        return False
    return int(event.get("resumed_from") or 0) == 0


def resume_transcript(session_root: Path | str, role: str, sid: str | None,
                      *, task: str) -> tuple[str, int]:
    """从会话记录重建"本趟"的 transcript，返回 `(transcript, 下一个 step)`。

    ## 判据：与循环里拼出来的那一份逐字一致

    重建只认两样东西：本趟的起点（最后一条"全新开始"的 `agent_run_start`，
    它带着任务 / 发起者 / 深度 / 台账号）与它之后逐条落盘的 `agent_step` 事件。
    每一行的拼法都走 `agent_loop` 里那几个模块级函数
    （`_opening_transcript` / `_step_line` / `_invalid_line` / ...）——
    循环里也是它们，所以"两处拼法"这件事在结构上不成立。

    ## 窗口怎么定（这是最容易读错的一段）

    - 「起点」 = 最后一条 `role` 相同、`task` 原文相同、且 `_is_fresh_run_start`
      为真的 run_start。续跑写下的那些 run_start（`resumed_from>0`）与
      「被拒的续跑」（`resume_refused`）都不是起点 —— 后者尤其重要：它没有步，
      若被当成起点，重建就会变成空的那一段，而"能续的那一段"其实还在后面。
    - 「终点」 = 该角色下一条"全新开始"的 run_start（任何任务）。它挡住两件事：
      同一任务被从头重跑（那一段应当在它自己的窗口里重建），
      以及同角色另一个任务的步混进来（`agent_step` 事件里没有任务号，
      窗口是唯一能把两趟分开的东西）。
    - 窗口里的「续跑段」照收：步号是全趟单调的（续跑从 `resumed_from` 接着编），
      所以"续了两趟"的那些步拼起来正好是当时那份对话。

    ## 三条要说清的边界（不假装比实际更强）

    1. 「收件箱那一段是现读的」：开头的"你的收件箱"用 `inbox_digest` 按当前盘上的
       状态重算（续跑本来就该听到新到的留言）。于是原趟开头若带着"（新）"标记，
       重建出来的那几行会不同 —— 变的只会是收件箱那一段，而且只会变新，不会变假。
    2. 「单字段超过落档上限的那一步」：事件里存的是截到 `RECORD_CHARS` 的审计副本，
       所以那一行的末尾会比当时短（截断标记留在文本里，短了这件事本身可读）。
       在"两条都要逐字相等"的意义上，这一档是重建能力的上限，不是我漏了。
    3. 「找不到本趟的起点 ⇒ 返回 `("", 0)`」：不猜、不退回"把所有步都收进来"。
       调用方（`run_role`）据此判"没查成"，而不是从第 1 步重跑一遍 ——
       把没读到当成"没做过"，正是这一整套三态纪律要挡的形态。
    """
    root = Path(session_root)
    events, _problems = SS.read_session(root, sid=sid)
    role_starts = [i for i, e in enumerate(events)
                   if e.get("kind") == "agent_run_start" and str(e.get("role")) == role]
    fresh_mine = [i for i in role_starts
                  if _is_fresh_run_start(events[i]) and str(events[i].get("task")) == task]
    if not fresh_mine:
        return "", 0
    begin = fresh_mine[-1]
    fresh_any = [i for i in role_starts if _is_fresh_run_start(events[i])]
    end = next((i for i in fresh_any if i > begin), len(events))
    head = events[begin]
    inbox, _fresh, _problems2 = inbox_digest(root, role, sid=sid)
    parts = [_opening_transcript(task, inbox=inbox,
                                 summoned_by=str(head.get("summoned_by") or ""),
                                 task_id=str(head.get("task_id") or ""),
                                 depth=int(head.get("depth") or 1))]
    next_step = 0
    for e in events[begin + 1:end]:
        if e.get("kind") != "agent_step" or str(e.get("role")) != role:
            continue
        step = int(e.get("index") or 0)
        shape = str(e.get("shape") or "")
        payload = e.get("payload") if isinstance(e.get("payload"), Mapping) else {}
        result = e.get("result") if isinstance(e.get("result"), Mapping) else {}
        if shape == "invalid":
            problem = str(result.get("problem") or "")
            if problem == "judge_bad_args":
                parts.append(_bad_args_line(step, str(result.get("detail") or "")))
            elif problem == "judge_bad_json":
                parts.append(_bad_json_line(step, problem, str(result.get("detail") or "")))
            else:
                parts.append(_invalid_line(step, problem))
        else:
            parts.append(_step_line(step, payload, result))
        next_step = max(next_step, step + 1)
    return "".join(parts), next_step


def _task_fingerprint(role: str, task: str) -> str:
    """`autonomy.task_fingerprint` 的转发（延迟 import：`autonomy` 在模块级 import 本模块）。

    为什么不在这里自己算一遍哈希：指纹的口径只有一处才叫口径。两处各算一次，
    将来任何一边动一个字符（换分隔符、截断长度），续跑就会一边说"指纹一致"、
    另一边说"不符"，而没有任何判据会因此变红。
    """
    from . import autonomy as AU

    return AU.task_fingerprint(role, task)


def _note_resume_refusal(root: Path, role: str, task: str, sid: str | None, why: str,
                         *, attempted_from: int = 0) -> None:
    """续跑被拒时也落一条 `agent_run_start`：为什么拒必须留在会话记录里。

    为什么不静默返回：`--resume` 被拒的那一趟在盘上什么都没留下，
    读会话记录的人只会看到"上一趟到此为止" —— 而"它被人要求续过、被拒了"
    这件事没有任何痕迹。这一条与 `AgentLoop.run` 里那条同名事件的区别有两个，
    两个都是刻意的：

    - 它带 `resume_refused` 这个码，且「没有」后续的 `agent_step`（一步都没跑）；
    - 它「不写 `resumed_from`」，而写 `resume_attempted_from`。
      为什么：`resumed_from` 的口径是"这一趟真的从第几步接着跑"（0 = 全新开始）——
      被拒的续跑一步都没跑，写 0 会被读成"它从第 0 步续的"（同一个字段两种含义，
      而读数的人只看得见那个 0）。"它想从第几步续"是另一件事，就得有另一个名字。
    """
    SS.append(root, {"kind": "agent_run_start", "role": role, "task": task,
                     "waiting_for": "", "resume_refused": why,
                     "resume_attempted_from": int(attempted_from)}, sid=sid)


def run_role(role: str, task: str, *, store: Any, registry: Any,
             session_root: Path | str | None = None,
             conductor: Any = None, seam: LlmSeam | None = None, gateway: Any | None = None,
             max_steps: int = 30, usd_budget: float | None = None,
             workspace_root: str = "", sid: str | None = None, token: Any = None,
             from_env: bool = True, user_timeout_sec: float | None = None,
             ask_policy: str | None = None, resume: bool = False,
             stop_file: str = "") -> LoopRun:
    """跑一个角色的一次循环（真机或替身都走这一条）。

    `session_root` 不给时取 `store.root`：会话记录的落点就该是项目根，
    两处分开写迟早会出现"审计记录落在别处"的静默错位。

    ## `resume=True`（`agentflow run-agent --resume` 那条路）

    先读这一趟的步检查点，四种结局分开（三态纪律：不许把"没读到"折成"重跑一遍"）：

    | 检查点 | 结局 |
    |---|---|
    | 读不到 | `stop_reason="no_checkpoint"`（没查成，一步模型都不调） |
    | 任务指纹不符 | `stop_reason="checkpoint_mismatch"`（拿 A 的进度续 B = 把两件事混成一条） |
    | 上一趟已收工（`final`） | `stop_reason="already_finished"`（续跑没有意义，不许重跑） |
    | 停在等用户 / 其它 | 从 `resume_transcript` 重建的那一段接着跑 |

    无论哪一条路，跑完都写一次步检查点（停在等用户时带 `waiting_for=<qid>`）——
    于是"上一趟停在等"与"上一趟做完了"在盘上是两件事，`--resume` 分得开。
    被拒的那几条路也各写一条 `agent_run_start`（带 `resume_refused` 与
    `resume_attempted_from`）：「只带 `resumed_from` 的那条事件才是真的接着跑了」。
    """
    root = Path(session_root) if session_root is not None else Path(str(getattr(store, "root", "")))
    if not str(root):
        raise ValueError("run_role 需要 session_root，或一个带 root 的 store")
    if seam is None:
        seam = LlmSeam.for_role(role, session_root=root, gateway=gateway,
                                usd_budget=usd_budget, sid=sid, from_env=from_env)
    loop = AgentLoop(role=role, session_root=root, registry=registry, seam=seam,
                     conductor=conductor, max_steps=max_steps, workspace_root=workspace_root,
                     sid=sid, token=token, store=store, user_timeout_sec=user_timeout_sec,
                     ask_policy=ask_policy, stop_file=str(stop_file or ""))
    summoned_by = S.CONDUCTOR_ROLE if role == S.CONDUCTOR_ROLE else ""
    start_depth = 1 if role == S.CONDUCTOR_ROLE else 2
    if resume:
        cp = load_run_checkpoint(root, role, sid)
        if cp is None:
            _note_resume_refusal(root, role, task, sid, "no_checkpoint")
            return LoopRun(role=role, task=task, stop_reason="no_checkpoint",
                           final=(f"要求续跑，但读不到这一趟的检查点"
                                  f"（{run_checkpoint_path(root, role, sid)}）⇒ 没查成。"
                                  "不许当成'从第 1 步重跑'：重跑会把已经做过的活再做一遍。"))
        if str(cp.get("fingerprint")) != _task_fingerprint(role, task):
            # 指纹不符时「不给」 `attempted_from`：那份检查点是另一个任务的，
            # 它的 `step` 数不是"这件事做到第几步"。
            _note_resume_refusal(root, role, task, sid, "checkpoint_mismatch")
            # `draft/37` §140：拒信要把检查点里那条任务原文交回去（照抄就能续）。
            # 实测（2026-10-05，两个工作区各撞一次）：用"原任务"去续一条以"续作任务"
            # 起的检查点 ⇒ 被拒，而拒信里没有那句该照抄的话，于是那一段成了空段
            # （一步都没跑，而驱动器还以为它在跑）。
            was = str(cp.get("task") or "")
            return LoopRun(role=role, task=task, stop_reason="checkpoint_mismatch",
                           final=("检查点里的任务指纹与这次的任务不一致 ⇒ 不许续跑："
                                  "拿一个任务的进度去续另一个任务会把两件事混成一条，"
                                  "而那条记录看起来完全正常。要接着跑就照抄检查点里那条"
                                  f"任务原文（`{run_checkpoint_path(root, role, sid)}` 的 "
                                  f"`task` 字段）：\n{was}"))
        if str(cp.get("stop_reason")) == "final":
            _note_resume_refusal(root, role, task, sid, "already_finished",
                                 attempted_from=int(cp.get("step") or 0))
            return LoopRun(role=role, task=task, stop_reason="already_finished",
                           final="上一趟已收工（final），续跑没有意义：没有要做的事。"
                                 "要做新的事就给一个新的任务原文（那会换一份检查点）。")
        waiting = str(cp.get("waiting_for") or "")
        if waiting:
            # 上一趟停在等某个问题：还没人答就「再停一次」，不许静默接着跑。
            #
            # 为什么这条必须在跑之前判（而不是靠模型自己"看见提示词里没有问题"）：
            # 续跑那一段的提示词里带着"我上次问了 q0001"，而模型完全可以自行决定
            # "既然没人答，我按最保守的做法继续" —— 那正是用户 2026-10-03 裁掉的
            # 形态（"就停着"）。框架这一层必须把"没答"死死地钉住：
            # 没有回答事件，就没有下一步。
            answered = {str(r.get("qid") or "") for r in U.read_replies(root, sid=sid)}
            if waiting not in answered:
                _note_resume_refusal(root, role, task, sid, "still_waiting",
                                     attempted_from=int(cp.get("step") or 0))
                return LoopRun(role=role, task=task, stop_reason="waiting_for_user",
                               waiting_for=waiting,
                               final=(f"还在等 {waiting} 的回答：没有人答就不接着跑"
                                      "（不许把「没答」当成默许，也不许从没答的地方重跑）。"
                                      f"用 `agentflow --root {root} answer {waiting} \"<回答>\"{f' --sid {sid}' if sid else ''}` 答完，再用 "
                                       f"`agentflow --root {root} run-agent --resume …"
                                       f"{f' --sid {sid}' if sid else ''}` 续跑。"))
        rebuilt, step0 = resume_transcript(root, role, sid, task=task)
        if step0 <= 0:
            _note_resume_refusal(root, role, task, sid, "resume_no_transcript",
                                 attempted_from=int(cp.get("step") or 0))
            return LoopRun(role=role, task=task, stop_reason="resume_no_transcript",
                           final=("要求续跑，但会话记录里重建不出这一趟的任何一步"
                                  "（同角色 + 同任务原文的 `agent_step` 一条都没有）"
                                  "⇒ 没查成：不许从第 1 步重跑。"))
        run = loop.run(task, summoned_by=summoned_by, my_task_id="", depth=start_depth,
                       resumed=(rebuilt, step0),
                       waiting_for=str(cp.get("waiting_for") or ""))
    else:
        run = loop.run(task, summoned_by=summoned_by, my_task_id="", depth=start_depth)
    completed = run.resumed_from + len(run.steps)
    problem = save_run_checkpoint(root, role, sid, task=task, step=completed,
                                  stop_reason=run.stop_reason, waiting_for=run.waiting_for,
                                  spend=run.spend)
    if problem:
        run.notes.append(f"这一趟的步检查点没写成（{problem}）：下一趟 `--resume` 会读到"
                         "更早的一份（或读不到），于是它要么多跑几步、要么如实报'没查成'")
    return run


def selftest() -> int:
    """自检：形状判定与收件箱（不需要模型、不需要网络）。"""
    problems: list[str] = []

    def check(ok: bool, what: str) -> None:
        """记一条自检结论（不通过就写进 problems，供最后统一打印）。"""
        if not ok:
            problems.append(what)

    shape, payload, problem = _shape_of({"tool": "graph.stats", "args": {}})
    check((shape, problem) == ("tool", ""), f"tool 形状判错：{shape}/{problem}")
    check(payload.get("name") == "graph.stats", "tool 名字没取到")
    shape, _p, problem = _shape_of({"summon": {"role": "E", "action": "run_experiment"}})
    check((shape, problem) == ("summon", ""), f"summon 形状判错：{shape}/{problem}")
    shape, _p, problem = _shape_of({"summon": {"role": "Z", "action": "x"}})
    check(shape == "" and "不在" in problem, "不存在的角色没有被拒")
    shape, _p, problem = _shape_of({"tool": "a", "final": "b"})
    check(shape == "" and "一次只能说一件事" in problem, "两种形状同时出现没有被拒")
    shape, payload, problem = _shape_of({"final": "做完了", "evidence": ["c-0001"]})
    check((shape, problem) == ("final", "") and payload["evidence"] == ["c-0001"],
          "final 形状判错")

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        msg_id, problem = send_message(root, sender="M", to="D", subject="任务", body="看一下这个")
        check(problem == "" and msg_id == "m0001", f"发消息失败：{msg_id}/{problem}")
        digest, fresh, problems_ = inbox_digest(root, "D", sid=SS.session_id())
        check("看一下这个" in digest and fresh == ["m0001"], f"收件箱没读到：{digest!r}/{fresh}")
        check(not problems_, f"读会话时报了问题：{problems_}")
        mark_delivered(root, "D", fresh, sid=SS.session_id())
        digest2, fresh2, _ = inbox_digest(root, "D", sid=SS.session_id())
        check(fresh2 == [] and "（新）" not in digest2, "投递登记没有生效")
        other, fresh_other, _ = inbox_digest(root, "E", sid=SS.session_id())
        check("（没有收到留言）" == other and fresh_other == [], "别人的留言跑进了 E 的收件箱")

    if problems:
        print("SELF-CHECK FAILED")
        for p in problems:
            print("  -", p)
        return 1
    print("SELF-CHECK DONE（六种形状的形状判定 + 消息投递与隔离）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(selftest())

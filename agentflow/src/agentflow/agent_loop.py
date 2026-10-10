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

## 循环形状（正典清单与条数只在 `SHAPES` 一处定义；下面是其中最常用的四种）

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
SHAPES = ("tool", "summon", "summon_many", "message", "handoff", "note", "ask_user", "final",
          "retire", "roster", "interrupt")
#: 出站门：哪些形状由秘书接管（所有者的裁定逐字"如果有些形状涉及到结构化交互，
#: 则需要秘书接管"）。判据是"这个形状是不是跨智能体的结构化交互"——
#: `summon` / `summon_many`（委托）· `handoff`（手稿通道）· `message`（私聊/公共频道，
#: 带 `to`/`subject`/`body`/`reply_to` 四个字段与一条协作边准入）。
#: 不在门里的四个（`tool` = 代码的硬闸与参数表；`note` = 写自己的台账；
#: `ask_user` = 直接问用户；`final` = 终态字段闸 `notify_reading`）各有各的接住者，
#: 登记在 `tests/test_secretary.py::STRUCTURED_INTERACTION` / `NOT_STRUCTURED` 那张表里
#: （形状表与登记表等额：新增一个形状不登记就红）。
SECRETARY_OUTBOUND_SHAPES: tuple[str, ...] = ("summon", "summon_many", "handoff", "message")

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
    # S1k-2 的 `retire`（业主 T22 的名册口径）：必填键表也在这里一处 ——
    # 父拿着名册名说"A1 退役"。`roster` 不进这张表：它的 `of` 可省（缺省 = 自己），
    # 没有"必填的扁平键"这回事（空键表会让扁平化那条路写出一个没有键的对象）。
    ("retire", ("name",), "name"),
)

#: 这些拒绝理由 ⇒ 自动转成"请主控代唤"的申请（2026-09-30）。
#:
#: `forbidden_edge`：目标不在 `capabilities.ALLOWED_EDGES` 里（例如 G 想找 A 要文献）；
#: `depth_exceeded`：召唤链已经到 `policy.max_depth`。两者都是"这条路今天不通"，
#: 而不是"我参数写错了" —— 参数错（`invalid_params`）该自己改，越权不该重试。
RELAY_REFUSALS: frozenset[str] = frozenset({"forbidden_edge", "depth_exceeded"})

#: 代唤申请的留言标题（机器可识别的那一位；改它要同时改提示词里的同一句）。
RELAY_SUBJECT = "请代唤"

#: 定义待补那件事的向上报文标题（`draft/97` §15.4 的①档：问直接父）。
#:
#: 为什么与 `RELAY_SUBJECT` 分开：那一条是"我要做的事被策略拒了，请父替我召唤"，
#: 这一条是"我缺一条定义，请父就地给我"。收件人同一套（`_relay_recipient`），
#: 但载荷与事件种类不同 —— 折成同一个标题，审计就分不出"这一次到底是哪种请求"。
DEFINITION_ASK_SUBJECT = "定义待补：请就地给出"

#: 每一步最后读到的那段输出契约（`draft/28` §195）。
#:
#: 为什么要在最后一行重述一遍：系统提示词有 6k+ token，循环协议埋在中间；
#: 真机实测（2026-09-30，M 做"核验定理与引理的证明"）—— 模型连着三次回 1400–2400 字的散文，
#: `judge_bad_json` × 3 ⇒ `bad_json_limit`，那次运行对交付物零贡献。
#: 它不是不听指令，是没读到：中间那句"请只输出一个 JSON 对象"离它的回答太远了。
JSON_TAIL = (
    "只回一行 JSON（不要解释、不要 Markdown 围栏、不要前后缀）。形状取其一"
    "（键名与嵌套层级照抄，`<...>` 是占位符）。**括号数看最后两行**："
    "`tool` 那行只以一个 `}` 结尾；`summon` / `summon_many` / `message` / `handoff` / "
    "`final` 这几行**本来就以 `}}` 结尾**（嵌套两层）—— 照抄时别再多补一个，"
    "实测最常见的坏 JSON 就是多补一个 `}`：\n"
    '{"tool": "<工具名>", "args": {...}}\n'
    '{"summon": {"role": "A-H", "action": "<动作名>", "params": {...}}}\n'
    '{"summon_many": {"targets": [{"role": "A-H", "action": "<动作名>", "instance": "<可选>"}],'
    ' "why": "<为什么一次派这一批>"}}\n'
    '{"message": {"to": "<伙伴或 #public>", "subject": "...", "body": "..."}}\n'
    # 骨架里的字段名用协议的首选名（2026-10-07 修）：这里原写 `"title"` + `"brief"`，
    # 而 `HANDOFF_PROTOCOL` 逐字写着"旧名仍然接受，但新写的一律用 `summary`" —— 骨架是
    # 每一步都发的那份文档、模型照抄它，两边口径相反却因为解码器三个名字都收而没有任何
    # 地方会报错。判据：`tests/test_agent_loop.py::test_the_skeleton_teaches_the_preferred_handoff_field_names`
    # （骨架必须用 `summary`；且"旧名仍然接受"这半句兼容性也当场真调验证）。
    '{"handoff": {"to": "<伙伴/M/ALL>", "summary": "<一句话描述>", "body": "<markdown 正文>",'
    ' "refs": ["<前序手稿编号>"], "revises": "<要订正的手稿号，可不填>"}}\n'
    '{"note": "一句话"}\n'
    '{"ask_user": {"question": "...", "options": ["..."]}}\n'
    # S1k-2（业主 T22 的名册口径）：两个新形状。`brief` 是"造一个子代理"时必给的一句简介；
    # 复用已有子代理写 `reuse:"D1"`（名册名，不是台账号）—— 它不新增名册项，只多一次调用。
    '{"retire": {"name": "A1"}}\n'
    '{"roster": {"of": "self"}}\n'
    # S-H（裁定 14）：`interrupt` 停的是某一个子代理当前那一轮 —— 它不是全局叫停
    # （那是 `conductor.stop`，所有人都停），也不是"结束它"（那是 `retire`）。
    '{"interrupt": {"name": "D1"}}\n'
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
#: `runs/<角色>-<时间戳>-<序号>.json` 里序号的上限（B11 的 `O_EXCL` 重试用它兜底）。
_RUN_ARTIFACT_MAX_SEQ = 9999

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


#: 一次召唤里"这件事是什么"的主题字段（按优先级）：同一个主题 + 同一类读数 = 同一条路。
#: 为什么按字段值取主题、而不是拿整份参数：参数里最先变的往往是"这次改的那一处"
#: （Lean 源码、一行措辞），而主题字段恰恰是不该变的那一部分。
_STALL_SUBJECT_KEYS: tuple[str, ...] = ("claim", "statement_full", "topic", "title",
                                        "problem", "script_path", "path", "doc_id")


def _norm_subject(value: Any) -> str:
    """主题的规范化：压空白、去标点、转小写、截前 60 字（换一行不算换了题目）。"""
    text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip().lower()
    text = re.sub(r"[^\w\u4e00-\u9fff ]+", "", text)
    return text[:60]


def _summon_reading_class(result: Mapping[str, Any]) -> str:
    """召唤这一步的"读数类"：只取结论形态（`reason` / `verified` / `outcome`），不取数值。

    `result["payload"]` 是工具层原样回的那份 JSON（字符串），真机里形如
    `{"checked": true, "verified": false, "reason": "compile_error", ...}` ——
    `reason` 正是"这一类的结论"。
    """
    raw = result.get("payload")
    data: Any = {}
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            data = json.loads(raw)
        except ValueError:
            data = {}
    elif isinstance(raw, Mapping):
        data = dict(raw)
    if not isinstance(data, Mapping):
        data = {}
    for key in ("reason", "status", "outcome"):
        got = data.get(key) or result.get(key)
        if isinstance(got, str) and got:
            return f"{key}={got[:40]}"
    if "verified" in data:
        return f"verified={bool(data['verified'])}"
    return f"outcome={result.get('outcome') or result.get('status') or 'ok'}"


def _stall_key(shape: str, payload: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    """「同一条路」的粗键：目标 + 主题 + 读数类（`draft/39` §6.23 的 D31）。

    真机读数（T1 第 17 趟）：M 连着 19 次 派 `E.check_formal`，每一步都改一处
    Lean 源码再试，读数一路是 `reason=compile_error`（报错从 `expected token`
    变成 `unsolved goals` / `simp made no progress`）—— 参数每次都不同，于是
    `_call_key` 那条"同参数"的连击每步都归零，活性判据眼看着它烧掉 60 步 / $1.6、
    一句话都没说。"改了参数"不等于"换了做法"：这一条认的是同一条路 + 同一类读数。

    只对召唤（`summon` / `summon_many`）算：工具调用那条路已经由
    `_call_key` + `_call_reading` 逐字看住了，再叠一层只会把"参数确实变了的重问"
    误判成卡住。
    """
    if shape not in ("summon", "summon_many"):
        return ""
    if shape == "summon":
        targets = [payload]
    else:
        targets = [t for t in (payload.get("targets") or []) if isinstance(t, Mapping)]
    if not targets:
        return ""
    parts: list[str] = []
    for t in targets:
        params = t.get("params")
        params = params if isinstance(params, Mapping) else {}
        subject = ""
        for key in _STALL_SUBJECT_KEYS:
            if params.get(key) not in (None, ""):
                subject = _norm_subject(params[key])
                break
        parts.append(f"{t.get('role')}.{t.get('action')}#{subject}")
    return "|".join(sorted(parts)) + "|" + _summon_reading_class(result)


def _stall_line(*, streak: int, alert: int, what: str) -> str:
    """「同一条路」那一步的提醒（D31）。

    与 `_dead_loop_line` 的分工：那一条认"同一个调用"，这一条认"同一件事、同一类结果"。
    这一条不宣告任何判停（`stall_*` 不参与 `stop_reason`）：真机里那条路最后是
    走通了的，问题不在"该不该停"，而在"没人把这件事说出来、也没人给它一个预算"。
    """
    if streak >= alert:
        return (f"【同一条路】同一件事、同一类读数，这是连续第 {streak} 次（{what}）——"
                f"参数改了但结论没变，那不是新做法。把命题改小到能一次过，"
                f"或者把「卡在哪」写进 final 并如实记「未核到」；"
                f"别把剩下的预算继续交给同一类失败。")
    return (f"【同一条路】同一件事、同一类读数，这是连续第 {streak} 次（{what}）——"
            f"再试之前先换一样东西：把命题改小、换检查条件，或者换一条路"
            f"（数值实验 / 文献 / 论证）。")


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
    return _spoken_half(step, payload) + _result_half(result)


def _spoken_half(step: int, payload: Mapping[str, Any]) -> str:
    """一步的"你说了"那半（S-C 改成消息序列之后，它进 assistant 那条消息）。"""
    return (f"\n\n[第 {step + 1} 步] 你说了：{_clip(_canonical(payload), ECHO_CHARS)}")


def _result_half(result: Mapping[str, Any]) -> str:
    """一步的"框架执行结果"那半（S-C 之后它进 tool 那条消息）。"""
    return f"\n框架执行结果：{_observe(_canonical(result))}"


# ---------------------------------------------------------------- 消息序列（S-C，裁定 5甲）
#
# 搬的是 DSH 的 messages：assistant 带 `tool_calls`、tool 带 `tool_call_id`。
# 我们的形态有一处必须说清的差异：协议是 JSON 形状的（每一步都是一句话，
# 不是原生函数调用），所以"一次工具调用"对我们等于"一步"—— 每一个非 final 的步
# 都落成 `assistant(tool_calls=[{id, name=形状, arguments=载荷}])` + `tool(结果)` 两条。
# `id` 由步号派生（不是随机数）：会话记录里只有步号，而重建序列要与当时那一份逐条相等。

#: 序列里允许的角色（与 DSH 的三种同名）。
MESSAGE_ROLES: tuple[str, ...] = ("user", "assistant", "tool")


def call_id_of(step: int) -> str:
    """第 `step` 步那次调用的 id —— 由步号派生，所以从会话记录里重建得回来。"""
    return f"call-{int(step) + 1}"


def user_message(content: str) -> dict[str, Any]:
    """一条 user 消息（开场简报那一整段、以及插话那一段，都是"别人对我说的"）。"""
    return {"role": "user", "content": str(content)}


def assistant_message(step: int, payload: Mapping[str, Any], *,
                      content: str = "", name: str = "",
                      reasoning: str = "") -> dict[str, Any]:
    """一条 assistant 消息：它在这一步要求了哪一件事（`tool_calls` 那半）。

    `content` 放"你说了"那半（渲染回文本时与改前逐字相同）；`tool_calls` 是结构化的
    那一份（这才是序列化的收益：谁调的、参数是什么，不必再从一行散文里解析）。

    `reasoning`（12-A=乙，业主裁定"原样带回去"）：那一趟"我先想……"的原文，
    占 `reasoning_content` 那一格（DSH 的同名格）。只有非空才写那一格 ——
    写一个空串会让"它没想"与"它想了但原文丢了"在盘上长得一样。
    """
    shape = str(name or payload.get("tool") or payload.get("shape") or "step")
    out: dict[str, Any] = {"role": "assistant", "content": str(content),
                           "tool_calls": [{"id": call_id_of(step), "type": "function",
                                           "function": {"name": shape,
                                                        "arguments": _clip(_canonical(payload),
                                                                           ECHO_CHARS)}}]}
    if reasoning:
        out["reasoning_content"] = str(reasoning)
    return out


def tool_message(step: int, content: str, *, name: str = "") -> dict[str, Any]:
    """一条 tool 消息：框架对第 `step` 步那个调用的回答（`tool_call_id` 必须配对）。"""
    out: dict[str, Any] = {"role": "tool", "tool_call_id": call_id_of(step),
                           "content": str(content)}
    if name:
        out["name"] = str(name)
    return out


def render_messages(messages: Sequence[Mapping[str, Any]]) -> str:
    """把序列渲染成那份 prompt 文本（S-C：`transcript` 从载体降成渲染）。

    逐字不变这件事是刻意的：`run.transcript` 的所有读者（Web UI 的事件回放、续跑、
    `--resume`）拿到的是同一份文本 —— 换的是"谁是载体"，不是"念出来是什么"。

    一处例外（12-A=乙，业主裁定"原样带回去"）：assistant 那条若带 `reasoning_content`，
    它会原样出现在那一句之前，前缀只有"我先想："那几个字（文本传输面唯一需要的结构标记
    —— DSH 靠消息字段把思维链带回去，我们的传输面是一段文本 ⇒ 它必须念出来）。
    代价是提示词变长（裁定里写明的），收益是"它记得自己想过什么"。
    """
    parts: list[str] = []
    for m in messages:
        thought = str(m.get("reasoning_content") or "")
        if thought:
            parts.append(f"\n\n[第 {_step_of_call_id(m)} 步] 我先想：{thought}")
        parts.append(str(m.get("content") or ""))
    return "".join(parts)


def _step_of_call_id(message: Mapping[str, Any]) -> int:
    """从 `tool_calls[0].id`（`call-<n>`）读回步号 —— 渲染"我先想"那一行要用它。"""
    for c in (message.get("tool_calls") or []):
        if isinstance(c, Mapping):
            cid = str(c.get("id") or "")
            if cid.startswith("call-") and cid[5:].isdigit():
                return int(cid[5:])
    return 0


def _recorded_reasoning(text: str) -> str:
    """思维链落档/进消息用的是同一份文本（12-A=乙 的 item-相等前提）。

    为什么要过 `_for_record` 这一道：一段上千字的思维链会随每一步进会话记录，
    而"落档截断"的口径在本仓只有一处（`RECORD_CHARS`）。让消息与事件共用那一份，
    两件事同时成立：① 重建序列与当时那份逐条相等；② 截断标记就在那条消息的文本里
    （"截断这件事要写进那条消息本身"，施工单 §3 第 4 条）。
    """
    raw = str(text or "")
    if not raw:
        return ""
    return str(_for_record({"reasoning": raw})["reasoning"])


class _CompactionRefused(Exception):
    """摘要这一次没拿到（没接线 / 调不通 / 空回复）⇒ 不压，如实落读数。

    与 `ValueError`（接线错误：注入的 summarize 违约）刻意分开：前者是一次失败
    （warn-and-continue，照 DSH 自动路径），后者是本仓自己的接线 bug，该炸就炸。
    """


#: 摘要那一次调用的指令（S-B / 裁定 8乙）。措辞是我们的，不是 DSH 那段逐字：
#: DSH 的 8 个固定小节是给英文会话写的，而我们的历史是中文 + 台账编号 +
#: "三态纪律"那一套本仓特有的口径 —— 逐字搬会让摘要漏掉这几样。
#: 结构照它（固定小节 + 规则），内容按我们的形态写。
COMPACTION_INSTRUCTION = """\
把下面这一段历史改写成一份**可继续工作的检查点摘要**。按这五个小节写，缺的写"无"：

1. 任务与目标：这一趟要做什么（原文里的那句话里的目标，别改写成别的）。
2. 已确认的事实与决定：已经查证过什么、定下过什么口径（带上来源/编号）。
3. 读过与引用过的编号：台账 id（`lit:` / `stmt:` / `exp:` / `rel:` / 手稿号）逐条列出。
4. 未完成与卡点：还没做什么、卡在哪（不知道的写"未知"，不要猜）。
5. 下一步：接着做时第一件该干的事。

规则：只复述上面给的历史里出现过的东西；不许下新结论、不许补充新事实、
不许写"我将要"这类计划外的承诺。摘要要比原文短得多 —— 它是检查点，不是第二份报告。"""


def step_node_tokens(step: int, payload: Mapping[str, Any],
                     result: Mapping[str, Any]) -> int:
    """这一步作为"节点"的估价（S-B：节点计价，给压力门当输入）。

    按未截断的那一份算（施工单 §2 逐字：不要用 `_for_record` 的截断副本 ——
    那会系统性偏小，于是压力门永远晚一步才响）。这里收到的 `result` 是循环手里
    那一份（`_for_record` 之前），所以那一句成立；`_result_half` 内部的
    `_observe` 仍按观测层口径剪一次，那是模型实际看到的那一份 —— 计价要按
    "它会占多少上下文"算，所以用被观测层剪过的那一份是对的。
    """
    from . import tokenestimate as TE

    msgs = [assistant_message(step, payload, name="step", content=_spoken_half(step, payload)),
            tool_message(step, _result_half(result), name="step")]
    return TE.estimate_messages(msgs).tokens


def message_sequence_problem(messages: Sequence[Mapping[str, Any]]) -> str:
    """序列的配对判据（S-C 的负控）：每一条 `tool` 必须挂在上一条 assistant 给的 id 上。

    DSH 的 tool 消息靠 `tool_call_id` 与 assistant 的 `tool_calls[].id` 配对 ——
    挂错 id 的后果是模型看到"一个它没要求过的结果"（它会把那条结果当成别人的，
    或者干脆当成协议漂移）。这个函数是那条判据的唯一实现，判据文件直接拿它做负控。
    返回空串 = 配对都对；非空 = 那句话就是问题本身。
    """
    last_ids: set[str] = set()
    for i, m in enumerate(messages or []):
        role = str(m.get("role") or "")
        if role not in MESSAGE_ROLES:
            return f"第 {i} 条的角色是 {role!r}，不在 {MESSAGE_ROLES} 里"
        if role == "assistant":
            ids = {str(c.get("id") or "") for c in (m.get("tool_calls") or [])
                   if isinstance(c, Mapping)}
            if not ids or "" in ids:
                return f"第 {i} 条 assistant 没有可配对的 tool_calls"
            last_ids = ids
        elif role == "tool":
            cid = str(m.get("tool_call_id") or "")
            if not cid:
                return f"第 {i} 条 tool 没有 tool_call_id"
            if cid not in last_ids:
                return (f"第 {i} 条 tool 挂在 {cid!r} 上，而上一条 assistant 给的 id 是 "
                        f"{sorted(last_ids) or '（没有）'} —— 挂错 id 等于把结果交给"
                        "一个没要求过它的调用")
            last_ids = set()
        else:
            last_ids = set()
    return ""


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


#: 「JSON 里有一段字符串没写好」的解析报错特征（`json.JSONDecodeError.msg` 的原文）。
#:
#: 真机读数（2026-10-05 T2，`projects/p6h-research-from-zero`，sid `t2h`）：M 在
#: `summon_many` 的 params 里内联一整段构造脚本/命题文本，回复只有 400–500 token
#: （远没到 8192 的输出上限），却在同一类位置连着三次 `Expecting ',' delimiter`
#: ⇒ `bad_json_limit`，49 步 / $0.62 全废。那不是"没按协议说"，而是"长字符串里有
#: 没转义的引号/换行"——两种处置完全不同（前者重述协议，后者要它把长文本落盘再引用）。
_BROKEN_STRING_MARKERS: tuple[str, ...] = (
    "Expecting ',' delimiter", "Unterminated string", "Invalid control character",
    "Expecting ':' delimiter", "Invalid \\escape", "Expecting property name enclosed",
)


def _bad_json_line(step: int, problem: str, detail: str) -> str:
    """整条回复不是可解析 JSON 的那一步（重述输出契约，含骨架）。

    两种坏法分开说（`draft/39` §6.24 的 D32）：
    - 字符串坏（`_BROKEN_STRING_MARKERS` 命中）：这一步的 JSON 形状其实是对的，
      只是某段长文本里有一个没转义的引号/换行 —— 处置是"别内联长文本，先落盘再用
      路径引用"，不是"再念一遍协议"；
    - 其它（多半真是形状漂移）：重述协议 + 骨架。
    为什么必须分开：真机里 M 连着三次撞的是前一种，而它每次收到的都是后一种那句话
    （"只回一行 JSON"）—— 它照做了，然后照样坏在同一处。不可行动的纠正等于没纠正。
    """
    head = (f"\n\n[第 {step + 1} 步] 框架：你上一条回复不是可解析的 JSON 对象"
            f"（{problem}；{_clip(detail, 240)}）。")
    if any(marker in detail for marker in _BROKEN_STRING_MARKERS):
        return (head + "**这一次不是形状漂移，是某段字符串里的引号或换行没转义**"
                "（长文本内联进 JSON 时最常见）。处置：别把长源码/长文本内联进这一步 —— "
                "先 `fs.write` 把它落盘（一次一小段就够），召唤时用 `script_path` / `path` "
                "引用它；确实要内联就把双引号写成反斜杠加双引号、把换行写成反斜杠加 n。"
                "**还有一个更省事的办法：把这一步拆小** —— 一次只派一个 target、"
                "参数里的长文本压到一两句（≤200 字），细的写进文件。"
                "然后只回一行 JSON（不要写分析、不要写 Markdown）。骨架：\n" + JSON_TAIL)
    return (head + "**不要写分析、不要写方案、不要写 Markdown**："
            "只回一行 JSON。骨架：\n" + JSON_TAIL)


def _dump_invalid_reply(root: str, sid: str | None, step: int, text: str) -> str:
    """把解析不出来的整条回复原样落盘，返回工作区相对路径。

    为什么必须落盘（`draft/39` §6.28 的 D40）：`raw_reply` 被 `_clip(..., 600)` 剪过，
    而"坏在第 1608 个字符"恰好落在剪掉的那一段里 —— T2 第 6/8/10 三趟死在同一类失败上，
    每一次都只能靠猜（报错给了列号，证据却被剪掉了）。三态纪律在这一层的落点：
    "没解析出来"要留下可复核的原文，而不是一条摘要。
    """
    safe_sid = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(sid or "run")) or "run"
    rel = f"out/invalid/{safe_sid}-step{step}.txt"
    try:
        path = Path(root or ".") / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text or "", encoding="utf-8", newline="\n")
    except OSError:
        return ""
    return rel


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


def _is_role_name(value: str) -> bool:
    """`value` 是不是一个真角色名（`schema.ROLES` 或主控）。

    为什么需要它：`tasks.called_by` 这一格对顶趟写的是 `"user"`
    （`Conductor.open_top_level_run(by="user")`），而 `"user"` 不是角色
    —— 把它当收件人角色传给 `open_item` 会被 `Task.validate` 拒掉
    （实测：`role 必须是 (…) 之一，收到 'user'`，于是终态通报一条都落不成）。
    角色名单的唯一来源是 `schema`（`ROLES` + `CONDUCTOR_ROLE`），这里照读、不抄。
    """
    return value in (*S.ROLES, S.CONDUCTOR_ROLE)


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
    #: 「同一条路 + 同一类读数」的最长连击（D31）：参数改动了但结论类没变的最长一串。
    #: 与 `dead_loop_max` 并列报出来，因为"同一件事问了 9 遍"与"同一条路撞了 9 次
    #: 同一类墙"是两种不同的卡法，处置也不同（前者换问法，后者换做法或改小目标）。
    stalled_max: int = 0
    #: 「提醒」这一档的读数（裁定 10丙：提醒与判停必须在读数上分开报）：
    #: 提醒触发了几次、以及"因此判停了没有"。改前这两个问题共用 `dead_loop_max` 一个数
    #: （它既当"提醒过没有"又当"停没停"），而那正是"两档分开"要拆开的地方。
    dead_loop_nudges: int = 0
    stalled_nudges: int = 0
    dead_loop_stopped: bool = False
    #: 最近一次计数清零发生在第几步（裁定 12-F：计数按委托记账，"这一次委托从哪算起"要可复核）。
    counters_reset_at: int = 0
    #: 这一趟压了几次历史（S-B；读数，不是判据）：0 = 一次都没压。
    compactions: int = 0
    elapsed_sec: float = 0.0
    notes: list[str] = field(default_factory=list)
    #: 「收工那一步」的原始载荷（模型给的 `final` / `evidence` / `notify` 逐字一份）。
    #:
    #: 为什么要有这一格（2026-10-08 真机读数，三处缺口之一）：`shape == "final"` 那一支在
    #: 步循环里 `break`（见 `run()` 里那段），而 `agent_step` 事件是在 `break` 之后的
    #: 公共尾段落的 ⇒ 收工这一步的事件从来没落过盘（`tests/test_status_report.py` 那条
    #: `len(steps) == 2 and len(run.steps) == 3` 把这个形态逐字钉着）。后果是模型填的
    #: `notify`（收工手稿的输入）与 `evidence` 只活在内存里：`agent_run_end` 只留
    #: `final` 的文本与哈希。真机现场：`projects/p5-review-t17/sessions/t1q.jsonl` 的
    #: `agent_run_end` 里有模型 2058 字的结论，而全仓 17.3MB 会话里没有任何一条
    #: `agent_step` payload 带 `notify`。
    #:
    #: 为什么不改走"给 final 补一条 `agent_step`"：那会把收工那一步塞进
    #: `resume_transcript` 重建的简报里（它按 `agent_step` 逐条重拼），于是"重建的那一段"
    #: 与"当时拼的那一段"不再逐字相等 —— 那是续跑正确性的判据
    #: （`tests/test_user_channel_stop_and_resume.py::test_resume_messages_is_item_equal_to_the_live_sequence`），
    #: 代价比多三个字段大得多。所以这一格与 `agent_run_end` 一起落盘。
    final_payload: dict[str, Any] = field(default_factory=dict)
    #: 这一趟停在等哪个问题（`stop_reason="waiting_for_user"` 时非空）。
    #:
    #: 为什么它是一个独立的字段而不是塞进 `final` 的一句话：人/界面要拿它去对
    #: 待答清单与回答入口（`agentflow answer <qid>`），从一句话里正则抠一个号
    #: 是"看起来能用、迟早漂移"的那类做法。
    waiting_for: str = ""
    #: 这一趟是从第几步接着跑的（0 = 全新开始，>0 = `--resume` 续跑的第几步）。
    resumed_from: int = 0
    #: 收工时被"强制 notify 表"打回的次数（`draft/39` §3.2/§3.3，用户 2026-10-05 裁）。
    #:
    #: 为什么它必须是个独立读数：用户点名的口径是"打回重填、不代填"——
    #: 于是"缺留痕"这件事在台账上的形态是"这一趟被打回了几次、最后是不是以 `no_notify` 收的"。
    #: 只报一个 stop_reason 看不出"它试了几次"。
    notify_rejections: int = 0
    #: 这一趟按 notify 表真的落成的手稿编号（按发生顺序）。空列表 + `stop_reason="final"`
    #: 只对主控成立（M 向用户回复不做这套）。
    handoffs: list[str] = field(default_factory=list)
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
    #: 这一趟的消息序列（S-C，裁定 5甲）：`[{role: user|assistant|tool, ...}]`，
    #: assistant 带 `tool_calls`（`id` 由步号派生 ⇒ 会话记录里重建得回来）、
    #: tool 带 `tool_call_id`（配对判据在 `message_sequence_problem`）。
    #:
    #: 与 `transcript` 的关系：序列是载体，文本是它的渲染
    #: （`render_messages(messages) == transcript` 由构造保证）。`transcript` 留着是因为
    #: 它的读者还在（Web UI 的事件回放、续跑简报、`--resume`）；`to_dict()` 只报条数
    #: 与角色分布 —— 整份序列逐条进 `agent_run_end` 会把会话记录撑大，而它是可重建的
    #: （`agent_step` 事件里有步号与载荷）。
    messages: list[dict[str, Any]] = field(default_factory=list)

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
            "stalled_max": self.stalled_max,
            # 两档分开报（裁定 10丙）：提醒了几次 / 有没有因此判停 / 账从第几步算起。
            "dead_loop_nudges": self.dead_loop_nudges, "stalled_nudges": self.stalled_nudges,
            "dead_loop_stopped": self.dead_loop_stopped,
            "counters_reset_at": self.counters_reset_at,
            # S-B：这一趟压了几次（0 = 一次都没压；与"没启用"那一档合起来读）。
            "compactions": self.compactions,
            "waiting_for": self.waiting_for, "resumed_from": self.resumed_from,
            "notify_rejections": self.notify_rejections, "handoffs": list(self.handoffs),
            "summons": self.summons, "messages_sent": self.messages_sent,
            "prompt_audit": dict(self.prompt_audit), "spend": dict(self.spend),
            "elapsed_sec": round(self.elapsed_sec, 3), "notes": list(self.notes),
            # 收工那一步的原始载荷（`LoopRun.final_payload`）：与 `agent_run_end` 落盘的那
            # 一格同一份 —— "给调用方的返回"与"盘上的记录"不该各是一份。
            "final_payload": dict(self.final_payload),
        }


# ------------------------------------------------------------------ 消息
# ------------------------------------------------------------------ 集体插话
#: 插话里"叫停类"的那一档：只有它额外落"谁在第几步收到、有没有改变做法"的读数
#: （`draft/39` §3.11 二 D07 第 3 条）—— 全量插话都落读数会让这一格淹掉。
INTERJECTION_STOP_MARKERS: tuple[str, ...] = ("叫停", "停止", "停止指令")


def send_interjection(session_root: Path, *, sender: str, subject: str, body: str,
                      to: str = "ALL", sid: str | None = None) -> tuple[str, str]:
    """写一条插话：只有用户能发，只有主控 M 会收到（所有者 2026-10-08 裁定）。返回 `(编号, 问题)`。

    逐字：「插话只有 M 可能受到用户的插话，处理学 dsh。」⇒ 这条通道收窄成
    用户 → M 一条：它对应的就是 DSH 里"人在中途说话、在最近步边界被 steer"那一档
    （`draft/84` §8.3）。同伴之间的传话不走这里，走留言/交接手稿（`draft/85` §2.1 的工作项）。

    权限判据落在这一层（最早的落点），拒绝时零写入并给一条可执行的说明 ——
    这与"插话与留言的区别不是措辞，是送达方式"那段历史口径并不冲突：插话的送达方式
    （下一步开头单列一段【插话】、不打断当前步）一个字没改，改的只是谁能发、谁收。

    历史（保留，免得后人以为这条通道一直是这么窄的）：`draft/39` §3.11 二 D07，
    用户 2026-10-05 的口径是"广播改成集体插话发送"（发给所有在册角色）。T18 收窄它
    之后，`conductor.stop(notify=True)` 的叫停广播改回留言（见 `conductor_tools`）。

    编号由脚本按会话内顺序发（`i-0001`…），与手稿/台账同一套做法：模型不许自己编号。
    """
    who = str(sender or "").strip()
    if who != U.USER:
        return "", (f"插话只有用户能发（所有者 2026-10-08：「插话只有 M 可能受到用户的插话」），"
                    f"收到 sender={who!r}。角色之间的传话走留言（`message.send`）或交接手稿 —— "
                    "那两条都有收件人可查的落点，插话没有。")
    target = str(to or "ALL").strip()
    if target not in (S.CONDUCTOR_ROLE, "ALL"):
        return "", (f"插话只送给主控（{S.CONDUCTOR_ROLE}），收到 to={target!r} —— "
                    "所有者 2026-10-08：只有 M 会收到用户的插话。要指定别的角色请用 `message.send`。")
    events, problems = SS.read_session(session_root, sid=sid)
    n = sum(1 for e in events if e.get("kind") == "agent_interjection") + 1
    iid = f"i-{n:04d}"
    payload = {"kind": "agent_interjection", "interjection_id": iid, "from": str(sender),
               "to": str(S.CONDUCTOR_ROLE), "subject": str(subject or ""),
               "body": str(body or ""),
               # 叫停类要额外落读数（见 `INTERJECTION_STOP_MARKERS`）
               "is_stop": any(m in str(subject or "") for m in INTERJECTION_STOP_MARKERS)}
    path, problem = SS.append(session_root, payload, sid=sid)
    if problem:
        return "", problem
    return iid, ""


def read_interjections(session_root: Path, role: str, *, sid: str | None = None,
                       ) -> tuple[list[dict[str, Any]], list[str]]:
    """这个角色还没消费过的插话（只有主控 M 有；所有者 2026-10-08 裁定 T18）。

    "消费过"由 `agent_interjection_seen` 事件记（`mark_interjections_seen`）——
    不记在内存里：续跑时那一趟要能接着从"已经读过哪些"往下走，否则同一段插话
    会被念第二遍（而"念第二遍"与"又来了一条"在模型眼里长得一样）。

    收口为什么在读取这一层（而不是只靠发送那一层挡住）：历史会话里确实有
    `to="ALL"` 的插话（D07 那一版留下的），读侧再挡一次，才不会让"后来改了发送口
    但老会话还在"变成一条静默通道。返回空表不是"没查成"：非主控角色本来就没有
    这条通道（要传话请走留言）。
    """
    if str(role) != S.CONDUCTOR_ROLE:
        return [], []
    events, problems = SS.read_session(session_root, sid=sid)
    seen: set[str] = set()
    for e in events:
        if e.get("kind") == "agent_interjection_seen":
            seen.update(str(x) for x in (e.get("ids") or []))
    out: list[dict[str, Any]] = []
    for e in events:
        if e.get("kind") != "agent_interjection":
            continue
        iid = str(e.get("interjection_id") or "")
        if not iid or iid in seen:
            continue
        to = str(e.get("to") or "ALL")
        if to in ("ALL", "#public", role):
            out.append(dict(e))
    return out, problems


def mark_interjections_seen(session_root: Path, role: str, ids: list[str], *,
                            sid: str | None = None, step: int | None = None,
                            ) -> tuple[Path | None, str]:
    """登记"这些插话我读过了"（带步号 —— 于是"谁在第几步收到"可查）。"""
    if not ids:
        return None, ""
    return SS.append(session_root, {
        "kind": "agent_interjection_seen", "role": role, "ids": [str(x) for x in ids],
        "step": int(step) if step is not None else None,
    }, sid=sid)


def _interjection_block(items: list[Mapping[str, Any]]) -> str:
    """插话在简报里的那一段：摆在最显眼的位置，并标明优先级。"""
    lines = ["", "=" * 60,
             "【插话】以下是用户/主控发给你的插话，**优先于你自己的计划**（收到它不代表"
             "当前这一步被中断：这一步照常做完，但做之前先按它调整做法）："]
    for it in items:
        mark = "（叫停类）" if it.get("is_stop") else ""
        lines.append(f"- [{it.get('interjection_id')}]{mark} 来自 {it.get('from')}："
                     f"{it.get('subject')} —— {_clip(str(it.get('body') or ''), 400)}")
    lines.append("=" * 60)
    return "\n".join(lines) + "\n"


def public_visibility(msg: Mapping[str, Any], *, parent_task_id: str = "",
                      parent_role: str = "") -> tuple[bool, str]:
    """一条公共频道留言对"我"可不可见（S6-a，业主 T20/T21 + 乙）。返回 `(可见, 读数)`。

    口径（`draft/86` §14.6 乙，逐条）：

    | 这一条长什么样 | 谁看得到 | 读数 |
    |---|---|---|
    | `by_framework=True`（叫停这类框架通报） | 所有角色 | `framework` |
    | 带 `from_task_id`（代理自己发的） | 它的直接子级（`from_task_id == 我的父实例号`） | `instance` |
    | 带 `from_task_id` 但我不是它的子级 | 谁也（除了它自己）看不到 | `not_my_parent` |
    | 老消息（没有 `from_task_id`） | 按角色级回退：`from == 我父的角色` | `role_fallback` |
    | 老消息、而我连父角色都不知道 | 看不到（不许当成"全角色可见"，也不许一律丢掉历史） | `unknown_parent` |

    为什么框架那一档必须留（这是 T21 之后唯一的例外，`draft/86` §14.6 写明了理由）：
    叫停是框架代表主控发的全树通知，而工具层手上没有实例号、全树叫停又是安全件
    （听不到叫停的子孙会继续烧钱跑实验）。S4 的"沿边逐层下发"落地后这一档退休。
    代理自己发的 public 必须带 `from_task_id`（`_do_message` 那一层受控拒绝）。
    """
    if msg.get("by_framework"):
        return True, "framework"
    frm_tid = str(msg.get("from_task_id") or "")
    if frm_tid:
        if parent_task_id and frm_tid == str(parent_task_id):
            return True, "instance"
        return False, "not_my_parent"
    parent_role = str(parent_role or "")
    if parent_role and str(msg.get("from") or "") == parent_role:
        return True, "role_fallback"
    return False, "unknown_parent"


def read_messages(session_root: Path, role: str, *, sid: str | None = None,
                  parent_task_id: str = "", parent_role: str = "",
                  ) -> tuple[list[dict[str, Any]], list[str]]:
    """读某个角色的收件箱（含未投递标记）。返回 `(消息, 问题)`。

    `parent_task_id` / `parent_role` 是公共频道可见面的两格（S6-a，业主 T21 附二 乙）：
    公聊只有"发信人是我的直接父"（实例级）或"这一条是框架通报"才进得了我的收件箱；
    老消息（没有 `from_task_id`）按角色级回退，并在行上留 `visibility` 读数。
    私聊逐字按老口径（`to == role`），不吃这两格。
    """
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
        reading = "private"
        if to != role:
            if to != PUBLIC:
                continue
            visible, reading = public_visibility(event, parent_task_id=parent_task_id,
                                                 parent_role=parent_role)
            if not visible:
                continue
        if str(event.get("from")) == role:
            continue                     # 自己说的不用再听一遍
        msg_id = str(event.get("msg_id") or "")
        if not msg_id:
            # 坏行不给"替身号"（`draft/83` D79）：旧写法按事件序号编一个 `m{i:04d}`，
            # 而那个 i 是全部事件的序号、不是消息序号 ⇒ 它会与真实号重复，
            # 而 `delivered` / `consume:` 都以 msg_id 为键 ⇒ 要么误判"已投递"、
            # 要么误判"已消费"（三态塌成一态）。身份读不出来就如实报坏行。
            problems.append(f"第 {i} 条 agent_message 没有 msg_id ⇒ 这一条的身份读不出来")
            continue
        out.append({**event, "msg_id": msg_id, "delivered": msg_id in delivered,
                    "visibility": reading})
    return out, problems


def pending_wake(session_root: Path | str, role: str, *, sid: str | None = None,
                 parent_task_id: str = "", parent_role: str = "") -> dict[str, Any]:
    """我停着的时候，有没有"值得再开一轮"的东西（S-G，裁定 15；DSH 的 `next-turn`）。

    `{"checked", "pending", "count", "why"}`

    ## 为什么它只认"还没投递过的"留言

    `inbox_digest` 的返回值里有一半是"这一轮新渲染出来、且还没投递的 id"（`fresh`），
    而投递登记（`mark_delivered`）刻意推迟到"模型真的被问过一次"才写。
    唤醒判据用的正是那个 `fresh`：

    - 只认没投递过的 ⇒ 读过的旧留言不会一轮又一轮地把循环开起来
      （那会把"轮次已用尽"的停止变成死循环，而且烧钱）；
    - 三态：会话读不成 ⇒ `checked=False` —— 不许折成"没有新消息"。折过去会把一次
      真的唤醒吞掉，而"有人叫我"这件事在盘上是有痕迹的（那正是三态的用处）。

    为什么不做"父代理循环里 sleep N 秒再看一次"（施工单 S-G 第 3 条逐字禁的形态）：
    那是 DSH 明确没有的东西，而且会把墙钟吃掉；唤醒是事件驱动的 —— 事件就是
    "收件箱里有新的、还没投递的留言"，由驱动的下一轮去读。
    """
    text, fresh, problems = inbox_digest(session_root, role, sid=sid, window=None,
                                        parent_task_id=parent_task_id,
                                        parent_role=parent_role)
    if problems:
        return {"checked": False, "pending": [], "count": 0,
                "why": "；".join(str(p) for p in problems), "text": text}
    return {"checked": True, "pending": [str(x) for x in fresh], "count": len(fresh),
            "why": "", "text": text}


def message_source(record: Mapping[str, Any]) -> dict[str, str]:
    """一条留言的来源读数（S-G）：`{kind, form, summary}` —— DSH 的 `source` 那一格。

    为什么必须搬（施工单 S-G 逐字）：DSH 的通知是带
    `source{kind, form:"notice", summary}` 的消息（`dsh-subagent:663-680`），
    而我们的 `heard` 是裸 dict ⇒ "这条是子代理结算 / 插话 / 广播"在读数上分不开。
    分开之后，"父收到的哪一条是孩子的交差通报"就有了机器可判的答案。

    四种 kind（取值刻意少而稳，且都是盘上已有的字面量）：
    - `subagent-settled`：框架投递的通报（`by_framework` 为真，即 `_emit_settlement` 那一类）；
    - `broadcast`：公共频道（`channel == "public"`）；
    - `user`：发信人是用户/主控以外的用户频道；
    - `message`：其余（角色之间的一条普通留言）。
    """
    channel = str(record.get("channel") or "")
    sender = str(record.get("from") or "")
    if record.get("by_framework"):
        kind = "subagent-settled"
    elif channel == "public":
        kind = "broadcast"
    elif sender in ("user", "用户"):
        kind = "user"
    else:
        kind = "message"
    return {"kind": kind, "form": "notice", "summary": str(record.get("subject") or "")}


def send_message(session_root: Path, *, sender: str, to: str, subject: str, body: str,
                 reply_to: str = "", sid: str | None = None, from_task_id: str = "",
                 by_framework: bool = False) -> tuple[str, str]:
    """发一条消息（append-only）。`to=PUBLIC` 是公共频道。返回 `(msg_id, 问题)`。

    编号口径：取现有最大号 + 1（`draft/83` D79）。旧写法是"数一数有多少条
    `agent_message` 再加一"，它在正常 append-only 会话里与 max+1 恰好相等，
    但只要有一条坏行占号、或将来做了删除/搬迁，计数口径就会撞上已用过的号 ——
    而 `msg_id` 正是投递登记与消费判定的键（撞号 = 两条消息共享一个身份）。

    `from_task_id` / `by_framework`（S6-a）：公共频道的可见面靠这两格判（见
    :func:`public_visibility`）。只在给了的时候写这两个键 —— 恒为假的键会让
    "谁都没写"与"框架特意写了假"在记录上长得一样，而历史判据是按逐键比对钉的。
    """
    events, _problems = SS.read_session(session_root, sid=sid)
    used = [str(e.get("msg_id") or "") for e in events if e.get("kind") == "agent_message"]
    nums = [int(m[1:]) for m in used if m[:1] == "m" and m[1:].isdigit()]
    msg_id = f"m{(max(nums) + 1) if nums else 1:04d}"
    rec: dict[str, Any] = {
        "kind": "agent_message", "msg_id": msg_id, "from": sender, "to": to,
        "subject": subject, "body": body, "reply_to": reply_to,
        "channel": "public" if to == PUBLIC else "private",
    }
    if str(from_task_id or ""):
        rec["from_task_id"] = str(from_task_id)
    if by_framework:
        rec["by_framework"] = True
    _path, problem = SS.append(session_root, rec, sid=sid)
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


def inbox_digest(session_root: Path, role: str, *, sid: str | None = None,
                 window: int | None = 8, parent_task_id: str = "",
                 parent_role: str = "") -> tuple[str, list[str], list[str]]:
    """收件箱摘要：`(文本, 这一轮新渲染出来、且还没投递的 id, 读会话时的问题)`。

    `parent_task_id` / `parent_role` 转给 :func:`read_messages`（公共频道的可见面，
    S6-a）：谁读就得以谁的身份读 —— 缺了这两格，公聊会按"老消息回退"那一档
    要么读不到、要么读成别人的（两种都是静默错，所以调用方必须给它能给的那一份）。

    为什么第二个返回值是"渲染过的"而不是"全部未投递的"（`draft/83` §11 的 D75）：
    旧实现渲染 `messages[-8:]`，却把全部未投递的 id 交给调用方去 `mark_delivered`
    ⇒ 第 9 条及更早的留言既不进提示词、也不再是 fresh，于是永久静默丢失
    （真机读数：128 个会话 579 条留言里，只有 8 条被标记读过）。
    现在两个集合只有一个来源：这里返回什么，调用方就标什么。

    未投递优先（同一处修法的另一半）：窗口先给还没投递的（按时间升序，老的先读 ——
    否则新的不断到来会把老的永远挤在窗口外），装得下再补最近的已投递项当背景；
    装不下时在末尾写明"还有 K 条没渲染，下一步继续"，于是"积压"是看得见的事实。

    `window=None` = 不限窗口（`_hear` 那条路会把新到的一次性全并进这一步的结果，
    所以它渲染多少就标多少）。
    """
    messages, problems = read_messages(session_root, role, sid=sid,
                                       parent_task_id=parent_task_id,
                                       parent_role=parent_role)
    if not messages:
        return "（没有收到留言）", [], problems
    fresh = [m for m in messages if not m.get("delivered")]
    delivered = [m for m in messages if m.get("delivered")]
    if window is None:
        pick = list(messages)
    else:
        n = max(1, int(window))
        room = n - len(fresh)
        pick = (list(fresh) + delivered[-room:]) if room > 0 else list(fresh[:n])
        pick = pick[:n]
    lines: list[str] = []
    for m in pick:
        mark = "" if m.get("delivered") else "（新）"
        lines.append(f"- {mark}[{m['msg_id']}] 来自 {m.get('from')}：{m.get('subject')} —— "
                     f"{_clip(m.get('body'), 300)}")
    backlog = len(fresh) - sum(1 for m in pick if not m.get("delivered"))
    if backlog > 0:
        # 积压必须是可读的事实：否则"读不完"与"没有新东西"在提示词里长得一模一样。
        lines.append(f"- （还有 {backlog} 条留言没渲染 —— 下一步继续读）")
    # 返回这一轮新渲染出来的、且还没投递的那些：已经投递过的那些当背景渲染，
    # 但它们已经标过了（重复标是幂等的，可把它们混进来会让"标记集合"这个读数变糊）。
    return "\n".join(lines), [str(m["msg_id"]) for m in pick if not m.get("delivered")], problems

def board_digest(conductor: Any, *, my_task_id: str,
                 window: int | None = 8) -> tuple[str, list[str], list[str]]:
    """板摘要（挂在我名下的工作项进上下文）：`(文本, 这一轮渲染出来的项 id, 问题)`。

    ## 口径与 `inbox_digest` 同源（`draft/83` §11 的 D75 那条教训）

    渲染集合 = 标记集合：这里返回什么 id，调用方就 `mark_item_seen` 什么。
    旧写法那种"渲染 8 条、却把全部未读标掉"在这条路上同样会让第 9 项永久静默丢失，
    所以两个集合只有一个来源。

    ## 什么是"渲染即 seen"（业主 A3=甲）

    板项的"已投递"标记就是它自己的状态机：`queued`/`claimed` ⇒ 还没被谁读进任何一步；
    `seen` 由这一步写（`seen_by` = 我的台账号、`seen_step` = 第几步）。
    所以：未 seen 的项才算"新"，渲染了就标 seen，标了才不再进下一轮的窗口。

    ## 三态（不许把"没读成"折成"板上没事"）

    没有 conductor / 没有台账号 / 读失败 —— 三种都返回一句带括号的问题，
    并把自己的问题也放进第三个返回值（进 `run.notes`）。最后一种绝不返回
    "（板上没有要你处理的事）"。

    `window=None` = 不限窗口（与 `inbox_digest` 的 `_hear` 那一档同义）。
    """
    if conductor is None:
        return "（读不到工作项板：这一趟没有 conductor 句柄）", [], []
    if not str(my_task_id or ""):
        return "（这一趟还没落台账，读不到挂在你名下的项）", [], []
    look = getattr(conductor, "open_items_of", None)
    if not callable(look):
        return "（读不到工作项板：这个 conductor 没有 `open_items_of`）", [], []
    try:
        rows = list(look(my_task_id))
    except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"，不是"板上没事"
        why = f"{type(exc).__name__}: {exc}"
        return f"（工作项板没读成：{why}）", [], [f"工作项板没读成：{why}"]
    if not rows:
        return "（板上没有要你处理的事）", [], []
    # 老的先读：按落行时间 + 编号（与 board_view 的排序同口径，免得两处读出两个顺序）
    rows.sort(key=lambda r: (str(r.get("started_at") or ""), str(r.get("task_id") or "")))
    n = len(rows) if window is None else max(1, int(window))
    pick = rows[:n]
    lines: list[str] = []
    for r in pick:
        fresh = str(r.get("item_state") or "") in ("queued", "claimed")
        mark = "（新）" if fresh else "（已读）"
        lines.append(f"- {mark}[{r['task_id']}] {r.get('kind')}"
                     f"·要{'一个回执' if str(r.get('expects') or '') == 'ack' else '一件活'}"
                     f" 来自 {r.get('called_by')}：{_clip(r.get('detail'), 300)}")
    backlog = len(rows) - len(pick)
    if backlog > 0:
        # 积压必须是可读的事实：否则"读不完"与"没有新东西"在提示词里长得一样。
        lines.append(f"- （还有 {backlog} 项没渲染 —— 下一步继续读）")
    return ("\n".join(lines),
            [str(r["task_id"]) for r in pick
             if str(r.get("item_state") or "") in ("queued", "claimed")],
            [])



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
    """规范形态的解码：一次只说一件事，取的那个键必须是 `SHAPES` 里的一种。

    清单与条数以 `SHAPES` 为唯一来源，本处不重抄第二份 —— 这里原先手抄的形状条数
    与 `SHAPES` 不一致，漏掉的正是 `handoff`（手稿落行的唯一入口：真机 1542 行手稿里
    967 行由框架派生、模型自写 0 行，而正典表里看不见它）。别名只负责把扁平形态
    改写成这里认的形态。"""
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
        # S1k-2/S1k-3（名册口径）：`brief` / `name` / `reuse` 三格要带过去 ——
        # 这里原先返回的是写死的键集，于是提示词教了这三格、解码器却把它们丢了
        # （S1k-3 的判据当场抓出来：`roster_problem` 永远是"没给一句任务简介"）。
        # 只在给了的时候带上，老载荷的键集因此一个字节不变。
        extra: dict[str, Any] = {k: str(value.get(k)) for k in ("brief", "name", "reuse")
                                 if str(value.get(k) or "").strip()}
        # S1g：动作声明里的参数被摆在了顶层（不在 `params` 里）时，别再静默丢掉它们
        # —— 今天这条路把它们丢在校验之前，于是模型看到的是「缺必填参数」，而那个值
        # 明明就在它写的那一句话里。带两类：① 声明过的键；② 名字写错、但按唯一候选
        # 能折算到某个声明键的那些（原名带过去，改名是秘书的事 —— 它要落账
        # "模型写错了哪个键"）。顶层别的键一个都不带：payload 是会落台账的形状，
        # 宽一格要有判据守着。真正的"收进 params"由秘书洗格式做
        # （`secretary.wash_delegation`）：没接秘书时这几个键是惰性的
        # （`conductor.summon` 只看 `params`），老行为逐字不变。
        extra.update(_carried_top_level_params(role, action, value, params))
        return key, _with_notify({"role": role, "action": action, "params": dict(params),
                                  "why": str(value.get("why") or ""), **extra}, value), ""
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
            item_extra: dict[str, Any] = {
                # S1k-4：一批派活的目标也各带自己的名册三格（只在给了的时候带，
                # 老载荷的键集因此不变）—— 与 `summon` 那一支同一口径。
                k: str(item.get(k)) for k in ("brief", "name", "reuse")
                if str(item.get(k) or "").strip()}
            # S1g：与 `summon` 那一支同一口径（声明里的参数被摆在目标顶层 ⇒ 别静默丢）。
            item_extra.update(_carried_top_level_params(role, action, item, params))
            clean.append({"role": role, "action": action, "params": dict(params),
                          "instance": str(item.get("instance") or ""),
                          "input_key": str(item.get("input_key") or ""),
                          **item_extra})
        out: dict[str, Any] = {"targets": clean, "why": str(value.get("why") or "")}
        return key, _with_notify(out, value), ""
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
        # `ALL` / `#public` 的等价关系只在 `_is_all_recipient` 一处定义，三条通道
        # （`message` / `handoff` / `notify`）都从那里取 —— 不许各写一份。
        to = _recipient_for_channel(to)      # 留言通道的"给所有人"规范形是 `#public`
        if not _known_recipient(to):
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
        # 用户原话"就传个编号感觉有点尬，可以再附一句简要描述" —— 那一句话是 `summary`
        # （`draft/39` §C2 的正名）；旧名 `brief` / `title` 仍然接受，三者取第一个非空的。
        if not isinstance(value, Mapping):
            return "", {}, "handoff 必须是一个对象"
        to = str(value.get("to") or "")
        # `ALL` 与 `#public` 等价（2026-10-06 修，主控裁定 (a)）：`message` / `notify`
        # 两条路早就两种写法都收（`_known_recipient`），只有这里只收 `#public` ——
        # 而拒信自己教的正是 `ALL`（"给所有人写 to="ALL""），`JSON_TAIL` 里的骨架
        # 也写 `<伙伴/M/ALL>`。于是模型照提示词写 `ALL` 会被拒，被拒后拿到的改法还是
        # `ALL`，同一步能连撞两次（这正是"提示词教了一个框架不收的字面量"。
        # 判据与归一都走唯一那份词表：`_known_recipient` / `_recipient_for_channel`。
        if not _known_recipient(to):
            return "", {}, (f"收件人 {to!r} 既不是角色（{S.ROLES}）、也不是主控 "
                            f"{S.CONDUCTOR_ROLE}、也不是 {PUBLIC}（给所有人写 to=\"ALL\"，"
                            "两种写法等价）")
        summary = (str(value.get("summary") or "").strip()
                   or str(value.get("brief") or "").strip()
                   or str(value.get("title") or "").strip())
        body = str(value.get("body") or "").strip()
        if not summary:
            return "", {}, ("handoff 需要 summary（一句话：它就是留言里那句 "
                            "`[手稿 NNNN] <summary>`；旧名 title/brief 也认）")
        if not body:
            return "", {}, ("handoff 需要 body（正文）—— 空手稿是「我交接了」的假证据，"
                            "而这一层存在的全部意义就是可溯源")
        refs = value.get("refs") or []
        if not isinstance(refs, (list, tuple)):
            return "", {}, "handoff 的 refs 必须是编号数组"
        return key, {"to": _recipient_for_channel(to, all_as="ALL"), "summary": summary,
                     "body": body,
                     "refs": [str(x) for x in refs],
                     # `R2b-⑲`：带了这一格 ⇒ 走秘书的 `handoff_revise`（订正某一号，
                     # 旧行保留）。它是可选键：不填就是新增（旧行为逐字不变）。
                     "revises": str(value.get("revises") or "").strip(),
                     "why": str(value.get("why") or "")}, ""
    if key in ("retire", "roster", "interrupt"):
        # 名册面的两个形状（S1k-2 加进 `SHAPES`、S1k-3 的判据直接打在 `_do_retire` /
        # `_do_roster` 上）—— 解码器当时漏了这两支，于是它们一路掉进下面那个
        # `final` 兜底：真机实测（M2 的 K1 探针，2026-10-09）模型写
        # `{"retire": {"name": "D1"}}`，落成 payload `{"final": "{\"name\": \"D1\"}"}`，
        # `_do_retire` 读不到 `name` ⇒ 连拒 6 次「要退谁：`name` 是名册名，不能空」、
        # 12 步用尽。单测全绿（它们绕过了 `_shape_of`），只有真跑抓得到 ——
        # 这正是"M2 必须含一次真机探针"这条要求的价值。
        if not isinstance(value, Mapping):
            return "", {}, f"{key} 必须是一个对象"
        if key == "retire":
            name = str(value.get("name") or "").strip()
            if not name:
                return "", {}, ("retire 需要 `name`（名册名，例如 \"D1\"）："
                                "「要退谁」只能用名册名说，绝对编码不是父子之间的指称")
            return key, {"name": name}, ""
        if key == "interrupt":
            # S-H（裁定 14）：与 `retire` 同一条指称纪律 —— 名册名，不是台账号。
            name = str(value.get("name") or "").strip()
            if not name:
                return "", {}, ("interrupt 需要 `name`（名册名，例如 \"D1\"）："
                                "「要停谁」只能用名册名说，绝对编码不是父子之间的指称")
            return key, {"name": name}, ""
        of = str(value.get("of") or "self").strip() or "self"
        # `of` 只做"是不是字符串"这一层：可见面由读侧判（`_do_roster` 对越界的名字
        # 受控拒绝并点名"越界"）—— 解码器预判"这个名字算不算数"会把两件事混起来，
        # 而其中一件（我能不能看）只有读侧知道。
        return key, {"of": of}, ""
    final = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    payload: dict[str, Any] = {"final": final,
                               "evidence": [str(x) for x in (data.get("evidence") or [])]}
    if data.get("notify") is not None:
        # `notify` 原样带过：它的校验统一在 `notify_reading` 里做（那一层才知道角色、
        # 才知道这是连续第几次被打回 —— 而"打回"要附四件事的警告，警告的措辞只有一处）。
        # 解码器只负责"认出了 final 这个形状"（纯函数、可单测）。
        payload["notify"] = data.get("notify")
    if data.get("blocked") is not None:
        # 业主 2026-10-09 的第四句：层层上报困难会带来一种停机状态 ——
        # 所有活跃子代理都是 blocked。子代理用它自己的收工那句话声明"我这趟卡住了"：
        # `{"final": "...", "blocked": {"what": "...", "why": "..."}}`。
        # 只在给了的时候带过（与 `notify` 同一纪律：恒为空的键会让"没声明"与"声明了空"
        # 长得一样），校验与落痕都在 `_execute` 那一层（`note_blocked`）。
        payload["blocked"] = data.get("blocked")
    return key, payload, ""


#: `final.notify` 的字段表（`draft/39` §3.2）：`to` / `summary` / `body` 必填，`refs` / `why` 可选。
NOTIFY_FIELDS: tuple[str, ...] = ("to", "summary", "body", "refs", "why")


def _declared_params(role: str, action: str) -> list[str]:
    """`(角色, 动作)` 声明里的参数键名（读不到 ⇒ 空列表 = 这一格判不了，不是"没有参数"）。

    用途只有一处（S1g）：解码派活形状时，把被摆在顶层的声明参数带上，
    别让它们在校验之前就消失。空列表在这里只意味着"不带任何顶层参数"，
    也就是今天的行为 —— 读不到声明绝不等于"这些键不合法"。
    """
    try:
        spec = C.find_action(str(role), str(action))
    except Exception:  # noqa: BLE001 —— 声明读不到不是"没有这个动作"
        return []
    try:
        props = dict(getattr(spec, "params", None) or {}).get("properties") or {}
    except Exception:  # noqa: BLE001
        return []
    return [str(k) for k in props]


def _carried_top_level_params(role: str, action: str, raw: Mapping[str, Any],
                              params: Mapping[str, Any]) -> dict[str, Any]:
    """顶层那些其实是参数的键（S1g）：声明过的 + 名字写错但唯一候选能折算的。

    值原样带走、键原名带走 —— 改名与落账都归秘书（它要写清"模型写错了哪个键"）。
    候选算法与秘书用的是同一份（`secretary.declarations_candidates` →：
    `tools.base.candidate_tool_names`），不在这里另写一份。
    """
    props = _declared_params(role, action)
    if not props:
        return {}
    from .secretary import declarations_candidates

    taken: dict[str, Any] = {}
    for prop in props:
        if prop in params or prop in ("name", "params"):
            # `name` / `params` 这两格是形状自己的（名册名 / 参数容器），
            # 同名参数不许把它们顶掉（`E.run_experiment` 恰好声明了这两个名字）。
            continue
        if raw.get(prop) is not None:
            taken[prop] = raw.get(prop)
    for key in raw:
        if key in taken or key in params or key in _SHAPE_PROTOCOL_KEYS:
            continue
        cand = declarations_candidates(str(key), props)
        if len(cand) == 1:
            taken[str(key)] = raw.get(key)      # 原名带着（改名是秘书的事）
    return taken


#: 形状协议自己的键（不是动作参数）：顶层带这些键不算"参数摆错了地方"。
#: 与 `secretary.Secretary._SHAPE_KEYS` 是同一份口径的解码侧副本 ——
#: 那边管"折叠时跳过谁"，这边管"压根不带谁"，两处不同名会被读成两件事。
_SHAPE_PROTOCOL_KEYS: tuple[str, ...] = ("role", "action", "params", "brief", "name",
                                         "reuse", "input_key", "instance", "targets",
                                         "notify", "why", "shape_alias", "tool", "args")


def _with_notify(payload: dict[str, Any], raw: Mapping[str, Any]) -> dict[str, Any]:
    """把派活形状里的 `notify` 原样带进 payload（没有这个键就一个字节都不加）。

    为什么不总是加一个 `notify: None`：payload 是落台账的形状，多一个恒为 None 的键
    会让"模型没填"与"框架没接住"在记录上长得一样；而且历史上按 payload 逐键比对的判据
    会因此集体变红（那是判据在替我们守"形状不许悄悄变宽"）。
    """
    if raw.get("notify") is None:
        return payload
    return {**payload, "notify": raw.get("notify")}


#: 「给所有人」的两种写法（等价）。这是那条等价关系的唯一来源：
#: `_is_all_recipient` / `_known_recipient` / `_recipient_for_channel` 三处都从这里取，
#: `message` / `handoff` / `notify` 三条通道也都调它们 —— 不许再各写一份。
#: 为什么会有两种：公共频道的落库形态是 `#public`（`_do_message` 按它判 `channel`），
#: 而手稿文件名（`…toALL.md`）与 `notify` 的口径是 `ALL`。
ALL_RECIPIENT_TOKENS: tuple[str, ...] = (PUBLIC, "ALL")


def _is_all_recipient(token: Any) -> bool:
    """这个写法是不是"给所有人"（`ALL` / `#public`，大小写不敏感）。"""
    return str(token or "").strip().upper() in {x.upper() for x in ALL_RECIPIENT_TOKENS}


def _known_recipient(token: Any) -> bool:
    """收件人写法认不认（大小写不敏感；`ALL` / `#public` 都算"给所有人"）。"""
    want = str(token or "").strip()
    return _is_all_recipient(want) or want.upper() in {r.upper() for r in (*S.ROLES,
                                                                          S.CONDUCTOR_ROLE)}


def message_admission(role: str, to: str, reply_to: str = "") -> str:
    """私聊的准入判据（唯一一份实现）：通过返回空串，不通过返回那句理由。

    为什么抽成模块级函数（而不是留在 `_do_message` 里、让秘书自己再抄一份）：
    `message` 是结构化交互 ⇒ 秘书要接管它（所有者的裁定），而秘书住在 `secretary.py`。
    它若自己写一遍"`to in partners_out(role)`"，两份判据漂了没有任何东西会红 ——
    这正是本仓反复登记的形态（同一件事两份实现）。所以秘书那一侧靠依赖注入
    拿这个函数（`Secretary.optimize_outbound(..., admission=message_admission)`），
    它的文件里不出现 `partners_out`（判据：`tests/test_secretary.py` 用 AST 扫）。

    `reply_to` 非空 ⇒ 放行：那是"回一条已经存在的对话"，协作边早在对方开口时成立过。
    """
    if to == PUBLIC:
        return ""
    allowed = (to in AP.partners_out(role) or role in AP.partners_out(to) or bool(reply_to))
    if allowed:
        return ""
    return (f"{role} 与 {to} 之间没有协作边（{role} 能叫的是 {sorted(AP.partners_out(role))}）"
            f"⇒ 私聊不成立；要么发到公共频道（to={PUBLIC}），要么先公开开口。")


def _recipient_for_channel(token: Any, *, all_as: str = PUBLIC) -> str:
    """收件人归一成这条通道的规范写法；角色名一律大写。

    `all_as` 之所以是参数而不是写死：两条通道的消费者认的形态不同 ——
    `_do_message` 按 `to == #public` 判 `channel`（留言通道要给 `#public`），
    而手稿文件名与 `notify` 的口径是 `ALL`。等价关系仍在 `_is_all_recipient` 一处，
    这里只是选一个规范写法，参数就是那处选择，并且必须在这句 docstring 里说明理由。
    """
    want = str(token or "").strip()
    return str(all_as) if _is_all_recipient(want) else want.upper()


def notify_shape_problem(notify: Any) -> str:
    """`final.notify` 的形状检查（空串 = 合规）。只判形状，不判"该不该有这一栏"。"""
    if not isinstance(notify, Mapping):
        return f"notify 必须是一个对象（字段：{list(NOTIFY_FIELDS)}），收到 {type(notify).__name__}"
    unknown = sorted(set(notify) - set(NOTIFY_FIELDS))
    if unknown:
        return (f"notify 里有不认识的字段 {unknown}：只有 {list(NOTIFY_FIELDS)} —— "
                "拼错的字段会被静默忽略，于是它与「没填」长得一样")
    to = str(notify.get("to") or "").strip()
    if not to:
        return "notify.to 没填（要交给谁：A–H 或 M，给所有人写 ALL）"
    if not _known_recipient(to):
        return (f"notify.to={to!r} 不是角色（{list(S.ROLES)}）、也不是主控 {S.CONDUCTOR_ROLE}、"
                f"也不是 {PUBLIC}（给所有人写 ALL）")
    if not str(notify.get("summary") or "").strip():
        return "notify.summary 没填（一句话：交给对方什么 —— 它会被拼进那条留言）"
    if not str(notify.get("body") or "").strip():
        return ("notify.body 没填（markdown 正文：做了什么 / 依据（实验号、文献号、手稿号）/ "
                "要对方做什么 / 我卡在哪）")
    refs = notify.get("refs")
    if refs is not None and not isinstance(refs, (list, tuple)):
        return "notify.refs 必须是数组（前序手稿编号或 stmt:/exp:/lit:/rel: 这类台账引用）"
    return ""


def clean_notify(notify: Mapping[str, Any]) -> dict[str, Any]:
    """把 `notify` 规范化（收件人大小写归一、`ALL`/`#public` 都写成 `ALL`、`refs` 转字符串数组）。

    收件人那一格调的是与 `message` / `handoff` 同一个归一函数（`_recipient_for_channel`）——
    三条通道共用一处词表，谁也不许自己判一遍"哪些写法算给所有人"。
    """
    to = str(notify.get("to") or "").strip()
    return {"to": _recipient_for_channel(to, all_as="ALL"),
            "summary": str(notify.get("summary") or "").strip(),
            "body": str(notify.get("body") or ""),
            "refs": [str(x) for x in (notify.get("refs") or [])],
            "why": str(notify.get("why") or "").strip()}


def _notify_help(problem: str, *, attempt: int,
                 what: str = "收工那一句（final）") -> str:
    """被打回时给模型看的那一段（用户点名要的"四件事" + 连续两次要反思）。

    四件事（`draft/39` §3.3 的裁定）：① 命中了哪个字段；② 正例；③ 反例；
    ④ "只改这一个字段再发一次"。为什么必须四件都给：只说"格式不对"时，模型下一句
    往往是把整段结论重写一遍（结论因此漂移），而这里要救的只是那一栏。

    `what` 说明被拒的是哪一句（收工 / 派活）—— 两处共用同一张表与同一段话，措辞只有这一份。
    """
    lines = [
        f"【打回重填】{what}必须带 notify 表，而你这一份的问题是：{problem}",
        "① 命中字段：见上一行那句（说的就是哪一个键）。",
        "② 正例：{\"final\": \"本轮把 X 推到 Y（读数见下）\", \"notify\": {\"to\": \"D\", "
        "\"summary\": \"交给 D：X 的族构造证据\", \"body\": \"## 我做了什么\n…\n## 依据\n"
        "exp:0002 / lit:0004\n## 要你做什么\n…\n## 我卡在哪\n…\", \"refs\": [\"0003\"]}}",
        "③ 反例：{\"final\": \"做完了\"}（没有 notify）；{\"notify\": {\"to\": \"D\"}}"
        "（缺 summary 与 body）；{\"notify\": {\"to\": \"Z\", …}}（收件人不是角色）。",
        "④ 只改这一个字段再发一次：final 的正文与你原来的结论照旧写，别整段重写 —— "
        "被救的只是那一栏。",
    ]
    if attempt >= 2:
        lines.append(
            f"这是连续第 {attempt} 次没按格式填：请**先说明你上一次为什么没按格式填**"
            "（一句话即可），再按上面的正例重发。")
    return "\n".join(lines)


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
    #: 收工时的 `notify` 表最多被打回几次。
    #:
    #: L-05e 之后这个数不再是判据（`draft/52` F 组 / P-10）：强制闸门已经降级成
    #: 读数（收工不带 `notify` ⇒ 不打回、不代填，只把"没有留痕"写进这一步的读数）。
    #: 常量留着是因为它仍在会话记录与 `LoopRun` 的读数面上（历史读数要能解释），
    #: 而不再有任何分支读它去决定行为 —— 这一点由
    #: `tests/test_forced_notify.py::test_the_forced_table_is_retired_in_code_and_the_prompt_half_is_bs`
    #: 钉住（源码里不许再出现 `_notify_bounce(` 与 `no_notify`）。
    max_notify_rejections: int = 3
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
    #: 判停阈值（裁定 10丙：提醒 3 次、判停 5 次）。
    #:
    #: 改前是 6。为什么现在 5 而不是 6：口径没变（"提醒过之后又重复了几次就停"），
    #: 变的是业主当场定的那个数；而那个数写在两处（这里与提示词里那句散文），
    #: 所以 S-D 的判据里有一条"散文里的数字必须等于这一格"（改一处忘了另一处是经典形态）。
    #:
    #: 改前那句注释写的是"6 给模型留三次改主意的机会"—— 5 是两次，
    #: 所以这里不是把数字换掉，是重新推导：提醒在第 3 次，判停在第 5 次 ⇒ 提醒之后还有 2 次。
    max_dead_loop: int = 5
    #: 「同一条路 + 同一类读数」的两个档（`draft/39` §6.23 的 D31）：3 次提醒、6 次再说一遍。
    #:
    #: 为什么不复用 `dead_loop_nudge` / `max_dead_loop`：那一对认的是"同一个调用"
    #: （同形状 + 同参数 + 同读数），而这一对认的是"同一件事 + 同一类结论"——
    #: 参数改一点点（换一行 Lean、改一处措辞）不算换了做法。两条读数分开报，
    #: 因为"同一件事问了 9 遍"与"同一条路撞了 9 次同一类墙"是两种不同的卡法。
    #: 为什么这一对不判停：真机读数（T1 第 17 趟）里那条路最后是走通了的
    #: （第 19 次拿到了 proof 行）—— 在这里判停会把"走得通但走得慢"判成失败。
    #: 它要买的是"看得见 + 提醒"，收敛与否由模型自己决定（提示词里给了试错预算）。
    stall_nudge: int = 3
    stall_alert: int = 6
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
    #: 这一趟的收件人（父代理）的台账号与角色 —— 由 `run` 现算（业主 T21 附：
    #: "知道我的父代理是谁"）。它同时是 `_emit_settlement` 挂板项的那个名字（D89）：
    #: 板项/留言的 `parent_task_id` 口径是"收件人的编号"，不是自己的。
    #: 空串 = 这一趟是顶层发起（没有父代理）⇒ 回报挂在这一趟自己名下（它就是这一支的根，
    #: 与改前的行为逐字相同）。
    parent_task_id: str = ""
    #: 父代理的角色（我那一行的 `called_by`）。收件人按角色归队时用它。
    parent_role: str = ""
    #: 父是谁没读成时的理由（空串 = 读成了）。与"没有父"分得开（三态纪律）：
    #: 读不成时 `_resolve_parent` 落到"挂在自己名下"那一档，并把这句话回给调用方。
    parent_problem: str = ""
    #: 这一趟的读写面（绝对路径；空串 = 没切面 ⇒ 老行为：`fs.*` 的沙箱根就是工作区）。
    #: 业主 T23：子代理只能读写父切割给它的面 —— 强制在 `_do_tool`（`_surface_refusal`），
    #: 由 `LlmBackend.call` 从父的名册里读出来传进 `run(surface=…)`（S1n-b）。
    surface: str = ""
    #: 本角色自己的秘书（A 线：`draft/53` v3 的四职责 + 手稿通道增改查）。
    #:
    #: `None` = 没装配（裸 `AgentLoop(...)`；测试与旧调用点）。三种后果，都是有意的：
    #: ① 手稿的写路径关闭 —— 循环形状 `handoff` 与 `summon` 的 `notify` 派生写
    #:    都改由秘书执笔（智能体只保留"查"，`draft/55` §3.2），没秘书就不写；
    #: ② 发件/收件两个钩子是 no-op（`_outbound_hook` / `_inbound_hook`）；
    #: ③ 其余行为逐字不变（秘书的失败姿态是 fail-open，而"没装配"不该改变别的判据）。
    #: 生产路径由 `run_role` 自动装配（每角色一个实例），所以这条默认值只影响裸构造。
    #: 2026-10-08 晚（业主 T14）：秘书从"可给可不给"变成"一定要" ——
    #: 逐字「秘书是个流程上的东西，不是可要可不要的，是一定要的，每唤起一个智能体就自带一个
    #: 秘书帮它忙前忙后」。于是不传时由 `__post_init__` 自动派生（见下面的实现），
    #: `auto_secretary=False` 只留给单测去造"没有秘书"这一态（生产路径上它不可达）。
    secretary: Any = None
    #: 不传秘书时要不要自动派生（`T14`）。默认 True；单测要"没有秘书"那一态时显式关掉。
    auto_secretary: bool = True
    #: 自动派生失败时的理由（空串 = 没事）。must not 静默：写路径关闭这件事
    #: 必须能从盘上/返回值读到（D81 的第 ③ 条就是为它加的留痕）。
    secretary_problem: str = ""
    #: 「容量读不到」那一档每趟只警告一次（S-B；照 DSH `CB:803-808` 的去重）。
    #: 不这样的话每一步都会往会话记录里塞同一句"读不到容量"。
    _compaction_capacity_warned: bool = False
    #: 最近一次摘要调用的读数（S-B：`{"note": "compaction"}` 那一族）。
    #: 判据与 `compaction_summary` 事件都读它 —— 于是"这一笔钱是压缩花的"可归口。
    _last_summary_note: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """T14：每唤起一个智能体就自带一个秘书（不传就派生）。

        三条口径：
        1. 给了秘书（`secretary` 非空）⇒ 用它，什么都不做；
        2. `auto_secretary=False` ⇒ 保持 `None`（单测造"没有秘书"那一态的唯一入口）；
        3. 否则派生 —— 失败不抛（fail-open：这一趟照跑，写路径关闭），
           但把理由落进 `secretary_problem` 并写一条 `agent_note`（与 D81 的留痕同族）。
        为什么"装配必定"不等于"运行脆断"：工厂抛异常是环境问题，不该让整个跑批死掉；
        但"没有秘书"这件事必须留痕，否则"没装配"与"不用装配"在盘上长得一样。
        """
        if self.secretary is not None or not self.auto_secretary:
            return
        if self.store is None:
            self.secretary_problem = ("秘书没装配：这一趟没有 store（`AgentLoop` 裸构造时"
                                      "既没给秘书、也没有可派生的依赖）")
            return
        try:
            self.secretary = _secretary_for(self.role, root=self.session_root,
                                            store=self.store, registry=self.registry,
                                            seam=self.seam, sid=self.sid)
        except Exception as exc:  # noqa: BLE001 —— 工厂坏了仍 fail-open，但必须留痕
            self.secretary = None
            self.secretary_problem = (f"秘书装配失败（{type(exc).__name__}: {exc}）⇒ 这一趟没有"
                                      "秘书：手稿的写路径整体关闭（`handoff` 与 `summon` 的"
                                      "`notify` 派生都写不成，返回 `ok is False`），而这一趟照跑。")
            try:
                SS.append(self.session_root, {"kind": "agent_note", "role": self.role,
                                              "note": self.secretary_problem}, sid=self.sid)
            except Exception:  # noqa: BLE001 —— 连留痕都写不成时不许把它变成"装配成功"
                pass

    # ------------------------------------------------- 父与子（业主 T21 附，S1d）
    def _parent_of_mine(self) -> tuple[str, str, str]:
        """我自己那一行 `tasks` 给的 `(父的台账号, 父的角色, 问题)`。

        为什么从台账现读、而不是只信调用方传进来的：`LlmBackend.call` 那条路手上就有行，
        但 `run_role` 那条顶趟路没有 —— 判据（D89）问的是"这一行的父是谁"，
        所以台账是那个唯一口径。

        三态：读成了 ⇒ 问题为空；读不成 ⇒ 问题非空（`("", "", "…")`），
        不许把"读不成"折成"没有父" —— 两者的后果不同（前者是"回报没挂对名字"，
        后者是"这一趟本来就是根"），而它们在盘上长得一样时没人能事后分辨。
        """
        if self.conductor is None:
            return "", "", "没有 conductor 句柄 ⇒ 读不到我这一行的父是谁"
        if not str(self.my_task_id or ""):
            return "", "", "这一趟没有台账号（尚未落台账）⇒ 读不到父是谁"
        look = getattr(self.conductor, "_task", None)
        if not callable(look):
            return "", "", "这个 conductor 没有 `_task` ⇒ 读不到我这一行的父是谁"
        try:
            row = look(self.my_task_id)
        except Exception as exc:  # noqa: BLE001 —— 读不成 ≠ 没有父
            return "", "", f"台账读不成（{type(exc).__name__}: {exc}）"
        if not row:
            return "", "", f"台账里没有我这一行（task_id={self.my_task_id!r}）"
        return (str(row.get("parent_task_id") or ""),
                str(row.get("called_by") or ""), "")

    def _step_counter(self, start: int) -> Iterator[int]:
        """步号计数器：无限（业主 2026-10-10 裁定 12-K：步数上限不作硬标准、不设机器闸）。

        为什么单独一个方法而不是在循环里写 `while True`：这一句就是那条裁定的落点本身，
        值得有个能被 grep 到的名字与 docstring（判据也直接打在它上面）。
        出口不在这里 —— 循环的 `break` 各自带 `stop_reason`（收工/叫停/预算/墙钟/判停/未接线…）。
        """
        step = start
        while True:
            yield step
            step += 1

    def _resolve_parent(self, given: str, summoned_by: str) -> tuple[str, str, str]:
        """定这一趟的收件人：`(父的台账号, 父的角色, 问题)`。三条分支，逐条都有理由。

        1. 调用方给了 `given`（`LlmBackend.call` 从它那一行读出来的）⇒ 用它，
           并把 `summoned_by`（同一个来源的 `called_by`）当父的角色；
        2. 没给 ⇒ 从台账读（`_parent_of_mine`）—— 这是 D89 的修法：
           子报给父，板项的 `parent_task_id` 必须是父的台账号；
        3. 两个来源都没有 ⇒ 顶层发起：收件人 = `(我的台账号, 主控的角色)`，
           也就是"回报挂在这一趟自己名下"。这一支与改前的行为逐字相同 ——
           它是有意的（顶层那一趟就是这一支的根，没有别人可挂）。
           为什么角色落回主控而不是"我自己"：顶趟那一行的 `called_by` 写的是
           `"user"`（`open_top_level_run` 的 `by="user"`），而 `"user"` 不是角色名
           （`schema.ROLES` 里没有它）⇒ 按角色归队时只能落到读板的那个人（主控）。

        但"没读成"不是这一支：台账读不成时返回 `pid=""` 并把理由放进第三个返回值。
        谁都不许把"读不成"当成"顶层发起" —— 前者会让提示词里那一格凭空写一个父编号
        （拿自己的编号冒充父的编号，模型会照它去沟通），后者才是事实。
        """
        pid, prole, problem = str(given or ""), str(summoned_by or ""), ""
        if not pid:
            pid, prole, problem = self._parent_of_mine()
        if prole and not _is_role_name(prole):
            prole = ""
        if pid:
            return pid, (prole or S.CONDUCTOR_ROLE), ""
        if problem:
            return "", (prole or S.CONDUCTOR_ROLE), problem
        return str(self.my_task_id or ""), (prole or S.CONDUCTOR_ROLE), ""

    def _children_text(self) -> str:
        """此刻我名下的子代理 —— 名册摘要（业主 E17：渲染的是名册，不是台账号）。

        格式：`D1 · 把 X 的族构造证据补齐 · 活跃`（名字 · 一句简介 · 状态）；
        名册读不成时退回 `conductor._children_of` 的代号清单并写明"（名册没读成，
        先给代号）" —— 退回也要看得见，不许静默换成另一种东西。

        四种返回值刻意不同：真清单 / 空串（确实没有 ⇒ 提示词层渲染「（此刻名下没有子代理）」）/
        带括号的问题串（没读成）/ 截断后的"…等 N 个"（把总数写出来，免得"20 个"被读成"正好 20 个"）。

        它是这一趟开始那一刻的名单（提示词在 `run` 里渲染一次）：这一趟里新派的
        子代理不会自己出现在这里。不假装实时 —— 那需要每一步重渲染，见 `draft/85` §5.2。
        """
        if not str(self.my_task_id or ""):
            return "（这一趟还没落台账，读不到子代理清单）"
        # 名册那一支（S1k-2）：有秘书就用它（名字 + 简介 + 状态）。
        if self.secretary is not None and hasattr(self.secretary, "roster_view"):
            try:
                view = self.secretary.roster_view(owner=self.my_task_id)
            except Exception as exc:  # noqa: BLE001 —— 读不成要如实说，别退回代号冒充名册
                return f"（名册没读成：{type(exc).__name__}: {exc}）"
            if view.get("checked"):
                rows = list(view.get("rows") or [])
                if not rows:
                    return ""
                head = "、".join(f"{r.get('name')} · {r.get('brief')} · {r.get('state')}"
                                 for r in rows[:20])
                more = int(view.get("more") or 0)
                return head if not more else f"{head} …等 {len(rows) + more} 个"
            # 名册没读成：如实说，但也别让模型瞎猜——附上代号清单（写清这是代号）
            codes = self._child_codes()
            return (f"（名册没读成：{view.get('reason')}；先给台账号：{codes}）"
                    if codes else f"（名册没读成：{view.get('reason')}）")
        codes = self._child_codes()
        if codes.startswith("（"):
            return codes
        return f"（没有名册可读，先给台账号：{codes}）" if codes else ""

    def _child_codes(self) -> str:
        """`conductor._children_of` 的代号清单（名册不可用时的退路；读不成 ⇒ 带括号的问题）。"""
        if self.conductor is None:
            return "（读不到子代理清单：这一趟没有 conductor 句柄）"
        look = getattr(self.conductor, "_children_of", None)
        if not callable(look):
            return "（读不到子代理清单：这个 conductor 没有 `_children_of`）"
        try:
            kids = [str(x) for x in look(self.my_task_id)]
        except Exception as exc:  # noqa: BLE001 —— 读不成 ≠ 没有子代理
            return f"（子代理清单没读成：{type(exc).__name__}: {exc}）"
        if not kids:
            return ""
        head = "、".join(kids[:20])
        return head if len(kids) <= 20 else f"{head} …等 {len(kids)} 个"

    def _prompt(self, messages: Sequence[Mapping[str, Any]], *, step: int) -> str:
        """这一步发给模型的提示词 = 序列的渲染 + 尾部那几句（S-C，裁定 5甲）。

        改前它接的是一整段 `transcript` 字符串；现在它接的是消息序列并在内部渲染 ——
        "历史载体是谁"从这一处起换了个东西，而念出来的那份文本一个字没变
        （`render_messages` 与改前那些 `+=` 拼法逐字相同，见 `_spoken_half`/`_result_half`）。
        """
        transcript = render_messages(messages)
        # 步数不是收工理由（业主 2026-10-10 裁定 12-K）⇒ 这一段里不再有
        # "这是最后一步"这一支。改前它在第 `max_steps` 步上对模型说
        # 「这是最后一步：不要再调用工具…直接输出 final」—— 那是硬闸的口吻，
        # 模型读到它会赶在线上交一个没做完的结论；而循环当时确实会收工，
        # 所以那句话是真的。现在循环不再因步数收工，这句话就成了谎话
        # （比没有更糟：它会让模型自己把活截断）。留给模型的是报告阈值本身。
        tail = ("请按循环协议输出下一步（一个 JSON 对象，"
                f"{len(SHAPES)} 种形状取其一：{' / '.join(SHAPES)}）。")
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
        return (f"{transcript}\n\n---\n现在是第 {step + 1} 步（步数没有硬上限；"
                f"每满 {self.max_steps} 步会向父代理报一次账，由它决定继续放行还是刹停）。{tail}\n"
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


    def _hear(self, *, step: int = 0) -> list[dict[str, Any]]:
        """听一次新消息 + 新板项：把这次运行期间新到的取出来并登记。

        这里用 `window=None`：这一步的结果会把新到的全部并进去（`heard` 就是它们），
        所以"渲染了多少就标多少"这条纪律在这里等价于"标全部新到的" ——
        与跑在 `run()` 开头的那一次（有窗口、见 `inbox_digest`）口径一致，只是窗口不同。

        板项那一半（S1i，业主 A3=甲"渲染即 seen"）：未 `seen` 的项与留言同一处取，
        取到什么就标什么（`mark_item_seen`，带 `seen_by`/`seen_step`）——
        于是"挂在父名下的交差通报"在下一步就进得了上下文，而不是等下一次运行。
        """
        digest, fresh, problems = inbox_digest(self.session_root, self.role, sid=self.sid,
                                              window=None,
                                              parent_task_id=self.parent_task_id,
                                              parent_role=self.parent_role)
        board_text, board_ids, board_problems = board_digest(
            self.conductor, my_task_id=self.my_task_id, window=None)
        if not fresh and not board_ids:
            return []
        problem = mark_delivered(self.session_root, self.role, fresh, sid=self.sid)
        heard: list[dict[str, Any]] = []
        messages, _ = read_messages(self.session_root, self.role, sid=self.sid,
                                    parent_task_id=self.parent_task_id,
                                    parent_role=self.parent_role)
        for m in messages:
            if str(m.get("msg_id")) in fresh:
                heard.append({"id": m.get("msg_id"), "from": m.get("from"),
                              "channel": m.get("channel"), "subject": m.get("subject"),
                              "body": _clip(m.get("body"), 400),
                              # S-G：来源那一格（DSH 的 `source`）—— 没有它，
                              # "这条是孩子交差 / 广播 / 用户的话"在读数上分不开。
                              "source": message_source(m)})
        if problem:
            heard.append({"投递登记失败": problem})
        if board_ids:
            heard.append({"板": _clip(board_text, 1200)})
            for item_id in board_ids:
                state, why = self.conductor.mark_item_seen(item_id, by_task_id=self.my_task_id,
                                                           step=step)
                if not state:
                    heard.append({"板项没标成 seen": f"{item_id}：{why}"})
        heard.extend({"板读取问题": p} for p in board_problems)
        return heard

    def _retire_ready_note(self) -> dict[str, Any]:
        """"名下哪几项可以退役了"的就绪读数（只报不动作，业主 T22 与 §1.9）。

        位置：与"板项进上下文"同一处 —— `run` 开头渲染到板项时、以及 `_hear` 拿到板项的那一步。
        为什么不在每一步都算：它要读一次台账快照（代价说明在 `retire_ready` 的 docstring 里），
        而只有"这一步真的读到了板项"时，父才谈得上"要不要退役谁"。

        框架不自动退役（业主逐字：「由父代理决定是否消边」）：这里只把读数并进结果，
        写盘那一步在 `Secretary.retire`（S1k，父说了才做）。读不成也如实并入。
        """
        if self.conductor is None or not str(self.my_task_id or ""):
            return {}
        look = getattr(self.conductor, "retire_ready", None)
        if not callable(look):
            return {}
        try:
            got = look(self.my_task_id)
        except Exception as exc:  # noqa: BLE001 —— 读不成也如实说
            return {"可退役读数没读成": f"{type(exc).__name__}: {exc}"}
        if not isinstance(got, dict) or not got.get("checked"):
            return {"可退役读数没读成": str((got or {}).get("reason") or "读数不是对象")}
        rows = list(got.get("ready") or [])
        if not rows:
            return {}
        return {"可退役": rows}

    def _summarize_for_compaction(self, early: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
        """把被遮蔽的那一段交给模型写摘要（裁定 8乙：机械摘要换成 LLM）。

        返回 `(摘要, 问题)`。三条照 DSH：

        - 送进去的是模型可见的 `content`（三个移植包里 `grep reasoning` 零命中 ⇒
          思维链不进摘要请求：摘要要复述的是"发生了什么"，不是"它当时怎么想的"）；
        - 这次调用记在现成的用量档上 + `note="compaction"`（裁定 12-J=甲：
          不新造 scope、不动 `schema.py`）—— 花销因此可归口，钱不会静默流走；
        - 拿不到摘要（没接线 / 调不通 / 空回复）⇒ 返回问题，不压（warn-and-continue，
          照 DSH 自动路径的姿态）。
        """
        body = "\n\n".join(str(m.get("content") or "") for m in early)
        prompt = f"{COMPACTION_INSTRUCTION}\n\n--- 要压缩的历史 ---\n{body}"
        try:
            call = self.seam.ask(prompt, system=self._compaction_system(), note="compaction",
                                 task_id=str(self.my_task_id or ""))
        except Exception as exc:  # noqa: BLE001 —— 摘要调用抛异常也要如实变成"没压成"
            return "", f"摘要调用抛异常（{type(exc).__name__}: {exc}）"
        if not call.ok:
            return "", f"摘要调用没成（{call.problem}：{call.detail or '无细节'}）"
        text = str(call.text or "").strip()
        if not text:
            return "", "摘要调用回了空文本（空摘要等于把那段历史静默扔掉）"
        return text, ""

    def _compaction_system(self) -> str:
        """摘要那一次调用用的 system：与研究无关的"压缩器"身份（不含本岗的工具面）。

        为什么另起一句而不是复用 `self` 那一份身份提示词：那一份写的是"你是谁、你的职责、
        你的工具面"，而这一次调用要它做的是压缩，不是接着干活 —— 拿干活的身份去要摘要，
        它会按职责继续研究（真机里那种"摘要变成第二份结论"的形态）。
        """
        return ("你是一个上下文压缩器。你的唯一任务是把给定的一段历史改写成一份可继续工作的"
                "检查点摘要。不要继续研究、不要调用工具、不要下新结论 —— 只复述已知信息，"
                "并如实标出未知。")

    def _maybe_compact(self, messages: list[dict[str, Any]], *, step: int,
                       run: "AgentLoop.LoopRun") -> list[dict[str, Any]]:
        """步边界上的压缩判定（S-B / 裁定 7乙 + 8乙 + 12-I=甲）。返回（可能被替换过的）序列。

        四件事按顺序，每一件都有它自己的读数：

        1. 没配预算（`registry.default_budget is None`）⇒ 什么都不做 ——
           那是"没启用"，不是"没查成"（三态里的第一档，所以不落任何"没压"的噪声）。
        2. 走 `compact_by_pressure`（token 压力那条路）。
        3. 没压（未到阈值 / 容量读不到 / 没有可遮蔽的条目 / 摘要更大）⇒ 不替换历史；
           "读不到容量"那一档每趟只警告一次（照 DSH `CB:803-808` 的去重）。
        4. 压了 ⇒ 事件三件套（`compaction_start` / `compaction_summary` /
           `compaction_end`）+ 一条带 `surface_op` 的替换事件（位置区间，闭区间两端都含），
           并把 `[start, end]` 换成一条摘要消息。

        为什么把替换消息也写进事件（施工单 §2 逐字）：只在内存里压会让续跑那一趟看到
        没压过的版本 —— 而"续跑看到的正是当时那份对话"是本仓最强的一条判据
        （`resume_messages`）。`resume_messages` 读这些事件按序重放，两处因此逐条相等。
        """
        budget = getattr(self.registry, "default_budget", None)
        if budget is None:
            return messages
        from . import contextbudget as CB

        cid = f"c{step:04d}-{self.role}"
        self._last_summary_note = {}

        def _summarize(early: list[Any]) -> str:
            """`compact_by_pressure` 要的摘要器（8乙：真调模型）。

            拿不到摘要时抛一个受控异常而不是返回空串：返回空串会被
            `compact_by_pressure` 当成"注入的 summarize 违约"抛 `ValueError`，
            而那与"摘要这次没拿到"是两件事（前者是接线错误，后者是一次失败）。
            """
            text, problem = self._summarize_for_compaction(early)
            if problem:
                raise _CompactionRefused(problem)
            self._last_summary_note = {"note": "compaction"}
            return text

        try:
            result = CB.compact_by_pressure(messages, budget=budget, summarize=_summarize)
        except (CB.CompactionNotSmallerError, _CompactionRefused) as exc:
            # 自动路径的处置：如实记一条读数、不替换历史（DSH 手动路径才抛给调用方）。
            SS.append(self.session_root, {
                "kind": "compaction_end", "role": self.role, "compaction_id": cid,
                "step": step, "ok": False, "error": f"{type(exc).__name__}: {exc}"}, sid=self.sid)
            run.notes.append(f"压缩没做成：{exc}")
            return messages
        if not result.compacted:
            if "读不到容量" in result.reason and not self._compaction_capacity_warned:
                self._compaction_capacity_warned = True
                SS.append(self.session_root, {
                    "kind": "agent_note", "role": self.role,
                    "note": f"压缩：{result.reason}"}, sid=self.sid)
                run.notes.append(f"压缩：{result.reason}")
            return messages
        # ---- 压成了：三件套 + 替换事件（start 先落盘 = 事实上的锁，照 DSH `CB:436-452`）
        summary_node = (result.text.split("--- 最近 ", 1)[0]) if result.text else ""
        SS.append(self.session_root, {
            "kind": "compaction_start", "role": self.role, "compaction_id": cid,
            "step": step, "turn": step}, sid=self.sid)
        summary_call_note = self._last_summary_note
        SS.append(self.session_root, {
            "kind": "compaction_summary", "role": self.role, "compaction_id": cid,
            "step": step, "summary": summary_node,
            "shadowed_range": list(result.shadowed_range),
            "shadowed_tokens": result.shadowed_tokens, "framed_tokens": result.framed_tokens,
            "threshold_tokens": result.threshold_tokens, "retain_tokens": result.retain_tokens,
            "chars_per_token": result.chars_per_token, "baseline_source": result.baseline_source,
            "summarizer": result.summarizer, "note": "compaction",
            "usage": dict(self._last_summary_note or {})}, sid=self.sid)
        start, end = result.shadowed_range
        replacement = {"role": "user", "content": summary_node}
        swapped = (list(messages[:start]) + [dict(replacement)] + list(messages[end + 1:]))
        SS.append(self.session_root, {
            "kind": "compaction_swap", "role": self.role, "compaction_id": cid, "step": step,
            # 闭区间、两端都含（DSH `SURF:165-174`）。这是位置 span 不是数值区间
            # （`types.d.ts:115-122` 的警告）⇒ 读回时按位置重放，不许写 range(start, end+1)。
            "surface_op": {"op": "replace", "start_seq": start, "end_seq": end},
            "replacement_index": start, "replacement_message": dict(replacement),
            "shadowed_token_count": result.shadowed_tokens}, sid=self.sid)
        SS.append(self.session_root, {
            "kind": "compaction_end", "role": self.role, "compaction_id": cid,
            "step": step, "ok": True}, sid=self.sid)
        run.compactions += 1
        run.notes.append(
            f"压缩（{result.summarizer}）：{result.shadowed_tokens} token → "
            f"{result.framed_tokens} token（阈值 {result.threshold_tokens}，"
            f"保留额 {result.retain_tokens}，尺 {result.chars_per_token} 字符/token）")
        return swapped

    def _in_flight_reading(self) -> str:
        """收工那一刻"我名下还有几条在飞"（S-G，裁定 15；读数，不拦）。

        四态各自如实（读不成也要说清是哪一档，不许静默返回空串糊过去）：
        - 没有 conductor / 没有台账号 ⇒ 空串（顶层没建行那一档，本来就没有"名下的孩子"）；
        - 台账读不成 ⇒ 一句"没读成"（不许当成"都回来了"——那是把没查成折成查过了）；
        - 一条在飞都没有 ⇒ 空串（绝大多数收工是这一档，不落噪声）；
        - 有在飞 ⇒ 点名那几条 + 明说"不拦收工"（含 DSH 的 `retry` 那一格：读数期间
          台账变了就重算，`retried=True` 要写在句子里）。
        """
        if self.conductor is None or not str(self.my_task_id or ""):
            return ""
        look = getattr(self.conductor, "settlement_reading", None)
        if not callable(look):
            return ""
        try:
            got = look(self.my_task_id)
        except Exception as exc:  # noqa: BLE001 —— 读不成也如实说
            return f"在飞读数没读成（{type(exc).__name__}: {exc}）⇒ 不知道收工时还有没有孩子在飞"
        if not isinstance(got, dict) or not got.get("checked"):
            return f"在飞读数没读成（{str((got or {}).get('reason') or '读数不是对象')}）"
        n = int(got.get("in_flight") or 0)
        if n <= 0:
            return ""
        who = "、".join(f"{r.get('role') or '?'}·{r.get('task_id')}" for r in
                        list(got.get("rows") or [])[:5] if int(r.get("in_flight") or 0) > 0)
        return (f"收工时名下还有 {n} 条在飞：{who}"
                "（读数，不拦收工 —— 这一趟的结论可能不含它们的产出）"
                + ("（注：这个读数是重算过的 —— 读数期间台账又变了）" if got.get("retried") else ""))

    def _budget_text(self) -> str:
        if self.seam.usd_budget is None:
            return f"未设置上限（已用 {self.seam.spend.usd:.6f} 美元）"
        left = max(0.0, self.seam.usd_budget - self.seam.spend.usd)
        return f"{left:.6f} 美元（上限 {self.seam.usd_budget:.6f}）"

    def run(self, task: str, *, summoned_by: str = "", my_task_id: str = "",
            parent_task_id: str = "", surface: str = "",
            depth: int = 1, resumed: tuple[Sequence[Mapping[str, Any]], int] | None = None,
            waiting_for: str = "") -> LoopRun:
        """跑一次循环。`task` 是这次要做的事（被召唤时就是调用方给的参数）。

        `resumed` 是 `(重建出来的消息序列, 从第几步接着跑)`（由 `run_role` 在
        `--resume` 那一趟里从检查点 + 会话记录算出来，见 `resume_messages`）——
        S-C 第 ② 步之前它是"一段文本"，现在是序列本身：给了它就「不再自己拼开头」，
        那一趟要接着说的正是"它上次说过的那些话"，重拼一遍等于换一段话重新开始。
        收件箱那一段仍然现读（新到的留言本来就该听到），投递登记也照旧做
        （那两件事是"这一趟"的事实，不是"上一趟"的）。
        """
        t0 = time.monotonic()
        self.my_task_id = my_task_id
        self.depth = depth
        # 这一趟的收件人（父是谁）现算一次：它既是提示词里 `{{parent_task_id}}` 那一格，
        # 也是终态回报挂板项时用的名字（D89）。三条分支见 `_resolve_parent`。
        self.parent_task_id, self.parent_role, self.parent_problem = self._resolve_parent(
            parent_task_id, summoned_by)
        # 读写面（S1n-b）：由调用方传进来（`LlmBackend.call` 从父的名册里读到它）。
        self.surface = str(surface or "")
        # 秘书绑到这一趟的实例上（S1m）：绑上之后它的台账分片、并落一份存活标记
        # （"一实例一秘书"从对象层面落到盘上）。失败 fail-open，但要留痕。
        if self.secretary is not None and str(my_task_id or ""):
            try:
                self.secretary.bind_task(my_task_id)
            except Exception as exc:  # noqa: BLE001 —— 绑定失败不许带走这一趟
                self.secretary_problem = (f"秘书没绑上实例（{type(exc).__name__}: {exc}）"
                                          "⇒ 它的台账仍写老文件（不分片）")
        # 收件箱：`inbox` 是渲染进开场提示词的那一段，`fresh_ids` 是它渲染过的 id
        # —— 下面 `mark_delivered` 只标这一批（D75：旧的写法渲染 8 条、却把全部未投递标掉，
        # 于是第 9 条及更早的留言永久丢失）。
        inbox, fresh_ids, inbox_problems = inbox_digest(self.session_root, self.role, sid=self.sid,
                                                        parent_task_id=self.parent_task_id,
                                                        parent_role=self.parent_role)
        # 板项（业主 A3=甲 "渲染即 seen"）：与我名下的未消项同一处现读；
        # `board_ids` 会在第一次成功的模型调用之后标成 `seen`（下面与投递标记同址）。
        board, board_ids, board_problems = board_digest(self.conductor, my_task_id=my_task_id)
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
        run.notes.extend(f"工作项板读取：{p}" for p in board_problems)
        # 投递标记推迟到第一次成功模型调用之后（`draft/86` §4.1 的 D75 后半）。
        #
        # 为什么不能在这里就标：旧写法在任何模型调用之前落 `mark_delivered`，于是
        # "这一趟在首次 `ask_step` 之前就死掉"（`not_wired`、步 0 撞停机开关、预算已尽）
        # 会把消息的"新"标记永久吃掉 —— 消息还在盘上，但它再也不标"新"，
        # 而且会被挤进 8 条窗口（真机 579 条留言、只有 8 条被标记读过，这个形态是其中一支）。
        # 现在：先进上下文、模型真的被问过一次之后，才承认"它送达了"。
        pending_delivery: list[str] = list(fresh_ids)
        delivered_marked = False
        # 板项那一半：渲染过、但还没标 seen 的项（与 `pending_delivery` 同一处落定 ——
        # "模型真的被问过一次"才算它进过上下文，业主 A3 的"渲染即 seen"落在这里）。
        pending_seen: list[str] = list(board_ids)

        availability = self._availability()
        # 父与子两格（业主 T21 附）：数据在台账里，缺的一直是"渲染给模型看"。
        # `children` 是这一趟开始那一刻的名单；`parent_problem` 非空时如实进 notes
        # （"父是谁没读成"不许静默 —— 那会让回报挂错名字而没人知道）。
        children_text = self._children_text()
        if self.parent_problem:
            run.notes.append(f"父代理没读成：{self.parent_problem} ⇒ 回报挂在这一趟自己名下")
        # 提示词那一格：读成了 ⇒ 真编号（顶层发起时是空串 ⇒ 提示词层渲染"顶层发起"
        # 那句缺省）；没读成 ⇒ 把理由端上去 —— 拿自己的编号冒充父的编号是最坏的
        # 一种"看起来成功"（模型会照它去沟通）。
        parent_fact = self.parent_task_id or (
            f"（没读成：{self.parent_problem}）" if self.parent_problem else "")
        facts = dict(task=task, summoned_by=summoned_by, task_id=my_task_id, depth=depth,
                     parent_task_id=parent_fact, children=children_text,
                     board=board,
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
            # ---- S-C（裁定 5甲）第 ① 步：历史载体从"一段字符串"换成消息序列。
            #
            # 开场那一整段（收件箱/任务/身份）是序列里的第一条 `user` 消息；
            # `transcript` 从此是 `render_messages(messages)` 的渲染（逐字不变），
            # 所以它的所有读者（Web UI 回放、续跑、`--resume`）这一步之后照旧。
            messages: list[dict[str, Any]] = [user_message(
                _opening_transcript(task, inbox=inbox, summoned_by=summoned_by,
                                    task_id=my_task_id, depth=depth))]
        else:
            rebuilt, start_step = resumed
            run.resumed_from = start_step
            # S-C 第 ② 步：续跑拿到的是消息序列（不是一段文本）——
            # 于是"接着上次那份对话"这句话从"两段字符串相等"变成"两条序列逐条相等"。
            messages = [dict(m) for m in rebuilt]
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
        #
        # ## 计数按委托记账（业主 2026-10-10 裁定 12-F + 补充）
        #
        # 逐字：「只有主控会和用户交互，其余子代理不会和用户交互，适应性地改为每做完一个委托清一次」。
        # 于是清零的触发点有两条（都在本文件里现成可判）：
        #   ① 委托边界：这里（新委托开始）与收工处（委托做完）各清一次 —— "这一次委托之内的账"；
        #   ② 只有主控：新的用户消息/插话到手时清（下面 `_user_message_reset`）——
        #      子代理收不到用户消息，这条对它们在结构上不存在。
        # 父代理的一条普通留言不清：留言不是新委托，否则"同一件事被反复要求"最该被发现的时候会被清掉。
        prev_key = ""
        prev_reading = ""
        same_call = 0
        #: 「同一条路」的游标与连击（D31）：上一个粗键，以及它连着出现了几次。
        prev_stall = ""
        stalled = 0
        #: 这两格是读数（提醒过几次），与"因此停了没有"分开报（裁定 10丙 要的两档分开）。
        nudged_calls = 0
        nudged_stalls = 0
        counters_reset_at = start_step        # 最近一次清零发生在第几步（可复核"这一次委托从哪算起"）
        #: 这一步收到的插话（叫停类要在这一步做完之后落一条"有没有改变做法"的读数）。
        pending_interjections: dict[str, Any] | None = None
        #: 步数上报（业主 2026-10-10 裁定 12-K 逐字：「步数上限不做为硬标准，不设机器闸，
        #: 但向父代理报告步数超限行为，由父代理决定继续放行还是刹停」）⇒
        #: `max_steps` 从"循环自己收工的理由"变成报告阈值：跨过它只落一条上报，
        #: 循环照常继续（父代理什么都不做 ⇒ 继续跑；要停由它走 `interrupt`）。
        #: 保留的闸只有两件 —— 预算与墙钟（它们不是"轮次预算"），以及 S-D 那道判停。
        reports_sent = 0
        next_report_at = max(1, int(self.max_steps))

        #: 不设步数硬闸（照 DSH：它的 agent-loop 里没有 maxSteps 这类字段）。
        #: 出口只有 `break`（收工 / 叫停 / 预算 / 墙钟 / 判停 / 未接线…），每个都带自己的 stop_reason。
        for step in self._step_counter(start_step):
            if step + 1 >= next_report_at:
                # 跨过阈值 ⇒ 上报（四样读数：已用步数 / 最近在做什么 / 花了多少 / 还没交 final）。
                # 它不改循环行为：父代理不动作就继续跑 —— 这正是本裁定的核心判据。
                reports_sent += 1
                next_report_at += max(1, int(self.max_steps))
                step_note = (
                    f"步数超限报告（第 {reports_sent} 次）：已用 {step + 1} 步（阈值 {self.max_steps}）；"
                    "最近三步：" + "；".join(_call_brief(s.shape, s.payload) for s in run.steps[-3:])
                    + f"；花销 {self._budget_text()}；到这一步为止没有 final。"
                )
                SS.append(self.session_root, {
                    "kind": "agent_note", "role": self.role, "note": step_note,
                    "steps_used": step + 1, "threshold": int(self.max_steps),
                    "reports_sent": reports_sent,
                }, sid=self.sid)
                # 报给父代理；主控是顶层（`depth == 1`，上面没有人可发）⇒ 读数留在会话里，
                # 由它自己裁。判"有没有父"用的是层号而不是 `summoned_by`：
                # `run_role` 给顶趟的 `summoned_by` 填的就是 `S.CONDUCTOR_ROLE`
                # （`agent_loop.py:4814`），所以"父的角色是 M"这件事既可能是顶层、
                # 也可能是"被 M 召唤的孩子"—— 两者用 `summoned_by` 分不开，
                # 而 `depth` 分得开（顶趟 1、被召唤 2 起，`agent_loop.py:4815`）。
                parent_role = str(self.parent_role or "")
                if int(self.depth or 1) > 1 and parent_role:
                    _mid, mproblem = send_message(
                        self.session_root, sender=self.role, to=parent_role,
                        subject=f"步数超限：{self.role} 已用 {step + 1} 步",
                        body=step_note, sid=self.sid, from_task_id=my_task_id)
                    if mproblem:
                        run.notes.append(f"步数上报未送达：{mproblem}")
            stop_reason = self._user_stop_reason(run)
            if stop_reason:
                # 人叫停：把这一步之前做过的事「如实收尾」（不是把进程杀掉）。
                # `draft/37` §125 的真机读数：用户在单趟 `run-agent` 里叫停，
                # 那一趟继续跑了 60 多个任务、烧掉 $0.98，最后只能强杀 ——
                # 强杀的结果是台账里没有 `agent_run_end`、盘上没有步检查点，
                # "跑到哪儿了"事后无从回答。这条 break 就是补那一格。
                run.stop_reason = stop_reason
                run.final = run.final or self._stop_note(stop_reason, step)
                # S4-b（`draft/84` §2.2）：停止沿边下发 —— 给我还在飞的直接子代理
                # 各开一条 `notice`/`ack` 板项（ack 才算传达到）。放在 break 之前：
                # 这一趟马上就要收工，边上的通知是它最后一次能做的事。
                out = self._notify_children_of_stop(stop_reason)
                if out:
                    run.notes.append(out)
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
            # ---- 集体插话（`draft/39` §3.11 二 D07，用户 2026-10-05 裁）
            #
            # 摆在下一步开头：插话不是"再来一条消息"，而是"做这一步之前先看它"。
            # 为什么在预算判据之后、`ask_step` 之前：预算耗尽/用户叫停时不该再被插话
            # 拖着做事；而这一步的提示词是下一句就要发出去的，插话必须在那之前进去。
            new_interjections, ij_problems = read_interjections(self.session_root, self.role,
                                                                sid=self.sid)
            run.notes.extend(f"插话读取：{p}" for p in ij_problems)
            if new_interjections:
                ids = [str(i.get("interjection_id") or "") for i in new_interjections]
                messages.append(user_message(_interjection_block(new_interjections)))
                _p, seen_problem = mark_interjections_seen(self.session_root, self.role, ids,
                                                           sid=self.sid, step=step)
                if seen_problem:
                    run.notes.append(f"插话消费登记失败：{seen_problem}")
                if any(i.get("is_stop") for i in new_interjections):
                    # 叫停类：这一步做完之后要落"有没有改变做法"（下面按 key 比）
                    pending_interjections = {"ids": ids, "step": step,
                                             "prev_key": prev_key, "prev_reading": prev_reading}
                # ---- 新用户消息 ⇒ 进度计数清零（裁定 12-F；只有主控有这条通道）
                #
                # 逐字理由（DSH 的承诺，照搬）：「A new user message clears the count,
                # so a fresh instruction is never treated as a loop」。
                # 只有 M 收得到用户插话（`read_interjections` 对非主控直接返回空表），
                # 所以这一格结构上只对主控生效；子代理按"委托边界"清零（见循环头的说明）。
                # 父代理的一条普通留言不清：留言不是新委托 —— 那条负控在
                # `tests/test_the_progress_counts_are_per_delegation.py` 里。
                if any(str(i.get("channel") or "") == "user" for i in new_interjections):
                    prev_key, prev_reading, prev_stall = "", "", ""
                    same_call, stalled = 0, 0
                    counters_reset_at = step
            # ---- S-B（裁定 7乙 + 8乙 + 12-I=甲）：步边界上的压缩判定。
            #
            # 位置与理由：读插话之后、`ask_step` 之前 —— 这一步的提示词是下一句就要发出去的，
            # 压缩必须在那之前生效；而插话（新用户消息）不该被刚压过的历史吃掉。
            # 判定本身在 `_maybe_compact`（它负责三态、事件三件套与"只压一次"的闸门）。
            messages = self._maybe_compact(messages, step=step, run=run)
            data, call = self.seam.ask_step(self._prompt(messages, step=step),
                                            system=system, task_id=my_task_id,
                                            note=f"{self.role}.step{step}",
                                            max_tokens=self.max_output_tokens,
                                            face=face)
            # 第一次成功的模型调用之后才登记投递（推迟标记的落点，见上面那段注释）：
            # "模型真的被问过一次"= 这一批消息确实进了上下文 ⇒ 承认它送达。
            if pending_delivery and not delivered_marked and call.ok:
                problem = mark_delivered(self.session_root, self.role, pending_delivery,
                                         sid=self.sid)
                if problem:
                    run.notes.append(f"投递登记失败：{problem}")
                pending_delivery, delivered_marked = [], True
            if pending_seen and call.ok:
                # 渲染即 seen（业主 A3=甲）：这一步的提示词里带了它们 ⇒ 标 seen。
                # 只标渲染过的那些（`board_digest` 返回什么就标什么，D75 的口径）。
                still: list[str] = []
                for item_id in pending_seen:
                    state, why = self.conductor.mark_item_seen(
                        item_id, by_task_id=my_task_id, step=step)
                    if not state:
                        still.append(item_id)
                        run.notes.append(f"工作项 {item_id} 没标成 seen：{why}")
                    elif state == "ack_unbacked":
                        run.notes.append(f"工作项 {item_id}：{why}")
                    else:
                        # S4-b：停止通知（`kind=notice`、`expects=ack`）读到就算收到
                        # ⇒ 框架替这一趟 ack 它（"ack 才算传达到"，`draft/84` §2.2）。
                        # 为什么框架可以代 ack：这条通知的对象是这一趟进程（收工），
                        # 不是要模型交付的活；模型有没有"表态"不影响它已经收到这件事。
                        ack_note = self._ack_stop_notice(item_id, step)
                        if ack_note:
                            run.notes.append(ack_note)
                pending_seen = still
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
                # 整条原文落盘（D40）：报错给了列号，而被剪掉的那一段才是证据。
                dump = _dump_invalid_reply(self.workspace_root, self.sid, step, call.text or "")
                if dump:
                    bad_result["raw_reply_path"] = dump
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
                    # S-C：这一句纠正进 tool 那条消息（配对 id 照给 —— 它确实是
                    # 框架对"这一步那次调用"的回答）。
                    messages.append(assistant_message(step, {}, name="invalid"))
                    messages.append(tool_message(step, _bad_args_line(step, str(bad_result["detail"]))))
                    continue
                if run.bad_json_streak > self.max_bad_json:
                    run.stop_reason = "bad_json_limit"
                    run.final = (f"连续 {run.bad_json_streak} 次没有给出可解析的 JSON"
                                 f"（最后一次：{call.problem}），停止")
                    break
                messages.append(assistant_message(step, {}, name="invalid"))
                messages.append(tool_message(
                    step, _bad_json_line(step, call.problem, str(bad_result["detail"]))))
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
                messages.append(assistant_message(step, data, name=recognized or "step"))
                messages.append(tool_message(
                    step, _payload_line(step, recognized, problem) if recognized
                    else _invalid_line(step, problem), name=recognized or "step"))
                continue
            # 说对了一次 ⇒ 连击清零（`draft/37` §68）。清零的判据是"它按协议说出了一个形状"，
            # 不是"那件事办成了" —— 工具被拒、召唤被拒、参数不合法都算说对了协议，
            # 那些走的是各自的纠正路径（`RELAY_REFUSALS` / `invalid_params`）。
            run.bad_json_streak = 0
            run.bad_args_streak = 0
            if shape == "final":
                # ---- 强制 notify 表（`draft/39` §3.2/§3.3，用户 2026-10-05 裁）
                #
                # 口径三句：① 除主控外的角色收工必须填这张表（`to`/`summary`/`body`）；
                # ② 填错/没填 ⇒ 打回重填（不代填），附"四件事"的详细格式说明；
                # ③ 连续打回两次，警告里再加"先说明你上一次为什么没按格式填"。
                # 主控 M 的 `final` 是给用户的回复，不在这套里（用户原话：
                # "M 向 Agent 派活时一样强制留痕，向用户回复时不搞这种操作"）。
                # ---- L-05e（`draft/52` F 组 / P-10）：强制闸门降级成读数
                #
                # 旧形态：收工不带 `notify` ⇒ 打回重填，连续 3 次 ⇒ `stop_reason="no_notify"`。
                # 真机读数把它的收益证伪了：5269 个 `agent_step` 里 shape 无 `final`、
                # `no_notify` 收场 0 次 ⇒ 这道闸门一次都没触发过，只贡献提示词篇幅与
                # "表格化"的负担。裁定的新口径是只留一条："要交接就写手稿" ——
                #   · 填了 `notify`（且形状对）⇒ 秘书照旧执笔一行手稿（写权已移交）；
                #   · 没填 / 填错 ⇒ 不打回：这一趟照常收工，只是没有手稿，
                #     而"为什么没有"如实落进这一步的读数（`notify_problem`）。
                # 于是它从"闸门"变成"读数"：留痕与否仍然是可见的事实，但不再拿它
                # 卡住一次已经做完的活（阻塞一条委托比放行更贵 —— 那就是 #1）。
                notify_problem = self.notify_reading(payload)
                notify = payload.get("notify")
                step_result: dict[str, Any] = {}
                if notify_problem:
                    step_result["notify_problem"] = notify_problem
                    run.notes.append(f"收工没有可用 notify 表（{notify_problem}）⇒ "
                                     "这一趟没有交接手稿（不打回、不代填）")
                if notify and not notify_problem:
                    # 写手稿 + 转发都由脚本做（模型只填表）—— 这一条是用户口径里
                    # "用脚本生成交接文件并代为转发"的落点；执笔已移交本角色的秘书。
                    hand = self._do_handoff(clean_notify(notify))
                    step_result["notify_handoff"] = hand
                    if hand.get("ok"):
                        run.handoffs.append(str(hand.get("id") or ""))
                run.final = str(payload.get("final") or "")
                run.evidence = list(payload.get("evidence") or [])
                # 收工那一步的原始载荷进 `LoopRun`（`run()` 末尾把它落进 `agent_run_end`）：
                # 这是"模型填的 notify 到得了盘"的唯一通路 —— 见 `LoopRun.final_payload`。
                run.final_payload = dict(_for_record(payload))
                # 业主 2026-10-09 第四句：整支卡住是一种停机状态 ——
                # 子代理用 `{"final": ..., "blocked": {"what":…, "why":…}}` 声明"我这趟卡住了"，
                # 框架把这一笔落到父那一行（`note_blocked`），于是"我名下在飞的子全 blocked"
                # 在盘上可读（`subtree_blocked`）。上报的正文仍由它自己那条上行报文承载。
                blocked_note = self._note_blocked_declaration(payload)
                if blocked_note:
                    step_result = {**step_result, "blocked": blocked_note}
                # 收工也是对插话的一种回应（"照插话收工"是最常见的形态）⇒ 同样落读数。
                self._record_interjection_effect(run, pending_interjections, step=step,
                                                 shape=shape, payload=payload)
                pending_interjections = None
                if step == 0 and board_ids:
                    # 开场提示词里就带了板项 ⇒ 这一步顺带报"哪几项可以退役了"
                    # （只报不动作；写盘在 S1k）。收工这一步的结果是另一只字典
                    # （`step_result`），所以这里单独并一次。
                    note = self._retire_ready_note()
                    if note:
                        step_result = {**step_result, **note}
                run.steps.append(LoopStep(step, shape, payload, step_result))
                run.stop_reason = "final"
                break
            # ---- 主控派活时的留痕（`draft/39` §3.3；L-05e 之后同样是读数不是闸门）
            #
            # 摆在"派活那一刻"（`summon`/`summon_many`）而不是 M 的 final 上：
            # M 的 final 是给用户的回复（用户明确说"向用户回复时不搞这种操作"），
            # 而"谁给谁派了什么活"正是交接的内容。
            #
            # 旧形态：填错形状 ⇒ 打回、那一次派活不发生（连续 3 次 ⇒ `no_notify`）。
            # 新形态（与收工侧同一条裁定）：派活照常发生，形状不对就把问题落进读数、
            # 用框架派生那一份留痕（谁是派生、谁是执笔仍然分得开）—— 不许因为
            # "一张表的格式"而让一次真的要发生的派活停下来。
            # （S1g 之后这段搬到了洗格式之后：留痕要看的是真正发出去的那一份载荷。）
            secretary_note = self._outbound_hook(shape, payload)
            # S1g：洗格式在发出去之前（`_outbound_hook` 与建议同一次调用、一行台账）。
            # 洗过的那一份才是真正发出去的那一份 —— 否则"秘书洗了"只是一句摆设，
            # 而模型原稿带着错名继续撞闸门（E5 实测：`run_once({"request_id": …})`
            # ⇒ `refused / invalid_params`「出现未声明的参数」）。
            washed_payload = secretary_note.pop("_washed_payload", None)
            dispatch_notify: dict[str, Any] | None = None
            if secretary_note.get("wash", {}).get("refused"):
                # 硬拒（只有"连派给谁/做什么都不全"这一格）：一行都不落（`draft/90` §1.2）。
                # 其它"洗不动"（缺必填参数…）照旧交给闸门 —— 那一档还会落 `refused` 行
                # 并可能转成"请主控代唤"，秘书抢在前面拒掉会把那条出路一起弄丢。
                result = {"ok": False, "outcome": "refused",
                          "refusal_reason": str(secretary_note["wash"]["refused"]),
                          "detail": ("秘书洗格式：这一趟派活连『派给谁/做什么』都不全 ⇒ 受控拒绝"
                                     f"（{secretary_note['wash'].get('reason') or ''}）"),
                          "washed": False}
            else:
                if (isinstance(washed_payload, Mapping)
                        and secretary_note.get("wash", {}).get("checked")):
                    if dict(washed_payload) != dict(payload):
                        run.notes.append("秘书洗格式：" + ("；".join(
                            f"{c.get('field')}→{c.get('to') or c.get('why')}"
                            for c in (secretary_note.get("changes") or ()))
                            or "（改了格式格）"))
                    # 洗过的那一份进入后面所有判据：notify 留痕、活性读数、步骤记录
                    # 都看同一次真正发出去的载荷（两份载荷并存必然分叉）。
                    payload = dict(washed_payload)
                if shape in ("summon", "summon_many") and self.role == S.CONDUCTOR_ROLE:
                    gate, dispatch_notify = self._dispatch_notify(payload)
                    if gate:
                        run.notes.append(f"派活的 notify 表格式有问题（{gate}）⇒ "
                                         "照常派活，留痕退回框架派生那一份")
                result = self._execute(shape, payload)
                if dispatch_notify is not None:
                    # 派活照旧执行，留痕在它之后写：账本里的每一行都对应一次"真的发出去的派活"
                    # （写在前面会让"被策略拒掉的派活"也留下一行像是办成了）。
                    hand = self._do_handoff(dispatch_notify)
                    if hand.get("ok"):
                        run.handoffs.append(str(hand.get("id") or ""))
                    result = {**result, "dispatch_handoff": hand}
            if secretary_note:
                result = {**result, "秘书": secretary_note}
            # 耳朵一直开着：这一步做完先听一次新消息与板项，把它并进这一步的结果里
            # （并进结果而不是只并进 transcript：台账与会话记录要能看到"他当时听到了什么"）。
            # `step=step`：板项标 seen 时要写"在第几步读的"（业主 A3 的判据靠它配对）。
            heard = self._hear(step=step)
            board_this_step = any("板" == str(k) for h in heard for k in h) if heard else False
            if board_this_step or (step == 0 and board_ids):
                # 这一步读到了板项 ⇒ 顺带把"哪几项可以退役了"报给父（只报；写盘在 S1k）。
                note = self._retire_ready_note()
                if note:
                    result = {**result, **note}
            if heard:
                result = {**result, "新消息": heard}
                inbound_note = self._inbound_hook(heard)
                if inbound_note:
                    result = {**result, "秘书加工": inbound_note}
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
            # 「同一条路 + 同一类读数」的连击（D31）：键里带的是"目标 + 主题 + 结论类"，
            # 参数里改掉的那一处不参与 —— 见 `_stall_key` 的真机理由。
            stall_key = _stall_key(shape, payload, result)
            stalled = stalled + 1 if (stall_key and stall_key == prev_stall) else 1
            prev_stall = stall_key
            # ---- 插话读数（`draft/39` §3.11 二 D07 第 3 条）：谁在第几步收到、有没有改变做法。
            self._record_interjection_effect(run, pending_interjections, step=step,
                                             shape=shape, payload=payload)
            pending_interjections = None
            run.same_call_max = max(run.same_call_max, same_call)
            run.dead_loop_max = max(run.dead_loop_max, dead)
            run.stalled_max = max(run.stalled_max, stalled if stall_key else 0)
            # 两档分开报（裁定 10丙）：提醒过几次是读数，"因此停了没有"由 `dead_loop_stopped` 说。
            run.dead_loop_nudges = nudged_calls
            run.stalled_nudges = nudged_stalls
            run.counters_reset_at = counters_reset_at
            remarks: list[str] = []
            if same_call == self.dead_loop_nudge:
                # 点名（不改结论、不停循环）：提醒写进这一步的结果里 ——
                # `_step_line` 读的就是它，于是"当时那一份"与"续跑重建那一份"逐字一致。
                nudged_calls += 1
                remarks.append(_dead_loop_line(
                    streak=same_call, same_reading=dead, limit=self.max_dead_loop,
                    what=_call_brief(shape, payload)))
            if stall_key and stalled in (self.stall_nudge, self.stall_alert):
                # 同一条路 + 同一类读数（D31）：参数改了不算换做法。这一条只提醒、不判停。
                nudged_stalls += 1
                remarks.append(_stall_line(streak=stalled, alert=self.stall_alert,
                                           what=_call_brief(shape, payload)))
            if remarks:
                result = {**result, "框架提醒": " ".join(remarks)}
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
            # 12-A=乙：思维链原样带回去。进消息与进事件的是同一份文本
            # （`_recorded_reasoning` 走的截断口径与落档一致）—— 于是"当时那份序列"
            # 与"从事件重建的那份序列"逐条相等（`resume_messages` 的判据靠这一条成立），
            # 而"这段被截过"这件事本身写在文本里（不静默截断）。
            thought = _recorded_reasoning(call.reasoning)
            event: dict[str, Any] = {
                "kind": "agent_step", "role": self.role, "index": step, "shape": shape,
                "payload": dict(payload), "result": dict(step_obj.result),
                # S-B：这一步作为"节点"的估价（压力门的输入）。它与 `result` 一起落盘，
                # 于是"当时那一段历史值多少 token"事后可复核（不必重算，也不会因为
                # 观测层的口径改了就与当时对不上）。
                "heuristic_tokens": step_node_tokens(step, payload, result),
            }
            if thought:
                event["reasoning"] = thought
            SS.append(self.session_root, event, sid=self.sid)
            # S-C（裁定 5甲）：这一笔进消息序列 —— assistant（它要求了什么，
            # 结构化一份 `tool_calls`）+ tool（框架给了什么，`tool_call_id` 配对）。
            # 渲染回文本与改前 `_step_line` 逐字相同（`_spoken_half`/`_result_half` 是
            # 那两个"半句"的唯一拼法，`_step_line` 也由它们拼出来）。
            messages.append(assistant_message(step, payload, name=shape,
                                              content=_spoken_half(step, payload),
                                              reasoning=thought))
            messages.append(tool_message(step, _result_half(result), name=shape))
            # ---- 原地打转：同调用 + 同读数连着到上限 ⇒ 这一趟收在这里（不再是"步数用尽"）
            #
            # 为什么停下来是"如实"而不是"失败"：这一步确实做了（台账与会话记录里都有），
            # 只是它没有产生新事实 —— `no_progress_limit` 这个名字说的就是这件事。
            # 为什么不继续问模型：前面已经在第 `dead_loop_nudge` 次点过名，
            # 它连着又重复了 `max_dead_loop - dead_loop_nudge` 次同样的调用 ——
            # 剩下的步数买不到新读数，只会买更多同样的调用。
            if dead >= self.max_dead_loop:
                run.stop_reason = "no_progress_limit"
                run.dead_loop_stopped = True
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
            # 到不了这里（上面的 `for` 走的是无限计数器，裁定 12-K：不设步数硬闸）。
            # 留着这一支只为"万一有人把计数器换成有限 range"时不静默：见下面的判据。
            run.stop_reason = "no_progress_limit"

        run.spend = self.seam.spend.to_dict()
        run.elapsed_sec = time.monotonic() - t0
        run.messages = list(messages)
        run.transcript = render_messages(messages)
        # 委托做完 ⇒ 进度计数清零（裁定 12-F 逐字："每做完一个委托清一次"）。
        # 这一次清零在读数上留下 `counters_reset_at`（= 收工那一步），于是"上一笔账
        # 到哪结束"可复核；下一个委托开始时循环头会再清一次（两句合起来才是那个边界）。
        prev_key, prev_reading, prev_stall = "", "", ""
        same_call, stalled = 0, 0
        run.counters_reset_at = max(run.counters_reset_at, len(run.steps))
        # 正常收工就注销进程登记（被杀时它自然留在盘上，`stopctl.live_pids` 会把死 pid 滤掉）。
        try:
            from . import stopctl as _sc

            _sc.unregister_pid(self.session_root, self.role, self.sid)
        except Exception:  # noqa: BLE001 —— 注销失败不影响这一趟的产出
            pass
        # 秘书随这一趟一起收（S1m："与它同生同死"的第二半）：注销存活标记，读数进 notes。
        # 失败不带走产出，但要留痕（"它还没收"与"收过了"必须分得开）。
        if self.secretary is not None:
            try:
                closed = self.secretary.close()
                if not closed.get("closed"):
                    run.notes.append(f"秘书存活标记没注销：{closed.get('reason')}")
            except Exception as exc:  # noqa: BLE001
                run.notes.append(f"秘书收尾失败：{type(exc).__name__}: {exc}")
        # ---- 报告强制（业主 2026-10-08 T17：「A-H每个任务跑完都要往回报告的」）
        #
        # 放在 `agent_run_end` 之前：这样那句读数会跟着这一条事件落盘（D81 给
        # `agent_run_end` 补的 `notes` 那一格），事后读得到"这一趟有没有补通报"。
        settlement_note = self._emit_settlement(run)
        if settlement_note:
            run.notes.append(settlement_note)
        # ---- 状态报告强制（`draft/38` §7 第三组判据的那一格；模型没调就框架补落）
        # 同样放在 `agent_run_end` 之前：那句读数要跟着这一条事件落盘，事后读得到
        # "这一格是模型落的还是框架补的"。
        status_note = self._ensure_status_report(run)
        if status_note:
            run.notes.append(status_note)
        # ---- S-G（裁定 15）：收工那一刻读一次"我名下还有几条在飞"（读数，不拦）。
        #
        # 为什么只落读数、绝不放行/否决：裁定 1 逐字是"收工由 M 判"，裁定 15 又要求
        # "超时/还有人在飞 ⇒ 记读数继续收工"。所以这一格的产物是一句 note（它跟着
        # `agent_run_end` 一起落盘），不是一个打断。代价（父的交付可能没有孩子的结论）
        # 由这句话本身说出来 —— 那是这一格存在的全部意义。
        flight_note = self._in_flight_reading()
        if flight_note:
            run.notes.append(flight_note)
        SS.append(self.session_root, {
            "kind": "agent_run_end", "role": self.role, "stop_reason": run.stop_reason,            "steps": len(run.steps), "summons": run.summons, "messages": run.messages_sent,
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
            # 交接留痕的两个读数（`draft/39` §6.6 F3）：设计里写的是"这一趟的
            # `agent_run_end` 里落 `handoff_id`"，而 E5 真机读数时发现这两个字段
            # 没进事件 ⇒ 只能自己扫账本，批⑥ 的状态报告同理。
            "handoffs": list(run.handoffs), "notify_rejections": run.notify_rejections,
            # ---- 收工那一步的留痕（2026-10-08 的三处缺口之一；见 `LoopRun.final_payload`）
            #
            # 这三个键一齐落，是因为它们此前只活在内存里：`final` / `final_sha256` 在
            # 上面那两行，而 `evidence`（模型自报的证据 id）、`notes`（这一趟的框架读数，
            # 含"收工没有可用 notify 表"那句）与收工那一步的原始载荷（含模型填的 `notify`）
            # 在盘上一条都没有。判据：
            # `tests/test_llm_work_reaches_the_ledger.py::test_the_closing_notify_and_conclusion_reach_the_ledger`
            # （盘上找得到 notify 与结论）+ 同文件里"不填就没有 notify 键"的负控。
            "evidence": list(run.evidence), "notes": list(run.notes),
            # `_for_record` 与 `agent_step` 落档同一把尺（单字段 2000 字上限）：
            # 两处存的是同一件事，截断口径不该有两份。
            "final_payload": dict(run.final_payload),
        }, sid=self.sid)
        return run

    # -------------------------------------------------------------- 执行
    def _notify_children_of_stop(self, stop_reason: str) -> str:
        """停止沿边下发（S4-b）：把通知交给 conductor，并回报一句读数（空串 = 没话说）。

        三态照旧：读不成 / 通知不成都不打断收工（这一趟已经要停了），
        但都要留下一句人读得懂的话 —— 静默失败在这里最贵（"通知了"与"没人被通知"
        在事后分不开，而"听不到叫停的子孙会继续烧钱跑实验"）。
        """
        cond = self.conductor
        mine = str(self.my_task_id or "")
        if cond is None or not mine:
            return ""
        look = getattr(cond, "notify_children_of_stop", None)
        if not callable(look):
            return ""
        try:
            got = look(mine, reason=stop_reason, by=self.role)
        except Exception as exc:  # noqa: BLE001 —— 下发失败不许带走收工
            return f"停止通知没下发成：{type(exc).__name__}: {exc}（这一趟照常收工）"
        if not got.get("checked"):
            return f"停止通知没下发成：{got.get('reason')}"
        notified = list(got.get("notified") or [])
        skipped = list(got.get("skipped") or [])
        if not notified and not skipped:
            return str(got.get("note") or "停止通知：没有边要通知")
        return (f"停止通知沿边下发：{len(notified)} 条边"
                + (f"（已通知过 {len(skipped)} 条）" if skipped else "")
                + "；ack 才算传达到")

    def _ack_stop_notice(self, item_id: str, step: int) -> str:
        """这一趟读到的停止通知：替它 ack（返回一句读数，空串 = 不是通知项/没成）。

        只对停止通知动手，判据是 `input_key` 以 `stop-notice@` 开头
        （`Conductor.notify_children_of_stop` 开的那一种）。别的 `notice`/`expects=ack` 项
        —— 子代理的交差通报、`message` 项 —— 不许在这里被 ack：它们是"要人处置的事"，
        框架替它 ack 会让"父还没看"这件事实消失（实测：`test_retire_ready_is_a_reading_not_an_action`
        与 `test_children_and_parent_are_visible` 当场变红，正是这条边界）。

        `ack` 走 `close_item(close="acked")` —— 于是"通知了"与"通知到了"
        在 `stop_edge_readings` 里分得开（`acked_at` 非空才算传到）。
        """
        cond = self.conductor
        if cond is None:
            return ""
        look = getattr(cond, "_task", None)
        if not callable(look):
            return ""
        try:
            row = look(item_id) or {}
        except Exception:  # noqa: BLE001 —— 读不成就不 ack（宁可不 ack，不许乱 ack）
            return ""
        if str(row.get("kind") or "") != "notice" or str(row.get("expects") or "") != "ack":
            return ""
        if not str(row.get("input_key") or "").startswith("stop-notice@"):
            return ""
        if str(row.get("item_state") or "") == "done":
            return ""
        close = getattr(cond, "close_item", None)
        if not callable(close):
            return ""
        try:
            state, why = close(item_id, close="acked",
                               by_task_id=str(self.my_task_id or ""))
        except Exception as exc:  # noqa: BLE001 —— ack 失败留一句话，不打断
            return f"停止通知 {item_id} 的 ack 没记上：{type(exc).__name__}: {exc}"
        if not state:
            return f"停止通知 {item_id} 的 ack 没记上：{why}"
        # ack 的时刻落在父那一行的落痕里（`item_close` 是受控词表，装不下时间戳）
        note = getattr(cond, "note_stop_ack", None)
        parent = str(getattr(self, "parent_task_id", "") or "")
        if callable(note) and parent and str(self.my_task_id or ""):
            try:
                note(parent, str(self.my_task_id), at=S.now_iso())
            except Exception as exc:  # noqa: BLE001 —— 落痕失败不改"ack 过了"这个事实
                return (f"停止通知 {item_id} 已 ack（第 {step} 步读到），"
                        f"但 ack 时刻没落痕：{type(exc).__name__}: {exc}")
        return f"停止通知 {item_id} 已 ack（第 {step} 步读到）"

    def _note_blocked_declaration(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """子代理在收工那句话里声明"我在等上级指导" ⇒ 落痕到父那一行（业主 2026-10-09）。

        业主对 `blocked` 的窄定义（第四句 + 第六句，逐字）：

        > 「上述层层上报困难也会带来一种停机状态，即所有活跃子代理的状态都是 blocked」
        > 「如果被委托的任务单纯是在职责之外，则应该将自己能力内的做完后上报情况就 over 了；
        > 如果是需要请示上级指导任务实施细则，才会 block」

        ⇒ 两件事必须分得开：

        - 职责之外：做完自己能力内的、上报情况、正常收工（`final`）—— 这条路上不写
          `blocked`（机器判据：那一条上报会让 `escalation_gaps` 归零，不需要 blocked）；
        - 等上级指导实施细则：才是 `blocked` —— 载体是
          `{"final": "...", "blocked": {"what": …, "why": …, "needs": "请上级定 X"}}`，
          其中 `needs`（要请示什么）必填：说不出要请示什么，那多半不是 blocked，
          而是"职责之外"那一档。

        只在给了 `blocked` 的时候处理（没声明 ⇒ 什么都不做，老行为逐字不变）。
        三态都如实报：没有父 / 没有 conductor / 落痕失败 ⇒ 一句读数，不打断收工。
        """
        decl = payload.get("blocked")
        if not isinstance(decl, Mapping):
            return {}
        what = str(decl.get("what") or "").strip()
        why = str(decl.get("why") or "").strip()
        needs = str(decl.get("needs") or "").strip()
        if not needs:
            # 「说不出要请示什么 ⇒ 不是 blocked」（业主第六句）：只记读数、不落痕。
            return {"declared": True, "recorded": False, "what": what, "why": why,
                    "problem": ("blocked 少了 `needs`（要请示上级什么）：说不出要请示什么，"
                                "多半不是『等指导』而是『职责之外』—— 那一档应当把自己能力内的"
                                "做完、上报情况、正常收工，不写 blocked")}
        if not why:
            return {"declared": True, "recorded": False, "what": what, "needs": needs,
                    "problem": "blocked 少了 `why`（被什么卡住）⇒ 不落痕（不许静默卡住）"}
        cond = self.conductor
        parent = str(getattr(self, "parent_task_id", "") or "")
        mine = str(self.my_task_id or "")
        if cond is None or not parent or not mine:
            return {"declared": True, "recorded": False, "what": what, "why": why,
                    "needs": needs,
                    "problem": ("没有父/conductor ⇒ 这一笔没落到盘上"
                                "（顶层发起的那一趟本来就该向用户请示）")}
        look = getattr(cond, "note_blocked", None)
        if not callable(look):
            return {"declared": True, "recorded": False, "what": what, "why": why,
                    "needs": needs, "problem": "这个主控没有 `note_blocked` ⇒ 没落痕"}
        try:
            mark, problem = look(parent, mine, what=what, why=why)
        except Exception as exc:  # noqa: BLE001 —— 落痕失败不许带走收工
            return {"declared": True, "recorded": False, "what": what, "why": why,
                    "needs": needs, "problem": f"{type(exc).__name__}: {exc}"}
        out: dict[str, Any] = {"declared": True, "recorded": bool(mark), "what": what,
                               "why": why, "needs": needs}
        if problem:
            out["problem"] = problem
        return out

    def _stop_applies(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """盘上这把停机开关管不管我（S4，`draft/90` E7 / `draft/84` §2.2）。

        返回 `{"stop","remove","why"}`：

        | 开关 | 我 | 结论 |
        |---|---|---|
        | 全工作区（没有 `root_task_id`） | 谁 | 停；读到的第一个撤掉它（老行为逐字不变） |
        | 子树（有 `root_task_id`） | 我在那一支里、我就是那一支的根 | 停，并且由我撤（`remove=True`） |
        | 子树 | 我在那一支里、是成员 | 停，但不撤（`remove=False`）—— 同支别的循环还要读到它 |
        | 子树 | 我不在那一支里 | 不停（"停 D 那一支"不许停到 E 那一支） |
        | 子树 | 判不了（台账读不成 / 我没编号） | 不停 + 一句读数（判不了 ≠ 适用） |

        为什么"不撤"这一档必须存在：一次性开关的语义（§140）是为"全工作区"设计的；
        子树开关要一支上多个循环各自读到，谁先读到谁撤就会让后面的人静默不停
        —— 那与 §140 那个 bug 是同一族，只是方向反过来。撤的责任落在那一支的根
        （通常就是叫停的人自己那一趟）。
        """
        try:
            from . import stopctl
        except Exception:  # noqa: BLE001 —— 模块都导不进来 ⇒ 判不了
            return {"stop": False, "remove": False, "why": "stopctl 没导进来 ⇒ 判不了"}
        scope = stopctl.stop_scope(state)
        if not scope.get("checked"):
            return {"stop": False, "remove": False,
                    "why": f"作用面判不了（{scope.get('reason')}）⇒ 不停（判不了 ≠ 适用）"}
        if scope["scope"] != "subtree":
            return {"stop": True, "remove": True, "why": ""}
        root_tid = str(scope["root_task_id"])
        cond = self.conductor
        mine = str(self.my_task_id or "")
        if cond is None or not mine:
            return {"stop": False, "remove": False,
                    "why": ("这一趟没有主控句柄或没有台账号 ⇒ 判不了我在不在"
                            f"{root_tid} 那一支里（不停）")}
        look = getattr(cond, "inside_subtree", None)
        if not callable(look):
            return {"stop": False, "remove": False,
                    "why": "这个主控没有 `inside_subtree` ⇒ 判不了（不停）"}
        try:
            got = look(root_tid, mine)
        except Exception as exc:  # noqa: BLE001 —— 读不成 ≠ 在里面
            return {"stop": False, "remove": False,
                    "why": f"判我在不在 {root_tid} 那一支里时出错（{type(exc).__name__}）⇒ 不停"}
        if not got.get("checked"):
            return {"stop": False, "remove": False,
                    "why": f"判不了我在不在 {root_tid} 那一支里（{got.get('reason')}）⇒ 不停"}
        if not got.get("inside"):
            return {"stop": False, "remove": False,
                    "why": f"这把开关只管 {root_tid} 那一支，我不在那一支里"}
        return {"stop": True, "remove": mine == root_tid, "why": ""}

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
        # ---- S-H（裁定 14）：父叫停某一个孩子当前那一轮的那一份信号。
        #
        # 为什么排在全局开关之前：工作区那把开关说的是"所有人停"，而这一份只针对我 ——
        # 先看我自己的那一份，"谁停了我"这个读数才准确（全局开关的理由码会是 user/stop_file）。
        # 一次性信号：读到即消费（与 §140 那把开关同一条纪律），排队消息一个字节都不动。
        if str(self.my_task_id or ""):
            try:
                from . import stopctl as _SC

                sig = _SC.read_interrupt(self.session_root, self.my_task_id)
                if sig is not None:
                    verdict = _SC.interrupt_applies(sig, self.my_task_id)
                    if verdict.get("checked") and verdict.get("applies"):
                        _SC.consume_interrupt(self.session_root, self.my_task_id, sid=self.sid)
                        return str(sig.get("reason") or _SC.INTERRUPT_REASON)
                    if not verdict.get("checked"):
                        run.notes.append(f"有一份中断信号，但作用面判不了 ⇒ 不停"
                                         f"（判不了 ≠ 适用：{verdict.get('reason')}）")
            except Exception as exc:  # noqa: BLE001 —— 读不成不是"没人叫停"，要留读数
                run.notes.append(f"中断信号没读成（{type(exc).__name__}: {exc}）⇒ 按没叫停继续")
        if self.stop_file and Path(self.stop_file).exists():
            # 显式给的路径也按同一套"停一次就消费"办（CLI 传的就是工作区那把开关）。
            try:
                from . import stopctl

                state = stopctl.read_stop(self.session_root, explicit=self.stop_file)
            except Exception:  # noqa: BLE001 —— 读不到开关不是"用户叫停"，如实不停
                state = None
            if state is not None:
                verdict = self._stop_applies(state)
                if not verdict["stop"]:
                    run.notes.append(f"停机开关在盘上，但{verdict['why']}")
                    return ""
                reason = "force_stop" if bool(state.get("force")) else "stop_file"
                try:
                    from . import stopctl

                    stopctl.consume_stop(self.session_root, sid=self.sid, level=reason,
                                         explicit=self.stop_file, remove=verdict["remove"])
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
            verdict = self._stop_applies(state)
            if not verdict["stop"]:
                run.notes.append(f"停机开关在盘上，但{verdict['why']}")
                return ""
            reason = "force_stop" if bool(state.get("force")) else "stop_file"
            try:
                from . import stopctl

                stopctl.consume_stop(self.session_root, sid=self.sid, level=reason,
                                     remove=verdict["remove"])
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

    def _notify_bounce(self, run: LoopRun, step: int, shape: str,
                       payload: Mapping[str, Any], data: Mapping[str, Any],
                       problem: str) -> tuple[str, bool]:
        """记录一次"notify 打回"；返回 `(写进 briefing 的那一行, 是否该就此收工)`。

        打回的记录形态与"形状说对了、值写错了"那一档一致（`invalid` 步 + `shape_recognized`）：
        它在台账上要与"说了个认不出的形状"分得开 —— 前者交回一次就能改对，后者是协议漂移。
        """
        run.notify_rejections += 1
        run.bad_args += 1
        run.bad_args_streak += 1
        help_text = _notify_help(problem, attempt=run.notify_rejections,
                                 what=("收工那一句（final）" if shape == "final"
                                       else f"派活那一句（{shape}）"))
        bad_result = {"problem": help_text, "shape_recognized": shape,
                      "notify_rejections": run.notify_rejections,
                      "raw_reply": _clip(json.dumps(data, ensure_ascii=False), 600)}
        run.steps.append(LoopStep(step, "invalid", payload, bad_result, problem=help_text))
        SS.append(self.session_root, {
            "kind": "agent_step", "role": self.role, "index": step,
            "shape": "invalid", "payload": dict(payload), "result": dict(bad_result),
        }, sid=self.sid)
        return _payload_line(step, shape, help_text), run.notify_rejections >= self.max_notify_rejections

    def _dispatch_notify(self, payload: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
        """主控派活时的留痕载荷：返回 `(问题, 交给 `_do_handoff` 的载荷 或 None)`。

        两种来源（`draft/39` §6.4 四.1 的裁定；L-05e 之后都不再打回）：

        1. 模型填了 `notify` ⇒ 用它（`note` 标成"模型填的 notify"）；
        2. 没填、或填的形状不能用 ⇒ 框架据派活本身派生一份
           （`note` 标成"框架据派活派生"）：写的是"谁派了谁做什么、参数是什么、为什么"
           ——这些是框架手上已有的事实，不是替模型编它想说的话。

        为什么形状不对也退回派生（L-05e）：旧口径是"填错就打回、那一次派活不发生"，
        但真机 5269 个 `agent_step` 里这道闸门一次都没触发（`no_notify` 收场 0 次），
        而"因为一张表的格式让一次真的要发生的派活停下来"正是 #1 的形态。
        现在：派活照常发生，形状问题落进这一步的读数（`run.notes`），留痕退回派生那一份
        —— "谁是派生、谁是执笔"两个标记仍然分得开（执笔在本角色的秘书手里）。

        `to` 的缺省是被派的那个角色（多目标 ⇒ `ALL`）："给谁派了活"与"手稿发给谁"
        因此不会因为要填两遍而分家。
        """
        notify = payload.get("notify")
        targets = self._dispatch_targets(payload)
        if notify is None:
            return "", self._derived_dispatch_notify(payload, targets)
        if not isinstance(notify, Mapping):
            return notify_shape_problem(notify), self._derived_dispatch_notify(payload, targets)
        patched = dict(notify)
        if not str(patched.get("to") or "").strip():
            patched["to"] = targets[0] if len(targets) == 1 else "ALL"
        problem = notify_shape_problem(patched)
        if problem:
            return problem, self._derived_dispatch_notify(payload, targets)
        from . import manuscripts as MS

        for ref in list(patched.get("refs") or []):
            why = MS.ref_problem(self.session_root, str(ref))
            if why:
                return (f"notify.refs 里的 {ref!r} 立不住：{why}",
                        self._derived_dispatch_notify(payload, targets))
        clean = clean_notify(patched)
        clean["note"] = "留痕来源：模型填的 notify"
        return "", clean

    def _derived_dispatch_notify(self, payload: Mapping[str, Any],
                                 targets: list[str]) -> dict[str, Any]:
        """没填 `notify` 时，从派活本身派生那一行留痕（事实是什么就写什么）。"""
        lines = ["## 派了什么活", ""]
        for t in (payload.get("targets") or [payload]) if "targets" in payload else [payload]:
            if not isinstance(t, Mapping):
                continue
            lines.append(f"- {t.get('role')}.{t.get('action')}：参数 "
                         f"`{json.dumps(dict(t.get('params') or {}), ensure_ascii=False)}`"
                         + (f"（instance={t.get('instance')}）" if t.get("instance") else ""))
        why = str(payload.get("why") or "").strip()
        if why:
            lines += ["", "## 为什么派它", why]
        lines += ["", "## 这一行是怎么来的",
                  "模型这一句派活没有填 `notify` 表 ⇒ 框架据派活本身派生（"
                  "谁派了谁做什么、参数、为什么），内容全部取自这一句派活；"
                  "执笔的是本角色自己的秘书（智能体侧只保留『查』，`draft/55` §3.2）。"]
        what = ", ".join(f"{t.get('role')}.{t.get('action')}"
                         for t in ((payload.get("targets") or []) if "targets" in payload
                                   else [payload]) if isinstance(t, Mapping))
        return {"to": targets[0] if len(targets) == 1 else "ALL",
                "summary": f"派活：{what or '（没有目标）'}",
                "body": "\n".join(lines) + "\n", "refs": [], "why": why,
                "note": ("留痕来源：框架据派活派生（模型这一句没填 notify）；"
                         "执笔=本角色的秘书")}

    @staticmethod
    def _dispatch_targets(payload: Mapping[str, Any]) -> list[str]:
        """这一句派活派给了谁（`summon` 一个、`summon_many` 一批）。"""
        if "targets" in payload:
            return [str(t.get("role") or "") for t in payload.get("targets") or []
                    if isinstance(t, Mapping)]
        return [str(payload.get("role") or "")]

    def notify_reading(self, payload: Mapping[str, Any]) -> str:
        """收工那一句的 `notify` 表读得成不成（空串 = 读成了；非空 = 那句话就是读数理由）。

        名字已按主控 2026-10-07 的裁定改掉：`_notify_gate` → `notify_reading`（旧名在说谎 ——
        它不打回；本仓的顶级教训之一是"名字在说一件事、断言在说另一件"）。
        改名时全树一共 8 处引用，其中 `tests/test_agent_prompts.py` 里还有 2 处注释提到旧名，
        刻意留到那条线（正在改该文件）收工后再改，以免两个写者撞车 —— 已登记在主控记录里。

        三条判断（顺序就是"先看该不该填，再看填得对不对"）：

        1. 主控 M 免填：它的 `final` 是给用户的回复（用户 2026-10-05 原话：
           "M 向 Agent 派活时一样强制留痕，向用户回复时不搞这种操作"）；
        2. 没填 / 填错形状 ⇒ 这一格没有可用读数（形状判据只有一份：`notify_shape_problem`）；
        3. 填了但 refs 悬空 ⇒ 同一格也没有可用读数（`manuscripts.ref_problem` 是写入期
           同一份判据：让它在"填表"这一步就被指出来，而不是写手稿时才炸）。

        返回空串只有一个含义：读成了、可以照着写手稿。
        """
        if self.role == S.CONDUCTOR_ROLE:
            return ""
        notify = payload.get("notify")
        if notify is None:
            return (f"没有 notify 表（`final` 要给一个 notify 对象，字段：{list(NOTIFY_FIELDS)}）"
                    "—— 除主控外每个角色收工都要留一份交接手稿，这是用户点名的强制项")
        problem = notify_shape_problem(notify)
        if problem:
            return problem
        from . import manuscripts as MS

        for ref in list(notify.get("refs") or []):
            why = MS.ref_problem(self.session_root, str(ref))
            if why:
                return f"notify.refs 里的 {ref!r} 立不住：{why}"
        return ""

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
        if shape == "retire":
            return self._do_retire(payload)
        if shape == "roster":
            return self._do_roster(payload)
        if shape == "interrupt":
            return self._do_interrupt(payload)
        return self._do_message(payload)

    def _do_interrupt(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """`{"interrupt": {"name": "D1"}}` —— 停某一个子代理当前那一轮（S-H，裁定 14）。

        搬运来源与四条语义见 `Conductor.interrupt_child`；这一层只做三件事：

        1. 指称：只用名册名（与 `retire` 同一条纪律 —— 台账号不是父子之间的指称），
           越界的名字（不在我名下）当面拒绝；
        2. 转发授权：谁有资格停谁由 `Conductor.interrupt_child` 判（精确活着的祖先、
           不许停自己、判不了就拒）—— 这一层不重写第二份授权判据；
        3. 留痕：落一条会话事件（谁停了谁、受理了没有、什么码），因为信号本身是
           "一个目标一份文件"，不落事件的话"父叫停过"在会话记录里看不见。
        """
        name = str(payload.get("name") or "").strip()
        if not name:
            return {"ok": False, "accepted": False, "code": "bad_request",
                    "why": ["要停谁：`name` 是名册名，不能空"]}
        if self.secretary is None or self.conductor is None:
            return {"ok": False, "accepted": False, "code": "no_secretary", "name": name,
                    "why": ["这一趟没有秘书/conductor ⇒ 名册不在手上，停不了"]}
        tid, problem = self.secretary.resolve_down(owner=self.my_task_id, name=name)
        if problem:
            return {"ok": False, "accepted": False, "code": "not_mine", "name": name,
                    "why": [f"{name} 不在我名下的名册里（{problem}）⇒ 越界的不许停"]}
        try:
            got = self.conductor.interrupt_child(parent_task_id=self.my_task_id,
                                                child_task_id=tid, by=self.role)
        except Exception as exc:  # noqa: BLE001 —— 叫停没跑成要如实报（不许当"停过了"）
            got = {"ok": False, "accepted": False, "code": "error", "why":
                   [f"叫停没跑成：{type(exc).__name__}: {exc}"]}
        if not isinstance(got, dict):
            got = {"ok": False, "accepted": False, "code": "bad_reading",
                   "why": ["叫停读数不是对象"]}
        got.setdefault("name", name)
        got["target_task_id"] = str(got.get("target_task_id") or tid)
        try:
            SS.append(self.session_root, {
                "kind": "agent_interrupt", "role": self.role, "name": name,
                "target_task_id": got["target_task_id"],
                "accepted": bool(got.get("accepted")), "code": str(got.get("code") or ""),
                "no_op": bool(got.get("no_op")),
            }, sid=self.sid)
        except Exception as exc:  # noqa: BLE001 —— 事件落不成不许改变受理结果
            got.setdefault("why", [])
            got["why"] = list(got["why"]) + [f"（留痕没落成：{type(exc).__name__}: {exc}）"]
        return got

    def _do_retire(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """`{"retire": {"name": "A1"}}` —— 父说"A1 退役"，判定与执行都在秘书那一侧。

        这一层只做转发与留痕（`draft/92` I-11 的"一处实现"）：三分支的判定在
        `Secretary.retire`，它自己会去读台账、读手稿、写名册/对照表/销号名单。
        没有秘书（裸构造的 `AgentLoop`）⇒ 如实拒绝，不许当"退役成功"。
        """
        name = str(payload.get("name") or "").strip()
        if not name:
            return {"ok": False, "action": "refused", "why": ["要退谁：`name` 是名册名，不能空"]}
        if self.secretary is None:
            return {"ok": False, "action": "refused",
                    "why": ["这一趟没有秘书（裸构造的 AgentLoop）⇒ 名册不在手上，退不了"]}
        try:
            got = self.secretary.retire(owner=self.my_task_id, name=name,
                                        by_task_id=self.my_task_id)
        except Exception as exc:  # noqa: BLE001 —— 退役失败要如实报（不许当"退过了"）
            return {"ok": False, "action": "refused",
                    "why": [f"退役没跑成：{type(exc).__name__}: {exc}"]}
        if not isinstance(got, dict):
            return {"ok": False, "action": "refused", "why": ["退役读数不是对象"]}
        got.setdefault("name", name)
        return got

    def _do_roster(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """`{"roster": {"of": "self"}}` —— 查名册（只读，业主："代理的查自己调用工具看"）。

        `of` 缺省 = 自己名下的名册；给了名册名 ⇒ 先译码（我名下 → 我父名册），再查它的名册
        （退役第②支要的那一步："A1 还在干什么活"）。可见面（`draft/92` I-13）：
        只有这三种目标 —— 我自己的、我名下的子代理的；兄弟的看不见（越界受控拒绝）。
        """
        if self.secretary is None:
            return {"checked": False, "rows": [], "reason": "这一趟没有秘书 ⇒ 名册不在手上"}
        want = str(payload.get("of") or "self").strip()
        # `scope="descendants"`（S-H，裁定 14）：全树（每一行带 `parent`/`depth`）。
        # 缺省仍是"下一层"（老行为逐字不变）；不认的取值当面拒绝 —— 静默折回缺省
        # 会让"我要全树"与"我要下一层"这两个请求得到同一个答案。
        scope = str(payload.get("scope") or "self").strip() or "self"
        if scope not in ("self", "descendants"):
            return {"checked": False, "rows": [], "more": 0, "scope": scope,
                    "reason": f"scope={scope!r} 不认（只有 self / descendants）"}
        if want in ("", "self", "自己"):
            return self.secretary.roster_view(owner=self.my_task_id, scope=scope)
        tid, problem = self.secretary.resolve_down(owner=self.my_task_id, name=want)
        if problem:
            return {"checked": False, "rows": [], "more": 0, "scope": scope,
                    "reason": f"{want} 不在我名下的名册里（{problem}）⇒ 越界的不许查"}
        return self.secretary.roster_view(owner=tid, scope=scope)

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
        # ---- 读写面（S1n-b，业主 T23）：子代理只能读写父切割给它的面。
        #
        # 判据在这一层（不是工具层）：`self.surface` 是这一趟的面（绝对路径），
        # 由 `LlmBackend.call` 从父的名册里读出来传进来；没设 ⇒ 今天的行为一个字节不变。
        # 拦的是 `fs.*` 的路径参数：一切都 `resolve()` 之后判"在不在面内"
        # （与 `fs_tools._resolve` 同一条判据：不比字符串里的 `..`，只比解析结果）。
        refusal = self._surface_refusal(name, args)
        if refusal:
            out = {"tool": name, "ok": False, "error": refusal,
                   "meta": {"surface": str(self.surface)}}
            if aliased_from:
                out["aliased_from"] = aliased_from
            return out
        tscope: Any = None
        try:
            # S6-b：工具调用也带上"我是谁"（`conductor.broadcast` 的收件人是
            # "我名下的直接子代理"，而工具的形状里没有这一格）。用 `calling_as`
            # 而不是给 conductor 塞属性：同一角色的两个并发实例共享对象。
            from .conductor import calling_as

            # ---- S-E（裁定 13甲 / 12-D / 12-G）：逐工具超时只在这一层装钟。
            #
            # 为什么不改 `tools/base.py`（禁改区）：截止是协作式的 ContextVar
            # （`tool_timeout` 模块），处理函数在检查点调 `raise_if_timed_out()`；
            # 循环在调 `registry.call` 前后设/清。没声明限时的工具一个字节都不变。
            from . import tool_timeout as TT

            tscope = TT.tool_deadline(name)
            with tscope:
                with calling_as(str(self.my_task_id or ""), self.role):
                    res = self.registry.call(name, role=self.role, **args)
        except Exception as exc:  # 工具层抛错也要变成"模型看得见的结果"
            self._note_tool_deadline(tscope)
            out = {"tool": name, "ok": False, "error": f"{type(exc).__name__}: {exc}",
                   **({"aliased_from": aliased_from} if aliased_from else {})}
            return out
        # 超时的两半分开报（裁定 12-E）：结果逐字节相同（耗时只在侧信道），
        # 而"工具到底停住没有"落一条会话事件（`observed` / `deadline_passed_unobserved`）。
        self._note_tool_deadline(tscope)
        if tscope.observed_timed_out:
            run = tscope.run
            assert run is not None      # observed_timed_out 只在装了钟时为真
            out = TT.timeout_result(name, run.code, run.timeout_ms)
            if aliased_from:
                out["aliased_from"] = aliased_from
            return out
        out = {"tool": name, "ok": bool(res.ok), "data": res.data,
               "error": res.error or "", "meta": dict(res.meta or {})}
        if aliased_from:
            out["aliased_from"] = aliased_from
        # `draft/97` §15.4 的载体那一半：工具把"哪几条定义待补"报回来 ⇒ 这一步就地
        # 向直接父发一条报文（父通常就是 A，原文在它手里）。不这样做的话，"定义待补"
        # 只是台账上的一个状态，而 §14.13 的正控要求"A 那边真的有人被找"。
        pending_defs = (res.data or {}).get("pending_definitions") if isinstance(res.data, dict) else None
        if pending_defs:
            try:
                ask = self.ask_parent_for_definitions(pending_defs)
            except Exception as exc:  # noqa: BLE001 —— 报文发不出去也要在读数里看得见
                ask = {"checked": False, "reason": f"发报文时异常（{type(exc).__name__}: {exc}）"}
            out["definition_ask"] = ask
            out["meta"]["definition_ask"] = dict(ask)
        return out

    def _note_tool_deadline(self, scope: Any) -> None:
        """把这一口钟的读数落到侧信道（会话事件）—— 耗时不进结果（裁定 12-E）。

        为什么耗时必须是侧信道：`_call_reading` 把整条结果哈希进"原地打转"的连击键，
        而结果里带上"这次等了多久"会让两次超时产生不同的读数 ⇒ 判停永远不触发
        （模型可以无限循环在一个超时调用上）。裁定 12-E 逐字选的是"超时结果逐字节相同"。

        为什么只在钟响过时落事件：绝大多数步根本没到点，每一步都落一条会把会话记录淹掉；
        `state` 为空串（没声明 / 没到点）⇒ 一个事件都不落。
        `state` 的两档分开报（三态）：`observed` = 工具真的停在检查点上；
        `deadline_passed_unobserved` = 到点了而工具没看信号（那一档不许替换结果，
        也不许说成"已经停住了"）。
        """
        run = getattr(scope, "run", None)
        if run is None or not run.state:
            return
        try:
            SS.append(self.session_root, {
                "kind": "tool_timeout", "role": self.role, "tool": run.name,
                "state": run.state, "code": run.code, "timeout_ms": run.timeout_ms,
                "elapsed_ms": round(run.elapsed_ms, 1), "note": run.note(),
            }, sid=self.sid)
        except Exception as exc:  # noqa: BLE001 —— 侧信道落不成不许改变这一步的结果
            # 落不成也要留痕（本仓最忌"报告没写成"与"不用报告"长得一样）：走 conductor
            # 的日志口子，没有就退到 stdout —— 但绝不动这一步的结果。
            line = f"[tool_timeout] 工具超时读数没落成（{type(exc).__name__}: {exc}）"
            log = getattr(self.conductor, "_log", None)
            if callable(log):
                log(line)
            else:
                print(line)

    def _surface_refusal(self, name: str, args: Mapping[str, Any]) -> str:
        """这一句工具调用越出读写面了吗？返回拒信（空串 = 放行）。

        口径（业主 T23）：`fs.*` 的路径参数按工作区根解析（与 `fs_tools` 同一基准），
        解析结果必须落在 `self.surface` 里；面内的新文件允许（判的是落在哪儿，
        不是"文件存在不存在"）。没设面（`self.surface == ""`）⇒ 直接放行（老行为不变）。

        三态：面目录不在盘上 ⇒ 拒绝（不许当"整工作区可写"）。

        ## 哪些参数算"路径"：一处口径

        `draft/90` §2 的 E22：先前这里只看 `args["path"]`，而 `fs.move` 的参数叫
        `src`/`dst`（它的 schema 里没有 `path`）⇒ 子代理可以用 `fs.move` 把面外的
        文件搬进自己的面、或把面内的文件搬出去，这一步不被任何判据拦。
        现在参数名从 `secretary.surface_path_args()` 取（默认 `path`，例外逐条登记）
        —— 与秘书的预看读数（`Secretary.surface_fit`）共用同一张表，
        免得出现"预看说越界、硬拦放过去"。

        ## 面是工作区里的一个子目录（过渡语义，为什么）

        今天 `fs.*` 的根焊死在注册表里（`build_registry(workspace_root=…)` 就定死了），
        所以"从面里看 `x.md`"这件事得先有每实例一个注册表（`draft/92` §3.6）——
        那是装配点的改动，另立一批。在那之前这里守的是"路径要写全、且必须落在面内"：
        既挡住越界与别人的面，也不假装"面就是新的根"。

        ## 面的基准 == 执行的基准（D8 / E23 已收口，2026-10-10 校）

        这一段此前写着"已知未收口：`registry_factory` 的装配点未接 ⇒ 检查按面、执行按工作区"。
        那已经不是事实了：`host.py` 装配时把 `backend.registry_factory` 接上，
        子代理那一趟由 `registry_factory(face)` 按面造一个注册表（同一个面复用同一个，
        见下面 `child_registry` 那一段），于是 `fs.*` 的根就是这一趟的面 ——
        本判据的基准（`self.surface`）与执行的基准（`fs` 工具的 root）终于是同一个目录。
        判据：`tests/test_the_surface_is_also_the_tools_root.py`（正控①装配点可调用、
        正控②按面造的注册表 `fs` 根 == 面、负控没有面时共用注册表逐字不变、
        反真空面外仍被 `fs` 自己的沙箱拒）。
        没有面时这里与执行层都退回老行为（路径要写全、且必须落在面内）——
        那一条不是"收口前的将就"，而是"没有面就没有面"的正当语义。
        """
        if not str(self.surface or ""):
            return ""
        from .secretary import surface_path_args

        keys = surface_path_args(name)
        if not keys:
            return ""
        raws = [(k, str(args.get(k) or "")) for k in keys]
        raws = [(k, v) for k, v in raws if v]
        if not raws:
            return ""                     # 没有路径参数（例如 `fs.list` 的缺省根）⇒ 不拦
        try:
            face = Path(str(self.surface)).resolve()
        except Exception as exc:  # noqa: BLE001 —— 读不成 ⇒ 拒（不许放行）
            return f"读写面读不成（{type(exc).__name__}: {exc}）⇒ 这一步不许执行"
        if not face.is_dir():
            return (f"读写面不在盘上（{face}）⇒ 这一步不许执行："
                    "没有面的时候不许当'整工作区可写'（业主 T23）")
        base = Path(str(self.workspace_root or ".")).resolve()
        refusals: list[str] = []
        for key, raw in raws:
            try:
                target = (Path(raw) if Path(raw).is_absolute() else (base / raw)).resolve()
            except Exception as exc:  # noqa: BLE001
                refusals.append(f"{key}={raw} 路径解析不了（{type(exc).__name__}: {exc}）"
                                "⇒ 这一步不许执行")
                continue
            try:
                target.relative_to(face)
            except ValueError:
                refusals.append(f"{key}={raw} 越出了你这趟的读写面（{face}）—— "
                                "面外一律不做：要别的目录就请父给你切一块（业主 T23）")
        return "；".join(refusals)

    def _do_summon(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        role = str(payload.get("role"))
        action = str(payload.get("action"))
        # 名册那三格要在这一步的载荷被结果覆盖之前取下来（S1k-3 的判据当场抓出来的坑：
        # 下面 `payload = res.payload` 之后 `payload.get("brief")` 读的是结果，
        # 于是每一次名册登记都变成"没给简介"）。
        brief_arg = str(payload.get("brief") or "")
        name_arg = str(payload.get("name") or "")
        reuse_arg = str(payload.get("reuse") or "")
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
        # ---- 名册登记（S1k-2；业主 T22："名册的增、删都由秘书做"）
        #
        # 只登记真的受理了的那一次（`refused` 不登记：它没跑）。
        # `brief` 的口径（与 `draft/92` 的一处偏差，理由写在提交信息里）：
        #   · 父点了名（`name` / `reuse`）却没给简介 ⇒ 受控拒绝式的读数（不打回派活）——
        #     一句话说明"名册没写进去"；这与 L-05e 的裁定同族（"阻塞一条委托比放行更贵"）；
        #   · 没点名也没给简介 ⇒ 照常派活，名册那一格如实报问题（不替它编）。
        if self.secretary is not None and str(res.status or "") in ("pending", "running", "done"):
            if str(res.outcome or "") != "refused":
                try:
                    reg = self.secretary.roster_add(
                        owner=self.my_task_id, role=role, task_id=str(res.task_id or ""),
                        brief=brief_arg, want_name=name_arg, reuse=reuse_arg)
                    if reg.get("problem"):
                        out["roster_problem"] = str(reg["problem"])
                    else:
                        out["roster_name"] = str(reg.get("name") or "")
                except Exception as exc:  # noqa: BLE001 —— 登记失败不许带走这次派活
                    out["roster_problem"] = f"名册登记没跑成：{type(exc).__name__}: {exc}"
        elif self.secretary is None:
            out["roster_problem"] = "这一趟没有秘书 ⇒ 名册不在手上（没有登记）"
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
        # ---- 收件人：直接父（业主 2026-10-09：「最常见的定义不明极可能是A查论文要B消化时
        # 遇到生僻定义，这时和父代理A交流即可」）——
        # 父通常就是那个能办这件事的人（B 的父常常就是 A，原文在它手里，就地就能给定义）；
        # 顶层（没有父）才发给主控 M。父那一行读不到 ⇒ 落回 M，并把"为什么落回"记进读数
        # （不静默改主，也不把申请丢掉）。
        to_role, whose = self._relay_recipient()
        if whose:
            body_lines_extra = [f"收件人：{whose}"]
        else:
            body_lines_extra = []
        body_lines = [*body_lines_extra, f"要谁：{role}", f"做什么动作：{action}"]
        if asked:
            body_lines.append("参数：" + json.dumps(asked, ensure_ascii=False, default=str)[:600])
        else:
            body_lines.append("参数：（这次没有参数）")
        body_lines.append(f"为什么：我要做的这件事被策略拒了（{reason}）—— {detail[:300]}")
        if role not in AP.partners_out(self.role):
            body_lines.append("注意：他不在我的可唤起伙伴里，所以我**看不到他的参数表** —— "
                              "参数可能不合法，请用 conductor.role_spec 核一遍再派。")
        body_lines.append(f"申请方：{self.role}（台账号 {self.my_task_id or '未拿到'}）；"
                          "批准与否由你决定，我这一步不会替你做。")
        body = "\n".join(body_lines)
        msg_id, problem = send_message(self.session_root, sender=self.role, to=to_role,
                                       subject=RELAY_SUBJECT, body=body, sid=self.sid)
        rec: dict[str, Any] = {"kind": "agent_summon_request", "role": self.role,
                               "wants_role": role, "wants_action": action, "params": asked,
                               "refusal_reason": reason, "message_id": msg_id,
                               "relay_to": to_role, "relay_why": whose}
        if problem:
            rec["problem"] = problem
        SS.append(self.session_root, rec, sid=self.sid)
        return {"to": to_role, "subject": RELAY_SUBJECT, "message_id": msg_id,
                "problem": problem,
                "note": (f"越权的边不会因为重试而成立 ⇒ 已向 {to_role} 申请代唤（{whose}）；"
                         "不要把这条申请当成'对方已经在做'。")}

    def ask_parent_for_definitions(self, pending: Sequence[Mapping[str, Any]], *,
                                   escalate: bool = False, stuck: str = "") -> dict[str, Any]:
        """定义抽不到时的向上报文（`draft/97` §15.4 的载体那一半）。

        业主逐字：

        > 「最常见的定义不明极可能是A查论文要B消化时遇到生僻定义，这时和父代理A交流即可」

        ⇒ 补法优先级定死：①问直接父（父通常就是 A，原文在它手里，就地能给）→
        ②A 上网搜（`pending_search`）→ ③B 自撰（`self_authored`，只对基本概念）。
        这一格做的是①，以及"父也办不了 ⇒ 才向上爬到 M，并逐级留痕"（`escalate=True`
        + `stuck` 写明哪一级卡住、为什么）。它不替父做判断：父办不办得了由父自己说，
        所以"爬上去"这一档必须由调用方显式传，而不是这里猜。

        三态（读的人要能分辨"没问"与"问了"）：

        | 结局 | 返回 |
        |---|---|
        | 没东西可问（`pending` 空） | `{"checked": False, "reason": "没有待补定义 ⇒ 没有发报文"}`（一条留言都不落） |
        | 报文落了 | `{"checked": True, "to": …, "message_id": …, "ask_why": …}` |
        | 落不成（收件人写不进去） | `checked=True` + `problem`：报文那一格没成要说出来，不许当成已发出 |
        """
        items = [dict(p) for p in (pending or []) if isinstance(p, Mapping)]
        if not items:
            return {"checked": False, "reason": "没有待补定义 ⇒ 没有发报文", "to": "",
                    "message_id": "", "ask_why": "", "concepts": []}
        if escalate:
            # 爬上去那一档：收件人是主控 M，而"哪一级卡住"必须写进载荷（逐级留痕）
            to_role, whose = S.CONDUCTOR_ROLE, (f"父那一级也办不了（{stuck or '未写明原因'}）"
                                                "⇒ 按 §15.4 向上爬到主控 M")
        else:
            to_role, whose = self._relay_recipient()
        names = "、".join(str(p.get("id") or p.get("stmt_id") or "?") for p in items[:8])
        body_lines = [
            f"收件人：{whose}",
            f"要什么：就地给出下面这些概念的定义（定义内容 + 出处；没有出处的就直说没有）",
            f"哪几条：{names}",
        ]
        for p in items[:8]:
            body_lines.append(f"  - {p.get('id') or p.get('stmt_id') or '?'}："
                              f"{p.get('why') or p.get('missing') or '定义待补'}")
        body_lines.append("为什么找我：我这边的定义抽不到，而原文按台账在你手里 —— "
                          "就地给比再上一趟网省（`draft/97` §15.4 的①档）。")
        body_lines.append("顺序（定死的优先级）：① 你（直接父）就地给 → ② 你办不了才 A 上网搜 "
                          "（落 search_requests）→ ③ 基本数学概念允许 B 自撰（记 self_authored）。")
        body_lines.append(f"申请方：{self.role}（台账号 {self.my_task_id or '未拿到'}）")
        msg_id, problem = send_message(self.session_root, sender=self.role, to=to_role,
                                       subject=DEFINITION_ASK_SUBJECT, body="\n".join(body_lines),
                                       sid=self.sid)
        rec: dict[str, Any] = {"kind": "definition_ask", "role": self.role,
                               "asks": to_role, "ask_why": whose,
                               "concepts": [str(p.get("id") or p.get("stmt_id") or "") for p in items],
                               "escalated": bool(escalate), "stuck_at": str(stuck or ""),
                               "message_id": msg_id}
        if problem:
            rec["problem"] = problem
        try:
            SS.append(self.session_root, rec, sid=self.sid)
        except Exception as exc:  # noqa: BLE001 —— 留痕失败也要在读数里看得见
            rec["ledger_problem"] = f"{type(exc).__name__}: {exc}"
        out: dict[str, Any] = {"checked": True, "to": to_role, "subject": DEFINITION_ASK_SUBJECT,
                               "message_id": msg_id, "ask_why": whose, "concepts": rec["concepts"],
                               "escalated": bool(escalate)}
        if problem:
            out["problem"] = problem
        if rec.get("ledger_problem"):
            out["ledger_problem"] = rec["ledger_problem"]
        return out

    def _relay_recipient(self) -> tuple[str, str]:
        """「请代唤」该发给谁：直接父的角色（顶层 / 读不到 ⇒ 落回主控 M）。

        业主 2026-10-09 的口径是"与父代理交流即可"（最常见的场景里父就是 A），
        而这一档此前写死发给 M（越级：中间那一层看不见，M 被当路由器）。
        返回 `(角色, 为什么是它)`；读不成时第二项写明原因（读数，不静默）。
        """
        pid = str(getattr(self, "parent_task_id", "") or "")
        mine = str(getattr(self, "my_task_id", "") or "")
        if not pid:
            return S.CONDUCTOR_ROLE, "顶层（没有父）⇒ 发给主控 M"
        if mine and pid == mine:
            # 顶层跑批那一行就是"我自己"（`open_top_level_run` 建的那一行）——
            # 它不当父（否则申请会发回给自己，等于没发）。
            return S.CONDUCTOR_ROLE, "父那一行就是我自己（顶层跑批的行）⇒ 发给主控 M"
        try:
            rows = list(self.conductor._tasks()) if self.conductor is not None else []
        except Exception as exc:  # noqa: BLE001 —— 读不成要如实说
            return S.CONDUCTOR_ROLE, f"台账读不成（{type(exc).__name__}: {exc}）⇒ 落回 M"
        row = next((r for r in rows if str(r.get("task_id") or "") == pid), None)
        role = str((row or {}).get("role") or "")
        if not role:
            return S.CONDUCTOR_ROLE, f"父那一行（{pid}）读不到 / 没有 role ⇒ 落回 M"
        if role == S.CONDUCTOR_ROLE:
            return S.CONDUCTOR_ROLE, f"父就是主控（{pid}）⇒ 发给 M"
        return role, f"发给直接父 {role}（台账号 {pid}）"

    def _do_message(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        to = str(payload.get("to"))
        reply_to = str(payload.get("reply_to") or "")
        # ---- 名册名那一支（S1k-2；业主 §1.8 的两个方向）
        #
        # 收件人写本地名（`D1` = 我名下的子代理；或我父名册里的名字 = 上行给父）。
        # 译码是秘书的事（接线员），落到盘上是一条挂在收件人名下的板项（不是公共频道）：
        # 那样"发给谁的只有谁能读"（T20 禁止代读）由板项的收件人字段天然保证。
        if to and to != PUBLIC and to != "ALL" and to not in (*S.ROLES, S.CONDUCTOR_ROLE,
                                                             "user", "用户"):
            return self._message_by_name(payload, to)
        if to == "ALL" and self.secretary is not None and str(self.my_task_id or ""):
            return self._message_my_children(payload)
        return self._message_by_channel(payload, to, reply_to)

    def _message_by_name(self, payload: Mapping[str, Any], name: str) -> dict[str, Any]:
        """按名册名发一条（下行走我名下的名册，上行走我父名册）—— 落到收件人名下的板项。"""
        if self.secretary is None or self.conductor is None:
            return {"message": "未发出", "to": name, "ok": False, "receipt": "unknown",
                    "note": "这一趟没有秘书/conductor ⇒ 名册不在手上，译不出这个名字"}
        tid, problem = self.secretary.resolve_down(owner=self.my_task_id, name=name)
        direction = "下行"
        if problem:
            tid, problem = self.secretary.resolve_up(my_task_id=self.my_task_id, name=name)
            direction = "上行"
        if problem:
            return {"message": "未发出", "to": name, "ok": False, "receipt": "unknown",
                    "note": f"名册里没有 {name!r}（下行与上行都查过）⇒ 受控拒绝并点名：{problem}"}
        row = self.conductor._task(tid) or {}
        role = str(row.get("role") or "")
        subject = str(payload.get("subject") or "")
        body = str(payload.get("body") or "")
        item_id = self.conductor.open_item(
            kind="message", role=role or S.CONDUCTOR_ROLE, expects="ack", action="message",
            summary=subject or f"来自 {self.role} 的一条留言",
            called_by=self.role, parent_task_id=tid,
            depth=int(row.get("depth") or 1) + 1 if row else 2,
            input_key=f"message@{self.role}:{self.my_task_id or '-'}->{name}")
        self.conductor.set_item_detail(item_id, (subject + "\n" + body).strip()[:400])
        return {"message": "已投递到收件人的板", "to": name, "to_task_id": tid,
                "item_id": item_id, "direction": direction, "channel": "roster",
                "receipt": "queued", "ok": True,
                "note": ("这一条挂在收件人名下（板项），只有它自己会渲染到 —— "
                         "父不许代读（T20）。若它此刻没有在跑，板项会等着它下次进循环。")}

    def _message_my_children(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """`to="ALL"` ⇒ 按我名下名册逐项开板项（内容一条、行为 per-recipient）。"""
        view = self.secretary.roster_view(owner=self.my_task_id)
        if not view.get("checked"):
            return {"message": "未发出", "to": "ALL", "ok": False, "receipt": "unknown",
                    "note": f"名册没读成（{view.get('reason')}）⇒ 不许当'没有收件人'"}
        active = [r for r in view.get("rows", []) if r.get("state") in ("活跃", "待命")]
        if not active:
            return {"message": "未发出", "to": "ALL", "ok": False, "receipt": "no_reader",
                    "note": "我名下名册里没有活跃/待命的子代理 ⇒ 没有收件人"}
        sent = [self._message_by_name(payload, str(r["name"])) for r in active]
        return {"message": "已按名册展开", "to": "ALL", "ok": all(x.get("ok") for x in sent),
                "receipt": "queued", "recipients": [r["name"] for r in active],
                "items": [x.get("item_id") for x in sent],
                "note": ("内容一条、行为 per-recipient：每项各自 ack；"
                         "'展开成功'不等于'都读到了'（读数看板面）。")}

    def _message_by_channel(self, payload: Mapping[str, Any], to: str,
                            reply_to: str) -> dict[str, Any]:
        """既有的那条路（角色 / `#public`）：准入与私聊逐字不动，公聊加一格身份。

        S6-a（业主 T20/T21 附二 乙）：公共频道的可见面 = 发信人的直接子代理
        ⇒ 发公聊必须带发信人的实例号；没有编号就受控拒绝（不许退回
        "全角色可见" —— 那正是 T20 要治的形态：任何角色随手 `to=#public`
        就等于全树广播）。
        """
        # 准入判据只有一份（模块级 `message_admission`）：这里与秘书那一侧都调它。
        not_allowed = message_admission(self.role, to, reply_to)
        if not_allowed:
            return {"message": "未发出", "to": to, "ok": False, "error": not_allowed}
        if to == PUBLIC and not str(self.my_task_id or ""):
            return {"message": "未发出", "to": to, "ok": False, "refused": "no_task_id",
                    "error": ("这一趟没有台账号 ⇒ 不发公共频道：它的可见面是"
                              "『发信人的直接子代理』，没有发信人编号就没人能判断"
                              "该不该看见这一条（业主 T20/T21）"),
                    "receipt": "unknown"}
        msg_id, problem = send_message(self.session_root, sender=self.role, to=to,
                                       subject=str(payload.get("subject") or ""),
                                       body=str(payload.get("body") or ""),
                                       reply_to=reply_to, sid=self.sid,
                                       from_task_id=str(self.my_task_id or ""))
        if problem:
            return {"message": "未发出", "to": to, "ok": False, "error": problem}
        where = "公共频道" if to == PUBLIC else f"给 {to} 的私聊"
        # 回执三态（`draft/85` §5 的 D76 / `draft/86` §4.2）："写进盘了"不等于"有人读"。
        #
        # 真机读数（`draft/89` §2）：128 个会话 579 条留言里只有 8 条被标记读过，
        # 而 12 次投递登记全部由 M 写 —— 因为生产形态下只有 M 有 LLM 循环，
        # A–H 是确定性动作 ⇒ 发给它们的留言没有任何进程会读。
        # 旧回执写的是 `ok: True` + "收件人下次运行时会看到它"，那是一句假话。
        #
        # 公聊那一档（S6-a）：读者就是我名下的直接子代理 ⇒ 一个都没有时
        # 如实回 `no_reader`（"展开了"绝不等于"有人读到了"）。
        receipt, reader_note = self._receipt_for(
            to, child_count=(self._my_children_count() if to == PUBLIC else None))
        return {"message_sent": msg_id, "to": to, "channel": where,
                "receipt": receipt, "ok": receipt != "no_reader",
                "note": reader_note}

    def _my_children_count(self) -> int | None:
        """我名下直接子实例的个数（`None` = 这一格没读成，不许当 0）。"""
        cond = self.conductor
        mine = str(self.my_task_id or "")
        if cond is None or not mine:
            return None
        look = getattr(cond, "_children_of", None)
        if not callable(look):
            return None
        try:
            return len(list(look(mine)))
        except Exception:  # noqa: BLE001 —— 读不成 ⇒ None（"没读成"不是"没有子代理"）
            return None

    def _receipt_for(self, to: str, *, child_count: int | None = None) -> tuple[str, str]:
        """这条留言的收件人有没有读者。返回 `(receipt, 一句话说明)`。

        三态（不许折平）：
        - `"queued"`：收件人有 LLM 循环 ⇒ 它下次进循环时会读到（今天只有 M 与
          `--drive`/`--subagents` 点过的那些）；公聊那一档的读者是我名下的直接子代理
          （`child_count > 0`，S6-a）；
        - `"no_reader"`：收件人没有循环（或公聊而我名下没有子代理）⇒ 这条留言不会有
          任何进程读它（写进盘了，但那是"存着"，不是"送达"）；
        - `"unknown"`：看不见接线表 / 看不见我名下的子代理 ⇒ 如实说不知道，
          不许按乐观猜成 `queued`（本仓的三态纪律）。
        """
        if to == PUBLIC:
            if child_count == 0:
                return "no_reader", ("我名下没有直接子代理 ⇒ 这条公共频道留言不会有任何"
                                     "进程读它（业主 T21：公聊的可见面就是我的直接子代理）")
            if child_count is None:
                return "unknown", ("看不见我名下的直接子代理 ⇒ 这条公聊有没有读者判不了："
                                   "『不知道』不许折成『送到了』")
            return "queued", (f"公共频道：我名下的 {child_count} 个直接子代理下次进循环时"
                              "会读到它 —— 要覆盖全树，得逐层向下转发（业主 T21）")
        loops = getattr(getattr(self.conductor, "backend", None), "loops", None)
        if isinstance(loops, Mapping):
            has_reader = any(str(k[0]) == to for k in loops if isinstance(k, tuple) and k)
            if has_reader:
                return "queued", f"{to} 有 LLM 循环 ⇒ 它下次进循环时会读到"
            return "no_reader", (f"{to} 没有 LLM 循环（确定性动作）⇒ 这条留言不会有任何进程读它；"
                                 "要送达就交给它的父，由父在步边界转达（业主 T13）")
        return "unknown", ("看不见接线表（本实例没有 backend 句柄）⇒ 无法判断收件人有没有读者："
                           "『不知道』不许折成『送到了』")

    def _outbound_hook(self, shape: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """发件钩子（A 线：秘书职责 1 格式内容优化 + 2 委派评估）。

        位置：委托离开本体之前（`_execute` 之前）。它是同步的（本体在等），
        产物却是"建议 + 并列候选"而不是改写后的载荷 —— 秘书不替本体表态，
        也不静默修实质缺陷（`draft/53` §2 的两条红线）。所以这里把读数并进结果，
        真正发出去的仍然是模型自己那一份。

        fail-open（`draft/53` §9.7）：超时/出错 ⇒ 原样放行 + 留痕。
        阻塞一条委托比放行更贵 —— 那正是 #1。所以任何异常都变成结果里的一格，
        绝不中断这一次循环。
        """
        if self.secretary is None or shape not in SECRETARY_OUTBOUND_SHAPES:
            return {}
        out: dict[str, Any] = {}
        try:
            # `admission` 是依赖注入：秘书要判 `message` 的协作边，判据本体在
            # 本模块（`message_admission`）—— 传进去而不是让 `secretary.py` 自己抄一份。
            got = self.secretary.optimize_outbound(shape, dict(payload),
                                                   admission=message_admission,
                                                   base=str(self.workspace_root or ""))
            out["alarms"] = list(got.get("alarms") or [])
            out["fail_open"] = bool(got.get("fail_open"))
            if got.get("problem"):
                out["problem"] = str(got["problem"])
            # ---- S1g：洗格式的读数 + 真正要发出去的那一份。
            #
            # `_washed_payload` 用一个下划线打头的键承载（本模块内部用）：
            # 它不并进这一步的结果 —— 结果里只看 `wash`（三态 + 动了几格），
            # 全文在台账的 `before`/`after` 两格里（那份才是给人逐格看的）。
            wash = got.get("wash") if isinstance(got.get("wash"), Mapping) else {}
            out["wash"] = {"checked": bool(wash.get("checked")),
                           "washed": bool(got.get("washed")),
                           "refused": str(wash.get("refused") or ""),
                           "reason": str(wash.get("reason") or "")}
            out["changes"] = [dict(x) for x in (got.get("changes") or ())]
            out["_washed_payload"] = got.get("after")
            # ---- S1g-2：面适配读数（业主 2026-10-09「"超越职责"的一个主要可能是
            # 无法在被分配的读写面内完成任务，这个秘书也要帮忙看」）。
            # `base` 传本实例自己的根：子代理那一趟它的根是它的面，父视角的基准
            # 必须跟着走（否则"父视角有、面内没有"这一档会算错）。
            out["surface_fit"] = dict(got.get("surface") or {}) if isinstance(
                got.get("surface"), Mapping) else {}
            if wash.get("refused"):
                # 硬拒：一次派活连"派给谁/做什么"都不全 ⇒ 不执行、不评估、不协商。
                return out
        except Exception as exc:  # noqa: BLE001 - fail-open：秘书坏了不许打断本体
            out["fail_open"] = True
            out["problem"] = f"{type(exc).__name__}: {exc}"
        if shape == "summon":
            try:
                to = str(payload.get("role") or "")
                action = str(payload.get("action") or "")
                key = str(payload.get("input_key") or "") or _summon_key(
                    action, dict(payload.get("params") or {}))
                dups: list[dict[str, Any]] = []
                if self.conductor is not None and hasattr(self.conductor, "duplicate_candidates"):
                    dups = self.conductor.duplicate_candidates(to, action, key)
                out["assessment"] = self.secretary.assess_delegation(
                    to=to, action=action, params=dict(payload.get("params") or {}),
                    input_key=key, duplicates=dups,
                    # S1g-2：复用已有子代理时它的面是已知的（名册那一格）
                    # ⇒ 面适配那一维判得最准；新起一个时槽位还没分（判得了
                    # "越界"与"父视角有、面内没有"两档）。
                    reuse=str(payload.get("reuse") or payload.get("name") or ""),
                    base=str(self.workspace_root or ""))
            except Exception as exc:  # noqa: BLE001 - 同上
                out["assessment_fail_open"] = f"{type(exc).__name__}: {exc}"
            # `R2b-⑲`：协商（职责 2 的"给出重新安排建议并协商"）—— 评估摆了同 key 的既有
            # 终态行、或结论是"建议重排/重复"时，秘书与对方的秘书协商；同一处再犯
            # （第二轮）⇒ `negotiate` 自己给出"上报本体"，这一格就把它摆出来（不静默）。
            try:
                verdict = str((out.get("assessment") or {}).get("decision") or "")
                if dups or "重排" in verdict or "重复" in verdict:
                    point = f"{to}.{action}（input_key={key or '无'}）"
                    seen = getattr(self, "_negotiated_points", None)
                    if seen is None:
                        seen = self._negotiated_points = {}       # type: ignore[attr-defined]
                    rounds = tuple(seen.get(point) or ())
                    rec = self.secretary.negotiate(with_role=to, point=point, rounds=rounds)
                    seen[point] = tuple(list(rounds) + [rec])
                    out["negotiation"] = rec
                    if rec.get("escalate_to_body"):
                        out["escalate_to_body"] = {
                            "why": "协商两轮仍未收敛 ⇒ 这一条上报本体（不许静默）",
                            "record": rec}
            except Exception as exc:  # noqa: BLE001 - 协商坏了不许打断派活
                out["negotiation_fail_open"] = f"{type(exc).__name__}: {exc}"
        return out

    def _inbound_hook(self, heard: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """收件钩子（A 线：秘书职责 4 委托加工 + 3 闭环提醒）。

        位置：委托进入本体之前（`_hear()` 拿到的新消息交给本体之前）。
        产物是"按本角色定位补的一段上下文"（`addendum`），原文一字不动 ——
        不加码不减码（`draft/53` §2），且原文与加工后并列留痕（`draft/55` §5.1）。

        fail-open 与发件钩子同一条纪律。
        """
        if self.secretary is None or not heard:
            return {}
        reworked: list[dict[str, Any]] = []
        for item in heard:
            try:
                reworked.append(dict(self.secretary.rework_inbound(dict(item))))
            except Exception as exc:  # noqa: BLE001 - fail-open
                reworked.append({"item": dict(item), "addendum": "",
                                 "problem": f"{type(exc).__name__}: {exc}", "fail_open": True})
        out: dict[str, Any] = {"reworked": reworked}
        # `R2b-⑲`：手稿通道的"摘要"也要有生产落点 —— 收件这一刻让本体看到最近几份交接
        # （`handoffs_digest` 只读；读不到就如实报"没读成"，不折成"没有交接"）。
        try:
            digest = str(self.secretary.handoffs_digest() or "")
            out["handoffs_digest"] = digest
            if not digest.strip():
                out["handoffs_digest_note"] = "手稿通道读成了、最近没有交接（不是没读成）"
        except Exception as exc:  # noqa: BLE001 - fail-open
            out["handoffs_digest_problem"] = f"{type(exc).__name__}: {exc}（这一格没读成）"
        return out

    def _ensure_status_report(self, run: LoopRun) -> str:
        """M 收工前保证有一份状态报告落盘（模型没调就框架补落）。返回一句读数（空 = 不用管）。

        ## 为什么必须有这一格（T1 第 18 趟实测）

        `draft/38` §7 第三组判据里"M 的状态报告落盘"是一格过程判据，而并表之后重跑的
        T1 两趟（`t1w`/`t1x`）实测：M 派了活、也收了工，却一次都没调
        `conductor.status_report` —— 工具在它的面上（注册表 83 件含它）、提示词里也写着，
        只是那句原先只说"用户问『现在什么情况』时用"；补一句"收工前也落一份"之后
        仍然没调（收尾序列被 `conductor.closing` 占满，一句散文不足以让它多走一步）。

        所以这一格与 `_emit_settlement` 同族：框架保证"有"，模型保证"内容"。

        三态（读的人要能分辨"模型落的"与"框架补的"）：

        | 结局 | 返回 |
        |---|---|
        | 模型这一趟调过（盘上有本趟产生的 `STATUS-*`） | `""`（一个字都不动，不覆盖） |
        | 没调 ⇒ 框架补落一份 | 一句读数（`written_by=framework` + 两份文件名） |
        | 补落失败 | 一句读数写清失败原因（不许当成"报告已落盘"） |
        """
        if self.role != S.CONDUCTOR_ROLE or self.store is None:
            return ""
        out_dir = Path(self.session_root) / "out" / "review"
        started = time.time() - float(getattr(run, "elapsed_sec", 0.0) or 0.0)
        try:
            fresh = [p for p in out_dir.glob("STATUS-*")
                     if p.is_file() and p.stat().st_mtime >= started - 1.0]
        except OSError as exc:  # noqa: BLE001 —— 判不了要如实说
            return f"状态报告这一格没查成（{type(exc).__name__}: {exc}）"
        if fresh:
            return ""
        try:
            from . import statusreport as SR

            _, md, js = SR.write_status_report(self.store, self.session_root)
        except Exception as exc:  # noqa: BLE001 —— 补落失败要留痕，不许静默
            return f"状态报告补落失败（{type(exc).__name__}: {exc}）⇒ 这一格仍然没有落盘读数"
        return (f"状态报告：模型这一趟没调 conductor.status_report ⇒ 框架补落 "
                f"{md.name}/{js.name}（written_by=framework）")

    def _emit_settlement(self, run: LoopRun) -> str:
        """终态回报：每个任务跑完都必须有一条回报（业主 2026-10-08 T17）。返回一句读数。

        两层必须分开（DSH 的教训，`draft/85` §5.4）：

        - 通报由框架保证：模型没写 `notify`（`run.handoffs` 为空）时，框架开一条
          `kind="notice"` 的板项，body 逐字写「（它没有留下结论）」—— 对齐 DSH 的
          `It left no closing message.`；
        - 内容由模型给：模型写了就不补第二条（负控见
          `tests/test_report_is_mandatory.py` 的"模型填了 ⇒ 恰好一条"）。

        三种"没做成"都如实返回一句读数，不静默：不是终态 / 没有 conductor 句柄 /
        开项抛异常 —— 后者在本仓是最忌的形态（"报告没写成"与"不用报告"长得一样）。

        收件人是谁（D89，2026-10-08 深夜修）：板项的 `parent_task_id` 口径是
        "收件人的编号"，所以子报给父时它必须是父的台账号、`role` 写父的角色。
        改前这里写的是 `parent_task_id=self.my_task_id`（挂在自己名下、角色记成 M）——
        后果是父的待办视图 `open_items_of(父的编号)` 里永远看不到"哪个子向我交差了"。
        现在用 `run` 里现算的 `parent_task_id` / `parent_role`（顶层发起时它们落回
        "这一趟自己"，与改前逐字相同）。判据：`tests/test_report_is_mandatory.py` /
        `tests/test_children_and_parent_are_visible.py`（负控：换成自己的编号 ⇒ 红）。
        """
        #: 三档"不停在终态"都在这一行里：正在等用户（`waiting_for_user`）、
        #: 以及还没定论就让出（空串）。改前这里还有 `"max_steps"` 一格 ——
        #: 裁定 12-K 之后循环不再产生它（步数只上报、不收工），留着就是一个
        #: 永远不会为真的分支，所以按"死取值"删掉而不是注释掉。
        if not str(run.stop_reason or "") or run.stop_reason == "waiting_for_user":
            return ""          # 没停在终态（还在等用户 / 还没有定论）⇒ 它不是"跑完了"，不补通报
        if run.handoffs:
            return ""          # 模型自撰过 ⇒ 不补第二条（不许把模型的内容淹掉）
        if self.conductor is None:
            return ("终态回报没落板：这一趟没有 conductor 句柄"
                    "（`run_role` 会自动装配；裸构造的 `AgentLoop` 不会）")
        body = str(run.final or "").strip() or "（它没有留下结论）"
        # 收件人：父的台账号与角色（`run` 里算好的；替身/裸对象没有这两格时落回旧行为）。
        to_id = str(getattr(self, "parent_task_id", "") or self.my_task_id or "")
        to_role = str(getattr(self, "parent_role", "") or S.CONDUCTOR_ROLE)
        # 板项是收件人的子行 ⇒ 深度 = 收件人的深度 + 1（`verify` 的
        # `task_depth_discontinuous` 判这一条，实测：写成"我的深度"会让顶层那一趟红）。
        #   · 挂在真父名下（子这一趟）⇒ 父的深度 + 1 = 我的深度；
        #   · 顶层那一趟挂在自己名下 ⇒ 我这一行的深度 + 1（与改前逐字相同）。
        hangs_on_self = (not to_id) or to_id == str(self.my_task_id or "")
        item_depth = int(self.depth or 1) + (1 if hangs_on_self else 0)
        try:
            item_id = self.conductor.open_item(
                kind="notice", role=to_role, expects="ack",
                summary=f"{self.role} 已收工（{run.stop_reason}）", called_by=self.role,
                parent_task_id=to_id or None, depth=item_depth,
                input_key=f"notice@{self.role}:{self.my_task_id or '-'}",
            )
        except Exception as exc:  # noqa: BLE001 —— 回报没落成必须留痕，不许静默
            return f"终态回报没落板：{type(exc).__name__}: {exc}"
        # body 落在板上的 `detail` 位（甲形态七格里没有正文字段；正文的正式落点是
        # `handoffs.jsonl`，板项只是"有一条回报"这件事本身）。写进 detail 是为了
        # 读板的人能一眼看见结论或那句"它没有留下结论"。
        self.conductor.set_item_detail(item_id, body)
        SS.append(self.session_root, {"kind": "agent_settlement_item", "role": self.role,
                                      "item_id": item_id, "stop_reason": run.stop_reason,
                                      # 收件人也进读数：事后要能回答"这条通报是挂给谁的"（D89）
                                      "to_task_id": to_id, "to_role": to_role,
                                      "has_conclusion": bool(str(run.final or "").strip()),
                                      "sid": self.sid}, sid=self.sid)
        return f"终态回报已落板：{item_id}（框架通报；模型没填 notify）" + (
            # 父是谁没读成时这里必须接着说一句：否则读的人会以为"挂对了"
            f"；父是谁没读成（{getattr(self, 'parent_problem', '')}）⇒ 挂在这一趟自己名下"
            if (getattr(self, "parent_problem", "") and not str(
                getattr(self, "parent_task_id", ""))) else "")

    def _do_handoff(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """写一份交接手稿 + 把"编号 + 一句简要描述"发给收件人（`draft/37` §134）。

        两件事一起做，是因为它们本来就是一件事的两半：手稿是「内容」，
        留言是「通知」。让模型分两步做，就会出现"写了手稿但对方不知道"（或反过来）
        的半截状态；而且用户点过名："就传个编号感觉有点尬，可以再附一句简要描述"。

        `to="ALL"` ⇒ 走公共频道（所有人收得到）；存储是追加式账本
        `manuscripts/handoffs.jsonl` 的一行（`draft/39` §C1：编号与那一行在同一把锁里分配）。

        ## A 线：执笔权已经移交给本角色的秘书（`draft/53` §2.1 / `draft/55` §3.2）

        用户口径（2026-10-06）："由于所有信息交互都由秘书过一遍手，所以 handoffs 的
        增改查能力都该给秘书，智能体只保留『查』的能力。" 落法：

        - 循环形状 `handoff` 保留（本体依旧"说我要交接什么"）；
        - 但写这一行的是 `self.secretary.handoff_add(...)`（`sender` 仍是本角色）；
        - 没装配秘书 ⇒ 不写并如实报错（"形状保留、写路径关闭"的判据就在这一支）。

        `manuscripts.read` / `manuscripts.list` 工具保留（这就是"智能体只保留查"）。
        """
        to = str(payload.get("to") or "")
        channel = PUBLIC if to == "ALL" else to
        # `summary` 是这一形状的正名（它就是进留言的那一句话）；`brief` / `title` 是旧名，
        # 仍然接受 —— 旧调用点、旧提示词与模型的历史习惯都不至于因此写不进去。
        one_line = (str(payload.get("summary") or "").strip()
                    or str(payload.get("brief") or "").strip()
                    or str(payload.get("title") or "").strip())
        why = str(payload.get("why") or "").strip()
        if self.secretary is None:
            return {
                "handoff": "未写成", "ok": False,
                "error": ("交接手稿的执笔权已移交给本角色的秘书（智能体只保留『查』），"
                          "而本次运行没有装配秘书 ⇒ 这一行不写。装配方式："
                          "`AgentLoop(..., secretary=secretary.Secretary(<本角色>, root=…))`"
                          "（`run_role` 会自动装配；裸构造不会）。"),
            }
        try:
            # `R2b-⑲`：手稿通道的三件在生产面都要有落点 —— `add` 已接（上面那段），
            # `revise` 走"payload 带了 `revises`"这一支（订正某一号，旧行保留）。
            revises = str(payload.get("revises") or "").strip()
            if revises:
                rec = self.secretary.handoff_revise(
                    mid=revises, summary=one_line, body=str(payload.get("body") or ""),
                    task_id=self.my_task_id,          # ← 一实例一秘书：每行都要能对回实例
                    reason=why, note=str(payload.get("note") or ""))
            else:
                rec = self.secretary.handoff_add(
                    to=to, summary=one_line, body=str(payload.get("body") or ""),
                    refs=list(payload.get("refs") or []), sid=self.sid or "",
                    task_id=self.my_task_id,          # ← 同上（真机 593 行缺这一格）
                    note=str(payload.get("note") or ""))
        except Exception as exc:  # noqa: BLE001 - 执笔失败必须报错留痕，不许静默放行
            return {"handoff": "未写成", "ok": False,
                    "error": (f"秘书执笔失败（这一格不许静默放行，否则手稿会缺行）："
                              f"{type(exc).__name__}: {exc}")}
        summary = str(rec.get("summary") or "")
        # `R2b-⑲` 的"查"：先问一句"这件事是不是已经交接过"（`handoff_query` 的用途就是
        # 判重复委派）。只摆读数、不阻断 —— 重复与否归本体与秘书判断（机器不替它裁）。
        try:
            same = [r for r in self.secretary.handoff_query(to=to, sender=self.role)
                    if str(r.get("summary") or "").strip() == summary
                    and str(r.get("id") or "") != str(rec.get("id") or "")]
            dup_note: Any = {"count": len(same),
                             "ids": [str(r.get("id") or "") for r in same[:5]],
                             "note": ("同一个人、同一句话的交接已经有过 ⇒ 可能是一次重复委派"
                                      "（要不要合并/订正由本体或秘书判断）" if same else
                                      "查过了：没有同一句话的既有交接")}
        except Exception as exc:  # noqa: BLE001 - 查坏了不许带走这次交接
            dup_note = {"count": 0, "ids": [],
                        "problem": f"{type(exc).__name__}: {exc}（这一格没查成）"}
        shown = revises or str(rec.get("id") or "")
        msg_id, problem = send_message(
            self.session_root, sender=self.role, to=channel,
            subject=f"手稿 {shown}：{summary}",
            body=(f"[手稿 {shown}] {summary}"
                  + ("（订正行，旧行保留）" if revises else "")
                  + (f"\n（为什么找你：{why}）" if why else "")
                  + f"\n全文：`manuscripts.read(id=\"{shown}\")`"
                    f"（盘上 {rec.get('path')}）"),
            sid=self.sid, from_task_id=str(self.my_task_id or ""))
        return {"handoff": shown, "ok": not problem, "id": shown,
                "path": rec.get("path"), "to": channel, "brief": summary,
                "revises": revises,
                "existing_same_summary": dup_note,
                "notified": msg_id if not problem else "",
                "error": problem,
                "note": ("收件人下次运行时（或本步之后）会在收件箱里看到编号；"
                         "它用 `manuscripts.read` 读全文")}

    def _record_interjection_effect(self, run: LoopRun, pending: dict[str, Any] | None,
                                    *, step: int, shape: str, payload: Mapping[str, Any]) -> None:
        """落"叫停类插话有没有改变这一步的做法"（`draft/39` §3.11 二 D07 第 3 条）。

        "改变做法"的判据是机械的、可复核的：这一步的调用键与收到插话之前那一步不同
        （`_call_key` 是"同形状 + 同参数"的指纹）。它不是"模型说它听了"——自述不是事实。
        收工（`final`）也要记：那一趟最常见的回应就是"照插话收工"，而它正好是最该被看到的形态。
        """
        if pending is None:
            return
        key = _call_key(shape, payload)
        changed = key != str(pending.get("prev_key") or "")
        SS.append(self.session_root, {
            "kind": "agent_interjection_effect", "role": self.role,
            "ids": list(pending["ids"]), "step": int(step), "shape": shape,
            "call_key": key, "changed_action": bool(changed),
            "what_it_did": _call_brief(shape, payload),
        }, sid=self.sid)
        run.notes.append(
            f"插话 {pending['ids']} 在第 {step} 步收到 ⇒ 这一步"
            + ("换了做法" if changed else "仍然做同一件事（读数里记 changed_action=false）"))

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
    #: 按实例的面造注册表（S1n-c，业主 T23）：`surface -> registry`。
    #:
    #: 为什么是工厂而不是"后端自己造"：`LlmBackend` 手上只有一个共用注册表，
    #: 而装配参数（`store` / `conductor` / `providers` / …）只有调用方知道 ⇒
    #: 调用方给一个工厂，这里只负责"这一趟该用哪一个"。
    #: 不给工厂（或那一趟没有面）⇒ 用共用的 `registry`，老行为逐字不变。
    registry_factory: Any = None
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
        # 秘书不在这里传：`AgentLoop.__post_init__` 会按业主 T14「每唤起一个智能体就自带一个
        # 秘书」自动派生（这里给了 store/registry/seam/sid，正是派生需要的四样）。
        # 别"顺手"补一个 `secretary=None` —— 那会把这条路上的秘书关掉，
        # 而真机读数正是"批量路写不出自撰交差行"（1562 行全框架派生，模型自撰 0）。
        row = self._running_row(role, task_id)
        # 读写面（S1n-b/c，业主 T23）：从父的名册里读这一行的面
        # （`out/roster/<父代号>.jsonl` 的 `surface` 那一格，两级查见 `Secretary.surface_of`）。
        # 读不到 ⇒ 不切面（老行为逐字不变）。
        child_surface = ""
        try:
            from .secretary import Secretary as _Sec

            parent_tid = str(row.get("parent_task_id") or "")
            own_tid = str(row.get("task_id") or params.get("_task_id") or "")
            if parent_tid and own_tid:
                found = _Sec(role, root=self.session_root,
                             store=self.store).surface_of(owner=parent_tid, task_id=own_tid)
                child_surface = str(found.get("path") or "") if found.get("checked") else ""
        except Exception:  # noqa: BLE001 —— 面读不成不打断这一趟（但也不假装切过）
            child_surface = ""
        # S1n-c：这一趟用哪一个注册表 —— 有面且有工厂 ⇒ 按面造一个
        # （面就是这一趟的 `fs.*` 根，业主 T23 的"面 = 新的根"）；否则共用那个。
        child_registry = self.registry
        if child_surface and callable(self.registry_factory):
            try:
                child_registry = self.registry_factory(child_surface)
            except Exception:  # noqa: BLE001 —— 造不出来就退回共用（并在结果里留痕）
                child_registry = self.registry
        loop = AgentLoop(role=role, session_root=self.session_root,
                         registry=child_registry,
                         seam=seam, conductor=self.conductor, max_steps=int(cfg.get("max_steps", self.max_steps)),
                         # S1n-c：注册表按面造时，`workspace_root` 也跟着面走 ——
                         # 否则 `_surface_refusal` 会拿工作区当基准，把面内的裸相对路径判成越界
                         # （实测：子代理写 `笔记.md` 被拒，而它本该落在自己的面里）。
                         workspace_root=child_surface or self.workspace_root,
                         sid=self.sid, token=token,
                         store=self.store, stop_file=self.stop_file)
        run = loop.run(str(cfg.get("task_from_params") or "") or _task_text(params, role, action),
                       summoned_by=str(row.get("called_by") or params.get("_summoned_by")
                                       or S.CONDUCTOR_ROLE),
                       my_task_id=str(row.get("task_id") or params.get("_task_id") or ""),
                       # 父的台账号从我这一行读（D89）：它同时是提示词里
                       # `{{parent_task_id}}` 那一格与终态回报挂项的名字。
                       parent_task_id=str(row.get("parent_task_id") or ""),
                       surface=child_surface,
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
        """把这次循环的完整记录写成文件，返回路径（失败就返回空串并留 note）。

        ## B11（`draft/41-A` 的 B11）：唯一性靠 `O_EXCL`，不靠"先数后写"

        旧实现是 `n = len(list(d.glob(f"{role}-*.json"))) + 1`，然后按这个名字写 ——
        没有锁、也不是 `O_EXCL`：同一角色同秒的两个并发循环会算出同一个 `n`，
        后写覆盖先写，于是两个召唤返回同一个 `llm_run_path`（一份产出凭空消失，
        而两个调用方都以为自己的产出在盘上）。`conductor._write_new_row` 为同类问题
        专门加了 `_id_lock`；这里用更省事也更彻底的一条：`open(..., "x")`（`O_EXCL`）
        —— 它同时挡住同进程的两个线程与两个进程（进程内的锁挡不住后者）。

        失败不用"猜一个名字"兜底：撞名就 +1 重试（名字里的时间戳不变，序号递增），
        重试到上限仍撞 ⇒ 如实留 note 并返回空串（"没写成"与"写成了"要分得开）。
        """
        try:
            d = self.session_root / RUNS_DIR_NAME
            d.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(run.to_dict(), ensure_ascii=False, indent=2) + "\n"
            stamp = time.strftime("%Y%m%d-%H%M%S")
            n = len(list(d.glob(f"{role}-{stamp}-*.json"))) + 1
            while n <= _RUN_ARTIFACT_MAX_SEQ:
                path = d / f"{role}-{stamp}-{n:03d}.json"
                try:
                    with path.open("x", encoding="utf-8", newline="\n") as fh:
                        fh.write(payload)
                    return str(path)
                except FileExistsError:
                    # 另一个写者抢到了这个名字（同秒并发或跨进程）⇒ 换下一个序号。
                    n += 1
            run.notes.append(f"产出落盘失败：同一秒内 {role} 的序号用尽（{stamp}）")
            return ""
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
        唤起的角色都以为"是主控直接派的、深度 1"。实测（读数摘录 `temp/t0260-evidence`）：
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
    """从会话记录重建"本趟"的 transcript（S-C 第 ② 步之后：它是 `resume_messages` 的渲染）。

    名字保留是因为它的读者还在（`run_role` 的检查点与拒绝读数都印它，判据也读它）；
    但它现在是一层薄壳：`render_messages(resume_messages(...))`。
    于是"重建两份"这件事在结构上不成立 —— 序列是真身，文本是渲染。
    """
    messages, step = resume_messages(session_root, role, sid, task=task)
    return render_messages(messages), step


def resume_messages(session_root: Path | str, role: str, sid: str | None,
                    *, task: str) -> tuple[list[dict[str, Any]], int]:
    """从会话记录重建"本趟"的消息序列，返回 `(messages, 下一个 step)`（S-C 第 ② 步）。

    ## 判据：与循环里那份逐条相等（含思维链那一格）

    重建只认两样东西：本趟的起点（最后一条"全新开始"的 `agent_run_start`，
    它带着任务 / 发起者 / 深度 / 台账号）与它之后逐条落盘的 `agent_step` 事件。
    每一条消息都走 `agent_loop` 里那几个模块级函数
    （`_opening_transcript` / `_spoken_half` / `_result_half` / `*_line` / `assistant_message` /
    `tool_message`）—— 循环里也是它们，所以"两处拼法"这件事在结构上不成立。

    思维链（12-A=乙）：事件里那一格 `reasoning` 就是当时进消息的那一份
    （`_recorded_reasoning` 与落档同一把尺）⇒ 重建出来的 `reasoning_content` 与当时逐字相同。

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
        return [], 0
    begin = fresh_mine[-1]
    fresh_any = [i for i in role_starts if _is_fresh_run_start(events[i])]
    end = next((i for i in fresh_any if i > begin), len(events))
    head = events[begin]
    # 恢复那一趟也要按"我是谁"读公聊（S6-a）：`agent_run_start` 里写着这一趟的
    # 父实例号与发起方，正是可见面要的那两格。
    inbox, _fresh, _problems2 = inbox_digest(root, role, sid=sid,
                                             parent_task_id=str(head.get("parent_task_id") or ""),
                                             parent_role=str(head.get("summoned_by") or ""))
    out: list[dict[str, Any]] = [user_message(
        _opening_transcript(task, inbox=inbox,
                            summoned_by=str(head.get("summoned_by") or ""),
                            task_id=str(head.get("task_id") or ""),
                            depth=int(head.get("depth") or 1)))]
    next_step = 0
    for e in events[begin + 1:end]:
        if e.get("kind") != "agent_step" or str(e.get("role")) != role:
            continue
        step = int(e.get("index") or 0)
        shape = str(e.get("shape") or "")
        payload = e.get("payload") if isinstance(e.get("payload"), Mapping) else {}
        result = e.get("result") if isinstance(e.get("result"), Mapping) else {}
        thought = str(e.get("reasoning") or "")
        if shape == "invalid":
            problem = str(result.get("problem") or "")
            if problem == "judge_bad_args":
                correction = _bad_args_line(step, str(result.get("detail") or ""))
            elif problem == "judge_bad_json":
                correction = _bad_json_line(step, problem, str(result.get("detail") or ""))
            else:
                correction = _invalid_line(step, problem)
            out.append(assistant_message(step, payload, name=shape, reasoning=thought))
            out.append(tool_message(step, correction, name=shape))
        else:
            out.append(assistant_message(step, payload, name=shape,
                                         content=_spoken_half(step, payload),
                                         reasoning=thought))
            out.append(tool_message(step, _result_half(result), name=shape))
        next_step = max(next_step, step + 1)
    # ---- S-B：把压缩的替换按序重放（施工单 §2 逐字：只在内存里压会让续跑那一趟
    # 看到没压过的版本，而"续跑看到的正是当时那份对话"是本仓最强的一条判据）。
    # `surface_op` 是闭区间、两端都含，且它是位置 span（不是数值区间）
    # ⇒ 按位置做切片替换，绝不写 `range(start, end + 1)`。
    for e in events[begin + 1:end]:
        if e.get("kind") != "compaction_swap" or str(e.get("role")) != role:
            continue
        op = e.get("surface_op") if isinstance(e.get("surface_op"), Mapping) else {}
        repl = e.get("replacement_message")
        if str(op.get("op") or "") != "replace" or not isinstance(repl, Mapping):
            continue
        start = int(op.get("start_seq") or 0)
        end = int(op.get("end_seq") or 0)
        if start < 0 or end < start or end >= len(out):
            continue
        out = out[:start] + [dict(repl)] + out[end + 1:]
    return out, next_step


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


def _secretary_for(role: str, *, root: Path | str, store: Any, registry: Any,
                   seam: Any, sid: str | None = None) -> Any:
    """给这一趟装配本角色自己的秘书（生产路径的唯一落点）。

    主控裁定 A5（2026-10-06）：打开秘书的模型判断。三个条件写在这一个函数里：

    1. 同一个缝实例 —— 传进去的就是 `run_role` 为这个角色造的那一个
       `LlmSeam`（`:2958`）。同一个实例意味着角色、`scope`、账本、预算都是同一份，
       于是判断那一笔钱记在本体自己的账上，而不是另开一本；
    2. `enable_model=True` —— 关着的时候三条判断在生产里等于不存在，
       而"把该不该派的判断全写死成确定性规则"正是用户点名不要的形态；
       花销由 `Secretary.should_engage` 绑在问题量上（干净的派活 0 次调用）；
    3. 可归因 —— 每次判断的 `usage_id`（取不到就 `call_index`）由
       `Secretary.last_judge_cost` 从缝自己落的 `llm_call` 事件读回来、进决定台账。

    装配失败不抛（fail-open）：`run_role` 那一层兜住异常 ⇒ 不装配秘书
    （写路径关闭、判断不发生），而这一趟照跑。
    """
    from . import secretary as _SEC

    return _SEC.for_role(role, root=root, store=store, registry=registry,
                         seam=seam, enable_model=True, sid=sid)


def run_role(role: str, task: str, *, store: Any, registry: Any,
             session_root: Path | str | None = None,
             conductor: Any = None, seam: LlmSeam | None = None, gateway: Any | None = None,
             max_steps: int = 30, usd_budget: float | None = None,
             workspace_root: str = "", sid: str | None = None, token: Any = None,
             from_env: bool = True, user_timeout_sec: float | None = None,
             ask_policy: str | None = None, resume: bool = False,
             stop_file: str = "", secretary: Any = None) -> LoopRun:
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
    if secretary is None:
        # A 线：每个智能体自带一名秘书（同一个类，每角色一份配置）。
        # 生产路径自动装配 —— 不给就自动造，是为了让"手稿写权移交"不需要
        # 每个调用点都记得传一个对象（那种"靠人记得"的设计在本项目里失败过多次）。
        # 失败姿态同秘书本身：造不出来 ⇒ 不装配（写路径关闭），但这不改变别的判据。
        #
        # ---- 2026-10-08（三处缺口之一）：这一支此前是光秃秃的 `except: secretary = None`
        #      —— 无日志、无事件。后果不是"少一个读数"，而是"写路径整体关闭而盘上无痕迹"：
        #     之后每一次 `handoff`（含收工那一句 `notify` 派生的手稿）都返回
        #     `{"ok": False, "error": "…没有装配秘书…"}`，而事后从会话记录里读不出
        #     "到底是哪一步、因为什么没装配"（真机没观测到，但它是结构性的）。
        #     改法与既有风格一致：落一条 `agent_note` 事件（`run` 里进程登记/插话消费
        #     读不成时就是这一种）+ 在 `run.notes` 里留一条（那一格会进
        #     `agent_run_end` 的 `notes`）。三态纪律：`except` 里不猜原因，把
        #     `type(exc).__name__` 与原文照抄。
        secretary_problem = ""
        try:
            secretary = _secretary_for(role, root=root, store=store, registry=registry,
                                       seam=seam, sid=sid)
            if conductor is not None and getattr(conductor, "secretary", None) is None:
                # M 的派活路径也接同一套钩子（`draft/54 §2` 的第 3 个落点）。
                conductor.secretary = secretary
        except Exception as exc:  # noqa: BLE001 - 秘书没装配不等于这一趟不能跑（fail-open）
            secretary = None
            secretary_problem = (f"秘书装配失败（{type(exc).__name__}: {exc}）⇒ 这一趟没有秘书："
                                 "手稿的写路径整体关闭（`handoff` 与收工 `notify` 派生那一份"
                                 "都写不成，返回 `ok is False`），而这一趟照跑。"
                                 "装配入口：`agent_loop._secretary_for` / `Secretary.for_role`")
            SS.append(root, {"kind": "agent_note", "role": role,
                             "note": secretary_problem}, sid=sid)
    loop = AgentLoop(role=role, session_root=root, registry=registry, seam=seam,
                     conductor=conductor, max_steps=max_steps, workspace_root=workspace_root,
                     sid=sid, token=token, store=store, user_timeout_sec=user_timeout_sec,
                     ask_policy=ask_policy, stop_file=str(stop_file or ""),
                     secretary=secretary)
    summoned_by = S.CONDUCTOR_ROLE if role == S.CONDUCTOR_ROLE else ""
    start_depth = 1 if role == S.CONDUCTOR_ROLE else 2
    # ---- F1（`44 J-32` 的"往前走"半）：给这一趟开一条 tasks 行，并让它成为
    # 这一趟每一次模型调用的 `task_id`。
    #
    # 改前这里是 `my_task_id=""`：`llmseam._charge_ledger` 把空串归一成 `None`，
    # 于是这一趟花的每一笔钱在账上都读不出"属于哪一次召唤"（真机 51%~66% 的账如此）。
    # 只填不建行是负收益（每行都会成 `dangling_usage_task` 的 error）⇒ 两件事同批。
    # 失败姿态：开行失败不打断这一趟（留不下来的是读数，不是这一趟的活）。
    top_tid = ""
    if conductor is not None and hasattr(conductor, "open_top_level_run"):
        try:
            top_tid = conductor.open_top_level_run(role, task)
        except Exception as exc:  # noqa: BLE001 - 开行失败不许打断顶趟（损失的是读数）
            log = getattr(conductor, "_log", None)
            if callable(log):
                log(f"顶趟开行失败（这一趟的账会读不出归属）：{type(exc).__name__}: {exc}")
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
        # S-C 第 ② 步：续跑的载体换成了消息序列（`resume_messages`）——
        # 重建出来的那份要么逐条相等、要么这一步没查成（三态：不猜、不从第 1 步重跑）。
        rebuilt, step0 = resume_messages(root, role, sid, task=task)
        if step0 <= 0:
            _note_resume_refusal(root, role, task, sid, "resume_no_transcript",
                                 attempted_from=int(cp.get("step") or 0))
            return LoopRun(role=role, task=task, stop_reason="resume_no_transcript",
                           final=("要求续跑，但会话记录里重建不出这一趟的任何一步"
                                  "（同角色 + 同任务原文的 `agent_step` 一条都没有）"
                                  "⇒ 没查成：不许从第 1 步重跑。"))
        run = loop.run(task, summoned_by=summoned_by, my_task_id=top_tid, depth=start_depth,
                       resumed=(rebuilt, step0),
                       waiting_for=str(cp.get("waiting_for") or ""))
    else:
        run = loop.run(task, summoned_by=summoned_by, my_task_id=top_tid, depth=start_depth)
    completed = run.resumed_from + len(run.steps)
    # ---- F1：顶趟也要收行（开了不收 = 台账上永远一条 `running`）
    if top_tid:
        try:
            conductor.finish_top_level_run(top_tid, stop_reason=str(run.stop_reason or ""),
                                          detail=str(run.final or "")[:200])
        except Exception as exc:  # noqa: BLE001 - 收行失败不许带走这一趟的产出
            log = getattr(conductor, "_log", None)
            if callable(log):
                log(f"顶趟收行失败（{top_tid}）：{type(exc).__name__}: {exc}")
            run.notes.append(f"顶趟那一行没写成终态（{type(exc).__name__}: {exc}）："
                             "台账上它会停在 running（这一趟的产出不受影响）")
    problem = save_run_checkpoint(root, role, sid, task=task, step=completed,
                                  stop_reason=run.stop_reason, waiting_for=run.waiting_for,
                                  spend=run.spend)
    if problem:
        run.notes.append(f"这一趟的步检查点没写成（{problem}）：下一趟 `--resume` 会读到"
                         "更早的一份（或读不到），于是它要么多跑几步、要么如实报'没查成'")
    # `R2b-⑲`：M 的状态读数 —— 秘书台账里的坏行要在这一趟的读数里看得见
    # （不是门：坏行只说明那几行读不出来，不改变任何判定；读不到与"没问题"必须分开）。
    try:
        bad = list(secretary.decision_problems()) if secretary is not None else []
        if bad:
            run.notes.append(f"秘书台账有 {len(bad)} 行读不出来（如实报，不当成'没有问题'）："
                             f"{bad[:3]}")
    except Exception as exc:  # noqa: BLE001 - 读数坏了不许带走这一趟
        run.notes.append(f"秘书台账的坏行这一格没读成：{type(exc).__name__}: {exc}")
    if secretary_problem:
        # "没装配秘书"这一事实要能被后续读到：事件在盘上（上面那一支落的
        # `agent_note`），而这一份跟着返回值走 —— 两条路都要有，缺一条就会有人
        # 只看其中一处而以为"秘书没问题"。
        run.notes.append(secretary_problem)
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
    print(f"SELF-CHECK DONE（{len(SHAPES)} 种形状的形状判定 + 消息投递与隔离）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(selftest())


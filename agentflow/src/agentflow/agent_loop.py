"""LLM 驱动的角色循环：模型决定调哪个工具、唤起谁、给谁留言，框架负责执行与留痕。

`draft/28` §178 的实测：A-H 里六个角色一份提示词都没有（C 两处、D 一处钩子）；更根本的是，角色之间没有一条"
由模型决定"的协作路径 —— `Conductor.summon` 是给编排层用的（`run_plan` 拿一份写死的计划去跑），于是"互相唤起
"只发生在脚本里。这一层把三件事接起来：提示词（`agent_prompts`）、模型缝（`llmseam`，每次调用带版本与哈希落
档）、工具与召唤（`ToolRegistry.call` 与 `Conductor.summon`，被拒的理由原样回到模型手里）。

循环形状（正典清单与条数只在 `SHAPES` 一处定义）：`{"tool": ...}` → `ToolRegistry.call(name, role=...)`，角
色面不对就 `role_denied`；`{"summon": ...}` → `Conductor.summon(..., by=<本角色>)`；`{"message": ...}` → 一
条 `agent_message` 事件（持久，收件人下次运行时在收件箱里看到）；`{"final": ...}` → 收工，带自报证据 id。

三态与"不许静默"：没接线 ⇒ 不发请求 + `stop_reason="not_wired"` 并落一条记录；坏 JSON ⇒ `bad_json_limit`（总
数 `run.bad_json` 与连击 `run.bad_json_streak` 分开记，判据是连击，§68）；参数不是合法 JSON（
`judge_bad_args`）另计 `run.bad_args` ⇒ `bad_args_limit`（§65）；没拿到可用回复（`judge_timeout` /
`judge_output_limit` / `judge_no_reply:<kind>`）另计 `run.no_reply` ⇒ `model_timeout` / `model_output_limit`
（判据与处置见 `LoopRun.no_reply` 与 `_no_reply_line`，读数见 2026-10-12 T2）；工具/召唤被拒带原因码并原样回
给模型；步数或预算耗尽则停，`stop_reason` 如实写进运行记录。消息落进项目会话记录（`sessions.append`，不新增
表），"读过哪些"用 append-only 的 `agent_inbox` 事件登记 ⇒ "投递"可复算。
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import agent_prompts as AP
from . import capabilities as C
from . import clock as CLK
from . import leanscope as _LEANSCOPE
from . import policy as P
from . import schema as S
from . import sessions as SS
from . import userio as U
from . import llmseam as LL
from . import promptstability as PSTAB
from . import stepdispatch as SD
from .llmseam import LlmSeam

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
    "（键名与嵌套层级照抄，`<...>` 与 `{...}` 是占位符）。把下面这些行**连括号一起抄**、"
    "只把占位符换成你的内容：不要自己数括号、也不要自己加一层嵌套 —— "
    "实测最常见的坏 JSON 就是最后多补一个 `}`：\n"
    '{"tool": "<工具名>", "args": {...}}\n'
    # 2026-10-25（审计 G/H/V/L 第 9 条）：骨架里不再有 `action` 这一格，也不再教 `A-H`
    # 这种角色级寻址 —— `_do_summon` 只读 `role` + `task` + `params`（形状里没有填动作的
    # 位置，见那里的注释），而寻址一律落在一个真的角色名上（伙伴表里那一格）。
    '{"summon": {"role": "<伙伴表里的角色名>", "task": "<一件可判定的活>", "params": {...}}}\n'
    '{"summon_many": {"targets": [{"role": "<伙伴表里的角色名>", "task": "<一件可判定的活>",'
    ' "instance": "<可选>"}], "why": "<为什么一次派这一批>"}}\n'
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
    # `final` 的层级曾经是错的（2026-10-11 修，业主口径"一切以代码为参考"）：
    # 骨架原写 `{"final": {"final": "<结论>", "evidence": []}}`（嵌套两层），而解码器读的是
    # 顶层 `{"final": <字符串>, "evidence": [...]}`（`_decode_shape` 的 final 那一支），
    # 原生工具面的 schema 也是顶层（`llmseam.py` 的 `framework_final`）。
    # 实测照抄骨架的后果：`final` 落成一个 JSON 字符串（`'{"final": "结论", …}'`）、
    # `evidence` 恒为空 —— 也就是"结论不是一句话、引用全丢"，而形状名两边都是 `final`，
    # 所以 `_shape_of` 那条同源判据照不到这一跳（判据只认形状名，不认字段怎么读）。
    # 判据（已扩到解码器那一跳）：`test_the_skeleton_and_the_parser_speak_the_same_shape`。
    '{"final": "<结论>", "evidence": ["<你实际用到的 id>"]}'
)

#: 公共频道。`message.to` 写它 = 所有人都能收到（说话，而不是派活）。
PUBLIC = "#public"

#: 公聊里"这条其实是在对某个具体代理下指令"的指令语气词表
#: （判据本体 `AgentLoop._public_addressee`；受控词表，加一个取值就是放宽一整格）。
#: 为什么需要这一格：业主 2026-10-19 第 5 条 —— `#public` 若保留，它是公告栏，
#: 不是对话；"公告栏里点名某人下指令"正是绕开名册的那条路（它进的是收件箱，
#: 而收件箱是按角色收的 ⇒ 同角色的所有实例都会读到）。
PUBLIC_DIRECTIVE_MARKS: tuple[str, ...] = (
    "请", "你去", "你要", "要你", "必须", "务必", "立刻", "马上", "尽快",
    "给我", "回我", "回复我", "执行", "照做", "去做", "来做",
)

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


def _first_call_action(face: Any, call: Any, shape: str, payload: Mapping[str, Any]) -> str:
    """这一步第一条调用的动作名（读数用：广告名映回真名，`fs_read` → `fs.read`）。

    只服务"逐条记账"的第一条那一格 —— 其余条目的名字由 `stepdispatch` 从载荷里取。
    取不到（没有原生面 / 没有调用表）就退回形状名，绝不编一个名字出来。
    """
    calls = tuple(getattr(call, "tool_call_list", ()) or ())
    if face is not None and calls:
        try:
            return str(face.action_name(calls[0]))
        except Exception:  # noqa: BLE001 —— 读数坏了不许带走这一步
            pass
    return SD.action_of(shape, payload)


# D-35 的读数"只执行第 1 条"到 2026-10-22 为止是本文件唯一处理"一步多条调用"的落点。
# 现在那件事搬到 `stepdispatch.catch_step_request`（接住 → 拆分 → 逐条执行 → 汇总），
# 理由与"为什么不能在循环里再写一段多条怎么办"见该模块 docstring。
# 本文件不再有"多条怎么办"的分支：循环只按 `StepDispatch.items` 逐条走同一条路
# （判据 `tests/test_multi_call_is_split_and_executed.py` 的"没有旁路"那一条扫源码）。


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


def _invalid_correction(step: int, problem: str, detail: str) -> str:
    """一个 invalid 步的纠正话术（按 `problem` 分档）—— 与 `resume_messages` 的取法同一份。

    为什么要一个名字：拆分口径里每条装不出来的调用也要落一对 assistant/tool 消息
    （续跑重建是按 `agent_step` 事件逐条重放的，只落事件不落消息会让重建出来的那一段
    比当时多两步）。那对消息的纠正话术必须与重建侧逐字相同，所以选档这件事只写一处。
    """
    if problem == "judge_bad_args":
        return _bad_args_line(step, detail)
    if problem == "judge_bad_json":
        return _bad_json_line(step, problem, detail)
    if _is_no_reply(problem):
        return _no_reply_line(step, problem, detail)
    return _invalid_line(step, problem)


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
    那一份（`_for_record` 之前），所以那一句成立；`_result_half` 内部那次观测层的
    截断仍按它自己的口径剪一次，那是模型实际看到的那一份 —— 计价要按
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


#: 「没拿到可用的回复」的那一档（`LoopRun.no_reply`）里有名字的两个成员：
#: 超时、以及"输出预算被思考吃光"。第三族 `judge_no_reply:<error_kind>` 带后缀，
#: 不能写成元组里的一个字面量 —— 成员判据只有 `judge.is_no_reply` 一处，
#: 本常量留在这里是给读的人看这一档有哪几张脸（不再参与判定）。
_NO_REPLY_NAMED: tuple[str, ...] = ("judge_timeout", "judge_output_limit")


def _is_no_reply(problem: str) -> bool:
    """这一档的成员判据 —— 转发 `judge.is_no_reply`（`judge_no_reply:<kind>` 那一族带后缀）。

    为什么不在这里就地判（2026-10-15 T5 第 8 趟 `t5h` 的真机读数）：本函数此前不存在，
    这里拿的是上面那张两元组，而网关把 DNS 失效折成 `error_kind="network"`
    ⇒ 落成 `judge_no_reply:network` ⇒ 不在元组里 ⇒ 被算进坏 JSON，
    三次连击把 run 判成 `bad_json_limit`、收场那句话还说"模型没给出可解析的 JSON"。
    成员表在 `judge`（失败码的唯一定义处），这里只许转发。
    """
    from . import judge as J   # 惰性：`agent_loop` 的 import 面已经很宽，不在这里加一条

    return J.is_no_reply(problem)


def _no_reply_line(step: int, problem: str, detail: str) -> str:
    """这一次没拿到可用的回复（`judge_timeout` / `judge_output_limit` / `judge_no_reply:*`）
    要回给它的那一句。

    为什么不复用"坏 JSON"那一行（2026-10-12 T2 真机读数）：那一行纠正的是"它说错了"，而这里它什么都没说；可
    行动的那句话是"把这一步拆小"—— 上限固定时，唯一由它控制的就是这一步要产出多少（单次请求的耗时与这一步要
    产出的长度成正比）。

    第三档（2026-10-15 T5 第 8 趟）：`judge_no_reply:<kind>` 是"我们根本没连上"（那一趟是 DNS），这一档里它
    没有任何可改的地方 ⇒ 那一行不许写"把这一步拆小"，只如实说明并把同样的请求再发一次。
    """
    why = f"：{_clip(detail, 200)}" if detail else ""
    if problem == "judge_output_limit":
        head = (f"\n\n[第 {step + 1} 步] 框架：上一条回复把**输出预算全花在思考上**了"
                f"（{why}）—— 正文一个字都没留下。处置：**下一步只回一行 JSON**，"
                "把想法压到十句以内（推理与正文共用同一份输出预算）；"
                "这一步要做的事如果本来就大，就把它拆小。")
    elif problem.startswith("judge_no_reply:"):
        head = (f"\n\n[第 {step + 1} 步] 框架：上一条请求**没送到 / 没回来**（{why}）—— "
                "这一次不是你回了坏东西，也不是这一步太大，是这台机器到模型的那条路"
                "这一会儿不通（网关已经按重试次数试过）。**你什么都不用改**："
                "把同样这一步再做一遍即可；如果连着几次都不通，这一趟会停下来并把原因写清。")
    else:
        head = (f"\n\n[第 {step + 1} 步] 框架：上一条请求**没等到返回**（超时{why}）—— "
                "不是你回了坏东西，是这一条回复在规定时间内没有回来。处置：**把这一步拆小**"
                "（一次只做一件事、只派一个 target，长产物先落盘再用路径引用），"
                "单次回复短了才来得及返回。")
    return head + "然后照旧只回一行 JSON。骨架：\n" + JSON_TAIL


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


#: 开场那条 user 消息要念的事实（`_opening_transcript` 的入参键）——一处列名。
#:
#: 它与 `promptstability.STEP_VOLATILE_FACTS` 里"跨 run 会变"的那几格同源：
#: 那些格从 system 挪出来之后，真值就住在这条消息里（判据
#: `tests/test_cross_run_prefix_is_reused.py` 逐个名字对账两处，少了谁就红）。
#:
#: 2026-10-21 第二批（`availability` / `parent_limits`）：这两格不是"这一趟活的事实"，
#: 而是"这一次 run 的配置"—— 前者随伙伴配置变（谁配了 provider / key），后者随
#: `Policy` 变（`cli.py` 每趟用 `wall_clock_sec` / `usd_budget` 现造）。它们此前住在
#: system 的 `PARTNER_AVAILABILITY`（段序 4520）/ `PARENT_LIMITS`（段序 5210）里，
#: 于是换一次配置 ⇒ M 的 system 从 63% / 88% 处断开（本机实测）。落点与那十格同一个：
#: 开场这一条消息（消息不是前缀）。
OPENING_FACT_KEYS: tuple[str, ...] = (
    "task", "inbox", "board", "children", "user_replies",
    "summoned_by", "task_id", "depth", "parent_task_id", "workspace_root",
    "availability", "parent_limits",
    # 2026-10-22（业主 B-3）：我名下被 V 判「有毛病」的证明明细。它与上面十二格同一个
    # 落点（开场那条 user 消息），因为它是"这一趟要补哪几条"的活账 —— 换一趟活/V 多签
    # 一签，它就不同；放进 system 会让前缀在每一签之后作废。
    "v_rejections",
)


def opening_facts(facts: Mapping[str, Any]) -> dict[str, Any]:
    """开场那条消息里真的念出来的那十三格（缺省句已代入）—— 落事件用这一份。

    为什么要代入缺省（而不是落原始值）：`agent_run_start.opening_facts` 的读者是
    "这一趟的模型到底读到了什么"。原始值里的空串在消息里会被 `prompt_facts` 换成
    一句人话（"（此刻名下没有子代理）"），落原始值就答不出那个问题 ——
    而"读到了什么"正是判据要断言的那件事（`tests/test_cross_run_prefix_is_reused.py`：
    逐格断言"在 user 消息里、不在 system 里"）。

    代入是幂等的：把这些值再喂回 `_opening_transcript`（续跑重建走那条路）
    得到同一句话，所以"重建 == 当时那一份"不受这一层影响。
    """
    defaulted = AP.prompt_facts(**{k: facts[k] for k in OPENING_FACT_KEYS})
    return {k: defaulted[k] for k in OPENING_FACT_KEYS}


def _opening_transcript(task: str, *, inbox: str, summoned_by: str, task_id: str,
                        depth: int, parent_task_id: str = "", children: str = "",
                        board: str = "", user_replies: str = "",
                        workspace_root: str = "", availability: str = "",
                        parent_limits: str = "", v_rejections: str = "") -> str:
    """一趟循环开头的简报（任务 / 父与子 / 用户回答 / 处境 / 派活上限）。

    ## 为什么这里没有「收件箱」与「板」两格（D-52，业主 2026-10-24 的口径）

    开场这一条消息是快照：谁派的、深度、台账号、名册、工作区 —— 一趟定一次，
    续跑要能逐字重建它（`tests/test_user_channel_stop_and_resume.py` 的
    `rebuilt == run.messages` 就是这条判据）。

    而留言与板项是流水：跑到一半子代理交差、父代理回复、V 的判决、计时器到点，
    每一步都可能新增。它们此前也被塞在快照里（开卷九格里的 `inbox` / `board`），
    于是"这一趟开头听到了什么"被冻在第一条消息里。开卷之后唯一还会送东西的是
    "一步执行完之后听一次"那条耳朵（`AgentLoop._hear`），而它对这些步都不发生：
    `invalid` / 没拿到回复 / 正在阻塞等子 / 收工那一步。真机现场（`projects/sylow3`，
    只读读数）：t-000031 / t-000038 在 17:44:42 / 17:45:45 落成 `item_state=queued`，
    收件人 t-000003 直到 18:05:06 那次阻塞式派活返回、步 8 执行完才被那条耳朵送到
    （19 分钟；它在这 19 分钟里一步都没有），而"送过没有"在盘上一条记录都没有
    （`seen_step=8` 查不到对应的投递事件）。所以缺的不是"再调一次渲染"，是
    "把流水的投递口从'上一步的耳朵'改成'每一次 ask_step 之前的一次读数'"。

    所以两格搬去了 :func:`mailbox_digest` / `AgentLoop._deliver_mailbox`：每一次
    `ask_step` 之前现算一次"发给我、还没读过的"那批，作为一条独立的增量消息投进去
    （不是重渲染开卷：重渲染会同时破坏续跑可重建性与去重）。三个后果都是刻意的：

    1. 快照里不再有流水 ⇒ 开场那一段与"之后到了什么"不再互相覆盖；
    2. `inbox` / `board` 两个形参仍然留着（它们仍在 `OPENING_FACT_KEYS` 与
       `agent_run_start.opening_facts` 里，是这一趟开头的读数），但一个字都不再渲染
       —— 判据 `tests/test_mailbox_delivers_mid_run_and_wakes_the_parent.py` 的第 3 条
       钉着"开卷那段不再包含 board/inbox 两格"；
    3. 流水只有一条通道、一个状态机（板项 `queued → seen`，留言 `agent_inbox` 投递登记），
       "投过没有"因此可复算（append-only 的 `agent_mailbox` 事件）。

    2026-10-21 起其余各格从 system 搬来（跨 run 也命中缓存）：`AGENT_IDENTITY`（段序 0）
    的 `task_id` / `depth` / `children` / `parent_task_id` / `summoned_by`、
    `TASK_FRAME`（4200）的 `task` / `user_replies`、`WORKSPACE_FACTS`（10000）的
    `workspace_root` 都是"这一趟的事实"（实测两份不同的活从第 95 个字符起就不同 ⇒
    换一趟活第一次调用 `hit=0`）；现在只在这条消息里念一遍（缺省句唯一来源仍是
    `agent_prompts.prompt_facts`），system（前缀）逐字节不变。第二批 `availability`
    / `parent_limits` 同搬（属"这一次 run 的配置"，原住 `PARTNER_AVAILABILITY` 4520 /
    `PARENT_LIMITS` 5210，换配置在 63% / 88% 处断开），system 只剩静态指路语
    （`PARTNER_WIRING_POINTER` / `PARENT_LIMITS_RULES`）。
    """
    defaulted = AP.prompt_facts(task=task, summoned_by=summoned_by, task_id=task_id,
                               depth=depth, parent_task_id=parent_task_id,
                               children=children, board=board, inbox=inbox,
                               user_replies=user_replies, workspace_root=workspace_root,
                               availability=availability, parent_limits=parent_limits,
                               v_rejections=v_rejections)
    # `inbox` / `board` 仍然过一遍 `prompt_facts`（缺省句的代入口只有那一处），
    # 但这里刻意不把 `defaulted['inbox']` / `defaulted['board']` 念出来：它们是流水，
    # 归属 `_deliver_mailbox`（见 docstring 的第一节）。
    return (f"你的任务：{defaulted['task']}\n\n"
            # 业主 2026-10-22 的 B-3：「V 的判决必须递到 F（让 F 去修）」。这一栏是
            # "V 已经判过、判的是有毛病"的逐条读数（数据源只有 V 的台账）。
            f"我名下被 V 判「有毛病」的证明（逐条读 V 的台账）："
            f"{defaulted['v_rejections']}\n\n"
            f"你名下的子代理（名册摘要：名字 · 一句简介 · 状态；"
            f"这是这一趟开始那一刻的快照）：{defaulted['children']}\n\n"
            f"用户回答过的问题（含迟到送达的回答）：{defaulted['user_replies']}\n\n"
            f"现在的接线态（谁当前真的能被唤起；没接线的派了也会被拒）：\n"
            f"{defaulted['availability']}\n\n"
            f"你的派活上限（四类数字现算）：\n{defaulted['parent_limits']}\n\n"
            f"你的处境：由 {defaulted['summoned_by']} 发起，"
            f"召唤链深度 {defaulted['depth']}，台账号 {defaulted['task_id']}；"
            f"父代理台账号：{defaulted['parent_task_id']}；"
            f"工作区根目录：{defaulted['workspace_root']}。")


def _is_role_name(value: str) -> bool:
    """`value` 是不是一个真角色名（`schema.ROLES` 或主控）。

    为什么需要它：`tasks.called_by` 这一格对顶趟写的是 `"user"`
    （`Conductor.open_top_level_run(by="user")`），而 `"user"` 不是角色
    —— 把它当收件人角色传给 `open_item` 会被 `Task.validate` 拒掉
    （实测：`role 必须是 (…) 之一，收到 'user'`，于是终态通报一条都落不成）。
    角色名单的唯一来源是 `schema`（`ROLES` + `CONDUCTOR_ROLE`），这里照读、不抄。
    """
    return value in (*S.ROLES, S.CONDUCTOR_ROLE)


def _message_landed(result: Mapping[str, Any]) -> bool:
    """这一步的留言真的落成了没有（`LoopRun.messages_sent` / `messages_refused` 的唯一判据）。

    为什么不能只看 `shape == "message"`（2026-10-22 查实的那条缺陷）：受控拒绝
    （`not_in_roster` / `not_an_edge` / `member_retired` / `public_is_not_a_conversation`
    / `no_task_id` / `broadcast_only`）同样产出一行 `shape == "message"` 的步，而它
    一条都没落盘。旧实现按形状数，于是 D 发给 E 的那一条被 `not_in_roster` 拒掉时，
    回执照报 `messages_sent == ["E"]`，而 E 的收件箱是空的 —— 回执把"尝试过"读成了
    "发成了"（`tests/test_a_message_receipt_never_lies.py` 守这一条）。

    判据两条，缺一不可：
    1. 没有受控拒绝理由码（`refused` 为空）：被拒的那一步没有落点；
    2. 有落点，且回执态说得过去：`message_sent`（会话里那条 `agent_message` 的编号）
       或 `item_id`（收件人名下的板项编号）任一非空 —— 这两个编号是"真的落成了"唯一
       能事后核的东西；同时回执态要么是 `ok` 真，要么是 `receipt="no_reader"`
       （"落盘了，但此刻没有任何进程会读它"）。

    为什么第 2 条不写成"`ok` 为真"：`ok` 在角色通道与公共频道上量的是"收件人有没有
    读者"（见 `_message_by_channel` 的 `receipt` 三态），`ok=False` + `receipt="no_reader"`
    的那一步留言确实落盘了、收件人的收件箱或板上读得到，只是没有进程会主动去读它 ——
    那是"没人读"，不是"没发出"。把这一档折成"没发出"，`messages_sent` 就会反过来少报
    （三条已登记的判据量的正是"落盘了"：`test_agent_loop.py::
    test_messages_are_durable_and_reach_only_the_recipient` /
    `test_a_role_can_send_a_private_message_to_the_conductor` 与
    `test_shape_vs_value_errors.py::test_to_all_is_the_public_channel`；
    `test_inbox_delivery.py` 另有一条把 `ok is False` 钉在 `no_reader` 这一档上）。
    """
    if not isinstance(result, Mapping):
        return False
    if str(result.get("refused") or ""):
        return False
    landed = str(result.get("message_sent") or "") or str(result.get("item_id") or "")
    if not landed:
        return False
    return result.get("ok") is True or str(result.get("receipt") or "") == "no_reader"


#: 这一步的结局里"没有派出去"的那几档（`_summon_landed` 判据 1 的取值表）。
#:
#: `refused`：策略/闸门说的"不"（`Conductor._refuse` 会为它写一行台账，所以那一行
#: 也有 `task_id` —— 光看编号会把被拒读成"派出去了"）；`cancelled`：取消之后不产生
#: 新任务；`wash_proposed`：两段式的第一段，结果自己写着"这一趟没有派活"。
SUMMON_NOT_DISPATCHED: tuple[str, ...] = ("refused", "cancelled", "wash_proposed")


def _summon_landed(result: Mapping[str, Any]) -> bool:
    """这一步的召唤真的派出去了没有（`LoopRun.summons` / `summons_refused` 的唯一判据）。

    为什么不能只看 `shape == "summon"`（2026-10-22 查实的那条缺陷）：两种"形状对、
    什么也没派出去"的步同样产出一行 `shape == "summon"`：

    1. 受控拒绝（`forbidden_edge` / `depth_exceeded` / `invalid_params` / `no_owner` …）
       —— `Conductor._refuse` 会为被拒的那一次写一行 `outcome="refused"` 的台账行，
       于是 `task_id` 非空、看起来像"有落点"，但一个子代理都没有被唤起
       （现场：C 想唤 A，被 `forbidden_edge` 拒，而回执照报 `summons == ["A"]`）；
    2. 两段式洗格式请示（`outcome="wash_proposed"`、`executed=False`）—— 结果自己
       写着"这一趟没有派活（0 行新任务、0 次子任务调用）"（现场：D 的回执照报 `["D"]`）。

    判据三条，缺一不可：

    1. 没有受控拒绝：`refused` 与 `refusal_reason` 都空，且 `outcome` 不在
       :data:`SUMMON_NOT_DISPATCHED` 里、`status` 不是 `cancelled`；
    2. 不是"请示/没执行"：`executed` 不许是 `False`（两段式第一段显式写这一格）；
    3. 有落点，且那一步说得出"派出去了"：`task_id` 非空 —— 被拒的那一行也有编号，
       所以第 1 条必须先判；派出去之后失败的（`status="failed"`）算派出去了
       （子代理真的跑过，只是跑坏了），回执不许把"派了没成"折成"没派"。

    为什么第 3 条不写成"`ok` 为真"：`SummonResult.ok` 的判据是
    `status == "done" and outcome == "ok"`，于是 `no_result` / `not_applicable`
    这些"跑完了、只是没东西"的召唤会被读成"没派出去"—— 那是反过来少报，与这边要治的
    缺陷同形（同一个取舍见 :func:`_message_landed` 的 docstring）。
    """
    if not isinstance(result, Mapping):
        return False
    if result.get("executed") is False:
        return False
    if str(result.get("refused") or "") or str(result.get("refusal_reason") or ""):
        return False
    if str(result.get("outcome") or "") in SUMMON_NOT_DISPATCHED:
        return False
    if str(result.get("status") or "") == "cancelled":
        return False
    return bool(str(result.get("task_id") or ""))


@dataclass(frozen=True)
class LoopStep:
    """循环里的一步：模型说了什么、框架做了什么、结果是什么。"""

    index: int
    shape: str
    payload: Mapping[str, Any]
    result: Mapping[str, Any]
    problem: str = ""
    #: 这一步那次模型调用的缓存读数（`promptstability.prompt_cache_record`）。
    #:
    #: 为什么它必须挂在 `step` 上（2026-10-19）：上游的
    #: `usage.prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` 从 2026-10-14 起
    #: 就已经被读进来了（`llmseam` 的 `SeamCall.cache_hit_tokens` 两格，计价也按两档算了），
    #: 但它们从没进过任何 run 记录 —— 于是"这一趟到底命中没命中"在事后
    #: 一条都答不出来，而它正是"提示词前缀稳不稳定"这件事唯一的端到端读数。
    #: 空 dict = 这一步没有模型调用（不是"零命中"——那是 `hit=0`）。
    cache: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """落会话记录用的扁平结构（模型说了什么、框架做了什么、结果是什么）。"""
        return {"index": self.index, "shape": self.shape, "payload": dict(self.payload),
                "result": dict(self.result), "problem": self.problem,
                # 三态：`prompt_cache` 这个键在、内容是 unknown（上游没给读数），
                # 与"这个键根本没有"（写入被删掉）必须分得开。
                "prompt_cache": dict(self.cache)}


@dataclass


class LoopRun:
    """一次角色运行的完整记录（含每一步与提示词审计读数）。"""

    role: str
    task: str
    steps: list[LoopStep] = field(default_factory=list)
    final: str = ""
    evidence: list[str] = field(default_factory=list)
    stop_reason: str = "final"
    #: 优雅停止时框架翻成 `block` 的那批任务/委托（业主 2026-10-13：
    #: 「接收到停的时候，剩余任务委托状态自动变成block」+「最终由M整理汇报用户」）。
    #: 形状取自 `stopctl.block_remaining_tasks` 的读数：`{checked, blocked, blocked_items, why}`。
    #: 它是"停的时候手上还剩什么"的唯一读数 —— 父在子结果里读它，M 再汇总进交付说明。
    blocked_remaining: dict[str, Any] = field(default_factory=dict)
    prompt_audit: dict[str, Any] = field(default_factory=dict)
    #: 这一趟的提示词缓存汇总（`promptstability.summarize_prompt_cache`）：
    #: `{calls, hit, miss, unknown_calls, hit_rate, mismatched_calls, saved_usd,
    #:   saved_unknown_calls, why}`。
    #:
    #: 为什么它是 `LoopRun` 的一等字段而不是从 `steps` 现算：收工那一行要打印它，
    #: 而"收工那一行"的读者（人、Web UI、下一次运行）手上没有 `LoopRun` 对象；
    #: 同时它也是"前缀稳不稳"这条判据在真机上的唯一读数 —— 没有它，
    #: 提示词改动的效果就只能在离线判据里看，真机花的钱买不到任何证据。
    prompt_cache: dict[str, Any] = field(default_factory=dict)
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
    #: 「没拿到可用的回复」的总数与连击数 —— 与上面两档分开计。
    #:
    #: 这一档装的不是"它说错了"，而是"它没有给出可用的回复"，今天有两个成员：
    #: `judge_timeout`（我们没等到返回）与 `judge_output_limit`（输出预算被思考吃光）。
    #:
    #: 为什么必须有这一档（2026-10-12 第一次无 Lean T2 真机读数）：步 1 连着三次
    #: `detail=超过 60.0s 未返回`、步 2/18 是"思维链 109,397 / 96,969 字而正文一个字没有"，
    #: 而它们当时都落成 `judge_failed:ModelReplyNotOk` ⇒ 计数进 `bad_json_streak`、
    #: 收场措辞是"连续 3 次没有给出可解析的 JSON"。那句归因是错的：模型没有"给出"
    #: 任何东西 —— 一端是我们在等另一端（超时），另一端是它把预算全花在思考上。
    #: 归因错的后果不是难看，是修错地方：坏 JSON 的处置是收紧输出协议，
    #: 超时的处置是调大上限，输出吃光的处置是把这一步拆小、把思考压短 —— 三个方向。
    #: 于是给它自己的计数与自己的停止理由（`model_timeout` / `model_output_limit`）。
    no_reply: int = 0
    no_reply_streak: int = 0
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
    #: ---- 信箱与唤醒的两个收口读数（D-52 / D-53）
    #:
    #: 业主的施工单第 ④ 条要两个数："这一趟投递了多少条 / 唤醒了几次"。
    #: 读数落在 `agent_run_end`（与 `agent_mailbox` / `agent_wake` 那两条事件同源），
    #: 于是"投了几条"既能从事件流逐条复算，也能从收工那一行一眼读到。
    #:
    #: `mailbox_items` / `mailbox_msgs` 是这一趟投进去的 id（按投递顺序）：
    #: 只报 count 的话，"投的是哪几条"还得去翻事件；而"投过没有"正是 D-52 要回答的问题。
    mailbox_items: list[str] = field(default_factory=list)
    mailbox_msgs: list[str] = field(default_factory=list)
    #: 监控回合数与唤醒标记数（`wake_ids` 逐条点名）。
    monitor_turns: int = 0
    wakes: int = 0
    wake_ids: list[str] = field(default_factory=list)
    #: 唤醒事件的明细（`wake_id` / `reason` / `due_at` / `mailbox_item_id`）：
    #: 收工那一行要能回答"为什么被叫醒"，而不只是"叫醒过几次"。
    wake_events: list[dict[str, Any]] = field(default_factory=list)
    #: 推了几次时钟 / 推响了几条计时器（D-53 的生产端读数）。
    clock_pumps: int = 0
    clock_fired: int = 0
    elapsed_sec: float = 0.0
    notes: list[str] = field(default_factory=list)
    #: 「收工那一步」的原始载荷（模型给的 `final` / `evidence` / `notify` 逐字一份）。
    #: 为什么要加这一格（2026-10-08 真机读数）：`shape == "final"` 那一支在 `run()` 里 `break`，
    #: 而 `agent_step` 事件在 break 之后的公共尾段落 ⇒ 收工这一步的事件从不落盘（`tests/test_status_report.py`
    #: 的 `len(steps) == 2 and len(run.steps) == 3` 钉着它），于是 `notify` 与 `evidence` 只活在内存里
    #: （现场 `projects/p5-review-t17/sessions/t1q.jsonl`：`agent_run_end` 只留结论文本与哈希 —— 全仓 17.3MB
    #: 会话里没有一条 `agent_step` payload 带 `notify`）。不改成"给 final 补一条 `agent_step`"：那会把收工那一步
    #: 塞进 `resume_transcript` 重拼的简报，"重建的那一段"与"当时拼的那一段"不再逐字相等 —— 而那正是续跑判据
    #: `tests/test_user_channel_stop_and_resume.py::test_resume_messages_is_item_equal_to_the_live_sequence` 守的东西。
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
    #: 这一趟每次派活产生了哪些子产出（`_call_productions` 的条目，按发生顺序）：
    #: `{kind, counted, task_id, role, step, status, outcome, handoff_id, outputs,
    #:   disposition, evidence?, recon_only?, waiver?}`。
    #:
    #: 为什么它是一个一等字段（而不是收工时从 `steps` 现算）：业主的规矩是
    #: 父代理必须处理子代理的产出，而"这一次调用产出了什么"要在调用那一刻
    #: 就落下来 —— 会话事件里同样有一份（`agent_step.productions`），
    #: 两处同源（`_call_productions` 只实现一次）。
    productions: list[dict[str, Any]] = field(default_factory=list)
    #: 子产出的处理读数（业主裁定：父必须处理子产出）。口径见 `summon_consumption`：
    #: `summons_total`（有产出的子任务数）、`summons_consumed`（留下了指到它的效应）、
    #: `summons_waived`（写了受控的 `not_consumed`）、
    #: `summons_unconsumed`（既没效应也没声明 —— 判据要抓的那一格）。
    #: `summons_continued` 是 `summons_consumed` 的细分（其中"再派活"的有几条），
    #: 是读数不是判据。
    #:
    #: 为什么是一等字段：收工那一行（`agent_run_end`）要打印它，而那一行的读者
    #: （人、Web UI、下一个父代理）手上没有 `LoopRun` 对象 —— 这条规矩唯一的
    #: 执行面就是"读数看得见"。
    summons_total: int = 0
    summons_consumed: int = 0
    summons_continued: int = 0
    summons_waived: int = 0
    summons_unconsumed: int = 0
    #: 那份明细（`summon_consumption()` 的完整返回：逐条处置 + 不成立的拒绝说明）。
    summon_consumption: dict[str, Any] = field(default_factory=dict)
    #: 收工那一刻"名下还有几条证明没有 V 的签字"（D12 的读数）：
    #: `{checked, total, unsigned, stmt_ids, unreadable, reason}`。
    #:
    #: 为什么要有这一格（业主 2026-10-22「final 无未了义务读数」）：`shape == "final"` 那一支
    #: 在收到就 `break` —— 模型说"做完了"，框架就把这句话当结论落盘，而"还有两条证明没送
    #: V、或送了被判定有毛病"这件事在收工那一行上一个字都没有。读者（人 / 父代理 / Web UI）
    #: 于是拿到一份看起来完整的交付，欠账只在事后翻 `verifications` 时才发现。
    #:
    #: 只做读数：不打回、不拦、不改 `stop_reason`、不改退出码 —— 这一格的用处是让"它说做完了"
    #: 与"它名下还有没签住的证明"在同一行上并排出现，由读的人决定怎么办。
    #: 口径与 `v_rejections_digest` / 收工门 R10 同一处判据（`verifications.statement_review_reading`）：
    #: `unsigned` 数的是"`proof_text` 非空、而最近那一签不是 `signed`"的那些命题
    #: （`rejected` / `stale` / `unsigned` / `unreadable` 都算未了 —— 读不出来的不许折成签过了）。
    #: 刻意不进 `to_dict()`：那是交付面（`runs/*.json`），这一格是读数，落在 `agent_run_end` 上。
    final_gaps: dict[str, Any] = field(default_factory=dict)
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
        """这次运行真的派出去的召唤（按发生顺序，可重复）。

        判据是 :func:`_summon_landed`（看那一步的结果有没有真的开出一行子任务），
        不是 `shape == "summon"`。受控拒绝（`forbidden_edge` 之类）与两段式请示
        （`wash_proposed`）也是 `shape == "summon"` 的步，把它们数进来就是回执说谎
        （2026-10-22 查实：C 想唤 A 被 `forbidden_edge` 拒掉、D 的两段式请示 0 行新任务，
        旧实现仍分别报 `["A"]` / `["D"]`）。没派出去的那些逐条进 :attr:`summons_refused`。
        """
        return [str(s.payload.get("role") or "") for s in self.steps
                if s.shape == "summon" and _summon_landed(s.result)]

    @property
    def summons_refused(self) -> list[dict[str, Any]]:
        """这次运行里"尝试过但没派出去"的召唤，逐条点名（按发生顺序）。

        每一条 `{to, refused, outcome, error}`：
        - `to`：模型写下的角色（与 `summons` 同一格口径，便于对账）；
        - `refused`：受控拒绝的理由码（`forbidden_edge` / `depth_exceeded` /
          `invalid_params` / `no_owner` / `member_retired` …；那一格在派活结果里叫
          `refusal_reason`，这里与 `refused` 合并成同一格）；空串表示那一步没有理由码，
          此时看 `outcome`（例如两段式的 `wash_proposed`：不是被拒，是在等父表态）；
        - `outcome`：那一步的结局（`refused` / `wash_proposed` / …）——「被拒」与
          「等你表态」在读数上就靠它分开；
        - `error`：那一步给模型/人读的那句话（没有 `error` 时取 `detail`，再退到 `note`）。

        为什么它与 `summons` 是一对：只报"真派出去的"会让"被拒/在请示"在回执上消失
        （同一个缺陷的另一半，与 `messages_sent` / `messages_refused` 同形）。
        """
        out: list[dict[str, Any]] = []
        for s in self.steps:
            if s.shape != "summon" or _summon_landed(s.result):
                continue
            result = s.result if isinstance(s.result, Mapping) else {}
            out.append({"to": str(s.payload.get("role") or ""),
                        "refused": str(result.get("refused")
                                       or result.get("refusal_reason") or ""),
                        "outcome": str(result.get("outcome") or ""),
                        "error": str(result.get("error") or result.get("detail")
                                     or result.get("note") or "")})
        return out

    @property
    def messages_sent(self) -> list[str]:
        """这次运行真的发出去的留言（按发生顺序，可重复）。

        判据是 :func:`_message_landed`（看那一步的结果有没有落点），不是 `shape == "message"`。
        被受控拒掉的那一步也是 `shape == "message"`，把它数进来就是回执说谎（2026-10-22
        查实：D 发给 E 的那一条被 `not_in_roster` 拒掉，旧实现仍报 `["E"]`，而 E 的收件箱
        是空的）。没落成的那些逐条进 :attr:`messages_refused`。
        """
        return [str(s.payload.get("to") or "") for s in self.steps
                if s.shape == "message" and _message_landed(s.result)]

    @property
    def messages_refused(self) -> list[dict[str, Any]]:
        """这次运行里"尝试过但没落成"的留言，逐条点名（按发生顺序）。

        每一条 `{to, refused, receipt, error, how}`：
        - `to`：模型写下的收件人（与 `messages_sent` 同一格口径，便于对账）；
        - `refused`：受控拒绝的理由码（`not_in_roster` / `not_an_edge` / `member_retired` /
          `public_is_not_a_conversation` / `no_task_id` / `broadcast_only` …）；空串表示
          那一步没有理由码，此时看 `error` 里那句说明（它照样没落成）；
        - `receipt`：那一步的回执态（没落成时通常是 `unknown`，不许读成"送到了"）；
        - `error`：那一步给模型/人读的那句话（没有 `error` 时取 `note`）；
        - `how`：寻址判据的结论（`addressing.how`）—— `not_in_roster`（不在父∪子里）与
          `not_an_edge`（没有协作边）在读数上就靠它分开。

        为什么它与 `messages_sent` 是一对：只报"发出去的那几条"会让"被拒"在回执上消失
        （同一个缺陷的另一半：回执不能说谎，也不能只说好消息）。
        """
        out: list[dict[str, Any]] = []
        for s in self.steps:
            if s.shape != "message" or _message_landed(s.result):
                continue
            result = s.result if isinstance(s.result, Mapping) else {}
            addressing = result.get("addressing")
            addr = addressing if isinstance(addressing, Mapping) else {}
            out.append({"to": str(s.payload.get("to") or ""),
                        "refused": str(result.get("refused") or ""),
                        "receipt": str(result.get("receipt") or ""),
                        "error": str(result.get("error") or result.get("note") or ""),
                        "how": str(addr.get("how") or "")})
        return out

    def to_dict(self) -> dict[str, Any]:
        """一次运行的完整记录（每一步 + 提示词审计 + 用量 + 停止原因）。

        顶层键集合（逐格，顺序即声明序）：
        `role` / `task` / `steps` / `final` / `evidence` / `stop_reason` / `bad_json` /
        `blocked_remaining` / `bad_json_streak` / `bad_args` / `bad_args_streak` /
        `no_reply` / `no_reply_streak` / `dead_loop_max` / `same_call_max` /
        `stalled_max` / `dead_loop_nudges` / `stalled_nudges` / `dead_loop_stopped` /
        `counters_reset_at` / `compactions` / `mailbox_items` / `mailbox_msgs` /
        `mailbox_delivered` / `monitor_turns` / `wakes` / `wake_ids` / `wake_events` /
        `clock_pumps` / `clock_fired` / `waiting_for` / `resumed_from` /
        `notify_rejections` / `handoffs` / `summons` / `summons_refused` /
        `messages_sent` / `messages_refused` / `productions` / `summons_total` /
        `summons_consumed` / `summons_continued` / `summons_waived` /
        `summons_unconsumed` / `summon_consumption` / `prompt_audit` / `spend` /
        `prompt_cache` / `elapsed_sec` / `notes` / `final_payload`。

        （D-52/D-53 那九格此前漏在这份清单外：`mailbox_*` / `monitor_turns` /
        `wake*` / `clock_*` —— 判据 `tests/test_summons_and_numbered_addressing.py::test_to_dict_documents_every_key_it_returns`
        要求两个方向都相等，所以"加了键没补文档"会当场红。这里补齐的是文档，不是行为。）

        `summons` 与 `summons_refused` 是同一件事的两半，判据都在
        :func:`_summon_landed`：前者只记真的开出了子任务的召唤，后者逐条点名"尝试过但
        没派出去"的那几条（`to` / 理由码 / 结局）。只报前者会让"被拒 / 在请示"在回执上
        消失 —— 那正是 2026-10-22 查实的那条缺陷（C 唤 A 被 `forbidden_edge` 拒掉仍报
        `["A"]`；D 的两段式请示 0 行新任务仍报 `["D"]`）。

        `messages_sent` 与 `messages_refused` 是同一件事的两半，判据都在
        :func:`_message_landed`：前者只记真的落成的收件人，后者逐条点名"尝试过但没落成"
        的那几条（`to` / 理由码 / 回执态）。只报前者会让"被拒"在回执上消失 —— 那正是
        2026-10-22 查实的那条缺陷（D 发给 E 被 `not_in_roster` 拒掉，回执照报 `["E"]`）。
        """
        return {
            "role": self.role, "task": self.task,
            "steps": [s.to_dict() for s in self.steps],
            "final": self.final, "evidence": list(self.evidence),
            "stop_reason": self.stop_reason, "bad_json": self.bad_json,
            "blocked_remaining": dict(self.blocked_remaining),
            "bad_json_streak": self.bad_json_streak,
            "bad_args": self.bad_args, "bad_args_streak": self.bad_args_streak,
            "no_reply": self.no_reply,
            "no_reply_streak": self.no_reply_streak,
            "dead_loop_max": self.dead_loop_max, "same_call_max": self.same_call_max,
            "stalled_max": self.stalled_max,
            # 两档分开报（裁定 10丙）：提醒了几次 / 有没有因此判停 / 账从第几步算起。
            "dead_loop_nudges": self.dead_loop_nudges, "stalled_nudges": self.stalled_nudges,
            "dead_loop_stopped": self.dead_loop_stopped,
            "counters_reset_at": self.counters_reset_at,
            # S-B：这一趟压了几次（0 = 一次都没压；与"没启用"那一档合起来读）。
            "compactions": self.compactions,
            # D-52 / D-53 的两个收口读数：投了几条（板项 / 留言分别列 id）、
            # 唤醒了几次（编号逐条点名）、监控回合数、推时钟的次数与推响的条数。
            "mailbox_items": list(self.mailbox_items),
            "mailbox_msgs": list(self.mailbox_msgs),
            "mailbox_delivered": len(self.mailbox_items) + len(self.mailbox_msgs),
            "monitor_turns": self.monitor_turns,
            "wakes": self.wakes,
            "wake_ids": list(self.wake_ids),
            "wake_events": [dict(e) for e in self.wake_events],
            "clock_pumps": self.clock_pumps,
            "clock_fired": self.clock_fired,
            "waiting_for": self.waiting_for, "resumed_from": self.resumed_from,
            "notify_rejections": self.notify_rejections, "handoffs": list(self.handoffs),
            "summons": self.summons,
            # 召回收执的另一半（2026-10-22）：尝试过但没派出去的那几条逐条点名，
            # 与 `summons` 同一份判据（`_summon_landed`）。
            "summons_refused": self.summons_refused,
            "messages_sent": self.messages_sent,
            # 回执的另一半（2026-10-22）：尝试过但没落成的那几条逐条点名，
            # 与 `messages_sent` 同一份判据（`_message_landed`）。
            "messages_refused": self.messages_refused,
            # 子产出处理读数（业主裁定：父必须处理子产出）：四个数 + 那份明细。
            # 与 `agent_run_end` 的那一格同源（同一份 `summon_consumption`）。
            "productions": [dict(p) for p in self.productions],
            "summons_total": self.summons_total,
            "summons_consumed": self.summons_consumed,
            "summons_continued": self.summons_continued,
            "summons_waived": self.summons_waived,
            "summons_unconsumed": self.summons_unconsumed,
            "summon_consumption": dict(self.summon_consumption),
            "prompt_audit": dict(self.prompt_audit), "spend": dict(self.spend),
            # 提示词缓存的汇总（`LoopRun.prompt_cache` 的说明）：与 `spend` 并列，
            # 因为它们是同一笔钱的两面（花了多少 / 省了多少）。
            "prompt_cache": dict(self.prompt_cache),
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

    逐字：「插话只有 M 可能受到用户的插话，处理学 dsh。」⇒ 这条通道收窄成用户 → M 一条，对应 DSH 里"人在中途
    说话、在最近步边界被 steer"那一档（`draft/84` §8.3）；同伴之间传话走留言/交接手稿（`draft/85` §2.1 的工
    作项）。权限判据落在这一层：拒绝时零写入并给一条可执行的说明。

    历史（免得后人以为这条通道一直这么窄）：`draft/39` §3.11 二 D07，用户 2026-10-05 的口径是"广播改成集体插
    话发送"；T18 收窄它之后 `conductor.stop(notify=True)` 的叫停广播改回留言（见 `conductor_tools`）。插话的
    送达方式（下一步开头单列一段【插话】、不打断当前步）一个字没改。编号由脚本按会话内顺序发（`i-0001`…），
    模型不许自己编号。
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
    iid = f"i-{S.format_id(n)}"
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
    - `by_framework=True`（框架通报）⇒ 所有角色，读数 `framework`；
    - 带 `from_task_id` ⇒ 它的直接子级（`from_task_id == 我的父实例号`），读数 `instance`；
    - 带 `from_task_id` 但我不是它的子级 ⇒ 谁也（除它自己）看不到，读数 `not_my_parent`；
    - 老消息（没有 `from_task_id`）⇒ 按角色级回退 `from == 我父的角色`，读数 `role_fallback`；
    - 老消息、而我连父角色都不知道 ⇒ 看不到（不许当成"全角色可见"，也不许一律丢掉历史），读数 `unknown_parent`。
    框架那一档必须留（T21 之后唯一的例外，`draft/86` §14.6 写了理由）：叫停是框架代表主控发的全树通知，而工具层手上没
    有实例号、全树叫停又是安全件（听不到叫停的子孙会继续烧钱）；S4 的"沿边逐层下发"落地后这一档退休。代理自己发的
    public 必须带 `from_task_id`（`_do_message` 那一层受控拒绝）。
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

    只认"还没投递过的"留言：`inbox_digest` 的 `fresh` 是这一轮新渲染、且还没投递的 id，而 `mark_delivered`
    刻意推迟到"模型真的被问过一次"才写 ⇒ 读过的旧留言不会一轮又一轮地开循环（那会把"轮次已用尽"的停止变成死
    循环，而且烧钱）；三态：会话读不成 ⇒ `checked=False`，不许折成"没有新消息"（折过去会把一次真的唤醒吞掉，
    而"有人叫我"在盘上是有痕迹的）。

    不做"父代理循环里 sleep N 秒再看一次"（施工单 S-G 第 3 条逐字禁的形态）：那是 DSH 明确没有的东西，而且会
    把墙钟吃掉；唤醒是事件驱动的 —— 事件就是"收件箱里有新的、还没投递的留言"。
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

    为什么必须搬（施工单 S-G 逐字）：DSH 的通知是带 `source{kind, form:"notice", summary}` 的消息（
    `dsh-subagent:663-680`），而我们的 `heard` 是裸 dict ⇒ "这条是子代理结算 / 插话 / 广播"在读数上分不开；
    分开之后，"父收到的哪一条是孩子的交差通报"就有了机器可判的答案。

    四种 kind（取值刻意少而稳，且都是盘上已有的字面量）：`subagent-settled`（框架投递的通报，`by_framework`
    为真，即 `_emit_settlement` 那一类）、`broadcast`（`channel == "public"`）、`user`（发信人是用户/主控以
    外的用户频道）、`message`（其余：角色之间的一条普通留言）。
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
                 by_framework: bool = False,
                 extra: Mapping[str, Any] | None = None) -> tuple[str, str]:
    """发一条消息（append-only）。`to=PUBLIC` 是公共频道。返回 `(msg_id, 问题)`。

    编号口径：取现有最大号 + 1（`draft/83` D79）。旧写法"数一数有多少条 `agent_message` 再加一"在正常
    append-only 会话里与 max+1 恰好相等，但只要一条坏行占号、或将来做了删除/搬迁就会撞上已用过的号 ——而
    `msg_id` 正是投递登记与消费判定的键（撞号 = 两条消息共享一个身份）。

    `from_task_id` / `by_framework`（S6-a）：公共频道的可见面靠这两格判（见 :func:`public_visibility`），只
    在给了的时候写 —— 恒为假的键会让"谁都没写"与"框架特意写了假"长得一样。`extra`（2026-10-19）：附加结构化
    键，并进同一条记录（不给 ⇒ 与从前逐字节相同），今天只有 `conductor.escalate` 用它带
    `escalation{need,kind,evidence}`；不另发一条事件，因为收件箱是按 `agent_message` 收的（:func:
    `read_messages` 只认这一种 kind），"父收到了"与"父拿到细节"必须是同一条。
    """
    events, _problems = SS.read_session(session_root, sid=sid)
    used = [str(e.get("msg_id") or "") for e in events if e.get("kind") == "agent_message"]
    nums = [int(m[1:]) for m in used if m[:1] == "m" and m[1:].isdigit()]
    msg_id = f"m{S.format_id((max(nums) + 1) if nums else 1)}"
    rec: dict[str, Any] = {
        "kind": "agent_message", "msg_id": msg_id, "from": sender, "to": to,
        "subject": subject, "body": body, "reply_to": reply_to,
        "channel": "public" if to == PUBLIC else "private",
    }
    if str(from_task_id or ""):
        rec["from_task_id"] = str(from_task_id)
    if by_framework:
        rec["by_framework"] = True
    if extra:
        for k, v in dict(extra).items():
            # 核心那几格不许被附加键盖掉（撞键 = 一条消息的身份被改写）
            if k not in rec:
                rec[str(k)] = v
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

    `parent_task_id` / `parent_role` 转给 :func:`read_messages`（公共频道的可见面，S6-a）：谁读就得以谁的身
    份读 —— 缺了这两格，公聊会按"老消息回退"那一档要么读不到、要么读成别人的（两种都是静默错）。

    第二个返回值是"渲染过的"而不是"全部未投递的"（`draft/83` §11 的 D75）：旧实现渲染 `messages[-8:]` 却把全
    部未投递的 id 交给调用方去 `mark_delivered` ⇒ 第 9 条及更早的留言既不进提示词、也不再是 fresh，永久静默
    丢失（真机：128 个会话 579 条留言里只有 8 条被标记读过）。现在两个集合只有一个来源：这里返回什么，调用方
    就标什么。未投递优先（时间升序，老的先读），装得下再补最近的已投递项当背景，装不下就在末尾写明"还有 K 条
    没渲染，下一步继续"；`window=None` = 不限窗口（`_hear` 那条路渲染多少就标多少）。
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

    口径与 `inbox_digest` 同源（`draft/83` §11 的 D75）：渲染集合 = 标记集合 —— 返回什么 id 就 `mark_item_seen` 什么；
    "渲染 8 条却把全部未读标掉"同样会让第 9 项永久静默丢失。

    "渲染即 seen"（业主 A3=甲）：板项的"已投递"标记就是它自己的状态机 —— `queued`/`claimed` ⇒ 还没被谁读进任何一步；
    `seen` 由这一步写（`seen_by` = 我的台账号、`seen_step` = 第几步）；未 seen 的项才算"新"，渲染了就标 seen，标了才不
    再进下一轮的窗口。
    三态（不许把"没读成"折成"板上没事"）：没有 conductor / 没有台账号 / 读失败 —— 三种都返回一句带括号的问题并进第三个
    返回值（`run.notes`），最后一种绝不返回"（板上没有要你处理的事）"；`window=None` = 不限窗口（与 `inbox_digest` 的
    `_hear` 那一档同义）。
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


# ---------------------------------------------------------------- 信箱（D-52）
#
# ## 它治的是哪一种病（一句话）
#
# 快照（这一趟是什么：谁派的、深度、台账号、名册）与流水（这期间到了什么：留言、
# 板项、V 的判决、计时器到点）此前被混在同一个落点上 —— `_opening_transcript` 的
# 九格。而那条消息只在跑起头渲染一次，于是流水被冻住：中途到达的一切读不到。
#
# ## 形态
#
# `mailbox_digest` 只读、只渲染（三态：读不成是"没查成"，不是"没有新东西"）；
# `AgentLoop._deliver_mailbox` 是唯一的投递点（每一次 `ask_step` 之前），投完把板项
# 推到 `seen`、把留言登记成已投递，并落一条 append-only 的 `agent_mailbox` 事件
# （以 item_id / msg_id 为键 ⇒ "投过没有"可复算；续跑按它重放那一段）。

#: 一次投递最多几条（板项与留言各算各自的上限）。其余按到达序留到下一次 ——
#: 一条不丢，且"还有 N 条没投"写在增量段末尾（否则"读不完"与"没新东西"同形）。
MAILBOX_LIMIT: int = 8

#: 信箱投递事件的 `kind`（append-only 的审计面）。
#:
#: 为什么不复用 `agent_inbox`：那一条的键是 `delivered`（留言的 msg_id），投递登记的
#: 读者也按它算"留言读过没有"。板项的键是 `item_id`（`tasks` 表的 task_id），两套键
#: 混在一条事件里，"投过几条"就会把两种东西加在一起（而它们的消费语义不同：
#: 留言是投递登记，板项是状态机 queued → seen）。
MAILBOX_EVENT: str = "agent_mailbox"

#: 监控回合里放行的形状（D-53 的出口限定）。`note` 在列：它只写自己的台账，
#: 什么也不派；`final` 是收口。
MONITOR_TURN_SHAPES: frozenset[str] = frozenset({"tool", "summon", "summon_many",
                                                 "note", "final"})

#: 监控回合里放行的工具名（`tool` 那一档只认这两件）。
MONITOR_TURN_TOOLS: frozenset[str] = frozenset({"conductor.watch", "conductor.guide"})


def monitor_exit_text(role: str) -> str:
    """监控回合的出口那一段（S2，2026-10-25：按角色渲染，不把 M 的出口写给所有人）。

    为什么必须按角色：`conductor.watch` / `conductor.guide` 只在主控的工具面上
    （`MONITOR_TURN_TOOLS` 是这两件，而非 M 角色连一件都没有）。改前这一段给十一个
    角色都写"只许 watch / guide / 补派 / 收口" ⇒ 非 M 读到两件它没有的工具，照做只会
    拿 `unknown_tool` / 越权拒绝。非 M 走得通的只有补派、收口、note 三类
    （`MONITOR_TURN_SHAPES` 里它们都在，且 `note` 只写自己的台账）。
    """
    if str(role) == S.CONDUCTOR_ROLE:
        return ("这一回合的出口只许这四类：`conductor.watch`（看全树）/ "
                "`conductor.guide`（给指导）/ 补派（`summon` 一个或 `summon_many` 一批）/ "
                "收口（`final`）。")
    return ("这一回合的出口只许这三类：补派（`summon` 一个或 `summon_many` 一批）/ "
            "收口（`final`）/ `note`（只写自己的台账）。")

#: 出口限定连拒几次之后放开（安全阀；理由见 `AgentLoop._monitor_refusal`）。
MONITOR_REFUSAL_LIMIT: int = 3

#: 可抢占派活（D-64）：派完在"这一步"里最多等多久（秒）。
#:
#: 真机读数（sylow3 只读复算）说这个数不能是"无上限"：M（t-000001）第 5 步的
#: `summon_many` 从 17:34:25 一直阻塞到 19:06:48（92 分钟），那期间父代理一步都
#: 没有，于是"下一次 ask_step 之前的投递"结构上不可能发生（t-000031 的通报迟到
#: 20m28s）。也不能是 0：`summon` 的既有契约是"返回值里有孩子的结果"，秒级的孩子
#: 必须照旧在同一个步里回来（`tests/test_d_summons_c_and_c_reports_back.py`）。
#:
#: 取的 180 秒是两个方向的折中，两边都有读数撑着：
#:   · 上界：真机那次是 92 分钟 ⇒ 180 秒把"零回合 92 分钟"改成"最迟 3 分钟一次回合"；
#:   · 下界：`tests/test_agent_loop.py` 那种"嵌套循环当孩子"的夹具在机器被压满时
#:     实测要 20 秒级；短于这个数会让"孩子还没回来"变成一个与机器快慢有关的抖动
#:     （那类判据本该只在真·长任务上红）。
CHILD_STEP_WAIT_SEC: float = 180.0

#: 可抢占派活（D-64）：返场点上最多等多久（秒）——"定期返场"的那个周期。
#:
#: 父代理还有子在跑时，每一次被问之前先等"有孩子回来 / 有时钟唤醒到点"。
#: 取的参考是 D-53 那条业主口径「每 10 分钟看一次全树」的一半：孩子一回来就立刻
#: 返场（那是生产性的回合），什么都没有时最迟 5 分钟返场一次（那是"定期"）。
#: 为什么不能是 0：还有子在跑又没有任何新事实时，立刻问模型只会买到一句
#: "我还在等"；而循环的步数没有硬闸（裁定 12-K），那是无限烧钱。
CHILD_RETURN_WAIT_SEC: float = 300.0

#: 收工时还在跑的孩子最多再等多久（秒）。到点就如实留痕、不再等 ——
#: 一次收工不该被一个后台 handler 拖成"这条命令不返回"。
CHILD_EXIT_DRAIN_SEC: float = 5.0

#: 可抢占派活的开关（D-64）。`False` = 退回改前"派完等全部完成"的旧拼法。
#:
#: 为什么留一个开关而不是无条件打开：这是"反真空"判据的挂点
#: （`tests/test_summon_is_preemptible.py` 的 d 条：把它打桩成 False ⇒ a/b 两条必红）。
#: 没有这一格，"父代理拿到了回合"可能只是被别的东西满足的 —— 那样的判据什么都没钉住。
PREEMPTIBLE_DISPATCH: bool = True


def _takes_kwarg(fn: Any, name: str) -> bool:
    """`fn` 收不收名为 `name` 的关键字（签名里带可变关键字形参也算收）。

    为什么要探这一下：D-64 的开关是给 `Conductor.run_plan` 加的一个关键字
    （`preemptible=`），而一批判据与外部调用点把它换成了替身
    （`def run_plan(calls, token=None)`）。硬传那个关键字对替身是 TypeError，
    而那种红的形状与"可抢占坏了"一样 —— 探签名把两者分开，替身走它自己那一套。
    """
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    if name in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _patched_on_instance(obj: Any, name: str) -> bool:
    """`obj` 上的 `name` 是不是被换成了实例属性（替身）。

    为什么这一格是"可抢占要不要让路"的判据：一批判据用
    `monkeypatch.setattr(cond, "summon", 替身)` 把派活那一层换掉，为的是只量
    名册登记或父编号。可抢占走的是另一条入口（`summon_preemptible` /
    `run_plan(preemptible=True)`），硬接上去就等于绕开它换掉的那一个 —— 那种红
    看起来像"可抢占把别的判据弄坏了"，实际是"绕开了替身"。
    所以：调用方显式换掉过 ⇒ 走它给的那一个（阻塞版），一行都不抢。
    """
    return name in getattr(obj, "__dict__", {})


def _child_record_done(rec: Mapping[str, Any]) -> bool:
    """这一笔挂账是不是"全落定了"（⇒ 可以从返场清单上摘掉）。"""
    handle = rec.get("handle")
    if handle is None:
        return True
    if str(rec.get("kind") or "") == "summon_many":
        done = getattr(handle, "done", None)
        return bool(done()) if callable(done) else True
    done = getattr(handle, "done", None)
    return bool(done()) if callable(done) else True

#: 板项渲染成提示词里那一行的顺序口径 —— 与 `board_digest` 同一条（到达序 =
#: 落行时间 + 编号）。两处都按这个键排，免得同一批项读出两个顺序。
def _board_item_line(row: Mapping[str, Any]) -> str:
    """一条板项在提示词里的那一行（`board_digest` 与信箱共用同一句话）。"""
    return (f"- （新）[{row['task_id']}] {row.get('kind')}"
            f"·要{'一个回执' if str(row.get('expects') or '') == 'ack' else '一件活'}"
            f" 来自 {row.get('called_by')}：{_clip(row.get('detail'), 300)}")


def mailbox_digest(conductor: Any, session_root: Path | str, role: str, *,
                   my_task_id: str, sid: str | None = None,
                   parent_task_id: str = "", parent_role: str = "",
                   limit: int = MAILBOX_LIMIT,
                   rendered: Sequence[str] = ()) -> dict[str, Any]:
    """投给我、还没读过的那一批：`{checked, text, item_ids, msg_ids, problems,
    backlog, reason}`。

    ## 只认 `item_state == "queued"`

    板项的状态机是 `queued → claimed → seen → done`（`schema.ITEM_STATES`）。
    `claimed` 是"某个实例接手了"、`seen` 是"已经读进过某一步的提示词"——
    对"该不该再投一次"这个问题，只有 `queued` 的答案是"该"。把 `seen` 折进来会让
    同一条通报每一步都重投一遍（模型会以为它又来了）；把 `claimed` 折进来会让
    一个已经有人在处理的项被念两次。

    两层去重，各管一件事（判据第 2 条把这条写死：一开始只有状态机那一层，
    超上限时队头被下一步重投、队尾永远轮不到）：

    - `rendered`：这一趟已经渲染进过提示词的 id（`AgentLoop._mailbox_rendered`），
      管"这一趟还要不要再渲染它"；
    - `item_state == queued`：状态机，管"跨趟还要不要再投它"（`seen` = 已经承认过）。

    两层都是必要的：承认送达是推迟的（要等"模型真的被问过一次"），而渲染是立刻的 ⇒
    只靠状态机，一次装不下的积压会在下一步被同一批队头项重新占满。

    ## 三态（不许折平）

    - `checked=True` + `text=""`：查过了，这一趟没有新东西；
    - `checked=False` + `problems`：没查成（没有 conductor / 没有台账号 / 读失败）
      —— 此时 `text` 里是一句带括号的说明，不是"板上没事"。

    上限 `limit`：板项与留言各取前 `limit` 条（到达序），其余的条数进 `backlog`，
    并写成增量段末尾那句"还有 N 条没投"。
    """
    got: dict[str, Any] = {"checked": True, "text": "", "item_ids": [], "msg_ids": [],
                           "problems": [], "backlog": 0, "reason": "",
                           "items": []}
    n = max(1, int(limit))
    already = {str(x) for x in (rendered or ())}
    blocks: list[str] = []

    # ---- ① 板项（D-52 的那一半：收件人 = 我，状态 = queued）
    if conductor is None:
        got["checked"] = False
        got["reason"] = "这一趟没有 conductor 句柄 ⇒ 读不到板项"
        got["problems"].append("信箱读不到板项：这一趟没有 conductor 句柄")
    elif not str(my_task_id or ""):
        got["checked"] = False
        got["reason"] = "这一趟还没有台账号 ⇒ 读不到发给你的板项"
        got["problems"].append("信箱读不到板项：这一趟没有台账号（尚未落台账）")
    else:
        look = getattr(conductor, "open_items_of", None)
        if not callable(look):
            got["checked"] = False
            got["reason"] = "这个 conductor 没有 `open_items_of` ⇒ 读不到板项"
            got["problems"].append("信箱读不到板项：conductor 没有 `open_items_of`")
        else:
            try:
                rows = list(look(my_task_id))
            except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
                why = f"{type(exc).__name__}: {exc}"
                got["checked"] = False
                got["reason"] = f"工作项板没读成：{why}"
                got["problems"].append(f"信箱读不到板项：{why}")
            else:
                queued = [dict(r) for r in rows
                          if str(r.get("item_state") or "") == "queued"
                          and str(r.get("task_id") or "") not in already]
                queued.sort(key=lambda r: (str(r.get("started_at") or ""),
                                           str(r.get("task_id") or "")))
                pick = queued[:n]
                got["backlog"] = max(0, len(queued) - len(pick))
                got["item_ids"] = [str(r.get("task_id") or "") for r in pick]
                got["items"] = pick
                if pick:
                    blocks.append("【新到的板项】（发给你的、还没读过的）\n"
                                  + "\n".join(_board_item_line(r) for r in pick))
                if got["backlog"]:
                    blocks.append(f"- （还有 {got['backlog']} 项没渲染 —— 下一次投递继续）")

    # ---- ② 留言（`agent_inbox` 那条通道的未投递项）
    try:
        msg_text, fresh, msg_problems = inbox_digest(
            Path(session_root), role, sid=sid, window=n,
            parent_task_id=parent_task_id, parent_role=parent_role)
    except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
        msg_text, fresh, msg_problems = "", [], [f"收件箱没读成：{type(exc).__name__}: {exc}"]
    fresh = [str(x) for x in fresh if str(x) not in already]
    if msg_problems:
        got["checked"] = False
        got["problems"].extend(f"信箱读不到留言：{p}" for p in msg_problems)
        got["reason"] = got["reason"] or "；".join(str(p) for p in msg_problems)
    if fresh:
        got["msg_ids"] = fresh
        blocks.append("【新到的留言】\n" + msg_text)

    if blocks:
        got["text"] = ("【信箱】这一段是本次投递的增量（不是这一趟的开场快照；"
                       "开场那一段只放这一趟的事实，流水在这里现念）：\n\n"
                       + "\n\n".join(blocks))
    return got


def record_mailbox_delivery(session_root: Path | str, role: str, *, step: int,
                            shape: str, text: str, item_ids: Sequence[str] = (),
                            msg_ids: Sequence[str] = (), wake_ids: Sequence[str] = (),
                            task_id: str = "", sid: str | None = None) -> str:
    """落一条 append-only 的投递事件；返回问题串（空 = 落成了）。

    `shape` 两档（续跑重放按它分叉，别把两档折平）：

    - `"turn"`：投递点落在一次 `ask_step` 之前 ⇒ 它是一条独立的 user 消息，
      续跑要按事件序把这条消息原样重放回序列里（`rebuilt == run.messages` 靠它）；
    - `"step_tail"`：投递落在某一步执行之后（`Agent.p._hear` 那条耳朵）⇒ 那段文字
      在这条步的 tool 结果里，续跑不再另加消息（另加会让重建的那一段多一条）。

    `item_ids` / `msg_ids` / `wake_ids` 是这一条事件的键：`agent_mailbox` 事件因此
    可以按 item_id 复算"这一项投过没有"，而不用相信任何内存状态。
    """
    return SS.append(Path(session_root), {
        "kind": MAILBOX_EVENT, "role": str(role), "task_id": str(task_id or ""),
        "step": int(step), "shape": str(shape), "text": str(text),
        "item_ids": [str(x) for x in (item_ids or ())],
        "msg_ids": [str(x) for x in (msg_ids or ())],
        "wake_ids": [str(x) for x in (wake_ids or ())],
        "at": S.now_iso(),
    }, sid=sid)[1]


# ---------------------------------------------------------------- 时钟唤醒（D-53 的读口）
#
# `clock.py` 把落点与读口都做好了（`read_wakes` / `pending_wakes` / `consume_wakes`），
# 但它的读口径是"按收件人台账号"。而这一层有两个读者：正在跑的循环手上有台账号
# （按编号读），`autonomy` 的轮边界上没有（每一轮 `run_role` 都会新开一行台账号）
# ⇒ 那里只能按角色读。两个口径都在这一处实现，别在调用方各写一份过滤。

def pending_clock_wakes(workspace: str | Path, *, role: str = "",
                        task_id: str = "") -> dict[str, Any]:
    """读"等我消费"的时钟唤醒标记；三态：`checked=False` 是"没查成"。

    过滤口径：给了 `task_id` 就按编号（正在跑的循环用这一档）；否则按 `role`
    （`autonomy` 的轮边界用这一档 —— 每一轮都会新开一行台账号，上一轮的编号已经
    不是这一轮的，"按编号读"在那里必然读到空）。两样都不给 = 全部（判据用）。
    """
    got = CLK.read_wakes(workspace)
    if not got.get("checked"):
        return {"checked": False, "events": [], "count": 0,
                "reason": str(got.get("reason") or "唤醒标记没读成"),
                "role": str(role or ""), "task_id": str(task_id or "")}
    events = [dict(e) for e in (got.get("events") or []) if isinstance(e, Mapping)]
    if str(task_id or ""):
        want = str(task_id)
        events = [e for e in events if str(e.get("task_id") or "") == want]
    elif str(role or ""):
        want = str(role)
        events = [e for e in events if str(e.get("role") or "") == want]
    return {"checked": True, "events": events, "count": len(events), "reason": "",
            "role": str(role or ""), "task_id": str(task_id or "")}


def consume_clock_wakes(workspace: str | Path,
                        events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """把这些唤醒标记消费掉（按 `task_id` 分组调 `clock.consume_wakes`）。

    为什么要分组：`clock.consume_wakes` 的签名是"一个收件人 + 一批编号"（删除与
    "返回被删的那几条"必须在同一个读-改-写里完成，那是 `clock.py` 的口径）。
    跨收件人的一批只能拆成几次调用；拆的时候每组的 `wake_ids` 都要带上，
    否则会把同一收件人名下别人的唤醒一起删掉。
    """
    by_task: dict[str, list[str]] = {}
    for e in events or ():
        if not isinstance(e, Mapping):
            continue
        tid = str(e.get("task_id") or "")
        wid = str(e.get("wake_id") or "")
        if wid:
            by_task.setdefault(tid, []).append(wid)
    consumed: list[dict[str, Any]] = []
    problems: list[str] = []
    checked = True
    for tid, wake_ids in by_task.items():
        got = CLK.consume_wakes(workspace, tid, wake_ids=wake_ids)
        if not got.get("checked"):
            checked = False
            problems.append(f"唤醒标记没消费成（{tid}）：{got.get('reason')}")
            continue
        consumed.extend(dict(x) for x in (got.get("consumed") or []) if isinstance(x, Mapping))
    return {"checked": checked, "consumed": consumed, "count": len(consumed),
            "problems": problems,
            "reason": "；".join(problems)}


#: V 的「有毛病」那一档的逐字取值（词表真身是 `verifications.parse_verdict`）。
V_VERDICT_REJECTED = "有毛病"

#: 「V 判决项」在板上的 `input_key` 前缀 —— 幂等投递的唯一键（同一条判决只开一项）。
V_VERDICT_ITEM_PREFIX = "v-verdict@"


def v_rejections_digest(root: str | Path, rows: Sequence[Mapping[str, Any]],
                        *, limit: int = 8) -> tuple[str, list[dict[str, Any]], list[str]]:
    """我名下被 V 判「有毛病」的证明明细：`(文本, 明细, 问题)`。

    ## 这一格为什么存在（业主 2026-10-22 的 B-3 裁定，逐字）

    「V 的判决必须递到 F（让 F 去修），否则瞎写的证明不能用」。

    改前的现场：V 的 `有毛病` 只落 `verifications/<命题号>.jsonl`，而 `agent_loop`
    全文 0 处读 `verifications` ⇒ 运行期 F 看不到「V 判过、判的是有毛病」；真机
    `t-000026` 里 V 逐条走查 `000000–000003`，四条全判「有毛病」（`unresolved_errors`
    1/1/2/3），而 `statements` 仍 `status=active`、`bits.reviewed=false`、
    `grade=conjecture` —— 数据诚实，但没有任何人看得见、也没有人去修；只有收工门 R10
    事后把它记成 rejected，运行期零后果。这一格就是那条判决的读侧落点。

    ## 唯一判据不在这里（两处各写一份就会漂）

    逐条证明的结论一律读 `verifications.statement_review_reading`（与 `closing` 的
    收工门 R10 同一个函数）：它答「这一份正文最近那一签是什么」。这里只做两件事 ——
    把 `state="rejected"` 的那些挑出来，再把那一签整行上的步号与 findings 读出来
    （`statement_review_reading` 只回编号，不回 `defect_step`）。

    ## 三态（不许把「没读成」折成「没有毛病」）

    - 「名下没有被 V 判有毛病的证明」是一句有内容的读数（每条都签过成立 / 一条都没签过）；
    - 读不出来（台账坏行 / 表读不到）⇒ 那一条进 `problems`，文本里明写「这一条没读成」；
    - `rows` 是调用方现读的 `statements`，本函数不读表（一处读表、一处判据）。

    ## 渲染集合 = 投递集合（与 `board_digest` / `inbox_digest` 同一条纪律）

    返回的 `明细` 是全量（投递那一侧要用），但 `文本` 只渲染前 `limit` 条并把
    「还有几条没渲染」写出来 —— 静默截断会让第 9 条永远不进任何人的视野。
    """
    from . import verifications as VR      # 惰性：本模块的运行期只在这一格读台账

    details: list[dict[str, Any]] = []
    problems: list[str] = []
    for row in rows:
        sid = str(row.get("stmt_id") or row.get("statement_id") or "")
        if not sid or str(row.get("kind") or "") == "concept":
            continue
        # 没有可审的证明 ⇒ 它是「还没送 V」，不是「V 判过有毛病」（两条读数必须分开）。
        if not VR.proof_list(row):
            continue
        try:
            reading = VR.statement_review_reading(root, row)
        except Exception as exc:  # noqa: BLE001 —— 读不成是「没查成」，不是「没有毛病」
            problems.append(f"{sid}：第 3 位读数没读成（{type(exc).__name__}: {exc}）")
            continue
        problems.extend(f"{sid}：{p}" for p in (reading.get("problems") or []))
        rejected = [e for e in (reading.get("proofs") or [])
                    if str(e.get("state") or "") == "rejected"]
        if not rejected:
            continue
        # 那一签的整行（步号 / findings）：唯一的读口是台账文件本身，不复制第二份。
        signed: dict[str, dict[str, Any]] = {}
        try:
            led_rows, _bad = VR.list_verifications(root, statement_id=sid, limit=None)
        except Exception as exc:  # noqa: BLE001
            led_rows = []
            problems.append(f"{sid}：台账读不成（{type(exc).__name__}: {exc}）⇒ "
                            "步号这一格没读出来")
        for r in led_rows:
            signed[str(r.get("verification_id") or "")] = dict(r)
        for e in rejected:
            vid = str(e.get("verification_id") or "")
            sign = signed.get(vid, {})
            steps = [int(f.get("step")) for f in (sign.get("findings") or [])
                     if isinstance(f.get("step"), int)]
            defect = sign.get("defect_step")
            if isinstance(defect, int) and defect not in steps:
                steps.insert(0, defect)
            first = next((dict(f) for f in (sign.get("findings") or [])
                          if isinstance(f, Mapping)
                          and isinstance(f.get("step"), int)), {})
            details.append({
                "stmt_id": sid,
                "proof_no": int(e.get("proof_no") or 1),
                "label": str(e.get("label") or f"{sid}#p{int(e.get('proof_no') or 1)}"),
                "verdict": str(sign.get("verdict") or V_VERDICT_REJECTED),
                "unresolved_errors": int(e.get("unresolved_errors")
                                         or sign.get("unresolved_errors") or 0),
                "verification_id": vid,
                "ledger": f"verifications/{sid}.jsonl",
                "steps": sorted(set(steps)),
                "defect_step": (int(defect) if isinstance(defect, int) else
                                (steps[0] if steps else None)),
                "finding": {"step": first.get("step"), "kind": str(first.get("kind") or ""),
                            "detail": str(first.get("detail") or "")} if first else {},
                # 「它的 proof_text 是否与现文一致」：`in_sync=True` 且 state=rejected
                # 就是「这一签盖的正是现在这一份、结论不是成立」。
                "in_sync": bool(e.get("in_sync")),
                "proof_sha256": str(e.get("proof_sha256") or ""),
            })
    details.sort(key=lambda d: (d["stmt_id"], int(d["proof_no"])))
    if not details and not problems:
        return ("（名下没有被 V 判「有毛病」的证明：要么每条都签过成立，"
                "要么一次都还没送 V）"), [], []
    lines: list[str] = []
    if details:
        lines.append(f"被 V 判「有毛病」的证明共 {len(details)} 条"
                     f"（数据源 `verifications/*.jsonl` 逐条读；步号就是 V 指的那一步）：")
        for d in details[:max(1, int(limit))]:
            step = ("第 %s 步" % d["defect_step"]) if d.get("defect_step") else "步号没读到"
            what = str((d.get("finding") or {}).get("detail") or "")
            lines.append(
                f"- {d['label']}：verdict={d['verdict']}、"
                f"unresolved_errors={d['unresolved_errors']}、最近一签 "
                f"{d['verification_id'] or '（没读到编号）'}（{d['ledger']}）；"
                f"错在{step}" + (f"（{what}）" if what else "") + "；"
                f"这一签盖的就是现在这一份（proof_text 与现文一致）："
                f"{'True' if d['in_sync'] else 'False'}；"
                f"下一步：补齐{step}之后把这一份重新送 V（`verify.verify_proof`）重签，不许绕开")
        backlog = len(details) - len(details[:max(1, int(limit))])
        if backlog > 0:
            lines.append(f"- （还有 {backlog} 条没渲染 —— 板上另有判决项，"
                         "`attack.status` 之外没有别的读法）")
    if problems:
        lines.append("- 没读成的：" + "；".join(problems[:4])
                     + (f"（另 {len(problems) - 4} 条）" if len(problems) > 4 else ""))
    return "\n".join(lines), details, problems


def deliver_v_verdicts(conductor: Any, *, task_id: str, depth: int, role: str = "F",
                       details: Sequence[Mapping[str, Any]] = (),
                       called_by: str = "V") -> dict[str, Any]:
    """把 V 的「有毛病」判决写进收件人的收件板（业主 B-3：递到人，不只加读数）。

    ## 用的就是既有通道（不新造机制）

    `conductor.open_item` + `set_item_detail` —— 与留言 / 通报 / 终态回报同一条路
    （板项 = 收件人名下的一行 `tasks`；`board_digest` 下一趟就会把它渲染给收件人）。
    框架不替 F 改证明：这一项里只有「哪一条、错在第几步、下一步该补什么」，
    正文一个字都不动。

    ## 幂等：同一条判决只开一项

    去重键是板项的 `input_key`（`v-verdict@<命题号>#p<号>@<verification_id>`）。
    没有它，F 每进一次循环就会多一条同样的话，而"板上 N 条"这个读数会随时间失真。

    ## 三态

    - 没有 conductor / 没有台账号 ⇒ `checked=False` + `reason`（不是「送过了」）；
    - 开项抛异常 ⇒ 那一条进 `problems`，其余照开（一条坏不许带走整批）；
    - 已经在了 ⇒ 进 `existing`（不重开，但读得出来它早就在那儿）。
    """
    out: dict[str, Any] = {"checked": False, "role": role, "task_id": str(task_id or ""),
                           "opened": [], "existing": [], "problems": [], "reason": ""}
    if conductor is None:
        out["reason"] = "这一趟没有 conductor 句柄 ⇒ 判决递不到任何板上（不是「已经送到」）"
        return out
    if not str(task_id or ""):
        out["reason"] = "这一趟还没落台账（没有台账号）⇒ 板项挂不到任何人名下"
        return out
    if not callable(getattr(conductor, "open_item", None)):
        out["reason"] = "这个 conductor 没有 `open_item` ⇒ 开不了板项"
        return out
    # 去重口径：优先读整块板（含已经 done 的项），读不到再退回"我名下未消的"。
    try:
        look = getattr(conductor, "_board_rows", None)
        board = [dict(r) for r in (look() if callable(look)
                                   else conductor.open_items_of(task_id))]
    except Exception as exc:  # noqa: BLE001 —— 去重读不成 ⇒ 不静默重开一遍
        out["reason"] = (f"板读不成（{type(exc).__name__}: {exc}）⇒ 为了不重复开项，"
                         "这一批判决没有投递")
        return out
    have = {str(r.get("input_key") or "") for r in board if str(r.get("input_key") or "")}
    for d in details:
        key = (f"{V_VERDICT_ITEM_PREFIX}{d['label']}"
               f"@{str(d.get('verification_id') or '')}")
        if key in have:
            out["existing"].append(key)
            continue
        step = (f"第 {d['defect_step']} 步" if d.get("defect_step") else "步号没读到")
        what = str((d.get("finding") or {}).get("detail") or "")
        body = (f"V 判「有毛病」：{d['label']}（最近一签 "
                f"{d.get('verification_id') or '（没读到编号）'}，"
                f"unresolved_errors={d.get('unresolved_errors')}）\n"
                f"错在{step}" + (f"：{what}" if what else "") + "\n"
                f"下一步该补的就是{step}；补完把这一份重新送 V"
                f"（`verify.verify_proof`）重签 —— 不许绕开 V 直接当定理用。\n"
                f"这一签盖的就是现在这一份（proof_text 与现文一致）："
                f"{'True' if d.get('in_sync') else 'False'}")
        try:
            item_id = conductor.open_item(
                kind="notice", role=role, expects="ack", action="notice",
                summary=f"V 判「有毛病」：{d['label']}（错在{step}）",
                called_by=called_by, parent_task_id=task_id,
                # 板项是收件人的子行 ⇒ 深度 = 收件人深度 + 1（`verify` 的
                # `task_depth_discontinuous` 判这一条，挂在自己名下也一样）。
                depth=int(depth or 1) + 1, input_key=key)
            conductor.set_item_detail(item_id, body[:400])
        except Exception as exc:  # noqa: BLE001 —— 一条开不成不许带走整批
            out["problems"].append(f"{d['label']}：板项没开成（{type(exc).__name__}: {exc}）")
            continue
        out["opened"].append(item_id)
        have.add(key)
    out["checked"] = True
    out["reason"] = (f"投递 {len(out['opened'])} 条（已在板上 {len(out['existing'])} 条）"
                     + (f"；{len(out['problems'])} 条没开成" if out["problems"] else ""))
    return out



# ------------------------------------------------------------------ 循环
def _sha(text: str) -> str:
    """文本的 sha256（会话记录里给交付物留指纹用；与 `llmseam._sha` 同一个口径）。"""
    import hashlib

    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _shape_of(data: Mapping[str, Any], *,
              roster: Any = None) -> tuple[str, Mapping[str, Any], str]:
    """把模型的一句输出判成一个形状。判不出来时返回 `("", {}, 原因)`。

    两个「别名形态」（都只改"从哪取键"，不放宽任何校验）：① `{"name": …, "args": …}` 是 `{"tool": …}` 的别名（
    2026-10-03，§61）：真机（第八、十趟）模型有时这么写工具调用，此前被判"认不出的形状"计进 `bad_json`、第 3 次就
    `bad_json_limit`（第十趟的步 8/12/35；与 §65 的 `judge_bad_args` 是两件事：这里坏「形状」，那里坏「参数」）；
    ② 扁平形态（2026-10-03，§68 的第十二趟读数）：`{"role": …, "action": …, "params": {…}}` 是 `framework_summon`
    的签名（第 13 步就这么死的），键集只有一种含义（见 `FLAT_SHAPE_ALIASES`），拒收的代价是整趟作废。

    理由：这些键集没有第二种含义，而"名字/签名"这一层本来就有歧义空间（带点的真名 vs 广告名，见 `_do_tool`）—— 多
    认一个写法比让整趟作废便宜；留痕照旧：payload 带 `shape_alias`（与 `_do_tool` 的 `aliased_from` 同一套做法）。

    `roster`（2026-10-22）：给 `message.to` 用的名册寻址（一个"写法 → 名册成员"的函数，
    真身是 `AgentLoop._address_of` → `roster_addresses`）。不给 ⇒ 判据与改前逐字相同
    （模块级单测直接调本函数的那一档）；给了 ⇒ 名册名 / 绝对编号也能寻址，见
    `_decode_shape` 的 `message` 那一支。
    """
    rewritten, alias = _unwrap_alias(data)
    if rewritten is not None:
        shape, payload, problem = _decode_shape(rewritten, roster=roster)
        if problem or not shape:
            return shape, payload, problem
        return shape, {**payload, "shape_alias": alias}, ""
    return _decode_shape(data, roster=roster)


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


def _proposal_fields() -> tuple[str, str]:
    """两段式的两个受控字段名（`accept_proposal` / `reject_proposal`）。

    真身只在 `secretary`（`ACCEPT_PROPOSAL` / `REJECT_PROPOSAL`）—— 本模块不抄第二份，
    只延迟取一次：解码那一步要保证它们活着，循环那一步要把"下一步该带什么"回给模型。
    """
    from .secretary import ACCEPT_PROPOSAL, REJECT_PROPOSAL

    return ACCEPT_PROPOSAL, REJECT_PROPOSAL


#: 解码层把"名册上的一个地址"翻成"哪个角色"时用的两个理由码。
#:
#: 它们只在解码这一步出现，与 `roster_addresses` 自己的码不是同义词也不合并：
#: `not_in_roster` 说的是"不在父∪子里"（名册判据那一层的口径），而解码这一步面对的
#: 是模型写下的一个地址写法 —— 名册上根本没有这个名字/编号，就叫 `unknown_roster_name`
#: （业主 2026-10-22：模型侧「按编号沟通」走不到时，回执要能分开"名字不认识"与
#: "名册说不行"）。
DECODE_UNKNOWN_ROSTER_NAME = "unknown_roster_name"
#: 名册上确实有这一行、但它的角色读不出来（或读出来的不是收件箱认得的角色）⇒
#: 翻不成"谁收" —— 原样投递只会落进一个没人读的收件箱，所以受控拒绝。
DECODE_MEMBER_WITHOUT_ROLE = "member_has_no_role"


def _decode_roster_recipient(written: str, roster: Any) -> dict[str, Any] | None:
    """把模型写下的名册名 / 绝对编号解析成"这个地址对应哪个角色"（解码层的唯一实现）。

    口径只有一处：直接调调用方给的 `roster`（真身是 :func:`roster_addresses` —— 循环把
    `AgentLoop._address_of` 传进来）。本函数不认任何形状（点号名、绝对编号、大小写都
    不自己判），因此"点名册名"这条路只有一份解析实现。

    返回解析结果（`roster_addresses` 的那份 dict）或 `None`：`None` 表示这一次解码
    没有名册上下文（模块级单测直接调 `_decode_shape` / `_shape_of` 的那一档）⇒ 调用方
    按改前逐字相同的那条判据拒收。解析自己抛异常 ⇒ 返回 `roster_unavailable` 那一档
    （读不成不等于"没有这个人"，也不等于"名册校验通过"）。
    """
    if roster is None:
        return None
    try:
        got = roster(str(written or ""))
    except Exception as exc:  # noqa: BLE001 —— 读不成要如实说，不许折成"查过了没问题"
        return {"checked": False, "how": "roster_unavailable", "name": "", "task_id": "",
                "role": "", "candidates": [], "callable": "",
                "refused": "roster_unavailable",
                "error": f"名册寻址没跑成（{type(exc).__name__}: {exc}）"}
    return dict(got) if isinstance(got, Mapping) else None


def _decode_roster_problem(addr: Mapping[str, Any],
                           written: str) -> tuple[str, list[str], str]:
    """名册解析结果能不能翻成"收件箱认得的角色"：`(理由码, 候选, 那句话)`，码空 = 能。

    三档，各有各的码（处置方向不同，不许折平）：
    - 名册这一趟读不成（`roster_unavailable`）⇒ 同一码：不猜"没有这个人"，也不退回
      把编号原样写进 `to`（那会写进一个没人读的收件箱）；
    - 名册上没有这个地址（`not_in_roster`）⇒ `unknown_roster_name`；
      名册自己给的 `ambiguous_in_roster` / `member_retired` 原样带过来 —— "同名多匹配"
      与"已退役"是两种不同的事实，合并会让回执读不出处置方向；
    - 解析到了成员、但角色读不出来 / 不是收件箱认得的角色 ⇒ `member_has_no_role`。

    候选点名：歧义那一档是匹配到的那几个名册名（`candidates`），认不出那一档是
    "你能通话的是"（`callable`）—— 两处都写进那句话里，不许静默。
    """
    how = str(addr.get("how") or "")
    refused = str(addr.get("refused") or "")
    candidates = [str(x) for x in (addr.get("candidates") or [])]
    callable_line = str(addr.get("callable") or "")
    error = str(addr.get("error") or "")
    if refused == "roster_unavailable" or how == "roster_unavailable":
        return ("roster_unavailable", candidates,
                (f"名册这一趟不在手上（{str(addr.get('why') or addr.get('error') or '未给理由')}）"
                 f"⇒ 解析不了 {written or '（空）'} 指向谁；要么把收件人写成角色名，"
                 "要么等名册可读再发（名册没读成不等于'没有这个人'）"))
    if refused == "not_in_roster" or how == "not_in_roster":
        return (DECODE_UNKNOWN_ROSTER_NAME, candidates,
                (f"名册上没有 {written or '（空）'} 这个名字/编号 ⇒ 受控拒绝：不许按名字瞎发。"
                 f"你能通话的是：{callable_line or '（名册上没有人可通话）'}"))
    if refused:
        return refused, candidates, error or f"{written} 的名册解析受控拒绝（{refused}）"
    role = str(addr.get("role") or "")
    if not role or not _known_recipient(role):
        return (DECODE_MEMBER_WITHOUT_ROLE, candidates,
                (f"名册上 {written} 这一行读不出一个收件箱认得的角色（role={role!r}）⇒ "
                 "受控拒绝：原样投递会写进一个没人读得到的收件箱"
                 f"（你能通话的是：{callable_line or '（名册上没有人可通话）'}）"))
    return "", candidates, ""


def _decode_roster_outcome(written: str, roster: Any
                           ) -> tuple[dict[str, Any] | None, dict[str, Any], str]:
    """名册写法在解码层的唯一落点（`message` 与 `handoff` 两条通道共用）。

    返回 `(拒收载荷, 读数格, 那句话)`，三条出口由调用方按同一个顺序读：

    - `拒收载荷` 非空 ⇒ 受控拒绝：里面已经有 `to` / `refused` / `candidates` /
      `callable` / `error`，调用方原样返回（同一份拒绝码，不各写一套）；
    - `拒收载荷` 为空而 `读数格["role"]` 非空 ⇒ 解析到了那个角色：调用方把 `to`
      换成收件箱认得的角色、把读数格原样挂到 `roster_addressing` 上；
    - 两格都空 ⇒ 这一次解码没有名册上下文（`roster is None`：模块级单测直接调
      `_decode_shape` 的那一档）⇒ 调用方按改前的判据拒收。

    为什么抽成一处：`message` 与 `handoff` 的"名册名 / 绝对编号"必须是同一份解析、
    同一个拒绝码。改前只有 `message` 那一支接了名册解析，而 D-63 之后政策教的就是
    名册名 —— 手稿通道若不接，模型照政策写的那一句会被判非法（提示词教了一个框架
    不收的字面量，本仓反复记过的形态）。

    D-63 起读数格多带一格 `addressed_by`（`roster_name` / `task_id` /
    `role_fallback`）：回执上要能看出这一次是靠哪种写法定到收件人的。
    """
    addr = _decode_roster_recipient(written, roster)
    if addr is None:
        return None, {}, ""
    code, candidates, error = _decode_roster_problem(addr, written)
    if code:
        refused = {"to": str(written or ""), "refused": code,
                   "candidates": [str(x) for x in candidates],
                   "callable": str(addr.get("callable") or ""), "error": error}
        return refused, {}, f"{code}：{error}"
    return None, {"written": str(written or ""),
                  "name": str(addr.get("name") or ""),
                  "task_id": str(addr.get("task_id") or ""),
                  "role": str(addr.get("role") or ""),
                  "how": str(addr.get("how") or ""),
                  "addressed_by": str(addr.get("addressed_by") or "")}, ""


def _decode_shape(data: Mapping[str, Any], *,
                  roster: Any = None) -> tuple[str, Mapping[str, Any], str]:
    """规范形态的解码：一次只说一件事，取的那个键必须是 `SHAPES` 里的一种。

    清单与条数以 `SHAPES` 为唯一来源，本处不重抄第二份 —— 这里原先手抄的形状条数
    与 `SHAPES` 不一致，漏掉的正是 `handoff`（手稿落行的唯一入口：真机 1542 行手稿里
    967 行由框架派生、模型自写 0 行，而正典表里看不见它）。别名只负责把扁平形态
    改写成这里认的形态。

    两段式（业主 2026-10-21）：`accept_proposal` / `reject_proposal` 这两个受控字段
    由这一步的解码带过去 —— 解码是白名单，漏带就等于"父说了接受、框架没听见"，
    而那在读数上与"父还没表态"完全一样。两个名字的真身只在 `secretary`（唯一来源，
    本处延迟导入）：这里不解码它们的内容，只保证它们活得过去。

    `roster`（2026-10-22，业主「按编号沟通」）：`message.to` 除了角色名 / M / `#public`
    之外还认名册名（`B1`）与绝对台账号 —— 判据与解析都走调用方给的 `roster`
    （真身是 `roster_addresses`，本处不另写一份形状判断），解析出来的角色才进 `to`
    （收件箱按角色收），原写法与解析结果留在 `roster_addressing` 里供回执对账。
    认不出 / 有歧义 / 名册读不成 ⇒ 受控拒绝码 + 候选点名（见 `_decode_roster_problem`）。
    """
    accept_field, reject_field = _proposal_fields()

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
        # 2026-10-16（S2「M 只派活」）：`task` 也要带过去 —— 广告面（`llmseam.META_FUNCTIONS`）
        # 它是"不点动作时必填的那件活"，解码器丢它 ⇒ 模型写了活、框架说"你没写活"。
        # 判据 `tests/test_native_tool_calls.py::test_every_advertised_key_survives_the_decoder`
        # 当场抓出这一条（它就是为这种"广告一份、解码另一份"设的）。
        extra: dict[str, Any] = {k: str(value.get(k)) for k in ("brief", "name", "reuse", "task")
                                 if str(value.get(k) or "").strip()}
        # 两段式（业主 2026-10-21）：确认/拒绝那两个受控字段要带过去 ——
        # 这一步的解码是白名单，不带就等于"父说了接受、框架没听见"，
        # 而那在读数上与"父还没表态"长得一样（同一族缺陷见上面 `brief`/`task` 那两段）。
        # 只在给了的时候带：老载荷的键集因此一个字节不变。
        # 字段名不在这里另写一份：真身在 `secretary`（延迟导入 —— 那个模块在装秘书那一侧
        # 才需要，本模块在解码这一步只需要两个字符串）。
        extra.update({k: str(value.get(k)) for k in (accept_field, reject_field)
                      if str(value.get(k) or "").strip()})
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
                k: str(item.get(k)) for k in ("brief", "name", "reuse", "task")
                if str(item.get(k) or "").strip()}
            # S1g：与 `summon` 那一支同一口径（声明里的参数被摆在目标顶层 ⇒ 别静默丢）。
            item_extra.update(_carried_top_level_params(role, action, item, params))
            clean.append({"role": role, "action": action, "params": dict(params),
                          "instance": str(item.get("instance") or ""),
                          "input_key": str(item.get("input_key") or ""),
                          **item_extra})
        out: dict[str, Any] = {"targets": clean, "why": str(value.get("why") or "")}
        # 两段式：一批也能整批请示/确认（与 `summon` 同一口径，只在给了的时候带）。
        out.update({k: str(value.get(k)) for k in (accept_field, reject_field)
                    if str(value.get(k) or "").strip()})
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
        written = str(value.get("to") or "")
        # `to` 的合法集合 = 八个角色 ∪ 主控 M ∪ 公共频道。M 必须在内（2026-09-30 真机修）：框架自己的
        # 代唤通道 `_request_relay` 就用 `to=S.CONDUCTOR_ROLE`（= "M"），而这里原来只认 `S.ROLES`（A–H，
        # 不含 M）⇒ 提示词教角色"直接发给 M"、角色照做却被判 `invalid`（场景 G 白扔一步：那条只该主控看到的
        # 申请被广播），而 `read_messages(role="M")` 本来就收 `to="M"` 的留言。`ALL` 也认（2026-10-05）：
        # 手稿通道约定"给所有人写 `to="ALL"`"（文件名 `…toALL.md`），原来只认 `#public` ⇒ M 写
        # `{"message": {"to": "ALL", …}}` 被判不合法、连三次 ⇒ `bad_json_limit` 收场（60 秒、一步有效的活都没干）。
        # `ALL` / `#public` 的等价只在 `_is_all_recipient` 一处定义，`message` / `handoff` / `notify` 三条通道
        # 都从那里取 —— 不许各写一份。
        to = _recipient_for_channel(written)      # 留言通道的"给所有人"规范形是 `#public`
        if not _known_recipient(to):
            # 2026-10-22（业主「按编号沟通」）：`_known_recipient` 之外还认名册名与
            # 绝对台账号 —— 判据与解析都在 `roster_addresses`（经 `roster` 传进来），
            # 这里只负责"翻成谁"与受控拒绝码。改前这些写法一律被判 invalid / bad_args
            # ⇒ 模型照提示词写 `to="B1"` 一步也发不出去，而名册那一层明明支持它。
            # D-63（2026-10-24 业主：「现在怎么还有to谁的写法？已经是名册机制了！」）：
            # 这段解析与 `handoff` 那一支共用同一个落点（`_decode_roster_outcome`）。
            refused, marker, problem = _decode_roster_outcome(written, roster)
            if refused is not None:
                return key, refused, problem
            role = str(marker.get("role") or "")
            if not role:
                return "", {}, (f"收件人 {to!r} 既不是角色（{S.ROLES}）、也不是主控 "
                                f"{S.CONDUCTOR_ROLE}、也不是公共频道 {PUBLIC}（写 ALL 也认）")
            # 原写法 + 解析结果（读数要能对回原稿）。`to` 已经是收件箱认得的角色：
            # 收件箱按角色收，把 B1 原样写进 `to` 只会得到一条没有进程读得到的留言
            # （业主 2026-10-22 的原话）。读数格在 `_decode_roster_outcome` 里造，
            # 这里不另拼一份（两份会漂）。
            return key, {"to": role,
                         "subject": str(value.get("subject") or "（无标题）"),
                         "body": str(value.get("body") or ""),
                         "reply_to": str(value.get("reply_to") or ""),
                         "roster_addressing": marker}, ""
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
        #
        # D-63（2026-10-24 业主：「现在怎么还有to谁的写法？已经是名册机制了！」）：
        # 名册名 / 绝对编号也是这一格的合法写法 —— 与 `message` 共用同一个解析落点
        # （`_decode_roster_outcome`）。手稿台账的收件人面仍然是角色（`manuscripts` 的
        # 主键口径），所以解析到成员之后 `to` 写它的角色、原写法进 `roster_addressing`；
        # "这一条通知落到哪个实例的板上"由 `_do_handoff` → `_handoff_address` 决定
        # （那一步用的是原写法，不是这里的角色）。
        roster_marker: dict[str, Any] = {}
        if not _known_recipient(to):
            refused, marker, problem = _decode_roster_outcome(to, roster)
            if refused is not None:
                return key, refused, problem
            role = str(marker.get("role") or "")
            if not role:
                return "", {}, (f"收件人 {to!r} 既不是角色（{S.ROLES}）、也不是主控 "
                                f"{S.CONDUCTOR_ROLE}、也不是 {PUBLIC}（给所有人写 to=\"ALL\"，"
                                "两种写法等价）")
            to = role
            roster_marker = marker
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
        ret = {"to": _recipient_for_channel(to, all_as="ALL"), "summary": summary,
               "body": body,
               "refs": [str(x) for x in refs],
               # `R2b-⑲`：带了这一格 ⇒ 走秘书的 `handoff_revise`（订正某一号，
               # 旧行保留）。它是可选键：不填就是新增（旧行为逐字不变）。
               "revises": str(value.get("revises") or "").strip(),
               "why": str(value.get("why") or "")}
        if roster_marker:
            # 只在原写法是名册写法时才加这一格：老载荷的键集因此一个字节不变
            # （与 `notify` / `blocked` 那些"给了才带"的键同一条纪律）。
            ret["roster_addressing"] = roster_marker
        return key, ret, ""
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
        #
        # `scope`（S-H 裁定 14 的"全树"那一档）必须原样带过：它此前在解码器这一层被丢掉，
        # 于是提示词里写的 `scope="descendants"` 在协议上不可达 ——
        # 读侧 `_do_roster` 支持它、原生工具面的 schema 也补了它、秘书那一侧的正控也测过，
        # 断的只有这一条缝（业主 2026-10-11 口径：一切以代码为参考 ⇒ 把代码自己的意图接通）。
        # 取值合法性仍归读侧判（不认的值当场拒绝），与 `of` 同一条分工。
        # 空串不写进 payload：`{"of": …}` 的形状保持不变（老路径逐字节不变）。
        scope = str(value.get("scope") or "").strip()
        return key, ({"of": of, "scope": scope} if scope else {"of": of}), ""
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
    if data.get("not_consumed") is not None:
        # 业主裁定（父必须处理子产出）的如实声明那一格：父在收工那句话里显式写
        # `"not_consumed": [{"task_id": …, "code": …, "why": …}]`。
        # 解码器只做"认出了这个键、原样带过"（与 `notify` / `blocked` 同一纪律：
        # 恒为空的键会让"没声明"与"声明了空"长得一样）；受控理由码与
        # "这个 task_id 是不是这趟真的派过的"在 `summon_consumption` 里判 ——
        # 那里才知道这一趟派过什么（解码器是纯函数，判不了）。
        payload["not_consumed"] = data.get("not_consumed")
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
                                         "notify", "why", "shape_alias", "tool", "args",
                                         # 两段式的确认/拒绝：它们是协议字段，
                                         # 既不是动作参数，也不许被折算进 `params`
                                         # （真身见 `secretary.ACCEPT_PROPOSAL` / `REJECT_PROPOSAL`）。
                                         "accept_proposal", "reject_proposal")


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


def _callable_members(secretary: Any, *, owner: str
                      ) -> tuple[list[dict[str, Any]], str]:
    """我「能通话的人」 = 我的父 + 我的子（业主 2026-10-19，逐字：「只有这些编号能通话」）。

    返回 `(成员, 问题)`；问题非空 ⇒ 名册这一格没读成（调用方按 `roster_unavailable` 处理 —— 不许当成"名册里一个人都
    没有"，那会把一次读失败变成一次静默的按角色名投递）。每个成员：
    `{"kind": "parent"|"child", "name", "task_id", "role", "brief", "retired"}`，`task_id` 是「绝对编号」（业主的要
    求），`name` 是名册名（父的名册名记在祖父的名册里，由 `roster_view` 的 `parent` 那一格换算好；读不到就是空串）。

    三件刻意的事：只读 `roster_view(owner=我自己)` 这一份（父在 `parent`、子在 `rows`，不另造视图）；`limit` 给到极
    大（默认只回 20 行，用默认值数匹配会在第 21 个子代理上悄悄数错，`more` 是读数不是判据）；父的 `checked` 为假（台
    账读不成 / 我这一行不在台账里）⇒ 集合「不完整」⇒ 报问题而不是"没有父"（少一个成员会变成一次「误拒」，与"多放进来
    一个"一样错）。
    """
    try:
        view = secretary.roster_view(owner=str(owner or ""), limit=1_000_000)
    except Exception as exc:  # noqa: BLE001 —— 读不成要如实说
        return [], f"名册读不成（{type(exc).__name__}: {exc}）"
    if not view.get("checked"):
        return [], f"名册没读成（{view.get('reason') or '未给理由'}）"
    parent = dict(view.get("parent") or {})
    if not parent.get("checked"):
        return [], (f"父是谁没读成（{parent.get('why') or '未给理由'}）"
                    "⇒ 能通话的集合不完整（不许当成'没有父'）")
    members: list[dict[str, Any]] = []
    if str(parent.get("task_id") or ""):
        members.append({"kind": "parent", "name": str(parent.get("name") or ""),
                        "task_id": str(parent.get("task_id") or ""),
                        "role": str(parent.get("role") or ""), "brief": "",
                        "retired": False})
    for r in view.get("rows") or []:
        members.append({"kind": "child", "name": str(r.get("name") or ""),
                        "task_id": str(r.get("task_id") or ""),
                        "role": str(r.get("role") or ""),
                        "brief": str(r.get("brief") or ""),
                        # `status` 的四档里 `retired` 是唯一"不许再被寻址"的那一档；
                        # `running`/`idle`/`ready` 都还叫得应（板项会等它下次进循环）。
                        "retired": str(r.get("status") or "") == "retired"})
    return members, ""


def _callable_line(members: Sequence[Mapping[str, Any]]) -> str:
    """「你能通话的是：…」那一句（受控拒绝的拒信里必须给的那一份名单）。"""
    live = [m for m in members if not m.get("retired")]
    if not live:
        return "（这张名册上没有一个可通话的人：先派活，名下才会有子代理）"
    parts = []
    for m in live:
        mark = "父" if str(m.get("kind") or "") == "parent" else "子"
        parts.append(f"{mark} {m.get('name') or '（无名）'}（{m.get('task_id')}）")
    return "、".join(parts)


#: 探针读数里「这一条按名册投得成投不成」的那几格（成功的一档挪进 `addressing.roster_probe`）。
_ROSTER_PROBE_KEYS: tuple[str, ...] = ("checked", "how", "refused", "error", "why")

#: 名册不可用时私聊的拒信（理由码沿用读数取值 `roster_unavailable`，不新造词）。
#:
#: 为什么写死一句而不是每个分支各写一句：这一档的判据是同一个（名册读不出来 ⇒ 不校验就不许
#: 开私聊），拒信要回答的也是同一个问题「那我该怎么办」。分支只补"为什么读不出来"。
_ROSTER_UNAVAILABLE_REFUSAL = (
    "名册不可用 ⇒ 私聊不投递（fail-closed：读不出名册时不许按角色名开私聊 —— "
    "那是「没校验」，不是「校验通过」）。上行给父（escalate / 步数上报 / 请代唤）"
    "与手稿的角色级通道不受影响：它们的收件人不是按名册挑出来的")


def delivery_addressing(base: Mapping[str, Any], addr: Mapping[str, Any]) -> dict[str, Any]:
    """成功那一档的 `addressing`：只讲「这一条实际怎么投的」，名册探针另起一格。

    为什么不能把 `addr` 原样合进成功的结果（2026-10-22 查实的缺陷）：`to` 写角色名、
    而那个角色不在我的名册上时，探针给的是 `refused="not_in_roster"` 加一句拒信；
    角色级那一支（按协作边）本来就能把这一条发出去 —— 于是同一个 `addressing` 里
    `ok=true` 与 `refused="not_in_roster"` 并存。走 `ok` 的判据不会因此误判，但事后
    按 `addressing.refused` 统计「被拒几条」的人会把成功的一步算进被拒。

    两种修法（清空 / 另起一格）里选后者：`refused` 与 `error` 从 `addressing` 移出，
    探针的整份读数原样进 `addressing.roster_probe` —— 「为什么这次能发给非名册收件人」
    这句话必须还读得到（收紧规则不等于把理由抹掉）。探针没有拒绝时那一格不出现
    （成功的一步不为空读数长出一个键）。

    D-63 起 `addressed_by`（`roster_name` / `task_id` / `role_fallback` /
    `role_dispatch` / `channel`）留在成功那一档的 `addressing` 里：它不属于"被拒"，
    而是"这一条是靠哪一种写法定到收件人的" —— 抹掉它，兼容档（角色代号兜到的那些）
    就数不出来了。它也不进 `roster_probe`：那是"名册探针怎么答的"，与"最终用了哪一档"
    是两个问题。
    """
    merged = {**base, **addr}
    out = {k: v for k, v in merged.items() if k not in ("refused", "error")}
    probe = {k: merged.get(k, "") for k in _ROSTER_PROBE_KEYS}
    if str(probe.get("refused") or "") or str(probe.get("error") or ""):
        out["roster_probe"] = probe
    return out


def roster_addresses(secretary: Any, *, to: str, owner: str = "",
                     my_task_id: str = "", sender: str = "") -> dict[str, Any]:
    """把收件人写法 `to` 解析成"名册上的那个成员"（业主 2026-10-19 的裁定）。

    口径（业主逐字）：名册 = 自己的父与子（含绝对编号），「只有这些编号能通话」，其余 `to` 一律拒收（不许按角色名随便
    发）。可接受的写法三种，且三种都必须落在"父 ∪ 子"里：①绝对编号（`task_id`，业主点名的第一公民）；②名册名（`F1` /
    `D1`）；③角色名（`F`，只作便利写法 —— 名册内唯一匹配才算，匹配到 0 个或多个都拒）。
    返回三态（不许折平）：`checked`（名册读成了没有，`False` 不等于"名册里没有这个人"）、`how`（这一条为什么这么投）、
    `kind`/`name`/`task_id`/`role`（解析到的成员）、`candidates`（同名多匹配时全部的候选名册名）、`callable`（「你能通
    话的是：…」，每一张拒信都带它）、`refused`（受控拒绝的理由码，空串 = 没拒）、`error`（给人/给模型读的那句拒信）。
    `how` 的取值（每一个都由某一行产出，没有死取值）：`outside_roster`（① `#public` / `ALL` —— 公共频道有自己那一套可
    见面判据，业主 T20/T21；②用户；③主控 M —— 代唤协议逐字要求任何角色都能把申请发给它；外加主控当发信人时按角色名派活
    /通知那一档）、`roster_unavailable`（没有秘书 / 没有台账号 / 名册读不成 ⇒ 私聊「不投递」：
    这一档带 `refused="roster_unavailable"` 与一句拒信，调用方按受控拒绝处理 —— 2026-10-22 按业主
    口径从 fail-open 改成 fail-closed，那之前它是"退回原来的路照发，读数标出来"）、`parent` / `child`
    （解析到了 ⇒「只投那一个」）、`member_retired`（已退役 ⇒ 受
    控拒绝，业主 B1：名字永久不复用）、`not_in_roster`（不在"父 ∪ 子"里 ⇒ 受控拒绝）、`ambiguous_in_roster`（角色名匹
    配到多个 ⇒ 受控拒绝 + 列候选，「不替你挑一个」）。
    这一格「只判"发给谁"」，不判"能不能发"：协作边准入仍是 `message_admission` 那一份唯一实现。

    ## `addressed_by`（D-63，业主 2026-10-24：「现在怎么还有to谁的写法？已经是名册机制了！」）

    这一格回答「这一次的收件人是靠哪一种写法定下来的」，取值与产出它的那一行一一对应：

    | 取值 | 含义 | 落到哪里 |
    |---|---|---|
    | `task_id` | 写的是绝对编号（第一公民） | 那个实例 |
    | `roster_name` | 写的是名册名（`D1`） | 那个实例 |
    | `role_fallback` | 写的是角色代号，而该角色在册恰好一个 | 那一个实例（兼容档） |
    | `role_dispatch` | 写的是角色代号、发信人是主控 M、而此刻在册 0 个 | 角色通道（派活/通知） |
    | `channel` | `#public` / `ALL` / 用户 / 主控 M | 频道（不归名册管） |
    | 空串 | 没有解析到任何收件人（含全部受控拒绝） | 无 |

    为什么必须有这一格：改前"按名册名发"与"按角色代号发"在回执上长得一样 ——
    `how` 都是 `parent` / `child`，读的人分不出这一次到底用的是哪一档，于是
    「角色代号还能不能当收件人」这件事在盘上没有读数。有了它，兼容档是可见的、
    也是可数的（`role_fallback` 出现的次数就是"还有多少条在用老写法"）。
    它刻意不是"收件人是不是唯一的"那种判断：唯一性由 `ambiguous_in_roster` 那一档拒。
    """
    out: dict[str, Any] = {
        "to": str(to or ""), "checked": False, "how": "", "kind": "", "name": "",
        "task_id": "", "role": "", "brief": "", "candidates": [], "callable": "",
        "refused": "", "error": "", "why": "", "addressed_by": "",
    }
    token = str(to or "").strip()
    if _is_all_recipient(token) or token in ("user", "用户") or token == S.CONDUCTOR_ROLE:
        out.update(checked=True, how="outside_roster", addressed_by="channel",
                   why=("`#public` / `ALL` / 用户 / 主控 M 不是'给名册上的某个代理发消息'："
                        "公共频道另有可见面判据（业主 T20/T21），用户是频道外的读者，"
                        "而 M 是顶层发起方（名册上没有它的上级）—— 代唤协议逐字要求"
                        "任何角色都能把申请发给它"))
        return out
    if secretary is None:
        out.update(how="roster_unavailable", refused="roster_unavailable",
                   error=_ROSTER_UNAVAILABLE_REFUSAL,
                   why=("这一趟没有秘书 ⇒ 名册不在手上（私聊不投递；"
                        "读数仍标 roster_unavailable，但它不是「名册校验通过」）"))
        return out
    if not str(owner or ""):
        out.update(how="roster_unavailable", refused="roster_unavailable",
                   error=_ROSTER_UNAVAILABLE_REFUSAL,
                   why="这一趟没有台账号 ⇒ 不知道读谁的名册（私聊不投递）")
        return out
    members, problem = _callable_members(secretary, owner=str(owner))
    if problem:
        out.update(how="roster_unavailable", refused="roster_unavailable",
                   error=f"{problem} ⇒ {_ROSTER_UNAVAILABLE_REFUSAL}",
                   why=f"{problem} ⇒ 私聊不投递")
        return out
    out["callable"] = _callable_line(members)
    mine = str(my_task_id or "")
    # ① 绝对编号（业主点名的第一公民）；自己那一行不算（"发给我自己"没有意义）
    hit = [m for m in members
           if str(m.get("task_id") or "") and str(m["task_id"]) == token
           and str(m["task_id"]) != mine]
    how_hint = token
    addressed_by = "task_id" if hit else ""
    # ② 名册名
    if not hit:
        hit = [m for m in members if str(m.get("name") or "") and str(m["name"]) == token]
        if hit:
            addressed_by = "roster_name"
    # ③ 角色名（便利写法：名册内唯一匹配）
    if not hit and token.upper() in S.ROLES:
        role = token.upper()
        live = [m for m in members if str(m.get("role") or "") == role
                and not m.get("retired")]
        if len(live) == 1:
            hit = live
            addressed_by = "role_fallback"
            how_hint = f"角色代号 {role} 在名册内唯一匹配（兼容档）"
        elif len(live) > 1:
            names = sorted(str(m.get("name") or m.get("task_id") or "") for m in live)
            out.update(checked=True, how="ambiguous_in_roster", role=role,
                       candidates=names, refused="ambiguous_in_roster",
                       error=(f"角色代号 {role} 在你的名册上在册 {len(names)} 个"
                              f"（{'、'.join(names)}）⇒ 受控拒绝：不替你挑一个 —— "
                              f"请写名册名或绝对编号：{' 或 '.join(names)}"
                              f"（名册名就是那个实例的名字，绝对编号是它的台账号）"),
                       why=f"名册内同名多匹配：{names}")
            return out
        else:
            dead = [m for m in members
                    if str(m.get("role") or "") == role and m.get("retired")]
            if dead:
                m = dead[0]
                return _retired_member(out, m)
    if not hit:
        if str(sender or "") == S.CONDUCTOR_ROLE and token.upper() in S.ROLES:
            # 主控「按角色派活/通知」那一档：它名下此刻还没有这个角色的实例是正常形态
            # （实例是它 `summon` 时才造出来的），而调度的第一句话就是按角色说的。
            # 这「不是」新放宽：改前 `to="E"` 走的正是这条通道（判据
            # `test_agent_loop.py::test_messages_are_durable_and_reach_only_the_recipient`）。
            # 名册里「有」匹配时上面那几支先命中，所以"同名多实例不许随便挑"对 M 同样成立。
            # `addressed_by="role_dispatch"`：它确实没有落到任何实例上（这是在册 0 个
            # 那一档），读数要能把它与"落到了某个实例"分开。
            out.update(checked=True, how="outside_roster", role=token.upper(),
                       addressed_by="role_dispatch",
                       why=(f"发信人是主控 M ⇒ 按角色代号 {token.upper()} 派活/通知不归名册管"
                            "（它名下这会还没有那个角色的实例）"))
            return out
        out.update(checked=True, how="not_in_roster", refused="not_in_roster",
                   error=(f"{token or '（空）'} 不在你的名册里（只有父与子能通话）⇒ 受控拒绝："
                          f"不许按角色代号随便发 —— 请写名册名或绝对编号。"
                          f"你能通话的是：{out['callable']}"),
                   why=f"名册上没有 {token}（父 ∪ 子 里没有这个编号/名字）")
        return out
    member = hit[0]
    if member.get("retired"):
        return _retired_member(out, member)
    out.update(checked=True, how=str(member.get("kind") or ""),
               kind=str(member.get("kind") or ""), name=str(member.get("name") or ""),
               task_id=str(member.get("task_id") or ""),
               role=str(member.get("role") or ""), brief=str(member.get("brief") or ""),
               addressed_by=addressed_by,
               why=(f"名册成员（{'父' if member.get('kind') == 'parent' else '子'}）"
                    f"{member.get('name') or member.get('task_id')} → "
                    f"实例 {member.get('task_id')}（{how_hint}）"))
    return out


def _retired_member(out: dict[str, Any], member: Mapping[str, Any]) -> dict[str, Any]:
    """退役的名册成员 ⇒ 受控拒绝（理由码 `member_retired`，可读）。"""
    label = str(member.get("name") or member.get("task_id") or "")
    out.update(checked=True, how="member_retired", kind=str(member.get("kind") or ""),
               name=str(member.get("name") or ""),
               task_id=str(member.get("task_id") or ""),
               role=str(member.get("role") or ""), refused="member_retired",
               error=(f"{label} 已退役（业主 B1：名字永久不复用）⇒ 受控拒绝："
                      "退役的名册成员不许再被寻址"),
               why=f"{label} 在名册里标着 retired")
    return out


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


def _dispatch_label(item: Mapping[str, Any]) -> str:
    """派活的那一行怎么称呼它（派生手稿的清单与"一句话"都用它）。

    2026-10-16（业主口径 S2 最终形态）：「action 完全不用父代理填」⇒ 派活不带动作，
    于是原来那句 `f"{role}.{action}"` 会拼出 `D.` 这种没有信息的一行。
    空动作时改用那件活（`task`／`params.task`），读的人才知道派了什么。
    """
    role = str(item.get("role") or "")
    action = str(item.get("action") or "").strip()
    if action:
        return f"{role}.{action}"
    task = str(item.get("task") or (item.get("params") or {}).get("task") or "").strip()
    return f"{role}（派活：{task or '（没写活）'}）"


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


# ------------------------------------------------------------------ 子产出的处理
# 业主裁定（真机证据已核实）：父代理必须处理子代理的产出 —— 现场 `projects/mp4/data/tasks.json` 里 F 的任务
# 都是 `called_by=D`，而 D 派完 F、拿到结果就 `final` 了，F 的产出只留给 M 下一轮读，推进责任被真空地转给最上层。
# 判读三样（唯一实现 `summon_consumption`）：`_call_productions` → `LoopRun.productions`（落点
# `agent_step.productions`）、处置 `consumed` / `waived` / `unconsumed`、汇总读数 `LoopRun.summons_total` 等（落进
# `agent_run_end`）。判据口径（业主 2026-10 修正）：「处理」不是白名单（那三条只是举例，正表会误杀没列举到的
# 合法形态），而是效应证据 —— 这次 summon 之后父在任何一步留下可查的效应、且指到那条子产出（`task_id` /
# 产物路径 / 台账 id）即算处理；"可查"用负表判（`_is_effect_evidence` 只排除只读侦察与无效步）⇒「列举」只在文档里。

#: 一条子产出的处置（受控词表）。`unconsumed` 就是这条规矩要抓的那一格。
#:
#: 顺序即文档顺序：处理了（效应证据）/ 如实声明不处理 / 没处理。
#: 注意这里没有"属于哪一类处理"的取值 —— 那不是判据（见上面的口径说明）；
#: 每一类处理的形状记在那条产出的 `evidence.effect` 里，只作说明、不参与判定。
SUMMON_DISPOSITIONS: tuple[str, ...] = ("consumed", "waived", "unconsumed")

#: `not_consumed` 的受控理由码。自造码 / 空串都不算 waive（负控 ④）：
#: 一张随便写的"我不处理它"等于把这条规矩降成一句自我声明。
NOT_CONSUMED_CODES: tuple[str, ...] = ("superseded", "out_of_scope", "waiting_on_other")

#: "只读侦察"的工具名：命中了子产出也不算效应。
#:
#: 业主逐字给的例子是 `fs.list` / `status_report`。这里把同族的"看一眼"一并登记
#: （`fs.stat` 只看元信息、`fs.search` 只搜、`table.list` / `table.schema` 只看表结构）——
#: 它们的共同形态是"参数能指到产物，但这一步没有改变任何东西"。
#: 刻意不含 `fs.read`：读子代理写的那份报告就是在用它。
RECON_ONLY_TOOLS: tuple[str, ...] = ("fs.list", "fs.stat", "fs.search", "status_report",
                                     "conductor.status", "table.list", "table.schema")

#: 子产出里"可以被别人指到"的两类字面量：台账 id 与产物路径。
#: 判据就是"后续那一步的参数/载荷里出现了其中一个"——业主逐字点名的两类指称。
_CHILD_OUTPUT_ID = re.compile(
    r"\b(?:t|exp|stmt|lit|rel|doc|msg|q|conj|att|proof|ho|handoff|plan|bit)-\d{4,8}\b")
_CHILD_OUTPUT_PATH = re.compile(
    r"(?:[\w.-]+/)+[\w.-]+\.(?:md|markdown|json|jsonl|txt|tex|lean|csv|py|bib)")


def child_outputs_of(result: Mapping[str, Any], *, own_task_id: str = "",
                     limit: int = 40) -> list[str]:
    """这次调用留下的、可以被别人指到的子产出（台账 id + 产物路径）。

    为什么判据落在"字面量"上（而不是"语义上有没有用到"）：机器读数只能读出一行参数里出现了什么。`t-000006`
    这种台账号与 `reports/attack-1.md` 这种产物路径正是父子之间已经在用的指称（业主的措辞逐字就是这两类）；"
    语义上有没有用到"要人来读，不是判据能回答的问题。

    父自己的台账号被剔掉（`own_task_id`）：否则父在后续任何一句里提到自己，都会把所有子产出判成"处理过了"——
    那是这条判据最容易被凑绿的一条路。三态：抽不到任何字面量 ⇒ 空列表，这不等于"没有产出"：`task_id` 一定在
    （由 `_production_item` 补上），它是业主逐字允许的指称。
    """
    text = json.dumps(result, ensure_ascii=False, default=str)
    raw: list[str] = [m.group(0) for m in _CHILD_OUTPUT_ID.finditer(text)]
    raw += [m.group(0) for m in _CHILD_OUTPUT_PATH.finditer(text)]
    own = str(own_task_id or "")
    seen: list[str] = []
    for token in raw:
        if own and token == own:
            continue
        if token and token not in seen:
            seen.append(token)
    return seen[:limit]


def _production_item(result: Mapping[str, Any], *, step: int,
                     own_task_id: str) -> dict[str, Any] | None:
    """一条 summon 产出（`task_id` 是它的身份；被拒的调用没有产出）。"""
    tid = str(result.get("task_id") or "")
    outcome = str(result.get("outcome") or "")
    if not tid or outcome == "refused":
        return None
    outputs: list[str] = []
    for token in [tid, *child_outputs_of(result, own_task_id=own_task_id)]:
        if token and token not in outputs:
            outputs.append(token)
    return {"kind": "summon", "counted": True, "task_id": tid,
            "role": str(result.get("role") or result.get("summoned") or ""),
            "step": int(step), "status": str(result.get("status") or ""),
            "outcome": outcome, "handoff_id": "", "outputs": outputs,
            "disposition": ""}


def _call_productions(shape: str, payload: Mapping[str, Any], result: Mapping[str, Any],
                      *, step: int, own_task_id: str = "") -> list[dict[str, Any]]:
    """把一次 `summon` / `summon_many` / `handoff` 折成"这次调用产生了哪些子产出"。

    三种形状的落点不一样：`summon` ⇒ 一个 `task_id` + 它带回来的结果（`status` / `outcome` / 产物路径与
    `final` 里出现的台账 id）；`summon_many` ⇒ 每个 target 各一条，批量结果没有逐项 `final`/路径的形状（见
    `_do_summon_many` 的 `results` 条目），于是产出字面量只有 `task_id` —— 而业主的判据逐字允许用 `task_id`
    指称；`handoff` ⇒ 手稿是对等通道，不是"下级产出"（没有 `task_id`、也没有子结果可以消费）⇒ 记一条
    `counted=False`，不进 `summons_*` 四个读数，进 `productions` 只是因为业主点名要"这次调用产生了哪些子产出
    "在一处读得到。

    被拒的调用（`outcome="refused"`）没有子产出 ⇒ 一条都不记（于是判据对它没有对象，而不是把它算成"父没处理"）
    。
    """
    out: list[dict[str, Any]] = []
    if shape == "summon":
        item = _production_item(result, step=step, own_task_id=own_task_id)
        if item:
            out.append(item)
    elif shape == "summon_many":
        rows = result.get("results")
        if isinstance(rows, (list, tuple)):
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                item = _production_item(row, step=step, own_task_id=own_task_id)
                if item:
                    out.append(item)
    elif shape == "handoff":
        hid = str(result.get("id") or "")
        if bool(result.get("ok")) and hid:
            out.append({"kind": "handoff", "counted": False, "task_id": "", "role": "",
                        "step": int(step), "status": "", "outcome": "ok", "handoff_id": hid,
                        "outputs": [], "disposition": ""})
    return out


def _waiver_declarations(run: "LoopRun",
                         known: set[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """把各步（含收工那一步）里的 `not_consumed` 读成 waive 表 + 不成立的理由。

    受控三件套（缺一不算 —— 负控 ④ 就是这三条）：`task_id` 指到这一趟真的派过的
    子任务、`code` 在 `NOT_CONSUMED_CODES` 里、`why` 非空（一句话理由）。

    不成立的声明不静默丢弃：逐条进 `problems`，收工那一行会把它念出来。
    静默丢弃会造出最坏的形态 —— 模型写了"我为什么没处理它"，框架不认，
    而双方都以为已经交代过了。
    """
    waivers: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for s in run.steps:
        raw = dict(s.payload).get("not_consumed")
        if raw is None:
            continue
        if isinstance(raw, Mapping):
            items: list[Any] | None = [raw]
        elif isinstance(raw, (list, tuple)):
            items = list(raw)
        else:
            items = None
        if items is None:
            problems.append(f"第 {s.index} 步的 not_consumed 必须是数组或对象，"
                            f"收到 {type(raw).__name__}")
            continue
        for i, item in enumerate(items):
            where = f"第 {s.index} 步 not_consumed[{i}]"
            if not isinstance(item, Mapping):
                problems.append(f"{where} 必须是一个对象（task_id / code / why）")
                continue
            tid = str(item.get("task_id") or "").strip()
            code = str(item.get("code") or "").strip()
            why = str(item.get("why") or "").strip()
            if not tid:
                problems.append(f"{where} 没写 task_id ⇒ 不知道在拒哪一条子产出，不算 waive")
                continue
            if tid not in known:
                problems.append(f"{where} 指的 {tid} 不是这一趟派过的子任务 ⇒ 不算 waive")
                continue
            if code not in NOT_CONSUMED_CODES:
                problems.append(f"{where} 的理由码 {code!r} 不在受控表里"
                                f"（只认 {list(NOT_CONSUMED_CODES)}）⇒ 不算 waive")
                continue
            if not why:
                problems.append(f"{where} 只有理由码、没有一句话理由（why 是空的）⇒ 不算 waive")
                continue
            waivers[tid] = {"code": code, "why": why, "step": int(s.index)}
    return waivers, problems


def _is_effect_evidence(shape: str, payload: Mapping[str, Any]) -> bool:
    """这一步有没有留下可查的效应 —— 判据是负表，不是白名单。

    为什么是负表（业主 2026-10 的修正，逐字）："处理"的真实形态远不止三条 —— 写进台账、改计划、立/改猜想、写
    报告、据以改派别的角色、用它的读数做判断、把它交给 H 审、把它折进收工结论……一张正表（"只有这三种算"）会
    把没被列举到的合法形态全判红，而且每加一种形态就要改一次判据。

    所以这里只排除两档：「只读侦察」（`RECON_ONLY_TOOLS`，业主逐字「`fs.list`/`status_report` 这类只读侦察不
    算」—— 它没有改变任何东西，不是效应）；`invalid` 步（它连一次真的调用都不是）。其余一律算「效应候选」，
    真正的判据落在那句"它有没有指到那条子产出"上 ⇒ "列举"只活在文档里，不活在判据里。
    """
    if shape == "invalid":
        return False
    if shape == "tool":
        return str(payload.get("name") or "") not in RECON_ONLY_TOOLS
    return True


def _effect_label(shape: str, payload: Mapping[str, Any]) -> str:
    """这次效应长什么样（只作说明，不参与判定 —— 判据不是按形状分类的）。

    为什么要给这行字：读数要能被人读懂"它到底做了什么"。但它不进判据：
    写成"只认下面这几行字"就把效应证据又缩回成白名单了。
    """
    if shape == "tool":
        return f"工具 {str(payload.get('name') or '?')}"
    if shape in ("summon", "summon_many"):
        return "再派活"
    if shape == "handoff":
        return "交接手稿"
    if shape == "final":
        return "收工结论里的具体产物指涉"
    if shape == "message":
        return "对外留言"
    if shape == "note":
        return "笔记"
    return f"形状 {shape}"


def summon_consumption(run: "LoopRun") -> dict[str, Any]:
    """父代理处理了它派出去的子产出没有 —— 一趟运行结束时的现算读数。

    判据（效应证据口径，不是白名单）：在这一次 `summon` 之后，父只要在任何一步留下了可查的效应、且这一步指到了那条子产
    出（`task_id` / 产物路径 / 台账 id）就算处理了（`disposition="consumed"`）。业主点名的形态只是举例：写进台账（
    `table.create/update`、`register_*`）、改计划、立/改猜想、写报告（`fs.write`）、再派活、交给 H 审、用它做判断、折
    进 final ……任何一条都算；效应由 `_is_effect_evidence` 用负表判（只排除只读侦察（`fs.list` / `status_report` 这类）
    与 `invalid` 步）。
    两端：如实声明不处理（`disposition="waived"`）—— 显式写一条 `not_consumed`（
    `{"task_id": …, "code": <受控理由码>, "why": "<一句话理由>"}`），理由码必须在 `NOT_CONSUMED_CODES` 里、理由不许是
    空串（自造码 / 空码 / 空理由都不算，负控 ④）；没处理（`disposition="unconsumed"`）—— 既没留下指到它的效应也没声明。
    三态与反真空：`summons_total == 0` ⇒ 判据没有对象（不红，但仍报 0）；被拒的调用（`outcome="refused"`）不进
    `summons_total`；只读侦察指到了产物（`recon_only`）既不算处理也不静默，逐条留在明细里。
    """
    productions = [dict(p) for p in (getattr(run, "productions", None) or [])]
    counted = [p for p in productions
               if bool(p.get("counted", True)) and str(p.get("task_id") or "")]
    waivers, problems = _waiver_declarations(run, {str(p["task_id"]) for p in counted})
    for p in counted:
        tid = str(p["task_id"])
        if tid in waivers:
            p["disposition"] = "waived"
            p["waiver"] = dict(waivers[tid])
            continue
        hit: dict[str, Any] | None = None
        recon: dict[str, Any] | None = None
        for s in run.steps:
            if int(s.index) <= int(p["step"]):
                continue
            step_payload = dict(s.payload)
            # 判据只看"它拿这条子产出做了什么"，不看它怎么拒绝它：
            # `not_consumed` 声明里必然写着那个 `task_id`（不然不知道在拒哪一条），
            # 把它算成"指到了产物"会让每一条合法的 waiver 都自动变成消费 ——
            # "拒绝并说明"那条通路就当场失去意义（负控 ④ 当场抓出过这个形态）。
            scan = {k: v for k, v in step_payload.items() if k != "not_consumed"}
            text = json.dumps(scan, ensure_ascii=False, default=str)
            refs = [str(t) for t in (p.get("outputs") or [])
                    if str(t) and str(t) in text]
            if not refs:
                continue
            if not _is_effect_evidence(s.shape, step_payload):
                recon = recon or {"step": int(s.index), "shape": s.shape,
                                  "effect": _effect_label(s.shape, step_payload),
                                  "refs": refs}
                continue
            hit = {"step": int(s.index), "shape": s.shape,
                   "effect": _effect_label(s.shape, step_payload), "refs": refs}
            break
        if hit is not None:
            p["disposition"] = "consumed"
            p["evidence"] = hit
        else:
            p["disposition"] = "unconsumed"
            if recon is not None:
                p["recon_only"] = recon
    # 三个计数的唯一取值来源是那张受控词表（`SUMMON_DISPOSITIONS`）：
    # 于是"有哪几种处置"只在定义处回答一次，这里不另抄一份取值清单
    # （抄两份的形态是"词表加了取值、计数悄悄不认它"）。
    counts = {d: sum(1 for p in counted if str(p.get("disposition") or "") == d)
              for d in SUMMON_DISPOSITIONS}
    consumed, waived, unconsumed = (counts["consumed"], counts["waived"],
                                    counts["unconsumed"])
    # "继续派"只是 consumed 的一个细分（读数，不是判据）：它回答的是
    # "这些处理里有多少是把它接着派出去了"，而"算不算处理"由效应证据判。
    continued = sum(1 for p in counted if p["disposition"] == "consumed"
                    and str((p.get("evidence") or {}).get("shape") or "")
                    in ("summon", "summon_many"))
    return {
        "summons_total": len(counted),
        "summons_consumed": consumed,
        "summons_continued": continued,
        "summons_waived": waived,
        "summons_unconsumed": unconsumed,
        "productions": productions,
        "waiver_problems": problems,
    }


def summon_consumption_sentence(reading: Mapping[str, Any]) -> str:
    """收工那一行里的那句话（与 `agent_run_end.summon_consumption` 同源）。

    为什么总要说一句（哪怕 `summons_total=0`）：这条判据的反真空形态就是
    "这一趟没有对象"。不出声时，"没派过子"与"派了没处理"在收工那一行上
    长得一模一样 —— 而那正是这条规矩要消灭的形态。
    """
    total = int(reading.get("summons_total") or 0)
    if total == 0:
        return ("子产出处理读数：summons_total=0（这一趟没派过子代理 ⇒ 没有要处理的"
                "子产出；判据没有对象，不红）")
    line = (f"子产出处理读数：summons_total={total}，"
            f"consumed={int(reading.get('summons_consumed') or 0)}，"
            f"waived={int(reading.get('summons_waived') or 0)}，"
            f"unconsumed={int(reading.get('summons_unconsumed') or 0)}")
    if int(reading.get("summons_continued") or 0):
        line += f"（consumed 里有 {int(reading['summons_continued'])} 条是『继续派』）"
    bad = [str(p.get("task_id") or "") for p in (reading.get("productions") or [])
           if isinstance(p, Mapping) and str(p.get("disposition") or "") == "unconsumed"]
    if bad:
        line += (f"；**没处理**的是 {bad} —— 拿到结果不等于处理了：在它之后留下任何"
                 "指到它的效应（写台账 / 改计划 / 改猜想 / 写报告 / 再派活 / 折进结论 …），"
                 "或者写 `not_consumed`（受控码 + 一句理由）如实声明不处理")
    problems = [str(x) for x in (reading.get("waiver_problems") or [])]
    if problems:
        line += f"；不成立的拒绝说明：{'；'.join(problems)}"
    return line


def summon_consumption_verdict(reading: Mapping[str, Any]) -> dict[str, Any]:
    """这条判据的红/绿两行可演示形态：一行状态、一行为什么。

    - `green`：`summons_total > 0` 且 `summons_unconsumed == 0`；
    - `red`：`summons_unconsumed > 0`（拿到了结果却没留下指到它的效应）；
    - `n/a`：`summons_total == 0` —— 判据没有对象。它既不是红、也不是通过：
      把"没派过子"折成通过，等于给一条什么都没管的 run 发绿灯（反真空，业主 ⑤）。
    """
    total = int(reading.get("summons_total") or 0)
    bad = int(reading.get("summons_unconsumed") or 0)
    if total == 0:
        status = "n/a"
        why = ("这一趟没有派过子代理（summons_total=0）⇒ 判据没有对象：不红，"
               "但也不记通过")
    elif bad:
        status = "red"
        why = (f"派了 {total} 条子任务，其中 {bad} 条拿到了结果却没有处理"
               "（它之后没有任何一步留下指到它的效应，也没有写受控的 not_consumed）")
    else:
        status = "green"
        why = (f"派了 {total} 条子任务，全部处理过"
               f"（consumed={int(reading.get('summons_consumed') or 0)}，"
               f"waived={int(reading.get('summons_waived') or 0)}）")
    return {"status": status, "why": why, "summons_total": total,
            "summons_unconsumed": bad,
            "line": (f"[父必须处理子产出] {status.upper()} "
                     f"summons_total={total} unconsumed={bad}：{why}")}


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
    #: `max_output_tokens` 这一格已删（2026-10-15 业主裁定：
    #: 「我们不卡 token，只卡总花销的钱」）。
    #:
    #: 它此前是 32,768（上一版从 8,192 抬上来的），而那一格治的正是"写稿步被截断"
    #: —— 但处方错了：我们不设这一栏之后，上游给的额度比 32,768 还宽
    #: （两发真调用对照：不带 `max_tokens` ⇒ `tokens_out=14,015` 且 `finish_reason=stop`；
    #: 带 32,768 ⇒ 12,987）。所以正确的动作是把这一栏整条路删掉（网关的请求体里
    #: 从此不出现 `max_tokens`，见 `modelgw._payload`），而不是继续调这个数。
    #:
    #: 历史读数留在这里，因为它们解释"为什么曾经需要它"：8,192 那一档被打穿过两次
    #: （2026-10-03 第八趟：整份重写 26 KB 的 `main.tex`，`tokens_out` 都是 8192、
    #: 回复截在字符串中间；2026-10-12 T1：思维链 26,215 字把 8,192 吃满、正文 0 字）。
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
    #: 「收工时由我撤」的那把全工作区开关（业主裁定：删是整棵树的事，不是第一个读者的）。
    #: 空 = 这一趟没有读到过该由我收尾撤的开关（或已经撤过）。由 `_stop_applies` 的
    #: `consume_at_end` 决定、由 `_arm_stop_teardown` 记下、由
    #: `_consume_stop_at_teardown` 在 `run()` 收尾（`agent_run_end` 落盘之后）兑现。
    _stop_to_consume_at_end: dict[str, Any] = field(default_factory=dict)

    # ---------------------------------------------------------------- 信箱与唤醒（D-52 / D-53）
    #: 这一趟是"被唤醒开起来的"时，唤醒的理由（空串 = 不是监控回合）。
    #:
    #: 谁来填：`autonomy` 在轮次边界上读到唤醒后、开那一轮时传给 `run_role`
    #: （`monitoring_of=…`）。它有两个后果，都在本文件里：① 第一条 user 消息旁边多一段
    #: 「监控回合」的树形读数与出口限定；② 这一回合的出口被收窄（见 `_monitor_refusal`）。
    monitor_of: str = ""
    #: 这一趟从哪个路径/哪一段被唤醒的读数（`clock` / `inbox`；空串 = 不是唤醒回合）。
    monitor_source: str = ""
    #: 这一趟已经渲染进过提示词的 id（板项 item_id 与留言 msg_id 混装）。
    #:
    #: 为什么它必须存在（而状态机不能替代它）：承认送达是推迟的（`item_state → seen`
    #: 要等"模型真的被问过一次"），而渲染是立刻的。两步之间如果只靠状态机去重，
    #: 一次装不下而留下的积压会在下一步被同一批队头项重新占满 —— 超上限那条规定
    #: （"其余下一次、一条不丢"）就变成了"队头无限重投、队尾永远轮不到"。
    #: 判据 `tests/test_mailbox_delivers_mid_run_and_wakes_the_parent.py` 的第 2 条
    #: 一开始就是被这个形态打红的（10 条投了两次 8 条、后 2 条一直 queued）。
    #:
    #: 两层各管一件事，不许折平：这一层管"这一趟还要不要渲染它"，状态机管
    #: "跨趟它还要不要投"（`queued` 才是要投；`seen` 是已经承认过的）。
    _mailbox_rendered: set[str] = field(default_factory=set)
    #: 「监控回合」是哪一步（-1 = 这一趟没有监控回合）：出口限定只作用在这一步上。
    _monitor_turn_step: int = -1
    #: 监控回合里被出口限定拒了几次（读数；到上限之后放开，免得把一圈拒信当收工）。
    _monitor_refusals: int = 0

    # ---------------------------------------------------------------- 可抢占的派活（D-64）
    #: 派完在"这一步"里最多等多久（秒）。到点就把"已派出 / 还在跑"交回父代理。
    #:
    #: 为什么要留这一段等待：`summon` / `summon_many` 的既有契约是"返回值里有孩子的
    #: 结果"（业主 2026-10-09：汇报就是返回值；`tests/test_d_summons_c_and_c_reports_back.py`
    #: 钉着它）。秒级、十秒级的孩子照旧在同一个步里回来；而 92 分钟那种阻塞被切成
    #: "等一小段，然后父代理继续拿回合"。
    child_step_wait_sec: float = CHILD_STEP_WAIT_SEC
    #: 返场点上最多等多久（秒）：父代理每一次被问之前，先等"有孩子回来 / 有唤醒到点"。
    #:
    #: 为什么要有它（而不是立刻把回合交给模型）：还有子在跑、又没有任何新事实时，
    #: 立刻问模型买到的是一句"我还在等" —— 而循环的步数没有硬上限（裁定 12-K），
    #: 那种空转是无限烧钱。等到有动静再返场，这也是"不忙等、也不不等待"的落点。
    child_return_wait_sec: float = CHILD_RETURN_WAIT_SEC
    #: 收工时还没回来的孩子最多再等多久（秒）；到点就如实留痕，不再等。
    child_exit_drain_sec: float = CHILD_EXIT_DRAIN_SEC
    #: 这一趟还挂着的派活句柄（`{"kind", "handle", "calls", "task_ids", "step"}`）。
    #:
    #: 只装"派出去但还没全部落定"的那些：全部落定的在派活那一步就消费掉了
    #: （于是"孩子很快回来"那条路上的行为与改前逐字相同 —— 一个句柄都不会留下）。
    _child_handles: list[dict[str, Any]] = field(default_factory=list)

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
            self._bind_roster_sink()
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
        self._bind_roster_sink()

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

        ## 与拆分口径的关系（2026-10-22）

        步数按拆分后的条目记（业主要看的步数是拆后的）：一步给 N 条调用 ⇒ N 条条目、
        N 个步号。这里不需要为它加游标 —— 循环里每次迭代只消费一个步号，而"这一回合的第 k 条
        拿到哪个步号"由 `stepdispatch.step_index_of` 算（判据 11 / 12 钉的就是那一处）。
        """
        step = start
        while True:
            yield step
            step += 1

    def _resolve_parent(self, given: str, summoned_by: str) -> tuple[str, str, str]:
        """定这一趟的收件人：`(父的台账号, 父的角色, 问题)`。三条分支，逐条都有理由。

        1. 调用方给了 `given`（`LlmBackend.call` 从它那一行读出来的）⇒ 用它，并把 `summoned_by`（同一个来源
           的 `called_by`）当父的角色；2. 没给 ⇒ 从台账读（`_parent_of_mine`），这是 D89 的修法：子报给父，
           板项的 `parent_task_id` 必须是父的台账号；3. 两个来源都没有 ⇒ 顶层发起：收件人 =
           `(我的台账号, 主控的角色)`，与改前的行为逐字相同。角色为什么落回主控：顶趟那一行的 `called_by` 写
           的是 `"user"`（`open_top_level_run` 的 `by="user"`），而 `"user"` 不是角色名（`schema.ROLES` 里没
           有它）⇒ 按角色归队时只能落到读板的那个人（主控）。

        但"没读成"不是这一支：台账读不成时返回 `pid=""` 并把理由放进第三个返回值 —— 谁都不许把"读不成"当成"
        顶层发起"（前者会让提示词里那一格凭空写一个父编号，拿自己的编号冒充父的编号，模型会照它去沟通）。
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
        # ---- 每步会变的两格挪到 user 消息里（2026-10-19，前缀缓存那一轴）
        # 改前它们在「system」里（那个每步重算 system 的实现今为 `_system_at_step` 的前身），于是几乎每一步
        # system 都变 ⇒ 上游前缀缓存永不命中（实测：第 0 步 54,902 字 / 第 1 步从第 35,035 个字符起就不同，
        # 差异正是"剩余预算 … 已用 0.000000 → 0.001200"）。现在 system 里那两格是静态指路语
        # （`promptstability.SYSTEM_PLACEHOLDERS`），数字在这里现读、追加在消息尾部 ⇒ 前面的前缀逐字节不变。
        # 2026-10-21 补的"跨 run 也会变"那十格不在这条尾部：它们一趟内不变，念在开场那条 user 消息里就够
        # （`_opening_transcript`）。不把 system 里那份冻在开局：那会让 system 说假话（余额是旧的），
        # 而循环协议里逐字写着"预算耗尽时必须收工"。
        notebook = notebook_digest(self.session_root, self.role)
        return (f"{transcript}\n\n---\n现在是第 {step + 1} 步（步数没有硬上限；"
                f"每满 {self.max_steps} 步会向父代理报一次账，由它决定继续放行还是刹停）。{tail}\n"
                f"剩余花销预算：{self._budget_text()}\n"
                f"你的草稿本（最近几条，每一步现读）：\n{notebook}\n"
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

        2026-10-04 修正（`draft/37` §106）：这一栏此前会说谎 —— 它原先只调 `host.wiring_status(store, ...)`，
        那个读数不带 providers，于是 A 被报成 `no_provider`，哪怕这一趟明明接了 openalex。真机后果（T1 第
        14 趟）：M 的提示词里那栏写着"接线态（这一栏是事实）"`A -> no_provider`，它在第 22 步据此写下「A 未
        接线（no_provider）⇒ 盘外引文放弃检索」，整趟没派过一次 A（而 A 的检索是通的：离线探针一次查询就登记
        了 9 行文献、含 Kuchment 那篇 DOI）。

        修法：先问真身（后端登记表里有哪些角色 ⇒ 它们真的能被唤起），再用主机读数补上其余角色（没接线的仍然
        如实报 —— 不是把这一栏变成永远"wired"）。
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


    def _clock_root(self) -> str:
        """本实例的时钟根（`<根>/out/clock/…` 就在它下面）。

        优先 `workspace_root`（与 `registry` 的构造同源：`build_registry(workspace_root=…)`
        把时钟工具绑在同一个根上）；没有就退到 `store.root`。两者都没有 ⇒ 空串
        （调用方据此报"推不了时钟"，而不是假装推过）。
        """
        root = str(self.workspace_root or "")
        if root:
            return root
        return str(getattr(self.store, "root", "") or "")

    def _pump_clock(self, *, step: int, when: str,
                    run: "AgentLoop.LoopRun") -> dict[str, Any]:
        """把到点的计时器推一下（`clock.fire_due`）—— D-53 的生产端。

        生产时钟没有后台线程，所以"到点动作"要有人在步进点/等待点推它。
        推在哪两处：① 每一次 `ask_step` 之前（本方法由 `_deliver_mailbox` 调）；
        ② 每一个被拆出来的条目执行之前（`stepdispatch` 那几条）。

        为什么"推在别人身上"也是对的：`clock.fire_due(workspace)` 是按工作区扫
        全部待发计时器（不区分收件人），而每个 agent 的循环都在推 ⇒ 父在等子（阻塞式
        派活、一步都还没发生）的那段时间里，子代理的步进点会替它把到点的表推响，
        于是"到点项 + 唤醒标记"在父还没回到自己回合时就已经落在盘上。

        三态：`checked=False` 表示这一次没查成（读不到时钟 / 簿记读不成），
        调用方不许把它读成"没有到点的计时器"。
        """
        root = self._clock_root()
        if not root:
            return {"checked": False, "fired": [], "deferred": [], "errors": [],
                    "reason": "没有工作区根 ⇒ 推不了时钟（不是「没有到点的计时器」）"}
        try:
            report = dict(CLK.fire_due(root))
        except Exception as exc:  # noqa: BLE001 —— 推不成是"没查成"
            return {"checked": False, "fired": [], "deferred": [], "errors": [],
                    "reason": f"推时钟失败：{type(exc).__name__}: {exc}"}
        run.clock_pumps += 1
        fired = list(report.get("fired") or ())
        if fired:
            run.clock_fired += len(fired)
            SS.append(self.session_root, {
                "kind": "agent_clock", "role": self.role, "task_id": str(self.my_task_id or ""),
                "step": int(step), "when": str(when), "fired": fired,
                "deferred": list(report.get("deferred") or ()),
                "errors": list(report.get("errors") or ()),
            }, sid=self.sid)
        elif not report.get("checked", True):
            run.notes.append(f"时钟推不动（{report.get('reason') or '没查成'}）⇒ "
                             "这一格的读数是 unknown，不是「没有到点的计时器」")
        elif report.get("deferred") or report.get("errors"):
            run.notes.append(f"时钟推到一半（deferred {len(report.get('deferred') or [])} / "
                             f"errors {len(report.get('errors') or [])}）—— 计时器保持 pending，"
                             "下一次步进再推")
        return report

    def _take_wakes(self, *, step: int, run: "AgentLoop.LoopRun") -> dict[str, Any]:
        """读一次"等我消费"的唤醒标记（并消费掉）—— D-53 的消费端。

        三态（这一段是 D-53 明确要求的）：
        - 读到了、有唤醒 ⇒ `consumed` 非空 ⇒ 这一步是监控回合；
        - 读到了、没有唤醒 ⇒ `consumed` 空 ⇒ "还没到"，不是"查过了没问题"；
        - 读不成 ⇒ `checked=False` + `reason` 进 `run.notes`（未知不许折成"没有"）。
        """
        root = self._clock_root()
        if not root or not str(self.my_task_id or ""):
            return {"checked": False, "consumed": [], "count": 0,
                    "reason": "没有工作区根或台账号 ⇒ 这个读口读不到（不是「没有唤醒」）"}
        got = pending_clock_wakes(root, task_id=self.my_task_id)
        if not got.get("checked"):
            run.notes.append(f"唤醒标记没读成（{got.get('reason')}）⇒ 这一格是 unknown，"
                             "不是「没有唤醒」")
            return got
        if not got.get("events"):
            return {"checked": True, "consumed": [], "count": 0, "reason": ""}
        consumed = consume_clock_wakes(root, got["events"])
        for p in consumed.get("problems") or ():
            run.notes.append(p)
        events = list(consumed.get("consumed") or ())
        if events:
            run.wakes += len(events)
            run.wake_ids.extend(str(e.get("wake_id") or "") for e in events)
            run.wake_events.extend(dict(e) for e in events)
            SS.append(self.session_root, {
                "kind": "agent_wake", "role": self.role, "task_id": str(self.my_task_id or ""),
                "step": int(step), "wake_ids": [str(e.get("wake_id") or "") for e in events],
                "reasons": [str(e.get("reason") or "") for e in events],
                "mailbox_item_ids": [str(e.get("mailbox_item_id") or "") for e in events],
                "checked": bool(consumed.get("checked")),
            }, sid=self.sid)
        return {"checked": bool(consumed.get("checked")), "consumed": events,
                "count": len(events), "reason": str(consumed.get("reason") or "")}

    def _tree_reading(self) -> str:
        """这一支的最新树形读数（谁在飞 / 谁排队 / 谁交差 / 谁失败）—— 现读，三态。

        D-53 的监控回合必须带这一格：没有它，"叫醒它看看全树"就只是叫醒它，
        它还得自己再发一条 `conductor.watch` 才知道看什么（而监控回合的步数也是钱）。
        读不成 ⇒ 带括号的说明，绝不是"这一支一个子代理都没有"。
        """
        cond = self.conductor
        if cond is None:
            return ("（读不到树形读数：这一趟没有 conductor 句柄 ⇒ 这是「没查成」，"
                    "不是「这一支没有子代理」）")
        look = getattr(cond, "tree", None)
        if not callable(look):
            return "（读不到树形读数：这个 conductor 没有 `tree` ⇒ 不是「没有子代理」）"
        try:
            rows = list(look(str(self.my_task_id or "") or None)) if self.my_task_id else list(look())
        except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
            return (f"（树形读数没读成：{type(exc).__name__}: {exc} ⇒ "
                    "不是「名下没有在飞的子代理」）")
        if not rows:
            return ("（台账里读不到这一支的任何行 —— 这是「读不到」，"
                    "不是「这一支没有任何代理」）")
        label = {"running": "在飞", "pending": "排队", "done": "已交差",
                 "failed": "失败", "cancelled": "已取消"}
        lines: list[str] = []
        for r in rows[:40]:
            status = str(r.get("status") or "")
            lines.append(f"- {'  ' * max(0, int(r.get('level') or 0))}"
                         f"[{r.get('task_id')}] {r.get('role')}·{status}"
                         f"（{label.get(status, '未知')}；名下未消 {int(r.get('items') or 0)} 项）")
        if len(rows) > 40:
            lines.append(f"- （还有 {len(rows) - 40} 行没渲染）")
        return "\n".join(lines)

    def _monitor_block(self, *, wakes: Mapping[str, Any], step: int) -> str:
        """监控回合那一段（树形读数 + 触发原因 + 出口限定）。不是监控回合 ⇒ 空串。

        两个入口：① 本文件在回合边界读到唤醒（`_take_wakes` 有消费）；② 调用方
        （`autonomy` 的轮边界）把这一趟标记成监控回合（`self.monitor_of` 非空）。
        """
        triggered = bool(wakes.get("consumed")) or bool(str(self.monitor_of or ""))
        if not triggered:
            return ""
        wake_ids = [str(e.get("wake_id") or "") for e in (wakes.get("consumed") or ())]
        reasons = [str(e.get("reason") or "") for e in (wakes.get("consumed") or ())]
        why = "；".join(x for x in reasons if x) or str(self.monitor_of or "") or \
            "收件箱里有没投递的留言"
        lines = ["【监控回合】这一回合是被唤醒开起来的（不是新派的研究方向）。",
                 f"触发原因：{why}"]
        for e in (wakes.get("consumed") or ()):
            lines.append(f"- 唤醒 {e.get('wake_id')}：{e.get('reason')}"
                         f"（到点 {e.get('due_at') or '未记录'}；"
                         f"对应板项 {e.get('mailbox_item_id') or '（没有）'}）")
        if wake_ids:
            lines.append(f"- 唤醒编号：{', '.join(wake_ids)}")
        lines += ["", "这一支的最新树形读数（现读，不是开场那一刻的快照）：",
                  self._tree_reading(), "",
                  monitor_exit_text(self.role) + "其它动作会被框架拒（`monitor_turn_restricted`）—— "
                  "监控回合不许开新的研究方向，也不许拿它做研究。"
                  f"（本回合 = 第 {step + 1} 步。）"]
        return "\n".join(lines)

    # ---------------------------------------------------------- 子代理返场（D-64）
    def _register_child_handle(self, handle: Any, *, kind: str, calls: Sequence[Any],
                               step: int = -1) -> dict[str, Any]:
        """把一个派活句柄挂在循环上（返场点从这里读）。返回那一笔挂账。

        ## 登记时机（"派出去就登记，落定了就摘掉"）

        派活那一步会先登记再等一小段：这样等待期间到达的时钟唤醒能把它打断
        （D-53 的监控回合不该被一个 180 秒的等待压住），而"等到了"的那些
        在下面被取走、摘掉 —— 于是"孩子很快回来"那条路上的行为与改前逐字相同
        （结果照旧写进派活那一步的返回值，一个句柄都不会留下）。
        """
        wait_any = getattr(handle, "wait_any", None)
        if kind != "summon_many" and not callable(wait_any):
            wait_any = getattr(handle, "wait", None)
        rec = {
            "kind": str(kind), "handle": handle, "calls": list(calls),
            "step": int(step), "wait": wait_any, "taken": False,
        }
        self._child_handles.append(rec)
        return rec

    def _forget_child_handle(self, rec: Mapping[str, Any]) -> None:
        """把一笔挂账摘掉（派活那一步已经把它的结果写进返回值了）。"""
        self._child_handles = [r for r in self._child_handles if r is not rec]

    def _children_running(self) -> list[str]:
        """还在跑的编号（全部挂着的句柄合起来，按登记顺序）。"""
        out: list[str] = []
        for rec in list(self._child_handles):
            handle = rec.get("handle")
            if handle is None:
                continue
            if rec["kind"] == "summon_many":
                out.extend(str(x) for x in (handle.running() or ()) if x)
            else:
                tid = getattr(handle, "task_id", None)
                if tid and not handle.done():
                    out.append(str(tid))
        return out

    def _take_child_results(self, rec: Mapping[str, Any]) -> list[Any]:
        """取走这一笔"新回来的"结果（每一条只投一次）。"""
        handle = rec.get("handle")
        if handle is None:
            return []
        if rec["kind"] == "summon_many":
            take = getattr(handle, "take_settled", None)
            return list(take() or ()) if callable(take) else []
        if rec.get("taken") or not handle.done():
            return []
        rec["taken"] = True            # type: ignore[index]
        return [handle.result()]

    def _child_settled_text(self, rows: Sequence[Any]) -> str:
        """把回来的那几条渲染成一段给人读的增量（与阻塞版里的字段同名）。"""
        lines: list[str] = []
        for r in rows:
            head = (f"- [{getattr(r, 'task_id', '') or '（没编号）'}] "
                    f"{getattr(r, 'role', '')} 结局 "
                    f"{getattr(r, 'status', '')}/{getattr(r, 'outcome', None) or '-'}")
            reason = str(getattr(r, "refusal_reason", None) or "")
            if reason:
                head += f"（拒绝理由 {reason}）"
            detail = _clip(getattr(r, "detail", "") or getattr(r, "error", "") or "", 200)
            lines.append(f"{head}：{detail}" if detail else head)
            payload = getattr(r, "payload", None)
            if isinstance(payload, Mapping):
                path = str(payload.get("llm_run_path") or "")
                if path:
                    lines.append(f"  它的完整记录：{path}；它的结论："
                                 f"{_clip(payload.get('final') or '（没留下结论）', 300)}")
        return "\n".join(lines)

    def _children_round_trip(self, *, step: int, run: "AgentLoop.LoopRun",
                             wait: bool) -> dict[str, Any]:
        """返场点：把已经回来的孩子取走、渲染成一段增量；还没回来的等一小段。

        ## 为什么它挂在 `_deliver_mailbox` 上（而不是另开一个投递点）

        D-52 已经把"每一次 `ask_step` 之前投一次增量"这件事收敛到那一个点上，
        D-64 的回灌必须走同一条：孩子回来的结果与板项、留言一样，都是"这一步
        才到的事实"，混进同一条 user 消息才不会出现"两条增量、两种去重"。

        ## 等待语义（不是忙等，也不是不等待）

        `wait=True` 时最多等 `child_return_wait_sec` 秒，但只要有孩子落定、
        或者时钟唤醒到点，就立刻返场（那是生产性的回合）。等待本身走句柄的
        条件变量（`WaveHandle.wait_any` / `SummonHandle.wait`），不是空转。
        """
        running_before = self._children_running()
        waited = {"reason": "none", "waited_sec": 0.0}
        if wait and running_before:
            waited = self._wait_for_children(timeout=float(self.child_return_wait_sec))
        settled: list[Any] = []
        still: list[str] = []
        for rec in list(self._child_handles):
            settled.extend(self._take_child_results(rec))
            handle = rec.get("handle")
            if rec["kind"] == "summon_many":
                still.extend(str(x) for x in (getattr(handle, "running", lambda: [])() or ())
                             if x)
            else:
                tid = getattr(handle, "task_id", None)
                if tid and not handle.done():
                    still.append(str(tid))
        # 全部落定的那些从挂账上摘掉（下一回合不再看它）
        self._child_handles = [r for r in self._child_handles
                               if not _child_record_done(r)]
        text = ""
        if settled:
            text = ("【子代理返场】你派出去的那些活回来了几条（这不是新消息，是你自己的"
                    "子代理交差）：\n" + self._child_settled_text(settled))
        if still:
            text = (text + "\n\n" if text else "") + (
                f"【子代理还在跑】名下还有 {len(still)} 项没回来："
                f"{'、'.join(still)}。它们回来之后会在下一次返场时投到这里。"
                "这段时间你仍拿得到回合：可以 `conductor.watch` 看全树、`conductor.guide` "
                "给指导、补派新活，或者把手上别的事推进；收工（final）会被拒到它们回齐"
                "（可抢占不等于不等孩子）。")
        return {"text": text, "settled": settled, "running": still,
                "checked": True, "wait": waited}

    def _wait_for_children(self, *, timeout: float) -> dict[str, Any]:
        """等"全部回来 / 时钟唤醒到点 / 到点"。返回读数（`reason` 说清是哪一种）。

        ## 一个坑：`wait_any` 不是"全部落定"

        句柄那两档的等待语义不同：`WaveHandle.wait_any()` 是"又有东西落定"
        （可抢占的语义），`SummonHandle.wait()` 是"这一个落定"。两种情况都可能
        "还有别人在跑"，所以这里只把它当作"带早醒的睡"，不把它当成
        "全回来了"—— 每一轮都回到 `_children_running()` 重新判。
        改前的写法（`wait(...) is True ⇒ settled`）会让"2 个孩子里回来 1 个"
        读成"全回来了"，于是派活那一步把另一个还在跑的孩子记成终局。

        每 0.5 秒看一眼唤醒标记（它是文件，读一次很便宜）：这样 D-53 的
        "每 10 分钟看一次全树"不会因为父代理正卡在等孩子里而晚到整整一个切片。
        """
        began = time.monotonic()
        deadline = began + max(0.0, float(timeout))
        while True:
            if not self._children_running():
                return {"reason": "settled", "waited_sec": time.monotonic() - began}
            if self._wake_pending():
                return {"reason": "wake", "waited_sec": time.monotonic() - began}
            left = deadline - time.monotonic()
            if left <= 0:
                return {"reason": "slice", "waited_sec": time.monotonic() - began}
            for rec in list(self._child_handles):
                wait = rec.get("wait")
                if not callable(wait):
                    continue
                try:
                    wait(min(left, 0.5))
                except Exception:  # noqa: BLE001 - 等坏了不许把返场点一起带走
                    continue

    def _wake_pending(self) -> bool:
        """有没有到点的唤醒（读不成 ⇒ 当作没有；下一次会重新读）。"""
        try:
            from . import clock as CLK

            got = CLK.pending_wakes(self.session_root, task_id=str(self.my_task_id or ""))
        except Exception:  # noqa: BLE001 - 见 docstring
            return False
        return bool(int(got.get("count") or 0)) if isinstance(got, Mapping) else False

    def _children_hold(self) -> str:
        """收工门（D-64 与 D-68 的接缝）：还有孩子在跑 ⇒ 不许收口。

        返回拒信（空串 = 放行）。业主口径的机器形态：「final 仍要求整棵树销号」——
        于是"可抢占"不许变成"不等子就收口"。这一道闸只认我自己派出去、还没回来
        的那些（台账里别人的行不在我的判断范围内：那是 D-68 那一条收工门的事）。
        两道门各管一件事，顺序上这一道先响（它更具体：点名到编号）。
        """
        running = self._children_running()
        if not running:
            return ""
        return (f"收工被拒（children_running）：你名下还有 {len(running)} 项派出去的活"
                f"没回来（{'、'.join(running)}）。可抢占不等于不等孩子 —— 它们回来之后"
                "结果会在下一次返场时投给你。现在可以：`conductor.watch` 看它们到哪一步、"
                "`conductor.guide` 给它们一句指导、补派新活，或者先推进手上别的事；"
                "它们回齐了再 final。")

    def _settle_children_at_exit(self, *, run: "AgentLoop.LoopRun") -> None:
        """退场：还挂着的孩子最多再等 `child_exit_drain_sec` 秒，然后如实留痕。

        为什么不是无限等：一次收工（预算用完 / 叫停 / 协议连击）不许被一个后台
        handler 拖住；那些孩子是台账里真实的行，会在后台跑完并各自落终态 ——
        这一趟要给的是"我走的时候它们还没回来"这句话，不是假装它没发生。
        """
        running = self._children_running()
        if not running:
            self._child_handles = []
            return
        waited = 0.0
        if float(self.child_exit_drain_sec) > 0:
            got = self._wait_for_children(timeout=float(self.child_exit_drain_sec))
            waited = float(got.get("waited_sec") or 0.0)
        left = self._children_running()
        if not left:
            self._child_handles = []
            return
        note = (f"收工时还有 {len(left)} 项派出去的活没回来（{'、'.join(left)}）；"
                f"已经又等了 {waited:.1f}s。它们不在这条进程的调用栈上，会在后台跑完并各自"
                "落终态 —— 这一趟没有等它们收口（如实记，不假装它们回来了）")
        run.notes.append(note)
        SS.append(self.session_root, {
            "kind": "agent_children", "role": self.role,
            "task_id": str(self.my_task_id or ""), "step": -1,
            "settled": [], "running": list(left), "waited_sec": round(waited, 3),
            "why": "exit", "checked": True,
        }, sid=self.sid)

    def _deliver_mailbox(self, *, step: int, messages: list[dict[str, Any]],
                         run: "AgentLoop.LoopRun") -> dict[str, Any]:
        """信箱投递点：每一次 `ask_step` 之前投一次增量（D-52 的唯一投递点）。

        三件事按顺序，缺一件都不算投递成功：

        1. 先推时钟（`_pump_clock`）—— 到点动作要在读信箱之前发生，否则这一趟
           读到的永远是"上一刻盘上的样子"（到点项刚写出来就漏掉一轮）；
        2. 读唤醒（`_take_wakes`）—— 有唤醒就把这一段变成监控回合（树形读数 + 出口限定）；
        3. 读信箱（`mailbox_digest`）—— 板项 + 留言，渲染成一段增量消息，
           追加成一条 user 消息（不是重渲染开卷），并落一条 `agent_mailbox` 事件。

        投递的承认（板项 `→ seen`、留言 `→ 已投递`）不在这里：它推迟到"模型真的
        被问过一次"之后（`run()` 里 `call.ok` 那一支，与改前的 `pending_delivery` 同一条
        纪律）。为什么：这一步的提示词还没发出去，此刻承认送达就是把"没发出去"记成
        "读过了"。

        返回 `{text, item_ids, msg_ids, wake_ids, monitor, checked, problems}`：
        `run()` 把 id 并进待标记的那两个队列，并在成功调用之后落定。
        """
        self._pump_clock(step=step, when="turn", run=run)
        wakes = self._take_wakes(step=step, run=run)
        monitor = self._monitor_block(wakes=wakes, step=step)
        # ---- 子代理返场（D-64）：与 D-52 同一条投递点
        #
        # 位置在这一处的理由：唤醒已经消费完（有唤醒就是监控回合，不再等孩子，
        # 否则"被叫醒看全树"会先被一个 5 分钟的等待拖住），而信箱还没读
        # （孩子回来的结果与板项、留言拼成同一条增量，才有同一个去重面）。
        children = self._children_round_trip(
            step=step, run=run, wait=not bool(wakes.get("consumed")))
        if children.get("settled") or children.get("running"):
            SS.append(self.session_root, {
                "kind": "agent_children", "role": self.role,
                "task_id": str(self.my_task_id or ""), "step": int(step),
                "settled": [str(getattr(r, "task_id", "") or "")
                            for r in (children.get("settled") or ())],
                "settled_outcomes": [str(getattr(r, "outcome", None) or "")
                                     for r in (children.get("settled") or ())],
                "running": [str(x) for x in (children.get("running") or ())],
                "waited_sec": round(float(
                    (children.get("wait") or {}).get("waited_sec") or 0.0), 3),
                "wait_reason": str((children.get("wait") or {}).get("reason") or ""),
                "checked": True,
            }, sid=self.sid)
            run.notes.append(
                f"第 {step} 步返场：子代理回来 {len(children.get('settled') or ())} 条，"
                f"还在跑 {len(children.get('running') or ())} 条"
                f"（等待 {float((children.get('wait') or {}).get('waited_sec') or 0):.1f}s，"
                f"原因 {(children.get('wait') or {}).get('reason') or 'none'}）")
        got = mailbox_digest(
            self.conductor, self.session_root, self.role,
            my_task_id=str(self.my_task_id or ""), sid=self.sid,
            parent_task_id=self.parent_task_id, parent_role=self.parent_role,
            rendered=sorted(self._mailbox_rendered))
        for p in got.get("problems") or ():
            run.notes.append(str(p))
        item_ids = [x for x in got.get("item_ids") or () if x]
        msg_ids = [x for x in got.get("msg_ids") or () if x]
        parts = [x for x in (monitor, str(children.get("text") or ""),
                             str(got.get("text") or "")) if x]
        if not parts:
            return {"text": "", "item_ids": [], "msg_ids": [],
                    "wake_ids": [str(e.get("wake_id") or "") for e in wakes.get("consumed") or ()],
                    "monitor": bool(monitor), "checked": bool(got.get("checked")),
                    "children": children,
                    "problems": list(got.get("problems") or ())}
        text = "\n\n".join(parts)
        messages.append(user_message(text))
        wake_ids = [str(e.get("wake_id") or "") for e in (wakes.get("consumed") or ())]
        problem = record_mailbox_delivery(
            self.session_root, self.role, step=step, shape="turn", text=text,
            item_ids=item_ids, msg_ids=msg_ids, wake_ids=wake_ids,
            task_id=str(self.my_task_id or ""), sid=self.sid)
        if problem:
            run.notes.append(f"信箱投递事件没落成：{problem}")
        # 渲染集：这一趟已经把它念进过提示词了（与"承认送达"分开的一层，见字段说明）。
        self._mailbox_rendered.update(item_ids)
        self._mailbox_rendered.update(msg_ids)
        if monitor:
            self._monitor_turn_step = int(step)
            run.monitor_turns += 1
        return {"text": text, "item_ids": item_ids, "msg_ids": msg_ids,
                "wake_ids": wake_ids, "monitor": bool(monitor),
                "checked": bool(got.get("checked")), "children": children,
                "problems": list(got.get("problems") or ())}

    def _monitor_refusal(self, shape: str, payload: Mapping[str, Any], *, step: int) -> str:
        """监控回合的出口限定：这一句该不该被拒（空串 = 放行）。

        D-53 的业主口径是"监控回合只许 watch / guide / 补派 / 收口"，
        理由写在 `draft/146`（"不许在监控回合里开新的研究方向 —— 否则会变成
        用监控回合偷偷做研究"）。它必须是框架闸，不能只写在提示词里：
        提示词是建议，而这一步花的是真钱。

        放行的形状：`tool` 里名字是 `conductor.watch` / `conductor.guide`；
        `summon` / `summon_many`（补派）；`final`（收口）；`note`（写自己的台账 ——
        它什么也不派，不构成"开研究方向"）。其余一律受控拒绝。

        安全阀：连拒 `MONITOR_REFUSAL_LIMIT` 次之后放开，并在 `run.notes` 里留一句
        —— 不然一个把名字写错的模型会在监控回合里被永久拒在原地（拒信不计入
        `bad_json` 那一族，也就没有别的闸去停它）。
        """
        if int(self._monitor_turn_step) < 0 or int(self._monitor_turn_step) != int(step):
            return ""
        if self._monitor_refusals >= MONITOR_REFUSAL_LIMIT:
            return ""
        if str(shape) in MONITOR_TURN_SHAPES:
            if str(shape) != "tool":
                return ""
            name = str(payload.get("name") or "")
            if name in MONITOR_TURN_TOOLS:
                return ""
        self._monitor_refusals += 1
        allowed = ("`conductor.watch` / `conductor.guide` / 补派（`summon` 或 "
                   "`summon_many`）/ 收口（`final`）")
        return (f"监控回合的出口限定：{_call_brief(shape, payload) or shape} 不属于"
                f"{allowed} —— 这一回合是被时钟/收件箱唤醒开起来的，只许看全树、给指导、"
                "补派、收口，不许开新的研究方向。请照这四类重写一句。"
                f"（第 {self._monitor_refusals}/{MONITOR_REFUSAL_LIMIT} 次被拒；"
                "到上限之后框架会放开这一限制并留一条读数。）")

    def _hear(self, *, step: int = 0, run: "AgentLoop.LoopRun | None" = None
              ) -> list[dict[str, Any]]:
        """听一次新消息 + 新板项：把这次运行期间新到的取出来并登记。

        这里用 `window=None`：这一步的结果会把新到的全部并进去（`heard` 就是它们），
        所以"渲染了多少就标多少"这条纪律在这里等价于"标全部新到的" ——
        与信箱投递点（有窗口、见 `mailbox_digest`）口径一致，只是窗口与落点不同：
        这一处把新到的并进这一步的结果（模型在下一步的 tool 消息里读到），
        信箱那一处把它作为一条独立的增量 user 消息（在下一步的提示词之前）。

        板项那一半（S1i，业主 A3=甲"渲染即 seen"）：未 `seen` 的项与留言同一处取，
        取到什么就标什么（`mark_item_seen`，带 `seen_by`/`seen_step`）——
        于是"挂在父名下的交差通报"在下一步就进得了上下文，而不是等下一次运行。

        2026-10-24（D-52）：这一处也落一条 `agent_mailbox` 事件（`shape="step_tail"`），
        于是"投过没有"在盘上是可复算的 —— 改前板项被标 seen 之后没有任何投递记录
        （真机 `projects/sylow3`：t-000031 / t-000038 的 `seen_step=8` 在会话里找不到
        对应的投递事件，只能靠猜它是哪一步读到的）。
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
        # 投递记录（append-only）：`step_tail` 那一档在续跑重放时不另加消息
        # （这段文字已经在下面那条 tool 消息里了，另加会让重建多一条）。
        tail_text = "\n\n".join(x for x in (
            ("【板】\n" + board_text) if board_ids else "",
            ("【留言】\n" + digest) if fresh else "") if x)
        if tail_text:
            event_problem = record_mailbox_delivery(
                self.session_root, self.role, step=step, shape="step_tail",
                text=tail_text, item_ids=board_ids, msg_ids=fresh,
                task_id=str(self.my_task_id or ""), sid=self.sid)
            if event_problem:
                heard.append({"投递记录没落成": event_problem})
            # 渲染集同源：这一段文字已经进了这一步的 tool 结果 ⇒ 这一趟不必再渲染它。
            self._mailbox_rendered.update(str(x) for x in board_ids)
            self._mailbox_rendered.update(str(x) for x in fresh)
            if run is not None:
                run.mailbox_items.extend(str(x) for x in board_ids)
                run.mailbox_msgs.extend(str(x) for x in fresh)
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

        四件事按顺序，每一件都有它自己的读数：1. 没配预算（`registry.default_budget is None`）⇒ 什么都不做
        ——那是"没启用"，不是"没查成"（三态的第一档，所以不落任何"没压"的噪声）；2. 走 `compact_by_pressure`；
        3. 没压（未到阈值 / 容量读不到 / 没有可遮蔽的条目 / 摘要更大）⇒ 不替换历史，其中"读不到容量"每趟只警
        告一次（照 DSH `CB:803-808` 的去重）；4. 压了 ⇒ 事件三件套（`compaction_start` /
        `compaction_summary` / `compaction_end`）+ 一条带 `surface_op` 的替换事件（闭区间两端都含），并把
        `[start, end]` 换成一条摘要消息。

        为什么把替换消息也写进事件（施工单 §2 逐字）：只在内存里压会让续跑那一趟看到没压过的版本 —— 而"续跑
        看到的正是当时那份对话"是本仓最强的一条判据（`resume_messages` 读这些事件按序重放，两处逐条相等）。
        """
        budget = getattr(self.registry, "default_budget", None)
        if budget is None:
            return messages
        from . import contextbudget as CB

        cid = f"c{S.format_id(step)}-{self.role}"
        self._last_summary_note = {}
        # ---- ① 压力门（S-B ③）：先问一次"该不该动历史"。
        #
        # DSH 的两条分支（overflow / 压力）都先确认压力，README:89 逐字「低于压力绝不动」
        # ⇒ 剪枝与摘要共用同一道门，不会出现"门说没超、剪枝却动了"那种分叉。
        pressure = CB.pressure_reading(messages, budget=budget)
        if pressure["checked"] and not pressure["over"]:
            return messages
        # ---- ② 剪枝不在这里做（S-B ③ 的落点在工具结果进历史之前，见 `_prune_result`）。
        #
        # 为什么不在这一步边界上剪：到这一步时工具结果已经渲染过（观测层把单字段压到
        # `RESULT_CHARS=6000`），而"假开"那条读数的病根正是"拿渲染过的文本去比 8000 的阈值"。
        # 剪枝必须落在原始结构上（那里没有逐字段上限），也就是 `_prune_result` 那一处。
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

    def _prune_result(self, result: Any, *, step: int, run: "AgentLoop.LoopRun",
                      messages: Sequence[Mapping[str, Any]]) -> Any:
        """把这一步的工具结果按 DSH 的形状剪一遍（S-B ③ / 施工单 §2 的甲方案）。

        返回剪过的结果（没剪就原样返回）。为什么剪的是原始结果结构、而不是渲染后的那段文本：这是"假开"那条读数的病根
        —— 工具层那次剪枝（禁改区 `tools/base.py`）剪的是已经渲染过的字符串，而观测层把单字段压到 `RESULT_CHARS=6000`
        ⇒ 那条分支在当前配置下永远不触发（"剪枝开着"是一句空话）；原始结构没有逐字段上限（
        `{"a": 3000字, "b": 3000字, …}` 就是 15000），所以"跨块一条字符流"这个形状在这里才真的剪得掉东西。
        触发时机（照 DSH，不是"每次都剪"）：DSH 只在压缩触发成立之后剪一次（`CB:887-890`、`:901-904`，README:89「低于
        压力绝不动」），而工具层是每次调用都剪；这里用同一个 `pressure_reading` 问一次压力门 —— 剪枝与摘要因此共用一道
        门，不会出现"门说没超、剪枝却动了"。不需要"替换事件"来保证可重放：剪发生在这���步的结果落档之前 ⇒ `agent_step`
        事件里存的就是剪过的那一份，`resume_messages` 重建时天然拿到它（压缩那条替换动的是更早的节点，才必须靠
        `surface_op` 重放）；`compaction_prune` 仍要落 —— 它是"这一趟剪过、省了多少"的唯一读数。
        """
        budget = getattr(self.registry, "default_budget", None)
        if budget is None or not isinstance(result, (Mapping, list, tuple, str)):
            return result
        from . import contextbudget as CB

        # 压力门：只在"该动历史"的时候剪（容量读不到 ⇒ 不剪，走压缩那条路的"警告一次"）。
        pressure = CB.pressure_reading(messages, budget=budget)
        if not pressure["checked"] or not pressure["over"]:
            return result
        pruned, reading = CB.prune_stream(result, budget=budget)
        if not reading.pruned:
            return result
        SS.append(self.session_root, {
            "kind": "compaction_prune", "role": self.role, "step": step,
            "original_chars": reading.original_chars, "kept_chars": reading.kept_chars,
            "saved_chars": reading.original_chars - reading.kept_chars,
            "reason": reading.reason,
            # 位置语义与压缩那条替换同族，但这里的"被替换的节点"是这一步自己：
            # 结果还没落档，所以重放不需要它（见 docstring）。
            "replaced_node": {"kind": "agent_step", "index": step},
        }, sid=self.sid)
        run.notes.append(f"剪枝（第 {step + 1} 步的结果）：{reading.reason}")
        return pruned

    def _final_gaps_reading(self) -> dict[str, Any]:
        """收工那一刻"我名下还有几条证明没有 V 的签字"（D12 的读数，不打回、不拦）。

        业主 2026-10-22 的口径：`final` 一到就 `break` 是这个缺陷的形态 ——
        模型说"做完了"，框架就把这句话当结论，而"名下还有两条证明没送 V / 送了被判有毛病"
        在收工那一行上一个字都没有。这一格把那件事变成 `agent_run_end` 上的一个数。

        ## 判据只有一处

        `verifications.statement_review_reading`（与 `v_rejections_digest`、收工门 R10 同一个
        函数）：它答"这一份正文最近那一签是什么"。这里只挑 `state != "signed"` 的：
        `rejected`（签过、结论不是成立）/ `stale`（签过、签的是旧版）/ `unsigned`（一次都没签）/
        `unreadable`（台账读不出来 —— 不许折成"签过了"，所以也算未了）。

        ## "名下"的口径

        `statements` 表没有"这一趟/这一个台账号"的列（只有 `created_by` 的岗位名），
        所以这一格与 `v_rejections_digest` 用同一个口径：盘上带 `proof_text` 的命题行
        （`kind="concept"` 不算 —— 概念不参与证明与审校）。它是"这一岗现在名下欠着的"，
        不是"这一趟新写的那几条"；后者没有任何数据面可判，硬造一个会比不报更坏。

        ## 三态

        - 没有 `store` ⇒ `checked=False` + 理由（不是 0 条）；
        - `statements` 读不出来 ⇒ `checked=False` + 理由（同上）；
        - 单条读不出来 ⇒ 那一条算未了（`unreadable` 计数 + 进 `problems`），
          于是"读数不完整"这件事在 `unsigned` 上体现为"至少这么多条没签住"。
        """
        if self.store is None:
            return {"checked": False, "total": 0, "unsigned": None, "stmt_ids": [],
                    "unreadable": 0, "problems": [],
                    "reason": "这一趟没有 store ⇒ 未了义务读不了（不是 0 条）"}
        try:
            rows = [dict(r) for r in self.store.rows("statements")]
        except Exception as exc:  # noqa: BLE001 —— 读不出来是"没查成"
            return {"checked": False, "total": 0, "unsigned": None, "stmt_ids": [],
                    "unreadable": 0, "problems": [],
                    "reason": (f"statements 读不出来（{type(exc).__name__}: {exc}）"
                               " ⇒ 未了义务读不了（不是 0 条）")}
        from . import verifications as VR      # 惰性：运行期只在这一格读台账

        root = getattr(self.store, "root", None) or self.workspace_root
        total = 0
        gaps: list[str] = []
        unreadable = 0
        problems: list[str] = []
        for row in rows:
            sid = str(row.get("stmt_id") or row.get("statement_id") or "")
            if not sid or str(row.get("kind") or "") == "concept":
                continue
            if not str(row.get("proof_text") or "").strip():
                continue
            total += 1
            try:
                reading = VR.statement_review_reading(root, row)
            except Exception as exc:  # noqa: BLE001 —— 读不成不许折成签过了
                unreadable += 1
                gaps.append(sid)
                problems.append(f"{sid}：{type(exc).__name__}: {exc}")
                continue
            problems.extend(f"{sid}：{p}" for p in (reading.get("problems") or []))
            if str(reading.get("state") or "") != "signed":
                if str(reading.get("state") or "") == "unreadable":
                    unreadable += 1
                gaps.append(sid)
        return {"checked": True, "total": total, "unsigned": len(gaps),
                "stmt_ids": gaps[:8], "unreadable": unreadable,
                "problems": problems[:4],
                "reason": ("查过了：名下还欠 V 的签字" if gaps else "查过了：名下每一条都已签住")}

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

    def _final_gate_reading(self, run: "AgentLoop.LoopRun | None" = None
                            ) -> dict[str, Any]:
        """收工前的结构完整性闸：M 名下整棵树是不是已经全部销号（D-68，三态）。

        业主 2026-10-26 逐字：「最终 final 时应该是 M 下整棵树都已销号，否则不记 final」。
        改前这一格不存在：M 名下有几十个还在册的代理，与它收工那件事毫无关系
        （真机 `projects/sylow3`：50 个实例行、48 条板项、0 条销号落痕）。

        返回 `{"checked","applicable","complete","root","nodes","dirty","count",
        "total","root_open_items","why","reason"}`：

        - `applicable`：这道闸对这一趟有没有对象 —— 只有主控 M 有（其余角色名下没有
          "整棵树"这回事），所以非 M 一律 `applicable=False, complete=True`（放行，且
          不落噪声）；"不是 M"是查过了的结论，不是"没查成"；
        - `checked`：台账读到没有。读不成 ⇒ `checked=False` 但这一趟照旧放行
          （没有台账的那一趟本来就不在这道闸的射程里：`run_role` 拿不到 conductor 时
          连台账号都没有），同时把"这一格没查成"写进 `run.notes` —— 不许静默；
        - `complete`：这一支全部销号了没有（`nodes` 与 `dirty` 都空）；
        - `nodes` / `dirty` / `count` / `total` / `root_open_items`：判据本体在
          `Conductor.retire_integrity`（这一层只做"要不要拦"与"怎么说"）；
        - `why`：不干净时那一句人话（逐节点点名 + 未消项条数 + 处置路径）。

        为什么只有这一处：业主那句说的是"不记 final"，而 `final` 落盘的唯一入口是
        `run()` 里 `shape == "final"` 那一支 —— 门放在别处就成了"记了 final 又提醒"。
        """
        reading: dict[str, Any] = {
            "checked": True, "applicable": False, "complete": True,
            "root": str(self.my_task_id or ""), "nodes": [], "dirty": [],
            "count": 0, "total": 0, "root_open_items": 0, "why": "", "reason": "",
        }
        if str(self.role) != S.CONDUCTOR_ROLE:
            reading["reason"] = "不是主控那一趟 ⇒ 名下没有整棵树可销（这道闸对它没有对象）"
            return reading
        # ---- 任何 final 都要清仓，没有例外（业主 2026-10-26 追裁）
        #
        # 这里曾经有一条"监控/被唤醒的回合不判"的例外（`monitor_of` 或 `run.wakes > 0`），
        # 被业主追裁删掉：它是一个绕闸的口子 —— M 只要在一次被唤醒的回合里发 `final`，
        # 就绕过了"整棵树都要销号"的要求。业主原话是「最终 final 时应该是 M 下整棵树
        # 都已销号，否则不记 final」，没有给"哪种回合的 final"留口子。
        # 于是判据只有一条：这一趟的 `final` 一律要过 `retire_integrity`；
        # 树没清 ⇒ 不记 final（`stop_reason="final_refused"`），谁被唤醒、因为什么被唤醒都一样。
        reading["applicable"] = True
        cond = self.conductor
        mine = str(self.my_task_id or "")
        if cond is None or not mine:
            reading["checked"] = False
            reading["reason"] = ("这一趟没有台账（conductor 或台账号是空的）⇒ "
                                 "名下那棵树查不成，这一格按没查成记，不按干净记")
            if run is not None:
                run.notes.append(f"收工前的销号完整性没查成：{reading['reason']}")
            return reading
        look = getattr(cond, "retire_integrity", None)
        if not callable(look):
            reading["checked"] = False
            reading["reason"] = "conductor 没有 retire_integrity（这一格没接上）"
            if run is not None:
                run.notes.append(f"收工前的销号完整性没查成：{reading['reason']}")
            return reading
        try:
            got = look(mine)
        except Exception as exc:  # noqa: BLE001 —— 读不成不许折成"干净"
            reading["checked"] = False
            reading["reason"] = f"{type(exc).__name__}: {exc}"
            if run is not None:
                run.notes.append(f"收工前的销号完整性没查成（{reading['reason']}）")
            return reading
        if not isinstance(got, Mapping):
            reading["checked"] = False
            reading["reason"] = "retire_integrity 的读数不是对象"
            if run is not None:
                run.notes.append(f"收工前的销号完整性没查成：{reading['reason']}")
            return reading
        for key in reading:
            if key in got:
                reading[key] = got[key]
        reading["applicable"] = True
        if not reading.get("checked"):
            if run is not None:
                run.notes.append(f"收工前的销号完整性没查成（{reading.get('reason')}）")
            return reading
        reading["complete"] = bool(reading.get("complete"))
        if reading["complete"]:
            return reading
        nodes = [dict(n) for n in (reading.get("nodes") or [])]
        dirty = [dict(n) for n in (reading.get("dirty") or [])]
        named = "、".join(
            f"{n.get('task_id')}（{n.get('role') or '?'}，名下 {int(n.get('open_items') or 0)}"
            " 条未消项）" for n in nodes[:6])
        more = f"等 {len(nodes)} 个" if len(nodes) > 6 else ""
        why = (f"还没销号：{reading.get('root') or mine} 名下整棵树还有 "
               f"{int(reading.get('count') or 0)}/{int(reading.get('total') or 0)} 个代理在册"
               + (f"（{named}{more}）" if named else "")
               + (f"；另有 {len(dirty)} 个已销号节点名下还有未消项" if dirty else "")
               + " ⇒ 先用 `conductor.ack` 把各节点名下的未消项确认掉，"
               "再用 `conductor.retire_child` 逐个销号；整棵树都销号之前不记 final"
               "（结构完整性闸）")
        reading["why"] = why
        return reading

    def _budget_text(self) -> str:
        """给模型看的那一句"还剩多少钱"。

        2026-10-15 业主裁定 B2：这里此前报的是 `self.seam.spend.usd`
        （这一条缝自己的累计），而 `usd_budget` 是这一趟的总预算 ——
        模型据以决策的那个数因此是偏大的（别的角色花的钱它看不见）。
        现在读的是全局口径（`seam.spent_usd()`），并把口径来源写在括号里：
        "还剩 0.4 美元"这句话必须能回答"这是谁的账"。
        """
        spent, src = self._global_spend()
        if self.seam.usd_budget is None:
            return f"未设置上限（全局已用 {spent:.6f} 美元，读数来自 {src}）"
        left = max(0.0, self.seam.usd_budget - spent)
        return f"{left:.6f} 美元（上限 {self.seam.usd_budget:.6f}，已用 {spent:.6f}，读数来自 {src}）"

    def _global_spend(self) -> tuple[float, str]:
        """全局已花 + 口径来源。缝上有 `spent_usd()` 就用它（权威账）；
        没有（替身缝 / 老调用点）就退回缝自己的累计，并如实标注 `per_seam`。"""
        fn = getattr(self.seam, "spent_usd", None)
        if callable(fn):
            got = fn()
            if isinstance(got, tuple) and len(got) == 2:
                return float(got[0]), str(got[1])
        return float(getattr(self.seam.spend, "usd", 0.0) or 0.0), "per_seam"

    def _system_at_step(self, facts: Mapping[str, Any], system: str, *, step: int) -> str:
        """步边界上确认 system 逐字节没变（静态/动态分离之后的守门读数）。

        改前它是"重算会变的那两格、变了就换 system"（业主裁定 J=乙）：动机是对的（`budget_left` 是模型据以决定"还能不
        能继续"的数，花销每步在涨），代价是几乎每步 system 都变 —— 而前缀缓存要求前缀逐字节相同 ⇒ 命中率结构性地是 0。
        实测（2026-10-19 本机，M 岗，非零价）：第 0 步 system 54,902 字，第 1 步 54,902 字，但从第 35,035 个字符起就不
        同（`剩余预算：5.000000 美元（…已用 0.000000…）` → `…已用 0.001200…`）。
        现在这两格在这一步的 user 消息里（`_prompt` 的尾部，现读数字）：system 逐字节稳定，而模型每步照样看得见最新余
        额与草稿本 —— 真话没丢，只是换了载体（`promptstability.SYSTEM_PLACEHOLDERS` 在 system 里那一格写的是"见每步消
        息末尾"的指路语）。
        为什么还要每步渲染一次："逐字节稳定"必须是结构上被检查的。这里每步用静态事实重算一次并逐字比：相同就复用旧串，
        不同就如实发新的并落一条带 diff 读数的 `agent_note` —— `promptstability.first_difference` 给出"从第几个字符起
        不同 + 前后各 80 字"；那一条出现 = 有人往 system 里塞回了每步会变的东西（`DYNAMIC_SECTION_WHITELIST` 就是为这
        件事存在的）。渲染成本实测 11.5 ms（`AP.system_prompt` 一次）。
        """
        cand = AP.system_prompt(self.role, registry=self.registry, **dict(facts))
        if cand == system:
            return system
        reading = PSTAB.step_stability(system, cand)
        SS.append(self.session_root, {
            "kind": "agent_note", "role": self.role,
            # 措辞刻意改了：旧的那句"system 重发（会变的事实变了）"说的是 J=乙 的正常行为，
            # 而这一步现在的正常行为是"不变"。仍然不同 ⇒ 这是一条违规读数，必须说出来。
            "note": (f"system 在步边界上变了（这一步之后仍应是同一段前缀）：第 {step} 步；"
                     f"{reading['reason']}"),
            "step": step,
            "system_sha256": hashlib.sha256(cand.encode("utf-8")).hexdigest(),
            "system_stability": reading,
        }, sid=self.sid)
        return cand

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
        # ---- 业主 2026-10-22 的 B-3：「V 的判决必须递到 F（让 F 去修）」。
        #
        # 两件事在同一处算，但它们是两条独立的路（判据就是这么分工的）：
        # ① 读侧 `v_rejections` 进开场事实 —— 只读 V 的台账，与板项无关；
        # ② 递送 `deliver_v_verdicts` 走既有 `open_item` 通道把判决写成 F 名下的一项。
        # 把 ② monkeypatch 掉 ⇒ ① 照旧有读数、② 板上没有项（反真空，见
        # `tests/test_v_verdict_reaches_f.py`）。框架不替 F 改证明：两项里只有
        # 「哪一条 / 错在第几步 / 下一步该补什么」，正文一个字都不动。
        #
        # 为什么在 `board_digest` 之前：板摘要是"这一刻盘上的板"，投递要在同一步里
        # 就被看见（否则 F 这一趟读到的板永远是上一趟的样子）。
        v_text, v_details, v_problems = "", [], []
        v_delivery: dict[str, Any] = {}
        if self.role == "F" and self.store is not None:
            _v_root = getattr(self.store, "root", None) or self.workspace_root
            try:
                _stmt_rows = [dict(r) for r in self.store.rows("statements")]
            except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"
                v_text = (f"（这一格没读成：`statements` 读不出来"
                          f"（{type(exc).__name__}: {exc}）⇒ 不是「没有毛病」）")
                v_problems = [f"statements 读不出来：{type(exc).__name__}: {exc}"]
            else:
                v_text, v_details, v_problems = v_rejections_digest(_v_root, _stmt_rows)
                v_delivery = deliver_v_verdicts(
                    self.conductor, task_id=my_task_id, depth=depth,
                    role=self.role, details=v_details)
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
        # V 判决那两条路的读数都进 notes：读侧没读成 / 递送没投成，都不许静默 ——
        # "F 这一趟没看到判决"与"V 没判过"在盘上是两件事。
        run.notes.extend(f"V 判决读取：{p}" for p in v_problems)
        if v_delivery:
            run.notes.append(f"V 判决递送：{v_delivery.get('reason') or '（没有读数）'}")
            run.notes.extend(f"V 判决递送：{p}" for p in (v_delivery.get("problems") or []))
        # 投递标记推迟到第一次成功模型调用之后（`draft/86` §4.1 的 D75 后半）。
        #
        # 为什么不能在这里就标：旧写法在任何模型调用之前落 `mark_delivered`，于是
        # "这一趟在首次 `ask_step` 之前就死掉"（`not_wired`、步 0 撞停机开关、预算已尽）
        # 会把消息的"新"标记永久吃掉 —— 消息还在盘上，但它再也不标"新"，
        # 而且会被挤进 8 条窗口（真机 579 条留言、只有 8 条被标记读过，这个形态是其中一支）。
        # 现在：先进上下文、模型真的被问过一次之后，才承认"它送达了"。
        #
        # 2026-10-24（D-52）：这两条队列从此由信箱投递点（每一次 `ask_step` 之前，
        # `_deliver_mailbox`）追加，开场那一次不再往里塞东西 —— 开卷九格已删掉
        # `inbox` / `board` 两格（见 `_opening_transcript` 的 docstring），所以
        # "开场读到的那批"不再是"进过提示词的那批"：把它们塞进来会造出
        # "没投过却标了 seen / 已投递"的那一族静默错（D-52 要治的正是它）。
        pending_delivery: list[str] = []
        # 板项那一半：投进过提示词、但还没标 seen 的项（与 `pending_delivery` 同一处落定
        # —— "模型真的被问过一次"才算它进过上下文，业主 A3 的"渲染即 seen"落在这里）。
        pending_seen: list[str] = []

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
                     # 2026-10-22（业主 B-3）：我名下被 V 判「有毛病」的证明明细
                     # （读侧那一格；递送那一条走 `deliver_v_verdicts` 的板项）。
                     v_rejections=v_text,
                     budget_left=self._budget_text(), inbox=inbox,
                     workspace_root=self.workspace_root, availability=availability,
                     notebook=notebook, user_replies=replies,
                     # 这台机器能不能做形式化核验（现算一次，`draft/37` §89）：
                     # E 在 T1 第 3 趟把 6 次 check_formal 花在 `import Mathlib` 上，
                     # 而框架早就知道本机没装 Mathlib —— 事实必须进模型看得见的地方。
                     # `toolchain_formal` 是同一批读数的第二种用法（怎么写），
                     # 只发给手上真有 `formal.*` 的角色（业主裁定 G；2026-10-22 之后
                     # 受众由 `agent_prompts._FORMAL_ENTRY_TOOLS` 现算，今天只有 L）。
                     toolchain_facts=AP.toolchain_facts_text(),
                     toolchain_formal=AP.toolchain_formal_text(),
                     # 派活上限（业主裁定 A）：数字从这一次 run 的 Policy 现算，
                     # 不写死 —— `cli.py` 就传过 `wall_clock_sec`，写死的数字在
                     # 覆盖过的 run 里是谎话。没有 conductor 时退回默认 Policy（那一档
                     # 的派活本来也不会发生：没有 conductor 就没有 summon）。
                     parent_limits=AP.parent_limits_text(
                         getattr(self.conductor, "policy", None) or P.Policy(), self.role,
                         depth=depth))
        # ---- 静态/动态分离（2026-10-19；2026-10-21 扩到"跨 run 也会变"的十格）：system 只拿"任何两趟
        # 都逐字不变"的事实。根因：`budget_left` / `notebook` 是这一步现算的，`task` / `task_id` / `depth` /
        # `parent_task_id` / `summoned_by` / `children` / `board` / `inbox` / `user_replies` /
        # `workspace_root` 是这一趟的事实 —— 前者让"同一趟第 2 步"命中不了、后者让"另一趟第一步"命中不了
        # （实测：两份不同的活从第 95 个字符起就不同），而上游前缀缓存要求前缀逐字节相同。现在这些值走
        # user 消息（每步会变的两格在 `_prompt` 尾部现读，其余十三格在 `_opening_transcript` 里），system 只留
        # 静态指路语（`promptstability.SYSTEM_PLACEHOLDERS`）；`moved`（判为"会变"的键）落进
        # `agent_run_start` ⇒"哪些事实被挪出了 system"在盘上可复核，不用读这段代码。
        system_facts, moved_facts = PSTAB.split_facts(facts)
        # `prompt_audit` 用同一份 system 事实：它的 `prompt_sha256` 从此等于
        # 真正发出去的那版 system 的哈希（改前它等于"开局带实时预算那一版"）。
        run.prompt_audit = AP.prompt_audit(self.role, registry=self.registry, **system_facts)
        system = AP.system_prompt(self.role, registry=self.registry, **system_facts)
        if resumed is None:
            start_step = 0
            # ---- S-C（裁定 5甲）第 ① 步：历史载体从"一段字符串"换成消息序列。
            #
            # 开场那一整段（收件箱/任务/身份）是序列里的第一条 `user` 消息；
            # `transcript` 从此是 `render_messages(messages)` 的渲染（逐字不变），
            # 所以它的所有读者（Web UI 回放、续跑、`--resume`）这一步之后照旧。
            messages: list[dict[str, Any]] = [user_message(
                _opening_transcript(**opening_facts(facts)))]
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
            # ---- 2026-10-21：开场那条 user 消息要念的十二格事实，原文落在这里。
            #
            # 为什么必须落事件（而不是续跑时现读）：`resume_messages` 要把这一趟的
            # 第一条消息逐字节重建出来（判据：`rebuilt == run.messages`），而那十二格
            # 里有四格（`children` / `board` / `user_replies` / `parent_task_id`）在续跑那一刻
            # 已经可能变了（又有子代理收工、板上又多一项、用户又答了一句）。现读会让
            # "重建的那一段"与"当时那一段"不是同一段 —— 而两边都自称是同一趟。
            # 它们是这一趟开始那一刻的快照，与 `children` 那一格的口径逐字一致。
            #
            # 为什么整包一格（而不是十格平铺在后面）：上面已经平铺了 `task` /
            # `summoned_by` / `task_id` / `depth` 四格（它们本来就在事件里），平铺会撞键。
            # 键名就是 `_opening_transcript` 的入参名（`OPENING_FACT_KEYS` 是那份列名的
            # 唯一来源）：改名会让重建悄悄少一格，而少一格只表现为"开场那句话短了点"。
            "opening_facts": opening_facts(facts),
            # 这一趟有哪些事实被判定为"会变"、因而从 system 挪进了 user 消息
            # （`promptstability.STEP_VOLATILE_FACTS` 那份登记表）。前缀缓存能不能命中
            # 全看这一格是不是空的（空 = system 里没有任何会变的东西）。
            "system_dynamic_facts": sorted(moved_facts),
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
        #   ② 只有主控：新的用户消息/插话到手时清（下面那段判 `channel == "user"` 的地方）——
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
        #:
        #: 拆分口径的待执行条目（一步给 N 条调用 ⇒ 这里排着 N 条，逐条执行、逐条计步）。
        pending: list[Any] = []
        dispatch: Any = None
        turn_call: Any = None
        turn_cache: dict[str, Any] = {}
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
                    # 名册（业主 2026-10-19）：步数上报也是"代理发给代理"（它挂的是
                    # 我的名字 `sender=self.role`，不是框架通报）。收件人是父，
                    # 按父的绝对编号过同一份判据；名册拒了就不发，并把理由留在
                    # `run.notes` 里（"没发出去"不许长得像"报过了"）。
                    _addr, _gate = self._roster_gate(
                        parent_role, to_task_id=str(self.parent_task_id or ""))
                    if _gate:
                        run.notes.append(
                            f"步数上报没发出（受控拒绝 {_gate['refused']}）：{_gate['error']}")
                    else:
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
                # 「接收到停的时候，剩余任务委托状态自动变成 block」—— 收停的这一支
                self._block_remaining(run, stop_reason)
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
            budget = getattr(self.seam, "budget_limit", None)
            limit = self.seam.usd_budget if budget is None else budget()
            spent, spent_src = self._global_spend()
            if limit is not None and spent >= limit:
                run.stop_reason = "budget"
                run.final = run.final or (
                    f"预算已耗尽，停止（**全局**已用 {spent:.6f} / 上限 {limit:.6f}；"
                    f"已花读数来自 {spent_src}；"
                    "没有继续调用模型）。追加预算（`agentflow budget --add` 或网页上的预算窗口）"
                    "之后用 `--resume` 可以接着跑。")
                # 业主 2026-10-12：「扣完时自动发送优雅停止请求（这时预算可能会继续扣成
                # 负的一点点，但无大碍）」。三件事一起做：
                # ① 给我还在飞的直接子代理各开一条停止通知（复用用户叫停那一套：板项 + ack）；
                # ② 在工作区落一个一次性停机记录（`stopctl` 的三态 + 历史）——
                #    它让别的进程（CLI 起的另一条循环、E 的实验子进程）也看得到"该收了"；
                # ③ 立刻把它消费掉（记一笔历史、撤走文件）：否则"追加预算后 --resume"会在
                #    第 0 步被自己上一趟留下的开关当场停掉 —— `draft/37` §140 那个 bug 的同一形态。
                out = self._notify_children_of_stop("budget")
                if out:
                    run.notes.append(out)
                # 业主 2026-10-12/13：预算耗尽自动触发的优雅停止走同一条路 ——
                # 剩余任务与委托在这里由框架翻 block（不是等模型自己声明）
                self._block_remaining(run, "budget")
                note = self._land_budget_stop_record(limit)
                if note:
                    run.notes.append(note)
                break
            # ---- 回合前段（一个"回合" = 一次模型调用）
            #
            # 拆出来的条目还排着（`pending` 非空）⇒ 这一趟不向模型要新东西，直接执行下一条：
            # 一个回合管 N 条调用，而"要一次模型"这件事只发生在队列空的时候。
            # 于是"一步给 N 条"与"一步给 1 条"走的是同一条执行路径（`stepdispatch` 的拆分结果），
            # 循环里没有第二支"多条怎么办"。
            if not pending:
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
                # ---- 信箱投递点（D-52）：每一次 `ask_step` 之前投一次增量。
                #
                # 为什么必须在压缩之后：压缩会把历史换掉（`surface_op` 的位置 span），
                # 增量段是"这一步才到的"，它不该被刚压过的那一段吃掉；而它又必须
                # 在提示词拼出来之前进 `messages` —— 这一步的提示词是下一句就发出去的。
                # 投进去的板项 / 留言的承认推迟到下面 `call.ok` 那一支（同一条纪律）。
                mailbox = self._deliver_mailbox(step=step, messages=messages, run=run)
                pending_seen.extend(x for x in mailbox.get("item_ids") or ()
                                    if x not in pending_seen)
                pending_delivery.extend(x for x in mailbox.get("msg_ids") or ()
                                        if x not in pending_delivery)
                if mailbox.get("item_ids"):
                    run.mailbox_items.extend(str(x) for x in mailbox["item_ids"])
                if mailbox.get("msg_ids"):
                    run.mailbox_msgs.extend(str(x) for x in mailbox["msg_ids"])
                # 静态/动态分离之后 system 本该一个字节都不变；这里每步确认一次
                # （变了就如实发新的并落一条红灯读数，见 `_system_at_step`）。
                system = self._system_at_step(system_facts, system, step=step)
                data, call = self.seam.ask_step(self._prompt(messages, step=step),
                                                system=system, task_id=my_task_id,
                                                note=f"{self.role}.step{step}",
                                                face=face)
                # 这一步那次调用的缓存读数（三态：上游没给 ⇒ `hit`/`miss` 都是 `None`，
                # 不许折成 0）。它随后挂进这一步的 `LoopStep` 与 `agent_step` 事件 ——
                # 改前上游的读数只到 `SeamCall` 为止，一条 run 记录里都没有它。
                step_cache = PSTAB.prompt_cache_record(call)
                # 模型真的被问过一次之后才登记投递（推迟标记的落点，见上面那段注释）：
                # "模型真的被问过一次"= 这一批消息确实进了上下文 ⇒ 承认它送达。
                if pending_delivery and call.ok:
                    problem = mark_delivered(self.session_root, self.role, pending_delivery,
                                             sid=self.sid)
                    if problem:
                        run.notes.append(f"投递登记失败：{problem}")
                    pending_delivery = []
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
                    # 「没拿到可用的回复」不进坏 JSON 那一档（`LoopRun.no_reply` 的说明）：
                    # 它不是"它说错了"，是我们没收到能用的回答。
                    no_reply = _is_no_reply(call.problem)
                    auth_failed = call.problem == "judge_auth_failed"
                    if args_error:
                        run.bad_args += 1
                        run.bad_args_streak += 1
                    elif no_reply:
                        run.no_reply += 1
                        run.no_reply_streak += 1
                    elif auth_failed:
                        # key 无效/无权：不是"没查成"（查过了、确定不行），也不是它说错了。
                        # 处置只有一条（换 key / 查额度），重试三次只是把钱再烧一遍 ⇒ 立刻停。
                        # 这里不并进任何 streak（`bad_json` / `no_reply` 都不）：并进去会让
                        # "三连击"这个读数把一个配置错误说成协议问题 —— 而这一条正是
                        # 「归因错 ⇒ 处置错」那一族（2026-10-15 与 `judge_no_reply` 同批加）。
                        pass
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
                                              problem=call.problem, cache=step_cache))
                    SS.append(self.session_root, {
                        "kind": "agent_step", "role": self.role, "index": step, "shape": "invalid",
                        "payload": {}, "result": dict(bad_result),
                        "prompt_cache": dict(step_cache),
                    }, sid=self.sid)
                    if call.problem == "judge_not_wired":
                        run.stop_reason = "not_wired"
                        run.final = ("没有接模型（judge_not_wired）：这次运行没有产生任何判断，"
                                     "也没有写任何数据")
                        break
                    if auth_failed:
                        # 立刻停：理由说实话（既不是"它说错了"，也不是"网络没通"），
                        # 并给出唯一那条可行动的路。步骤与事件已在上面记全（与 `judge_not_wired` 同形）。
                        run.stop_reason = "model_auth_failed"
                        run.final = (f"模型没认这把 key（{_clip(str(call.detail), 200)}）—— "
                                     "这不是它回了坏 JSON，也不是网络没通；"
                                     "换 key / 查额度之后再跑，重试没有意义")
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
                    if no_reply:
                        # 这一档不走"重述协议"那条纠正（它不是它说错了），也不与坏 JSON 共用一个上限。
                        # 上限仍复用 `max_bad_json`：它量的是"连着几次这一步没产出任何东西"，
                        # 而上限存在的理由是"不许拿整趟运行去等一个不回来的回答"
                        # （每次超时在网关里已经自己重试过 `ModelSpec.max_retries` 次）。
                        if run.no_reply_streak > self.max_bad_json:
                            # 停止理由逐档说实话（2026-10-15 加第三档）：超时 / 输出吃光 /
                            # 没连上（`judge_no_reply:<kind>`）三者的处置方向不同 ——
                            # 调大上限、拆小这一步、等网络回来 —— 而它们此前共用一个
                            # "bad_json_limit"，那句话在 DNS 失效那一趟是假的。
                            if call.problem == "judge_timeout":
                                run.stop_reason = "model_timeout"
                                nxt = ("超时那一档可调大 AGENTFLOW_MODEL_TIMEOUT_SEC")
                            elif call.problem == "judge_output_limit":
                                run.stop_reason = "model_output_limit"
                                nxt = "输出吃光那一档要把这一步拆小、把思考压短"
                            else:
                                run.stop_reason = "model_unreachable"
                                nxt = ("没连上那一档要看网络/DNS 与本机到 api 的通路"
                                       "（网关已按 `ModelSpec.max_retries` 重试过）")
                            run.final = (
                                f"连着 {run.no_reply_streak} 次没拿到可用的回复"
                                f"（最后一次：{call.problem}；{_clip(str(bad_result['detail']), 200)}）—— "
                                "这不是它回了坏 JSON，是这一步没有产出可用的东西；停止。"
                                f"下一趟可以 `--resume` 续跑；{nxt}")
                            break
                        messages.append(assistant_message(step, {}, name="invalid"))
                        messages.append(tool_message(
                            step, _no_reply_line(step, call.problem, str(bad_result["detail"]))))
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
                # `roster=self._address_of`（2026-10-22）：名册名 / 绝对编号也能寻址 ——
                # 解码这一步就要把它们翻成"哪个角色"（收件箱按角色收），判据只有
                # `roster_addresses` 那一份（`_address_of` 只是把它的上下文接上）。
                shape, payload, problem = _shape_of(data, roster=self._address_of)
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
                                  "raw_reply": _clip(json.dumps(data, ensure_ascii=False, default=str), 600)}
                    run.steps.append(LoopStep(step, "invalid", payload, bad_result,
                                              problem=problem, cache=step_cache))
                    SS.append(self.session_root, {
                        "kind": "agent_step", "role": self.role, "index": step, "shape": "invalid",
                        "payload": dict(payload), "result": dict(bad_result),
                        "prompt_cache": dict(step_cache),
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
                run.no_reply_streak = 0
                # ---- 接住这一步的请求并拆分（唯一入口：`stepdispatch.catch_step_request`）
                #
                # 模型一次可能给 1 条、也可能给 4 条原生调用。这里把"这一步要求做什么"
                # 整包接住、按原顺序拆成有序条目，下面按条目逐条执行（每条 = 一步）。
                # 单条与多条走的是同一个函数、同一个结果类型：拆一条 = 一条。
                dispatch = SD.catch_step_request(
                    SD.StepRequest(
                        turn_index=step, first_step=step, shape=shape, payload=payload,
                        action=_first_call_action(face, call, shape, payload), call=call),
                    decode=self._decode_call_item)
                if dispatch.problem:
                    # 接住层自己接不住（一个条目都拆不出来）⇒ 整步 unknown。
                    # 绝不允许退化成"只跑第一条"：那正是这次要修掉的形态。
                    unknown = {"problem": dispatch.problem,
                               "detail": _clip(dispatch.detail, 600)}
                    run.steps.append(LoopStep(step, "invalid", {}, unknown,
                                              problem=dispatch.problem, cache=step_cache))
                    SS.append(self.session_root, {
                        "kind": "agent_step", "role": self.role, "index": step,
                        "shape": "invalid", "payload": {},
                        "result": dict(unknown), "prompt_cache": dict(step_cache),
                    }, sid=self.sid)
                    run.bad_json += 1
                    run.bad_json_streak += 1
                    messages.append(assistant_message(step, {}, name="invalid"))
                    messages.append(tool_message(step, _invalid_line(step, dispatch.problem)))
                    if run.bad_json_streak > self.max_bad_json:
                        run.stop_reason = "bad_json_limit"
                        run.final = (f"连续 {run.bad_json_streak} 次这一步没有拆出可执行的条目"
                                     f"（最后一次：{dispatch.problem}），停止")
                        break
                    continue
                pending = list(dispatch.items)
                turn_call, turn_cache = call, step_cache
            # ---- 条目执行（一条 = 一步；拆分口径见 `stepdispatch`）
            #
            # 走到这里 `pending` 一定有货：要么刚被 `catch_step_request` 拆出来，
            # 要么是同一回合里剩下的条目。每条都走下面同一条路径 ——
            # 单条与多条没有第二条路（判据 `test_the_single_path_and_the_multi_path_are_one`）。
            item = pending.pop(0)
            step = item.step_index
            call = turn_call
            # 缓存读数与思维链只挂在回合的第一条上：它们量的是"那一次模型调用"，
            # 抄给每一条会让同一笔调用在 `prompt_cache` 汇总里被数 N 次、思维链被读 N 遍。
            step_cache = turn_cache if item.call_index == 0 else {}
            shape, payload = item.shape, item.payload
            # 逐条记账的两个读数（只在多调用回合里算：单条那一路与改前逐字相同）。
            item_t0 = time.monotonic() if (dispatch is not None and dispatch.multi) else 0.0
            item_spend0 = self._global_spend()[0] if item_t0 else 0.0
            if item.problem:
                # 这一条解码不出来 ⇒ 如实记一条"未执行"，不影响其余条目
                # （判据③：一条被拒不作废整步）。
                self._record_undecodable_item(item, dispatch, run, step_cache, messages)
                continue
            if shape == "final":
                # ---- D-64：还有子代理没回来 ⇒ 这一步的 final 被拒（可重试）
                #
                # 位置在 D-68 那道结构完整性闸之前：这一条更具体（点名到还在跑的编号），
                # 而且它是可恢复的（那几个孩子一定会落定，父只需再等一次返场）。
                # 两条闸各管一件事、不互相替代：
                #   · 这一条管"我自己派出去、还没回来"的（可抢占不许变成不等子就收口）；
                #   · D-68 那条管"整棵树在册节点与未消项"（结构完整性，M 才有对象）。
                hold = self._children_hold()
                if hold:
                    run.notes.append(hold)
                    refused_result: dict[str, Any] = {
                        "ok": False, "refused": "children_running", "error": hold,
                        "detail": hold, "running": self._children_running()}
                    run.steps.append(LoopStep(step, shape, payload,
                                              _for_record(refused_result), cache=step_cache))
                    SS.append(self.session_root, {
                        "kind": "agent_step", "role": self.role, "index": step,
                        "shape": shape, "payload": dict(payload),
                        "result": dict(_for_record(refused_result)),
                        "heuristic_tokens": step_node_tokens(step, payload, refused_result),
                        "prompt_cache": dict(step_cache),
                    }, sid=self.sid)
                    messages.append(assistant_message(
                        step, payload, name=shape, content=_spoken_half(step, payload)))
                    messages.append(tool_message(step, _result_half(refused_result),
                                                 name=shape))
                    continue
                # ---- 强制 notify 表（`draft/39` §3.2/§3.3，用户 2026-10-05 裁）：除主控外收工必须填这张表
                # （`to`/`summary`/`body`），填错/没填就打回并附格式说明；主控 M 的 `final` 是给用户的回复，
                # 不在这套里（用户原话："向用户回复时不搞这种操作"）。
                # ---- L-05e（`draft/52` F 组 / P-10）：强制闸门降级成读数。收益被真机证伪：5269 个
                # `agent_step` 里 shape 无 `final`、`no_notify` 收场 0 次 ⇒ 旧闸门（不带 `notify` 打回、连续
                # 3 次 ⇒ `stop_reason="no_notify"`）一次都没触发过，只贡献提示词篇幅。新口径只留"要交接就写
                # 手稿"：形状对 ⇒ 秘书照旧执笔一行手稿；没填/填错 ⇒ 不打回、照常收工，只把原因落进这一步
                # 的读数（`notify_problem`）—— 阻塞一条委托比放行更贵。
                #
                # ---- D-68（业主 2026-10-26 逐字）：「最终 final 时应该是 M 下整棵树都已销号，
                # 否则不记 final」。这是结构完整性闸，不是建议：闸不过就一个字节都不写
                # （`run.final` 留空、不落手稿、`stop_reason="final_refused"`），
                # 并把"哪些节点还在册、各自名下还有多少未消项"的清单交回给模型与盘上。
                # 位置必须在 notify / 手稿之前：一份写着"我做完了"的交接手稿与一次被拒的
                # 收工互相矛盾，而"记了 final 又提醒"正是业主要挡的那一档（不记 final）。
                final_gate = self._final_gate_reading(run)
                if final_gate.get("applicable") and not final_gate.get("complete"):
                    why = str(final_gate.get("why") or "还有节点没销号 ⇒ 不记 final")
                    run.notes.append(why)
                    # 清单进这一步的结果：模型下一轮读得到（有几种工具能处置它）；
                    # 落盘的那一份在 `agent_run_end.notes` 与 `runs/*.json` 的 steps 里。
                    run.steps.append(LoopStep(step, shape, payload,
                                              {"final_refused": dict(final_gate),
                                               "why": why}, cache=step_cache))
                    run.stop_reason = "final_refused"
                    break
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
                # ---- D12：收工之前读一次"未了义务"（只做读数，不打回、不拦）。
                #
                # 为什么就在这一支里读、而不是收工之后统一算：这一支是唯一一条"模型说做完了"
                # 的路径，而这一格要回答的正是"它说做完了的那一刻，名下还欠几条 V 的签字"。
                # 结算点跟着这句话走，读数才与那句话同一时刻（收工之后统一算会把
                # 收工过程中别的写入也算进来）。
                # 失败不许带走这一趟：读数抛异常就落一条 note，`final` 照旧收工。
                try:
                    run.final_gaps = self._final_gaps_reading()
                except Exception as exc:  # noqa: BLE001 —— 读数坏了不许拦住收工
                    run.final_gaps = {"checked": False, "unsigned": None, "stmt_ids": [],
                                      "reason": (f"未了义务读数抛了异常"
                                                 f"（{type(exc).__name__}: {exc}）")}
                if run.final_gaps.get("unsigned"):
                    run.notes.append(
                        f"收工时名下还有 {run.final_gaps['unsigned']} 条证明没有 V 的签字"
                        f"（读数，不拦收工；明细：{'、'.join(run.final_gaps.get('stmt_ids') or [])}）")
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
                # ---- 拆分口径的逐条记账（`stepdispatch`）
                #
                # 收工这一条也是"回合里的一条"：它同样占一个步号、落一条 `agent_step_call`，
                # 而"第 k 条 <工具名> <结果一句话>"的汇总挂在回合的最后一条上（模型只读一遍）。
                # 改前这里是"只执行第 1 条"的 warn —— 真机三趟 76 个多调用步里丢掉的
                # 107 条全是只读，一条都没执行；现在每一条都有它自己的结局读数。
                if dispatch is not None and dispatch.multi:
                    final_outcome = SD.outcome_of(shape, payload, {**step_result, "ok": True})
                    final_outcome["elapsed_ms"] = int((time.monotonic() - item_t0) * 1000)
                    final_outcome["usd"] = round(
                        self._global_spend()[0] - item_spend0, 6)
                    dispatch.note(item, final_outcome)
                    self._land_step_call(item, shape, payload, final_outcome, run)
                    batch = dispatch.provenance(item)
                    if item.is_last:
                        summary = dispatch.summary()
                        batch = {**batch, "summary": summary, "turn": dispatch.reading()}
                        step_result = {**step_result, "warn": summary,
                                       "multi_call": batch}
                    else:
                        step_result = {**step_result, "multi_call": batch}
                run.steps.append(LoopStep(step, shape, payload, step_result,
                                          cache=step_cache))
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
            # ---- 两段式（业主 2026-10-21 裁定）：洗格式 → 请示 → 确认 → 才执行。
            #
            # 为什么不是"直接应用"（S1g 的旧形态）：那等于秘书替本体表态
            # （`draft/53` §2 的两条红线：不替它承诺、不改结论）。为什么也不是
            # "永远只建议"（E5 之前的形态）：那让"洗一遍格式"变成一句摆设，
            # 派活实际发出的仍是错名原稿、继续撞闸门。
            #
            # 三档，各有各的读数：
            #   ① 无差异（`washed == original`）⇒ 直接执行，不进第二段（不为"没差异"多花一轮）；
            #   ② 有差异、父还没表态        ⇒ 不执行，返回 `outcome="wash_proposed"` +
            #      `proposal_id` + 逐字段 diff（台账里那一行也带着同一个编号）；
            #   ③ 父带了 `accept_proposal` / `reject_proposal` ⇒ 按它说的那一份执行
            #      （`accepted` 真/假进这一步的结果），编号在台账里核过。
            washed_payload = secretary_note.pop("_washed_payload", None)
            wash_plan = secretary_note.pop("wash_proposal", None)
            accept_field, reject_field = _proposal_fields()
            dispatch_notify: dict[str, Any] | None = None
            wash_audit: dict[str, Any] | None = None
            if secretary_note.get("wash", {}).get("refused"):
                # 硬拒（只有"连派给谁/做什么都不全"这一格）：一行都不落（`draft/90` §1.2）。
                # 其它"洗不动"（缺必填参数…）照旧交给闸门 —— 那一档还会落 `refused` 行
                # 并可能转成"请主控代唤"，秘书抢在前面拒掉会把那条出路一起弄丢。
                result = {"ok": False, "outcome": "refused",
                          "refusal_reason": str(secretary_note["wash"]["refused"]),
                          "detail": ("秘书洗格式：这一趟派活连『派给谁/做什么』都不全 ⇒ 受控拒绝"
                                     f"（{secretary_note['wash'].get('reason') or ''}）"),
                          "washed": False}
            elif isinstance(wash_plan, Mapping) and wash_plan.get("outcome"):
                # ② 有差异 ⇒ 不执行。这一格的 `ok` 是 False：确实什么都没派出去；
                # 而 `outcome` 说清"它不是失败，是在等父表态"（受控词表只有这几个值）。
                pid = str(wash_plan.get("proposal_id") or "")
                lines = [str(x) for x in (wash_plan.get("changes") or ())]
                result = {
                    "ok": False, "outcome": str(wash_plan.get("outcome") or ""),
                    "executed": False, "proposal_id": pid,
                    "detail": (f"秘书洗出 {len(lines)} 处格式差异 ⇒ 这一趟没有派活"
                               "（0 行新任务、0 次子任务调用）：要按洗过的形状派 ⇒ 下一步"
                               f"带 accept_proposal=\"{pid}\" 再派一次；要按原稿派 ⇒ 带 "
                               f"reject_proposal=\"{pid}\""),
                    "original": dict(wash_plan.get("original") or {}),
                    "washed": dict(wash_plan.get("washed") or {}),
                    "changes": lines,
                    "changed_keys": list(wash_plan.get("changed_keys") or ()),
                    "diff": dict(wash_plan.get("diff") or {}),
                    "next": {accept_field: pid, reject_field: pid},
                }
                run.notes.append(
                    f"秘书洗格式：{len(lines)} 处格式差异 ⇒ **没有派活**（请示 {pid}）："
                    "下一步带 accept_proposal / reject_proposal 再派一次")
            elif isinstance(wash_plan, Mapping) and wash_plan.get("problem"):
                # 确认/拒绝的编号不成立（查不到 / 指纹不符 / 两个都给了）⇒ 受控拒绝，
                # 不猜它想按哪一份执行。理由码沿用闸门那一档：这次调用本身不成立。
                result = {"ok": False, "outcome": "refused",
                          "refusal_reason": "invalid_params",
                          "detail": str(wash_plan.get("problem") or ""),
                          "washed": False,
                          "proposal_id": str(wash_plan.get("proposal_id") or "")}
            else:
                # ③ 确认/拒绝，或 ① 无差异：执行的那一份就是 `wash_plan["execute"]`
                # （接受 ⇒ washed；拒绝 ⇒ original）。没有计划时按原稿执行 ——
                # 失败方向必须是"发原稿"，绝不因为缺一格读数就静默发洗过的那一份。
                confirmed = (isinstance(wash_plan, Mapping)
                             and wash_plan.get("accepted") is not None)
                if confirmed:
                    # 「执行哪一份」只有一处判据（秘书那一侧 `plan_wash` 的 `execute`）：
                    # 接受 ⇒ washed；拒绝 ⇒ original。这里只照做，不自己再选一次
                    # （两处各选一次 ⇒ 读数说 washed、发出去 original 而没人报错）。
                    chosen = wash_plan.get("execute")
                    if not isinstance(chosen, Mapping) and wash_plan.get("accepted") is True:
                        chosen = washed_payload        # 兜底：秘书没给那一格时仍按 washed
                    if isinstance(chosen, Mapping):
                        payload = dict(chosen)
                    run.notes.append("秘书洗格式：parent **接受了** —— 按洗过的那一份派出"
                                     if wash_plan.get("accepted") is True else
                                     "秘书洗格式：parent **拒绝了** —— 按原稿派出（留痕）")
                if (isinstance(washed_payload, Mapping)
                        and secretary_note.get("wash", {}).get("checked")
                        and dict(washed_payload) != dict(payload)):
                    run.notes.append("秘书洗格式：" + ("；".join(
                        str(c) for c in (wash_plan.get("changes") or ()))
                        if isinstance(wash_plan, Mapping) else "（改了格式格）"))
                if confirmed:
                    # 执行那一刻的三份读数（业主：`original` / `washed` / `accepted` / `proposal_id`
                    # 一起进这一步的结果 —— 不另造表，它进的就是 `agent_step` 那一格）。
                    wash_audit = {
                        "proposal_id": str(wash_plan.get("proposal_id") or ""),
                        "original": dict(wash_plan.get("original") or {}),
                        "washed": dict(wash_plan.get("washed") or {}),
                        "accepted": bool(wash_plan.get("accepted")),
                        "executed_with": str(wash_plan.get("executed_with") or ""),
                        "changes": [str(x) for x in (wash_plan.get("changes") or ())],
                        "changed_keys": list(wash_plan.get("changed_keys") or ()),
                    }
                if shape in ("summon", "summon_many") and self.role == S.CONDUCTOR_ROLE:
                    gate, dispatch_notify = self._dispatch_notify(payload)
                    if gate:
                        run.notes.append(f"派活的 notify 表格式有问题（{gate}）⇒ "
                                         "照常派活，留痕退回框架派生那一份")
                # ---- 时钟推进（D-53 的生产端）：每一条被执行的条目之前推一次。
                #
                # 为什么连"拆出来的每一条"都要推：一条模型回复可能拆出 N 条调用，
                # 这 N 条各占一步、各可能耗时（召唤尤其），而"到点"不该等整个回合
                # 结束才被发现。`fire_due` 是幂等的（已 fired 的不再算 due）。
                self._pump_clock(step=step, when="step", run=run)
                # ---- 监控回合的出口限定（D-53）：被唤醒开起来的那一回合只许
                # watch / guide / 补派 / 收口。这是一道框架闸（不是提示词建议）。
                monitor_refusal = self._monitor_refusal(shape, payload, step=step)
                if monitor_refusal:
                    result = {"ok": False, "refused": "monitor_turn_restricted",
                              "error": monitor_refusal,
                              "detail": monitor_refusal}
                    run.notes.append(f"监控回合出口限定拒了一条：{_call_brief(shape, payload)}")
                    if self._monitor_refusals >= MONITOR_REFUSAL_LIMIT:
                        run.notes.append(
                            f"监控回合出口限定已连拒 {self._monitor_refusals} 次 ⇒ "
                            "从下一步起放开（许可的名单写在提示词里；放开这件事必须留痕）")
                else:
                    result = self._execute(shape, payload)
                if dispatch_notify is not None:
                    # 派活照旧执行，留痕在它之后写：账本里的每一行都对应一次"真的发出去的派活"
                    # （写在前面会让"被策略拒掉的派活"也留下一行像是办成了）。
                    hand = self._do_handoff(dispatch_notify, board_item=False)
                    if hand.get("ok"):
                        run.handoffs.append(str(hand.get("id") or ""))
                    result = {**result, "dispatch_handoff": hand}
                if wash_audit is not None:
                    result = {**result, "wash": wash_audit}
            # ---- 子产出的落点（业主裁定：父代理必须处理子代理的产出）
            #
            # 在调用那一刻就把"这次调用产生了哪些子产出"记进 `LoopRun`
            # （而不是等收工时从 steps 反推）：`summon` 的 `task_id` 与它带回来的
            # 结果、`summon_many` 每个 target 一条、`handoff` 一条（对等通道，
            # 不计入 `summons_*`，见 `_call_productions`）。
            #
            # 会话事件里的落点是 `agent_step.productions` 那一格 —— 只在真的有产出时
            # 写（老载荷的键集因此一个字节不变）；两处同源（同一份 `_call_productions`）。
            step_productions = _call_productions(
                shape, payload, result, step=step, own_task_id=str(self.my_task_id or ""))
            if step_productions:
                run.productions.extend(step_productions)
            if secretary_note:
                result = {**result, "秘书": secretary_note}
            # 耳朵一直开着：这一步做完先听一次新消息与板项，把它并进这一步的结果里
            # （并进结果而不是只并进 transcript：台账与会话记录要能看到"他当时听到了什么"）。
            # `step=step`：板项标 seen 时要写"在第几步读的"（业主 A3 的判据靠它配对）。
            heard = self._hear(step=step, run=run)
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
            # ---- 拆分口径的逐条记账（`stepdispatch` 接住 → 拆分 → 逐条执行）
            #
            # 改前（D-35 方案 B）：解析层只取 `tool_call_list[0]`，其余丢弃，这里只补一句
            # warn 点名被丢的那几条 —— 真机三趟 76 个多调用步、被丢 107 条全部是只读，
            # 一个字节都没执行。现在每一条都有自己的步号、自己的准入与记账，
            # 这里把这一条的结局记下来（`agent_step_call`），并给最后一条挂上汇总
            # （"第 k 条 <工具名> <结果一句话>" + 一句可执行建议）。
            if dispatch is not None and dispatch.multi:
                outcome = SD.outcome_of(shape, payload, result)
                outcome["elapsed_ms"] = int((time.monotonic() - item_t0) * 1000)
                outcome["usd"] = round(self._global_spend()[0] - item_spend0, 6)
                dispatch.note(item, outcome)
                self._land_step_call(item, shape, payload, outcome, run)
                batch = dispatch.provenance(item)
                if item.is_last:
                    summary = dispatch.summary()
                    result = {**result, "warn": summary,
                              "multi_call": {**batch, "summary": summary,
                                             "turn": dispatch.reading()}}
                else:
                    result = {**result, "multi_call": batch}
            # ---- S-B ③（施工单 §2 的甲方案）：剪枝在观测层之前做一次。
            #
            # 位置是关键，也是"假开"那条读数的真正修法：工具层那次（禁改区 `tools/base.py`）
            # 用 `threshold_chars=8000` 剪已经渲染过的文本，而观测层把单字段压到
            # `RESULT_CHARS=6000` ⇒ 那个分支永远不触发。这里剪的是原始结果结构
            # （它没有逐字段上限：5 个 3000 字的字段就是 15000）⇒ 跨块一条字符流才有意义，
            # 剪完再交给观测层渲染。触发时机照 DSH：只在压力门确认之后（低于压力绝不动）。
            result = self._prune_result(result, step=step, run=run, messages=messages)
            step_obj = LoopStep(step, shape, payload, _for_record(result), cache=step_cache)
            run.steps.append(step_obj)
            # 12-A=乙：思维链原样带回去。进消息与进事件的是同一份文本
            # （`_recorded_reasoning` 走的截断口径与落档一致）—— 于是"当时那份序列"
            # 与"从事件重建的那份序列"逐条相等（`resume_messages` 的判据靠这一条成立），
            # 而"这段被截过"这件事本身写在文本里（不静默截断）。
            #
            # 拆分口径：思维链属于那个回合（一次模型调用），所以只有第一条带它 ——
            # 抄给同一回合的每条会让"它想了什么"在上下文里重复 N 遍。
            thought = _recorded_reasoning(call.reasoning) if item.call_index == 0 else ""
            event: dict[str, Any] = {
                "kind": "agent_step", "role": self.role, "index": step, "shape": shape,
                "payload": dict(payload), "result": dict(step_obj.result),
                # S-B：这一步作为"节点"的估价（压力门的输入）。它与 `result` 一起落盘，
                # 于是"当时那一段历史值多少 token"事后可复核（不必重算，也不会因为
                # 观测层的口径改了就与当时对不上）。
                "heuristic_tokens": step_node_tokens(step, payload, result),
                # 这一步那次调用的缓存读数（`promptstability.prompt_cache_record`）。
                # 键必须存在（三态）：`hit`/`miss` 为 null = 上游没给读数，
                # 与"这一步没有模型调用"（整格没有）是两件事。
                "prompt_cache": dict(step_cache),
            }
            if thought:
                event["reasoning"] = thought
            if step_productions:
                # 子产出的会话落点（业主裁定：父必须处理子产出）。与 `LoopRun.productions`
                # 是同一份 —— 只在真的有产出时写这一格（其余步的键集一个字节不变）。
                event["productions"] = step_productions
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
            # ---- 上报召唤者（`conductor.escalate`，业主 2026-10-19「父子天然双向」）：与上面 `ask_user`
            # 那一支同形、同理由 —— 需求已经写进父的收件箱，这一趟就不该再替父往下做。必须优雅停而不是
            # 抛错：它不是失败（需求送到了、台账有留痕、`--resume` 能接着跑），所以它有自己的退出码 5
            # （与 3/4 同族「成功的中断」）。判据读 `data.state` 而不是工具名（名字会被 `_do_tool` 的
            # `aliased_from` 改写）：`state="escalated"` 只有真走通上行通道才有，受控拒绝（`not_caller`）
            # 那一档 `ok=False`、`data=None` ⇒ 继续跑（顶层 M 调它不该停掉自己）。`shape` 在这一档是
            # `"tool"`（`_decode_shape` 返回 SHAPES 的键），工具真名在 `payload["name"]` —— 写成
            # `shape == "conductor.escalate"` 永远不成立，模型每步重发 ⇒ 跑成 O(n²) 死循环。
            _esc = result.get("data") if isinstance(result.get("data"), dict) else {}
            if (shape == "tool" and str(payload.get("name") or "") == "conductor.escalate"
                    and _esc.get("state") == "escalated"):
                run.stop_reason = "escalated"
                run.final = (f"已上报召唤者 {_esc.get('to') or '（角色未记）'}"
                             f"（{_esc.get('kind') or '?'}）：{_esc.get('need') or ''}；"
                             f"留言 {_esc.get('msg_id') or '（没有编号）'} 已在它下一趟的收件箱里 —— "
                             "这一趟停在交出判断的那一步之后，等它处理完再续。")
                run.notes.append(
                    f"以 escalated 收工：上报给 {_esc.get('to')}（台账号 "
                    f"{_esc.get('to_task_id') or '?'}，msg_id={_esc.get('msg_id') or '?'}）")
                break
        else:
            # 到不了这里（上面的 `for` 走的是无限计数器，裁定 12-K：不设步数硬闸）。
            # 留着这一支只为"万一有人把计数器换成有限 range"时不静默：见下面的判据。
            run.stop_reason = "no_progress_limit"

        # ---- 拆分口径的收尾：本回合拆出来、但没轮到执行的条目
        #
        # 出口（收工 / 判停 / 预算 / 叫停 / 墙钟 / 上行）都可能在回合中途发生。
        # 剩下的条目照样计步（业主要看的步数是拆后的）并标 `not_executed`，
        # 理由如实写（"因预算未执行" / "因本回合已收工未执行"）—— 不许把它们静默丢掉，
        # 更不许把没执行的那一条折成成功。
        if dispatch is not None and pending:
            self._settle_pending_items(dispatch, pending, run, messages)

        # ---- D-64 退场：还挂着的派活句柄最多再等一小段，然后如实留痕
        #
        # 正常收工走不到"还有孩子在跑"这一支（收工门会先拒）；能走到这里的是
        # 别的出口（预算/叫停/协议连击/上行/等用户）。那些孩子不在这条调用栈上，
        # 会在后台跑完 —— 这一趟要给的是"我走的时候它们还没回来"，不是假装没有。
        self._settle_children_at_exit(run=run)

        run.spend = self.seam.spend.to_dict()
        # ---- 提示词缓存的收工汇总（2026-10-19）：上游的
        # `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` 从 2026-10-14 起就在
        # `SeamCall` 上，但从没汇总进任何 run 记录 ⇒ "提示词改完到底省了多少"
        # 在真机上一条读数都没有。这里把它按调用汇总成 `LoopRun.prompt_cache`，
        # 并落一句人话进 `notes`（它跟着 `agent_run_end` 一起落盘 = 收工那一行）。
        #
        # 三态纪律：上游没给读数 ⇒ `unknown_calls` 加一，命中率是 `None`（不是 0）;
        # 可省金额按 `modelcost.usd_for` 的口径算（`promptstability._saved_usd_of`），
        # 算不出来的那些单独计数 —— 不拿"0"顶上。
        run.prompt_cache = PSTAB.summarize_prompt_cache(
            [dict(s.cache) for s in run.steps if s.cache])
        cache_note = PSTAB.cache_sentence(run.prompt_cache)
        if cache_note:
            run.notes.append(cache_note)
        # ---- 子产出的处理读数（业主裁定：父代理必须处理子代理的产出）
        #
        # 为什么在这里算（而不是在步循环里逐条记）：这一格要回答的是"这一趟整体
        # 有没有把子产出用起来"，而"用起来"的判据允许后续任何一步（含收工那一句里的
        # 具体产物指涉）—— 只有全部步都走完才判得准。判据本体在 `summon_consumption`，
        # 这里只把结果落成 `LoopRun` 的读数 + 收工那一行的一句话。
        #
        # 四个数进 `agent_run_end`（收工那一行）与 `to_dict()`：`summons_unconsumed > 0`
        # 时它必须看得见（不 fail，但收工门的相应格读得到 —— 见
        # `closing.summon_consumption_reading`）。
        run.summon_consumption = summon_consumption(run)
        run.summons_total = int(run.summon_consumption["summons_total"])
        run.summons_consumed = int(run.summon_consumption["summons_consumed"])
        run.summons_continued = int(run.summon_consumption["summons_continued"])
        run.summons_waived = int(run.summon_consumption["summons_waived"])
        run.summons_unconsumed = int(run.summon_consumption["summons_unconsumed"])
        run.notes.append(summon_consumption_sentence(run.summon_consumption))
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
        # ---- 业主 2026-10-21「全面接入」第二步（写侧）：收工那一行也要带绝对编号。
        #
        # 改前的形态就是下面这行去掉 `task_id` 那个键：`agent_run_start` 带编号
        # （`"task_id": my_task_id`，见本文件 run() 里那条 start 事件）、`agent_message`
        # 带 `from_task_id`，唯独 `agent_run_end` 不带。后果不在这一层，而在读侧：
        # `webui.readers._chat_line` 的 `task_id_source` 于是对"某某交付"那条对话线
        # 恒判 `missing`（真机读数 projects/p3-verify：A 交付 / E 交付两条都是 missing，
        # 而同段会话里 A、E 的 `agent_run_start` 都有编号）—— 页面上的那句话
        # "哪个绝对编号的哪个角色在说话"在交付那一行上答不出来。
        #
        # 取值的口径与 start 那条逐字相同：`self.my_task_id` 就是 `run_role` 为这一趟
        # 开出来的 tasks 行号（子代理那条路是 `row["task_id"]`），不是新编的号。
        # 空串照落（不造一个假编号）：没拿到台账号的那一趟，读侧要看得见"没拿到"。
        SS.append(self.session_root, {
            "kind": "agent_run_end", "role": self.role,
            "task_id": str(self.my_task_id or ""),
            "stop_reason": run.stop_reason, "steps": len(run.steps), "summons": run.summons,
            "messages": run.messages_sent,
            "blocked_remaining": dict(run.blocked_remaining),
            # 停在等谁（空 = 不是那一档）：界面与 `inbox` 要的就地读数，
            # 不必去解析 `final` 那句话里的 qid。
            "waiting_for": run.waiting_for,
            # `final` 是这一岗的交付物本身：只记长度的话，事后没人能核
            # "它到底与验收表对齐了没有"（实测：终点门槛 A 要逐条核交付说明，
            # 而会话记录里只有 `final_chars`）。文本与哈希一起留，长度保留是为了
            # 让"有没有被截断"一眼可见。
            "final": run.final, "final_sha256": _sha(run.final)[:16],
            "final_chars": len(run.final), "spend": dict(run.spend),
            # ---- D-52 / D-53 的收口读数：这一趟投递了多少条 / 唤醒了几次。
            #
            # 与 `agent_mailbox` / `agent_wake` 两条事件同源：事件流可以逐条复算
            # （以 item_id / wake_id 为键），这两个数是它的汇总（收工那一行一眼可读）。
            # 刻意分成两格而不是并成一个总数：板项与留言的消费语义不同
            # （状态机 vs 投递登记），合并之后"投了 9 条"读不出是哪一种。
            "mailbox_items": list(run.mailbox_items),
            "mailbox_msgs": list(run.mailbox_msgs),
            "mailbox_delivered": len(run.mailbox_items) + len(run.mailbox_msgs),
            "monitor_turns": run.monitor_turns,
            "wakes": run.wakes,
            "wake_ids": list(run.wake_ids),
            "wake_events": [dict(e) for e in run.wake_events],
            "clock_pumps": run.clock_pumps,
            "clock_fired": run.clock_fired,
            # 提示词缓存的收工读数（`LoopRun.prompt_cache`）：与 `spend` 并列 ——
            # "花了多少"与"靠前缀缓存省了多少"是同一笔钱的两面，分开落才核得动。
            "prompt_cache": dict(run.prompt_cache),
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
            # ---- 子产出的处理读数（业主裁定：父代理必须处理子代理的产出）
            #
            # 收工那一行必须读得到这四个数（`summons_total` / `summons_consumed` /
            # `summons_waived` / `summons_unconsumed`）—— 它们是这条规矩唯一的执行面：
            # "没处理"不 fail，但必须可见（收工门那一格读的就是它，
            # 见 `closing.summon_consumption_reading`）。
            #
            # 只落这一份（不再把四个数另抄一份到顶层）：`summon_consumption` 是
            # `summon_consumption()` 的完整返回，四个数就在里面 —— 同一件事两份落点
            # 迟早会分叉，而分叉的形态是"事件说处理了、明细说没处理"。
            "summon_consumption": dict(run.summon_consumption),
            # ---- 未了义务（D12）：收工那一刻名下还有几条证明没有 V 的签字。
            #
            # 两个键并排落，是因为它们答的不是同一个问题：
            # `final_gaps` 是那个数（`None` = 没读成 —— 不是 0，三态纪律），
            # `final_gaps_reading` 是它的明细（逐条命题号 + 哪一条读不成 + 理由）。
            # 只报数会让"读不成"与"0 条"在读数上同形，而这两件事下一步该做的事相反。
            "final_gaps": (None if run.final_gaps.get("unsigned") is None
                           else int(run.final_gaps.get("unsigned") or 0)),
            "final_gaps_reading": dict(run.final_gaps),
        }, sid=self.sid)
        # ---- 业主裁定（「M 停整棵树」的删除半）：全工作区开关的删除推迟到这一趟收尾，
        # 且只有树根删（`_stop_to_consume_at_end` 只由树根挂上）。位置必须在这里 ——
        # `agent_run_end`（含 `final`/台账读数）已经落盘，再撤信号；反过来一旦写台账失败，
        # 盘上就只剩"开关没了"，没有任何东西说明"该停"。
        self._consume_stop_at_teardown()
        return run

    # -------------------------------------------------------------- 执行
    def _block_remaining(self, run: "AgentLoop.LoopRun", why: str) -> None:
        """优雅停止：把这一趟没做完的任务与委托由框架翻成 `block`（业主 2026-10-13）。

        为什么是框架翻而不是"让模型汇报"：预算耗尽那一支根本没有模型回合
        （循环在步边界直接 break）—— 想让它汇报就只能等下一次模型调用，而那时钱已经没了。
        所以口径落成：状态由框架翻、理由由框架写（`why` = 停机理由），模型只在下游读它。
        """
        task_id = str((run.prompt_audit or {}).get("task_id") or "")
        if not task_id:
            run.blocked_remaining = {"checked": False, "blocked": [], "blocked_items": [],
                                     "why": why,
                                     "reason": "这一趟还没落台账号 ⇒ 剩余任务翻不了（没查成）"}
            return
        from . import stopctl as SC

        got = SC.block_remaining_tasks(self.store, task_id=task_id, why=why)
        run.blocked_remaining = dict(got)
        if got.get("blocked"):
            run.notes.append(
                f"优雅停止（{why}）：{len(got['blocked'])} 条没做完的任务/委托已由框架翻成 "
                f"`block`（{', '.join(got['blocked'][:6])}）—— 这一步会随结果回给父代理，"
                "由 M 汇总进交付说明")

    def _land_budget_stop_record(self, limit: float) -> str:
        """预算耗尽时落一个一次性停机记录（写 + 立刻消费，见调用点的三条理由）。

        返回空串 = 落成了；非空 = 没落成的那一句（调用方把它收进 `run.notes`）——
        静默失败会让"停机信号发出去了"变成一句假话。

        为什么用 `stopctl` 而不是自己写一个文件：跨进程停机信号这一层已经有它
        （三态结局 `created/upgraded/existing`、append-only 历史 `runs/stop-history.jsonl`、
        `agentflow stop --status` 读它），再写一份必然分叉 —— 而分叉的形态是
        "有一条循环停了、另一条没看见"。
        """
        from . import stopctl as SC

        problems: list[str] = []
        try:
            _payload, outcome = SC.request_stop_detail(
                self.session_root, reason=f"预算耗尽（上限 {limit:.6f}）", by="budget",
                sid=self.sid)
        except Exception as exc:  # noqa: BLE001 —— 见 docstring
            return f"预算停机记录没落成：{type(exc).__name__}: {exc}"
        if outcome != "created":
            # 盘上已经有一把别人的开关（`existing` / `upgraded`）：不许动它
            # （谁写的谁清，`request_stop_detail` 的 docstring 逐字写着这条），
            # 于是这一次不消费 —— 只把这件事记成读数。
            return (f"预算耗尽，但盘上已有一把停机开关（结局 {outcome}）"
                    "⇒ 这一次没有再写、也没有消费它")
        try:
            SC.consume_stop(self.session_root, sid=self.sid, level="budget")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"预算停机记录消费失败：{type(exc).__name__}: {exc}")
        return "；".join(problems)

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

        业主对 `blocked` 的窄定义（第四句 + 第六句，逐字）：「上述层层上报困难也会带来一种停机状态，即所有活跃子代理的
        状态都是 blocked」；而「如果被委托的任务单纯是在职责之外，则应该将自己能力内的做完后上报情况就 over 了；如果是
        需要请示上级指导任务实施细则，才会 block」⇒ 两件事必须分得开：
        - 职责之外：做完自己能力内的、上报情况、正常收工（`final`）—— 这条路上不写 `blocked`（机器判据：那一条上报会让
          `escalation_gaps` 归零，不需要 blocked）；
        - 等上级指导实施细则：才是 `blocked`，载体是
          `{"final": "...", "blocked": {"what": …, "why": …, "needs": "请上级定 X"}}`，其中 `needs` 必填：说不出要请示
          什么，那多半不是 blocked，而是"职责之外"那一档。
        只在给了 `blocked` 的时候处理（没声明 ⇒ 老行为逐字不变）。三态都如实报：没有父 / 没有 conductor / 落痕失败 ⇒
        一句读数，不打断收工。
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

    def _is_tree_root(self) -> bool:
        """这一趟是不是「这棵树」的根（业主裁定：全工作区开关 = M 把整棵树停了）。

        业主的口径：一个停机开关落下后，M 那一趟以及它派出去的所有子孙循环都必须停；"谁是第一个读到的"不许决定别人停不
        停。所以撤开关这件事只能落在树根身上 —— 任何成员撤它，都会让还没读到的那一支静默继续跑（方向正好相反的那个
        §140 bug）。
        判据三档（取第一个成立的）：1. 这一趟没有台账号（`my_task_id` 空）⇒ 它就是树的起点（没落台账的顶趟、没接主控的
        那条路都没有别人可挂在下面）；2. 没有父任务（`parent_task_id` 空）⇒ 树根；3. `parent_task_id == my_task_id` ⇒
        也是没有父：`_resolve_parent` 的第三条分支把"顶层发起"的收件人落回自己（`parent_task_id` 是空时，它逐字
        `return str(self.my_task_id or ""), …`）。
        其余一律是成员。"没有台账号"也算树根而不是判不了：台账号是被召唤那一刻由调用方给的（`LlmBackend.call` 从它那一
        行读出来），没有台账号的循环不可能是别人派出来的 —— 这一档不是"不知道"，而是"确定没有父"。
        """
        mine = str(self.my_task_id or "")
        if not mine:
            return True
        parent = str(getattr(self, "parent_task_id", "") or "")
        return (not parent) or (parent == mine)

    def _stop_applies(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """盘上这把停机开关管不管我（S4，`draft/90` E7 / `draft/84` §2.2）。

        返回 `{"stop","remove","why"}`；全工作区那一档多一格 `consume_at_end`：
        | 开关 | 我 | 结论 |
        |---|---|---|
        | 全工作区（没有 `root_task_id`） | 树根 | 停，读时不撤；`consume_at_end=True` ⇒ 由我收尾时撤 |
        | 全工作区 | 成员（有父） | 停，不撤（`remove=False`、`consume_at_end=False`）—— 别人还要读到它 |
        | 子树（有 `root_task_id`） | 我就是那一支的根 | 停，并且由我撤（`remove=True`，读时即撤） |
        | 子树 | 我在那一支里、是成员 | 停，但不撤（`remove=False`）—— 同支别的循环还要读到它 |
        | 子树 | 我不在那一支里 | 不停（"停 D 那一支"不许停到 E 那一支） |
        | 子树 | 判不了（台账读不成 / 我没编号） | 不停 + 一句读数（判不了 ≠ 适用） |
        为什么"读时不删、收工时树根才删"：改前是"读到的第一个撤掉它"（§140 一次性信号），可并行子孙各有各的步边界 ——
        谁先读到谁撤了开关，其余人下一刻读到"没人叫停"，静默继续跑。第一次修（"只有树根撤"）只挡住一半：树根读到时即删，
        兄弟下一刻同样读不到。真机读数：第 1 趟 `s1 stop_reason='stop_file' … 开关还在=False`，第 2 趟
        `s2 stop_reason='final'`。现在把删除推迟到这一趟收工时：谁读到都 `stop=True`，但谁都不在这一刻删；只有树根带着
        `consume_at_end=True` 走到收尾（`run()` 末尾、`agent_run_end` 落盘之后）才由 `_consume_stop_at_teardown` 调
        `consume_stop(remove=True)`。成员一律 `remove=False`、`consume_at_end=False`，只把这一笔记进
        `runs/stop-history.jsonl`（`removed=False`）。子树那一档语义一个字没动（`stop_scope="subtree"` 仍按
        `inside_subtree` 四档判）；`force` 与 `stop_file` 走同一条判据（`_user_stop_reason` 只在理由码上分岔）。
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
            # 全工作区 = 整棵树停：谁都停，但读的时候谁都不删；只有树根收尾时撤
            # （`consume_at_end`，见 docstring 那一节与 `_consume_stop_at_teardown`）。
            return {"stop": True, "remove": False,
                    "consume_at_end": self._is_tree_root(), "why": ""}
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

    def _arm_stop_teardown(self, reason: str, *, explicit: str = "") -> None:
        """记下「这一趟收工时该由我撤」的那把全工作区开关（业主裁定：删是整棵树的事）。

        只有树根会走到这里 —— `_stop_applies` 只在「全工作区 + `_is_tree_root()`」时
        给出 `consume_at_end=True`。成员一律不记：它们撤了，同一棵树上还没读到的
        那一支下一刻就是"没人叫停"（静默继续跑）。

        `explicit` 原样带着：这一趟读的是 `--stop-file` 给的路径，收尾要撤的也必须是它
        —— 工作区里可能同时有 `.agentflow-stop` 与一个显式路径，撤错文件等于没撤。
        """
        self._stop_to_consume_at_end = {"reason": str(reason or "stop_file"),
                                        "explicit": str(explicit or "")}

    def _consume_stop_at_teardown(self) -> str:
        """树根收工时撤掉那把全工作区开关；返回一句读数（空串 = 没什么要报的）。

        为什么删除落在这里、不在"读到时"：读的那一刻删 ⇒ 还没走到步边界的兄弟/子孙下一刻读不到文件 ⇒ 静默继续跑。真机
        读数（前代理实测）：第 1 趟 `s1 stop_reason='stop_file' … 开关还在=False`，第 2 趟 `s2 stop_reason='final'`
        —— 继续跑。所以读只记录"该停"与"该由我撤"（`_arm_stop_teardown`），删除统一落到这一趟自己的收尾。
        为什么只有树根：成员删它等于替整棵树做了决定（同树别的循环还没读到），`_stop_applies` 只在 `_is_tree_root()`
        为真时给 `consume_at_end=True`。顺序：先写 final/台账，再删开关 —— 调用点在 `run()` 末尾、`agent_run_end`（含
        `final` 与这一趟的台账读数）落盘之后；反过来一旦写台账失败，盘上就只剩"开关没了"、没有任何东西说明"该停"。
        三态（不许把"没撤成"读成"没叫停"）：撤成功 ⇒ 空串；走到收尾时开关已经不在盘上（别处 `--clear` 或另一个进程撤走）
        ⇒ 一句读数（这一笔不是我撤的）；历史记了但文件还在（被别的进程占着）⇒ 一句读数。三者都不改变"这一趟已停"这个事
        实（`stop_reason` 早已是 `stop_file`/`force_stop`）。
        """
        pending = self._stop_to_consume_at_end
        self._stop_to_consume_at_end = {}
        if not pending:
            return ""
        explicit = str(pending.get("explicit") or "") or None
        try:
            from . import stopctl

            record = stopctl.consume_stop(
                self.session_root, sid=self.sid,
                level=str(pending.get("reason") or "stop_file"),
                explicit=explicit, remove=True)
        except Exception as exc:  # noqa: BLE001 —— 撤开关失败不许带走这一趟的产出
            note = (f"收工撤停机开关失败（{type(exc).__name__}: {exc}）"
                    "⇒ 开关可能还在盘上，下一趟会被它再停一次")
        else:
            if not record:
                note = ("收工撤停机开关：走到收尾时开关已经不在盘上了"
                        "（别处 `--clear` 或另一个进程撤走了）⇒ 这一笔不是我撤的")
            else:
                try:
                    still = stopctl.stop_path(self.session_root, explicit=explicit).is_file()
                except Exception:  # noqa: BLE001 —— 判不了就不猜（不许把没查成报成没撤掉）
                    return ""
                if not still:
                    return ""
                note = ("收工撤停机开关：历史记下了（`removed=True`）但文件还在盘上"
                        "（多半被别的进程占着）⇒ 下一趟会被它再停一次")
        try:
            SS.append(self.session_root, {"kind": "agent_note", "role": self.role,
                                          "note": note}, sid=self.sid)
        except Exception:  # noqa: BLE001 —— 连读数都写不成也不许带走这一趟
            pass
        return note

    def _user_stop_reason(self, run: "AgentLoop.LoopRun") -> str:
        """人叫停了吗（`draft/37` §125）。返回停止原因（空串 = 没叫停，继续跑）。

        两处来源，与 `autonomy._stop_before_round` 用「同一套词」：`stop_file`（`--stop-file` 或这里给的路径指向的文件
        存在于盘上）；`user_stop` 已删除（业主口径 2026-10-17「删掉旁路」：停意由主控理解意思后调 `conductor.stop` 完
        成，不靠单词匹配 —— 字面匹配漏中文「停」「收工」）。
        `escalated` 不在这张表里（业主 2026-10-19「父子天然双向」）：`conductor.escalate` 收工那一趟的 `stop_reason`
        是 `"escalated"`，而它不是用户叫停 —— 停意不是任何人从外面下的，是这一趟自己判定"这件事该交回召唤者"，所以本方
        法只给 `stop_file` / `force_stop` / `interrupted_by_parent`；`cli.EXIT_CODE_BY_STOP` 把它归 5（自行停止），归
        4 的是 `stop_file` / `force_stop` / `budget` / `interrupted_by_parent`。判据：
        `tests/test_escalate_goes_up_and_stops.py` 的 `test_escalated_is_not_read_as_a_user_stop`（两向都钉）。
        为什么要在步循环里查：`autonomy` 那套只在「每轮之间」跑，单趟 `run-agent`（不 `--rounds`）根本不走那条路—— 真
        机实测（2026-10-04）用户叫停后那一趟继续跑了 60 多个任务、烧掉 $0.98 才被强杀（不留痕：没有 `agent_run_end`）；
        `user_stop` 要比时间戳：翻到「上一次」的 STOP 就停会把之后每一趟都判死。
        第三个来源（`draft/37` §128）：「工作区的停机开关」（`.agentflow-stop`，`stopctl`）—— M 的 `conductor.stop` 与
        `agentflow stop` 写下的那一份，也是「唯一」能打断在飞工作的通道（广播做不到：收件箱是 `run()` 开头读一次的）；
        `force=true` ⇒ 走 `force_stop`。§140：开关是「一次性信号」（停一趟 → 记一笔 → 撤走）—— 实测（
        `temp/_stop_probe.py`）：`conductor.stop` 停一趟后开关留在盘上、紧接着的 `--resume` 在第 0 步就被它停掉 ⇒ 判定
        生效就调 `stopctl.consume_stop(...)`（审计进 `runs/stop-history.jsonl`）。全工作区那一档的删除再往后挪一格（业
        主裁定「M 停整棵树」）：树根的删除推迟到这一趟收尾（`_consume_stop_at_teardown`，排在 `agent_run_end` 之后）。
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
                if verdict.get("consume_at_end"):
                    # 全工作区 + 我是树根：读的这一刻不删（兄弟/子孙还没读到），
                    # 只记下"这一趟收工时该我撤"——见 `_consume_stop_at_teardown`。
                    self._arm_stop_teardown(reason, explicit=self.stop_file)
                else:
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
            if verdict.get("consume_at_end"):
                # 全工作区 + 我是树根：读时不删，收尾才删（见 `_stop_applies`）。
                self._arm_stop_teardown(reason)
            else:
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
            break                      # 只看"开始之后最近的那一条"
        return ""

    def _stop_note(self, stop_reason: str, step: int) -> str:
        """人叫停时写进 `final` 的那句话（要能直接告诉人"停在哪儿、怎么接着跑"）。"""
        what = {"stop_file": f"用户叫停（开关文件 {self.stop_file or '.agentflow-stop'}）",
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
                      "raw_reply": _clip(json.dumps(data, ensure_ascii=False, default=str), 600)}
        run.steps.append(LoopStep(step, "invalid", payload, bad_result, problem=help_text))
        SS.append(self.session_root, {
            "kind": "agent_step", "role": self.role, "index": step,
            "shape": "invalid", "payload": dict(payload), "result": dict(bad_result),
        }, sid=self.sid)
        return _payload_line(step, shape, help_text), run.notify_rejections >= self.max_notify_rejections

    def _dispatch_notify(self, payload: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
        """主控派活时的留痕载荷：返回 `(问题, 交给 `_do_handoff` 的载荷 或 None)`。

        两种来源（`draft/39` §6.4 四.1 的裁定；L-05e 之后都不再打回）：1. 模型填了 `notify` ⇒ 用它（`note`
        标成"模型填的 notify"）；2. 没填、或填的形状不能用 ⇒ 框架据派活本身派生一份（`note` 标成"框架据派活
        派生"），写的是"谁派了谁做什么、参数是什么、为什么"——这些是框架手上已有的事实。

        为什么形状不对也退回派生（L-05e）：旧口径是"填错就打回、那一次派活不发生"，但真机 5269 个
        `agent_step` 里这道闸门一次都没触发（`no_notify` 收场 0 次），而"因为一张表的格式让一次真的要发生的
        派活停下来"正是 #1 的形态。现在：派活照常发生，形状问题落进 `run.notes`，留痕退回派生那一份（"谁是派
        生、谁是执笔"两个标记仍然分得开）。`to` 的缺省是被派的那个角色（多目标 ⇒ `ALL`）。
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
            lines.append(f"- {_dispatch_label(t)}：参数 "
                         f"`{json.dumps(dict(t.get('params') or {}), ensure_ascii=False, default=str)}`"
                         + (f"（instance={t.get('instance')}）" if t.get("instance") else ""))
        why = str(payload.get("why") or "").strip()
        if why:
            lines += ["", "## 为什么派它", why]
        lines += ["", "## 这一行是怎么来的",
                  "模型这一句派活没有填 `notify` 表 ⇒ 框架据派活本身派生（"
                  "谁派了谁做什么、参数、为什么），内容全部取自这一句派活；"
                  "执笔的是本角色自己的秘书（智能体侧只保留『查』，`draft/55` §3.2）。"]
        what = ", ".join(_dispatch_label(t)
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

        名字已按主控 2026-10-07 的裁定改掉（`_notify_gate` → `notify_reading`：旧名在说谎 —— 它不打回；本仓
        顶级教训之一是"名字在说一件事、断言在说另一件"）。改名时全树 8 处引用，`tests/test_agent_prompts.py`
        里还有 2 处注释提到旧名，刻意留到那条线收工后再改（已登记在主控记录里）。

        三条判断（顺序就是"先看该不该填，再看填得对不对"）：1. 主控 M 免填（它的 `final` 是给用户的回复，用
        户 2026-10-05 原话："M 向 Agent 派活时一样强制留痕，向用户回复时不搞这种操作"）；2. 没填 / 填错形状
        ⇒ 这一格没有可用读数（形状判据只有一份：`notify_shape_problem`）；3. 填了但 refs 悬空 ⇒ 同一格也没有
        可用读数（`manuscripts.ref_problem` 是写入期同一份判据）。返回空串只有一个含义：读成了、可以照着写手
        稿。
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

    # ---------------------------------------------------------------- 拆分条目（stepdispatch）
    #
    # 这一组是本文件与 `stepdispatch` 的接缝，只做三件事：解码第 2..N 条原生调用、
    # 落"逐条记录"、把没轮到的条目如实收尾。拆分本身与"多条怎么处理"的判据
    # 全在 `stepdispatch` 里 —— 本文件没有第二支"多条怎么办"。

    def _decode_call_item(self, raw: Mapping[str, Any]) -> tuple[str, Mapping[str, Any],
                                                                str, str, str]:
        """接住层的 `decode` 回调：一条原生调用 ⇒ `(shape, payload, action, problem, detail)`。

        与第 1 条走的是同一套解码（`ToolFace.to_shape` → `_shape_of`），所以
        "第 2 条调用被怎么读"与"第 1 条被怎么读"不可能出现两套判据。
        解码不出来时第 3 个返回值是 `problem`（那一条不执行、如实记成被拒）。
        """
        face = self._face
        if face is None:
            return ("", {}, str(raw.get("name") or ""), "judge_bad_json",
                    "这一趟没有原生工具面 ⇒ 这条调用解码不出来")
        action = str(face.action_name(raw))
        data, problem, detail = face.to_shape(raw)
        if data is None:
            return "", {}, action, problem or "judge_bad_json", str(detail)
        shape, payload, problem = _shape_of(data, roster=self._address_of)
        return str(shape), payload, action, str(problem), ""

    def _land_step_call(self, item: Any, shape: str, payload: Mapping[str, Any],
                        outcome: Mapping[str, Any], run: "AgentLoop.LoopRun") -> None:
        """落一条 `agent_step_call`：第几条 / 工具名 / ok / 耗时 / usd（逐条可查的落点）。

        键的三态：`not_executed=True` 的那一条 `ok=False` 且带 `reason`（不许折成成功）；
        `usd` 是这一条执行期间的全局花销增量（只读工具是 0.0，召唤一路才可能非零），
        `usd=None` 只在"这一条没执行"时出现（没有花销可算，不是"花了零"）。
        """
        try:
            SS.append(self.session_root, {
                "kind": SD.STEP_CALL_EVENT, "role": self.role,
                "index": int(item.step_index),
                "turn_index": int(item.turn_index),
                "call_index": int(item.call_index),
                "calls": int(item.calls),
                "shape": str(shape),
                "tool": str(outcome.get("action") or SD.action_of(shape, payload)),
                "ok": bool(outcome.get("ok")),
                "outcome": str(outcome.get("line") or ""),
                "not_executed": bool(outcome.get("not_executed")),
                "reason": str(outcome.get("reason") or ""),
                "elapsed_ms": int(outcome.get("elapsed_ms") or 0),
                "usd": outcome.get("usd"),
            }, sid=self.sid)
        except Exception as exc:  # noqa: BLE001 —— 读数落不成不许带走这一趟
            run.notes.append(f"逐条记录没落成（第 {item.call_index + 1} 条："
                             f"{type(exc).__name__}: {exc}）")

    def _record_undecodable_item(self, item: Any, dispatch: Any, run: "AgentLoop.LoopRun",
                                 step_cache: Mapping[str, Any],
                                 messages: list[dict[str, Any]]) -> None:
        """这一条装不出来（没广告过的函数 / 参数不是 JSON）⇒ 记一条"未执行"，不影响其余。

        为什么不把它算进 `bad_json` 连击：整步的协议是对的（其余条目照常执行），
        坏的只是"这一条调用"。把它算进连击会让"模型多给了一条写错的调用"变成
        "整趟按坏 JSON 收工"，那正是这次要修掉的形态。
        """
        outcome = SD.outcome_of(item.shape, item.payload, {}, executed=False)
        outcome["line"] = ("未执行（解码不出："
                           f"{SD.digest_line(item.detail or item.problem, 60)}）")
        outcome["not_executed"] = True
        outcome["reason"] = "decode"
        outcome["usd"] = None
        if dispatch is not None:
            dispatch.note(item, outcome)
        entry = {"ok": False, "not_executed": True, "reason": "decode",
                 "problem": str(item.problem or "judge_bad_json"),
                 "detail": str(item.detail or ""),
                 "multi_call": (dispatch.provenance(item) if dispatch is not None else {})}
        run.steps.append(LoopStep(int(item.step_index), "invalid", dict(item.payload), entry,
                                  problem=str(item.problem or "judge_bad_json"),
                                  cache=dict(step_cache)))
        SS.append(self.session_root, {
            "kind": "agent_step", "role": self.role, "index": int(item.step_index),
            "shape": "invalid", "payload": dict(item.payload), "result": dict(entry),
            "prompt_cache": dict(step_cache),
        }, sid=self.sid)
        # 消息序列照 `resume_messages` 对 invalid 步的拼法补上（同一套纠正话术）：
        # 只落事件不落消息，续跑重建出来的那一段就会比当时多两步。
        problem = str(item.problem or "judge_bad_json")
        messages.append(assistant_message(item.step_index, item.payload, name="invalid"))
        messages.append(tool_message(item.step_index,
                                     _invalid_correction(item.step_index, problem,
                                                         str(item.detail or "")),
                                     name="invalid"))
        self._land_step_call(item, item.shape, item.payload, outcome, run)
        run.notes.append(f"第 {item.call_index + 1} 条调用没执行（解码不出）："
                         f"{SD.digest_line(item.detail or item.problem, 120)}")

    def _settle_pending_items(self, dispatch: Any, pending: list[Any], run: "AgentLoop.LoopRun",
                              messages: list[dict[str, Any]]) -> None:
        """把回合里没轮到的条目收尾：照样计步、标"未执行"、理由如实。

        消息序列也要补上同样的两条（assistant + tool）：`resume_messages` 是按
        `agent_step` 事件逐条重建的，这里只落事件不落消息，续跑那一趟就会看到
        比当时多出几步 —— "当时那份"与"重建那份逐条相等"是本仓最强的一条判据。
        """
        reason = (SD.NOT_EXECUTED_BUDGET if run.stop_reason == "budget"
                  else SD.NOT_EXECUTED_FINISHED)
        for item in list(pending):
            outcome = dispatch.mark_not_executed(item, reason)
            outcome["usd"] = None
            shape = str(item.shape or "invalid")
            entry: dict[str, Any] = {
                "ok": False, "not_executed": True, "reason": str(reason),
                "detail": str(outcome.get("detail") or outcome.get("line") or ""),
                "multi_call": dispatch.provenance(item),
            }
            if item.is_last:
                summary = dispatch.summary()
                entry["warn"] = summary
                entry["multi_call"] = {**dispatch.provenance(item), "summary": summary,
                                       "turn": dispatch.reading()}
            run.steps.append(LoopStep(int(item.step_index), shape, dict(item.payload), entry,
                                      cache={}))
            SS.append(self.session_root, {
                "kind": "agent_step", "role": self.role, "index": int(item.step_index),
                "shape": shape, "payload": dict(item.payload), "result": dict(entry),
                "prompt_cache": {},
            }, sid=self.sid)
            messages.append(assistant_message(item.step_index, item.payload, name=shape,
                                              content=_spoken_half(item.step_index, item.payload)))
            messages.append(tool_message(item.step_index, _result_half(entry), name=shape))
            self._land_step_call(item, shape, item.payload, outcome, run)

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
        # 父的绝对编号（2026-10-20）：整批共用这一格；空 ⇒ 受控拒绝（同 `_do_summon`）。
        owner = self._summon_owner()
        if not owner:
            got = self._no_owner_refusal("把这一批活派出去：")
            return {**got, "summoned": [], "count": 0}
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
        #: 每个 target 的 `brief` / `task`（与 `calls` 同序）—— 登记时逐项取自己的那两句。
        #: 2026-10-20 业主裁定（「简介没写，则秘书帮忙写」）：`brief` 只原样传下去，
        #: 代写这件事在秘书那一侧做（`roster_add(task=…)` 内部派生 + 留痕
        #: `brief_source="secretary"`）—— 这里刻意不写 `brief or task`（那是"任务原文顶替"，
        #: 业主选的是"秘书写"）。
        briefs: list[str] = []
        tasks: list[str] = []
        blank: list[str] = []
        for t in targets:
            instance = str(t.get("instance") or "")
            if not instance and str(t.get("role")) in auto:
                used[str(t["role"])] = used.get(str(t["role"]), 0) + 1
                instance = auto[str(t["role"])][used[str(t["role"])] - 1]
            # 2026-10-16（S2「M 只派活」）：每个 target 与 `summon` 同一套语义 ——
            # 不点动作（`action` 空）= 派一件活给它，由它自己选动作；
            # 此时 `task` 必填（否则接活的人不知道自己该干什么）。与 `_do_summon` 同款。
            # 2026-10-16（口径 S2 最终形态）：每个 target 的动作一律当空（父代理不填动作）。
            t_action = ""
            t_params = dict(t.get("params") or {})
            t_task = str(t.get("task") or "")
            # 2026-10-16（口径 S2）：`task` 一律必填（与 `_do_summon` 同款）。
            if not t_task.strip():
                blank.append(str(t.get("role")))
                continue
            if not t_action:
                t_params["task"] = t_task
            calls.append(SC.TaskCall(role=str(t.get("role")), action=t_action,
                                     params=t_params, by=self.role,
                                     parent_task_id=owner,
                                     input_key=(str(t.get("input_key") or "")
                                                or _summon_key(t_action, t_params)),
                                     instance=instance,
                                     # 名册那两格随这一项走（`scheduler` 逐个调 `summon`
                                     # 时原样转交）—— 登记在 `summon` 的 [5b]，而 brief
                                     # 只活在这个载荷里（`tasks` 行没有这两格）。
                                     roster={"brief": str(t.get("brief") or ""),
                                             "task": t_task,
                                             "name": str(t.get("name") or ""),
                                             "reuse": str(t.get("reuse") or "")}))
            briefs.append(str(t.get("brief") or ""))
            tasks.append(t_task)
        if blank:
            return {"summoned": [], "ok": False, "count": 0,
                    "error": ("这批里有 target 没写清活（role="
                              + "、".join(blank) + "）：`task` 必填")}
        # 父是谁要挂到上下文里（`run_plan` 的队列认领那一步从这里读）—— 不走形参，
        # 见 `conductor.consuming_as` 的理由（一批判据的替身函数不接受新形参）。
        from .conductor import consuming_as

        # 要不要走可抢占那一档：`run_plan` 收不收 `preemptible` 这个开关。
        # 为什么要探一下签名的本事：一批判据用 `run_plan` 的替身（它们只认
        # `(calls, token=None)`），硬传一个多余的关键字会变成 TypeError ——
        # 那种红与"可抢占坏了"长得一样，会把真问题淹掉。替身/旧实现 ⇒ 走它们
        # 自己那一套（返回列表，本来就是"全部跑完"的语义）。
        preemptible = (bool(PREEMPTIBLE_DISPATCH)
                       and not _patched_on_instance(c, "run_plan")
                       and _takes_kwarg(c.run_plan, "preemptible"))
        with consuming_as(owner):
            if preemptible:
                batch = c.run_plan(calls, token=self.token, preemptible=True)
            else:
                batch = c.run_plan(calls, token=self.token)
        # ---- 可抢占（D-64）：只在本步里等 `child_step_wait_sec` 秒
        #
        # 改前这里拿到的是一个已经全部跑完的列表 —— 于是父代理在等孩子期间零回合
        # （真机 sylow3 的 M 卡了 92 分钟）。现在 `run_plan` 给的是句柄：
        # 秒级能回来的那些照旧写进这一步的 `results`（"汇报 = 返回值"那条契约不动），
        # 还没回来的转成"已派出 / 还在跑" + 一条返场挂账，结果下一次返场投过来。
        by_index: dict[int, Any] = {}
        dispatched: dict[int, str] = {}
        preempted = False
        if isinstance(batch, list):            # 替身 / 旧实现：已经是终局
            for i, r in enumerate(batch):
                by_index[i] = r
        else:
            rec = self._register_child_handle(batch, kind="summon_many", calls=calls)
            # 等"全部落定"或"有时钟唤醒到点"，最多 `child_step_wait_sec`。
            # 走 `_wait_for_children` 而不是 `batch.wait_all`：一条 180 秒的等待
            # 不许压住 D-53 的监控回合（唤醒一到就返场）。
            self._wait_for_children(timeout=float(self.child_step_wait_sec))
            settled_all = bool(batch.done()
                               if callable(getattr(batch, "done", None)) else False)
            taken = getattr(batch, "settled_by_index", None)
            if callable(taken):
                by_index.update(taken())
            for row in batch.dispatched() or ():
                dispatched[int(row.get("index"))] = str(row.get("task_id") or "")
            if settled_all:
                self._forget_child_handle(rec)
            else:
                preempted = True
        probe = getattr(c, "_last_probe", None)
        waves = [len(w) for w in P.waves_of(calls,
                                            limit=getattr(c.policy, "max_concurrency", None))]
        items = []
        for i, call in enumerate(calls):
            r = by_index.get(i)
            if r is None:
                # 还没回来：这一项不是「被拒了」，也不是「失败了」。两档要分开：
                #   · 已经有 `task_id` ⇒ 它在跑（`running`）；
                #   · 还没有编号 ⇒ 它还在排队（分波：前一波没落定，这一波不许开跑）。
                # 折成一档会让「3 个在跑」与「1 个在跑、2 个排队」读成同一件事。
                tid = dispatched.get(i) or ""
                items.append({"role": call.role, "action": call.action,
                              "instance": call.instance,
                              "task_id": tid or None,
                              "status": ("running" if tid else "pending"), "outcome": None,
                              "refusal_reason": None,
                              "detail": ("还在跑：本步先不等（可抢占）；它回来之后"
                                         "结局会在下一次返场时投给你" if tid else
                                         "还在排队（分波：前一波还没落定）⇒ 还没派出去；"
                                         "它会在前一波落定后被派出去，结局同样在返场时投给你")})
                continue
            items.append({"role": call.role, "action": call.action, "instance": call.instance,
                          "task_id": r.task_id, "status": r.status, "outcome": r.outcome,
                          "refusal_reason": r.refusal_reason, "detail": _clip(r.detail, 200)})
        out: dict[str, Any] = {
            "summoned": [f"{i['role']}.{i['action']}" for i in items],
            "count": len(items),
            "ok_count": sum(1 for i in items if i["outcome"] == "ok"),
            "refused_count": sum(1 for i in items if i["outcome"] == "refused"),
            "failed_count": sum(1 for i in items if i["status"] == "failed"),
            "running_count": sum(1 for i in items if i["status"] == "running"),
            "waves": waves, "concurrent_peak": int(getattr(probe, "peak", 0) or 0),
            "results": items,
            "ok": True,
        }
        if preempted:
            # 三件事一起说，缺一件都会让读的人把"还在跑"读成别的：
            # ① 哪几项已经派出去了（编号）；② 哪几项还在跑；③ 结果去哪拿。
            out["preempted"] = True
            out["dispatched"] = [i["task_id"] for i in items if i.get("task_id")]
            out["running"] = [i["task_id"] for i in items
                              if i["status"] == "running" and i.get("task_id")]
            out["how_to_get_the_rest"] = (
                "这一批还没跑完，所以 `results` 里状态为 running 的那几项还没有结局。"
                "它们回来之后，框架会在你下一次被问之前以【子代理返场】投给你"
                "（不必再派一次，也不要因为 status=running 就重试）。"
                "在那之前你仍拿得到回合：可以 watch 全树、guide 给指导、补派新活；"
                "收工（final）会被拒到它们回齐。")
        # ---- 名册登记：读数在这里，写字不在这里（2026-10-21 收口）
        #
        # 唯一的登记点是 `Conductor.summon` 的第 [5b] 步（子行落盘之后、子代理跑起来
        # 之前）。这条路（`run_plan` → `scheduler` → `summon`）改前一个登记点都没有：
        # 生产读数批量步 1006 次、派出 2822 个子代理，名册只登记 413 个；真机
        # `projects/p3-verify` 也是这条路（M 第 9 步的原生工具 `conductor.summon_many`），
        # 名册 0 行。现在每一项目标自己带着 `roster`（`brief` / `task`）交给 `summon`，
        # 这一层只把结果里的读数汇总回返回值：
        #   · `roster_names`：登记上了的那些（顺序与 targets 一致）；
        #   · `roster_problems`：没登记的逐项理由（没秘书 / 秘书拒收 / 没有父编号…）。
        # 老键一字节不动：两格只在有值时才加（"一个都没登记"与"都登记了"分得开）。
        # 一项登记失败不带走整批（`ok` 照旧）—— 这是本文件与秘书两侧共同的口径。
        self._bind_roster_sink()
        names: list[str] = []
        problems: list[str] = []
        for i, call in enumerate(calls):
            r = by_index.get(i)
            if r is None:
                # 还没回来 ⇒ 名册读数也还没回来（登记本身发生在派活的第 [5b] 步，
                # 也就是已经发生了；这里缺的是"登记成了没有"那个读数）。
                continue
            got_name, got_problem = self._roster_reading(
                r, owner=str(self.my_task_id or ""), role=str(call.role),
                task_id=str(getattr(r, "task_id", "") or ""),
                brief=briefs[i] if i < len(briefs) else "",
                task=tasks[i] if i < len(tasks) else "",
                name=str((targets[i] or {}).get("name") or "") if i < len(targets) else "",
                reuse=str((targets[i] or {}).get("reuse") or "") if i < len(targets) else "")
            if got_name:
                names.append(got_name)
            if got_problem:
                problems.append(f"{call.role}：{got_problem}")
        if names:
            out["roster_names"] = names
        if problems:
            out["roster_problems"] = problems
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

    def _statement_filing_tier(self, name: str, args: Mapping[str, Any]) -> dict[str, Any] | None:
        """B 要入库一条命题时，先问它自己的秘书"这条太平凡吗"；判太平凡就落 T0，不再拒收。

        业主 2026-10-23 的裁定（逐字要点）：「B 侧收录命题时被"太平凡"拦截了很多次……
        可以让秘书不再因"太平凡"拦收录，只是加一个档位叫 T0（和 T1 到 T4 是一个性质），
        T0 叫基础定理或初步结论」。业主 2026-10-14 裁决第 12 条前半那句「判断一个待入库的
        命题是否太平凡有没有资格入库」因此换了收场方式：秘书照旧判，判「太平凡」的
        落 T0（基础定理或初步结论）并如实收下 —— 平凡不是"不许进"，是"进哪一档"。

        三件事分开写在这里：
        1. 只在三个条件同时成立时才问秘书：本角色是 B、工具是它这一趟被派的那件入库动作
           （`own.register_statement`）、秘书装配了判断面。三者缺一 ⇒ `None`（什么都不加）。
        2. 秘书没缝 / 开关关着 / 超时 / 坏 JSON ⇒ `checked=False` ⇒ 什么都不加（"没查成"
           不等于"太平凡"，也不等于"合格"；台账里那一行仍会落，见 `judge` 的 `_record_judge`）。
        3. 判了且判「太平凡」⇒ 返回一格读数（不是拒绝）：`tier="T0"`、`downgraded=True`、
           秘书的原话与依据。调用方（`_do_tool`）把它并进这次工具调用的结果，于是
           "这一条进了 T0"在模型与台账上都看得见。

        为什么不再返回拒绝：拒收的代价在真机上量过（2026-10-14 第五趟：同一份 21 字的命题
        被提交 6 次、每次都拿到同一个「太平凡」，一次 run 烧掉 20/26 次调用与 $0.226，
        而 `statements` 仍是 0 行；r34 那一趟 B 的秘书台账里 4 次「太平凡」、收录表 0 行）。
        挡的是"平凡能进表"，代价却是"整条收录链停摆" —— 而业主这一次裁定把这个交换取消了。
        """
        if str(getattr(self, "role", "")) != "B" or str(name) != "own.register_statement":
            return None
        sec = getattr(self, "secretary", None)
        if sec is None or not hasattr(sec, "judge_statement"):
            return None
        try:
            got = sec.judge_statement(
                statement_full=str(args.get("statement_full") or args.get("statement") or ""),
                statement=str(args.get("statement") or ""),
                source=str(args.get("source_lit_id") or args.get("source") or ""),
                task_id=str(getattr(self, "my_task_id", "") or ""),
            )
        except Exception as exc:  # noqa: BLE001 —— 判断炸了不许把入库这条路堵死
            # fail-open（与秘书的失败姿态同一条纪律）："没查成"不决定产出入库。
            # 但也不许静默：往秘书台账补一行，"这一格没查成"必须能从盘上读到。
            try:
                sec.note_decision(
                    duty=0, decision="", fail_open=True,
                    reason=f"入库前的审美判断炸了：{type(exc).__name__}: {exc}",
                    target=str(name), after="照旧入库（fail-open）")
            except Exception:  # noqa: BLE001 —— 连留痕都写不成时不再往上抛（同上）
                pass
            return None
        if not got.get("checked"):
            return None
        from . import secretary as _SEC

        if not _SEC._is_trivial_verdict(got.get("decision")):
            return None
        # 档位读数由秘书台账给（`append_nontriviality` 已经写过一行 T0）：
        # 这里只把它翻成这一步的读数，不另存一份状态。
        return {
            "tier": _SEC.nontriviality_label(0),
            "downgraded": True,
            "decision": str(got.get("decision") or ""),
            "reason": str(got.get("reason") or "")[:300],
            "basis": list(got.get("basis") or []),
            "note": ("平凡 ⇒ 落 T0（基础定理或初步结论），照旧收录（业主 2026-10-23："
                     "秘书不再因「太平凡」拦收录）。想升档就按秘书的理由补一条判据："
                     "① 后面哪一步会用到它（指名道姓）；② 它比收录表里最接近的那一条强在哪"),
            "judged_by": "secretary",
            "judge": "statement_aesthetic",
        }

    def _do_tool(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """执行一步工具调用。

        `draft/37` §52 的真机读数（第四趟）：本岗同时开着原生工具面（`tools` 里有 `fs_list` 这样的函数名 ——
        带点的真名 `fs.list` 不符合 function name 的字符集，广告时被归一化成下划线），而模型仍按文本协议回了
        一行 JSON、把广告名 `fs_list` 写进 `tool` 字段 ⇒ 执行层报 `unknown_tool`，29 步全白花。

        这不是模型的错：它看到的两个名字都是我们给的。所以这一层逐次把广告名映回真名，并在结果里留一句
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
        # ---- 自己的动作按短名叫我（2026-10-19 晚，`projects/mp2` 第 94 行）
        #
        # 真机形态：B 手册里的动作名就是 `register_statement`（`specs/b.py` 的动作表），
        # 而工具面上那一件叫 `own.register_statement`（本仓工具名必须带点）。
        # 于是模型照手册喊短名 ⇒ `unknown_tool`，改走 `table.create` 手写表。
        # 这一格只把短名映到 `own.<短名>`，而那个名字必须已经在这一趟的注册表里
        # （注入按角色/按面发生）⇒ 它不打开任何权限：能映到的工具本来就能调。
        # 认账不静默：`aliased_from` 随结果回给模型，读数上看得见谁在用短名。
        if name not in known and f"own.{raw}" in known:
            name, aliased_from = f"own.{raw}", raw
        args = dict(payload.get("args") or {})
        # ---- B 的入库口：先过秘书那一关（业主 2026-10-14 裁决第 12 条前半 +
        #      2026-10-23 的收场方式：判「太平凡」落 T0，不再拒收）
        #
        # 位置在这一层而不是工具层：这一格要本体自己的缝（`self.secretary`）与
        # `my_task_id`，而工具层两样都没有；而且"这一条落哪一档"必须与别的读数同形
        # （并进这一次工具调用的结果），所以它得在 `registry.call` 之前、同一个返回面上。
        #
        # `name in known` 那一句是必要的（不是防御性写法）：注册表里没有这个名字时
        # 这一步的结果是 `unknown_tool`，而秘书的这一次判断要花一次模型调用 ——
        # 为一次不会发生的入库去问它，等于让"名字写错了"顺手扣一笔钱。
        filing_tier: dict[str, Any] | None = None
        if name in known:
            filing_tier = self._statement_filing_tier(name, args)
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
                # 2026-10-19（业主裁定「父子天然双向」）：除了"我是谁"，还把这一趟的
                # 召唤者与会话身份挂上 —— `conductor.escalate` 要把需求写进父的收件箱，
                # 而父是 `run()` 开头由 `_resolve_parent(...)` 解析出来的那一个
                # （不是工具自己猜的、也不要求在 `edges` 里登记）。
                # 会话身份同样必须现挂：按缺省会话写会把上报丢进一个父不会读的文件。
                with calling_as(str(self.my_task_id or ""), self.role,
                                parent_task_id=str(self.parent_task_id or ""),
                                parent_role=str(self.parent_role or ""),
                                session_root=str(self.session_root or ""),
                                sid=str(self.sid or "")):
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
        # 入库前那一趟判断的档位读数（业主 2026-10-23：平凡 ⇒ 落 T0，不拒收）。
        # 只在这一步真的把那条命题交下去了之后才挂（拒绝 / 没调成时它没有对象可言）。
        if filing_tier:
            out["tier"] = dict(filing_tier)
            out["meta"]["statement_tier"] = dict(filing_tier)
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

        口径（业主 T23）：`fs.*` 的路径参数按工作区根解析（与 `fs_tools` 同一基准），结果必须落在 `self.surface` 里；
        面内的新文件允许（判的是落在哪儿，不是"文件存在不存在"）；没设面（`self.surface == ""`）⇒ 直接放行（老行为不变）
        。三态：面目录不在盘上 ⇒ 拒绝（不许当"整工作区可写"）。
        哪些参数算"路径"：`draft/90` §2 的 E22 —— 先前这里只看 `args["path"]`，而 `fs.move` 的参数叫 `src`/`dst`（没有
        `path`）⇒ 可以用它把面外的文件搬进面、或把面内的搬出去，这一步不被任何判据拦。现在参数名从
        `secretary.surface_path_args()` 取（默认 `path`，例外逐条登记），与 `Secretary.surface_fit` 共用同一张表，免得
        "预看说越界、硬拦放过去"。
        面是工作区里的一个子目录（过渡语义）：`fs.*` 的根焊死在注册表里（`build_registry(workspace_root=…)` 就定死了），
        所以"从面里看 `x.md`"要等每实例一个注册表（`draft/92` §3.6），那是装配点的改动、另立一批。基准已收口（D8 / E23，
        2026-10-10 校）：`host.py` 装配时把 `backend.registry_factory` 接上，子代理那一趟由 `registry_factory(face)`
        按面造注册表（同一个面复用同一个，见 `child_registry`）⇒ 判据的基准与执行的基准终于是同一个目录；判据
        `tests/test_the_surface_is_also_the_tools_root.py`（正控①装配点可调用、正控② `fs` 根 == 面、负控无面时共用注册
        表逐字不变）。没有面时两者都退回老行为（路径要写全、且必须落在面内）。
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

    def _summon_owner(self) -> str:
        """这一笔派活的父的绝对编号（空串 = 这一趟没有台账编号 ⇒ 不许派）。

        口径（2026-10-20，真机 `projects/tree-check` 的 t-000019 那一行孤儿）：
        `tasks.parent_task_id` 是父子关系的唯一权威来源（`draft/104` §2.5），
        所以它不许为空（只有顶趟那一行 `parent=None`，它是树根）。
        号一律取自台账/上下文（`self.my_task_id` 是 `run_role` 开行时拿到的绝对编号；
        conductor 那一侧还会回退到当前调用上下文与本进程顶趟）——这里不拼号。
        """
        own = str(getattr(self, "my_task_id", "") or "").strip()
        if own:
            return own
        look = getattr(self.conductor, "_owner_task_id", None)
        if callable(look):
            try:
                return str(look() or "")
            except Exception:  # noqa: BLE001 —— 读不成按"没有号"处理（下面会拒）
                return ""
        return ""

    def _no_owner_refusal(self, what: str) -> dict[str, Any]:
        """没有父的绝对编号 ⇒ 受控拒绝（不许造一行 `parent_task_id=None` 的子行）。

        改前的形态是 `parent_task_id=self.my_task_id or None`：号一空就落 None，
        于是子代理在台账上是孤儿 —— 名册里没有它、任何父的扇出也不数它、
        `roster_view(scope="descendants")` 走不到它（真机 t-000019 就是这一行）。
        """
        return {"ok": False, "refused": "no_owner", "to": "",
                "error": (f"{what}没有父的绝对编号（这一趟还没落台账）⇒ 不派："
                          "子行不许出现 `parent_task_id=None`"
                          "（`draft/104` §2.5：父子关系的唯一权威来源是台账）"),
                "why": ["这一趟的 `my_task_id` 是空串，且 conductor 那侧也读不到顶趟"]}

    def _bind_roster_sink(self) -> None:
        """把本实例的秘书接成 conductor 的名册写入口（幂等；没秘书就不接）。

        为什么要有这一步（2026-10-21 真机）：登记收口在 `Conductor.summon` 的第 [5b] 步
        （子行落盘之后、子代理跑起来之前），而那一步要一个"写的人"。conductor 自己的
        `secretary` 只在 `run_role` 那一条路上被挂上；工具路径（`conductor.summon` /
        `conductor.summon_many` 这两个原生工具）与 `LlmBackend.call` 起的子循环都不经过
        `run_role` ⇒ 只靠 `conductor.secretary` 会让"谁写名册"取决于装配运气（真机
        `projects/p3-verify` 的名册就是这么空的）。所以每个循环把自己的秘书接上去。

        两条口径：
        1. 先到先得（只在 `roster_sink is None` 时接）：同一个 conductor 会被父与
           所有子循环共用，先接上的那个是"这一棵树的主写入口"，后来者不该把它换掉
           （名册写的是 `owner` + 那几格，换人对盘上结果没有影响，但"谁写的"应当稳定）；
        2. 接不上（老装配 / 只读桩 / 属性只读）⇒ 什么都不做、也不抛 —— 那一态由
           `Conductor._register_roster` 记成一条 problem（"名册不在手上"），不在这里抛。
        """
        cond = getattr(self, "conductor", None)
        sec = getattr(self, "secretary", None)
        if cond is None or sec is None:
            return
        if getattr(cond, "roster_sink", None) is not None:
            return
        try:
            cond.roster_sink = sec
        except Exception:  # noqa: BLE001 - 老装配 / 只读桩：接不上就留 problem，不在这一层抛
            pass

    def _roster_reading(self, res: Any, *, owner: str, role: str, task_id: str,
                        brief: str = "", task: str = "", name: str = "",
                        reuse: str = "") -> tuple[str, str]:
        """从一次派活的结果里读回名册那两格：`(名册名, 问题)`。

        两条路，判据是 `res.roster_considered`（那是第三态，不是布尔）：
        * `True` —— 这次派活走过 `Conductor.summon` 的 [5b] 漏斗 ⇒ 只读数、不写字。
          登记已经发生（或已经带理由地没发生），这一层再调一次 `roster_add` 就会让同一个
          子代理在名册上有两条同名项（`next_name` 按角色序号发号，第二条是 X2）——
          这正是这次改动要钉死的"恰好一次"。
        * `False` —— 这个结果不是 `Conductor.summon` 产出的（判据里的替身、老实现）。
          漏斗没走过 ⇒ 这一层按老口径补一次登记，否则"登记有没有发生"在那类替身上永远
          读不出来（`test_roster_registration_holes` 的批量正控就打在替身上）。
        """
        if getattr(res, "roster_considered", False):
            return (str(getattr(res, "roster_name", "") or ""),
                    str(getattr(res, "roster_problem", "") or ""))
        sec = getattr(self, "secretary", None)
        status = str(getattr(res, "status", "") or "")
        if sec is None:
            return "", "这一趟没有秘书 ⇒ 名册不在手上（没有登记）"
        if status not in ("pending", "running", "done"):
            return "", (f"这次派活没跑成（status={status}）⇒ 名册没登记"
                        "（不是『不需要登记』，也不是『登记过了』）")
        if str(getattr(res, "outcome", "") or "") == "refused":
            return "", ""            # 被拒的那一次没跑：不登记（理由在 refusal_reason 上）
        try:
            reg = sec.roster_add(owner=owner, role=role, task_id=task_id, brief=brief,
                                 task=task, want_name=name, reuse=reuse)
        except Exception as exc:  # noqa: BLE001 —— 登记失败不许带走这次派活
            return "", f"名册登记没跑成：{type(exc).__name__}: {exc}"
        problem = str(reg.get("problem") or "")
        return ("" if problem else str(reg.get("name") or "")), problem

    def _do_summon(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        role = str(payload.get("role"))
        # 2026-10-16（口径 S2 最终形态）：「完全不要有填 action 的位置」——
        # 形状里没有 `action` 这一格，这里也就不读它、不持有它；派活只有 `role` + `task`。
        # 下面调 `conductor.summon` 时那个 `""` 是内部 API 的实参，不是留给模型的位置。
        # 名册那三格要在这一步的载荷被结果覆盖之前取下来（S1k-3 的判据当场抓出来的坑：
        # 下面 `payload = res.payload` 之后 `payload.get("brief")` 读的是结果，
        # 于是每一次名册登记都变成"没给简介"）。
        brief_arg = str(payload.get("brief") or "")
        name_arg = str(payload.get("name") or "")
        reuse_arg = str(payload.get("reuse") or "")
        out: dict[str, Any] = {"summoned": role, "action": ""}   # 派活不点动作（S2 最终形态）
        if self.conductor is None:
            out.update(ok=False, error="本次运行没有接线主控（summon 不可用）")
            return out
        if self.token is not None and getattr(self.token, "cancelled", False):
            out.update(ok=False, error="取消信号已置位：不再发起新的召唤")
            return out
        # 这里此前构造 `budget = {"usd": 剩余}` 传给 `conductor.summon` ——
        # 那是一个哑闸（2026-10-15 裁定 B2 的同一族）：
        # `_meter_guard` 读的键是 `max_usd`，`"usd"` 这个键从来没被任何判据读过；
        # 而且就算键对了，它当时的意思是"拿这个数去和全局已花比"，
        # 与"这一单最多花多少"毫无关系。钱的判据只有一处（`_meter_guard` →
        # 全局账 vs 全局预算），循环这一层不再自己造一个假的每单限额。
        params = dict(payload.get("params") or {})
        # 2026-10-16（S2「M 只派活」）：不点动作时，那件活就是参数 —— 把它转给
        # 后端（`LlmBackend` 要用它当这一趟循环的任务文本，见 `_task_text`）。
        # 为什么不塞进 `params` 的语义里而是单独取一格：`params` 是"动作的参数"，
        # 而这里根本没有动作；混在一起会让记录里出现"一个不存在的动作的参数"。
        task_arg = str(payload.get("task") or "")
        # 2026-10-16（口径 S2）：`task` 一律必填（业主："一致改成 task 必填，action 不填"）。
        if not task_arg.strip():
            out.update(ok=False, error="派活必须写清是什么活：`task` 必填"
                                       "（否则接活的人不知道自己该干什么）")
            return out
        params["task"] = task_arg
        # `input_key` 由形状给不出（形状里没有这个字段）⇒ 按同一件事派生一个确定性键，
        # 否则这一行落库时键为空、`verify_tasks` 会报 `task_without_input_key`
        # （真机实测：场景 G 的 t-0252）。模型若显式给了就用它给的。
        key = str(payload.get("input_key") or "") or _summon_key("", params)
        # 父的绝对编号（2026-10-20）：空 ⇒ 受控拒绝，不许落一行孤儿（见 `_summon_owner`）。
        owner = self._summon_owner()
        if not owner:
            out.update(self._no_owner_refusal(f"把「{task_arg[:40]}」派给 {role}："))
            return out
        try:
            if PREEMPTIBLE_DISPATCH and not _patched_on_instance(self.conductor, "summon"):
                # ---- 可抢占（D-64）：派完就拿到句柄，只在本步里等一小段
                handle = self.conductor.summon_preemptible(
                    role, "", params,
                    by=self.role, parent_task_id=owner,
                    token=self.token, input_key=key,
                    # 名册登记的材料（登记发生在 `summon_begin` 的 [5b]：
                    # 子行落盘之后、子代理跑起来之前）。
                    roster={"brief": brief_arg, "task": task_arg,
                            "name": name_arg, "reuse": reuse_arg})
                rec = self._register_child_handle(handle, kind="summon", calls=[])
                # 等"它回来"或"有时钟唤醒到点"，最多 `child_step_wait_sec`。
                # 走 `_wait_for_children` 而不是 `handle.wait`：一条 180 秒的等待
                # 不许压住 D-53 的监控回合（唤醒一到就返场）。
                self._wait_for_children(timeout=float(self.child_step_wait_sec))
                if not handle.done():
                    # 还没回来：把"已派出 / 还在跑"如实交回，并挂一条返场账。
                    # ok 仍是 True —— 派活这件事真的发生了（有一行 running、有编号）；
                    # 它有没有干成由 status/outcome 说，而这两格现在说的是"还在跑"。
                    tid = getattr(handle, "task_id", None)
                    out.update(ok=True, task_id=tid, status="running", outcome=None,
                               refusal_reason=None, preemptible=True,
                               dispatched=[tid] if tid else [],
                               running=[tid] if tid else [],
                               detail=("还在跑：本步先不等（可抢占）。它回来之后结论会在"
                                       "你下一次被问之前以【子代理返场】投给你 —— "
                                       "不要因为 status=running 就重派；收工会被拒到它回齐"))
                    return out
                # 回来了：结果照旧写进这一步的返回值（"汇报 = 返回值"那条契约），
                # 挂账摘掉（否则返场点会把它再投一次）。
                got = self._take_child_results(rec) or [handle.result()]
                self._forget_child_handle(rec)
                res = got[0]
            else:
                res = self.conductor.summon(role, "", params,
                                            by=self.role, parent_task_id=owner,
                                            token=self.token, input_key=key,
                                            # 名册登记的材料（登记发生在 `Conductor.summon`
                                            # 的 [5b]：子行落盘之后、子代理跑起来之前）。
                                            roster={"brief": brief_arg, "task": task_arg,
                                                    "name": name_arg, "reuse": reuse_arg})
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
            out["relay_requested"] = self._request_relay(role, "", payload,
                                                         str(res.refusal_reason or ""),
                                                         str(res.detail or ""))
        if path:
            # 伙伴是 LLM 循环驱动的：它的完整产出在磁盘上，这里只给路径 + 一段结论。
            out["llm_run_path"] = path
            out["final"] = _clip(payload.get("final") or "", 600)
            out["payload"] = _clip({k: v for k, v in payload.items() if k != "llm_run"}, 400)
        else:
            out["payload"] = _clip(payload, 800)
        # ---- 名册：写字在 `Conductor.summon` 的 [5b]，这里只把材料交过去、读数读回来
        #
        # 材料（2026-10-21）：`brief` / `task` / `name` / `reuse` 四格随 `roster=` 进漏斗。
        # 为什么不从 `tasks` 行读：`schema.Task` 里没有 `brief` / `task` 两格（禁改区），
        # 而"父给的那句简介"只活在这个载荷里 —— 改前那版在途实现从行里读 ⇒ 恒空 ⇒
        # 秘书用"没给一句任务简介"拒收每一条（名册照样空）。
        # 口径（2026-10-20 业主裁定逐字：「简介没写，则秘书帮忙写」）：`brief` 只原样传，
        # `task` 一并给秘书（`roster_add(task=…)`）；这里刻意不写 `brief_arg or task_arg`
        # —— 业主选的是"秘书写"，不是"拿任务原文顶替"（代写与留痕都在秘书那一侧）。
        # 读数（`_roster_reading`）：走过漏斗就只读 `res.roster_*`，不再自己调 `roster_add`
        # —— 同一子代理登记两次会让名册里出现两条同名项（X1 与 X2）。
        self._bind_roster_sink()
        got_name, got_problem = self._roster_reading(
            res, owner=str(self.my_task_id or ""), role=role,
            task_id=str(res.task_id or ""), brief=brief_arg, task=task_arg,
            name=name_arg, reuse=reuse_arg)
        if got_name:
            out["roster_name"] = got_name
        if got_problem:
            out["roster_problem"] = got_problem
        return out

    def _needs_relay(self, role: str, reason: str) -> bool:
        """这次拒绝该不该转成"请主控代唤"。

        两档要转：`forbidden_edge` / `depth_exceeded`（这条路今天不通，而重试不会让它通）；以及
        `invalid_params` 且目标不在我的伙伴表里 —— 我看不到他的动作表，所以我给的参数必然是在猜，而
        `Conductor.summon` 的顺序是"先查参数、再查边"⇒ 我会拿到 `invalid_params`，真相却是"我根本不该直接找
        他"。把这一档也算进来，代唤才不会因为"参数猜错"而永远发不出去（本轮实测：第一次写这条判据时，真实场
        景恰恰落在这档上）。

        反过来，目标在我能唤起的伙伴里时 `invalid_params` 就只是"参数写错了"：该由模型自己改参数，不该占用主
        控的注意力。
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
        # ---- 名册（业主 2026-10-19）：请代唤也是"代理发给代理"。
        # 收件人通常是直接父（名册内），顶层才落回主控 M（`outside_roster`：名册上
        # 没有 M 的上级）。按父的绝对编号寻址：角色名在同名多实例时是歧义的，
        # 而歧义在这里的代价是"这条申请投给了别人的父"。
        _addr, _gate = self._roster_gate(
            to_role,
            to_task_id=(str(self.parent_task_id or "")
                        if str(to_role) == str(self.parent_role or "") else ""))
        if _gate:
            # 一行留言都不发（受控拒绝），但"申请发生过"仍要留痕：它是这一趟的实际行为。
            SS.append(self.session_root, {
                "kind": "agent_summon_request", "role": self.role, "wants_role": role,
                "wants_action": action, "params": asked, "refusal_reason": reason,
                "message_id": "", "relay_to": to_role, "relay_why": whose,
                "refused": _gate["refused"], "problem": _gate["error"],
            }, sid=self.sid)
            return {"to": to_role, "subject": RELAY_SUBJECT, "message_id": "",
                    "problem": _gate["error"], "refused": _gate["refused"],
                    "addressing": _addr,
                    "note": ("受控拒绝：这一条没有写进任何收件箱"
                             "（名册上只有父与子能通话）")}
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
        # `from_task_id`（业主 2026-10-21「全面接入」第二步）：这条留言也是"某个
        # 编号的某一岗在说话"，与别处那三条 `send_message` 同一口径（`_do_message` /
        # `_do_handoff` / 收工 `notify` 都带）。漏了它的后果只在线上一格可见：
        # `readers._chat_line` 给这条线判 `missing`，而说话的人自己有绝对编号。
        msg_id, problem = send_message(self.session_root, sender=self.role, to=to_role,
                                       subject=RELAY_SUBJECT, body=body, sid=self.sid,
                                       from_task_id=str(self.my_task_id or ""))
        rec: dict[str, Any] = {"kind": "agent_summon_request", "role": self.role,
                               "wants_role": role, "wants_action": action, "params": asked,
                               "refusal_reason": reason, "message_id": msg_id,
                               "relay_to": to_role, "relay_why": whose}
        if problem:
            rec["problem"] = problem
        SS.append(self.session_root, rec, sid=self.sid)
        return {"to": to_role, "subject": RELAY_SUBJECT, "message_id": msg_id,
                "problem": problem, "addressing": _addr,
                "note": (f"越权的边不会因为重试而成立 ⇒ 已向 {to_role} 申请代唤（{whose}）；"
                         "不要把这条申请当成'对方已经在做'。")}

    def ask_parent_for_definitions(self, pending: Sequence[Mapping[str, Any]], *,
                                   escalate: bool = False, stuck: str = "") -> dict[str, Any]:
        """定义抽不到时的向上报文（`draft/97` §15.4 的载体那一半）。

        业主逐字：「最常见的定义不明极可能是A查论文要B消化时遇到生僻定义，这时和父代理A交流即可」⇒ 补法优先
        级定死：①问直接父（原文在它手里）→ ②A 上网搜（`pending_search`）→ ③B 自撰（`self_authored`，只对基本
        概念）。这一格做①，以及"父也办不了 ⇒ 才向上爬到 M，并逐级留痕"（`escalate=True` + `stuck` 写明哪一级
        卡住、为什么）；它不替父做判断，所以"爬上去"必须由调用方显式传。

        三态（要能分辨"没问"与"问了"）：`pending` 空 ⇒
        `{"checked": False, "reason": "没有待补定义 ⇒ 没有发报文"}`（一条留言都不落）；报文落了 ⇒
        `{"checked": True, "to": …, "message_id": …, "ask_why": …}`；落不成 ⇒ `checked=True` + `problem`（报
        文那一格没成要说出来，不许当成已发出）。
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
        # ---- 名册（业主 2026-10-19）：定义报文也是"代理发给代理"，与 `message`
        # 同一判据（直接父 = 名册内的父，爬到 M = `outside_roster`）。
        _addr, _gate = self._roster_gate(
            to_role,
            to_task_id=(str(self.parent_task_id or "")
                        if str(to_role) == str(self.parent_role or "") else ""))
        if _gate:
            return {"checked": True, "to": to_role, "subject": DEFINITION_ASK_SUBJECT,
                    "message_id": "", "ask_why": whose, "concepts": [],
                    "escalated": bool(escalate), "refused": _gate["refused"],
                    "problem": _gate["error"], "addressing": _addr}
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
                                       sid=self.sid,
                                       # 同上一条申请报文：谁的编号在说话，事件里就要有它。
                                       from_task_id=str(self.my_task_id or ""))
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
                               "escalated": bool(escalate), "addressing": _addr}
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

    def _address_of(self, to: str) -> dict[str, Any]:
        """这一条该发给谁（「名册 ⊆ 通话面」）：把 `roster_addresses` 接到本实例的上下文上。

        fail-closed（2026-10-22 按业主口径改的）：名册读坏 / 寻址那一格自己抛异常 ⇒ 与
        「没有秘书 / 没有台账号」同一档 —— 读数标 `roster_unavailable` 并给出 `refused`，
        私聊因此受控拒绝。改前这里是 fail-open（"说话不该被一次读失败挡住"），代价是
        「读不出名册」等于「不校验名册」，而名册规则的收紧方向恰好相反。读数仍然照旧可见：
        `how="roster_unavailable"` 与 `why` 说明为什么没读成 —— 折成"解析成功"才是本仓最忌的
        那种静默错（业主 2026-10-19 第 ⑦ 条要的就是这一格）。
        """
        try:
            return roster_addresses(self.secretary, to=to,
                                    owner=str(self.my_task_id or ""),
                                    my_task_id=str(self.my_task_id or ""),
                                    sender=str(self.role or ""))
        except Exception as exc:  # noqa: BLE001 —— 判据自己坏了也是"没查成"
            return {"to": str(to or ""), "checked": False, "how": "roster_unavailable",
                    "kind": "", "name": "", "task_id": "", "role": "", "brief": "",
                    "candidates": [], "callable": "", "refused": "roster_unavailable",
                    "error": (f"名册寻址没跑成（{type(exc).__name__}: {exc}）"
                              f"⇒ {_ROSTER_UNAVAILABLE_REFUSAL}"),
                    "why": (f"名册寻址没跑成（{type(exc).__name__}: {exc}）"
                            "⇒ 私聊不投递（这不是'名册校验通过'）")}

    def _handoff_address(self, to: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """交接手稿的收件人（`handoff` / 收工 `notify` 共用）：`(addr, gate)`。

        为什么不能照抄 `message` 那一格：手稿通道的收件人面本来就是角色（`manuscripts/handoffs.jsonl` 的 `to` 是角色或
        `ALL`：`handoff_query(to=…)` / `manuscripts.read` 的过滤都按它），名册上没有"手稿收件人"这个地址面（
        `secretary.handoff_add` 写的时候就把非角色收件人拒掉：`ValueError: 收件人必须是 [A…M, V] 之一`）。
        | `to` 的写法 | 判据 |
        |---|---|
        | 名册名 / 绝对编号（解析成父或子） | 手稿写它的角色，通知投那个实例的板项 |
        | 角色名 | 手稿写那个角色；通知按协作边准入（`message_admission`） |
        | 角色名 = 我自己 | 自记一笔（不是代理之间的通信）⇒ 放行 |
        | `ALL` / `#public` / 用户 / 主控 | `outside_roster`（公告栏与频道外读者，不归名册管） |
        | 解析不到的名册名 / 编号 | 受控拒绝 `handoff_is_role_addressed`（台账没有实例地址面） |
        为什么角色名那一档用协作边而不是名册：`notify`（每个终态都要有）正是靠它把"手稿编号 + 一句话"交给下一个角色；
        按名册拒掉会把整条交付链掐死，而"按角色名随便发"由协作边那份判据（`_address_of` / `message_admission`）守着。
        这一档也不是"名册校验通过"：读数里 `how="outside_roster"`，且 `delivery="role"`。

        成功的那几支一律经 `delivery_addressing`：名册探针的 `refused` / `error` 不进
        `addressing`（挪进 `roster_probe`）—— 缺陷 1 就是这一支把"B 不在你的名册里 ⇒ 受控拒绝"
        与 `ok=true` 留在同一个字典里。失败那几支不经过它：那两条拒信本来就该带着理由码。
        """
        token = str(to or "").strip()
        base: dict[str, Any] = {"checked": True, "how": "", "to": token, "kind": "",
                                "name": "", "task_id": "", "role": "", "brief": "",
                                "candidates": [], "callable": "", "refused": "",
                                "error": "", "why": "", "delivery": "role",
                                "manuscript_to": token}
        if (not token or _is_all_recipient(token) or token in ("user", "用户")
                or token == S.CONDUCTOR_ROLE):
            return {**base, "how": "outside_roster",
                    "why": "角色级/公告栏/频道外的收件人面（手稿台账按它建键）"}, {}
        addr = self._address_of(token)
        how = str(addr.get("how") or "")
        probe_refused = str(addr.get("refused") or "")
        if how in ("parent", "child"):
            role = str(addr.get("role") or "")
            if not role:
                return {**delivery_addressing(base, addr), "how": "roster_unavailable",
                        "why": "名册成员的角色读不出来 ⇒ 手稿那一行没有收件人面"}, {}
            return {**delivery_addressing(base, addr), "delivery": "roster",
                    "manuscript_to": role,
                    "why": f"名册成员（{how}）⇒ 手稿写角色 {role}，通知投实例 {token}"}, {}
        if str(token).upper() in S.ROLES:
            role = str(token).upper()
            if role == str(self.role or "").upper():
                return {**delivery_addressing(base, addr), "how": "outside_roster",
                        "manuscript_to": role,
                        "why": "交接给'我自己'是自记一笔（不是代理之间的通信）"}, {}
            reason = message_admission(self.role, role)
            if reason:
                gate = {"refused": "not_an_edge", "error": f"交接给 {role} 不成立：{reason}",
                        "addressing": {**base, **addr, "how": "not_an_edge",
                                       "manuscript_to": role}}
                return {**base, **addr, "how": "not_an_edge", "manuscript_to": role}, gate
            return {**delivery_addressing(base, addr), "how": "outside_roster",
                    "manuscript_to": role,
                    "why": ("角色级收件人面（手稿台账的口径）+ 协作边成立"
                            + (f"；名册上没有 {role}（{probe_refused}）⇒ 这一条按角色投，"
                               "不靠名册（名册探针的读数见 roster_probe）"
                               if probe_refused else ""))}, {}
        if how == "roster_unavailable":
            # 名册不可用 ⇒ 不回退成"按名字发"（那会写进一个没人读的收件箱），
            # 也不把一次读失败说成"这个名字不存在"：让调用方按三态处理。角色级那一档
            # 在上面已经放行了 —— 手稿通道不靠名册（这是业主 2026-10-22 明确保留的那条）。
            return {**delivery_addressing(base, addr), "how": "roster_unavailable"}, {}
        gate = {"refused": "handoff_is_role_addressed",
                "error": (f"手稿的收件人只认角色或 ALL（台账的主键面），收到 {token!r} ⇒ 受控拒绝："
                          "要给**某个实例**说话请用 `message`（`to` 写名册名或绝对编号）；"
                          "要把手稿交给一个角色，`to` 写角色名。"),
                "addressing": {**base, **addr, "how": "handoff_is_role_addressed"}}
        return {**base, **addr, "how": "handoff_is_role_addressed"}, gate

    def _roster_gate(self, to: str, *, to_task_id: str = ""
                     ) -> tuple[dict[str, Any], dict[str, Any]]:
        """「这一条要发给谁」的唯一判据 —— 给 `message` 之外那几条通道共用。

        业主 2026-10-19：「代理之间的通信必须经名册（父 ＋ 直接子 ＋ 绝对编号）」。`_do_message` 走的是
        `_address_of`（由另一条线负责）；而 `handoff` / 请代唤 / 定义报文 / 步数上报这四条也是代理发给代理，
        它们此前直接调 `send_message`（按角色名写进角色级收件箱）⇒ 绕开了名册。这一格把它们接到同一份判据上
        （`roster_addresses`，不是第二份实现）。

        返回 `(addr, gate)`：`gate` 为空 dict = 放行；非空 = 受控拒绝那三格（`refused` / `error` /
        `addressing`）。三态照旧：`roster_unavailable`（名册读不成）不是「这一条投给谁」的拒绝，也
        「不是」"名册校验通过"。`to_task_id` 给了就按绝对编号寻址（同名多实例时不会歧义）。

        2026-10-22（fail-closed 的边界）：名册不可用时这几条通道照旧放行 —— 请代唤 / 定义报文 /
        步数上报的收件人是运行期解析出来的父（结构上只有那一个），手稿的角色级收件人靠协作边；
        它们不靠名册挑人，掐死它们等于把整条通信一起停掉（业主明说保留）。私聊那一档才受控拒绝
        （`_do_message` 只看 `refused`）。放行时读数经 `delivery_addressing` 收拾过：
        `refused` / `error` 挪进 `roster_probe`，成功的一步里不许留着「被拒」。
        """
        addr = self._address_of(str(to_task_id or to))
        if str(addr.get("refused") or "") == "roster_unavailable":
            return delivery_addressing({}, addr), {}
        if str(addr.get("refused") or "") and str(to_task_id or "") \
                and str(to_task_id) != str(to):
            # 绝对编号没落在名册上 ⇒ 退回按「写法本身」再判一次（三态：这一步不吞问题）。
            # 为什么必须有这一步：收件人是主控 M（顶层那一档）时，调用方手里那个
            # `parent_task_id` 指的其实是"这一趟自己那一行"，拿它去寻址只会得到一个假的
            # `not_in_roster` —— 真机上就是"请代唤"发不出去
            # （判据 `test_agent_loop.py::test_a_forbidden_edge_becomes_a_relay_request_to_the_conductor`）。
            alt = self._address_of(str(to))
            if not str(alt.get("refused") or ""):
                addr = alt
        if not str(addr.get("refused") or ""):
            return addr, {}
        return addr, {"refused": str(addr.get("refused") or ""),
                      "error": str(addr.get("error") or ""),
                      "addressing": addr,
                      "candidates": [str(x) for x in (addr.get("candidates") or [])]}

    def _all_recipient_refusal(self, to: str = "ALL") -> dict[str, Any]:
        """`to="ALL"` 走到内部直调那一支时的受控拒绝（那个按名册逐项开板项的旧实现已删）。

        为什么是拒绝而不是补回那个方法：广播的语义今天由 `conductor.broadcast`（名下直接子代理，每人一条
        ack 板项）与 `public_visibility`（公共频道的可见面）承担；`to="ALL"` 在解码层已经归一成 `#public`（
        `_decode_shape` → `_recipient_for_channel`）⇒ 能走到这里只剩内部直调。改前这两支各调一次一个全仓没有
        def 的方法 ⇒ `AttributeError`："没发出去"看起来像"框架坏了"，而它不是一种可处置的拒绝。补回那个方法
        更糟：它会把"按角色名逐项展开"的老语义复活，与 `conductor.broadcast` 分叉。

        所以这里如实拒：理由码 `broadcast_only` + 一句话指路（拒信里带工具名）。
        """
        return {"message": "未发出", "to": str(to or "ALL"), "ok": False,
                "receipt": "unknown", "refused": "broadcast_only",
                "error": ("给名下子代理广播用 `conductor.broadcast`；"
                          "`to=\"ALL\"` 在解码层已归一成 `#public`"),
                "note": ("这一条受控拒绝：那个按名册逐项开板项的旧实现已删（语义由 "
                         "`conductor.broadcast` 与 `public_visibility` 承担）⇒ "
                         "一条都没发、一个板项都没开（受控拒绝不是「稍后再试」）")}

    def _message_legacy(self, payload: Mapping[str, Any], to: str,
                        reply_to: str) -> dict[str, Any]:
        """按名字发的那条老路（`_do_message` 已不再回退到这里：名册不可用是受控拒绝）。

        改前它是"名册读不成"那一档的回退 —— 2026-10-22 按业主口径改成 fail-closed 之后，
        那一档不再投放（见 `roster_addresses` 的 `roster_unavailable`）。函数与它逐字保留
        旧行为，因为「回退必须是逐字的老行为」这条纪律仍然成立：判据要能拿它对照
        （`tests/test_roster_registration_holes.py` 直接打它，量 `to="ALL"` 那一支）。
        """
        if to and to != PUBLIC and to != "ALL" and to not in (*S.ROLES, S.CONDUCTOR_ROLE,
                                                             "user", "用户"):
            return self._message_by_name(payload, to)
        if to == "ALL" and self.secretary is not None and str(self.my_task_id or ""):
            return self._all_recipient_refusal(to)
        return self._message_by_channel(payload, to, reply_to)

    def _do_message(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """`message` 形状的寻址与投递（业主 2026-10-19：「只有名册上的编号能通话」）。

        2026-10-22（业主「按编号沟通」）：`to` 由解码层按名册名 / 绝对编号解析过时
        （payload 带 `roster_addressing`，见 `_decode_shape` 的 `message` 那一支），
        `to` 已经是那个成员的角色、原写法留在 `roster_addressing["written"]` 里。
        这一档「按原写法再问一次名册」（同一份判据、同一份上下文 ⇒ 读数就是那条地址的
        读数），然后投角色收件箱：收件箱是按角色收的，把 `B1` 原样当 `to` 写进去
        会得到一条没有任何进程读得到的留言。读数仍然带 `how=parent/child`
        （名册判据通过），所以"按名册名发的角色留言"在盘上看得出来是哪一种落点。

        这一档的判据链与"按角色名发"逐字相同（先协作边、再回执）：`to` 已经是收件箱
        认得的角色，闸门就是那道闸。名册只回答"这个写法是哪个角色"，不另开一条投递
        通道 —— 两种落点（角色收件箱 / 实例板项）的区别在读数上看得见：
        `addressing.how` 都是 parent/child（名册判据通过），而这一档的 `channel`
        是角色通道。`via_roster` 只认那一次现读的名册：payload 里的 `written` 只是
        "原写法"的指针，它自称的东西不算数。

        D-63（2026-10-24 业主：「现在怎么还有to谁的写法？已经是名册机制了！」）：
        收件人的三种写法各有各的处置，判据仍然只有 `roster_addresses` 那一处，
        这一层只读它的结论：

        1. 名册名或绝对编号 ⇒ 只投那个成员（读数 `addressed_by=roster_name` / `task_id`）；
        2. 角色代号、而该角色在册恰好一个 ⇒ 兼容解析到那一个（读数
           `addressed_by=role_fallback`），不因为"写法旧"就拒掉；
        3. 角色代号、而该角色在册多个 ⇒ 受控拒绝 `ambiguous_in_roster` 并点名那几个
           名册名（拒信里给改写法）；在册 0 个 ⇒ 受控拒绝 `not_in_roster` 并列出
           "你能通话的是"。两档都不许静默挑一个、也不许静默丢弃。
        """
        to = str(payload.get("to"))
        reply_to = str(payload.get("reply_to") or "")
        marker = payload.get("roster_addressing")
        written = str(marker.get("written") or "") if isinstance(marker, Mapping) else ""
        # ---- 寻址：先问名册
        #
        # 改前这里是"`to` 像不像角色名"的字符串启发式：不在 `S.ROLES` 里就当名册名。
        # 那个启发式把名册「绕开」了 —— 角色名那一条路从不问名册，于是
        # ①名册名在发消息这条路上用不上、②同名多实例时行为未定义（谁都能读到）、
        # ③退役的名字仍可被寻址。现在判据只有一处（`roster_addresses`），
        # 而"发给谁"的结论进读数 `addressing`（三态：读成了 / 不在名册 / 读不成）。
        addr = self._address_of(written or to)
        how = str(addr.get("how") or "")
        via_roster = (bool(written) and how in ("parent", "child")
                      and str(addr.get("role") or "") == to)
        if written and not via_roster:
            # 原写法没有解析成 `to` 这个角色（载荷被改过 / 名册在两步之间变了）⇒
            # 按 `to` 重新问一次名册：不拿一个对不上的地址去投递。
            addr = self._address_of(to)
            how = str(addr.get("how") or "")
        # 权限先于路由（业主 2026-10-19 之后仍然如此）：`to` 写成「角色名」时，
        # 那句拒信必须先说"没有协作边"，而不是"你要发给谁" —— 否则同一个越权会被
        # 读成一次寻址问题，而准入判据的唯一实现仍只有 `message_admission` 那一份。
        # 名册名 / 绝对编号不被解码层翻成角色之前不吃这一条（`_message_to_member`
        # 那条实例板项的路）；翻成角色之后它走的就是角色通道，与按角色名发同一条闸。
        if to.upper() in S.ROLES:
            not_allowed = message_admission(self.role, to, reply_to)
            if not_allowed:
                return {"message": "未发出", "to": to, "ok": False,
                        "error": not_allowed, "addressing": addr}
        refused = str(addr.get("refused") or "")
        if refused:
            return {"message": "未发出", "to": to, "ok": False, "receipt": "unknown",
                    "refused": refused,
                    "candidates": [str(x) for x in (addr.get("candidates") or [])],
                    "addressing": addr, "error": str(addr.get("error") or ""),
                    "note": (f"{addr.get('error')}（这一条没有落盘：`send_message` 没调、"
                             "板项没开 —— 受控拒绝不是「稍后再试」）")}
        # 名册不可用那一档不再有回退（2026-10-22 按业主口径从 fail-open 改成 fail-closed）：
        # 它由上面那条 `refused` 拦下（`roster_addresses` / `_address_of` 给的是
        # `refused="roster_unavailable"`）。改前这里有一支 `_message_legacy` 的回退 ——
        # 那句"说话不该被一次读失败挡住"在私聊上恰好是"不校验名册"，而名册规则的方向是收紧：
        # 已经有双边通话（父/子）、上行与手稿角色级通道，私聊没有非开不可的场合。
        if how in ("parent", "child") and via_roster:
            # 名册名 / 绝对编号已翻成角色 ⇒ 落角色收件箱（见本方法 docstring）。
            out = self._message_by_channel(payload, to, reply_to)
        elif how in ("parent", "child"):
            # 名册成员 ⇒ 落成"挂在收件人名下的板项"（只有它自己读得到，父不代读 T20）
            out = self._message_to_member(payload, addr)
        elif to == "ALL" and self.secretary is not None and str(self.my_task_id or ""):
            out = self._all_recipient_refusal(to)
        else:
            # `#public` / 用户 / `ALL`（没有秘书那一档）：原来的通道逐字不动
            out = self._message_by_channel(payload, to, reply_to)
        out["addressing"] = addr
        return out

    def _message_to_member(self, payload: Mapping[str, Any],
                           addr: Mapping[str, Any]) -> dict[str, Any]:
        """投给名册上的一个成员（父或子）—— 落到它名下的一条板项。

        与 `_message_by_name` 的区别只有一处：这里「不再自己译码」 —— 名字 / 绝对编号 /
        角色名的解析已经在 `roster_addresses` 里做过，重复译码会让"判据说发给 A、实际
        投给 B"这种事在两条实现之间漂（本仓反复记过的同一种病）。
        """
        tid = str(addr.get("task_id") or "")
        name = str(addr.get("name") or tid)
        kind = str(addr.get("kind") or "")
        return self._deliver_to_instance(
            payload, name=name, tid=tid, role=str(addr.get("role") or ""),
            direction="上行" if kind == "parent" else "下行",
            how=f"名册成员（{kind}）")

    def _deliver_to_instance(self, payload: Mapping[str, Any], *, name: str, tid: str,
                             role: str, direction: str, how: str) -> dict[str, Any]:
        """往某个「实例」的板上开一条 `message` 项（唯一的投递实现）。"""
        if self.conductor is None:
            return {"message": "未发出", "to": name, "ok": False, "receipt": "unknown",
                    "note": "这一趟没有 conductor ⇒ 开不了收件人名下的板项（不是'已送到'）"}
        try:
            row = self.conductor._task(tid) or {}
        except Exception as exc:  # noqa: BLE001 —— 读不成要如实说，不许当"没有这一行"
            return {"message": "未发出", "to": name, "ok": False, "receipt": "unknown",
                    "note": f"台账里那一行读不成（{type(exc).__name__}: {exc}）⇒ 没投"}
        role = role or str(row.get("role") or "")
        subject = str(payload.get("subject") or "")
        body = str(payload.get("body") or "")
        item_id = self.conductor.open_item(
            kind="message", role=role or S.CONDUCTOR_ROLE, expects="ack", action="message",
            summary=subject or f"来自 {self.role} 的一条留言",
            called_by=self.role, parent_task_id=tid,
            depth=int(row.get("depth") or 1) + 1 if row else 2,
            input_key=f"message@{self.role}:{self.my_task_id or '-'}->{tid}")
        self.conductor.set_item_detail(item_id, (subject + "\n" + body).strip()[:400])
        return {"message": "已投递到收件人的板", "to": name, "to_task_id": tid,
                "item_id": item_id, "direction": direction, "channel": "roster",
                "receipt": "queued", "ok": True, "how": how,
                "note": ("这一条挂在收件人名下（板项），只有它自己会渲染到 —— "
                         "父不许代读（T20）。若它此刻没有在跑，板项会等着它下次进循环。")}

    def _message_by_name(self, payload: Mapping[str, Any], name: str) -> dict[str, Any]:
        """按名册名发一条（译码 → 落到收件人名下的板项）。

        `_do_message` 不走这里（判据在 `roster_addresses`）；它今天只有两个调用点：
        `_message_legacy`（判据拿来逐字对照旧行为的那条路）与判据文件对这条实现本身的
        直接调用（`tests/test_the_name_face_is_wired.py`）。`to="ALL"` 的内部直调已改成
        受控拒绝（见 `_all_recipient_refusal`，那个按名册逐项开板项的旧实现已删，
        语义由 `conductor.broadcast` 承担）。
        """
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
        return self._deliver_to_instance(
            payload, name=name, tid=str(tid), role="", direction=direction,
            how="名册名（回退路）")

    def _message_by_channel(self, payload: Mapping[str, Any], to: str,
                            reply_to: str) -> dict[str, Any]:
        """`#public` / 用户 / `ALL` 那一档：留言落 `send_message`（append-only），准入逐字不动。

        S6-a（业主 T20/T21 附二 乙）：公共频道的可见面 = 发信人的直接子代理 ⇒ 发公聊必须带发信人的实例号，没有编号就受
        控拒绝（不许退回"全角色可见"—— 那正是 T20 要治的形态：随手 `to=#public` 就等于全树广播）。谁能走到这一支：只有
        `#public` / `ALL` / 用户（以及名册名已翻成角色的 `via_roster` 那一档）；给某个代理的私聊走 `roster_addresses` +
        `_message_to_member`。名册不可用那一档已经不再回退到这里（2026-10-22：fail-closed，私聊受控拒绝）。
        这一支刻意不加名册校验：公共频道不是"给某个代理发消息" —— 它有自己的可见面判据（我名下的直接子代理）。
        公告栏（业主 2026-10-19 第 5 条："若保留，必须写成公告栏，不是对话"）：`#public` 保留，但它是公告栏—— 一条公聊
        里若点名了名册上的某个成员（名册名 / 绝对编号）并且带指令语气（`PUBLIC_DIRECTIVE_MARKS`）或显式收件人写法（
        `@F1` / `F1：` / `to=F1` / `给 F1`），它就是"对某个具体代理下指令" ⇒ 受控拒绝 `public_is_not_a_conversation`；
        其余公聊照发，但记录上带 `board_kind="bulletin"`。为什么必须机械可判：公聊进的是角色级收件箱（`to == role` 才
        进），所以"公告栏里点名某人"会被那个角色的所有实例读到。
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
        # 公告栏判据（见 docstring）：点名 + 指令语气 ⇒ 这不是公告，是对某个代理下指令。
        #
        # 一句明确的口径：框架通报（`by_framework=True`，叫停那一路）与用户插话
        # 不受这条判据限制 —— 它们不是"代理在对话"，是框架/人代表全树说话
        # （听不到叫停的子孙会继续烧钱跑实验）。豁免落在 `_public_framework_exempt`
        # 这一格、且是显式的：摘掉它，同文件的
        # `test_framework_notice_and_user_interjection_still_get_through` 当场红。
        board_kind = "bulletin" if to == PUBLIC else ""
        by_framework = self._public_framework_exempt(payload)
        if to == PUBLIC and not by_framework:
            named = self._public_addressee(payload)
            if named:
                return {"message": "未发出", "to": to, "ok": False, "receipt": "unknown",
                        "refused": "public_is_not_a_conversation", "board_kind": board_kind,
                        "error": (f"这是在公告栏里点名 {named} 下指令 ⇒ 受控拒绝："
                                  f"{PUBLIC} 是公告栏，不是对话（公告不构成对某个具体代理的指令）。"
                                  "要指定收件人请用名册编号发一条私聊"
                                  "（`message.to` 写名册名或绝对编号）。"),
                        "note": ("这一条没有落盘：公聊进的是角色级收件箱，"
                                 "点名会让那个角色的所有实例都读到 —— 那不是对话")}
        msg_id, problem = send_message(self.session_root, sender=self.role, to=to,
                                       subject=str(payload.get("subject") or ""),
                                       body=str(payload.get("body") or ""),
                                       reply_to=reply_to, sid=self.sid,
                                       from_task_id=str(self.my_task_id or ""),
                                       by_framework=by_framework,
                                       extra={"board_kind": board_kind} if board_kind else None)
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
                "board_kind": board_kind,
                "receipt": receipt, "ok": receipt != "no_reader",
                "note": reader_note}

    def _public_addressee(self, payload: Mapping[str, Any]) -> str:
        """公聊里"点名某个名册成员 + 指令语气"⇒ 返回那个成员（否则空串）。

        判据本体在 `_message_by_channel` 那一支（拒/放行）；这里只做机器可判的那一半：

        1. 名册（父 ∪ 子）里有成员的名册名或绝对编号出现在 subject/body 里；
        2. 并且满足下面任一条：
           - 显式收件人写法：`@F1` / `F1:` / `F1：` / `to=F1` / `给 F1`；
           - 指令语气词（`PUBLIC_DIRECTIVE_MARKS`）。

        名册读不成（无秘书 / 读失败）⇒ 返回空串：这一格"没查成"不许当成"查过了没问题"，
        但也不许因此把整条公聊拒掉 —— 它由 `board_kind="bulletin"` 的标注兜底。
        """
        if self.secretary is None or not str(self.my_task_id or ""):
            return ""
        try:
            members, problem = _callable_members(self.secretary, owner=str(self.my_task_id))
        except Exception:  # noqa: BLE001 —— 判不了 ⇒ 不拒（标注那一路兜底）
            return ""
        if problem:
            return ""
        text = f"{payload.get('subject') or ''}\n{payload.get('body') or ''}"
        for m in members:
            for token in (str(m.get("name") or ""), str(m.get("task_id") or "")):
                if not token or token not in text:
                    continue
                if any(f in text for f in (f"@{token}", f"{token}:", f"{token}：",
                                           f"to={token}", f"给{token}", f"给 {token}")):
                    return token
                if any(mark in text for mark in PUBLIC_DIRECTIVE_MARKS):
                    return token
        return ""

    def _public_framework_exempt(self, payload: Mapping[str, Any]) -> bool:
        """公告栏判据的显式豁免位（口径只有一句，写在 `_message_by_channel` 的判据本体里）。

        取的是框架自己落的那一格（`by_framework`），不是模型能写出来的东西：
        `_decode_shape` 的 `message` 白名单只带 `to` / `subject` / `body` / `reply_to`
        ⇒ 代理把这一格塞进载荷也到不了这里；真机上的框架通报
        （`conductor_tools` 的叫停）走 `send_message(by_framework=True)` 那条直路。
        """
        return bool(payload.get("by_framework"))

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
            # ---- 两段式（业主 2026-10-21）：这一格是"这次派活该执行哪一份"的受控读数 ——
            # 要么是一条请示（`outcome=wash_proposed` + `proposal_id` + diff），
            # 要么是一次确认/拒绝的结论（`accepted` 真/假），要么是"编号不成立"的受控拒绝。
            # 循环取完就 pop 掉，然后按它决定：执行 washed / 执行 original / 谁都不执行。
            if isinstance(got.get("wash_proposal"), Mapping):
                out["wash_proposal"] = dict(got["wash_proposal"])
            # ---- S1g-2：面适配读数（业主 2026-10-09「"超越职责"的一个主要可能是
            # 无法在被分配的读写面内完成任务，这个秘书也要帮忙看」）。
            # `base` 传本实例自己的根：子代理那一趟它的根是它的面，父视角的基准
            # 必须跟着走（否则"父视角有、面内没有"这一档会算错）。
            out["surface_fit"] = dict(got.get("surface") or {}) if isinstance(
                got.get("surface"), Mapping) else {}
            # ---- 能力面那一维（业主 2026-10-14：「秘书侧……评估派发出的任务能否由
            # 子代理及子代理的出边共同完成」）。与 `surface_fit`（路径面）各判一维：
            # 这一条说"谁能做"（`in_self` / `via_edges` / `unreachable` / `unknown`），
            # 那条说"在哪做"。两条都是读数，都不替父改主意。
            if isinstance(got.get("surface"), Mapping):
                out["reach_fit"] = dict(got["surface"].get("reach") or {})
                if got["surface"].get("reach_bad"):
                    out["reach_bad_targets"] = list(got["surface"]["reach_bad"])
                    out["reach_reason"] = str(got["surface"].get("reach_reason") or "")
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

        为什么必须有这一格（T1 第 18 趟实测）：`draft/38` §7 第三组判据里"M 的状态报告落盘"是一格过程判据，
        而并表之后重跑的 T1 两趟（`t1w`/`t1x`）实测：M 派了活、也收了工，却一次都没调
        `conductor.status_report` —— 工具在它的面上（注册表 83 件含它）、提示词里也写着，只是那句原先只说"用
        户问『现在什么情况』时用"；补一句"收工前也落一份"之后仍然没调（收尾序列被 `conductor.closing` 占满）。
        所以这一格与 `_emit_settlement` 同族：框架保证"有"，模型保证"内容"。

        三态（要能分辨"模型落的"与"框架补的"）：模型这一趟调过（盘上有本趟产生的 `STATUS-*`）⇒ `""`（一个字
        都不动）；没调 ⇒ 框架补落一份 + 一句读数（`written_by=framework` + 两份文件名）；补落失败 ⇒ 一句读数
        写清失败原因（不许当成"报告已落盘"）。
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

        两层必须分开（DSH 的教训，`draft/85` §5.4）：通报由框架保证 —— 模型没写 `notify`（`run.handoffs` 为空）时，框
        架开一条 `kind="notice"` 的板项、body 逐字写「（它没有留下结论）」（对齐 DSH 的 `It left no closing message.`）
        ；内容由模型给 —— 模型写了就不补第二条（负控见 `tests/test_report_is_mandatory.py` 的"模型填了 ⇒ 恰好一条"）。
        三种"没做成"都如实返回一句读数，不静默：不是终态 / 没有 conductor 句柄 / 开项抛异常。
        收件人是谁（D89，2026-10-08 深夜修）：板项的 `parent_task_id` 口径是"收件人的编号"，所以子报给父时它必须是父的
        台账号、`role` 写父的角色 —— 改前写的是 `parent_task_id=self.my_task_id`（挂在自己名下），后果是父的
        `open_items_of(父的编号)` 里永远看不到"哪个子向我交差了"；现在用 `run` 里现算的 `parent_task_id` /
        `parent_role`。判据：`tests/test_report_is_mandatory.py` / `tests/test_children_and_parent_are_visible.py`（负
        控：换成自己的编号 ⇒ 红）。
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
        # `task_id`（业主 2026-10-21「全面接入」第二步）：这一条是"哪个编号的哪一岗
        # 在报告收工"—— 它与 `agent_run_end` 是同一件事的两条落点（一条进板、一条进
        # 会话记录），编号口径必须同一份（`self.my_task_id`），否则读侧要把两条事件
        # 对起来时只能按 role 猜。
        SS.append(self.session_root, {"kind": "agent_settlement_item", "role": self.role,
                                      "task_id": str(self.my_task_id or ""),
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

    def _do_handoff(self, payload: Mapping[str, Any], *,
                    board_item: bool = True) -> dict[str, Any]:
        """写一份交接手稿 + 把"编号 + 一句简要描述"发给收件人（`draft/37` §134）。

        两件事一起做，因为它们是同一件事的两半：手稿是「内容」，留言是「通知」；让模型分两步做就会出现"写了手稿但对方
        不知道"（或反过来）的半截状态，而且用户点过名："就传个编号感觉有点尬，可以再附一句简要描述"。`to="ALL"` ⇒ 走公
        共频道；存储是追加式账本 `manuscripts/handoffs.jsonl` 的一行（`draft/39` §C1：编号与那一行在同一把锁里分配）。

        A 线：执笔权已经移交给本角色的秘书（`draft/53` §2.1 / `draft/55` §3.2）。用户口径（2026-10-06）："由于所有信息
        交互都由秘书过一遍手，所以 handoffs 的增改查能力都该给秘书，智能体只保留『查』的能力。"落法：循环形状
        `handoff` 保留；写这一行的是 `self.secretary.handoff_add(...)`（`sender` 仍是本角色）；没装配秘书 ⇒ 不写并如实
        报错（"形状保留、写路径关闭"的判据就在这一支）。`manuscripts.read` / `manuscripts.list` 工具保留（这就是"智能
        体只保留查"）。

        ## `board_item=False`（D-68，2026-10-26）：派活通知不落收件人的板

        派活那条路（`_dispatch_notify` → 本方法）写的是"父把活交出去了"这份投递凭证：
        活本身已经是那次召唤的 `task`，手的正文在 `handoffs.jsonl` 里读得回全文，收件人
        此刻已经跑完了那一趟。把它落成收件人名下的 `queued` 板项，等于给一个已经离场的
        收件人留一条它这辈子读不到、也没人替得了的待办 —— 而 D-68 的销号门要求"板上有
        没消的就不许销号"（业主逐字：「task_board 没清，不准直接销号」）⇒ 那一支永远
        销不掉、`final` 永远记不下来。所以这一档改落一条 `agent_message` 事件
        （投递照旧有痕），不建 `tasks` 行。
        """
        to = str(payload.get("to") or "")
        # D-63（2026-10-24）：解码层把名册写法（名册名 / 绝对编号）翻成了角色的同时，
        # 把原写法留在 `roster_addressing.written` 里。寻址要问的是原写法 —— 问角色
        # 只会得到"落到角色通道"，而业主的口径是"写名册名就是写给那一个实例"。
        # 没有这一格（照旧按角色名 / M / ALL 写）时逐字走改前的路。
        _marker = payload.get("roster_addressing")
        written = str(_marker.get("written") or "") if isinstance(_marker, Mapping) else ""
        channel = PUBLIC if to == "ALL" else to
        # `summary` 是这一形状的正名（它就是进留言的那一句话）；`brief` / `title` 是旧名，
        # 仍然接受 —— 旧调用点、旧提示词与模型的历史习惯都不至于因此写不进去。
        one_line = (str(payload.get("summary") or "").strip()
                    or str(payload.get("brief") or "").strip()
                    or str(payload.get("title") or "").strip())
        why = str(payload.get("why") or "").strip()
        # ---- 收件人（业主 2026-10-19）：名册名 / 绝对编号这一档必须落在名册上
        # （判据与理由见 `_handoff_address`：手稿的收件人面是角色，名册给的是实例）。
        # 拒绝发生在写任何东西之前：半份状态（手稿写了、人没收到）比没写更贵。
        _addr, _gate = self._handoff_address(written or to)
        if _gate:
            return {"handoff": "未写成", "ok": False, "to": channel,
                    "refused": _gate["refused"], "candidates": (_gate.get("candidates") or []),
                    "addressing": _addr, "error": _gate["error"],
                    "note": ("这一条受控拒绝：手稿一行没写、留言一条没发"
                             "（受控拒绝不是「稍后再试」）")}
        # 手稿那一行的收件人 = 名册解析出的角色（台账的口径）；`ALL` 走公共频道。
        manuscript_to = str(_addr.get("manuscript_to") or to)
        channel = PUBLIC if _is_all_recipient(to) else manuscript_to
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
                    to=manuscript_to, summary=one_line, body=str(payload.get("body") or ""),
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
            same = [r for r in self.secretary.handoff_query(to=manuscript_to,
                                                             sender=self.role)
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
        notify_subject = f"手稿 {shown}：{summary}"
        notify_body = (f"[手稿 {shown}] {summary}"
                       + ("（订正行，旧行保留）" if revises else "")
                       + (f"\n（为什么找你：{why}）" if why else "")
                       + f"\n全文：`manuscripts.read(id=\"{shown}\")`"
                         f"（盘上 {rec.get('path')}）")
        notify_how = "role"
        if str(_addr.get("delivery") or "") == "roster" and board_item:
            # 名册成员 ⇒ 投到那个实例的板项（实例级）。改前这里对名册名也走
            # `send_message(to="D1")`，而收件箱是按角色收的 ⇒ 那条留言没有任何人读得到。
            deliv = self._message_to_member({"subject": notify_subject, "body": notify_body},
                                            _addr)
            msg_id, problem = str(deliv.get("item_id") or ""), (
                "" if deliv.get("ok") else str(deliv.get("note") or "投递没成"))
            notify_how = "roster"
        elif str(_addr.get("delivery") or "") == "roster":
            # 派活通知这一档（D-68）：不建板项，改落一条 `agent_message` 事件。
            # 理由见本方法的 docstring 末一节；投递照旧有痕，只是不再留一条清不掉的待办。
            msg_id, problem = send_message(
                self.session_root, sender=self.role, to=channel,
                subject=notify_subject, body=notify_body,
                sid=self.sid, from_task_id=str(self.my_task_id or ""))
            notify_how = "event"
        else:
            msg_id, problem = send_message(
                self.session_root, sender=self.role, to=channel,
                subject=notify_subject, body=notify_body,
                sid=self.sid, from_task_id=str(self.my_task_id or ""))
        return {"handoff": shown, "ok": not problem, "id": shown,
                "path": rec.get("path"), "to": channel, "brief": summary,
                "addressing": _addr, "notify_channel": notify_how,
                "revises": revises,
                "existing_same_summary": dup_note,
                "notified": msg_id if not problem else "",
                "error": problem,
                "note": (("收件人下次运行时会在收件箱里看到这条留言（派活通知不落板："
                          "见本方法 docstring 的 D-68 一节，它用 `manuscripts.read` 读全文）")
                         if notify_how == "event" else
                         ("收件人下次运行时（或本步之后）会在收件箱/板上看到编号；"
                          "它用 `manuscripts.read` 读全文"))}

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

        | `state` | 结果给模型 | 循环 |
        |---|---|---|
        | `answered` | 原样把那句回答给它（含 `selected` / `custom`） | 继续 |
        | `refused` | 无人值守档：确定性拒绝（fail-closed） | 继续（一次普通工具结果） |
        | `pending` | 还停在等（`user_no_answer` 的含义变了） | 停：`stop_reason="waiting_for_user"` |
        | `cancelled` | 等待被当前轮次的取消信号中止 | 停：`stop_reason="ask_cancelled"` |
        | `""`（问题没落档） | 通道没通 | 继续（没有 qid 就没有人能答） |
        为什么 `refused` 不许停：它是无人值守这个设定本身的结论，不是"有人在等回答"（停了 CI 里没人续跑）。为什么
        `pending` 必须停且不许再发请求：提问的意义是"这个取舍只有人能定"，继续跑等于替人定了。
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
        """登记过的 `(角色, 动作)` 走 LLM 循环；空动作也走循环；其余交给内层后端。

        ## 空动作为什么走循环（2026-10-16，业主口径 S2「M 只派活」）

        原话逐字：「M 只是个派活的，对所有角色都一样，只根据它们的能力范围派活，
        不指定能力。」⇒ 召唤时不点动作，意思是把这件活交给这个角色，
        由它按自己的手册、工具面与政策选动作。它当然要跑自己的循环才选得了 ——
        交给内层处理器反而是"替它选了那个不存在的动作"。
        给了动作的那条路逐字不变（向后兼容：`pipeline` / `scheduler` / `deliver` 照旧）。
        """
        if not str(action):
            # 角色级那一格（`--drive D` 这种写法）留了口子；没登记就用默认档。
            cfg: Mapping[str, Any] | None = dict(self.loops.get((role, "")) or {})
            cfg.setdefault("max_steps", self.max_steps)
        else:
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
        # 2026-10-22 真机缺陷（p3-verify2 收官趟，`manuscripts/handoffs.jsonl` 的 000017/000018）：
        # 父给 G 切了一个空的槽（`out/surfaces/t-000025/S01`），于是 G 的 `fs.*` 根就是那个空目录，
        # 连 `out/paper/main.tex` 都读不到（两条读法都 `path_denied`），`doc.paper_compile` 只能报
        # `paper_no_source` ⇒ 论文那一格永远 unknown。
        # 口径：空面不算切面。切面是为了"把这一趟要用的那一块切进来"，一个空目录切进去，
        # 等于把这一趟的手脚绑住；它与"面读不到就不切"是同一条纪律的两种情形。
        # 三态照旧：不切要留痕（下面 `child_surface_empty`），不许静默退回项目根冒充"面切过了"。
        child_surface, child_surface_empty = _surface_root_decision(child_surface)
        child_registry = self.registry
        if child_surface and callable(self.registry_factory):
            try:
                child_registry = self.registry_factory(child_surface)
            except Exception:  # noqa: BLE001 —— 造不出来就退回共用（并在结果里留痕）
                child_registry = self.registry
        # ---- 「做我这一趟被派的那个动作」这一件工具（2026-10-14，业主裁定 ③ 的收尾）
        # 真机形态（p9-t1-nolean，`--subagents`）：`B.register_statement` 被交给模型驱动，而它不在工具面上 ⇒ 模型拿到
        # `unknown_tool`，改去 `table.create(table="statements")` 手写行，绕过 `register_statement` 的全部写库前
        # 预检（出处、页码形状、引文证据、取号、查重）。修法：把这一趟被派的那个动作原样包成一件工具（handler 走内层
        # 确定性实现，名字就是动作名），只在这一趟的循环里存在。2026-10-19 晚（`projects/mp2` 的 `mp2-7.jsonl`）：
        # 这一格原先只在点了动作时注入（`if str(action):`），而真机派活是 S2 口径的「只派活、不指定能力」
        # （`tasks.action=""`）⇒ 注入一次都没发生，B 拿到 32 件常规工具、第 94 行撞 `unknown_tool`、第 97 行改走
        # `table.create` 手写 `bits={}` —— 病因在"只派活"成为常态后又回来了一次（中间层只在另一条路上装）。
        # 现在两种派活都装（`_own_actions_to_expose`）：空动作时把本角色「没有同名工具」的动作各包一件
        # （`capabilities.unmapped_actions` 是那件事的现成判据）。
        child_registry = self._registry_with_own_action(
            child_registry, role=role, action=action, token=token, instance=instance,
            task_id=str(row.get("task_id") or params.get("_task_id") or ""))
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
               "steps": len(run.steps), "summons": run.summons, "messages": run.messages_sent,
               # 优雅停止时"手上还剩什么"随结果回给父（父再往上报，M 汇总给用户）
               "blocked_remaining": dict(run.blocked_remaining)}
        if not artifact:
            out["llm_run"] = run.to_dict()      # 落盘失败时退回内联，绝不静默丢产出
        return out

    def _own_actions_to_expose(self, role: str, *, action: str) -> list[str]:
        """这一趟该把本角色的哪几个动作包成工具交过去。

        两种派活，同一件事（2026-10-19 晚）：点了动作（`--drive B.register_statement` / `conductor.summon(action=…)`）
        ⇒ 就那一个，老行为逐字不变；只派活、不点动作（S2 业主口径；真机 `tasks.action=""`）⇒ 把本角色「声明了但没有同
        名工具」的那些动作各包一件，判据用 `capabilities._KNOWN_UNMATCHED_ACTIONS`（导入期 `assert_capabilities()` 第
        [7] 条把它与现算的 `unmapped_actions()` 逐条对过，判据在 `tests/test_capabilities_two_layer.py`）—— 不另抄一份
        清单，也不每次召唤现算（`unmapped_actions()` 要装配完整工具面，实测 270ms/次）。
        为什么空动作也要装（真机读数，`projects/mp2/sessions/mp2-7.jsonl`）：这一格此前是 `if str(action):`，于是「只
        派活」那一路上一次都没装过 ⇒ B 的工具面里没有 `register_statement`，它第 94 行撞 `unknown_tool`、第 97 行改走
        `table.create(table="statements")` 手写 `bits={}`。业主 S2 的"不指定能力"说的是派活的人不越俎代庖，不是让被派
        的人够不着自己的动作。
        """
        if str(action):
            return [str(action)]
        try:
            from . import capabilities as C

            # 登记副本优先（导入期对账过）；没有它就退回现算（慢，但不会"没装"）。
            unmatched = getattr(C, "_KNOWN_UNMATCHED_ACTIONS", None)
            if unmatched is None:
                unmatched = {f"{r}.{a}" for r, a in C.unmapped_actions()}
        except Exception:  # noqa: BLE001 —— 读不到就不注入（不许猜）
            return []
        prefix = f"{role}."
        found = [n[len(prefix):] for n in unmatched if str(n).startswith(prefix)]
        return [a for a in sorted(found) if a]

    def _registry_with_own_action(self, base: Any, *, role: str, action: str,
                                  token: Any = None, instance: str = "",
                                  task_id: str = "") -> Any:
        """把「我这一趟能做的动作」包成工具，挂到这一趟循环的注册表上。

        为什么必须有它（业主 2026-10-14 裁定 ③ 的收尾，真机 p9-t1-nolean）：`--subagents` / `--drive 角色.动作` 会把
        `(角色, 动作)` 交给 LLM 循环执行，于是那份确定性实现这一趟不会被调用；而角色的动作不在工具面上（
        `capabilities.unmapped_actions()` 逐条报的就是这一族）⇒ 被派的子代理拿不到自己被派的活，只能改用
        `table.create` / `table.update` 手写表：真机里 B 就是这么写 statements 的，绕过了出处、页码形状、引文证据、取
        号与查重五道预检，`quote_verified=true` 变成它自报的。
        这里把动作按声明面（`capabilities.find_action` 的 `params` / `side_effect`）原样包成一件工具，handler 走内层后
        端（`self.inner.call`）—— 那套带闸门的确定性实现。工具名是 `own.<动作名>`（本仓约定是 `组.动作`，不带点的名字
        `ToolSpec.__post_init__` 当场拒），只活在这一趟循环的注册表里；模型若按手册里的短名（`register_statement`）来
        叫，`_do_tool` 的别名那一格会映射到 `own.register_statement` 并留 `aliased_from`。不注入的两种情况（绝不给一件
        调不通的工具）：内层后端没有这个角色的实现（`role not in self.inner.known_roles()`）⇒ 那本来就该由模型自己用工
        具做；这个动作的声明读不到（`capabilities.find_action` 返回 `None`）。
        """
        if self.inner is None or not hasattr(self.inner, "known_roles"):
            return base
        try:
            if role not in set(self.inner.known_roles()):
                return base
        except Exception:  # noqa: BLE001 —— 读不到就不注入（不许猜）
            return base
        from . import capabilities as C
        from .tools.base import ToolRegistry, ToolSpec

        specs: list[Any] = []
        for one in self._own_actions_to_expose(role, action=action):
            try:
                spec = C.find_action(role, one)  # 声明面只有一处（`capabilities`，内置 specs）
            except Exception:  # noqa: BLE001
                spec = None
            if spec is not None:
                specs.append(spec)
        if not specs:
            return base

        scoped = base.scoped_to(role) if hasattr(base, "scoped_to") else ToolRegistry(name=f"{role}:own")
        registered = 0
        for spec in specs:
            one = str(getattr(spec, "action", "") or "")
            if not one:
                continue
            try:
                scoped.register(self._own_action_tool(
                    spec, one, role=role, token=token, instance=instance, task_id=task_id))
            except Exception:  # noqa: BLE001 —— 注入失败不许带走这一趟（也不假装注过）
                continue
            registered += 1
        return scoped if registered else base

    def _own_action_tool(self, spec: Any, action: str, *, role: str, token: Any = None,
                         instance: str = "", task_id: str = "") -> Any:
        """把一个动作声明包成一件只活在这一次循环里的工具（`own.<动作名>`）。"""
        from .tools.base import ToolSpec

        params_schema = dict(getattr(spec, "params", None) or {})
        if not params_schema:
            params_schema = {"type": "object", "properties": {}}

        def _handler(**given: Any) -> Any:
            """跑这件动作（走内层确定性实现，闸门照旧）。"""
            from . import cancellation as _CAN

            # `token=None` 时补一个真令牌：内层后端会调它的 `raise_if_cancelled`
            # （取消语义是那一条路上的硬约定，不许因为我这一层传了 `None` 就炸）。
            tk = token if token is not None else _CAN.CancelToken()
            try:
                got = self.inner.call(role, action, given, token=tk,
                                      instance=instance, task_id=task_id)
            except Exception as exc:  # noqa: BLE001 —— 受控失败也要如实回给模型
                return {"ok": False, "kind": "own_action_failed",
                        "reason": f"{type(exc).__name__}: {exc}"}
            if isinstance(got, Mapping) and got.get("ok") is False:
                # 动作自己的受控拒绝（`_refuse` 的形态）照原样透出去：
                # `kind` / `reason` 是模型据此改参数的唯一依据，不许被压成"成功"。
                #
                # `error` 那一格必须算进"理由"里（2026-10-19 晚修）：`refusals.refuse`
                # 的返回是 `{"ok": False, "kind": …, "error": "<一句话说清怎么办>"}` ——
                # 没有 `reason` 键。旧写法只读 `reason`/`detail`，于是每一条动作级
                # 拒绝到了模型眼前都变成两个字「被拒」（实测：`missing_own_source` 的
                # 完整拒信被吞掉，模型只能猜）—— 那正是"拒信要能把模型指回正路"这条
                # 要求的反面。`refusal_reason` 也一并带出去（终态映射读它）。
                return {"ok": False,
                        "kind": str(got.get("kind") or "refused"),
                        "reason": str(got.get("reason") or got.get("error")
                                      or got.get("detail") or "被拒"),
                        "refusal_reason": str(got.get("refusal_reason") or ""),
                        **{k: v for k, v in got.items()
                           if k in ("problems", "missing", "stmt_id", "available_lit_ids",
                                    "literature_rows", "unresolved", "changes", "upgraded")}}
            return got

        return ToolSpec(
            # 名字带组名（`own.`）：本仓的工具名约定是 `组.动作`（`ToolSpec.__post_init__`
            # 当场拒不带点的名字）。`own.` 这个组名本身也是一句说明 ——
            # "这是你自己的动作"，与通用表工具 `table.*` 区分得开。
            name=f"own.{action}",
            summary=(f"做我自己的那个动作（{role}.{action}）："
                     f"{str(getattr(spec, 'summary', '') or '').strip()}"),
            params=params_schema,
            handler=_handler,
            side_effect=str(getattr(spec, "side_effect", "none") or "none"),
            roles=(role,),
            returns=("与动作实现同形；受控拒绝时给出 `kind` / `reason`"
                     "（照它改参数，别改用 `table.*` 手写表绕过预检）"),
            tags=("own_action", "drive"),
        )

    def _seam(self, role: str) -> LlmSeam:
        if self.seam_factory is not None:
            return self.seam_factory(role)
        raise RuntimeError("LlmBackend 需要 seam_factory（一个按角色造模型缝的调用方）")

    def _write_run_artifact(self, role: str, run: LoopRun) -> str:
        """把这次循环的完整记录写成文件，返回路径（失败就返回空串并留 note）。

        B11（`draft/41-A` 的 B11）：唯一性靠 `O_EXCL`，不靠"先数后写"。旧实现是
        `n = len(list(d.glob(f"{role}-*.json"))) + 1`，然后按这个名字写 —— 没有锁、也不是 `O_EXCL`：同一角色
        同秒的两个并发循环会算出同一个 `n`，后写覆盖先写，于是两个召唤返回同一个 `llm_run_path`（一份产出凭
        空消失，而两个调用方都以为自己的产出在盘上）。`conductor._write_new_row` 为同类问题专门加了
        `_id_lock`；这里用更省事也更彻底的一条：`open(..., "x")`（`O_EXCL`）—— 它同时挡住同进程的两个线程与
        两个进程。

        失败不用"猜一个名字"兜底：撞名就 +1 重试（时间戳不变，序号递增），重试到上限仍撞 ⇒ 如实留 note 并返
        回空串（"没写成"与"写成了"要分得开）。
        """
        try:
            d = self.session_root / RUNS_DIR_NAME
            d.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(run.to_dict(), ensure_ascii=False, indent=2, default=str) + "\n"
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

        两条取材路径，按可靠性排序：1. 给了 `task_id`（`Conductor.summon` 现在会传，见 `conductor.py` 第 [6] 步）⇒ 直
        接按号取那一行（并发多实例下唯一可靠，按角色找会同时找到 N 条）；2. 没给号（旧调用方 / 直接建 `LlmBackend` 的
        单测）⇒ 退回"按角色找恰好一条"。
        为什么找而不是让调用方传：`Conductor.summon` 先写 running 行、再调后端，所以后端天然不知道自己的台账号；三种"
        没拿到"必须分得开（没有台账 / 读台账失败 / 恰好不是一条），所以返回值带 `checked` 与 `reason`。为什么返回整行
        而不是只返回 `task_id`（2026-09-30 修的 bug）：子循环的 `summoned_by` / `depth` 以前读
        `params["_summoned_by"]` / `params["_depth"]`，而全仓没有任何地方生产这两个键 ⇒ 每一次被同伴唤起的角色都以为"
        是主控直接派的、深度 1"（实测读数摘录 `temp/t0260-evidence`：
        `t-0260 E.run_experiment called_by=F parent=t-0259 depth=2`，而 E 自己的 `agent_run_start` 记的是
        `summoned_by=M, depth=1`）。
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
    """把召唤参数渲染成给孩子看的任务描述（没有参数时如实说明）。

    2026-10-16（S2「M 只派活」）：`action` 为空时，任务就是那件活本身 ——
    取 `params["task"]` / `params["brief"]`（派活方写的那句话）。两者都没有 ⇒
    如实说"没有带活"，不许编一个动作出来。
    """
    given = {k: v for k, v in (params or {}).items() if not str(k).startswith("_")}
    if not str(action):
        work = str(given.get("task") or given.get("brief") or "").strip()
        if work:
            return f"{role}：这一趟派给你的活是 —— {work}"
        return f"{role}：这一趟**没有点动作、也没写清是什么活**（调用方要你按职责自己判断）。"
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
                        waiting_for: str = "", spend: Mapping[str, Any] | None = None,
                        prompt_cache: Mapping[str, Any] | None = None) -> str:
    """写这一趟的步检查点，返回问题串（空 = 写成了）。写入失败不许静默。

    指纹用 `autonomy.task_fingerprint(role, task)`（同一条口径，不另立一份）：续跑之前必须比对它 —— 拿 A 任务的检查点
    去续 B 任务，会把两件事的进度混成一条，而那条记录看起来完全正常。
    为什么这里也要 `prompt_cache`（2026-10-19 的真机缺口）：这一份文件是顶趟唯一落在 `runs/` 下的"这一趟干了什么"的记
    录（产出文件 `runs/<角色>-<时间戳>-<序号>.json` 只在被召唤那条路上写（`_summon` 收尾，见 `_write_run_artifact`）；
    `run_role` 收工时不写它），于是 `agent_run_end` 的 `prompt_cache` 汇总在盘上只活在一处，而这一格此前只有 `spend`
    —— 同一笔钱的两面只落了前一面。
    三态（与 `LoopStep.to_dict()` 同一套）：算过、上游给了读数 ⇒ 11 格汇总（`hit` / `miss` 是数）；算过、上游一次都没
    给 ⇒ 汇总在，`unknown_calls > 0`、`hit_rate is None`（绝不折成 0%）、`why` 里写明原因；没算过 ⇒ `{}` ——"没有汇总"
    与"算过但上游没给"必须分得开，所以这一格永远在。
    """
    from . import autonomy as AU

    path = run_checkpoint_path(session_root, role, sid)
    payload = {"role": role, "sid": str(sid or ""), "task": task,
               "fingerprint": AU.task_fingerprint(role, task),
               "step": int(step), "stop_reason": str(stop_reason),
               "waiting_for": str(waiting_for or ""),
               "spend": dict(spend or {}),
               # 与 `spend` 并列：键永远在（三态见 docstring）。
               "prompt_cache": dict(prompt_cache or {}),
               "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")
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

    判据：与循环里那份逐条相等（含思维链那一格）。重建只认两样东西：本趟的起点（最后一条"全新开始"的 `agent_run_start`，
    它带着任务 / 发起者 / 深度 / 台账号）与它之后逐条落盘的 `agent_step` 事件；每一条消息都走 `agent_loop` 里那几个模
    块级函数（`_opening_transcript` / `_spoken_half` / `_result_half` / `*_line` / `assistant_message` /
    `tool_message`）—— 循环里也是它们，"两处拼法"因此结构上不成立。思维链（12-A=乙）：事件里那一格 `reasoning` 就是当
    时进消息的那一份（`_recorded_reasoning` 与落档同一把尺）⇒ 重建出来的 `reasoning_content` 与当时逐字相同。
    窗口：起点 = 最后一条 `role` 相同、`task` 原文相同、且 `_is_fresh_run_start` 为真的 run_start（续跑写下的
    `resumed_from>0` 与「被拒的续跑」`resume_refused` 都不是起点 —— 后者没有步，若被当成起点，重建就会变成空的那一段）；
    终点 = 该角色下一条"全新开始"的 run_start（任何任务），它挡住"同一任务被从头重跑"与"同角色另一个任务的步混进来"（
    `agent_step` 里没有任务号，窗口是唯一能把两趟分开的东西）；窗口里的续跑段照收（步号全趟单调，续跑从 `resumed_from`
    接着编）。
    三条边界（不假装比实际更强）：1. 开头的收件箱用 `inbox_digest` 按当前盘上的状态重算 ⇒ 原趟开头若带"（新）"标记，重
    建出来的那几行会不同（变的只会是收件箱那一段，而且只会变新）；2. 单字段超过落档上限的那一步存的是截到
    `RECORD_CHARS` 的审计副本 ⇒ 那一行末尾会比当时短（这是重建能力的上限，不是漏了）；3. 找不到本趟的起点 ⇒ 返回
    `("", 0)`，不猜、不退回"把所有步都收进来"，调用方（`run_role`）据此判"没查成"，而不是从第 1 步重跑一遍。
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
    # 十二格事实的还原口径（2026-10-21 起它们住在开场那条 user 消息里，见 `_opening_transcript`）：
    #
    # - 起点事件里整包落了一份 `opening_facts`（这一趟开始那一刻的快照）⇒ 逐格读回；
    # - `task` / `summoned_by` / `task_id` / `depth` 四个老键在事件上是平铺的（那一版就有），
    #   它们与 `opening_facts` 同值，取平铺那份即可；
    # - `inbox` 仍然现读（`inbox_digest`）：续跑本来就该听到新到的留言 —— 这是这条
    #   重建路上唯一"该变"的一格，写在 `resume_messages` 的 docstring 第 1 条边界里。
    #   于是"重建 == 当时那一份"在没有新留言时逐条成立，有新留言时只差收件箱那一段
    #   （只会变新，不会变假）。
    opening: dict[str, Any] = {k: (head.get("opening_facts") or {}).get(k, "")
                               for k in OPENING_FACT_KEYS}
    opening.update({
        "task": task,
        "inbox": inbox,
        # `user_replies` 与 `inbox` 一样现读（2026-10-21）：用户的回答可能在两趟之间
        # 才到（"迟到的回答"那一档就是这条路的常客），用起点事件里的旧快照会让那句话
        # 在续跑那一趟彻底消失 —— 而它此前在 system 里、每趟现算，所以现读才是
        # 改前的行为。其余八格是"这一趟的事实"（谁派的、深度、台账号、名册、板、工作区），
        # 用事件里的快照重建：它们不该在续跑时被"今天盘上的样子"替换掉，
        # 否则重建出来的那一段与当时那一段不是同一趟（判据 `rebuilt == run.messages`）。
        "user_replies": AP.user_replies_digest(
            U.read_replies(root, role=role, sid=sid)),
        "summoned_by": str(head.get("summoned_by") or ""),
        "task_id": str(head.get("task_id") or ""),
        "depth": int(head.get("depth") or 1),
    })
    out: list[dict[str, Any]] = [user_message(_opening_transcript(**opening))]
    next_step = 0
    for e in events[begin + 1:end]:
        if str(e.get("role") or "") != role:
            continue
        # ---- 信箱投递（D-52）：`shape="turn"` 的那一档要按事件序把那条 user 消息
        # 原样重放回来 —— 它当时就在"第 k 步的提示词之前"，位置由事件顺序决定。
        # `shape="step_tail"` 那一档不重放：那段文字当时在那一步的 tool 结果里
        # （`result["新消息"]`），这里再加一条会让重建多出一条消息。
        if e.get("kind") == MAILBOX_EVENT:
            if str(e.get("shape") or "") == "turn":
                out.append(user_message(str(e.get("text") or "")))
            continue
        if e.get("kind") != "agent_step":
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
            elif _is_no_reply(problem):
                # 续跑要拼出当时那一句（判据：重建的对话与当时逐字相等）。
                correction = _no_reply_line(step, problem, str(result.get("detail") or ""))
            else:
                correction = _invalid_line(step, problem)
            out.append(assistant_message(step, payload, name=shape, reasoning=thought))
            # 这一条不带 `name`：`invalid` 那一支在循环里append 的就是不带名字的
            # （`messages.append(tool_message(step, _bad_json_line(...)))`）。改前这里
            # 带了 `name=shape`，于是"含 invalid 步的一趟"永远重放不回去
            # （`rebuilt == run.messages` 在 name 那一格上红）—— 那是改前就存在的一处
            # 重建不一致，2026-10-24（D-52 的续跑判据）在这里补上。
            # 还剩一处已知不一致（本次没修，已登记）："形状认不出来"的那一档
            # （`messages.append(assistant_message(step, data, name=recognized or "step"))`）
            # 把原始 `data` 塞进了 assistant 消息，而事件里存的是解码后的 `payload`
            # ⇒ 它拼不回来；要修得先改那一条事件的落档内容（那是另一条缺陷）。
            out.append(tool_message(step, correction))
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
        # 压缩那条替换（`compaction_swap`）与剪枝那条（`compaction_prune`）共用同一套
        # 位置语义（`surface_op` 闭区间 + `replacement_message`）⇒ 重放只写一遍。
        if e.get("kind") not in ("compaction_swap", "compaction_prune") \
                or str(e.get("role")) != role:
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
                         *, attempted_from: int = 0, task_id: str = "") -> None:
    """续跑被拒时也落一条 `agent_run_start`：为什么拒必须留在会话记录里。

    为什么不静默返回：`--resume` 被拒的那一趟在盘上什么都没留下，读会话记录的人只会看到"上一趟到此为止"，而"
    它被人要求续过、被拒了"没有任何痕迹。这一条与 `AgentLoop.run` 里那条同名事件的区别有两个，都是刻意的：它
    带 `resume_refused` 这个码，且没有后续的 `agent_step`（一步都没跑）；它不写 `resumed_from`，而写
    `resume_attempted_from` —— 因为 `resumed_from` 的口径是"这一趟真的从第几步接着跑"（0 = 全新开始），被拒
    的续跑一步都没跑，写 0 会被读成"它从第 0 步续的"。"它想从第几步续"是另一件事，就得有另一个名字。

    `task_id`（业主 2026-10-21「全面接入」第二步）：这条 `agent_run_start` 也是"某一岗
    说的话"，编号口径与 `AgentLoop.run` 里那条 start 一致（`run_role` 开出来的那一行）。
    它此前没有这一格 ⇒ 被拒的续跑在对话线上是一条"（未记录编号）"的起趟。
    """
    payload: dict[str, Any] = {"kind": "agent_run_start", "role": role, "task": task,
                               "task_id": str(task_id or ""),
                               "waiting_for": "", "resume_refused": why,
                               "resume_attempted_from": int(attempted_from)}
    SS.append(root, payload, sid=sid)


def _secretary_for(role: str, *, root: Path | str, store: Any, registry: Any,
                   seam: Any, sid: str | None = None) -> Any:
    """给这一趟装配本角色自己的秘书（生产路径的唯一落点）。

    主控裁定 A5（2026-10-06）：打开秘书的模型判断。三个条件写在这一个函数里：1. 秘书自己那一档模型（业主 2026-10-14：
    「所有智能体的秘书另外共用一个 api key」）—— 设置文件里有 `secretary` 段（或它回落到的某一档）配了 key 时走
    `LlmSeam.for_secretary`（同一把 key、同一个模型，全角色的秘书共用），没配时退回本体的缝（老行为逐字不变），两条路
    都写进 `Secretary.model_source` 留痕；2. `enable_model=True` —— 关着的时候三条判断在生产里等于不存在，而"把该不该
    派的判断全写死成确定性规则"正是用户点名不要的形态，花销由 `Secretary.should_engage` 绑在问题量上（干净的派活 0 次
    调用）；3. 可归因 —— 每次判断的 `usage_id`（取不到就 `call_index`）由 `Secretary.last_judge_cost` 从缝自己落的
    `llm_call` 事件读回来、进决定台账，秘书那一档的账记在 `by_role="secretary:<本体角色>"` 上（共用一把 key 仍然分得清
    是哪个角色的秘书花的钱）。
    装配失败不抛（fail-open）：`run_role` 那一层兜住异常 ⇒ 不装配秘书（写路径关闭、判断不发生），这一趟照跑。
    """
    from . import secretary as _SEC
    from . import modelgw as _MG

    seam_for_secretary, source = _secretary_seam(role, root=root, seam=seam, sid=sid,
                                                 mg=_MG)
    sec = _SEC.for_role(role, root=root, store=store, registry=registry,
                        seam=seam_for_secretary, enable_model=True, sid=sid)
    try:
        sec.model_source = source
    except Exception:  # noqa: BLE001 —— 留痕失败不许带走秘书
        pass
    return sec


def _secretary_seam(role: str, *, root: Path | str, seam: Any, sid: str | None,
                    mg: Any) -> tuple[Any, str]:
    """秘书这一趟用哪个缝（返回 `(缝, 来源)`；来源进 `Secretary.model_source`）。

    只有 `secretary` 段自己配了 key 才另起一个缝。 为什么不用"梯子回落到了有 key
    的那一档"作判据：回落链的末端是 `model` 段，而几乎所有工作区都配了它 ——
    那等于"默认就给每个秘书换一把新缝"，后果有两样，都不是我们想要的：
    ① 测试里那些替身网关会被一把真 key 顶掉（秘书改用真网关发请求）；
    ② 账本归口从本体角色变成 `secretary:<角色>`，历史读数跟着变。
    业主那句话的意思是"另配一把共用的 key 时用它"，所以判据就是那一格配没配。
    """
    if seam is None:
        return None, "none"
    from . import settings as SET

    try:
        spec, where = mg.spec_for(secretary=True)
    except Exception as exc:  # noqa: BLE001 —— 配置读不成 ⇒ 退回本体那一档
        return seam, f"body（秘书档读不成：{type(exc).__name__}: {exc}）"
    if not spec.configured or where != SET.SECRETARY_SECTION:
        return seam, f"body（secretary 档没配 key：{where or '空'}）"
    # 共用的三样照抄本体的缝：账本（唯一一份账）、预算上限、价格表 ——
    # 秘书那一档换的只是"用哪把 key/哪个端点/哪个模型"，不换预算窗口。
    return LlmSeam(role=f"secretary:{role}", session_root=Path(root),
                   gateway=mg.ModelGateway(spec), sid=sid,
                   usd_budget=getattr(seam, "usd_budget", None),
                   price=getattr(seam, "price", None),
                   meter=getattr(seam, "meter", None),
                   budget_of=getattr(seam, "budget_of", None)), f"secretary（{where}）"


def run_role(role: str, task: str, *, store: Any, registry: Any,
             session_root: Path | str | None = None,
             conductor: Any = None, seam: LlmSeam | None = None, gateway: Any | None = None,
             max_steps: int = 30, usd_budget: float | None = None,
             workspace_root: str = "", sid: str | None = None, token: Any = None,
             from_env: bool = True, user_timeout_sec: float | None = None,
             ask_policy: str | None = None, resume: bool = False,
             stop_file: str = "", secretary: Any = None,
             monitoring_of: str = "") -> LoopRun:
    """跑一个角色的一次循环（真机或替身都走这一条）。

    `session_root` 不给时取 `store.root`：会话记录的落点就该是项目根，两处分开写迟早会出现"审计记录落在别处"
    的静默错位。

    `resume=True`（`agentflow run-agent --resume`，即 `--resume`）先读步检查点，四种结局分开（不许把"没读到"
    折成"重跑一遍"）：读不到 ⇒ `no_checkpoint`；任务指纹不符 ⇒ `checkpoint_mismatch`（拿 A 的进度续 B = 把两
    件事混成一条）；上一趟已收工（`final`）⇒ `already_finished`；停在等用户 / 其它 ⇒ 从 `resume_transcript`
    重建的那一段接着跑。无论哪条路，跑完都写一次步检查点（停在等用户时带 `waiting_for=<qid>`）；被拒的那几条
    路也各写一条 `agent_run_start`（带 `resume_refused` 与 `resume_attempted_from`；`resumed_from` 只在真的
    接着跑时才写）。

    `monitoring_of`（D-53）：这一趟是不是"被唤醒开起来的监控回合"。非空 = 唤醒的理由，
    它让这一趟的第一条增量消息带上这一支的树形读数与出口限定，并把第一步的出口收窄成
    watch / guide / 补派 / 收口（`AgentLoop._monitor_refusal`，框架闸）。空串 = 普通回合，
    改前的行为一个字不变。
    """
    root = Path(session_root) if session_root is not None else Path(str(getattr(store, "root", "")))
    if not str(root):
        raise ValueError("run_role 需要 session_root，或一个带 root 的 store")
    if seam is None:
        seam = LlmSeam.for_role(role, session_root=root, gateway=gateway,
                                usd_budget=usd_budget, sid=sid, from_env=from_env)
    #: 装配失败的理由（空 = 装配成了 / 或者调用方自带一只）。 必须在分支之外初始化：
    #: 它只在"自动装配"那一支里被赋值，而下面对应的那一行无条件读它 —— 于是
    #: `run_role(..., secretary=<自带的一只>)` 这条路会抛 `UnboundLocalError`
    #: （2026-10-21 实测：本文件的新判据把秘书传进来时当场炸，而那是公开形参）。
    secretary_problem: str = ""
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
    # ---- D-53：这一趟是不是"被唤醒开起来的监控回合"（由 `autonomy` 在轮边界上判定）。
    # 它让第一条增量消息带上树形读数与出口限定，并在这一步上收窄出口（框架闸，
    # 见 `_monitor_refusal`）。空串 = 普通回合（改前行为一个字不变）。
    loop.monitor_of = str(monitoring_of or "")
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
    # ---- 用户指定单条执行的角色：自己给自己开名册行 + 读写面（业主 B-5）
    #
    # 为什么落在这里：B-5 之后 L 没有入边（没有任何角色能派它），于是"父的秘书
    # 在 `Conductor._register_roster` 里登记"这条路永远走不到 —— 而业主明确要求
    # 单条执行时同样有名册行与读写面。判定不在这里写死角色名：读
    # `leanscope.LEAN_ONLY_ROLES`（"由 Lean 开关决定存在性、只能由用户起"的那一批），
    # 于是将来若多一个同类角色，它自动得到同一份台账。
    # 失败姿态是 fail-open：拿不到名册/面 ⇒ 这一趟照跑，只在 `notes` 里留一句。
    solo_problem: str = ""
    if (secretary is not None and str(top_tid or "")
            and str(role) in _LEANSCOPE.LEAN_ONLY_ROLES):
        try:
            got = secretary.open_solo_entry(task_id=str(top_tid), task=str(task))
        except Exception as exc:  # noqa: BLE001 - 少一份名册不许带走这一趟
            solo_problem = f"单条执行的名册没登记（{type(exc).__name__}: {exc}）"
        else:
            solo_problem = str(got.get("problem") or "")
    if resume:
        cp = load_run_checkpoint(root, role, sid)
        if cp is None:
            # 2026-10-18（缺陷 ㉑，真机 `projects/t3a` 抓到）：检查点只在 `loop.run()`
            # 返回之后才写（本文件 6326 行），于是被 kill/崩溃的运行永远没有检查点 ——
            # 而"被 kill"恰恰是 `--resume` 存在的唯一理由。真机读数：t3a 跑了 97 次调用、
            # 40 条实验、$1.05，`--resume` 却回 `no_checkpoint`，一条活都接不上。
            # 但会话记录里有每一步（`agent_step` 事件）⇒ 用 `resume_messages` 重建：
            # 重建得出步数就接着跑（这不是"从第 1 步重跑"）；重建不出就仍然如实拒。
            _rebuilt, _step0 = resume_messages(root, role, sid, task=task)
            if _step0 > 0:
                cp = {"step": int(_step0), "task": str(task),
                      "fingerprint": _task_fingerprint(role, task),
                      "waiting_for": "", "stop_reason": ""}
            else:
                _note_resume_refusal(root, role, task, sid, "no_checkpoint", task_id=top_tid)
                return LoopRun(role=role, task=task, stop_reason="no_checkpoint",
                               final=(f"要求续跑，但既读不到检查点"
                                      f"（{run_checkpoint_path(root, role, sid)}），"
                                      "也重建不出会话记录里的任何一步 ⇒ 没查成。"
                                      "不许当成'从第 1 步重跑'：重跑会把已经做过的活再做一遍。"))
        if str(cp.get("fingerprint")) != _task_fingerprint(role, task):
            # 指纹不符时「不给」 `attempted_from`：那份检查点是另一个任务的，
            # 它的 `step` 数不是"这件事做到第几步"。
            _note_resume_refusal(root, role, task, sid, "checkpoint_mismatch", task_id=top_tid)
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
                                 attempted_from=int(cp.get("step") or 0), task_id=top_tid)
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
                                     attempted_from=int(cp.get("step") or 0), task_id=top_tid)
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
                                 attempted_from=int(cp.get("step") or 0), task_id=top_tid)
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
                                  spend=run.spend,
                                  # 与 `spend` 同源、同一刻：`run()` 末尾（收工汇总那一节）
                                  # 已经把它算好了，这里只是把它一起落盘 —— 此前只传了
                                  # `spend`，于是顶趟的检查点里没有这一格（根因不是
                                  # "先写文件后算汇总"，而是写文件这条路自己拼了一份
                                  # 9 格的 dict，没拿到 `LoopRun` 的这一面）。
                                  prompt_cache=run.prompt_cache)
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

def _surface_root_decision(surface: str) -> tuple[str, bool]:
    """这一趟该不该把 `fs.*` 的根切到面上：返回（要用的面；空串 = 不切）与"是否因空而退回"。

    口径（2026-10-22 真机）：空面不算切面。切面是为了"把这一趟要用的那一块切进来"；
    切一个空目录进去等于把这一趟的手脚绑住（真机上 G 因此读不到 `out/paper/main.tex`）。
    面读不到（路径不存在 / 不是目录）与面是空的同属"不切"这一档，但两者都留痕，
    不许静默退回项目根冒充"面切过了"。
    """
    text = str(surface or "")
    if not text:
        return "", False
    path = Path(text)
    try:
        if not path.is_dir():
            return "", True
        if not any(path.iterdir()):
            return "", True
    except OSError:
        return "", True
    return text, False

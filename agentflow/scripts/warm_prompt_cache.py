"""把十个角色 + 秘书的提示词前缀**写进上游缓存**，并把当次读数落成可复核的 JSON。

## 先说结论：本仓**没有**"写缓存"的开关

上游（DeepSeek）的前缀缓存是**服务端自动**的：请求体里没有 `cache_control`，也没有
`AGENTFLOW_*_CACHE` 这类环境变量。全仓 grep `cache_control` 命中 0 处；`modelgw.py`
的 `_payload`（`:739-764`）只拼 `model` / `messages` / `temperature` / `stream` /
推理强度 / `tools`，一个缓存注解都没有。

于是"写缓存"这件事的唯一开关是**前缀逐字节相同**：上游自己对没命中的那部分建索引，
下一次同前缀的请求就命中。读数那一侧才有字段：`usage.prompt_cache_hit_tokens` /
`prompt_cache_miss_tokens`（`modelgw.py:878-888` 读进来 → `llmseam.py:477-478`
转成 `SeamCall` 两格 → `promptstability.prompt_cache_record` 成形）。

**上游没有"写"这个计数**。本脚本里的 `write` 是**推导量**：一次调用里被上游建索引的
就是它报的 miss 那部分（`write = prompt_cache_miss_tokens`），并在读数里标
`write_source="derived:miss"`。上游没给这两格时三者都是 `None`（unknown，绝不折成 0）。

## 这个脚本发的是什么请求（为什么它和生产对得上）

每个角色发的形状与 `agent_loop` 生产路径一致：

    tools = llmseam.build_tool_face(role, registry)     # 原生工具面（生产也发这个）
    system = agent_prompts.system_prompt(role, registry=..., **split_facts(facts))
    user   = 一句话"只回 OK"                            # 生产的第 0 条 user 是开场白，
                                                        # 它在前缀之后 ⇒ 不影响命中

`facts` 用 `promptstability.split_facts` 过一遍 —— 与生产同一个函数，于是 system 里
**会变的事实全是静态指路语**（`budget_left` / `notebook` / `task` / `task_id` / `depth` /
`parent_task_id` / `summoned_by` / `children` / `board` / `inbox` / `user_replies` /
`workspace_root`，见 `promptstability.STEP_VOLATILE_FACTS`）。

秘书那一档（2026-10-21 起与十个角色**同形**）：`Secretary.judge` 调
`seam.ask_json(material, system=_judge_system(kind))` —— 稳定头进 system、
材料留在 user。所以秘书那一行的预热对象是 `_judge_system(kind)` 那一段，
user 消息是空材料的形状（`材料：` + 一份 JSON）。改前它整条都在 user 位
（`system=""`），实测连发两趟 `hit=0 / miss=175`。

## 内置花费上限

`LlmSeam(usd_budget=--cap-usd)`（默认 0.10 美元）是真闸：每发一次请求之前它自己比一次
全局已花（`llmseam.ask` 的前两个分支），超了就返回 `judge_over_budget` 而**不发请求**。
本脚本在它之外再预检一次（`spent >= cap` ⇒ 干净停下并说"剩下的没预热"），
于是"超上限"不会被误读成"某一个角色预热失败"。

## 幂等 / 可重复

同一 scenario 再跑一遍：同样的 prompt_sha256、同样的 system/tools 摘要，第二趟的
`hit` 会接近满、`write` 接近 0（这正是判据 ② 要的那一跳）。所以**重复跑是安全的**，
而且它本身就是"缓存真的落了盘"的证明。

## 退出码（三态，与 `noai_gate.py` / `release_check.py` 同一纪律）

```text
0 = warmed       查过了：点名的每个目标都有"写进去"的记录（write>0 或 hit>0）
1 = incomplete   查过了：有目标**没有**那条记录（调用失败 / 预算中途停 / 上游不给读数）
2 = unknown      **没查成**：没有模型 key、渲染不出来、写不出读数文件
```

`unknown` 绝不是 `warmed`。"没预热"与"预热了但上游没给读数"也是两件事：
后者是本文件里 `known=false` 的那一档，它算 `incomplete`（那块缓存有没有落地**不可判定**）。
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import agent_prompts as AP  # noqa: E402
from agentflow import modelgw as MG  # noqa: E402
from agentflow import promptstability as PSTAB  # noqa: E402
from agentflow.llmseam import LlmSeam, build_tool_face  # noqa: E402

EXIT_WARMED = 0
EXIT_INCOMPLETE = 1
EXIT_UNKNOWN = 2

#: 十个角色（`agent_prompts.ROLE_BRIEFS` 的键；与 `tools.ROLES` 同源）。
ROLES: tuple[str, ...] = ("A", "B", "C", "D", "E", "F", "G", "H", "V", "M")

#: 秘书那一档在读数里的名字（它不是 `ROLE_BRIEFS` 的键：秘书没有 system 提示词）。
SECRETARY = "secretary"

#: 要预热的目标全集 —— `--roles` 的缺省值，也是文档里那条命令的写法。
WARM_TARGETS: tuple[str, ...] = ROLES + (SECRETARY,)

#: 内置花费上限（美元）。超了自停，不是"跑完再说"。
DEFAULT_CAP_USD = 0.10

#: 做"第二次调用应该命中"那一跳的样本（省钱：只挑 2 个）。
#: 挑规则：`M` 是最大的一份（历史真机读数就是它），`C` 是最小的一份（最便宜的对照）。
DEFAULT_HIT_SAMPLE: tuple[str, ...] = ("M", "C")

#: 秘书那一档预热的是哪一类判断的提示词（`secretary.JUDGE_KINDS` 之一；
#: 稳定头的长度与类别无关，取一个确定性的即可）。
SECRETARY_KIND = "duplicate_retry"

#: 这一趟的"规范场景"。**必须逐字节确定性** —— 判据（`tests/test_prompt_cache_warm.py`）
#: 会用同一份事实重算一遍 prompt_sha256，对不上就说明提示词改了、该重新预热。
#:
#: 为什么几格取空串而不是取"这台机器上的真值"（`toolchain_facts` / `parent_limits`）：
#: 那几段读的是**这台机器的盘**（有没有 Lean、Mathlib 在哪），换机器就换个字节 ——
#: 判据会因此变成"只在这一台机器上绿"。它们的位置在 `TOOLCHAIN_FACTS` 之后（段序 > 86），
#: 而跨 run 能复用的前缀在第 95 个字符处就断了（见读数里的 `cross_run_prefix_chars`），
#: 所以"取空渲染"对可复用的那一段**一个字节都不损失**，换来的是判据的确定性。
CANONICAL_FACTS: Mapping[str, Any] = {
    "task": "预热：把这一份系统提示词的前缀写进上游缓存（不研究、不抓文献、只回 OK）",
    "summoned_by": "user",
    "task_id": "t-warm-0001",
    "depth": 1,
    "parent_task_id": "",
    "children": "",
    "board": "",
    "inbox": "（没有收到留言）",
    # 这两格会被 `split_facts` 换成静态指路语（生产里也是这两段）。
    "budget_left": "1.000000 美元",
    "notebook": "（草稿本还是空的）",
    "workspace_root": "",
    "availability": None,
    "user_replies": "",
    "toolchain_facts": "",
    "toolchain_formal": "",
    "parent_limits": "",
}

#: 预热请求里那条 user 消息：只要两个字，省输出 token（钱花在前缀上，不花在回答上）。
USER_PROMPT = "这是前缀预热：不要做任何工作，不要调用工具，只回两个字：OK"

#: "另一趟"的事实 —— 只用来算"跨 run 还能命中多少前缀"（`cross_run_prefix_chars`）。
#: 它模拟的是"同一个角色被派去做另一件活"：任务文本、台账号、深度、收件箱、板上、
#: 名册、用户答、工作区根全换，其余不变。
#:
#: 2026-10-21 之后这份事实**改变不了 system 一个字节**（上面那些格子全在
#: `promptstability.STEP_VOLATILE_FACTS` 里、全被换成静态指路语）⇒
#: `cross_run_prefix_chars` 应当等于整条 system 的长度，而真机读数里"换一趟活"的
#: 第一次调用就该命中（`cross_run_hit` 的两行）。这份事实因此变成了**判据的探针**：
#: 它一变 system 就变，说明有人把跨 run 会变的东西塞回了 system。
OTHER_RUN_FACTS: Mapping[str, Any] = {
    **dict(CANONICAL_FACTS),
    "task": "另一件完全不同的活：核一条引文。",
    "task_id": "t-other-0002",
    "depth": 2,
    "parent_task_id": "t-parent-0003",
    "children": "- A1（working）",
    "board": "- 一条板项",
    "inbox": "- [m-0001] 一条留言",
    "user_replies": "- [q-0001] 问：… → 用户答（user）：…",
    "workspace_root": "/tmp/another-workspace",
    # ---- 2026-10-21 第二批：**另一份伙伴配置**（不只是另一件活）。
    #
    # `availability`（`host.wiring_status` 的读数）与 `parent_limits`（`Policy` 的数字）
    # 此前住在 system 里（段序 4520 / 5210），于是"换一份伙伴配置"在这里会表现为
    # 前缀从 63% / 88% 处断开 —— 跨 run 探针那一行（`pass=4`，第一次见这份 system）
    # 的 `hit` 就是"换配置之后还剩多少前缀"的实测值。
    # 改后它们只在开场那条 user 消息里（消息不是前缀）⇒ `pass=4` 也该≥90%。
    # 判据：`tests/test_cross_run_prefix_is_reused.py::test_two_partner_configs_hit_...`。
    "availability": {"A": "no_provider", "B": "wired", "C": "no_key", "D": "wired",
                     "E": "wired", "F": "wired", "G": "wired", "H": "wired", "V": "wired"},
    "parent_limits": ("这一次 run 的派活上限（现算读数，不是记忆）：\n"
                      "- （另一份配置：同时在飞 7 个、墙钟不限）"),
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def lean_mode() -> bool:
    """这一趟渲染用的是哪一档形式化开关（`True` = 走 Lean 那一套提示词）。

    ## 为什么必须记下来、而且必须读这**一个**来源

    `system_prompt` 会在"形式化关着"那一档把 Lean 相关的段整段换掉
    （`_apply_no_lean_variant`），所以同一份代码在开关两档下渲染出的 system
    **不是同一段前缀** —— 预热在关着那一档落的，判据就得在关着那一档重算，
    否则摘要对不上，而"对不上"看起来就像"提示词被人改了"。

    来源选 `agent_prompts._lean_switch()` 而不是 `settings.lean_enabled()`：
    前者是渲染真正读的那个闩（`lru_cache` 住的那一格），后者是它的上游 ——
    两条路各读一次就可能各给一个答案（缓存暖着、env 又被改过时），
    而"渲染按哪一档走的"只有一个正确答案：渲染读到的那个。
    """
    try:
        return bool(AP._lean_switch()[0])       # noqa: SLF001 —— 见 docstring：唯一真身
    except Exception:                            # noqa: BLE001 —— 读不到就当"关着"（产品缺省）
        return False


#: 读数文件里保留最近几趟（`{"schema": 1, "runs": [<一趟的读数>, …]}`）。
#:
#: ## 为什么是一个**容器**而不是"最近一次快照"
#:
#: 一次预热只能回答"写进去了"，"下次跑能命中"这个问题要**第二趟**才答得出。
#: 而"第二趟"必然把第一趟的冷写读数覆盖掉 —— 那等于用一个更弱的读数换掉一个更强的
#: （"命中"能证明"写过"以外的更多事，但"写过"这一格就没了）。所以两趟都留着。
#: 键集仍然只有一个来源（本文件），`MAX_RUNS_KEPT` 防止它无限长。
MAX_RUNS_KEPT = 8


def load_readings(path: Path) -> list[dict[str, Any]]:
    """读读数文件里的历次预热（读不到/读坏了 ⇒ 空表，**不是**"没有记录就是没问题"）。"""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    runs = doc.get("runs") if isinstance(doc, dict) else None
    if isinstance(runs, list):
        return [r for r in runs if isinstance(r, dict)]
    # 兼容旧的"单趟快照"形态（`{"schema":1, "rows":[…], …}`）：当成一趟。
    if isinstance(doc, dict) and isinstance(doc.get("rows"), list):
        return [doc]
    return []


def save_readings(path: Path, runs: list[dict[str, Any]]) -> None:
    """把历次预热写回去（只留最近 `MAX_RUNS_KEPT` 趟）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema": 1, "runs": runs[-MAX_RUNS_KEPT:]}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def _ensure_utf8_stdout() -> None:
    """Windows 控制台默认 GBK：打印 `⇒` / `√` 会抛 `UnicodeEncodeError`（`test_cli_console_encoding`）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 —— 不是文本流 / 老 Python：不打字总比崩掉好
            pass


# ---------------------------------------------------------------- 渲染（判据共用这一份）


def _registry(workspace: Path) -> Any:
    """造一份与生产同形的工具注册表（`build_registry(strict=True)`）。"""
    from agentflow.store import Store
    from agentflow.tools import ROLES as TOOL_ROLES
    from agentflow.tools import build_registry

    ws = workspace / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    store = Store(ws)
    store.init()
    return build_registry(store=store, workspace_root=ws,
                          roles=tuple(TOOL_ROLES), strict=True).registry


def _render_system(role: str, registry: Any, facts: Mapping[str, Any]) -> str:
    """按生产路径渲染一份 system（`split_facts` → `system_prompt`）。"""
    system_facts, _moved = PSTAB.split_facts(facts)
    return AP.system_prompt(role, registry=registry, **system_facts)


def _secretary_head() -> tuple[str, int]:
    """秘书的**稳定头**（进 `system` 那一位的那一段）与它的长度。

    2026-10-21 之前：`Secretary.judge`（`secretary.py:1325`）调的是
    `seam.ask_json(prompt)` —— **不带 system**，抬头 + 问题 + 材料全在一条 user 消息里，
    而材料每问一次都变。真机读数（`2026-10-21`，本脚本 `--roles secretary
    --hit-sample secretary`）：连发两趟都是 `hit=0 / miss=175`。

    现在：`_judge_system(kind)` 走 `system=`，`_judge_material(context)` 留在 user。
    于是可预热的那一段就是 **system 本身**（`prefix_chars = len(system)`），
    而它与"这一趟问的是什么材料"无关 —— 换一份材料照样命中。
    """
    from agentflow.secretary import _judge_system

    system = _judge_system(SECRETARY_KIND)
    if not system.strip():                  # 提示词形状变了：如实报错，不猜一个长度
        raise ValueError("秘书的稳定头是空的 —— 形状变了，预热对象不可判定")
    return system, len(system)


def _secretary_material() -> str:
    """秘书那条 user 消息（可变部分）：空材料的形状（`材料：` + 一份 JSON）。

    与 `_judge_system` 合起来逐字节等于 `secretary._judge_prompt(kind, {})`
    （判据：`tests/test_secretary_system_carries_the_head.py`）。
    """
    from agentflow.secretary import _judge_material

    return _judge_material({})


def render_prompts(*, targets: tuple[str, ...] = WARM_TARGETS,
                   workspace: Path | None = None) -> dict[str, dict[str, Any]]:
    """渲染每个目标的 (system, tools, 摘要, 跨 run 可复用前缀长度) —— **不联网、不花钱**。

    判据（`tests/test_prompt_cache_warm.py`）与真机入口共用这一份实现：两边各写一份
    就会漂，而"漂了"在读数上长得像"提示词改了、该重新预热"。

    返回 `{target: {...}}`，每项含：`kind`（`system` / `judge_head`）、`system`、
    `prompt`、`system_sha256`、`prompt_sha256`、`system_chars`、`prompt_chars`、
    `tools`（`ToolFace` 的函数面或空表）、`tools_sha256`、`tools_functions`、
    `tools_chars`、`prefix_chars`（这一次请求前缀里**确定稳定**的那部分）、
    `cross_run_prefix_chars`（换一趟活之后仍在前缀里的那部分）。
    """
    tmp = Path(workspace) if workspace is not None else Path(
        tempfile.mkdtemp(prefix="warm-render-"))
    own_tmp = workspace is None
    try:
        registry = _registry(tmp)
        out: dict[str, dict[str, Any]] = {}
        for target in targets:
            if target == SECRETARY:
                system, stable = _secretary_head()
                prompt = _secretary_material()
                face = None
                # 秘书的可复用前缀就是它的 system（材料在 user 位，且每问一次都变）。
                cross = stable
                out[target] = {
                    "kind": "judge_system",
                    "system": system,
                    "prompt": prompt,
                    "system_sha256": _sha(system),
                    "prompt_sha256": _sha(system),
                    "system_chars": len(system),
                    "prompt_chars": len(prompt),
                    "tools": (),
                    "tools_sha256": "",
                    "tools_functions": 0,
                    "tools_chars": 0,
                    "prefix_chars": stable,
                    "cross_run_prefix_chars": cross,
                }
                continue
            face = build_tool_face(target, registry)
            system = _render_system(target, registry, CANONICAL_FACTS)
            other = _render_system(target, registry, OTHER_RUN_FACTS)
            diff = PSTAB.first_difference(system, other)
            tools_text = json.dumps(list(face.functions), ensure_ascii=False,
                                    sort_keys=True, default=str)
            out[target] = {
                "kind": "system",
                "system": system,
                "prompt": USER_PROMPT,
                "system_sha256": _sha(system),
                "prompt_sha256": _sha(system),
                "system_chars": len(system),
                "prompt_chars": len(USER_PROMPT),
                "tools": face.functions,
                "tools_sha256": face.sha256,
                "tools_functions": len(face.functions),
                "tools_chars": len(tools_text),
                # 这一次请求的稳定前缀 = 整个 system（两次渲染逐字节相同才成立，
                # 判据会重算一遍；这里只是把它记下来）。
                "prefix_chars": len(system),
                "cross_run_prefix_chars": (diff["common_prefix_chars"] if diff else len(system)),
            }
        return out
    finally:
        if own_tmp:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 预热（真机）


def _other_facts(stamp: str) -> dict[str, Any]:
    """`OTHER_RUN_FACTS` 的一份**这一次没用过**的实例（task_id 带时间戳）。

    为什么必须每趟换一个 task_id：诊断行要回答的是"**第一次**见到这份 system 时
    能命中多少"。若沿用固定的 `t-other-0002`，第二次跑本脚本时它已经被上一次
    探针写进缓存 ⇒ 同一个读数从 0 变成 99%，而原因不是提示词变了，是"这次是第二次"。
    """
    facts = dict(OTHER_RUN_FACTS)
    facts["task_id"] = f"t-other-{stamp}"
    return facts


def _record_of(target: str, item: Mapping[str, Any], call: Any, *, pass_no: int,
               at: str) -> dict[str, Any]:
    """一次调用的读数行（含 `write` 的推导与三态）。

    `prompt_sha256` 在这一份读数里的口径：**这一行被预热的那段提示词**的 sha256 ——
    2026-10-21 起十一个目标**同形**：都是真正发出去的那条 `system`（秘书也是）。
    `system_sha256` / `user_sha256` 两格分别给出真正发出去的两条消息的摘要，
    于是"预热的是哪一段"不必靠字段名猜。
    """
    cache = PSTAB.prompt_cache_record(call)
    hit = cache["prompt_cache_hit_tokens"]
    miss = cache["prompt_cache_miss_tokens"]
    known = bool(cache["known"])
    took = (hit + miss) if known else 0
    return {
        "role": target,
        "kind": str(item["kind"]),
        "pass": int(pass_no),
        "at": at,
        "ok": bool(getattr(call, "ok", False)),
        "problem": str(getattr(call, "problem", "") or ""),
        "detail": str(getattr(call, "detail", ""))[:300],
        "requested": bool(cache["called"]),
        "model": str(getattr(call, "model", "") or ""),
        "system_sha256": str(item["system_sha256"]),
        "user_sha256": _sha(str(item["prompt"])),
        "prompt_sha256": str(item["prompt_sha256"]),
        "system_chars": int(item["system_chars"]),
        "prompt_chars": int(item["prompt_chars"]),
        "tools_sha256": str(item["tools_sha256"]),
        "tools_functions": int(item["tools_functions"]),
        "tools_chars": int(item["tools_chars"]),
        "prefix_chars": int(item["prefix_chars"]),
        "cross_run_prefix_chars": int(item["cross_run_prefix_chars"]),
        "cache": {
            "known": known,
            "hit": hit,
            "miss": miss,
            # 上游没有独立的写计数：被写进索引的就是 miss 那部分（见模块 docstring）。
            "write": miss,
            "write_source": "derived:miss",
            "tokens_in": int(cache["tokens_in"]),
            "tokens_out": int(cache["tokens_out"]),
            "hit_rate": (round(hit / took, 4) if known and took else None),
            "cache_tri": str(cache["cache_tri"]),
            "usd_per_m_in": cache["usd_per_m_in"],
            "usd_per_m_in_hit": cache["usd_per_m_in_hit"],
            "usd_per_m_out": cache["usd_per_m_out"],
        },
        "usd": (None if getattr(call, "usd", None) is None else round(float(call.usd), 6)),
        "elapsed_sec": round(float(getattr(call, "elapsed_sec", 0.0) or 0.0), 3),
    }


def warm(targets: tuple[str, ...] = WARM_TARGETS, *, cap_usd: float = DEFAULT_CAP_USD,
         hit_sample: tuple[str, ...] = DEFAULT_HIT_SAMPLE, model: str = "",
         effort: str = "off", out_path: Path | None = None,
         dry_run: bool = False, keep_session: bool = False,
         session_root: Path | None = None, tools_probe: str = "",
         cross_run_probe: str = "") -> tuple[int, dict[str, Any]]:
    """按目标各发**一次**最小请求（再给样本各补一次），把读数写成 JSON。

    `effort="off"` 是省钱不是省字节：推理强度不进 `messages`，**不改变缓存前缀**，
    但它决定"它想多久才回那两个字"（默认 `high` 会为一句 OK 写上千字思维链）。

    `tools_probe`（可选）回答一个本脚本**必须**回答的问题：**工具面在不在缓存前缀里**？
    做法：拿一个已经带工具面预热过的目标，把同一个 system 在**不带工具面**的情况下再发一次。

    - `hit > 0` ⇒ 缓存只按 `messages` 建索引（工具面不在前缀里）；
    - `hit == 0` ⇒ 工具面在它的前缀里（去掉工具 = 换了一段前缀）。
    """
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rendered = render_prompts(targets=targets)
    empty = [t for t in targets if not (rendered[t]["system"] or rendered[t]["prompt"])]
    if empty:
        return EXIT_UNKNOWN, {"verdict": "unknown",
                              "error": f"这些目标渲染不出提示词（空串）：{empty}"}

    if dry_run:
        rows = [{"role": t, "kind": rendered[t]["kind"],
                 "system_chars": rendered[t]["system_chars"],
                 "tools_chars": rendered[t]["tools_chars"],
                 "prompt_sha256": rendered[t]["prompt_sha256"],
                 "cross_run_prefix_chars": rendered[t]["cross_run_prefix_chars"]}
                for t in targets]
        return EXIT_WARMED, {"verdict": "dry_run", "rows": rows,
                             "note": "只渲染，没发请求，花费 0 美元"}

    # 配置走**生产那一口** `spec_from_env()`（唯一入口：key 的取值梯子只有一份）。
    # 覆盖模型名 / 推理强度用 `dataclasses.replace` 而不是自己拼一份 env ——
    # `settings.model_settings(env=…)` 在"注入环境但没给 AGENTFLOW_SETTINGS"时
    # 读不到设置文件（真机实测：那样造出来的 spec `configured=False`，
    # 于是明明配了 key 却报"没有模型 key"）。
    spec = MG.spec_from_env()
    if model:
        spec = dataclasses.replace(spec, model=str(model))
    if effort:
        spec = dataclasses.replace(spec, reasoning_effort=str(effort))
    if not spec.configured:
        return EXIT_UNKNOWN, {
            "verdict": "unknown",
            "error": (f"没有模型 key（{MG.ENV_KEY} 与 settings.json 的 model.api_key 都没有值）"
                      "—— 这是没查成，不是'预热失败'"),
        }

    own_session = session_root is None
    root = Path(session_root) if session_root is not None else Path(
        tempfile.mkdtemp(prefix="warm-session-"))
    tmp_registry = Path(tempfile.mkdtemp(prefix="warm-registry-"))
    try:
        registry = _registry(tmp_registry)
        faces = {t: build_tool_face(t, registry) for t in targets if rendered[t]["tools"]}
        seam = LlmSeam(role="cache-warm", session_root=root,
                       gateway=MG.ModelGateway(spec), usd_budget=float(cap_usd),
                       scope="reason", sid="prompt-cache-warm")
        rows: list[dict[str, Any]] = []
        stopped = ""
        plan: list[tuple[str, int]] = [(t, 1) for t in targets]
        plan += [(t, 2) for t in hit_sample if t in targets]
        if tools_probe in targets:
            plan.append((tools_probe, 3))       # 诊断行：同一 system、**不带工具面**
        if cross_run_probe in targets:
            # 诊断行（两次）：**另一趟活**的 system 发两遍。
            # 为什么必须两遍：第一遍回答"换一趟活还剩多少（=0）"，第二遍回答
            # "同一份 system 再发一次会不会命中（=会）"。只发一遍的话，第二次跑本脚本时
            # 那一份 system 已经被上一次探针写进缓存了 ⇒ 读数从 0 变成 99%，
            # 而读者分不出是"这次变了"还是"这次是第二次"。`_other_facts()` 因此给
            # 每一次调用生成一个**没被发过**的 task_id，让第一遍永远是"第一次见"。
            plan.append((cross_run_probe, 4))
            plan.append((cross_run_probe, 5))

        for target, pass_no in plan:
            spent, source = seam.spent_usd()
            if spent >= float(cap_usd):
                stopped = (f"已花 {spent:.6f} / 上限 {cap_usd:.6f}（读数来自 {source}）"
                           f"⇒ 剩下的 {len(plan) - len(rows)} 次调用**没有发**")
                break
            item = rendered[target]
            if pass_no in (4, 5):
                # 换成"另一趟活"的 system（任务/台账号/深度/收件箱全不同）：
                # 这一发的 hit 就是"换一趟活之后还剩多少前缀能复用"的实测值。
                # `prompt_sha256` 也跟着换 —— 它是"这一行预热的是哪一段"的身份，
                # 换了 system 还挂旧摘要，读数就在说谎（判据按它分组，会当场对不上）。
                other_facts = _other_facts(at)
                other = _render_system(target, registry, other_facts)
                item = {**item, "system": other, "system_sha256": _sha(other),
                        "prompt_sha256": _sha(other), "system_chars": len(other),
                        "cross_run_prefix_chars":
                            rendered[target]["cross_run_prefix_chars"]}
            face = None if pass_no == 3 else faces.get(target)
            call = seam.ask(str(item["prompt"]), system=str(item["system"]),
                            task_id=str(CANONICAL_FACTS["task_id"]),
                            note=f"warm:{target}#{pass_no}", face=face)
            rows.append(_record_of(target, item, call, pass_no=pass_no, at=at))

        spent, source = seam.spent_usd()
        by_role: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if int(row["pass"]) > 2:       # 诊断行不参与"这个目标预热了吗"
                continue
            by_role.setdefault(str(row["role"]), []).append(row)
        missing = [t for t in targets
                   if not any((r["cache"]["write"] or 0) > 0 or (r["cache"]["hit"] or 0) > 0
                              for r in by_role.get(t, []))]
        unknown_cache = [t for t in targets
                         if any(not r["cache"]["known"] for r in by_role.get(t, []))]
        failed = [f"{r['role']}#{r['pass']}: {r['problem']}" for r in rows if not r["ok"]]
        samples = {t: [r for r in by_role.get(t, []) if r["pass"] == 2] for t in hit_sample}
        sample_miss = [t for t, rs in samples.items()
                       if not rs or not (rs[0]["cache"]["hit"] or 0) > 0]
        probe_rows = [r for r in rows if int(r["pass"]) == 3]
        tools_in_prefix: bool | None = None
        if probe_rows:
            got = probe_rows[0]["cache"]["hit"]
            tools_in_prefix = None if got is None else (int(got) == 0)
        cross_rows = [r for r in rows if int(r["pass"]) in (4, 5)]

        result: dict[str, Any] = {
            "schema": 1,
            "at": at,
            "verdict": "",
            "cap_usd": float(cap_usd),
            "spent_usd": round(float(spent), 6),
            "spent_source": source,
            "model": str(getattr(spec, "model", "") or ""),
            "base_url": str(getattr(spec, "base_url", "") or ""),
            "reasoning_effort": str(getattr(spec, "reasoning_effort", "") or ""),
            "prompt_version": AP.PROMPT_VERSION,
            # 这一趟的提示词是哪一档形式化开关下渲染的（见 `lean_mode`）：
            # 判据要按同一档重算摘要，否则"对不上"会被误读成"提示词改了"。
            "lean_enabled": lean_mode(),
            "roles": list(targets),
            "hit_sample": list(hit_sample),
            "stopped": stopped,
            "rows": rows,
            "missing": missing,
            "unknown_cache": unknown_cache,
            "failed_calls": failed,
            "sample_without_hit": sample_miss,
            # 工具面在不在缓存前缀里（None = 没做这个诊断 / 上游没给读数）。
            "tools_in_prefix": tools_in_prefix,
            "tools_probe": tools_probe,
            "cross_run_probe": cross_run_probe,
            # "换一趟活（不同 task/task_id/depth）之后实测还能命中多少"：
            # 这一格比 `cross_run_prefix_chars`（离线算的字符数）硬 —— 那边是推理，这边是读数。
            # 两行：`pass=4` 是**第一次见**这份 system（应当 0 命中），
            # `pass=5` 是同一份再发一次（应当接近满命中）。两行一起才说明白
            # "命中条件是前缀逐字节相同"，而不是"缓存坏了 / 缓存很好"。
            "cross_run_hit": ([{"role": r["role"], "pass": int(r["pass"]),
                                "cross_run_prefix_chars": r["cross_run_prefix_chars"],
                                "hit": r["cache"]["hit"], "miss": r["cache"]["miss"],
                                "tokens_in": r["cache"]["tokens_in"]}
                               for r in cross_rows] if cross_rows else None),
            "note": "",
        }
        # 先定结论、再落盘：读数文件里必须**带着结论**写下去。
        # 反例（本脚本第一版就是这个形态）：先写文件后判结论 ⇒ 盘上 `verdict` 恒为空串，
        # 而"没判过"与"判过了没问题"在读者眼里长得一模一样（三态纪律）。
        incomplete = bool(missing or unknown_cache or failed or sample_miss or stopped)
        bits: list[str] = []
        if missing:
            bits.append(f"没有落地记录的目标：{missing}")
        if unknown_cache:
            bits.append(f"上游没给缓存读数的目标：{unknown_cache}")
        if failed:
            bits.append(f"失败调用：{failed[:4]}")
        if sample_miss:
            bits.append(f"第二次调用没命中的样本：{sample_miss}")
        if stopped:
            bits.append(stopped)
        result["verdict"] = "incomplete" if incomplete else "warmed"
        result["note"] = ("；".join(bits) if incomplete else
                          f"{len(targets)} 个目标都有缓存落地记录；"
                          f"二调样本 {list(hit_sample)} 命中；花费 {spent:.6f} 美元")

        if out_path is not None:
            runs = load_readings(out_path)
            runs.append({k: v for k, v in result.items() if k != "out"})
            save_readings(out_path, runs)
            result["out"] = str(out_path)
            result["runs_in_file"] = min(len(runs), MAX_RUNS_KEPT)
        return (EXIT_INCOMPLETE if incomplete else EXIT_WARMED), result
    finally:
        shutil.rmtree(tmp_registry, ignore_errors=True)
        if own_session and not keep_session:
            shutil.rmtree(root, ignore_errors=True)


def _table(rows: list[dict[str, Any]]) -> str:
    """人读的那张表（一行一个目标；逐格对齐，Windows 控制台下也不花）。"""
    head = (f"{'role':<10}{'pass':>4}{'sys_chars':>10}{'tools':>7}"
            f"{'tokens_in':>10}{'write':>8}{'hit':>8}{'hit_rate':>10}{'usd':>10}")
    lines = [head, "-" * len(head)]
    for row in rows:
        cache = row["cache"]
        rate = cache["hit_rate"]
        lines.append(
            f"{row['role']:<10}{row['pass']:>4}{row['system_chars']:>10}"
            f"{row['tools_functions']:>7}{cache['tokens_in']:>10}"
            f"{(cache['write'] if cache['write'] is not None else 'unknown'):>8}"
            f"{(cache['hit'] if cache['hit'] is not None else 'unknown'):>8}"
            f"{('unknown' if rate is None else f'{rate * 100:.1f}%'):>10}"
            f"{(row['usd'] if row['usd'] is not None else 'unknown'):>10}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 入口


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    parser = argparse.ArgumentParser(
        description="把十个角色 + 秘书的提示词前缀写进上游缓存（幂等、内置花费上限）",
    )
    parser.add_argument("--roles", default=",".join(WARM_TARGETS),
                        help=f"要预热的目标，逗号分隔（缺省 {','.join(WARM_TARGETS)}）")
    parser.add_argument("--hit-sample", default=",".join(DEFAULT_HIT_SAMPLE),
                        help="再调一次、验证命中的样本（缺省 2 个：省钱的取舍）")
    parser.add_argument("--cap-usd", type=float, default=DEFAULT_CAP_USD,
                        help=f"总花费上限（美元，缺省 {DEFAULT_CAP_USD}）")
    parser.add_argument("--model", default="", help=f"覆盖模型名（缺省取 {MG.ENV_NAME} / 设置文件）")
    parser.add_argument("--effort", default="off",
                        help="推理强度（缺省 off：它不改变缓存前缀，只省输出 token）")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[1]
                                            / "tests" / "fixtures" / "prompt_cache_warm.json"),
                        help="读数 JSON 的落点")
    parser.add_argument("--dry-run", action="store_true",
                        help="只渲染、不发请求（花费 0 美元）")
    parser.add_argument("--keep-session", action="store_true",
                        help="保留这一趟的会话记录（缺省用临时目录并在收尾删净）")
    parser.add_argument("--probe-no-tools", default="",
                        help="诊断：拿这个目标（须在 --roles 里、且是最后一步）"
                             "在不带工具面的情况下再发一次，用来看"
                             "「工具面在不在缓存前缀里」；空 = 不做")
    parser.add_argument("--probe-cross-run", default="",
                        help="诊断：拿这个目标换一份「另一趟活」的 system（不同 "
                             "task/task_id/depth）再发一次，用来看「换一趟活还剩多少前缀"
                             "能复用」；空 = 不做")
    args = parser.parse_args(argv)

    targets = tuple(x.strip() for x in str(args.roles).split(",") if x.strip())
    bad = [t for t in targets if t not in WARM_TARGETS]
    if not targets or bad:
        print(f"[unknown] --roles 里有没登记的目标：{bad}（认 {list(WARM_TARGETS)}）")
        return EXIT_UNKNOWN
    sample = tuple(x.strip() for x in str(args.hit_sample).split(",") if x.strip())
    if any(t not in targets for t in sample):
        print(f"[unknown] --hit-sample 必须是 --roles 里的目标：{sample}")
        return EXIT_UNKNOWN
    probe = str(args.probe_no_tools or "").strip()
    if probe and probe not in targets:
        print(f"[unknown] --probe-no-tools 必须是 --roles 里的目标：{probe!r}")
        return EXIT_UNKNOWN
    cross = str(args.probe_cross_run or "").strip()
    if cross and (cross not in targets or cross == SECRETARY):
        print(f"[unknown] --probe-cross-run 必须是 --roles 里的某个角色（不能是秘书）：{cross!r}")
        return EXIT_UNKNOWN

    try:
        code, result = warm(targets, cap_usd=float(args.cap_usd), hit_sample=sample,
                            model=str(args.model), effort=str(args.effort),
                            out_path=Path(args.out), dry_run=bool(args.dry_run),
                            keep_session=bool(args.keep_session), tools_probe=probe,
                            cross_run_probe=cross)
    except Exception as exc:  # noqa: BLE001 —— 渲染/写盘炸了属于"没查成"
        print(f"[unknown] 预热没跑起来：{type(exc).__name__}: {exc}")
        return EXIT_UNKNOWN

    if result.get("verdict") == "unknown":
        print(f"[unknown] {result.get('error')}")
        return EXIT_UNKNOWN

    print(f"[{result['verdict']}] 花费 {result.get('spent_usd', 0.0):.6f} / 上限 "
          f"{result.get('cap_usd', args.cap_usd):.2f} 美元"
          f"（模型 {result.get('model') or '（没发请求）'}，"
          f"推理强度 {result.get('reasoning_effort') or 'n/a'}）")
    if result["verdict"] == "dry_run":
        print(f"{'role':<10}{'kind':<12}{'sys_chars':>10}{'tools':>8}"
              f"{'cross_run':>10}  prompt_sha256")
        for row in result["rows"]:
            print(f"{row['role']:<10}{row['kind']:<12}{row['system_chars']:>10}"
                  f"{row['tools_chars']:>8}{row['cross_run_prefix_chars']:>10}  "
                  f"{row['prompt_sha256'][:16]}")
        print("（--dry-run：一个请求都没发）")
        return code

    print(_table(list(result["rows"])))
    if result.get("tools_in_prefix") is not None:
        print(f"工具面在缓存前缀里：{'是' if result['tools_in_prefix'] else '否'}"
              f"（诊断：目标 {result.get('tools_probe')} 去掉工具面后再发一次，"
              f"hit={[r['cache']['hit'] for r in result['rows'] if r['pass'] == 3]}）")
    if result.get("cross_run_hit"):
        for got in result["cross_run_hit"]:
            print(f"跨 run 实测（{got['role']}，第 {'一' if got['pass'] == 4 else '二'}次见这份 "
                  f"system）：命中 {got['hit']} / 未命中 {got['miss']} token"
                  f"（可复用前缀 {got['cross_run_prefix_chars']} 字符，"
                  f"整份 system {got['tokens_in']} token）")
    if result.get("out"):
        print(f"读数已写入 {result['out']}")
    if result.get("note"):
        print(result["note"])
    print("再落一次：python scripts/warm_prompt_cache.py "
          "--roles A,B,C,D,E,F,G,H,V,M,secretary")
    return code


if __name__ == "__main__":
    raise SystemExit(main())

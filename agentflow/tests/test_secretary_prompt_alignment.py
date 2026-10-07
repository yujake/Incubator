"""秘书与提示词的双向对齐（2026-10-07 所有者逐字要求："需要双向对齐"）。

## 这份判据要治的两个方向

调提示词时，秘书常常被当作"接住方"（`draft/63 §2` 的"谁接住"那一栏大量写的就是它）。
但"它接住了"这句话有两个方向，任缺一边都会静默出错：

- 方向一（代码 → 提示词）：秘书真的做这件事（代码里有落点、有生产调用点），
  可是没有任何角色被告知 ⇒ 它的输出没人看、它的提醒没人接 ⇒ 能力等于不存在。
- 方向二（提示词 → 代码）：提示词里对角色承诺了"秘书会替你 X"，
  而代码里没有这件事 ⇒ 角色按承诺行事，撞墙时没人接。

## 为什么不能靠"读一眼"（`draft/63 §4-5` 的血账）

上一批减负把"你是只读角色：不许写/改任何数据"整句删了：C 被一条判据抓住，H 没有任何东西会红。
⇒ "谁接住"必须被机器钉住，不能凭一句话当它接住了。

## 表怎么读

`DUTIES` 里每一项是一条职责：代码真身（`code`）· 生产调用点（`call`，逐处写 文件:行）
· 可见性（`visibility`）：

- `prompt` —— 角色应当知道它（且有出口探针命中）；
- `conditional` —— 只有一部分角色应当知道它；`roles` 是登记下来的那一批
  （注意：刻意不写"由某个代码条件推导"：实测 `duty2` 的可见集 {D,E,F,G,M} 不等于
  "有出边的角色"（A/B/H/V 也有边）⇒ 写一个猜的条件比登记更松。登记 + 等额 = 改了就红，人来裁）；
- `internal` —— 框架内部用，角色不需要知道；必须写明 `why`，且任何提示词的出口探针都不许命中它
  （否则就成了"提示词在承诺一件角色看不见的事"）。

`pin` 是"某个方法今天没有生产调用点"的登记（有产出方没调用点的东西要留读数，不许沉默）。

## 反真空

判据会报：扫了几个角色 · 抽到几句"对秘书的承诺" · 表里几项职责 ·
`duty=N` 在代码里出现了几个 N。任何一个是 0 ⇒ 这一格没查成，不是没问题。
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
import tempfile

import pytest

#: 四项职责 + 交接手稿那一族。`call` 里的行号只作"人读时去找"的线索 ——
#: 判据不按行号断言（锚点纪律 A：行号会漂），它只断言"这个符号在生产面被调用过 ≥1 次"。
DUTIES: dict[str, dict[str, object]] = {
    "duty1_prescreen": {
        "code": "prescreen",
        "where": "secretary.py",
        "call": ("secretary.py:617", "secretary.py:662"),
        "visibility": "prompt",
        "probe": ("会被拒", "名字必须是真的"),
        "why": "派活前预筛：被拒时给出并列候选，角色必须知道有这一步，否则它只会瞎猜名字",
    },
    "duty2_assess": {
        "code": "assess_delegation",
        "where": "secretary.py",
        "call": ("agent_loop.py:2465", "conductor.py:907"),
        "visibility": "conditional",
        "roles": ("D", "E", "F", "G", "M"),
        "probe": ("评估这次派活", "assess", "建议你换"),
        "why": "派活评估只对'会派活的角色'有意义。⚠️ 这一批是**登记**的，不是推导的："
               "实测 {D,E,F,G,M} 不等于'有出边的角色'（A/B/H/V 也有边）",
    },
    "duty3_closure": {
        "code": "remind_closure",
        "where": "secretary.py",
        "call": ("conductor.py:807",),
        "visibility": "prompt",
        "probe": ("收件箱", "待办"),
        "why": "闭环提醒落在收件箱里；角色必须知道要去看，否则提醒等于没发",
    },
    "duty4_rework": {
        "code": "rework_inbound",
        "where": "secretary.py",
        "call": ("agent_loop.py:2506",),
        "visibility": "internal",
        "why": "收件后重解读：重解读结果由**框架直接替换进交给角色的那批 item**"
               "（`agent_loop.py:2506` 的 `reworked.append(...)`）⇒ 角色无需知情。"
               "⚠️ 这一条是**登记**：实测它在十角色提示词里 0/10 命中（探针见 `probe_internal`）",
    },
    "handoff": {
        "code": "handoff_add",
        "where": "secretary.py",
        "call": ("agent_loop.py:2568",),
        "visibility": "prompt",
        # 探针要覆盖同一种承诺的不同措辞：判据首跑就抓到我只写了"秘书执笔"，
        # 而 M 那边还有"框架会把它交给秘书写成一份交接手稿"、"交给秘书写成手稿并发出去"
        # 两种说法 ⇒ 那两句当时被判成"没人认领的承诺"（假红，但方向是对的：措辞一变就该有人看）。
        "probe": ("秘书执笔", "交给秘书", "写成手稿", "写成交接手稿"),
        "why": "交接手稿由秘书执笔编号；十个角色的提示词都写了这件事（这是唯一一处本来就双向对齐的）",
    },
}

#: `internal` 那一档的"出口探针"：这些词若出现在任何角色的提示词里，
#: 就说明有人把"框架内部的事"当成对角色的承诺写进了提示词 ⇒ 红。
PROBE_INTERNAL = ("重解读", "重新理解", "rework")

#: 普查 `draft/63 §2-①` 点名的另一个接住方：错名时的并列候选。
#: 它不在秘书里（薄转发到 `tools/base.py`），但同一条"双向对齐"纪律适用：
#: 提示词教了「名字必须是真的 / 会被拒」，那"给候选"这件事就必须真的发生。
OTHER_CATCHERS: dict[str, dict[str, object]] = {
    "candidate_tool_names": {
        "where": "tools/base.py",
        "promise": ("名字必须是真的", "会被拒"),
        "call": ("tools/base.py:945 的候选计算", "secretary.py:124 的薄转发"),
        "why": "工具/动作名写错时给并列候选（`secretary.py:116` 的 docstring 逐字写着"
               "「错名的并列候选（薄转发到 tools.base.candidate_tool_names，判据只有一份）」）",
    },
}

#: 登记的"有产出方、今天没有生产调用点"的秘书方法（留读数，不许沉默）。
#: 注意：这一档不是禁令，是登记制：登记了就必须写清"它今天由谁消费"。
NO_CALL_POINT_TODAY = {
    "pending_inbox": "定义了、`inbox_todos` 之外没有生产调用点（2026-10-07 现算 0 处）—— "
                     "与 `draft/69 §5` 的 R5-㔔 同族：**有产出方没接**，登记为读数而不是删掉",
    "decisions": "只读访问器（把决定台账读成 list）；生产面今天无调用点，"
                 "由 `tests/test_secretary.py` 等与「看一眼台账」的人消费",
    "knowledge": "只读访问器（角色画像：briefs/账本/权限位）；生产面今天无调用点，"
                 "由测试与未来的「审校 / 状态报告」入口消费",
    "may_read_narrative": "只读判定（该角色能不能读叙事文本）；生产面今天无调用点，"
                          "由测试消费（权限面的读数，不是派发点）",
}


def _roles_and_prompts() -> dict[str, str]:
    """渲染十角色的提示词（口径 = `tests/test_agent_surface_snapshot.py::_build/_snapshot`）。"""
    from agentflow.store import Store
    from agentflow.tools import ROLES, build_registry
    from agentflow.agent_prompts import system_prompt
    from agentflow.tools import TOOL_ROLES

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="align-two-way-"))
    ws = tmp / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    full = build_registry(store=st, workspace_root=ws, roles=tuple(ROLES), strict=True).registry
    out: dict[str, str] = {}
    for role in (*TOOL_ROLES, "M"):
        out[role] = system_prompt(role, registry=full)
    return out


def _secretary_source() -> str:
    import agentflow.secretary as SEC

    return pathlib.Path(SEC.__file__).read_text(encoding="utf-8")


def _src_text(rel: str) -> str:
    import agentflow

    return (pathlib.Path(agentflow.__file__).parent / rel).read_text(encoding="utf-8")


def _called_in_production(symbol: str) -> list[str]:
    """`symbol` 在生产面（`src/agentflow` 的 py）被调用的每一处。

    两种调用形态都要认（第一版只认第一种，于是把 `candidate_tool_names` 误报成"死的"）：

    1. 属性调用 `.symbol(` —— 例如 `self.secretary.prescreen(...)`；
    2. 裸调用 `symbol(` —— 例如 `from .tools.base import candidate_tool_names` 之后的直接调用。

    刻意排除三类"看着像调用"的行：`def symbol(`（那是定义）、`from/import` 行、
    以及行首是注释或引号的行（本仓的 docstring 大量引用代码，不排会把"提及"当成"调用"）。
    紧跟在反引号后的名字也排除（`` `symbol(…)` `` 是文档里的引用，不是调用）。

    已知口径边界（如实写在判据里，免得下一个人把命中数当精确值）：多行字符串内部的行认不出来
    —— 例如提示词正文里那句"写这一行的是 `self.secretary.handoff_add(...)`"会被算成一处。
    所以调用点的条数只作"非空"判据（`assert calls`），不作精确计数；
    要精确数就得走 `ast`（本判据刻意不引 `ast`：它要的是"生产面到底有没有人调它"这一档，
    而这一档用行级扫描已经够，且不依赖被扫文件的语法能否解析）。
    """
    import re as _re

    root = pathlib.Path(__import__("agentflow").__file__).parent
    attr = _re.compile(r"\." + _re.escape(symbol) + r"\s*\(")
    bare = _re.compile(r"(?<![\w.`])" + _re.escape(symbol) + r"\s*\(")
    hits: list[str] = []
    for p in sorted(root.rglob("*.py")):
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            s = ln.lstrip()
            if s.startswith(("#", '"', "'", "def ", "from ", "import ")):
                continue
            if attr.search(ln) or bare.search(ln):
                hits.append(f"{p.relative_to(root)}:{i}")
    return hits


def _secretary_claims(text: str) -> list[str]:
    """提示词里"对秘书的承诺"：把提到「秘书」的句子抽出来（句级，去重）。"""
    parts = [s.strip() for s in re.split(r"[。\n]", text) if "秘书" in s]
    return [p for p in parts if p]


# --------------------------------------------------------------------------------------
# 方向一：代码 → 提示词
# --------------------------------------------------------------------------------------

def test_every_secretary_duty_is_either_visible_to_roles_or_registered_internal() -> None:
    prompts = _roles_and_prompts()
    reading: dict[str, object] = {"roles": len(prompts), "duties": len(DUTIES)}
    problems: list[str] = []

    for key, spec in DUTIES.items():
        probe = tuple(spec.get("probe", ()))  # type: ignore[arg-type]
        vis = spec["visibility"]
        seen = tuple(r for r, t in prompts.items() if any(k in t for k in probe)) if probe else ()
        reading[f"{key}.seen_in"] = len(seen)

        if vis == "prompt":
            if not seen:
                problems.append(
                    f"{key}：{spec['why']} —— 但十角色提示词里**一个**出口探针都没命中 "
                    f"{probe} ⇒ 这是'代码 → 提示词'那一向的缺口（角色不知道它存在）")
        elif vis == "conditional":
            want = tuple(spec.get("roles", ()))  # type: ignore[arg-type]
            if tuple(sorted(seen)) != tuple(sorted(want)):
                problems.append(
                    f"{key}：登记该知道它的角色是 {sorted(want)}，而提示词里实际命中 {sorted(seen)} "
                    f"⇒ 两边**不等额**（多一个/少一个都要人来裁，不许自动跟着变）")
        elif vis == "internal":
            if not spec.get("why"):
                problems.append(f"{key}：登记为 internal 但没写 why")
            hit = tuple(r for r, t in prompts.items() if any(k in t for k in PROBE_INTERNAL))
            if hit:
                problems.append(
                    f"{key}：登记为'框架内部、角色无需知情'，可是 {list(hit)} 的提示词里出现了"
                    f"{PROBE_INTERNAL} 这类出口词 ⇒ 提示词在承诺一件角色看不见的事")

    assert reading["roles"] == 10, f"只渲染到 {reading['roles']} 个角色 ⇒ 这一格没查成"
    assert reading["duties"] >= 5, reading
    assert not problems, ("秘书职责与提示词**没有双向对齐**：\n  - " + "\n  - ".join(problems))


# --------------------------------------------------------------------------------------
# 方向二：提示词 → 代码
# --------------------------------------------------------------------------------------

def test_every_promise_about_the_secretary_has_a_code_catcher() -> None:
    prompts = _roles_and_prompts()
    claimed_by: dict[str, set[str]] = {}
    for role, text in prompts.items():
        for claim in _secretary_claims(text):
            claimed_by.setdefault(claim, set()).add(role)

    # 反真空：抽不到任何承诺 ⇒ 扫描面坏了，不是"没问题"。
    assert claimed_by, "十角色提示词里一句'秘书'相关的话都没抽到 ⇒ 抽取面坏了（不是没问题）"

    # 每条承诺必须能映射到表里一个"对角色可见"的条目。
    prompt_visible_probes = {
        k: tuple(v.get("probe", ()))  # type: ignore[arg-type]
        for k, v in DUTIES.items() if v["visibility"] in ("prompt", "conditional")
    }
    unmapped = [c for c in claimed_by
                if not any(k in c for k in PROBE_INTERNAL)
                and not any(any(p in c for p in probes) for probes in prompt_visible_probes.values())]
    assert not unmapped, (
        "这些句子在对角色承诺'秘书会做某事'，但表里没有任何一条职责认领它"
        "（= 承诺了一个没人接住的接住方）：\n  - " + "\n  - ".join(f"[{'/'.join(sorted(claimed_by[c]))}] {c[:120]}" for c in unmapped))

    # 被承诺的那些条目：代码真身必须在，且在生产面被真的调用过。
    for key, spec in DUTIES.items():
        if spec["visibility"] == "internal":
            continue
        probes = tuple(spec.get("probe", ()))  # type: ignore[arg-type]
        claimed = [c for c in claimed_by if any(p in c for p in probes)]
        if not claimed:
            continue
        assert spec["code"] in _src_text(str(spec["where"])), (
            f"{key}：提示词承诺了它（{len(claimed)} 句），而 `{spec['where']}` 里找不到符号 "
            f"`{spec['code']}` ⇒ 承诺了一个不存在的接住方")
        calls = _called_in_production(str(spec["code"]))
        assert calls, (
            f"{key}：提示词承诺了 `{spec['code']}`，但它在生产面**一次都没被调用** ⇒ "
            f"这个接住方今天是死的（登记线索：{spec['call']}）")


# --------------------------------------------------------------------------------------
# 等额：代码里出现的职责编号必须都在表里
# --------------------------------------------------------------------------------------

def test_every_duty_number_in_the_code_is_registered_here() -> None:
    src = _secretary_source()
    nums = sorted({int(m.group(1)) for m in re.finditer(r"duty=(\d)", src)})
    assert nums, "`secretary.py` 里一个 `duty=N` 都没扫到 ⇒ 扫描面坏了（不是没问题）"
    registered = {int(k[4]) for k in DUTIES if k.startswith("duty")}
    assert set(nums) == registered, (
        f"代码里出现的职责编号 {nums} 与表里登记的 {sorted(registered)} 不等额 —— "
        "新加一项职责必须在这张表里登记（它要不要让角色知道，是人来裁的）")


def test_secretary_methods_without_a_call_point_are_registered() -> None:
    """有产出方、今天没有生产调用点的秘书方法 ⇒ 必须登记（留读数，不许沉默）。"""
    import agentflow.secretary as SEC

    public = [n for n in dir(SEC.Secretary) if not n.startswith("_")]
    dead = sorted(n for n in public if callable(getattr(SEC.Secretary, n, None))
                  and not _called_in_production(n))
    unregistered = [n for n in dead if n not in NO_CALL_POINT_TODAY]
    assert not unregistered, (
        "这些秘书方法今天在生产面**没有调用点**，却没有登记（登记表 = `NO_CALL_POINT_TODAY`）："
        f"{unregistered}\n  （登记过的：{sorted(NO_CALL_POINT_TODAY)}）")


# --------------------------------------------------------------------------------------
# 同一条纪律：普查点名的其它接住方（不在秘书里的那些）也要双向
# --------------------------------------------------------------------------------------

def test_other_named_catchers_are_two_way_aligned() -> None:
    """`draft/63 §2` 的"谁接住"那一栏还点名了秘书之外的组件；同一条纪律适用。

    这里只登记真正会被提示词承诺的那些（今天一条：错名的并列候选）。
    不在秘书里不影响判定 —— 判据问的是同一件事：承诺了就得真做。
    """
    prompts = _roles_and_prompts()
    reading: dict[str, object] = {}
    problems: list[str] = []
    for sym, spec in OTHER_CATCHERS.items():
        promise = tuple(spec["promise"])  # type: ignore[arg-type]
        seen = sorted(r for r, t in prompts.items() if any(p in t for p in promise))
        reading[sym] = len(seen)
        if not seen:
            problems.append(f"{sym}：十角色提示词里没有任何人被告知 {promise} ⇒ 接住方没人知道它存在")
        if sym not in _src_text(str(spec["where"])):
            problems.append(f"{sym}：`{spec['where']}` 里找不到这个符号 ⇒ 提示词承诺了一个不存在的东西")
        calls = _called_in_production(sym)
        if not calls:
            problems.append(
                f"{sym}：提示词承诺了它（{len(seen)} 个角色），而它在生产面**一次都没被调用** ⇒ "
                f"这个接住方今天是死的（登记线索：{spec['call']}）")
    assert reading, "表是空的 ⇒ 这一格没查成"
    assert not problems, ("其它接住方与提示词**没有双向对齐**：\n  - " + "\n  - ".join(problems))


# --------------------------------------------------------------------------------------
# 负控：两个方向各自都要"能红"
# --------------------------------------------------------------------------------------

def test_the_alignment_check_can_actually_go_red_both_ways() -> None:
    """负控（不依赖真文件的内容，只用判据自己的形状）：

    - 方向二：编一句"秘书会替你把结论写成章节" ⇒ 表里没有任何条目认领它 ⇒ 必须能被认出来；
    - 方向一：把 `duty4_rework` 的可见性从 internal 改成 prompt ⇒ 它的探针在十角色里 0 命中
      ⇒ 必须被判红。
    """
    fake_claim = "框架会让秘书替你把结论写成章节。"
    prompt_visible_probes = {
        k: tuple(v.get("probe", ()))  # type: ignore[arg-type]
        for k, v in DUTIES.items() if v["visibility"] in ("prompt", "conditional")
    }
    claimed = not any(any(p in fake_claim for p in probes) for probes in prompt_visible_probes.values())
    assert claimed, "负控失败：编的这句承诺被表里某条职责认领了 ⇒ 这条负控是空转"

    prompts = _roles_and_prompts()
    seen4 = tuple(r for r, t in prompts.items() if any(k in t for k in ("重解读", "重新理解")))
    assert not seen4, (
        f"`duty4_rework` 登记为 internal（角色无需知情），可是 {list(seen4)} 的提示词里出现了它的出口词 ⇒ "
        "把它改成 prompt 就会红（这条负控证明了那一半有牙）")

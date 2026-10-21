"""`draft/37` §49/§50 的判据：循环走原生工具调用，名字不再由模型手写。

## 这一条判据挡的是什么（第三趟真机的死因）

§48：第三趟真机连续三次回 `{"name": …, "args": …}` 而不是 `{"tool": …}`（框架逐字纠正过两次），`max_bad_json=2` ⇒ 第 3 次 `bad_json_limit`，整趟作废。
§49 去读了 DSH 的源码：它那条路上不存在这一类失败，因为工具名来自传输层的结构化字段（`delta.tool_calls[].function.name`），模型不需要把调用序列化成一行 JSON。

这一组判据钉三件事：

1. 原生路径：`tool_calls` 进来 ⇒ 被翻成循环认的形状（含 `framework_*` 那几个
非工具形状），且名字逐字来自结构化字段；
2. 回落路径：上游没给 `tool_calls` ⇒ 照旧解析文本 JSON，口径一个字没放宽
（既有那批"坏 JSON ⇒ judge_bad_json"的判据一条都不许改）；
3. 键名漂移不再致命：同一句"想调 `fs.read`"的意图，用原生形状表达时
根本不需要写 `tool` 这个键 —— 判据直接断言"那条路上没有键可漂"，而不是断言"漂了也能解析"（后者是把宽容当解法，DSH 的做法是前者）。

判据里的 seam 是桩（不联网）：`_StubGateway` 按脚本回 `tool_calls` 或文本。
"""
from __future__ import annotations

import json
from pathlib import Path

from agentflow import judge as J
from agentflow import llmseam as LL
from agentflow import modelgw as MG
from agentflow.store import Store
from agentflow.tools import build_registry

WS = Path(r"D:\Incubator\agentflow")


class _StubGateway:
    """按脚本返回：每条要么给 `tool_calls`，要么给文本。"""

    def __init__(self, script: list[dict]) -> None:
        self.script = list(script)
        self.seen: list[dict] = []
        self.spec = MG.ModelSpec(model="stub-model", api_key="x", base_url="http://stub")

    def complete(self, prompt: str, *, scope: str, system=None, max_tokens=None,
                 tools=None, tool_choice="auto") -> MG.ModelReply:
        self.seen.append({"tools": list(tools or []), "tool_choice": tool_choice})
        item = self.script.pop(0) if self.script else {"tool_calls": []}
        return MG.ModelReply(ok=True, text=item.get("text", ""),
                             tool_calls=tuple(item.get("tool_calls", ())),
                             tokens_in=1, tokens_out=1, model="stub-model", scope=scope)


def _seam(tmp_path: Path, script: list[dict]) -> tuple[LL.LlmSeam, _StubGateway]:
    gw = _StubGateway(script)
    seam = LL.LlmSeam(role="A", session_root=tmp_path, gateway=gw)
    return seam, gw


def _wired_registry(tmp_path: Path):
    """带工作区的注册表：`fs.*` 那一组只有在给了 `workspace_root` 时才装配。

    这一条本身是个教训（`agent_prompts._specs_for` 的 docstring 记过）：不带工作区的
    注册表少一整组工具，而"少的那一组"在读数上看不出来 —— 判据必须用真的会执行
    的那个注册表，否则它证明的是另一份工具面。
    """
    (tmp_path / "data").mkdir(exist_ok=True)
    st = Store(tmp_path)
    st.init()
    return build_registry(store=st, workspace_root=tmp_path).registry


def _call(name: str, args: dict) -> dict:
    return {"id": "c1", "name": name, "arguments": json.dumps(args, ensure_ascii=False)}


# ============================================================ 一、工具面

def test_the_tool_face_advertises_the_role_tools_plus_the_loop_shapes():
    """正控：广告面 = 这一岗的工具 + 循环的非工具形状，且名字可逆、摘要是可复核的事实。

    "名字可逆"不是洁癖：`fs.read` 带点，而 OpenAI 兼容接口的 function name 只允许
    `[A-Za-z0-9_-]` —— 换名之后必须能映回真名，否则模型调的是另一个东西。
    """
    reg = build_registry().registry
    face = LL.build_tool_face("M", reg)
    advertised = [f["function"]["name"] for f in face.functions]
    assert "framework_summon" in advertised and "framework_final" in advertised
    assert "conductor_summon" in advertised, advertised[:6]
    # 映回真名：换名是双射（点 → 下划线），且真名必须在工具面上
    real = {v for v in face.names.values() if v.startswith("tool:")}
    assert "tool:conductor.summon" in real, sorted(real)[:6]
    assert all(n["type"] == "function" for n in face.functions)
    # 摘要随工具面走：改了工具面，这个数就变（"广告了哪份面"是可复核的事实）
    assert len(face.sha256) == 64
    face2 = LL.build_tool_face("M", reg)
    assert face2.sha256 == face.sha256, "同一份工具面必须给出同一个摘要"
    # 反真空：一件工具都没有的面不该悄悄通过
    assert len(face.functions) >= len(LL.META_FUNCTIONS) + 1


def test_two_tools_that_sanitize_to_the_same_name_are_refused():
    """负控：广告名撞车必须当场炸，而不是让模型按一个含糊的名字去调工具。"""
    class _Spec:
        def __init__(self, name: str) -> None:
            self.name = name
            self.summary = name
            self.params = {"type": "object", "properties": {}}

    class _Reg:
        def for_role(self, role: str):
            return [_Spec("fs.read"), _Spec("fs_read")]

    try:
        LL.build_tool_face("A", _Reg())
    except ValueError as exc:
        assert "撞车" in str(exc), exc
    else:
        raise AssertionError("两件工具归一化成同一个广告名，却没有当场报错")


# ============================================================ 二、原生路径

def test_native_tool_call_needs_no_tool_key(tmp_path: Path):
    """本组的核心：原生 `tool_calls` 进来 ⇒ 形状里那个 `tool` 键由框架自己写。

    断言方式刻意选得"结构"而不是"宽容"：如果这条路上还需要模型写 `tool` 键，
    那 §48 的失败只是被推迟了；所以这里断言的是模型给的 `arguments` 里没有
    `tool` 键，而结果里有。
    """
    seam, _gw = _seam(tmp_path, [{"tool_calls": [_call("fs_read", {"path": "a.txt", "why": "看"})]}])
    face = LL.build_tool_face("A", _wired_registry(tmp_path))
    data, call = seam.ask_step("读文件", face=face)
    assert call.ok and call.protocol == "tool_calls", call.to_dict()
    assert call.tool_calls == 1
    assert data == {"tool": "fs.read", "args": {"path": "a.txt"}, "why": "看"}, data
    # 模型那一侧从来没写过 "tool" 这个键
    assert "tool" not in json.loads(_call("fs_read", {"path": "a.txt"})["arguments"])


def test_the_flat_native_signature_decodes_to_the_same_shapes():
    """`draft/37` §68：`framework_summon` 的实参原样写出来 ⇒ 解成同一个 `summon` 形状。

    正控三条：单条召唤、批量召唤、以及别名留痕（`shape_alias`）。
    这三条都要"解出来的 payload 与包裹形态逐键相同"，否则别名就是第二条解码路径。
    """
    from agentflow.agent_loop import _shape_of

    shape, payload, problem = _shape_of({"role": "G", "action": "revise",
                                         "params": {"doc_id": "0000"}, "why": "派活"})
    assert (shape, problem) == ("summon", ""), (shape, problem)
    assert {k: v for k, v in payload.items() if k != "shape_alias"} == {
        "role": "G", "action": "revise", "params": {"doc_id": "0000"}, "why": "派活"}
    assert payload["shape_alias"] == "role", payload

    shape2, payload2, problem2 = _shape_of({
        "targets": [{"role": "B", "action": "run_once", "params": {"limit": 3}}], "why": "批量"})
    assert (shape2, problem2) == ("summon_many", ""), (shape2, problem2)
    assert payload2["targets"][0]["role"] == "B" and payload2["shape_alias"] == "targets"


def test_the_flat_alias_does_not_widen_any_validation():
    """负控：别名只改"从哪取键"，校验一个字都不放宽。

    关键的一条是"角色名不在 ROLES 里"：如果别名是另写一条解码路径，
    很容易把 `summon` 那条 `role not in S.ROLES` 的判据漏掉 —— 那等于用一个
    新写法绕过了权限面校验的第一道闸。
    """
    from agentflow.agent_loop import _shape_of

    shape, _payload, problem = _shape_of({"role": "Z", "action": "revise"})
    assert not shape and "不在" in problem, (shape, problem)
    shape2, _p2, problem2 = _shape_of({"role": "G", "action": "revise", "params": "不是对象"})
    assert not shape2 and "params 必须是一个对象" in problem2, (shape2, problem2)


def test_two_flat_aliases_at_once_are_refused():
    """负控（fail-closed）：两个扁平别名同时命中 ⇒ 仍然判"认不出的形状"。

    不许按别名表里的先后顺序挑一个：那会让"先写哪个键"决定框架执行哪一件事，
    而两件事的后果完全不同（派一环 vs 派一批）。
    """
    from agentflow.agent_loop import _shape_of

    shape, _payload, problem = _shape_of({"role": "G", "action": "revise",
                                          "targets": [{"role": "B", "action": "run_once"}]})
    assert not shape and "认不出的形状" in problem, (shape, problem)


def test_the_advertised_ask_user_schema_matches_what_the_channel_accepts():
    """`draft/37` §72：广告面必须广告 `userio` 真收的那份形状。

    真机教训的同族：广告一份、执行另一份，模型就会按广告写、框架说"这不是我认识的形状"。
    所以这一条把两件事钉在一起：广告里有 `header` 与「对象形状」的选项（带 `description`），
    而 `_shape_of` 对这两种形状都收（裸字符串是旧形状，照样收）。
    """
    from agentflow.agent_loop import _shape_of
    from agentflow import llmseam as LL

    face = {name: schema for name, _shape, schema in LL.META_FUNCTIONS}
    ask = face["framework_ask_user"]
    props = ask["properties"]
    assert "header" in props, props
    items = props["options"]["items"]
    assert items.get("type") == "object", items
    assert "label" in items["properties"] and "description" in items["properties"], items
    assert "multi_select" in props, props

    # 广告了就得真收：对象形状与旧的裸字符串形状都要能解出来，且都进同一个 payload 形状
    obj = _shape_of({"ask_user": {"question": "选哪个？", "header": "取舍",
                                  "options": [{"label": "A", "description": "先做 A"}],
                                  "multi_select": True}})
    flat = _shape_of({"ask_user": {"question": "选哪个？", "options": ["A", "B"]}})
    for shape, payload, problem in (obj, flat):
        assert (shape, problem) == ("ask_user", ""), (shape, problem, payload)
        assert payload["options"][0]["label"] == "A", payload
    assert obj[1]["header"] == "取舍" and obj[1]["multi_select"] is True, obj[1]
    assert flat[1]["options"][1]["label"] == "B", flat[1]


def test_the_meta_shapes_travel_as_functions(tmp_path: Path):
    """正控：`summon` / `note` / `final` 这些非工具形状也走结构化调用。"""
    seam, _gw = _seam(tmp_path, [
        {"tool_calls": [_call("framework_summon",
                              {"role": "G", "action": "revise", "params": {"doc_id": "0000"},
                               "why": "派活"})]},
        {"tool_calls": [_call("framework_note", {"text": "记一句"})]},
        {"tool_calls": [_call("framework_final", {"final": "交付说明", "evidence": ["x"]})]},
    ])
    face = LL.build_tool_face("M", build_registry().registry)
    got = []
    for _ in range(3):
        data, _callres = seam.ask_step("t", face=face)
        got.append(data)
    assert got[0]["summon"]["role"] == "G" and got[0]["summon"]["why"] == "派活"
    assert got[1] == {"note": {"text": "记一句"}}
    assert got[2] == {"final": "交付说明", "evidence": ["x"]}


def test_the_advertised_face_is_recorded_in_the_audit_trail(tmp_path: Path):
    """正控（审计链）：每次调用都要记下"这一趟广告了哪份工具面"。"""
    seam, gw = _seam(tmp_path, [{"tool_calls": [_call("conductor_state", {})]}])
    face = LL.build_tool_face("M", build_registry().registry)
    _data, call = seam.ask_step("t", face=face)
    d = call.to_dict()
    assert d["protocol"] == "tool_calls"
    assert d["tools_advertised"] == len(face.functions)
    assert d["tools_sha256"] == face.sha256
    assert d["tool_calls"] == 1
    # 请求里真的带上了 tools（不是"记了但没发"）
    assert gw.seen and len(gw.seen[0]["tools"]) == len(face.functions)


def test_every_non_tool_shape_has_an_advertised_function(tmp_path: Path):
    """`llmseam.build_tool_face` 的注释说"`SHAPES` 减去 `tool` 全都广告成函数" —— 这条判据
    把那句话变成机器读数（`draft/108` CS-17 的正面）。

    为什么值得单开一条：广告面与接受面分家有两种形态，第二种更坏 —— 模型按形状名写，
    框架回一句"没广告过这个函数"（白扔一步，还能改）；或者模型在广告过的函数里
    带了一个没广告过的参数，框架静默丢掉（模型以为生效了）。这一条钉第一种：
    逐形状从 `agent_loop.SHAPES` 现算（加一个形状而忘了广告 ⇒ 必红），
    并做一次往返：广告名 → `to_shape` → `_shape_of` 必须解回同一个形状、无 problem。
    """
    from agentflow import agent_loop as AL

    face = LL.build_tool_face("M", build_registry().registry)
    by_shape = {shape: san for san, shape, _schema in LL.META_FUNCTIONS}
    advertised = {f["function"]["name"] for f in face.functions}
    #: 每个形状一份最小合法载荷（与 `_decode_shape` 各支的必填一致）。加形状不在这里
    #: 补一份 ⇒ 下面那句 `sorted(samples)` 会红 —— 判据不会因为"新形状没人管"而变空。
    samples: dict[str, dict] = {
        "summon": {"role": "G", "action": "revise", "params": {}},
        "summon_many": {"targets": [{"role": "B", "action": "run_once"}]},
        "message": {"to": "F", "subject": "喂", "body": "在吗"},
        "handoff": {"to": "F", "summary": "把结论交给你", "body": "第二版在 refs 里。"},
        "note": {"text": "记一句"},
        "ask_user": {"question": "选哪个？"},
        "final": {"final": "交付说明"},
        "retire": {"name": "D1"},
        "roster": {},
        "interrupt": {"name": "D1"},
    }
    non_tool = tuple(s for s in AL.SHAPES if s != "tool")
    assert sorted(samples) == sorted(non_tool), (
        f"样例表与 `agent_loop.SHAPES`（减 `tool`）不等额：{sorted(samples)} vs {sorted(non_tool)}")
    for shape in non_tool:
        san = by_shape.get(shape, "")
        assert san, f"{shape} 没有对应的 `framework_*` 广告名（`llmseam.META_FUNCTIONS`）"
        assert san in advertised, f"{san} 不在广告面里：{sorted(advertised)[:6]}…"
        data, problem, detail = face.to_shape(_call(san, samples[shape]))
        assert problem == "" and data is not None, (shape, problem, detail)
        got, payload, bad = AL._shape_of(data)
        assert (got, bad) == (shape, ""), (shape, got, bad, data)
        assert payload, f"{shape} 解出来的载荷是空的（那等于「广告了但什么也没发生」）"


def test_the_native_final_keeps_the_blocked_declaration():
    """`blocked`（"我在等上级指导"的收工声明）在原生那条路上不许被静默丢掉。

    `draft/108` CS-17：文本路 `_decode_shape` 一直带过 `{"final": …, "blocked": {…}}`，
    而原生面此前既没广告 `blocked`、`to_shape` 又只重建 `final`/`evidence`/`notify`
    ⇒ 模型在 `framework_final` 里带 `blocked` 时那一笔凭空消失：父那边 `subtree_blocked`
    读出来仍是"没卡住"，而模型以为它声明了（这一轴要治的"静默"里最坏的一种）。

    三条一起钉：① 广告面里有这一格；② 给了就原样透传；③ 没给就不许造一个空 dict
    （"没声明"与"声明了空"必须在盘上分得开），且它不许进 `required`
    （那会先拒掉一次"合法的收工" —— 与 `NOTIFY_JSON_SCHEMA` 上面那条教训同源）。
    """
    from agentflow import agent_loop as AL

    meta = {name: schema for name, _shape, schema in LL.META_FUNCTIONS}
    fin = meta["framework_final"]
    props = fin["properties"]
    assert "blocked" in props, sorted(props)
    assert fin.get("required") == ["final"], fin.get("required")
    assert set(props["blocked"]["properties"]) == {"what", "why", "needs"}, props["blocked"]

    face = LL.build_tool_face("A", build_registry().registry)
    decl = {"what": "核引文", "why": "口径没定", "needs": "请上级定『引文一致』的判定口径"}
    data, problem, detail = face.to_shape(
        _call("framework_final", {"final": "卡住了", "blocked": decl}))
    assert problem == "" and data is not None, (problem, detail)
    assert data.get("blocked") == decl, data
    # 负控（不凭空造键）：没给 `blocked` 时那一格不许出现
    plain, _p, _d = face.to_shape(_call("framework_final", {"final": "收工"}))
    assert "blocked" not in plain, plain
    # 与文本那条路同源：同一个载荷经 `_shape_of` 解出来也带 `blocked`
    shape, payload, bad = AL._shape_of({"final": "卡住了", "blocked": decl})
    assert (shape, bad) == ("final", "") and payload.get("blocked") == decl, (shape, bad, payload)


def test_every_advertised_key_survives_the_decoder(tmp_path: Path):
    """键一级的"广告一份、执行另一份"：广告面声明的每一格，解码器都要真收。

    `draft/108` CS-17 那一族的另一半（批 R48 开这个角时补的）：形状名一级由上面那条判据钉着，
    而键一级此前只有人记着。这一条把方向一并钉住 —— 广告了就必须收
    （反向"收了解码器却没广告"由 `temp/_probe_shape_keys.py` 出读数；判据面放一条
    只读一半的理由：那一半要挨个试键、会把测试变成探针，而这一半是纯集合运算）。

    形状与广告键都现算自 `llmseam.META_FUNCTIONS`，载荷样例与
    `temp/_probe_shape_keys.py` 同源（只放最小合法值）。
    """
    from agentflow.agent_loop import _shape_of

    base: dict[str, object] = {
        "summon": {"role": "G", "action": "revise", "params": {}},
        "summon_many": {"targets": [{"role": "B", "action": "run_once"}]},
        "message": {"to": "F", "body": "在吗"},
        "handoff": {"to": "F", "summary": "交给你", "body": "正文"},
        "note": {"text": "一句"},
        "ask_user": {"question": "选哪个？"},
        "final": "收工",
        "retire": {"name": "D1"},
        "roster": {},
        "interrupt": {"name": "D1"},
    }
    sample: dict[str, object] = {
        "params": {}, "notify": {"to": "F", "summary": "s", "body": "b"},
        "blocked": {"what": "w", "why": "y", "needs": "n"},
        "targets": [{"role": "B", "action": "run_once"}], "refs": ["0001"],
        "evidence": ["x"], "options": [], "multi_select": True, "revises": "0001",
        "reuse": "D1", "name": "D1", "scope": "descendants", "of": "self",
        "brief": "一句话", "instance": "i", "input_key": "k", "timeout_sec": 0,
        "reply_to": "0001", "subject": "标题", "role": "G", "action": "revise",
        "text": "一句", "question": "问？", "summary": "s", "body": "b", "why": "w",
        "final": "收工", "header": "标题", "to": "F", "what": "w", "needs": "n",
    }
    checked = 0
    for _san, shape, schema in LL.META_FUNCTIONS:
        assert shape in base, f"新形状 {shape} 没在样例表里（这一条判据就没覆盖它）"
        for key in sorted(schema.get("properties") or {}):
            if shape == "final":      # final 的其余键住在 data 顶层（值是字符串）
                data = {"final": base["final"], key: sample.get(key, "x")}
            else:
                data = {shape: {**dict(base[shape]), key: sample.get(key, "x")}}  # type: ignore[arg-type]
            got, payload, bad = _shape_of(data)
            assert (got, bad) == (shape, ""), (shape, key, got, bad)
            assert payload.get(key) not in (None, ""), (
                f"广告面声明了 `{shape}.{key}`，而解码器没把它带进 payload：{payload}")
            checked += 1
    assert checked >= 25, f"只核了 {checked} 格 —— 判据看着像是空转了"


def test_the_native_summon_carries_the_dispatch_notify():
    """主控派活时的留痕：`summon` / `summon_many` 里的 `notify` 在原生那条路上也要给得出。

    `draft/108` CS-18（批 R48）：`agent_loop._decode_shape` 的 `summon` / `summon_many`
    两支都调 `_with_notify` 把这一栏带进 payload，`_dispatch_notify` 还会把缺省的 `to`
    补成"被派的那个角色"；而 `llmseam.META_FUNCTIONS` 的两个 schema 都没有这一格
    ⇒ 原生路上主控结构上给不出留痕，只能退回"框架据派活派生"的那一行 ——
    而那一行按本仓口径只是日志、不算交接（`agent_prompts` 循环协议第 2) 段逐字写着）。

    四条一起钉：① 两个 schema 都有 `notify`；② 那一格的 `required` 不含 `to`
    （缺省由 `_dispatch_notify` 补 —— 与收工那一份 `NOTIFY_JSON_SCHEMA` 的唯一差别）；
    ③ `to_shape` 原样透传；④ 解码器真收，且没给时不造键。
    """
    from agentflow import agent_loop as AL

    meta = {name: schema for name, _shape, schema in LL.META_FUNCTIONS}
    for san in ("framework_summon", "framework_summon_many"):
        props = meta[san]["properties"]
        assert "notify" in props, (san, sorted(props))
        sub = props["notify"]
        assert sub.get("required") == ["summary", "body"], (san, sub.get("required"))
        assert "to" in (sub.get("properties") or {}), (san, sorted(sub.get("properties") or {}))

    face = LL.build_tool_face("M", build_registry().registry)
    note = {"summary": "派了核引文这活", "body": "依据见 refs。"}
    for san, args in (("framework_summon",
                       {"role": "G", "action": "revise", "params": {}, "notify": note}),
                      ("framework_summon_many",
                       {"targets": [{"role": "B", "action": "run_once"}], "notify": note})):
        data, problem, detail = face.to_shape(_call(san, args))
        assert problem == "" and data is not None, (san, problem, detail)
        shape = next(sh for n, sh, _s in LL.META_FUNCTIONS if n == san)
        assert data[shape].get("notify") == note, data
        got, payload, bad = AL._shape_of(data)
        assert (got, bad) == (shape, "") and payload.get("notify") == note, (got, bad, payload)
    # 负控（不凭空造键）：没给 `notify` 时那一格不许出现
    plain, _p, _d = face.to_shape(
        _call("framework_summon", {"role": "G", "action": "revise", "params": {}}))
    assert "notify" not in plain["summon"], plain


# ============================================================ 三、负控与回落

def test_bad_arguments_are_reported_as_arguments_not_as_shape(tmp_path: Path):
    """负控（DSH 的 `parseArguments` + `INVALID_ARGS` 那一条）：
    参数不是合法 JSON ⇒ `judge_bad_args`，且错误里点名是哪个函数。

    与 `judge_bad_json` 分开是有用的：那句纠正能说"函数 X 的参数坏了"，
    而不是"认不出的形状（键：[...]）"—— 名字已经从结构化字段拿到了。
    """
    seam, _gw = _seam(tmp_path, [{"tool_calls": [{"id": "c1", "name": "conductor_state",
                                                  "arguments": "{坏 JSON"}]}])
    face = LL.build_tool_face("M", build_registry().registry)
    data, call = seam.ask_step("t", face=face)
    assert data is None
    assert call.problem == "judge_bad_args", call.to_dict()
    assert "conductor_state" in call.detail, call.detail
    assert J.is_judge_problem(call.problem), "新码必须登记进 JUDGE_PROBLEMS"


def test_an_unadvertised_function_is_refused_with_the_name_in_the_message(tmp_path: Path):
    """负控：模型调了一个没广告过的函数 ⇒ 拒，且消息里点名它（可行动）。"""
    seam, _gw = _seam(tmp_path, [{"tool_calls": [_call("fs_read", {"path": "a.txt"})]}])
    face = LL.build_tool_face("M", build_registry().registry)   # M 的面里没有 fs.read
    data, call = seam.ask_step("t", face=face)
    assert data is None and "fs_read" in call.detail, call.detail


def test_two_tool_calls_in_one_step_are_refused_not_silently_truncated(tmp_path: Path):
    """负控（一步一件事）：两条原生调用 ⇒ 明确拒；不许悄悄只执行第一条。"""
    seam, _gw = _seam(tmp_path, [{"tool_calls": [_call("conductor_state", {}),
                                                 _call("conductor_ledger", {"view": "stats"})]}])
    face = LL.build_tool_face("M", build_registry().registry)
    data, call = seam.ask_step("t", face=face)
    assert data is None and "只做一件事" in call.detail, call.detail


def test_the_text_fallback_is_untouched(tmp_path: Path):
    """正控（回落，口径零放宽）：上游不给 `tool_calls` ⇒ 走原来的文本 JSON 那一套。

    - 合法 JSON 形状 ⇒ 原样解析（`protocol` 回落成 `text`）；
    - 坏 JSON ⇒ 仍然是 `judge_bad_json`（没有因为"宽容参数"而放宽形状）。
    """
    seam, _gw = _seam(tmp_path, [
        {"text": json.dumps({"tool": "fs.read", "args": {"path": "a.txt"}, "why": ""})},
        {"text": "这不是 JSON"},
    ])
    face = LL.build_tool_face("A", _wired_registry(tmp_path))
    data, call = seam.ask_step("t", face=face)
    assert data == {"tool": "fs.read", "args": {"path": "a.txt"}, "why": ""}, data
    assert call.protocol == "text" and call.tool_calls == 0
    bad, call2 = seam.ask_step("t", face=face)
    assert bad is None and call2.problem == "judge_bad_json", call2.to_dict()


def test_a_seam_without_a_face_still_works(tmp_path: Path):
    """正控（无面 = 老行为）：不给 `face` 时与改造前逐字相同（既有调用点零改动）。"""
    seam, _gw = _seam(tmp_path, [{"text": json.dumps({"note": {"text": "一句"}})}])
    data, call = seam.ask_step("t")
    assert data == {"note": {"text": "一句"}} and call.protocol == "text"


# ============================================================ 四、广告名 → 真名（§52）

def test_the_advertised_name_is_mapped_back_at_execution(tmp_path: Path):
    """正控（`draft/37` §52 的真机读数）：模型把广告名写进 `tool` 字段时，执行层要认它。

    第四趟真机实测：模型看到了函数面里的 `fs_list`（带点的真名 `fs.list` 不能当函数名），
    却仍按文本协议回了一行 JSON，写的就是 `fs_list` ⇒ 执行层报 `unknown_tool`，29 步全废。
    这一条钉住"逐次映回真名 + 认账（`aliased_from`）"，而不是让那个名字继续撞墙。
    """
    from agentflow.agent_loop import AgentLoop

    reg = _wired_registry(tmp_path)
    loop = AgentLoop(role="A", session_root=tmp_path, registry=reg,
                     seam=LL.LlmSeam(role="A", session_root=tmp_path,
                                     gateway=_StubGateway([])))
    loop._face = LL.build_tool_face("A", reg)
    res = loop._do_tool({"name": "fs_list", "args": {"path": "."}, "why": "看盘"})
    assert res["ok"] is True, res
    assert res["tool"] == "fs.list", res
    assert res["aliased_from"] == "fs_list", "别名用了就要认账（读数上看得见）"


def test_an_unknown_name_is_still_refused_even_with_a_face(tmp_path: Path):
    """负控：映不回来的名字照旧拒 —— 别名只对"我们广告过的那些"生效。"""
    from agentflow.agent_loop import AgentLoop

    reg = _wired_registry(tmp_path)
    loop = AgentLoop(role="A", session_root=tmp_path, registry=reg,
                     seam=LL.LlmSeam(role="A", session_root=tmp_path,
                                     gateway=_StubGateway([])))
    loop._face = LL.build_tool_face("A", reg)
    res = loop._do_tool({"name": "fs_rm_rf", "args": {}, "why": "编的"})
    assert res["ok"] is False and "fs_rm_rf" in str(res["error"]), res
    assert "aliased_from" not in res


def test_the_name_args_shape_is_accepted_as_a_tool_call():
    """正控（`draft/37` §61）：`{"name": …, "args": …}`（没有 `tool` 键）必须被认成工具调用。

    第八、十趟真机各有一次这种写法，被判"认不出的形状"、计进 `bad_json`，
    第 3 次就 `bad_json_limit` 收场。这个形状没有第二种含义（循环协议里只有工具调用
    用 `name`+`args`），所以收下它、并留痕 `shape_alias="name"`。
    """
    from agentflow.agent_loop import _shape_of

    shape, payload, problem = _shape_of({"name": "fs.read", "args": {"path": "a"}, "why": "看"})
    assert (shape, problem) == ("tool", ""), (shape, problem)
    assert payload["name"] == "fs.read" and payload["args"] == {"path": "a"}, payload
    assert payload["shape_alias"] == "name", payload
    # 负控：`args` 不是对象 ⇒ 仍然是坏形状（别名只放宽"键名"，不放宽类型）
    shape2, _p2, problem2 = _shape_of({"name": "fs.read", "args": "a"})
    assert shape2 == "" and "args 必须是一个对象" in problem2, problem2
    # 负控：真·认不出的形状照旧拒
    shape3, _p3, problem3 = _shape_of({"foo": 1})
    assert shape3 == "" and "认不出的形状" in problem3, problem3

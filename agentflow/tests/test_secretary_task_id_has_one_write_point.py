# -*- coding: utf-8 -*-
"""① 绑定只有一个写点：`Secretary.task_id` 只许 `bind_task` 写。

## 取证（2026-11-20；`temp/splitdesign/05-VERDICT.md` §顺带上报，复算见 `temp/sdfect/00-before.txt`）

`tools/conductor_tools.py:3398` 曾以 `sender_secretary.task_id = sender` 绑实例。分片
照样生效（`decisions_path` 只读那一格），但 `bind_task` 的第二半 —— 存活标记
（`out/secretary/<role>-<task>.jsonl.alive`）—— 一个字节都没落。实测那一支的 4 跳链：

- `relay.jsonl` 4 行、四个 `secretary_task_id` 与链逐位一致（分片没坏）；
- `out/secretary/*.alive` 0 个；
- 同一 role/task 的 `secretary_alive()` 回 `checked=True, alive=False`，理由逐字
  「没有存活标记（没绑过实例，或已经注销）」。

被破的不变式是 `bind_task` 的那句话「绑上 = 有存活标记」（是 `close` 那一半
「同生同死」的前提）：一个已经绑过的实例被读成没绑过。三态纪律里最忌的折平
不是把"没查成"写成"通过"，而是把"绑过、只是没标记"写成"没绑过"——它让
「上次没善终」与「从来没跑过」在纸上长得一样。

## 本文件钉四件事

1. 静态：可能持有 Secretary 的模块里，`task_id` 的裸赋值 0 处（唯一例外形态是写在
   `with pytest.raises(AttributeError):` 里、用来断言"写不进去"的探针）；`_task_id`
   全仓只有 `Secretary.bind_task` 一处写（AST 扫 `src/` + `tests/` + `tools/` + `scripts/`）。
2. 结构：`task_id` 是只读属性（没有 setter），外部赋值当场 `AttributeError` ——
   "只许 bind_task 写"不再靠自觉。
3. 行为：`conductor.guide` 那一支经 `bind_task` 之后存活标记在、分片照旧；
   转发链的下一跳（`_peer_secretary`）经 `mark_alive=False` 只分片、不伪造存活。
4. 反真空：把 `:3398` 的裸赋值与 `bind_task` 里旧的 `self.task_id =` 各放回去一份
   ⇒ 第 1 条必红；把 `bind_task` 打桩成"只写字段" ⇒ 第 3 条必红。

零模型：夹具只有台账、名册与板项；工作区在 `tmp_path` 里自建。
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import warnings
from dataclasses import dataclass
from typing import Any

import pytest

from agentflow import secretary as SEC
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.store import Store
from agentflow.tools import build_registry
import _secretary_home as HOME  # 打桩打在定义处（搬家后 SEC 那一格只是再导出）

REPO = pathlib.Path(__file__).resolve().parents[1]

#: 扫描面：产品代码 + 判据 + 开发期脚本（`temp/` 与 `projects/` 不在内）。
SCAN_ROOTS: tuple[str, ...] = ("src", "tests", "tools", "scripts")

#: 会被本判据计入的写点（`task_id` 是公开读口，`_task_id` 是它现在的存储格）。
WRITE_ATTRS: tuple[str, ...] = ("task_id", "_task_id")

SID = "bind-one-write-point"


# ---------------------------------------------------------------- 源码扫描


@dataclass(frozen=True)
class Write:
    """一个 `X.<attr> = ...` 写点。"""

    module: str
    qualname: str
    receiver: str
    attr: str
    line: int
    refused_probe: bool = False

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.module, self.qualname, self.receiver, self.attr)


def _parse(text: str) -> ast.AST:
    """`ast.parse` 的薄壳：压掉历史源码里 `"\\d"` 一类转义带来的告警。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ast.parse(text)


def _qualnames(tree: ast.AST) -> dict[int, str]:
    """每个函数 / 类节点的 qualname。"""
    out: dict[int, str] = {}

    def walk(node: ast.AST, stack: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out[id(child)] = ".".join(stack + [child.name])
                walk(child, stack + [child.name])
            else:
                walk(child, stack)

    walk(tree, [])
    return out


def _spans(tree: ast.AST) -> list[tuple[int, int, int, str]]:
    """所有函数 / 类的行区间 `(起点, 终点, 名字长度, qualname)`（取最内层用它）。"""
    names = _qualnames(tree)
    out: list[tuple[int, int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        name = names.get(id(node), node.name)
        out.append((node.lineno, node.end_lineno or node.lineno, len(name), name))
    return out


def _enclosing(spans: list[tuple[int, int, int, str]], line: int) -> str:
    best, best_len = "", 0
    for start, end, length, name in spans:
        if start <= line <= end and length > best_len:
            best, best_len = name, length
    return best


def _could_hold_a_secretary(text: str) -> bool:
    """这份源码有没有可能持有 / 造出一个 Secretary（静态预筛，不 import）。

    为什么要预筛：全仓的 `task_id` 裸赋值里有一批属于别的类（`ProgramSpan` 的
    `self.task_id`、`CallRecord` 的 `rec.task_id`、`ModelClient` 的 `c.task_id`）。
    把它们也算进来就只剩两条路：拉一张白名单（白名单会腐烂），或者把判据放宽到
    "看名字像不像"。这里选第三条：只有提到 `Secretary` / `secretary` / `for_role`
    的模块才可能持有秘书（改个名也要先在这里出现），其余模块里同名属性与
    这条不变式无关。非 self 接收者（`sender_secretary` / `peer` / `sec`）同样被这条
    规则覆盖 —— 它们所在的文件一定提到秘书。
    """
    return "Secretary" in text or "secretary" in text or "for_role" in text


def _scan_sources() -> dict[str, str]:
    """`{仓库相对路径: 源码}`：扫描面里的全部 `.py`。"""
    out: dict[str, str] = {}
    for rel in SCAN_ROOTS:
        base = REPO / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            out[path.relative_to(REPO).as_posix()] = path.read_text(
                encoding="utf-8", errors="replace")
    return out


#: 整棵树的源码只读一次（三条用例读的是同一份扫描；各扫一遍是"同一读数两个主人"）。
_CACHE: dict[str, object] = {}


def _all_sources() -> dict[str, str]:
    if "sources" not in _CACHE:
        _CACHE["sources"] = _scan_sources()
    return dict(_CACHE["sources"])  # type: ignore[arg-type]


def _inside_refusal_probe(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    """这一句赋值是不是写在 `with pytest.raises(AttributeError):` 里。

    全仓唯一的合法裸赋值就是这一种：它不是在写，而是在断言"写不进去"。把它与真正的
    绕过区分开，靠的是形态（AST 上的 `with` 上下文），不是文件名或注释。
    """
    cur = parents.get(id(node))
    while cur is not None:
        if isinstance(cur, ast.With):
            for item in cur.items:
                text = ast.unparse(item.context_expr)
                if "raises" in text and "AttributeError" in text:
                    return True
        cur = parents.get(id(cur))
    return False


def _writes(sources: dict[str, str]) -> list[Write]:
    """扫出全部 `X.task_id = ...` / `X._task_id = ...` 写点（赋值 / 注解 / 自增都算）。"""
    found: list[Write] = []
    for module, text in sorted(sources.items()):
        # 字面预筛只省时间，判的是下面的 AST（预筛掉的文件里连 ".task_id" 都没有）。
        if ".task_id" not in text and "._task_id" not in text:
            continue
        tree = _parse(text)
        spans = _spans(tree)
        parents: dict[int, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[id(child)] = parent
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if not isinstance(target, ast.Attribute) or target.attr not in WRITE_ATTRS:
                    continue
                found.append(Write(
                    module=module,
                    qualname=_enclosing(spans, node.lineno),
                    receiver=ast.unparse(target.value),
                    attr=target.attr,
                    line=node.lineno,
                    refused_probe=_inside_refusal_probe(node, parents),
                ))
    return found


def _describe(sites: list[Write]) -> str:
    return "\n".join(f"  {w.module}:{w.line}  {w.receiver}.{w.attr}  "
                     f"(在 {w.qualname or '<模块级>'})" for w in sites)


def _all_writes() -> list[Write]:
    """整棵树的写点只扫一次（同一读数不许有两个主人）。"""
    if "writes" not in _CACHE:
        _CACHE["writes"] = _writes(_all_sources())
    return list(_CACHE["writes"])  # type: ignore[arg-type]


def _bind_calls(sources: dict[str, str]) -> list[tuple[str, str, str, dict[str, str], list[str]]]:
    """扫出全部 `x.bind_task(...)` 调用：`(模块, 接收者, 所在 qualname, 关键字, 位置参数)`。"""
    found: list[tuple[str, str, str, dict[str, str], list[str]]] = []
    for module, text in sorted(sources.items()):
        if "bind_task" not in text:
            continue
        tree = _parse(text)
        spans = _spans(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "bind_task"):
                continue
            found.append((
                module,
                ast.unparse(node.func.value),
                _enclosing(spans, node.lineno),
                {kw.arg or "": ast.unparse(kw.value) for kw in node.keywords},
                [ast.unparse(arg) for arg in node.args],
            ))
    return found


# ---------------------------------------------------------------- 1 静态：一个写点


def test_no_bare_task_id_write_in_a_module_that_can_hold_a_secretary() -> None:
    """静态：`task_id` 的裸赋值在"可能持有 Secretary 的模块"里 0 处；`_task_id` 只有一处。"""
    sources = _all_sources()
    assert len(sources) >= 500, f"只扫到 {len(sources)} 个 .py ⇒ 扫描面没接上（不是'没有违规'）"

    scoped = {m: t for m, t in sources.items() if _could_hold_a_secretary(t)}
    # 正控：这些模块确实在扫描面里（少一个就是漏扫）。它们是这条不变式的四处现场：
    # 绑定点（secretary.py）、两个曾经裸赋值的调用方（conductor_tools.py / _peer_secretary
    # 在 secretary.py 内）、唯一的生产绑定调用点（agent_loop.py）。
    for must in ("src/agentflow/secretary.py", "src/agentflow/tools/conductor_tools.py",
                 "src/agentflow/agent_loop.py", "src/agentflow/tools/table_tools.py"):
        assert must in scoped, f"{must} 不在扫描面里 ⇒ 判据失去对象"
    assert len(scoped) >= 50, f"只有 {len(scoped)} 个模块提到秘书 ⇒ 预筛坏了"

    all_writes = _all_writes()
    bad = [w for w in all_writes
           if w.attr == "task_id" and w.module in scoped and not w.refused_probe]
    assert not bad, (
        "可能持有 Secretary 的模块里出现了 task_id 裸赋值（唯一绑定点是 bind_task）：\n"
        + _describe(bad))
    # 豁免面只有一种形态：`with pytest.raises(AttributeError):` 里的那一句 —— 它是
    # 在断言"写不进去"，不是绕过。它也必须真的存在，否则"只读属性"那条判据没被验证。
    probes = [w for w in all_writes if w.attr == "task_id" and w.refused_probe]
    assert probes, ("全仓找不到一处'赋值应当失败'的探针 ⇒ 只读属性那条判据可能没被验证")
    assert all(w.module.startswith("tests/") for w in probes), (
        "产品代码里出现了'赋值应当失败'的探针 ⇒ 它不是在测只读属性：\n" + _describe(probes))

    storage = [w for w in all_writes if w.attr == "_task_id"]
    # 两处，且只有这两处：构造函数落初值（"还没绑"），`bind_task` 落绑定。初值不是绑定
    # （它把 `task_id` 置空、分片随即退回老文件），真正的写点是 `bind_task`。
    # 搬家之后 qualname 是 SessionMixin.bind_task（方法进了混入类）：比"最后一段"，
    # 因为这一条钉的是"哪两个地方写"，不是"类叫什么名"。模块按声明定位。
    assert {(w.module, w.qualname.split(".")[-1]) for w in storage} == {
        (HOME.module_rel("Secretary.__init__"), "__init__"),
        (HOME.module_rel("Secretary.bind_task"), "bind_task"),
    }, ("`_task_id`（task_id 的存储格）只许构造函数与 bind_task 写：\n" + _describe(storage))

    # 两个现场走的是 bind_task，且"代表别人"那一档显式声明了不写标记。
    calls = _bind_calls(sources)
    guide = [c for c in calls if c[0] == "src/agentflow/tools/conductor_tools.py"]
    assert len(guide) == 1, guide
    assert guide[0][1] == "sender_secretary" and guide[0][4] == ["sender"], guide[0]
    assert "mark_alive" not in guide[0][3], (
        "conductor.guide 是'我自己这一趟'的秘书，必须走会写存活标记的那一档", guide[0])
    peer = [c for c in calls
            if c[0] == HOME.module_rel("Secretary._peer_secretary")
            and c[2].split(".")[-1] == "_peer_secretary"]
    assert len(peer) == 1, peer
    assert peer[0][3].get("mark_alive") == "False", (
        "转发链下一跳只许分片、不许伪造存活标记：mark_alive=False 是显式契约", peer[0])


# ---------------------------------------------------------------- 2 结构：只读属性


def test_task_id_is_a_read_only_property(tmp_path: pathlib.Path) -> None:
    """结构：`task_id` 没有 setter，外部赋值当场 AttributeError（不靠自觉）。"""
    assert isinstance(SEC.Secretary.task_id, property), type(SEC.Secretary.task_id)
    assert SEC.Secretary.task_id.fset is None, "task_id 又被做成可写属性了"
    sec = SEC.Secretary("M", root=tmp_path)
    with pytest.raises(AttributeError):
        sec.task_id = "t-000001"  # type: ignore[misc]
    # 只读不等于读不到：没绑过 ⇒ 空串（这是 `decisions()` 选老文件那一档的判据）。
    assert sec.task_id == ""


# ---------------------------------------------------------------- 夹具（零模型）


def _agent_row(cond: Conductor, *, role: str, parent: str, key: str) -> str:
    prow = cond._task(parent) or {}
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "write_report", "called_by": "M",
        "parent_task_id": parent, "depth": int(prow.get("depth") or 1) + 1,
        "input_key": key, "status": "running", "outcome": None,
        "refusal_reason": None, "instance": "", "detail": f"{role} 的活（{key}）",
        "error": None, "started_at": "2026-11-20T00:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="start:bind-one-write-point")


def _env(root: pathlib.Path, *, levels: int = 3) -> dict[str, Any]:
    """一条从顶趟往下的链（顶趟 + 3 层），每一级都登记进名册。"""
    ws = root / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    top = cond.open_top_level_run("M", "绑定写点的顶趟")
    chain = [top]
    roles = ["D", "E", "F", "G"]
    for i in range(levels):
        chain.append(_agent_row(cond, role=roles[i], parent=chain[-1], key=f"bind@{i}"))
    writer = SEC.for_role("M", root=ws, store=st)
    for i in range(len(chain) - 1):
        got = writer.roster_add(owner=chain[i], role=roles[i], task_id=chain[i + 1],
                                brief="链上一跳")
        assert got["problem"] == "", got
    return {"ws": ws, "st": st, "cond": cond, "reg": reg, "top": top, "chain": chain}


def _guide(env: dict[str, Any]) -> Any:
    """以顶趟那一行（M）的身份调 `conductor.guide`（生产路径由 `_do_tool` 挂同一身份）。"""
    with calling_as(env["top"], "M", session_root=str(env["ws"]), sid=SID):
        return env["reg"].call("conductor.guide", role="M",
                               to="->".join(env["chain"]), text="探针：停一停")


def _relay_rows(ws: pathlib.Path) -> list[dict[str, Any]]:
    path = ws / "out" / "secretary" / "relay.jsonl"
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _alive_names(ws: pathlib.Path) -> list[str]:
    return sorted(p.name for p in (ws / "out" / "secretary").glob("*.alive"))


def _guide_and_read_markers(root: pathlib.Path) -> tuple[dict[str, Any], Any, list[str]]:
    """判据 3 的两条读数共用这一份（正控与反真空同形）。"""
    env = _env(root)
    res = _guide(env)
    assert res.ok, res.to_dict()
    assert str(res.data.get("status")) == "delivered", res.data
    rows = _relay_rows(env["ws"])
    assert [r["secretary_task_id"] for r in rows] == env["chain"], rows
    alive = _alive_names(env["ws"])
    top = env["chain"][0]
    assert alive == [f"M-{top}.jsonl.alive"], (
        "绑定之后存活标记应当只有发起方这一个；实测 " + repr(alive)
        + "（0 个 = 那一支绕过了 bind_task 的第二半；多于 1 个 = 转发链的下一跳"
          "伪造了'它活着'）")
    return env, res, alive


# ---------------------------------------------------------------- 3 行为：标记在、下一跳不伪造


def test_the_guide_branch_leaves_the_alive_marker(tmp_path: pathlib.Path) -> None:
    """行为：`conductor.guide` 那一支经 bind_task 之后，存活标记在、分片照旧。"""
    env, _res, alive = _guide_and_read_markers(tmp_path)
    top = env["chain"][0]
    marker = json.loads((env["ws"] / "out" / "secretary" / alive[0]).read_text(encoding="utf-8"))
    assert marker["task_id"] == top, marker
    assert marker["role"] == "M", marker
    assert int(marker["pid"]) == os.getpid(), marker
    assert str(marker["at"]).strip(), marker
    # 分片没有因为这次改法而退化：发起方那一份台账就是分片名。
    assert SEC.decisions_path(env["ws"], "M", top).name == f"M-{top}.jsonl"
    assert len(_relay_rows(env["ws"])) == len(env["chain"]), _relay_rows(env["ws"])


def test_the_relay_hop_does_not_fabricate_liveness(tmp_path: pathlib.Path) -> None:
    """行为：转发链的下一跳只分片、不写存活标记（`mark_alive=False` 的契约）。"""
    env, _res, alive = _guide_and_read_markers(tmp_path)
    # 4 跳转发是真的 ⇒ `_peer_secretary` 真的被走过（不然这条负控是真空的）。
    assert len(_relay_rows(env["ws"])) == 4, _relay_rows(env["ws"])
    assert len(alive) == 1, alive
    sender = env["chain"][0]
    assert alive == [f"M-{sender}.jsonl.alive"], alive
    # 链上其余三位一个标记都没有：转发是请求，不是接管。
    for tid in env["chain"][1:]:
        assert not any(name.endswith(f"-{tid}.jsonl.alive") for name in alive), (tid, alive)


# ---------------------------------------------------------------- 4 反真空


def test_putting_the_bare_write_back_turns_a_red() -> None:
    """反真空：把两处裸赋值各放回去一份 ⇒ 静态判据必红（用的是真源码文本）。"""
    sources = _all_sources()

    ct_rel = "src/agentflow/tools/conductor_tools.py"
    ct = sources[ct_rel]
    assert "sender_secretary.bind_task(sender)" in ct, "反真空的前提变了：那一行不是预期写法"
    put_back = ct.replace("sender_secretary.bind_task(sender)",
                          "sender_secretary.task_id = sender")
    caught = [w for w in _writes({ct_rel: put_back}) if w.attr == "task_id"]
    assert caught and caught[0].receiver == "sender_secretary", caught
    assert _could_hold_a_secretary(put_back), (
        "放回去的源码不在'可能持有秘书'的扫描面里 ⇒ 这条反真空证明不了第 1 条有牙")

    sec_rel = HOME.module_rel("Secretary.bind_task")
    sec = sources[sec_rel]
    storage = 'self._task_id = str(task_id or "")'
    assert storage in sec, "反真空的前提变了：bind_task 的存储格不是预期写法"
    old = sec.replace(storage, 'self.task_id = str(task_id or "")')
    caught2 = [w for w in _writes({sec_rel: old}) if w.attr == "task_id"]
    assert caught2 and caught2[0].qualname.split(".")[-1] == "bind_task", caught2


def test_stubbing_bind_task_to_a_bare_write_loses_the_marker(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把 `bind_task` 打桩成"只写字段"（改前那一半）⇒ 行为判据必红。"""
    def bare(self: Any, task_id: str, *, mark_alive: bool = True) -> None:
        # 用 setattr 而不是赋值：这里要模拟"只写字段"，不能让判据自己的源码里多出一个
        # `_task_id =` 写点（静态那一条数的是 AST 赋值节点）。
        setattr(self, "_task_id", str(task_id or ""))

    monkeypatch.setattr(SEC.Secretary, "bind_task", bare)
    with pytest.raises(AssertionError):
        _guide_and_read_markers(tmp_path)

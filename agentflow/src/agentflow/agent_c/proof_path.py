# -*- coding: utf-8 -*-
"""角色 C 的「去重自足证明路径」：把几个目标的依赖闭包排成一条线性序。

需求真身（业主 2026-11-26）：G 把几条核心定理的编号交给 C；C 分析各自依赖链到根
（定义 / 引文成果 / 穷举实验 / 自足证明；引文与自足证明自己也会依赖定义 ⇒ 最根源是
定义）；C 规划一条去重的自足证明路径交给 G。三个验收例子（逐位相等）：

    例 1：A←概念1；B←概念1,A；C←概念2,A；D←A,B；E←概念1,B,D ⇒ 写 E：概念1 → A → B → D → E（C 与 概念2 不出现）
    例 2：实验a←概念1；A←实验a；B←概念1；C 路径一←A、路径二←B；D←概念1,C ⇒ 概念1 → B → C → D
    例 3：A←概念1,3；B←概念2,3；C←概念1,A；D←B,C；E←C ⇒ 写 D 与 E：概念1和3 → A → C → E → 概念2 → B → D

排序规则不是任意拓扑序，而是「每个条目紧贴它第一个使用点之前」（按需引入 / 尽量晚
引入）：① 目标之间闭包小的先排（同大小按调用方给的顺序）—— 先排小需求，共享依据只
落一次（例 3 的 E 闭包是 D 的真子集 ⇒ E 先排，D 只补「概念2 → B → D」）；② 目标
内部对每条候选证明路径做后序 DFS：前提先排、自己后排、同节点只排一次，被依赖端按节点
号升序访问（与边的插入顺序无关，两次运行逐字节一致）。由此每个节点都排在它所有前提
之后、第一次被用到之前，且与第一个使用点之间只隔着那个使用点自己的其它前提。

选哪条候选路径：先比「新增几个本文别处用不到的根」，少者胜；并列再比新节点数、长度、
`(证明号, 组号)`。例 2 的 C 两条路径里，B 那条新增根 0（概念1 别处已用到）、A 那条
多引入实验a（1）⇒ 选 B。逐条记在 `choices`（含 `elsewhere_roots` / `new_root_nodes`）。
四档根：`definition` / `literature` / `experiment`（行级：`method="exhaustive_search"`、
`result="supports"`、证书 `enumeration_bound`、`search_bound` 非空、程序事实齐、
`exit_code==0`；写入期 `Experiment.validate` 已核过穷尽材料，读侧不重判）/ 
`self_contained_proof`。`method="formal"` 的 exp 行仍不是根（形式化入链属另一路）。
三态：读不到 / 不可判一律 `checked=False` 并逐条写清缺什么（`missing`）；绝不折成
「没有依赖」或「已经是根」。`plan_path` 是纯函数（零模型调用、不落库、不读表；
`root` 只读 V 台账那一格）。`plan_report` 是适配层：把计划挂到 C 既有的
`_report("proof_chain", …)` 上（登记走 `analysis_reports`，四格放 payload 顶层）。
"""
from __future__ import annotations

import json
from pathlib import Path

from ._support import Any, Mapping, Sequence
from .. import proofloc as _PL          # `used_by` 尾巴（`#pN`）只有这一处解析
from .. import statementledger as SL   # 取数 `rows_of` / 全表→索引 `index_by_id`
from .. import textutil as T           # 别名/标签规范化（与 proof_chain 同口径）
from ..migrate_concepts import PRIMITIVE_PROOF as CONCEPT_PRIMITIVE_MARKER

TIER_LABELS: dict[str, str] = {
    "definition": "定义", "literature": "引文成果",
    "experiment": "穷举实验", "self_contained_proof": "自足证明",
}

DEFAULT_MAX_DEPTH = 64

MAX_PLAN_NODES = 4000       # 一次规划最多评估多少节点（超了报「没算完」，绝不静默截断）
MAX_EXCLUDED = 200          # `excluded` 最多列多少条（超出截断并写进 `excluded_note`）
ENUMERATION_CERT_KIND = "enumeration_bound"  # 穷举那一档要求的证书形态：枚举界


def _split_used_by(used_by: str) -> tuple[str, int, str]:
    """把一条依赖的 `used_by` 拆成 `(命题侧键, 证明号, problem)`，先按前缀分流。

    `doc:` 前缀的尾巴是 claim 号（`doc:0001#claim-3`）、不是证明号；不分流就把它送进
    `proofloc`，一条正常引用会被记成坏尾巴（`problem` 非空，按 canonical 读 —— 读数
    看着没变，台账里已悄悄多了一类假缺陷）。`problem` 非空 = 尾巴坏了（`#p0` /
    `#pabc` / 多段），此时按 canonical（第 1 条）读并把原串交回调用方留痕 —— 绝不抛。
    """
    text = str(used_by or "")
    if text.startswith("doc:"):
        return text, _PL.DEFAULT_PROOF_NO, ""
    head, number, problem = _PL.parse_used_by_checked(text)
    return head, number, problem


def verified_ok(root: str | Path | None, stmt_id: str) -> bool:
    """V 的台账（`verifications/<号>.jsonl`）里有没有「成立」。

    读不到 / 解析不动 ⇒ False（「没读到」不等于「审过了」，也不许折成「审过了」）。
    """
    if not root:
        return False
    path = Path(root) / "verifications" / f"{stmt_id}.jsonl"
    if not path.is_file():
        return False
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and "成立" in str(json.loads(line).get("verdict") or ""):
                return True
    except Exception:  # noqa: BLE001 - 读/解析不动 ⇒ 不当成「审过了」
        return False
    return False


def _target_of(dep: Mapping[str, Any]) -> tuple[str, str]:
    """一条边的被依赖端 ⇒ `(节点号, 种类)`（`stmt:` / `exp:` / `lit:` / `doc:` / `""`）。"""
    for key, kind, prefix in (("source_stmt_id", "stmt", "stmt"),
                              ("source_experiment_id", "exp", "exp"),
                              ("source_lit_id", "lit", "lit"),
                              ("source_doc_id", "doc", "doc")):
        if str(dep.get(key) or ""):
            return f"{prefix}:{dep[key]}", kind
    return "", ""


def _node_ref(value: Any) -> str:
    """把节点号写到同一种写法上（`0008` 与 `stmt:0008` 是同一个节点）。"""
    text = str(value or "").strip()
    if not text:
        return ""
    return text if ":" in text else f"stmt:{text}"


def experiment_root_reading(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """穷举实验那一档的根读数 ⇒ `{"root","tier","why","proof_grade","missing"}`。

    只核行级事实（不读盘）：写入期 `Experiment.validate` 等已把穷尽材料核过；缺哪一
    格就点名哪一格，绝不折成一句「不是根」。
    """
    if not isinstance(row, Mapping):
        return {"root": False, "tier": "", "proof_grade": False,
                "why": "实验不在册（experiments 里没有这个号）", "missing": ["实验不在册"]}
    missing: list[str] = []
    if str(row.get("status") or "") == "voided":
        missing.append("这一行已撤销（status=voided）")
    method = str(row.get("method") or "")
    if method != "exhaustive_search":
        missing.append(f"method={method!r} 不是穷举（本档只认 exhaustive_search）")
    if str(row.get("result") or "") != "supports":
        missing.append(f"result={row.get('result')!r} 不是对命题的支撑（要 'supports'）")
    cert = row.get("certificate")
    cert_kind = str(cert.get("kind") or "") if isinstance(cert, Mapping) else ""
    if cert_kind != ENUMERATION_CERT_KIND:
        missing.append(f"certificate.kind={cert_kind!r} 不是枚举界（要 {ENUMERATION_CERT_KIND}）")
    if not (isinstance(row.get("search_bound"), Mapping) and row.get("search_bound")):
        missing.append("缺搜索边界 search_bound")
    if not str(row.get("code_path") or "").strip():
        missing.append("缺程序路径 code_path（穷举的签名就是那份程序）")
    if not str(row.get("code_hash") or "").strip():
        missing.append("缺程序哈希 code_hash（脚本一改记录就指向另一段代码）")
    exit_code = row.get("exit_code")
    if exit_code is None:
        missing.append("exit_code 缺（跑没跑成不可判）")
    else:
        try:
            if int(exit_code) != 0:
                missing.append(f"exit_code={exit_code!r} 不是 0")
        except (TypeError, ValueError):
            missing.append(f"exit_code={exit_code!r} 读不成整数")
    if missing:
        return {"root": False, "tier": "", "proof_grade": False,
                "why": "不是可走到根的穷举实验：" + "；".join(missing), "missing": missing}
    return {"root": True, "tier": "experiment",
            "proof_grade": str(row.get("evidence_kind") or "") == "proof",
            "why": ("在册的穷举实验（method=exhaustive_search、证书 enumeration_bound、"
                    "搜索边界与程序事实齐、exit_code=0）"), "missing": []}


class _Snapshot:
    """一次规划用的只读快照：三张索引 + 依赖分组 + 反向引用。"""

    def __init__(self, statements: Sequence[Mapping[str, Any]],
                 dependencies: Sequence[Mapping[str, Any]],
                 experiments: Sequence[Mapping[str, Any]] = (),
                 literature: Sequence[Mapping[str, Any]] = (),
                 root: str | Path | None = None) -> None:
        self.stmts = SL.index_by_id(statements)     # 全表→索引只走查口（不自己写推导式）
        # 主键是 `experiment_id`：旧写法读 `exp_id`（表里没这个键），9 行只建出 1 条空键。
        self.exps = {str(r.get("experiment_id") or ""): dict(r) for r in experiments}
        self.lits = {str(r.get("lit_id") or ""): dict(r) for r in literature}
        self.root_dir = root
        self.edges: dict[str, dict[int, dict[int, list[dict[str, Any]]]]] = {}
        self.users: dict[str, list[str]] = {}
        self.bad_used_by: list[str] = []
        for dep in dependencies:
            used = str(dep.get("used_by") or "")
            if not used:
                continue
            head, proof_no, problem = _split_used_by(used)
            if problem and used not in self.bad_used_by:
                self.bad_used_by.append(used)
            key = head[5:] if head.startswith("stmt:") else head
            try:
                group = int(dep.get("path_group") or 1)
            except (TypeError, ValueError):
                group = 1
            self.edges.setdefault(key, {}).setdefault(proof_no, {}).setdefault(
                group, []).append(dict(dep))
            tgt, _kind = _target_of(dep)
            user_ref = key if key.startswith("doc:") else f"stmt:{key}"
            if tgt and key and user_ref not in self.users.setdefault(tgt, []):
                self.users[tgt].append(user_ref)

    def candidates(self, node: str) -> dict[tuple[int, int], list[dict[str, Any]]]:
        """候选证明路径：`(证明号, 组号)` → 那一组的边（组内 AND、组间 OR）。

        与 `proof_chain._DepGraph.groups_of` 同一口径：不跨证明号合并（一份证明借另一
        份的依赖 = 「借光」）。
        """
        bare = node[5:] if str(node).startswith("stmt:") else str(node)
        found = self.edges.get(bare) or {}
        return {(int(no), int(group)): [dict(d) for d in edges]
                for no, by_group in found.items() for group, edges in by_group.items()}

    def label(self, node: str) -> str:
        """人读标签（命题行用 label 缺省退号；实验/文献各取可读的那一格）。"""
        kind, _, bare = str(node).partition(":")
        if kind == "stmt":
            return str((self.stmts.get(bare) or {}).get("label") or bare)
        row = (self.exps if kind == "exp" else self.lits).get(bare) or {}
        return str(row.get("claim") or row.get("claim_key") or row.get("title") or bare)

    def kind(self, node: str) -> str:
        """节点种类：命题行给它自己的 `kind`，实验/文献各给一个固定名。"""
        kind, _, bare = str(node).partition(":")
        if kind == "stmt":
            return str((self.stmts.get(bare) or {}).get("kind") or "theorem")
        return {"exp": "experiment", "lit": "literature"}.get(kind, kind)

    def root_reading(self, node: str) -> dict[str, Any]:
        """这个节点是不是根、是哪一档（四档；理由逐条写清）。"""
        kind, _, bare = str(node).partition(":")
        if kind == "lit":
            if bare in self.lits:
                return {"root": True, "tier": "literature", "proof_grade": False,
                        "why": "在册文献（引文成果）", "missing": []}
            return {"root": False, "tier": "", "proof_grade": False,
                    "why": "文献不在册", "missing": ["文献不在册"]}
        if kind == "exp":
            return experiment_root_reading(self.exps.get(bare))
        if kind != "stmt":
            return {"root": False, "tier": "", "proof_grade": False,
                    "why": f"{kind} 不是可走到根的节点（手稿不入链）",
                    "missing": [f"{kind} 不是可走到根的节点"]}
        row = self.stmts.get(bare)
        if row is None:
            return {"root": False, "tier": "", "proof_grade": False,
                    "why": "被依赖的那条命题不在册", "missing": ["被依赖的那条命题不在册"]}
        if self.candidates(node):
            return {"root": False, "tier": "", "proof_grade": False, "why": "",
                    "missing": []}
        if str(row.get("kind") or "") == "concept":
            # 概念是「定义性的根」：有定义 ⇒ 根；历史哨兵照旧认；待补行不是根，理由说
            # 「定义还没到」而不是「缺证明」。
            if (str(row.get("proof_text") or "") == CONCEPT_PRIMITIVE_MARKER
                    or str(row.get("statement_full") or "").strip()):
                return {"root": True, "tier": "definition", "proof_grade": False,
                        "why": "概念行有定义（定义性的根）", "missing": []}
            return {"root": False, "tier": "", "proof_grade": False,
                    "why": "概念的定义还没到（pending_definition）⇒ 这一条还不是根",
                    "missing": ["概念的定义还没到（pending_definition）"]}
        if str(row.get("evidence_kind") or "") in ("proof",):
            return {"root": True, "tier": "self_contained_proof", "proof_grade": True,
                    "why": "无依赖边且有 proof 证据（自足证明）", "missing": []}
        if (str(row.get("origin") or "") == "own_result"
                and verified_ok(self.root_dir, bare)):
            return {"root": True, "tier": "self_contained_proof", "proof_grade": True,
                    "why": "无依赖边、且 V 的台账里记为成立（经审核的自证定理）",
                    "missing": []}
        return {"root": False, "tier": "", "proof_grade": False,
                "why": "依赖没写（没有依赖边，也没有 proof 证据；也不是经审核的自证定理）",
                "missing": ["依赖没写（没有依赖边，也没有 proof 证据）"]}

    def closure(self, starts: Sequence[str], *,
                budget: dict[str, int] | None = None) -> set[str]:
        """从 `starts` 出发、沿所有候选证明路径可达的节点集（含起点，到根即停）。"""
        seen: set[str] = set()
        stack = [str(s) for s in starts if str(s)]
        limit = int((budget or {}).get("max") or MAX_PLAN_NODES)
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            if len(seen) > limit:
                break
            if self.root_reading(node)["root"]:
                continue
            for edges in self.candidates(node).values():
                for dep in edges:
                    tgt, _kind = _target_of(dep)
                    if tgt and tgt not in seen:
                        stack.append(tgt)
        return seen


def path_costs(graph: Any, rows: Sequence[Mapping[str, Any]],
               target: str = "") -> dict[tuple[int, int], dict]:
    """每条候选路径「新增几个本文别处用不到的根」—— 供 `proof_chain` 排序做并列判据。

    口径（可复算，与 `plan_path` 的 `choices` 同一把尺）：根集 = 承重脊
    （`path_shapes.spine_nodes`）上被 `graph.is_root` 判真的节点；「本文别处」=
    台账里除这条候选路径之外的引用者（`graph.users`）。只做并列判据。
    """
    users = getattr(graph, "users", None) or {}
    target_ref = _node_ref(target)
    per = [{"key": (int(row.get("proof_no") or 1), int(row.get("path_group") or 1)),
            "roots": [n for n in (row.get("spine_nodes") or []) if graph.is_root(n)[0]],
            "path": [target_ref] + list(row.get("spine_nodes") or [])}
           for row in rows]
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for item in per:
        elsewhere = sorted(n for n in item["roots"]
                           if _used_outside(users.get(n) or (), item["path"]))
        fresh = sorted(set(item["roots"]) - set(elsewhere))
        out[item["key"]] = {"roots": sorted(set(item["roots"])),
                            "elsewhere_roots": elsewhere,
                            "new_root_nodes": fresh, "new_roots": len(fresh)}
    return out


def _used_outside(users: Sequence[str], path_nodes: Sequence[str]) -> bool:
    """这个根在台账里有没有「这条候选路径之外」的使用点（= 本文别处用得到）。

    只看台账里谁引用了它，与排布顺序无关（单目标链与多目标规划同一把尺）。
    """
    inside = set(path_nodes)
    return any(user not in inside for user in users)


def _pick_candidate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """从可行候选里挑一条：新增根最少，其次新节点数、长度、`(证明号, 组号)`。

    单列成函数是为了让反真空能把选路键换成旧的 `(length, proof_no, group)`：
    例 2 的 C 一旦用旧键就会翻成 A 路径（业主口径的 ③）。
    """
    return min(rows, key=lambda r: (r["new_roots"], r["new_nodes"], r["length"],
                                    r["proof_no"], r["path_group"]))


def _missing(node: str, why: str) -> dict[str, str]:
    """一条「这一趟没算成」的读数（节点 + 缺什么）。"""
    return {"node": str(node), "why": str(why)}


class _Walker:
    """沿候选证明路径做「后序 DFS + 去重 + 按新增根选路」，产出一条线性序。"""

    def __init__(self, snapshot: _Snapshot, *, max_depth: int = DEFAULT_MAX_DEPTH,
                 max_nodes: int = MAX_PLAN_NODES) -> None:
        self.snap = snapshot
        self.max_depth = max(1, int(max_depth))
        self.max_nodes = max(1, int(max_nodes))
        self.emitted: list[str] = []
        self.emitted_set: set[str] = set()
        self.root_of: dict[str, dict[str, Any]] = {}   # 节点 → 根读数
        self.edges: list[dict[str, str]] = []          # 被选中的边（给「首次被用到」）
        self.choices: list[dict[str, Any]] = []
        self.missing: list[dict[str, str]] = []
        self.budget: dict[str, int] = {"n": 0, "max": self.max_nodes}

    def run(self, targets: Sequence[str]) -> "_Walker":
        """按目标顺序各排一段；失败的目标进 `missing`，已排成的那一段照旧留下。"""
        for ref in targets:
            ok, plan = self._subtree(ref, 0, (), set(self.emitted_set))
            if not ok:
                self.missing.extend(plan.get("missing") or [_missing(ref, "没排成")])
            else:
                self._commit(plan)
        return self

    def _commit(self, plan: Mapping[str, Any]) -> None:
        """把一份已经算好的子树按它的顺序落进全局序（同一个节点只落一次）。"""
        for ref in plan.get("order") or []:
            if ref not in self.emitted_set:
                self.emitted_set.add(ref)
                self.emitted.append(ref)
        for ref, reading in (plan.get("roots") or {}).items():
            self.root_of.setdefault(ref, reading)
        self.edges.extend(dict(edge) for edge in plan.get("edges") or [])
        self.choices.extend(dict(choice) for choice in plan.get("choices") or [])

    def _subtree(self, ref: str, depth: int, stack: tuple[str, ...],
                 emitted: set[str]) -> tuple[bool, dict[str, Any]]:
        """`ref` 这棵子树排成什么序（只读，不落全局）⇒ `(排成了吗, 计划)`。

        `emitted` 里已有的节点不再重复规划（去重）。"""
        def fail(why: str) -> tuple[bool, dict[str, Any]]:
            """这一支排不成 ⇒ `(False, 计划)`（`why` 会进 `missing`）。"""
            return False, {"order": [], "roots": {}, "edges": [], "length": 0,
                           "missing": [_missing(ref, why)], "choices": []}

        if ref in emitted:
            return True, {"order": [], "roots": {}, "edges": [], "missing": [],
                          "length": 0, "choices": []}
        if ref in stack:
            return fail("依赖里出现环")
        if depth > self.max_depth:
            return fail(f"超过规划深度上限 {self.max_depth}")
        self.budget["n"] += 1
        if self.budget["n"] > self.max_nodes:
            return fail(f"超过节点上限 {self.max_nodes}（这一趟没算完，不是『没有这条路』）")
        reading = self.snap.root_reading(ref)
        if reading["root"]:
            return True, {"order": [ref], "roots": {ref: reading}, "edges": [],
                          "missing": [], "length": 0, "choices": []}
        cands = self.snap.candidates(ref)
        if not cands:
            return fail(reading.get("why") or "依赖没写")
        rows = [self._try_candidate(ref, cands[key], proof_no=key[0], group=key[1],
                                    depth=depth, stack=stack, emitted=emitted)
                for key in sorted(cands)]
        viable = [row for row in rows if row["ok"]]
        if not viable:
            miss = [_missing(ref, "所有候选证明路径都没走到根")]
            for row in rows:
                miss.extend(row["missing"])
            return False, {"order": [], "roots": {}, "edges": [], "missing": miss,
                           "length": 0, "choices": []}
        for row in rows:
            row["elsewhere_roots"] = sorted(
                r for r in row["roots"]
                if _used_outside(self.snap.users.get(r) or (), row["order"]))
            row["new_root_nodes"] = sorted(
                set(row["roots"]) - set(row["elsewhere_roots"]))
            row["new_roots"] = len(row["new_root_nodes"])
            row["new_nodes"] = len(row["order"])
        best = _pick_candidate(viable)
        choices = list(best.get("choices") or [])
        if len(cands) > 1:
            choices.append(self._choice_reading(ref, best, rows))
        return True, {"order": best["order"], "roots": best["roots"],
                      "edges": best["edges"], "missing": [], "length": best["length"],
                      "choices": choices}

    def _try_candidate(self, ref: str, edges: Sequence[Mapping[str, Any]], *,
                       proof_no: int, group: int, depth: int, stack: tuple[str, ...],
                       emitted: set[str]) -> dict[str, Any]:
        """试一条候选证明路径（组内 AND：每条边都要走到根）。不落全局序。"""
        order: list[str] = []
        roots: dict[str, dict[str, Any]] = {}
        plan_edges: list[dict[str, str]] = []
        sub_choices: list[dict[str, Any]] = []
        missing: list[dict[str, str]] = []
        # 被依赖端按稳定键（节点号）升序访问：边的插入顺序不影响结果。
        for dep in sorted(edges, key=lambda d: _node_ref(_target_of(d)[0])):
            tgt, _kind = _target_of(dep)
            if str(dep.get("status") or "") == "dangling":
                missing.append(_missing(tgt or ref,
                                        str(dep.get("status_reason") or "这条边悬空")))
                break
            if not tgt:
                missing.append(_missing(ref, "这条边没有指向任何节点（三个 source_* 都是空的）"))
                break
            sub_ok, sub = self._subtree(tgt, depth + 1, stack + (ref,), emitted)
            if not sub_ok:
                missing.extend(sub["missing"])
                break
            order.extend(sub["order"])
            roots.update(sub["roots"])
            sub_choices.extend(sub.get("choices") or [])
            plan_edges.extend(sub["edges"])
            plan_edges.append({"from": ref, "to": tgt, "dep_id": str(dep.get("dep_id") or "")})
        else:
            return {"proof_no": proof_no, "path_group": group, "ok": True,
                    "order": order + [ref], "roots": roots, "edges": plan_edges,
                    "missing": [], "length": max(0, len(order)),
                    "choices": sub_choices}
        return {"proof_no": proof_no, "path_group": group, "ok": False,
                "order": [], "roots": {}, "edges": [], "missing": missing,
                "length": 0, "choices": sub_choices}

    def _choice_reading(self, ref: str, best: Mapping[str, Any],
                        rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """「为什么选这一条」写成一份可复算的读数（逐候选给新增根与新节点）。"""
        if best["new_roots"] == 0:
            why = (f"选第 {best['proof_no']} 条证明的第 {best['path_group']} 组："
                   "它不新增本文别处用不到的根（这些依据路径上已经用到）")
        else:
            why = (f"选第 {best['proof_no']} 条证明的第 {best['path_group']} 组："
                   f"它在所有可行路径里新增根最少（{best['new_roots']} 个："
                   + "、".join(best["new_root_nodes"]) + "）")
        extra: list[str] = []
        for row in rows:
            if row is best:
                continue
            if not row["ok"]:
                extra.append(f"第 {row['proof_no']} 条证明的第 {row['path_group']} 组"
                             "没走到根（逐条见 missing）")
            else:
                extra.append(f"第 {row['proof_no']} 条证明的第 {row['path_group']} 组"
                             f"多引入 {row['new_roots']} 个本文别处用不到的根"
                             + ("（" + "、".join(row["new_root_nodes"]) + "）"
                                if row["new_root_nodes"] else ""))
        if extra:
            why = why + "；" + "；".join(extra)
        return {"node": ref, "label": self.snap.label(ref),
            "chosen": {"proof_no": best["proof_no"], "path_group": best["path_group"]},
            "why": why,
            "candidates": [
                {"proof_no": row["proof_no"], "path_group": row["path_group"],
                 "viable": bool(row["ok"]), "length": int(row["length"]),
                 "new_roots": int(row["new_roots"]), "new_nodes": int(row["new_nodes"]),
                 "new_root_nodes": list(row["new_root_nodes"]), "elsewhere_roots": list(row["elsewhere_roots"]),
                 "roots": sorted(row["roots"]), "nodes": list(row["order"]),
                 "chosen": row is best,
                 "why": ("选中" if row is best else
                         ("没走到根" if not row["ok"] else "落选（新增根/节点/长度更大）"))}
                for row in rows
            ],
        }

    def excluded(self, plan_nodes: Sequence[str],
                 targets: Sequence[str]) -> tuple[list[dict[str, Any]], str]:
        """`(excluded, note)`：没进路径的节点 + 原因。

        取景三层：① 目标闭包里被走过、但候选路径没选中的节点（例 2 的 A 与 实验a）；
        ② 反过来引用路径节点的「兄弟」命题（例 1 的 C）；③ 兄弟自己的闭包（例 1 的
        概念2：只服务 C，而 C 不在路径上）。
        """
        path = list(dict.fromkeys(str(n) for n in plan_nodes))
        path_set = set(path)
        scope = self.snap.closure(targets)
        siblings: list[str] = []
        for node in path:
            for ref in self.snap.users.get(node) or []:
                if ref not in path_set and ref not in scope and ref not in siblings:
                    siblings.append(ref)
        sib_closure = {sib: self.snap.closure([sib]) for sib in siblings}
        universe: list[str] = list(dict.fromkeys(
            list(scope) + siblings + [n for nodes in sib_closure.values() for n in nodes]))
        rejected: dict[str, str] = {}
        for choice in self.choices:
            for row in choice.get("candidates") or []:
                if row.get("chosen"):
                    continue
                for node in row.get("nodes") or []:                    rejected.setdefault(
                        node, (f"在「{choice['label']}」的另一条候选证明路径（第 "
                               f"{row['proof_no']} 条证明 · 第 {row['path_group']} 组）上；"
                               "那条没被选中"))
        out: list[dict[str, Any]] = []
        for node in sorted(universe, key=lambda n: str(n).partition(":")[::2]):
            if node in path_set:
                continue
            if node in rejected:
                why = rejected[node]
            elif node in siblings:
                used = [n for n in path if node in (self.snap.users.get(n) or [])]
                why = ("不是任何目标的前提：它反过来引用了路径上的 "
                       + ("、".join(self.snap.label(n) for n in used) or "节点")
                       + "，但没有任何目标用到它")
            elif node in scope:
                why = "在任何目标的候选证明路径上，但这条去重路径没有选中它"
            else:
                server = [sib for sib in siblings if node in sib_closure[sib]]
                names = "、".join(self.snap.label(s) for s in server)
                why = (f"只服务 {names}（{names} 不在路径上）" if server
                       else "不在任何目标的依赖闭包里（既不是目标的前提，也没被这条路用到）")
            out.append({"node": node, "kind": self.snap.kind(node),
                        "label": self.snap.label(node), "why": why})
        if len(out) <= MAX_EXCLUDED:
            return out, ""
        return out[:MAX_EXCLUDED], (f"没进路径的节点有 {len(out)} 个，只列前 "
                                    f"{MAX_EXCLUDED} 个（其余是同一批原因的重复）")


def plan_path(targets: Sequence[str] | str, *,
              statements: Sequence[Mapping[str, Any]],
              dependencies: Sequence[Mapping[str, Any]],
              experiments: Sequence[Mapping[str, Any]] = (),
              literature: Sequence[Mapping[str, Any]] = (),
              root: str | Path | None = None,
              max_depth: int = DEFAULT_MAX_DEPTH) -> dict[str, Any]:
    """一组目标 ⇒ 一条去重的自足路径（纯函数：零模型调用、不落库、不读表）。

    `targets` 是目标的一组「号 / 别名」（也认逗号或空白分隔的一整串）；四张表是已经
    读出来的行；`root` 只用来读 V 的台账那一格。返回四格 + 三态（口径见模块 docstring）。
    """
    wanted = _target_list(targets)
    snap = _Snapshot(statements, dependencies, experiments, literature, root)
    resolved: list[str] = []
    missing: list[dict[str, str]] = []
    target_rows: list[dict[str, Any]] = []
    for raw in wanted:
        hit = _resolve_target(snap, raw)
        if hit is None:
            missing.append(_missing(str(raw), "号与别名都试过，statements 里找不到"))
            continue
        matched_by, ref = hit
        if ref not in resolved:
            resolved.append(ref)
        target_rows.append({"request": str(raw), "stmt_id": ref[5:],
                            "label": snap.label(ref), "matched_by": matched_by})
    if not resolved:
        return _empty_plan(targets=target_rows, missing=missing,
                           bad_used_by=snap.bad_used_by)
    budget: dict[str, int] = {"n": 0, "max": MAX_PLAN_NODES}
    closing = {ref: snap.closure([ref], budget=budget) for ref in resolved}
    for ref in resolved:
        if len(closing[ref]) >= MAX_PLAN_NODES:
            missing.append(_missing(ref, f"闭包超过节点上限 {MAX_PLAN_NODES}（这一趟没算完）"))
    # 目标序：闭包小的先排（同大小按调用方给的顺序）—— 先排小需求，共享依据只落一次。
    ordered = sorted(resolved, key=lambda ref: (len(closing[ref]), resolved.index(ref)))
    walker = _Walker(snap, max_depth=max_depth).run(ordered)
    missing.extend(walker.missing)
    order_items = _order_items(snap, walker)
    roots = _root_items(snap, walker)
    excluded, excluded_note = walker.excluded(walker.emitted, ordered)
    checked = not missing
    if not checked:
        note = (f"规划没算成：{len(missing)} 处读不到 / 不可判（逐条见 missing）"
                "—— 这不是「没有依赖」，也不是「已经是根」")
    elif walker.choices:
        note = f"{len(walker.choices)} 处候选路径做了选择（见 choices 的逐候选读数）"
    else:
        note = ""
    return {
        "checked": checked, "targets": target_rows, "order": order_items, "roots": roots,
        "excluded": excluded, "choices": walker.choices,
        "missing": missing, "bad_used_by": list(snap.bad_used_by),
        "excluded_note": excluded_note, "note": note,
        "stats": {"targets": len(target_rows), "nodes": len(order_items),
                  "roots": len(roots), "excluded": len(excluded),
                  "choices": len(walker.choices), "bad_used_by": len(snap.bad_used_by),
                  "max_depth": int(max_depth)},
    }


def _target_list(targets: Sequence[str] | str) -> list[str]:
    """把 `targets` 归一成一串（字符串可以是逗号/空白分隔的一整串）。"""
    if isinstance(targets, str):
        return [p for p in targets.replace("，", ",").replace(",", " ").split() if p]
    return [text for text in (str(i or "").strip() for i in targets or ()) if text]


def _resolve_target(snap: _Snapshot, raw: str) -> tuple[str, str] | None:
    """号优先、别名兜底 ⇒ `(matched_by, "stmt:号")`；找不到给 None。"""
    text = str(raw or "").strip()
    if not text:
        return None
    bare = text[5:] if text.startswith("stmt:") else text
    if SL.by_id(rows=list(snap.stmts.values()), stmt_id=bare)["found"]:
        return ("stmt_id" if text.startswith("stmt:") else "label"), f"stmt:{bare}"
    want = T.normalize(bare)
    for row in snap.stmts.values():
        if T.normalize(str(row.get("label") or "")) == want:
            return "label", f"stmt:{row['stmt_id']}"
    for row in snap.stmts.values():
        if any(T.normalize(str(a)) == want for a in (row.get("aliases") or [])):
            return "alias", f"stmt:{row['stmt_id']}"
    return None


def _order_items(snap: _Snapshot, walker: _Walker) -> list[dict[str, Any]]:
    """`order` 那一格：节点 + kind + 一句「为什么在这里」。"""
    pos = {ref: i for i, ref in enumerate(walker.emitted)}
    users: dict[str, list[str]] = {}
    deps: dict[str, list[str]] = {}
    for edge in walker.edges:
        for bucket, key, value in ((users, edge["to"], edge["from"]),
                                   (deps, edge["from"], edge["to"])):
            if value not in bucket.setdefault(key, []):
                bucket[key].append(value)
    out: list[dict[str, Any]] = []
    for ref in walker.emitted:
        reading = walker.root_of.get(ref)
        if reading and reading.get("root"):
            why = (f"根（{TIER_LABELS.get(reading['tier'], reading['tier'])}）："
                   f"{reading.get('why') or '没有依赖'}；它没有前提可排，落在路径的末端")
        elif users.get(ref):
            first = min(users[ref], key=lambda u: pos.get(u, 10 ** 9))
            why = (f"首次被「{snap.label(first)}」用到（第 {pos.get(first) + 1} 位），"
                   "本条目排在它之前；它自己的前提是 "
                   + ("、".join(f"「{snap.label(d)}」" for d in deps.get(ref) or []) or "无"))
        else:
            why = ("没有任何别处用到它 —— 它是本次要写的目标之一（路径的终点），"
                   "所以排在最后")
        item = {"node": ref, "kind": snap.kind(ref), "label": snap.label(ref), "why": why}
        if reading and reading.get("root"):
            item["root_tier"] = reading["tier"]
        out.append(item)
    return out


def _root_items(snap: _Snapshot, walker: _Walker) -> list[dict[str, Any]]:
    """`roots` 那一格：这条路径用到的根，四档逐档可区分。"""
    return [{"node": ref, "kind": r["tier"], "node_kind": snap.kind(ref),
             "label": snap.label(ref), "why": r.get("why") or "",
             "proof_grade": bool(r.get("proof_grade"))}
            for ref in walker.emitted for r in [walker.root_of.get(ref)]
            if r and r.get("root")]


def _empty_plan(*, targets: Sequence[Mapping[str, Any]],
                missing: Sequence[Mapping[str, str]],
                bad_used_by: Sequence[str] = ()) -> dict[str, Any]:
    """一个目标都没解析出来时的读数（`checked=False`，四格给空但三态位在）。"""
    return {
        "checked": False, "targets": [dict(t) for t in targets],
        "order": [], "roots": [], "excluded": [], "choices": [],
        "missing": [dict(m) for m in missing], "bad_used_by": list(bad_used_by), "excluded_note": "",
        "note": "一个目标都没解析出来 ⇒ 这一趟没查成（不是「这些目标没有依赖」）",
        "stats": {"targets": len(targets), "nodes": 0, "roots": 0, "excluded": 0,
                  "choices": 0, "bad_used_by": len(bad_used_by)}}


def plan_report(agent: Any, target: str, *, targets: Sequence[str] | str = (),
                max_depth: int = 6, k: int = 1,
                weights: Mapping[str, float] | None = None) -> Any:
    """把多目标规划接到 C 既有的报告通道上（唯一写盘 = `_report` 的产出即登记）。

    `target` 是主目标（ActionSpec 的必填格），`targets` 是其余目标；两者都参与规划，
    按解析后的号去重。报告 `kind` 仍是 `proof_chain`，四格直接放 payload 顶层。
    `max_depth` / `k` / `weights` 是单目标链的批次参数；规划深度上限是 `DEFAULT_MAX_DEPTH`。
    """
    warnings: list[str] = []
    try:
        stmts, problem, error = SL.rows_of(agent.store)
    except Exception as exc:  # noqa: BLE001 - 读不成 ⇒ 明说，不许当成「没有依赖」
        return _failed_report(agent, target, targets, max_depth, k,
                              f"{type(exc).__name__}: {exc}")
    if problem:
        return _failed_report(agent, target, targets, max_depth, k, str(problem))
    try:
        deps = [dict(r) for r in agent.store.rows("dependencies")]
        exps = [dict(r) for r in agent.store.rows("experiments")]
        lits = [dict(r) for r in agent.store.rows("literature")]
    except Exception as exc:  # noqa: BLE001 - 同上
        return _failed_report(agent, target, targets, max_depth, k,
                              f"{type(exc).__name__}: {exc}")
    plan = plan_path([target, *_target_list(targets)],
                     statements=stmts, dependencies=deps, experiments=exps,
                     literature=lits,
                     root=getattr(getattr(agent, "store", None), "root", None))
    if plan.get("bad_used_by"):
        warnings.append(f"有 {len(plan['bad_used_by'])} 条依赖的 `used_by` 尾巴读不懂（逐条见 payload）")
    labels = "、".join(f"「{row['label']}」" for row in plan.get("targets") or []) or target
    if plan.get("checked"):
        summary = (f"{labels}：一条去重自足路径，{len(plan['order'])} 个条目、"
                   f"{len(plan['roots'])} 个根、{len(plan['choices'])} 处选路"
                   "（逐位见 payload.order）")
        error_name = None
    else:
        first = (plan.get("missing") or [{}])[0]
        summary = (f"{labels}：规划没算成（{first.get('node') or '?'}："
                   f"{first.get('why') or '见 payload.missing'}）⇒ 这不是「没有依赖」")
        error_name = "proof_path_incomplete"
    payload = {**plan, "max_depth": int(max_depth), "k": int(k),
               "weights": dict(weights or {})}
    return agent._report(
        "proof_chain", str(target),
        {"targets": _target_list([target, *_target_list(targets)]),
         "max_depth": int(max_depth), "k": int(k), "weights": dict(weights or {})},
        summary=summary, payload=payload, markdown=_plan_markdown(plan, summary),
        warnings=[*warnings, *([plan["note"]] if plan.get("note") else [])],
        ok_=bool(plan.get("checked")), error=error_name)


def _failed_report(agent: Any, target: str, targets: Sequence[str] | str,
                   max_depth: int, k: int, why: str) -> Any:
    """依赖图读不成时的报告（`ok_=False`，不登记 —— 但它说清「没查成」）。"""
    plan = _empty_plan(targets=(), missing=[_missing(str(target), why)])
    plan["note"] = f"依赖图读不成（{why}）⇒ 这一趟没查成（不是「这些目标没有依赖」）"
    return agent._report(
        "proof_chain", str(target),
        {"targets": _target_list([target, *_target_list(targets)]),
         "max_depth": int(max_depth), "k": int(k)},
        summary=plan["note"], payload=dict(plan), ok_=False,
        markdown=_plan_markdown(plan, plan["note"]), error="dependency_unreadable")


def _plan_markdown(plan: Mapping[str, Any], summary: str) -> str:
    """计划读数渲染成人读正文（`persist()` 拒收空 markdown）。"""
    checked = "算成了" if plan.get("checked") else "没算成"
    labels = "、".join(str(t.get("label") or t.get("request")) for t in plan.get("targets") or []) or "（无）"
    lines = ["# C 分析报告：proof_chain（去重自足路径）", "",
             f"- 标题摘要：{summary}", "", f"- 三态（checked）：{checked}",
             f"- 目标：{labels}", "", "## 路径（逐位：条目 · 种类 · 为什么在这里）", ""]
    for i, item in enumerate(plan.get("order") or [], start=1):
        tier = f"（根档 `{item['root_tier']}`）" if item.get("root_tier") else ""
        lines.append(f"{i}. `{item.get('node')}` · {item.get('label')} · "
                     f"{item.get('kind')}{tier} —— {item.get('why')}")
    lines += ["", "## 根（四档逐档可区分）", ""]
    if plan.get("roots"):
        lines += ["| 节点 | 档 | 标签 | 为什么是根 |", "|---|---|---|---|"]
        lines += [f"| `{r.get('node')}` | {r.get('kind')}"
                  f"{'（proof 级）' if r.get('proof_grade') else ''} | "
                  f"{r.get('label')} | {r.get('why')} |" for r in plan["roots"]]
    else:
        lines.append("（没有根：路径没走到根，或者没算成。）")
    lines += ["", "## 没进路径的节点（与原因）", ""]
    lines += ([f"- `{i.get('node')}` · {i.get('label')}：{i.get('why')}"
               for i in plan.get("excluded") or []]
              or ["（没有：这次的目标闭包全在路径上。）"])
    if plan.get("excluded_note"):
        lines.append(f"- 截断说明：{plan['excluded_note']}")
    lines += ["", "## 同一命题多条路径时的选择", ""]
    if plan.get("choices"):
        for choice in plan["choices"]:
            lines += [f"### {choice.get('label')}（`{choice.get('node')}`）", "",
                      f"- 选择：{choice.get('why')}"]
            lines += [f"  - 第 {r.get('proof_no')} 条证明 · 第 {r.get('path_group')} 组："
                      f"{'可行' if r.get('viable') else '不可行'}；新增根 "
                      f"{r.get('new_roots')} 个"
                      f"（{'、'.join(r.get('new_root_nodes') or []) or '无'}），"
                      f"新节点 {r.get('new_nodes')} 个"
                      for r in choice.get("candidates") or []]
    else:
        lines.append("（没有分叉：每个命题只有一条候选证明路径。）")
    lines += ["", "## 边界（三态）", ""]
    lines += ([f"- `{i.get('node')}`：{i.get('why')}" for i in plan.get("missing") or []]
              or ["- 没有缺读：目标、依赖边、四档根都读到了。"])
    if plan.get("bad_used_by"):
        lines.append("- 读不懂的 `used_by` 尾巴："
                     + "、".join(f"`{b}`" for b in plan["bad_used_by"]))
    lines.append("")
    return "\n".join(lines)

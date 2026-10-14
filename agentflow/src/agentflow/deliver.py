"""交付前的判据闸门：逐项判据 + 机械半 → 结论、报告、以及"派回去"的工作项。

## 这一层填的是哪个洞

`draft/28` §184.1 第 2 条：`judges.judge(` 在产品代码里零调用点 ——
判据存在、真机验过，但没有任何交付流程会去问它们。于是"这次交付达不达标"仍然靠人读。

这一层把三件事接起来（都不新增表：`draft/29` §3.2 的"候选落点先落文件"）：

1. 闸门：给定一个交付物，跑一组判据（语义半）+ 机械半，得到一个三态结论：
   `pass` / `needs_work` / `unknown`。其中 `unknown` 专指"没判成"（没接线、坏 JSON）——
   它与 `pass` 必须分得开，否则"没查"又一次被读成"没问题"。
2. 报告：`<项目根>/gates/<名字>.json`（含每条判据的判定、理由、落地的发现、审计字段）
   + 一条会话事件 `delivery_gate`。
3. 工作项：每一条不过的判据/机械问题 → 一条 `work_item` 落 `<项目根>/work_items.jsonl`
   （append-only；状态由最后一条同名记录决定）。工作项带 `who`（该谁来改）与
   `suggested_action`（可派的具体动作，可能为空）。
   `dispatch_work_items` 只对"角色与动作都存在"的工作项真去召唤，其余如实记
   `dispatch: skipped`，绝不编一个动作名 —— 编出来的动作会被工具层拒，而拒绝会被记成失败。

## 为什么"谁该改"要单独写

判据说"有品味不达标"，不等于知道"该派谁改哪一段"。把 `faculty → 角色` 写死是判断，
所以它是一张显式的表（`FACULTY_FIXERS`），改它是一次可见的 diff，而不是散在代码里的默认值。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import faculty_checks as FC
from . import judges as JG
from . import schema as S   # 编号形态的唯一来源（`format_id`）
from . import sessions as SS

#: 交付闸门的落点：`<项目根>/gates/<名字>.json`。
GATES_DIR_NAME = "gates"
#: 工作项日志：`<项目根>/work_items.jsonl`（append-only）。
WORK_ITEMS_NAME = "work_items.jsonl"

#: 官能 → 默认该由谁来改。这是判断，所以显式写成一张表（改它会有一次可见的 diff）。
FACULTY_FIXERS: dict[str, str] = {
    "高观点": "C",
    "敢创新": "F",
    "有品味": "G",
    "脑子": "D",
    "能思辨": "D",
}

#: 机械半的 kind → 该由谁来改。
MECHANICAL_FIXERS: dict[str, str] = {
    "unknown_id": "B",
    "unsupported_pair": "C",
    "style": "G",
    "progress": "D",
    "trace": "D",
}


@dataclass
class WorkItem:
    """一条待办的修改项。`action` 为空 = 没有可直接派的具体动作（留给人或 M 决定）。"""

    id: str
    source: str            # `criterion:<id>` 或 `mechanical:<kind>`
    who: str               # 该谁来改（角色名；可能为空 = 不知道）
    what: str              # 一句话：改什么
    evidence: list[str] = field(default_factory=list)
    action: str = ""       # 可派的具体动作（必须真的在该角色动作表里才会被派）
    status: str = "open"
    dispatched_task_id: str = ""
    at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """落 `work_items.jsonl` 的扁平结构（append-only：状态按最后一条记录折叠）。"""
        return {"id": self.id, "source": self.source, "who": self.who, "what": self.what,
                "evidence": list(self.evidence), "action": self.action, "status": self.status,
                "dispatched_task_id": self.dispatched_task_id, "at": self.at}


@dataclass
class DeliveryGate:
    """一次交付闸门的结论。

    为什么不复用 gates.GateResult（R003 抓到过这次重名）：那一个是通用的
    「一道门的结构化结论」（gate_id / axis / criterion / verdict / reason /
    findings / 自证），而这里要带两样它没有的东西 —— 「工作项」（谁该改什么）
    与「没判成的判据清单」（三态里的 unknown 必须能被读出来）。合并两者是一次
    口径变更，需要人裁；在裁定之前：改名加把关系写在 docstring 里，既不静默
    合并也不静默撞名。
    """

    name: str
    verdict: str = "unknown"           # pass / needs_work / unknown
    criteria: list[dict[str, Any]] = field(default_factory=list)
    mechanical: list[dict[str, Any]] = field(default_factory=list)
    work_items: list[WorkItem] = field(default_factory=list)
    report_path: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def unknown_criteria(self) -> list[str]:
        """没判成的那几条判据（`judge_not_wired` / 坏 JSON）——它们不是"通过"。"""
        return [c["criterion"] for c in self.criteria if c.get("problem")]

    def to_dict(self) -> dict[str, Any]:
        """落报告用的扁平结构（含没判成的判据清单）。"""
        return {"name": self.name, "verdict": self.verdict, "criteria": list(self.criteria),
                "mechanical": list(self.mechanical),
                "work_items": [w.to_dict() for w in self.work_items],
                "report_path": self.report_path, "notes": list(self.notes),
                "unknown_criteria": self.unknown_criteria}


def _next_work_id(session_root: Path, seq: int) -> str:
    """工作项号：`w-000001`（宽度取 `schema.ID_DIGITS` 一处）。序号由调用方给（读取现有一遍就够）。"""
    return f"w-{S.format_id(seq)}"


def read_work_items(session_root: Path | str) -> list[dict[str, Any]]:
    """读工作项（append-only 折叠：同一个 id 取最后一条的状态）。"""
    path = Path(session_root) / WORK_ITEMS_NAME
    if not path.is_file():
        return []
    latest: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for raw in lines:
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(obj, dict) or not obj.get("id"):
            continue
        wid = str(obj["id"])
        if wid not in latest:
            order.append(wid)
        latest[wid] = obj
    return [latest[w] for w in order]


def append_work_item(session_root: Path | str, item: WorkItem) -> str:
    """追加一条工作项记录，返回问题串（空 = 写成了）。"""
    path = Path(session_root) / WORK_ITEMS_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"
    return ""


def _mechanical_checks(store: Any, artifact: str, *, claimed_pairs: Sequence[Sequence[str]] = (),
                       require_disclaimer: bool = False, disclaimer: str = "",
                       ) -> list[dict[str, Any]]:
    """机械半：引用落地 + 体例 + 断言强度（不需要模型的那三条）。"""
    out: list[dict[str, Any]] = []
    if store is not None and claimed_pairs:
        res = FC.overview_findings(store, artifact, claimed_pairs=claimed_pairs)
        for table, ids in (res["unknown_ids"] or {}).items():
            out.append({"kind": "unknown_id", "detail": f"{table}: {'、'.join(ids)}"})
        for pair in res["unsupported_pairs"]:
            out.append({"kind": "unsupported_pair",
                        "detail": f"{pair['pair']} 在图里没有边也没有路径"})
    if store is not None:
        # 断言强度（`draft/28` §189，第 7 步）：把稿件的每一条断言与它挂的证据等级
        # 逐条比一遍。判不了"这句话证明了没有"（那是语义半），但"证据等级是 cross_check
        # 却写着『证明』"这种形态不需要模型就能判。
        claims: list[dict[str, Any]] = []
        try:
            for row in store.rows("documents"):
                claims.extend(dict(c) for c in (row.get("claims") or []))
        except Exception as exc:  # noqa: BLE001 —— 表读不了如实记一档，不当作"没有断言"
            out.append({"kind": "claim_strength",
                        "detail": f"断言台账读不到：{type(exc).__name__}: {exc} ⇒ 强度没判成"})
        if claims:
            strength = FC.claim_strength_findings(claims)
            for finding in strength["findings"]:
                out.append({"kind": "claim_strength", "detail": finding})
    style = FC.style_findings(artifact, require_disclaimer=require_disclaimer,
                              disclaimer=disclaimer)
    for finding in style["findings"]:
        out.append({"kind": "style", "detail": finding["detail"]})
    return out


def gate(name: str, artifact: str, *, session_root: Path | str, seam: Any = None,
         criteria: Sequence[str] = (), store: Any = None,
         claimed_pairs: Sequence[Sequence[str]] = (), context: str = "",
         require_disclaimer: bool = False, disclaimer: str = "") -> DeliveryGate:
    """跑一次交付闸门：逐条判据 + 机械半 → 结论、报告、工作项。

    三态：`pass`（全过）/ `needs_work`（有确定的不达标）/ `unknown`（有判据没判成）。
    有 `unknown` 时不产生"确定不达标"的工作项 —— 但会把"这几条没判成"写进报告与 notes。
    """
    root = Path(session_root)
    result = DeliveryGate(name=name)
    chosen = list(criteria) or sorted(JG.CRITERIA)
    for cid in chosen:
        verdict = JG.judge(cid, artifact, seam=seam, context=context)
        result.criteria.append(verdict.to_dict())
        if verdict.problem or not verdict.ok:
            who = FACULTY_FIXERS.get(verdict.faculty, "")
            what = (f"判据 {cid}（{verdict.faculty}）判定为 {verdict.verdict or '未判'}"
                    + (f"：{verdict.why}" if verdict.why else
                       f"：没判成（{verdict.problem}）"))
            evidence = [f["quote"] for f in verdict.findings][:3]
            result.work_items.append(WorkItem(id="", source=f"criterion:{cid}", who=who,
                                              what=what, evidence=evidence))
    result.mechanical = _mechanical_checks(store, artifact, claimed_pairs=claimed_pairs,
                                           require_disclaimer=require_disclaimer,
                                           disclaimer=disclaimer)
    for item in result.mechanical:
        result.work_items.append(WorkItem(id="", source=f"mechanical:{item['kind']}",
                                          who=MECHANICAL_FIXERS.get(item["kind"], ""),
                                          what=item["detail"], evidence=[]))

    if result.unknown_criteria:
        result.verdict = "unknown"
        result.notes.append("这些判据没判成：" + "、".join(result.unknown_criteria)
                            + "（没判成 ≠ 通过）")
    elif result.work_items:
        result.verdict = "needs_work"
    else:
        result.verdict = "pass"

    # 编号：从现有工作项往下排（一次读取就够）
    seq = len(read_work_items(root)) + 1
    for item in result.work_items:
        item.id = _next_work_id(root, seq)
        item.at = time.strftime("%Y-%m-%dT%H:%M:%S")
        seq += 1
        problem = append_work_item(root, item)
        if problem:
            result.notes.append(f"工作项 {item.id} 没写成：{problem}")

    report = {"name": name, "verdict": result.verdict, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "criteria": result.criteria, "mechanical": result.mechanical,
              "work_items": [w.to_dict() for w in result.work_items],
              "notes": result.notes}
    gates_dir = root / GATES_DIR_NAME
    try:
        gates_dir.mkdir(parents=True, exist_ok=True)
        path = gates_dir / f"{name}.json"
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        result.report_path = str(path)
    except OSError as exc:
        result.notes.append(f"闸门报告没写成：{type(exc).__name__}: {exc}")
    _p, problem = SS.append(root, {"kind": "delivery_gate", "name": name,
                                   "verdict": result.verdict,
                                   "work_items": [w.id for w in result.work_items],
                                   "unknown_criteria": result.unknown_criteria}, sid=None)
    if problem:
        result.notes.append(f"闸门事件没落进会话记录：{problem}")
    return result


def dispatch_work_items(wiring: Mapping[str, Any], items: Sequence[WorkItem], *,
                        budget: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """把工作项派回去。只派"角色与动作都真的存在"的那些，其余如实记 `skipped`。

    为什么这么严：编一个动作名递过去，会被工具层以 `unknown_action` 拒 ——
    而那条拒绝在台账里看起来像"执行失败"，把"我不知道派谁"伪装成"派了但失败了"。
    """
    from . import capabilities as C

    conductor = wiring.get("conductor") if wiring else None
    out: list[dict[str, Any]] = []
    for item in items:
        if not item.who or not item.action or conductor is None:
            out.append({"id": item.id, "dispatch": "skipped",
                        "why": "没有可派的具体动作（或没有主控）⇒ 留给人或让 M 决定"})
            continue
        if C.find_action(item.who, item.action) is None:
            out.append({"id": item.id, "dispatch": "skipped",
                        "why": f"{item.who} 的动作表里没有 {item.action}（不许编动作名）"})
            continue
        res = conductor.summon(item.who, item.action, {"note": item.what}, by="M",
                               budget=budget)
        out.append({"id": item.id, "dispatch": "summoned", "task_id": res.task_id,
                    "status": res.status, "outcome": res.outcome,
                    "refusal_reason": res.refusal_reason})
        if res.task_id:
            item.status = "dispatched"
            item.dispatched_task_id = str(res.task_id)
            append_work_item(Path(str(wiring.get("session_root") or ".")), item)
    return out


def selftest() -> int:
    """自检：三态闸门 + 工作项落盘 + 派回去的 fail-closed。"""
    import tempfile

    from .llmseam import LlmSeam
    from .store import Store

    problems: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "ws"
        st = Store(root)
        st.init()
        good = ('{"verdict": "structural", "why": "点明了一般与特例", "findings": []}')
        seam = LlmSeam(role="H", session_root=root, gateway=_Fake(good), price=(0.0, 0.0),
                       sid="t")
        res = gate("selftest", "# 稿子\n\n阿贝尔群是群的特例。\n", session_root=root,
                   seam=seam, criteria=["overview.essence"], store=st)
        if res.verdict != "pass":
            problems.append(f"全过的样本没判 pass：{res.to_dict()}")
        if not Path(res.report_path).is_file():
            problems.append("闸门报告没有落盘")
        # 没接线 ⇒ unknown，不许当通过
        unknown = gate("selftest-no-wire", "文本", session_root=root, seam=None,
                       criteria=["overview.essence"])
        if unknown.verdict != "unknown" or not unknown.unknown_criteria:
            problems.append(f"没接线没判 unknown：{unknown.to_dict()}")
        # 体例不达标 ⇒ needs_work + 工作项落盘
        bad = gate("selftest-bad", "没有标题的一段 TODO 文字\n", session_root=root, seam=seam,
                   criteria=["brain.blocker_specificity"])
        if bad.verdict == "pass":
            problems.append("有机械问题时仍判 pass")
        item_ids = [w["id"] for w in read_work_items(root)]
        if not item_ids:
            problems.append("工作项没有落盘")
        # 派回去：动作不存在时必须 skipped（不许编动作名）
        dispatched = dispatch_work_items({"conductor": None}, bad.work_items)
        if any(d["dispatch"] != "skipped" for d in dispatched):
            problems.append(f"没有主控却派了活：{dispatched}")

    if problems:
        print("SELF-CHECK FAILED")
        for p in problems:
            print("  -", p)
        return 1
    print("SELF-CHECK DONE（三态闸门 / 报告与工作项落盘 / 派回去 fail-closed）")
    return 0


class _Fake:
    """自检用的替身模型（只实现 `complete`）。"""

    spec = type("S", (), {"model": "fake"})()

    def __init__(self, text: str) -> None:
        self.text = text

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        """自检替身：固定返回一段文本。"""
        return type("R", (), {"ok": True, "text": self.text, "tokens_in": 3, "tokens_out": 3,
                              "error_detail": "", "error_kind": ""})()


if __name__ == "__main__":
    import sys

    sys.exit(selftest())

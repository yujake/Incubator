# -*- coding: utf-8 -*-
"""收工门（`draft/37` §16 P3）：把"能不能交"从一句判断变成五条各自能造红的读数。

## 为什么需要一个门（而不是让 M 自己总结一句"我觉得可以交了"）

真机读数里最贵的一类失败不是"做错了"，而是"做完了"与"能交"被当成同一件事：
包是旧的（锚 `drifted`）、有一条依赖还挂着争议、承重的那条结论只有数值支持却写着
"已证明"、报告缺了三节、还有一个问题在等用户回答 —— 这些每一条都能被机器判，
而它们混在一段总结里就只剩一句"基本完成"。

## 各条（`DEFAULT_CHECKS`）+ 三态

| 检查 | 判什么 |
|---|---|
| `anchor` | 渲染锚必须 `consistent`（`renderanchor.check_package` 的同一份实现） |
| `contradictions` | 没有未裁决的矛盾：`dependencies.status ∈ {disputed, refuted}`、
|  | `statements.status = disputed`、稿件 `status = unresolved_review` |
| `load_bearing` | 承重结论（正文里 `evidence_kind="proof"` 的断言）必须有 T3（形式化）或已降档 |
| `report_shape` | 报告九节齐全（§14.4）+ "我们补的/原文的"分栏 + 附件三件套 |
| `user_pending` | 没有还在等用户回答的问题（有 ⇒ 必须停在"等待用户"，不许续跑） |
| `substance` | 实质产出：`documents` / `relations` / `experiments` / `review_findings` / `statements` 至少一张非空（全 0 ⇒ 不许报「可交付」；`tasks`/`usage_ledger` 不算 —— 派过活、花过钱可以在什么都没产出时也非空） |

三态纪律：每条给出 `pass` / `fail` / `unknown`，`unknown` 不是通过
（"没查成"与"查过了没问题"必须分得开）。`can_close` 只在每一条都 `pass` 时为真。

## 每一条都能单独造红

判据见 `tests/test_closing_gate.py`：每条各一条负控（把这一条弄坏 ⇒ 它单独红、
其余各条仍然绿），外加一条反真空（好数据必须全绿）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from . import renderanchor as RA
from . import userio as U

#: 检查的名字（顺序就是报告里的顺序）。
#:
#: 2026-10-03（`draft/37` §86）加了第六条 `substance`：T1 实测里
#: `documents`/`statements`/`relations`/`experiments`/`review_findings` 全是 0，
#: 而前五条全过、`can_close=true`、报告写着「可交付」—— 五格里没有一格问
#:「这一趟到底产出了什么」。这不是新判据，是把已有的三态纪律补到它该管的地方：
#: 「没做」不许读成「没问题」。
DEFAULT_CHECKS: tuple[str, ...] = (
    "anchor", "contradictions", "load_bearing", "report_shape", "user_pending", "substance",
    "acceptance",
)

#: 「实质产出」那一格认的表：至少一张非空 ⇒ 这一趟真的产出了东西。
#:
#: 为什么是这五张：它们分别对应「稿件 / 概念关系 / 实验证据 / 审校发现 / 命题台账」——
#: 一份 review 交付至少要在其中一格留下痕迹。`tasks` / `usage_ledger` 刻意不算：
#: 它们记的是"派过活、花过钱"，而那两件事恰恰可以在什么都没产出时也非空
#: （T1 就是 30 行 tasks、0 行产出）。
SUBSTANCE_TABLES: tuple[str, ...] = ("documents", "relations", "experiments",
                                      "review_findings", "statements")

#: 「这一趟的验收表里，机器可判的那几行」落在哪张文件上（项目根相对）。
#:
#: ## 为什么需要这一格（`draft/37` §94 的真机读数）
#:
#: T1 第 7、8 趟：任务原文点名的那两条腿（逐字核验引文、形式化验证）那一趟都没落台账，
#: 而收工门六格全过、`can_close=true` —— `substance` 只问"五张表里有没有非空的"，
#: 而那一趟 `statements`/`literature` 是 0、`documents` 与 `experiments` 非空，
#: 于是"缺了两条腿"被读成了"可交付"。验收表（人给的那张）才是任务口径的来源，
#: 但它此前只被 `conductor.acceptance` 读、从来没有被判。
#:
#: 判据的形式：验收表是人写的散文（"这一行怎么算数"散在读数栏里），散文没法复算；
#: 所以人给的机器可判行另落一份声明文件（JSON），每行一个受控的 `kind` + 阈值。
#: 这一格就是把这些行从台账现算一遍：不满足 ⇒ `fail`（并逐行给出读数）。
ACCEPTANCE_CHECKS_NAME = "out/paper/ACCEPTANCE-CHECKS.json"

#: 机器可判的验收行只有这几档（受控词表）。加一档 = 加一条能被复算的验收口径，
#: 所以它必须在这里逐档实现，不许写成"任意表达式"（那等于让验收表能执行代码）。
LEG_CHECK_KINDS: dict[str, str] = {
    "quote_verified_rows": "台账里带逐字比对记录的命题行数（`statements` 或 `relations` "
                           "里 `quote_verified` 非 null 的行）",
    "proof_experiment_rows": "台账里的 proof 级形式化实验行数（`experiments` 里 "
                             "`method=formal` 且 `evidence_kind=proof` 的行）",
    "reviewed_documents": "被审到有裁决的我方稿件行数（`documents` 里状态被推成 "
                          "accepted/revised 的行，或 `review_rounds >= 1` 的行）",
}

#: 「被审过」这一档认的稿件状态：H 的裁决把 `draft` 推成这几个之一。
#:
#: 为什么不能只看 `review_rounds`（`draft/37` §95 的真机读数）：T1 第 9 趟里
#: `documents/0000` 是 `status=accepted`、`review_rounds=0` —— H 审过并给了裁决，
#: 而"轮次"只在真的改过稿时才会加。按 `review_rounds >= 1` 判会把一次
#: 已经审过且通过的稿件读成"没审过"（判据恒红 ⇒ 谁都不会再信它）。
REVIEWED_DOC_STATUSES: tuple[str, ...] = ("accepted", "revised")


def _leg_reading(store: Any, kind: str) -> tuple[int, dict[str, Any]]:
    """按受控档位从台账现算一行验收读数 ⇒ `(条数, 明细)`。

    台账读不到时抛出去，由调用方落成 `unknown`（"问不出来"不许读成"没有"）。
    """
    if kind == "quote_verified_rows":
        st = store.rows("statements")
        rel = store.rows("relations")
        s_rows = [r for r in st if r.get("quote_verified") is not None]
        r_rows = [r for r in rel if r.get("quote_verified") is not None]
        return len(s_rows) + len(r_rows), {
            "statements": len(s_rows), "relations": len(r_rows),
            "true": sum(1 for r in s_rows + r_rows if r.get("quote_verified") is True),
            "false": sum(1 for r in s_rows + r_rows if r.get("quote_verified") is False),
            "unchecked": sum(1 for r in s_rows + r_rows if r.get("quote_verified") is None),
        }
    if kind == "proof_experiment_rows":
        rows = [r for r in store.rows("experiments")
                if str(r.get("method") or "") == "formal"
                and str(r.get("evidence_kind") or "") == "proof"]
        return len(rows), {"experiments": [str(r.get("experiment_id") or "") for r in rows[:8]]}
    if kind == "reviewed_documents":
        rows = [r for r in store.rows("documents")
                if str(r.get("status") or "") in REVIEWED_DOC_STATUSES
                or int(r.get("review_rounds") or 0) >= 1]
        return len(rows), {"documents": [
            {"doc_id": str(r.get("doc_id") or ""), "status": str(r.get("status") or ""),
             "review_rounds": int(r.get("review_rounds") or 0)} for r in rows[:8]]}
    raise ValueError(f"没有这一档验收行：{kind!r}（受控词表：{tuple(LEG_CHECK_KINDS)}）")


def _check_acceptance(rep: ClosingReport, store: Any, project_dir: str) -> None:
    """验收表的机器可判行（`draft/37` §94）：逐行现算，任一不满足 ⇒ `fail`。

    三态：文件不在 ⇒ `pass` 并在读数里写明"这个项目没有机器可判的验收行"
    （那是"没有这一栏"，不是"没查成"）；文件在但读不懂/有未知档位/台账读不到 ⇒ `unknown`
    （"没查成"）；逐行都满足 ⇒ `pass`。
    """
    if not str(project_dir or "").strip():
        rep.status["acceptance"] = "unknown"
        rep.findings.append(Finding(
            "acceptance", "acceptance_not_checked", "warning",
            "没给项目根 ⇒ 验收表的机器可判行没查成（不是「没有这一条」）",
        ))
        return
    path = Path(resolve_under_workspace(store, project_dir)) / ACCEPTANCE_CHECKS_NAME
    if not path.is_file():
        rep.status["acceptance"] = "pass"
        rep.readings["acceptance"] = {"checks_file": str(path), "rows": [],
                                      "note": f"这个项目没有 {ACCEPTANCE_CHECKS_NAME}"}
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw["checks"] if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            raise ValueError("顶层必须是数组，或 {'checks': [...]}")
    except Exception as exc:  # noqa: BLE001 —— 读不懂就说读不懂（unknown 不是 pass）
        rep.status["acceptance"] = "unknown"
        rep.findings.append(Finding(
            "acceptance", "acceptance_unreadable", "warning",
            f"机器可判的验收行读不出来（{path}：{type(exc).__name__}: {exc}）⇒ 没查成",
        ))
        return

    out: list[dict[str, Any]] = []
    unmet: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            rep.status["acceptance"] = "unknown"
            rep.findings.append(Finding(
                "acceptance", "acceptance_unreadable", "warning",
                f"验收行必须是对象，收到了 {type(row).__name__} ⇒ 没查成"))
            return
        cid = str(row.get("id") or "")
        kind = str(row.get("kind") or "")
        name = str(row.get("name") or "")
        note = str(row.get("note") or "")
        want_min = int(row.get("min") or 1)
        if kind not in LEG_CHECK_KINDS:
            rep.status["acceptance"] = "unknown"
            rep.findings.append(Finding(
                "acceptance", "acceptance_unknown_kind", "warning",
                f"验收行 {cid} 的 kind={kind!r} 不在受控词表 {tuple(LEG_CHECK_KINDS)} 里 "
                "⇒ 这一行没查成（不是「满足了」）"))
            return
        got, detail = _leg_reading(store, kind)
        out.append({"id": cid, "name": name, "kind": kind, "min": want_min, "got": got,
                    "ok": got >= want_min, "detail": detail})
        if got < want_min:
            unmet.append(f"{cid}（{name or LEG_CHECK_KINDS[kind]}）：台账里 {got} 条，"
                         f"要求 ≥ {want_min} 条 —— 读数 {detail}"
                         + (f"；{note}" if note else ""))

    rep.readings["acceptance"] = {"checks_file": str(path), "rows": out}
    if unmet:
        rep.status["acceptance"] = "fail"
        rep.findings.append(Finding(
            "acceptance", "acceptance_unmet", "blocker",
            "验收表里机器可判的这几行**没满足**（这一趟的交付缺了任务点名的凭据）："
            + "；".join(unmet)
            + "。台账是唯一能复算的地方 —— 把凭据落进台账（不是只写进报告）再收工"))
    else:
        rep.status["acceptance"] = "pass"

#: 「这次调用没有会话身份」——与 `sid=None`（= 读缺省会话）「刻意分开」的两个输入。
#:
#: 为什么必须分开（`draft/37` §63 的真机读数，修法 B）：运行内 `conductor.closing`
#: 报 `user_pending: pass`，而同一次运行外部带 sid 的读数报 `fail` —— 假绿的病因
#: 是工具体按 `sid=None` 走到了 `sessions/<今天>.jsonl`，而那一趟的提问落在
#: `sessions/real11.jsonl` 里。"读缺省会话"是一个「具体且合法」的问题
#: （运维会问："这个工作区今天那段会话在等什么？"），所以 `sid=None` 的语义不改；
#: 缺的是第三个输入："调用方「没有」会话身份，这一格问不出来"。
#: 把它折进 `sid=None` 就会重演同一个假绿 —— 而这次连"读错了文件"都不会有人发现。
NO_SESSION = ""

#: 报告的九节（逐字照 `draft/37` §14.4 的清单）。
REPORT_SECTIONS: tuple[tuple[str, str], ...] = (
    ("一", "任务与范围"),
    ("二", "逐条读数"),
    ("三", "定理与引理清单"),
    ("四", "形式化覆盖"),
    ("五", "引文核验"),
    ("六", "体例与表述"),
    ("七", "我们做的补救"),
    ("八", "未决问题"),
    ("九", "诚实边界"),
)

#: 附件三件套（§16 P3 报告行逐字要求）。
ATTACHMENT_FIELDS: tuple[str, ...] = ("origin=own_result", "依据", "sha")

#: 分栏标记：报告必须把"我们补的"与"原文的"分开写。
SPLIT_MARKERS: tuple[str, ...] = ("我们补的", "原文的")

#: `draft/37` §10.2 的"什么时候必须上 T3"四条，逐条连同它今天的机械形态。
#: 写进门的意思不是"写进文档"，而是"门要能对每一条说出它判得了还是判不了" ——
#: 判不了的那一条必须明确登记为缺口，不许它悄悄消失。
#:
#:   (条件, 今天的机械形态, `load_bearing` 认不认它)
MUST_T3_CONDITIONS: tuple[tuple[str, str, str], ...] = (
    ("①作为定理写进正文",
     "`documents.claims[].evidence_kind == \"proof\"` 的断言必须引到一条 T3 实验"
     "（`method=\"formal\"` + `evidence_kind=\"proof\"` + `verifier_output` 非空）",
     "enforced"),
    ("②有别的结论依赖它",
     "`statements` 里被别人 `derived_from` 引到的 `active` 命题",
     "counted_only"),
    ("③与外部文献冲突",
     "`dependencies.status ∈ {refuted, disputed}` 或 `statements.status = disputed`",
     "enforced_by_contradictions"),
    ("④要进事实库",
     "`statements` 里 `status=\"active\"` 且 `evidence_kind=\"proof\"` 的命题",
     "counted_only"),
)

#: `counted_only` 那两条为什么今天判不了（写下来，免得下一个人以为是忘了）：
#: `statements` 表没有指向实验的字段（P1 的字段表里没有它）⇒
#: "这条命题有没有 T3 背书"在数据面上不可判定：只能数出"有几条承重命题"，
#: 判不了它们各自有没有形式化。补法有两条（都要改 `schema.py` ⇒ 属字段取舍，留给人）：
#: ① 给 `statements` 加一列指向 `experiments`（如 `proof_experiment_id`）；
#: ② 或者让 E 的 T3 实验反过来登记"我背书的是哪条 stmt"。
#: 在补上之前，收工门会对这两条给出 `counted_only` 的读数，
#: 而不是假装它们过了 —— 那正是"没查成不许折成通过"。
MUST_T3_GAP_NOTE = ("statements 表没有指向 experiments 的字段 ⇒ ②④今天只能数"
                    "（承重命题几条 / 降档几条），判不了逐条有没有 T3 背书。"
                    "补法见 closing.MUST_T3_CONDITIONS 上方的注释（要动 schema.py，留给人裁）")


@dataclass(frozen=True)
class Finding:
    """一条把门拦住的读数。`code` 是处置把手（谁该去做什么，见各处的 message）。"""

    check: str
    code: str
    level: str          # "blocker" | "warning"
    detail: str

    def to_dict(self) -> dict[str, Any]:
        """一条拦门读数的可读视图（落档与工具返回共用同一个形状）。"""
        return {"check": self.check, "code": self.code, "level": self.level, "detail": self.detail}


@dataclass
class ClosingReport:
    """各条检查的读数。`status` 每条一个三态值；`findings` 是拦门的原因。"""

    status: dict[str, str] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    readings: dict[str, Any] = field(default_factory=dict)

    @property
    def blockers(self) -> list[Finding]:
        """拦门的读数（`warning` 那些只报不拦：它们是"已知边界"，不是谎报）。"""
        return [f for f in self.findings if f.level == "blocker"]

    @property
    def unknowns(self) -> list[str]:
        """没查成的那些检查（不是通过）。"""
        return sorted(k for k, v in self.status.items() if v == "unknown")

    @property
    def failed(self) -> list[str]:
        """查过了、结论是"被拦住"的那些检查。"""
        return sorted(k for k, v in self.status.items() if v == "fail")

    @property
    def can_close(self) -> bool:
        """每条都 `pass` 才为真 —— `unknown` 与 `fail` 都不算通过。"""
        return all(v == "pass" for v in self.status.values()) and not self.blockers

    def to_dict(self) -> dict[str, Any]:
        """整份读数的可读视图（CLI、工具与落档共用同一个形状）。"""
        return {
            "can_close": self.can_close,
            "status": dict(self.status),
            "failed": self.failed,
            "unknowns": self.unknowns,
            "findings": [f.to_dict() for f in self.findings],
            "readings": dict(self.readings),
        }

    def summary(self) -> str:
        """一句话读数（给 CLI 与交付说明用；不许盖过明细）。"""
        if self.can_close:
            return f"收工门：{len(self.status)} 条全过 ⇒ 可交付"
        return (f"收工门：拦住（fail={self.failed or '无'} / unknown={self.unknowns or '无'}）"
                f"；拦门读数 {len(self.blockers)} 条")


# ------------------------------------------------------------------ 各条实现

def resolve_under_workspace(store: Any, given: str) -> str:
    """把"相对工作区"的路径解析成绝对路径（`"."` = 工作区根）。

    ## 为什么必须有它（`draft/37` §60 的真机读数）

    第十趟主控按工具描述传 `project_dir="."` 与 `report_path="out/review/REPORT.md"`
    （描述逐字写的是"相对工作区"），然后撞上一串怪读数：
    `closing` 报"报告不在盘上"（它明明刚写完、`fs.stat` 也确认 6,743 字节）、
    "锚文件读不到"（文件也在盘上），`conductor.acceptance(project_dir=".")`
    还解析到了工作区上一级。它花了 8 步去查这件事（步 27–34），
    最后结论："`project_dir='.'` 被解析到工作区上一级"。

    病因在实现侧：`Path(given)` 是按进程当前目录解析的，而工具的契约是
    "相对工作区" —— 两个口径不一致时，错的读数看起来像"文件不在"。
    处置：在入口处解析一次（`store.root` 为基准），并把绝对路径原样放过。
    """
    raw = str(given or "").strip()
    if not raw:
        return ""
    path = Path(raw)
    if path.is_absolute():
        return str(path)
    root = Path(getattr(store, "root", "."))
    return str((root / path).resolve())


def _check_anchor(rep: ClosingReport, project_dir: str, store: Any) -> None:
    """锚：复用 `renderanchor.check_package`（同一份实现，不另写一个判据）。

    `project_dir` 要的是项目根，不是论文包目录 —— `check_package` 自己会拼
    `out/paper`。这一点原先只有实现知道、措辞全说反了（工具描述与这里的提示语都写
    "论文包所在目录"），2026-10-02 的真机读数就是后果：主控照描述传 `out/paper`，
    工具去找 `out/paper/out/paper/RENDER-ANCHOR.json`，锚那一格变成 `unknown`，
    白花一步（`draft/37` §44.5）。所以现在两件事一起做：
    措辞改成"项目根"，并在找不到锚时把期望的路径形状点名。
    相对路径按工作区根解析（见 `resolve_under_workspace`）。
    """
    if not str(project_dir or "").strip():
        rep.status["anchor"] = "unknown"
        rep.findings.append(Finding(
            "anchor", "anchor_not_checked", "warning",
            "没给项目根（project_dir）⇒ 渲染锚没查成。这是没查成，不是一致 —— "
            "交付前必须指到**项目根**再跑一次（锚在 <项目根>/out/paper/RENDER-ANCHOR.json）",
        ))
        return
    got = RA.check_package(resolve_under_workspace(store, project_dir), store=store)
    verdict = str(got.get("verdict") or "unknown")
    rep.readings["anchor"] = {"verdict": verdict, "dimensions": got.get("dimensions"),
                              "drift": list(got.get("drift") or [])[:10]}
    if verdict == "consistent":
        rep.status["anchor"] = "pass"
    elif verdict == "drifted":
        rep.status["anchor"] = "fail"
        rep.findings.append(Finding(
            "anchor", "anchor_drifted", "blocker",
            f"渲染锚报 drifted：{('；'.join(list(got.get('drift') or [])[:3]))[:200]} ⇒ "
            "包不是库里现在的样子。重渲染 + 重编译，并在**最后一次写台账之后**再核一次",
        ))
    else:
        rep.status["anchor"] = "unknown"
        hint = ""
        if not got.get("anchor_present"):
            # 没找到锚时把"该给哪个目录"说清楚：这是最常见的调用姿势错误
            # （给论文包目录而不是项目根），而原来的错误只说"读不到"。
            expect = Path(str(project_dir)) / "out" / "paper" / RA.ANCHOR_NAME
            hint = (f"；锚要在 {expect} —— 若你给的是论文包目录（…/out/paper），"
                    "请改传**项目根**（check_package 会自己拼 out/paper）")
        rep.findings.append(Finding(
            "anchor", "anchor_unknown", "warning",
            f"渲染锚报 unknown：{('；'.join(list(got.get('problems') or [])[:3]))[:200]} ⇒ "
            "有一维判不了（锚不在 / 回执不在）。这不是一致" + hint,
        ))


def pollution_set(store: Any, stmt_id: str) -> list[str]:
    """一条命题被推翻时跟着倒的那些命题（`draft/37` §9 / R20 的"污染面"）。

    做法是 `statements.derived_from` 上的传递闭包（谁用到我、谁又用到它……），
    不含自身。为什么必须有它：§9 的处置不是"把这一条划掉"就完事 ——
    `draft/37` 的用词是"如果错的是文献，那么压在它上面的结论就不能再算数"，
    而"压在它上面"在数据面上就是这张有向图。

 已知边界（写成读数而不是假装完整）：今天的污染面只覆盖命题之间的
    `derived_from`。正文断言（`documents.claims[].citations`）今天只认 `lit:` / `exp:` /
    `rel:` 三种前缀，没有引用命题的形式 ⇒ "哪几条正文断言压在这条命题上"判不了。
    补法是给 citations 加一种 `stmt:` 前缀（属字段取舍，留给人裁）——
    在补上之前，本函数只对命题层给读数，并把这条边界写进 `readings`。
    """
    rows = {str(s.get("stmt_id")): s for s in (store.rows("statements") if store else [])}
    if stmt_id not in rows:
        return []
    seen: set[str] = set()
    frontier = {stmt_id}
    while frontier:
        nxt: set[str] = set()
        for sid, row in rows.items():
            if sid in seen or sid == stmt_id:
                continue
            if set(str(x) for x in (row.get("derived_from") or [])) & frontier:
                seen.add(sid)
                nxt.add(sid)
        frontier = nxt
    return sorted(seen)


def _check_contradictions(rep: ClosingReport, store: Any) -> None:
    """未裁决的矛盾：三种病因各自一个 code（`draft/37` §8 / R19）+ 污染面（R20）。

    为什么不能只报一句"有矛盾"：三种病因的处置方向完全不同，而代码就是处置把手 ——

    | 病因 | code | 谁去做什么 |
    |---|---|---|
    | 我们读错了文献（下成另一篇） | `contradiction_wrong_paper` | A：重取对的那一篇（`matched="mismatch"` 已在 P2 落成一栏） |
    | 来源本身有争议（两篇文献两说） | `contradiction_disputed_source` | D 追原始证明 → 判不了就 `ask_user`（§8 的裁决闭环） |
    | 我们自己的证明有洞 | `contradiction_own_hole` | D 给可挽救性评估，E 补 T3，或如实降档 |
    | 稿件审校未过（H 的未决项） | `review_unresolved` | G 修订 / H 复审（§14.4 的"未决问题"那一节） |

    前三种正是 §17.1 要求"三种病因各一条负控"的那三条；第四种来自 §14.4
    的报告第九节，单列是因为它的处置是"回稿子"而不是"回证据"。
    """
    if store is None:
        rep.status["contradictions"] = "unknown"
        rep.findings.append(Finding("contradictions", "no_store", "warning",
                                    "没有 store ⇒ 矛盾没查成（不是没有矛盾）"))
        return
    wrong_paper: list[str] = []
    disputed_source: list[str] = []
    own_hole: list[str] = []
    unresolved_review: list[str] = []
    pollution: dict[str, list[str]] = {}
    #: 被证否、且确实有结论压在它上面的那些（§9：压在上面的结论不能再算数）。
    #: 与 `own_hole` 分开：`own_hole` 说的是"我们的 proof 级证明压在不可用的命题上"，
    #: 而这一条不管压在上面的那几条是什么证据等级 —— 只要有人用，就必须处置。
    pollution_items: list[str] = []

    # ---- ① 我们读错了文献：命中校验 mismatch 且已经被消化（P2 的那一栏）
    for row in store.rows("literature"):
        if str(row.get("matched") or "") == "mismatch" and row.get("processed"):
            wrong_paper.append(f"文献 {row.get('lit_id')}"
                               f"（{str(row.get('title') or '')[:40]}）")

    # ---- ② 来源本身有争议 / 被证否：依赖与命题两处
    stmt_status = {str(s.get("stmt_id")): str(s.get("status") or "")
                   for s in store.rows("statements")}
    for row in store.rows("dependencies"):
        st = str(row.get("status") or "")
        if st in ("disputed", "refuted"):
            disputed_source.append(f"依赖 {row.get('dep_id')} status={st}"
                                   f"（{str(row.get('label') or '')[:40]}）")
    for row in store.rows("statements"):
        st = str(row.get("status") or "")
        if st == "disputed":
            disputed_source.append(f"命题 {row.get('stmt_id')} status=disputed"
                                   f"（{str(row.get('label') or '')[:40]}）")
        if st in ("refuted", "disputed"):
            # ③ 我们自己的证明压在一条不可用的命题上 ⇒ 洞在我们这边
            for other in store.rows("statements"):
                if str(other.get("status") or "") != "active":
                    continue
                if str(other.get("evidence_kind") or "") != "proof":
                    continue
                if str(row.get("stmt_id")) in {str(x) for x in (other.get("derived_from") or [])}:
                    own_hole.append(f"命题 {other.get('stmt_id')} 的证明压在 {row.get('stmt_id')}"
                                    f"（status={st}）上")
            if st == "refuted":
                downstream = pollution_set(store, str(row.get("stmt_id")))
                pollution[str(row.get("stmt_id"))] = downstream
                if downstream:
                    pollution_items.append(f"命题 {row.get('stmt_id')} 被证否 ⇒ "
                                           f"{downstream} 跟着倒")

    for row in store.rows("documents"):
        if str(row.get("status") or "") == "unresolved_review":
            unresolved_review.append(f"稿件 {row.get('doc_id')}")

    rep.readings["contradictions"] = {
        "wrong_paper": wrong_paper,
        "disputed_source": disputed_source,
        "own_hole": own_hole,
        "review_unresolved": unresolved_review,
        "pollution": pollution,
        "pollution_scope": "只覆盖命题之间的 derived_from；正文断言没有引用命题的形式"
                           "（citations 只认 lit:/exp:/rel:）⇒ 断言级污染面今天判不了",
    }
    causes: tuple[tuple[str, str, str, list[str]], ...] = (
        ("contradiction_wrong_paper", "blocker", "我们读错了文献（下成了另一篇）", wrong_paper),
        ("contradiction_disputed_source", "blocker", "来源本身有争议或已被证否", disputed_source),
        ("contradiction_own_hole", "blocker", "我们自己的证明压在不可用的命题上", own_hole),
        ("contradiction_pollution", "blocker",
         "污染面：被证否的命题下面**还压着结论**（§9：它们不能再算数）", pollution_items),
        ("review_unresolved", "blocker", "稿件审校未过（H 的未决项）", unresolved_review),
    )
    fired = False
    for code, level, why, items in causes:
        if not items:
            continue
        fired = True
        extra = ""
        if code == "contradiction_disputed_source":
            extra = ("。处置：追原始证明 → 判不了就 `ask_user`（§8 的裁决闭环）；"
                     "**不许**把有争议的来源当成已确认的")
        elif code == "contradiction_wrong_paper":
            extra = "。处置：重取对的那一篇（这一栏就是 P2 的 `matched`）"
        elif code == "contradiction_own_hole":
            extra = ("。处置：D 给可挽救性评估、E 补 T3，或如实降档 —— "
                     "压在上面的结论在修好之前不能算数")
        elif code == "review_unresolved":
            extra = "。处置：G 修订 / H 复审（§14.4 的未决问题那一节）"
        elif code == "contradiction_pollution":
            extra = ("。处置：要么把被证否那条的来源换掉（重取 / 换一篇），"
                     "要么把压在上面的结论一起降档或撤回")
        pollution_note = ""
        if code == "contradiction_disputed_source" and pollution:
            pollution_note = ("；**污染面**（被证否的那些，谁跟着倒）："
                              + "；".join(f"{k} → {v}" for k, v in sorted(pollution.items())))
        rep.findings.append(Finding(
            "contradictions", code, level,
            f"{why}：共 {len(items)} 处 —— " + "；".join(items[:5]) + extra + pollution_note,
        ))
    rep.status["contradictions"] = "fail" if fired else "pass"


def _has_t3(exp: Mapping[str, Any]) -> bool:
    """T3 的机械形态（§10.2）：形式化方法 + proof 级 + 检查器真的说过话。"""
    return (str(exp.get("method") or "") == "formal"
            and str(exp.get("evidence_kind") or "") == "proof"
            and bool(str(exp.get("verifier_output") or "").strip()))


def _check_load_bearing(rep: ClosingReport, store: Any) -> None:
    """承重结论必须有 T3 或已降档（§10.2 的四条"必须上 T3"在收工门上的形态）。

    承重 = 正文里 `evidence_kind="proof"` 的断言（"作为定理写进正文"那一档，
    §10.2 的第①条）。T3 = 一条 `method="formal"` + `evidence_kind="proof"` +
    `verifier_output` 非空的 `experiments` 行，且被该断言的 `citations` 引到
    （或有一条 `closed` 依赖指向它）。

    负控②（`draft/37` §10.2）：非承重的结论没上 T3 不许因此判失败 ——
    省下来的钱要看得见，所以这里只数承重的那些。
    """
    if store is None:
        rep.status["load_bearing"] = "unknown"
        rep.findings.append(Finding("load_bearing", "no_store", "warning",
                                    "没有 store ⇒ 承重结论没查成"))
        return
    docs = store.rows("documents")
    exps = {str(r.get("experiment_id")): r for r in store.rows("experiments")}
    closed_exp_ids = {str(r.get("source_experiment_id"))
                      for r in store.rows("dependencies")
                      if str(r.get("status") or "") == "closed" and r.get("source_experiment_id")}
    load_bearing = 0
    downgraded = 0
    bad: list[str] = []
    for doc in docs:
        for claim in doc.get("claims") or []:
            if not isinstance(claim, Mapping):
                continue
            if str(claim.get("evidence_kind") or "") != "proof":
                continue          # 非承重（cross_check / heuristic）⇒ 这条门不管它
            load_bearing += 1
            cites = {str(c) for c in (claim.get("citations") or [])}
            backed = any(f"exp:{eid}" in cites and _has_t3(row) for eid, row in exps.items())
            backed = backed or any(eid in closed_exp_ids and _has_t3(row)
                                   for eid, row in exps.items() if f"exp:{eid}" in cites)
            if not backed:
                bad.append(f"{doc.get('doc_id')}#{claim.get('claim_id')}"
                           f"（{str(claim.get('text') or '')[:40]}）")
    # 命题台账那一半：`active` + proof 级 + 有下游（被别人 derived_from 引到）= 承重。
    stmts = store.rows("statements")
    downstream: dict[str, int] = {}
    for s in stmts:
        for dep in s.get("derived_from") or []:
            downstream[str(dep)] = downstream.get(str(dep), 0) + 1
    stmt_load_bearing = 0
    for s in stmts:
        if str(s.get("status") or "") != "active":
            continue
        if not downstream.get(str(s.get("stmt_id"))):
            continue
        stmt_load_bearing += 1
        if str(s.get("evidence_kind") or "") != "proof":
            downgraded += 1          # 已降档：这正是允许的出路
    rep.readings["load_bearing"] = {
        "claims_with_proof": load_bearing,
        "claims_without_t3": len(bad),
        "statements_load_bearing": stmt_load_bearing,
        "statements_downgraded": downgraded,
        "must_t3_conditions": [{"condition": c, "mechanical": m, "status": s}
                               for c, m, s in MUST_T3_CONDITIONS],
        "must_t3_gap": MUST_T3_GAP_NOTE,
    }
    if bad:
        rep.status["load_bearing"] = "fail"
        rep.findings.append(Finding(
            "load_bearing", "load_bearing_without_t3", "blocker",
            f"有 {len(bad)} 条承重结论（正文里 evidence_kind='proof'）没有 T3 背书："
            + "；".join(bad[:5])
            + "。要么补形式化（E 的 check_formal，检查器原话进 verifier_output），"
            "要么如实降档成 cross_check/heuristic 并改稿件的措辞（§10.2："
            "措辞不许出现「已证明/定理/必然」）",
        ))
    else:
        rep.status["load_bearing"] = "pass"


def _check_report_shape(rep: ClosingReport, report_path: str, store: Any) -> None:
    """报告九节 + 分栏 + 附件三件套（§14.4 / §16 P3 的报告行）。"""
    if not str(report_path or "").strip():
        rep.status["report_shape"] = "unknown"
        rep.findings.append(Finding(
            "report_shape", "report_path_missing", "warning",
            "没给报告路径 ⇒ 报告形状没查成（不是「报告没问题」）",
        ))
        return
    path = Path(resolve_under_workspace(store, report_path))
    if not path.is_file():
        rep.status["report_shape"] = "unknown"
        rep.findings.append(Finding(
            "report_shape", "report_not_written", "warning",
            f"报告不在盘上：{path} ⇒ 没查成。报告是 M 的产物（九节；落点 out/review/REPORT.md）",
        ))
        return
    text = path.read_text(encoding="utf-8")
    missing = [f"{num}、{name}" for num, name in REPORT_SECTIONS
               if f"{num}、" not in text and name not in text]
    missing_split = [m for m in SPLIT_MARKERS if m not in text]
    has_attach = [f for f in ATTACHMENT_FIELDS if f in text]
    rep.readings["report_shape"] = {
        "path": str(path), "chars": len(text),
        "missing_sections": missing, "missing_split_markers": missing_split,
        "attachment_fields": has_attach,
    }
    problems: list[str] = []
    if missing:
        problems.append(f"缺 {len(missing)} 节（{'、'.join(missing[:4])}）")
    if missing_split:
        problems.append(f"缺分栏标记（{'、'.join(missing_split)}）—— "
                        "「我们补的」与「原文的」必须分开写")
    if problems:
        rep.status["report_shape"] = "fail"
        rep.findings.append(Finding(
            "report_shape", "report_incomplete", "blocker",
            f"报告形状不齐：{'；'.join(problems)}（§14.4 的九节是形状，不是建议）",
        ))
    else:
        rep.status["report_shape"] = "pass"


def _check_substance(rep: ClosingReport, store: Any) -> None:
    """实质产出：这一趟到底产出了什么（空台账不许报「可交付」）。

    ## 为什么要有这一格（T1 实测，`draft/37` §84 的 D2）

    那一趟退出码 0、报告九节齐全、`user_pending: pass`，而台账是
    `documents=0 / statements=0 / relations=0 / experiments=0 / review_findings=0`
    —— 前五格全过、`can_close=true`、报告写「可交付」。原因不是判据写错了，
    而是没有一格问"产出了什么"：`report_shape` 只看节名，而 `anchor` /
    `contradictions` / `load_bearing` 在空台账上天然为空（真空成立）。
    这正是本项目最忌的同族形态：把"没做"读成"没问题"。

    ## 三态

    - 五张表都读得到：全 0 ⇒ `fail`（读数逐张列出）；有非空 ⇒ `pass`；
    - 有表读不到 ⇒ `unknown`（"问不出来"不是"没问题"）。
    """
    if store is None:
        rep.status["substance"] = "unknown"
        rep.findings.append(Finding("substance", "no_store", "warning",
                                    "没有 store ⇒ 产出了什么问不出来（不是没有产出）"))
        return
    counts: dict[str, int] = {}
    problems: list[str] = []
    for table in SUBSTANCE_TABLES:
        try:
            counts[table] = len(store.rows(table))
        except Exception as e:  # noqa: BLE001 - 表读不到要如实报"问不出来"
            problems.append(f"{table} 读不到（{type(e).__name__}: {e}）")
    detail = "、".join(f"{t}={counts.get(t, '读不到')}" for t in SUBSTANCE_TABLES)
    rep.readings["substance"] = dict(counts)
    if problems:
        rep.status["substance"] = "unknown"
        rep.findings.append(Finding(
            "substance", "substance_unreadable", "warning",
            "有一张表读不到 ⇒ 这一格问不出来：" + "；".join(problems) + f"（读数：{detail}）"))
        return
    total = sum(counts.values())
    if total == 0:
        rep.status["substance"] = "fail"
        rep.findings.append(Finding(
            "substance", "no_substantive_output", "blocker",
            f"这一趟没有任何实质产出（{detail}）⇒ 不许报「可交付」："
            "报告形状对、锚一致、没有矛盾，都不等于**做了事**。"
            "处置：把该产出的东西产出（登记命题 / 跑实验 / 落稿件 / 审校发现），"
            "或如实写清「这一趟什么都没做成、卡在哪」，而不是交一份形式上的交付"))
        return
    rep.status["substance"] = "pass"
    rep.readings["substance_total"] = total


def _check_user_pending(rep: ClosingReport, session_root: Any,
                       *, sid: str | None = None) -> None:
    """还在等用户回答 ⇒ 必须停在"等待用户"（§14.5 第 4 件 / R26）。

    `sid` 的三态（`draft/37` §63）：一个具体会话号 = 读那一段；
    `None` = 读缺省会话（`sessions/<今天>.jsonl`，运维口径，合法）；
    `NO_SESSION` = 「调用方没有会话身份」 ⇒ 这一格是 `unknown`。
    第三个输入是修法 B 加的：装配期没把 sid 注入进来时，按缺省会话读会得出
    "没问过用户"——而真机每一趟都有自己的 sid（实测 `real11`：
    运行内报 pass、外部带 sid 报 fail）。「不许」用缺省值冒充"查过了"。
    """
    if session_root is None:
        rep.status["user_pending"] = "unknown"
        rep.findings.append(Finding("user_pending", "no_session_root", "warning",
                                    "没有会话记录根 ⇒ 待答问题没查成"))
        return
    if sid == NO_SESSION:
        rep.status["user_pending"] = "unknown"
        rep.findings.append(Finding(
            "user_pending", "no_session_identity", "warning",
            "这次调用没有会话身份（装配期没注入 sid，`tools.build_registry(sid=...)`）"
            "⇒ 待答问题**没查成**。不许按缺省会话读：真机每一趟都有自己的 sid，"
            "按缺省读会把「问了还没答」读成「没问过」（`draft/37` §63 的假绿）",
        ))
        return
    # `sid` 必须跟着运行走（`draft/37` §58）：不带它时按默认会话读，
    # 而真机每一趟都有自己的 sid ⇒ 待答问题会被读成「没问过」。
    pending = U.pending_questions(session_root, sid=sid)
    replies = U.read_replies(session_root, sid=sid)
    rep.readings["user_pending"] = {
        "pending": [{"qid": q.qid, "role": q.role, "text": q.text[:80]} for q in pending],
        "answered": len(replies),
        "asked": len(pending) + len(replies),
    }
    if pending:
        rep.status["user_pending"] = "fail"
        rep.findings.append(Finding(
            "user_pending", "waiting_for_user", "blocker",
            f"还有 {len(pending)} 个问题在等用户回答（"
            + "、".join(q.qid for q in pending[:5]) + "）⇒ **必须停在「等待用户」**："
            "不许把它当成默许继续做（三态纪律）。用户答完（`agentflow answer`）再 `--resume` 续跑",
        ))
    else:
        rep.status["user_pending"] = "pass"


# ------------------------------------------------------------------ 入口

def check_closing(store: Any, *, project_dir: str = "", report_path: str = "",
                  session_root: Any = None, checks: tuple[str, ...] = DEFAULT_CHECKS,
                  sid: str | None = None,
                  ) -> ClosingReport:
    """跑收工门，返回读数（不抛业务异常 —— 没查成落成 `unknown`）。

    `session_root` 不给时取 `store.root`（会话记录与工作区本来就是同一个根，
    两处分开写迟早会出现"审计记录落在别处"的静默错位）。
    `project_dir` / `report_path` 不给 ⇒ 对应的那一两格是 `unknown`（不是 pass）：
    门宁可说"我没查成"，也不许在缺少读数时说"可以交"。
    `sid` 三态见 :data:`NO_SESSION`：具体会话号 / `None`（缺省会话）/
    `NO_SESSION`（没有会话身份 ⇒ `user_pending` 那格 `unknown`）。
    """
    rep = ClosingReport()
    root = session_root if session_root is not None else getattr(store, "root", None)
    for name in checks:
        if name == "anchor":
            _check_anchor(rep, project_dir, store)
        elif name == "contradictions":
            _check_contradictions(rep, store)
        elif name == "load_bearing":
            _check_load_bearing(rep, store)
        elif name == "report_shape":
            _check_report_shape(rep, report_path, store)
        elif name == "user_pending":
            _check_user_pending(rep, root, sid=sid)
        elif name == "substance":
            _check_substance(rep, store)
        elif name == "acceptance":
            _check_acceptance(rep, store, project_dir)
        else:
            rep.status[name] = "unknown"
            rep.findings.append(Finding(name, "unknown_check", "warning",
                                        f"没有这个检查：{name!r}（判据表与实现在这里分家了）"))
    return rep


def tri_state_exit_code(rep: ClosingReport) -> int:
    """CLI 的三态退出码：0 可交付 / 1 被拦住 / 2 没查成（`unknown` 不算通过）。"""
    if rep.can_close:
        return 0
    if rep.unknowns and not rep.failed:
        return 2
    return 1

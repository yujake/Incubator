"""F 的证明手稿：依赖段由 F 写在这里，依赖台账由 B 读稿登记（业主 2026-10-24 最终形态）。

## 业主原话（唯一权威）

    「依赖面登记是否是F在其手稿中写好，D的研究手稿引用F的证明手稿给B入库时，B侧读到
      F手稿处的依赖面，按此入库的？（即和V签一个逻辑）」
    「改」

⇒ 作者只写内容，登记由收方读稿产生（与 V 读 F 的手稿再签字同一个逻辑）。所以本文件
只做两件不写台账的事：

1. `AgentF.proof_manuscript(...)`：把这一轮的论证写成一份手稿文件。两段命名（原因见方法
   docstring 的"死结 1"）：登记之前先按计划号写成 `reports/f-proof-plan-<plan_id>.md`，
   登记拿到命题号之后由 `publish_manuscript` 改名为 `reports/f-proof-<命题号>.md`；
   两份都含那一节固定格式的 `## 依赖`（四列表，见 `agentflow.depsection.COLUMN_KEYS`）。
2. `AgentF.preview_dependencies(...)`：只读预览 —— 拿一份手稿正文，按 B 那条判据
   （`depsection` 的解析 ＋ 引用档位门 ＋ 三态读数）算出"如果现在入库会怎样"，
   F 据此在自己这一侧先看见问题。它一行都不写盘。

## 为什么依赖段必须由 F 写在手稿里（而不是 F 直接写表）

四趟真机 `dependencies` 全 0 行的根因不是"没人想写"，而是"没人有入口"：唯一点名的
依赖正路是 G 的 `doc.register_dependency`，F 一件依赖写入口都没有；而秘书那条
"从证明正文扫依赖"只认 `stmt:` / `lit:` / `exp:` / `doc:` 前缀，真机的证明是中文
散文（"由引理 2"）⇒ 扫出 0 条。业主的处置不是"给 F 开一个写表的工具"，而是把格式
定死：作者在手稿里写清楚"我引了哪一条、用在哪一步、属于第几条证明"，收方（B）照表登记。
散文读不出来的东西，一张四列的表读得出来。

## 这一份手稿里有什么

```
# F 的证明手稿：<子目标>

- 命题号：stmt:<号>（这一份证明落成的那条）
- 计划：<plan_id> · 子目标：<sid>

## 命题
<命题正文>

## 证明
1. <这一步说了什么>（依据：stmt:000001）
2. ...

## 依赖
| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |
|---|---|---|---|
| 由定理甲，G 有 p 阶元 | stmt:000000 | 第 1 步 | 1 |
```
"""

from __future__ import annotations

from ._support import Any, Mapping, S, Sequence, _short

from .. import depsection as _DS
from .. import manuscriptform as _MF
from ..manuscriptform import (  # noqa: F401 —— 两族唯一实现在这里，本模块只转发
    carry_sign_block,
    ensure_statement_line,
    formal_shape_problem,
)


class _Manuscript:
    """F 的证明手稿（依赖段 ＋ 只读预览）＋ 提示词里那份"可引用的在册命题"。"""

    #: 手稿落点（工作区相对）：与 `_Core.REPORT_DIR` 同一个目录（`reports/`）。
    MANUSCRIPT_DIR = "reports"
    #: 依赖段里"引用（F 的原话）"那一格最多占多少字（超出截断，并写明截断了）。
    QUOTE_CHARS = 80
    #: 一条在册命题在提示词里最多占多少字（超出截断，并写明截断了）。
    STATEMENT_ITEM_CHARS = 160
    #: 提示词里最多列几条"可引用的在册命题"（超出只报条数，不静默截断）。
    CITABLE_STATEMENTS = 20

    # ---------------------------------------------------------------- 读侧

    def statement_rows(self) -> tuple[list[dict[str, Any]], str]:
        """把 `statements` 读成行列表，并如实带回读不成的那一句（空列表 + 非空 why）。

        绝不用 `[]` 冒充"台账里一条命题都没有" —— 那是两件事。
        """
        try:
            return [dict(r) for r in self.store.rows("statements")], ""
        except Exception as exc:  # noqa: BLE001 - 读不到要如实说，不许折成空表
            return [], f"{type(exc).__name__}: {exc}"

    def citable_statements(self) -> tuple[list[str], list[str], str]:
        """B 已收录、这一轮写证明时可读可引的命题 ⇒ `(提示词行, 可引 id, 说明)`。

        业主的裁定是"写证明时允许读 B 侧已收录的定理" —— 读得到的前提是提示词里有它们。
        改前提示词只列子目标自己攒的那几条证据，模型根本不知道台账里有哪些命题可引，
        于是"引用在册定理"这件事在真机里没有发生的机会。

        列入的条件与 B 读稿时那一条判据同源（`depsection.citation_level_allowed`）：
        只有等级 `pre_theorem` 及以上的才既读得到又引得成（2026-11-05 起门槛读等级，
        不再读 `statements.evidence_kind` 那一列历史）。低于该档的、等级算不出来的
        只报条数并说清"引用它们会被受控拒绝" —— 不列出来，是因为"能引"与"列在这里"
        必须是同一件事（两份清单漂开，模型就会照着引一条注定被拒的）。
        """
        rows, unreadable = self.statement_rows()
        if unreadable:
            return [], [], (f"（`statements` 这一次读不出来：{unreadable} ⇒ 本轮没有可引的"
                            "在册命题可列；那是「读不到」，不是「台账里没有」）")
        #: 可引池只有一处定义（`depsection.citable_pool` = 在册 ∧ 等级 ≥ pre_theorem）：
        #: 提示词里列的这几条与 B / V 收稿时允许引的那一批同一个判据。两份各算
        #: 一份的形态是"提示词里列了、交上去却被拒"（或反过来），而那种漂没有读数。
        pool = _DS.citable_pool(rows)
        usable = [r for r in rows if str(r.get("status") or "") == "active"]
        usable.sort(key=lambda r: str(r.get("stmt_id") or ""))
        eligible: list[dict[str, Any]] = []
        below = 0
        unknown_level = 0
        for row in usable:
            if str(row.get("stmt_id") or "") in pool:
                eligible.append(row)
            elif not _DS.statement_grade(row):
                unknown_level += 1
            else:
                below += 1
        lines: list[str] = []
        ids: list[str] = []
        for row in eligible[: self.CITABLE_STATEMENTS]:
            sid = str(row.get("stmt_id") or "")
            kind = str(row.get("kind") or "")
            label = " ".join(str(row.get("label") or row.get("statement_text") or "").split())
            grade = _DS.statement_grade(row)
            line = (f"stmt:{sid}（kind={kind or '（没写）'}，label={label or '（没有标签）'}，"
                    f"grade={grade or '（算不出来）'}）")
            if len(line) > self.STATEMENT_ITEM_CHARS:
                line = _short(line, self.STATEMENT_ITEM_CHARS)
            lines.append(line)
            ids.append(f"stmt:{sid}")
        rest: list[str] = []
        if below:
            rest.append(f"{below} 条的等级低于 {_DS.CITATION_MIN_LEVEL}（conjecture / "
                        "strong_conjecture 那一档）—— 引用它们会被受控拒绝")
        if unknown_level:
            rest.append(f"{unknown_level} 条的等级算不出来 —— 也不许引（读不到就不放行）")
        if len(eligible) > len(lines):
            rest.append(f"另有 {len(eligible) - len(lines)} 条够格但没列出来（这一块只列前 "
                        f"{self.CITABLE_STATEMENTS} 条）")
        note = f"（另有 {'；'.join(rest)}）" if rest else ""
        if not eligible:
            empty = ("（台账里现在没有一条站到 "
                     f"{_DS.CITATION_MIN_LEVEL} 级及以上的在册命题 ⇒ 这一轮不许引 `stmt:`；"
                     "要声明前提就把那一步写成 `assumption: true`")
            return [], [], empty + (f"；另有 {'；'.join(rest)}" if rest else "") + "）"
        return lines, ids, note

    # ---------------------------------------------------------------- 写手稿

    def dependency_rows(self, product: Mapping[str, Any]) -> list[dict[str, Any]]:
        """这一轮产物里点名的 `stmt:` 引用 ⇒ 依赖段的数据行（一条引用一行）。

        口径与判据都不在这里另写：能进这一份手稿的引用已经在 `_foreign_cites` 与
        `_evidence_digest` 那一层核过（只许引在册 id），本函数只负责"把 F 的原话、
        命题号、用在哪一步、第几条证明"这四格摆出来。
        """
        rows: list[dict[str, Any]] = []
        steps = [s for s in (product.get("steps") or []) if isinstance(s, Mapping)]
        seen: dict[str, int] = {}
        for i, step in enumerate(steps, 1):
            for cite in (step.get("cites") or []):
                text = str(cite).strip()
                if not text.startswith("stmt:"):
                    continue
                bare = text[5:].split("#", 1)[0].strip()
                if not bare:
                    continue
                if bare in seen:
                    # 同一条命题在几步里都引了：依赖边是一条（一条引用一行），
                    # 但"用在哪几步"必须写全 —— 少一步就是"这条边挂错了位置"。
                    rows[seen[bare]]["steps"].append(i)
                    continue
                seen[bare] = len(rows)
                rows.append({
                    "stmt_id": bare,
                    "quote": _short(" ".join(str(step.get("text") or "").split()),
                                    self.QUOTE_CHARS),
                    "steps": [i],
                    "path_group": 1,
                })
        for row in rows:
            row["step"] = "第 " + "、".join(str(n) for n in row.pop("steps")) + " 步"
        return rows

    @staticmethod
    def render_dependency_section(rows: Sequence[Mapping[str, Any]]) -> str:
        """这一节固定格式的表格（转发到 `depsection.render_dependency_section`）。

        「渲染出来的这一份，解析器必须读得回同一批行」由
        `tests/test_dependency_face_is_read_from_f_manuscript.py::test_the_policy_example_is_the_format_the_parser_accepts`
        钉住。实现本体在 `depsection`（解析与渲染必须同一个人写），本方法只转发 ——
        原来这里另写了一份一模一样的渲染，已在 2026-11-04 的统一里删掉。
        """
        return _DS.render_dependency_section(rows)

    def proof_manuscript(self, product: Mapping[str, Any], *, sg: Mapping[str, Any],
                         statement_id: str = "", plan: Mapping[str, Any],
                         label: str = "", proof_no: int = 1,
                         ) -> dict[str, Any]:
        """把这一轮的论证写成手稿文件并返回读数（写盘失败不许静默）。

        返回 `{"ok", "path", "text", "rows", "preview", "why", "named_by"}`：`rows` 是依赖段里的
        数据行，`preview` 是"这份手稿交给 B 会怎样"的只读预览（`preview_dependencies`），
        `text` 是整份手稿（调用方可以直接把它交给 B 入库，不必再读盘）。

        ## 为什么 `statement_id` 现在可以不给（2026-10-26，死结 1 的修法）
        改前这个方法必须在登记之后调用（它要拿命题号命名），而登记那一刻稿还不存在 ⇒
        B 侧读稿登记这一格永远读不到东西。现在两段：
        ① 登记之前先写一份，按计划号命名（`reports/f-proof-plan-<plan_id>.md`）——
           此刻手上还没有命题号，但稿已经在盘上、正文也在手上；
        ② 登记成功之后由 :meth:`publish_manuscript` 改名为 `reports/f-proof-<命题号>.md`，
           于是按命号找稿的读方（B 的兜底读盘）也找得到。
        `named_by` 如实说这一份是按什么命名的（`plan` / `stmt`），读的人不必猜。

        ## 2026-11-04（业主裁定）：渲染与落盘只剩一份实现
        页头与三节的拼法在 `manuscriptform.render_proof_manuscript`（与 B 的改写稿同
        一段代码），写盘事务在 `manuscriptform.commit_manuscript`。本方法只做两件 F 特有
        的事：把 `steps[]` 拼成证明正文、把读数换成 F 的调用方要的形状。
        """
        sid = str(sg.get("sid") or "")
        plan_id = str(plan.get("plan_id") or "")
        rows = self.dependency_rows(product)
        steps = [s for s in (product.get("steps") or []) if isinstance(s, Mapping)]
        proof_lines = []
        for i, step in enumerate(steps, 1):
            cites = [str(c) for c in (step.get("cites") or [])]
            suffix = f"（依据：{'、'.join(cites)}）" if cites else "（前提）"
            proof_lines.append(f"{i}. {str(step.get('text') or '').strip()}{suffix}")
        proposition = str(sg.get("text") or "").strip() + (
            f"；这一条的可检验形式：{sg.get('testable')}" if sg.get("testable") else "")
        text = _MF.render_proof_manuscript(
            _MF.FAMILY_F, title=str(sg.get("text") or ""),
            statement_id=statement_id, proposition=proposition,
            proof_text="\n".join(proof_lines or ["（这一轮没有交出论证正文）"]),
            dependency_rows=rows, plan_id=plan_id, sid=sid,
            label=label, proof_no=proof_no)
        rel = self.manuscript_path(statement_id, sid, plan_id=plan_id)
        root = self.cfg.get("workspace_root") or getattr(self.store, "root", "") or "."
        preview = self.preview_dependencies(text)
        got = _MF.commit_manuscript(
            root, family=_MF.FAMILY_F, text=text, statement_id=statement_id,
            plan_id=plan_id, retitle="none", dependency_rows=rows)
        out = {"ok": bool(got.get("ok")), "path": rel, "text": text, "rows": rows,
               "preview": preview, "named_by": "stmt" if statement_id else "plan",
               "why": str(got.get("why") or "")}
        if not got.get("ok"):
            # 写盘那一格失败时保留 F 原来那句"依赖面这一趟只能靠 B 读正文"的读数。
            out["why"] = str(got.get("why") or "") or out["why"]
        return out

    def publish_manuscript(self, manuscript: Mapping[str, Any], *,
                           statement_id: str) -> dict[str, Any]:
        """登记拿到命题号之后，把那一份手稿改名为 `reports/f-proof-<命题号>.md`。

        为什么必须改名（而不是留在计划号那个名字上）：兜底读盘的第一个候选名就是
        `f-proof-<命题号>.md`（`depsection.manuscript_relpaths`），而收方（B）手上最确切的号
        正是它要登记的那条命题点名过的号。计划号那个名字太宽（一个计划会有好几轮），
        只留着它，收方要么找不到、要么找到别人的稿。

        ## 2026-11-04（业主口径）：「登记成功（拿到命题号）就改名，签另算」

        改前这一步与"有没有 V 签"缠在一起：登记被 `proof_without_v_sign` 整笔拒
        ⇒ 拿不到号 ⇒ 一次也没改名（87 的 6 份稿里 0 份按号命名）。现在两条纪律：

        - 改名只看号：`statement_id` 非空就改名 + 重写标题，有没有签都不影响；
        - 搬签是可选第二步（`carry_sign_block`）：有块且 sha 相符才搬；没块只改名
          （`sign_moved=False`、`publish_problem={}`，那是「签另算」不是失败）。

        三件纪律（读数面）：
        - 正文不再读盘：改名用的是手上这一份 `text`（登记那一刻的稿就是它）；
        - 任何半改名都不许静默：`publish_problem` 是一个受控读数（`kind` / `stage` / `why`），
          覆盖「改名了但标题没重写」「旧名没删掉」「签块 sha 不符」「搬块读不成」；
          `published` / `retitled` / `sign_moved` 三格分开给，读的人不必猜成功到哪一步；
        - 旧名与命名来源都留在读数里（`renamed_from` / `named_by`），溯源要能看出改名发生过。
        """
        sid = str(statement_id or "").strip()
        text = str(manuscript.get("text") or "")
        old_rel = str(manuscript.get("path") or "")
        out = dict(manuscript)
        out["renamed_from"] = ""
        out["published"] = False
        out["retitled"] = False
        out["sign_moved"] = False
        out["sign_step"] = {"checked": False, "found": False, "sha_match": None,
                            "moved": False, "candidates": [], "why": ""}
        out["publish_problem"] = {}
        if not sid:
            out["why"] = "没有命题号 ⇒ 这一份手稿不改名（它仍按计划号命名）"
            return out
        if not text.strip():
            # 手上没有正文时绝不写一个空文件：空稿会被兜底读盘跳过（"文件在、正文是空的"），
            # 而在盘上留一个空文件只会让下一个读它的人以为"稿写过、只是空的"。
            out["why"] = "手上没有正文 ⇒ 这一份手稿不按命号落盘（写一个空文件比没有更坏）"
            return out
        root = self.cfg.get("workspace_root") or getattr(self.store, "root", "") or "."
        # 改名 / 搬签 / 不毁签 / 旧名清理的判据全在 `manuscriptform.commit_manuscript`
        # （与 B 的改写落稿同一个事务）：这里只把读数换成 F 的调用方要的形状。
        got = _MF.commit_manuscript(
            root, family=_MF.FAMILY_F, text=text, statement_id=sid,
            old_rel=old_rel, retitle="replace", delete_old=True)
        out["retitled"] = bool(got.get("retitled"))
        out["sign_moved"] = bool(got.get("sign_moved"))
        out["sign_step"] = dict(got.get("sign_step") or {})
        problem = dict(got.get("problem") or {})
        out["publish_problem"] = problem
        if not got.get("ok"):
            out["why"] = str(got.get("why") or "")
            return out
        # 半改名（有名字没标题）也要有读数：不静默，但不因此拒绝改名 ——
        # 号是已经拿到的，按号命名对收方仍然比计划名更精确。
        if not out["retitled"] and not out["publish_problem"]:
            out["publish_problem"] = {
                "kind": "renamed_without_retitle", "stage": "retitle",
                "why": ("这一份稿头里没有 `- 命题号：` 那一行（或写了别的号）"
                        "⇒ 名字会按号、正文认不出是哪一条；要补这一行再交"),
            }
        out["text"] = str(got.get("text") or text)
        out["path"] = str(got.get("path") or self.manuscript_path(sid))
        out["renamed_from"] = str(got.get("renamed_from") or "")
        out["published"] = True
        out["why"] = ""
        return out

    # -------------------------------------------------------------- 只读预览

    def preview_dependencies(self, manuscript: str) -> dict[str, Any]:
        """只读预览：一份手稿交给 B 入库时，依赖面会变成什么样（一行都不写盘）。

        三态纪律都落在这里：
        - 段里某行读不懂 ⇒ `checked=True` ＋ `ok=False` ＋ `refused`（带行号与列名）；
        - 手稿没有依赖段 ⇒ `ok=False` ＋ `refused=dependency_section_missing`，
          而证明正文里有 `stmt:` 引用时 `deps_missing.state="missing"`（反静默 0 行）；
        - 段里的来源档位不够 / 读不到 ⇒ 与 B 那条判据同一个受控码（`depsection.gate_rows`）。
        """
        text = str(manuscript or "")
        section = _DS.parse_dependency_section(text)
        #: 引用只在"证明正文"那一节里数（手稿开头的元信息不是引用，见
        #: `depsection.proof_body` 的注释）—— 数进来会让 `refs` 与 `derived_from` 都虚高。
        body = _DS.proof_body(text)
        out: dict[str, Any] = {"checked": True, "ok": False, "refused": "", "reason": "",
                              "section": section, "rows": section.get("rows") or [],
                              "levels": {}, "would_write": 0, "deps_missing": {}}
        refs = _DS.stmt_refs(body)
        if section.get("refused"):
            out.update(refused=str(section.get("refused")),
                       reason=str(section.get("reason") or ""))
            out["deps_missing"] = _DS.deps_missing_reading(
                proof_text=body, deps_written=0, derived_from=refs, refs=len(refs),
                section=section)
            return out
        if not section.get("present"):
            if refs:
                out.update(refused=str(_DS.REFUSED_SECTION_MISSING),
                           reason=_MF.detail(_MF.DEPENDENCY_SECTION_MISSING,
                                             refs=len(refs)))
            else:
                out["reason"] = (f"手稿里没有 `{_DS.SECTION_HEADING}` 这一节，正文也没有引用任何"
                                 "在册命题 ⇒ 依赖面这一格不适用（B 不会因此拒收：自足的证明合法）")
            out["deps_missing"] = _DS.deps_missing_reading(
                proof_text=body, deps_written=0, derived_from=refs, refs=len(refs),
                section=section)
            return out
        rows = section.get("rows") or []
        # 2026-11-05（缺陷甲）：表在、但 0 行数据而正文点了在册号 ⇒ 预览就必须说"会退"。
        # 改前预览与 B 的登记入口都只看 `present`，于是"交出去会不会被退"这一格会亮 ok。
        #
        # 2026-11-06（业主口径的纠正）：正文里的号必须是"可引"的（在册 ∧ 等级
        # ≥ pre_theorem）；不在册 / 等级不够的号 ⇒ 这一笔写错了（F 读不到它），
        # 预览就报受控拒，拒信点名那个号。可引池只有一处定义（`citable_pool`），
        # 与提示词那份清单、B 的登记入口、V 的依赖面审计同源。
        try:
            stmt_rows = [dict(r) for r in self.store.rows("statements")]
        except Exception as exc:  # noqa: BLE001 - 读不到就不许说"够格"
            out.update(refused=str(_DS.REFUSED_LEVEL_UNREADABLE),
                       reason=(f"预览要核每条来源的档位、并判正文的引用在不在可引池里，"
                               f"而 `statements` 读不出来"
                               f"（{type(exc).__name__}: {exc}）⇒ 这次预览没查成"))
            return out
        _code, _why = _DS.dependency_consistency_problem(
            text, known_ids=_DS.citable_pool(stmt_rows), statement_rows=stmt_rows)
        if _code:
            out.update(refused=str(_code), reason=str(_why))
            out["deps_missing"] = _DS.deps_missing_reading(
                proof_text=body, deps_written=0, derived_from=refs, refs=len(refs),
                section=section)
            return out
        gate = _DS.gate_rows(rows, stmt_rows)
        out["levels"] = dict(gate.get("levels") or {})
        if not gate.get("ok"):
            out.update(refused=str(gate.get("refused") or ""),
                       reason=str(gate.get("reason") or ""))
            out["deps_missing"] = _DS.deps_missing_reading(
                proof_text=body, deps_written=0, derived_from=refs, refs=len(refs),
                section=section)
            return out
        out.update(ok=True, would_write=len(rows))
        out["deps_missing"] = _DS.deps_missing_reading(
            proof_text=body, deps_written=len(rows), derived_from=refs,
            refs=len(refs), section=section)
        return out

    def promote_manuscript(self, source: str, *, statement_id: str,
                           text: str = "", delete_source: bool = False,
                           write_dependencies: Any = None) -> dict[str, Any]:
        """把盘上已经存在的一份攻坚稿转成 `reports/f-proof-<号>.md`（实现见模块级函数）。

        这是 `publish_manuscript` 的盘上稿入口：后者只改"这一轮刚写完、手上还拿着
        正文"的那一份；这一件读盘上那一份（`notes/…` 或 `reports/f-proof-plan-*.md`）。
        签块跟着搬、第 9 格手稿号按新名重算、形状不对就受控拒绝 —— 判据本体只有一处
        （`manuscriptform.promote_formal`）。
        """
        root = self.cfg.get("workspace_root") or getattr(self.store, "root", "") or "."
        return promote_manuscript(root, statement_id=statement_id, source=source,
                                  text=text, delete_source=delete_source,
                                  store=self.store,
                                  write_dependencies=write_dependencies)

    def manuscript_path(self, statement_id: str = "", sid: str = "",
                        plan_id: str = "") -> str:
        """这一份手稿的落点（工作区相对）—— 与 `proof_manuscript` 写的是同一处。

        两种名由 `manuscriptform.name_reading` 一处定义（内部只走
        `vsigns.parse_manuscript_name`；兜底读盘读的是同一处口径）：有命题号按命题号，
        只有计划号按计划号，都没有时退回子目标号（那一支只在调用方既没给命题号、
        计划也没号时才会出现，绝不静默返回一个空路径）。
        """
        if statement_id:
            got = _MF.name_reading(_MF.FAMILY_F, statement_id=statement_id)
            if got.get("ok"):
                return str(got["path"])
        elif plan_id:
            got = _MF.name_reading(_MF.FAMILY_F, plan_id=plan_id)
            if got.get("ok"):
                return str(got["path"])
        return f"{self.MANUSCRIPT_DIR}/{_MF.family_prefix(_MF.FAMILY_F)}{sid}.md"



# ---------------------------------------------------------------- 转正（攻坚稿 → 正式稿）
#
# 业主口径（2026-11-04 交接的那条链）：「登记成功（拿到命题号）就改名，签另算」。
# `publish_manuscript` 覆盖的是 F 自己手上那一份（`_apply_round` 的 proof 档写完就改名）；
# 盘上已经存在的一份稿（真机 `projects/paper-rewrite-big` 的
# `notes/F-conj000000-proof.md`，F 自己 `fs.write` 写的攻坚稿）此前没有任何代码把它
# 变成 `reports/f-proof-<号>.md` —— 于是按号命名的正式稿 0 份，B 的兜底读盘、D 的携带单、
# V 的签块落点全都找不到它。
#
# 2026-11-04（业主裁定）：转正实现只有一份（`manuscriptform.promote_formal`），F 与 B
# 两族由 `family=` 参数区分 —— 本模块这一个只做转发。

#: 转正只收工作区相对路径里的这两种根：`notes/`（草稿本，攻坚手稿）与 `reports/`
#: （正式落点；计划名那份稿也在这里）。唯一的实现在 `manuscriptform`。
PROMOTE_SOURCE_ROOTS: tuple[str, ...] = _MF.PROMOTE_SOURCE_ROOTS


def promote_manuscript(root: Any, *, statement_id: str, source: str = "",
                       text: str = "", delete_source: bool = False,
                       store: Any = None,
                       write_dependencies: Any = None) -> dict[str, Any]:
    """把盘上已经存在的一份稿转成 `reports/f-proof-<号>.md`（转发，判据只在一处）。

    返回 `{promoted, path, source, renamed_from, retitled, sign_moved, sign_step,
    problem, source_kept, why}`；`problem` 是受控读数（`kind`/`stage`/`why`）。
    实现本体在 :func:`manuscriptform.promote_formal`（B 的转正也走它）。
    """
    return _MF.promote_formal(
        root, family=_MF.FAMILY_F, statement_id=statement_id, source=source,
        text=text, delete_source=delete_source, store=store,
        write_dependencies=write_dependencies)
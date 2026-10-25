"""F 的证明手稿：依赖段由 F 写在这里，依赖台账由 B 读稿登记（业主 2026-10-24 最终形态）。

## 业主原话（唯一权威）

    「依赖面登记是否是F在其手稿中写好，D的研究手稿引用F的证明手稿给B入库时，B侧读到
      F手稿处的依赖面，按此入库的？（即和V签一个逻辑）」
    「改」

⇒ 作者只写内容，登记由收方读稿产生（与 V 读 F 的手稿再签字同一个逻辑）。所以本文件
只做两件不写台账的事：

1. `AgentF.proof_manuscript(...)`：把这一轮的论证写成一份手稿文件
   （`reports/f-proof-<命题号>.md`），其中必须有那一节固定格式的 `## 依赖`
   （四列表，见 `agentflow.depsection.COLUMN_KEYS`）；
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

from ._support import Any, Mapping, Path, S, Sequence, _short

from .. import depsection as _DS


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
        只有 `proof_review` 级及以上的才既读得到又引得成。低于该档的、档位读不到的
        只报条数并说清"引用它们会被受控拒绝" —— 不列出来，是因为"能引"与"列在这里"
        必须是同一件事（两份清单漂开，模型就会照着引一条注定被拒的）。
        """
        rows, unreadable = self.statement_rows()
        if unreadable:
            return [], [], (f"（`statements` 这一次读不出来：{unreadable} ⇒ 本轮没有可引的"
                            "在册命题可列；那是「读不到」，不是「台账里没有」）")
        usable = [r for r in rows if str(r.get("status") or "") == "active"]
        usable.sort(key=lambda r: str(r.get("stmt_id") or ""))
        eligible: list[dict[str, Any]] = []
        below = 0
        unknown_level = 0
        for row in usable:
            level = str(row.get("evidence_kind") or "").strip()
            if not level or level not in S.EVIDENCE_KINDS:
                unknown_level += 1
            elif _DS.citation_level_allowed(level):
                eligible.append(row)
            else:
                below += 1
        lines: list[str] = []
        ids: list[str] = []
        for row in eligible[: self.CITABLE_STATEMENTS]:
            sid = str(row.get("stmt_id") or "")
            kind = str(row.get("kind") or "")
            label = " ".join(str(row.get("label") or row.get("statement_text") or "").split())
            ek = str(row.get("evidence_kind") or "")
            line = (f"stmt:{sid}（kind={kind or '（没写）'}，label={label or '（没有标签）'}，"
                    f"evidence_kind={ek or '（没写）'}）")
            if len(line) > self.STATEMENT_ITEM_CHARS:
                line = _short(line, self.STATEMENT_ITEM_CHARS)
            lines.append(line)
            ids.append(f"stmt:{sid}")
        rest: list[str] = []
        if below:
            rest.append(f"{below} 条的档位低于 {_DS.CITATION_MIN_LEVEL}（cross_check / heuristic "
                        "那一档）—— 引用它们会被受控拒绝")
        if unknown_level:
            rest.append(f"{unknown_level} 条的档位读不到 —— 也不许引（读不到就不放行）")
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
        """把数据行渲染成那一节固定格式的表格（表头四列，逐字与解析器对齐）。"""
        head = "| " + " | ".join(name for _f, _k, name in _DS.COLUMN_KEYS) + " |"
        rule = "|" + "|".join("---" for _ in _DS.COLUMN_KEYS) + "|"
        lines = [_DS.SECTION_HEADING, "", head, rule]
        for row in rows:
            lines.append("| {quote} | stmt:{sid} | {step} | {group} |".format(
                quote=str(row.get("quote") or "").replace("|", "／"),
                sid=str(row.get("stmt_id") or ""),
                step=str(row.get("step") or ""),
                group=int(row.get("path_group") or 1)))
        if not rows:
            # 一条引用都没有也要把表头留着：于是"这份证明是自足的、确实没有引用"
            # 与"作者忘写了这一节"在 B 那侧读得不一样（三态不是靠猜的）。
            lines.append("")
            lines.append("（这一份证明没有引用任何在册命题 —— 空表就是声明。）")
        return "\n".join(lines) + "\n"

    def proof_manuscript(self, product: Mapping[str, Any], *, sg: Mapping[str, Any],
                         statement_id: str, plan: Mapping[str, Any]) -> dict[str, Any]:
        """把这一轮的论证写成手稿文件并返回读数（写盘失败不许静默）。

        返回 `{"ok", "path", "text", "rows", "preview", "why"}`：`rows` 是依赖段里的数据行，
        `preview` 是"这份手稿交给 B 会怎样"的只读预览（`preview_dependencies`），
        `text` 是整份手稿（调用方可以直接把它交给 B 入库，不必再读盘）。
        """
        sid = str(sg.get("sid") or "")
        rows = self.dependency_rows(product)
        steps = [s for s in (product.get("steps") or []) if isinstance(s, Mapping)]
        proof_lines = []
        for i, step in enumerate(steps, 1):
            cites = [str(c) for c in (step.get("cites") or [])]
            suffix = f"（依据：{'、'.join(cites)}）" if cites else "（前提）"
            proof_lines.append(f"{i}. {str(step.get('text') or '').strip()}{suffix}")
        text = "\n".join([
            f"# F 的证明手稿：{_short(str(sg.get('text') or ''), 60)}",
            "",
            f"- 命题号：stmt:{statement_id or '（还没落号）'}",
            f"- 计划：{plan.get('plan_id')} · 子目标：{sid}",
            "",
            "## 命题",
            "",
            str(sg.get("text") or "").strip()
            + (f"；这一条的可检验形式：{sg.get('testable')}" if sg.get("testable") else ""),
            "",
            "## 证明",
            "",
            *(proof_lines or ["（这一轮没有交出论证正文）"]),
            "",
            self.render_dependency_section(rows),
        ])
        rel = f"{self.MANUSCRIPT_DIR}/f-proof-{statement_id or sid}.md"
        root = self.cfg.get("workspace_root") or getattr(self.store, "root", "") or "."
        preview = self.preview_dependencies(text)
        try:
            path = Path(root) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "path": rel, "text": text, "rows": rows,
                    "preview": preview,
                    "why": f"手稿没写成（{type(exc).__name__}: {exc}）⇒ 依赖面这一趟只能靠"
                           "B 读正文（而正文是散文的话，B 读不出依赖边）"}
        return {"ok": True, "path": rel, "text": text, "rows": rows,
                "preview": preview, "why": ""}

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
                           reason=(f"手稿里没有 `{_DS.SECTION_HEADING}` 这一节：依赖面不会按格式"
                                   f"登记（证明正文里现在有 {len(refs)} 条 `stmt:` 引用）"
                                   "⇒ B 会整笔拒收 `dependency_section_missing`"))
            else:
                out["reason"] = (f"手稿里没有 `{_DS.SECTION_HEADING}` 这一节，正文也没有引用任何"
                                 "在册命题 ⇒ 依赖面这一格不适用（B 不会因此拒收：自足的证明合法）")
            out["deps_missing"] = _DS.deps_missing_reading(
                proof_text=body, deps_written=0, derived_from=refs, refs=len(refs),
                section=section)
            return out
        rows = section.get("rows") or []
        try:
            stmt_rows = [dict(r) for r in self.store.rows("statements")]
        except Exception as exc:  # noqa: BLE001 - 读不到就不许说"够格"
            out.update(refused=str(_DS.REFUSED_LEVEL_UNREADABLE),
                       reason=(f"预览要核每条来源的档位，而 `statements` 读不出来"
                               f"（{type(exc).__name__}: {exc}）⇒ 这次预览没查成"))
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

    def manuscript_path(self, statement_id: str, sid: str = "") -> str:
        """这一份手稿的落点（工作区相对）—— 与 `proof_manuscript` 写的是同一处。"""
        return f"{self.MANUSCRIPT_DIR}/f-proof-{statement_id or sid}.md"

    @staticmethod
    def section_example() -> str:
        """政策里那个正例（逐字与渲染器同形；判据拿它核渲染与解析不漂）。"""
        return _Manuscript.render_dependency_section([
            {"stmt_id": S.format_id(0), "quote": "由定理甲，G 有 p 阶元",
             "step": "第 1 步", "path_group": 1},
        ])

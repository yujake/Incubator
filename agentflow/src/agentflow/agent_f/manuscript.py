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
        """把数据行渲染成那一节固定格式的表格（表头四列，逐字与解析器对齐）。

        「渲染出来的这一份，解析器必须读得回同一批行」由
        `tests/test_dependency_face_is_read_from_f_manuscript.py::test_the_policy_example_is_the_format_the_parser_accepts`
        钉住（它把渲染 → 解析走一遍并逐格比）；原来这里另有一个 `section_example`
        供那条判据用，但它全仓 0 个调用者、判据实际走的是上面那条 —— 已删。
        """
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
                         statement_id: str = "", plan: Mapping[str, Any],
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
        rel = self.manuscript_path(statement_id, sid, plan_id=plan_id)
        root = self.cfg.get("workspace_root") or getattr(self.store, "root", "") or "."
        preview = self.preview_dependencies(text)
        try:
            path = Path(root) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "path": rel, "text": text, "rows": rows,
                    "preview": preview, "named_by": "stmt" if statement_id else "plan",
                    "why": f"手稿没写成（{type(exc).__name__}: {exc}）⇒ 依赖面这一趟只能靠"
                           "B 读正文（而正文是散文的话，B 读不出依赖边）"}
        return {"ok": True, "path": rel, "text": text, "rows": rows,
                "preview": preview, "named_by": "stmt" if statement_id else "plan",
                "why": ""}

    @staticmethod
    def _retitle(text: str, statement_id: str) -> str:
        """把开头那行"命题号"改成真的号（登记之前写的是"还没落号"）。

        为什么必须改：按命号改名之后，读者（B 的携带核对、D 的递交、人）
        都会读这一行来认"这份稿是哪条命题的"。只改文件名、不改它，盘上就出现
        "文件叫 `f-proof-000001.md`、正文说'还没落号'"的双读数 —— 而按号去对
        携带单的那一侧会找不到它（`depsection.manuscript_statement_id`）。
        """
        sid = str(statement_id or "").strip()
        if not sid:
            return str(text or "")
        lines = str(text or "").replace("\r\n", "\n").split("\n")
        for i, line in enumerate(lines[:12]):
            if line.strip().startswith("- 命题号"):
                lines[i] = f"- 命题号：stmt:{sid}"
                return "\n".join(lines)
        return "\n".join(lines)

    def publish_manuscript(self, manuscript: Mapping[str, Any], *,
                           statement_id: str) -> dict[str, Any]:
        """登记拿到命题号之后，把那一份手稿改名为 `reports/f-proof-<命题号>.md`。

        为什么必须改名（而不是留在计划号那个名字上）：兜底读盘的第一个候选名就是
        `f-proof-<命题号>.md`（`depsection.manuscript_relpaths`），而收方（B）手上最确切的号
        正是它要登记的那条命题点名过的号。计划号那个名字太宽（一个计划会有好几轮），
        只留着它，收方要么找不到、要么找到别人的稿。

        三件纪律：
        - 正文不再读盘：改名用的是手上这一份 `text`（登记那一刻的稿就是它）；
        - 改名失败不许静默：返回里 `published=False` + `why`，`path` 仍是旧名（稿还在盘上，
          只是叫旧名字）—— "稿丢了"与"稿没改名"是两件事；
        - 旧名与命名来源都留在读数里（`renamed_from` / `named_by`），溯源要能看出改名发生过。
        """
        sid = str(statement_id or "").strip()
        text = str(manuscript.get("text") or "")
        old_rel = str(manuscript.get("path") or "")
        out = dict(manuscript)
        out["renamed_from"] = ""
        out["published"] = False
        if not sid:
            out["why"] = "没有命题号 ⇒ 这一份手稿不改名（它仍按计划号命名）"
            return out
        if not text.strip():
            # 手上没有正文时绝不写一个空文件：空稿会被兜底读盘跳过（"文件在、正文是空的"），
            # 而在盘上留一个空文件只会让下一个读它的人以为"稿写过、只是空的"。
            out["why"] = "手上没有正文 ⇒ 这一份手稿不按命号落盘（写一个空文件比没有更坏）"
            return out
        new_rel = self.manuscript_path(sid)
        root = self.cfg.get("workspace_root") or getattr(self.store, "root", "") or "."
        # 按号改名时把开头那一行"命题号"也改成真的号：只改文件名会让盘上出现
        # "文件叫 f-proof-000001.md、正文说还没落号"的双读数（见 `_retitle`）。
        titled = self._retitle(text, sid)
        out["text"] = titled
        if old_rel == new_rel:
            out.update(path=new_rel, published=True, why="")
            return out
        try:
            target = Path(root) / new_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(titled, encoding="utf-8")
            old_path = (Path(root) / old_rel) if old_rel else None
            if old_path is not None and old_path.is_file():
                try:
                    old_path.unlink()
                    out["renamed_from"] = old_rel
                except OSError as exc:  # noqa: BLE001 - 旧名删不掉不影响新名可读
                    out["renamed_from"] = old_rel
                    out["why"] = (f"新名写成了，旧名 {old_rel} 没删掉（{type(exc).__name__}: "
                                  f"{exc}）—— 盘上会有两份同一份稿")
                    out.update(path=new_rel, published=True)
                    return out
        except OSError as exc:
            out["why"] = (f"手稿没改名（{type(exc).__name__}: {exc}）⇒ 它还叫 {old_rel}；"
                          "按命号找稿的读方会找不到它")
            return out
        out.update(path=new_rel, published=True, why="")
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

    def manuscript_path(self, statement_id: str = "", sid: str = "",
                        plan_id: str = "") -> str:
        """这一份手稿的落点（工作区相对）—— 与 `proof_manuscript` 写的是同一处。

        两种名由 `depsection.manuscript_relpath` 一处定义（兜底读盘读的是同一处口径）：
        有命题号按命题号，只有计划号按计划号，都没有时退回子目标号（那一支只在调用方
        既没给命题号、计划也没号时才会出现，绝不静默返回一个空路径）。
        """
        rel = _DS.manuscript_relpath(statement_id=statement_id, plan_id=plan_id)
        if rel:
            return rel
        return f"{self.MANUSCRIPT_DIR}/{_DS.MANUSCRIPT_STMT_PREFIX}{sid}.md"

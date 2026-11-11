"""角色 G 的动作 `revise`（`goal-7f5116c1` M6：从 `agent_g.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import Any, DT, DocumentError, Mapping, S, SIG, Sequence
from .revise_gates import checked_claims

#: `revise` 回来时必须点名的下一步（丙，2026-11-11）。措辞照 `specs/m.py` 那句
#: 「改完之后要再复核（D57）」—— 同一个意思只有一份说法，不自造新词。
#: 2026-11-11 业主裁定之后 `G → H` 是真边（`G` 的出边 = `C/D/H`），所以 G 自己就能派。
REVISE_NEXT_STEP = (
    "改完之后要再复核：派 `H.verify_fixes`（它按 `round_no` 复核这一版）"
    "或 `H.review`，让签名钉到现行版上；改完不复核的稿子不许当成交付。"
)

class _Revise:
    def revise(
        self,
        doc_id: str,
        *,
        fixed_findings: Sequence[str] | None = None,
        new_claims: Sequence[Mapping[str, Any]] | None = None,
        note: str = "",
    ) -> dict:
        """按 H 的发现修订稿件。
        - `review_rounds += 1`、`status = "revised"`、并重渲染 markdown；- `new_claims` 里代号已存在的断言会替换原
        断言（修订），新代号则追加。没有这条替换语义，G 就只能"再加一句新话"，永远改不掉那句错话 —— 那 `revise` 就修不好任何一条审校发现；- 
        `fixed_findings` 里的 finding 只改 `status`/`resolution_note`，内容一个字不改（那是 H 的判断依据）。发现不属于本稿
        ⇒ 抛错： G 不许借"修订"去动别人的稿件上的发现。
        这里标的 `fixed` 不是终局判定：H 的 `verify_fixes` 会重跑检查，仍复现就把状态改回 `open`。
        ## 修订同样要核"引用是否真的存在"（此前的缺口）
        `build_document` 有两道闸：`normalize_claims`（`citations` 非空）与`check_citations`（引用指向的对象真的在库
        里）。`revise` 此前只过了第一道，于是 `revise(new_claims=[claim citing "lit:9999"])` 会成功写库 ——一份用"改写"
        这条路绕开引用存在性检查的稿件。这比"没有引用"更隐蔽：读者看到的是一个像模像样的 `lit:9999`，而库里根本没有这篇文献。
        现在两条路复用同一个 `DT.check_citations`（不另写第二份判据），并把它放在同一笔事务里读表，避免"核引用"与"写 documents"看到不同快照。
        """
        doc_id = str(doc_id)
        with self.store.tx(
            "documents", "dependencies", "review_findings",
            # 下面五张表只为 `check_citations` / `check_proofs` 而声明：`Store.tx` 按
            # `LOCK_ORDER` 统一排序加锁，多声明几张表不会引入加锁顺序问题。
            #
            # `statements` 是真机 t1v 抓出来的（`draft/94` §10）：`check_citations`
            # 按 `CITATION_PREFIXES`（六张表）核引用，而这里原来只声明了五张 ⇒ 任何
            # 引用了自家命题（`stmt:`）的修订都整笔写不进去，报的是
            # 「事务未声明表 statements」。同族的缺口在 `doc.build_document` 上
            # （`a3f4c83` 修过一次）—— 一处改完、另一处没跟着改，两个入口就此分家。
            "literature", "relations", "experiments", "eval_results", "statements",
            actor=self.actor, note=f"revise doc:{doc_id} {note}".strip(),
        ) as tx:
            doc = tx.find("documents", doc_id=doc_id)
            if doc is None:
                raise DocumentError(f"稿件 {doc_id} 不存在 ⇒ 不能修订一份不存在的稿件")

            merged = [dict(c) for c in (doc.get("claims") or [])]
            replaced: list[str] = []
            appended: list[str] = []
            for raw in new_claims or []:
                if not isinstance(raw, Mapping):
                    raise DocumentError(f"new_claims 的元素必须是对象，收到 {type(raw).__name__}")
                c = dict(raw)
                cid = str(c.get("claim_id") or "").strip()
                idx = next(
                    (i for i, e in enumerate(merged) if cid and str(e.get("claim_id")) == cid), None
                )
                if idx is not None:
                    merged[idx] = c
                    replaced.append(cid)
                else:
                    merged.append(c)
                    appended.append(cid or f"（自动编号，第 {len(merged)} 条）")

            # 三道闸（机械检查 / 引用存在性 / proof 级证据锚）搬进了
            # `agent_g/revise_gates.py`：判断、顺序、异常与消息逐字不变，只是为了让
            # 这个动作留在 200 行线内（2026-11-11 体量拆分）。
            normalized = checked_claims(
                tx.rows, merged, doc_id=doc_id,
                kind=str(doc.get("kind") or ""),
                workspace_root=self.workspace_root,
            )

            doc["claims"] = normalized
            doc["review_rounds"] = int(doc.get("review_rounds") or 0) + 1
            doc["status"] = "revised"
            doc["updated_at"] = S.now_iso()
            # 改稿 = 新的一版（`draft/30` §T4-A）：`revision` 前进一格、内容哈希重算。
            # 旧审批因此自动失效（它钉的是上一版的哈希），这是设计要的：
            # "审批过的版本"与"被引用的版本"不许静默分家。
            doc["revision"] = int(doc.get("revision") or 0) + 1
            doc["content_sha256"] = SIG.content_sha256_of(doc)
            row = S.row_from_dict("documents", doc)
            row.validate()
            payload = row.to_dict()
            tx.upsert("documents", payload)

            fixed_ids: list[str] = []
            for fid in fixed_findings or []:
                f = tx.find("review_findings", finding_id=str(fid))
                if f is None:
                    raise DocumentError(f"发现 {fid} 不存在 ⇒ 不能把一条不存在的发现标成已修")
                if str(f.get("doc_id")) != doc_id:
                    raise DocumentError(
                        f"发现 {fid} 属于稿件 {f.get('doc_id')}，不是 {doc_id}："
                        "**G 只能改自己稿件上的发现状态**（跨稿改动是掩盖问题的入口）"
                    )
                f["status"] = "fixed"
                stamp = f"[round {payload['review_rounds']}] G 在 revise 中声明已处理"
                if note:
                    stamp += f"：{note}"
                f["resolution_note"] = (str(f.get("resolution_note") or "").strip() + " " + stamp).strip()
                tx.upsert("review_findings", f)
                fixed_ids.append(str(fid))

            rendered: str | None = None
            rel = payload.get("markdown_path")
            body_rel, body_abs = DT.body_artifact_of(self.workspace_root, payload)
            if rel:
                target = self._resolve_inside(str(rel))
                deps = DT.dependencies_for_doc(tx.rows("dependencies"), doc_id)
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(DT.render_markdown(payload, dependencies=deps), encoding="utf-8")
                except OSError as e:
                    raise DocumentError(
                        f"修订后重渲染失败（{target}）：{type(e).__name__}: {e}。"
                        "宁可整笔回滚，也不留下一份'库与磁盘不一致'的稿件"
                    ) from e
                rendered = str(target)
                # `D-44`：重画之后，中间产物自己的 sha 也跟着换一版 —— 记在同一笔事务里。
                # 不记的话，读侧会把每一次正常改稿都报成"内容已变"（噪音会把真信号淹掉）。
                # 甲（2026-11-11）：同一条事件里记「正文」那一份的 sha（paper =
                # `out/paper/main.tex`，其它 kind = markdown 自己）。这是"改稿"这件事
                # 在 `documents` 登记行上的唯一读数 —— 不新造第二份账。
                artifact = DT.record_markdown_artifact(
                    tx, doc_id, rel, target,
                    body_rel=body_rel, body_absolute=body_abs,
                )
            else:
                # 没有 markdown_path 的行（历史行）仍然要给正文读数：正文就是
                # `out/paper/main.tex`（paper）或空（其它 kind）。这里只记读数、
                # 不改任何数据行（与 `note_markdown_artifact` 同一条纪律）。
                artifact = {
                    "body_path": str(body_rel or ""), "body_sha256": "",
                    "body_problem": "这一行没有 markdown_path", "sha256": "",
                }
            # 「这份稿子引了几条台账凭据 / 库里还有多少可引的」（`doc.build_document` 的
            # `meta.citation_coverage` 同一条读数，走同一份实现）：修订这条路也要给，
            # 否则"改写"成了绕开那条读数的后门 —— 与 `check_citations` / `check_proofs`
            # 在同一条路上各补过一次的那两处完全同形（本文件上面两段注释）。
            # 它在事务内现算，看到的是这一笔修订之后的 claims。
            try:
                coverage = DT.citation_coverage(
                    tx.rows, normalized, citing_kind=str(doc.get("kind") or "")
                )
            except Exception as exc:  # noqa: BLE001 —— 读数算不出不许影响这笔修订
                coverage = {"readable": False, "reason": f"{type(exc).__name__}: {exc}"}

        self._emit(
            f"修订 doc:{doc_id} → review_rounds={payload['review_rounds']}，"
            f"替换 {len(replaced)} 条、新增 {len(appended)} 条断言，标记 {len(fixed_ids)} 条发现为 fixed；"
            f"正文 {artifact.get('body_path') or '（无）'} sha={(artifact.get('body_sha256') or '')[:16]}…"
            f"；下一步：{REVISE_NEXT_STEP}"
        )
        return {
            "doc_id": doc_id,
            "review_rounds": payload["review_rounds"],
            "status": payload["status"],
            "claim_count": len(payload["claims"]),
            "replaced_claim_ids": replaced,
            "appended_claim_ids": appended,
            "fixed_findings": fixed_ids,
            "markdown_path": rel,
            "rendered_path": rendered,
            # ---- 甲（2026-11-11）：这一版「正文」的读数（哪份文件为准见
            # `DT.body_artifact_of`：paper ⇒ out/paper/main.tex；其它 kind ⇒ markdown）。
            # `content_sha256` 仍是"这一版内容"的规范哈希，两者不互相冒充。
            "body_path": artifact.get("body_path") or "",
            "body_sha256": artifact.get("body_sha256") or "",
            "body_bytes": int(artifact.get("body_bytes") or 0),
            "body_problem": artifact.get("body_problem") or "",
            "content_sha256": payload["content_sha256"],
            # ---- 丙（2026-11-11）：改完必须送回 H 复审（G→H 是真边，见 capabilities）。
            # 措辞照 `specs/m.py` 那句，不自造新词。
            "next_step": REVISE_NEXT_STEP,
            # 与 `doc.build_document` 的 `meta.citation_coverage` 是同一份实现的同一份读数
            # （那边走工具结果的 meta，这边是角色方法的返回值）。
            "citation_coverage": coverage,
        }

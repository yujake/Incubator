"""角色 G 的动作 `revise`（`goal-7f5116c1` M6：从 `agent_g.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import Any, DT, DocumentError, Mapping, S, SIG, Sequence

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

        - `review_rounds += 1`、`status = "revised"`、并重渲染 markdown；
        - `new_claims` 里代号已存在的断言会替换原断言（修订），
          新代号则追加。没有这条替换语义，G 就只能"再加一句新话"，
          永远改不掉那句错话 —— 那 `revise` 就修不好任何一条审校发现；
        - `fixed_findings` 里的 finding 只改 `status`/`resolution_note`，
          内容一个字不改（那是 H 的判断依据）。发现不属于本稿 ⇒ 抛错：
          G 不许借"修订"去动别人的稿件上的发现。

        这里标的 `fixed` 不是终局判定：H 的 `verify_fixes` 会重跑检查，
        仍复现就把状态改回 `open`。

        ## 修订同样要核"引用是否真的存在"（此前的缺口）

        `build_document` 有两道闸：`normalize_claims`（`citations` 非空）与
        `check_citations`（引用指向的对象真的在库里）。`revise` 此前只过了
        第一道，于是 `revise(new_claims=[claim citing "lit:9999"])` 会成功写库 ——
        一份用"改写"这条路绕开引用存在性检查的稿件。这比"没有引用"更隐蔽：
        读者看到的是一个像模像样的 `lit:9999`，而库里根本没有这篇文献。

        现在两条路复用同一个 `DT.check_citations`（不另写第二份判据），
        并把它放在同一笔事务里读表，避免"核引用"与"写 documents"看到不同快照。
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

            # 合规闸门：修订后的整份稿子要重过一遍机械检查。
            # 只查"新加的那几条"是不够的 —— 替换语义下，旧的错话可能被换掉，
            # 也可能被换坏，只有全量重查才说得清现在的稿子是否合规。
            try:
                normalized = DT.normalize_claims(merged)
            except ValueError as exc:
                # 2026-10-17（子代理 agents #11）：`normalize_claims` 是**纯函数校验**，抛裸
                # `ValueError` ⇒ 绕过工具层的包装穿出动作，被记成 `failed/执行中异常`，
                # 模型拿不到"哪一条断言、缺什么字段"。翻成 `DocumentError`（在
                # `_BUSINESS_ERROR_NAMES` 里）⇒ 落 `refused/invalid_params`，可自救。
                raise DocumentError(f"修订未通过机械检查：{exc}") from exc

            # 第二道闸：引用存在性。与 `doc.build_document` 复用同一个判据，
            # 理由见本方法 docstring —— 少了它，"修订"就是绕过引用检查的后门。
            # `citing_kind` 必须传（业主义 2026-10-09 的两阶段口径）：正式论文
            # （`kind="paper"`）里不许直接引我方手稿，手稿内容要在正文里重建。
            cites = DT.check_citations(tx.rows, normalized,
                                       citing_kind=str(doc.get("kind") or ""))
            if not cites["checked"]:
                # 理论上不可达（这里必然有 tx）。留着是为了让"没法查"这条状态
                # 有出口，而不是在某次重构里悄悄退化成"当作查过了"。
                raise DocumentError(
                    f"修订 doc:{doc_id} 时无法核对引用是否存在：{cites['reason']} ⇒ 整笔不写库"
                )
            if cites["missing"]:
                bad = "；".join(
                    f"[{m['claim_id']}] {m['citation']!r}：{m['why']}" for m in cites["missing"]
                )
                raise DocumentError(
                    f"修订 doc:{doc_id} 被拒：{len(cites['missing'])} 条引用指向**不存在**的对象，"
                    f"整笔不写库（documents/review_findings 都不动）：{bad}。"
                    "引用一个不存在的代号，等于把外部结论当成自己的结论（FC-02）——"
                    "`normalize_claims` 只看 citations 非空，查不出这一点"
                )

            # 第三道闸：proof 级断言的证据锚（`D-1`）。与 `doc.build_document`
            # 复用同一个 `DT.check_proofs`，理由与上面那条逐字相同 ——
            # 少一道，"修订"就是绕过它的后门。这条不是推演：实测把 `revise` 的
            # 新断言换成一条只引 `lit:`、没有 `proof_location` 的 proof 断言，
            # 它能成功写库（`temp/r2-revise-bypass.txt`，本文件修之前跑出来的）。
            proofs = DT.check_proofs(tx.rows, normalized, workspace_root=self.workspace_root)
            if not proofs["checked"]:
                raise DocumentError(
                    f"修订 doc:{doc_id} 时无法核对 proof 级断言的证据：{proofs['reason']} ⇒ 整笔不写库"
                )
            if proofs["problems"]:
                bad = "；".join(f"[{p['claim_id']}] {p['detail']}" for p in proofs["problems"])
                raise DocumentError(
                    f"修订 doc:{doc_id} 被拒：{len(proofs['problems'])} 条 proof 级断言的证据"
                    f"不成立，整笔不写库（documents/review_findings 都不动）：{bad}。"
                    "`evidence_kind='proof'` 享受最高一档的证据待遇，所以改写这条路"
                    "也必须指向一条真的跑过检查器的实验行、并给出盘上真的存在的落点"
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
            f"替换 {len(replaced)} 条、新增 {len(appended)} 条断言，标记 {len(fixed_ids)} 条发现为 fixed"
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
            # 与 `doc.build_document` 的 `meta.citation_coverage` 是同一份实现的同一份读数
            # （那边走工具结果的 meta，这边是角色方法的返回值）。
            "citation_coverage": coverage,
        }

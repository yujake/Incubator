# -*- coding: utf-8 -*-
"""秘书的命题同一性判定（判不了不许新建/合并，从 secretary.py 的 U21 前半逐字搬出）。

我保证哪条不变式：判不了就不许新建、不许合并；只有判成了的判词才进缓存。

## 为什么它能单独成文件（依赖方向）

`secretary_identity` 只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

（`secretary_identity` 这一份）类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from . import propositionkey as _PK
from . import schema as S
from . import statementledger as SL
from typing import Mapping

from .secretary_axes import (  # noqa: F401 — 这些名字由 secretary_axes 定义
    _proposition_verdict_key,
    append_proposition_verdict,
    proposition_verdict_of,
)

from .secretary_decl import (  # noqa: F401 — 这些名字由 secretary_decl 定义
    PROOF_ROUTES_KEY,
    PROPOSITION_KINDS,
)

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    PROPOSITION_VERDICTS,
)

from .secretary_wash import (  # noqa: F401 — 这些名字由 secretary_wash 定义
    normalize_same_as,
)


PROPOSITION_VERDICT_CANDIDATES = 4

class IdentityMixin:
    """命题同一性判定（判不了不许新建/合并）（从 secretary.py 搬出的混入类）。"""

    @staticmethod
    def _candidate_reading(hits: Sequence[Mapping[str, Any]],
                           limit: int = PROPOSITION_VERDICT_CANDIDATES
                           ) -> list[dict[str, Any]]:
        """一页命中候选 ⇒ 判定的上下文那一份（只留判定要看的格）。

        这一格只是一页的成形器（页大小
        `PROPOSITION_VERDICT_CANDIDATES`）；分页在 `_identity_pages`，问到命中或页尽，
        不再把整批截到前 4 条。
        """
        return [{"stmt_id": str(h.get("stmt_id") or ""),
                 "label": str(h.get("label") or ""),
                 "proof_nos": list(h.get("proof_nos") or []),
                 "statement_full": str(h.get("statement_full") or "")}
                for h in list(hits)[: max(0, int(limit))]]

    def adjudicate_proposition(self, stmt_like: Mapping[str, Any] | str, *,
                               rows: Iterable[Mapping[str, Any]] | None = None,
                               candidates: Sequence[Mapping[str, Any]] | None = None,
                               note: str = "secretary:proposition_identity",
                               use_cache: bool = True,
                               task_id: str = "") -> dict[str, Any]:
        """这一条与在册的哪一条是同一个定理（秘书主动查询 + 一次模型判定，两档，按正文 sha256 缓存）。

        两句准绳：「不用机械判据，让秘书洗定理名，让秘书判」；
        「定理描述一致（什么条件推出什么结论），就是一个定理」。这一问不许有第三种
        结论 —— 读不清就是没判成，不是一种判词。

        所以这一格做三件事、两次模型调用（挑词 + 判定；判定那一趟同时洗名）：
        ⓪ 「秘书自己出查询」：`pick_statement_keywords` 挑数学关键词（一次调用），
           代码按关键词在 `statements` 里检索 active 命题（`label` / `statement_full`
           包含该词，归一按 `textutil`）—— 检索只取候选，「不把全表交给模型过一遍」；
           调用方已经检索好候选（`candidates=`）时跳过这一问（兼容既有写法），
           但走的是同一处判定；
        ① 洗定理名：`Sylow 三定理（路线一：类方程/强归纳 + 共轭作用，自证草稿，待 V 审签）`
           ⇒ `canonical_name = "Sylow 三定理"`，被洗掉的"路线一：…"进 `route`
           （它不丢：落进证明那一层，见 :func:`proof_route_of`）；
        ② 判是不是同一个命题：读条件与结论，只给 same / different，
           判 same 时点名并进哪一条（`same_as`）。

        ## 检索读数（"它确实查过"必须看得见）
        `keywords` / `hits_total`（命中几条）/ `hits_named`（这一趟交给模型看的全部候选，
        带每条命中的词）/ `judged`（判定那一趟发没发）/ `same_as` / `why`。
        分页读数（缺陷 ②）：`candidates_total`（候选总数）/ `pages_total`（要问几页）/
        `pages_judged`（真问了几页）/ `candidates_seen`（已经入眼几条）/
        `page_exhausted`（问完了还没命中）。候选按 `PROPOSITION_VERDICT_CANDIDATES`
        分页，问到命中或页尽；改前只把前 4 条交给模型，第 5–N 条永不入眼却被记成
        "这批都不是"。
        台账里 0 条可检索命题、或关键词 0 命中 ⇒ `checked=True` + `verdict="different"`
        （查过、没有同一条；0 命中仍发判定那一趟洗定理名，读数里 `candidates_total=0`、
        `page_exhausted=True`）；关键词没提取成 / 台账读不成 ⇒ `checked=False`（没判成，
        上层 fail-closed；这一档不许退回"拿全表或相似度候选去猜"）。

        ## 两档与依据（返回）
        | 结局 | 返回 |
        |---|---|
        | 判同一 | `checked=True` + `verdict="same"` + `same_as=<stmt_id>` + `canonical_name` |
        | 判不同 | `checked=True` + `verdict="different"`（不并，新建） |
        | 没判成 | `checked=False` + `verdict=""` + `reason`（没缝 / 开关关着 / 超时 / 坏 JSON / 词表外结论 / same 点不出号） |

        没有第三种结论词。`basis` 是那一趟的判词（条件一句 + 结论一句 + 一句理由）；
        `same` 而 `same_as` 指不出一个候选号 ⇒ 没判成（`checked=False`，不并也不新建）：
        凭一个指不出来的号合并，等于替它编一条依据（与"模型给的结论不在词表里就不采信"
        同一条纪律）。这一档以前会降成第三种结论再照旧新建一行 —— 那正是"既在账上又不在
        账上"的形态，2026-11-08 起不许再出现。

        ## 为什么按正文 sha256 缓存（`out/secretary/proposition_verdicts.jsonl`）
        判定的对象是那段正文；同一条正文换个标签、重试、换个人再交一次，结论不会有别的
        答案，而每一次都要真发一次调用。真机 sylow4 的形态正好是"同一条定理交了三遍"——
        没有这一层就是三笔钱买同一句话。只缓存判成了的两档（`checked=True`）：没判成不许
        缓存，那会把"这一次没判成"变成"以后都别查了"。缓存行也带检索读数，于是"沿用
        那一次判定"时同样读得出它当年查过什么。
        `reused=True` + `cost.reason="没发调用（沿用缓存）"` 是"这一趟没花钱"的唯一读数。
        """
        if isinstance(stmt_like, str):
            stmt_like = {"statement_full": stmt_like}
        full = str(stmt_like.get("statement_full") or "")
        label = str(stmt_like.get("label") or "")
        kind = str(stmt_like.get("kind") or "theorem")
        out: dict[str, Any] = self._identity_out(label=label, kind=kind)
        if not _is_proposition_kind(kind):
            out["reason"] = (f"kind={kind!r} 不在命题性的那几档 {list(PROPOSITION_KINDS)} 里 "
                             "⇒ 不是命题，不参与同一性判定（也不洗它的名字）")
            return self._with_adjudication_visibility(out)
        if not full.strip():
            out["reason"] = "命题正文是空的 ⇒ 没有可判的东西（不洗名、不并）"
            return self._with_adjudication_visibility(out)
        key = _proposition_verdict_key(full)
        out["statement_sha256"] = key
        # `use_cache=False` 是"候选逐页给"那一档（调用方手里已经有候选）：按正文 sha
        # 缓存会把"这一页没查到"沿用到下一页。
        cached = ((self._proposition_verdicts.get(key)
                   or proposition_verdict_of(self.root, full)) if use_cache else {})
        cached_verdict = str((cached or {}).get("verdict") or "")
        cached_same_as, _cached_n = normalize_same_as((cached or {}).get("same_as"))
        # 只认判成了的两档：判 same 的还必须点得出号（否则那一行也不是一次判定）。
        # 历史行（2026-11-08 之前）里可能有旧的第三种结论词 —— 它不许当缓存用：
        # 那会把"那一次没判成"沿用到今天，而这一趟本来可以重新判（判据 c）。
        if (cached and cached_verdict in PROPOSITION_VERDICTS
                and (cached_verdict != _PK.STATE_SAME or bool(cached_same_as))):
            # 缓存里的坏值也要按同一把尺归一化：本趟 `proposition_verdicts.jsonl` 的
            # 第 6-9 行就是 `"['000001']"` 这一族，而同一段正文重交时读的正是它
            # （"判过一次就复用"这条纪律会让坏值一直活着）。只归一化外形，
            # 不重判 verdict —— 判词是那一趟的读数，改它等于替那一趟翻案。
            out.update(
                checked=True,
                verdict=cached_verdict,
                canonical_name=str(cached.get("canonical_name") or ""),
                same_as=cached_same_as,
                route=str(cached.get("route") or ""),
                condition=str(cached.get("condition") or ""),
                conclusion=str(cached.get("conclusion") or ""),
                basis=str(cached.get("basis") or ""),
                reused=True, cached=True,
                cached_at=str(cached.get("at") or ""),
                cached_label=str(cached.get("label") or ""),
                cost={"ledger": "", "reason": "没发调用（沿用缓存：同一段正文判过一遍）"},
                # 检索读数照旧摆出来（缓存行里存着那一次查过什么）；候选表不重算 ——
                # 重算要再花一次挑词调用，而这一次的处置不取决于候选还在不在。
                keywords=[str(x) for x in (cached.get("keywords") or ())],
                hits_total=int(cached.get("hits_total") or 0),
                hits_named=[dict(x) if isinstance(x, Mapping) else {"stmt_id": str(x)}
                            for x in (cached.get("hits_named") or ())],
                judged=bool(cached.get("judged")),
                why=str(cached.get("why") or ""),
                keyword_checked=bool(cached.get("keyword_checked")),
                candidates_total=int(cached.get("candidates_total") or 0),
                pages_total=int(cached.get("pages_total") or 0),
                pages_judged=int(cached.get("pages_judged") or 0),
                candidates_seen=int(cached.get("candidates_seen") or 0),
                page_exhausted=bool(cached.get("page_exhausted")),
                candidates=[])
            return self._with_adjudication_visibility(out)
        if cached:
            out["cache_ignored"] = (
                f"台账里那一行判词 {cached_verdict!r} 不是两档里的一次判定"
                "（历史行：旧的第三种结论词，或判 same 却没点名候选号）⇒ 不当缓存用，"
                "这一趟重新判")
        # ---- 取候选：默认路径 = 秘书自己查（业主 2026-11-08：「应该是主动查询」）------
        #
        # 两档来源，处置不同：
        # - `candidates=` 给了：调用方已经检索好（兼容既有写法），这一趟不自己查；
        # - 没给：秘书自己挑关键词、自己在台账里检索。关键词那一问没成 ⇒ 没判成
        #   （fail-closed），「不许」退回"拿全表/相似度候选去猜"。
        #
        # 没有候选（台账 0 条 / 关键词 0 命中）时「仍然发判定那一趟」：洗定理名
        # （`canonical_name` / `route`）与判定是同一趟的输出，跳过它就会让"第一条命题
        # 的 label 原样落盘"—— 那正是洗名要治的形态。这一档只省掉挑词那一问。
        if self._identity_candidates(out, candidates=candidates, rows=rows,
                                     full=full, label=label, kind=kind,
                                     task_id=task_id):
            return self._with_adjudication_visibility(out)
        if self._judge_identity_pages(out, full=full, label=label, kind=kind,
                                      note=note, task_id=task_id):
            return self._with_adjudication_visibility(out)
        if not out["checked"]:     # 防御：只有判成了的两档才许进缓存
            return self._with_adjudication_visibility(out)
        if use_cache:
            self._remember_proposition_verdict(out, full=full, label=label,
                                               task_id=task_id)
        return self._with_adjudication_visibility(out)

    def _judge_identity_pages(self, out: dict[str, Any], *, full: str,
                              label: str, kind: str, note: str,
                              task_id: str) -> bool:
        """按页判同一性（问到命中或页尽）；返回 True = 调用方应直接回读数。

        2026-11-08 缺陷 ② 的实现从 `adjudicate_proposition` 拆出（只搬移）：分页、
        命中收口、成员校验三段合起来 90 余行；拆出来之后那一格回到 200 行以内 ——
        体量基线是读数，不许为了它抬（业主口径：拆函数，不抬基线）。

        三件事与改前逐字同序：① 每页发一次判定（`judge`）；② 判 same 就在那一页
        校验 `same_as` 是页内候选号（指不出号 ⇒ 没判成）；③ 判 different 继续下一页，
        页尽时 `page_exhausted=True`。
        """
        candidates_page = list(out["candidates"])
        pages = self._identity_pages(candidates_page)
        # ---- 检索读数（2026-11-08 缺陷 ②）：候选总数 / 页数 / 实际问了几页 / 是否页尽 ----
        #
        # 改前这里只把前 4 条交给模型（`_candidate_reading` 截断），而 `hits_total`
        # 照旧报全量 ⇒ "第 5–20 条永不入眼"与"20 条都看过"在读数上同形。现在按
        # `PROPOSITION_VERDICT_CANDIDATES` 分页，问到命中或页尽为止，并把三件事写进
        # 读数：`pages_total` / `pages_judged` / `page_exhausted`（外加
        # `candidates_total` / `candidates_seen`）。
        out["candidates_total"] = len(candidates_page)
        out["pages_total"] = len(pages)
        out["pages_judged"] = 0
        out["candidates_seen"] = 0
        out["page_exhausted"] = False
        out["judged"] = False
        seen: list[str] = []
        parts: list[str] = []
        page_ids: list[str] = []
        for index, page in enumerate(pages, 1):
            context = self._identity_context(
                full=full, label=label, kind=kind, candidates=page)
            got = self.judge("proposition_identity", context, task_id=task_id,
                             note=note)
            out["judged"] = True
            out["pages_judged"] = index
            page_ids = [str(c.get("stmt_id") or "") for c in page]
            seen.extend(page_ids)
            out["candidates_seen"] = len(seen)
            out["cost"] = dict(got.get("cost") or out.get("cost") or {})
            out["judged_elapsed_sec"] = got.get("elapsed_sec")
            if not got.get("checked"):
                out["checked"] = False
                out["reason"] = str(got.get("reason") or "这一格没查成（原因不明）")
                return True
            verdict = str(got.get("decision") or "")
            if verdict not in PROPOSITION_VERDICTS:
                # `judge()` 已经按词表挡了一层；这里再挡一层是防"别的类别借这一格"：
                # 词表外的结论不是一种判定 ⇒ 没判成（不新建、不合并）。
                out.update(checked=False, verdict="",
                           reason=(f"模型给的结论 {verdict!r} 不在两档 "
                                   f"{list(PROPOSITION_VERDICTS)} 里 ⇒ 不采信：这一格没判成"))
                return True
            # 洗定理名与判同一趟（每一页的判词都带 `canonical_name` / `route`）：
            # 取"判成的那一页"—— 判 same 就在那一页收口，判 different 一直问到页尽。
            out["canonical_name"] = str(got.get("canonical_name") or "").strip()
            out["route"] = str(got.get("route") or "").strip()
            out["condition"] = str(got.get("condition") or "").strip()
            out["conclusion"] = str(got.get("conclusion") or "").strip()
            out["reason"] = str(got.get("reason") or "")
            parts = [str(x).strip() for x in (got.get("basis") or []) if str(x).strip()]
            out["basis"] = "；".join(parts + ([out["reason"]] if out["reason"] else []))
            out["checked"] = True
            out["verdict"] = verdict
            out["same_as"] = str(got.get("same_as") or "").strip()
            if verdict == _PK.STATE_SAME:
                ids = page_ids
                # ---- 先归一化外壳，再判成员（真机 82，2026-11-01）
                #
                # 现场：模型判 same 时把号写成 `"['000003']"`（52 处 / 16 个会话行），
                # 而下面这条成员判据逐字比 ⇒ 判了 same 也不并、照旧落新行
                # （重复对 000001/000004、000003/000005 就是这么来的）。
                # 纪律不改：归一化后仍指不出候选号 ⇒ 没判成（2026-11-08 起不再降成
                # 第三种结论）："凭一个指不出来的号合并，等于替它编一条依据"这句话仍然成立；
                # 多元素列表也不猜，只说清"你给了 N 个号"。
                raw_same_as = str(out["same_as"] or "")
                normalized, how_many = normalize_same_as(raw_same_as)
                out["same_as"] = normalized
                if not normalized:
                    if how_many > 1:
                        why = (f"模型判 same，但 same_as 给了 {how_many} 个号"
                               f"（收到 {raw_same_as!r}）⇒ 不猜：并进哪一条是它的判断，"
                               f"框架替它挑一个等于替它表态；要并请只点一个号"
                               f"（候选 {ids or '空'}）")
                    else:
                        why = (f"模型判 same，但 same_as 没给出可用的号"
                               f"（收到 {raw_same_as!r}）⇒ 没判成：指不出候选号的合并等于"
                               f"替它编一条依据（候选 {ids or '空'}）")
                    out.update(checked=False, verdict="", same_as="", reason=why,
                               basis="；".join(parts + [why]))
                    return True
                if normalized not in ids:
                    why = (f"模型判 same，但 same_as={normalized!r}（原文 {raw_same_as!r}）"
                           f" 不是候选表里的号（候选 {ids or '空'}）⇒ 没判成：凭一个指不出来的"
                           "号合并，等于替它编一条依据")
                    out.update(checked=False, verdict="", same_as="", reason=why,
                               basis="；".join(parts + [why]))
                    return True
                break
            # different：还有下一页就接着问；页尽就由下面那一格收口。
        out["page_exhausted"] = bool(out["verdict"] == _PK.STATE_DIFFERENT
                                     and out["pages_judged"] >= out["pages_total"])
        return False

    def _identity_context(self, *, full: str, label: str, kind: str,
                          candidates: list[dict[str, Any]]) -> dict[str, Any]:
        """判定那一趟的材料（只搬移：字面量逐字相同）。

        2026-11-08 从 `adjudicate_proposition` 拆出（体量基线是读数，不许为了它抬）。
        """
        return {
        # 这一条给三倍于候选的篇幅：它是要被判的那一条，缺了一半就没法判。
        "statement_full": full[: PROPOSITION_VERDICT_TEXT_CHARS * 3],
        "label": label,
        "kind": kind,
        "candidates": self._candidate_reading(candidates),
        "how_to_judge": ("只比条件与结论；条件强弱不同 ⇒ different；"
                         "条件只是记号/等价改写 ⇒ same；"
                         "候选表为空 ⇒ different（没有可并的对象）；"
                         "读不清就不给判词（不许猜，也不许给第三档）"),
    }

    def _identity_out(self, *, label: str, kind: str) -> dict[str, Any]:
        """这一趟的初值读数（键无条件存在：没判成由 `checked` 说，不靠少给键）。

        2026-11-08 从 `adjudicate_proposition` 拆出（只搬移，字面量逐字相同）：那一格 30 余行，
        拆出来之后 `adjudicate_proposition` 回到 200 行以内 —— 体量基线是读数，不许为了它抬。
        """
        out: dict[str, Any] = {
            #: 判词只有两档（`PROPOSITION_VERDICTS`）；空串 = 这一趟没判成（没有判词）。
            "checked": False, "verdict": "", "canonical_name": "",
            "same_as": "", "route": "", "condition": "", "conclusion": "",
            "basis": "", "reason": "", "label": label, "kind": kind,
            "candidates": [], "cost": {"ledger": "", "reason": "没发调用（还没判）"},
            "reused": False, "cached": False, "statement_sha256": "",
            #: 检索读数（2026-11-08 主动查询）：关键词 / 命中几条 / 实际交给模型看的是
            #: 哪几条（带每条命中的词）/ 判定那一趟发没发 / 一句话为什么。
            "keywords": [], "hits_total": 0, "hits_named": [], "judged": False,
            "why": "",
            #: 分页读数（2026-11-08 缺陷 ②）：候选总数 / 总页数 / 真问了几页 /
            #: 已经看过几个候选 / 是否页尽。"只看了 4 条就说都不是"与"20 条都看过"
            #: 必须在这一组数上分得开。
            "keyword_checked": False, "candidates_total": 0,
            "pages_total": 0, "pages_judged": 0, "candidates_seen": 0,
            "page_exhausted": False,
            #: 这一条判定用的是哪一条缝（`Secretary.model_source` 的三档读数：
            #: `body（…）` / `secretary（…）` / `none（…）`）。空串 = 这一名秘书是裸造的
            #: （`Secretary(...)` 没传 `seam=`），那一档就是"没有判断面"。
            #:
            #: 为什么把它放进返回值（2026-10-26 真机 sylow5）：`judge()` 那句"没有装配
            #: 模型缝"只在 `Secretary.judge` 的局部返回值里，调用方（B 的工具返回、直写
            #: 路由的 detail）看不到"缝为什么没有" —— 而 sylow5 的根因恰恰是装配处漏了
            #: 一根线，不是判据坏了。缝的来源与"判了没有"必须同时在读数上。
            "seam_source": str(self.model_source or ""),
            #: 这一格到底有没有"试过"：有缝且开关开着才是试过。
            #:
            #: 它与 `checked` 是两根轴：`attempted=False` 是"这一名秘书根本没有判同一性
            #: 这一路"（没缝），`attempted=True` + `checked=False` 是"试了、没判成"
            #: （超时 / 坏 JSON / same 点不出号 / 词表外结论）。「上层 fail-closed 的判据是
            #: 这两根轴的交集」：试过而没判成 ⇒ 不新建、不合并、受控拒（见
            #: `_merge_into_proposition`）。没有判断面的秘书走 2026-11-04 的确定性兜底
            #: （只认确定性键相同），盘上要不要留痕也由这一格决定 —— 没有缝的秘书写出来的
            #: 行必须与改前逐字节相同（否则"这一段正文之前长什么样"被一个从来没发生过的
            #: 判定改写了）。
            "attempted": bool(self.seam is not None and self.enable_model),
        }
        return out

    @staticmethod
    def _identity_pages(candidates: Sequence[Mapping[str, Any]],
                        page_size: int = PROPOSITION_VERDICT_CANDIDATES
                        ) -> list[list[dict[str, Any]]]:
        """候选表 ⇒ 判定分页（问到命中或页尽；不是截断到第一页）。

        2026-11-08 缺陷 ②：改前 `_candidate_reading` 把命中截到前 4 条，第 5–N 条
        永不入眼却记成"这批都不是"。这一格是那条纪律的唯一实现：候选按页切开，
        调用方逐页问；空候选也要给一页（洗定理名与判定是同一趟的输出）。

        独立成函数是为了留一个可打桩的判据点：反真空把这里换成"只给第一页"，
        `tests/test_one_retrieval_path_pages_until_hit_or_end.py` 必须当场红。
        """
        size = max(1, int(page_size))
        items = [dict(c) for c in (candidates or ()) if isinstance(c, Mapping)]
        return ([items[i:i + size] for i in range(0, len(items), size)] or [[]])

    @staticmethod
    def _named_hits(items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """命中 / 候选的对外读数：`stmt_id` + `hit_words` 两格，逐条。

        「调用方给的候选」与「自己检索到的命中」两条来路给的是同一份形状，
        原先两处各写一遍同一段推导 —— 这里合并成一处，形状只有一份。
        """
        return [{"stmt_id": str(h.get("stmt_id") or ""),
                 "hit_words": [str(x) for x in (h.get("hit_words") or ())]}
                for h in items]

    def _identity_candidates(self, out: dict[str, Any], *,
                             candidates: Sequence[Mapping[str, Any]] | None,
                             rows: Iterable[Mapping[str, Any]] | None,
                             full: str, label: str, kind: str, task_id: str) -> bool:
        """取这一趟的候选表；返回 True = 这一趟到此为止（调用方直接回读数）。

        2026-11-08 从 `adjudicate_proposition` 拆出（只搬移，块内逐字相同）：「调用方给了候选」
        与「秘书自己挑词检索」是同一格的两条来路，合起来 50 余行；拆开之后 `adjudicate_proposition`
        回到 200 行以内 —— 体量基线是读数，不许为了它抬（业主口径：拆函数，不抬基线）。
        """
        if candidates is not None:
            supplied = [dict(c) for c in candidates
                        if isinstance(c, Mapping) and str(c.get("stmt_id") or "").strip()]
            for item in supplied:
                item.setdefault("hit_words", [])
                item.setdefault("proof_nos", [])
                item["statement_full"] = str(item.get("statement_full") or "")[
                    :PROPOSITION_VERDICT_TEXT_CHARS]
            out.update(
                keywords=[], hits_total=len(supplied),
                # 读了哪几条 = 全部（分页之后每页都会看到；这里不再截到一页）。
                hits_named=self._named_hits(supplied),
                candidates=list(supplied),
                candidates_total=len(supplied),
                why=("调用方给了候选表 ⇒ 这一趟不再自己检索" if supplied
                     else "调用方给的候选表为空 ⇒ 没有可比的条目（查过 0 条）"))
            if not supplied:
                # 兼容档：调用方已经查过一圈且明确给了空表 ⇒ 不再花一次调用（旧入口的语义）。
                out.update(checked=True, verdict=_PK.STATE_DIFFERENT, judged=False,
                           pages_total=0, pages_judged=0, candidates_seen=0,
                           page_exhausted=True,
                           reason="查过：调用方给的候选表为空（0 条）⇒ 没有同一条",
                           basis="查过：没有可比的候选 ⇒ 不同")
                self._remember_proposition_verdict(out, full=full, label=label,
                                                   task_id=task_id)
                return True
        else:
            # 检索的两件事各归一处：池过滤（`pool`）与关键词匹配（`by_keywords`）都在
            # `statementledger`；本层只负责「挑词 → 问查口」，不重写任何过滤。
            pool_rows, pool_problem = self._ledger_pool(rows)
            if pool_problem:
                out.update(checked=False, verdict="", reason=pool_problem,
                           why=pool_problem)
                return True
            if not pool_rows:
                out["why"] = ("台账里没有可检索的 active 命题（读过了，0 条）"
                              "⇒ 没有候选，判定直接判 different")
            else:
                kw = self.pick_statement_keywords(statement_full=full, label=label,
                                                  kind=kind, task_id=task_id)
                # 三格取自同一份 `kw`：checked / why 各读一次（原先 why 读两遍）。
                kw_checked = bool(kw.get("checked"))
                kw_why = str(kw.get("why") or "")
                out["keywords"] = [str(x) for x in (kw.get("keywords") or ())]
                out["keyword_checked"] = kw_checked
                out["why"] = kw_why
                if not kw_checked:
                    out.update(
                        checked=False, verdict="",
                        reason=("关键词没提取成 ⇒ 这一问没判成（不新建、不合并、受控拒）："
                                + (kw_why or "（没有给原因）")))
                    return True
                search = SL.by_keywords(rows=pool_rows, keywords=out["keywords"],
                                        text_chars=PROPOSITION_VERDICT_TEXT_CHARS)
                if not search.get("checked"):
                    out.update(checked=False, verdict="",
                               reason=str(search.get("reason")
                                          or "检索没查成 ⇒ 这一问没判成"),
                               why=str(search.get("why") or ""))
                    return True
                hits = list(search.get("hits") or [])
                out["hits_total"] = len(hits)
                # 读了哪几条 = 全部命中（分页之后每页都会看到；不再是"前 4 条"）。
                out["hits_named"] = self._named_hits(hits)
                out["candidates_total"] = len(hits)
                out["candidates"] = hits
                if not hits:
                    out["why"] = str(search.get("why") or "")
        return False

    def _ledger_pool(self, rows: Iterable[Mapping[str, Any]] | None = None
                     ) -> tuple[list[dict[str, Any]], str]:
        """本层要的那一批：可检索 / 可并的 active 命题（口径由 `statementledger.pool` 定）。

        2026-11-09 之前这里叫 `_searchable_statement_rows`，过滤三条与
        `_same_proposition_candidate` 逐字同源；现在两者都问 `statementledger.pool`。
        「这一层要哪一批」是语义决定（命题池），所以池的 kind 名单仍由这里给 ——
        名单的唯一来源是 `PROPOSITION_KINDS`，箱子里不复制它。
        """
        got, problem, _error = SL.rows_of(self.store, rows=rows)
        if problem:
            return [], problem
        return SL.pool(got or (), kinds=PROPOSITION_KINDS), ""

    def _remember_proposition_verdict(self, out: dict[str, Any], *, full: str,
                                      label: str = "", task_id: str = "") -> None:
        """把判成了的这一条落进缓存（写不成只留读数，不改这一趟的结论）。

        只该在 `out["checked"]` 为真时调用：没判成的不许缓存 —— 那会把"这一次没判成"
        变成"以后都别查了"，而缝是可能好起来的（与 `_statement_verdicts` 同一条纪律）。
        """
        if not out.get("checked"):
            return
        try:
            row = append_proposition_verdict(
                self.root, statement_full=full, verdict=str(out.get("verdict") or ""),
                canonical_name=str(out.get("canonical_name") or ""),
                same_as=str(out.get("same_as") or ""),
                route=str(out.get("route") or ""), label=label,
                condition=str(out.get("condition") or ""),
                conclusion=str(out.get("conclusion") or ""),
                basis=str(out.get("basis") or ""),
                keywords=[str(x) for x in (out.get("keywords") or ())],
                hits_total=int(out.get("hits_total") or 0),
                hits_named=list(out.get("hits_named") or ()),
                judged=bool(out.get("judged")), why=str(out.get("why") or ""),
                keyword_checked=bool(out.get("keyword_checked")),
                candidates_total=int(out.get("candidates_total") or 0),
                pages_total=int(out.get("pages_total") or 0),
                pages_judged=int(out.get("pages_judged") or 0),
                candidates_seen=int(out.get("candidates_seen") or 0),
                page_exhausted=bool(out.get("page_exhausted")),
                seam_source=str(out.get("seam_source") or ""),
                role=str(self.role or ""), task_id=str(task_id or self.task_id or ""))
            self._proposition_verdicts[_proposition_verdict_key(full)] = dict(row)
            out["cached"] = True
            out["cached_at"] = str(row.get("at") or "")
        except OSError as exc:
            # 缓存写不成不影响这一趟的结论（结论已经在返回值里），但必须说出来：
            # 写不成意味着下一趟还要再花一次钱。
            out["cache_problem"] = f"{type(exc).__name__}: {exc}"
            self._log(f"命题判定台账没写成：{out['cache_problem']}")

    @staticmethod
    def _with_adjudication_visibility(adj: Mapping[str, Any]) -> dict[str, Any]:
        """把"判了没有"那一格挂到判定返回值上（键名 `proposition_adjudication`）。

        ## 它为什么必须存在（真机 sylow5，2026-10-26）

        改前这一格只活在 `checked` / `reason` 两个平铺的键里，而它们旁边紧挨着
        `verdict` / `canonical_name` / `basis` 那一组判词 —— 读的人（尤其是模型，
        它只看工具返回的那一份 JSON）很容易把它们读成"判过了，结论是某一档"。
        真机 sylow5 的后果就是：`out/secretary/proposition_verdicts.jsonl` 一次都没
        建出来，而会话里没有任何一格说"这一条判定根本没发生"。

        所以这里把三件事收进同一格、显式命名：
        - `checked`：判成了没有（`False` 不是说"不同"，是"没判"）；
        - `attempted`：有没有真的去判（没缝 ⇒ `False`，试了没成 ⇒ `True`）；
        - `seam_source`：这一条判定用的哪条缝（`none（…）` 就是没接线）。

        检索读数（`keywords` / `hits_total` / `hits_named` / `judged`）也在这一格里：
        "它确实自己查过一圈"必须与"判了没有"同时看得见（2026-11-08 业主：
        「语义判定当前实现是秘书主动查询还是必须全过一遍？应该是主动查询」）。

        ## 为什么挂在这里而不是每个 `return` 自己写

        :meth:`adjudicate_proposition` 有五条返回路径（不是命题 / 正文空 / 沿用缓存 /
        没查成 / 判了）。让每条路径各写一次，等于把"这一格在不在"交给五处自觉 ——
        而本仓最贵的那一类缺陷正是"某一条返回路径少写一格"。所以只留一个出口。
        """
        out = dict(adj)
        out["proposition_adjudication"] = {
            "checked": bool(out.get("checked")),
            "attempted": bool(out.get("attempted")),
            "verdict": str(out.get("verdict") or ""),
            "reason": str(out.get("reason") or ""),
            "seam_source": str(out.get("seam_source") or ""),
            "reused": bool(out.get("reused")),
            "keywords": [str(x) for x in (out.get("keywords") or ())],
            "hits_total": int(out.get("hits_total") or 0),
            "hits_named": [dict(x) if isinstance(x, Mapping) else {"stmt_id": str(x)}
                           for x in (out.get("hits_named") or ())],
            "judged": bool(out.get("judged")),
            "same_as": str(out.get("same_as") or ""),
            "why": str(out.get("why") or ""),
            #: 分页读数（2026-11-08 缺陷 ②）：看了几页 / 几个候选 / 是否页尽。
            "keyword_checked": bool(out.get("keyword_checked")),
            "candidates_total": int(out.get("candidates_total") or 0),
            "pages_total": int(out.get("pages_total") or 0),
            "pages_judged": int(out.get("pages_judged") or 0),
            "candidates_seen": int(out.get("candidates_seen") or 0),
            "page_exhausted": bool(out.get("page_exhausted")),
        }
        return out

    @staticmethod
    def _annotate_proposition(row: dict[str, Any], adj: Mapping[str, Any], *,
                              proof_no: int = 1, route: str = "") -> dict[str, Any]:
        """把"这一次判定"与"这条路子"落到命题行上（只加读数键，不动 schema）。

        ## 两格，各管一件事
        - `PROOF_ROUTES_KEY` 那一格 = {证明号: 一句话}：这条路线的说明。业主 2026-10-24：
          「路线写在证明这一层」—— 它从此不住在 label 里，也不再丢（洗名不是丢信息）。
        - `_proposition_adjudication = {verdict, basis, ...}`：这一条是凭哪一次判定落成
          现在这样的。判 different 的也要落：只落 same 的记录，读的人就分不出
          "判过了、不同"与"没人判过"（没判成是 `checked=False`，与"判过了"必须分得开）。
        这两个键都不在 `schema.Statement` 里 —— store 落的是 JSON 行，`row_from_dict` 只取
        它认识的键（与命题并表痕迹 / `proof_history` 同一做法），所以不必动 schema。
        """
        out = dict(row)
        if str(route or "").strip():
            routes = dict(out.get(PROOF_ROUTES_KEY) or {})
            routes[str(int(proof_no or 1) or 1)] = str(route).strip()
            out[PROOF_ROUTES_KEY] = routes
        if adj and (adj.get("checked") or adj.get("attempted")):
            out["_proposition_adjudication"] = {
                "checked": bool(adj.get("checked")),
                "attempted": bool(adj.get("attempted")),
                "verdict": str(adj.get("verdict") or ""),
                "canonical_name": str(adj.get("canonical_name") or ""),
                "same_as": str(adj.get("same_as") or ""),
                "basis": str(adj.get("basis") or ""),
                "reason": str(adj.get("reason") or ""),
                "reused": bool(adj.get("reused")),
                # 这一条判定用的是哪条缝（2026-11-08，①）：`body（…）` / `secretary（…）` /
                # `none（…）` / 空串（裸造）。收工读数按它数 `seam_source` 分布 ——
                # "整条判定链是死的"（sylow5）必须在盘上读得出来，不能只在返回值里。
                "seam_source": str(adj.get("seam_source") or ""),
                "seam_attempted": bool(adj.get("attempted")),
                "at": S.now_iso(),
            }
        return out


#: 一次判定一页给几条候选（分页的页大小，不是截断）。
#:
#: 候选是秘书自己按关键词在台账里检索出来的命中项（查口的 `by_keywords`，
#: 唯一实现在 `statementledger`）；
#: 命中多于这个数时按页依次交给模型，问到命中或页尽为止（只把前 4 条交给模型会让
#: 第 5–N 条永不入眼，却被记成"这批都不是"）。
#: `pages_total` / `pages_judged` / `page_exhausted` / `candidates_total` 四个读数
#: 把"看了几页 / 几个候选 / 是不是页尽"与判词一起摆出来。
#: 为什么一页是 4：一次判定要在提示词里同时放下这一条的正文与每条候选的正文/定理名；
#: 候选越多，每条能分到的字数越少 —— 而对"条件与结论是否一致"这件事，半条命题没有用。


#: 一次判定里这一条正文最多看多少字符（每条候选各自也有同样的上限）。
PROPOSITION_VERDICT_TEXT_CHARS = 1200


def _is_proposition_kind(kind: Any) -> bool:
    """这个 kind 算不算"命题性的"（决定它参不参与同一命题判定）。"""
    return str(kind or "").strip().lower() in PROPOSITION_KINDS


def _proposition_judgment_missing(kind: Any, adj: Mapping[str, Any]) -> str:
    """这一次同一性判定能不能支撑"新建 / 合并"（返回非空 = 不能，值是为什么）。

    ## 判据（业主 2026-11-08：「没有判不了」）
    三条，顺序固定：
    1. 不是命题性的 kind ⇒ 不适用（返回空串：概念那一档走 `same_concept`，不走这一问）；
    2. 试过而没判成（`attempted=True` + `checked=False`：超时 / 坏 JSON / 词表外结论 /
       same 点不出号 / 没有检索面）⇒ 受控拒：不新建、不合并。"没判成"不等于"不是同一条"，
       拿它当 different 去新建一行，就是"既在账上又不在账上"的那种重复；
    3. 判成了、但判词不在两档里 ⇒ 同上（防御：`judge()` 已经挡了一层）。

    `attempted=False`（没缝 / 开关关着）并不在这里拒：那一档是"这一名秘书根本没有
    判同一性这一路"，沿用 2026-11-04 的确定性兜底（只认确定性键相同）—— 把"没有判断面"
    与"判定失败"折成同一档，会让裸装的测试工作区一笔都写不进去，而归因还指不到缝上。
    """
    if not _is_proposition_kind(kind):
        return ""
    if not adj.get("checked"):
        if not adj.get("attempted"):
            return ""
        return ("这一条要查「是不是在册的同一条命题」，而这一问没判成 ⇒ 受控拒："
                "不新建、不合并（没判成不等于「不是同一条」）："
                + (str(adj.get("reason") or "") or "（没有给原因）"))
    if str(adj.get("verdict") or "") not in PROPOSITION_VERDICTS:
        return (f"这一次判定的判词 {str(adj.get('verdict') or '')!r} 不在两档 "
                f"{list(PROPOSITION_VERDICTS)} 里 ⇒ 受控拒：不新建、不合并")
    return ""

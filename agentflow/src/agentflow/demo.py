"""离线端到端演示：不访问网络，把 A→B→校验整条链路真跑一遍。

为什么值得单独做一个 demo，而不是只在测试里断言：
- 单元测试证明"每块零件对"，但证明不了它们拼起来还能跑（接口错配、字段名不一致、
  锁顺序搞错，这类问题只在集成时暴露）。
- demo 用的是真实文件、真实表、真实事务，只有"搜索"和"下载"两步被替换成 fixture。
  这样"端到端可跑"这句话才有内容。

演示会刻意制造三件事，用来检验设计里最容易写错的地方：
1. 重复文献：两个候选标题相同 → 检验文献去重没有新建第二行。
2. 重复关系：两篇文献给出同一句原文 → 检验关系判重拒绝写入。
3. 幂等重跑：A 再跑一次 → 检验不会产生重复文献。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from . import conceptrows as _CR
from . import dedup as D
from . import litstage as L
from . import schema as S
from .agent_a import AgentA
from .agent_b import AgentB
from .canonical import json_default
from .store import Store
from .verify import verify_all

# ---------------------------------------------------------------- 演示素材

DOCS: dict[str, list[str]] = {
    # 每篇文档按"页"给出；txt 素材会被合成一个文件，页数记为 1。
    "group.txt": [
        "A group is a set together with a binary operation that is associative, "
        "in which there is an identity element and every element has an inverse."
    ],
    "abelian_group.txt": [
        "An abelian group is a group in which the commutative law holds for every "
        "pair of elements."
    ],
    "ring.txt": [
        "A ring is an algebraic structure equipped with two binary operations, "
        "usually called addition and multiplication."
    ],
    "field.txt": [
        "A field is a ring in which every nonzero element has a multiplicative inverse."
    ],
    # 与 abelian_group.txt 内容完全相同 —— 用来触发"关系判重"
    "abelian_group_reprint.txt": [
        "An abelian group is a group in which the commutative law holds for every "
        "pair of elements."
    ],
}


def _candidate(
    title: str,
    fname: str,
    *,
    year: int,
    doi: str | None,
    venue: str,
    type_code: str = "J",
    summary: str = "",
) -> dict:
    """构造一条 fixture 候选。

    `pdf_url` 用自定义 `abfixture:` 方案指向本地素材 —— 由 `FixtureDownloader` 解析。
    这样"下载"这一步的代码路径与真实运行时完全一致（同样要落盘、算 sha256、
    写 download 状态），只是字节来源换成了本地文件。
    """
    return {
        "title": title,
        "year": year,
        "doi": doi,
        "authors": ["A. Author"],
        "venue": venue,
        "type_code": type_code,
        "summary": summary or f"离线演示素材：{title}",
        "pdf_url": f"abfixture:{fname}",
        "landing_url": None,
        "language": "en",
        "provider": "fixture",
        "path": fname,
    }


def build_fixtures(root: Path) -> Path:
    """写出演示素材与候选清单，返回 candidates.json 的路径。"""
    demo = root / "demo"
    sources = demo / "sources"
    fixtures = demo / "fixtures"
    sources.mkdir(parents=True, exist_ok=True)
    fixtures.mkdir(parents=True, exist_ok=True)

    for name, pages in DOCS.items():
        (sources / name).write_text("\n\n".join(pages) + "\n", encoding="utf-8")

    candidates = [
        _candidate(
            "Foundations of group theory",
            "group.txt",
            year=1925,
            doi="10.1000/demo.group",
            venue="Demonstration Journal of Algebra",
            summary="给出群的定义：集合 + 满足结合律的二元运算 + 单位元 + 逆元。",
        ),
        _candidate(
            "Commutativity in abelian groups",
            "abelian_group.txt",
            year=1930,
            doi="10.1000/demo.abelian",
            venue="Demonstration Journal of Algebra",
            summary="给出阿贝尔群的定义：满足交换律的群。",
        ),
        _candidate(
            "A survey of ring theory",
            "ring.txt",
            year=1940,
            doi="10.1000/demo.ring",
            venue="Demonstration Surveys in Mathematics",
            type_code="M",
            summary="环的定义与基本结构。",
        ),
        _candidate(
            "Inverses and fields",
            "field.txt",
            year=1950,
            doi="10.1000/demo.field",
            venue="Demonstration Journal of Algebra",
            summary="域的定义：每个非零元有乘法逆元的环。",
        ),
        # ↓ 标题/DOI 与第 2 条不同，但正文逐字相同 ——
        #   用来验证"关系判重"：同一概念组 + 同一句引文 ⇒ 应被拒绝写入。
        _candidate(
            "A reprint note on commutativity",
            "abelian_group_reprint.txt",
            year=1931,
            doi="10.1000/demo.abelian.reprint",
            venue="Demonstration Notes",
            summary="重印说明，正文与《Commutativity in abelian groups》逐字相同。",
        ),
        # ↓ 与第 2 条标题+年份+DOI 全同，但素材是另一个文件 ——
        #   用来验证"文献去重"：应复用既有 lit_id，而不是新建第 6 行。
        _candidate(
            "Commutativity in abelian groups",
            "abelian_group_reprint.txt",
            year=1930,
            doi="10.1000/demo.abelian",
            venue="Demonstration Journal of Algebra",
            summary="同一篇文献的重复命中（重印版）。",
        ),
    ]
    cpath = fixtures / "candidates.json"
    cpath.write_text(json.dumps({"candidates": candidates}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return cpath


# ---------------------------------------------------------------- 离线下载器


class FixtureDownloader:
    """把 `abfixture:<name>` 解析到 demo/sources/<name>，其余走 HTTP。

    存在的意义：让"下载"这一步的下游代码路径完全真实（原子落盘、sha256、
    失败状态），只有字节来源是假的。若直接跳过下载，demo 就证明不了下载链路。
    """

    name = "fixture-downloader"

    def __init__(self, sources: Path, fallback=None):
        self.sources = Path(sources)
        self.fallback = fallback

    def download(self, url: str, dest_dir: Path, filename_hint: str):
        from .fetch import FetchResult
        import hashlib

        if not url.startswith("abfixture:"):
            if self.fallback is not None:
                return self.fallback.download(url, dest_dir, filename_hint)
            # `kind` 是 `FetchResult` 的受控失败档（`F-6`）：契约要求"失败的下载
            # 必须答得出为什么"，所以这里不能再只给自由文本的 error。
            return FetchResult(ok=False, kind="non_fixture_url", path=None, http_status=None,
                               bytes=0, sha256=None,
                               error=f"non-fixture_url:{url[:60]}")

        name = url.split(":", 1)[1]
        src = self.sources / name
        if not src.exists():
            return FetchResult(ok=False, kind="fixture_missing", path=None, http_status=None,
                               bytes=0, sha256=None,
                               error=f"fixture_missing:{name}")

        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / src.name
        shutil.copy2(src, target)
        data = target.read_bytes()
        return FetchResult(
            ok=True,
            path=str(target),
            http_status=200,
            bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            error=None,
        )


# ---------------------------------------------------------------- 逐条判决（演示替身）


def _judge_pending_candidates(store: Store, log, *, agent: AgentA,
                              candidates: dict[str, Any] | None = None) -> dict:
    """演示替身：替 A 把「待新增列表」里的每一条逐条判过（2026-10-26 Q16 之后入库的唯一定路）。

    为什么演示里必须有这一步：A 的自动链路只负责把检索到的候选暂存进列表（注册即待裁），
    入库必须先逐条判过 —— 判过的证据就是那一句 `relevance`（为什么与本次检索相关），
    而没有逐条判完之前整批提交会被拒（`lit.admit_all` 的提交闸）。
    真机 `projects/mp3-r3` 那次就是反例：33 条同一秒整批入库、`relevance` 一条都没写。

    演示里没有模型，所以"读"这个动作由演示脚本替：先把这一条的 PDF 取下来（
    `AgentA._stage_download`，与产品里同一条下载路径），再代写那一句 relevance，
    然后逐条判 —— 判收的走 `lit.admit`（并把取到的字节搬进 `library/<lit_id>/`），
    判拒的用受控理由码（同一篇的重复副本），行留着、不物理删。

    返回 `{request_id: {admitted, rejected}}`（读数，交给演示日志）。
    """
    import tempfile as _tempfile

    from .providers import Candidate
    from .tools import build_for_role

    registry = build_for_role("A", store=store, workspace_root=store.root).registry
    registry.bound_role = "A"
    out: dict[str, dict[str, int]] = {}
    staging = Path(_tempfile.mkdtemp(prefix="demo-judge-"))
    try:
        for rid in sorted({str(r.get("request_id") or "")
                           for r in store.rows("lit_candidates")}):
            waiting = [r for r in store.rows("lit_candidates")
                       if str(r.get("request_id") or "") == rid
                       and L.judged_state(r) == "pending"]
            if not waiting:
                continue
            # A 的那一句证据先落在行上（产品里是 A 读过之后自己写；演示里由这里代写）。
            with store.tx("lit_candidates", actor="demo", note="demo.judge") as tx:
                for row in tx.rows("lit_candidates"):
                    if str(row.get("request_id") or "") != rid:
                        continue
                    if str(row.get("relevance") or "").strip():
                        continue
                    row["relevance"] = (
                        "演示替身：逐条读过的记录 —— 这一条的题名与本次检索的主题同族"
                        "（产品里这一句由 A 写过再入库）")
                    tx.upsert("lit_candidates", row, note="demo.judge")
            counts = {"admitted": 0, "rejected": 0}
            admitted_ids: list[str] = []
            for row in waiting:
                slot = str(row.get("slot") or "")
                # "读过"这一步在演示里的落地：真的把这一条的 PDF 取下来。
                # 字节要从当次 provider 交回的 Candidate 取（`pdf_url` 只活在它上面，
                # 候选行上那一格 `url` 是给 B 的定位符）—— 找不到就退回按行重建，
                # 退化的那一档只会让这一条没有全文，不会让它变成"读过"。
                cand = (candidates or {}).get(str(row.get("title") or ""))
                if cand is None:
                    cand = Candidate(title=str(row.get("title") or ""), year=row.get("year"),
                                     doi=row.get("doi"),
                                     type_code=str(row.get("type_code") or "Z"),
                                     summary=str(row.get("summary") or ""),
                                     pdf_url=str(row.get("url") or "") or None,
                                     provider=str(row.get("provider") or ""))
                dl = agent._stage_download(cand, staging)
                res = registry.call("lit.admit", slots=[slot], request_id=rid)
                if res.ok and (res.unwrap().get("admitted") or []):
                    lit_id = str(res.unwrap()["admitted"][0]["lit_id"])
                    rel_path, dl_clean = agent._attach_staged(lit_id, dict(dl))
                    if rel_path:
                        with store.tx("literature", actor="demo", note="demo.judge") as tx:
                            got = tx.find("literature", lit_id=lit_id)
                            if got is not None:
                                got["path"] = rel_path
                                got["download"] = dl_clean
                                tx.upsert("literature", got, note="demo.judge")
                    counts["admitted"] += 1
                    admitted_ids.append(lit_id)
                    continue
                code = ""
                if res.ok:
                    code = str(((res.unwrap().get("refused") or [{}])[0] or {}).get("code") or "")
                reason = code if code in S.CANDIDATE_REASON_CODES else "duplicate_doi"
                registry.call("lit.stage_reject", slot=slot, reason_code=reason,
                              note="演示替身：逐条判过 —— 这一条不入库（理由见理由码）")
                counts["rejected"] += 1
                if reason == "duplicate_doi":
                    # 同一篇被别的请求先登记了：判拒是对的，但它仍然是"这一问找到的那一篇"
                    # （产品的判重分支就是这么记的：复用既有 lit_id、只追加来源）。
                    hit, _key = D.find_existing_literature(
                        store.rows("literature"), str(row.get("title") or ""),
                        row.get("year"), row.get("doi"))
                    if hit is not None:
                        dup_id = str(hit.get("lit_id") or "")
                        admitted_ids.append(dup_id)
                        # 同一篇被多个请求命中：来源要累积到那一行上（可追溯）。
                        with store.tx("literature", actor="demo", note="demo.judge") as tx:
                            got_dup = tx.find("literature", lit_id=dup_id)
                            if got_dup is not None:
                                src = set(got_dup.get("source_request_ids") or [])
                                src.add(rid)
                                got_dup["source_request_ids"] = sorted(src)
                                tx.upsert("literature", got_dup, note="demo.judge")
            # 判完之后收口（提交闸在这一步才放行；它同时写委托报告）。
            registry.call("lit.admit_all", request_id=rid)
            # 这一问最终入库了哪几篇要写回请求行：Q16 之后入库不在 `run_once` 里发生，
            # 于是 `result_lit_ids` 也得在这里补上（否则请求行永远说"一篇都没找到"）。
            if admitted_ids:
                with store.tx("search_requests", actor="demo", note="demo.judge") as tx:
                    got_req = tx.find("search_requests", request_id=rid)
                    if got_req is not None:
                        got_req["result_lit_ids"] = S.sorted_unique(
                            [i for i in (list(got_req.get("result_lit_ids") or [])
                                         + admitted_ids) if i])
                        # 这一问最终有文献落库 ⇒ 终局是 ok，而 run_once 那一刻写下的
                        # "命中 N 条、入库 0 条（待裁）"读数已经过期，不许留在盘上。
                        if got_req["result_lit_ids"]:
                            got_req["outcome"] = "ok"
                            got_req["last_error"] = None
                        tx.upsert("search_requests", got_req, note="demo.judge")
            out[rid] = counts
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    if out:
        log("    " + json.dumps(out, ensure_ascii=False, default=str))
    return out


# ---------------------------------------------------------------- 主流程


def run_demo(root: Path, *, reset: bool = True, verbose: bool = True) -> int:
    from .extract import extract_text
    # `R-56`（`draft/28` §172）：演示点名要一个离线确定性抽取器，所以用
    # `OfflineFixtureExtractor`（与 `RuleExtractor` 同实现、声明自己不是框架回退）。
    # 用 `RuleExtractor` 会被 `AgentB` 当成"框架在无 LLM 时偷偷回退"而拒抽 ——
    # 那条规矩是对的（它会往概念图里灌碎片），演示要的是"调用方明确选择"。
    from .llm import OfflineFixtureExtractor
    from .providers import FixtureProvider

    root = Path(root).resolve()
    cpath = build_fixtures(root)
    work = root / "demo" / "run"
    if reset and work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    st = Store(work)
    st.init(force=reset)

    log = (lambda *a: print(*a)) if verbose else (lambda *a: None)

    log("=" * 78)
    log("A/B 多智能体协同工作流 —— 离线端到端演示")
    log(f"工作区：{work}")
    log("=" * 78)

    # ---------------- 1. 其他智能体提交搜索请求 ----------------
    requests = [
        ("群论基础概念", "broad", ""),
        ("阿贝尔群与交换律", "topical", ""),
        ("域的定义与其对环的依赖", "precise", "field definition in terms of ring"),
    ]
    with st.tx("search_requests", actor="agent-C", note="submit") as tx:
        rows = tx.rows("search_requests")
        for i, (topic, mode, desc) in enumerate(requests, 1):
            row = S.SearchRequest(
                request_id=f"r-{S.format_id(i)}",
                timestamp=S.now_iso(),
                topic=topic,
                mode=mode,
                content_description=desc,
                done=False,
                submitted_by="agent-C",
            )
            row.validate()
            tx.upsert("search_requests", row.to_dict(), note="submitted")
    log(f"\n[1] agent-C 提交了 {len(requests)} 条搜索请求")

    # ---------------- 2. A 智能体：搜索 + 下载 + 登记 ----------------
    providers = [FixtureProvider(cpath)]
    # 演示里"读过"要拿得到字节：把这一轮 provider 交回的 Candidate 按题名留一份
    # （`pdf_url` 只活在它上面；Q16 之后入库被推迟到逐条判决那一步）。
    cand_by_title = {getattr(c, "title", ""): c
                     for c in providers[0].search("", "topical", "", 100)}
    agent_a = AgentA(
        st,
        providers=providers,
        downloader=FixtureDownloader(root / "demo" / "sources"),
        config={"lease_seconds": 900, "max_attempts": 3, "download": True,
                "limits": {"broad": 20, "topical": 15, "precise": 10},
                "max_downloads_per_request": 25},
    )
    out_a = agent_a.run()
    log(f"\n[2] A 智能体跑完：{json.dumps(out_a, ensure_ascii=False, default=str)}")
    judged = _judge_pending_candidates(st, log, agent=agent_a, candidates=cand_by_title)
    log("\n[2b] 待新增列表逐条判决（演示替身）："
        + json.dumps(judged, ensure_ascii=False, default=json_default))

    # ---------------- 3. B 智能体：整理 ----------------
    agent_b = AgentB(
        st,
        extractor=OfflineFixtureExtractor(),
        extract_text=extract_text,
        config={"lease_seconds": 900, "max_attempts": 3, "dup_strong": 0.92, "dup_review": 0.72,
                "quote_widen_pages": 1, "allow_fulltext_quote_fallback": False},
    )
    out_b = agent_b.run()
    log(f"\n[3] B 智能体跑完：{json.dumps(out_b, ensure_ascii=False, default=str)}")

    # ---------------- 4. 幂等重跑：A 再来一次 ----------------
    out_a2 = agent_a.run()
    log(f"\n[4] A 智能体重跑（应无待办）：{json.dumps(out_a2, ensure_ascii=False, default=str)}")

    # ---------------- 5. 统计与校验 ----------------
    log("\n[5] 各表统计")
    stats = st.stats()
    # 表名从 `schema.TABLES` 取（`stats()` 的键就是它生成的）——
    # 写死一张名单在这里正是"并表之后 `stats["concepts"]` 当场 KeyError"的成因。
    for t in [*S.TABLES, "events"]:
        info = stats[t]
        extra = " ".join(f"{k}={v}" for k, v in info.items() if k != "count")
        log(f"    {t:16} 行数={info.get('count', info.get('appended', 0)):<4} {extra}")

    log("\n[6] 概念表（老字段名投影：并表之后它们住 `statements`，`kind='concept'`）")
    _concepts = _CR.view(st, shape="legacy")["rows"]
    for c in _concepts:
        log(f"    {c['concept_id']}  {c['name']:<22} related={c.get('related_concepts')}")

    log("\n[7] 关系表")
    for r in st.rows("relations"):
        log(f"    {r['relation_id']}  {r['concept_ids']}  status={r['status']:<8} "
            f"quote_verified={r['quote_verified']}  lit={r['lit_id']}")
        log(f"          {r['description'][:90]}")

    log("\n[8] 不变量校验")
    rep = verify_all(st, deep=True, extract_text=extract_text)
    log(f"    {'通过' if rep.ok else '**有错误**'}：错误 {len(rep.errors)} / 警告 {len(rep.warnings)}")
    for i in rep.issues[:20]:
        log(f"    [{'ERR ' if i.level == 'error' else 'WARN'}] {i.table}/{i.row_id or '-'} {i.code}: {i.message}")

    # ---------------- 6. 结果判定（demo 的"是否成功"必须可判定）----------------
    checks = {
        "请求全部完成": all(r["done"] for r in st.rows("search_requests")),
        "文献已去重（6 候选 → 5 行）": len(st.rows("literature")) == 5,
        "全部文献已处理": all(r["processed"] for r in st.rows("literature")),
        "概念已建立": len(_concepts) >= 4,
        "关系已建立（阿贝尔群↔群、域↔环）": len([r for r in st.rows("relations")
                                                  if r["status"] == "active"]) >= 2,
        "重复关系被拒绝（同一引文二次出现）": out_b.get("relations_duplicate", 0) >= 1,
        "引文全部通过逐字校验": out_b.get("quotes_verified", 0) >= 3 and out_b.get("quotes_failed", 0) == 0,
        "related_concepts 由关系表派生且形状合法": all(
            _want == sorted(set(_want)) and c["concept_id"] not in _want
            for c in _concepts
            for _want in [D.derive_related_concepts(c["concept_id"], st.rows("relations"),
                                                    include_suspect=True)]
        ),
        "每个概念都在关系图里出现过（图不是一堆孤立点）": all(
            any(c["concept_id"] in (r.get("concept_ids") or []) for r in st.rows("relations"))
            for c in _concepts
        ),
        "校验无错误": rep.ok,
    }
    log("\n[9] 演示判定")
    for k, v in checks.items():
        log(f"    {'✓' if v else '✗'} {k}")
    ok = all(checks.values())
    log(f"\n演示{'成功' if ok else '**未全部通过**'}。")
    log("=" * 78)
    return 0 if ok else 1

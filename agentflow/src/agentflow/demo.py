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

from . import schema as S
from .agent_a import AgentA
from .agent_b import AgentB
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
    cpath.write_text(json.dumps({"candidates": candidates}, ensure_ascii=False, indent=2), encoding="utf-8")
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
            return FetchResult(ok=False, path=None, http_status=None, bytes=0, sha256=None,
                               error=f"non-fixture_url:{url[:60]}")

        name = url.split(":", 1)[1]
        src = self.sources / name
        if not src.exists():
            return FetchResult(ok=False, path=None, http_status=None, bytes=0, sha256=None,
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


# ---------------------------------------------------------------- 主流程


def run_demo(root: Path, *, reset: bool = True, verbose: bool = True) -> int:
    from .extract import extract_text
    from .llm import RuleExtractor
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
                request_id=f"r-{i:04d}",
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
    agent_a = AgentA(
        st,
        providers=providers,
        downloader=FixtureDownloader(root / "demo" / "sources"),
        config={"lease_seconds": 900, "max_attempts": 3, "download": True,
                "limits": {"broad": 20, "topical": 15, "precise": 10},
                "max_downloads_per_request": 25},
    )
    out_a = agent_a.run()
    log(f"\n[2] A 智能体跑完：{json.dumps(out_a, ensure_ascii=False)}")

    # ---------------- 3. B 智能体：整理 ----------------
    agent_b = AgentB(
        st,
        extractor=RuleExtractor(),
        extract_text=extract_text,
        config={"lease_seconds": 900, "max_attempts": 3, "dup_strong": 0.92, "dup_review": 0.72,
                "quote_widen_pages": 1, "allow_fulltext_quote_fallback": False},
    )
    out_b = agent_b.run()
    log(f"\n[3] B 智能体跑完：{json.dumps(out_b, ensure_ascii=False)}")

    # ---------------- 4. 幂等重跑：A 再来一次 ----------------
    out_a2 = agent_a.run()
    log(f"\n[4] A 智能体重跑（应无待办）：{json.dumps(out_a2, ensure_ascii=False)}")

    # ---------------- 5. 统计与校验 ----------------
    log("\n[5] 各表统计")
    stats = st.stats()
    for t in ("search_requests", "literature", "concepts", "relations"):
        info = stats[t]
        extra = " ".join(f"{k}={v}" for k, v in info.items() if k != "count")
        log(f"    {t:16} 行数={info['count']:<4} {extra}")

    log("\n[6] 概念表")
    for c in st.rows("concepts"):
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
        "概念已建立": len(st.rows("concepts")) >= 4,
        "关系已建立（阿贝尔群↔群、域↔环）": len([r for r in st.rows("relations")
                                                  if r["status"] == "active"]) >= 2,
        "重复关系被拒绝（同一引文二次出现）": out_b.get("relations_duplicate", 0) >= 1,
        "引文全部通过逐字校验": out_b.get("quotes_verified", 0) >= 3 and out_b.get("quotes_failed", 0) == 0,
        "related_concepts 已由关系表派生": any(c.get("related_concepts") for c in st.rows("concepts")),
        "related_concepts 升序且不含自身": all(
            c.get("related_concepts") == sorted(set(c.get("related_concepts") or []))
            and c["concept_id"] not in (c.get("related_concepts") or [])
            for c in st.rows("concepts")
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

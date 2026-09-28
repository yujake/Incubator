"""构造一个"够丰富"的演示数据集，用于端到端验证 C/D/pipeline。

为什么需要它：`demo/` 的离线演示只有 4 个概念 / 2 条关系 —— 那足够验证 A/B 的写入链路，
但验证不了 C 的多路径搜索（只有一条路径谈不上"多条低重合度路径"），
也验证不了 D 的"缺口→提问→复查"循环（没有问题可提）。

本数据集刻意满足以下条件，每一条件都对应一条要被验证的能力：
- ≥9 个概念：够形成多条路径与结构洞；
- a 与 b 之间存在 2 跳与 3 跳两类路径：验证多长度路径枚举；
- 含一条 `quote_verified=False` 与一条 `status=suspect`：验证信息量评分会降级；
- 含一个 degree=0 的孤立概念：验证 `cold` 把它单列（"没人连接"≠"没人研究"）；
- 含一个"冷门但连接强"的概念：这是给 D 的核心输入（最可能被低估的研究点）；
- 文献有真实文本文件：让 L3 溯源与引文复核能真的下钻，而不是空手返回。

用法：
    python tools/make_demo_dataset.py [目标目录]
默认写到 `test/test1/pipelinedemo/`（已存在则整体重建）。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentflow import dedup as D  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow.store import Store  # noqa: E402

DEFAULT_DEST = ROOT / "pipelinedemo"

#: 概念表：(id, 名字, 定义)
CONCEPTS: list[tuple[str, str, str]] = [
    ("0000", "群", "集合配一个满足结合律的二元运算，有单位元且每元有逆元。"),
    ("0001", "阿贝尔群", "满足交换律的群。"),
    ("0002", "域", "每个非零元都有乘法逆元的交换环。"),
    ("0003", "环", "配两个二元运算（加、乘）的代数结构，加法成群、乘法满足分配律。"),
    ("0004", "理想", "环的一个加法子群，且对环中任意元素的乘法封闭。"),
    ("0005", "模", "环上的作用结构，是向量空间的推广。"),
    ("0006", "子群", "群的一个子集，在群的运算下自身成群。"),
    ("0007", "素理想", "若乘积属于该理想则至少一个因子属于它的真理想。"),
    ("0008", "环同态", "保持加乘与单位元的映射。"),
    ("0009", "孤立概念", "本次数据集里刻意不与任何概念相连，用来验证 cold 的分类。"),
]

#: 文献表：(id, 标题, 类型, 文件名, 正文)
LITS: list[tuple[str, str, str, str, str]] = [
    ("0000", "Foundations of group theory", "J", "group.txt",
     "A group is a set with an associative binary operation, an identity element, "
     "and inverses for every element."),
    ("0001", "Commutativity in abelian groups", "J", "abelian.txt",
     "An abelian group is a group in which the commutative law holds for every pair of elements."),
    ("0002", "A survey of ring theory", "M", "ring.txt",
     "A ring is an algebraic structure equipped with two binary operations, usually called "
     "addition and multiplication."),
    ("0003", "Inverses and fields", "J", "field.txt",
     "A field is a ring in which every nonzero element has a multiplicative inverse."),
    ("0004", "Ideals and quotients", "J", "ideal.txt",
     "An ideal is an additive subgroup of a ring that is closed under multiplication "
     "by arbitrary ring elements."),
    ("0005", "Modules over rings", "M", "module.txt",
     "A module is an abelian group together with a ring action, generalising the notion "
     "of a vector space over a field."),
    ("0006", "Subgroup structure", "J", "subgroup.txt",
     "A subgroup is a subset of a group that is itself a group under the inherited operation."),
    ("0007", "Prime ideals in commutative algebra", "M", "prime.txt",
     "A prime ideal is a proper ideal such that whenever a product lies in it, at least one "
     "factor does."),
    ("0008", "Ring homomorphisms", "J", "hom.txt",
     "A ring homomorphism is a map preserving addition, multiplication and the unit element."),
]

#: 关系表：(id, 概念组, 描述, 文献, 引文, 页码, 状态, quote_verified, 概念名备注)
#: `quote_verified=None` 表示"无法校验"（本数据集里给那些刻意不放在文献正文里的句子）。
RELATIONS: list[tuple] = [
    ("0000", ["0000", "0001"], "阿贝尔群是满足交换律的群",
     "0001", "An abelian group is a group in which the commutative law holds for every pair of elements.",
     (1, 1), "active", True),
    ("0001", ["0000", "0006"], "子群是群在继承运算下自身成群的子集",
     "0006", "A subgroup is a subset of a group that is itself a group under the inherited operation.",
     (1, 1), "active", True),
    ("0002", ["0002", "0003"], "域是每个非零元都有乘法逆元的环",
     "0003", "A field is a ring in which every nonzero element has a multiplicative inverse.",
     (1, 1), "active", True),
    ("0003", ["0002", "0004"], "理想是环的加法子群且对乘法封闭",
     "0004", "An ideal is an additive subgroup of a ring that is closed under multiplication "
             "by arbitrary ring elements.",
     (1, 1), "active", True),
    ("0004", ["0002", "0005"], "模是配环作用的阿贝尔群",
     "0005", "A module is an abelian group together with a ring action, generalising the notion "
             "of a vector space over a field.",
     (1, 1), "active", True),
    ("0005", ["0002", "0007"], "素理想是乘积落入其中则至少一个因子落入的真理想",
     "0007", "A prime ideal is a proper ideal such that whenever a product lies in it, "
             "at least one factor does.",
     (1, 1), "active", True),
    ("0006", ["0002", "0008"], "环同态是保持加法乘法与单位元的映射",
     "0008", "A ring homomorphism is a map preserving addition, multiplication and the unit element.",
     (1, 1), "active", True),
    # ---- 刻意造的两个降级样本
    # 引文在文献里找不到 → quote_verified=False → 评分必须降级
    ("0007", ["0000", "0002"], "群与域之间存在某种未在本数据集文献中出现的联系",
     "0000", "This sentence does not appear anywhere in the cited document at all.",
     (1, 1), "active", False),
    # 标为 suspect → 评分必须降级
    ("0008", ["0004", "0005"], "理想上的模结构（待复核）",
     "0005", "A module is an abelian group together with a ring action, generalising the notion "
             "of a vector space over a field.",
     (1, 1), "suspect", True),
    # ---- 3 跳路径的一条边：群-环同态（刻意与 2 跳路径低重合）
    ("0009", ["0000", "0008"], "群的运算可经环同态与环的加法结构对应",
     "0008", "A ring homomorphism is a map preserving addition, multiplication and the unit element.",
     (1, 1), "active", True),
    # 让 0008(环同态) 与 0007(素理想) 相连 → 形成 群→环同态→素理想→域 的 3 跳链
    ("0010", ["0008", "0007"], "素理想是环同态的核的典型例子",
     "0007", "A prime ideal is a proper ideal such that whenever a product lies in it, "
             "at least one factor does.",
     (1, 1), "active", True),
    # 一些增加密度的边（同时制造结构洞的素材）
    ("0011", ["0000", "0005"], "阿贝尔群是环上的模的最简单情形",
     "0005", "A module is an abelian group together with a ring action, generalising the notion "
             "of a vector space over a field.",
     (1, 1), "active", True),
    ("0012", ["0003", "0004"], "域的理想只有零理想与自身",
     "0004", "An ideal is an additive subgroup of a ring that is closed under multiplication "
             "by arbitrary ring elements.",
     (1, 1), "active", True),
    ("0013", ["0006", "0001"], "阿贝尔群的子群仍是阿贝尔群",
     "0001", "An abelian group is a group in which the commutative law holds for every pair of elements.",
     (1, 1), "active", True),
    ("0014", ["0005", "0004"], "模的理想化子给出环作用的核",
     "0004", "An ideal is an additive subgroup of a ring that is closed under multiplication "
             "by arbitrary ring elements.",
     (1, 1), "active", True),
]


def build(dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    st = Store(dest)
    st.init()

    lib = st.library
    doc_text: dict[str, str] = {}
    for lid, title, ltype, fname, text in LITS:
        d = lib / lid
        d.mkdir(parents=True, exist_ok=True)
        (d / fname).write_text(text + "\n", encoding="utf-8")
        doc_text[lid] = text

    with st.tx("concepts", "literature", "relations", "search_requests", actor="dataset") as tx:
        for cid, name, definition in CONCEPTS:
            tx.upsert("concepts", S.Concept(
                concept_id=cid, name=name, definition=definition, related_concepts=[],
                normalized_name=name.lower(), aliases=[],
                definition_source_lit_id="0000", created_at=S.now_iso(), updated_at=S.now_iso(),
            ).to_dict())

        for lid, title, ltype, fname, _ in LITS:
            # `dedup_key` 必须取自唯一的键族 `dedup.literature_keys`（`F-8`）。
            # 改前这里是 `f"title:{title.lower()}"` —— 第三种标题键形态：
            # 它既不是 `literature_keys` 的产物（差一个 `|*` 后缀），
            # 也没有走 `textutil.normalize`（标点与全角不会折平），
            # 于是演示数据里的 `dedup_key` 与判重时算出的键互相不是成员关系。
            # 演示集是端到端验证的输入，它带着一个判重路径永远匹配不上的键，
            # 会让"判重已生效"这件事看起来成立而实际不成立。
            demo_keys = D.literature_keys(title, 1900 + int(lid), None)
            tx.upsert("literature", S.Literature(
                lit_id=lid, title=title, type=ltype, summary=f"演示素材：{title}",
                path=f"{lid}/{fname}", processed=True, source_request_ids=[],
                dedup_key=demo_keys[0], doi=None, year=1900 + int(lid), authors=[],
                venue="Demo", language="en", added_at=S.now_iso(),
                download={"status": "ok", "http_status": 200, "bytes": len(doc_text[lid]),
                          "sha256": "0" * 64, "error": None},
            ).to_dict())

        # 由关系派生 related_concepts，与 agent_b 的语义保持一致
        lid_to_rels: dict[str, list[str]] = {c[0]: [] for c in CONCEPTS}
        for rid, cids, desc, lit, quote, pages, status, verified in RELATIONS:
            pr = S.PageRange(pages[0], pages[1], f"pp. {pages[0]}-{pages[1]}")
            row = S.Relation(
                relation_id=rid, concept_ids=sorted(cids), description=desc, lit_id=lit,
                page_range=pr, quote=quote,
                quote_normalized=__import__("agentflow.textutil", fromlist=["x"]).normalize_for_quote(quote),
                quote_verified=verified, statement=desc,
                concept_group_key="|".join(sorted(cids)),
                dedup_key=f"{'|'.join(sorted(cids))}::{rid}",
                status=status, duplicate_of=None, created_at=S.now_iso(),
            )
            row.validate()
            tx.upsert("relations", row.to_dict())
            for c in cids:
                for other in cids:
                    if other != c:
                        lid_to_rels[c].append(other)

        for cid, name, _ in CONCEPTS:
            row = tx.find("concepts", concept_id=cid)
            row["related_concepts"] = sorted(set(lid_to_rels[cid]))
            tx.upsert("concepts", row)

    # counters 对齐
    counters = {"lit": len(LITS), "concept": len(CONCEPTS), "relation": len(RELATIONS),
                "question": 0, "report": 0}
    (st.data / "counters.json").write_text(
        json.dumps({"schema_version": S.SCHEMA_VERSION, "counters": counters}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return dest


def main() -> int:
    dest = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_DEST
    build(dest)
    st = Store(dest)
    s = st.stats()
    print(f"已构造数据集：{dest}")
    for t in ("concepts", "literature", "relations"):
        print(f"  {t:12} {s[t]['count']} 行")
    # 快速体检：孤立的 degree=0 概念数、以及 a→b 的原始路径数
    print("  （用 `agentflow.cli --root <dest> verify` 做不变量体检）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

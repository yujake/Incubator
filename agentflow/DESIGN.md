# A/B 多智能体协同工作流 —— 细化草案 (v0.1)

> 本文件是 `test/test1/` 原型（包名 `abflow`）的**设计基线**。凡代码与本文冲突，以本文为准；凡本文未定，代码中的 `TODO`/`待决` 标注为准。
>
> 本文件是**设计理由**（"为什么这么设计"），**不构成判据**；与代码冲突处以代码为准。
> 本文的部分落点（表结构、锁、事件日志、工具层、A/B 角色实现）在正式版 `agentflow/`（包名 `agentflow`）里已经长大成形，
> 对应路径见下文各节；框架的**权威现状描述与路径索引**见
> [`../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md`](../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md)。
>
> **本机实测（版本关系）**：原型在 `test/test1/src/abflow/`，正式版在 `agentflow/src/agentflow/`；两者刻意分开，
> 定位写在 `agentflow/src/agentflow/__init__.py` 的 docstring 里（"原型是『跑通』的证据，正式版是『可发布』的形态"）。
> 正式版顶层的 `agentflow/src/agentflow/` 现有 62 个 `*.py`（复跑：`Get-ChildItem agentflow/src/agentflow -Filter *.py | Measure-Object`）。

---

## 0. 需求解读与澄清

原始需求给定了两个智能体：

- **A（文献搜索）**：消费"文献搜索请求清单"，产出"文献表"，并把文献**下载到本地**。
- **B（文献整理）**：消费 A 产出的文献，产出"概念表"与"关系表"，并**回写文献表的处理情况**。

两表由两个智能体共同读写（A 追加文献行，B 改 `processed`），因此**共享存储与并发控制是本设计的核心难点**，而不是检索算法。

### 0.1 需要澄清的点（本草案给出的裁决 + 理由）

| # | 原需求模糊处 | 本草案裁决 | 理由 |
|---|---|---|---|
| C1 | 清单用 json 还是表格 | **JSON（JSONL 追加日志 + JSON 快照投影）** | 机器写、结构化、天然支持数组字段（`related_concepts` 等）；表格对嵌套数组不友好 |
| C2 | A 与 B 如何被"触发" | **轮询 + 租约声明（claim lease）**，不引入消息队列 | 保持零外部依赖；租约保证多实例不重复处理，崩溃后自动回收 |
| C3 | `文献代号` 是否全局唯一、跨类型 | **全局唯一、4 位十进制、从 `0000` 起、单调递增不复用** | 需求原文；不复用是为了让"已删除/撤销"不产生歧义 |
| C4 | ID 用满 9999 怎么办 | **报错停止分配（fail-closed）**，不静默进位到 5 位 | 静默改变宽度会破坏所有下游解析；宁可显式失败 |
| C5 | `文献相对于文献库的地址` | 相对 `library/` 的 POSIX 路径，形如 `0007/source.pdf` | 便于整库搬迁；每个文献一个子目录，可放附件（补充材料、快照 HTML） |
| C6 | `关系描述` "需完全引用参考文献" | 拆成**两个字段**：`quote`（逐字原文，机器可校验）+ `statement`（规范化陈述） | 只有独立保存逐字引文，B 才能**自我校验**引文确实存在于该文献；把两者混在一个字段就无法验证 |
| C7 | `页码范围` 格式 | 结构化 `{start:int, end:int}` + 冗余 `label:str` | 便于程序比较；`label` 保留原书写的形态（如 `"pp. 45–67"`） |
| C8 | "相同或几乎相同的表述" | **两级判定**：精确键（概念集合相同且规范化文本相等）→ 直接判重；否则用 token 集合 Jaccard ≥ `dup_strong`(0.92) 判重、`dup_review`(0.72)~`dup_strong` 落 `suspect` 待复核 | 纯阈值判重会误杀"同一概念组的两个不同定理"；分档保留可审计的中间态 |
| C9 | 文献去重 | 按 (1) DOI 归一化 (2) 标题规范化+年份 三级键 | 同一文献常从多个 provider 命中 |
| C10 | 一条关系涉及多个文献 | 需求原文是单 `文献代号`；本草案**保留单值**（符合原文），但允许同一概念组有多条关系行（各引不同文献） | 不改动给定 schema，同时不失表达力 |

### 0.2 本草案**新增的扩展字段**（原需求没有；必须加，否则无法正确工作）

原需求字段全部保留、语义不变。以下为**附加**字段，已在 schema 中标注 `x-extension: true`：

| 表 | 新增字段 | 为什么必须加 |
|---|---|---|
| `search_requests` | `request_id` | 无稳定标识就无法标记完成、无法追溯 |
| `search_requests` | `claimed_by`, `lease_until`, `attempts` | 多实例并发时防止重复搜索；崩溃后租约到期自动回收 |
| `search_requests` | `result_lit_ids: []` | 需求只要求把 `done` 改 1，但**无法验证"完成"是否真的产出了文献**；此字段建立请求→文献的可追溯链 |
| `literature` | `lit_id` 之外的 `source_request_ids: []` | 同上，反向指回请求；也是去重时"同一文献被多个请求命中"的记录处 |
| `literature` | `dedup_key`, `doi`, `year`, `authors`, `venue`, `language` | 去重与规范引用需要；`文献类型` 标注也要靠 venue/type 判定 |
| `literature` | `download` 子对象 `{status, http_status, bytes, sha256, error}` | 下载会失败；需要可观测的失败原因，且 `sha256` 让"同一文件重复下载"可检测 |
| `concepts` | `aliases: []`, `normalized_name` | 同一概念的异名（如"群"/"group"）合并的前提 |
| `relations` | `quote_normalized`, `quote_verified`, `dedup_key`, `status` | `quote_verified` 是 B 的**质量门**；`status ∈ {active, suspect, rejected}` 承载 C8 的中间态 |
| 全局 | `data/events.jsonl` 追加式事件日志 | 所有变更可回放/审计；也是"谁在何时改了哪一行"的唯一真相 |

---

## 1. 数据模型

所有 ID 均为 **4 位十进制字符串**（`"0000"`…`"9999"`）。所有数组按**升序**存放且无重复。所有时间戳为 **ISO-8601 带时区**（`2026-09-23T21:30:00+08:00`）。

### 1.1 `data/search_requests.json`

```jsonc
{
  "schema_version": 1,
  "rows": [
    {
      "request_id": "r-0001",            // 扩展：稳定标识
      "timestamp": "2026-09-23T21:30:00+08:00",
      "topic": "阿贝尔群的基本性质",       // 搜索主题
      "mode": "topical",                  // broad | topical | precise
      "content_description": "",          // broad 模式可空
      "done": false,
      "submitted_by": "agent-C",          // 扩展：其他智能体
      // 以下为扩展（并发控制）
      "claimed_by": null, "lease_until": null, "attempts": 0,
      "result_lit_ids": [], "last_error": null
    }
  ]
}
```

**不变量**：`mode ∈ {broad, topical, precise}`；`mode == "broad"` 时 `content_description` 允许为空，`precise` 时**必须非空**；`done == true` ⟹ `result_lit_ids` 非空**或** `last_error` 非空（二者留一，说明"完成"包含"确认无结果"）。

### 1.2 `data/literature.json`

```jsonc
{
  "schema_version": 1,
  "rows": [
    {
      "lit_id": "0000",
      "title": "Elementary properties of Abelian groups",
      "type": "J",                        // GB/T 7714 类型码，见 §1.5
      "summary": "……",                    // 内容简述
      "path": "0000/source.pdf",          // 相对 library/
      "processed": false,                 // B 处理完置 true
      // 扩展
      "source_request_ids": ["r-0001"],
      "dedup_key": "doi:10.4064/fm-1-1-1",
      "doi": "10.4064/fm-1-1-1",
      "year": 1925, "authors": ["..."], "venue": "...", "language": "en",
      "added_at": "2026-09-23T21:31:00+08:00",
      "download": { "status": "ok", "http_status": 200, "bytes": 812345,
                    "sha256": "…", "error": null }
    }
  ]
}
```

**不变量**：`path` 必须在 `library/` 下真实存在文件（除非 `download.status != "ok"`，此时允许 `path == null`）；`type ∈ {J, M, C, D, R, S, P, N, EB, Z}`。

### 1.3 `data/concepts.json`

```jsonc
{
  "schema_version": 1,
  "rows": [
    {
      "concept_id": "0000",
      "name": "群",
      "definition": "……（逐字或紧致改写，附来源 lit_id）",
      "related_concepts": ["0001", "0002"],   // 升序、不含自身
      // 扩展
      "normalized_name": "群",
      "aliases": ["group"],
      "definition_source_lit_id": "0000",
      "created_at": "…", "updated_at": "…"
    }
  ]
}
```

**不变量**（`verify` 强制）：`related_concepts` 升序、无重复、**不含自身**、每个元素都存在于概念表。

### 1.4 `data/relations.json`

```jsonc
{
  "schema_version": 1,
  "rows": [
    {
      "relation_id": "0000",              // 扩展：稳定标识（需求未要求，但审计必需）
      "concept_ids": ["0001", "0002", "0003"],  // 升序
      "description": "阿贝尔群是满足交换律的群",  // 需求字段：应为引文的忠实转写
      "lit_id": "0000",
      "page_range": { "start": 45, "end": 46, "label": "pp. 45–46" },
      // 扩展
      "quote": "An abelian group is a group in which the commutative law holds.",
      "quote_normalized": "an abelian group is a group in which the commutative law holds",
      "quote_verified": true,
      "statement": "阿贝尔群是满足交换律的群",
      "concept_group_key": "0001|0002|0003",
      "dedup_key": "0001|0002|0003::<hash(quote_normalized)>",
      "status": "active",                 // active | suspect | rejected
      "created_at": "…"
    }
  ]
}
```

**不变量**：`concept_ids` 升序、无重复、**长度 ≥ 2**、全部存在于概念表；`lit_id` 存在**且该文献 `processed == true`**；`page_range.start ≤ end`。

### 1.5 `文献类型` 受控词表（GB/T 7714 标注法）

| 码 | 含义 | 典型来源 |
|---|---|---|
| `J` | 期刊论文 | Crossref `journal-article` |
| `M` | 专著/教材 | OpenAlex `book` |
| `C` | 会议论文/论文集 | OpenAlex `proceedings-article` |
| `D` | 学位论文 | OpenAlex `dissertation` |
| `R` | 报告/技术报告 | OpenAlex `report` |
| `S` | 标准 | — |
| `P` | 专利 | — |
| `N` | 报纸文章 | — |
| `EB` | 电子文献/预印本/网页 | OpenAlex `preprint`、arXiv、网页 |
| `Z` | 其他 | 兜底 |

---

## 2. 共享存储：并发、原子性与崩溃恢复

### 2.1 事实来源与投影

```
data/events.jsonl   ← 唯一追加式事实源（append-only，只增不改）
data/*.json         ← 由事件折叠出的快照投影（可随时从 events 重建）
```

每次写事务 = 追加一组事件 → 原子替换对应快照。快照损坏可 `agentflow rebuild` 从事件重建。

### 2.2 锁

- 每个表一个**跨进程排他锁文件** `data/.locks/<table>.lock`，用 `filelock`（已在环境中）。
- 所有读-改-写**必须在同一锁内完成**（避免 lost update）。
- 跨表事务（如"加关系 + 维护 related_concepts"）按**固定顺序**获取多把锁（`concepts` → `relations` → `literature`）**防止死锁**。
- `lease_until` 提供**逻辑租约**，与 OS 锁分离：OS 锁防"同时写"，租约防"重复干活"。

### 2.3 原子写

写临时文件 `<table>.json.tmp` → `os.replace()` 覆盖（同盘原子）。写前 `json.dumps(..., ensure_ascii=False, indent=2, sort_keys=False)` 并**校验一遍 schema**，校验失败则放弃写入（不污染快照）。

### 2.4 幂等与顺序

- **A 的顺序**：搜索 → 下载 → **先追加 `literature` 行** → 再置 `done=true` + 写 `result_lit_ids`。若中途崩溃：`done` 仍为 false，下次重跑会重新搜索；文献行因 `dedup_key` 已存在而**不会重复登记**（幂等）。
- **B 的顺序**：解析 → 抽取 → **先在单事务内写 concepts + relations + related_concepts** → 再置 `processed=true`。崩溃则重做；因关系 `dedup_key` 去重，重做不产生重复。
- **绝不**先置标志位再干实事。

### 2.5 ID 分配

`data/counters.json` 在**锁内**分配：读计数 → 校验 ≤ 9999 → 写回并返回。分配与建行在**同一事务内**，避免"号发出去了行没建"造成空洞。
> 空洞本身无害（ID 只需唯一+单调），但**同一事务**可让 `rebuild` 完全确定。

---

## 3. 去重与相似度

### 3.1 规范化

`normalize(text)`：Unicode NFC → 小写 → 全角转半角 → 去标点 → 折叠空白 → 去首尾。中英文都走同一路径（中文无空格，标点去除后成串，可用字符 bigram 集合）。

### 3.2 相似度

`similarity(a, b)` = token 集合 Jaccard（英文按词、中文按字符 bigram）。**无需外部依赖、确定性、可解释**。
（预留 `similarity_fn` 插槽，将来可换 embedding；本草案不引入。）

### 3.3 关系判重（对应 C8）

设 `K = concept_group_key`（排序后拼接）：

1. 若存在 `K` 相同且 `quote_normalized` **相等** → 判重，**拒绝**写入，返回既有 `relation_id`。
2. 否则在 `K` 相同的行中取最大 `similarity`：
   - `≥ dup_strong(0.92)` → 判重，拒绝写入（记 `duplicate_of`）。
   - `∈ [dup_review(0.72), dup_strong)` → **写入但置 `status="suspect"`**，并记 `duplicate_of == 最相似行的 id`，等人工/LLM 复核。
   - `< dup_review` → 正常写入 `status="active"`。
3. `K` 不同 → 不同关系，正常写入（即使文本相似）。

> 之所以用"概念组相同"作为前置条件：不同概念组之间文本相似（如"群是……"vs"环是……"）是**不同知识点**，不应判重。

### 3.4 概念判重

`normalized_name` 相等 → 合并（把本次的 `aliases` 并入既有行）。否则不合并（不靠相似度自动合并概念，避免错误归并；相似名落 `suspect` 交由复核）。

### 3.5 文献判重

三级键，命中即复用既有 `lit_id`：
1. `doi:<normalized doi>`
2. `title:<normalize(title)>|<year>`
3. `sha256:<下载文件哈希>`

---

## 4. 模块与接口契约

原型实现（包名 `abflow`，落在 `test/test1/src/abflow/`）：

```
test/test1/src/abflow/
├── schema.py     数据模型、字段校验、(可选) jsonschema 导出
├── store.py      Store：锁、原子写、事务、事件日志、ID 分配、rebuild
├── textutil.py   normalize / similarity / slugify / parse_page_range
├── providers.py  SearchProvider 协议 + OpenAlex/Crossref/DOAJ/EuropePMC/Fixture 实现
├── fetch.py      Downloader：限速、重试、镜像回退、sha256
├── extract.py    extract_text(path) -> DocumentText（txt/md/html/pdf）
├── llm.py        Extractor 协议 + RuleExtractor(离线) + LLMExtractor(可插拔)
├── dedup.py      三级判重逻辑（文献/概念/关系）
├── agent_a.py    AgentA.run_once()
├── agent_b.py    AgentB.run_once()
├── verify.py     全局不变量校验（含引文可验证性）
└── cli.py        命令行入口
```

正式版（包名 `agentflow`）里同一批模块的路径（相对工作区根 `D:\Incubator`）：

| 原型模块 | 正式版路径（相对工作区根） |
|---|---|
| `schema.py` | `agentflow/src/agentflow/schema.py` |
| `store.py` | `agentflow/src/agentflow/store.py` |
| `textutil.py` | `agentflow/src/agentflow/textutil.py`（另加 `canonical.py`：规范 JSON 字节串的唯一实现） |
| `providers.py` | `agentflow/src/agentflow/providers.py` |
| `fetch.py` | `agentflow/src/agentflow/fetch.py` |
| `extract.py` | `agentflow/src/agentflow/extract.py` |
| `llm.py` | `agentflow/src/agentflow/llm.py` |
| `dedup.py` | `agentflow/src/agentflow/dedup.py` |
| `agent_a.py` | `agentflow/src/agentflow/agent_a.py` |
| `agent_b.py` | `agentflow/src/agentflow/agent_b.py` |
| `verify.py` | `agentflow/src/agentflow/verify.py` |
| `cli.py` | `agentflow/src/agentflow/cli.py` + `agentflow/src/agentflow/__main__.py` |

**本机实测**：正式版的 `AgentA` / `AgentB` 只保留 `run_once()`（`agentflow/src/agentflow/agent_a.py:421`、
`agentflow/src/agentflow/agent_b.py:404`），下面 §5/§6 里写的 `run_forever()` 只存在于原型 `test/test1/src/abflow/agent_a.py`；
正式版把"反复跑"交给了 `agentflow/src/agentflow/agent_loop.py::run_role` 与
`agentflow/src/agentflow/scheduler.py`。

### 4.1 关键接口（其余模块必须遵守）

```python
# providers.py
@dataclass(frozen=True)
class Candidate:
    title: str; year: int | None; doi: str | None; authors: list[str]
    venue: str | None; type_code: str          # GB/T 7714 码
    summary: str; pdf_url: str | None; landing_url: str | None
    language: str | None; provider: str; raw: dict

class SearchProvider(Protocol):
    name: str
    def search(self, topic: str, mode: str, description: str, limit: int) -> list[Candidate]: ...

# fetch.py
@dataclass(frozen=True)
class FetchResult:
    ok: bool; path: str | None; http_status: int | None
    bytes: int; sha256: str | None; error: str | None

class Downloader(Protocol):
    def download(self, url: str, dest_dir: Path, filename_hint: str) -> FetchResult: ...

# extract.py
@dataclass(frozen=True)
class DocumentText:
    text: str; pages: list[str]        # 逐页文本，供页码定位
    source_kind: str                   # pdf | txt | md | html
    def text_at(self, start: int, end: int) -> str: ...

# llm.py
@dataclass(frozen=True)
class ConceptDraft:
    name: str; definition: str; aliases: list[str]; source_lit_id: str

@dataclass(frozen=True)
class RelationDraft:
    concept_names: list[str]           # 松散输入，由 agent_b 解析/新建概念
    description: str; quote: str
    page_range: PageRange

class Extractor(Protocol):
    def extract(self, doc: DocumentText, lit_id: str, meta: dict) -> tuple[list[ConceptDraft], list[RelationDraft]]: ...
```

### 4.2 `Store` 公开 API

```python
class Store:
    def __init__(self, root: Path): ...
    @contextmanager
    def tx(self, *tables: str) -> Iterator[Tx]: ...      # 多表事务（固定顺序加锁）
    def read(self, table: str) -> dict: ...              # 无锁快照读
    def alloc_id(self, tx, table: str) -> str: ...       # 锁内 4 位分配
    def append_event(self, tx, kind: str, payload: dict) -> None: ...
    def rebuild(self) -> None: ...                       # 从 events.jsonl 重建快照
```

---

## 5. A 智能体的工作流

### 5.1 模式策略（把"广泛/专题/精确"落成可执行查询）

| 模式 | 目标 | 查询构造 | 文献类型偏好 | 默认 limit |
|---|---|---|---|---|
| `broad` 广泛 | 建立领域全貌 | `topic + ("survey" OR "review" OR "introduction" OR "textbook")`；同时拉一次 `topic` 的高被引 top-N | 优先 `M`/`J` 综述；`EB` 次之 | 20 |
| `topical` 专题 | 细分领域奠基 + 前沿 | 两路：① `topic` 按**被引数降序**取前 N（奠基）② `topic` 按**发表年降序**取前 N（前沿） | `J` 优先，`C` 次之 | 15 + 15 |
| `precise` 精确 | 命中明确课题 | `description` 全文检索 + `topic` 约束；按相关性排序 | 不限，但要求 `similarity(topic, title) ≥ 0.2` 或 keyword 全命中 | 10 |

> 说明：这些是**可配置的默认策略**，不是硬编码。配置见 `config.yaml`。

### 5.2 主循环（单次）

```
1. claim:  在 requests 表内按 timestamp 升序取第一条 done=false 且 (lease 为空或已过期) 的行，
           置 claimed_by=me, lease_until=now+lease_secs, attempts+=1
2. search: 按 mode 调 provider（可多个，结果合并）
3. dedup:  对每个 Candidate 算 dedup_key，命中既有文献则只追加 source_request_ids
4. download: 对未命中的、且有 pdf_url 的，下载到 library/<lit_id>/<slug>.<ext>
           （失败不致命：登记行但 download.status=failed，并在 summary 里保留元数据）
5. commit: 先在 literature 表 append 行（processed=false），
           再把 request.result_lit_ids = 本次新增的 lit_ids，done=true, lease 清空
6. event:  追加 request_claimed / lit_registered / request_done 事件
```

### 5.3 失败与重试

- 搜索失败：`attempts += 1`，`last_error` 记录，`done` **保持 false**，租约到期后可重试；`attempts > max_attempts(3)` → `done=true` + `last_error`（**显式放弃**，避免死循环）。
- 下载失败：不影响请求完成；文献行存在但 `path=null`，B 会跳过（并计入 `unprocessable`）。

---

## 6. B 智能体的工作流

### 6.1 主循环（单次）

```
1. claim:  取 literature 中 processed=false 且文件存在、且租约可用的一条
2. extract: extract_text(path) -> DocumentText（逐页）
3. mine:    Extractor.extract(...) -> (ConceptDraft[], RelationDraft[])
4. resolve: 概念名 -> concept_id（命中则复用，缺失则新建并分配 ID）
5. verify:  对每条 RelationDraft：
            - quote 必须能在 doc.text_at(page.start, page.end) 中（规范化后）**子串命中**
            - 命中 → quote_verified=true；未命中 → 扩大窗口到 ±1 页重试；
              仍失败 → quote_verified=false 且 status="suspect"
            - concept_ids 长度 ≥ 2
6. dedup:   按 §3.3 判重（reject / suspect / active）
7. commit:  单事务内：新建概念 + 追加关系 + 维护所有相关概念的 related_concepts
            （related_concepts = 该概念参与的所有关系的其它概念并集，升序去重）
8. mark:    同事务或紧随其后置 processed=true（§2.4 说明为何"先在事务内写实体"）
```

### 6.2 `related_concepts` 的维护语义

`related_concepts` **不由增量 append 直接决定**，而是**由关系表派生**：

```
related_concepts(c) = sort( ⋃ over relations r where c ∈ r.concept_ids :
                            r.concept_ids \ {c} )
```

- 需求说"每次 append 时保持升序"→ 实现上每次事务后对该概念**重算并整体写回**，结果与"追加+排序+去重"完全一致，且**可自愈**（漏更新会在下次重算时修正）。
- 关系被判 `rejected` 时，**不计入** `related_concepts`；`suspect` **计入**（保守：宁可多连，等复核）。
- `verify` 会重算一遍与表中值比对，不一致即报错。

### 6.3 引文校验（把"完全引用参考文献"变成质量门）

- 规范化后做**子串匹配**（不是相似度），因为需求要求"完全引用"。
- 允许的差异仅限：空白折叠、大小写、连字符/引号归一化、全半角。**不允许**改词、省略号省略。
- 若原文献是扫描版无文本层 → `extract_text` 返回 `pages=[]`，此时 `quote_verified=null` 且 `status="suspect"`，并在报告中显式统计"因无文本层未能校验"的条数（**不假装通过**）。

---

## 7. CLI

```text
python -m agentflow init                       # 建表
python -m agentflow submit --topic ... --mode broad [--content ...] [--by agent-C]
python -m agentflow run-a [--once|--forever] [--provider openalex,fixture] [--max 5]
python -m agentflow run-b [--once|--forever] [--max 5]
python -m agentflow status [--json]
python -m agentflow verify [--strict]
python -m agentflow rebuild                    # 从 events.jsonl 重建快照
python -m agentflow demo                       # 离线端到端（fixture provider + 内置样本 PDF/txt）
```

> **本机实测（CLI 现状）**：原型包名是 `abflow`，`run-a` / `run-b` 是它的两个子命令 ——
> 原型子命令实测（`test/test1/src/abflow/cli.py`）为
> `analyze / demo / init / pipeline / rebuild / repair / research / run-a / run-b / status / submit / tools / verify`。
> **正式版**（`agentflow/src/agentflow/cli.py`）现有 21 个子命令，实测为
> `init`、`submit`、`run-a`、`run-b`、`status`、`verify`、`rebuild`、`repair`、`tools`、
> `analyze`、`research`、`pipeline`、`demo`、`run`、`evidence`、`artifacts`、`project`、
> `run-agent`、`gate`、`inbox`、`answer`（复跑：`python -m agentflow.cli --help`）；
> 其中 `run-a` / `run-b` 仍在（`agentflow/src/agentflow/cli.py` 的 `sub.add_parser("run-a")` / `("run-b")`），
> 而"一次真实的多智能体运行"的入口是 `python -m agentflow.cli run-agent`
> （`agentflow/src/agentflow/cli.py::cmd_run_agent`，带 `--role` / `--task` / `--drive` / `--max-steps`）。

---

## 8. 目录布局（`test/test1/`）

```
test/test1/
├── DESIGN.md               本文（原型副本）
├── DESIGN-TOOLS.md / DESIGN-INTERACTIONS.md / DESIGN-ROLES.md   后续三份设计（原型副本）
├── README.md               上手说明
├── config.yaml             阈值/并发/provider 配置
├── requirements.txt
├── src/abflow/             §4 的模块（包名 `abflow`，不是 `agentflow`）
├── tests/                  pytest（含 fixtures）
├── data/                   运行时数据（三表 + requests + counters + events.jsonl + .locks/）
├── library/                下载的文献（lit_id 子目录）
├── demo/                   离线演示素材与产物
└── logs/
```

**正式版对应落点**（相对工作区根 `D:\Incubator`，本次实测）：

| 原型位置 | 正式版路径 |
|---|---|
| `test/test1/src/abflow/` | `agentflow/src/agentflow/`（62 个顶层 `*.py`） |
| `test/test1/tests/` | `agentflow/tests/`（162 个 `test_*.py`） |
| `test/test1/data/` | `agentflow/data/`（17 张表的快照 JSON + `events.jsonl`） |
| `test/test1/library/` | `agentflow/library/`（本地书架） |
| `test/test1/demo/` | `agentflow/demo/`（离线演示素材） |
| `test/test1/logs/` | 正式版无对应目录；长产出落 `<工作区根>/runs/*.json` 与 `<工作区根>/notes/<角色>.md`（`agentflow/src/agentflow/agent_loop.py`） |

> **判据不在本文**：正式版的分层结构与逐项路径索引见
> [`../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md`](../draft/35-框架现状：正式版 agentflow 的分层结构（逐项带工作区相对路径）.md)。

---

## 9. 待决问题（本草案未定，留待评审）

1. **关系描述的语言**：需求例子是中文（"阿贝尔群是满足交换律的群"），但引文多为英文。`description` 用**中文转写**、`quote` 存**原文**，还是两者都英文？本草案默认前者，但需确认。
2. **`related_concepts` 是否该有类型**（如"是……的特例"/"是对偶"）：需求只要数组，本草案不加类型；但关系表已有 `description`，若下游要按关系类型检索会不够。
3. **B 的抽取是否必须用 LLM**：本草案实现了 RuleExtractor 作为可离线运行的基线，但真正抽取概念/关系质量依赖 LLM。需要确认 LLM provider 与预算。
4. **多文献同一关系**：C10 选择保留单 `lit_id`。若需要"一条关系引多篇"，需改 schema。
5. **概念定义的来源**：需求未给 `definition` 的来源字段，本草案加了 `definition_source_lit_id`。是否需要？
6. **审批与人机协同**：`suspect` 状态如何被复核？本草案只落库，未做复核 UI/流程。
7. **规模上限**：4 位 ID 上限 10000。若预计超出，需尽早决定是否改成 6 位（**越早越好，因为会破坏所有历史 ID**）。

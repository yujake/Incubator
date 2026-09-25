# test1 —— A/B 双智能体文献流水线（初步构造）

> 这是 `DESIGN.md` 的**可运行实现**。设计理由、字段取舍、待决问题都在 `DESIGN.md`；
> 本文件只讲**怎么跑**、**跑出来是什么**、**哪些是真的、哪些还是空的**。

---

## 1. 这是什么

两个智能体通过**共享的三张表**协作：

- **A（文献搜索）**：读"搜索请求清单" → 检索 → **把文献下载到本地** → 登记到文献表 → 把请求标记完成。
- **B（文献整理）**：取未处理的文献 → 抽取概念与关系 → 写概念表/关系表 → 把文献标记为已处理。

关键点：**两者唯一的交汇点是共享存储**，所以本原型的工程量主要花在并发与一致性上
（锁、原子写、租约、幂等、可重建的事件日志），而不是检索算法。

---

## 2. 30 秒跑通（完全离线，不访问网络）

```powershell
cd D:\Incubator\test\test1
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
cd src
python -m abflow.cli demo
```

`demo` 会自建素材、自建独立工作区（`demo/run/`），把整条链路跑一遍并**打印 10 项判定**。
退出码 0 表示全部通过。

它刻意制造两件事来检验最容易写错的地方：

| 刻意制造的情况 | 检验的性质 |
|---|---|
| 两个候选**标题+DOI+年份全同** | 文献去重应复用 `lit_id`，不新建行（6 候选 → 5 行） |
| 两篇**不同文献**给出**逐字相同**的一句原文 | 关系判重应判为重复并**拒绝写入** |

### 跑测试（两套）

```powershell
cd D:\Incubator\test\test1\src
python -m pytest ..\tests -q              # 离线套件：127 passed, 8 deselected
python -m pytest ..\tests -q -m network   # 联网套件：8 passed, 127 deselected
```

**为什么分两套**：日常套件必须离线、确定性、可重复 —— 否则一次上游限流就会把 CI 搞红，
久而久之没人再看红灯。但有几个真实缺陷（Crossref `select` 参数错误导致全 400、
`precise` 模式恒为 0）**只有真实 HTTP 往返才能发现**，所以它们必须留在套件里
（不能只写在文档里），只是默认不跑。**"进套件 + 默认 deselect"是两个诉求的唯一交集。**

联网套件里限流（HTTP 429）判 `skip`（环境状况），**400 一律判失败**（那是真 bug）。

---

## 3. 真实网络模式（会联网、会下载）```powershell
cd D:\Incubator\test\test1\src
python -m abflow.cli init
python -m abflow.cli submit --topic "abelian group" --mode topical
python -m abflow.cli run-a --provider openalex      # 检索 + 下载 PDF
python -m abflow.cli run-b                          # 抽取概念与关系
python -m abflow.cli status
python -m abflow.cli verify --deep                  # 复核引文是否真在文献里
```

**已实测可用**：OpenAlex 检索、真实 PDF 下载（实测下过一个 12.4 MB 的 PDF，含 sha256）、
Crossref/DOAJ/Europe PMC 的客户端（Crossref 见 §7 已知问题）。

联网冒烟测试（只搜不下载，或加 `--download`）：

```powershell
python tools\smoke_real_provider.py --download
```

---

## 4. 目录结构

```
test/test1/
├── DESIGN.md                 设计基线（字段取舍、并发模型、待决问题）
├── README.md                 本文件
├── config.yaml               全部阈值与开关（判重阈值、租约、限速、镜像）
├── requirements.txt
├── src/abflow/               实现
│   ├── schema.py             数据模型 + 行级校验
│   ├── store.py              ★ 锁 / 原子写 / 事务 / 事件日志 / ID 分配 / 重建
│   ├── textutil.py           规范化、相似度、slug、页码解析
│   ├── dedup.py              文献 / 概念 / 关系 三种判重（策略不同，故集中）
│   ├── quoteverify.py        ★ 引文逐字校验（防幻觉引文的质量门）
│   ├── providers.py          OpenAlex / Crossref / DOAJ / EuropePMC / Fixture
│   ├── fetch.py              下载器（限速、重试、镜像回退、sha256、防穿越）
│   ├── extract.py            PDF/txt/md/html → 逐页文本
│   ├── llm.py                RuleExtractor（离线基线）+ LLMExtractor（可插拔）
│   ├── agent_a.py            A 智能体
│   ├── agent_b.py            B 智能体
│   ├── verify.py             ★ 全局不变量校验
│   ├── demo.py               离线端到端演示
│   └── cli.py                命令行
├── tests/                    pytest（离线 127 条 + 联网 8 条，见下）
├── tools/                    联网工具（都会真的访问网络）
│   ├── smoke_real_provider.py          各 provider 三模式冒烟 + 可选下载
│   ├── probe_ams_content_type.py       探针：确认 .pdf 链接返回 text/html
│   └── probe_download_ams_vs_arxiv.py  探针：AMS（病态）vs arXiv（正常）对比 ← 缺陷 #8 的证据来源
├── data/                     运行时数据（四张表 + counters + events.jsonl + .locks/）
├── library/                  下载的文献（每篇一个 lit_id 子目录）
├── demo/                     演示素材与演示工作区
└── realrun/                  ★ 真实联网小规模试跑的工作区与结果记录（见 RESULTS.md）
```

---

## 5. 数据文件速查

| 文件 | 内容 |
|---|---|
| `data/search_requests.json` | 搜索请求清单（含租约字段） |
| `data/literature.json` | 文献表（含下载状态与 sha256） |
| `data/concepts.json` | 概念表（`related_concepts` 由关系派生） |
| `data/relations.json` | 关系表（含逐字引文与校验结论） |
| `data/counters.json` | 4 位 ID 分配器 |
| `data/events.jsonl` | **追加式事件日志，唯一事实源**；快照可从它重建 |
| `data/.locks/*.lock` | 跨进程排他锁 |

> 快照被改坏时：`python -m abflow.cli rebuild`（会先自动备份）。

---

## 6. 校验器能发现什么

`python -m abflow.cli verify --deep` 会检查（不是"相信写入路径正确"）：

- ID 唯一性、连续性（空洞报警告）、`counters` 是否落后（落后会**撞号**）
- 请求 ↔ 文献双向可追溯（`done=true` 却没产出也没记错 → 报错）
- `relations.lit_id` 是否存在、其文献是否 `processed=true`（**违反写入顺序会报错**）
- `concept_ids` / `related_concepts` 是否升序、去重、不含自身、指向存在的概念
- `related_concepts` 是否与**从关系表重新派生**的结果一致（不一致给修复建议）
- `concept_group_key` 是否与 `concept_ids` 一致（不一致会让判重失效）
- 同一概念组内是否残留完全相同的引文（判重漏了）
- `--deep`：**重新打开文献**，复核每条引文的声明页码（这是唯一能自动发现编造引文的地方）

---

## 7. 已知限制（务必先读）

1. **抽取质量取决于抽取器**。`RuleExtractor` 只认定义句式（"X is a/an Y"、"X 是 Y"），
   抽不到定理式关系。**真实论文上它产出的概念名大多是垃圾**（实测抽出 `'This paper'`、
   `'If W'`、`'when W'`、`'havior'` 等，见 `realrun/RESULTS.md`）。
   它是**可测试的基线**，不是可用的抽取器；真正可用需要接 LLM
   （`LLMExtractor` 已提供提示词与 quote 回验逻辑，但本机未接 provider、未实跑）。

   > ⚠️ **最重要的一条认知**：离线 demo 全绿 + 122 个测试全绿 + 真实数据 `verify --deep`
   > 零错误零警告，**三个绿灯叠加仍然不能证明系统有用**，只能证明它**自洽**。
   > 不变量检查的是"结构自洽"，它不检查也无法检查"这个概念名是不是一个概念"。

2. ~~**Crossref provider 的 `select` 字段名有误**~~ —— **已修复并联网复验**。
   原缺陷：`select` 里用了 `abst`，Crossref 报
   `Select 'abst' specified but there is no such select for this route`，三个模式全部 HTTP 400。
   修复后实测：`broad` / `topical` / `precise` 均正常返回（各 3 条，含 `[M]` 专著类型）。
3. ~~**`precise` 模式实测召回为 0**~~ —— **已修复并联网复验**。
   原缺陷：同一 topic 下 `broad`=10、`topical`=6、**`precise`=0**。
   修复后 `precise` 返回 2 条（`Elementary theory of free non-abelian groups`、
   `Symmetry protected topological orders and the group cohomology…`）。
   ⚠️ **注意**：`precise` 召回本就应当少（它的语义是"命中明确课题"），
   所以"条数下降"不是回归；判断它是否正常应看**是否归零**与**头几条是否切题**。
4. **"下载成功"不等于"拿到的是论文"**：实测碰到一个以 `.pdf` 结尾的 URL 返回了
   **12.4 MB 的 HTML**（落地页/反爬页）。下载器会标 `content_type_mismatch`，
   A 会把它降级为 `status="content_mismatch"` 并**保留字节作为证据**，
   B 会**跳过**它并记 `last_mine_error`。这条链路已有回归测试
   （`tests/test_download_handoff.py`）。**但更广义的内容校验（是不是真 PDF、
   是不是目标论文）仍未做。**
5. **未做真实的多进程并发压测**（测试里有并发用例，但规模小）。
6. **`suspect` 状态没有复核流程**：关系被标 `suspect` 后只是留在表里等人看，
   本原型没有做复核 UI/命令。
7. **4 位 ID 上限 10000 条**（每类）。用满会 fail-closed 报错，不会静默升位宽。
8. **A 与 B 是轮询式**，没有消息队列；`run-a` / `run-b` 每跑一次处理一条（或一批）。
9. **扫描版 PDF（无文本层）**：`quote_verified` 会是 `null` 而非 `true`，
   `verify` 会把它与"校验失败"区分开。这类文献需要 OCR 才能真正校验。
10. `verify --deep` 会打印 `The 'fitz' API is deprecated... Use 'import pymupdf' instead`
    —— `extract.py` 用的是 PyMuPDF 的旧导入名，功能正常，属小瑕疵。

---

## 8. 环境

- Python 3.11+（实测 3.11.4）；依赖见 `requirements.txt`（`filelock`、`PyYAML`、`PyPDF2`、`pdfminer.six`、`PyMuPDF`、`pytest`）
- 控制台是 GBK 时请设 `$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'`，否则中文输出会乱码
- 本机网络说明：`github.com` 系域名被 hosts 劫持到 `127.0.0.1`；
  OpenAlex/Crossref/DOAJ/Europe PMC 可直连。`config.yaml` 的 `download.mirrors`
  用于直连失败时的前缀回退。

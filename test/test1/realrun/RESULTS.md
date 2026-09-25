# `realrun/` —— 真实联网小规模试跑记录

> 目的：证明"线上那条路真的通"，并把**真实数据下的失败方式**记录下来。
> 离线 demo 与 **127 个测试**（另有 8 个联网用例）证明的是"自洽"，不能证明"有用" —— 本文件补上后者。

复现命令（`config.yaml` 已把下载量压到 3 篇、单文件上限 50 MB）：

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
cd D:\Incubator\test\test1\src
$R="D:\Incubator\test\test1\realrun"
python -m abflow.cli --root $R init
python -m abflow.cli --root $R submit --topic "abelian group" --mode topical --by agent-C
python -m abflow.cli --root $R run-a --provider openalex      # 真实检索 + 真实下载 PDF
python -m abflow.cli --root $R run-b                          # 对真实 PDF 抽取
python -m abflow.cli --root $R status
python -m abflow.cli --root $R verify --deep
```

---

## 1. A 阶段（真实检索 + 真实下载）

`run-a` 返回：

```json
{ "processed": 1, "registered": 10, "duplicated": 0,
  "downloaded": 3, "download_failed": 0, "gave_up": 0,
  "outcome": "ok", "skipped_reason": "no_pending_request" }
```

- OpenAlex `topical` 模式对 `abelian group` 召回 **10 条**（受 `limits.topical: 5` × 两路"奠基 + 前沿"影响，实际多于 5）
- 其中 **3 篇**有可直连的 OA PDF，全部下载成功
- 真实下载证据（来自 `tools/smoke_real_provider.py --download`）：
  `https://www.ams.org/mcom/1987-48-177/S0025-5718-1987-0866109-5/S0025-5718-1987-0866109-5.pdf`
  → `ok=True http=200 bytes=12425458 sha256=520801e120df79ee…`
  ⚠️ **注意 `bytes` 有两个值，不是笔误**：`12424994`（首次试跑）与 `12425458`（复跑）
  相差 464 字节，**是两次不同的下载**（同一 URL，服务端返回的 HTML 落地页内容变了）。
  更关键的是 `err=content_type_mismatch: text/html` —— 这个 `.pdf` URL 返回的**根本不是 PDF**，
  见 §4 与 `README.md` §7.4。
- 429 限流与指数退避重试按预期工作（日志可见"检索受限/失败（HTTP 429），1.1s 后重试"）

## 2. B 阶段（对真实 PDF 抽取）

| 表 | 结果 |
|---|---|
| `search_requests` | 1 行，`done=1` |
| `literature` | **10 行**（3 行有本地文件，7 行无 PDF 链接） |
| `concepts` | **40 行** |
| `relations` | **4 行**，全部 `status=active`、`quote_verified=True` |
| `events` | 136 条 |
| `verify --deep` | **通过：错误 0 / 警告 0** |

## 3. ⭐ 核心观察：结构不变量通过 ≠ 知识质量可用

真实论文上抽出的**概念名**（`concepts.json` 前 15 条，逐字引用）：

```
0000 'havior'                      ← "behavior" 被 PDF 连字切断后的残片
0001 'e'
0002 'Channel polarization'        ← 这条是像样的
0003 'This paper'
0004 'Z(W)'
0005 'when W'
0006 'B-DMC W'
0007 'operator RN in the ﬁgure'
0008 'W'                           ← related=['0015','0030','0037','0038']
0009 'given threshold'
0010 'This mapping'
0011 '1 The ratio K/N'
0012 'Equality holds in (27) iff W'
0013 'with equality iff W'
0014 'If W'
```

### 三层结论

1. **`RuleExtractor` 在真实论文上产出的概念名大多是垃圾。** 它只认定义句式，而真实数学论文的定义句与它假定的模式差异很大；PDF 连字（`ﬁ`/`ﬂ`）还会把词切断（`havior` 就是证据）。

2. **但流水线本身是对的。** 它把这 40 条如实落库、4 条关系全部通过逐字引文校验、`verify --deep` **0 错误 0 警告**。也就是说：

   > **结构不变量全绿，并不代表知识可用。**

   不变量检查的是"结构自洽"（ID 唯一、数组升序、引文能在声明页内找到、`processed` 因果顺序正确）；它**不检查、也无法检查"这个概念名是不是一个概念"**。

3. **这正是必须接 LLM 抽取器的理由**，而且接的时候**必须保留 `LLMExtractor` 里的 quote 回验**（`llm.py` 已实现：模型返回的每条 `quote` 都必须能在文档里找到，找不到就剔除该条）。没有这层回验，LLM 会产出"看起来完全合理但原文里没有"的关系 —— 那是最难发现的一类错误。

### 为什么这条证据比"演示全绿"更重要

三个绿灯叠加（离线 demo 10/10 + 127 个离线测试全绿 + 真实数据 verify 0 错误）**仍然不能证明系统有用**，只能证明它**自洽**。区分"自洽"与"有用"，是本原型最重要的一个认知产出。

## 4. 本次暴露的问题及**当前状态**

| # | 问题 | 状态 |
|---|---|---|
| 1 | `CrossrefProvider` 的 `select` 用了 `abst`（Crossref 要求 `abstract`），三个模式全部 HTTP 400 | ✅ **已修复并联网复验**（三模式均正常返回） |
| 2 | OpenAlex `precise` 模式真实召回为 0（同 topic 下 broad=10、topical=6、precise=0） | ✅ **已修复并联网复验**（现返回 2 条；`precise` 召回少属预期，判据是"不归零且头几条切题"） |
| 3 | **以 `.pdf` 结尾的 URL 返回 12.4 MB 的 HTML**，下载器检测到 `content_type_mismatch`，但 AgentA 仍记 `status="ok"`，AgentB 照常抽取 → 网页文字被当成"概念" | ✅ **已修复**：A 降级为 `status="content_mismatch"` 且**保留字节作为证据**；B **跳过**并记 `last_mine_error`；已补回归测试 `tests/test_download_handoff.py`（3 个用例） |
| 4 | `verify --deep` 硬编码 `widen=1, allow_fulltext_fallback=False`，与 `agent_b` 读 config 不一致 | ✅ **已修复**：`verify_all()` 新增两个参数，CLI 从同一份 config 取值 |
| 5 | `providers.http_get_json` 里 `or isinstance(exc, json.JSONDecodeError)` 是**死代码**（注释承诺"JSON 解析失败重试一轮后放弃"，实际重试到耗尽） | ✅ **已修复**：改为 `isinstance(exc, json.JSONDecodeError) and attempt >= 1`，真正实现"重试一次即放弃" |
| 6 | `verify --deep` 打印 `The 'fitz' API is deprecated... Use 'import pymupdf' instead` | ⚠️ 无害告警，未处理（`extract.py` 用 PyMuPDF 旧导入名） |

## 5. 真实数据下的召回数值（口径说明）

`realrun` 里只有**一条 `topical` 请求**，因此**无法**从它的数据分别核实三种模式的召回数。
三种模式的召回数以联网冒烟测试（`tools/smoke_real_provider.py`）为准：

| 模式 | OpenAlex | Crossref |
|---|---|---|
| `broad` | 10 条 | 3 条 |
| `topical` | 6 条 | 3 条 |
| `precise` | 2 条（修复前为 0） | 3 条 |

> 早期本文件曾把"topical 召回 10 条"与"topical 6 条"混写 —— 前者是 `literature` 表的
> **登记行数**（受 `limits.topical` 与去重影响），后者是**单次 provider 调用的返回条数**，
> 两者口径不同。此处以 provider 返回条数为准。

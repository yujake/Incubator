# FIX16 —— `O6 = 0` 的根因修复（`C-4`）

日期：2026-09-28 · 阶段 C · 作者：本会话父代理

## 1. 读数（第一手，全部可复现）

| 读数 | 值 | 命令 / 出处 |
|---|---|---|
| 产品实际发出的 OpenAlex 检索串 | `"spectral sequence of a filtered complex and its convergence"`（整串加引号） | `temp/_oa_probe.py`（spy 住 `http_get_json`） |
| 同一请求的 `meta.count` | **0** | 同上 |
| 同一题面**不加引号**的 `meta.count` | **92549** | 同一探针的 `term` 形态 |
| `T3` 20 条内域题的 O6 | **0 / 120**（0 verified） | `temp/t3-bench.jsonl` / `temp/T3-BENCH.md` |
| `T3` 每条题的 `tokens_in` | **272（恒定）** | `temp/t3-runs/T3-01/model-transcript.jsonl` |
| 模型收到的材料 | 空（6 条 claim 全 `reason=no_source_text`，claim 文本 = "材料中没有可据以陈述的实质结论。"） | `temp/t3-runs/T3-01/claims.json` |
| 逐源状态 | `openalex=no_results`（"查过了、没有可用条目"）、`crossref=ok` 2 条（Crossref 通常无摘要） | `temp/t3-runs/T3-01/evidence.json::sources_detail` |
| OpenAlex 限流（本机当前） | `HTTP 429`，`Retry-After: 20712` 秒（≈5.75 小时） | `temp/_oa_cool_probe.py`（02:14:51） |

## 2. 根因（两条，同一条链上）

### `C-4a` 整串短语化 ⇒ 长题面召回恒为 0

`providers._phrase_query()` 把**整段** ASCII 题面塞进一对引号（`return f'"{cleaned}"'`），
而 OpenAlex 的引号是**字面短语**匹配。函数自己的 docstring 已经写明这件事
（"只适用于短的 topic …… 实测命中数为 0"），但**没有实现这个前提**：
`_plan_mode` 在 `topical`/`precise` 两条路上无条件调用它，
而生产检索路径（`evidence._default_sources` / `_default_search`）恰好以
`mode="precise", description=""` 调用 ⇒ 查询串 = 整串短语 ⇒ 20/20 内域题召回为 0。

后果链：OpenAlex 0 条 → 只剩 Crossref 2 条（无摘要）→ 交给模型的材料为空
（`tokens_in` 恒 272）→ 模型如实回答"材料里没有结论" → 0 条可回验 → **O6 = 0**。

### `C-4b` 单路异常被吞成"没有结果"

`OpenAlexProvider.search` 的 per-plan 分支把 `ProviderError` 吞成 `continue`，
下游 `evidence` 看到的是"零候选"，于是逐源状态写成 `no_results`
（"查过了、没有可用条目"）。而事实是**这个请求根本没查成**（429/网络错）。
`_oa_cool_probe.py` 刚拿到的 `429 + Retry-After=20712` 就是活体形态：
今天若在限流窗口内重跑 `T3`，每条题都会以"上游没有这个主题的文献"的读数呈现。

## 3. 修法

`src/agentflow/providers.py`（FC-27 `solver-core`：`_plan_mode` / 查询编排）：

1. `_QueryPlan` 增加 `fallback: str = ""`（该路的"词项形态"检索串，空串 = 无降级形态）。
2. `_plan_mode` 填 `fallback`：`topical` 用 `_term_query(topic)`；`precise` 用
   `_term_query(description) OR _term_query(topic)`；`broad` 不填（它的两路本来就不做整串短语）。
3. `search` 的 per-plan 抓取改为 `_fetch_with_fallback(plan)`：
   主查询**返回 0 条**且存在 `fallback`（且与主串不同）时，用词项形态**再抓一次**；
   两次都记进 `last_phrase_fallbacks[channel] = {phrase, terms, count}`、
   `stats["phrase_fallbacks"]`。`last_query_text[channel]` 记**真正产出结果的**那一条
   （"实际发出的检索串"这一语义不变），原始短语留在 `last_phrase_fallbacks` 里。
4. 单路异常不再静默：记进 `last_channel_errors[channel]` 与 `stats["channel_errors"]`；
   **所有路都异常且一条都没产出**时抛 `ProviderError`（下游因此落 `failed`，
   而不是 `no_results`）。仍有任一路成功 ⇒ 照旧不抛（"单源失败不许让整体失败"）。
5. 产物可见性：`TopicalityReport` 增加 `query_notes: tuple[str, ...] = ()`，
   `_record_topicality` 接收并填它；`evidence._report_fields` 折成
   `sources_detail[].topicality_query_notes`；`tools/search_tools._provider_diagnostics`
   的读属性表加上 `last_phrase_fallbacks` / `last_channel_errors`。

**为什么不做"按词数阈值决定要不要加引号"**：阈值是个凭空的魔数，
而"短语零召回就退词项"是自适应、无常数、且顺带覆盖其它零召回原因；
短题面的既有精度收益（"abelian group" 的实测）逐字不变。

## 4. 判据（正控 / 负控）

| 用例 | 主张 |
|---|---|
| `test_positive_plan_gives_long_topics_a_term_fallback` | 长英文题面在 `topical`/`precise` 两路上 `fallback` 非空且 ≠ 主串 |
| `test_positive_phrase_zero_recall_falls_back_to_terms` | 替身：短语查询返回 0 条、词项查询返回 3 条 ⇒ 有候选、`stats["phrase_fallbacks"] == 1`、`last_query_text` = 词项形态、台账记下原短语 |
| `test_negative_control_phrase_with_results_never_falls_back` | 替身对任何查询都给结果 ⇒ `phrase_fallbacks == 0`、只发一次请求 |
| `test_positive_all_channels_failing_raises_instead_of_no_results` | 两路都抛 ⇒ `ProviderError`，`last_channel_errors` 两条 |
| `test_negative_control_one_channel_failing_keeps_the_other` | 只一路抛 ⇒ 不抛，另一路结果照常返回 |

## 5. 生效顺序（配额现实）

OpenAlex 对本机限流到 ≈08:00（`Retry-After: 20712`）。因此：
先用替身把判据跑绿（离线可证"降级逻辑对"），**再**等配额恢复重跑 `T3` 拿 `O6` 新读数
（离线读数**不能**替代 `O6` 读数 —— 这一条不许含糊）。

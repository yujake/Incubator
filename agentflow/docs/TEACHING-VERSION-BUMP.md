# TEACHING-VERSION-BUMP.md —— 抬提示词版本的同步清单（7 处）

> 适用范围：**改了"教法"或"工具面"** —— 也就是改到了模型读得到的那些文本 / 声明，
> 于是提示词指纹变了。**只改散文、注释、`docs/` 里的说明不需要抬版本。**
>
> 为什么要有这一页：抬版本不是改一个号，是**七个落点必须同笔改完**。少改一处，
> 对应的判据就红；而红的位置离"你真正改的那段教法"往往隔着好几个文件，没有清单
> 就只能靠翻判据报错。这一页把七处、命令与"缺了谁红"列成一张表。
>
> 当前版本号**不写死在这一页**：`python -c "from agentflow import agent_prompts as A;print(A.PROMPT_VERSION)"`。

## 一、什么算"改了教法 / 工具面"

| 改了 | 要不要抬 | 为什么 |
|---|---|---|
| `specs/<role>.py` 的 `SPEC` / `ACTIONS` / policy 正文 | **要** | 那是角色读到的声明正文 |
| 工具的名字 / 摘要 / 必填参数 / 副作用（`tools/*_tools.py` 的声明） | **要** | 工具行对**每个**角色都渲染 ⇒ 十一格全换 |
| 边表 / 写集 / 可召唤面 | **要** | 伙伴表与官能段跟着换 |
| 技能的**索引行**（slug / 一句话 / 何时用） | **要** | 索引行在提示词里 |
| 技能手册的**正文** | 通常**不要** | 正文只落盘、提示词里只有索引行；索引行也变了才要抬 |
| 工具的 `returns=` | 通常**不要**（但动 golden） | `returns` 只进声明快照，不进工具行 |
| 注释、docstring、`docs/` 里的说明 | 不要 | 不进提示词 |

拿不准时的判据只有一条：**模型读到的字节变了吗？** 变了就抬。

## 二、七处（同笔改完）

| # | 落点 | 改什么 | 命令 / 判据 |
|---|---|---|---|
| 1 | `src/agentflow/agent_prompts.py` | `PROMPT_VERSION` 抬一格（`p318 → p319` 这种形式），**不在这里写换法记录** | 源码里不许再出现版本账段头（`#: pNNN`）—— 判据 `tests/test_the_prompt_history_is_the_only_ledger.py` |
| 2 | `tests/test_agent_prompts.py` | **十一格摘要**（十一个角色各一格指纹）逐格重算 | `python scripts/recompute_prompt_digests.py --write`（先不带 `--write` 只报） |
| 3 | `tests/golden/agent_surface_snapshot.json` ＋ `tool_surface_snapshot.json` | **两份 golden**（角色面 / 工具面）重冻 | 先 `python scripts/golden_diff.py` 逐格看，再 `python scripts/refreeze_goldens.py --write`；**禁改区动作**（要人逐行走查 ＋ 2 名 reviewer） |
| 4 | `docs/PROMPT-HISTORY.md` **账末** | 追加一节：段头 `#: pA → pB（日期，笔名：…）`，正文写清"动的是哪几格、哪一格没动"，末行写 `本笔 = pB` | 判据要求**末节标题 == `PROMPT_VERSION`**（箭头体例取右边那个）；账末多一段而版本没抬也红 |
| 5 | `src/agentflow/promptstability.py` ＋ `tests/test_prompt_stability.py` | 只在**动了 fact 落点 / 键集**时才改：`STEP_VOLATILE_FACTS` 与 `_VOLATILE_FACT_SETS` 末尾追加一格 | `count` / `keys_sha256` 用 `volatile_facts_digest()` **现算**，不手抄；判据 `tests/test_prompt_stability.py` |
| 6 | `docs/ROLE-GUIDE.md` ＋ `docs/SYSTEM-COMPONENTS.md` | **两份生成物**重新生成（它们是给人读的工具面镜像） | `python -B tools/write_system_docs.py`（只比对用 `--check`）；判据 `tests/test_system_docs_are_generated.py` 逐字节比 |
| 7 | `tests/fixtures/prompt_cache_warm.json` | **warm 两档真跑**重落这份读数（不重落就 stale） | `python scripts/warm_prompt_cache.py`（**花钱**；内置上限默认 `--cap-usd 0.10`，退出码 0 warmed / 1 incomplete / 2 unknown） |

> 第 3 与第 7 处都有"代价"或"禁改区"属性：**golden 是尺子**（重冻一次等于换尺子），
> **warm 是花钱的上游调用**。两处都先跑"只报不写"的那一档，看过差异再落盘。

## 三、顺序（照着做一遍）

```powershell
# 0) 先看当前版本号与账末是不是同一版（两条读数必须相等）
python -c "import sys;sys.path.insert(0,'src');from agentflow import agent_prompts as A;print(A.PROMPT_VERSION)"

# 1) 改教法 / 工具面（specs / tools / 技能索引行）

# 2) 抬号
#    编辑 src/agentflow/agent_prompts.py 的 PROMPT_VERSION

# 3) 十一格：先只报，再写回
python scripts/recompute_prompt_digests.py           # 0=一致 / 1=漂了 / 2=没查成
python scripts/recompute_prompt_digests.py --write

# 4) 两份 golden：先逐格 diff，再重冻（禁改区，人逐行走查）
python scripts/refreeze_goldens.py
python scripts/golden_diff.py
python scripts/refreeze_goldens.py --write

# 5) 账末追加一节（docs/PROMPT-HISTORY.md），末行写 本笔 = pNNN

# 6) 两份生成物
python -B tools/write_system_docs.py --check
python -B tools/write_system_docs.py

# 7) warm 两档真跑（花钱；业主没批就不要跑，并把 stale 记成待办）
python scripts/warm_prompt_cache.py
```

收尾自检（四条都必须 `0`；这些判据在本机 `tests/` 里，**不随仓库交付**）：

```powershell
python scripts/recompute_prompt_digests.py
python scripts/refreeze_goldens.py
python -B tools/write_system_docs.py --check
python -m pytest -q tests/test_agent_prompts.py tests/test_prompt_stability.py `
    tests/test_the_prompt_history_is_the_only_ledger.py tests/test_system_docs_are_generated.py
```

## 四、缺哪一处，哪条判据红

| 漏掉 | 会红在 | 症状 |
|---|---|---|
| ① 号没抬 | `test_the_prompt_history_is_the_only_ledger` | 账末是 `pNNN`，而 `PROMPT_VERSION` 还是上一版 |
| ② 十一格没重算 | `test_agent_prompts` | 某几格"现算 ≠ 冻结" |
| ③ golden 没重冻 | `test_agent_surface_snapshot` / `test_tool_surface_snapshot` | 冻结快照与现值逐字不同 |
| ④ 账末没写 | 同 ① | 版本抬了、账没落 ⇒ 红 |
| ⑤ volatile 账本没跟 | `test_prompt_stability` | `_VOLATILE_FACT_SETS` 与 `STEP_VOLATILE_FACTS` 键集不等 |
| ⑥ 生成物没重生成 | `test_system_docs_are_generated` | 盘上两份与现算逐字节不同 |
| ⑦ warm 没重跑 | `test_prompt_cache_warm` | 缓存读数 stale（不是"坏"，是"没重落"） |

## 五、两件容易搞反的事

1. **号是这一版的名字，账末是它的落点**：两件事必须同笔。只改号不落账、或只落账不改号，
   两个方向都会红 —— 这是故意的（否则账会烂成"反正都得登记"）。
2. **"十一格只有一格变"也是全量重算**：重算命令逐格算完再比，**不要**手改那一格 ——
   手改等于换了口径（摘要函数里有四处夹具替换，自己另写一份就不再是同一条判据的尺子）。

## 六、与哪些文档相邻

- 版本账本体：[`PROMPT-HISTORY.md`](PROMPT-HISTORY.md)（末节标题就是版本号）。
- 生成物为什么由代码现算：[`SYSTEM-COMPONENTS.md`](SYSTEM-COMPONENTS.md)、
  [`ROLE-GUIDE.md`](ROLE-GUIDE.md) 的开头两行。
- 禁改区（golden 在册）与批准流程：[`NOAI-GOVERNANCE.md`](NOAI-GOVERNANCE.md)、
  [`../AGENTS.md`](../AGENTS.md)。
- 术语（教法 / 十一格 / golden）：[`GLOSSARY.md`](GLOSSARY.md) §五。

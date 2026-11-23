# agent_b —— B：文献整理 / 命题入库

**职责（声明原文）**：文献整理 —— 第一阶段是快录（E/F 交来的成果几乎自动录入，
机械录入证明原文 + 已有的 V 签）；第二阶段（逐个优化）是主职，**自驱、不必等 M 派**：
洗稿 → 重拿 V 签 → 精准替换。

- 声明在 [`../specs/b.py`](../specs/b.py)（禁改区族），两段 policy 分住在
  `b_ingest_policy.py` / `b_sign_policy.py`。10 个动作、出边 `C/D/H/L/V`、
  写集 `conjectures/dependencies/literature/relations/reprocess_requests/statements`。
  （`dependencies` 是 2026-11-22 WRITESETFIX 补进写集的：那 6 条依赖行不是本目录直接写的
  —— 是 B 的秘书经 [`../secretary_deps.py`](../secretary_deps.py) 的 `_write_dep_steps`
  落 `tx.upsert("dependencies", …)`，actor 写作 `secretary-<角色>`；而 G 的写集里也有
  这张表 ⇒ 改前 `B×G` 这一对从来没被并发轴算成冲突。判据
  `tests/test_write_sets_match_their_write_points.py`。）
- 实现类 `agent_b:AgentB`；**谁读**：改 B 的人（尤其是改收录/签发口径的人）。

## 文件

| 文件 | 是什么 |
|---|---|
| `core.py` | `AgentB` 骨架（装 mixin） |
| `run_once.py` / `run.py` | 动作：抽一篇待处理文献 / 连续抽取（有界 `max_docs`） |
| `reprocess_once.py` / `run_reprocess.py` | 动作：处理一条定向重抽取请求 / 连续处理 |
| `register_statement.py` | 动作 `register_statement`：命题进台账（写库前逐条硬校验） |
| `land_manuscript.py` | 动作 `land_manuscript`：把已登记命题的某一版证明落成 B 号稿 |
| `ingest_manuscript.py` | 动作 `ingest_manuscript`：按"位置 + 格"从稿里提取并回填 |
| `open_polish_copy.py` | 动作 `open_polish_copy`：把已签稿复制成 B 号优化副本（源稿只读） |
| `decide_structural_duplicate.py` / `resolve_structural_duplicate.py` | 动作：判结构重复 / 执行合并 |
| `stage_two.py` | 第二阶段自驱（从 `run_once` 拆出的那一块） |
| `autosubmit.py` | 收录成功即提交这一份稿（读"已提交"的那一半在同名动作面） |
| `proof_receipt.py` | 收录回执：把正文号与指纹写到 `statements` 顶层 |
| `optimize_prompts.py` | 优化侧按 `kind` 分派的提示词注册表 |
| `_support.py` | 包内共用小工具 |

## 怎么用

```powershell
python -m agentflow.agent_b                                   # 零模型自检
python -m agentflow.cli --root D:\Incubator\temp\ws run-agent B --task "把待处理文献整理进台账"

# 本目录声明的动作数（现算；本文件开头写的那个数字就是它的输出）
python -c "import sys;sys.path.insert(0,'src');from agentflow import specs;print(len(specs.builtin_specs()['B'].actions))"
```

## 邻居

上游：**A**（文献行）、**F/E**（证明稿与实验稿）、**V**（签）。下游：**C**（关系分析）、
**D**（研究问题）、**H**（语义判引文）、**L**（形式化）、**V**（**送签** —— `B→V` 是手稿
拿签的主路径：B 把稿交出去，V 判、落签信封，收方秘书把签块盖回手稿与命题行；
改前这一格漏了 V，2026-11-22 ROLEDOC-1 更正）。B 是"谁能写 `statements`"的唯一角色：
通用写口一律拒写这两张表（`store.direct_write_refusal`），所以别处不要把命题写进台账。

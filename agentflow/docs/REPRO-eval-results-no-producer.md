# 复算：`eval_results` 这一档「0 行 = 没有产出方」

`tests/test_eval_results_has_no_producer.py` 那条判据背后的三条读数，原本写在它的模块 docstring 里。
2026-10-21 压 docstring 时**从 docstring 里取出**放到这里 —— 原因不是"过时"，而是那三条命令里含
`\"` 与 `\n` 这种转义序列，写回源码后会被重新解释成别的值（值会变形、复算结果就不可信了）。
放在 `.md` 里没有这层转义，可以逐字复制粘贴。

逐条在 `D:\Incubator` 下跑。

```powershell
# ① 产品代码里的写入方（AST 实调：只数 upsert/insert 的真实调用，不数注释与字符串）
python -B -c "import ast,pathlib;hits=[(str(p),n.lineno) for p in pathlib.Path('agentflow/src').rglob('*.py') for n in ast.walk(ast.parse(p.read_text(encoding='utf-8'))) if isinstance(n,ast.Call) and getattr(n.func,'attr','') in ('upsert','insert') and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='eval_results'];print(hits or '（无）')"
```

```powershell
# ② 真机根下的文件数 与 "rows 非空" 的文件数
python -B -c "import pathlib,re;fs=[p for r in ('agentflow/projects','projects') for p in pathlib.Path(r).rglob('eval_results.json')];ne=[p for p in fs if not re.search(r'\"rows\":\s*\[\s*\]', p.read_text(encoding='utf-8'))];print(len(fs),'个文件；rows 非空',len(ne))"
```

```powershell
# ③ 全盘"rows 非空"的那几个是谁
python -B -c "import pathlib,re;fs=pathlib.Path('.').rglob('eval_results.json');ne=[str(p) for p in fs if not re.search(r'\"rows\":\s*\[\s*\]', p.read_text(encoding='utf-8'))];print(len(ne));print('\n'.join(ne[:14]))"
```

## 2026-10-07 的实测结果（判据 docstring 里保留的那几行就是它）

- ① **0 个**写入方（`src/`、`tools/`、`scripts/` 全扫）；
- ② 81 个 `eval_results.json`（`agentflow/projects` 58 + 旧根 `projects` 23），`rows` **全为空**；
- ③ 全盘唯一 12 个 `rows` 非空的落在 `temp/audit/bt/**`，是测试夹具写出来的合成行，不是真机产出。

## 维护

- 判据本体：`tests/test_eval_results_has_no_producer.py`（一旦有人真的补上产出方它会红，逼人回来把真正的评测判据一起补上）。
- 这条边界为什么钉在测试侧而不在 `verify.py`：`verify.py` 在 FC-27 禁改区，动它要人审。

---

## 2026-11-22：这张表已退役（本文档的结论仍然成立，处置变了）

DATAHYGIENE 路（业主已批"派人做"）复算了上面三条读数并加了第 ④ 条，结论是
**退役**，不是"补产出方"：

- ① 产品代码里的写入方：**0 个**（AST 复算，同上）；
- ②/③ 真机工作区：**51/51** 个 `data/eval_results.json`、`rows` **全空**（本次普查口径
  改成 `projects/*/data/eval_results.json`，与 ② 同一批 51 个工作区）；
- ④ 计数器：51 个工作区的 `counters.json` 里**连 `eval` 这一格都没有** ⇒ 发号器一次也没为
  这张表发过号（"0 行"不是"曾经有行、后来删了"）。

处置（`schema.py` / `store.py` / `tools/table_tools.py` / `tools/doc_tools.py` 各一处）：

| 面 | 改后 |
|---|---|
| `schema.TABLES` | `eval_results` **不在**（`init()` 不再建 `data/eval_results.json`） |
| `schema.RETIRED_TABLES` | 新清单：文件 / 行类型 / 主键 / 为什么退 / 历史文件怎么读 |
| `schema.ID_COUNTERS` | `eval` 一格摘掉（表没了而类别还在 ⇒ `verify` 每次审计报 `counter_table_missing`） |
| `CITATION_PREFIXES` / `refspecs` | `eval` 前缀**保留**、指向退役表：历史文档里的 `eval:` 引用仍要能解析（`verify` 的 `_BRANCH_KINDS` 在导入期与它逐字对账，摘了会把 FC-27 的 `verify.py` 炸掉） |
| `store` 读侧 | `read("eval_results")` / `rows("eval_results")` 仍可用：文件在 ⇒ 行照旧读得出来 + `retired=true`；文件不在 ⇒ 空表 + `retired=true`；坏 JSON ⇒ 照旧 `StoreError`（不折成空表） |
| `store` 写侧 | `tx.upsert` / `tx.delete` / `mark_dirty` 抛 `StoreError`（码 `retired_table`）；`tx("eval_results")` 仍可声明（读历史文件），但不取锁 |
| `table.*` | 对 `eval_results` 受控拒（`ToolError`，说清"已退役"而不是"未知表名"） |

**三态**：读到旧表 ⇒ 「已退役」（`retired=true` + 为什么），不是 `unknown`（"未知表"），
也不是 `pass`（"空表所以没问题"）。历史工作区里那份文件**不算畸形**。

复算命令（在 `D:\Incubator` 下）：

```powershell
# 三条一起跑（探针落在 temp/，按 R2）
python -B agentflow/temp/datahygiene/probe_eval_retired.py
# 期望：
#   ① new workspace has eval_results.json: False
#   ② retired= True rows= 0 why= 全仓 0 个写点 + 51 个工作区全 0 行 ⇒ 从来没有产出方…
#   ③ refused: retired_table：表 'eval_results' 已退役（2026-11-22）…
```

判据：`tests/test_eval_results_has_no_producer.py`（原来的"没有产出方"四条保留；新增
a1–a6：新工作区不生成 / 历史文件可读且 retired / 文件缺席是空表不是错 / 写侧三层拒 /
把退役清单打桩成空 ⇒ 读旧表变「未知表」（反真空）/ 两张清单互斥）。

> FC-27：`schema.py` 与 `store.py` 在禁改区（`schema-migration` / `eval-criteria`）。
> 本笔按 `noai_gate --baseline` 登记，**reviewers 留空**（登记 ≠ 批准）；合入前需要
> 2 名人类 reviewer 逐行走查。

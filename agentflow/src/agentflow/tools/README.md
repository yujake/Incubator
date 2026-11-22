# src/agentflow/tools —— 工具层（模型的权限面）

> 这里装配"模型能调什么、谁能调什么"。**它不是能力清单，是权限面的落点**：
> 提示词可以被绕过，注册表不能。

## 谁读

改工具、改角色权限、排查"某个角色为什么调不到某个工具"的人。
模型看到的是 `python -m agentflow.cli tools --role <R>` 打印出来的那一份（由本目录装配）。

## 文件

| 文件 | 是什么 |
|---|---|
| `__init__.py` | 装配：按 `inspect.signature` 只给各模块传它要的参数；`_MODULES` 决定装哪些；`UNIVERSAL_TOOLS` 是"通用能力"的受控集合 |
| `base.py` | 权限面真身：`for_role`（结构性过滤）、`call` / `_callable_for`（调用期判据）、`READONLY_CALL_EXCEPTIONS`（只读角色仍可调的那几个落库代理，逐条登记）、参数门 `PARAM_SEAMS` |
| `table_tools.py` | 台账读写（`_rows` 的行级可见面也在这里，见 `AGENTS.md` 的 auth-audit 登记） |
| `fs_tools.py` | 文件读写 / 删；`RESERVED_ARTIFACT_TABLE` 与 D 的证明稿内容闸 |
| `search_tools.py` / `ocr_tools.py` / `text_tools.py` | 检索、OCR、正文抽取 |
| `graph_tools.py` / `trace_tools.py` / `analysis_tools.py` | 图、溯源、C 的分析面（第一根轴都是 `read`） |
| `research_tools.py` / `attack_tools.py` / `doc_tools.py` / `review_tools.py` | D / F / G / H 的动作面 |
| `manuscript_tools.py` / `ledger_tools.py` / `verify_tools.py` | 稿件、台账、验证（`verify_tools` 同时是 Lean 桥接层） |
| `formal_tools.py` | L 的三件（`formal.*`）；**Lean 关着时不装这个模块** |
| `conductor_tools.py` | M 与所有角色共用的通信/簿记面 |
| `clock_tools.py` / `cache_tools.py` | 计时与唤醒、提示词缓存 |

## 怎么用

```powershell
# 全库工具面（Lean 开/关两档数字不同，别互换）
python -m agentflow.cli tools

# 某个角色真正拿到的面（只读角色应当一个写工具都没有）
python -m agentflow.cli tools --role H
```

## 加一个工具的路径（四处，缺一处判据会红）

1. 在 `../specs/<角色>.py` 的 `ACTIONS` 里声明（名字 / 参数 schema / 返回 / 副作用 / 外部性）；
2. 在本目录某个 `*_tools.py` 里写 handler 并 `register()`；
3. 在 `__init__.py` 的 `_MODULES` 里装（漏装会被 `tests/test_wiring_edges.py` 一族看见）；
4. 跑 `tests/test_action_face_has_no_dangling_handlers.py` 与 `tests/test_tools_returns_declaration.py`：
   声明与实现必须两向对得上，总数由判据钉住。

**别改 `base.py` 的过滤或例外表来"让某个角色能调"**：那三处（`for_role` / `call` /
`READONLY_CALL_EXCEPTIONS`）是 FC-27 的 auth-audit 禁改区，改要 2 名 reviewer。

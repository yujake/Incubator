# agent_g —— G：论文撰写

**职责（声明原文）**：论文撰写 —— 把台账里的结论汇编成可审校的稿件，附带每条断言的来路。
**典型误根**：把"有一条数值/交叉验证支持"说成"这条断言已经成立"。

- 声明在 [`../specs/g.py`](../specs/g.py)：7 个动作、出边 `C/D/H`、写集
  `dependencies` + `documents` + `review_findings`。实现类 `agent_g:AgentG`。
- **谁读**：改稿件生成 / 引用与依赖口径的人。

## 文件

| 文件 | 是什么 |
|---|---|
| `core.py` | `AgentG` 骨架（装 mixin） |
| `build_document.py` | 动作 `build_document`：写一行 `documents` 并渲染 markdown |
| `render.py` | 动作 `render`：把稿件渲染成 markdown 文本（不写库、不落盘） |
| `refresh_markdown.py` | 动作 `refresh_markdown`：按库里当前数据重画文件 |
| `revise.py` | 动作 `revise`：按 H 的发现修订稿件 |
| `revise_gates.py` | `revise` 的闸（为守住 200 行软基线单独成文件） |
| `compose_claim.py` | 动作 `compose_claim`：构造一条合规断言（转发 `doc_tools.compose_claim`） |
| `register_dependency.py` | 动作 `register_dependency`：登记外部依赖（第一道闭合闸在工具层） |
| `write_mapping.py` | 动作 `write_mapping`：论文对应表三份（json / md / 正文附录） |
| `hard_to_prove.py` | 难以自证的命题在论文里的形态（业主 2026-11-13 裁定） |
| `_support.py` | 包内共用小工具 |

## 怎么用

```powershell
python -m agentflow.agent_g        # 零模型自检
python -m agentflow.cli --root D:\Incubator\temp\ws run-agent G --task "把台账里已定的结论写成稿件"

# 本目录声明的动作数（现算；本文件开头写的那个数字就是它的输出）
python -c "import sys;sys.path.insert(0,'src');from agentflow import specs;print(len(specs.builtin_specs()['G'].actions))"
```

## 邻居

上游：**B**（命题台账）、**E/F**（证明与实验）。下游：**H**（审校）、**M**（打包）、
**C**（依赖链）、**D**（尚未定的问题写进 open problems）。每条 claim 的 `citations`
必须指得到台账已有的号（`stmt:` / `lit:` / `exp:`）；审到 `documents.status=accepted`
才算完。

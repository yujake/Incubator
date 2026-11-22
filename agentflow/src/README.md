# src/ —— 源码根（`src` 布局）

> 只有一个包：`agentflow/`。`tests/conftest.py` 与 `pyproject.toml` 都把这里当 `sys.path` 的入口，
> 所以**不装包也能跑**：`PYTHONPATH=src python -m agentflow.cli --help`。

## 谁读

人（开发者）与编码 agent。跑起来之前不需要读它；改代码之前读
[`../README-PRODUCT.md`](../README-PRODUCT.md)，再按 `../DEVELOPMENT.md` 指的路走。

## 里面是什么

| 路径 | 是什么 | 谁生成 |
|---|---|---|
| `agentflow/` | 产品包（顶层模块 + 十个角色子包 `agent_a`…`agent_v` + `tools/` `specs/` `web/` `webui/` `wellformed/`）。见 [`agentflow/README.md`](agentflow/README.md) | 人 |
| `agentflow.egg-info/` | `pip install -e .` 的元数据（`PKG-INFO` / `SOURCES.txt` / `entry_points.txt` …）。**生成物，不要手改**；重装即覆盖，删掉也会被重装重建 | `pip` |

## 怎么用

```powershell
# 不安装，直接从源码树跑
$env:PYTHONPATH = "src"
python -m agentflow.cli --help

# 或装成可编辑包（之后在任意目录都能用 agentflow 模块）
python -m pip install -e .
```

## 与谁相邻

上游是仓库根与 `../pyproject.toml`；下游是 `../tests`（判据按 `src` 布局注入路径）
与 `../scripts`（工具同样把 `src` 加进 `sys.path`）。安装产物 `agentflow.egg-info/`
只由打包工具读，产品代码不读它。

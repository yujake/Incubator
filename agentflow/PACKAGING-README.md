# agentflow（包级 README）

这是 `agentflow` 包的**打包用** README：`pyproject.toml` 的 `readme = "README.md"`
读的就是这一份（setuptools 不允许指向项目根之外的文件，见 pyproject 里的注释）。
面向使用者的权威说明在**仓库根**的 `README.md`，两者内容不重复。

## 它是什么

面向数学研究的多智能体协同框架：一个主控（M）按需召唤 A–H 八个角色与 L（Lean
形式化者）／V（验证者），共享一份追加式台账，每个结论都要留下可回验的证据。
角色与职责见 `docs/ROLE-SPECS.md`，编排在 `agentflow.conductor`。

## 装与跑

```powershell
pip install -e .            # 开发装；控制台入口 agentflow = agentflow.cli:main
python -m agentflow --help  # 与上面那条 console script 是同一条命令
python -m agentflow --version
```

`python -m agentflow` 与 `agentflow` 是同一条命令（`pyproject.toml` 的
`[project.scripts]` 转发到 `agentflow.cli:main`，`agentflow/__main__.py` 也是同一句转发）。
CLI 的四组入口是 `incubate` / `inspect` / `run` / `serve`，28 个旧命令名一个都没删。

## 打包注意

`src/agentflow/web/static/` 是入库的前端产物，随包发布（`[tool.setuptools.package-data]`）。
未打包它时网页端在源码树里正常、装好之后白页 —— 这条由
`tests/test_packaging_includes_static.py` 钉着。

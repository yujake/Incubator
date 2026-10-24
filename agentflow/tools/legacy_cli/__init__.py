# -*- coding: utf-8 -*-
"""移植期工具的临时落点（业主 2026-10-24 批的 CLI 更新方案 C）。

## 这个包是什么

`agentflow` 的四条命令是"移植期"留下的运维/演示工具，它们不属于研究流程本身：

| 命令 | 这一件工具干什么 | 为什么它不该长期留在 CLI 里 |
|---|---|---|
| `repair --related` | 重算派生列 `related_concepts` | 并表之后那一列已随老表退役，读侧现算；留着只会让人以为还要"修" |
| `rebuild` | 从 `events.jsonl` 重建全部快照 | 数据维护动作，正常使用不该出现；出事时的逃生门 |
| `demo` | 离线端到端演示（不联网、不花钱） | 首次体验用一次，不是日常命令 |
| `evidence migrate` | 把历史产物里的内联正文迁成引用形态 | 一次性迁移（`draft/30` §T0-7），迁完就没有对象了 |

## 它们现在的形态：薄转发

实现搬到了本包（`tools/legacy_cli/<名字>.py`，每个文件一个 `main(args) -> int`），
CLI 里只留同名命令做一行转发（见 `src/agentflow/cli.py` 里那几个 `cmd_*` 的 docstring）。
这么做的目的是让"下一版删掉它们"变成一次机械操作：删掉本目录 + 删掉那四个一行函数，
其余代码一行都不用动。

## 三条纪律

1. 行为逐字节不变。搬走前后用同一份夹具工作区对拍过 stdout / stderr / 退出码，
   指纹写在 `tests/test_legacy_cli_forwards.py` 里（那是"搬走前"实测的值）。
   所以本包里的代码是原样搬过来的，不是"顺手重构一下"。
2. 不进发布门。本目录不被 `tools/release_all.py` 的任何一步点名，也不进
   `src/agentflow/` 的顶层模块登记表（它不在那个包目录里）。
3. 装好的包里没有它。`tools/` 只在源码仓库里；从 `pip install` 装出来的 CLI 没有
   这个目录，于是那四条命令会得到一句人话（"这条命令的实现已搬出 CLI…请从源码仓库运行"）
   并以退出码 2 结束 —— 那是"没查成"，不是"跑过了没问题"。

## 怎么手工跑

```text
python -c "import sys; sys.path.insert(0,'src'); from agentflow import cli; \
           raise SystemExit(cli.main(['rebuild']))"
```

每个模块只暴露一个 `main(args)`（`args` 就是 argparse 出来的那个 namespace），
所以本包既能被 CLI 的薄转发调用，也能被对拍脚本按"造一个 Namespace 再调 `main`"的方式
单独跑 —— 判据 `tests/test_legacy_cli_forwards.py` 走的正是后一种。
"""

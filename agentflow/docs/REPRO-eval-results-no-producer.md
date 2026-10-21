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

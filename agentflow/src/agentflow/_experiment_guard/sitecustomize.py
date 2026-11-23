"""实验脚本的数据目录守卫入口（只由 `agent_e/core.py::_run_script` 挂上 `PYTHONPATH`）。

`_run_script` 起实验子进程时，把本目录 prepend 进子进程的 `PYTHONPATH`，并把 data 根
写进 `AGENTFLOW_EXPERIMENT_GUARD`；解释器启动时 `site` 会 import 本模块一次，
于是守卫在脚本第一行之前就装好了。

两条底线：环境变量为空时一行副作用都没有（别的 Python 进程即使误把这个目录放进
`PYTHONPATH` 也不受影响）；装不上时绝不挡住实验 —— 退化成不设防，并在 stderr 留一行。
"""
import importlib.util
import os
import sys

try:
    _data_root = (os.environ.get("AGENTFLOW_EXPERIMENT_GUARD") or "").strip()
    if _data_root:
        # 直接按文件装 `eguard.py`，不 import `agentflow`：守卫不该把整个包的导入链
        # 拖进实验子进程（那既慢，又会给脚本多一层启动期副作用）。
        _here = os.path.dirname(os.path.abspath(__file__))
        _guard_file = os.path.join(os.path.dirname(_here), "eguard.py")
        _spec = importlib.util.spec_from_file_location("_agentflow_eguard", _guard_file)
        _module = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_module)
        _module.install(_data_root)
except Exception as _exc:  # noqa: BLE001 - 守卫失败绝不能挡住实验
    _line = ("[agentflow] experiment guard not installed, this run is unguarded: "
             f"{type(_exc).__name__}: {_exc}\n")
    try:
        sys.stderr.write(_line)
        sys.stderr.flush()
    except Exception:  # noqa: BLE001 - stderr 编码/关闭都不许把启动带坏
        try:
            os.write(2, _line.encode("utf-8", "backslashreplace"))
        except Exception:  # noqa: BLE001 - 同上
            pass

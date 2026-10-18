#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runner: task (2) 圆对照组。等价于 `python code/equichordal_scan.py circle 2000`，
不依赖 argv：按文件路径加载主脚本并调用 task_circle(2000)。"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(HERE, "equichordal_scan.py")
spec = importlib.util.spec_from_file_location("equichordal_scan", MAIN)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

sys.exit(mod.task_circle(2000))

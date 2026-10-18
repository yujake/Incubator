"""Deterministic wrapper: run pyjama_numeric.py in mode part1.

Cwd-independent (resolves via __file__), no reliance on how verify.run_experiment
passes `params` to the child process: the mode is fixed here as a literal string.
stdout carries the single REPRO_RESULT line printed by pyjama_numeric.py itself.
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(HERE, "pyjama_numeric.py")

sys.argv = ["pyjama_numeric.py", "part1"]
runpy.run_path(MAIN, run_name="__main__")

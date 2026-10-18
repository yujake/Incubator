"""Deterministic wrapper: run pyjama_numeric.py in mode part2 (minimal k for eps=0.1, 0.05).

Mode is a literal here, so nothing depends on how verify.run_experiment passes `params`.
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(HERE, "pyjama_numeric.py")

sys.argv = ["pyjama_numeric.py", "part2"]
runpy.run_path(MAIN, run_name="__main__")

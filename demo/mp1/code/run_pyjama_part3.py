"""Deterministic wrapper: run pyjama_numeric.py in mode part3 (counterexample search).

Mode is a literal here, so nothing depends on how verify.run_experiment passes `params`.
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(HERE, "pyjama_numeric.py")

sys.argv = ["pyjama_numeric.py", "part3"]
runpy.run_path(MAIN, run_name="__main__")

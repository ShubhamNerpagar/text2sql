#!/usr/bin/env python3
from __future__ import annotations
import subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
cmd=[sys.executable,'-m','pytest','-q','tests','--tb=short']
print('=== Data Intelligence Platform 7.0 test suite ===',flush=True)
rc=subprocess.run(cmd,cwd=ROOT).returncode
if rc: raise SystemExit(rc)
print('ALL TESTS PASSED',flush=True)

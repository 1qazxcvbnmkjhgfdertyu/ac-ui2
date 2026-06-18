#!/usr/bin/env python3
"""Build the optional compiled visualizer hot-path (ac_ui/_vizfast).

Entirely optional: ac-ui runs fine in pure Python and uses the compiled module
automatically when present (big speedup for the kaleido / liquid / plasma
feedback visualizers).

This builds without setuptools — it runs Cython to emit C, then compiles the C
into an extension module with the system C compiler.

Usage:
    .venv/bin/python build_native.py
"""
import os
import subprocess
import sys
import sysconfig

HERE = os.path.dirname(os.path.abspath(__file__))
PYX = os.path.join("ac_ui", "_vizfast.pyx")
CSRC = os.path.join("ac_ui", "_vizfast.c")


def main():
    os.chdir(HERE)
    try:
        import Cython  # noqa: F401
    except ImportError:
        sys.exit("Cython not installed — `.venv/bin/pip install cython` first "
                 "(optional; ac-ui works without it).")

    # 1) Cython -> C
    print("· cython", PYX)
    rc = subprocess.call([sys.executable, "-m", "cython", "-3", PYX])
    if rc != 0:
        sys.exit(f"cython failed (exit {rc})")

    # 2) C -> shared extension module with the right name for this interpreter
    suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
    out = os.path.join("ac_ui", "_vizfast" + suffix)
    include = sysconfig.get_path("include")
    cc = os.environ.get("CC", "cc")
    cmd = [cc, "-shared", "-fPIC", "-O3", "-ffast-math",
           "-I", include, CSRC, "-o", out]
    print("·", " ".join(cmd))
    rc = subprocess.call(cmd)
    if rc != 0:
        sys.exit(f"C compile failed (exit {rc})")

    # Verify it imports.
    rc = subprocess.call([sys.executable, "-c",
                          "import ac_ui._vizfast; print('ok:', ac_ui._vizfast.__file__)"])
    if rc != 0:
        sys.exit("built but failed to import")
    print("Built — ac-ui will now use the compiled feedback path automatically.")


if __name__ == "__main__":
    main()

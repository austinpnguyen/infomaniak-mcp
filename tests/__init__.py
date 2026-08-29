"""Make the package importable when the tests are run straight from a clone.

Without this, `python3 -m unittest discover -s tests` from the repository root fails
because `src` is not on the path, which is a poor first impression for something whose
selling point is that there is nothing to install.
"""
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

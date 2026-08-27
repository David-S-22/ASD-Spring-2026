import pathlib
import sys

root = str(pathlib.Path(__file__).resolve().parent.parent)

if root not in sys.path:
    sys.path.insert(0, root)

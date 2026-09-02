import pathlib
import sys


ethan_path = pathlib.Path(__file__).resolve().parent.parent
ethan_path_str = str(ethan_path)

if ethan_path_str not in sys.path:
    sys.path.insert(0, ethan_path_str)

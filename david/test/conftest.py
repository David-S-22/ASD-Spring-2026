import pathlib
import sys

def add_to_path(path: pathlib.Path):
    path_str = str(path)

    if path_str not in sys.path:
        sys.path.insert(0, path_str)

add_to_path(pathlib.Path(__file__).resolve().parent.parent.parent)
add_to_path(pathlib.Path(__file__).resolve().parent.parent)

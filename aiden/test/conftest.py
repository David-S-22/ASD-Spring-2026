import pathlib
import sys

# Add the package root (aiden/) to sys.path so tests can import the local `database` package
# using absolute imports like `from database.app import app`. Pytest imports test modules as
# top-level modules, so relative imports (e.g. `from .database`) will fail otherwise.
aiden_root = str(pathlib.Path(__file__).resolve().parent.parent)

if aiden_root not in sys.path:
    sys.path.insert(0, aiden_root)

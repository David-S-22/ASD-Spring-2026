import importlib
import pathlib
import sys

def add_to_path(path: pathlib.Path):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

root_dir = pathlib.Path(__file__).resolve().parent.parent.parent
david_dir = pathlib.Path(__file__).resolve().parent.parent
add_to_path(root_dir)
add_to_path(david_dir)

# Map backend.savings-service to backend.savings_service so hyphenated directory can be imported
pkg = importlib.import_module("backend.savings-service")
sys.modules["backend.savings_service"] = pkg
sys.modules["savings_service"] = pkg

for sub in ["app", "helpers", "ollama_service", "classifier_service", "suggestion_service"]:
    m = importlib.import_module(f"backend.savings-service.{sub}")
    sys.modules[f"backend.savings_service.{sub}"] = m
    sys.modules[f"savings_service.{sub}"] = m

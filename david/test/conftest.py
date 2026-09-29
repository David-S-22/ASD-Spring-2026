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

import backend.savings_service
import backend.savings_service.app
import backend.savings_service.classifier_service
import backend.savings_service.helpers
import backend.savings_service.ollama_service
import backend.savings_service.suggestion_service

sys.modules["savings_service"] = backend.savings_service
sys.modules["backend.savings-service"] = backend.savings_service
for sub in ["app", "classifier_service", "helpers", "ollama_service", "suggestion_service"]:
    mod = getattr(backend.savings_service, sub)
    sys.modules[f"savings_service.{sub}"] = mod
    sys.modules[f"backend.savings-service.{sub}"] = mod

from pathlib import Path

from dotenv import load_dotenv

from .config.review_config import build_mode_config
from .core.ai_runner import AIRunner
from .core.orchestrator import run_mode
from .core.prompt_registry import PromptRegistry
from .core.recorder import RunRecorder
from .core.reporter import print_menu, print_prompt_map, print_result

ALL_MODES = ("db", "endpoints", "architecture", "devops")


def _resolve_roots() -> tuple[Path, Path]:
    # agentic_loop/ sits at the repository root, so the app directory and the
    # repo root are the same place (unlike the lab layout it was ported from).
    module_dir = Path(__file__).resolve().parent
    repo_root = module_dir.parent
    return repo_root, repo_root


def _menu_choice_to_key(choice: str) -> str | None:
    return {
        "1": "db",
        "2": "endpoints",
        "3": "architecture",
        "4": "devops",
    }.get(choice)


def _print_mode_mapping(app_dir: Path) -> None:
    prompt_map = {
        "DB": app_dir / "prompts" / "service",
        "Endpoints": app_dir / "prompts" / "service",
        "Architecture": app_dir / "prompts" / "architecture",
        "DevOps": app_dir / "prompts" / "devops",
    }
    print_prompt_map({key: str(path) for key, path in prompt_map.items()})


def main() -> None:
    app_dir, repo_root = _resolve_roots()
    env_file = repo_root / ".env"
    if env_file.exists():
        load_dotenv(dotenv_path=env_file)

    mode_config = build_mode_config()
    prompts = PromptRegistry(app_dir)
    ai = AIRunner()
    recorder = RunRecorder(repo_root)

    print("AGENTIC LOOP — shared review workflow (Plan -> Act -> Observe -> Adapt)")
    print(f"Run record: {repo_root / 'reports'}")
    _print_mode_mapping(app_dir)

    while True:
        print_menu()
        choice = input("Choose a review target: ").strip()

        if choice == "0":
            print("Loop closed.")
            break

        if choice == "5":
            for key in ALL_MODES:
                result = run_mode(mode_config[key], app_dir, repo_root, prompts, ai, recorder)
                print_result(mode_config[key].label, result)
            continue

        mode_key = _menu_choice_to_key(choice)
        if not mode_key:
            print("Invalid choice. Select 0, 1, 2, 3, 4, or 5.")
            continue

        result = run_mode(mode_config[mode_key], app_dir, repo_root, prompts, ai, recorder)
        print_result(mode_config[mode_key].label, result)


if __name__ == "__main__":
    main()

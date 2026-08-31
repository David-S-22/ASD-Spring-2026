from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModeConfig:
    key: str
    label: str
    prompt_family: str
    implementation_prompts: tuple[str, ...]
    review_prompts: tuple[str, ...] = ()


def build_mode_config() -> dict[str, ModeConfig]:
    return {
        "architecture": ModeConfig(
            key="architecture",
            label="Architecture",
            prompt_family="architecture",
            implementation_prompts=(
                "implementation/system_prompt.txt",
                "implementation/task_prompt.txt",
            ),
            review_prompts=("review/review_prompt.txt",),
        ),
    }


def prompts_root(app_dir: Path) -> Path:
    return app_dir / "prompts"

def print_prompt_map(mapping: dict[str, str]):
    print("PROMPT PATH MAP")
    for label, path in mapping.items():
        print(f"- {label}: {path}")


def print_menu() -> None:
    print()
    print("=" * 70)
    print("AGENTIC REVIEW MENU  (Plan -> Act -> Observe -> Adapt)")
    print("1 - Architecture (compose topology + repo layout)")
    print("2 - Database (row counts per student DB API)")
    print("3 - Endpoints (live status + latency sweep)")
    print("4 - DevOps (GitHub Actions workflows)")
    print("5 - Run All")
    print("0 - Exit")
    print("=" * 70)


def print_result(title: str, text: str) -> None:
    print()
    print(f"RESULT: {title}")
    print(text)

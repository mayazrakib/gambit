import argparse
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__,).resolve().parents[1]
DEFAULT_AGENTS_ROOT = REPOSITORY_ROOT.parents[1] / "agents"

def render_skill(
    agents_root: Path,
    skill_name: str = "chess_tutor",
) -> dict[
    str,
    str,
]:
    skill = (agents_root / "skills" / "CHESS_TUTOR_SKILL.md").read_text()
    rules = (agents_root / "rules" / "CHESS_TUTOR_RULES.md").read_text()

    skill = skill.replace(
        "name: chess-tutor",
        f"name: {skill_name}",
        1,
    )

    skill = skill.replace(
        "# `CHESS_TUTOR_SKILL.md`",
        "# `SKILL.md`",
        1,
    )

    skill = skill.replace(
        "[Chess Tutor Rules](../rules/CHESS_TUTOR_RULES.md) and [General Rules](../rules/GENERAL_RULES.md)",
        "[Chess Tutor Rules](references/chess_tutor_rules.md)",
    )

    rules = rules.replace(
        "This ruleset supplements [General Rules](GENERAL_RULES.md). The [Chess Tutor Skill](../skills/CHESS_TUTOR_SKILL.md) defines tool routing.",
        "This ruleset supplements the host's governing instructions. The [Chess Tutor Skill](../SKILL.md) defines tool routing.",
    )

    return {"SKILL.md": skill, "references/chess_tutor_rules.md": rules,}

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate portable tutoring instructions from the canonical agents repository.",)

    parser.add_argument(
        "--agents-root",
        type=Path,
        default=DEFAULT_AGENTS_ROOT,
    )

    parser.add_argument(
        "--destination",
        type=Path,
        default=REPOSITORY_ROOT / ".agents" / "skills" / "chess_tutor",
    )

    parser.add_argument(
        "--name",
        default="chess_tutor",
    )

    parser.add_argument(
        "--check",
        action="store_true",
    )

    arguments = parser.parse_args()

    if re.fullmatch(
        r"[a-z][a-z0-9_-]{0,63}",
        arguments.name,
    ) is None:
        raise ValueError("The skill identity is invalid.",)

    files = render_skill(
        arguments.agents_root,
        arguments.name,
    )

    different = []

    for relative_path, content in files.items():
        path = arguments.destination / relative_path

        if path.is_file() and path.read_text() == content:
            continue

        different.append(relative_path,)

        if not arguments.check:
            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            path.write_text(content,)

    if arguments.check and different:
        raise SystemExit("Generated tutoring instructions differ: " + ", ".join(different,),)

    print(f"Validated {len(files,)} generated tutoring instruction files.",)

if __name__ == "__main__":
    main()

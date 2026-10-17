import argparse
from pathlib import Path

REPOSITORY_ROOT = Path(__file__,).resolve().parents[1]
DEFAULT_AGENTS_ROOT = REPOSITORY_ROOT.parents[1] / 'agents'

def render_skill(agents_root: Path,) -> dict[
    str,
    str,
]:
    skill = (agents_root / 'skills' / 'CHESS_TUTOR_SKILL.md').read_text()
    rules = (agents_root / 'rules' / 'CHESS_TUTOR_RULES.md').read_text()

    skill = skill.replace(
        'name: chess-tutor',
        'name: chess_tutor',
        1,
    ).replace(
        '# `CHESS_TUTOR_SKILL.md`',
        '# `SKILL.md`',
        1,
    )

    skill = skill.replace(
        '[Chess Tutor Rules](../rules/CHESS_TUTOR_RULES.md) and [General Rules](../rules/GENERAL_RULES.md)',
        '[Chess Tutor Rules](references/chess_tutor_rules.md)',
    )

    rules = rules.replace(
        'This ruleset supplements [General Rules](GENERAL_RULES.md).',
        "This ruleset supplements the host's governing instructions.",
    ).replace(
        '[Chess Tutor Skill](../skills/CHESS_TUTOR_SKILL.md)',
        '[Chess Tutor Skill](../SKILL.md)',
    )

    return {'SKILL.md': skill, 'references/chess_tutor_rules.md': rules,}

def main() -> None:
    parser = argparse.ArgumentParser(description='Generate portable chess evidence instructions from canonical sources.',)

    parser.add_argument(
        '--agents-root',
        type=Path,
        default=DEFAULT_AGENTS_ROOT,
    )

    parser.add_argument(
        '--destination',
        type=Path,
        default=REPOSITORY_ROOT / '.agents' / 'skills' / 'chess_tutor',
    )

    parser.add_argument(
        '--check',
        action='store_true',
    )

    arguments = parser.parse_args()
    different = []

    for relative, content in render_skill(arguments.agents_root,).items():
        path = arguments.destination / relative

        if path.is_file() and path.read_text() == content:
            continue

        different.append(relative,)

        if not arguments.check:
            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            path.write_text(content,)

    if arguments.check and different:
        raise SystemExit('Generated instructions differ: ' + ', '.join(different,),)

    print('Validated two generated chess evidence instruction files.',)

if __name__ == '__main__':
    main()

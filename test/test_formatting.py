import ast

import pytest

from scripts.format_code import format_source, get_comments

@pytest.mark.parametrize(
    "source",
    [
        'value = """a  \n\n\nb"""\n',
        'def calculate():\n    """Details."""\n    return 2\n',
        'def calculate(first, second, /, *, third=3):\n    return first + second + third\n',
        'class Combined(First, Second, metaclass=Factory):\n    pass\n',
        'values = list[\n    str,\n]\n',
        'value = call(\n    first,  # Keep this explanation.\n    second,\n)\n',
        'def calculate():\n    values = [\n        1,\n        2,\n    ]\n    other = 4\n    return values, other\n',
        'def calculate():\n    if True:\n        return 1\n    else:\n        return 2\n',
    ],
)
def test_formatting_preserves_python_and_converges(source: str,) -> None:
    formatted = format_source(source,)
    assert ast.dump(ast.parse(formatted,),) == ast.dump(ast.parse(source,),)
    assert get_comments(formatted,) == get_comments(source,)
    assert format_source(formatted,) == formatted

def test_formatting_separates_multiline_assignments_without_block_padding() -> None:
    source = 'def calculate():\n    values = [\n        1,\n        2,\n    ]\n    other = 4\n    return values, other\n'
    formatted = format_source(source,)
    assert ']\n\n    other' in formatted
    assert all((line == line.rstrip() for line in formatted.splitlines()),)

def test_formatting_does_not_pad_initial_docstring() -> None:
    formatted = format_source('def calculate():\n    """Details."""\n    return 2\n',)
    assert 'def calculate():\n    """Details."""' in formatted

def test_formatting_verticalizes_bases_and_positional_only_parameters() -> None:
    assert 'class Combined(\n' in format_source('class Combined(First, Second):\n    pass\n',)
    assert 'def calculate(\n' in format_source('def calculate(first, second, /):\n    return first + second\n',)

def test_formatting_collapses_one_type_argument() -> None:
    assert 'list[str,]' in format_source('values = list[\n    str,\n]\n',)

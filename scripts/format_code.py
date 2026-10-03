import argparse
import ast
import re
from pathlib import Path

import libcst
from libcst.metadata import PositionProvider

ROOT = Path(__file__,).resolve().parents[1]
CONTROL_TYPES = (libcst.If, libcst.For, libcst.While, libcst.Try, libcst.With, libcst.Match)

def is_section(statement,) -> bool:
    return isinstance(
        statement,
        CONTROL_TYPES,
    ) or (
        isinstance(
            statement,
            libcst.SimpleStatementLine,
        )
        and any((isinstance(
            part,
            libcst.Return,
        ) for part in statement.body),)
    )

def is_docstring(statement,) -> bool:
    return (
        isinstance(
            statement,
            libcst.SimpleStatementLine,
        )
        and len(statement.body,) == 1
        and isinstance(
            statement.body[0],
            libcst.Expr,
        )
        and isinstance(
            statement.body[0].value,
            (libcst.SimpleString, libcst.ConcatenatedString),
        )
    )

class CodeStyle(libcst.CSTTransformer):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def leave_SimpleString(
        self,
        original_node,
        updated_node,
    ):
        literal = ast.literal_eval(updated_node.value,)

        if isinstance(
            literal,
            str,
        ) and literal.startswith("#!",) and "\nimport " in literal:
            formatted = format_source(literal,)

            return updated_node.with_changes(value='"""' + formatted + '"""',)

        return updated_node

    def __init__(
        self,
        source: str,
    ) -> None:
        self.lines = source.splitlines()
        self.block_depth = 0

    def get_padding(
        self,
        original_node,
    ) -> str:
        position = self.get_metadata(
            PositionProvider,
            original_node,
        )
        line = self.lines[position.start.line - 1]
        indentation = len(line,) - len(line.lstrip(),)

        return " " * max(
            0,
            indentation - self.block_depth * 4,
        )

    def get_newline(
        self,
        padding: str,
    ):
        return libcst.ParenthesizedWhitespace(
            first_line=libcst.TrailingWhitespace(),
            indent=True,
            last_line=libcst.SimpleWhitespace(padding,),
        )

    def visit_IndentedBlock(
        self,
        node,
    ) -> None:
        self.block_depth += 1

    def leave_IndentedBlock(
        self,
        original_node,
        updated_node,
    ):
        self.block_depth -= 1
        statements = []

        for index, statement in enumerate(updated_node.body,):
            comments = tuple((line for line in statement.leading_lines if line.comment is not None),)
            should_separate = index > 0 and (
                is_section(statement,)
                or is_section(updated_node.body[index - 1],)
                or bool(statement.leading_lines,)
                or isinstance(
                    updated_node.body[index - 1],
                    (libcst.FunctionDef, libcst.ClassDef),
                )
                or isinstance(
                    statement,
                    (libcst.FunctionDef, libcst.ClassDef),
                )
            )
            has_docstring = is_docstring(statement,)
            leading = (libcst.EmptyLine(),) if should_separate or has_docstring else ()
            statements.append(statement.with_changes(leading_lines=leading + comments,),)

        return updated_node.with_changes(
            body=statements,
            indent="    ",
        )

    def leave_Module(
        self,
        original_node,
        updated_node,
    ):
        statements = []

        for index, statement in enumerate(updated_node.body,):
            comments = tuple((line for line in statement.leading_lines if line.comment is not None),)
            has_separator = index > 0 and (
                bool(statement.leading_lines,)
                or isinstance(
                    statement,
                    (libcst.FunctionDef, libcst.ClassDef),
                )
                or isinstance(
                    updated_node.body[index - 1],
                    (libcst.FunctionDef, libcst.ClassDef),
                )
            )
            leading = (libcst.EmptyLine(),) if has_separator else ()
            statements.append(statement.with_changes(leading_lines=leading + comments,),)

        return updated_node.with_changes(body=statements,)

    def leave_Call(
        self,
        original_node,
        updated_node,
    ):
        if not updated_node.args:
            return updated_node

        padding = self.get_padding(original_node,)
        is_vertical = len(updated_node.args,) >= 2
        arguments = []

        for index, argument in enumerate(updated_node.args,):
            if isinstance(
                argument.value,
                libcst.GeneratorExp,
            ) and not argument.value.lpar:
                argument = argument.with_changes(value=argument.value.with_changes(
                    lpar=[libcst.LeftParen(),],
                    rpar=[libcst.RightParen(),],
                ),)

            if is_vertical:
                suffix = padding if index == len(updated_node.args,) - 1 else padding + "    "
                comma = libcst.Comma(whitespace_after=self.get_newline(suffix,),)
            else:
                comma = libcst.Comma(whitespace_after=libcst.SimpleWhitespace("",),)

            arguments.append(argument.with_changes(
                comma=comma,
                whitespace_after_arg=libcst.SimpleWhitespace("",),
            ),)

        return updated_node.with_changes(
            args=arguments,
            whitespace_before_args=self.get_newline(padding + "    ",)
            if is_vertical
            else libcst.SimpleWhitespace("",),
        )

    def leave_FunctionDef(
        self,
        original_node,
        updated_node,
    ):
        parameters = updated_node.params
        positional = list(parameters.posonly_params,) + list(parameters.params,)
        keyword = list(parameters.kwonly_params,)
        star = parameters.star_arg
        star_keyword = parameters.star_kwarg
        count = (
            len(positional,)
            + len(keyword,)
            + int(isinstance(
                star,
                libcst.Param,
            ),)
            + int(star_keyword is not None,)
        )

        if parameters.posonly_params:
            return updated_node

        padding = self.get_padding(original_node,)
        entries = list(parameters.params,)

        if isinstance(
            star,
            (libcst.Param, libcst.ParamStar),
        ):
            entries.append(star,)

        entries.extend(keyword,)

        if star_keyword is not None:
            entries.append(star_keyword,)

        formatted = []

        for index, parameter in enumerate(entries,):
            suffix = padding if index == len(entries,) - 1 else padding + "    "
            whitespace = self.get_newline(suffix,) if count >= 2 else libcst.SimpleWhitespace("",)
            changes = {"comma": libcst.Comma(whitespace_after=whitespace,),}

            if isinstance(
                parameter,
                libcst.Param,
            ):
                changes["whitespace_after_param"] = libcst.SimpleWhitespace("",)

            formatted.append(parameter.with_changes(**changes,),)

        cursor = len(parameters.params,)
        new_star = parameters.star_arg

        if isinstance(
            star,
            (libcst.Param, libcst.ParamStar),
        ):
            new_star = formatted[cursor]
            cursor += 1

        new_parameters = parameters.with_changes(
            params=formatted[: len(parameters.params,)],
            star_arg=new_star,
            kwonly_params=formatted[cursor : cursor + len(keyword,)],
            star_kwarg=formatted[-1] if star_keyword is not None else None,
        )

        return updated_node.with_changes(
            params=new_parameters,
            whitespace_before_params=self.get_newline(padding + "    ",)
            if count >= 2
            else libcst.SimpleWhitespace("",),
        )

    def format_collection(
        self,
        original_node,
        updated_node,
        opening_name,
        closing_name,
    ):
        position = self.get_metadata(
            PositionProvider,
            original_node,
        )
        elements = list(updated_node.elements,)

        if not elements:
            return updated_node

        is_vertical = position.start.line != position.end.line
        padding = self.get_padding(original_node,)
        formatted = []

        for index, element in enumerate(elements,):
            is_last = index == len(elements,) - 1
            suffix = padding if is_last else padding + "    "
            whitespace = self.get_newline(suffix,) if is_vertical else libcst.SimpleWhitespace("" if is_last else " ",)
            formatted.append(element.with_changes(comma=libcst.Comma(whitespace_after=whitespace,),),)

        opening = getattr(
            updated_node,
            opening_name,
        ).with_changes(whitespace_after=self.get_newline(padding + "    ",) if is_vertical else libcst.SimpleWhitespace("",),)
        closing = getattr(
            updated_node,
            closing_name,
        ).with_changes(whitespace_before=libcst.SimpleWhitespace("",),)

        return updated_node.with_changes(
            elements=formatted,
            **{opening_name: opening, closing_name: closing,},
        )

    def leave_Dict(
        self,
        original_node,
        updated_node,
    ):
        return self.format_collection(
            original_node,
            updated_node,
            "lbrace",
            "rbrace",
        )

    def leave_List(
        self,
        original_node,
        updated_node,
    ):
        return self.format_collection(
            original_node,
            updated_node,
            "lbracket",
            "rbracket",
        )

    def leave_Set(
        self,
        original_node,
        updated_node,
    ):
        return self.format_collection(
            original_node,
            updated_node,
            "lbrace",
            "rbrace",
        )

    def format_type_arguments(
        self,
        original_node,
        updated_node,
        attribute,
    ):
        entries = list(getattr(
            updated_node,
            attribute,
        ),)

        if len(entries,) < 2:
            return updated_node

        padding = self.get_padding(original_node,)
        formatted = []

        for index, entry in enumerate(entries,):
            suffix = padding if index == len(entries,) - 1 else padding + "    "
            formatted.append(entry.with_changes(comma=libcst.Comma(whitespace_after=self.get_newline(suffix,),),),)

        return updated_node.with_changes(
            **{attribute: formatted,},
            lbracket=updated_node.lbracket.with_changes(whitespace_after=self.get_newline(padding + "    ",),),
            rbracket=updated_node.rbracket.with_changes(whitespace_before=libcst.SimpleWhitespace("",),),
        )

    def leave_Subscript(
        self,
        original_node,
        updated_node,
    ):
        return self.format_type_arguments(
            original_node,
            updated_node,
            "slice",
        )

    def leave_TypeParameters(
        self,
        original_node,
        updated_node,
    ):
        return self.format_type_arguments(
            original_node,
            updated_node,
            "params",
        )

def format_source(source: str,) -> str:
    for _ in range(12,):
        module = libcst.parse_module(source,)
        formatted = libcst.MetadataWrapper(module,).visit(CodeStyle(source,),).code
        formatted = "\n".join((line.rstrip() for line in formatted.splitlines()),) + "\n"
        formatted = re.sub(
            r"\n[ \t]*\n(?:[ \t]*\n)+",
            "\n\n",
            formatted,
        ).rstrip() + "\n"

        if formatted == source:
            break

        source = formatted

    ast.parse(source,)

    return source

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
    )
    arguments = parser.parse_args()
    failures = []

    for directory in ("src", "test", "scripts"):
        for path in sorted((ROOT / directory).rglob("*.py",),):
            source = path.read_text()
            formatted = format_source(source,)

            if formatted == source:
                continue

            if arguments.check:
                failures.append(str(path.relative_to(ROOT,),),)
            else:
                path.write_text(formatted,)

    if failures:
        raise SystemExit("Code formatting failed: " + ", ".join(failures,) + ".",)

    print("Code formatting checks passed.",)

if __name__ == "__main__":
    main()

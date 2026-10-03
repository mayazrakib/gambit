# `AGENTS.md`

## 1. Scope
This specification governs formatting for internally controlled code in the `chessboard` package.

This specification applies to source code, tests, scripts, configuration containing code, generated code, and code embedded in strings or documentation.

Externally controlled code MAY retain its required format at the compatibility boundary. Internally controlled code MUST conform immediately beyond that boundary.

## 2. General Formatting

- Code MUST use 4 spaces for indentation.
- Code MUST NOT use tabs for indentation.
- Code MUST be syntactically valid.
- Code MUST NOT contain trailing whitespace.
- Text files containing code MUST end with exactly one newline where the format permits it.
- Code MUST NOT contain two or more consecutive blank lines.
- Code MUST avoid unnecessary blank lines, dense formatting, and gratuitous horizontal alignment.
- Code MUST use consistent delimiter and operator spacing.
- Code MUST make logical structure visually apparent.
- Code MUST use explicit grouping when operator precedence could be unclear.
- Statements SHOULD normally occupy separate lines.
- Complex expressions SHOULD use named intermediate values when decomposition improves clarity.
- Deeply nested expressions SHOULD be avoided.
- Trailing commas SHOULD appear in every nonempty comma-separated list where syntax permits and semantics remain unchanged.

## 3. Code Body Structure

Code bodies MUST use logical and conceptual separation.

Within a function, method, branch, loop, class body, test body, or similar executable block:
- Closely related statements forming one operation MUST remain adjacent.
- Conceptually distinct groups of statements MUST be separated by exactly one blank line.
- A control-flow construct and its complete attached continuation chain MUST form its own logical section.
- Exactly one blank line MUST separate a control-flow section from preceding or following statements in the same code body.
- Control-flow constructs include `if`, loops, `switch`, `try`, and equivalent constructs that introduce a block.
- Attached continuations, including `else if`, `else`, `catch`, `finally`, `elif`, and `except`, MUST remain attached to the preceding control-flow construct without a blank line.
- Every `return` statement MUST form its own logical section.
- Exactly one blank line MUST separate a `return` statement from preceding or following statements in the same code body.
- A control-flow construct or `return` statement at the beginning or end of a code body MUST NOT add blank-line padding beside the opening or closing delimiter.
- A `return` statement that is the only statement in a code body MUST NOT have blank-line padding.
- Statements inside a control-flow block form a new code body. This section MUST apply independently within that nested body.
- A blank line MUST NOT appear between a block signature and the first statement in its body.

## 4. Signatures and Calls

- Function signatures, method signatures, constructors, type constructors, generic invocations, and calls with zero or one parameter or argument MUST remain horizontal where syntax permits.
- Function signatures, method signatures, constructors, type constructors, generic invocations, and calls with two or more parameters or arguments MUST use vertical formatting.
- Each vertically formatted parameter or argument MUST occupy its own line.
- The opening delimiter MUST remain on the signature or call line where syntax permits.
- The closing delimiter MUST occupy its own line.
- Vertically formatted parameters and arguments MUST align by indentation rather than manual spaces.
- Vertically formatted parameter and argument lists SHOULD use trailing separators where syntax permits.

## 5. Embedded and Generated Code

Code embedded in strings, templates, HTML, documentation, or generated output MUST follow this specification as though the code were stored in a standalone source file.

Code generators MUST generate conforming output. The authoritative generator or template MUST be corrected when generated output violates this specification.

# `AGENTS.md`

## 1. Scope

Artificial intelligence (AI) agents MUST follow these rules and instructions.

## 2. Keywords

These keywords define normative requirements:

| Keyword | Classification | Meaning |
|---|---|---|
| `MUST` | Obligation | An absolute requirement. |
| `MUST NOT` | Prohibition | An absolute prohibition. |
| `SHOULD` | Recommendation | Expected unless a justified exception exists. |
| `SHOULD NOT` | Discouragement | Discouraged unless a justified exception exists. |
| `MAY` | Permission | Optional; permitted but not required. |

Only uppercase forms are normative.

Normative text MUST use these keywords consistently without weaker or less precise substitutes. Informative text SHOULD avoid them. Keywords MUST NOT be capitalized for emphasis.

## 3. Entry Points

Rules are maintained in `github.com/mayazrakib/agents.git` and read from the local `agents/` checkout.

Before work, agents MUST read and follow [General Rules](/home/mayaz/workspace/agents/rules/GENERAL_RULES.md) and every ruleset its contextual routing requires.

Agents SHOULD batch independent reads and MAY reuse unchanged rules in context. Agents MUST load new or changed applicable rules before affected work.

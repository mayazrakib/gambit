# `AGENTS.md`

This file is generated from canonical shared rules. All repository-root copies MUST remain byte-identical. The requirements below are self-contained; a separate rules checkout is not required.

Before work, agents MUST discover `.ai/skills/*_SKILL.md` at the repository root and relevant project roots and read applicable project skills. Those skills own project-specific commands, constraints, and documented exceptions. Task-specific workflow names below describe required procedures; available global skills MAY supply additional detail without replacing these requirements.

Agents MUST inspect source and consumers before changes, preserve public and persisted contracts, use fresh available code indexes for structural impact, and confirm findings in current source. Broad audits MUST inventory scope and retain coverage and rule findings in task context. Required tests MUST execute without task-result cache reuse. Deletion MUST remain recoverable unless exact permanent removal is explicitly authorized. Commits, pushes, publication, and deployment MUST remain within user authorization. Deployment MUST preserve overrides, verify every intended target and complete managed contents, and distinguish saved files from running-client behavior.

## General Rules

### 2. Keywords

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

### 3. Precedence

Agents MUST resolve instruction conflicts in this order:

1. Higher-priority instructions, required syntax, and external compatibility contracts override these rules only as needed for correctness or compliance.
2. Specific instructions override general instructions.
3. Explicit task requirements override general preferences.
4. These rules override repository, framework, language, tooling, and ecosystem conventions, including existing code.

Exceptions follow these rules:

1. Exceptions MUST have the smallest necessary scope.
2. Internally controlled code MUST conform outside that scope.
3. Agents MUST identify material conflicts that precedence cannot resolve.

### 5. General Agent Behavior

Before material changes, agents MUST inspect relevant implementation, document structure, and working state. Agents MUST prefer the smallest coherent solution satisfying the task and preserve unrelated user changes, behavior, data, compatibility, security, and correctness invariants.

Agents MUST identify required behavior, contracts, and failure cases before changes. Agents SHOULD reuse adequate existing implementations or platform features and prefer local changes before new dependencies or abstractions. Added state, branches, configuration, layers, and public surface MUST address current requirements, demonstrated repetition, or concrete risks. Choices SHOULD favor ease of understanding, modification, and removal over minimal line or token counts.

Agents SHOULD reuse current evidence and batch independent operations to minimize redundant reads, tool calls, and output. Required freshness checks MUST remain intact. Planning and tracking MUST follow the task tiers in Section 9; specialized workflows MAY add requirements within their stated applicability.

Necessary validation, errors, security, accessibility, and compatibility MUST remain explicit and readable. Before completion, agents MUST check for missing behavior and remove their own unjustified additions. Review-only tasks MUST remain read-only.

Agents MUST ask for clarification only when unresolved ambiguity could materially affect correctness, compatibility, security, data, architecture, or scope. Agents MUST identify material ambiguity before dependent changes.

Agents MUST NOT invent requirements or introduce unrelated refactoring, cleanup, formatting, documentation, or architecture changes. Unless intentionally changed, agents MUST preserve requested purpose, canonical terminology, normative force, meaning, and stable requirement identifiers.

Before deleting anything, agents MUST follow Delete. Agents MUST prefer recoverable deletion and obtain explicit user approval for permanently destructive operations. Existing explicit approval for the same action and scope MUST NOT require repeated confirmation.

### 6. Communication

Prose MUST be clear, direct, literal, precise, and plain, with proper sentences, the Oxford comma, and no em dash. Identifiers and structured values are exempt from sentence-form requirements. This applies to chat, output, errors, logs, messages, comments, docstrings, and labels.

AI-generated titles and names MUST be descriptive and use title case for chats, tasks, scheduled items, Spaces, pages, files, folders, and similar user-visible items. Agents MUST apply this default when each item is created, including automatic title generation for every new chat, without requiring a separate user request. Titles and names MUST identify the item's subject or purpose rather than use generic labels. Body text MUST retain normal sentence capitalization. Explicit user-supplied names, required system formats, identifiers, file extensions, and canonical filenames MUST retain their required form; applicable naming rules MUST govern separators, prefixes, and dates.

Chat MUST state material caveats, distinctions, alternatives, exceptions, and uncertainty. Technical explanations SHOULD lead with the conclusion.

For tasks requiring tools, agents SHOULD give a brief opening and meaningful progress updates during extended work. Final responses MUST concisely report results and, where applicable, changes, verification, and remaining limits. Agents MUST omit routine narration and SHOULD explain only tradeoffs affecting decisions or maintainability. Brevity MUST NOT hide required information or reduce task scope, correctness, or required verification.

### 7. Verification

Modified artifacts SHOULD receive the strongest relevant verification within scope and environment. Agents MUST report relevant failures and material verification gaps, distinguishing pre-existing failures where possible. Agents MUST NOT report unexecuted or unsuccessful checks as passed.

Required checks, including applicable regression checks, MUST remain within execution restrictions. Efficiency MUST NOT reduce required verification.

### 9. Task Tiers

Agents MUST select the lightest tier that covers the task's scope and risk and reassess it when scope changes. Tiers govern workflow effort, not authorization or preservation requirements.

| Tier | Applicability | Required evidence and tracking |
|---|---|---|
| Small edit | Local changes preserving behavior and dependencies, such as copy, formatting, or a bounded internal cleanup. | Inspect relevant source and working state, preserve contracts, and perform focused checks. Graph startup, repository inventories, and full ledgers are not required. |
| Behavior or dependency change | Changes to behavior, symbol identity, interfaces, dependencies, or cross-file relationships. | Inspect consumers and dependencies, establish relevant baseline evidence, and run affected regression checks. Use fresh graph evidence when structural analysis applies and a graph interface is available. Record affected scope and verification. |
| Broad refactor or systematic audit | Repository-wide or subsystem-wide assessment, structural refactoring, or systematic compliance work. | Inventory the requested scope, maintain coverage and rule ledgers, and assess or validate dependency-aware batches through the Refactor skill. |

Small diffs affecting compatibility, security, persistence, concurrency, or other material risks MUST use at least the behavior or dependency tier. Broad scope MUST use the broad tier even when each individual change is mechanical. Audits and plans MUST remain read-only regardless of tier.

## Code Rules

### 2. Code Style Authority

Agent-generated and agent-modified code MUST follow these rules. Directly modified existing code SHOULD conform where local, safe, and in scope.

Required external forms MAY differ at language, runtime, framework, protocol, wire, public application programming interface (API), database, serialization, generated-code, foreign-function, callback, or other external compatibility boundaries.

### 3. General Code Formatting

Code MUST satisfy these rules:

- Indentation MUST use 4 spaces and MUST NOT use tabs.
- Syntax MUST be valid.
- Trailing whitespace MUST NOT occur.
- Code text files MUST end with exactly one newline where permitted.
- Blank lines MUST be necessary and MUST NOT be consecutive.
- Formatting MUST NOT be dense, compressed, or gratuitously space-aligned.
- Delimiter and operator spacing MUST be consistent.
- Logical structure MUST remain visually apparent.
- Unclear operator precedence MUST use explicit grouping.

Nonempty comma-separated lists SHOULD have trailing commas, horizontally or vertically, where permitted. Commas MUST NOT invalidate syntax or change meaning, including creating tuples or array holes.

Statements SHOULD occupy separate lines. Complex expressions SHOULD use named intermediate values when clearer. Deep nesting SHOULD be avoided.

### 4. Blank Lines and Code Body Structure

Apply these rules independently inside functions, methods, branches, loops, classes, tests, Structured Query Language (SQL) statements, and similar bodies:

- Related one-line statements and declarations MUST remain adjacent within a logical or conceptual group. Distinct groups MUST have exactly one separating blank line.
- Each block-like construct MUST form a separate group with exactly one blank line between it and adjacent groups. Block-like constructs include function and method definitions, control-flow constructs, vertically formatted calls and signatures, and multiline declarations, initializers, and assignments.
- Grouping MUST apply recursively within each block. Entries within a single parameter, argument, member, or collection list MUST NOT receive blank lines solely because the enclosing construct is multiline. Logical or conceptual subdivisions MAY have one separating blank line.
- Preconditions and guards MUST be separated from subsequent independent operations. Preparatory computations SHOULD be separated from operations consuming their results when they form distinct logical steps.
- Each `return` MUST form a separate logical section with one blank line between adjacent sections.
- Control flow includes `if`, loops, `switch`, `try`, and equivalents. Attached `else if`, `else`, `catch`, `finally`, `elif`, and `except` continuations MUST NOT have separating blank lines.
- Sections MUST NOT have blank-line padding at body boundaries. A lone `return` MUST NOT have padding.
- Block signatures MUST directly precede their first statements without blank lines.

Module-level declarations MUST be grouped by purpose, visibility, and state characteristics, with exactly one blank line between groups. Related one-line constants MUST remain adjacent without blank lines. Exported constants, exported mutable state, internal constants, and internal mutable state SHOULD form distinct groups where applicable. Within a mutable-state group, simple flags, counters, and similar state SHOULD precede complex mutable references.

Object members MUST be distinct declarations. Constructors, methods, getters, and setters MUST form separate groups under the block-like construct rule. Related one-line fields and member declarations MUST remain adjacent. A member's closing delimiter MUST NOT share the next member declaration's line. Member delimiters and commas MUST attach to the preceding member.

### 5. Vertical Signature and Call Formatting

Signatures, calls, constructors, type constructors, generics, type parameter lists, decorators, and similar constructs MUST be horizontal with zero arguments or parameters and, where valid, with one.

Constructs with two or more arguments or parameters MUST be vertical where permitted, one per line. Opening delimiters MUST remain on the signature or call line where supported; closing delimiters MUST occupy their own line. Alignment MUST use indentation, not manual spacing. Trailing non-comma separators SHOULD appear where supported; commas follow General Code Formatting.

SQL types, columns, and function signatures MAY remain horizontal when vertical formatting materially reduces readability. This exception applies only to this section.

### 6. Naming

#### 6.1 PascalCase

Classes, types, interfaces, protocols, traits, contracts, abstractions, typed schemas, domain objects, value objects, data transfer object types, exception types, type aliases, generics, and structured object definitions MUST use `PascalCase`.

#### 6.2 snake_case

Functions, methods, variables, parameters, local values, modules, packages, supported namespaces, source filenames, database columns and tables, configuration keys, and internally controlled JSON keys, commands, events, metrics, log fields, and identifiers MUST use `snake_case`.

#### 6.3 Constants

Constants MUST use `UPPER_SNAKE_CASE`.

#### 6.4 Enumerations

Enumeration members MUST use `UPPER_SNAKE_CASE`. Internally controlled serialized, persisted, displayed, and wire values MUST use lowercase, space-separated text. Machine-only values MAY use another representation when whitespace is unsuitable, but MUST remain lowercase and semantically clear.

#### 6.5 Boolean Names

Booleans and boolean-returning functions MUST begin with predicates such as `is_`, `has_`, `can_`, `should_`, `does_`, `was_`, or `will_`. Negated names SHOULD NOT be used; double negatives MUST NOT be used.

#### 6.6 Function and Method Names

Function and method names MUST begin with action-describing verbs. Noun-only names MUST NOT be used unless externally required.

#### 6.7 Type and Object Names

Class, type, object, contract, and abstraction names MUST be nouns or noun phrases. Generic names such as `Manager`, `Helper`, `Utility`, `Processor`, `Handler`, `Thing`, `Data`, and `Object` SHOULD NOT be used unless they identify stable domain concepts.

Names MUST NOT end in `Impl`. Interfaces MUST NOT have an `I` prefix. Abstract types MUST NOT have an `Abstract` prefix unless needed to avoid genuine ambiguity.

#### 6.8 Semantic Naming

Names MUST communicate domain meaning, prefer complete words, avoid unnecessary abbreviations and unexplained acronyms, use one canonical term per concept across layers, and avoid changeable implementation details.

Single-character names MUST NOT be used except for conventional mathematics, very small local indices, coordinates, and conventional generic parameters. Vague names SHOULD NOT replace precise domain names.

#### 6.9 Acronyms

Acronyms MUST follow surrounding naming case. Well-known acronyms MAY remain abbreviated when clearer.

#### 6.10 Collections

Multiple-value collections MUST normally have plural names. Container suffixes SHOULD NOT appear unless the structure has semantic importance.

#### 6.11 Quantities and Units

Quantity names MUST include units unless encoded by types. Variables MUST NOT change semantic units during their lifetimes. Conversions SHOULD occur at explicit boundaries.

#### 6.12 Private and Internal Names

Leading underscores MUST NOT solely indicate privacy. Native visibility mechanisms MUST be preferred; otherwise, privacy SHOULD use module boundaries, scope, architecture, or contracts rather than punctuation.

### 7. Literals and Constants

Semantically important or reused literals MUST use names rather than repeated magic values. Constant names MUST describe meaning, not literal values. Sentinels MUST have explicit semantics. Ambiguous domain-unit numbers SHOULD use named constants or typed values.

### 8. Imports

Imports MUST be explicit, used, and free of wildcards. Symbols MUST retain exported names without aliases for internal style compliance. Default imports MUST use documented canonical names where available. Conflicting internally controlled names MUST change.

Paths MUST be stable and direct. Import-time side effects MUST NOT occur unless explicitly required. Imports MUST be grouped by dependency origin and purpose. Related imports SHOULD be grouped by subsystem or responsibility.

Groups MUST follow this order:

1. Standard-library imports.
2. External dependencies.
3. Internal type-only imports, where supported.
4. Internal value imports.

External type-only imports MAY remain with their corresponding dependencies. Package API imports MUST be separated from worker, WebAssembly, and other asset imports. Groups MUST have exactly one separating blank line; related one-line imports within each group MUST remain adjacent. Group members MUST sort alphabetically by path, then symbol, where permitted.

### 9. Embedded and Generated Code

Rendered embedded, escaped, templated, interpolated, and generated code MUST conform as standalone code, including inline code, strings, shell commands, HTML, dynamic templates, generated source, SQL, executable configuration, tests, migrations, and executable examples.

Generators MUST produce conforming output. Non-conforming output MUST be repaired in its authoritative generator or template, not through repeated manual formatting.

### 10. Comments

Comments MUST NOT restate obvious code and SHOULD explain only non-obvious intent, constraints, invariants, algorithms, compatibility, counterintuitive decisions, or justified workarounds.

Agents MUST NOT add, remove, or modify comments unless requested, needed for existing comment correctness, or needed to explain a non-obvious invariant introduced by the task.

### 11. Documentation

README files and standalone documentation MUST NOT change unless requested, required by an intentional public-interface change, or needed to prevent materially false documentation.

### 12. Dependencies and Existing Implementations

Before adding implementations or dependencies, agents MUST search standard-library functionality, project dependencies, and repository implementations, and reuse adequate existing implementations. Dependencies MUST NOT be added for trivial functionality and MUST satisfy known runtime, build, deployment, and licensing constraints.

### 13. SQL Structure and Formatting

Internally controlled SQL MUST have clear structural sections.

#### 13.1 Front Matter

Dimensional and entity-like tables SHOULD begin with applicable identity columns ordered `id`, `key`, `name`, and `label`. Other stable or primary descriptive identity fields MAY follow.

`id` MUST identify the row or canonical object. `key` SHOULD identify a stable logical identity, `name` SHOULD identify the canonical human-readable name, and `label` SHOULD identify a separate display value where applicable. Identity semantics MUST remain distinct and MUST NOT be duplicated in the business body.

#### 13.2 Business Body

Domain columns MUST keep related fields adjacent, follow stable domain ordering, and avoid arbitrary mixing with identity or system metadata.

#### 13.3 Back Matter

System-maintained lifecycle, version, audit, and historical fields MUST follow business columns, remain adjacent, and use the `system_` prefix for internal row and version lifecycle metadata. Business-valid and system-valid time MUST remain distinct. Domain timestamps MUST NOT appear in system metadata.

Persistent tables MUST include `system_created_at` and `system_updated_at` where technically applicable.

Slowly Changing Dimension Type 2 (SCD2) preserves historical row versions. Dimensional tables retaining history SHOULD use applicable SCD2 fields, including `system_first_seen_at`, `system_last_seen_at`, `system_valid_from`, `system_valid_to`, `system_version`, and `system_is_active`.

Fact tables SHOULD use only system fields needed for creation, update, audit, or technical lifecycle unless historical versioning is explicitly required.

#### 13.4 SQL Statements

SQL MUST use explicit joins without implicit Cartesian products. External values MUST be bound through parameters and MUST NOT be interpolated.

SQL MUST use deterministic ordering where order matters, explicit column lists for durable `INSERT` operations, and explicit material transaction boundaries. Durable application code MUST NOT use `SELECT *` without explicit justification.

Expressions and joins MUST preserve type semantics. Ambiguous references MUST use explicit aliases and qualified columns. Predicates MUST reflect query business meaning.

### 14. Tests

Behavior changes SHOULD have tests where a relevant suite exists. Tests MUST be deterministic where possible and reuse suitable fixtures and helpers. Tests MUST NOT use arbitrary sleeps where observable synchronization exists.

Valid tests MUST NOT be weakened, skipped, deleted, or altered merely to pass unless intended behavior changed. External-system-dependent behavior SHOULD use integration tests.

### 15. Code Graph

When structural analysis is needed under Task Tiers and an interface is available, agents MUST use fresh graph evidence for structure, implementation discovery, dependencies, impact, and cross-file behavior. Before changing symbol names, signatures, behavior, or locations, agents MUST inspect indexed callers and dependencies. When structural analysis is required, implementation searches MUST include relevant indexes.

Prose, formatting, and exact-text edits MAY omit graph queries when structural or behavioral analysis is unnecessary.

Graph results MUST provide navigation and relationship evidence without replacing current source or behavioral verification. Before completeness claims, agents MUST inspect parsing failures, exclusions, and truncation, and retrieve omitted relevant results through pagination or narrower queries.

Missing symbols, callers, or edges MUST NOT establish unused or independent code. Agents MUST inspect source and use ordinary search for gaps, dynamic relationships, and exact text.

For required structural analysis and graph operations, agents MUST follow Code Graph. Supported repeated syntax searches and structural rewrites MUST follow Structural Rewriting.

### 16. Refactoring

Requested repository or subsystem refactoring, architectural cleanup, and systematic audits MUST follow Refactor without expanding scope or implementing audit-only requests.

### 17. Affected Verification

Verification selection MUST account for available task definitions, inputs, outputs, and dependencies. Task dependencies MUST NOT be inferred solely from the code graph. Repositories without a task graph MUST use their existing build and test definitions.

Required verification MUST execute checks rather than reuse workflow-cached results. Valid existing evidence MAY inform scope and baselines but MUST NOT be presented as a fresh run. Ordinary dependency and build artifacts MAY remain. Task selection MUST NOT authorize restricted tests.

Before selecting or running verification tasks, agents MUST follow Affected Verification.

### 18. Browser Verification and Diagnosis

Agents MUST distinguish web renderer results from Electron integration. Main-process, preload, native, and window-lifecycle checks MUST use repository Electron tests or Playwright's experimental `_electron` API. Browser-only results MUST NOT be reported as native Electron verification.

Browser work MUST follow Browser Verification, loaded only when an actual browser is needed.

### 19. Command-Line Tools

Workspace commands MUST follow Command Line. Structural searches and rewrites MUST follow Structural Rewriting.

### 20. Repository Standards and Language Routing

All owned or maintained repositories MUST follow Repository Rules. README work MUST follow README Rules. Configuration, dependencies, testing, benchmarks, GitHub, security, and licensing work MUST follow Engineering Rules. Design systems and assets MUST follow Design Rules.

Agents MUST load only the applicable language rules: Python, Rust, JavaScript, and TypeScript. Other languages MUST follow this ruleset and required toolchain contracts; agents MUST add a language-specific ruleset when recurring language-specific requirements justify one.

Repository initialization, standardization, README maintenance, configuration, dependency maintenance, CI/CD setup, design synchronization, and compliance audits MUST follow Repository Standards. That skill MUST NOT expand an authorized local edit into a repository migration.

## Repository Rules

### 2. Authority and Scope Terms

The `agents` repository MUST remain the authoritative source for shared standards, templates, and verification tooling. Each requirement MUST have one authoritative definition; summaries and generated copies MUST derive from it.

A repository is an independently version-controlled Git repository. A monorepo contains multiple independently structured projects. A subproject is a distinct application, package, library, or codebase within a repository. The repository root is the Git top-level directory; a project root is the root of an independently configured project or subproject.

Repository-level requirements MUST occur once per repository, including monorepos. Codebase-level requirements MUST apply to independently configured subprojects. Shared workspace manifests, lockfiles, and configuration MUST remain at the tool-required workspace root; agents MUST NOT duplicate them for appearance.

### 3. Directory Organization

Internally controlled directories MUST use these names where their purpose exists. Agents MUST NOT create empty directories solely for compliance.

| Path | Purpose |
|---|---|
| `src/` | Application, package, and library source. |
| `tests/` | All automated tests. |
| `tests/perf/` | Performance and profiling tests. |
| `tools/` | Developer tools and utilities. |
| `tools/scripts/` | Development and operational scripts. |
| `database/` | Database resources. |
| `database/migrations/` | Database migrations. |
| `assets/` | Static and multimedia resources. |
| `assets/icons/` | Icons and favicons. |
| `assets/images/` | Other vector and raster images. |
| `assets/logos/` | Logos and brand marks. |
| `showcase/` | Demonstrations, examples, and playground projects. |
| `benchmarks/` | Dedicated benchmarks and benchmarking infrastructure. |
| `build/` | Generated build outputs and artifacts. |
| `design/` | Repository-level design system. |
| `.ai/skills/` | Project-specific AI skills. |
| `.github/workflows/` | GitHub Actions workflows. |

Test directories MUST be named `tests`, never `test`. Existing duplicate test directories MUST be consolidated during authorized structural migrations. Performance tests and dedicated benchmarks MUST retain distinct purposes; neither MUST be confused with saved benchmark results. New canonical naming supersedes earlier shared `benchmark/` conventions.

Moves MUST update imports, package discovery, runtime paths, scripts, manifests, documentation, build contexts, CI, and deployment references. Framework-required discovery, public entry points, migration checksums, and tool-required locations MUST remain compatible. Source filenames and internally controlled names MUST follow Code Rules Section 6; required canonical filenames MUST retain their exact form.

### 4. Configuration and Environment

Configuration and metadata MUST reside at the applicable project or workspace root where supported. Tool-required paths, GitHub configuration, and explicitly scoped subproject configuration MAY remain in their required locations. Configuration variants MUST use `<config-name>.<variation>.<config-extension>` with consistent identifiers such as `development`, `production`, and `test`. Required names such as `.env.example` and `pyproject.toml` MUST remain unchanged.

Every Git repository MUST have a root `.gitignore`. Ignore sections MUST use relevant title-case headings in the form `# Environment`, `# Build`, or `# Temporary Files`. Dependency lockfiles MUST be committed and MUST NOT be ignored. Source, migrations, manifests, and required resources MUST NOT be ignored.

Every project requiring secrets or environment configuration MUST have a root `.env.example` listing every required variable. Values requiring user configuration MUST use exactly `<CHANGE-ME>`. Comments SHOULD explain non-obvious variables. Examples MUST contain no credentials and MUST remain synchronized with actual requirements. Real `.env` and sensitive local files MUST be ignored. Docker build contexts MUST have an appropriate `.dockerignore` at their context root, normally the repository root, excluding secrets and unnecessary files while retaining required resources.

Every independently configured codebase MUST have `.tool-versions` with verified compatible pins for relevant supported tools. Redundant `.python-version`, `.nvmrc`, and similar files SHOULD be replaced during authorized migrations; required external-tool files MUST remain and agree with the canonical pins.

Every repository MUST have the byte-identical canonical `.editorconfig`, generated or copied from the authoritative template. It MUST define UTF-8, LF, a final newline, trailing-whitespace handling, four-space indentation, and necessary file-type exceptions. Generated and language-required forms MUST remain valid.

Git attributes MUST preserve LF checkouts of byte-identical shared files across operating systems, including when a user's Git configuration enables automatic CRLF conversion. The canonical `.gitattributes` template supplies this behavior while preserving required Windows command-script endings.

### 5. Agent Instructions

Every repository, including a monorepo, MUST have a byte-identical root `AGENTS.md` generated from the canonical rules. Its shared general coding and repository requirements MUST be self-contained and MUST NOT depend on links to the `agents` checkout. Repository descriptions and exceptions MUST NOT diverge this file. Agents MUST regenerate and verify it whenever its authoritative rules change.

Agents MUST discover `.ai/skills/*_SKILL.md` at the repository root and each relevant project root and read applicable skills before work. Project-local requirements and necessary exceptions MUST live there, with applicability, inputs, workflow, verification, and failure handling. Migrations MUST preserve existing skill instructions, assets, references, and functionality without redundant copies. Nested instruction files required by external tools MUST retain their required scope without altering the common root instructions.

Canonical templates MUST remain in `agents/templates/repository/`. `scripts/repository_standards.py` MUST generate the shared root instructions and check exact equality without silently fixing target repositories. Deployment MUST include the templates and verifier in managed bundles and the workflow plugin.

### 6. Compatibility and Exceptions

Consistency MUST apply across languages, frameworks, project sizes, and architectures wherever technically possible. Unnecessary complexity MUST NOT be introduced. Agents MUST preserve functionality, public APIs, supported workflows, build systems, deployment environments, security, data, user changes, and unrelated work.

Necessary exceptions MUST identify the exact path, affected requirement, concrete compatibility or architectural reason, permitting authority, and verification. Exceptions MUST be minimal and explicit in a project-local skill. Missing evidence MUST remain unknown, not a speculative exception. Automated checks MUST report excepted findings separately rather than treating them as unconditional compliance.

For conflicts within repository standardization, agents MUST prioritize security, licensing, and data integrity, then existing correctness, required toolchain and platform constraints, explicit canonical requirements, recommendations, and cosmetic uniformity. Higher-priority instructions retain precedence. Agents MUST implement the closest technically correct authorized solution and document unresolved conflicts without weakening tests or security checks.

## Readme Rules

### 2. Title and Metadata

Every README MUST start with a level-one heading containing the actual project name in inline code, such as `# ` followed by `` `gambit` ``. No banner, image, or introductory text MUST precede it.

Immediately after the title, exactly eight badge or metadata categories MUST appear in this order: `Version`, `License`, `Languages`, `Frameworks`, `Compatibility`, `Build`, `Tests`, and `Vulnerabilities`. The canonical template's Shields.io flat-square pattern, label capitalization, compact values, and color conventions MUST be shared across repositories. Reliable dynamic status SHOULD be preferred over static claims.

Version MUST reflect actual project metadata. License MUST identify the actual license or `Proprietary`. Languages and Frameworks MUST identify actual languages, fundamental frameworks, and significant dependencies. Compatibility MUST identify verified supported operating systems and CPU architectures. Build MUST reflect actual CI and build status. Tests MUST report verified status and coverage where measured. Vulnerabilities MUST distinguish first-party and dependency findings where practical and include known severity and relevant context.

Missing information MUST use truthful values such as `Unknown`, `Not measured`, or `Not configured`. Agents MUST NOT fabricate versions, compatibility, coverage, build results, vulnerability counts, or security assurances. Reliable automation SHOULD maintain badges; unavailable scanning MUST NOT become a zero-vulnerability claim.

### 3. Required Sections

Every README MUST contain these exact level-two headings, once each, in this order. Additional detail SHOULD use level-three headings or linked documentation.

| Heading | Required content |
|---|---|
| `## 1. Introduction` | Purpose, problem, intended users, and concise project description. |
| `## 2. Usage` | Verified prerequisites, installation, initialization, minimal configuration, and executable basic examples forming the shortest practical path to a working result. |
| `## 3. Features` | All significant implemented capabilities, grouped logically, with planned capabilities distinguished. |
| `## 4. Architecture` | Actual components, layers, data flow, interfaces, storage, execution model, integrations, and material decisions. Use accurate GitHub-renderable Mermaid when helpful. |
| `## 5. Dependencies` | All declared direct runtime, development, and build dependencies in the required table. |
| `## 6. Roadmap` | Evidence-based completed, active, and planned work, using concise checklists where helpful. No invented commitments or deadlines. |
| `## 7. Contributing` | The canonical Contributing text with only project-specific values substituted. |
| `## 8. License` | The canonical License text with the actual licensing classification and terms. |

The dependency table MUST use exactly `Dependency`, `Version`, and `Use` as its columns. Manifests and lockfiles MUST supply exact resolved or pinned versions where available; otherwise, the declared constraint and unresolved state MUST be explicit. Runtime, development, build, and package ownership MUST be distinguishable in the Dependency or Use cells. Transitive dependencies MUST remain distinguishable from direct declarations. Versions MUST NOT be invented.

### 4. Shared Text and Accuracy

The Contributing section MUST use the following exact paragraph, substituting only the setup, test, and build commands:

Read `AGENTS.md` and the applicable skills in `.ai/skills/` before contributing. Set up the development environment with `<INIT_COMMAND>`. Follow the repository conventions, preserve supported behavior, and add relevant tests for behavior changes. Run `<TEST_COMMAND>` and `<BUILD_COMMAND>` before opening a pull request. Describe the change, its purpose, and the validation results in the pull request.

The License section MUST use the following exact two-paragraph form, substituting only actual project, classification, and terms:

`<PROJECT_NAME>` is `<LICENSE_CLASSIFICATION>`. `<LICENSE_TERMS>`

See `ACKNOWLEDGEMENTS.md` for third-party notices and attributions.

For open source, classification MUST be `licensed under the <LICENSE_NAME> license`, and terms MUST be `See LICENSE for the complete license text.` For proprietary projects, classification MUST be `proprietary`, and terms MUST be `All rights are reserved. Use, modification, and redistribution require authorization.` Uncertain licensing MUST remain explicitly unresolved until classification is verified; agents MUST NOT select a license on the owner's behalf.

Heading hierarchy, ordering, Markdown, tables, fences, badges, terminology, capitalization, precise claims, tone, and shared sentence structure MUST remain consistent. Agents MUST preserve accurate existing instructions and substantive content when restructuring a README, moving extensive operational detail into appropriate documentation only when necessary.

## Engineering Rules

### 2. Dependencies

Dependencies and relevant runtimes, frameworks, build tools, and testing tools MUST use the newest verified compatible versions. Before an authorized upgrade, agents MUST inspect constraints, verify available releases from authoritative sources, assess compatibility and licensing, regenerate applicable lockfiles through the package manager, run relevant tests and builds, and investigate failures. Agents MUST retain a compatible pin and document the reason when a newer release cannot safely satisfy supported behavior. Agents MUST NOT blindly upgrade or introduce dependencies for trivial functionality.

All applicable dependency lockfiles MUST be tracked, including workspace-root lockfiles. A shared workspace lockfile MUST NOT be duplicated in members. Dependency and build caches MAY accelerate installation; caches MUST NOT substitute for executed verification. Reproducible installation MUST use locked or frozen modes in CI.

### 3. Taskfiles

Every independently configured codebase MUST provide `Taskfile.yml` at its project root. Tasks MUST use lowercase names, concise descriptions, consistent output, explicit argument handling, propagated failure status, and cross-platform commands appropriate to supported systems. Required shared configuration MAY be included from the workspace root without duplicating manifests or lockfiles.

| Task | Behavior |
|---|---|
| `default` | Display available tasks or delegate to `help`. |
| `help` | Describe available tasks. |
| `init` | Initialize the actual development environment. |
| `test` | Execute relevant automated tests. |
| `build` | Build the project or distributable artifacts. |

Task behavior MUST be semantically consistent across repositories. Tasks MUST NOT claim unavailable capabilities; interpreted or documentation projects MUST describe their real artifact validation or packaging. Unnecessary aliases MUST NOT be introduced. `format` and `lint` tasks MUST NOT exist. Initialization, test, and build tasks MUST NOT invoke automatic formatting or linting. Developers or agents MUST explicitly control formatting and linting outside these tasks.

### 4. Testing and Benchmarks

Automated tests MUST use `tests/`, performance and profiling tests MUST use `tests/perf/`, and dedicated benchmarks MUST use `benchmarks/`. Tests MUST preserve framework discovery, isolate destructive operations, use relevant fixtures, and synchronize through observable state instead of arbitrary sleeps. Tests MUST NOT be weakened, skipped, deleted, or suppressed merely to establish compliance. Behavior changes SHOULD receive meaningful regression coverage.

Benchmarks MUST identify the revision, workload, toolchain, environment, units, repetitions, and aggregation. Comparative claims MUST use compatible conditions and distinguish executable benchmark infrastructure from saved results. Browser results MUST NOT establish native Electron, packaged-application, CI, or production behavior. Required checks MUST execute without workflow result-cache reuse.

### 5. Git and GitHub

Agents MUST inspect Git boundaries, revision, dirty state, tracked paths, and nested repositories before broad changes. Commits, pushes, releases, and deployment MUST remain within authorization, preserve unrelated work, and verify remote revisions. Existing project history and public interfaces MUST NOT be rewritten merely for uniformity.

Every Git repository MUST contain `.github/workflows/`, `.github/dependabot.yml`, `.github/issue_template.md`, `.github/pull_request_template.md`, and `.pre-commit-config.yaml`. Canonical templates MUST supply their shared structure, terminology, and conventions. Templates MUST be recognized by GitHub; required alternate discovery paths MAY be used without conflicting duplicates.

CI SHOULD use `ci.yml`, security SHOULD use `security.yml`, and release automation SHOULD use `release.yml` only when required. Workflows MUST have consistent descriptive jobs, push and pull-request verification, least-privilege permissions, explicitly pinned action revisions, actual dependency installation, lockfile-keyed caches where useful, build verification, tests, relevant security scans, and clear status reporting. Release permissions and triggers MUST remain restricted to authorized publication. Untrusted pull requests MUST NOT gain write tokens or secrets through privileged execution. README status MUST correspond to actual workflow jobs and results.

Dependabot MUST monitor GitHub Actions and every supported applicable ecosystem discovered from real manifests at its actual directory. The canonical schedule MUST be weekly on Monday at `09:00` in `Australia/Sydney`; update groups SHOULD separate compatible development or patch updates from major updates. Unsupported ecosystems, unused labels, and unnecessary update entries MUST NOT be invented.

Issue templates MUST request a reproducible problem, environment, expected behavior, actual behavior, and reproduction steps. Pull-request templates MUST request purpose, changes, validation evidence, and relevant risks. Both MUST direct contributors to `AGENTS.md`.

Pre-commit MUST provide non-mutating checks for accidental secrets, merge conflict markers, invalid configuration, oversized staged files, and applicable basic hygiene. Language-specific checks MAY be added when relevant. Revisions MUST be pinned and inputs MUST remain scoped. Hooks MUST NOT implicitly reformat or rewrite code. Security checks MUST NOT be disabled or failures suppressed to achieve compliance.

### 6. Security and Licensing

Agents MUST preserve secrets, authentication, local overrides, and trust decisions. Examples, commits, logs, artifacts, and CI output MUST contain no real secret values. Security findings MUST identify first-party versus dependency scope, severity where known, scan tool and revision, and limitations. A clean scan MUST NOT imply absence of all vulnerabilities.

Every open-source repository MUST have a root `LICENSE` containing the complete actual license text. Proprietary repositories MUST NOT have a root `LICENSE` under this convention; their README badge MUST say `Proprietary` and their License section MUST reserve rights and require authorization. Agents MUST NOT change license terms or infer third-party rights from a missing file. Uncertain ownership or classification MUST be resolved before rights-affecting changes.

Every repository MUST have a root `ACKNOWLEDGEMENTS.md` using the canonical format and retaining applicable third-party licenses, copyright notices, attributions, acknowledgements, and other required notices. Repository-wide notices MUST remain at the repository root unless distribution or licensing requires additional copies. Legally required notices MUST NOT be omitted, shortened, or consolidated in violation of their terms.

## Design Rules

### 2. Canonical Design

Repositories requiring a design system MUST locate it at repository-root `design/`, including monorepos. Independent competing systems MUST NOT be created in arbitrary application or subproject directories.

| File | Content |
|---|---|
| `design/colors.json` | Primitive and semantic colors. |
| `design/typography.json` | Font families, weights, line heights, and type scales. |
| `design/spacing.json` | Spacing increments and sizing scales. |
| `design/elevation.json` | Shadows, z-index layers, border radii, and elevation. |

These four files MUST be byte-identical across applicable repositories. The existing Meson design system and token values MUST remain authoritative. Agents MUST inspect actual Meson source files, record their revision and paths, validate their structure, and copy verified canonical bytes. Agents MUST NOT invent tokens, silently substitute template values, or modify shared values independently in consumers.

If Meson has not yet exposed the four canonical files, agents MUST report the missing source mapping and defer synchronization until an authorized Meson migration establishes it. Existing Meson values MUST remain the authority during that migration. Agents MUST NOT modify Meson solely because a consumer requests synchronization.

### 3. Project Themes and Assets

Projects MAY define `design/palette.json` and `design/theme.json` for project-specific palettes, default light and dark themes, and additional supported themes. Schemas, naming, organization, and token references SHOULD remain consistent across repositories. Project-specific files MUST compose or reference shared tokens and MUST NOT redefine their canonical values. The schemas in `templates/repository/design/` define document containers and reference forms without supplying invented Meson values.

Icons and favicons MUST use `assets/icons/`. Other vector and raster images MUST use `assets/images/`. Logos and brand marks MUST use `assets/logos/`. This applies to Meson and associated products as well as other applicable repositories. Agents MUST avoid redundant asset roots and preserve necessary framework loading paths through compatible references or documented tool-required exceptions.

### 4. Verification

Design checks MUST compare bytes with the actual authoritative Meson checkout, validate JSON documents and applicable schemas, and verify token references through the consuming build. A schema or identical file alone MUST NOT establish correct rendering, accessibility, or runtime integration. An unavailable or incomplete authoritative source MUST remain an explicit verification gap.

## Python Rules

### 2. Packaging and Toolchains

Python projects MUST use `uv`, root `pyproject.toml`, and committed `uv.lock`. A uv workspace MUST share its root lockfile. Python and uv versions MUST be pinned through `.tool-versions` at the independently configured codebase root. CI MUST use `uv sync --locked` and execute checks with the locked environment.

Modern packaging MUST be used. New packages MUST use a compatible modern build backend, such as `uv_build` or Hatchling, when a backend is required. Setuptools MUST NOT be the default. Applications that do not build packages MAY use uv's non-package mode. Existing `setup.py` or `setup.cfg` arrangements SHOULD migrate when compatible and authorized; bootstraps or external tools requiring requirements exports MAY retain generated pinned exports synchronized with the lockfile.

### 3. Code, Tests, and Verification

Packages MUST use `src/` and automated tests MUST use `tests/` where package discovery supports those paths. Python code MUST follow shared naming, imports, four-space indentation, grouping, and vertical-call rules. Externally required special methods and library names MUST preserve their contracts.

Dependencies MUST distinguish runtime, development, and build requirements. Agents MUST verify imports, test discovery, supported Python versions, and built distributions where applicable after packaging changes. Taskfile commands MUST delegate to actual uv-managed initialization, tests, and builds without automatic formatting or linting.

## Rust Rules

### 2. Cargo and Toolchains

Rust projects MUST use Cargo, `Cargo.toml`, and a committed `Cargo.lock`, including libraries. Cargo workspaces MUST keep the authoritative shared manifest configuration and lockfile at the workspace root. Package metadata, workspace dependency ownership, feature configuration, and supported Rust versions MUST remain consistent.

`.tool-versions` MUST pin the supported Rust toolchain at each independently configured codebase root. A required `rust-toolchain.toml` MAY remain for external compatibility and MUST agree with the canonical pin. CI MUST use locked dependency resolution, including `cargo test --locked` and `cargo build --locked` with the relevant workspace and feature selections.

### 3. Code, Tests, and Verification

Source MUST use `src/`; integration tests MUST use `tests/`. Inline Rust unit-test modules MAY remain beside the implementation when required for private-item testing. Dedicated benchmarks MUST use `benchmarks/` with explicit Cargo targets when Cargo's default `benches/` discovery is replaced. Performance and profiling tests MUST use `tests/perf/`.

Shared naming and formatting MUST apply where valid; compiler-required trait methods, macros, and foreign-function contracts MUST remain intact. Agents MUST verify affected features, target platforms, test discovery, and public crate APIs after structural changes. Build outputs SHOULD use `build/` through Cargo configuration where supported without breaking consumers.

## Javascript Rules

### 2. npm and Configuration

JavaScript projects MUST use npm, `package.json`, and a committed `package-lock.json` at the applicable npm project or workspace root. A workspace MUST NOT mix package managers or duplicate its root lockfile in members. Node.js and npm MUST have verified compatible pins in `.tool-versions`. CI MUST use `npm ci` at the owning workspace root.

Package scripts MUST use consistent initialization, test, and build semantics and preserve explicit module formats, exports, entry points, and supported runtimes. Taskfiles MUST delegate to actual scripts without automatic formatting or linting. Source MUST use `src/`, tests MUST use `tests/`, and generated outputs MUST use `build/` where supported. External package export paths and required framework filenames MUST remain compatible.

### 3. Code and Verification

Internally controlled JavaScript MUST use shared snake_case identifiers and filenames, PascalCase types, UPPER_SNAKE_CASE constants, explicit imports, and shared grouping and vertical-call rules. External properties, DOM interfaces, framework callbacks, and public wire contracts MUST retain their required forms. Agents MUST verify import resolution, package exports, actual supported runtimes, tests, and affected browser or native integration after changes.

## Typescript Rules

### 2. Compiler Configuration

TypeScript projects MUST provide `tsconfig.json` at the appropriate project or workspace root and follow the npm and lockfile requirements in JavaScript Rules. Shared root configuration and project references MUST retain the actual build graph. Variants SHOULD use `tsconfig.<variation>.json` where supported. Supported compiler versions MUST derive from manifests and lockfiles.

Strict type checking SHOULD be enabled where compatible. Agents MUST NOT weaken types, disable checks, or suppress errors merely to pass migration. Internally controlled types and interfaces MUST use PascalCase; functions, members, and variables MUST use shared snake_case naming outside necessary external contracts. Type-only imports MUST remain explicit and follow shared import ordering.

### 3. Verification

Agents MUST execute affected compiler checks, tests, and builds after changes. Generated declarations, package exports, JSX requirements, module resolution, project references, browser integration, and native boundaries MUST remain compatible. Browser checks MUST NOT establish native Electron behavior.

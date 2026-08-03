---
name: create-implementation-plan
description: Create deterministic implementation plans for any project. Use for new features, algorithm work, refactoring, upgrades, infrastructure, or architecture changes. Do not use when migrating a component from one language or codebase to another (use migration-implementation-plan). Plans are fully executable by AI agents or humans, providing complete task steps, tech stack constraints, validation procedures, risks, and rollback strategies.
argument-hint: Describe the project name and purpose of the implementation plan (e.g., "backend API performance refactor", "new algorithm for audio processing")
---

# Create Implementation Plan — <PROJECT_NAME>

> **How to use this template:** Replace every `<PLACEHOLDER>` with the value appropriate to your project. Key placeholders to define before generating a plan:
>
> | Placeholder | Meaning | Example |
> |---|---|---|
> | `<PROJECT_NAME>` | The name of the project | `gen-e2 fpengine`, `my-api-service` |
> | `<CODEBASE_ROOT>` | Root directory of the codebase | `a886-fpengine`, `src` |
> | `<LANG>` | Primary language | `C++23`, `Go 1.26`, `TypeScript 5` |
> | `<BUILD_TOOL>` | Build system/tool | `CMake 3.13+`, `make`, `cargo`, `npm` |
> | `<BUILD_CMD>` | Command to build the project | `fpengine-install`, `make build`, `cargo build` |
> | `<FMT_CMD>` | Formatter check command | `fpengine-format-src`, `make fmt-check`, `cargo fmt --check` |
> | `<FMT_FIX_CMD>` | Formatter fix command | `fpengine-format-src --all`, `make fmt`, `cargo fmt` |
> | `<LINT_CMD>` | Linter command | `make lint`, `cargo clippy`, `eslint .` |
> | `<TEST_CMD>` | Test runner command | `aero_test_<module>`, `go test ./...`, `cargo test` |
> | `<REGR_CMD>` | Regression/integration test command | `comma-test-run`, `make integration-test` |
> | `<DEV_ENV>` | Dev environment description | `Docker fpe-dev`, `local venv`, `devcontainer` |
> | `<MODULE_DIR>` | Module/package directory pattern | `aero/<module>/`, `internal/<package>/`, `src/<module>/` |
> | `<TEST_DIR>` | Test directory pattern | `aero-test/regression/`, `internal/<pkg>/testdata/`, `tests/` |
> | `<DOCS_DIR>` | Documentation directory | `algorithm_description/`, `docs/`, `wiki/` |
> | `<PLANS_DIR>` | Where plans are saved | `.github/plans/`, `docs/plans/` |
> | `<PLAN_REFERENCE>` | A completed plan to use as the gold standard | `.github/plans/archived/T4-segment-physics.md` |
> | `<ISSUE_TRACKER>` | Issue/ticket system | `JIRA`, `GitHub Issues`, `Linear` |
> | `<ISSUE_PREFIX>` | Issue ID prefix | `FPE-`, `PROJ-`, `#` |
> | `<NAMESPACE>` | Code namespace/package convention | `acfr::aero`, `github.com/org/repo/internal`, `@org/pkg` |
> | `<NAMING_CONVENTION>` | File and symbol naming rules | `aero_<module>`, `snake_case`, `camelCase` |

## Primary Directive

Your goal is to create a new implementation plan file for the project you will describe. Your output must be machine-readable, deterministic, and structured for autonomous execution by other AI systems or humans.

This template enforces deterministic, machine-parseable structure using standardized identifiers (REQ-, TASK-, RISK-, etc.), placeholder constraints, and phase-level validation gates — ensuring plans are executable by AI agents without human interpretation.

## Tech Stack Constraints

> **Fill in these constraints for your project before generating a plan. Remove any that do not apply. Add project-specific entries as needed.**

All plans must operate within the `<CODEBASE_ROOT>` technology boundaries. These are non-negotiable constraints that apply to every plan:

- **Language:** `<LANG>`. All new code must use the canonical file extensions — no other languages unless explicitly directed
- **Build system:** `<BUILD_TOOL>`. Never invoke the compiler directly — always use `<BUILD_CMD>` (the project build command)
- **Compiler/runtime:** `<COMPILER_OR_RUNTIME>` (dev environment: `<DEV_ENV>`). Key flags/options: `<COMPILER_FLAGS>`
- **Build output:** `<BUILD_OUTPUT_DIR>`; installed artifacts at `<INSTALL_DIR>` (on `$PATH` if applicable)
- **Library/module type:** `<LIBRARY_TYPE>` (e.g., static only, shared, ESM modules)
- **Namespace/package convention:** `<NAMESPACE>` (e.g., `acfr::aero` for all `aero/` code)
- **Import/include convention:** `<IMPORT_CONVENTION>` (e.g., public headers under `include/<module>/`, consumed as `#include <module/foo.h>`)
- **Naming conventions:** `<NAMING_CONVENTION>` (e.g., library naming `<MODULE_DIR>`, file naming, symbol naming)
- **Parallelism:** `<PARALLELISM_APPROACH>` (e.g., Intel TBB — never raw threads for data-parallel work)
- **Key third-party libs:** `<THIRD_PARTY_LIBS>` (list approved libraries with versions)
- **Testing (unit):** `<UNIT_TEST_FRAMEWORK>`. Test naming: `<TEST_NAMING_CONVENTION>`. Run: `<TEST_CMD>`
- **Testing (regression/integration):** `<REGR_TEST_FRAMEWORK>` in `<TEST_DIR>`. External data: `<TEST_DATA_LOCATION>`
- **Code formatting:** `<FORMAT_TOOL>`. Run: `<FMT_CMD>`. Style: `<FORMAT_STYLE>`
- **Linting:** `<LINT_TOOL>`. Config: `<LINT_CONFIG_FILE>`. Run: `<LINT_CMD>`
- **Dev environment:** `<DEV_ENV>` (e.g., Docker container name, devcontainer config, local install instructions)
- **Versioning:** `<VERSION_STRATEGY>`. Pre-merge command: `<PRE_MERGE_CMD>`
- **No new external dependencies** without explicit approval — use existing approved libraries first

## Directory Structure Reference

> **Replace with your project's actual directory layout.**

| Directory | Purpose |
|---|---|
| `<CODEBASE_ROOT>/<CORE_SRC_DIR>/` | Core source code — main algorithms/business logic |
| `<CODEBASE_ROOT>/<TEST_DIR>/` | Unit and regression tests |
| `<CODEBASE_ROOT>/<UTIL_DIR>/` | Utility/shared libraries |
| `<CODEBASE_ROOT>/<CONFIG_DIR>/` | Configuration files |
| `<CODEBASE_ROOT>/<DEV_ENV_DIR>/` | Dev environment setup (Docker, scripts, etc.) |
| `<CODEBASE_ROOT>/<DOCS_DIR>/` | Documentation |
| `<PLANS_DIR>/` | Implementation plans (current and archived) |

## Plan Structure Requirements

Plans must consist of discrete, atomic phases containing executable tasks. Each phase must be independently processable by AI agents or humans without cross-phase dependencies unless explicitly declared.

## Phase Architecture

- Each phase must have measurable completion criteria
- **Every phase must end with a validation step:** `<FMT_CMD>` must produce no diffs, all affected tests must pass, regression tests must pass if applicable
- Tasks within phases must be executable in parallel unless dependencies are specified
- All task descriptions must include specific file paths, function/class names, and exact implementation details
- No task should require human interpretation or decision-making

## AI-Optimized Implementation Standards

- Keep the plan deterministic and machine-parseable: use repo-relative file paths, concrete code references, standardized identifiers (REQ-, TASK-, RISK-, etc.), and the output file naming rules defined below.

## Output File Specifications

- Save implementation plan files in `<PLANS_DIR>/` directory
- Use naming convention: `[purpose]-[feature]-[version].md`
- Purpose prefixes: `upgrade|refactor|feature|algorithm|data|infrastructure|process|architecture|bugfix`
- Feature names should align with `<MODULE_DIR>` directory names where applicable
- Examples: `feature-<module>-<capability>-1.md`, `refactor-<module>-<concern>-1.md`, `bugfix-<module>-<issue>-1.md`, `upgrade-<dependency>-1.md`
- File must be valid Markdown with proper front matter structure

## Mandatory Template Structure

All implementation plans must strictly adhere to the following template. Each section is required and must be populated with specific, actionable content. AI agents must validate template compliance before execution.

## Template Validation Rules

- All front matter fields must be present and properly formatted
- All section headers must match exactly (case-sensitive)
- All identifier prefixes must follow the specified format
- Tables must include all required columns
- No placeholder text may remain in the final output
- File paths must be relative to project root and must reference actual files in the repo

## Status

The status of the implementation plan must be clearly defined in the front matter and must reflect the current state of the plan. The status can be one of the following (status_color in brackets): `Completed` (bright green badge), `In progress` (yellow badge), `Planned` (blue badge), `Deprecated` (red badge), or `On Hold` (orange badge). It should also be displayed as a badge in the introduction section.

```md
---
goal: [Concise Title Describing the Implementation Plan's Goal]
jira: [Optional: <ISSUE_TRACKER> ticket ID(s), e.g., <ISSUE_PREFIX>1234]
version: [Optional: e.g., 1.0, Date]
date_created: [YYYY-MM-DD]
last_updated: [Optional: YYYY-MM-DD]
owner: [Optional: Team/Individual responsible for this spec]
status: 'Completed'|'In progress'|'Planned'|'Deprecated'|'On Hold'
tags: [Optional: List of relevant tags, e.g., `feature`, `algorithm`, `upgrade`, `refactor`, `architecture`, `bugfix`, `infrastructure`]
feature: [Optional: The <MODULE_DIR> or component this relates to]
---

# Introduction

![Status: <status>](https://img.shields.io/badge/status-<status>-<status_color>)

[A short concise introduction to the plan and the goal it is intended to achieve. Include context about which module/component is affected, what algorithm or business functionality changes, and any runtime/integration impact.]

## 1. Requirements & Constraints

[Explicitly list all requirements and constraints that affect the plan. Always include the relevant tech stack constraints. Use bullet points or tables for clarity.]

- **REQ-001**: Requirement 1
- **SEC-001**: Security Requirement 1 (e.g., input validation of external/untrusted data at system boundaries)
- **[3 LETTERS]-001**: Other Requirement 1
- **CON-001**: Constraint 1 (e.g., `<LANG>` only — no new external dependencies without approval; `<LIBRARY_TYPE>` libraries only)
- **GUD-001**: Guideline 1 (e.g., use `<NAMESPACE>`; follow `<NAMING_CONVENTION>`; `<FORMAT_TOOL>` column limit)
- **PAT-001**: Pattern to follow 1 (e.g., follow `<EXISTING_REFERENCE_FILE>` as the module template)

## 2. Implementation Steps

### Implementation Phase 1

- GOAL-001: [Describe the goal of this phase, e.g., "Add new class/algorithm to the <module> library"]

| Task     | Description                                                                                               | Completed | Date       |
| -------- | --------------------------------------------------------------------------------------------------------- | --------- | ---------- |
| TASK-001 | Description of task 1 (include file path, class/function name, namespace/package)                        | ✅        | YYYY-MM-DD |
| TASK-002 | Description of task 2                                                                                     |           |            |
| TASK-003 | Validation: run `<FMT_CMD>`, build with `<BUILD_CMD>`, run `<TEST_CMD>`                                   |           |            |

### Implementation Phase 2

- GOAL-002: [Describe the goal of this phase, e.g., "Wire new module into pipeline and add regression test"]

| Task     | Description                                                                                               | Completed | Date |
| -------- | --------------------------------------------------------------------------------------------------------- | --------- | ---- |
| TASK-004 | Description of task 4                                                                                     |           |      |
| TASK-005 | Description of task 5                                                                                     |           |      |
| TASK-006 | Validation: run `<FMT_CMD>`, `<BUILD_CMD>`, all affected tests, regression tests                          |           |      |

## 3. Alternatives

[A bullet point list of any alternative approaches considered and why they were not chosen.]

- **ALT-001**: Alternative approach 1
- **ALT-002**: Alternative approach 2

## 4. Dependencies

[List any dependencies that need to be addressed — existing modules, libraries, external data sources.]

- **DEP-001**: Dependency 1 (e.g., `<module>_geometry` — used for coordinate transformations in the new algorithm)
- **DEP-002**: Dependency 2 (e.g., `<module>_navigation` — provides data consumed by this feature)
- **DEP-003**: Dependency 3 (e.g., `<util_lib>` — used for parsing input files)

## 5. Files

[List files to be created or modified. Use full paths relative to project root. Group by type.]

**New files:**

- **FILE-001**: `<MODULE_DIR>/<feature>.<ext>` — Core implementation; class/function declaration in `<NAMESPACE>`
- **FILE-002**: `<MODULE_DIR>/<feature>_test.<ext>` — Unit tests; added to `<TEST_EXECUTABLE>` target
- **FILE-003**: `<TEST_DIR>/<feature>/` — Regression/integration test directory with `input/`, test script, `expected/` (if applicable)

**Modified files:**

- **FILE-004**: `<MODULE_DIR>/<BUILD_CONFIG_FILE>` — Add new source file(s) to build target; add new test source
- **FILE-005**: `<MODULE_DIR>/<module_header>.<ext>` — Add import/include for new public API (if relevant)
- **FILE-006**: `<INTEGRATION_LAYER>/<file>.<ext>` — Integrate new module into pipeline (if applicable)

## 6. Testing

[List the tests to be implemented. Unit tests are co-located in the module's test directory. Regression/integration tests live in `<TEST_DIR>`.]

- **TEST-001**: Unit test — verify [behaviour] in `<MODULE_DIR>/<feature>_test.<ext>`; run with `<TEST_CMD>`
- **TEST-002**: Unit test — edge case coverage (e.g., empty input, boundary values, numerical precision)
- **REGR-001**: Regression/integration test — add scenario in `<TEST_DIR>/<feature>/`; verify expected output matches; run via `<REGR_CMD>`
- **FMT-001**: `<FMT_CMD>` produces no diffs against the main branch
- **BUILD-001**: `<BUILD_CMD>` completes with zero errors and zero warnings
- **UNIT-001**: `<TEST_CMD>` passes all tests with no failures
- **MANUAL-001**: Manual integration verification (e.g., "Run end-to-end on a sample input, verify output matches expected result")

## 7. Risks & Assumptions

[List any risks or assumptions related to the plan.]

- **RISK-001**: Risk 1 (e.g., "Algorithm numerical precision may degrade at boundary conditions — add test cases at edge values")
- **RISK-002**: Risk 2 (e.g., "Third-party library version differences may affect output — pin version in `<DEV_ENV_DIR>` or add tolerance")
- **ASSUMPTION-001**: Assumption 1 (e.g., "Input data conforms to the existing schema used by `<MODULE_DIR>`")
- **ASSUMPTION-002**: Assumption 2 (e.g., "Current parallelism approach is sufficient — no additional concurrency needed")

## 8. Related Specifications / Further Reading

[Link to related tickets, skill files, algorithm documentation, or external references.]

- <ISSUE_TRACKER>: [ticket ID]
- Documentation: `<DOCS_DIR>/` (algorithm/design documentation)
- Related skill: `/.github/skills/<skill-name>/SKILL.md`
- Related instructions: `/.github/instructions/<topic>.instructions.md`
- External reference: [link if applicable, e.g., RFC, spec document, external API docs]
```

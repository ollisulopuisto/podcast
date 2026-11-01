# Path-Scoped CI Test Selection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Avoid running unrelated application suites on every PR while retaining tests for shared libraries and their consumers.

**Architecture:** Add a small, deterministic path-to-suite selector used by both platform test workflows. Each workflow gets a cheap Ubuntu selector job; platform suites run only when needed. Run shared test suites when their sources change, run dependent application suites for shared-library changes, and keep manual runs full. Lint and workspace-contract tests remain global.

**Tech Stack:** Python standard library, GitHub Actions, pytest.

---

### Task 1: Test path-to-suite selection

**Files:**
- Create: `tests/test_ci_test_selection.py`
- Create: `scripts/ci_test_selection.py`

1. Write cases for an app-only edit, each shared library and its consumers, global lock/workflow changes, docs-only edits, and manual/full selection.
2. Run `pytest tests/test_ci_test_selection.py`; verify it fails because the selector is absent.
3. Implement a pure selector that maps changed paths to Linux and macOS suites and includes a full-run mode.
4. Run the focused tests and root workspace tests.

### Task 2: Use selection in CI

**Files:**
- Modify: `.github/workflows/tests-linux.yml`
- Modify: `.github/workflows/tests.yml`
- Modify: `CONTRIBUTING.md`

1. Add a selector step that diffs the PR base or prior push commit; manual dispatch selects every suite.
2. Gate member test steps with the selector outputs, preserving required runner checks and shared-library consumer coverage.
3. Run workflow-contract tests, Ruff, and inspect the resulting diffs.
4. Commit only the selector, its tests, workflows, plan, and documentation.

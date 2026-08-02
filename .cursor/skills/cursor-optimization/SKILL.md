---
name: cursor-optimization
description: >-
  Token and memory optimization for Cursor agents. Use when coding or editing
  to stay concise, make surgical diffs, avoid full-file rewrites, and respect
  .cursorignore so heavy/irrelevant paths stay out of indexing context.
---

# Cursor Optimization Guide

Persistent project instructions for lean AI coding: less filler, surgical edits, and respect for ignore patterns.

## Rules for AI

- Be extremely concise. Avoid conversational filler, pleasantries, or introductory/concluding text.
- Do not explain how the code works unless explicitly asked.
- Provide only the specific code snippets or functions that need changing. Do not rewrite unchanged parts of a file.
- Use placeholders or comments like `// ... existing code ...` to represent untouched lines of code.
- Prefer efficient, clean solutions with minimal code footprint.

## Edit practice

- Prefer StrReplace / surgical edits over rewriting whole files.
- Never dump an entire file when only a few lines change.
- Keep the code footprint small: efficient, clean solutions over expansive rewrites.

## `.cursorignore`

Project root `.cursorignore` excludes noisy and heavy paths from Cursor indexing/context. Agents should:

- Treat ignored paths as out-of-scope for default exploration and `@`-style context stuffing.
- Not read or re-index `node_modules/`, lockfiles, build outputs (`.next/`, `dist/`, etc.), logs, media, `.env*`, venvs, temp dirs, or large snapshot JSON unless the user explicitly asks.
- Never ignore source code to “save tokens” — only heavy/non-source artifacts listed in `.cursorignore`.

Key categories already covered in this repo’s `.cursorignore`:

| Category | Examples |
|----------|----------|
| Node & deps | `node_modules/`, lockfiles |
| Build output | `dist/`, `build/`, `.next/`, `out/` |
| Secrets/logs | `.env*`, `*.log`, `*.sqlite` |
| Media/archives | `*.png`, `*.mp4`, `*.pdf`, `*.zip` |
| trade_api extras | `backend/.venv/`, `.venv/`, `tmp/`, `.tmp/`, `*.pack`, large snapshot JSON |

## Always-apply rule

Companion rule: `.cursor/rules/cursor-optimization.mdc` (`alwaysApply: true`). This skill expands that rule for agents that load it explicitly; do not contradict it.

## Do not

- Modify the user’s global Cursor `settings.json` for this guide — project rule + skill is the mechanism.
- Rewrite whole files “for clarity” when a surgical patch suffices.
- Add conversational padding around code changes.

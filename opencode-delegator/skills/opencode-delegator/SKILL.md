---
name: opencode-delegator
description: Use only when the user explicitly mentions or @-invokes the OpenCode Delegator plugin/skill and wants Codex to hand text-heavy, low-reasoning routine work to the local opencode CLI. Do not trigger automatically for ordinary coding, research, review, debugging, or multimodal tasks.
---

# OpenCode Delegator

This skill is opt-in only. Use it only when the user explicitly mentions `opencode-delegator`, `OpenCode Delegator`, `@opencode-delegator`, or asks to use this plugin/skill.

## What to Delegate

Delegate only text-heavy routine work that would bloat the main Codex thread but does not require deep reasoning:

- reading many source, log, Markdown, CSV, JSON, or text files
- extracting repeated facts or examples
- summarizing long terminal output or text artifacts
- broad first-pass grep/list/read exploration
- producing a compact handoff for Codex to verify and use

Do not delegate:

- multimodal tasks: images, screenshots, video, audio, visual PDF inspection, OCR, chart/figure interpretation
- high-stakes decisions, architecture choices, subtle debugging, or complex implementation strategy
- tasks where opencode would need private context that is already only in the Codex thread
- code edits unless the user explicitly asks for opencode to edit

## Workflow

1. Confirm the user explicitly invoked this plugin/skill in the current request.
2. Compress the delegated task into a bounded prompt with the exact files or directories to inspect.
3. Call `opencode_delegate` with the current workspace absolute path as `working_directory`.
4. Keep `allow_edits=false` unless the user explicitly asks opencode to modify files.
5. Set `contains_multimodal=true` and do not delegate if the task depends on images, screenshots, audio, video, binary PDFs, or Office documents.
6. Treat opencode's result as an assistant handoff, not ground truth. Verify key code facts locally before acting on them.

## Output Expectations

When using the tool, ask opencode for concise sections:

- `RESULT`: the compressed answer
- `EVIDENCE`: file paths, line numbers, counts, or exact search terms
- `UNCERTAINTIES`: anything it could not verify
- `NEXT_HANDOFF`: what Codex should do next

Return only the opencode summary that matters to the user. Do not paste long raw opencode output into the main thread unless the user asked for it.

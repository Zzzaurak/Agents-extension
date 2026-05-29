---
name: mineru-pdf-reader
description: Use when Codex needs to summarize, analyze, extract, or answer questions about a local PDF or PDF URL by first converting it through MinerU into Markdown. Automatically use MinerU v4 when MINERU_API_KEY is configured in ~/.codex/mineru-pdf-router.env, otherwise fall back to MinerU v1 lightweight parsing. Prefer this skill for content understanding; prefer the built-in `pdf` skill when visual layout, rendering, or formatting fidelity matters.
---

# MinerU PDF Reader

Convert supported documents through MinerU before reading them as model-friendly Markdown. This skill is for semantic understanding, not visual QA.

## Workflow

1. Decide whether the task is content-first or layout-first.
   - If the user wants summary, extraction, analysis, or Q&A, call the `mineru_parse_document` MCP tool first.
   - If the user wants to inspect layout, spacing, tables-as-rendered, screenshots, or page visuals, use the `pdf` skill instead when available.
   - If both matter, use MinerU first for semantic extraction, then use `$pdf` for visual verification.
2. Know the routing rule before you call the tool.
   - MinerU reads `~/.codex/mineru-pdf-router.env`.
   - If `MINERU_API_KEY` is present, the plugin automatically uses MinerU v4 precision extraction with `model_version=vlm` unless the config overrides it to `pipeline`.
   - If `MINERU_API_KEY` is missing, the plugin automatically falls back to the MinerU v1 lightweight Agent API.
3. Call `mineru_parse_document` with:
   - `source_type="local_path"` for a local file path
   - `source_type="remote_url"` for a remote PDF or document URL
   - `file_name` only when the remote URL lacks a reliable filename
   - `page_range` only when you need a subset of PDF pages
4. Handle sandboxed network access explicitly.
   - MinerU parsing requires outbound HTTPS access to `mineru.net` and result archive/CDN URLs.
   - If the MinerU call fails because the sandbox cannot reach `https://mineru.net/api/v4/file-urls/batch`, another MinerU API endpoint, or the returned archive URL, immediately request network approval and retry the same MinerU request.
   - Do not fall back to guessing from the PDF, and do not stop after the first sandbox network failure when network approval can solve it.
5. Read the returned Markdown, not the original PDF bytes.
   - On v1, the tool downloads the Markdown from `markdown_url`.
   - On v4, the tool downloads `full_zip_url` and extracts `full.md`.
6. In the final answer:
   - Say that the content came from MinerU Markdown output and mention whether it used v1 or v4.
   - Mention relevant limits or warnings from the tool.
   - Base your summary, Q&A, or advice on the Markdown output.

## Decision Rules

- Treat MinerU output as semantic text extraction. Do not claim layout fidelity.
- If the user asks how to enable v4 precision parsing, point them to `~/.codex/mineru-pdf-router.env`.
- If a request fails with sandbox/network errors, ask for outbound network approval for MinerU and retry before changing strategy.
- If the tool reports preflight or API limits, explain the limit and recommend a smaller `page_range`, a split PDF, or a different workflow.
- For remote URLs, do not assume local preflight happened; the tool only preflights local files.
- For non-PDF supported files, keep the same behavior: content extraction first, no promises about visual fidelity.

## Output Expectations

- Start with the parsing source and any important constraints.
- Mention whether the plugin used the configured v4 precision API or the v1 lightweight fallback.
- Then provide the requested summary, analysis, answers, or recommendations from the Markdown.
- Do not pretend the model read the original binary PDF directly.

## Reference

- Read [references/mineru-agent-api.md](./references/mineru-agent-api.md) when adjusting config loading, limits, v1/v4 request fields, or error handling.

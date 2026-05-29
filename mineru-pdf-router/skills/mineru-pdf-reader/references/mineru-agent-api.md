# MinerU API Notes

Sources:
- https://mineru.net/apiManage/docs
- https://mineru.net/doc/docs/index_en/
- https://opendatalab.github.io/MinerU/reference/output_files/

## Use This Reference When

- Adjusting request fields for the MinerU v1 lightweight Agent API
- Adjusting request fields for the MinerU v4 precision API
- Explaining config-driven backend routing
- Updating MCP validation or error messages

## Plugin Routing Rules

- The plugin reads `~/.codex/mineru-pdf-router.env` by default.
- Supported config keys:
  - `MINERU_API_KEY`
  - `MINERU_BACKEND=auto|v1-agent|v4-precision`
  - `MINERU_V4_MODEL_VERSION=vlm|pipeline`
  - `MINERU_API_BASE=https://mineru.net`
- `MINERU_CONFIG_PATH` is an internal override for tests or advanced setups.
- In `auto` mode:
  - If `MINERU_API_KEY` exists, route to v4 precision extraction.
  - If `MINERU_API_KEY` is missing, fall back to v1 lightweight parsing.

## MCP Runtime Notes

- `.mcp.json` must set `cwd` to `.` so relative script paths resolve from the installed plugin directory, matching Codex's bundled plugin pattern.
- The MCP server should use an absolute Python executable path in GUI environments because the app process may not inherit the interactive shell `PATH`.
- The MCP server runs with `python3` from `PATH`; use a Python environment that has `requests` installed.
- `/usr/bin/python3` and `/opt/homebrew/bin/python3` may be visible to GUI-launched processes, but they do not currently have `requests` installed here.

## Network Approval Notes

- MinerU v4 requires outbound HTTPS to `https://mineru.net/api/v4/file-urls/batch`, `https://mineru.net/api/v4/extract/task/batch`, `https://mineru.net/api/v4/extract-results/batch/{batch_id}`, and the returned result archive URL.
- MinerU v1 requires outbound HTTPS to the v1 Agent endpoints and the returned `markdown_url`.
- In Codex sandboxed sessions with network disabled, failures that mention inability to reach MinerU endpoints or result URLs should be treated as network-permission failures.
- When that happens, request network approval and retry the same MinerU parse operation instead of changing to local PDF reading or stopping.

## v1 Lightweight Notes

- Endpoints:
  - Local upload: `POST /api/v1/agent/parse/file`
  - Remote URL: `POST /api/v1/agent/parse/url`
  - Poll: `GET /api/v1/agent/parse/{task_id}`
- No Authorization header is required.
- Output is Markdown only.
- Local limits used by this plugin:
  - File size: 10 MB
  - PDF pages: 20
- `page_range` is intentionally limited by the plugin to a single page or a simple range like `1-10`.
- Terminal states:
  - `done`
  - `failed`
- On `done`, use `markdown_url`.
- On `failed`, surface `err_code` and `err_msg`.

## v4 Precision Notes

- Authorization header must be `Bearer <token>`.
- Endpoints:
  - Local signed upload batch: `POST /api/v4/file-urls/batch`
  - Remote URL batch: `POST /api/v4/extract/task/batch`
  - Poll batch results: `GET /api/v4/extract-results/batch/{batch_id}`
- For the signed `PUT` upload, do not add a manual `Content-Type` header unless MinerU explicitly includes that requirement in the signed URL contract; extra headers can invalidate the signature.
- Local upload request shape used by this plugin:
  - Top-level:
    - `enable_formula`
    - `enable_table`
    - `language`
    - `model_version`
  - Per-file:
    - `name`
    - `is_ocr`
    - `page_ranges`
- Remote URL batch request shape used by this plugin:
  - Top-level:
    - `enable_formula`
    - `enable_table`
    - `language`
    - `model_version`
  - Per-file:
    - `url`
    - `is_ocr`
    - `page_ranges`
- This plugin only exposes `vlm` and `pipeline` for `model_version`.
- This plugin does not expose `MinerU-HTML`.
- Result polling states include:
  - `waiting-file`
  - `pending`
  - `running`
  - `converting`
  - `done`
  - `failed`
- On `done`, read `data.extract_result[0].full_zip_url`.
- The plugin downloads the zip archive and extracts `full.md`.
- `markdown_url` is not used on v4.

## Result Archive Notes

- `full_zip_url` is a zip archive containing Markdown and JSON outputs.
- For this plugin, the only required file is `full.md`.
- If the archive does not contain `full.md`, the plugin must return a structured error and must not fabricate Markdown text.

## Error Handling Notes

- v1:
  - `-30001`: file too large for lightweight mode
  - `-30003`: page count exceeds lightweight limit
  - `429`: IP-based rate limit
- v4:
  - `A0202`: invalid token
  - `A0211`: token expired
  - `-60005`: file size exceeds limit
  - `-60006`: page count exceeds limit
  - `-60008`: file read timeout
  - `-60022`: web page read failure
- For token errors, instruct the user to check `MINERU_API_KEY` in `~/.codex/mineru-pdf-router.env`.

## Known Doc Inconsistencies

- The Chinese API page shows a v4 page example like `1-200`.
- The English overview table says v4 supports up to 600 pages.
- The plugin should not hardcode a local v4 page-count limit because the public docs are inconsistent; rely on upstream validation and return the upstream error clearly.

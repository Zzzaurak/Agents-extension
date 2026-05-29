# Agents Extension

Personal Codex extensions: two local plugins, one standalone skill, and a linked literature workflow project.

## Contents

- `mineru-pdf-router`: a Codex plugin that routes PDF/document parsing through MinerU and exposes an MCP tool for Markdown extraction.
- `opencode-delegator`: a Codex plugin that delegates explicit text-heavy routine work to the local `opencode` CLI through MCP.
- `codex-study-mode`: a standalone Codex skill for staged Chinese teaching and literature-project-based learning.
- `research-literature-pipeline`: a Git submodule for the literature workflow repo.

## Install With npx

Install both plugins and the study skill from GitHub:

```bash
npx github:Zzzaurak/Agents-extension install all
```

Install selected items:

```bash
npx github:Zzzaurak/Agents-extension install mineru-pdf-router opencode-delegator
npx github:Zzzaurak/Agents-extension install codex-study-mode
```

The installer:

- copies plugins into `~/.agents/plugins/plugins/`;
- creates or updates `~/.agents/plugins/marketplace.json`;
- copies skills into `~/.codex/skills/`.

Override destinations when needed:

```bash
npx github:Zzzaurak/Agents-extension install all --codex-home ~/.codex
npx github:Zzzaurak/Agents-extension install all --marketplace-root ~/.agents/plugins
```

Preview changes without writing files:

```bash
npx github:Zzzaurak/Agents-extension install all --dry-run
```

## Configuration

### MinerU PDF Router

The MCP server runs with `python3` from `PATH`; use a Python environment with `requests` available.

Optional configuration lives at:

```text
~/.codex/mineru-pdf-router.env
```

Use `mineru-pdf-router/assets/mineru-pdf-router.env.example` as the field reference. If `MINERU_API_KEY` is absent, the plugin falls back to the MinerU v1 lightweight route when possible.

### OpenCode Delegator

Install and authenticate the local `opencode` CLI before using this plugin.

Optional defaults live at:

```text
~/.config/opencode/opencode-delegator.env
```

Use `opencode-delegator/assets/opencode-delegator.env.example` as the field reference. The plugin also works without this file and will use opencode's own defaults.

### Codex Study Mode

Invoke explicitly with one of:

```text
$codex-study-mode
启用学习模式
按学习skill下一步
按skill下一步
```

The skill is intentionally narrow: it should not activate for ordinary coding, paper summaries, or quick explanations unless explicitly requested.

## Development

Clone with submodules when working on the whole repository:

```bash
git clone --recurse-submodules git@github.com:Zzzaurak/Agents-extension.git
```

If the repo was cloned without submodules:

```bash
git submodule update --init --recursive
```

Check local path leaks before publishing:

```bash
rg -n --hidden --glob '!**/.git/**' "$HOME" .
```

Validate the npm package contents:

```bash
npm pack --dry-run
```

The extension files should not contain API keys, tokens, private PDFs, research notes, or machine-specific absolute paths.

#!/usr/bin/env python3
"""MCP wrapper that delegates selected text-heavy work to the local opencode CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SERVER_INFO = {"name": "opencode-delegator", "version": "0.1.0"}
DEFAULT_TIMEOUT_SEC = 1800
DEFAULT_MAX_OUTPUT_CHARS = 20000

TEXT_LIKE_EXTENSIONS = {
    "",
    ".c",
    ".cc",
    ".cfg",
    ".conf",
    ".cpp",
    ".cs",
    ".css",
    ".csv",
    ".env.example",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".ipynb",
    ".java",
    ".js",
    ".json",
    ".jsonc",
    ".jsx",
    ".kt",
    ".lock",
    ".log",
    ".m",
    ".md",
    ".mdx",
    ".mjs",
    ".mm",
    ".php",
    ".plist",
    ".py",
    ".rb",
    ".rs",
    ".scss",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

MULTIMODAL_OR_BINARY_EXTENSIONS = {
    ".aac",
    ".avi",
    ".bmp",
    ".doc",
    ".docx",
    ".flac",
    ".gif",
    ".heic",
    ".jpeg",
    ".jpg",
    ".m4a",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".tiff",
    ".wav",
    ".webm",
    ".webp",
    ".xls",
    ".xlsx",
}


TOOL_DEFINITIONS = [
    {
        "name": "opencode_delegate",
        "description": (
            "Delegate a text-heavy, low-reasoning routine task to the local opencode CLI. "
            "Use only after the user explicitly invokes the OpenCode Delegator plugin/skill. "
            "Do not use for multimodal work."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Bounded task prompt for opencode.",
                },
                "working_directory": {
                    "type": "string",
                    "description": "Absolute directory where opencode should run.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["research", "summarize", "review", "implementation_plan", "freeform"],
                    "default": "research",
                    "description": "Routine task shape used to frame the delegation prompt.",
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "Optional text/code files to pass with repeated --file arguments.",
                },
                "model": {
                    "type": "string",
                    "description": "Optional opencode model in provider/model format.",
                },
                "agent": {
                    "type": "string",
                    "description": "Optional opencode agent name.",
                },
                "variant": {
                    "type": "string",
                    "description": "Optional provider-specific reasoning variant.",
                },
                "session_id": {
                    "type": "string",
                    "description": "Optional opencode session id to continue.",
                },
                "timeout_sec": {
                    "type": "integer",
                    "default": DEFAULT_TIMEOUT_SEC,
                    "minimum": 30,
                    "description": "Maximum time to wait for opencode.",
                },
                "max_output_chars": {
                    "type": "integer",
                    "default": DEFAULT_MAX_OUTPUT_CHARS,
                    "minimum": 1000,
                    "description": "Maximum returned assistant text length.",
                },
                "allow_edits": {
                    "type": "boolean",
                    "default": False,
                    "description": "Allow opencode to perform edit-capable work. Default is read-only delegation.",
                },
                "contains_multimodal": {
                    "type": "boolean",
                    "default": False,
                    "description": "Set true when the task requires image, audio, video, PDF visual, OCR, or other multimodal input.",
                },
            },
            "required": ["task", "working_directory"],
            "additionalProperties": False,
        },
    },
    {
        "name": "opencode_delegate_status",
        "description": "Check whether opencode and optional OpenCode Delegator defaults are available.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
]


@dataclass
class DelegatorError(Exception):
    code: str
    message: str
    suggestion: str | None = None
    details: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"ok": False, "error_code": self.code, "error_message": self.message}
        if self.suggestion:
            payload["suggestion"] = self.suggestion
        if self.details:
            payload["details"] = self.details
        return payload


def write_message(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def make_response(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def make_error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def tool_success(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
        "structuredContent": result,
    }


def tool_error(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
        "structuredContent": result,
        "isError": True,
    }


def initialize(params: dict[str, Any] | None) -> dict[str, Any]:
    protocol_version = "2024-11-05"
    if isinstance(params, dict):
        protocol_version = str(params.get("protocolVersion") or protocol_version)
    return {"protocolVersion": protocol_version, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO}


def coerce_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def coerce_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise DelegatorError("invalid_boolean", "Boolean arguments must be true or false.")


def coerce_int(value: Any, *, default: int, minimum: int | None = None) -> int:
    if value is None:
        result = default
    else:
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise DelegatorError("invalid_integer", "Integer arguments must be numeric.") from exc
    if minimum is not None and result < minimum:
        raise DelegatorError("integer_too_small", f"Integer argument must be at least {minimum}.")
    return result


def load_env_file() -> dict[str, str]:
    env_path = os.environ.get("OPENCODE_DELEGATOR_ENV")
    if not env_path:
        env_path = str(Path.home() / ".config" / "opencode" / "opencode-delegator.env")
    path = Path(env_path).expanduser()
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            loaded[key] = value
    return loaded


def merged_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(load_env_file())
    return env


def env_file_path() -> Path:
    configured = os.environ.get("OPENCODE_DELEGATOR_ENV")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".config" / "opencode" / "opencode-delegator.env"


def opencode_global_model() -> str | None:
    path = Path.home() / ".config" / "opencode" / "opencode.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    model = payload.get("model") if isinstance(payload, dict) else None
    return model if isinstance(model, str) and model.strip() else None


def validate_working_directory(value: Any) -> Path:
    if not value:
        raise DelegatorError("missing_working_directory", "working_directory is required.")
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        raise DelegatorError(
            "working_directory_not_absolute",
            "working_directory must be an absolute path.",
            "Pass the current workspace directory as an absolute path.",
        )
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise DelegatorError("working_directory_not_found", f"Directory does not exist: {resolved}")
    return resolved


def file_extension(path: Path) -> str:
    suffixes = path.suffixes
    if len(suffixes) >= 2 and suffixes[-2] == ".env":
        return ".env.example" if suffixes[-1] == ".example" else suffixes[-1].lower()
    return path.suffix.lower()


def is_probably_text(path: Path) -> bool:
    try:
        sample = path.read_bytes()[:4096]
    except OSError:
        return False
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        try:
            sample.decode("latin-1")
        except UnicodeDecodeError:
            return False
    return True


def is_sensitive_env_file(path: Path) -> bool:
    name = path.name.lower()
    if name == ".env":
        return True
    return name.startswith(".env.") and not name.endswith(".example")


def validate_files(values: Any, working_directory: Path) -> list[Path]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise DelegatorError("invalid_files", "files must be an array of paths.")
    result: list[Path] = []
    for raw in values:
        candidate = Path(str(raw)).expanduser()
        if not candidate.is_absolute():
            candidate = working_directory / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(working_directory)
        except ValueError as exc:
            raise DelegatorError(
                "external_file_rejected",
                f"Refusing to pass a file outside working_directory: {resolved}",
                "Keep delegated files inside the workspace or run opencode manually for external inputs.",
            ) from exc
        if not resolved.exists() or not resolved.is_file():
            raise DelegatorError("file_not_found", f"Delegated file does not exist: {resolved}")
        if is_sensitive_env_file(resolved):
            raise DelegatorError(
                "sensitive_env_file_rejected",
                f"Refusing to pass a sensitive env file to opencode: {resolved}",
                "Use a redacted example file or describe the needed variables without secret values.",
            )
        ext = file_extension(resolved)
        if ext in MULTIMODAL_OR_BINARY_EXTENSIONS:
            raise DelegatorError(
                "multimodal_or_binary_file_rejected",
                f"Refusing to delegate non-text or multimodal file to opencode/deepseek: {resolved}",
                "Use Codex's PDF, image, document, or multimodal-capable tools first, then delegate extracted text if needed.",
            )
        if (ext == "" or ext not in TEXT_LIKE_EXTENSIONS) and not is_probably_text(resolved):
            raise DelegatorError(
                "non_text_file_rejected",
                f"Refusing to delegate a file that does not look like text: {resolved}",
                "Convert the file to text or Markdown before delegating it to opencode.",
            )
        result.append(resolved)
    return result


def create_readonly_config() -> str:
    payload = {
        "$schema": "https://opencode.ai/config.json",
        "permission": {
            "*": "ask",
            "read": "allow",
            "list": "allow",
            "glob": "allow",
            "grep": "allow",
            "edit": "deny",
            "external_directory": "ask",
            "bash": "ask",
        },
    }
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".json", prefix="opencode-delegator-", delete=False
    )
    with handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    return handle.name


def build_prompt(task: str, mode: str, allow_edits: bool) -> str:
    edit_policy = (
        "You may edit files only if the task explicitly requires it. Keep changes minimal and list exact paths changed."
        if allow_edits
        else "Read-only mode: do not edit, write, patch, delete, move, or create files."
    )
    return f"""You are a delegated opencode sidecar called by Codex.

Use this delegation only for text-heavy, low-reasoning routine work. Do not attempt multimodal work. If the task requires images, screenshots, video, audio, visual PDF inspection, OCR, or binary Office/PDF interpretation, refuse briefly and say what text extraction is needed first.

Mode: {mode}
Policy: {edit_policy}

Task:
{task.strip()}

Return a compact handoff for Codex with these exact sections:
RESULT
EVIDENCE
UNCERTAINTIES
NEXT_HANDOFF

Keep the answer concise. Prefer file paths, line numbers, counts, and concrete observations over long raw dumps.
"""


def collect_string_values(value: Any, *, depth: int = 0) -> list[str]:
    if depth > 8:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        collected: list[str] = []
        for item in value:
            collected.extend(collect_string_values(item, depth=depth + 1))
        return collected
    if isinstance(value, dict):
        collected = []
        for key in ("text", "content", "markdown", "output"):
            item = value.get(key)
            if isinstance(item, str):
                collected.append(item)
        for key in ("message", "part", "parts", "delta", "data", "result"):
            if key in value:
                collected.extend(collect_string_values(value[key], depth=depth + 1))
        return collected
    return []


def find_session_id(value: Any, *, depth: int = 0) -> str | None:
    if depth > 8:
        return None
    if isinstance(value, dict):
        for key in ("session_id", "sessionId", "sessionID"):
            item = value.get(key)
            if isinstance(item, str) and item:
                return item
        for item in value.values():
            found = find_session_id(item, depth=depth + 1)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = find_session_id(item, depth=depth + 1)
            if found:
                return found
    return None


def parse_opencode_stdout(stdout: str, max_output_chars: int) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    assistant_chunks: list[str] = []
    generic_chunks: list[str] = []
    session_id: str | None = None
    tool_event_count = 0
    malformed_lines = 0

    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            malformed_lines += 1
            generic_chunks.append(stripped)
            continue
        if not isinstance(event, dict):
            continue
        events.append(event)
        session_id = session_id or find_session_id(event)
        event_type = str(event.get("type") or event.get("event") or "").lower()
        if "tool" in event_type or "tool" in event:
            tool_event_count += 1
        role = str(event.get("role") or "").lower()
        nested_message = event.get("message")
        if isinstance(nested_message, dict):
            role = role or str(nested_message.get("role") or "").lower()
        strings = [text.strip() for text in collect_string_values(event) if text and text.strip()]
        if role == "assistant" or "assistant" in event_type or "message" in event_type:
            assistant_chunks.extend(strings)
        else:
            generic_chunks.extend(strings)

    chunks = assistant_chunks or generic_chunks
    text = "\n".join(dict.fromkeys(chunks)).strip()
    if not text and stdout.strip():
        text = stdout.strip()
    truncated = len(text) > max_output_chars
    if truncated:
        text = text[:max_output_chars].rstrip() + "\n[truncated]"
    return {
        "summary": text,
        "session_id": session_id,
        "event_count": len(events),
        "tool_event_count": tool_event_count,
        "malformed_line_count": malformed_lines,
        "truncated": truncated,
    }


def run_delegate(arguments: dict[str, Any]) -> dict[str, Any]:
    env = merged_env()
    opencode_bin = shutil.which("opencode")
    if not opencode_bin:
        raise DelegatorError(
            "opencode_not_found",
            "Could not find `opencode` in PATH.",
            "Install opencode or ensure the MCP server environment includes its PATH.",
        )

    task = str(arguments.get("task") or "").strip()
    if not task:
        raise DelegatorError("missing_task", "task is required.")
    if coerce_bool(arguments.get("contains_multimodal"), default=False):
        raise DelegatorError(
            "multimodal_task_rejected",
            "Refusing to delegate a multimodal task to opencode/deepseek.",
            "Use a multimodal-capable Codex tool first, then delegate extracted text if needed.",
        )

    working_directory = validate_working_directory(arguments.get("working_directory"))
    files = validate_files(arguments.get("files"), working_directory)
    mode = str(arguments.get("mode") or "research")
    allow_edits = coerce_bool(arguments.get("allow_edits"), default=False)
    timeout_sec = coerce_int(
        arguments.get("timeout_sec") or env.get("OPENCODE_DELEGATOR_TIMEOUT_SEC"),
        default=DEFAULT_TIMEOUT_SEC,
        minimum=30,
    )
    max_output_chars = coerce_int(arguments.get("max_output_chars"), default=DEFAULT_MAX_OUTPUT_CHARS, minimum=1000)
    model = coerce_optional_string(arguments.get("model")) or coerce_optional_string(env.get("OPENCODE_DELEGATOR_MODEL"))
    agent = coerce_optional_string(arguments.get("agent")) or coerce_optional_string(env.get("OPENCODE_DELEGATOR_AGENT"))
    variant = coerce_optional_string(arguments.get("variant")) or coerce_optional_string(env.get("OPENCODE_DELEGATOR_VARIANT"))
    session_id = coerce_optional_string(arguments.get("session_id"))
    attach_url = coerce_optional_string(env.get("OPENCODE_DELEGATOR_ATTACH"))

    warnings: list[str] = []
    readonly_config_path: str | None = None
    if not allow_edits:
        readonly_config_path = create_readonly_config()
        if env.get("OPENCODE_CONFIG"):
            warnings.append("Overrode existing OPENCODE_CONFIG for this read-only delegation.")
        env["OPENCODE_CONFIG"] = readonly_config_path

    argv = [opencode_bin, "run", "--format", "json", "--dir", str(working_directory)]
    if attach_url:
        argv.extend(["--attach", attach_url])
    if session_id:
        argv.extend(["--session", session_id])
    if model:
        argv.extend(["--model", model])
    if agent:
        argv.extend(["--agent", agent])
    if variant:
        argv.extend(["--variant", variant])
    for path in files:
        argv.extend(["--file", str(path)])
    argv.append(build_prompt(task, mode, allow_edits))

    try:
        completed = subprocess.run(
            argv,
            cwd=str(working_directory),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DelegatorError(
            "opencode_timeout",
            f"opencode did not finish within {timeout_sec} seconds.",
            "Retry with a narrower task or a larger timeout_sec.",
            {"stdout": (exc.stdout or "")[-4000:], "stderr": (exc.stderr or "")[-4000:]},
        ) from exc
    finally:
        if readonly_config_path:
            try:
                Path(readonly_config_path).unlink(missing_ok=True)
            except OSError:
                pass

    parsed = parse_opencode_stdout(completed.stdout, max_output_chars)
    if completed.returncode != 0:
        raise DelegatorError(
            "opencode_failed",
            f"opencode exited with status {completed.returncode}.",
            "Check opencode auth/config, or run opencode manually with a tiny prompt.",
            {
                "stdout_tail": completed.stdout[-4000:],
                "stderr_tail": completed.stderr[-4000:],
                "parsed_summary": parsed.get("summary", ""),
            },
        )

    if completed.stderr.strip():
        warnings.append(completed.stderr.strip()[-2000:])

    return {
        "ok": True,
        "summary": parsed["summary"],
        "session_id": parsed["session_id"] or session_id,
        "resume_hint": "Pass session_id back to opencode_delegate to continue this opencode session.",
        "event_count": parsed["event_count"],
        "tool_event_count": parsed["tool_event_count"],
        "malformed_line_count": parsed["malformed_line_count"],
        "truncated": parsed["truncated"],
        "mode": mode,
        "model_source": "argument_or_env" if model else "opencode_default",
        "allow_edits": allow_edits,
        "files": [str(path) for path in files],
        "warnings": warnings,
    }


def run_status() -> dict[str, Any]:
    env = merged_env()
    opencode_bin = shutil.which("opencode")
    version: str | None = None
    version_error: str | None = None
    if opencode_bin:
        try:
            completed = subprocess.run(
                [opencode_bin, "--version"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=False,
            )
            if completed.returncode == 0:
                version = completed.stdout.strip()
            else:
                version_error = (completed.stderr or completed.stdout).strip()
        except Exception as exc:  # pragma: no cover - diagnostic path
            version_error = str(exc)

    return {
        "ok": bool(opencode_bin),
        "opencode_path": opencode_bin,
        "opencode_version": version,
        "opencode_version_error": version_error,
        "env_file": str(env_file_path()),
        "env_file_exists": env_file_path().exists(),
        "default_model_configured": bool(env.get("OPENCODE_DELEGATOR_MODEL")),
        "opencode_global_model": opencode_global_model(),
        "default_agent_configured": bool(env.get("OPENCODE_DELEGATOR_AGENT")),
        "default_variant_configured": bool(env.get("OPENCODE_DELEGATOR_VARIANT")),
        "attach_url_configured": bool(env.get("OPENCODE_DELEGATOR_ATTACH")),
    }


def handle_tool_call(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return tool_error(DelegatorError("invalid_arguments", "Tool arguments must be an object.").to_payload())
    try:
        if name == "opencode_delegate":
            return tool_success(run_delegate(arguments))
        if name == "opencode_delegate_status":
            return tool_success(run_status())
    except DelegatorError as exc:
        return tool_error(exc.to_payload())
    return tool_error(DelegatorError("unknown_tool", f"Unknown tool name: {name}").to_payload())


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    message_id = message.get("id")
    params = message.get("params")

    if method == "initialize":
        return make_response(message_id, initialize(params if isinstance(params, dict) else None))
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return make_response(message_id, {})
    if method == "tools/list":
        return make_response(message_id, {"tools": TOOL_DEFINITIONS})
    if method == "resources/list":
        return make_response(message_id, {"resources": []})
    if method == "resources/templates/list":
        return make_response(message_id, {"resourceTemplates": []})
    if method == "prompts/list":
        return make_response(message_id, {"prompts": []})
    if method == "tools/call":
        if not isinstance(params, dict):
            return make_error(message_id, -32602, "tools/call requires params.")
        return make_response(message_id, handle_tool_call(params))
    if message_id is not None:
        return make_error(message_id, -32601, f"Method not found: {method}")
    return None


def main() -> int:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        response = handle_message(message)
        if response is not None:
            write_message(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

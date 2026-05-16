#!/usr/bin/env python3
"""Minimal newline-delimited JSON-RPC MCP server for MinerU parsing."""

from __future__ import annotations

import json
import sys
from typing import Any

from mineru_agent_client import DEFAULT_TIMEOUT_SEC, MinerUAgentClient, MinerUClientError


SERVER_INFO = {
    "name": "mineru-pdf-router",
    "version": "0.2.2",
}

TOOL_DEFINITION = {
    "name": "mineru_parse_document",
    "description": (
        "Convert a local file or remote document URL through MinerU. When MINERU_API_KEY is "
        "configured, use the v4 precision API and extract Markdown from full.md inside the result "
        "zip archive; otherwise fall back to the v1 lightweight Agent API."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "source_type": {
                "type": "string",
                "enum": ["local_path", "remote_url"],
                "description": "Use `local_path` for a local file path or `remote_url` for a document URL.",
            },
            "source": {
                "type": "string",
                "description": "Absolute local path or remote URL to submit to MinerU.",
            },
            "file_name": {
                "type": "string",
                "description": "Optional filename hint, mainly useful when a remote URL does not expose a reliable filename.",
            },
            "language": {
                "type": "string",
                "default": "ch",
                "description": "OCR language hint for PDF parsing.",
            },
            "page_range": {
                "type": "string",
                "description": "Optional PDF page subset using a single page like `5` or a simple range like `1-10`.",
            },
            "enable_table": {
                "type": "boolean",
                "default": True,
                "description": "Pass MinerU's table recognition flag through for PDF parsing.",
            },
            "is_ocr": {
                "type": "boolean",
                "default": False,
                "description": "Pass MinerU's OCR flag through for PDF parsing.",
            },
            "enable_formula": {
                "type": "boolean",
                "default": True,
                "description": "Pass MinerU's formula recognition flag through for PDF parsing.",
            },
            "timeout_sec": {
                "type": "integer",
                "default": DEFAULT_TIMEOUT_SEC,
                "minimum": 10,
                "description": "Maximum time to wait for task completion before returning a timeout error.",
            },
        },
        "required": ["source_type", "source"],
        "additionalProperties": False,
    },
}


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
    return {
        "protocolVersion": protocol_version,
        "capabilities": {
            "tools": {},
        },
        "serverInfo": SERVER_INFO,
    }


def handle_tool_call(arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        client = MinerUAgentClient()
        result = client.parse_document(
            source_type=str(arguments["source_type"]),
            source=str(arguments["source"]),
            file_name=coerce_optional_string(arguments.get("file_name")),
            language=str(arguments.get("language", "ch")),
            page_range=coerce_optional_string(arguments.get("page_range")),
            enable_table=coerce_bool(arguments.get("enable_table", True), default=True),
            is_ocr=coerce_bool(arguments.get("is_ocr", False), default=False),
            enable_formula=coerce_bool(arguments.get("enable_formula", True), default=True),
            timeout_sec=coerce_int(arguments.get("timeout_sec", DEFAULT_TIMEOUT_SEC), default=DEFAULT_TIMEOUT_SEC),
        )
    except MinerUClientError as exc:
        return tool_error(exc.to_payload())
    return tool_success(result)


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
    raise MinerUClientError(
        code="invalid_boolean",
        message="Boolean MCP arguments must be true or false.",
        suggestion="Pass booleans such as `true` or `false` for enable_table, is_ocr, and enable_formula.",
    )


def coerce_int(value: Any, *, default: int) -> int:
    if value is None:
        return default
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise MinerUClientError(
            code="invalid_integer",
            message="timeout_sec must be an integer.",
            suggestion="Pass timeout_sec as an integer number of seconds.",
        ) from exc
    return normalized


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
        return make_response(message_id, {"tools": [TOOL_DEFINITION]})
    if method == "resources/list":
        return make_response(message_id, {"resources": []})
    if method == "resources/templates/list":
        return make_response(message_id, {"resourceTemplates": []})
    if method == "prompts/list":
        return make_response(message_id, {"prompts": []})
    if method == "tools/call":
        if not isinstance(params, dict):
            return make_error(message_id, -32602, "tools/call requires params.")
        if params.get("name") != "mineru_parse_document":
            return make_error(message_id, -32602, "Unknown tool name.")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return make_error(message_id, -32602, "Tool arguments must be an object.")
        return make_response(message_id, handle_tool_call(arguments))
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

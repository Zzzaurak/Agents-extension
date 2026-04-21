#!/usr/bin/env python3
"""MinerU client with automatic v1 lightweight and v4 precision routing."""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


DEFAULT_API_BASE = "https://mineru.net"
DEFAULT_CONFIG_PATH = Path.home() / ".codex" / "mineru-pdf-router.env"
DEFAULT_POLL_INTERVAL_SEC = 2.0
DEFAULT_TIMEOUT_SEC = 120
DEFAULT_V4_MODEL_VERSION = "vlm"
LOCAL_FILE_SIZE_LIMIT_BYTES = 10 * 1024 * 1024
LOCAL_PDF_PAGE_LIMIT = 20
REQUEST_TIMEOUT_SEC = 30

BACKEND_AUTO = "auto"
BACKEND_V1_AGENT = "v1-agent"
BACKEND_V4_PRECISION = "v4-precision"

PROVIDER_V1_NAME = "mineru-v1-agent"
PROVIDER_V4_NAME = "mineru-v4-precision"

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".jp2",
    ".webp",
    ".gif",
    ".bmp",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
}

V4_MODEL_VERSIONS = {"pipeline", "vlm"}
TERMINAL_V4_STATES = {"done", "failed"}
INTERMEDIATE_V4_STATES = {"waiting-file", "pending", "running", "converting"}


class MinerUClientError(Exception):
    """Structured error for config, preflight, HTTP, and MinerU API failures."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        provider: str,
        backend: str,
        model_version: str,
        suggestion: str | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
        source_type: str | None = None,
        normalized_source: str | None = None,
        task_id: str | None = None,
        batch_id: str | None = None,
        state: str = "failed",
        warnings: list[str] | None = None,
        result_archive_url: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.provider = provider
        self.backend = backend
        self.model_version = model_version
        self.suggestion = suggestion
        self.retryable = retryable
        self.details = details or {}
        self.source_type = source_type
        self.normalized_source = normalized_source
        self.task_id = task_id
        self.batch_id = batch_id
        self.state = state
        self.warnings = list(warnings or [])
        self.result_archive_url = result_archive_url

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "provider": self.provider,
            "backend": self.backend,
            "model_version": self.model_version,
            "task_id": self.task_id or "",
            "batch_id": self.batch_id or "",
            "state": self.state,
            "markdown": "",
            "markdown_url": "",
            "result_archive_url": self.result_archive_url,
            "source_type": self.source_type,
            "normalized_source": self.normalized_source,
            "warnings": self.warnings,
            "error_code": self.code,
            "error_message": self.message,
            "retryable": self.retryable,
        }
        if self.suggestion:
            payload["suggestion"] = self.suggestion
        if self.details:
            payload["details"] = self.details
        return payload


@dataclass(frozen=True)
class MinerUSettings:
    api_base: str
    api_key: str | None
    backend: str
    model_version: str
    config_path: str
    config_exists: bool
    api_key_source: str


def _parse_page_range(page_range: str | None) -> tuple[str | None, int | None, int | None]:
    if page_range is None:
        return None, None, None
    normalized = page_range.strip().replace(" ", "")
    if not normalized:
        return None, None, None
    if "," in normalized:
        raise MinerUClientError(
            code="invalid_page_range",
            message="page_range only supports a single page or a simple from-to range.",
            suggestion="Use a value like `5` or `1-10`.",
            provider="",
            backend="",
            model_version="",
        )
    if "-" in normalized:
        start_raw, end_raw = normalized.split("-", 1)
        if not start_raw.isdigit() or not end_raw.isdigit():
            raise MinerUClientError(
                code="invalid_page_range",
                message="page_range must use positive integer page numbers.",
                suggestion="Use a value like `5` or `1-10`.",
                provider="",
                backend="",
                model_version="",
            )
        start = int(start_raw)
        end = int(end_raw)
    else:
        if not normalized.isdigit():
            raise MinerUClientError(
                code="invalid_page_range",
                message="page_range must be a single positive integer page number or a from-to range.",
                suggestion="Use a value like `5` or `1-10`.",
                provider="",
                backend="",
                model_version="",
            )
        start = end = int(normalized)

    if start < 1 or end < 1 or end < start:
        raise MinerUClientError(
            code="invalid_page_range",
            message="page_range must be a forward range of positive page numbers.",
            suggestion="Use a value like `5` or `1-10`.",
            provider="",
            backend="",
            model_version="",
        )
    return normalized, start, end


def _count_requested_pages(page_range: str | None) -> int | None:
    normalized, start, end = _parse_page_range(page_range)
    if normalized is None or start is None or end is None:
        return None
    return end - start + 1


def _count_pdf_pages(path: Path) -> int | None:
    try:
        import pypdf  # type: ignore

        with path.open("rb") as handle:
            reader = pypdf.PdfReader(handle)
            return len(reader.pages)
    except Exception:
        pass

    mdls = _count_pdf_pages_with_mdls(path)
    if mdls is not None:
        return mdls
    return None


def _count_pdf_pages_with_mdls(path: Path) -> int | None:
    if not shutil_which("mdls"):
        return None
    try:
        result = subprocess.run(
            ["mdls", "-name", "kMDItemNumberOfPages", "-raw", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    value = result.stdout.strip()
    return int(value) if value.isdigit() else None


def shutil_which(binary: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        candidate = Path(directory) / binary
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise MinerUClientError(
                code="invalid_config_line",
                message=f"Invalid line in MinerU config file: {path}:{line_number}",
                suggestion="Use KEY=value lines or comment lines starting with #.",
                provider="",
                backend="",
                model_version="",
                details={"line": raw_line},
            )
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise MinerUClientError(
                code="invalid_config_line",
                message=f"Invalid empty key in MinerU config file: {path}:{line_number}",
                suggestion="Use KEY=value lines or comment lines starting with #.",
                provider="",
                backend="",
                model_version="",
                details={"line": raw_line},
            )
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _resolve_config_value(name: str, file_values: dict[str, str], default: str | None) -> tuple[str | None, str]:
    if name in os.environ:
        return os.environ[name], "env"
    if name in file_values:
        return file_values[name], "config"
    return default, "default"


def load_settings(api_base_override: str | None = None) -> MinerUSettings:
    config_override = os.environ.get("MINERU_CONFIG_PATH")
    config_path = Path(config_override).expanduser() if config_override else DEFAULT_CONFIG_PATH
    file_values = _parse_env_file(config_path)

    api_base_raw, _ = _resolve_config_value("MINERU_API_BASE", file_values, DEFAULT_API_BASE)
    backend_raw, _ = _resolve_config_value("MINERU_BACKEND", file_values, BACKEND_AUTO)
    model_version_raw, _ = _resolve_config_value(
        "MINERU_V4_MODEL_VERSION",
        file_values,
        DEFAULT_V4_MODEL_VERSION,
    )
    api_key_raw, api_key_source = _resolve_config_value("MINERU_API_KEY", file_values, None)

    api_base = (api_base_override or api_base_raw or DEFAULT_API_BASE).strip().rstrip("/")
    backend = (backend_raw or BACKEND_AUTO).strip().lower()
    model_version = (model_version_raw or DEFAULT_V4_MODEL_VERSION).strip().lower()
    api_key = (api_key_raw or "").strip() or None

    if backend not in {BACKEND_AUTO, BACKEND_V1_AGENT, BACKEND_V4_PRECISION}:
        raise MinerUClientError(
            code="invalid_backend",
            message="MINERU_BACKEND must be one of auto, v1-agent, or v4-precision.",
            suggestion=f"Update {config_path} and retry.",
            provider="",
            backend=backend,
            model_version=model_version,
            details={"config_path": str(config_path)},
        )
    if model_version not in V4_MODEL_VERSIONS:
        raise MinerUClientError(
            code="invalid_model_version",
            message="MINERU_V4_MODEL_VERSION must be `vlm` or `pipeline` in this plugin.",
            suggestion=f"Update {config_path} and retry.",
            provider="",
            backend=backend,
            model_version=model_version,
            details={"config_path": str(config_path)},
        )

    return MinerUSettings(
        api_base=api_base,
        api_key=api_key,
        backend=backend,
        model_version=model_version,
        config_path=str(config_path),
        config_exists=config_path.exists(),
        api_key_source=api_key_source if api_key else "missing",
    )


class MinerUAgentClient:
    """Wrap MinerU v1 lightweight and v4 precision parsing workflows."""

    def __init__(
        self,
        api_base: str | None = None,
        poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
        settings: MinerUSettings | None = None,
    ) -> None:
        self.settings = settings or load_settings(api_base_override=api_base)
        self.api_base = self.settings.api_base
        self.agent_base = f"{self.api_base}/api/v1/agent"
        self.v4_base = f"{self.api_base}/api/v4"
        self.poll_interval_sec = poll_interval_sec

    def parse_document(
        self,
        *,
        source_type: str,
        source: str,
        file_name: str | None = None,
        language: str = "ch",
        page_range: str | None = None,
        enable_table: bool = True,
        is_ocr: bool = False,
        enable_formula: bool = True,
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    ) -> dict[str, Any]:
        backend = self._resolve_backend()
        try:
            normalized_page_range, _, _ = _parse_page_range(page_range)
        except MinerUClientError as exc:
            raise self._error(
                code=exc.code,
                message=exc.message,
                suggestion=exc.suggestion,
                retryable=exc.retryable,
                details=exc.details,
                backend=backend,
                source_type=source_type,
                normalized_source=source,
            ) from exc

        if backend == BACKEND_V4_PRECISION:
            return self._parse_document_v4(
                source_type=source_type,
                source=source,
                file_name=file_name,
                language=language,
                page_range=normalized_page_range,
                enable_table=enable_table,
                is_ocr=is_ocr,
                enable_formula=enable_formula,
                timeout_sec=timeout_sec,
            )
        return self._parse_document_v1(
            source_type=source_type,
            source=source,
            file_name=file_name,
            language=language,
            page_range=normalized_page_range,
            enable_table=enable_table,
            is_ocr=is_ocr,
            enable_formula=enable_formula,
            timeout_sec=timeout_sec,
        )

    def _resolve_backend(self) -> str:
        if self.settings.backend == BACKEND_AUTO:
            return BACKEND_V4_PRECISION if self.settings.api_key else BACKEND_V1_AGENT
        if self.settings.backend == BACKEND_V4_PRECISION and not self.settings.api_key:
            raise self._error(
                code="missing_api_key",
                message="MINERU_BACKEND is set to v4-precision but MINERU_API_KEY is missing.",
                suggestion=f"Set MINERU_API_KEY in {self.settings.config_path} or change MINERU_BACKEND to auto/v1-agent.",
                backend=BACKEND_V4_PRECISION,
            )
        return self.settings.backend

    def _parse_document_v1(
        self,
        *,
        source_type: str,
        source: str,
        file_name: str | None,
        language: str,
        page_range: str | None,
        enable_table: bool,
        is_ocr: bool,
        enable_formula: bool,
        timeout_sec: int,
    ) -> dict[str, Any]:
        if source_type == "local_path":
            return self._parse_local_file_v1(
                source=source,
                file_name=file_name,
                language=language,
                page_range=page_range,
                enable_table=enable_table,
                is_ocr=is_ocr,
                enable_formula=enable_formula,
                timeout_sec=timeout_sec,
            )
        if source_type == "remote_url":
            return self._parse_remote_url_v1(
                source=source,
                file_name=file_name,
                language=language,
                page_range=page_range,
                enable_table=enable_table,
                is_ocr=is_ocr,
                enable_formula=enable_formula,
                timeout_sec=timeout_sec,
            )
        raise self._error(
            code="invalid_source_type",
            message="source_type must be `local_path` or `remote_url`.",
            suggestion="Call the tool with `source_type=\"local_path\"` for files or `source_type=\"remote_url\"` for URLs.",
            backend=BACKEND_V1_AGENT,
            source_type=source_type,
            normalized_source=source,
        )

    def _parse_document_v4(
        self,
        *,
        source_type: str,
        source: str,
        file_name: str | None,
        language: str,
        page_range: str | None,
        enable_table: bool,
        is_ocr: bool,
        enable_formula: bool,
        timeout_sec: int,
    ) -> dict[str, Any]:
        if source_type == "local_path":
            return self._parse_local_file_v4(
                source=source,
                file_name=file_name,
                language=language,
                page_range=page_range,
                enable_table=enable_table,
                is_ocr=is_ocr,
                enable_formula=enable_formula,
                timeout_sec=timeout_sec,
            )
        if source_type == "remote_url":
            return self._parse_remote_url_v4(
                source=source,
                file_name=file_name,
                language=language,
                page_range=page_range,
                enable_table=enable_table,
                is_ocr=is_ocr,
                enable_formula=enable_formula,
                timeout_sec=timeout_sec,
            )
        raise self._error(
            code="invalid_source_type",
            message="source_type must be `local_path` or `remote_url`.",
            suggestion="Call the tool with `source_type=\"local_path\"` for files or `source_type=\"remote_url\"` for URLs.",
            backend=BACKEND_V4_PRECISION,
            source_type=source_type,
            normalized_source=source,
        )

    def _parse_local_file_v1(
        self,
        *,
        source: str,
        file_name: str | None,
        language: str,
        page_range: str | None,
        enable_table: bool,
        is_ocr: bool,
        enable_formula: bool,
        timeout_sec: int,
    ) -> dict[str, Any]:
        normalized, effective_file_name = self._resolve_local_file(source, file_name, backend=BACKEND_V1_AGENT)
        warnings = self._backend_warnings(BACKEND_V1_AGENT)
        warnings.extend(self._preflight_local_file(normalized, effective_file_name, page_range))
        payload = {
            "file_name": effective_file_name,
            "language": language,
            "enable_table": enable_table,
            "is_ocr": is_ocr,
            "enable_formula": enable_formula,
        }
        if page_range:
            payload["page_range"] = page_range
        created = self._post_json_v1(
            f"{self.agent_base}/parse/file",
            payload,
            normalized_source=str(normalized),
            source_type="local_path",
        )
        data = created.get("data") or {}
        task_id = data.get("task_id")
        file_url = data.get("file_url")
        if not task_id or not file_url:
            raise self._error(
                code="bad_create_response",
                message="MinerU v1 did not return the expected signed upload fields.",
                suggestion="Retry the request later or inspect MinerU's upstream response.",
                backend=BACKEND_V1_AGENT,
                source_type="local_path",
                normalized_source=str(normalized),
                details={"response": created},
            )
        self._upload_local_file(
            file_url=file_url,
            path=normalized,
            backend=BACKEND_V1_AGENT,
            source_type="local_path",
            normalized_source=str(normalized),
            task_id=task_id,
        )
        return self._poll_until_done_v1(
            task_id=task_id,
            source_type="local_path",
            normalized_source=str(normalized),
            timeout_sec=timeout_sec,
            warnings=warnings,
        )

    def _parse_remote_url_v1(
        self,
        *,
        source: str,
        file_name: str | None,
        language: str,
        page_range: str | None,
        enable_table: bool,
        is_ocr: bool,
        enable_formula: bool,
        timeout_sec: int,
    ) -> dict[str, Any]:
        normalized_source = self._normalize_remote_url(source, backend=BACKEND_V1_AGENT)
        warnings = self._backend_warnings(BACKEND_V1_AGENT)
        warnings.append("Remote URLs are submitted directly to MinerU without local size or page preflight.")
        payload = {
            "url": normalized_source,
            "language": language,
            "enable_table": enable_table,
            "is_ocr": is_ocr,
            "enable_formula": enable_formula,
        }
        if file_name:
            payload["file_name"] = file_name.strip()
        if page_range:
            payload["page_range"] = page_range
        created = self._post_json_v1(
            f"{self.agent_base}/parse/url",
            payload,
            normalized_source=normalized_source,
            source_type="remote_url",
        )
        data = created.get("data") or {}
        task_id = data.get("task_id")
        if not task_id:
            raise self._error(
                code="bad_create_response",
                message="MinerU v1 did not return a task_id for the remote URL request.",
                suggestion="Retry the request later or inspect MinerU's upstream response.",
                backend=BACKEND_V1_AGENT,
                source_type="remote_url",
                normalized_source=normalized_source,
                details={"response": created},
            )
        return self._poll_until_done_v1(
            task_id=task_id,
            source_type="remote_url",
            normalized_source=normalized_source,
            timeout_sec=timeout_sec,
            warnings=warnings,
        )

    def _parse_local_file_v4(
        self,
        *,
        source: str,
        file_name: str | None,
        language: str,
        page_range: str | None,
        enable_table: bool,
        is_ocr: bool,
        enable_formula: bool,
        timeout_sec: int,
    ) -> dict[str, Any]:
        normalized, effective_file_name = self._resolve_local_file(source, file_name, backend=BACKEND_V4_PRECISION)
        warnings = self._backend_warnings(BACKEND_V4_PRECISION)
        warnings.append("MinerU v4 returns a zip archive. Markdown is extracted from `full.md` inside `full_zip_url`.")
        if file_name:
            warnings.append(
                "MinerU v4 remote URL extraction does not support a true filename hint. "
                "file_name is only preserved as data_id metadata."
            )
        payload: dict[str, Any] = {
            "files": [
                {
                    "name": effective_file_name,
                    "is_ocr": is_ocr,
                }
            ],
            "enable_formula": enable_formula,
            "enable_table": enable_table,
            "language": language,
            "model_version": self.settings.model_version,
        }
        if page_range:
            payload["files"][0]["page_ranges"] = page_range
        created = self._post_json_v4(
            f"{self.v4_base}/file-urls/batch",
            payload,
            normalized_source=str(normalized),
            source_type="local_path",
        )
        batch_id, file_urls = self._extract_v4_upload_targets(created, str(normalized), "local_path")
        self._upload_local_file(
            file_url=file_urls[0],
            path=normalized,
            backend=BACKEND_V4_PRECISION,
            source_type="local_path",
            normalized_source=str(normalized),
            batch_id=batch_id,
        )
        return self._poll_until_done_v4(
            batch_id=batch_id,
            source_type="local_path",
            normalized_source=str(normalized),
            timeout_sec=timeout_sec,
            warnings=warnings,
        )

    def _parse_remote_url_v4(
        self,
        *,
        source: str,
        file_name: str | None,
        language: str,
        page_range: str | None,
        enable_table: bool,
        is_ocr: bool,
        enable_formula: bool,
        timeout_sec: int,
    ) -> dict[str, Any]:
        normalized_source = self._normalize_remote_url(source, backend=BACKEND_V4_PRECISION)
        warnings = self._backend_warnings(BACKEND_V4_PRECISION)
        warnings.append("MinerU v4 returns a zip archive. Markdown is extracted from `full.md` inside `full_zip_url`.")
        payload: dict[str, Any] = {
            "files": [
                {
                    "url": normalized_source,
                    "is_ocr": is_ocr,
                }
            ],
            "enable_formula": enable_formula,
            "enable_table": enable_table,
            "language": language,
            "model_version": self.settings.model_version,
        }
        if page_range:
            payload["files"][0]["page_ranges"] = page_range
        if file_name:
            payload["files"][0]["data_id"] = file_name.strip()
        created = self._post_json_v4(
            f"{self.v4_base}/extract/task/batch",
            payload,
            normalized_source=normalized_source,
            source_type="remote_url",
        )
        data = created.get("data") or {}
        batch_id = data.get("batch_id")
        if not batch_id:
            raise self._error(
                code="bad_create_response",
                message="MinerU v4 did not return a batch_id for the remote URL request.",
                suggestion="Retry the request later or inspect MinerU's upstream response.",
                backend=BACKEND_V4_PRECISION,
                source_type="remote_url",
                normalized_source=normalized_source,
                details={"response": created},
            )
        return self._poll_until_done_v4(
            batch_id=str(batch_id),
            source_type="remote_url",
            normalized_source=normalized_source,
            timeout_sec=timeout_sec,
            warnings=warnings,
        )

    def _resolve_local_file(
        self,
        source: str,
        file_name: str | None,
        *,
        backend: str,
    ) -> tuple[Path, str]:
        path = Path(source).expanduser()
        try:
            normalized_path = str(path.resolve(strict=True))
        except FileNotFoundError as exc:
            raise self._error(
                code="missing_file",
                message=f"Local file not found: {path}",
                suggestion="Pass an existing absolute path to a local file.",
                backend=backend,
                source_type="local_path",
                normalized_source=str(path),
            ) from exc

        normalized = Path(normalized_path)
        effective_file_name = (file_name or normalized.name).strip()
        if not effective_file_name:
            raise self._error(
                code="missing_file_name",
                message="Could not determine a file_name for the local file.",
                suggestion="Pass file_name explicitly or use a file with a normal filename.",
                backend=backend,
                source_type="local_path",
                normalized_source=str(normalized),
            )

        extension = normalized.suffix.lower()
        file_name_extension = Path(effective_file_name).suffix.lower()
        effective_extension = file_name_extension or extension
        if effective_extension not in SUPPORTED_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            raise self._error(
                code="unsupported_file_type",
                message=f"Unsupported local file type `{effective_extension or '<none>'}` for MinerU parsing.",
                suggestion=f"Use one of: {supported}",
                backend=backend,
                source_type="local_path",
                normalized_source=str(normalized),
            )
        if file_name_extension and extension and file_name_extension != extension:
            raise self._error(
                code="file_name_mismatch",
                message="file_name extension does not match the local file extension.",
                suggestion="Omit file_name or pass a matching filename.",
                backend=backend,
                source_type="local_path",
                normalized_source=str(normalized),
                details={"file_name": effective_file_name, "path_suffix": extension},
            )
        return normalized, effective_file_name

    def _preflight_local_file(
        self,
        path: Path,
        file_name: str,
        page_range: str | None,
    ) -> list[str]:
        warnings = [
            "MinerU v1 lightweight output is Markdown-only and is not a layout-fidelity check."
        ]
        size_bytes = path.stat().st_size
        if size_bytes > LOCAL_FILE_SIZE_LIMIT_BYTES:
            raise self._error(
                code="file_too_large",
                message="Local file exceeds MinerU lightweight size limit of 10 MB.",
                suggestion="Split or compress the file before retrying, or configure MINERU_API_KEY to use the v4 precision route.",
                backend=BACKEND_V1_AGENT,
                source_type="local_path",
                normalized_source=str(path),
                details={"size_bytes": size_bytes, "size_limit_bytes": LOCAL_FILE_SIZE_LIMIT_BYTES},
            )
        effective_extension = Path(file_name).suffix.lower() or path.suffix.lower()
        if effective_extension != ".pdf":
            return warnings
        requested_pages = _count_requested_pages(page_range)
        if requested_pages is not None and requested_pages > LOCAL_PDF_PAGE_LIMIT:
            raise self._error(
                code="page_range_too_large",
                message="Requested page_range exceeds MinerU lightweight PDF limit of 20 pages.",
                suggestion="Reduce page_range to 20 pages or fewer, or configure MINERU_API_KEY to use the v4 precision route.",
                backend=BACKEND_V1_AGENT,
                source_type="local_path",
                normalized_source=str(path),
                details={"page_range": page_range, "page_limit": LOCAL_PDF_PAGE_LIMIT},
            )
        total_pages = _count_pdf_pages(path)
        if total_pages is None:
            raise self._error(
                code="page_count_unknown",
                message="Could not determine local PDF page count for lightweight preflight.",
                suggestion="Install `pypdf` or run on macOS where `mdls` is available, then retry.",
                backend=BACKEND_V1_AGENT,
                source_type="local_path",
                normalized_source=str(path),
            )
        warnings.append(f"Local PDF preflight detected {total_pages} page(s).")
        if page_range:
            normalized_page_range, _, end = _parse_page_range(page_range)
            assert normalized_page_range is not None
            if end is not None and end > total_pages:
                raise self._error(
                    code="page_range_out_of_bounds",
                    message="page_range extends beyond the end of the local PDF.",
                    suggestion="Use a page_range within the document page count.",
                    backend=BACKEND_V1_AGENT,
                    source_type="local_path",
                    normalized_source=str(path),
                    details={"page_range": page_range, "total_pages": total_pages},
                )
            warnings.append(f"Only page_range {normalized_page_range} will be submitted to MinerU.")
            return warnings
        if total_pages > LOCAL_PDF_PAGE_LIMIT:
            raise self._error(
                code="pdf_page_limit_exceeded",
                message="Local PDF exceeds MinerU lightweight limit of 20 pages.",
                suggestion="Retry with a smaller page_range, split the PDF, or configure MINERU_API_KEY to use the v4 precision route.",
                backend=BACKEND_V1_AGENT,
                source_type="local_path",
                normalized_source=str(path),
                details={"total_pages": total_pages, "page_limit": LOCAL_PDF_PAGE_LIMIT},
            )
        return warnings

    def _normalize_remote_url(self, source: str, *, backend: str) -> str:
        normalized = source.strip()
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise self._error(
                code="invalid_remote_url",
                message="Remote URL must use http or https.",
                suggestion="Pass a full URL such as `https://example.com/file.pdf`.",
                backend=backend,
                source_type="remote_url",
                normalized_source=normalized,
            )
        return normalized

    def _post_json_v1(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        normalized_source: str,
        source_type: str,
    ) -> dict[str, Any]:
        try:
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=REQUEST_TIMEOUT_SEC,
            )
        except requests.RequestException as exc:
            raise self._error(
                code="request_failed",
                message=f"Could not reach MinerU at {url}.",
                suggestion="Check network connectivity and try again.",
                retryable=True,
                backend=BACKEND_V1_AGENT,
                source_type=source_type,
                normalized_source=normalized_source,
            ) from exc
        return self._parse_v1_api_response(response, source_type=source_type, normalized_source=normalized_source)

    def _post_json_v4(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        normalized_source: str,
        source_type: str,
    ) -> dict[str, Any]:
        try:
            response = requests.post(
                url,
                json=payload,
                headers=self._v4_headers(),
                timeout=REQUEST_TIMEOUT_SEC,
            )
        except requests.RequestException as exc:
            raise self._error(
                code="request_failed",
                message=f"Could not reach MinerU at {url}.",
                suggestion="Check network connectivity and try again.",
                retryable=True,
                backend=BACKEND_V4_PRECISION,
                source_type=source_type,
                normalized_source=normalized_source,
            ) from exc
        return self._parse_v4_api_response(response, source_type=source_type, normalized_source=normalized_source)

    def _parse_v1_api_response(
        self,
        response: requests.Response,
        *,
        source_type: str,
        normalized_source: str,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        if response.status_code == 429:
            raise self._error(
                code="rate_limited",
                message="MinerU v1 lightweight API rate-limited this request with HTTP 429.",
                suggestion="Wait a moment and retry. If this persists, reduce request frequency.",
                retryable=True,
                backend=BACKEND_V1_AGENT,
                source_type=source_type,
                normalized_source=normalized_source,
                task_id=task_id,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise self._error(
                code="invalid_json",
                message="MinerU returned a non-JSON response.",
                suggestion="Retry later and inspect the upstream response body if the issue persists.",
                backend=BACKEND_V1_AGENT,
                source_type=source_type,
                normalized_source=normalized_source,
                task_id=task_id,
                details={"status_code": response.status_code, "body": response.text[:500]},
            ) from exc
        if not response.ok:
            raise self._error(
                code="http_error",
                message=f"MinerU returned HTTP {response.status_code}.",
                suggestion="Retry later or inspect the upstream response message.",
                retryable=response.status_code >= 500,
                backend=BACKEND_V1_AGENT,
                source_type=source_type,
                normalized_source=normalized_source,
                task_id=task_id,
                details={"status_code": response.status_code, "response": payload},
            )
        if payload.get("code") not in (0, None):
            raise self._error(
                code="api_error",
                message=str(payload.get("msg") or "MinerU returned a non-zero API code."),
                suggestion="Adjust the request or retry later.",
                backend=BACKEND_V1_AGENT,
                source_type=source_type,
                normalized_source=normalized_source,
                task_id=task_id,
                details={"response": payload},
            )
        return payload

    def _parse_v4_api_response(
        self,
        response: requests.Response,
        *,
        source_type: str,
        normalized_source: str,
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        if response.status_code == 429:
            raise self._error(
                code="rate_limited",
                message="MinerU v4 precision API rate-limited this request with HTTP 429.",
                suggestion="Wait a moment and retry. If this persists, reduce request frequency.",
                retryable=True,
                backend=BACKEND_V4_PRECISION,
                source_type=source_type,
                normalized_source=normalized_source,
                batch_id=batch_id,
            )

        payload: dict[str, Any] | None = None
        if response.content:
            try:
                parsed = response.json()
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                payload = parsed

        if response.status_code in {401, 403}:
            code = str((payload or {}).get("code") or response.status_code)
            message = str((payload or {}).get("msg") or f"MinerU returned HTTP {response.status_code}.")
            raise self._error(
                code=code,
                message=message,
                suggestion=f"Check MINERU_API_KEY in {self.settings.config_path} and ensure the Bearer token is valid.",
                backend=BACKEND_V4_PRECISION,
                source_type=source_type,
                normalized_source=normalized_source,
                batch_id=batch_id,
                details={"status_code": response.status_code, "response": payload or response.text[:500]},
            )

        if payload is None:
            raise self._error(
                code="invalid_json",
                message="MinerU returned a non-JSON response.",
                suggestion="Retry later and inspect the upstream response body if the issue persists.",
                backend=BACKEND_V4_PRECISION,
                source_type=source_type,
                normalized_source=normalized_source,
                batch_id=batch_id,
                details={"status_code": response.status_code, "body": response.text[:500]},
            )

        if not response.ok:
            raise self._error(
                code=str(payload.get("code") or "http_error"),
                message=str(payload.get("msg") or f"MinerU returned HTTP {response.status_code}."),
                suggestion=self._v4_error_suggestion(payload.get("code")),
                retryable=response.status_code >= 500,
                backend=BACKEND_V4_PRECISION,
                source_type=source_type,
                normalized_source=normalized_source,
                batch_id=batch_id,
                details={"status_code": response.status_code, "response": payload},
            )

        if payload.get("code") not in (0, None):
            raise self._error(
                code=str(payload.get("code")),
                message=str(payload.get("msg") or "MinerU returned a non-zero API code."),
                suggestion=self._v4_error_suggestion(payload.get("code")),
                backend=BACKEND_V4_PRECISION,
                source_type=source_type,
                normalized_source=normalized_source,
                batch_id=batch_id,
                details={"response": payload},
            )
        return payload

    def _extract_v4_upload_targets(
        self,
        created: dict[str, Any],
        normalized_source: str,
        source_type: str,
    ) -> tuple[str, list[str]]:
        data = created.get("data") or {}
        batch_id = data.get("batch_id")
        file_urls = data.get("file_urls")
        if not batch_id or not isinstance(file_urls, list) or len(file_urls) != 1:
            raise self._error(
                code="bad_create_response",
                message="MinerU v4 did not return the expected upload URL payload.",
                suggestion="Retry the request later or inspect MinerU's upstream response.",
                backend=BACKEND_V4_PRECISION,
                source_type=source_type,
                normalized_source=normalized_source,
                details={"response": created},
            )
        return str(batch_id), [str(file_urls[0])]

    def _upload_local_file(
        self,
        *,
        file_url: str,
        path: Path,
        backend: str,
        source_type: str,
        normalized_source: str,
        task_id: str | None = None,
        batch_id: str | None = None,
    ) -> None:
        try:
            with path.open("rb") as handle:
                response = requests.put(
                    file_url,
                    data=handle,
                    timeout=REQUEST_TIMEOUT_SEC,
                )
        except requests.RequestException as exc:
            raise self._error(
                code="upload_failed",
                message="Uploading the local file to MinerU's signed URL failed.",
                suggestion="Retry the request. If it keeps failing, regenerate a new signed upload URL.",
                retryable=True,
                backend=backend,
                source_type=source_type,
                normalized_source=normalized_source,
                task_id=task_id,
                batch_id=batch_id,
            ) from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise self._error(
                code="upload_rejected",
                message=f"Signed upload returned HTTP {response.status_code}.",
                suggestion="Retry the request so MinerU can issue a fresh signed upload URL.",
                retryable=True,
                backend=backend,
                source_type=source_type,
                normalized_source=normalized_source,
                task_id=task_id,
                batch_id=batch_id,
                details={"status_code": response.status_code, "body": response.text[:500]},
            )

    def _poll_until_done_v1(
        self,
        *,
        task_id: str,
        source_type: str,
        normalized_source: str,
        timeout_sec: int,
        warnings: list[str],
    ) -> dict[str, Any]:
        deadline = time.time() + timeout_sec
        url = f"{self.agent_base}/parse/{task_id}"
        while time.time() < deadline:
            try:
                response = requests.get(url, timeout=REQUEST_TIMEOUT_SEC)
            except requests.RequestException as exc:
                raise self._error(
                    code="poll_failed",
                    message="Polling MinerU for task status failed.",
                    suggestion="Retry later with the same source.",
                    retryable=True,
                    backend=BACKEND_V1_AGENT,
                    source_type=source_type,
                    normalized_source=normalized_source,
                    task_id=task_id,
                    warnings=warnings,
                ) from exc
            payload = self._parse_v1_api_response(
                response,
                source_type=source_type,
                normalized_source=normalized_source,
                task_id=task_id,
            )
            data = payload.get("data") or {}
            state = str(data.get("state", "unknown"))
            if state == "done":
                markdown_url = data.get("markdown_url")
                if not markdown_url:
                    raise self._error(
                        code="missing_markdown_url",
                        message="MinerU marked the task done but did not return markdown_url.",
                        suggestion="Retry the task or inspect the upstream response.",
                        backend=BACKEND_V1_AGENT,
                        source_type=source_type,
                        normalized_source=normalized_source,
                        task_id=task_id,
                        details={"response": payload},
                        warnings=warnings,
                    )
                markdown = self._download_text(
                    url=str(markdown_url),
                    backend=BACKEND_V1_AGENT,
                    source_type=source_type,
                    normalized_source=normalized_source,
                    task_id=task_id,
                    warnings=warnings,
                    download_kind="Markdown",
                )
                return self._success_payload(
                    backend=BACKEND_V1_AGENT,
                    task_id=task_id,
                    batch_id="",
                    state=state,
                    markdown=markdown,
                    markdown_url=str(markdown_url),
                    result_archive_url="",
                    source_type=source_type,
                    normalized_source=normalized_source,
                    warnings=warnings,
                )
            if state == "failed":
                err_code = data.get("err_code")
                err_msg = data.get("err_msg") or "MinerU reported a failed task."
                suggestion = "Retry later."
                if err_code == -30003:
                    suggestion = "Reduce page_range, split the PDF, or configure MINERU_API_KEY to use the v4 precision route."
                raise self._error(
                    code=str(err_code) if err_code is not None else "task_failed",
                    message=str(err_msg),
                    suggestion=suggestion,
                    backend=BACKEND_V1_AGENT,
                    source_type=source_type,
                    normalized_source=normalized_source,
                    task_id=task_id,
                    details={"err_code": err_code},
                    warnings=warnings,
                )
            time.sleep(self.poll_interval_sec)
        raise self._error(
            code="poll_timeout",
            message=f"Timed out after {timeout_sec} seconds waiting for MinerU task completion.",
            suggestion="Retry later or query the task again if you still have the task_id.",
            retryable=True,
            backend=BACKEND_V1_AGENT,
            source_type=source_type,
            normalized_source=normalized_source,
            task_id=task_id,
            warnings=warnings,
        )

    def _poll_until_done_v4(
        self,
        *,
        batch_id: str,
        source_type: str,
        normalized_source: str,
        timeout_sec: int,
        warnings: list[str],
    ) -> dict[str, Any]:
        deadline = time.time() + timeout_sec
        url = f"{self.v4_base}/extract-results/batch/{batch_id}"
        while time.time() < deadline:
            try:
                response = requests.get(url, headers=self._v4_headers(include_content_type=False), timeout=REQUEST_TIMEOUT_SEC)
            except requests.RequestException as exc:
                raise self._error(
                    code="poll_failed",
                    message="Polling MinerU v4 for batch status failed.",
                    suggestion="Retry later with the same source.",
                    retryable=True,
                    backend=BACKEND_V4_PRECISION,
                    source_type=source_type,
                    normalized_source=normalized_source,
                    batch_id=batch_id,
                    warnings=warnings,
                ) from exc
            payload = self._parse_v4_api_response(
                response,
                source_type=source_type,
                normalized_source=normalized_source,
                batch_id=batch_id,
            )
            data = payload.get("data") or {}
            extract_result = data.get("extract_result") or []
            if isinstance(extract_result, dict):
                extract_result = [extract_result]
            if not isinstance(extract_result, list) or not extract_result:
                raise self._error(
                    code="bad_poll_response",
                    message="MinerU v4 did not return extract_result entries for the batch.",
                    suggestion="Retry later or inspect the upstream response payload.",
                    backend=BACKEND_V4_PRECISION,
                    source_type=source_type,
                    normalized_source=normalized_source,
                    batch_id=batch_id,
                    details={"response": payload},
                    warnings=warnings,
                )
            result = extract_result[0] or {}
            state = str(result.get("state", "unknown"))
            if state == "done":
                result_archive_url = str(result.get("full_zip_url") or "")
                if not result_archive_url:
                    raise self._error(
                        code="missing_full_zip_url",
                        message="MinerU v4 marked the batch done but did not return full_zip_url.",
                        suggestion="Retry the task or inspect the upstream response.",
                        backend=BACKEND_V4_PRECISION,
                        source_type=source_type,
                        normalized_source=normalized_source,
                        batch_id=batch_id,
                        details={"response": payload},
                        warnings=warnings,
                    )
                markdown = self._download_v4_markdown_archive(
                    result_archive_url=result_archive_url,
                    batch_id=batch_id,
                    source_type=source_type,
                    normalized_source=normalized_source,
                    warnings=warnings,
                )
                return self._success_payload(
                    backend=BACKEND_V4_PRECISION,
                    task_id="",
                    batch_id=batch_id,
                    state=state,
                    markdown=markdown,
                    markdown_url="",
                    result_archive_url=result_archive_url,
                    source_type=source_type,
                    normalized_source=normalized_source,
                    warnings=warnings,
                )
            if state == "failed":
                err_msg = str(result.get("err_msg") or "MinerU reported a failed batch task.")
                err_code = result.get("err_code") or payload.get("code")
                raise self._error(
                    code=str(err_code or "task_failed"),
                    message=err_msg,
                    suggestion=self._v4_error_suggestion(err_code),
                    backend=BACKEND_V4_PRECISION,
                    source_type=source_type,
                    normalized_source=normalized_source,
                    batch_id=batch_id,
                    details={"response": payload, "err_code": err_code},
                    warnings=warnings,
                )
            if state not in INTERMEDIATE_V4_STATES:
                warnings = list(warnings) + [f"Observed unexpected MinerU v4 state `{state}` while polling."]
            time.sleep(self.poll_interval_sec)
        raise self._error(
            code="poll_timeout",
            message=f"Timed out after {timeout_sec} seconds waiting for MinerU batch completion.",
            suggestion="Retry later or query the batch again if you still have the batch_id.",
            retryable=True,
            backend=BACKEND_V4_PRECISION,
            source_type=source_type,
            normalized_source=normalized_source,
            batch_id=batch_id,
            warnings=warnings,
        )

    def _download_text(
        self,
        *,
        url: str,
        backend: str,
        source_type: str,
        normalized_source: str,
        warnings: list[str],
        download_kind: str,
        task_id: str | None = None,
        batch_id: str | None = None,
    ) -> str:
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT_SEC)
        except requests.RequestException as exc:
            raise self._error(
                code="download_failed",
                message=f"Downloading the {download_kind} failed.",
                suggestion="Retry later with the same task context if the result is still available.",
                retryable=True,
                backend=backend,
                source_type=source_type,
                normalized_source=normalized_source,
                task_id=task_id,
                batch_id=batch_id,
                warnings=warnings,
            ) from exc
        if not response.ok:
            raise self._error(
                code="download_rejected",
                message=f"Downloading the {download_kind} returned HTTP {response.status_code}.",
                suggestion="Retry later with the same task context if the result is still available.",
                retryable=response.status_code >= 500,
                backend=backend,
                source_type=source_type,
                normalized_source=normalized_source,
                task_id=task_id,
                batch_id=batch_id,
                warnings=warnings,
                details={"status_code": response.status_code, "body": response.text[:500]},
            )
        return response.text

    def _download_v4_markdown_archive(
        self,
        *,
        result_archive_url: str,
        batch_id: str,
        source_type: str,
        normalized_source: str,
        warnings: list[str],
    ) -> str:
        try:
            response = requests.get(result_archive_url, timeout=REQUEST_TIMEOUT_SEC)
        except requests.RequestException as exc:
            raise self._error(
                code="archive_download_failed",
                message="MinerU returned full_zip_url, but downloading the zip archive failed.",
                suggestion="Retry later with the same batch_id if the result is still available.",
                retryable=True,
                backend=BACKEND_V4_PRECISION,
                source_type=source_type,
                normalized_source=normalized_source,
                batch_id=batch_id,
                warnings=warnings,
                result_archive_url=result_archive_url,
            ) from exc
        if not response.ok:
            raise self._error(
                code="archive_download_rejected",
                message=f"Downloading full_zip_url returned HTTP {response.status_code}.",
                suggestion="Retry later with the same batch_id if the result is still available.",
                retryable=response.status_code >= 500,
                backend=BACKEND_V4_PRECISION,
                source_type=source_type,
                normalized_source=normalized_source,
                batch_id=batch_id,
                warnings=warnings,
                details={"status_code": response.status_code, "body": response.text[:500]},
                result_archive_url=result_archive_url,
            )
        try:
            archive = zipfile.ZipFile(io.BytesIO(response.content))
        except zipfile.BadZipFile as exc:
            raise self._error(
                code="invalid_result_archive",
                message="MinerU returned a result archive that is not a valid zip file.",
                suggestion="Retry later with the same batch_id if the result is still available.",
                backend=BACKEND_V4_PRECISION,
                source_type=source_type,
                normalized_source=normalized_source,
                batch_id=batch_id,
                warnings=warnings,
                result_archive_url=result_archive_url,
            ) from exc

        candidate_paths = sorted(
            [
                name
                for name in archive.namelist()
                if name == "full.md" or name.endswith("/full.md")
            ],
            key=len,
        )
        if not candidate_paths:
            raise self._error(
                code="missing_full_md",
                message="MinerU returned a result zip archive, but it does not contain full.md.",
                suggestion="Retry later or inspect the archive contents if the issue persists.",
                backend=BACKEND_V4_PRECISION,
                source_type=source_type,
                normalized_source=normalized_source,
                batch_id=batch_id,
                warnings=warnings,
                details={"archive_entries": archive.namelist()[:50]},
                result_archive_url=result_archive_url,
            )
        with archive.open(candidate_paths[0]) as handle:
            return handle.read().decode("utf-8", errors="replace")

    def _success_payload(
        self,
        *,
        backend: str,
        task_id: str,
        batch_id: str,
        state: str,
        markdown: str,
        markdown_url: str,
        result_archive_url: str,
        source_type: str,
        normalized_source: str,
        warnings: list[str],
    ) -> dict[str, Any]:
        provider = self._provider_name(backend)
        model_version = self.settings.model_version if backend == BACKEND_V4_PRECISION else ""
        return {
            "provider": provider,
            "backend": backend,
            "model_version": model_version,
            "task_id": task_id,
            "batch_id": batch_id,
            "state": state,
            "markdown": markdown,
            "markdown_url": markdown_url,
            "result_archive_url": result_archive_url,
            "source_type": source_type,
            "normalized_source": normalized_source,
            "warnings": warnings,
        }

    def _backend_warnings(self, backend: str) -> list[str]:
        config_path = self.settings.config_path
        if backend == BACKEND_V4_PRECISION:
            source_label = "process environment" if self.settings.api_key_source == "env" else config_path
            return [
                f"Using MinerU v4 precision backend with model_version={self.settings.model_version}.",
                f"MINERU_API_KEY was loaded from {source_label}.",
            ]
        if self.settings.backend == BACKEND_AUTO:
            return [
                f"No MINERU_API_KEY configured in {config_path}. Falling back to MinerU v1 lightweight API.",
            ]
        return [
            "MinerU backend forced to v1-agent by MINERU_BACKEND.",
        ]

    def _provider_name(self, backend: str) -> str:
        return PROVIDER_V4_NAME if backend == BACKEND_V4_PRECISION else PROVIDER_V1_NAME

    def _error(
        self,
        *,
        code: str,
        message: str,
        backend: str,
        suggestion: str | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
        source_type: str | None = None,
        normalized_source: str | None = None,
        task_id: str | None = None,
        batch_id: str | None = None,
        state: str = "failed",
        warnings: list[str] | None = None,
        result_archive_url: str = "",
    ) -> MinerUClientError:
        provider = self._provider_name(backend) if backend in {BACKEND_V1_AGENT, BACKEND_V4_PRECISION} else ""
        model_version = self.settings.model_version if backend == BACKEND_V4_PRECISION else ""
        return MinerUClientError(
            code=code,
            message=message,
            provider=provider,
            backend=backend,
            model_version=model_version,
            suggestion=suggestion,
            retryable=retryable,
            details=details,
            source_type=source_type,
            normalized_source=normalized_source,
            task_id=task_id,
            batch_id=batch_id,
            state=state,
            warnings=warnings,
            result_archive_url=result_archive_url,
        )

    def _v4_headers(self, *, include_content_type: bool = True) -> dict[str, str]:
        if not self.settings.api_key:
            raise self._error(
                code="missing_api_key",
                message="MINERU_API_KEY is required for MinerU v4 requests.",
                suggestion=f"Set MINERU_API_KEY in {self.settings.config_path} and retry.",
                backend=BACKEND_V4_PRECISION,
            )
        headers = {
            "Accept": "*/*",
            "Authorization": f"Bearer {self.settings.api_key}",
        }
        if include_content_type:
            headers["Content-Type"] = "application/json"
        return headers

    def _v4_error_suggestion(self, code: Any) -> str:
        normalized = str(code or "")
        if normalized in {"A0202", "A0211", "401", "403"}:
            return f"Check MINERU_API_KEY in {self.settings.config_path} and ensure the Bearer token is valid."
        if normalized in {"-60005", "-60006"}:
            return "Split the file or reduce page_ranges before retrying."
        if normalized in {"-60008", "-60022"}:
            return "Check that the remote URL is accessible to MinerU and try again later."
        if normalized in {"-60009", "-60010", "-10001", "-60007"}:
            return "Retry later."
        if normalized == "-60011":
            return "Retry the request so MinerU can see a valid uploaded file."
        return "Adjust the request or retry later."


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a MinerU parse request with automatic v1/v4 routing.")
    parser.add_argument("--source-type", required=True, choices=["local_path", "remote_url"])
    parser.add_argument("--source", required=True)
    parser.add_argument("--file-name")
    parser.add_argument("--language", default="ch")
    parser.add_argument("--page-range")
    parser.add_argument("--enable-table", dest="enable_table", action="store_true", default=True)
    parser.add_argument("--disable-table", dest="enable_table", action="store_false")
    parser.add_argument("--is-ocr", action="store_true", default=False)
    parser.add_argument("--enable-formula", dest="enable_formula", action="store_true", default=True)
    parser.add_argument("--disable-formula", dest="enable_formula", action="store_false")
    parser.add_argument("--timeout-sec", type=int, default=DEFAULT_TIMEOUT_SEC)
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    client = MinerUAgentClient()
    try:
        result = client.parse_document(
            source_type=args.source_type,
            source=args.source,
            file_name=args.file_name,
            language=args.language,
            page_range=args.page_range,
            enable_table=args.enable_table,
            is_ocr=args.is_ocr,
            enable_formula=args.enable_formula,
            timeout_sec=args.timeout_sec,
        )
    except MinerUClientError as exc:
        print(json.dumps(exc.to_payload(), ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

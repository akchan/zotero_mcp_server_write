"""MCP server exposing Zotero local write operations.

Tools:
    - add_by_doi
    - add_pdf
    - attach_pdf_to_item
    - add_note
    - update_note
    - add_tags
"""

from __future__ import annotations

import base64
import functools
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .client import ZoteroWriteClient, ZoteroWriteError
from .notes import markdown_to_html

_client: ZoteroWriteClient | None = None

# Longest error text forwarded to the client. Plugin errors can embed remote
# HTTP response bodies, so they are flattened and truncated before reaching
# the model.
_MAX_ERROR_CHARS = 1000
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")

# PDF readers accept the "%PDF-" header anywhere in the first 1024 bytes.
_PDF_MAGIC = b"%PDF-"
_PDF_HEADER_WINDOW = 1024


class ToolInputError(ValueError):
    """Raised for invalid tool input; reported to the client verbatim."""


def get_client() -> ZoteroWriteClient:
    """Return a process-wide ZoteroWriteClient (lazily initialised)."""
    global _client
    if _client is None:
        _client = ZoteroWriteClient()
    return _client


def set_client(client: ZoteroWriteClient | None) -> None:
    """Replace the process-wide client (used by tests)."""
    global _client
    _client = client


def _read_pdf_b64(file_path: str) -> tuple[str, str]:
    """Read a local PDF and return (basename, base64 content).

    The file must start with a PDF header so the tools cannot be used to copy
    arbitrary local files (keys, configs) into the Zotero library, which may
    sync to the cloud.
    """
    try:
        path = Path(file_path).expanduser()
    except RuntimeError as exc:
        raise ToolInputError(
            f"Cannot expand file_path {file_path!r}: {exc}"
        ) from exc
    if not path.is_absolute():
        raise ToolInputError(
            f"file_path must be absolute, got: {file_path!r}"
        )
    try:
        if not path.is_file():
            raise FileNotFoundError(f"No such file: {file_path}")
        with path.open("rb") as fh:
            header = fh.read(_PDF_HEADER_WINDOW)
            if _PDF_MAGIC not in header:
                raise ToolInputError(
                    f"Not a PDF file (no %PDF- header): {file_path!r}"
                )
            data = header + fh.read()
    except (FileNotFoundError, ToolInputError):
        raise
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        raise ToolInputError(
            f"Cannot read file_path {file_path!r}: {reason}"
        ) from exc
    return path.name, base64.b64encode(data).decode("ascii")


async def add_by_doi(
    identifier: str, collection_key: str | None = None
) -> dict[str, Any]:
    """Import a new Zotero item from an identifier (DOI, ISBN, arXiv ID, or PMID).

    The identifier type is auto-detected by Zotero's translation server.

    Args:
        identifier: e.g. "10.1038/nature12373", "arXiv:2310.06825",
            "978-0-262-03561-3", or a PMID.
        collection_key: Optional 8-character Zotero collection key
            (e.g. "ABCD1234") to file the new item into. Collection keys can be
            discovered via the read-only `54yyyu/zotero-mcp` server.

    Returns:
        The parsed JSON response from the plugin, typically including the new
        `item_key` of the created item.
    """
    return await get_client().import_by_identifier(identifier, collection_key)


async def add_pdf(
    file_path: str, collection_key: str | None = None
) -> dict[str, Any]:
    """Import a local PDF file into Zotero and run the metadata recognizer.

    The file is base64-encoded and sent to the Zotero plugin, which creates a
    standalone attachment and then attempts to recognize bibliographic metadata.
    The response `status` is "recognized" when Zotero matched the PDF to an
    online source (and a parent item was created), otherwise "standalone".

    Args:
        file_path: Absolute path to a readable PDF file on the same machine as
            the Zotero process. Files without a PDF header are rejected.
        collection_key: Optional 8-character Zotero collection key (e.g.
            "ABCD1234") to file the resulting item(s) into. Collection keys
            can be discovered via the read-only `54yyyu/zotero-mcp` server.

    Returns:
        Plugin response dict including `parent_item_key` and `attachment_key`
        when recognition succeeded.
    """
    file_name, b64 = _read_pdf_b64(file_path)
    return await get_client().import_pdf(file_name, b64, collection_key)


async def attach_pdf_to_item(
    item_key: str, file_path: str, title: str | None = None
) -> dict[str, Any]:
    """Attach a local PDF file to an existing Zotero item.

    Args:
        item_key: 8-character Zotero item key (e.g. "ABCD1234") of the parent
            item. Item keys can be discovered via the read-only
            `54yyyu/zotero-mcp` server.
        file_path: Absolute path to a readable PDF file on the same machine as
            the Zotero process. Files without a PDF header are rejected.
        title: Optional display title for the attachment. Defaults to the
            file's basename.

    Returns:
        Plugin response dict including the new `attachment_key`.
    """
    file_name, b64 = _read_pdf_b64(file_path)
    display_title = title if title is not None else file_name
    return await get_client().attach_file(item_key, file_name, b64, display_title)


async def add_note(
    item_key: str,
    content: str,
    format: Literal["markdown", "html"] = "markdown",
) -> dict[str, Any]:
    """Attach a child note to an existing Zotero item.

    Args:
        item_key: 8-character Zotero item key (e.g. "ABCD1234") of the parent
            item. Item keys can be discovered via the read-only
            `54yyyu/zotero-mcp` server.
        content: Note body. When `format="markdown"` (default), the content is
            rendered to HTML before being stored. When `format="html"`, the
            content is sent through unchanged.
        format: Either "markdown" or "html".

    Returns:
        Plugin response dict including the new note's `item_key`.
    """
    if format == "markdown":
        note_html = markdown_to_html(content)
    elif format == "html":
        note_html = content
    else:
        raise ToolInputError(
            f"format must be 'markdown' or 'html', got {format!r}"
        )
    return await get_client().attach_note(item_key, note_html)


async def update_note(
    note_key: str,
    content: str,
    format: Literal["markdown", "html"] = "markdown",
) -> dict[str, Any]:
    """Replace the body of an existing Zotero note.

    Args:
        note_key: 8-character Zotero item key (e.g. "ABCD1234") of the note
            item to update. Note keys can be discovered via the read-only
            `54yyyu/zotero-mcp` server.
        content: New note body. When `format="markdown"` (default), the
            content is rendered to HTML before being stored. When
            `format="html"`, the content is sent through unchanged.
        format: Either "markdown" or "html".

    Returns:
        Plugin response dict including the note's `note_key`.
    """
    if format == "markdown":
        note_html = markdown_to_html(content)
    elif format == "html":
        note_html = content
    else:
        raise ToolInputError(
            f"format must be 'markdown' or 'html', got {format!r}"
        )
    return await get_client().update_note(note_key, note_html)


async def add_tags(item_key: str, tags: list[str]) -> dict[str, Any]:
    """Add one or more tags to an existing Zotero item.

    Tags that the item already carries are silently skipped (the plugin
    reports them under `skipped` rather than treating it as an error).

    Args:
        item_key: 8-character Zotero item key (e.g. "ABCD1234") of the item
            to tag. Item keys can be discovered via the read-only
            `54yyyu/zotero-mcp` server.
        tags: Non-empty list of tag names to add.

    Returns:
        Plugin response dict including `added`, `skipped`, `added_count`,
        and `skipped_count`.
    """
    if not tags:
        raise ToolInputError("tags must contain at least one entry")
    return await get_client().add_tags(item_key, tags)


def _clean_message(message: object) -> str:
    """Flatten control characters and cap length of text sent to the client."""
    text = _CONTROL_CHARS.sub(" ", str(message)).strip()
    if len(text) > _MAX_ERROR_CHARS:
        omitted = len(text) - _MAX_ERROR_CHARS
        text = f"{text[:_MAX_ERROR_CHARS]}... [truncated {omitted} chars]"
    return text


def _report_errors(
    fn: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    """Re-raise anticipated failures as ToolError so the message reaches the client.

    MCPServer treats any other exception as a crash and replaces its text with
    a bare "Error executing tool <name>", which hides the plugin's reason.
    """

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except ZoteroWriteError as exc:
            raise ToolError(
                f"Zotero write plugin error: {_clean_message(exc)}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ToolError(
                "Timed out waiting for Zotero "
                f"({type(exc).__name__}). Zotero may still finish the "
                "operation, so search the library before retrying to avoid "
                "duplicates. Raise ZOTERO_WRITE_TIMEOUT for slow lookups."
            ) from exc
        except httpx.ConnectError as exc:
            base_url = get_client().base_url
            raise ToolError(
                "Cannot connect to Zotero's local HTTP server: "
                f"{_clean_message(exc)}. Check that Zotero is running and "
                f"{base_url}/connector/ping responds."
            ) from exc
        except httpx.HTTPError as exc:
            raise ToolError(
                f"HTTP error talking to Zotero ({type(exc).__name__}): "
                f"{_clean_message(exc)}"
            ) from exc
        except (ToolInputError, FileNotFoundError) as exc:
            raise ToolError(_clean_message(exc)) from exc

    return wrapper


def build_server() -> MCPServer:
    """Create an MCPServer instance with all tools registered."""
    server = MCPServer("zotero-mcp-server-write")
    for fn in (
        add_by_doi,
        add_pdf,
        attach_pdf_to_item,
        add_note,
        update_note,
        add_tags,
    ):
        server.tool()(_report_errors(fn))
    return server


def main() -> None:
    """Entry point: run the MCP server over stdio."""
    server = build_server()
    server.run()


if __name__ == "__main__":  # pragma: no cover
    main()

"""MCP server exposing Zotero local write operations.

Tools:
    - add_by_doi
    - add_pdf
    - attach_pdf_to_item
    - add_note
    - update_note
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .client import ZoteroWriteClient
from .notes import markdown_to_html

_client: ZoteroWriteClient | None = None


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


def _read_file_b64(file_path: str) -> tuple[str, str]:
    path = Path(file_path).expanduser()
    if not path.is_absolute():
        raise ValueError(
            f"file_path must be absolute, got: {file_path!r}"
        )
    if not path.is_file():
        raise FileNotFoundError(f"No such file: {file_path}")
    data = path.read_bytes()
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
            the Zotero process.
        collection_key: Optional 8-character Zotero collection key (e.g.
            "ABCD1234") to file the resulting item(s) into. Collection keys
            can be discovered via the read-only `54yyyu/zotero-mcp` server.

    Returns:
        Plugin response dict including `parent_item_key` and `attachment_key`
        when recognition succeeded.
    """
    file_name, b64 = _read_file_b64(file_path)
    return await get_client().import_pdf(file_name, b64, collection_key)


async def attach_pdf_to_item(
    item_key: str, file_path: str, title: str | None = None
) -> dict[str, Any]:
    """Attach a local file (typically a PDF) to an existing Zotero item.

    Args:
        item_key: 8-character Zotero item key (e.g. "ABCD1234") of the parent
            item. Item keys can be discovered via the read-only
            `54yyyu/zotero-mcp` server.
        file_path: Absolute path to a readable file on the same machine as the
            Zotero process.
        title: Optional display title for the attachment. Defaults to the
            file's basename.

    Returns:
        Plugin response dict including the new `attachment_key`.
    """
    file_name, b64 = _read_file_b64(file_path)
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
        raise ValueError(f"format must be 'markdown' or 'html', got {format!r}")
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
        raise ValueError(f"format must be 'markdown' or 'html', got {format!r}")
    return await get_client().update_note(note_key, note_html)


def build_server() -> FastMCP:
    """Create a FastMCP instance with all tools registered."""
    server = FastMCP("zotero-mcp-server-write")
    server.tool()(add_by_doi)
    server.tool()(add_pdf)
    server.tool()(attach_pdf_to_item)
    server.tool()(add_note)
    server.tool()(update_note)
    return server


def main() -> None:
    """Entry point: run the MCP server over stdio."""
    server = build_server()
    server.run()


if __name__ == "__main__":  # pragma: no cover
    main()

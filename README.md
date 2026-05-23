# zotero-mcp-server-write

A Model Context Protocol (MCP) server that exposes the *write* operations of a
local Zotero installation to LLM agents. It is a thin async wrapper around the
companion [`zotero_write_api_plugin`](https://github.com/akchan/zotero_write_api_plugin)
Zotero plugin, which adds HTTP endpoints to Zotero's built-in local server on
`http://127.0.0.1:23119`. Together they let an agent import items by DOI,
ingest PDFs with Zotero's metadata recognizer, attach files to existing items,
and add formatted notes.

## Prerequisite

You must install the **`zotero_write_api_plugin`** XPI in Zotero before this
MCP server can do anything useful. Download the latest release from
[github.com/akchan/zotero_write_api_plugin/releases](https://github.com/akchan/zotero_write_api_plugin/releases)
and install it via *Tools → Add-ons → Install Add-on From File…* in Zotero.
Make sure Zotero is running whenever you use the MCP server.

## Recommended pairing

This server only covers *writes*. For *reads* (searching the library,
browsing collections, fetching item metadata, getting tags, etc.) install
[`54yyyu/zotero-mcp`](https://github.com/54yyyu/zotero-mcp) alongside it. The
two together give an agent a complete view-and-edit surface over your local
Zotero library. The tool descriptions in this server explicitly point at
`54yyyu/zotero-mcp` as the way to discover `item_key` and `collection_key`
values.

## Install / run

The server is published to GitHub and installable directly with `uv`:

```bash
# Run from a clone:
uv run zotero-mcp-server-write

# Or, once published to PyPI:
uvx zotero-mcp-server-write
```

(The PyPI package name is `zotero-mcp-server-write`. The console-script entry
point has the same name.)

## Tools

| Tool                  | Description                                                                                          |
| --------------------- | ---------------------------------------------------------------------------------------------------- |
| `add_by_doi`          | Import a new item from a DOI / ISBN / arXiv ID / PMID (type auto-detected).                          |
| `add_pdf`             | Import a local PDF, then run Zotero's metadata recognizer to find a parent item.                     |
| `attach_pdf_to_item`  | Attach a local file (typically a PDF) to an existing Zotero item by `item_key`.                      |
| `add_note`            | Add a child note to an existing item. Accepts markdown (rendered to HTML) or raw HTML.               |

## Claude Desktop config example

Register both the read server and this write server side-by-side:

```json
{
  "mcpServers": {
    "zotero-mcp": {
      "command": "uvx",
      "args": ["zotero-mcp"]
    },
    "zotero-mcp-server-write": {
      "command": "uvx",
      "args": ["zotero-mcp-server-write"],
      "env": {
        "ZOTERO_LOCAL_API_BASE": "http://127.0.0.1:23119",
        "ZOTERO_WRITE_TIMEOUT": "60"
      }
    }
  }
}
```

## Environment variables

| Variable                 | Default                    | Purpose                                                            |
| ------------------------ | -------------------------- | ------------------------------------------------------------------ |
| `ZOTERO_LOCAL_API_BASE`  | `http://127.0.0.1:23119`   | Base URL of Zotero's local HTTP server (where the plugin is hooked in). |
| `ZOTERO_WRITE_TIMEOUT`   | `60` (seconds)             | Per-request HTTP timeout for the plugin endpoints.                 |

## Out of scope

- **Group libraries.** Only the user's local library is targeted; group library
  writes are not supported by the underlying plugin.
- **Tag and collection management.** This server does not create, rename,
  delete, or reassign tags or collections. Use
  [`54yyyu/zotero-mcp`](https://github.com/54yyyu/zotero-mcp) for read access
  to those structures and edit them in the Zotero UI when needed.

## License

MIT, see [LICENSE](LICENSE).

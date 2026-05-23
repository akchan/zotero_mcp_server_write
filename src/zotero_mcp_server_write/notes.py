"""Convert markdown to HTML for Zotero notes."""

from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark").enable("table")


def markdown_to_html(md: str) -> str:
    """Render a markdown string to HTML suitable for a Zotero note."""
    return _md.render(md)

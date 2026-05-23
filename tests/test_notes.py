from zotero_mcp_server_write.notes import markdown_to_html


def test_markdown_bold():
    html = markdown_to_html("**hi**")
    assert "<strong>hi</strong>" in html


def test_markdown_table():
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    html = markdown_to_html(md)
    assert "<table>" in html
    assert "<td>1</td>" in html

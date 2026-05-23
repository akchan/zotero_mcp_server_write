import base64
import json
from pathlib import Path

import httpx
import pytest
import respx

from zotero_mcp_server_write import server as srv
from zotero_mcp_server_write.client import ZoteroWriteClient


BASE = "http://127.0.0.1:23119"


@pytest.fixture
def client():
    c = ZoteroWriteClient(base_url=BASE, timeout=5)
    # Bypass the plugin-version probe for tests that don't exercise it.
    c._version_checked = True
    srv.set_client(c)
    yield c
    srv.set_client(None)


async def test_add_by_doi_calls_client(client, monkeypatch):
    calls = {}

    async def fake_import(identifier, collection_key=None):
        calls["args"] = (identifier, collection_key)
        return {"success": True, "item_key": "AAAA1111"}

    monkeypatch.setattr(client, "import_by_identifier", fake_import)
    result = await srv.add_by_doi("10.1/x", collection_key="COL12345")
    assert result == {"success": True, "item_key": "AAAA1111"}
    assert calls["args"] == ("10.1/x", "COL12345")


async def test_add_note_markdown_converts(client, monkeypatch):
    captured = {}

    async def fake_attach(item_key, note_html):
        captured["item_key"] = item_key
        captured["note_html"] = note_html
        return {"success": True, "item_key": "NOTE0001"}

    monkeypatch.setattr(client, "attach_note", fake_attach)
    await srv.add_note("PARENT01", "**bold**", format="markdown")
    assert "<strong>bold</strong>" in captured["note_html"]


async def test_add_note_html_passthrough(client, monkeypatch):
    captured = {}

    async def fake_attach(item_key, note_html):
        captured["note_html"] = note_html
        return {"success": True}

    monkeypatch.setattr(client, "attach_note", fake_attach)
    await srv.add_note("PARENT01", "<p>raw</p>", format="html")
    assert captured["note_html"] == "<p>raw</p>"


async def test_add_note_invalid_format(client):
    with pytest.raises(ValueError):
        await srv.add_note("PARENT01", "x", format="rst")  # type: ignore[arg-type]


async def test_update_note_markdown_converts(client, monkeypatch):
    captured = {}

    async def fake_update(note_key, note_html):
        captured["note_key"] = note_key
        captured["note_html"] = note_html
        return {"success": True, "note_key": "NOTE0001"}

    monkeypatch.setattr(client, "update_note", fake_update)
    await srv.update_note("NOTE0001", "**bold**", format="markdown")
    assert captured["note_key"] == "NOTE0001"
    assert "<strong>bold</strong>" in captured["note_html"]


async def test_update_note_html_passthrough(client, monkeypatch):
    captured = {}

    async def fake_update(note_key, note_html):
        captured["note_html"] = note_html
        return {"success": True}

    monkeypatch.setattr(client, "update_note", fake_update)
    await srv.update_note("NOTE0001", "<p>raw</p>", format="html")
    assert captured["note_html"] == "<p>raw</p>"


async def test_update_note_invalid_format(client):
    with pytest.raises(ValueError):
        await srv.update_note("NOTE0001", "x", format="rst")  # type: ignore[arg-type]


async def test_add_tags_calls_client(client, monkeypatch):
    captured = {}

    async def fake_add_tags(item_key, tags):
        captured["args"] = (item_key, tags)
        return {"success": True, "added": tags, "skipped": []}

    monkeypatch.setattr(client, "add_tags", fake_add_tags)
    result = await srv.add_tags("PARENT01", ["foo", "bar"])
    assert result["added"] == ["foo", "bar"]
    assert captured["args"] == ("PARENT01", ["foo", "bar"])


async def test_add_tags_rejects_empty(client):
    with pytest.raises(ValueError):
        await srv.add_tags("PARENT01", [])


async def test_add_pdf_requires_absolute_path(client):
    with pytest.raises(ValueError):
        await srv.add_pdf("relative.pdf")


async def test_add_pdf_missing_file(client, tmp_path):
    with pytest.raises(FileNotFoundError):
        await srv.add_pdf(str(tmp_path / "nope.pdf"))


@respx.mock
async def test_add_pdf_base64_roundtrip(client, tmp_path):
    sample = b"%PDF-1.4 sample bytes \x00\x01\x02"
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(sample)

    route = respx.post(f"{BASE}/write").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "status": "standalone",
                "attachment_key": "ATT00001",
            },
        )
    )
    result = await srv.add_pdf(str(pdf), collection_key="COL12345")
    assert result["attachment_key"] == "ATT00001"

    body = json.loads(route.calls.last.request.content)
    assert body["operation"] == "import_pdf"
    assert body["file_name"] == "doc.pdf"
    assert body["collection_key"] == "COL12345"
    assert base64.b64decode(body["file_bytes_base64"]) == sample


@respx.mock
async def test_attach_pdf_to_item_default_title(client, tmp_path):
    sample = b"hello-bytes"
    pdf = tmp_path / "attach.pdf"
    pdf.write_bytes(sample)

    route = respx.post(f"{BASE}/attach").mock(
        return_value=httpx.Response(
            200, json={"success": True, "attachment_key": "ATT00002"}
        )
    )
    await srv.attach_pdf_to_item("PARENT01", str(pdf))
    body = json.loads(route.calls.last.request.content)
    assert body["item_key"] == "PARENT01"
    assert body["file_name"] == "attach.pdf"
    assert body["title"] == "attach.pdf"
    assert base64.b64decode(body["file_bytes_base64"]) == sample


@respx.mock
async def test_attach_pdf_to_item_custom_title(client, tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"abc")
    route = respx.post(f"{BASE}/attach").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    await srv.attach_pdf_to_item("PARENT01", str(pdf), title="My Title")
    body = json.loads(route.calls.last.request.content)
    assert body["title"] == "My Title"

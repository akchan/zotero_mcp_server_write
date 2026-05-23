import json

import httpx
import pytest
import respx

from zotero_mcp_server_write.client import (
    MIN_PLUGIN_VERSION,
    ZoteroWriteClient,
    ZoteroWriteError,
    _parse_plugin_version,
)


BASE = "http://127.0.0.1:23119"


@pytest.fixture
async def client():
    c = ZoteroWriteClient(base_url=BASE, timeout=5)
    # Bypass the plugin-version probe for tests that don't exercise it.
    c._version_checked = True
    yield c
    await c.aclose()


@respx.mock
async def test_version_ok(client):
    respx.get(f"{BASE}/version").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "version": "0.1.0",
                "operations": ["import_by_identifier"],
            },
        )
    )
    data = await client.version()
    assert data["version"] == "0.1.0"
    assert "import_by_identifier" in data["operations"]


@respx.mock
async def test_import_by_identifier_payload(client):
    route = respx.post(f"{BASE}/write").mock(
        return_value=httpx.Response(
            200, json={"success": True, "item_key": "AAAA1111"}
        )
    )
    data = await client.import_by_identifier("10.1/x", collection_key="COL12345")
    assert data["item_key"] == "AAAA1111"
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "operation": "import_by_identifier",
        "identifier": "10.1/x",
        "collection_key": "COL12345",
    }


@respx.mock
async def test_import_by_identifier_omits_collection(client):
    route = respx.post(f"{BASE}/write").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    await client.import_by_identifier("10.1/x")
    body = json.loads(route.calls.last.request.content)
    assert "collection_key" not in body
    assert body["operation"] == "import_by_identifier"


@respx.mock
async def test_attach_note_payload(client):
    route = respx.post(f"{BASE}/write").mock(
        return_value=httpx.Response(
            200, json={"success": True, "item_key": "NOTE0001"}
        )
    )
    await client.attach_note("PARENT01", "<p>hi</p>")
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "operation": "attach_note",
        "item_key": "PARENT01",
        "note": "<p>hi</p>",
    }


@respx.mock
async def test_update_note_payload(client):
    route = respx.post(f"{BASE}/write").mock(
        return_value=httpx.Response(
            200, json={"success": True, "note_key": "NOTE0001"}
        )
    )
    await client.update_note("NOTE0001", "<p>updated</p>")
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "operation": "update_note",
        "note_key": "NOTE0001",
        "note": "<p>updated</p>",
    }


@respx.mock
async def test_import_pdf_payload(client):
    route = respx.post(f"{BASE}/write").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "status": "recognized",
                "parent_item_key": "P1",
                "attachment_key": "A1",
            },
        )
    )
    data = await client.import_pdf("a.pdf", "Zm9v", collection_key="C1")
    assert data["status"] == "recognized"
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "operation": "import_pdf",
        "file_name": "a.pdf",
        "file_bytes_base64": "Zm9v",
        "collection_key": "C1",
    }


@respx.mock
async def test_attach_file_payload(client):
    route = respx.post(f"{BASE}/attach").mock(
        return_value=httpx.Response(
            200, json={"success": True, "attachment_key": "ATT00001"}
        )
    )
    data = await client.attach_file("PARENT01", "a.pdf", "Zm9v", "Title")
    assert data["attachment_key"] == "ATT00001"
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "item_key": "PARENT01",
        "title": "Title",
        "file_name": "a.pdf",
        "file_bytes_base64": "Zm9v",
    }


@respx.mock
async def test_add_tags_payload(client):
    route = respx.post(f"{BASE}/write").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "added": ["foo"],
                "skipped": ["bar"],
                "added_count": 1,
                "skipped_count": 1,
            },
        )
    )
    data = await client.add_tags("PARENT01", ["foo", "bar"])
    assert data["added_count"] == 1
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "operation": "add_tags",
        "item_key": "PARENT01",
        "tags": ["foo", "bar"],
    }


@respx.mock
async def test_non_2xx_raises(client):
    respx.post(f"{BASE}/write").mock(
        return_value=httpx.Response(500, json={"success": False, "error": "boom"})
    )
    with pytest.raises(ZoteroWriteError) as exc:
        await client.import_by_identifier("10.1/x")
    assert exc.value.status_code == 500
    assert "boom" in str(exc.value)


def test_parse_plugin_version():
    assert _parse_plugin_version("0.2.0") == (0, 2, 0)
    assert _parse_plugin_version("1.10.3") == (1, 10, 3)
    assert _parse_plugin_version("0.2.0-dev") == (0, 2, 0)


def test_min_plugin_version_is_0_3_0():
    assert MIN_PLUGIN_VERSION == (0, 3, 0)


@respx.mock
async def test_post_probes_version_once():
    c = ZoteroWriteClient(base_url=BASE, timeout=5)
    try:
        version_route = respx.get(f"{BASE}/version").mock(
            return_value=httpx.Response(
                200, json={"success": True, "version": "0.3.0"}
            )
        )
        respx.post(f"{BASE}/write").mock(
            return_value=httpx.Response(200, json={"success": True})
        )
        await c.import_by_identifier("10.1/x")
        await c.import_by_identifier("10.1/y")
        assert version_route.call_count == 1
    finally:
        await c.aclose()


@respx.mock
async def test_post_rejects_outdated_plugin():
    c = ZoteroWriteClient(base_url=BASE, timeout=5)
    try:
        respx.get(f"{BASE}/version").mock(
            return_value=httpx.Response(
                200, json={"success": True, "version": "0.1.2"}
            )
        )
        with pytest.raises(ZoteroWriteError) as exc:
            await c.import_by_identifier("10.1/x")
        assert "0.1.2" in str(exc.value)
        assert "0.3.0" in str(exc.value)
    finally:
        await c.aclose()


@respx.mock
async def test_post_rejects_missing_version_field():
    c = ZoteroWriteClient(base_url=BASE, timeout=5)
    try:
        respx.get(f"{BASE}/version").mock(
            return_value=httpx.Response(200, json={"success": True})
        )
        with pytest.raises(ZoteroWriteError):
            await c.import_by_identifier("10.1/x")
    finally:
        await c.aclose()


@respx.mock
async def test_success_false_raises(client):
    respx.post(f"{BASE}/write").mock(
        return_value=httpx.Response(
            200, json={"success": False, "error": "bad identifier"}
        )
    )
    with pytest.raises(ZoteroWriteError) as exc:
        await client.import_by_identifier("nope")
    assert "bad identifier" in str(exc.value)
    assert exc.value.response_json == {
        "success": False,
        "error": "bad identifier",
    }

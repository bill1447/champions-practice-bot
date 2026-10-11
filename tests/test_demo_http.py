from email.message import Message
from http import HTTPStatus
from io import BytesIO
from types import SimpleNamespace

import pytest

from champions_practice.demo_server import (
    DemoRequestHandler,
    MAX_DEMO_REQUEST_BYTES,
)


def handler(path="/api/start", body=b"{}", overrides=None):
    request = object.__new__(DemoRequestHandler)
    request.path = path
    request.headers = Message()
    values = {
        "Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765",
        "Content-Type": "application/json", "Content-Length": str(len(body)),
        "X-Demo-CSRF-Token": "test-session-token",
    }
    values.update(overrides or {})
    for key, value in values.items():
        if value is not None:
            request.headers[key] = value
    calls = []

    def mutate():
        calls.append(path)
        return {"ok": True}

    request.server = SimpleNamespace(
        server_address=("127.0.0.1", 8765), mutation_token="test-session-token",
        app=SimpleNamespace(start=mutate, end_battle=mutate, abort_transport=mutate,
                            snapshot=lambda: {"started": False}),
    )
    request.rfile = BytesIO(body)
    request.responses = []
    request._send_json = lambda payload, status=HTTPStatus.OK: request.responses.append(
        (status, payload)
    )
    return request, calls


@pytest.mark.parametrize("path", ["/api/start", "/api/end", "/api/abort-transport"])
@pytest.mark.parametrize("headers", [
    {"Origin": "http://foreign.example"}, {"Origin": "null"},
    {"Host": "foreign.example:8765"}, {"Sec-Fetch-Site": "cross-site"},
    {"X-Demo-CSRF-Token": None}, {"X-Demo-CSRF-Token": "wrong"},
    {"X-Demo-CSRF-Token": "non-ascii-é"},
])
def test_unauthorized_mutation_never_reaches_application(path, headers):
    request, calls = handler(path=path, overrides=headers)
    request.do_POST()
    assert request.responses[0][0] == HTTPStatus.FORBIDDEN
    assert not calls
    assert request.rfile.tell() == 0


@pytest.mark.parametrize("content_type", [None, "text/plain", "application/x-www-form-urlencoded"])
def test_simple_cross_origin_content_types_are_rejected(content_type):
    request, calls = handler(overrides={"Content-Type": content_type})
    request.do_POST()
    assert request.responses[0][0] == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    assert not calls


@pytest.mark.parametrize("body", [b"{broken", b"\xff", b"[]", b"null"])
def test_malformed_json_is_bad_request_instead_of_state_conflict(body):
    request, calls = handler(body=body)
    request.do_POST()
    assert request.responses[0][0] == HTTPStatus.BAD_REQUEST
    assert not calls


@pytest.mark.parametrize("length,status", [
    ("broken", HTTPStatus.BAD_REQUEST), ("-1", HTTPStatus.BAD_REQUEST),
    ("12", HTTPStatus.BAD_REQUEST),
    (str(MAX_DEMO_REQUEST_BYTES + 1), HTTPStatus.REQUEST_ENTITY_TOO_LARGE),
])
def test_invalid_or_unbounded_lengths_are_rejected(length, status):
    request, calls = handler(overrides={"Content-Length": length})
    request.do_POST()
    assert request.responses[0][0] == status
    assert not calls


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
@pytest.mark.parametrize("origin_present", [True, False])
def test_valid_local_request_and_token_reach_application(host, origin_present):
    request, calls = handler(overrides={
        "Host": f"{host}:8765",
        "Origin": f"http://{host}:8765" if origin_present else None,
        "Content-Type": "application/json; charset=utf-8",
    })
    request.do_POST()
    assert request.responses == [(HTTPStatus.OK, {"ok": True})]
    assert calls == ["/api/start"]


def test_battle_state_errors_still_return_conflict():
    request, _ = handler()

    def conflict():
        raise RuntimeError("battle already started")

    request.server.app.start = conflict
    request.do_POST()
    assert request.responses[0][0] == HTTPStatus.CONFLICT


def test_html_injects_session_token_into_browser_requests():
    request, _ = handler(path="/")
    request.wfile = BytesIO()
    request.send_response = lambda status: None
    request.send_header = lambda *args: None
    request.end_headers = lambda: None
    request._send_html()
    html = request.wfile.getvalue().decode()
    assert "__DEMO_CSRF_TOKEN__" not in html
    assert 'options.headers["X-Demo-CSRF-Token"] = "test-session-token"' in html


def test_rebinding_host_cannot_read_browser_token_or_state():
    request, _ = handler(path="/api/state", overrides={"Host": "foreign.example:8765"})
    request.do_GET()
    assert request.responses[0][0] == HTTPStatus.FORBIDDEN


def test_live_http_page_token_authorizes_json_mutations_and_rejects_foreign_origin():
    from http.client import HTTPConnection
    import json
    import re
    from threading import Thread
    from champions_practice.demo_server import DemoHTTPServer

    calls = []

    def start():
        calls.append("start")
        return {"started": True}

    server = DemoHTTPServer(("127.0.0.1", 0), SimpleNamespace(start=start))
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        assert response.status == HTTPStatus.OK
        html = response.read().decode()
        token = re.search(r'X-Demo-CSRF-Token"\] = "([^"]+)"', html).group(1)
        assert token == server.mutation_token
        headers = {"Content-Type": "application/json", "X-Demo-CSRF-Token": token}
        connection.request("POST", "/api/start", body="{}", headers=headers)
        response = connection.getresponse()
        assert response.status == HTTPStatus.OK
        assert json.loads(response.read()) == {"started": True}
        connection.request("POST", "/api/start", body="{}", headers={
            **headers, "Origin": "https://foreign.example",
        })
        response = connection.getresponse()
        assert response.status == HTTPStatus.FORBIDDEN
        response.read()
        connection.request("POST", "/api/start", body="{broken", headers=headers)
        response = connection.getresponse()
        assert response.status == HTTPStatus.BAD_REQUEST
        response.read()
        assert calls == ["start"]
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert not thread.is_alive()

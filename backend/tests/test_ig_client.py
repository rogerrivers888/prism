"""IG client: read-only by construction, and credentials that cannot escape."""

import httpx
import pytest

from app.ig.client import IGClient, IGError

KEY = "abc123APIKEY"
USER = "roger@example.com"
PASSWORD = "sup3r-s3cret-pw"


def make_client(handler, **kwargs) -> IGClient:
    transport = httpx.MockTransport(handler)
    return IGClient(
        api_key=KEY, username=USER, password=PASSWORD,
        client=httpx.AsyncClient(transport=transport, timeout=5),
        max_retries=2, **kwargs,
    )


def login_response(request):
    return httpx.Response(
        200, json={"accounts": [{"accountId": "ABC1", "accountType": "SPREADBET"}]},
        headers={"CST": "cst-token-value", "X-SECURITY-TOKEN": "xst-token-value"},
    )


def test_the_client_exposes_no_way_to_trade():
    """Read-only is a property of the surface, not a promise in a comment."""
    surface = {name for name in dir(IGClient) if not name.startswith("_")}
    for forbidden in ("create_position", "close_position", "amend", "deal", "order",
                      "post", "delete", "put"):
        assert not any(forbidden in name for name in surface), (
            f"IGClient exposes '{forbidden}' — this integration must stay read-only"
        )


@pytest.mark.asyncio
async def test_password_never_appears_in_a_login_error():
    def handler(request):
        # IG genuinely echoes request context in some failures.
        return httpx.Response(400, text=f"bad request body: {request.content.decode()}")

    client = make_client(handler)
    with pytest.raises(IGError) as caught:
        await client.login()
    message = str(caught.value)
    assert PASSWORD not in message
    assert USER not in message
    assert KEY not in message


@pytest.mark.asyncio
async def test_api_key_never_appears_in_a_request_error():
    def handler(request):
        if request.url.path.endswith("/session"):
            return login_response(request)
        return httpx.Response(400, text=f"denied for key {KEY}")

    client = make_client(handler)
    with pytest.raises(IGError) as caught:
        await client.positions("ABC1")
    assert KEY not in str(caught.value)
    assert "***" in str(caught.value)


@pytest.mark.asyncio
async def test_session_tokens_are_redacted_too():
    """A leaked CST is a live credential until it expires."""
    calls = {"n": 0}

    def handler(request):
        if request.url.path.endswith("/session"):
            return login_response(request)
        calls["n"] += 1
        return httpx.Response(400, text="failure involving cst-token-value")

    client = make_client(handler)
    with pytest.raises(IGError) as caught:
        await client.positions("ABC1")
    assert "cst-token-value" not in str(caught.value)


@pytest.mark.asyncio
async def test_expired_session_triggers_exactly_one_relogin():
    state = {"logins": 0, "position_calls": 0}

    def handler(request):
        if request.url.path.endswith("/session"):
            state["logins"] += 1
            return login_response(request)
        state["position_calls"] += 1
        # First call 401s; after the re-login it succeeds.
        if state["position_calls"] == 1:
            return httpx.Response(401, text="token expired")
        return httpx.Response(200, json={"positions": []})

    client = make_client(handler)
    result = await client.positions("ABC1")
    assert result == {"positions": []}
    assert state["logins"] == 2, "should re-login once, not loop"


@pytest.mark.asyncio
async def test_a_401_that_persists_does_not_loop_forever():
    state = {"logins": 0}

    def handler(request):
        if request.url.path.endswith("/session"):
            state["logins"] += 1
            return login_response(request)
        return httpx.Response(401, text="still expired")

    client = make_client(handler)
    with pytest.raises(IGError):
        await client.positions("ABC1")
    # One initial login plus one retry login. Never an unbounded loop against
    # a rate-limited API.
    assert state["logins"] <= 2


@pytest.mark.asyncio
async def test_account_scoping_header_is_sent():
    seen = {}

    def handler(request):
        if request.url.path.endswith("/session"):
            return login_response(request)
        seen["account"] = request.headers.get("IG-ACCOUNT-ID")
        return httpx.Response(200, json={"positions": []})

    client = make_client(handler)
    await client.positions("PENSION1")
    assert seen["account"] == "PENSION1"


@pytest.mark.asyncio
async def test_from_keyword_is_translated_for_ig():
    """`from` is a Python keyword; IG names the parameter exactly that."""
    seen = {}

    def handler(request):
        if request.url.path.endswith("/session"):
            return login_response(request)
        seen["query"] = str(request.url.query)
        return httpx.Response(200, json={"transactions": []})

    client = make_client(handler)
    await client.transactions("ABC1", "2024-01-01", "2025-01-01")
    assert "from=2024-01-01" in seen["query"]
    assert "from_" not in seen["query"]

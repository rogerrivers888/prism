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
    """Read-only is a property of the surface, not a promise in a comment.

    switch_account is deliberately permitted: it is a session operation that
    moves no money and places no order, and IG's /positions endpoint cannot
    be scoped any other way.
    """
    surface = {name for name in dir(IGClient) if not name.startswith("_")}
    for forbidden in ("create", "close", "amend", "deal", "order", "delete",
                      "confirm", "otc", "working"):
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
    result = await client.get("/positions", version="2")
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
        await client.get("/positions", version="2")
    # One initial login plus one retry login. Never an unbounded loop against
    # a rate-limited API.
    assert state["logins"] <= 2


@pytest.mark.asyncio
async def test_transactions_are_scoped_by_switching_too():
    """Same trap as positions: history answers for the active account."""
    switched = []

    def handler(request):
        if request.url.path.endswith("/session") and request.method == "POST":
            return login_response(request)
        if request.method == "PUT":
            import json as json_module

            switched.append(json_module.loads(request.content)["accountId"])
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"transactions": []})

    client = make_client(handler)
    await client.transactions("PENSION1", "2024-01-01", "2025-01-01")
    assert switched == ["PENSION1"]


@pytest.mark.asyncio
async def test_from_keyword_is_translated_for_ig():
    """`from` is a Python keyword; IG names the parameter exactly that."""
    seen = {}

    def handler(request):
        if request.url.path.endswith("/session") and request.method == "POST":
            return login_response(request)
        if request.method == "PUT":
            return httpx.Response(200, json={})
        seen["query"] = str(request.url.query)
        return httpx.Response(200, json={"transactions": []})

    client = make_client(handler)
    await client.transactions("ABC1", "2024-01-01", "2025-01-01")
    assert "from=2024-01-01" in seen["query"]
    assert "from_" not in seen["query"]


@pytest.mark.asyncio
async def test_positions_switch_the_session_to_the_right_account():
    """IG ignores IG-ACCOUNT-ID on /positions and answers for whichever
    account the session is on. Verified against the live API: without the
    switch, both of Roger's accounts return the same positions and every one
    is counted twice."""
    calls = []

    def handler(request):
        if request.url.path.endswith("/session") and request.method == "POST":
            return login_response(request)
        if request.url.path.endswith("/session") and request.method == "PUT":
            import json as json_module

            calls.append(("switch", json_module.loads(request.content)["accountId"]))
            return httpx.Response(
                200, json={},
                headers={"CST": "cst-2", "X-SECURITY-TOKEN": "xst-2"},
            )
        calls.append(("positions", request.headers.get("CST")))
        return httpx.Response(200, json={"positions": []})

    client = make_client(handler)
    await client.positions("SPREAD1")
    await client.positions("CFD1")
    assert ("switch", "SPREAD1") in calls
    assert ("switch", "CFD1") in calls
    # The reissued token must be adopted, or every later call is silently
    # unauthenticated and returns an empty body rather than an error.
    assert ("positions", "cst-2") in calls


@pytest.mark.asyncio
async def test_switching_twice_to_the_same_account_is_skipped():
    switches = []

    def handler(request):
        if request.url.path.endswith("/session") and request.method == "POST":
            return login_response(request)
        if request.method == "PUT":
            switches.append(1)
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"positions": []})

    client = make_client(handler)
    await client.positions("A1")
    await client.positions("A1")
    assert len(switches) == 1, "should not re-switch to the account already active"

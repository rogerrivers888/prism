"""IG REST client. READ-ONLY.

Prism observes IG; it never trades there. This module exposes only GET
endpoints — there is no create/amend/close position method to accidentally
call, and adding one should be treated as a change of product rather than a
feature.

Credentials are handled the same way as EODHD's key: any exception escaping a
request is scrubbed before it can reach a log. IG's failure modes make this
more important than usual, because the password is in the login body and IG
echoes request context in some error responses.

Session model (REST v3): POST /session with the API key and credentials
returns CST and X-SECURITY-TOKEN headers. Those expire — typically six hours,
sooner if idle — so a 401 triggers exactly one silent re-login and retry.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

LIVE_BASE = "https://api.ig.com/gateway/deal"
DEMO_BASE = "https://demo-api.ig.com/gateway/deal"

# IG's published allowances are per-application and unforgiving; a burst of
# retries is how an application key gets throttled for the day.
RETRY_STATUSES = {429, 500, 502, 503, 504}


class IGError(RuntimeError):
    """An IG failure with every credential already scrubbed out."""


class IGRateLimited(IGError):
    pass


@dataclass
class IGSession:
    cst: str
    security_token: str
    opened_at: datetime
    accounts: list[dict] = field(default_factory=list)
    # IG's own default is six hours; refreshing early costs one call and
    # avoids a mid-sync failure.
    ttl: timedelta = timedelta(hours=5)

    @property
    def expired(self) -> bool:
        return datetime.now(timezone.utc) - self.opened_at > self.ttl


class IGClient:
    """Read-only IG gateway."""

    name = "ig"

    def __init__(
        self,
        api_key: str,
        username: str,
        password: str,
        demo: bool = False,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 4,
    ) -> None:
        self._api_key = api_key
        self._username = username
        self._password = password
        self._base = DEMO_BASE if demo else LIVE_BASE
        self._client = client
        self._max_retries = max_retries
        self._session: IGSession | None = None
        self._active_account: str | None = None
        # One login at a time: a concurrent sync must not race two sessions,
        # because IG invalidates the older one and both callers then fail.
        self._login_lock = asyncio.Lock()

    # ------------------------------------------------------------ redaction

    def _redact(self, text: str) -> str:
        """Remove every secret from a string bound for a log or an exception.

        Ordered longest-first so a credential that contains another (a
        username inside an email, say) cannot leave a fragment behind.
        """
        secrets = sorted(
            (s for s in (self._api_key, self._password, self._username) if s),
            key=len,
            reverse=True,
        )
        for secret in secrets:
            text = text.replace(secret, "***")
        if self._session:
            for token in (self._session.cst, self._session.security_token):
                if token:
                    text = text.replace(token, "***")
        return text

    def _scrub(self, exc: Exception) -> IGError:
        return IGError(self._redact(str(exc)))

    # -------------------------------------------------------------- session

    def _headers(self, version: str = "1", authed: bool = True) -> dict[str, str]:
        headers = {
            "X-IG-API-KEY": self._api_key,
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json; charset=UTF-8",
            "Version": version,
        }
        if authed and self._session:
            headers["CST"] = self._session.cst
            headers["X-SECURITY-TOKEN"] = self._session.security_token
        return headers

    async def login(self) -> IGSession:
        """Open a session. Returns the accounts IG reports for this login."""
        async with self._login_lock:
            if self._session and not self._session.expired:
                return self._session
            client = self._client or httpx.AsyncClient(timeout=60)
            owned = self._client is None
            try:
                response = await client.post(
                    f"{self._base}/session",
                    headers=self._headers(version="2", authed=False),
                    json={"identifier": self._username, "password": self._password},
                )
                if response.status_code == 403:
                    raise IGError(
                        "IG rejected the credentials or the API key is not enabled "
                        "for this account (HTTP 403)."
                    )
                response.raise_for_status()
                body = response.json()
                cst = response.headers.get("CST", "")
                token = response.headers.get("X-SECURITY-TOKEN", "")
                if not cst or not token:
                    raise IGError("IG login returned no session tokens")
                self._session = IGSession(
                    cst=cst,
                    security_token=token,
                    opened_at=datetime.now(timezone.utc),
                    accounts=body.get("accounts", []),
                )
                self._active_account = body.get("currentAccountId")
                logger.info(
                    "ig session opened, %d account(s) visible",
                    len(self._session.accounts),
                )
                return self._session
            except IGError:
                raise
            except Exception as exc:  # noqa: BLE001
                # The login body carries the password; nothing derived from
                # this exception may reach a log unscrubbed.
                raise self._scrub(exc) from None
            finally:
                if owned:
                    await client.aclose()

    async def _ensure_session(self) -> IGSession:
        if self._session is None or self._session.expired:
            return await self.login()
        return self._session

    # ------------------------------------------------------------- requests

    async def get(
        self, path: str, version: str = "1", account_id: str | None = None, **params
    ) -> dict:
        """Authenticated GET with backoff, one re-login on 401, and no
        credential able to escape in an error."""
        await self._ensure_session()
        client = self._client or httpx.AsyncClient(timeout=60)
        owned = self._client is None
        try:
            return await self._request(client, path, version, account_id, params)
        except IGError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._scrub(exc) from None
        finally:
            if owned:
                await client.aclose()

    async def _request(
        self,
        client: httpx.AsyncClient,
        path: str,
        version: str,
        account_id: str | None,
        params: dict,
    ) -> dict:
        delay = 2.0
        relogged = False
        for attempt in range(self._max_retries):
            headers = self._headers(version=version)
            if account_id:
                # Scopes the request to one account without switching the
                # session's default, which would mutate shared state.
                headers["IG-ACCOUNT-ID"] = account_id
            # IG names two query parameters "from" and "to"; "from" is a
            # Python keyword, so callers pass from_ and it is translated here.
            query = {("from" if k == "from_" else k): v for k, v in (params or {}).items()}
            response = await client.get(
                f"{self._base}{path}", headers=headers, params=query or None
            )

            if response.status_code == 401 and not relogged:
                logger.info("ig session expired on %s, re-authenticating", path)
                self._session = None
                await self.login()
                relogged = True
                continue

            if response.status_code == 429:
                logger.warning("ig rate limited on %s, backing off %.1fs", path, delay)
                await asyncio.sleep(delay)
                delay *= 2
                continue

            if response.status_code in RETRY_STATUSES:
                logger.warning(
                    "ig %s on %s, backing off %.1fs (attempt %d/%d)",
                    response.status_code, path, delay, attempt + 1, self._max_retries,
                )
                await asyncio.sleep(delay)
                delay *= 2
                continue

            if response.status_code >= 400:
                # IG returns errorCode strings; surface them, scrubbed.
                detail = self._redact(response.text[:400])
                raise IGError(f"IG {response.status_code} on {path}: {detail}")
            return response.json()

        raise IGRateLimited(
            f"IG did not recover on {path} after {self._max_retries} attempts"
        )

    # ---------------------------------------------------------- read-only API

    async def switch_account(self, account_id: str) -> None:
        """Point the session at one account.

        The ONLY non-GET call in this client, and it exists because IG's
        /positions endpoint ignores the IG-ACCOUNT-ID header and always
        answers for the session's active account. Without switching, both of
        Roger's accounts return the same positions and Prism double-counts
        every one of them — verified against the live API before this was
        written.

        It is a session operation, not a trading one: it moves no money,
        places no order, and changes nothing about the account itself. IG
        reissues CST and X-SECURITY-TOKEN on a switch, so the new tokens are
        adopted here; missing that silently unauthenticates every later call,
        which returns 200 with an empty body rather than an error.
        """
        await self._ensure_session()
        client = self._client or httpx.AsyncClient(timeout=60)
        owned = self._client is None
        try:
            response = await client.put(
                f"{self._base}/session",
                headers=self._headers(version="1"),
                json={"accountId": account_id},
            )
            if response.status_code == 412 and "must-be-different" in response.text:
                # Already on this account. IG treats that as an error; for our
                # purposes it is the desired state, and the session's tokens
                # are unchanged.
                self._active_account = account_id
                return
            if response.status_code >= 400:
                raise IGError(
                    f"IG {response.status_code} switching to account: "
                    f"{self._redact(response.text[:200])}"
                )
            if self._session:
                if response.headers.get("CST"):
                    self._session.cst = response.headers["CST"]
                if response.headers.get("X-SECURITY-TOKEN"):
                    self._session.security_token = response.headers["X-SECURITY-TOKEN"]
            self._active_account = account_id
        except IGError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._scrub(exc) from None
        finally:
            if owned:
                await client.aclose()

    async def accounts(self) -> dict:
        return await self.get("/accounts")

    async def positions(self, account_id: str) -> dict:
        """Open positions for one account.

        Switches the session first: IG answers /positions for the active
        account regardless of the IG-ACCOUNT-ID header.
        """
        if self._active_account != account_id:
            await self.switch_account(account_id)
        return await self.get("/positions", version="2")

    async def transactions(
        self, account_id: str, from_date: str, to_date: str, page_size: int = 500
    ) -> dict:
        """Transaction history. IG limits how far back this reaches; whatever
        it gives is what exists."""
        if self._active_account != account_id:
            await self.switch_account(account_id)
        return await self.get(
            "/history/transactions",
            version="2",
            from_=from_date,
            to=to_date,
            pageSize=page_size,
        )

    async def activity(self, account_id: str, from_date: str) -> dict:
        if self._active_account != account_id:
            await self.switch_account(account_id)
        return await self.get(
            "/history/activity", version="3",
            from_=from_date, detailed="true", pageSize=500,
        )

    async def market(self, epic: str) -> dict:
        """Market detail for one epic — needed to resolve option contracts to
        their underlying, strike and expiry."""
        return await self.get(f"/markets/{epic}", version="3")

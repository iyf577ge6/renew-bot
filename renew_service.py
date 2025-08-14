import aiohttp


class MarzbanRenewService:
    """Simple client for renewing Marzban users.

    Parameters are pulled from environment variables in ``bot.py`` and
    provided here.  The service keeps an ``aiohttp`` session with basic
    authentication and exposes a helper for renewing a user for 31 days.
    """

    def __init__(self, address: str, username: str, password: str):
        self._base = address.rstrip("/")
        self._auth = aiohttp.BasicAuth(username, password)
        self._session = aiohttp.ClientSession(auth=self._auth)

    async def renew_user_31d(self, username: str) -> dict:
        """Renew *username* for 31 days.

        Returns a dictionary with ``ok`` and ``message`` keys describing the
        outcome so that ``bot.py`` can act on the response.  Any unexpected
        error is caught and converted into ``ok=False`` with the error message.
        """
        url = f"{self._base}/api/users/{username}/renew"
        payload = {"duration": 31}
        try:
            async with self._session.post(url, json=payload) as resp:
                if resp.status == 200:
                    try:
                        data = await resp.json()
                        msg = data.get("message", "") if isinstance(data, dict) else ""
                    except aiohttp.ContentTypeError:
                        msg = await resp.text()
                    return {"ok": True, "message": msg}
                text = await resp.text()
                return {"ok": False, "message": text}
        except Exception as exc:  # pragma: no cover - network errors
            return {"ok": False, "message": str(exc)}

    async def close(self) -> None:
        """Close the underlying ``aiohttp`` session."""
        await self._session.close()

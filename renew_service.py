import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import aiohttp


class MarzbanRenewService:
    """
    تمدید دقیقاً ۳۱ روز از «الان»، ریست حجم، و Active کردن کاربر.
    اگر کاربر وجود نداشت، پیام فارسی برمی‌گرداند.
    """

    def __init__(self, address: str, username: str, password: str):
        self.address = address.rstrip("/")
        self.username = username
        self.password = password
        self.session: Optional[aiohttp.ClientSession] = None
        self._token: Optional[str] = None

    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=40)
            # اگر SSL خودامضا دارید و خطای SSL دیدید، ssl=False را باز کنید (غیرتوصیه‌شده):
            # connector = aiohttp.TCPConnector(ssl=False)
            # self.session = aiohttp.ClientSession(timeout=timeout, connector=connector)
            self.session = aiohttp.ClientSession(timeout=timeout)

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def _auth_headers(self) -> Dict[str, str]:
        """Return auth headers, fetching a new token if needed."""
        await self._ensure_session()
        if self._token is None:
            # گرفتن توکن ادمین با application/x-www-form-urlencoded
            url = f"{self.address}/api/admin/token"
            form = {"username": self.username, "password": self.password}
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            async with self.session.post(url, data=form, headers=headers) as r:
                text = await r.text()
                if r.status != 200:
                    raise RuntimeError(f"عدم موفقیت در دریافت توکن ({r.status}): {text}")
                try:
                    data = await r.json()
                except Exception:
                    raise RuntimeError(f"پاسخ غیرقابل‌خواندن از سرور توکن: {text}")
                self._token = data.get("access_token") or data.get("token")
                if not self._token:
                    raise RuntimeError(f"توکن در پاسخ سرور یافت نشد: {data}")
        return {"Authorization": f"Bearer {self._token}"}

    @staticmethod
    def _expire_in_31_days_seconds() -> int:
        # مارزبان timestamp را به «ثانیه» می‌پذیرد
        expires_at = datetime.now(timezone.utc) + timedelta(days=31)
        return int(expires_at.timestamp())

    async def _get_user(self, username: str) -> Optional[Dict[str, Any]]:
        url = f"{self.address}/api/user/{username}"
        for attempt in range(2):
            headers = await self._auth_headers()
            async with self.session.get(url, headers=headers) as r:
                if r.status == 401 and attempt == 0:
                    self._token = None
                    continue
                if r.status == 404:
                    return None
                if r.status != 200:
                    text = await r.text()
                    raise RuntimeError(f"خطا در دریافت کاربر ({r.status}): {text}")
                return await r.json()
        raise RuntimeError("خطا در دریافت کاربر پس از تلاش مجدد")

    async def _modify_user(self, username: str, **fields) -> Dict[str, Any]:
        url = f"{self.address}/api/user/{username}"
        for attempt in range(2):
            headers = await self._auth_headers()
            async with self.session.put(url, headers=headers, json=fields) as r:
                text = await r.text()
                if r.status == 401 and attempt == 0:
                    self._token = None
                    continue
                if r.status not in (200, 201):
                    raise RuntimeError(f"خطا در بروزرسانی کاربر ({r.status}): {text}")
                try:
                    return await r.json()
                except Exception:
                    return {"raw": text}
        raise RuntimeError("خطا در بروزرسانی کاربر پس از تلاش مجدد")

    async def _reset_usage(self, username: str) -> None:
        url = f"{self.address}/api/user/{username}/reset"
        for attempt in range(2):
            headers = await self._auth_headers()
            async with self.session.post(url, headers=headers) as r:
                if r.status == 401 and attempt == 0:
                    self._token = None
                    continue
                if r.status not in (200, 204):
                    text = await r.text()
                    raise RuntimeError(f"خطا در ریست مصرف ({r.status}): {text}")
                return
        raise RuntimeError("خطا در ریست مصرف پس از تلاش مجدد")

    async def renew_user_31d(self, username: str) -> Dict[str, Any]:
        """
        - اگر نبود: پیام فارسی «این کاربر وجود ندارد.»
        - اگر بود: expire = now + 31d (ثانیه)، status=active، reset usage
        """
        user = await self._get_user(username)
        if user is None:
            return {"ok": False, "message": "این کاربر وجود ندارد."}

        new_expire = self._expire_in_31_days_seconds()

        # 1) تنظیم expire دقیقاً برای ۳۱ روز آینده + Active
        await self._modify_user(username, expire=new_expire, status="active")

        # 2) ریست حجم مصرفی
        await self._reset_usage(username)

        # 3) وضعیت نهایی
        latest = await self._get_user(username)
        return {
            "ok": True,
            "message": "تمدید با موفقیت انجام شد: ۳۱ روزه + ریست حجم + اکتیوسازی.",
            "user": (latest or {}).get("username", username),
            "expire": new_expire,
        }


# ---- CLI برای استفاده مستقیم ----
if __name__ == "__main__":
    import argparse
    import os
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(description="Marzban: renew user for exactly 31 days, reset traffic and activate.")
    parser.add_argument("--address", required=False, default=os.getenv("MARZBAN_ADDRESS", "https://yourpanel.com/"))
    parser.add_argument("--admin", required=False, default=os.getenv("MARZBAN_USERNAME", "sudo_username"))
    parser.add_argument("--password", required=False, default=os.getenv("MARZBAN_PASSWORD", "sudo_password"))
    parser.add_argument("username", help="Marzban username to renew")
    args = parser.parse_args()

    async def _run():
        svc = MarzbanRenewService(args.address, args.admin, args.password)
        try:
            res = await svc.renew_user_31d(args.username)
            print(res.get("message"))
        finally:
            await svc.close()

    asyncio.run(_run())

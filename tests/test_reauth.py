import os
import sys

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

# Ensure the project root is importable
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from renew_service import MarzbanRenewService


@pytest.mark.asyncio
async def test_get_user_reauth():
    token_calls = 0
    async def token_handler(request):
        nonlocal token_calls
        token_calls += 1
        return web.json_response({"access_token": f"token{token_calls}"})

    user_calls = 0
    async def user_handler(request):
        nonlocal user_calls
        user_calls += 1
        if user_calls == 1:
            assert request.headers.get("Authorization") == "Bearer token1"
            return web.Response(status=401)
        assert request.headers.get("Authorization") == "Bearer token2"
        return web.json_response({"username": "alice"})

    app = web.Application()
    app.router.add_post("/api/admin/token", token_handler)
    app.router.add_get("/api/user/alice", user_handler)

    server = TestServer(app)
    await server.start_server()
    svc = MarzbanRenewService(str(server.make_url('/')), 'admin', 'pass')
    try:
        user = await svc._get_user('alice')
        assert user['username'] == 'alice'
        assert token_calls == 2
        assert user_calls == 2
    finally:
        await svc.close()
        await server.close()


@pytest.mark.asyncio
async def test_modify_user_reauth():
    token_calls = 0
    async def token_handler(request):
        nonlocal token_calls
        token_calls += 1
        return web.json_response({"access_token": f"token{token_calls}"})

    put_calls = 0
    async def put_handler(request):
        nonlocal put_calls
        put_calls += 1
        if put_calls == 1:
            assert request.headers.get("Authorization") == "Bearer token1"
            return web.Response(status=401)
        assert request.headers.get("Authorization") == "Bearer token2"
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_post("/api/admin/token", token_handler)
    app.router.add_put("/api/user/alice", put_handler)

    server = TestServer(app)
    await server.start_server()
    svc = MarzbanRenewService(str(server.make_url('/')), 'admin', 'pass')
    try:
        res = await svc._modify_user('alice', expire=123)
        assert res.get('ok') is True
        assert token_calls == 2
        assert put_calls == 2
    finally:
        await svc.close()
        await server.close()


@pytest.mark.asyncio
async def test_reset_usage_reauth():
    token_calls = 0
    async def token_handler(request):
        nonlocal token_calls
        token_calls += 1
        return web.json_response({"access_token": f"token{token_calls}"})

    reset_calls = 0
    async def reset_handler(request):
        nonlocal reset_calls
        reset_calls += 1
        if reset_calls == 1:
            assert request.headers.get("Authorization") == "Bearer token1"
            return web.Response(status=401)
        assert request.headers.get("Authorization") == "Bearer token2"
        return web.Response(status=200)

    app = web.Application()
    app.router.add_post("/api/admin/token", token_handler)
    app.router.add_post("/api/user/alice/reset", reset_handler)

    server = TestServer(app)
    await server.start_server()
    svc = MarzbanRenewService(str(server.make_url('/')), 'admin', 'pass')
    try:
        await svc._reset_usage('alice')
        assert token_calls == 2
        assert reset_calls == 2
    finally:
        await svc.close()
        await server.close()

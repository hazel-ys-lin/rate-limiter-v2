"""
模擬 JS boundary attack 測試：
- 在 window 交界連發 6+6 個請求
- fixed window 漏洞：兩個 window 各自只看到 6 個 → 全部通過
- sliding window：前 window 的貢獻仍存在 → 部分請求被擋
"""

import asyncio
import time

import httpx
import pytest

from main import app
from redis_client import client as redis_client

BASE_URL = "http://test"
LIMIT = 10
WINDOW = 1  # seconds


async def send_n(c: httpx.AsyncClient, url: str, n: int) -> list[httpx.Response]:
    return [await c.get(url) for _ in range(n)]


async def wait_until_near_end_of_window(threshold_ms: int = 800) -> None:
    """等到接近秒末（> threshold_ms ms），模擬 JS getStartPoint()"""
    while True:
        ms_in_second = (time.time() % 1) * 1000
        if ms_in_second > threshold_ms:
            return
        await asyncio.sleep(0.01)


@pytest.fixture(autouse=True)
async def clear_redis():
    await redis_client.flushdb()
    yield
    await redis_client.flushdb()
    await redis_client.aclose()  # force reconnect in next test's event loop


@pytest.fixture
async def ac():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE_URL
    ) as c:
        yield c


# ── fixed window ───────────────────────────────────────────────────────────


async def test_fixed_window_blocks_over_limit(ac: httpx.AsyncClient):
    """超過 limit 的請求應該被擋下"""
    responses = await send_n(ac, "/items", LIMIT + 3)
    statuses = [r.status_code for r in responses]
    assert statuses.count(200) == LIMIT
    assert statuses.count(429) == 3


async def test_fixed_window_resets_after_window(ac: httpx.AsyncClient):
    """window 過後計數重置，可以再發請求"""
    responses = await send_n(ac, "/items", LIMIT)
    assert all(r.status_code == 200 for r in responses)

    await asyncio.sleep(WINDOW + 0.1)

    responses2 = await send_n(ac, "/items", 5)
    assert all(r.status_code == 200 for r in responses2)


async def test_fixed_window_boundary_vulnerability(ac: httpx.AsyncClient):
    """
    boundary attack：在 window 交界連發 6+6 個請求
    fixed window 漏洞 → 兩個 window 各自只看到 6 個，12 個全部通過
    """
    await wait_until_near_end_of_window(threshold_ms=800)

    # 在舊 window 末尾發 6 個（對應 JS initAttack 第一批）
    first_batch = await send_n(ac, "/items", 6)

    # 等 window 切換（對應 JS 的 setTimeout(againTime)）
    wait = (1.0 - time.time() % 1) + 0.02
    await asyncio.sleep(wait)

    # 在新 window 開頭發 6 個
    second_batch = await send_n(ac, "/items", 6)

    assert all(r.status_code == 200 for r in first_batch)
    assert all(r.status_code == 200 for r in second_batch), (
        "fixed window 漏洞：新 window 看不到舊 window 的 6 個請求，全部通過"
    )


# ── sliding window ─────────────────────────────────────────────────────────


async def test_sliding_window_blocks_over_limit(ac: httpx.AsyncClient):
    """超過 limit 的請求應該被擋下"""
    responses = await send_n(ac, "/items/1", LIMIT + 3)
    statuses = [r.status_code for r in responses]
    assert statuses.count(200) == LIMIT
    assert statuses.count(429) == 3


async def test_sliding_window_resets_after_window(ac: httpx.AsyncClient):
    """
    sliding window 看前後兩個 window，需等 window * 2 才完全清零
    （等 1 個 window 不夠，前一個 window 的貢獻還在）
    """
    responses = await send_n(ac, "/items/1", LIMIT)
    assert all(r.status_code == 200 for r in responses)

    await asyncio.sleep(WINDOW * 2 + 0.1)

    responses2 = await send_n(ac, "/items/1", 5)
    assert all(r.status_code == 200 for r in responses2)


async def test_sliding_window_handles_boundary(ac: httpx.AsyncClient):
    """
    同樣的 boundary attack
    sliding window：前 window 的請求仍有貢獻 → 部分請求被擋
    ec = prev_count * (remaining_ms / window_ms) + curr_count + 1
    """
    await wait_until_near_end_of_window(threshold_ms=800)

    first_batch = await send_n(ac, "/items/1", 6)

    wait = (1.0 - time.time() % 1) + 0.02
    await asyncio.sleep(wait)

    second_batch = await send_n(ac, "/items/1", 6)

    all_statuses = [r.status_code for r in first_batch + second_batch]
    assert 429 in all_statuses, "sliding window 應擋下部分 boundary 攻擊"

# Rate Limiter

A FastAPI + Redis implementation of three rate limiting algorithms, ported from JavaScript.

## Getting Started

```bash
docker compose up -d        # start Redis
uv run uvicorn main:app --reload
```

## Algorithms

### Fixed Window Counter

Each window uses an independent Redis key (keyed by window ID). The counter resets when the key expires at the end of the window. Implemented as a Lua script for atomicity.

**Vulnerability**: Allows up to 2x the limit at window boundaries. For example, with `limit=10` and `window=1s`, sending 10 requests at t=999ms and 10 more at t=1001ms results in all 20 passing — each window only sees 10.

### Sliding Window Counter (Lua)

Estimates the current request rate using a weighted combination of the previous and current window counts:

```
ec = prev_count × (time_remaining / window_size) + curr_count + 1
```

Mitigates the boundary vulnerability, but accuracy is limited to 1-second granularity.

> Note: Requires `window × 2` seconds to fully reset, since it tracks both the current and previous window simultaneously.

### Sliding Log (Lua)

Records each request's timestamp in a Redis Sorted Set. On each request, expired entries are removed and `ZCARD` is used to count active requests within the window.

Highest accuracy, but memory usage scales linearly with the number of requests.

## FastAPI Dependency Injection Design

Each method on `RateLimiter` returns a `Depends(...)` object, which plugs into FastAPI's dependency injection system:

```python
# rate_limiter.py
class RateLimiter:
    def fixed_window(self, limit: int, window: int) -> Any:
        async def dependency(request: Request) -> None:
            # rate limiting logic
            ...
        return Depends(dependency)

    def __call__(self, algorithm: str, limit: int, window: int) -> Any:
        # select algorithm by name
        ...
```

```python
# main.py
@app.get("/items")
def get_items(_: None = rate_limiter(algorithm="fixed_window", limit=10, window=1)):
    ...
```

Compared to middleware, the DI approach allows **per-route configuration** — each route can use a different algorithm and limit without affecting others.

## Tests

```bash
uv run pytest -v
```

| Test                                       | Description                                                             |
| ------------------------------------------ | ----------------------------------------------------------------------- |
| `test_fixed_window_blocks_over_limit`      | Requests exceeding the limit receive 429                                |
| `test_fixed_window_resets_after_window`    | Counter resets after the window expires                                 |
| `test_fixed_window_boundary_vulnerability` | Boundary attack passes all 12 requests (demonstrates the vulnerability) |
| `test_sliding_window_blocks_over_limit`    | Requests exceeding the limit receive 429                                |
| `test_sliding_window_resets_after_window`  | Fully resets after `window × 2` seconds                                 |
| `test_sliding_window_handles_boundary`     | Same boundary attack is partially blocked                               |

### Testing Notes

- Requests in `send_n` are sent sequentially (not concurrently) to avoid concurrent reads on the same Redis connection.
- The `clear_redis` fixture calls `aclose()` after each test to tear down TCP connections, ensuring each test starts with a fresh connection.

## Improvements over the JavaScript Version

### Design

**Lua scripts extracted to separate files**
The original JS version embedded Lua scripts as inline strings inside the JavaScript code, making them hard to read and impossible to syntax-highlight. This version moves each script into a dedicated `.lua` file under the `lua/` directory.

**Per-route algorithm selection via DI**
The original JS version exposed three separate middleware functions with no way to dynamically select or configure them per route. This version uses a `RateLimiter` class with `__call__`, allowing each route to specify its algorithm, limit, and window independently.

**Consistent async style**
The original JS version mixed `async/await` (`fixedWindowCounter`) with callbacks (`slidingLogs`, `slidingWindowCounter`). This version uses `async/await` throughout.

### Bug Fixes

#### 1. `sliding_log.lua` — Off-by-one

```lua
-- before
if amount <= limit then

-- after
if amount < limit then
```

`amount == limit` would still ZADD and return `0`. Since the Python check was `remaining < 0`, the last slot was allowed through — effectively permitting `limit + 1` requests. Fixed the Lua condition and updated the Python check to `remaining <= 0`.

#### 2. `sliding_window.lua` — Hardcoded TTL

```lua
-- before
redis.call('expire', ip .. tostring(currentWindow), 2, 'NX')

-- after
redis.call('expire', ip .. tostring(currentWindow), math.floor(windowSize / 1000) * 2, 'NX')
```

The TTL was hardcoded to 2 seconds, only correct for 1-second windows. Now derived from `windowSize`.

#### 3. `fixed_window` — Non-atomic operations

`INCR` and `EXPIRE` were two separate calls with a race condition window between them. Moved into `fixed_window.lua` so both operations execute atomically.

#### 5. `sliding_log` — Unique key collision risk

```javascript
// before (JS)
let uniqueString = Math.random() * 1000;

// after (Python)
unique = time.time_ns()
```

`Math.random() * 1000` produces a float in `[0, 1000)`, meaning two near-simultaneous requests could generate the same value and collide in the sorted set. Replaced with a nanosecond timestamp, which is effectively collision-free in practice.

---

# Rate Limiter（中文說明）

使用 FastAPI + Redis 實作三種 rate limiting 演算法，從 JavaScript 版本移植而來。

## 啟動

```bash
docker compose up -d        # 啟動 Redis
uv run uvicorn main:app --reload
```

## 演算法

### Fixed Window Counter

每個 window 用獨立的 Redis key（含 window 編號），window 結束後 key 過期，計數歸零。以 Lua script 實作保證原子性。

**漏洞**：在 window 交界可發送 2x 的請求。例如 limit=10、window=1s，在 t=999ms 發 10 個、t=1001ms 再發 10 個，兩個 window 各自只看到 10 個，共 20 個全部通過。

### Sliding Window Counter（Lua）

用前後兩個 window 的計數加權估算當前速率：

```
ec = prev_count × (剩餘時間 / window大小) + curr_count + 1
```

改善了 boundary 漏洞，但精度有限（以 1 秒為最小單位）。

> 注意：需等 `window × 2` 秒才能完全清零，因為同時追蹤前後兩個 window。

### Sliding Log（Lua）

用 Redis Sorted Set 記錄每筆請求的 timestamp，每次請求時清除過期記錄後計算 ZCARD。

精度最高，但記憶體用量隨請求數線性增長。

## FastAPI DI 設計

`RateLimiter` 的每個方法都回傳 `Depends(...)`，利用 FastAPI 的 dependency injection 注入到 route handler。與 middleware 方式相比，DI 的優點是可以**針對個別 route 設定不同的演算法與參數**。

## 測試說明

- `send_n` 使用循序請求（非 concurrent），避免多個 coroutine 同時讀取同一條 Redis 連線。
- `clear_redis` fixture 在每個 test 結束後呼叫 `aclose()` 關閉 TCP 連線，確保每個 test 都從乾淨的連線開始。

## 相較於 JavaScript 版本的改進

### 設計

**Lua script 獨立成檔案**
原本的 JS 版把 Lua script 以字串形式嵌在 JS 程式碼裡，可讀性差且無法語法 highlight。本版本將每個 script 抽成獨立的 `.lua` 檔，統一放在 `lua/` 目錄下。

**透過 DI 支援 per-route 演算法選擇**
原本的 JS 版將三個演算法各自暴露為獨立的 middleware function，無法動態選擇或針對不同 route 設定。本版本使用 `RateLimiter` class 搭配 `__call__`，讓每個 route 可以獨立指定演算法、limit 和 window。

**統一 async 風格**
原本的 JS 版混用 `async/await`（`fixedWindowCounter`）和 callback（`slidingLogs`、`slidingWindowCounter`）。本版本全部統一使用 `async/await`。

### Bug 修正

| 問題                               | 說明                                                  | 修正方式                                              |
| ---------------------------------- | ----------------------------------------------------- | ----------------------------------------------------- |
| `sliding_log.lua` off-by-one       | `amount <= limit` 導致多允許一個請求                  | 改為 `amount < limit`，Python 端改為 `remaining <= 0` |
| `sliding_window.lua` TTL 硬編碼    | TTL 寫死 2 秒，只對 1 秒 window 正確                  | 改為 `math.floor(windowSize / 1000) * 2`              |
| `fixed_window` 非原子操作          | `INCR` + `EXPIRE` 兩步之間有 race condition           | 移入 `fixed_window.lua` 以 Lua 保證原子性             |
| `sliding_log` unique key 碰撞風險  | `Math.random() * 1000` 可能產生相同值，造成 ZSET 碰撞 | 改用 `time.time_ns()` 奈秒時間戳                      |

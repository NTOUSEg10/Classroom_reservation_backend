"""Claim in a short transaction; perform external I/O after releasing the DB lock."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import asyncpg
import httpx

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    accepted: int = 0
    failed: int = 0


class Dispatcher:
    def __init__(
        self,
        pool: asyncpg.Pool,
        client: httpx.AsyncClient,
        edge_url: str,
        dispatch_secret: str,
        service_key: str,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.pool = pool
        self.client = client
        self.edge_url = edge_url
        self.headers = {
            "X-Dispatch-Secret": dispatch_secret,
            "apikey": service_key,
        }
        self.clock = clock

    async def tick(self) -> BatchResult:
        now = self.clock()
        async with self.pool.acquire() as connection:
            # A lease permits recovery after a worker exits between claim and send.
            rows = await connection.fetch(
                """WITH ready AS (
                       SELECT id FROM public.notifications
                       WHERE delivered_at IS NULL AND next_attempt_at <= $1
                         AND (claimed_at IS NULL OR claimed_at < $1 - interval '30 seconds')
                       ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 100
                   ) UPDATE public.notifications n
                     SET claimed_at=$1, attempts=n.attempts+1
                     FROM ready WHERE n.id=ready.id
                     RETURNING n.id,n.attempts,n.created_at""",
                now,
            )
        results = await asyncio.gather(*(self._send(row) for row in rows))
        return BatchResult(
            accepted=sum(results), failed=len(results) - sum(results)
        )

    async def _send(self, row) -> bool:
        try:
            # Poll <=1s + request <=1.7s leaves headroom within the 3s emission budget.
            async with asyncio.timeout(1.7):
                response = await self.client.post(
                    self.edge_url,
                    headers=self.headers,
                    json={"notification_id": str(row["id"])},
                    timeout=1.6,
                )
                response.raise_for_status()
                body = response.json()
                if body.get("ok") is not True:
                    raise ValueError("invalid dispatch acknowledgement")
            async with self.pool.acquire() as connection:
                await connection.execute(
                    """UPDATE public.notifications SET delivered_at=$2,
                         claimed_at=NULL,last_error=NULL WHERE id=$1""",
                    row["id"],
                    self.clock(),
                )
            if (self.clock() - row["created_at"]).total_seconds() >= 3:
                logger.warning("push_emission_budget_exceeded")
            return True
        except (httpx.HTTPError, TimeoutError, ValueError) as error:
            # Store only the error class: provider bodies/URLs may contain private tokens.
            delay = min(60, 2 ** min(row["attempts"] - 1, 6))
            async with self.pool.acquire() as connection:
                await connection.execute(
                    """UPDATE public.notifications SET claimed_at=NULL,
                         last_error=$2,next_attempt_at=$3 WHERE id=$1""",
                    row["id"],
                    type(error).__name__,
                    self.clock() + timedelta(seconds=delay),
                )
            logger.warning("push_dispatch_failed attempts=%s", row["attempts"])
            return False


async def run_worker(
    pool, edge_url, dispatch_secret, service_key, *, clock=None
):
    async with httpx.AsyncClient(follow_redirects=False) as client:
        arguments = {} if clock is None else {"clock": clock}
        dispatcher = Dispatcher(
            pool, client, edge_url, dispatch_secret, service_key, **arguments
        )
        while True:
            try:
                result = await dispatcher.tick()
                if result.accepted + result.failed == 100:
                    continue
            except (asyncpg.PostgresError, httpx.HTTPError, OSError):
                logger.exception("push_worker_unavailable")
            await asyncio.sleep(1)

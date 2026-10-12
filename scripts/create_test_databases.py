"""CI-only database provisioning; credentials come from TEST_DATABASE_URL."""

import asyncio
from urllib.parse import urlsplit, urlunsplit

import asyncpg

from tests.harness import test_database_url


async def main():
    url = test_database_url()
    parts = urlsplit(url)
    connection = await asyncpg.connect(
        urlunsplit(parts._replace(path="/postgres"))
    )
    try:
        for name in ("ntou_integration", "ntou_load", "ntou_e2e"):
            if not await connection.fetchval(
                "SELECT EXISTS(SELECT FROM pg_database WHERE datname=$1)", name
            ):
                await connection.execute(f'CREATE DATABASE "{name}"')
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())

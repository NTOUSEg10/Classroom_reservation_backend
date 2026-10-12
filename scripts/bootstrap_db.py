"""Apply the reviewed bootstrap to a NEW database; never resets existing data."""

import argparse
import asyncio
import os
from pathlib import Path

import asyncpg


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--demo-seed",
        action="store_true",
        help="Insert clearly labeled sample rooms",
    )
    arguments = parser.parse_args()
    url = os.environ.get("DATABASE_MIGRATION_URL")
    if not url:
        raise SystemExit(
            "Set DATABASE_MIGRATION_URL in the environment; do not put credentials in arguments."
        )
    connection = await asyncpg.connect(url)
    try:
        existing = await connection.fetchval(
            "SELECT to_regclass('public.profiles')"
        )
        if existing:
            raise SystemExit(
                "Application tables already exist. Bootstrap refuses to reset or overwrite data."
            )
        root = Path(__file__).resolve().parent.parent
        await connection.execute(
            (root / "supabase/schema.sql").read_text(encoding="utf-8")
        )
        await connection.execute(
            (root / "supabase/auth-hook.sql").read_text(encoding="utf-8")
        )
        if arguments.demo_seed:
            await connection.execute(
                (root / "supabase/seed.sql").read_text(encoding="utf-8")
            )
        print(
            "Schema and Google signup hook applied. Enable the hook in Supabase Auth and provision a separate application LOGIN with membership in ntou_backend."
        )
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())

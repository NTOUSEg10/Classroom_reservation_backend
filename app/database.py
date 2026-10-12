from contextlib import asynccontextmanager


async def initialize_connection(connection):
    await connection.execute("SET ROLE ntou_backend")


async def reset_connection(connection):
    # Keep asyncpg's complete session cleanup and restore the role in one trip.
    await connection.execute(
        connection.get_reset_query() + "\nSET ROLE ntou_backend;"
    )


@asynccontextmanager
async def transaction(pool):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SET LOCAL lock_timeout='1200ms'")
            await conn.execute("SET LOCAL statement_timeout='1800ms'")
            yield conn


async def points_for(conn, user_id):
    return await conn.fetchval(
        "SELECT COALESCE(sum(points),0)::int FROM violations WHERE user_id=$1 AND NOT resolved",
        user_id,
    )


async def audit(
    conn,
    actor_id,
    action,
    now,
    *,
    reservation_id=None,
    target_user_id=None,
    old_status=None,
    new_status=None,
):
    await conn.execute(
        """INSERT INTO audit_logs(actor_id,action,reservation_id,target_user_id,old_status,new_status,created_at)
      VALUES($1,$2,$3,$4,$5,$6,$7)""",
        actor_id,
        action,
        reservation_id,
        target_user_id,
        old_status,
        new_status,
        now,
    )


async def notify(conn, user_id, title, body, now, reservation_id=None):
    await conn.execute(
        """INSERT INTO notifications(user_id,reservation_id,title,body,created_at,next_attempt_at)
      VALUES($1,$2,$3,$4,$5,$5)""",
        user_id,
        reservation_id,
        title,
        body,
        now,
    )


RESERVATION_SELECT = """SELECT r.*, rooms.name AS room_name,p.name AS user_name
  FROM reservations r JOIN rooms ON rooms.id=r.room_id JOIN profiles p ON p.id=r.user_id"""


async def reservation_detail(conn, reservation_id):
    return dict(
        await conn.fetchrow(
            RESERVATION_SELECT + " WHERE r.id=$1", reservation_id
        )
    )

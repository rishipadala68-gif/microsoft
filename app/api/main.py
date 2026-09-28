import redis
from fastapi import FastAPI, HTTPException, status

from app.config import settings
from app.db import get_pool
from app.logging import logger, setup_logging

setup_logging()

app = FastAPI(
    title="Incident Response Agent",
    description="Brain-inspired memory incident response assistant",
    version="0.1.0",
)


@app.get("/healthz", status_code=status.HTTP_200_OK)
def healthz():
    db_ok = False
    redis_ok = False
    errors = []

    # Check Postgres
    try:
        pool = get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                res = cur.fetchone()
                if res and (res == (1,) or res.get("?column?") == 1 or list(res.values()) == [1]):
                    db_ok = True
    except Exception as e:
        errors.append(f"postgres: {e!s}")

    # Check Redis
    try:
        r = redis.from_url(settings.REDIS_URL, decode_responses=True)
        if r.ping():
            redis_ok = True
    except Exception as e:
        errors.append(f"redis: {e!s}")

    if not db_ok or not redis_ok:
        logger.error("healthz_failed", postgres=db_ok, redis=redis_ok, errors=errors)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"postgres": db_ok, "redis": redis_ok, "errors": errors}
        )

    return {"status": "ok", "postgres": "healthy", "redis": "healthy"}

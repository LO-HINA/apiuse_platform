from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_authenticated_user
from app.core.database import get_db
from app.storage import UserRecord

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("/daily")
async def daily_usage(
    _user: Annotated[UserRecord, Depends(get_authenticated_user)],
    days: int = Query(default=30, ge=1, le=90),
) -> list[dict]:
    db = get_db()
    cursor = await db.execute(
        """
        SELECT DATE(created_at) AS day,
               SUM(prompt_tokens)  AS input_tokens,
               SUM(completion_tokens) AS output_tokens,
               SUM(total_tokens)   AS total_tokens,
               COUNT(*)            AS requests
        FROM call_logs
        WHERE created_at >= datetime('now', ? || ' days')
        GROUP BY day
        ORDER BY day
        """,
        (str(-days),),
    )
    rows = await cursor.fetchall()
    return [
        {
            "date": row[0],
            "input_tokens": row[1],
            "output_tokens": row[2],
            "total_tokens": row[3],
            "requests": row[4],
        }
        for row in rows
    ]


@router.get("/detail")
async def detail_usage(
    _user: Annotated[UserRecord, Depends(get_authenticated_user)],
    days: int = Query(default=30, ge=1, le=90),
    model: str = Query(default=""),
) -> list[dict]:
    db = get_db()
    if model:
        cursor = await db.execute(
            """
            SELECT DATE(created_at) AS date,
                   model,
                   COUNT(*)            AS requests,
                   SUM(prompt_tokens)  AS input_tokens,
                   SUM(completion_tokens) AS output_tokens,
                   SUM(total_tokens)   AS total_tokens
            FROM call_logs
            WHERE created_at >= datetime('now', ? || ' days')
              AND model = ?
            GROUP BY date, model
            ORDER BY date DESC, model
            """,
            (str(-days), model),
        )
    else:
        cursor = await db.execute(
            """
            SELECT DATE(created_at) AS date,
                   model,
                   COUNT(*)            AS requests,
                   SUM(prompt_tokens)  AS input_tokens,
                   SUM(completion_tokens) AS output_tokens,
                   SUM(total_tokens)   AS total_tokens
            FROM call_logs
            WHERE created_at >= datetime('now', ? || ' days')
            GROUP BY date, model
            ORDER BY date DESC, model
            """,
            (str(-days),),
        )
    rows = await cursor.fetchall()
    return [
        {
            "date": row[0],
            "model": row[1],
            "requests": row[2],
            "input_tokens": row[3],
            "output_tokens": row[4],
            "total_tokens": row[5],
        }
        for row in rows
    ]


@router.get("/models")
async def list_models(
    _user: Annotated[UserRecord, Depends(get_authenticated_user)],
) -> list[str]:
    db = get_db()
    cursor = await db.execute(
        "SELECT DISTINCT model FROM call_logs ORDER BY model"
    )
    rows = await cursor.fetchall()
    return [row[0] for row in rows]

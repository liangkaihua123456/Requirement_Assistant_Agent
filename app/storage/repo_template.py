"""需求模板仓储。"""

from __future__ import annotations

from sqlalchemy import delete, select

from app.storage.db import TemplateRecord, get_db_session


def _to_dict(record: TemplateRecord) -> dict:
    return {
        "id": record.id,
        "name": record.name,
        "content": record.content,
        "created_at": str(record.created_at),
    }


async def list_templates(limit: int = 50) -> list[dict]:
    async with get_db_session() as session:
        rows = (
            await session.execute(
                select(TemplateRecord).order_by(TemplateRecord.id.desc()).limit(limit)
            )
        ).scalars().all()
    return [_to_dict(row) for row in rows]


async def create_template(name: str, content: str) -> dict:
    async with get_db_session() as session:
        record = TemplateRecord(name=name.strip(), content=content.strip())
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return _to_dict(record)


async def delete_template(template_id: int) -> bool:
    async with get_db_session() as session:
        result = await session.execute(
            delete(TemplateRecord).where(TemplateRecord.id == template_id)
        )
        await session.commit()
    return bool(result.rowcount)

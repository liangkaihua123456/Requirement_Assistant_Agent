"""需求模板接口。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.storage import repo_template

router = APIRouter(prefix="/templates", tags=["templates"])


class TemplateInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    content: str = Field(..., min_length=1, max_length=4000)


@router.get("")
async def list_templates():
    return await repo_template.list_templates()


@router.post("")
async def create_template(body: TemplateInput):
    return await repo_template.create_template(body.name, body.content)


@router.delete("/{template_id}")
async def delete_template(template_id: int):
    if not await repo_template.delete_template(template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"deleted": template_id}

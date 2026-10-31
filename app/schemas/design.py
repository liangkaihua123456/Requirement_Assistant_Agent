"""技术设计相关的 Pydantic Schema 定义。"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _coerce_str_list(value: Any) -> Any:
    """Accept string lists, or objects that models sometimes emit instead of strings."""
    if not isinstance(value, list):
        return value
    fixed: list[str] = []
    for item in value:
        if isinstance(item, str):
            fixed.append(item)
        elif isinstance(item, dict):
            fixed.append(
                str(
                    item.get("name")
                    or item.get("package")
                    or item.get("lib")
                    or item.get("dependency")
                    or json.dumps(item, ensure_ascii=False)
                )
            )
        elif item is None:
            continue
        else:
            fixed.append(str(item))
    return fixed


class ServiceComponent(BaseModel):
    """服务组件。"""

    name: str = Field(..., description="服务名称")
    responsibility: str = Field(..., description="职责描述")
    tech_stack: list[str] = Field(default_factory=list, description="技术栈")

    @field_validator("tech_stack", mode="before")
    @classmethod
    def _tech_stack_as_strings(cls, value: Any) -> Any:
        return _coerce_str_list(value)


class DBTable(BaseModel):
    """数据库表设计。"""

    table_name: str = Field(..., description="表名")
    description: str = Field(..., description="表描述")
    columns: list[dict] = Field(default_factory=list, description="列定义列表, 每项包含 name/type/nullable/description")
    indexes: list[str] = Field(default_factory=list, description="索引描述")
    related_features: list[str] = Field(default_factory=list, description="覆盖的 PRD 功能模块名称")

    @field_validator("indexes", "related_features", mode="before")
    @classmethod
    def _str_lists(cls, value: Any) -> Any:
        return _coerce_str_list(value)

    @field_validator("columns", mode="before")
    @classmethod
    def _normalize_columns(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        fixed: list[dict] = []
        for item in value:
            if isinstance(item, dict):
                fixed.append(item)
            elif isinstance(item, str):
                fixed.append({"name": item, "type": "TEXT", "nullable": True, "description": ""})
            else:
                continue
        return fixed


def _coerce_relationship(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        frm = item.get("from") or item.get("source") or item.get("table") or ""
        to = item.get("to") or item.get("target") or item.get("ref") or ""
        rel = item.get("type") or item.get("relation") or item.get("description") or item.get("name") or ""
        if frm or to or rel:
            return f"{frm} -> {to}: {rel}".strip(": ").strip()
        return json.dumps(item, ensure_ascii=False)
    if item is None:
        return ""
    return str(item)


class DBSchema(BaseModel):
    """数据库 Schema 设计。"""

    database_type: str = Field("PostgreSQL", description="数据库类型")
    tables: list[DBTable] = Field(default_factory=list, description="表列表")
    relationships: list[str] = Field(default_factory=list, description="表间关系描述")

    @field_validator("relationships", mode="before")
    @classmethod
    def _relationships_as_strings(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        return [text for text in (_coerce_relationship(item) for item in value) if text]


class APIEndpoint(BaseModel):
    """API 端点设计。"""

    method: str = Field(..., description="HTTP 方法: GET / POST / PUT / DELETE")
    path: str = Field(..., description="端点路径")
    description: str = Field(..., description="端点描述")
    request_body: str = Field("", description="请求体描述")
    response_body: str = Field("", description="响应体描述")
    auth_required: bool = Field(True, description="是否需要认证")
    related_features: list[str] = Field(default_factory=list, description="覆盖的 PRD 功能模块名称")

    @field_validator("related_features", mode="before")
    @classmethod
    def _related_as_strings(cls, value: Any) -> Any:
        return _coerce_str_list(value)

    @field_validator("request_body", "response_body", "description", "path", "method", mode="before")
    @classmethod
    def _stringify_fields(cls, value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        if value is None:
            return ""
        return value


class TechRisk(BaseModel):
    """技术风险。"""

    risk: str = Field(..., description="风险描述")
    impact: str = Field("medium", description="影响程度: high / medium / low")
    mitigation: str = Field("", description="缓解措施")


class CodeScaffold(BaseModel):
    """代码骨架建议。"""

    directory_structure: list[str] = Field(default_factory=list, description="目录结构")
    key_files: list[dict] = Field(
        default_factory=list,
        description="关键文件列表, 每项包含 path / purpose / skeleton",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="核心依赖，必须是字符串列表，例如 fastapi / sqlalchemy",
    )

    @field_validator("directory_structure", mode="before")
    @classmethod
    def _dirs_as_strings(cls, value: Any) -> Any:
        if isinstance(value, str):
            parts = [line.strip(" -\t") for line in value.replace("\\n", "\n").splitlines()]
            return [p for p in parts if p]
        return _coerce_str_list(value)

    @field_validator("dependencies", mode="before")
    @classmethod
    def _deps_as_strings(cls, value: Any) -> Any:
        return _coerce_str_list(value)

    @field_validator("key_files", mode="before")
    @classmethod
    def _normalize_key_files(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        fixed: list[dict] = []
        for item in value:
            if isinstance(item, str):
                fixed.append({"path": item, "purpose": "", "skeleton": ""})
                continue
            if not isinstance(item, dict):
                continue
            entry = dict(item)
            skeleton = entry.get("skeleton", "")
            if skeleton is None:
                entry["skeleton"] = ""
            else:
                text = skeleton if isinstance(skeleton, str) else json.dumps(skeleton, ensure_ascii=False)
                # Keep scaffold short so structured output stays within token limits.
                entry["skeleton"] = text[:600]
            fixed.append(entry)
        return fixed


class TechnicalDesign(BaseModel):
    """Engineer Agent 输出的技术设计方案。"""

    architecture_overview: str = Field(..., description="架构概述")
    architecture_style: str = Field("", description="架构风格（微服务 / 单体 / Serverless 等）")
    services: list[ServiceComponent] = Field(default_factory=list, description="服务组件列表")
    db_schema: DBSchema = Field(default_factory=DBSchema, description="数据库设计")
    api_endpoints: list[APIEndpoint] = Field(default_factory=list, description="API 端点列表")
    tech_risks: list[TechRisk] = Field(default_factory=list, description="技术风险列表")
    code_scaffold: CodeScaffold = Field(default_factory=CodeScaffold, description="代码骨架建议")

    @field_validator("architecture_overview", "architecture_style", mode="before")
    @classmethod
    def _stringify_arch(cls, value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        if value is None:
            return ""
        return value

    @field_validator("db_schema", mode="before")
    @classmethod
    def _ensure_db_schema(cls, value: Any) -> Any:
        if value is None or value == "":
            return {}
        return value

    @field_validator("code_scaffold", mode="before")
    @classmethod
    def _ensure_scaffold(cls, value: Any) -> Any:
        if value is None or value == "":
            return {}
        return value

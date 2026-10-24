"""技术设计相关的 Pydantic Schema 定义。"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ServiceComponent(BaseModel):
    """服务组件。"""

    name: str = Field(..., description="服务名称")
    responsibility: str = Field(..., description="职责描述")
    tech_stack: list[str] = Field(default_factory=list, description="技术栈")


class DBTable(BaseModel):
    """数据库表设计。"""

    table_name: str = Field(..., description="表名")
    description: str = Field(..., description="表描述")
    columns: list[dict] = Field(default_factory=list, description="列定义列表, 每项包含 name/type/nullable/description")
    indexes: list[str] = Field(default_factory=list, description="索引描述")
    related_features: list[str] = Field(default_factory=list, description="覆盖的 PRD 功能模块名称")
    related_feature_ids: list[str] = Field(
        default_factory=list, description="覆盖的 PRD feature_id 列表，用于精确追溯"
    )


class DBSchema(BaseModel):
    """数据库 Schema 设计。"""

    database_type: str = Field("PostgreSQL", description="数据库类型")
    tables: list[DBTable] = Field(default_factory=list, description="表列表")
    relationships: list[str] = Field(default_factory=list, description="表间关系描述")


class APIEndpoint(BaseModel):
    """API 端点设计。"""

    method: str = Field(..., description="HTTP 方法: GET / POST / PUT / DELETE")
    path: str = Field(..., description="端点路径")
    description: str = Field(..., description="端点描述")
    request_body: str = Field("", description="请求体描述")
    response_body: str = Field("", description="响应体描述")
    auth_required: bool = Field(True, description="是否需要认证")
    related_features: list[str] = Field(default_factory=list, description="覆盖的 PRD 功能模块名称")
    related_feature_ids: list[str] = Field(
        default_factory=list, description="覆盖的 PRD feature_id 列表，用于精确追溯"
    )


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
    dependencies: list[str] = Field(default_factory=list, description="核心依赖")


class TechnicalDesign(BaseModel):
    """Engineer Agent 输出的技术设计方案。"""

    architecture_overview: str = Field(..., description="架构概述")
    architecture_style: str = Field("", description="架构风格（微服务 / 单体 / Serverless 等）")
    services: list[ServiceComponent] = Field(default_factory=list, description="服务组件列表")
    db_schema: DBSchema = Field(default_factory=DBSchema, description="数据库设计")
    api_endpoints: list[APIEndpoint] = Field(default_factory=list, description="API 端点列表")
    tech_risks: list[TechRisk] = Field(default_factory=list, description="技术风险列表")
    code_scaffold: CodeScaffold = Field(default_factory=CodeScaffold, description="代码骨架建议")

    @model_validator(mode="before")
    @classmethod
    def _coerce_loose_fields(cls, data: Any) -> Any:
        """Normalize common deviations instead of failing the whole document.

        The model intermittently emits a string where a list is expected, or a
        dependency object where the schema asks for a string. Rejecting the
        whole design over one such field wastes a full generation, so known
        deviations are converted here.
        """
        if not isinstance(data, dict):
            return data
        value = deepcopy(data)

        for service in value.get("services") or []:
            if isinstance(service, dict):
                service["tech_stack"] = _as_str_list(service.get("tech_stack"))

        for endpoint in value.get("api_endpoints") or []:
            if isinstance(endpoint, dict):
                endpoint["related_features"] = _as_str_list(endpoint.get("related_features"))
                endpoint["related_feature_ids"] = _as_str_list(endpoint.get("related_feature_ids"))

        db_schema = value.get("db_schema")
        if isinstance(db_schema, dict):
            db_schema["relationships"] = _as_str_list(db_schema.get("relationships"))
            for table in db_schema.get("tables") or []:
                if not isinstance(table, dict):
                    continue
                for key in ("related_features", "related_feature_ids", "indexes"):
                    table[key] = _as_str_list(table.get(key))
                columns = table.get("columns")
                if isinstance(columns, list):
                    table["columns"] = [
                        column
                        if isinstance(column, dict)
                        else {"name": str(column), "type": "text", "nullable": True, "description": str(column)}
                        for column in columns
                    ]

        scaffold = value.get("code_scaffold")
        if isinstance(scaffold, dict):
            scaffold["directory_structure"] = _as_str_list(scaffold.get("directory_structure"))
            scaffold["dependencies"] = [_dependency_to_text(item) for item in _as_list(scaffold.get("dependencies"))]
            scaffold["key_files"] = [
                item
                if isinstance(item, dict)
                else {"path": str(item), "purpose": "", "skeleton": ""}
                for item in _as_list(scaffold.get("key_files"))
            ]
        return value


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_str_list(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value) if str(item).strip()]


def _dependency_to_text(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        name = str(item.get("name") or item.get("package") or "").strip()
        version = str(item.get("version") or "").strip()
        purpose = str(item.get("purpose") or item.get("reason") or "").strip()
        text = " ".join(part for part in (name, version) if part)
        if purpose:
            text = f"{text} - {purpose}" if text else purpose
        return text or json.dumps(item, ensure_ascii=False)
    return str(item)

"""PRD 产品方案相关的 Pydantic Schema 定义。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class UserStory(BaseModel):
    """用户故事。"""

    role: str = Field(..., description="角色")
    action: str = Field(..., description="行为")
    benefit: str = Field(..., description="收益")


class FeatureModule(BaseModel):
    """功能模块。"""

    feature_id: str = Field(
        "",
        description="稳定标识（小写蛇形，如 order_refund），用于跨文档追溯；缺省时由系统按名称生成",
    )
    name: str = Field(..., description="模块名称")
    description: str = Field(..., description="模块描述")
    priority: str = Field("P1", description="优先级: P0 / P1 / P2")
    sub_features: list[str] = Field(default_factory=list, description="子功能列表")
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="可验证的验收标准，每条应能被测试用例直接判定",
    )


class UserFlow(BaseModel):
    """用户流程。"""

    name: str = Field(..., description="流程名称")
    steps: list[str] = Field(default_factory=list, description="流程步骤")


class NonFunctionalRequirement(BaseModel):
    """非功能性需求。"""

    category: str = Field(..., description="类别（性能 / 安全 / 可用性等）")
    description: str = Field(..., description="需求描述")
    metric: str = Field("", description="量化指标")


class PRDDocument(BaseModel):
    """Solution Agent 输出的 PRD 文档。"""

    product_name: str = Field(..., description="产品/项目名称")
    positioning: str = Field(..., description="产品定位")
    user_stories: list[UserStory] = Field(default_factory=list, description="用户故事列表")
    feature_modules: list[FeatureModule] = Field(default_factory=list, description="功能模块列表")
    user_flows: list[UserFlow] = Field(default_factory=list, description="用户流程列表")
    non_functional_requirements: list[NonFunctionalRequirement] = Field(
        default_factory=list, description="非功能性需求"
    )
    success_metrics: list[str] = Field(default_factory=list, description="成功指标")
    out_of_scope: list[str] = Field(default_factory=list, description="不在范围内的功能")

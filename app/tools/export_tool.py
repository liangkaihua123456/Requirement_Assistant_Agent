"""Export Tool —— 将最终结果导出为 Markdown 文件。

V1 仅支持 Markdown 导出，后续可扩展 PDF / DOCX / Notion。
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.core.logger import logger
from app.tools.template_tool import render_template


def export_deliverable(state_data: dict, task_id: str = "") -> dict[str, str]:
    """将交付产物导出为 Markdown 文件。

    Args:
        state_data: 包含所有产物的状态字典
        task_id: 任务 ID

    Returns:
        文件名到文件路径的映射。
    """
    settings = get_settings()
    output_dir = settings.output_dir / (task_id or "default")
    output_dir.mkdir(parents=True, exist_ok=True)

    exported = {}
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # 1. 导出 PRD
    prd_doc = state_data.get("prd_doc")
    if prd_doc:
        try:
            content = render_template("prd", prd_doc)
            path = output_dir / f"prd_{timestamp}.md"
            path.write_text(content, encoding="utf-8")
            exported["prd"] = str(path)
        except Exception as e:
            logger.error(f"导出 PRD 失败: {e}")
            # 回退为 JSON 导出
            path = output_dir / f"prd_{timestamp}.json"
            path.write_text(json.dumps(prd_doc, ensure_ascii=False, indent=2), encoding="utf-8")
            exported["prd"] = str(path)

    # 2. 导出技术设计
    tech_design = state_data.get("technical_design")
    if tech_design:
        try:
            content = render_template("technical_design", tech_design)
            path = output_dir / f"technical_design_{timestamp}.md"
            path.write_text(content, encoding="utf-8")
            exported["technical_design"] = str(path)
        except Exception as e:
            logger.error(f"导出技术设计失败: {e}")
            path = output_dir / f"technical_design_{timestamp}.json"
            path.write_text(json.dumps(tech_design, ensure_ascii=False, indent=2), encoding="utf-8")
            exported["technical_design"] = str(path)

    # 3. 导出评审报告
    review_result = state_data.get("review_result")
    if review_result:
        try:
            content = render_template("review_report", review_result)
            path = output_dir / f"review_report_{timestamp}.md"
            path.write_text(content, encoding="utf-8")
            exported["review_report"] = str(path)
        except Exception as e:
            logger.error(f"导出评审报告失败: {e}")
            path = output_dir / f"review_report_{timestamp}.json"
            path.write_text(json.dumps(review_result, ensure_ascii=False, indent=2), encoding="utf-8")
            exported["review_report"] = str(path)

    # 4. 导出需求澄清结果
    clarified = state_data.get("clarified_requirement")
    if clarified:
        path = output_dir / f"requirement_{timestamp}.json"
        path.write_text(json.dumps(clarified, ensure_ascii=False, indent=2), encoding="utf-8")
        exported["clarified_requirement"] = str(path)

    # 5. 导出完整交付包 JSON
    path = output_dir / f"full_deliverable_{timestamp}.json"
    path.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")
    exported["full_deliverable"] = str(path)

    logger.info(f"导出完成，共 {len(exported)} 个文件", extra={"task_id": task_id})
    return exported


def export_bundle_zip(task_id: str) -> Path:
    """把任务目录下的全部产物打包为 zip。"""
    settings = get_settings()
    source = settings.output_dir / (task_id or "default")
    source.mkdir(parents=True, exist_ok=True)
    archive = settings.output_dir / f"{task_id or 'default'}_deliverables.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(source))
    logger.info(f"打包完成：{archive.name}", extra={"task_id": task_id})
    return archive


def export_docx(state_data: dict, task_id: str = "") -> Path:
    """把 PRD、技术设计与评审结论汇总成一份 Word 文档。"""
    from docx import Document

    settings = get_settings()
    output_dir = settings.output_dir / (task_id or "default")
    output_dir.mkdir(parents=True, exist_ok=True)

    document = Document()
    document.add_heading("需求交付文档", level=0)
    meta = document.add_paragraph()
    meta.add_run(f"任务 ID：{task_id or '-'}\n").bold = True
    meta.add_run(f"生成时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    prd = state_data.get("prd_doc") or {}
    if prd:
        document.add_heading("一、产品需求文档", level=1)
        if prd.get("product_name"):
            document.add_paragraph(f"产品名称：{prd['product_name']}")
        if prd.get("positioning"):
            document.add_heading("产品定位", level=2)
            document.add_paragraph(str(prd["positioning"]))

        features = prd.get("feature_modules") or prd.get("features") or []
        if features:
            document.add_heading("功能模块", level=2)
            table = document.add_table(rows=1, cols=3)
            table.style = "Light Grid Accent 1"
            header = table.rows[0].cells
            header[0].text = "模块"
            header[1].text = "描述"
            header[2].text = "优先级"
            for feature in features:
                if not isinstance(feature, dict):
                    continue
                row = table.add_row().cells
                row[0].text = str(feature.get("name") or feature.get("feature_id") or "")
                row[1].text = str(feature.get("description") or "")
                row[2].text = str(feature.get("priority") or "")

        stories = prd.get("user_stories") or []
        if stories:
            document.add_heading("用户故事", level=2)
            for item in stories[:20]:
                if isinstance(item, dict):
                    text = str(item.get("story") or item.get("description") or item)
                else:
                    text = str(item)
                document.add_paragraph(text, style="List Bullet")

        non_functional = prd.get("non_functional_requirements") or prd.get("non_functional") or []
        if non_functional:
            document.add_heading("非功能需求", level=2)
            for item in non_functional:
                document.add_paragraph(str(item), style="List Bullet")

        metrics = prd.get("success_metrics") or []
        if metrics:
            document.add_heading("成功指标", level=2)
            for item in metrics:
                document.add_paragraph(str(item), style="List Bullet")

    design = state_data.get("technical_design") or {}
    if design:
        document.add_heading("二、技术设计", level=1)
        if design.get("architecture_overview"):
            document.add_heading("架构概述", level=2)
            document.add_paragraph(str(design["architecture_overview"]))
        if design.get("architecture_style"):
            document.add_paragraph(f"架构风格：{design['architecture_style']}")

        endpoints = design.get("api_endpoints") or []
        if endpoints:
            document.add_heading("API 端点", level=2)
            table = document.add_table(rows=1, cols=3)
            table.style = "Light Grid Accent 1"
            header = table.rows[0].cells
            header[0].text = "方法"
            header[1].text = "路径"
            header[2].text = "说明"
            for endpoint in endpoints:
                row = table.add_row().cells
                row[0].text = str(endpoint.get("method") or "")
                row[1].text = str(endpoint.get("path") or "")
                row[2].text = str(endpoint.get("description") or "")

        tables = (design.get("db_schema") or {}).get("tables") or []
        if tables:
            document.add_heading("数据表", level=2)
            table = document.add_table(rows=1, cols=2)
            table.style = "Light Grid Accent 1"
            header = table.rows[0].cells
            header[0].text = "表名"
            header[1].text = "说明"
            for item in tables:
                row = table.add_row().cells
                row[0].text = str(item.get("table_name") or "")
                row[1].text = str(item.get("description") or "")

    review = state_data.get("review_result") or {}
    if review:
        document.add_heading("三、评审结论", level=1)
        document.add_paragraph(
            f"综合评分：{review.get('overall_score', '-')}　"
            f"结论：{'通过' if review.get('passed') else '未通过'}"
        )
        for issue in (review.get("issues") or [])[:15]:
            line = f"[{issue.get('severity', '-')}] {issue.get('description', '')}"
            if issue.get("suggestion"):
                line += f"　建议：{issue['suggestion']}"
            document.add_paragraph(line, style="List Bullet")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"delivery_{timestamp}.docx"
    document.save(path)
    logger.info(f"Word 导出完成：{path.name}", extra={"task_id": task_id})
    return path

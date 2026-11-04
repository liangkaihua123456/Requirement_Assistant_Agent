"""Backend skeleton generation for the four supported languages.

The output is a runnable project: routes are registered and handlers return 501
with a TODO, so the code compiles and starts, while business logic stays with
the developer. Templates use string.Template so JSON braces need no escaping.
"""

from __future__ import annotations

import re
from string import Template
from typing import Any

SUPPORTED = ("python", "node", "java", "go")

LANGUAGE_LABELS = {
    "python": "Python / FastAPI",
    "node": "Node.js / NestJS",
    "java": "Java / Spring Boot",
    "go": "Go / Gin",
}

_PARAM = re.compile(r"\{([^}]+)\}")


def pascal(value: str) -> str:
    parts = re.split(r"[^0-9a-zA-Z]+", str(value or ""))
    return "".join(part[:1].upper() + part[1:] for part in parts if part) or "Default"


def snake(value: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(value or ""))
    text = re.sub(r"[^0-9a-zA-Z]+", "_", text)
    return text.strip("_").lower() or "default"


def module_key(endpoint: dict[str, Any]) -> str:
    """Group endpoints by the first English path segment.

    Feature names are often Chinese, which cannot become identifiers; the path
    segment is stable and ASCII, so it wins.
    """
    path = str(endpoint.get("path") or "")
    for part in path.split("/"):
        if not part or part in ("api", "v1", "v2", "v3"):
            continue
        if part.startswith("{"):
            continue
        if re.fullmatch(r"[A-Za-z0-9_\-]+", part):
            return snake(part)
    features = [str(item) for item in (endpoint.get("related_features") or []) if item]
    if features:
        key = snake(features[0])
        if key and key != "default":
            return key
    return "default"


def group_by_module(design: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for endpoint in design.get("api_endpoints") or []:
        if not isinstance(endpoint, dict):
            continue
        grouped.setdefault(module_key(endpoint), []).append(endpoint)
    return grouped


def _path_params(path: str) -> list[str]:
    return [snake(name) for name in _PARAM.findall(path)]


def relative_path(path: str, module: str) -> str:
    """Strip the api/version/module prefix so it is not mounted twice.

    Designs are inconsistent: some paths are `/api/v1/books`, others `/api/books`
    or `/books`. The module prefix is mounted once at the router/controller, so
    only the remainder belongs to the handler.
    """
    parts = [part for part in str(path or "").split("/") if part]
    while parts and (parts[0].lower() == "api" or re.fullmatch(r"v\d+", parts[0], re.I)):
        parts.pop(0)
    if parts and snake(parts[0]) == module:
        parts.pop(0)
    return "/" + "/".join(parts) if parts else ""


def _doc(endpoint: dict[str, Any]) -> str:
    return str(endpoint.get("description") or "").replace("\n", " ").strip()[:120]


# ---------------------------------------------------------------------------
# Python / FastAPI
# ---------------------------------------------------------------------------

_PY_ROUTES = Template('''"""$module_label 路由，由技术设计自动生成。"""

from fastapi import APIRouter, HTTPException, Path

router = APIRouter(prefix="/$module", tags=["$module_label"])

$handlers
''')

_PY_HANDLER = Template('''
@router.${method}("${path}")
def ${func}(${args}):
    """${doc}"""
    # TODO: 实现业务逻辑，参考 openapi.yaml 中的请求与响应定义
    raise HTTPException(status_code=501, detail="${func} 尚未实现")
''')


def _python(design: dict[str, Any], prd: dict[str, Any]) -> dict[str, str]:
    grouped = group_by_module(design)
    files: dict[str, str] = {}

    main_routes: list[str] = []
    for module, endpoints in grouped.items():
        handlers: list[str] = []
        for endpoint in endpoints:
            method = str(endpoint.get("method") or "get").lower()
            original = str(endpoint.get("path") or "/")
            path = relative_path(original, module) or ""
            func = f"{method}_{snake(original)}"
            params = _path_params(path)
            args = ", ".join(f"{name}: str = Path(...)" for name in params)
            handlers.append(
                _PY_HANDLER.substitute(
                    method=method,
                    path=path,
                    func=func,
                    args=args,
                    doc=_doc(endpoint),
                )
            )
        body = _PY_ROUTES.substitute(
            module=module, module_label=module, handlers="".join(handlers)
        )
        files[f"backend/app/routes/{module}.py"] = body
        main_routes.append(
            f"from app.routes import {module}  # noqa: E402\n"
            f"app.include_router({module}.router, prefix=\"/api/v1\")"
        )

    files["backend/app/__init__.py"] = ""
    files["backend/app/routes/__init__.py"] = ""

    title = str((prd or {}).get("product_name") or "Generated Service")
    modules = [module for module in grouped]
    module_imports = "\n".join(
        f"from app.routes import {module}" for module in modules
    )
    module_routers = "\n".join(
        f'app.include_router({module}.router, prefix="/api/v1")' for module in modules
    )
    files["backend/app/main.py"] = (
        '"""服务入口，由技术设计自动生成。"""\n\n'
        "from fastapi import FastAPI\n\n"
        + (module_imports + "\n\n" if module_imports else "")
        + f'app = FastAPI(title="{title}", version="1.0.0")\n\n'
        + (module_routers + "\n\n\n" if module_routers else "")
        + '@app.get("/health")\ndef health():\n    return {"status": "ok"}\n'
    )

    files["backend/requirements.txt"] = (
        "fastapi>=0.115\nuvicorn[standard]>=0.30\npydantic>=2.7\nsqlalchemy>=2.0\n"
    )
    files["backend/Dockerfile"] = (
        "FROM python:3.12-slim\nWORKDIR /app\n"
        "COPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\n"
        "COPY app ./app\nEXPOSE 8000\n"
        'CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]\n'
    )
    files["backend/README.md"] = (
        f"# {title} 后端\n\n"
        "```bash\npip install -r requirements.txt\nuvicorn app.main:app --reload\n```\n\n"
        "接口定义见 `openapi.yaml`，数据库脚本见 `schema.sql`。\n"
        "各 handler 目前返回 501，按 TODO 补齐业务逻辑。\n"
    )
    return files


# ---------------------------------------------------------------------------
# Go / Gin
# ---------------------------------------------------------------------------

_GO_HANDLER = Template('''
// ${func} ${doc}
func ${func}(c *gin.Context) {
	c.JSON(http.StatusNotImplemented, gin.H{"error": "${func} 尚未实现"})
}
''')

_GO_FILE = Template('''// ${module} 路由，由技术设计自动生成。
package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// Register${Module} 注册 ${module} 模块路由。
func Register${Module}(r *gin.RouterGroup) {
${routes}
}
${handlers}
''')


def _go(design: dict[str, Any], prd: dict[str, Any]) -> dict[str, str]:
    grouped = group_by_module(design)
    files: dict[str, str] = {}
    registrations: list[str] = []

    for module, endpoints in grouped.items():
        routes: list[str] = []
        handlers: list[str] = []
        for endpoint in endpoints:
            method = str(endpoint.get("method") or "GET").upper()
            original = str(endpoint.get("path") or "/")
            rel = relative_path(original, module)
            gin_path = _PARAM.sub(r":\1", rel) if rel else ""
            func = pascal(f"{method}_{original}")
            routes.append(f'\tr.{method}("{gin_path}", {func})')
            handlers.append(_GO_HANDLER.substitute(func=func, doc=_doc(endpoint)))
        module_pascal = pascal(module)
        files[f"backend/handlers/{module}.go"] = _GO_FILE.substitute(
            module=module,
            Module=module_pascal,
            routes="\n".join(routes),
            handlers="".join(handlers),
        )
        registrations.append(
            f'\thandlers.Register{module_pascal}(api.Group("/{module}"))'
        )

    files["backend/main.go"] = (
        "// 服务入口，由技术设计自动生成。\npackage main\n\n"
        'import (\n\t"net/http"\n\n\t"github.com/gin-gonic/gin"\n\n'
        '\t"generated/backend/handlers"\n)\n\n'
        "func main() {\n\tr := gin.Default()\n"
        '\tr.GET("/health", func(c *gin.Context) { c.JSON(http.StatusOK, gin.H{"status": "ok"}) })\n'
        '\tapi := r.Group("/api/v1")\n'
        + "\n".join(registrations)
        + "\n\n\tr.Run(\":8080\")\n}\n"
    )
    files["backend/go.mod"] = (
        "module generated/backend\n\ngo 1.22\n\nrequire github.com/gin-gonic/gin v1.10.0\n"
    )
    files["backend/README.md"] = (
        "# 后端（Go / Gin）\n\n```bash\ncd backend && go mod tidy && go run .\n```\n\n"
        "接口定义见 `openapi.yaml`，数据库脚本见 `schema.sql`。\n"
    )
    return files


# ---------------------------------------------------------------------------
# Node / NestJS
# ---------------------------------------------------------------------------

_NODE_CONTROLLER = Template('''import { Controller, Get, Post, Put, Delete, Param } from '@nestjs/common';

@Controller('${base}')
export class ${Module}Controller {
$methods
}
''')


def _node(design: dict[str, Any], prd: dict[str, Any]) -> dict[str, str]:
    grouped = group_by_module(design)
    files: dict[str, str] = {}
    modules: list[str] = []

    for module, endpoints in grouped.items():
        methods: list[str] = []
        for endpoint in endpoints:
            method = str(endpoint.get("method") or "GET").upper()
            original = str(endpoint.get("path") or "/")
            rel = relative_path(original, module)
            nest_path = _PARAM.sub(r":\1", rel)
            params = _PATH_PARAMS_NODE(rel)
            decorator = {
                "GET": "Get",
                "POST": "Post",
                "PUT": "Put",
                "PATCH": "Put",
                "DELETE": "Delete",
            }.get(method, "Get")
            signature = ", ".join(f"@Param('{name}') {name}: string" for name in params)
            methods.append(
                f"  @{decorator}('{nest_path}')\n"
                f"  {snake(method + '_' + original)}({signature}) {{\n"
                f"    // TODO: {_doc(endpoint)}\n"
                f"    throw new Error('NotImplemented');\n"
                f"  }}\n"
            )
        files[f"backend/src/{module}/{module}.controller.ts"] = _NODE_CONTROLLER.substitute(
            base=module,
            Module=pascal(module),
            methods="\n".join(methods),
        )
        modules.append(pascal(module))

    files["backend/src/app.module.ts"] = (
        "import { Module } from '@nestjs/common';\n"
        + "\n".join(
            f"import {{ {name}Controller }} from './{snake(name)}/{snake(name)}.controller';"
            for name in modules
        )
        + "\n\n@Module({\n  controllers: ["
        + ", ".join(f"{name}Controller" for name in modules)
        + "],\n})\nexport class AppModule {}\n"
    )
    files["backend/src/main.ts"] = (
        "import { NestFactory } from '@nestjs/core';\nimport { AppModule } from './app.module';\n\n"
        "async function bootstrap() {\n  const app = await NestFactory.create(AppModule);\n"
        "  await app.listen(3000);\n}\nbootstrap();\n"
    )
    files["backend/package.json"] = (
        '{\n  "name": "generated-backend",\n  "version": "1.0.0",\n'
        '  "scripts": { "start": "nest start", "build": "nest build" },\n'
        '  "dependencies": {\n    "@nestjs/common": "^10.4.0",\n'
        '    "@nestjs/core": "^10.4.0",\n    "@nestjs/platform-express": "^10.4.0",\n'
        '    "rxjs": "^7.8.1",\n    "reflect-metadata": "^0.2.2"\n  },\n'
        '  "devDependencies": {\n    "@nestjs/cli": "^10.4.0",\n'
        '    "typescript": "^5.5.0"\n  }\n}\n'
    )
    files["backend/README.md"] = (
        "# 后端（NestJS）\n\n```bash\ncd backend && npm install && npm run start:dev\n```\n\n"
        "接口定义见 `openapi.yaml`，数据库脚本见 `schema.sql`。\n"
    )
    return files


def _PATH_PARAMS_NODE(path: str) -> list[str]:
    return [_PARAM_NAME(name) for name in _PARAM.findall(path)]


def _PARAM_NAME(name: str) -> str:
    return snake(name)


# ---------------------------------------------------------------------------
# Java / Spring Boot
# ---------------------------------------------------------------------------

_JAVA_CONTROLLER = Template('''package com.example.demo.controller;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/v1/${module}")
public class ${Module}Controller {
$methods
}
''')


def _java(design: dict[str, Any], prd: dict[str, Any]) -> dict[str, str]:
    grouped = group_by_module(design)
    files: dict[str, str] = {}

    for module, endpoints in grouped.items():
        methods: list[str] = []
        for endpoint in endpoints:
            method = str(endpoint.get("method") or "GET").upper()
            original = str(endpoint.get("path") or "/")
            rel = relative_path(original, module)
            mapping = {
                "GET": "GetMapping",
                "POST": "PostMapping",
                "PUT": "PutMapping",
                "PATCH": "PutMapping",
                "DELETE": "DeleteMapping",
            }.get(method, "GetMapping")
            params = [f"@PathVariable String {name}" for name in _path_params(rel)]
            signature = ", ".join(params)
            methods.append(
                f'    @{mapping}("{rel}")\n'
                f"    public Object {snake(method + '_' + original)}({signature}) {{\n"
                f"        // TODO: {_doc(endpoint)}\n"
                f'        throw new ResponseStatusException(HttpStatus.NOT_IMPLEMENTED, "尚未实现");\n'
                f"    }}\n"
            )
        files[
            f"backend/src/main/java/com/example/demo/controller/{pascal(module)}Controller.java"
        ] = _JAVA_CONTROLLER.substitute(
            module=module,
            Module=pascal(module),
            methods="\n".join(methods),
        )

    files["backend/src/main/java/com/example/demo/DemoApplication.java"] = (
        "package com.example.demo;\n\n"
        "import org.springframework.boot.SpringApplication;\n"
        "import org.springframework.boot.autoconfigure.SpringBootApplication;\n\n"
        "@SpringBootApplication\npublic class DemoApplication {\n"
        "    public static void main(String[] args) {\n"
        "        SpringApplication.run(DemoApplication.class, args);\n    }\n}\n"
    )
    files["backend/pom.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<project xmlns="http://maven.apache.org/POM/4.0.0" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 '
        'https://maven.apache.org/xsd/maven-4.0.0.xsd">\n'
        "  <modelVersion>4.0.0</modelVersion>\n"
        "  <parent>\n    <groupId>org.springframework.boot</groupId>\n"
        "    <artifactId>spring-boot-starter-parent</artifactId>\n"
        "    <version>3.3.0</version>\n  </parent>\n"
        "  <groupId>com.example</groupId>\n  <artifactId>demo</artifactId>\n"
        "  <version>1.0.0</version>\n  <properties><java.version>17</java.version></properties>\n"
        "  <dependencies>\n    <dependency>\n"
        "      <groupId>org.springframework.boot</groupId>\n"
        "      <artifactId>spring-boot-starter-web</artifactId>\n    </dependency>\n"
        "  </dependencies>\n</project>\n"
    )
    files["backend/README.md"] = (
        "# 后端（Spring Boot）\n\n```bash\ncd backend && mvn spring-boot:run\n```\n\n"
        "接口定义见 `openapi.yaml`，数据库脚本见 `schema.sql`。\n"
    )
    return files


def build_backend(
    design: dict[str, Any], prd_doc: dict[str, Any], language: str
) -> dict[str, str]:
    """Return {relative_path: content} for the chosen language."""
    if language == "node":
        return _node(design, prd_doc)
    if language == "java":
        return _java(design, prd_doc)
    if language == "go":
        return _go(design, prd_doc)
    return _python(design, prd_doc)

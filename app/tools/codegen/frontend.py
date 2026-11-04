"""Frontend skeleton generation (Vue 3 + Element Plus).

Pages are derived from the API modules: one list page and one form page per
module, with columns taken from the matching database table.
"""

from __future__ import annotations

from string import Template
from typing import Any

from app.tools.codegen.backend import group_by_module, pascal, relative_path, snake


def _endpoint_url(path: str, module: str) -> str:
    """Mount the module once and keep only the remainder."""
    rel = relative_path(path, module)
    return f"/{module}{rel}" if rel else f"/{module}"


def _table_for_module(module: str, design: dict[str, Any]) -> dict[str, Any]:
    tables = [
        item
        for item in ((design.get("db_schema") or {}).get("tables") or [])
        if isinstance(item, dict)
    ]
    for table in tables:
        if snake(str(table.get("table_name") or "")) == module:
            return table
    for table in tables:
        features = [snake(str(item)) for item in (table.get("related_features") or [])]
        if module in features:
            return table
    if tables:
        return tables[0]
    return {}


def _columns(table: dict[str, Any], limit: int = 5) -> list[str]:
    names: list[str] = []
    for column in table.get("columns") or []:
        if not isinstance(column, dict):
            continue
        name = str(column.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    if not names:
        names = ["id", "name", "status", "created_at"]
    return names[:limit]


_LIST_PAGE = Template('''<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { $MODULE_CAMEL } from '@/api/client'

interface Row {
  id?: string | number
  [key: string]: unknown
}

const rows = ref<Row[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await $MODULE_CAMEL.list()
    rows.value = Array.isArray(data) ? data : (data.items ?? [])
  } catch {
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <h2>$MODULE_LABEL</h2>
      <router-link to="/$MODULE_SNAKE/new">
        <el-button type="primary">新建</el-button>
      </router-link>
    </header>

    <el-table v-loading="loading" :data="rows" border stripe>
$COLUMNS
    </el-table>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.page-head h2 { font-size: 16px; font-weight: 650; }
</style>
''')

_FORM_PAGE = Template('''<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { $MODULE_CAMEL } from '@/api/client'

const router = useRouter()
const saving = ref(false)
const form = reactive<Record<string, unknown>>({
$FIELDS
})

async function submit() {
  saving.value = true
  try {
    await $MODULE_CAMEL.create(form)
    ElMessage.success('已保存')
    router.push('/$MODULE_SNAKE')
  } catch {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="page">
    <h2>新建 $MODULE_LABEL</h2>
    <el-form :model="form" label-width="120px">
$FORM_ITEMS
      <el-form-item>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
        <el-button @click="router.back()">取消</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<style scoped>
.page { padding: 16px; max-width: 720px; }
.page h2 { font-size: 16px; font-weight: 650; margin-bottom: 16px; }
</style>
''')


def _api_client(grouped: dict[str, list[dict[str, Any]]]) -> str:
    lines = [
        "import axios from 'axios'",
        "",
        "export const http = axios.create({ baseURL: '/api/v1', timeout: 15000 })",
        "",
    ]
    for module, endpoints in grouped.items():
        camel = module + "Api"
        has_create = any(
            str(item.get("method") or "").upper() == "POST" for item in endpoints
        )
        has_list = any(
            str(item.get("method") or "").upper() == "GET" for item in endpoints
        )
        lines.append(f"export const {camel} = {{")
        if has_list:
            candidate = next(
                (
                    item
                    for item in endpoints
                    if str(item.get("method") or "").upper() == "GET"
                ),
                None,
            )
            target = _endpoint_url(str(candidate.get("path") or ""), module) if candidate else f"/{module}"
            lines.append(f"  list: () => http.get('{target}'),")
        if has_create:
            candidate = next(
                (
                    item
                    for item in endpoints
                    if str(item.get("method") or "").upper() == "POST"
                ),
                None,
            )
            target = _endpoint_url(str(candidate.get("path") or ""), module) if candidate else f"/{module}"
            lines.append(
                f"  create: (payload: Record<string, unknown>) => http.post('{target}', payload),"
            )
        lines.append("}")
        lines.append("")
    return "\n".join(lines)


def _router(grouped: dict[str, list[dict[str, Any]]]) -> str:
    imports = "\n".join(
        f"import {pascal(module)}List from '@/views/{pascal(module)}List.vue'"
        for module in grouped
    )
    form_imports = "\n".join(
        f"import {pascal(module)}Form from '@/views/{pascal(module)}Form.vue'"
        for module in grouped
    )
    routes: list[str] = []
    for module in grouped:
        name = pascal(module)
        routes.append(
            f"  {{ path: '/{module}', name: '{module}-list', component: {name}List }},"
        )
        routes.append(
            f"  {{ path: '/{module}/new', name: '{module}-new', component: {name}Form }},"
        )
    return (
        "import { createRouter, createWebHistory } from 'vue-router'\n\n"
        + imports
        + "\n"
        + form_imports
        + "\n\nconst router = createRouter({\n  history: createWebHistory(),\n"
        + "  routes: [\n"
        + "\n".join(routes)
        + "\n  ],\n})\n\nexport default router\n"
    )


def build_frontend(design: dict[str, Any]) -> dict[str, str]:
    """Return {relative_path: content} for the Vue admin skeleton."""
    grouped = group_by_module(design)
    files: dict[str, str] = {}

    for module, _endpoints in grouped.items():
        name = pascal(module)
        table = _table_for_module(module, design)
        columns = _columns(table)

        table_columns = "\n".join(
            f'      <el-table-column prop="{column}" label="{column}" />'
            for column in columns
        )
        files[f"frontend/src/views/{name}List.vue"] = _LIST_PAGE.substitute(
            MODULE_CAMEL=module + "Api",
            MODULE_LABEL=module,
            MODULE_SNAKE=module,
            COLUMNS=table_columns,
        )

        fields = "\n".join(f"  {column}: ''," for column in columns if column != "id")
        items = "\n".join(
            f'      <el-form-item label="{column}">\n'
            f'        <el-input v-model="form.{column}" />\n'
            f"      </el-form-item>"
            for column in columns
            if column != "id"
        )
        files[f"frontend/src/views/{name}Form.vue"] = _FORM_PAGE.substitute(
            MODULE_CAMEL=module + "Api",
            MODULE_LABEL=module,
            MODULE_SNAKE=module,
            FIELDS=fields,
            FORM_ITEMS=items,
        )

    files["frontend/src/api/client.ts"] = _api_client(grouped)
    files["frontend/src/router/index.ts"] = _router(grouped)
    files["frontend/package.json"] = (
        '{\n  "name": "generated-frontend",\n  "version": "1.0.0",\n'
        '  "scripts": { "dev": "vite", "build": "vue-tsc -b && vite build" },\n'
        '  "dependencies": {\n    "axios": "^1.7.0",\n'
        '    "element-plus": "^2.8.0",\n    "vue": "^3.5.0",\n'
        '    "vue-router": "^4.4.0"\n  },\n'
        '  "devDependencies": {\n    "@vitejs/plugin-vue": "^5.1.0",\n'
        '    "typescript": "^5.5.0",\n    "vite": "^5.4.0",\n'
        '    "vue-tsc": "^2.1.0"\n  }\n}\n'
    )
    files["frontend/README.md"] = (
        "# 前端（Vue 3 + Element Plus）\n\n"
        "```bash\ncd frontend && npm install && npm run dev\n```\n\n"
        "页面按功能模块生成，字段来自数据库表定义；接口地址与 `openapi.yaml` 一致。\n"
    )
    return files

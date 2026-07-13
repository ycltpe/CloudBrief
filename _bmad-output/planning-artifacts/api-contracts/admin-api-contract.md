---
title: CloudBrief Admin 后台 API 契约
status: draft
created: 2026-07-04
updated: 2026-07-04
---

# Admin 后台 API 契约

本契约面向前后端开发者，定义管理后台所需的 REST API 接口、请求/响应 Schema、错误码与鉴权方式。

## 1. 鉴权方式

所有 Admin 后台接口（除 `/auth/register`、`/auth/login` 外）均需在请求头携带：

```http
Authorization: Bearer <access_token>
```

JWT token 由 `/auth/login` 返回，前端在 localStorage 中保存并在每次请求时注入。

## 2. 通用错误响应

所有接口统一返回以下错误结构：

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "人类可读的错误说明",
    "detail": {}
  }
}
```

常用错误码：

| HTTP 状态 | 错误码 | 说明 |
| --- | --- | --- |
| 400 | `BAD_REQUEST` | 请求参数非法 |
| 401 | `UNAUTHORIZED` | 未登录或 token 过期 |
| 403 | `FORBIDDEN` | 无权访问 |
| 404 | `NOT_FOUND` | 资源不存在 |
| 409 | `CONFLICT` | 资源冲突（如用户名已存在） |
| 422 | `VALIDATION_ERROR` | 请求体验证失败 |
| 500 | `INTERNAL_ERROR` | 服务器内部错误 |

## 3. 认证接口

### 3.1 用户注册

```http
POST /auth/register
```

**请求体：**

```json
{
  "username": "string",  // 必填，3-32 字符，仅允许字母/数字/下划线
  "password": "string",  // 必填，至少 6 位
  "role": "user"         // 可选，默认 user；可选值 admin/qa/user
}
```

**响应 201：**

```json
{
  "id": 1,
  "username": "alice",
  "role": "user",
  "created_at": "2026-07-04T08:00:00"
}
```

### 3.2 用户登录

```http
POST /auth/login
```

**请求体：**

```json
{
  "username": "string",
  "password": "string"
}
```

**响应 200：**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "username": "alice",
    "role": "user"
  }
}
```

### 3.3 退出登录

```http
POST /auth/logout
```

**响应 200：**

```json
{
  "message": "已退出登录"
}
```

> MVP 阶段 token 黑名单可选实现，前端清除 token 即可视为登出。

### 3.4 当前用户信息

```http
GET /auth/me
```

**响应 200：**

```json
{
  "id": 1,
  "username": "alice",
  "role": "user"
}
```

## 4. Dashboard 接口

### 4.1 系统概览

```http
GET /admin/dashboard
```

**响应 200：**

```json
{
  "user_count": 12,
  "conversation_count_today": 45,
  "index_status": {
    "is_ready": true,
    "active_collection": "cloudbrief_chunks_v2",
    "bm25_index_path": "./data/bm25_index_20260704_081055_035f6b87.pkl",
    "last_task_status": "completed",
    "last_task_updated_at": "2026-07-04T08:10:55"
  },
  "latest_eval_scores": {
    "context_precision": 0.82,
    "context_recall": 0.78,
    "faithfulness": 0.85,
    "answer_relevancy": 0.88
  },
  "recent_tasks": [
    {
      "task_id": "...",
      "status": "completed",
      "created_at": "2026-07-04T08:00:00"
    }
  ]
}
```

## 5. 用户管理接口

仅 `admin` 角色可访问。

### 5.1 用户列表

```http
GET /admin/users?q=&role=&limit=20&offset=0
```

**查询参数：**

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| q | string | 可选，按用户名模糊搜索 |
| role | string | 可选，按角色筛选 |
| limit | int | 默认 20，最大 100 |
| offset | int | 默认 0 |

**响应 200：**

```json
{
  "total": 12,
  "items": [
    {
      "id": 1,
      "username": "alice",
      "role": "admin",
      "created_at": "2026-07-01T10:00:00",
      "last_login_at": "2026-07-04T09:00:00"
    }
  ]
}
```

### 5.2 新增用户

```http
POST /admin/users
```

**请求体：**

```json
{
  "username": "bob",
  "password": "initial_password",
  "role": "user"
}
```

**响应 201：**

```json
{
  "id": 2,
  "username": "bob",
  "role": "user",
  "created_at": "2026-07-04T10:00:00"
}
```

### 5.3 删除用户

```http
DELETE /admin/users/{user_id}
```

**响应 204：** 无内容

**限制：** 禁止删除最后一个 `admin`。

## 6. 系统设置接口

仅 `admin` 角色可修改，`admin` 和 `qa` 可查看。

### 6.1 获取设置

```http
GET /admin/settings
```

**响应 200：**

```json
{
  "refusal_threshold": 0.3,
  "stale_threshold_days": 90,
  "max_history_rounds": 10,
  "request_timeout": 30
}
```

### 6.2 更新设置

```http
PUT /admin/settings
```

**请求体：**

```json
{
  "refusal_threshold": 0.35,
  "stale_threshold_days": 60,
  "max_history_rounds": 10,
  "request_timeout": 30
}
```

**响应 200：** 返回更新后的完整设置对象

## 7. 知识库管理接口

仅 `admin` 角色可访问。

### 7.1 目录列表

```http
GET /admin/kb/directories
```

**响应 200：**

```json
{
  "items": [
    {
      "id": 1,
      "name": "帮助文档",
      "path": "data/help",
      "parent_id": null,
      "created_at": "2026-07-01T10:00:00",
      "updated_at": "2026-07-01T10:00:00"
    }
  ]
}
```

### 7.2 新建目录

```http
POST /admin/kb/directories
```

**请求体：**

```json
{
  "name": "产品更新",
  "parent_id": null
}
```

**响应 201：**

```json
{
  "id": 2,
  "name": "产品更新",
  "path": "data/产品更新",
  "parent_id": null,
  "created_at": "2026-07-04T10:00:00"
}
```

### 7.3 删除目录

```http
DELETE /admin/kb/directories/{directory_id}
```

**限制：** 仅允许删除空目录。

**响应 204：** 无内容

### 7.4 目录下文件列表

```http
GET /admin/kb/directories/{directory_id}/files
```

**响应 200：**

```json
{
  "items": [
    {
      "id": 1,
      "filename": "help.md",
      "source_type": "help_doc",
      "file_path": "data/help/help.md",
      "file_size": 10240,
      "updated_at": "2026-07-04T10:00:00",
      "created_at": "2026-07-04T10:00:00"
    }
  ]
}
```

### 7.5 上传文件

```http
POST /admin/kb/files
Content-Type: multipart/form-data
```

**表单字段：**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| directory_id | int | 必填，目标目录 ID |
| file | File | 必填，Markdown/JSON/CSV |
| source_type | string | 可选，默认根据文件内容推断；可选值 help_doc/changelog/ticket/faq |

**响应 201：**

```json
{
  "id": 2,
  "filename": "changelog_july.json",
  "source_type": "changelog",
  "file_path": "data/产品更新/changelog_july.json",
  "file_size": 2048,
  "updated_at": "2026-07-04T10:05:00",
  "created_at": "2026-07-04T10:05:00"
}
```

### 7.6 删除文件

```http
DELETE /admin/kb/files/{file_id}
```

**响应 204：** 无内容

### 7.7 整合重建索引

复用现有接口：

```http
POST /index/rebuild
```

**响应 200：**

```json
{
  "task_id": "celery-task-id"
}
```

## 8. RAGAS 评测审计接口

`admin` 和 `qa` 角色可访问。

### 8.1 评测记录列表

```http
GET /admin/eval/results?min_score=&has_feedback=&limit=20&offset=0
```

**查询参数：**

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| min_score | float | 可选，最低 faithfulness 分数筛选 |
| has_feedback | bool | 可选，是否已有人工反馈 |
| limit | int | 默认 20 |
| offset | int | 默认 0 |

**响应 200：**

```json
{
  "total": 30,
  "items": [
    {
      "id": 1,
      "question": "报表导出后无法打开怎么办？",
      "answer": "...",
      "ground_truth": "...",
      "ragas_scores": {
        "context_precision": 0.8,
        "context_recall": 0.75,
        "faithfulness": 0.7,
        "answer_relevancy": 0.85
      },
      "human_score": null,
      "is_adopted": false,
      "is_modified": false,
      "created_at": "2026-07-04T10:00:00"
    }
  ]
}
```

### 8.2 评测详情

```http
GET /admin/eval/results/{result_id}
```

**响应 200：**

```json
{
  "id": 1,
  "question": "报表导出后无法打开怎么办？",
  "answer": "...",
  "ground_truth": "...",
  "contexts": [
    {
      "chunk_id": "help:export:0",
      "source_title": "导出功能帮助",
      "source_type": "help_doc",
      "content": "...",
      "updated_at": "2026-06-01T10:00:00"
    }
  ],
  "ragas_scores": {
    "context_precision": 0.8,
    "context_recall": 0.75,
    "faithfulness": 0.7,
    "answer_relevancy": 0.85
  },
  "reasoning": {
    "faithfulness_reasoning": "..."
  },
  "human_score": null,
  "human_note": null,
  "is_adopted": false,
  "is_modified": false,
  "created_at": "2026-07-04T10:00:00",
  "updated_at": "2026-07-04T10:00:00"
}
```

### 8.3 人工反馈

```http
POST /admin/eval/results/{result_id}/feedback
```

**请求体：**

```json
{
  "human_score": 3,
  "human_note": "答案遗漏了关键步骤 4",
  "is_adopted": false,
  "is_modified": true
}
```

**响应 200：** 返回更新后的记录对象

### 8.4 导出人工标注

```http
GET /admin/eval/export?format=csv
```

**查询参数：**

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| format | string | 必填，`csv` 或 `json` |

**响应 200：** 返回文件下载流

## 9. 前端路由约定

| 路由 | 页面 | 所需最低角色 |
| --- | --- | --- |
| `/admin/login` | 登录页 | 公开 |
| `/admin/register` | 注册页 | 公开 |
| `/admin/dashboard` | Dashboard | user |
| `/admin/settings` | 系统设置 | admin |
| `/admin/users` | 用户管理 | admin |
| `/admin/chat` | 聊天助手 | user |
| `/admin/kb` | 知识库管理 | admin |
| `/admin/eval` | RAGAS 评测审计 | qa |

## 10. 数据库表扩展摘要

| 表名 | 核心字段 | 说明 |
| --- | --- | --- |
| `users` | id, username, password_hash, role, created_at, updated_at | 用户账号 |
| `kb_directories` | id, name, parent_id, path, created_at, updated_at | 知识库目录 |
| `kb_files` | id, directory_id, filename, source_type, file_path, file_size, updated_at, created_at | 知识库文件 |
| `system_settings` | id, key, value, updated_at | 运行期配置 |

## 11. 待后端确认事项

1. `GET /admin/dashboard` 中的"今日会话数"是否需要给 `conversations` 表增加 `user_id` 字段？当前 schema 未关联用户。
2. `system_settings` 更新后是立即全局生效还是需要重启？建议立即生效。
3. 上传文件大小限制建议为 10MB。
4. JWT token 有效期建议为 24 小时，MVP 阶段暂不做 refresh token。

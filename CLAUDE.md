# CLAUDE.md

> **重要**: 硬约束与项目事实以 `AGENTS.md` 为准。本文件仅包含 Claude Code 专用的交互偏好与协作规范。

---

## 1. 项目概述

NDR (Node-Document-Relations) 是一个通用的节点-文档-关系存储微服务，提供 RESTful API 用于管理层级化的节点树和文档。

**技术栈**: FastAPI + PostgreSQL + SQLAlchemy + Alembic

**默认端口**: 9000

---

## 2. 开发命令

```bash
# 快速启动（含数据库）
make run

# 运行测试
make test

# 代码检查
make lint

# 数据库迁移
make migration MSG="描述"
make upgrade
```

---

## 3. Claude-Codex 协作规范

Codex 是可选的协作伙伴，**仅在用户明确要求时调用**。

### 3.1 调用时机

**仅在以下情况调用 Codex**：
- 用户明确要求（如"让 Codex 审查"、"问一下 Codex"）
- 用户同意进入协作模式

**不要主动调用 Codex**，除非用户授权。

### 3.2 协作流程

1. **需求分析阶段**: 将需求和初步思路告知 Codex，要求完善分析
2. **编码实施阶段**: 向 Codex 索要代码原型（unified diff patch）
3. **代码审查阶段**: 使用 Codex review 代码改动

### 3.3 独立思考原则

- Codex 只能给出参考，**必须有自己的思考**
- 对 Codex 的回答**提出质疑**
- 最终目标是与 Codex **达成统一、全面、精准的意见**

---

## 4. Codex MCP 工具调用规范

**必选参数**：
- `PROMPT` (string): 发送给 Codex 的任务指令
- `cd` (Path): 项目根路径 `/home/pi/codes/ndr`

**调用规范**：
- 使用 `sandbox="read-only"` 确保安全
- 要求 Codex 仅给出 unified diff patch
- 保存返回的 `SESSION_ID` 用于多轮对话

---

## 5. 引用文档

- **硬约束与项目规范**: `AGENTS.md`
- **API 文档**: 启动服务后访问 `http://localhost:9000/docs`

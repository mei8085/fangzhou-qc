# 仓库说明（Codex / 通用 Agent 入口）

方舟 coding 众测质检工作仓库。

- 评测规范原文：[spec/方舟coding众测质检流程及规范.md](spec/方舟coding众测质检流程及规范.md)
- **工作流唯一权威**：[skills/qc-eval/SKILL.md](skills/qc-eval/SKILL.md)
- 单题工作目录：`tasks/<TASK_ID>/`
- 交付目录：`delivery/<TASK_ID>/`（含单任务 xlsx + 复测截图）

> 任何质检相关动作（取题、拉附件、登录平台、起 dev server、截图、写交付物）必须按 `skills/qc-eval/SKILL.md` 执行，不要绕过其中的脚本直接调底层 API 或 lark-cli。

## 配置依赖

- 数据源：47期从本地 `docs/47.xlsx` 按任务ID读取；交付回写飞书 `sheet=O8b911`。具体流程以 `skills/qc-eval/SKILL.md` 为准
- Python 依赖清单：`skills/qc-eval/requirements.txt`。每个新工程目录先执行 `python3 skills/qc-eval/scripts/bootstrap_qc_env.py`，它会创建或更新项目级 `.venv` 并安装 Pillow、openpyxl、cryptography、zstandard 及 Windows Cookie 解密依赖；后续 Python 命令使用 `.venv/bin/python`（Windows 为 `.venv\\Scripts\\python.exe`），不要依赖全局 Python
- Node.js + Playwright：在 `skills/qc-eval/` 内 `npm install` + 一次 `node node_modules/playwright/cli.js install chromium`
- Ark 平台登录态：`node skills/qc-eval/scripts/fetch_g1_platform.js auth-from-chrome` 只从人工提前登录成功的 Chrome `quan-134` 个人资料（磁盘目录 `Profile 4`）导出到 `skills/qc-eval/.ark_platform_state.json`（gitignored）；导出或校验失败时必须停止并提醒人工在该 Profile 登录后重试，禁止启动新浏览器，也不得复用旧状态掩盖当前 Profile 失败

## 多 CLI 兼容

本仓库同时面向 Claude Code、Codex、Cursor。三者各自的入口文件（`CLAUDE.md` / `AGENTS.md` / `.cursor/rules/qc-eval.mdc`）只做指引，所有流程逻辑都在 `skills/qc-eval/SKILL.md`，避免漂移。

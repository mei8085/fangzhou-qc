# 仓库说明（Codex / 通用 Agent 入口）

方舟 coding 众测质检工作仓库。

- 评测规范原文：[spec/方舟coding众测质检流程及规范.md](spec/方舟coding众测质检流程及规范.md)
- **工作流唯一权威**：[skills/qc-eval/SKILL.md](skills/qc-eval/SKILL.md)
- 单题工作目录：`tasks/<TASK_ID>/`
- 交付目录：`delivery/<TASK_ID>/`（含单任务 xlsx + 复测截图）

> 任何质检相关动作（取题、拉附件、登录平台、起 dev server、截图、写交付物）必须按 `skills/qc-eval/SKILL.md` 执行，不要绕过其中的脚本直接调底层 API 或 lark-cli。

## 配置依赖

- 数据源：38 期从飞书正式表 `sheet=uBlwx4` 同步到本地 xlsx（默认 `D:/fz/fangzhou/众测质检38.xlsx`），具体流程以 `skills/qc-eval/SKILL.md` 为准
- Python 3 + Pillow + openpyxl：`pip3 install Pillow openpyxl`
- Node.js + Playwright：在 `skills/qc-eval/` 内 `npm install` + 一次 `node node_modules/playwright/cli.js install chromium`
- Ark 平台登录态：通过 `node skills/qc-eval/scripts/fetch_38_platform.js auth-from-chrome` 导出到 `skills/qc-eval/.ark_platform_state.json`（gitignored）

## 多 CLI 兼容

本仓库同时面向 Claude Code、Codex、Cursor。三者各自的入口文件（`CLAUDE.md` / `AGENTS.md` / `.cursor/rules/qc-eval.mdc`）只做指引，所有流程逻辑都在 `skills/qc-eval/SKILL.md`，避免漂移。

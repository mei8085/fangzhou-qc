---
name: qc-eval
description: >-
  G1-new Fangzhou coding crowdtest QC workflow. Use when the user asks to
  质检, review a 任务ID, collect Ark platform runs from project 277, write
  qc_cells.json, generate delivery xlsx, selfcheck, fill the Ark QC form
  as a draft, or push to Feishu sheet=cHr9N5. Canonical instructions live
  in skills/qc-eval/SKILL.md; this
  file is the Cursor project-skill entry only.
---

# qc-eval（Cursor 入口）

开始任何质检工作前，必须先完整阅读并严格遵循：

- `skills/qc-eval/SKILL.md`

不要绕过 `skills/qc-eval/scripts/` 中的脚本直接调平台 API、lark-cli 或用 openpyxl 写盘。

质量备注和审核理由必须写清本条反馈质量为什么是高质量 / 合格 / 不合格；细则见权威 SKILL「写作约束」。

跨平台约定写在权威 SKILL 的「运行环境」一节：源表默认 `docs/G1-new.xlsx`，Python 用 `python3`，Ark 登录可用 `auth-from-chrome` 或 `auth-login`。复测是本机起服务还是 SSH 到 `u03l` 用 Docker，以权威 SKILL 的「复测启动与截图」为准。

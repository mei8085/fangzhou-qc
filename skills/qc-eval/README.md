# qc-eval

方舟 coding 众测质检工作流。**所有说明在 [SKILL.md](SKILL.md)，不要在此 README 中写流程**。

## 快速命令

```bash
# 一次性
cd skills/qc-eval && npm install && npx playwright install chromium

# 每题
python3 skills/qc-eval/scripts/fetch.py        <TASK_ID>
node    skills/qc-eval/scripts/screenshot.js   tasks/<TASK_ID>
python3 skills/qc-eval/scripts/compose.py      tasks/<TASK_ID>
# ↓ 智能体先把结论写到 tasks/<TASK_ID>/qc_cells.json
python3 skills/qc-eval/scripts/push_text.py    <TASK_ID>
python3 skills/qc-eval/scripts/push_images.py  <TASK_ID>
python3 skills/qc-eval/scripts/verify.py       <TASK_ID>
```

## 目录

```
skills/qc-eval/
├── SKILL.md          ← 主文档
├── README.md         ← 速查
├── package.json      ← Playwright 依赖
└── scripts/
    ├── lib/          ← 共享：feishu / sheet_layout / eval_html
    ├── fetch.py
    ├── screenshot.js
    ├── compose.py
    ├── push_text.py
    ├── push_images.py
    └── verify.py
```

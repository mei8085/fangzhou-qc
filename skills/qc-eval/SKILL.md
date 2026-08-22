---
name: qc-eval
description: 38 期方舟 coding 众测质检工作流。默认从飞书 sheet=uBlwx4 同步到仓库 data/众测质检38.xlsx（Windows 若仍存在 D:/fz/fangzhou/众测质检38.xlsx 则继续用它），按 38 期规则评出题质量与反馈质量，使用 fetch_38_platform.js 采集 Ark 平台 4 个模型运行、Workspace、Session 轨迹、评测打分与审核信息，输出 delivery/<TASK_ID>/，并通过 push_38_feishu.py 或 push_feishu.py 显式回写 38 期飞书表。适用于 Cursor、Claude Code、Codex，以及 Windows / macOS / Linux。
---

# 方舟 coding 众测质检 - 38 期工作流技能

唯一权威说明文件。`CLAUDE.md`、`AGENTS.md`、`.cursor/rules/qc-eval.mdc`、`.cursor/skills/qc-eval/SKILL.md` 只做入口指引，不复制流程。

配套规范：

- 新规则整理：`spec/36期质检新规则.md`（38 期继续沿用这套质量口径）
- 脏数据标签与标准：`spec/Coding场景脏数据标签与标准.md`（平台反馈质检的脏数据标签按此执行）
- 兼容入口：`spec/方舟coding众测质检流程及规范.md` 已更新为同一套质量规则

## 38 期默认配置

- 飞书源表：`https://bytedance.larkoffice.com/wiki/OY1Dw0dcailCxTk3UGOcykVznAf?sheet=uBlwx4`
- sheet_id：`uBlwx4`
- 默认表名：`38期coding质检`
- 本地源表：仓库内 `data/众测质检38.xlsx`（`data/` 已 gitignore）。若本机仍存在 Windows 旧路径 `D:/fz/fangzhou/众测质检38.xlsx`，脚本会优先使用它。可用环境变量 `QC_SOURCE_XLSX` 或 `--out` / `--source` 覆盖。
- 本地任务目录名：必须使用源表 `任务ID`，例如 `任务ID` 列里的真实 ID；不再使用行号编号
- Ark 平台项目：`https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/projects/256?tab=review`
- Ark 平台采集脚本：`node skills/qc-eval/scripts/fetch_38_platform.js`
- 飞书同步脚本：`python3 skills/qc-eval/scripts/sync_source_from_feishu.py` 或 `python3 skills/qc-eval/scripts/sync_38_source_from_feishu.py`
- 交付 xlsx：`python3 skills/qc-eval/scripts/push_xlsx.py <任务ID> --period 38期`
- 飞书回写：默认只允许执行 `python3 skills/qc-eval/scripts/push_38_feishu.py <任务ID> --dry-run` 预检；只有用户明确指令“上传/回写/写入飞书”后，才允许执行带 `--write` 的命令。

## 运行环境

同时支持 Cursor、Claude Code、Codex；操作系统为 Windows（含 Git Bash）、macOS、Linux。

- Python 3：下列命令写 `python3`。Windows 若只有 `python`，把命令中的 `python3` 换成 `python`。也可用 `QC_PYTHON` 指定解释器。
- 源表路径不要写死盘符。默认见上文「本地源表」；Cursor / macOS 不要再假定 `D:/fz/fangzhou/` 存在。
- Ark 登录态：`auth-from-chrome` 会从本机 Chrome 导出 volcengine cookie（Windows 用 VSS，macOS 用 Keychain，Linux 用 libsecret）。导出失败时自动打开有头浏览器，改为 `auth-login`。也可直接跑 `node skills/qc-eval/scripts/fetch_38_platform.js auth-login`。
- Cursor 跑 Playwright / 有头登录 / 平台采集时需要本机网络，并批准相应权限；有头登录会弹出 Chrome/Chromium 窗口，需人工完成登录。
- `lark-cli` 必须在 PATH 中（macOS/Linux 为 `lark-cli`，Windows 可为 `lark-cli.exe`）。

## 新规则口径

38 期以用户提供的新规则为准，不沿用旧期数历史口径。

### 出题质量

一句话：高经济价值且高评测价值的完整任务。

重点看三类指标：

- 完整性：题目目标、输入输出、约束、术语和上下文清楚；rubric 和交付要求完整；Coding Agent 必须提交 workspace，代码仓库至少 1k+ 行代码（暂定）。
- 经济价值：来源真实，来自真实业务场景、工单或客户需求；Coding Agent 公司项目要和公司方向匹配，个人项目需达到上线标准，学校项目仅接受研究生及以上科研项目。
- 评测价值：正确与错误有客观证据，得分点可稳定判定；区分度参考标准差 > 1.5 且最低分 < 9 分；复杂度指标只作参考，Coding Agent 参考模型平均工具轮次 > 450。

### 反馈质量

一句话：清晰、可复现的任务反馈和模型洞察。

重点看四类指标：

- 反馈数据完整：有清晰产物截图或链接、完整任务描述、模型输出结果、关键过程信息和必要上下文材料。
- 可复现：有明确操作步骤、输入数据或链接、期望结果和实际结果，不能只写“效果不好”“不符合预期”。
- 模型行为洞察深度：能指出具体能力短板，能归因到模型行为，能区分不同模型或框架表现差异。
- 真实业务影响：说明问题是否影响真实用户完成任务，以及是否影响效率、质量、成本、合规或业务结果。

### 反馈质量评级

| 评级 | 判定 |
| --- | --- |
| 高质量 | 打分准确，备注规范，佐证充分，与实际完全一致。 |
| 合格 | 打分大体合理但存在部分偏差或不完善；或打分、备注、佐证有明显问题但未触发红线。 |
| 不合格 | 反馈完全不可信，或触发红线规则。 |

38 期飞书列“反馈质量（作业质量）”下拉只有 `高质量`、`合格`、`不合格` 三个选项，禁止写 `红线`。若模型反馈触发反馈质量红线或脏数据标签，该模型“反馈质量（作业质量）”填 `不合格`；具体红线类型写到“红线问题”列，逐模型平台质检里的“脏数据标签”写对应标签，例如 `trace和反馈结果明显不一致`。

红线仍需明确证据。截图中明确可见的出题质量红线补充包括：从 Openbenchmark 上找题、用网页生成 PPT 或旅游攻略等静态展示性页面。

### 脏数据标签与标准

平台反馈质检的脏数据标签以 `spec/Coding场景脏数据标签与标准.md` 为准。判断时先区分粒度：

- L1 单条运行记录（模型 × 任务）：判断反馈质量、平台 & 模型表现、Harness 表现。
- L2 单任务（同任务多模型）：判断题目质量、L2 粒度反馈质量。

组合规则：

- L1 粒度要打的脏数据标签：反馈质量脏数据标签 + 平台 & 模型表现 + Harness 表现。
- L2 粒度要打的脏数据标签：题目质量脏数据标签 + L2 粒度的反馈质量脏数据标签。

常用标签口径：

- `API 请求超时 / 轨迹大量 error`：`status_code != 200` 且用户理由提卡、超时、掉线或请求失败，且效率维度低分；或结构化字段 `ttft / tpot / input_tokens / output_tokens` 为 `null`。`status_code = 200` 的红色非流式输出不算异常；不把 message 文本或 tool result 当 API 异常证据。
- `OpenClaw / Hermes 框架问题`：trace 有完整交付但用户前端没收到，或用户连续多条 user message 无对应 assistant 回复与工具调用；必须同时有用户侧证据和轨迹侧证据。模型自身死循环或工具调用失败后无法恢复属于模型能力问题，不打此标签。
- `用户切换模型错误`：模型自称身份与接入点不一致，且前段轨迹与其他模型雷同，能指向未清 workspace 或未 `/new` 的模型切换污染。
- `AI 打分 / AI 评价`：反馈有 AI 打分口癖，或轨迹含模型自评、prompt 内置打分指令、产物里有 AI 打分文件。
- `敷衍恶意打分`：打分理由为空或极短、标准前后不一、不同板块结论相悖、非关联维度连带扣分、评分与实际产物明显不符；L2 还包括多模型理由高度雷同、未测完全部模型就提交、各模型分数一致但实际差异明显。
- `题目红线（prompt 简单 / VLM 错配）`：prompt 过于简单或模糊、纯题库题、VLM 错配、纯生图任务、全部模型工具调用轮次 < 10、同任务给各模型 prompt 不一致；补充红线包括毫无意义题目、非代码题、题目不合理、非本人场景、静态展示性页面。
- `低质量任务` 是任务质量问题，但不是脏数据标签；例如 4 模型综合分差 <= 1 且均分 >= 9，或低价值任务。

## 标准流程

1. 同步 38 期源表。

```bash
python3 skills/qc-eval/scripts/sync_source_from_feishu.py
```

2. 确认源表 `任务ID` 列有值，并使用该 `任务ID` 作为 `tasks/` 和 `delivery/` 的子目录名；禁止使用行号作为本地工作编号。

```bash
python3 skills/qc-eval/scripts/probe_38_task_ids.py --task-title "<任务名>"
```

3. 首次使用 Ark 平台前导出登录态。

```bash
node skills/qc-eval/scripts/fetch_38_platform.js auth-from-chrome
# cookie 导出失败时（常见于 macOS Chrome v20 / Cursor）改为人工登录：
node skills/qc-eval/scripts/fetch_38_platform.js auth-login
```

4. 采集 Ark 平台材料。必须传 `--sheet-task-id <任务ID>`，让平台材料落到源表 `任务ID` 对应的本地目录。

```bash
node skills/qc-eval/scripts/fetch_38_platform.js collect --project 256 --task-title "<任务名>" --sheet-task-id <任务ID>
# 或
node skills/qc-eval/scripts/fetch_38_platform.js collect --project 256 --task-id <平台任务ID> --sheet-task-id <任务ID>
```

脚本会保存模型运行列表、任务详情、评测详情、Workspace Browser、Workspace zip、ByteHouse Session 列表与 Session 轨迹。输出目录为 `tasks/<任务ID>/ark38/`。

5. 人工质检并写 `tasks/<任务ID>/qc_cells.json`。

推荐结构：

```json
{
  "task_id": "<任务ID>",
  "task_title": "源表里的完整任务名",
  "sheet": {
    "reviewer": "质检人",
    "supplier": "所属商",
    "is_high_quality_task": "否",
    "is_normal_task": "是",
    "prompt_quality": "高质量",
    "prompt_quality_note": "按 38 期出题质量规则说明完整性、经济价值、评测价值。",
    "verifiable": "是",
    "verifiable_reason": "",
    "category_correct": "是",
    "redline_issue": "",
    "models": {
      "<表头模型名>": {
        "rating": "高质量",
        "screenshot": "",
        "note": "按 38 期反馈质量规则说明标注人打分、备注、证据、trace 与实际产物是否一致。"
      }
    }
  }
}
```

表头若仍保留旧下拉值，交付脚本按表头写入；人工判断语言和备注依据必须按 38 期规则。

`sheet.models.<模型>.rating` 对应飞书列“反馈质量（作业质量）”，只能填 `高质量`、`合格`、`不合格`。触发反馈红线时也填 `不合格`，不要填 `红线`；红线原因在 `redline_issue` 和逐模型 `dirty_tag` 中体现。

`is_high_quality_task` 对应飞书列“是否是高质量题目”，必须填“是/否”；该字段按模型反馈质量的整体情况判断，不按题目本身经济价值或评测价值判断。通常只有所有模型反馈质量均为“高质量”时填“是”；任一模型反馈质量为“合格”或“不合格”时填“否”。若未写，交付脚本会按 `sheet.models` 中 4 个模型反馈质量自动推导，无法推导时保持空白并由自检拦截。

`prompt_quality` 对应飞书列“任务质量（题目质量）”，按题目本身的完整性、经济价值、评测价值和可验证性判断；它可以与“是否是高质量题目”不一致，例如题目本身为“高质量”，但模型反馈整体未达到高质量时，“是否是高质量题目”填“否”。

`is_normal_task` 对应飞书列“是否正常题目”，必须填“是/否”；若未写，交付脚本默认写“是”，仅在存在明确红线问题或题目质量为“红线/不可用”时自动写“否”。

`category_correct` 对应飞书列“分类是否正确”，必须填“是/否”；判断源表 `label` 是否与任务真实类型一致，例如 Coding Agent 功能开发、迁移、Bug fix 等分类与题目目标匹配则填“是”。

6. 生成本地交付物，并生成每个模型对应的平台质检填写文件。

```bash
python3 skills/qc-eval/scripts/push_xlsx.py <任务ID> --period 38期
python3 skills/qc-eval/scripts/selfcheck.py <任务ID>
python3 skills/qc-eval/scripts/generate_model_qc_platform.py <任务ID>
```

逐模型平台填写文件输出为 `delivery/<TASK_ID>/<TASK_ID>_model_qc_platform.md`，用于 Ark 质检页面逐模型复制填写；包含任务质量、任务质量备注、标注人反馈质量、反馈质量备注、审核理由和脏数据标签。反馈质量备注保留完整复核证据；审核理由按平台输入框示例写简洁事实结论，必须包含从反馈质量备注中抽出的具体问题点，并覆盖响应是否符合任务要求、输出代码或产物是否可复核、标注人反馈与复核结果是否一致、是否触发红线或脏数据标签，不复制完整备注。需要特殊说明时，可在模型数据下写 `platform_audit_reason` 或 `audit_reason` 覆盖默认审核理由。脏数据标签按 `spec/Coding场景脏数据标签与标准.md` 判断；可在每个模型数据下写 `dirty_tag`，或在 `qc_cells.json` 的 `platform_qc.dirty_tag` 下按模型名填写。未写时，脚本默认输出“非脏数据”。

7. 回写飞书必须听用户指令：常规质检流程到 dry-run 为止，不得主动上传或回写飞书。只有用户明确要求“上传/回写/写入飞书”后，才执行 write；执行顺序仍必须先 dry-run，再 write。

```bash
python3 skills/qc-eval/scripts/push_38_feishu.py <任务ID> --dry-run
python3 skills/qc-eval/scripts/push_38_feishu.py <任务ID> --write --confirm-user-instructed
```

`push_38_feishu.py` 会重新读取远端 `uBlwx4` 对应行的“任务”单元格，并与本地交付 xlsx 的任务名完全一致才允许写入。

## 写作约束

- 备注以人工质检员口吻写，不暴露脚本化过程。
- 不使用第一人称主语，如“我跑了”“我本地”。
- 不写工程内部路径或字段名到交付备注里，如 `qc_cells.json`、`SKILL.md`。
- 题目质量说明只解释题目本身的完整性、经济价值、评测价值、可复核性和未达高质量的原因；不要写“是否是高质量题目填是/否”这类表字段自述，也不要写平台页面没有展示的“4 个模型总分”。
- 红线必须有明确证据；只有疑似、可能、看起来像时，不判红线。
- 质量备注建议按“标注人给执行过程 X 分、执行产物 Y 分”组织；如果页面只有总分，就写“标注人给 X 分”。后面再补一句证据是否支撑结论，避免只写“方向基本准确”这类模糊表述。
- 反馈质量备注要围绕标注人的打分、备注、截图或材料、trace 与模型实际产物是否一致来写。
- 平台审核理由要按页面示例写短事实结论，并写出一个具体问题点，例如“采购记录刷新后丢失”“页面缺少采购执行模块”“构建失败但标注给满分”；不能只写“存在偏差”“证据不完整”这类空泛结论。不要复制反馈质量备注全文，也不要写“任务质量判定为高”。
- 38 期高质量反馈要求必须体现在备注里：数据是否完整、能否复现、是否有模型行为洞察、是否说明真实业务影响。
- 避免 AI 腔或模板感短评，如“偏薄”“兜底”“更稳”“方向到位”“抓得准”；改写成具体可核验的问题，例如“没有给出具体操作步骤和业务影响，支撑满分的证据还不够充分”。

## 关键约束

1. 质检相关动作只走本技能列出的集中脚本，不直接调底层 API 或 lark-cli。
2. 本仓库默认且唯一飞书目标为 `sheet=uBlwx4`。
3. 自动流程只生成本地文件；飞书回写只能在用户明确下达上传/回写指令后，通过显式 push 命令执行。用户只说“质检 <任务ID>”时，不得执行 `--write`。
4. 截图必须是本人复测证据，不能复用标注人的截图；`delivery/<TASK_ID>/screenshots/` 只保留有效截图 PNG（如 `<模型>_01_cli.png`）和合成图 PNG（`<模型>_verify.png`），不要保留 `log.txt`、临时图、别名图或其他辅助文件。合成图必须按左右横向拼接原图，禁止上下纵向拼接；若只有一张有效截图，则直接复用该原图作为 `<模型>_verify.png`。
5. `delivery/<TASK_ID>/<TASK_ID>.xlsx` 必须从空白 workbook 重建，只包含表头行和该任务行。
6. `.ark_platform_state.json`、本地探测缓存和登录态文件不能提交。

## 常用命令

```bash
python3 skills/qc-eval/scripts/sync_source_from_feishu.py
python3 skills/qc-eval/scripts/probe_38_task_ids.py --task-title "<任务名>"
node skills/qc-eval/scripts/fetch_38_platform.js auth-from-chrome
# 或：node skills/qc-eval/scripts/fetch_38_platform.js auth-login
node skills/qc-eval/scripts/fetch_38_platform.js collect --project 256 --task-title "<任务名>" --sheet-task-id <任务ID>
python3 skills/qc-eval/scripts/push_xlsx.py <任务ID> --period 38期
python3 skills/qc-eval/scripts/selfcheck.py <任务ID>
python3 skills/qc-eval/scripts/generate_model_qc_platform.py <任务ID>
python3 skills/qc-eval/scripts/push_38_feishu.py <任务ID> --dry-run
# 用户明确要求上传/回写飞书后才可执行：
python3 skills/qc-eval/scripts/push_38_feishu.py <任务ID> --write --confirm-user-instructed
```


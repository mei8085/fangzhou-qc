---
name: qc-eval
description: G1-new 方舟 coding 众测质检工作流。质检题目从本地 docs/G1-new.xlsx 按任务ID读取，不从飞书同步源表。标注与产物从 Ark 平台 project 277 按任务ID搜索后进入任务详情采集 5 个模型（S347/harrier、S20/grotto、S53/ferrite、S60/estuary、S1075/dendrite）的模型运行与下载列表。交付回写飞书 sheet=cHr9N5。适用于 Cursor、Claude Code、Codex，以及 Windows / macOS / Linux。
---

# 方舟 coding 众测质检 - G1-new 工作流技能

唯一权威说明文件。`CLAUDE.md`、`AGENTS.md`、`.cursor/rules/qc-eval.mdc`、`.cursor/skills/qc-eval/SKILL.md` 只做入口指引，不复制流程。

配套规范：

- 新规则整理：`spec/36期质检新规则.md`（G1-new 继续沿用这套质量口径）
- 脏数据标签与标准：`spec/Coding场景脏数据标签与标准.md`（平台反馈质检的脏数据标签按此执行）
- 兼容入口：`spec/方舟coding众测质检流程及规范.md` 已更新为同一套质量规则

## G1-new 默认配置

- 本地源表：`docs/G1-new.xlsx`（`docs/` 已 gitignore）。可用环境变量 `QC_SOURCE_XLSX` 或 `--source` 覆盖。
- 源表不从飞书同步。飞书只作为交付回写目标。
- 飞书交付表：`https://bytedance.larkoffice.com/wiki/OY1Dw0dcailCxTk3UGOcykVznAf?sheet=cHr9N5`
- sheet_id：`cHr9N5`
- 本地任务目录名：必须使用源表 `任务ID`，例如 `4267`
- Ark 平台项目：`https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/projects/277?tab=review`
- 任务详情：`https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/myprojects/277/task/<任务ID>`
- 平台检索：以任务ID搜索；任务详情页有「模型运行」和「下载列表」两个 tab。下载列表走 `CaseBffV1CrowdtestTaskModelWorkspaceDownloadLatestList`。
- 模型对应：

| 表头模型 | 代号 | 平台 codeName |
| --- | --- | --- |
| 【G1】S347 | S347 | harrier |
| 【G1】S20 | S20 | grotto |
| 【G1】S53 | S53 | ferrite |
| 【G1】S60 | S60 | estuary |
| 【G1】S1075 | S1075 | dendrite |

- 配置文件：`skills/qc-eval/config/g1.json`
- 平台质检表单模版：`skills/qc-eval/config/g1_audit_form.json`（从 [review/12232?mode=audit](https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/projects/277/review/12232?mode=audit) 读取）
- 质检后填写文件：`delivery/<TASK_ID>/<TASK_ID>_model_qc_platform.md` 与 `delivery/<TASK_ID>/<TASK_ID>_audit_form_fill.json`
- 平台质检表单回填（只保存草稿）：`node skills/qc-eval/scripts/fill_g1_audit_form.js --task-id <任务ID>`
- Ark 平台采集脚本：`node skills/qc-eval/scripts/fetch_g1_platform.js`
- 本地任务探测：`python3 skills/qc-eval/scripts/probe_g1_task_ids.py --task-id <任务ID>`
- 交付 xlsx：`python3 skills/qc-eval/scripts/push_xlsx.py <任务ID> --period G1-new`
- 飞书回写：默认只允许执行 `python3 skills/qc-eval/scripts/push_g1_feishu.py <任务ID> --dry-run` 预检；只有用户明确指令“上传/回写/写入飞书”后，才允许执行带 `--write` 的命令。

## 运行环境

同时支持 Cursor、Claude Code、Codex；操作系统为 Windows（含 Git Bash）、macOS、Linux。

- Python 3：下列命令写 `python3`。Windows 若只有 `python`，把命令中的 `python3` 换成 `python`。也可用 `QC_PYTHON` 指定解释器。
- 源表路径不要写死盘符。默认见上文「本地源表」。
- Ark 登录态：`auth-from-chrome` 会从本机 Chrome 导出 volcengine cookie（Windows 用 VSS，macOS 用 Keychain，Linux 用 libsecret）。导出失败时自动打开有头浏览器，改为 `auth-login`。也可直接跑 `node skills/qc-eval/scripts/fetch_g1_platform.js auth-login`。
- Cursor 跑 Playwright / 有头登录 / 平台采集时需要本机网络，并批准相应权限；有头登录会弹出 Chrome/Chromium 窗口，需人工完成登录。
- `lark-cli` 必须在 PATH 中（macOS/Linux 为 `lark-cli`，Windows 可为 `lark-cli.exe`）。
- 测试机 SSH 别名 `u03l`：只有题目依赖数据库、消息队列、Celery，或交付物自带 docker-compose 且本机不便跑时，才在这台机器上用 Docker 起基础设施。一次性准备见 `skills/qc-eval/remote/README.md`；何时用、用哪条脚本见下文「复测启动与截图」。

## 新规则口径

G1-new 以用户提供的新规则为准，不沿用更早期历史口径。质量判断仍按 `spec/36期质检新规则.md`。

### 出题质量

一句话：高经济价值且高评测价值的完整任务。

重点看三类指标：

- 完整性：题目目标、输入输出、约束、术语和上下文清楚；rubric 和交付要求完整；Coding Agent 必须提交 workspace，代码仓库至少 1k+ 行代码（暂定）。
- 经济价值：来源真实，来自真实业务场景、工单或客户需求；Coding Agent 公司项目要和公司方向匹配，个人项目需达到上线标准，学校项目仅接受研究生及以上科研项目。
- 评测价值：正确与错误有客观证据，得分点可稳定判定；区分度参考标准差 > 1.5 且最低分 < 9 分；复杂度指标只作参考，Coding Agent 参考模型平均工具轮次 > 450。**质检不负责统计轨迹轮次**（甲方自行分析轨迹）；质检只核对提示词有没有把轮次配额写给模型。

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

G1-new 飞书列“反馈质量（作业质量）”下拉只有 `高质量`、`合格`、`不合格` 三个选项，禁止写 `红线`。若模型反馈触发反馈质量红线或脏数据标签，该模型“反馈质量（作业质量）”填 `不合格`；题目红线写到“题目红线问题 / 题目红线备注”；逐模型飞书“脏数据标签”必须写成下拉原文，例如 `用户问题:敷衍恶意打分`。非脏数据时该列留空，不要填 `非脏数据`。

红线仍需明确证据。截图中明确可见的出题质量红线补充包括：从 Openbenchmark 上找题、用网页生成 PPT 或旅游攻略等静态展示性页面。提示词轮次作弊也按出题质量红线处理，见「提示词轮次作弊闸门」。

### 脏数据标签与标准

判断口径以 `spec/Coding场景脏数据标签与标准.md` 为准。写入飞书「【G1】Sxxx脏数据标签」时必须用下拉原文，不要改空格或中英文冒号：

- `模型资源问题:API请求超时/轨迹大量error`
- `OpenClaw/Hermes框架问题`
- `用户问题:低质量任务`
- `用户问题:敷衍恶意打分`
- `用户问题:AI打分/AI评价`
- `用户问题:用户切换模型错误`
- `用户问题:LLM任务测试VLM能力`
- `其他`

非脏数据：该列留空，不要填 `非脏数据`。`qc_cells.json` 里可写 `""` 或 `"非脏数据"`，`push_xlsx.py` 会写成空单元格。平台「质检」面板没有「非脏数据」按钮，不选标签即可。上传飞书时禁止把空字符串写入脏数据标签下拉格：飞书会把 `""` 当成不在选项里的值，显示「数据无效」。`push_g1_feishu.py` 对空的脏数据标签和空的脏数据标签理由走单元格内容清除（`+cells-clear --scope content`），效果与手动清除单元格相同，并保留下拉规则。

判断时先区分粒度：

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
- `题目红线（prompt 简单 / VLM 错配）`：prompt 过于简单或模糊、纯题库题、VLM 错配、纯生图任务、全部模型工具调用轮次 < 10、同任务给各模型 prompt 不一致；补充红线包括毫无意义题目、非代码题、题目不合理、非本人场景、静态展示性页面、**提示词轮次作弊**。
- `低质量任务`：飞书下拉选项是 `用户问题:低质量任务`。提示词轮次作弊时各模型打此标签。内部可用页面上的执行过程分、执行产物分判断是否整体偏高且分差很小；交付备注不要另写「综合评分 / 均分 / 总分」，页面评测打分没有这些聚合字段。

## 标准流程

1. 确认本地源表存在，并按任务ID定位题目。不要从飞书同步源表。

```bash
python3 skills/qc-eval/scripts/probe_g1_task_ids.py --task-id 4267
```

2. 使用该 `任务ID` 作为 `tasks/` 和 `delivery/` 的子目录名；禁止使用行号作为本地工作编号。同一任务ID也是 Ark 平台搜索关键字。

3. 首次使用 Ark 平台前导出登录态。

```bash
node skills/qc-eval/scripts/fetch_g1_platform.js auth-from-chrome
# cookie 导出失败时（常见于 macOS Chrome v20 / Cursor）改为人工登录：
node skills/qc-eval/scripts/fetch_g1_platform.js auth-login
```

4. 采集 Ark 平台材料。按任务ID搜索 project 277，进入任务详情。先拉任务提示词，再按「提示词轮次作弊闸门」决定要不要继续拉 Workspace 与轨迹。未作弊时采集 5 个模型的模型运行、评测、下载列表、Workspace 与轨迹。

```bash
node skills/qc-eval/scripts/fetch_g1_platform.js collect --task-id <任务ID>
```

脚本默认 `--project 277`，本地目录与平台搜索都用同一个任务ID。输出目录为 `tasks/<任务ID>/ark_g1/`，并写 `tasks/<任务ID>/model_map.json`。

采集在拿到 `task.json`（提示词）之后会立刻跑 `check_prompt_cheat.py --scan-only`。命中轮次作弊时**不再下载 workspace zip / 轨迹 / 下载列表**，也不要再去复测产物。

若 5 个平台 codeName 与 `harrier,grotto,ferrite,estuary,dendrite` 不一致，脚本会停住；只有确认可以部分采集时才加 `--allow-partial`。采集过程中若「下载列表」API 不一致，先停下来与人工核对，不要自行发明下载方式。

5. **提示词轮次作弊闸门（必须在复测产物之前）**。不要先测完五个模型产物再回头看提示词。

```bash
python3 skills/qc-eval/scripts/check_prompt_cheat.py <任务ID>
```

- 质检**不数**轨迹工具轮次。甲方会自行分析轨迹。
- 只核对提示词有没有要求模型把轮次/工具调用次数做到某个数量，例如「工具轮次达到 450」「至少调用工具 100 次」「不够就刷轮次」。
- **未命中**：继续下一步人工质检和产物复测。
- **命中**：题目质量填 `不合格`；`题目红线问题` 填 `题目不合理`；五个模型反馈质量一律 `不合格`；脏数据标签填 `用户问题:低质量任务`；验证截图全部用提示词截图，红色框选作弊语句。不要再起 dev server、不要再打开各模型产物。

```bash
python3 skills/qc-eval/scripts/check_prompt_cheat.py <任务ID> --apply
```

`--apply` 会写好 `qc_cells.json` 草稿并生成 `delivery/<任务ID>/screenshots/<模型>_01_prompt_cheat.png`。然后直接进入交付（`push_xlsx.py` / `generate_model_qc_platform.py` / `selfcheck.py`），跳过「复测启动与截图」。

6. 未命中轮次作弊时，才人工质检并写 `tasks/<TASK_ID>/qc_cells.json`。备注按下文「句式模版」三档短句写；对照最近一题开头，不要和上一题同一句首，也不要照抄参考表里的长句。

推荐结构：

```json
{
  "task_id": "<任务ID>",
  "task_title": "源表里的完整任务名",
  "sheet": {
    "reviewer": "质检人",
    "supplier": "所属商",
    "is_high_quality_task": "否",
    "prompt_quality": "高质量",
    "prompt_quality_note": "按出题质量规则说明完整性、经济价值、评测价值。",
    "verifiable": "是",
    "verifiable_reason": "",
    "category_correct": "是",
    "redline_issue": "",
    "redline_note": "",
    "models": {
      "【G1】S347": {
        "rating": "高质量",
        "note": "1～2 句。高质量：和产物实测情况一致，评分正确。合格：写清一致或不符合的点，并点名哪一项评分偏高或偏低。不合格：点名红线并按脏数据标签写一句。同一题可共用开头，连续几题换句首。",
        "platform_audit_reason": "一句收束：完全可用 / 部分可用 / 完全不可用。不要写高质量、合格、不合格。",
        "dirty_tag": "",
        "dirty_tag_reason": ""
      }
    }
  }
}
```

`sheet.models` 的 key 必须是表头模型名：`【G1】S347`、`【G1】S20`、`【G1】S53`、`【G1】S60`、`【G1】S1075`。

`sheet.models.<模型>.rating` 对应飞书列“反馈质量（作业质量）”，只能填 `高质量`、`合格`、`不合格`。触发反馈红线时也填 `不合格`，不要填 `红线`；红线原因在 `redline_issue` / `redline_note` 和逐模型 `dirty_tag` 中体现。`dirty_tag` 非脏数据时留空；有标签时必须写成飞书下拉原文。

`is_high_quality_task` 对应飞书列“是否是高质量题目”，必须填“是/否”；该字段按模型反馈质量的整体情况判断，不按题目本身经济价值或评测价值判断。通常只有所有模型反馈质量均为“高质量”时填“是”；任一模型反馈质量为“合格”或“不合格”时填“否”。若未写，交付脚本会按 `sheet.models` 中 5 个模型反馈质量自动推导，无法推导时保持空白并由自检拦截。

`prompt_quality` 对应飞书列“任务质量（题目质量）”，按题目本身的完整性、经济价值、评测价值和可验证性判断；它可以与“是否是高质量题目”不一致，例如题目本身为“高质量”，但模型反馈整体未达到高质量时，“是否是高质量题目”填“否”。命中提示词轮次作弊时 `prompt_quality` 填 `不合格`，`sheet.prompt_cheat` 填 `true`。

`category_correct` 对应飞书列“分类是否正确”，必须填“是/否”；判断源表 `label` 是否与任务真实类型一致。

写完 `qc_cells.json` 后，未命中提示词轮次作弊的题目必须按「复测启动与截图」本人现场出图，再进入下一步交付。不要复用标注人截图，也不要跳过复测直接 `push_xlsx.py`。命中轮次作弊时验证截图已由 `check_prompt_cheat.py` 用提示词红框生成，直接进入交付。

7. 生成本地交付物，并生成每个模型对应的平台质检填写文件。

```bash
python3 skills/qc-eval/scripts/push_xlsx.py <任务ID> --period G1-new
python3 skills/qc-eval/scripts/generate_model_qc_platform.py <任务ID>
python3 skills/qc-eval/scripts/selfcheck.py <任务ID>
```

逐模型平台填写文件输出为 `delivery/<TASK_ID>/<TASK_ID>_model_qc_platform.md` 和 `delivery/<TASK_ID>/<TASK_ID>_audit_form_fill.json`，字段名、选项与 `skills/qc-eval/config/g1_audit_form.json` 一致。用户明确要求填写平台质检表单时，用 `fill_g1_audit_form.js` 写入网页并只保存草稿；未下达该指令时不要打开审核页去改表单。表单字段为：请选择该任务的质量（高/中/低/不可用）、任务质量备注、请选择该用户的反馈质量（完全可用/部分可用/完全不可用）、反馈质量备注、审核理由、请选择脏数据标签。页面没有「非脏数据」按钮，不选标签即非脏数据。反馈质量备注按档位写 1～2 句，并用飞书档位词（高质量 / 合格 / 不合格）收束；审核理由写一句事实结论，必须用平台选项词（完全可用 / 部分可用 / 完全不可用）收束，禁止写「故高质量」「故合格」「反馈质量为高质量」。审核理由抽出备注里的具体问题点即可，不复制完整备注。需要特殊说明时，可在模型数据下写 `platform_audit_reason` 或 `audit_reason` 覆盖默认审核理由。脏数据标签按 `spec/Coding场景脏数据标签与标准.md` 判断后映射到页面选项；可在每个模型数据下写 `dirty_tag`。未写时填写文件输出「不选」。

8. 填写平台质检表单必须听用户指令。用户明确要求“填写平台质检表单 / 保存草稿 / 写入网页质检”后，才把 `delivery/<TASK_ID>/<TASK_ID>_audit_form_fill.json` 填进 `projects/277/review/<taskModelRunId>?mode=audit` 右侧「质检」面板。脚本只改质检表单，并只点「保存草稿」。禁止点「提交审核」「打回」「返回列表」，禁止改「评测打分」、Session 轨迹、Workspace 或附件。提交必须留给人工检查后再点。

```bash
node skills/qc-eval/scripts/fill_g1_audit_form.js --task-id <任务ID>
# 只填一个模型、或先看填入结果不点保存：
# node skills/qc-eval/scripts/fill_g1_audit_form.js --task-id <任务ID> --only harrier
# node skills/qc-eval/scripts/fill_g1_audit_form.js --task-id <任务ID> --dry-run
```

9. 回写飞书必须听用户指令：常规质检流程到 dry-run 为止，不得主动上传或回写飞书。只有用户明确要求“上传/回写/写入飞书”后，才执行 write；执行顺序仍必须先 dry-run，再 write。

```bash
python3 skills/qc-eval/scripts/push_g1_feishu.py <任务ID> --dry-run
python3 skills/qc-eval/scripts/push_g1_feishu.py <任务ID> --write --confirm-user-instructed
```

`push_g1_feishu.py` 会重新读取远端 `cHr9N5` 对应行的“任务”单元格，并与本地交付 xlsx 的任务名完全一致才允许写入。飞书列“一次质检平台审核理由（按模型）”按模型分行，前缀为表头模型名加平台 codeName，例如 `【G1】S347（harrier）：……`。非脏数据时不要给「脏数据标签」写入空字符串；脚本会清除单元格内容。已出现「数据无效」的空下拉格，重新 `--write` 即可按同样方式清掉。

## 复测启动与截图

现场复测默认在本机起服务。不要因为仓库里有 `u03l.py` 就把每题都推到测试机。命中提示词轮次作弊时不要走下面任何产物启动路径。

### 决策

按产物形态选脚本：

| 产物形态 | 在哪启动 | 脚本 |
| --- | --- | --- |
| 提示词轮次作弊 | 不测产物 | `python3 skills/qc-eval/scripts/check_prompt_cheat.py <任务ID> --apply`。五个模型共用提示词截图，红框标出配额语句 |
| Vue / Vite 前端，无强制后端栈 | 本机 dev server | `node skills/qc-eval/scripts/screenshot_vue.js <任务ID>`，再 `python3 skills/qc-eval/scripts/compose.py <任务ID>` |
| CLI / 测试报告 | 本机 | `python3 skills/qc-eval/scripts/compose_cli.py <任务ID>` |
| FastAPI + Vite，且依赖 Postgres / Redis / Celery | **u03l Docker** 起 PG/Redis/Celery；本机起 uvicorn + vite，经 SSH 隧道连接 | 手写 `tasks/<TASK_ID>/verify_routes.json`，`sheet.verifiable` 填 `是`，再 `python3 skills/qc-eval/scripts/verify_fullstack.py <任务ID>` |
| ASP.NET + docker-compose | **全部 Docker 命令在 u03l** | `node skills/qc-eval/scripts/screenshot_dotnet_u03l.js <任务ID>` |
| 必须在 Linux 上跑的 Vue CLI（如 ELADMIN） | u03l 上 npm / vue-cli-service | `python3 skills/qc-eval/scripts/verify_eladmin_frontend_u03l.py <任务ID>` |
| 起不来，或标成不可验证 | 本机静态走读 | `python3 skills/qc-eval/scripts/screenshot_static_walkthrough.py <任务ID>`；`verifiable` 填 `否` 并写原因 |

`verify_fullstack.py` 只看文件是否存在，不看期数。同时满足下面两条才启动全栈验证：

1. `qc_cells.json` 里 `sheet.verifiable` 为 `是`
2. 已手写 `tasks/<TASK_ID>/verify_routes.json`

缺路由文件时不要编造全栈验证，改走上表对应的本机截图路径。`verify_routes.json` 的格式见 `screenshot_fullstack_verify.js` 文件头。

### u03l 约束

- 先 `python3 skills/qc-eval/scripts/u03l.py check-host`。不可达则停，开机后再跑；禁止降级成 mock 服务后仍把 `verifiable` 写成 `是`。
- 标准全栈栈里，Docker 在 u03l 上只起 postgres / redis / celery；uvicorn 和 vite 仍在本机。
- 题目文案提到 postgres / redis / mysql / docker / celery 等服务栈，却要把 `verifiable` 标成 `否` 时，`verifiable_reason` 必须写明为何没法在 u03l / 工作机 Docker 上复测。`evidence_guard.py` 会拦截含糊理由。
- 测完执行 `python3 skills/qc-eval/scripts/u03l.py down <任务ID>`，需要时再 `python3 skills/qc-eval/scripts/tunnel.py close <任务ID>`，不要留残余容器或 SSH 隧道。

### 截图合格线

跑不通不要交白屏。换成报错终端、浏览器 console 或出错源码截图。`delivery/<TASK_ID>/screenshots/` 只留有效 PNG 和横向拼接的 `<模型>_verify.png`。`blank_guard.py` / `evidence_guard.py` / `screenshot_style_guard.py` 命中即不合格。

CLI / 测试 / 终端证据必须用等宽字体 `MONO_FONT_CANDIDATES`（macOS Menlo，Windows Consolas，Linux DejaVu Sans Mono）。禁止用冬青黑体、苹方等比例中文字体画终端图，数字 `4` 横画会发虚。`compose_cli.py` 的 `render_text_png` / `render_extra_command_png` 已按此出图；含中文说明的静态走读才用 CJK 字体。

质量备注里凡是写「与实际情况不符」「产物备注未记录」等与标注不一致的点，该模型验证截图必须能直接看出该事实。看不出来就补测补图，不要只靠文字。测试失败未写入标注备注时，补 `<模型>_NN_test.png`。CLI 主图看不出该事实时，不要无筛选地重跑 `compose_cli.py`（会覆盖各模型 `_01_cli.png`）。用 `compose_cli.render_extra_command_png` 补编号图，再 `python3 skills/qc-eval/scripts/compose.py <任务ID>`。`evidence_guard.py` 在备注同时写测试失败和与标注不一致时，会要求文件名含 `test` 的编号 PNG。

## 写作约束

- 备注以人工质检员口吻写，不暴露脚本化过程。
- 不使用第一人称主语，如“我跑了”“我本地”。
- 不写工程内部路径或字段名到交付备注里，如 `qc_cells.json`、`SKILL.md`。
- 题目质量说明只解释题目本身的完整性、经济价值、评测价值、可复核性和未达高质量的原因；不要写“是否是高质量题目填是/否”这类表字段自述。
- 红线必须有明确证据；只有疑似、可能、看起来像时，不判红线。
- 交付备注只写平台页面上能看见的内容。G1「评测打分」可见字段是执行过程分、执行产物分、归因标签、维度备注、产出物反馈。evaluation.json / API 里即使有综合评分、总分、均分、加权分、综合分差、dimension id、字段英文名，也不要写进质量备注、题目质量说明或审核理由。
- 质量备注写 **1～2 句**，不要写成复核说明书。必须写出页面上的过程分 / 产物分（轮次作弊除外）。同一题 5 个模型可以共用同一开头；**连续几题不要沿用同一句首**（`selfcheck.py` 对照最近 3 题）。没有过程/产物分时，不要用 API 里的聚合分顶替。产物起句不要只扔命令名或字段名，同一句里写清是缺陷还是正常。
- 反馈质量备注评的是**标注人作业**，不是给模型写产品说明。按下面三档写短句，不要为凑三拍或四条高质量指标把备注拉长。不要写「标注指出」「标注写：」冒号短句，改用「标注人备注」。不要写「标注轨迹」。**转述标注人意思时不要加引号**（包括 “” 和 「」）；只有逐字引用原句才用引号。`selfcheck.py` 命中弯引号即不合格。命中提示词轮次作弊时，各模型备注只陈述该轮次作弊行为，并写明反馈质量不合格；对应审核理由写反馈完全不可用。
- **两套档位词不要混用。** 飞书「反馈质量」、`rating`、质量备注 `note` 用 `高质量` / `合格` / `不合格`。平台「请选择该用户的反馈质量」、`platform_audit_reason`、飞书「一次质检平台审核理由」用 `完全可用` / `部分可用` / `完全不可用`。审核理由禁止写「故高质量」「故合格」「故不合格」「反馈质量为高质量」。
- **档位理由必须写清，且保持短句。** 复核人只看质量备注和审核理由，就要知道本条为什么落在该档。禁止只复述模型卡死、花屏、报错而不提标注打分对不对。
  - `高质量` / `完全可用`：用「和产物实测情况一致，评分正确」收束。不要再列一项仍构成合格档的偏差。
  - `合格` / `部分可用`：写清和产物实际情况一致或不符合的地方，并点名哪一项评分偏高或偏低。只写「卡死和 1 分相符」会读成高质量。
  - `不合格` / `完全不可用`：点名红线、完全不可信；按脏数据标签补一句，例如敷衍恶意打分、AI 打分、轮次作弊、用户切换模型错误。
- 主语要分开：模型交付报告 / 标注备注 / 质检结论。不要单独写「报告声称」，以免读成标注人的话。不要写「标注人在备注中记录……，与备注相符」：前半句已在说备注内容，后半句缺主语且自己和自己相符。列举备注要点最多写两点再加「等」，收束写成「实际情况与备注相符」，或写明谁与谁相符（例如「产物 8 分与备注相符」）。`selfcheck.py` 命中句首或逗号、句号后紧跟「与备注相符」「与反馈相符」即不合格。
- 分数与实测是否对齐，写「相符 / 不符」，不要写「同向」。评分相对实测是高了还是低了，写「偏高 / 偏低」，不要写「偏严 / 偏松」。
- 不要用「缺口」。缺功能、缺控件、没写全，改写成「缺陷」「缺失」「问题」或「不完整」。`selfcheck.py` 命中「缺口」即不合格。
- 平台审核理由写一句事实结论，并点出档位原因，例如“产物 9 分偏高，反馈部分可用”“构建失败但标注给满分，反馈完全不可用”。不能只写“存在偏差”“证据不完整”。不要复制反馈质量备注全文。同一题可以共用句式；连续几题不要沿用同一句首。优先手写 `platform_audit_reason`。
- 高质量档用「和产物实测情况一致，评分正确」收束即可，不要为凑数据完整、可复现、模型洞察、业务影响四条把备注写成长文。
- 禁止档位套话和空评价：`站得住`、`高一档`、`低一档`、`略高一档`、`偏高一档`、`方向对`、`方向到位`、`判断成立`、`评分方向合理`、`完全吻合`、`标签成立`、`偏薄`、`兜底`、`更稳`、`抓得准`、`缺口`。改成具体事实，例如“产物 6 分偏高，核心战斗进不去”。
- 禁止口语化对照词，改成书面判断用语（`selfcheck.py` 命中即不合格）：`说得通`→`合理`；`对得上` / `能对上` / `全对上`→`与…相符` 或 `一致`；`对不上`→`不符` 或 `不一致`；`同向`→`相符`；`偏松`→`偏高`；`偏严`→`偏低`；`写重了` / `过重` / `偏重` / `说得过头`→`与实际情况不符`；`仍在`→`与实际情况相符`；`可核` / `也可核` / `能核`→`和实际验证结果相符`；`抬上去了` / `抬在`→`得益于`；`没有抬`→`未虚高`；`缺口`→`问题` / `缺陷` / `缺失` / `不完整`。不要写「未写反」，过程分和产物分要分别写清相符、偏高或偏低。标注写对了就写「与实际情况相符」，写错了就写「与实际情况不符」，不要用「仍在」「说得过头」「可核」。
- 机器词表在 `skills/qc-eval/config/writing_style.json`，`selfcheck.py` 命中即不合格。参考表 `docs/描述语言参考.xlsx` 里也会出现「属实」「站得住」等过期套话，只学句式，不要把这些词写进交付。

### 句式模版（按档位写短句，连续题换开头）

写 `note` 时按档位套短语，**1～2 句**，不要按场景堆 20 种开头。同一题 5 个模型可以共用同一开头；连续几题不要沿用同一句首。质量备注用飞书档位词收束；`platform_audit_reason` 另写一句，用平台选项词收束。完整列表在 `skills/qc-eval/config/writing_style.json` 的 `opening_families`。

| 档位 | 质量备注怎么写 | 审核理由收束 |
| --- | --- | --- |
| 高质量 | 和产物实测情况一致，评分正确 | 反馈完全可用 |
| 合格 | 写出和产物实际情况一致或不符合的地方，并点名哪一项评分偏高或偏低 | 反馈部分可用 |
| 不合格 | 点名红线、完全不可信，并按脏数据标签写一句 | 反馈完全不可用 |

例句（把本题事实换进去，不要照抄前 8 字）：

1. 高质量 / 打分先行：标注人给执行过程 8 分、执行产物 8 分，和产物实测情况一致，评分正确，反馈质量为高质量。
2. 高质量 / 实测先行：主页面能开、主链路能走完，和标注一致。过程 9 分、产物 9 分和产物实测情况一致，评分正确，反馈质量为高质量。
3. 合格 / 偏高：标注人给执行过程 8 分相符、执行产物 9 分偏高。主页面能开和标注一致，反馈质量为合格。
4. 合格 / 偏低：服务起不来，和标注备注一致。过程 2 分相符，产物 4 分偏低，反馈质量为合格。
5. 合格 / 不符：标注人备注写完全无法启动，和产物实际情况不符。过程 3 分偏低，产物 2 分相符，反馈质量为合格。
6. 不合格 / 敷衍恶意打分：标注评语空泛、各模型串同一张图，属敷衍恶意打分，结论不可信。反馈质量为不合格。
7. 不合格 / AI 打分：标注备注带百分制和作为 AI 口癖，属 AI 打分红线，结论不可信。反馈质量为不合格。
8. 不合格 / 低质量任务：提示词要求模型工具轮次达到 450，属轮次作弊红线，本题不再核产物。反馈质量为不合格。
9. 不合格 / 切换模型：标注按本模型独立完成来打分，轨迹前段与他模型雷同，属用户切换模型错误，结论不可信。反馈质量为不合格。

其他脏数据标签按同一句式补一句即可，例如 API 超时、OpenClaw/Hermes、LLM 测 VLM。审核理由不要抄「反馈质量为…」，改写成：和产物实测情况一致，评分正确，反馈完全可用。 / 产物 9 分偏高，反馈部分可用。 / 标注空评且串图，属红线，反馈完全不可用。

## 关键约束

1. 质检相关动作只走本技能列出的集中脚本，不直接调底层 API 或 lark-cli。
2. 本仓库当前默认飞书交付目标为 `sheet=cHr9N5`。源表只读本地 `docs/G1-new.xlsx`。
3. 自动流程只生成本地文件；飞书回写只能在用户明确下达上传/回写指令后，通过显式 push 命令执行。用户只说“质检 <任务ID>”时，不得执行 `--write`。平台质检表单同样：只有用户明确要求填写网页表单后才运行 `fill_g1_audit_form.js`；该脚本只能保存草稿，不能提交。
4. 截图必须是本人复测证据，不能复用标注人的截图；`delivery/<TASK_ID>/screenshots/` 只保留有效截图 PNG（如 `<模型>_01_cli.png`）和合成图 PNG（`<模型>_verify.png`），不要保留 `log.txt`、临时图、别名图或其他辅助文件。合成图必须按左右横向拼接原图，禁止上下纵向拼接；若只有一张有效截图，则直接复用该原图作为 `<模型>_verify.png`。提示词轮次作弊时五个模型都用同一张提示词红框图，文件名用 `<模型>_01_prompt_cheat.png`。
5. `delivery/<TASK_ID>/<TASK_ID>.xlsx` 必须从空白 workbook 重建，只包含表头行和该任务行。
6. `.ark_platform_state.json`、本地探测缓存和登录态文件不能提交。
7. 流程脚本未调通、模型数不一致、或「下载列表」采不到时，停下来与人工核对，不要继续编造材料。命中提示词轮次作弊而采集脚本主动跳过 workspace / 轨迹时，不按本条拦截。
8. 提示词轮次作弊必须在下载到提示词之后、复测产物之前判定。禁止先测完产物再补判作弊。
9. 填写平台质检表单时只改右侧「质检」面板，只点「保存草稿」。禁止提交审核、打回，也禁止改评测打分或其他页签。

## 常用命令

```bash
python3 skills/qc-eval/scripts/probe_g1_task_ids.py --task-id <任务ID>
node skills/qc-eval/scripts/fetch_g1_platform.js auth-from-chrome
# 或：node skills/qc-eval/scripts/fetch_g1_platform.js auth-login
node skills/qc-eval/scripts/fetch_g1_platform.js collect --task-id <任务ID>
python3 skills/qc-eval/scripts/check_prompt_cheat.py <任务ID>
# 命中轮次作弊时用 --apply 写 qc_cells 并出提示词红框截图，跳过下面的产物复测：
# python3 skills/qc-eval/scripts/check_prompt_cheat.py <任务ID> --apply
# 复测截图按「复测启动与截图」选题型，不要一律上 u03l：
# node skills/qc-eval/scripts/screenshot_vue.js <任务ID>
# python3 skills/qc-eval/scripts/compose.py <任务ID>
# python3 skills/qc-eval/scripts/compose_cli.py <任务ID>
# python3 skills/qc-eval/scripts/u03l.py check-host
# python3 skills/qc-eval/scripts/verify_fullstack.py <任务ID>
python3 skills/qc-eval/scripts/push_xlsx.py <任务ID> --period G1-new
python3 skills/qc-eval/scripts/generate_model_qc_platform.py <任务ID>
python3 skills/qc-eval/scripts/selfcheck.py <任务ID>
# 用户明确要求填写平台质检表单后才可执行；只保存草稿，不提交：
node skills/qc-eval/scripts/fill_g1_audit_form.js --task-id <任务ID>
python3 skills/qc-eval/scripts/push_g1_feishu.py <任务ID> --dry-run
# 用户明确要求上传/回写飞书后才可执行：
python3 skills/qc-eval/scripts/push_g1_feishu.py <任务ID> --write --confirm-user-instructed
```

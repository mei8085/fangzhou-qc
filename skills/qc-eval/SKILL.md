---
name: qc-eval
description: 44期方舟 coding 众测质检工作流。质检题目从本地 docs/44.xlsx 按任务ID读取，不从飞书同步源表。标注与产物从 Ark 平台 project 326 按任务ID搜索，采集 0825E/harpoon、0901B/gazelle、0819K-RLHF/finch、0902F/elixir。交付回写飞书 sheet=vD6HYi。允许部分题目只完成了部分模型，未作答模型按不合格交付。
---

# 方舟 coding 众测质检 - 44期工作流技能

唯一权威说明文件。`CLAUDE.md`、`AGENTS.md`、`.cursor/rules/qc-eval.mdc`、`.cursor/skills/qc-eval/SKILL.md` 只做入口指引，不复制流程。

配套规范：

- 新规则整理：`spec/36期质检新规则.md`（44期继续沿用这套质量口径）
- 脏数据标签与标准：`spec/Coding场景脏数据标签与标准.md`（平台反馈质检的脏数据标签按此执行）
- 兼容入口：`spec/方舟coding众测质检流程及规范.md` 已更新为同一套质量规则

## 44期默认配置

- 本地源表：`docs/44.xlsx`（`docs/` 已 gitignore）。可用环境变量 `QC_SOURCE_XLSX` 或 `--source` 覆盖。
- 源表不从飞书同步。飞书只作为交付回写目标。
- 飞书交付表：`https://bytedance.larkoffice.com/wiki/OY1Dw0dcailCxTk3UGOcykVznAf?sheet=vD6HYi`
- sheet_id：`vD6HYi`
- Chrome 默认个人资料：`quan-134`（磁盘目录 `Profile 4`）。`auth-from-chrome` 默认从该 Profile 导出方舟平台 cookie；如需临时改用其他 Profile，显式传 `--profile <Profile目录名>`。
- 本地任务目录名：必须使用源表 `任务ID`，例如 `6397`
- Ark 平台项目：`https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/myprojects/326/task/7841`
- 任务详情：`https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/myprojects/326/task/<任务ID>`
- 平台检索：以任务ID搜索。任务详情页首轮 Prompt 下的「上传产物」来自任务详情 `attachments`；它与模型侧「模型运行」/「下载列表」/Workspace 是两个独立数据源，不能用模型下载列表是否为空推断首轮上传产物是否存在。下载列表走 `CaseBffV1CrowdtestTaskModelWorkspaceDownloadLatestList`。
- 模型对应：

| 表头模型 | 代号 | 平台 codeName |
| --- | --- | --- |
| 0825E | 0825E | harpoon |
| 0901B | 0901B | gazelle |
| 0819K-RLHF | 0819K-RLHF | finch |
| 0902F | 0902F | elixir |

- 44期允许部分题目只有部分预期模型运行。配置 `allow_missing_models=true` 只放行“预期模型缺失”，若出现未配置的额外模型仍停止采集。缺失模型必须在 `model_map.json` 标记 `missing=true`，飞书反馈质量填“不合格”，脏数据标签填 `用户问题:敷衍恶意打分`；因无 `taskModelRunId`，不得伪造平台审核页或草稿。

- 配置文件：`skills/qc-eval/config/g1.json`
- 任务类型选项：`skills/qc-eval/config/g1_label_options.json`。44期源表 `label` 为空时，必须从该文件 10 个选项中选择；未在 `qc_cells.json` 显式填写时，交付脚本按任务名和提示词做启发式推断。
- 平台质检表单模版：`skills/qc-eval/config/g1_audit_form.json`（适用于 project 326；逐模型审核页由采集到的 `taskModelRunId` 动态生成）
- 质检后填写文件：`delivery/<TASK_ID>/<TASK_ID>_model_qc_platform.md` 与 `delivery/<TASK_ID>/<TASK_ID>_audit_form_fill.json`
- 平台质检表单回填（只保存草稿）：`node skills/qc-eval/scripts/fill_g1_audit_form.js --task-id <任务ID>`
- Ark 平台采集脚本：`node skills/qc-eval/scripts/fetch_g1_platform.js`
- 本地任务探测：`python3 skills/qc-eval/scripts/probe_g1_task_ids.py --task-id <任务ID>`
- 交付 xlsx：`python3 skills/qc-eval/scripts/push_xlsx.py <任务ID> --period 44期`
- 飞书回写：默认只允许执行 `python3 skills/qc-eval/scripts/push_g1_feishu.py <任务ID> --dry-run` 预检；只有用户明确指令“上传/回写/写入飞书”后，才允许执行带 `--write` 的命令。

## 多 Agent 并发约束

- 不同 Agent 必须各自处理不同的 `任务ID`；所有采集、复测、日志和交付产物都写入 `tasks/<TASK_ID>/` 或 `delivery/<TASK_ID>/`，不得使用共享的单题工作目录。
- `probe_g1_task_ids.py --task-id <TASK_ID>` 默认写 `tasks/<TASK_ID>/source_probe.json`。只有不带任务筛选、生成全量诊断索引时才写 `tasks/_g1_task_ids.json`；该全量文件不是后续质检流程的输入或任务状态。
- 官方截图/启动脚本默认按任务分配本地端口，通用 Vue/SPA 脚本还会预留端口块；显式传相同的 `--base-port` 会被端口锁或 `strictPort` 拒绝，不要让不同任务复用同一显式端口。
- Ark 采集和平台草稿可按不同任务并发；共享 `.ark_platform_state.json` 只读。登录态刷新使用临时文件完成后原子替换，避免采集进程读到半写文件。批量并发前仍建议先完成一次 `auth-from-chrome`。
- 飞书实际写入会按目标 sheet 自动串行化，锁覆盖“重新定位任务行、核对任务名、写文字与图片”的完整过程；不同任务可以同时完成本地工作，写回阶段短暂等待即可。`--dry-run` 不持有写锁。
- u03l 的目录、Docker project、数据库和隧道状态均按任务ID命名。不要对另一任务执行 `tunnel.py close`、`u03l.py down`，也不要手工复用它的远端目录。

## 运行环境

同时支持 Cursor、Claude Code、Codex；操作系统为 Windows（含 Git Bash）、macOS、Linux。

- Python 3：下列命令写 `python3`。Windows 若只有 `python`，把命令中的 `python3` 换成 `python`。也可用 `QC_PYTHON` 指定解释器。
- 源表路径不要写死盘符。默认见上文「本地源表」。
- Ark 登录态：`auth-from-chrome` 会从本机 Chrome 的 `quan-134` 个人资料（`Profile 4`）导出 volcengine cookie（Windows 用 VSS，macOS 用 Keychain，Linux 用 libsecret）。导出失败时自动打开有头浏览器，改为 `auth-login`。也可直接跑 `node skills/qc-eval/scripts/fetch_g1_platform.js auth-login`。
- Cursor 跑 Playwright / 有头登录 / 平台采集时需要本机网络，并批准相应权限；有头登录会弹出 Chrome/Chromium 窗口，需人工完成登录。
- `lark-cli` 必须在 PATH 中（macOS/Linux 为 `lark-cli`，Windows 可为 `lark-cli.exe`）。
- 测试机 SSH 别名 `u03l`：只有题目依赖数据库、消息队列、Celery，或交付物自带 docker-compose 且本机不便跑时，才在这台机器上用 Docker 起基础设施。一次性准备见 `skills/qc-eval/remote/README.md`；何时用、用哪条脚本见下文「复测启动与截图」。

### 本地环境依赖闸门

复测失败先判定是不是质检机环境问题，不能把本地缺依赖直接当成模型产物问题。

- 出现 `command not found`、`Cannot find module`、`ModuleNotFoundError`、`No module named`、`No matching version found`、`Electron failed to install correctly`、Playwright 浏览器缺失、Vite/tsc/vitest/playwright shim 缺失等情况时，先补齐环境再复测。
- Node 项目优先按仓库锁文件执行 `npm install` / `pnpm install` / `yarn install`；缺 `.bin` shim 时必须重建依赖；Playwright 缺浏览器时执行项目内 `npx playwright install chromium` 或技能目录的 Playwright 安装命令；Electron 二进制下载失败时可切换可用 mirror 后重跑 install。Python 项目缺包时按 `requirements.txt` / `pyproject.toml` 安装，必要时新建隔离 venv。
- 补齐环境后必须重新跑与任务验收相关的命令或页面验证，例如 typecheck、unit tests、build、dev server、Playwright E2E、API smoke。只有补齐后仍失败，且失败能指向交付代码、配置、测试断言或功能行为，才按产物问题评价。
- 若环境因外部服务、私有源、系统版本或硬件条件确实无法补齐，`verifiable` 才可填 `否`，并在不可验证原因中写清已尝试的安装/修复动作和仍不可复现的外部条件；不得用泛泛的“本地环境问题”代替复测结论。
- 质量备注或审核理由提到本地环境、缺依赖、Playwright/Electron/Chromium、`command not found` 等环境现象时，必须同时说明已补齐环境并复跑后的结果；`selfcheck.py` 会拦截只写环境失败、未说明补齐复测的结论。

### 标注测试环境差异归因闸门

标注人备注、附件或平台截图明确写了特定测试环境（例如 Windows、macOS、Linux、CI、Docker、测试机、浏览器版本、Node/Python 版本、路径格式、端口或外部服务），而质检复测环境与其不同或无法确认相同环境时，按“结果差异”处理，不能冒然写成“标注人错误 / 失败原因错误 / 失败理由不符 / 与实际情况不符”。

- 只有满足至少一项时，才可断定标注人备注或归因不符：同环境复测复现了相反结果；轨迹、源码、配置、命令输出或平台可见证据足以证明标注描述不可能成立；标注人内部前后矛盾且不依赖环境差异解释。
- 不满足上面条件时，用谨慎表述：`本次环境未复现该失败`、`本次环境结果不同，无法排除环境差异`、`标注人记录的失败结论仍可采信 / 仅部分可采信`、`本次只按可重复执行性和证据完整度降档`。
- 对 Windows 空格路径、大小写敏感文件系统、换行符、shell/PATH、Playwright/Chromium 版本、Docker/CI service 初始化顺序等环境相关失败，若未在同类环境复测，不要否定标注人的具体原因；最多写本次环境观察到的另一种失败或未复现。
- 备注需要同时写清三件事：标注人在哪类环境观察到什么结果；本次质检在哪类环境观察到什么结果；为何仍给当前反馈质量档位。审核理由同样使用“未复现 / 结果不同 / 可采信程度”表述，不写“理由不符”。

## 原始 Session 采集与故障排查

「原始 Session」与 ByteHouse Session 汇总是两个独立数据源。`collect` 对各框架都先探测并采集原始 Session，再保留 ByteHouse 汇总，不按任务框架名称跳过下载。当前支持 Codex、Claude Code 的 JSONL/NDJSON 解析及框架名称大小写、空格、连字符变体；未知框架名称下仅在原始记录符合已知结构时解析。汇总中的输入输出为空或只有完成说明，不代表原始轨迹缺失，不得据此给标注反馈降档。

判断模型是否虚报测试通过，必须核对原始 Session 中关联的工具命令、工具返回与之后的完成声明，不用质检员复测结果反推模型当时是否执行。Claude Code 的 `user.message.content` 中 `tool_result` 是工具返回，不是用户评语；`assistant` 的 `tool_use` 通过 ID 与其关联。压缩摘要和模型报告本身不替代工具证据。7979 的原始工具返回确有 `65 passed`，不能因为另一次复测失败就说模型推测性通过。

页面“更多 Session 操作 → 下载原始 Session”使用 Workspace 下载任务、`path=".sessions"`，得到 Session ZIP；这与代码 Workspace ZIP 是不同路径。逐文件预览接口返回 `application/octet-stream`，须按原始字节保存，不能读取 JSON 的 `data` 字段。7979 已核对菜单 ZIP 内 JSONL 与预览接口文件完全一致。排查页面下载时可运行 `node skills/qc-eval/scripts/fetch_g1_platform.js discover-session --task-id <任务ID> --run-id <运行ID> --download-original`，脚本只点击 Session 下载菜单，保留菜单截图、ZIP 和下载校验信息。

- 原始文件通过 `CaseBffV1CrowdtestTaskModelSessionBrowserGet` 分页列出，预览响应统一按原始字节读取，兼容 octet-stream、text/plain、JSON/NDJSON 等响应头；不得直接取 `data`。HTTP 错误、登录 HTML、API 错误包装与空响应不能当成原文件。超时、限流和常见服务端临时错误有界重试；登录失效先按认证流程恢复。
- 每模型输出在 `trajectory/original_sessions/`：`manifest.json` 记录完整性、原路径、大小和 SHA-256；哈希命名的 `.jsonl` 保留原文件，`.events.jsonl` 与 `.md` 展开助手消息、工具参数与原始返回，并按 `call_id` 关联。`trajectory.md` 提供这些证据入口。阅读过程评分证据时应打开原始 Session 对应的 Markdown，而非只看 ByteHouse 摘要。
- `compacted` 是上下文压缩摘要，不是独立工具执行证据；`event_msg` 可能重复助手消息，不据此重复计数。未知事件仍保留在原文件中，质检不统计实际工具轮次。
- `manifest.json` 分别记录 `download_status`、`parse_status`：未知格式或解析失败也保留原始文件、哈希和错误原因，并继续下载列表中的后续文件，最终以错误退出；不能把已下载但未解析写成下载失败或无轨迹。列表分页不完整、路径重复、运行 ID 不符、字节数不符会以错误退出。只有成功列完且确实为零个文件才是 `empty`。
- `--keep-existing` 仍刷新文件列表，只复用同一运行、大小和本地 SHA-256 均匹配的缓存，并重新解析；本地哈希不能证明远端同大小文件未变化，需确认远端更新时去掉该参数重新下载。失败重采会使旧的成功轨迹入口失效，避免把上次材料当成本次成功。
- 遇到 `error`，先读原始 Session 清单和已保存的 `browser.json`，按认证、网络、大小不符或解析错误处理；接口异常但页面可下载时，运行下述 `discover-session --download-original` 保存菜单 ZIP 和网络证据。ZIP 下载成功不等于内容已解析，仍需核对文件并修复对应解析器后重跑，不能据此跳过证据检查。单文件 64 MiB、总量 256 MiB、最多 1000 文件为当前保护上限；超限应核对实际列表后有依据地调整脚本，不可当成轨迹缺失。

已有材料可只补采轨迹，不重下 Workspace 或覆盖质检结论：

```bash
node skills/qc-eval/scripts/fetch_g1_platform.js collect-sessions --task-id 7972 --keep-existing
# 只探测一个审核页的原始 Session 入口和只读网络响应：
node skills/qc-eval/scripts/fetch_g1_platform.js discover-session --task-id 7972 --run-id 24669
```

这两个维护命令用于用户明确要求的轨迹补采或探测；常规质检仍遵守下载按钮和提示词闸门。补采不自动改档、回写飞书或保存平台草稿；需要结合工具执行记录重新判断，外部写入沿用用户的授权范围。

## 新规则口径

44期以用户提供的新规则为准，不沿用更早期历史口径。质量判断仍按 `spec/36期质检新规则.md`。

### 出题质量

一句话：高经济价值且高评测价值的完整任务。

重点看三类指标：

- 完整性：题目目标、输入输出、约束、术语和上下文清楚；rubric 和交付要求完整；Coding Agent 必须提交 workspace，代码仓库体量、结构和工程完整度需达到高商业价值企业软件标准。编写「题目质量说明」时不得出现具体代码量阈值或代码行数，只可概括写代码仓库体量较小、工程完整度不足、未达到高商业价值的企业软件标准等判断。
- 经济价值：来源真实，来自真实业务场景、工单或客户需求；Coding Agent 公司项目要和公司方向匹配，个人项目需达到上线标准，学校项目仅接受研究生及以上科研项目。
- 评测价值：正确与错误有客观证据，得分点可稳定判定；区分度参考标准差 > 1.5 且最低分 < 9 分；复杂度指标只作参考，Coding Agent 参考模型平均工具轮次 > 450。**质检不负责统计轨迹轮次**（甲方自行分析轨迹）；质检只核对提示词有没有把轮次配额写给模型。

### 反馈质量

一句话：清晰、可复现的任务反馈和模型洞察。

重点看四类指标：

- 反馈数据完整：有清晰产物截图或链接、完整任务描述、模型输出结果、关键过程信息和必要上下文材料。
- 可复现：有明确操作步骤、输入数据或链接、期望结果和实际结果，不能只写“效果不好”“不符合预期”。
- 模型行为洞察深度：能指出具体能力短板，能归因到模型行为，能区分不同模型或框架表现差异。
- 真实业务影响：说明问题是否影响真实用户完成任务，以及是否影响效率、质量、成本、合规或业务结果。
- **归因标签**：对照评测打分里的过程/产物归因标签、维度备注和实际情况。标签是标注人评价的一部分；若所选标签符合实际情况，且备注没有与标签相反或矛盾的描述，即使备注没有展开该标签，也不按错选处理。只有标签本身不符合实际，或标签与备注明确矛盾时，才按标签错选处理；不能定高质量。

### 反馈质量评级

| 评级 | 判定 |
| --- | --- |
| 高质量 | 打分准确，备注规范，佐证充分，与实际完全一致。归因标签符合实际，且不与维度备注矛盾。 |
| 合格 | 打分大体合理但存在部分偏差或不完善；或打分、备注、佐证、归因标签有明显问题但未触发红线。 |
| 不合格 | 反馈完全不可信，或触发红线规则。 |

44期飞书列“反馈质量（作业质量）”下拉只有 `高质量`、`合格`、`不合格` 三个选项，禁止写 `红线`。若模型反馈触发反馈质量红线或脏数据标签，该模型“反馈质量（作业质量）”填 `不合格`；题目红线写到“红线问题”；逐模型飞书“脏数据标签”必须写成下拉原文，例如 `用户问题:敷衍恶意打分`。非脏数据时该列留空，不要填 `非脏数据`。

特殊例外：每个已提交模型都必须先检查任务详情「下载列表」里的下载按钮。某模型按钮禁用时，该模型按“产物不可下载”处理：反馈质量填 `不合格`、脏数据标签填 `其他`，但这不是反馈红线；必须由下文按钮禁用闸门的机器可读结果和页面截图佐证。部分模型不可下载时，只给这些模型套模板，其余可下载模型仍按正常规则质检。

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
- `AI 打分 / AI 评价`：仅当明确证据表明标注人员使用 AI 生成提交的评分或评价时判定。任务要求测试模型自评、自测、逐项验收或生成执行报告均不触发；图标、百分制、Markdown 或转述模型原话也不能单独作为依据。
- `敷衍恶意打分`：打分理由为空或极短、标准前后不一、不同板块结论相悖、非关联维度连带扣分、评分与实际产物明显不符；L2 还包括多模型理由高度雷同、未测完全部模型就提交、各模型分数一致但实际差异明显。
- `题目红线（prompt 简单 / VLM 错配）`：prompt 过于简单或模糊、纯题库题、VLM 错配、纯生图任务、全部模型工具调用轮次 < 10、同任务给各模型 prompt 不一致；补充红线包括毫无意义题目、非代码题、题目不合理、非本人场景、静态展示性页面、**提示词轮次作弊**。
- `低质量任务`：飞书下拉选项是 `用户问题:低质量任务`。提示词轮次作弊时，下载可用模型打此标签；下载不可用模型仍打 `其他`。内部可用页面上的执行过程分、产物质量分判断是否整体偏高且分差很小；交付备注不要另写「综合评分 / 均分 / 总分」，页面评测打分没有这些聚合字段。

### AI 评价证据归属

选择 `用户问题:AI打分/AI评价` 前，必须区分测试模型的任务产物与标注人员提交的评价。不得把前者中的自评内容当成后者使用 AI 的证据；有评分 rubric、验收对照或自测报告时仍按正常流程复测。7979 的模型自评与测试要求就是不触发此红线的反例。仅有风格疑点时不打此标签，也不改套“虚假反馈”等其他红线。

确有标注侧证据时，在对应 `sheet.models.<模型>` 中填写 `ai_feedback_evidence`：`source` 固定为 `annotator_feedback`，`quote` 为该模型平台评测备注或产出物反馈中的原文，`reason` 说明该原文如何证明**标注人员**使用 AI 评分或评价，而非转述测试模型内容。字段结构为 `{"source":"annotator_feedback","quote":"标注反馈的真实原文","reason":"标注人员使用 AI 评价的具体依据"}`。脚本只检查来源和引用能否核对，归因仍须人工判断；不得为了通过校验编造引用或把任务自评改称标注自评。

`python3 skills/qc-eval/scripts/check_ai_feedback.py <任务ID>` 检查该证据；自检、平台填写文件生成、飞书写入和平台草稿入口均执行此校验。检查失败时回到证据核对，不自动改档或改选红线。非 AI 评价记录无需填写该字段。

## 标准流程

1. 确认本地源表存在，并按任务ID定位题目。不要从飞书同步源表。

```bash
python3 skills/qc-eval/scripts/probe_g1_task_ids.py --task-id 6397
```

2. 使用该 `任务ID` 作为 `tasks/` 和 `delivery/` 的子目录名；禁止使用行号作为本地工作编号。同一任务ID也是 Ark 平台搜索关键字。

3. 首次使用 Ark 平台前导出登录态。

```bash
node skills/qc-eval/scripts/fetch_g1_platform.js auth-from-chrome
# 默认等价于：node skills/qc-eval/scripts/fetch_g1_platform.js auth-from-chrome --profile "Profile 4"
# cookie 导出失败时（常见于 macOS Chrome v20 / Cursor）改为人工登录：
node skills/qc-eval/scripts/fetch_g1_platform.js auth-login
```

4. **先执行模型产物下载可用性闸门，再采集 Ark 平台材料。** 这是每题、每个已提交模型的强制前置步骤，不能等到看完轨迹或启动产物后再补查。

```bash
node skills/qc-eval/scripts/fetch_g1_platform.js discover-download --task-id <任务ID>
node skills/qc-eval/scripts/fetch_g1_platform.js collect --task-id <任务ID>
python3 skills/qc-eval/scripts/extract_g1_workspaces.py <任务ID>
```

`discover-download` 先截图并记录每个模型的按钮状态；`collect` 没有同任务的有效检查结果会拒绝继续。随后按任务ID搜索 project 326，拉取任务详情与页面提示词，下载并扫描首轮 Prompt 下的全部「上传产物」，把上传文本与页面提示词一起过「提示词轮次作弊闸门」。对下载按钮禁用的模型，采集只保留运行映射和填写模板所需的执行过程分、产物质量分，跳过评测附件、审核记录、Workspace Browser、轨迹、逐模型下载列表和 Workspace ZIP；对按钮可用的模型正常采集并质检。脚本默认 `--project 326`，本地目录与平台搜索都用同一个任务ID。输出目录为 `tasks/<任务ID>/ark_g1/`，并写 `tasks/<任务ID>/model_map.json`。

首轮「上传产物」固定输出如下，和各模型目录内的 `workspace/`、`download_list.json` 分开：

- 原文件：`tasks/<任务ID>/ark_g1/task_uploads/`
- 下载清单：`tasks/<任务ID>/ark_g1/task_uploads.json`，含平台报告数量、原文件名、大小和 SHA-256；`status` 必须为 `complete`
- 压缩包与文本检查报告：`tasks/<任务ID>/ark_g1/task_uploads_inspection.json`
- 去重后的 Markdown/文本材料：`tasks/<任务ID>/ark_g1/task_prompt_materials.json`
- 页面提示词与上传文本合并后的检查稿：`tasks/<任务ID>/prompt.md`

即使模型「下载列表」为 0，也必须单独检查上述首轮上传清单。上传产物里的 `.md` / `.txt` 等文本可能才是用户的真实提示词或补充要求，必须在看模型产物前阅读；压缩包会受路径、体积、文件数和嵌套深度限制递归扫描。页面/API 报告有上传文件但下载失败、校验不一致、文本无法解码、压缩包超限或存在未能检查的嵌套包时，采集脚本必须停住，人工核对后再继续，不得把它当作「无上传产物」。二进制文件会保留并在检查报告标记 `manual_review_required`，质检时需按文件类型人工查看。

采集成功后必须运行 `extract_g1_workspaces.py`。脚本只解压下载可用模型的 Workspace，自动跳过未作答和下载不可用模型，跳过 `.autocase` 输入缓存，并把可复测入口写回 `model_map.json`；后续截图脚本依赖该 `entry`。已有解压目录时默认不覆盖，确需重建才显式加 `--force`。

采集在拿到 `task.json` 并完整下载、检查首轮「上传产物」之后，才会跑 `check_prompt_cheat.py --scan-only`。检查范围是页面提示词加上传产物中的 Markdown/文本。命中轮次作弊时**不再下载 workspace zip / 轨迹 / 逐模型下载列表**，也不要再去复测产物；前置的任务详情下载按钮截图仍保留。

若平台 codeName 出现未配置的额外模型，脚本必须停住。缺少 `harpoon,gazelle,finch,elixir` 中的预期模型时，脚本按 `allow_missing_models` 配置继续，在 `model_map.json` 留下明确缺失记录，并用 `render_missing_model_evidence.py` 生成缺失证据。采集过程中若「下载列表」API 不一致，先停下来与人工核对，不要自行发明下载方式。

5. **提示词轮次作弊闸门（必须在复测产物之前）**。不要先测完已作答模型产物再回头看提示词。脚本读取 `tasks/<任务ID>/prompt.md` 对应的合并材料；若 `task.json` 报告存在首轮上传文件，但 `task_uploads.json` 或文本检查结果缺失/不完整，脚本会直接报错，不得绕过。

```bash
python3 skills/qc-eval/scripts/check_prompt_cheat.py <任务ID>
```

- 质检**不数**轨迹工具轮次。甲方会自行分析轨迹。
- 只核对提示词有没有要求模型把轮次/工具调用次数做到某个数量，例如「工具轮次达到 450」「至少调用工具 100 次」「不够就刷轮次」。
- **未命中**：继续下一步人工质检和产物复测。
- **命中**：题目质量填 `不合格`；`红线问题` 填 `题目不合理`。下载按钮可用模型的反馈质量填 `不合格`、脏数据标签填 `用户问题:低质量任务`，验证截图使用提示词红框图；下载按钮禁用模型仍按产物不可下载模板填写并使用下载列表截图。不要再起 dev server、不要再打开各模型产物。

```bash
python3 skills/qc-eval/scripts/check_prompt_cheat.py <任务ID> --apply
```

`--apply` 会为下载可用模型写好 `qc_cells.json` 草稿并生成 `delivery/<任务ID>/screenshots/<模型>_01_prompt_cheat.png`。若存在下载不可用模型，随后仍须运行 `apply_download_unavailable.py <任务ID> --apply` 为这些模型补模板和下载列表截图；再进入交付（`push_xlsx.py` / `generate_model_qc_platform.py` / `selfcheck.py`），跳过「复测启动与截图」。

### 下载列表按钮禁用闸门

每题都必须在任何模型级质检之前，用集中脚本检查任务详情页「下载列表」。不能用已下载 Workspace 为空、只有说明文档，或首轮上传产物是否存在来推断模型产物能否下载。

```bash
node skills/qc-eval/scripts/fetch_g1_platform.js discover-download --task-id <任务ID>
```

`discover-download` 会打开任务详情页、点击「下载列表」、截图并把逐模型按钮状态写入 `tasks/<任务ID>/ark_g1/download_list_discover.json`。逐模型只按「下载」按钮本身判定；`等待创建`、`尚未开始` 等文字只作辅助证据，不能替代按钮状态。结果分类如下：

- `all_artifacts_download_unavailable`：所有已显示、已提交模型的按钮都禁用；这些模型全部套模板，不做模型级质检。
- `partial_artifact_download_unavailable`：部分模型按钮禁用；只给禁用模型套模板，只质检按钮可用的模型。
- `all_artifacts_download_available`：所有已提交模型按钮可用；全部走正常质检。
- `download_state_requires_review`：页面未加载完整、按钮缺失或状态不是明确布尔值；必须停下人工核对，不得猜测、不得开始模型级质检。

预期模型未作答不等于下载状态未知。`collect` 会用实际运行记录与发现结果交叉核对：每个已提交模型都必须有明确按钮状态，未作答模型继续按未作答流程处理。

应用前先按第 6 步创建 `tasks/<任务ID>/qc_cells.json`，完成任务名、题目质量、题目质量说明、label 和分类判断；下载不可用模板不会代替这些题目级判断。随后默认运行 `apply_download_unavailable.py` 只预检，预检通过后再显式应用：

```bash
python3 skills/qc-eval/scripts/apply_download_unavailable.py <任务ID>
python3 skills/qc-eval/scripts/apply_download_unavailable.py <任务ID> --apply
```

该脚本保留已有题目质量与分类判断，只更新按钮禁用模型，读取这些模型页面的执行过程分和产物质量分，并把下载列表截图作为对应模型的本人验证证据。逐模型填写口径固定为：反馈质量 `不合格`；脏数据标签 `其他`；质量备注、脏数据理由和审核理由都必须逐字填写 `产物不可下载，无法验证`，不得添加分数、按钮状态、档位结论、句号或其他说明；平台反馈质量仍选择 `完全不可用`。当所有已提交模型都不可下载时，题目填“不可验证”，不可验证原因也必须逐字填写 `产物不可下载，无法验证`；没有独立题目红线时红线留空。部分模型不可下载时，不覆盖题目级可验证性或红线，避免清除可下载模型或题目本身的结论。历史任务 6699 的已核对值和当前期固定模板保存在 [config/artifact_download_unavailable.json](config/artifact_download_unavailable.json)，以后不再读取旧飞书表。

页面仍在加载、截图缺失、已提交模型行缺失或按钮状态未知时，禁止套用模板并停止模型级质检。应用后只对 `artifact_download_available_models` 中的模型执行归因标签核对、轨迹检查、产物启动和复测截图；不可下载模型不得补做静态走读或尝试绕过按钮取包。最后按正常交付步骤运行 `push_xlsx.py`、`generate_model_qc_platform.py`、`selfcheck.py`；飞书和 Ark 草稿仍分别受原有用户授权约束。

6. 未命中轮次作弊时，才人工质检并写 `tasks/<TASK_ID>/qc_cells.json`。写备注前必须对照归因标签：

```bash
python3 skills/qc-eval/scripts/check_annotator_tags.py <任务ID>
```

脚本只读取下载按钮可用模型的 `evaluation.json` 过程/产物标签和维度备注，按 `model_map.json` 自动跳过产物不可下载模型。标签视为标注人评价的一部分；若所选标签符合实际情况，且备注没有与标签相反或矛盾的描述，备注未展开标签不算问题。只有缺陷标签对上明确相反的好评备注、标签本身不符合实测等情况，才会打印 mismatch 并写 `tasks/<TASK_ID>/annotator_tags.json`。这种情况不能定高质量；质量备注必须点名标签与备注或实测不符。`selfcheck.py` 会拦截漏写。备注按下文「句式模版」三档短句写；对照最近一题开头，不要和上一题同一句首，也不要照抄参考表里的长句。

推荐结构：

```json
{
  "task_id": "<任务ID>",
  "task_title": "源表里的完整任务名",
  "sheet": {
    "artifact_download_unavailable_models": ["仅列下载按钮禁用的表头模型名"],
    "artifact_download_available_models": ["仅列下载按钮可用的表头模型名"],
    "is_high_quality_task": "否",
    "prompt_quality": "高质量",
    "prompt_quality_note": "简洁说明题目本身的完整性、经济价值、评测价值、可复核性和质量结论，不引用测试模型的实际分数或分差。",
    "verifiable": "是",
    "verifiable_reason": "",
    "category_correct": "是",
    "redline_issue": "",
    "redline_note": "",
    "models": {
      "0825E": {
        "rating": "高质量",
        "note": "1～2 句。高质量：执行过程和产物质量分别与实际情况一致，评分正确。合格：写清一致或不符合的点，并点名哪一项评分偏高或偏低；过程分偏差必须写模型执行过程证据。不合格：点名红线并按脏数据标签写一句。同一题可共用开头，连续几题换句首。",
        "platform_audit_reason": "一句收束：完全可用 / 部分可用 / 完全不可用。不要写高质量、合格、不合格。",
        "dirty_tag": "",
        "dirty_tag_reason": ""
      }
    }
  }
}
```

`sheet.models` 的 key 必须是表头模型名：`0825E`、`0901B`、`0819K-RLHF`、`0902F`。未作答模型也必须写入，`rating` 填 `不合格`，备注明确写“未作答 / 平台没有运行记录”，`dirty_tag` 填 `用户问题:敷衍恶意打分`。

`sheet.models.<模型>.rating` 对应飞书列“反馈质量（作业质量）”，只能填 `高质量`、`合格`、`不合格`。触发反馈红线时也填 `不合格`，不要填 `红线`；红线原因在 `redline_issue` / `redline_note` 和逐模型 `dirty_tag` 中体现。`dirty_tag` 非脏数据时留空；有标签时必须写成飞书下拉原文。

`is_high_quality_task` 对应飞书列“是否是高质量题目”，必须填“是/否”；只有 `prompt_quality` 为“高质量”，且所有模型反馈质量均为“高质量”时才能填“是”。任务质量或任一模型反馈质量为“合格”/“不合格”时填“否”。交付脚本会按 `prompt_quality` 和 `sheet.models` 中全部模型反馈质量自动推导，无法推导时使用显式填写值并由自检拦截不一致结果。

`prompt_quality` 对应飞书列“任务质量（题目质量）”，按题目本身的完整性、经济价值、评测价值和可验证性判断；它可以与“是否是高质量题目”不一致，例如题目本身为“高质量”，但模型反馈整体未达到高质量时，“是否是高质量题目”填“否”；题目本身为“合格”/“不合格”时，即使全部模型反馈质量为“高质量”，“是否是高质量题目”也填“否”。命中提示词轮次作弊时 `prompt_quality` 填 `不合格`，`sheet.prompt_cheat` 填 `true`。

`label` 对应飞书列“label”。44期源表该列为空时，需要判断题目真实类型并填入，取值必须来自 `skills/qc-eval/config/g1_label_options.json`。推荐在 `qc_cells.json` 的 `sheet.label` 显式填写；若不填，`push_xlsx.py` 会在本地源表 label 为空时按任务名和提示词启发式补齐。源表 label 已有值时，本地交付不覆盖原值。

`category_correct` 对应飞书列“分类是否正确”，必须填“是/否”；判断源表或补齐后的 `label` 是否与任务真实类型一致。

飞书列 `质检人`、`所属商`（兼容历史错字 `所述商`）由人工/分配流程维护，质检交付脚本不得填写或上传；即使本地 `qc_cells.json` 或源表里存在这些字段，也必须在生成交付物和回写飞书时跳过。

写完 `qc_cells.json` 后，未命中提示词轮次作弊的题目，只对下载按钮可用的模型按「复测启动与截图」本人现场出图，再进入下一步交付。下载按钮禁用的模型只使用任务详情「下载列表」截图，不打开轨迹、不静态走读、不启动产物；不要复用标注人截图，也不要跳过可下载模型的复测直接 `push_xlsx.py`。命中轮次作弊时验证截图已由 `check_prompt_cheat.py` 用提示词红框生成，直接进入交付。

7. 生成本地交付物，并生成每个模型对应的平台质检填写文件。

```bash
python3 skills/qc-eval/scripts/push_xlsx.py <任务ID> --period 44期
python3 skills/qc-eval/scripts/generate_model_qc_platform.py <任务ID>
python3 skills/qc-eval/scripts/selfcheck.py <任务ID>
```

逐模型平台填写文件输出为 `delivery/<TASK_ID>/<TASK_ID>_model_qc_platform.md` 和 `delivery/<TASK_ID>/<TASK_ID>_audit_form_fill.json`，字段名、选项与 `skills/qc-eval/config/g1_audit_form.json` 一致。用户明确要求填写平台质检表单时，用 `fill_g1_audit_form.js` 写入网页并只保存草稿；未下达该指令时不要打开审核页去改表单。表单字段为：请选择该任务的质量（高/中/低/不可用）、任务质量备注、请选择该用户的反馈质量（完全可用/部分可用/完全不可用）、反馈质量备注、审核理由、请选择脏数据标签。页面没有「非脏数据」按钮，不选标签即非脏数据。反馈质量备注按档位写 1～2 句，并用飞书档位词（高质量 / 合格 / 不合格）收束；审核理由写一句事实结论，通常必须用平台选项词（完全可用 / 部分可用 / 完全不可用）收束，禁止写「故高质量」「故合格」「反馈质量为高质量」。唯一例外是产物不可下载模型：反馈质量备注和审核理由都逐字填写 `产物不可下载，无法验证`。其他场景的审核理由抽出备注里的具体问题点即可，不复制完整备注；必须包含一个简短的产物/反馈事实总结，不要只写「过程 X 分、产物 X 分和产物实测情况一致，反馈完全可用」这类评分一致套话，也不要直接压缩复述反馈质量备注。需要特殊说明时，可在模型数据下写 `platform_audit_reason` 或 `audit_reason` 覆盖默认审核理由。脏数据标签按 `spec/Coding场景脏数据标签与标准.md` 判断后映射到页面选项；可在每个模型数据下写 `dirty_tag`。未写时填写文件输出「不选」。

8. 填写平台质检表单必须听用户指令。用户明确要求“填写平台质检表单 / 保存草稿 / 写入网页质检”后，才把 `delivery/<TASK_ID>/<TASK_ID>_audit_form_fill.json` 填进 `projects/326/review/<taskModelRunId>?mode=audit` 右侧「质检」面板。脚本只改质检表单，并只点「保存草稿」。未作答模型没有审核页，脚本会记录跳过，不得伪造草稿。禁止点「提交审核」「打回」「返回列表」，禁止改「评测打分」、Session 轨迹、Workspace 或附件。提交必须留给人工检查后再点。

```bash
node skills/qc-eval/scripts/fill_g1_audit_form.js --task-id <任务ID>
# 只填一个模型、或先看填入结果不点保存：
# node skills/qc-eval/scripts/fill_g1_audit_form.js --task-id <任务ID> --only harpoon
# node skills/qc-eval/scripts/fill_g1_audit_form.js --task-id <任务ID> --dry-run
```

9. 回写飞书必须听用户指令：常规质检流程到 dry-run 为止，不得主动上传或回写飞书。只有用户明确要求“上传/回写/写入飞书”后，才执行 write；执行顺序仍必须先 dry-run，再 write。

```bash
python3 skills/qc-eval/scripts/push_g1_feishu.py <任务ID> --dry-run
python3 skills/qc-eval/scripts/push_g1_feishu.py <任务ID> --write --confirm-user-instructed
```

`push_g1_feishu.py` 会重新读取远端 `vD6HYi` 对应行的“任务”单元格，并与本地交付 xlsx 的任务名完全一致才允许写入。飞书 `label` 列只在远端单元格为空时写入；若远端已有值，即使本地交付 xlsx 有新 label 也跳过，避免覆盖人工或上游分类。飞书列“一次质检平台审核理由（按模型）”按模型分行，前缀为表头模型名加平台 codeName，例如 `0825E（harpoon）：……`。“一次质检是否完成”由人工填写，脚本不得写入。非脏数据时不要给「脏数据标签」写入空字符串；脚本会清除单元格内容。已出现「数据无效」的空下拉格，重新 `--write` 即可按同样方式清掉。

## 复测启动与截图

现场复测默认在本机起服务。不要因为仓库里有 `u03l.py` 就把每题都推到测试机。命中提示词轮次作弊时不要走下面任何产物启动路径。

### 决策

按产物形态选脚本：

| 产物形态 | 在哪启动 | 脚本 |
| --- | --- | --- |
| 提示词轮次作弊 | 不测产物 | `python3 skills/qc-eval/scripts/check_prompt_cheat.py <任务ID> --apply`。下载可用模型共用提示词截图；下载不可用模型仍用下载列表模板和截图 |
| 模型下载按钮禁用 | 该模型不质检、不启动 | `python3 skills/qc-eval/scripts/apply_download_unavailable.py <任务ID> --apply`。仅该模型使用下载列表截图并套本地模板；同题按钮可用模型继续按下列产物形态复测 |
| Vue / Vite 前端，无强制后端栈 | 本机 dev server | `node skills/qc-eval/scripts/screenshot_vue.js <任务ID>`，再 `python3 skills/qc-eval/scripts/compose.py <任务ID>` |
| Next.js / Node 前端，无强制后端栈，且用户明确要求尽量使用 u03l 或本机缺少 Chrome/FFmpeg/系统能力 | u03l 跑依赖、构建和验证；页面截图仍用本机截图脚本 | `python3 skills/qc-eval/scripts/verify_next_u03l.py <任务ID>` 生成 `tasks/<任务ID>/logs/<模型>-cli-u03l.log`，再按页面形态配置 `tasks/<任务ID>/screenshot_vue.json` 后执行 `node skills/qc-eval/scripts/screenshot_vue.js <任务ID>`、`python3 skills/qc-eval/scripts/compose_cli.py <任务ID> --no-web-from-attachments`、`python3 skills/qc-eval/scripts/compose.py <任务ID>` |
| SPA MM030 FastAPI + Vite，SQLite 可本机闭环 | 本机 uvicorn + vite | `node skills/qc-eval/scripts/screenshot_spa_mm030.js <任务ID>`，再 `python3 skills/qc-eval/scripts/compose.py <任务ID>` |
| CLI / 测试报告 | 本机 | `python3 skills/qc-eval/scripts/compose_cli.py <任务ID>`。若标注人附件中存在前端页面截图，脚本会自动先尝试运行可检测到的前端并补本人页面截图；不要只交终端图 |
| FastAPI + Vite，且依赖 Postgres / Redis / Celery | **u03l Docker** 起 PG/Redis/Celery；本机起 uvicorn + vite，经 SSH 隧道连接 | 手写 `tasks/<TASK_ID>/verify_routes.json`，`sheet.verifiable` 填 `是`，再 `python3 skills/qc-eval/scripts/verify_fullstack.py <任务ID>` |
| ASP.NET + docker-compose | **全部 Docker 命令在 u03l** | `node skills/qc-eval/scripts/screenshot_dotnet_u03l.js <任务ID>` |
| 必须在 Linux 上跑的 Vue CLI（如 ELADMIN） | u03l 上 npm / vue-cli-service | `python3 skills/qc-eval/scripts/verify_eladmin_frontend_u03l.py <任务ID>` |
| 起不来，或标成不可验证 | 本机静态走读 | `python3 skills/qc-eval/scripts/screenshot_static_walkthrough.py <任务ID>`；`verifiable` 填 `否` 并写原因 |
| 预期模型未作答 | 不复测不存在的产物 | `python3 skills/qc-eval/scripts/render_missing_model_evidence.py <任务ID>` 从采集到的模型运行列表生成缺失证据；该模型反馈质量填 `不合格` |

`verify_fullstack.py` 只看文件是否存在，不看期数。同时满足下面两条才启动全栈验证：

1. `qc_cells.json` 里 `sheet.verifiable` 为 `是`
2. 已手写 `tasks/<TASK_ID>/verify_routes.json`

缺路由文件时不要编造全栈验证，改走上表对应的本机截图路径。`verify_routes.json` 的格式见 `screenshot_fullstack_verify.js` 文件头。

### u03l 约束

- 先 `python3 skills/qc-eval/scripts/u03l.py check-host`。不可达则停，开机后再跑；禁止降级成 mock 服务后仍把 `verifiable` 写成 `是`。
- 标准全栈栈里，Docker 在 u03l 上只起 postgres / redis / celery；uvicorn 和 vite 仍在本机。
- Node/Next 项目只有在用户明确要求“尽量用 u03l”或本机确实不适合复测时，才用 `verify_next_u03l.py` 把构建和验证放到 u03l；该脚本只补测试环境和拉回日志，不修改模型产物源码。若 u03l 缺 Chrome/FFmpeg，先按环境依赖闸门补齐后复跑。
- 题目文案提到 postgres / redis / mysql / docker / celery 等服务栈，却要把 `verifiable` 标成 `否` 时，`verifiable_reason` 必须写明为何没法在 u03l / 工作机 Docker 上复测。`evidence_guard.py` 会拦截含糊理由。
- 测完执行 `python3 skills/qc-eval/scripts/u03l.py down <任务ID>`，需要时再 `python3 skills/qc-eval/scripts/tunnel.py close <任务ID>`，不要留残余容器或 SSH 隧道。

### 截图合格线

跑不通不要交白屏。换成报错终端、浏览器 console 或出错源码截图。`delivery/<TASK_ID>/screenshots/` 只留有效 PNG 和横向拼接的 `<模型>_verify.png`。`blank_guard.py` / `evidence_guard.py` / `screenshot_style_guard.py` 命中即不合格。

CLI / 测试 / 终端证据必须用等宽字体 `MONO_FONT_CANDIDATES`（macOS Menlo，Windows Consolas，Linux DejaVu Sans Mono）。禁止用冬青黑体、苹方等比例中文字体画终端图，数字 `4` 横画会发虚。`compose_cli.py` 的 `render_text_png` / `render_extra_command_png` 已按此出图；含中文说明的静态走读才用 CJK 字体。

截图中不能保留影响判断的乱码、缺字或不可读终端输出。遇到压缩包文件名编码异常、ANSI 控制符、进度条符号、绝对路径过长导致的不可读内容时，先用 `compose_cli.py` 的清洗渲染能力或手工裁剪出关键原始命令结果；保留测试通过/失败、错误类型、断言位置等判断依据，不用乱码截图作为唯一证据。

CLI / 测试 / 终端证据截图只保留与复测结论直接相关的命令输入和原始输出；不要额外加入 `command:`、`exit_code=`、`pwd`、人工标题、结论注解、本地路径说明或脚本补写的证据解释。终端面板宽度不要超过可读范围，长行必须换行，避免合成图第一张终端截图过宽。若原始命令输出包含本机绝对路径、用户名等隐私信息，截图前必须脱敏或裁剪为仓库相对路径 / `<repo>` 占位；脱敏不改变关键错误、测试结果和对比结论即可。

标注人上传了前端页面截图时，本人复测证据也必须包含现场运行产物得到的前端页面截图。即使核心结论主要来自测试命令，也应先用 `screenshot_vue.js <任务ID> --if-annotator-web` 或全栈 `verify_fullstack.py` 补页面图，再合成验证截图；只有产物确实没有可运行前端入口或前端启动失败，才改用终端错误/静态走读图说明。

质量备注里凡是写「与实际情况不符」「产物备注未记录」等与标注不一致的点，该模型验证截图必须能直接看出该事实。看不出来就补测补图，不要只靠文字。测试失败未写入标注备注时，补 `<模型>_NN_test.png`。CLI 主图看不出该事实时，不要无筛选地重跑 `compose_cli.py`（会覆盖各模型 `_01_cli.png`）。用 `compose_cli.render_extra_command_png` 补编号图，再 `python3 skills/qc-eval/scripts/compose.py <任务ID>`。`evidence_guard.py` 在备注同时写测试失败和与标注不一致时，会要求文件名含 `test` 的编号 PNG。

## 写作约束

- 备注以人工质检员口吻写，不暴露脚本化过程。
- 不使用第一人称主语，如“我跑了”“我本地”。
- 不写工程内部路径或字段名到交付备注里，如 `qc_cells.json`、`SKILL.md`。
- 题目质量说明只解释题目本身的完整性、经济价值、评测价值、可复核性和未达高质量的原因；不要写“是否是高质量题目填是/否”这类表字段自述。涉及 Coding Agent 初始 workspace 规模时，只写代码仓库体量较小、工程完整度不足、未达到高商业价值的企业软件标准等概括判断，不要写具体数字阈值、具体行数或具体代码量要求。
- 题目质量说明禁止引用测试模型的实际分数、执行过程分、产物质量分、均分或模型间实际分差。区分度结论只从题目设计本身说明，保持简洁，不要求展开考察维度、决策空间或约束细节；可直接写“但题目设计与校验标准未达到高质量题目的区分度参考要求，因此题目质量为合格”。
- 红线必须有明确证据；只有疑似、可能、看起来像时，不判红线。
- 交付备注只写平台页面上能看见的内容。G1「评测打分」可见字段是执行过程分、产物质量分、归因标签、维度备注、产出物反馈。evaluation.json / API 里即使有综合评分、总分、均分、加权分、综合分差、dimension id、字段英文名，也不要写进质量备注、题目质量说明或审核理由。
- **执行过程分和产物质量分必须分开理解。** 执行过程分评价的是测试模型做任务时的过程表现，包括需求理解、规划拆解、工具调用、代码修改、调试排错、自测充分性、迭代恢复、耗时效率、是否过早宣称完成、是否中断或卡住等；证据只能来自测试模型的运行轨迹、过程维度备注和过程归因标签。产物质量分评价的是最终交付物的页面、功能、接口、测试、构建、业务链路和用户可见结果。标注人或质检员事后复测时补依赖、清理环境、重新构建或运行测试所得的结果，只能用于判断产物质量或标注反馈是否准确，不能反推测试模型当时的执行过程。只有轨迹明确显示测试模型亲自运行测试或构建，并记录了模型如何处理结果时，该动作才可作为过程证据，例如模型忽略失败、继续排查、完成修复或错误宣称成功。反过来，看到过程备注写“测试失败还交”也不能直接认定那是标注人自己的复测；应先与模型轨迹核对，轨迹支持时按模型执行过程评价，轨迹不支持或结论冲突时只写“过程备注缺少轨迹佐证”或“与轨迹记录不符”，只有备注、附件或其他证据明确说明是事后复测时才作此归因。不要用“页面流程可走通 / 章节加载通过 / 主链路能跑 / 响应式验证通过 / 复测补齐依赖后测试通过”等产物或事后验证事实解释“执行过程 X 分相符 / 偏高 / 偏低”。只要判断执行过程分，就必须点明测试模型轨迹中的对应行为或标注过程备注与轨迹之间的出入。
- 写质量备注前必须对照归因标签、维度备注和实际情况，不要只看分数和总评。标签是标注人评价的一部分；所选标签符合实际且备注没有相反矛盾描述时，备注未展开标签不算错选。只有标签本身不符合实测，或标签是缺陷项但备注明确写成相反好评时，才属于标签错选：反馈质量最高合格，备注要点名哪一维标签与备注或实测不符。分数可以仍与产物相符。漏写时 `selfcheck.py` 会拦截；高质量档遇到标签错选也会拦截。
- 质量备注写 **1～2 句**，不要写成复核说明书。必须写出页面上的过程分 / 产物分（轮次作弊和产物不可下载固定模板除外）。产物不可下载模型的质量备注只能写 `产物不可下载，无法验证`。同一题各模型可以共用同一开头；**连续几题不要沿用同一句首**（`selfcheck.py` 对照最近 3 题）。没有过程/产物分时，不要用 API 里的聚合分顶替。产物起句不要只扔命令名或字段名，同一句里写清是缺陷还是正常。
- 质量备注正文不要直接写表格模型名或平台 codeName，例如不要写某个表头代号或平台内部代号。因表格与平台对同一模型使用的代号不同，正文统一写「这个模型」「该测试模型」「这个模型的产物」「该测试模型产物」等自然指代；`qc_cells.json` 的 `sheet.models` key、平台填写文件标题、URL、截图文件名等结构字段仍保留原代号。
- 反馈质量备注评的是**标注人作业**，不是给模型写产品说明。按下面三档写短句，不要为凑三拍或四条高质量指标把备注拉长。不要写「标注指出」「标注写：」冒号短句，改用「标注人备注」。不要写「标注轨迹」。**转述标注人意思时不要加引号**（包括 “” 和 「」）；只有逐字引用原句才用引号。`selfcheck.py` 命中弯引号即不合格。命中提示词轮次作弊时，下载可用模型备注只陈述该轮次作弊行为，并写明反馈质量不合格；对应审核理由写反馈完全不可用。下载不可用模型只使用产物不可下载模板。
- **两套档位词不要混用。** 飞书「反馈质量」、`rating`、质量备注 `note` 用 `高质量` / `合格` / `不合格`。平台「请选择该用户的反馈质量」、`platform_audit_reason`、飞书「一次质检平台审核理由」通常用 `完全可用` / `部分可用` / `完全不可用`；产物不可下载模型的质量备注和审核理由固定为 `产物不可下载，无法验证`，不追加档位词。审核理由禁止写「故高质量」「故合格」「故不合格」「反馈质量为高质量」。
- **档位理由必须写清，且保持短句。** 复核人只看质量备注和审核理由，就要知道本条为什么落在该档。禁止只复述模型卡死、花屏、报错而不提标注打分对不对。
  - `高质量` / `完全可用`：用「执行过程和产物质量分别与实际情况一致，评分正确」收束。不要再列一项仍构成合格档的偏差。
  - `合格` / `部分可用`：写清和实际情况一致或不符合的地方，并点名具体偏差。若分数有偏差，写明哪一项评分偏高或偏低；若分数均相符，但过程备注错误地混入标注人事后复测结果，也可点明该备注不符合维度范围。判断执行过程分时必须使用测试模型执行过程证据或标注过程备注与轨迹的出入，不能使用标注人复测、补依赖、清理环境、页面或最终测试结果。标签错选时分数可仍写相符，但必须点名标签与备注或实测不符；标签成立且备注未矛盾时不要因备注未展开标签而降档。只写「卡死和 1 分相符」会读成高质量。
  - `不合格` / `完全不可用`：点名红线、完全不可信；按脏数据标签补一句，例如敷衍恶意打分、AI 打分、轮次作弊、用户切换模型错误。
- 主语要分开：模型交付报告 / 标注备注 / 质检结论。不要单独写「报告声称」，以免读成标注人的话。不要写「标注人在备注中记录……，与备注相符」：前半句已在说备注内容，后半句缺主语且自己和自己相符。列举备注要点最多写两点再加「等」，收束写成「实际情况与备注相符」，或写明谁与谁相符（例如「产物 8 分与备注相符」）。`selfcheck.py` 命中句首或逗号、句号后紧跟「与备注相符」「与反馈相符」即不合格。
- 分数与实测是否对齐，写「相符 / 不符」，不要写「同向」。评分相对实测是高了还是低了，写「偏高 / 偏低」，不要写「偏严 / 偏松」。
- 不要用「缺口」。缺功能、缺控件、没写全，改写成「缺陷」「缺失」「问题」或「不完整」。`selfcheck.py` 命中「缺口」即不合格。
- 平台审核理由写一句事实结论，并点出档位原因，例如“产物 9 分偏高，反馈部分可用”“构建失败但标注给满分，反馈完全不可用”。不能只写“存在偏差”“证据不完整”。不要复制反馈质量备注全文。同一题可以共用句式；连续几题不要沿用同一句首。优先手写 `platform_audit_reason`。产物不可下载是固定模板例外，审核理由直接写 `产物不可下载，无法验证`。
- 高质量档用「执行过程和产物质量分别与实际情况一致，评分正确」收束即可，不要为凑数据完整、可复现、模型洞察、业务影响四条把备注写成长文。
- 禁止档位套话和空评价：`站得住`、`高一档`、`低一档`、`略高一档`、`偏高一档`、`方向对`、`方向到位`、`判断成立`、`评分方向合理`、`完全吻合`、`标签成立`、`偏薄`、`兜底`、`更稳`、`抓得准`、`缺口`。改成具体事实，例如“产物 6 分偏高，核心战斗进不去”。
- 禁止口语化对照词，改成书面判断用语（`selfcheck.py` 命中即不合格）：`说得通`→`合理`；`对得上` / `能对上` / `全对上`→`与…相符` 或 `一致`；`对不上`→`不符` 或 `不一致`；`同向`→`相符`；`偏松`→`偏高`；`偏严`→`偏低`；`写重了` / `过重` / `偏重` / `说得过头`→`与实际情况不符`；`仍在`→`与实际情况相符`；`可核` / `也可核` / `能核`→`和实际验证结果相符`；`抬上去了` / `抬在`→`得益于`；`没有抬`→`未虚高`；`缺口`→`问题` / `缺陷` / `缺失` / `不完整`。不要写「未写反」，过程分和产物分要分别写清相符、偏高或偏低。标注写对了就写「与实际情况相符」，写错了就写「与实际情况不符」，不要用「仍在」「说得过头」「可核」。
- 机器词表在 `skills/qc-eval/config/writing_style.json`，`selfcheck.py` 命中即不合格。参考表 `docs/描述语言参考.xlsx` 里也会出现「属实」「站得住」等过期套话，只学句式，不要把这些词写进交付。

### 句式模版（按档位写短句，连续题换开头）

写 `note` 时按档位套短语，**1～2 句**，不要按场景堆 20 种开头。同一题各模型可以共用同一开头；连续几题不要沿用同一句首。质量备注用飞书档位词收束；`platform_audit_reason` 另写一句，用平台选项词收束。完整列表在 `skills/qc-eval/config/writing_style.json` 的 `opening_families`。

| 档位 | 质量备注怎么写 | 审核理由收束 |
| --- | --- | --- |
| 高质量 | 执行过程和产物质量分别与实际情况一致，评分正确 | 反馈完全可用 |
| 合格 | 写出和产物实际情况一致或不符合的地方，并点名哪一项评分偏高或偏低；标签错选时分数可仍写相符，但必须点名标签与备注或实测不符；标签成立且备注未矛盾时不要因备注未展开标签而降档 | 反馈部分可用 |
| 不合格 | 点名红线、完全不可信，并按脏数据标签写一句 | 反馈完全不可用 |

例句（把本题事实换进去，不要照抄前 8 字）：

1. 高质量 / 打分先行：标注人给执行过程 8 分、产物质量 8 分，测试模型的执行轨迹和最终产物分别与对应备注一致，评分正确，反馈质量为高质量。
2. 高质量 / 实测先行：主页面能开、主链路能走完，模型执行过程也无明显异常，和标注一致。过程 9 分、产物 9 分评分正确，反馈质量为高质量。
3. 合格 / 产物偏高：标注人给执行过程 8 分相符、产物质量 9 分偏高。主页面能开但关键编辑无法保存，反馈质量为合格。
4. 合格 / 产物偏低：模型执行过程多轮排查和自测较充分，过程 7 分相符；服务起不来和标注备注一致，但产物质量 4 分偏低，反馈质量为合格。
5. 合格 / 过程偏低：模型执行过程中完成根因定位、修复和自测，标注人备注写自测不充分与实际执行过程不符。过程 3 分偏低，产物 2 分相符，反馈质量为合格。
6. 合格 / 标签错选：过程 8 分相符，产物 8 分相符，但过程标签自测不充分和标注人备注比较充分不符，反馈质量为合格。
7. 不合格 / 敷衍恶意打分：标注评语空泛、各模型串同一张图，属敷衍恶意打分，结论不可信。反馈质量为不合格。
8. 不合格 / AI 打分：标注人员明确说明提交的评分与评价由 AI 生成，触发 AI 评价红线，反馈质量为不合格。
9. 不合格 / 低质量任务：提示词要求模型工具轮次达到 450，属轮次作弊红线，本题不再核产物。反馈质量为不合格。
10. 不合格 / 切换模型：标注按本模型独立完成来打分，轨迹前段与他模型雷同，属用户切换模型错误，结论不可信。反馈质量为不合格。

其他脏数据标签按同一句式补一句即可，例如 API 超时、OpenClaw/Hermes、LLM 测 VLM。审核理由不要抄「反馈质量为…」，改写成：执行过程和产物质量分别与实际情况一致，评分正确，反馈完全可用。 / 产物 9 分偏高，反馈部分可用。 / 标注空评且串图，属红线，反馈完全不可用。

## 关键约束

1. 质检相关动作只走本技能列出的集中脚本，不直接调底层 API 或 lark-cli。
2. 本仓库当前默认飞书交付目标为 `sheet=vD6HYi`。源表只读本地 `docs/44.xlsx`。
3. 自动流程只生成本地文件；飞书回写只能在用户明确下达上传/回写指令后，通过显式 push 命令执行。用户只说“质检 <任务ID>”时，不得执行 `--write`。平台质检表单同样：只有用户明确要求填写网页表单后才运行 `fill_g1_audit_form.js`；该脚本只能保存草稿，不能提交。
4. 截图必须是本人复测证据，不能复用标注人的截图；`delivery/<TASK_ID>/screenshots/` 只保留有效截图 PNG（如 `<模型>_01_cli.png`）和合成图 PNG（`<模型>_verify.png`），不要保留 `log.txt`、临时图、别名图或其他辅助文件。合成图必须按左右横向拼接原图，禁止上下纵向拼接；若只有一张有效截图，则直接复用该原图作为 `<模型>_verify.png`。提示词轮次作弊时，下载可用模型共用提示词红框图，文件名用 `<模型>_01_prompt_cheat.png`；下载不可用模型使用 `<模型>_01_download_blocker.png`。
5. `delivery/<TASK_ID>/<TASK_ID>.xlsx` 必须从空白 workbook 重建，只包含表头行和该任务行。
6. `.ark_platform_state.json`、本地探测缓存和登录态文件不能提交。
7. 流程脚本未调通、出现未配置额外模型、首轮「上传产物」未完整下载/检查、或已完成模型的「下载列表」采不到时，停下来与人工核对，不要继续编造材料。44期预期模型缺失不属于模型集异常，但必须有 `missing=true` 和缺失证据。两类产物必须分别判断，任何一方为空都不能推断另一方为空。命中提示词轮次作弊时仍保留前置下载按钮判定：下载不可用模型用下载阻断模板，下载可用模型用提示词作弊模板；两类模型都跳过 workspace / 轨迹和产物复测。
8. 提示词轮次作弊必须在页面提示词和首轮上传产物中的 Markdown/文本全部收集后、复测模型产物之前判定。禁止只看页面 Prompt，或先测完模型产物再补判作弊。
9. 填写平台质检表单时只改右侧「质检」面板，只点「保存草稿」。禁止提交审核、打回，也禁止改评测打分或其他页签。
10. 写反馈质量前必须对照评测打分的归因标签、维度备注和实际情况。标签是标注人评价的一部分；标签成立且备注没有相反矛盾描述时，不因备注未展开标签降档。标签错选不能定高质量，质量备注必须点名标签与备注或实测不符。
11. 每题必须先按模型检查任务详情「下载列表」按钮。某模型“产物不可下载”只由该模型下载按钮禁用来判定，并由 `download_list_discover.json` 留存机器可读证据；该模型使用 `apply_download_unavailable.py` 和 `config/artifact_download_unavailable.json`，不再检查轨迹、标注或产物。部分模型不可下载时，只跳过并套用这些模型，其余可下载模型照常质检；状态未知时整题停止。不要再查历史飞书表，也不要把按钮禁用改判为 Workspace 为空、产物无法启动或反馈红线。

## 常用命令

```bash
python3 skills/qc-eval/scripts/probe_g1_task_ids.py --task-id <任务ID>
node skills/qc-eval/scripts/fetch_g1_platform.js auth-from-chrome
# 默认使用 Chrome 的 quan-134 个人资料（Profile 4）
# 或：node skills/qc-eval/scripts/fetch_g1_platform.js auth-login
# 每题强制先检查逐模型下载按钮；状态未知时停止：
node skills/qc-eval/scripts/fetch_g1_platform.js discover-download --task-id <任务ID>
node skills/qc-eval/scripts/fetch_g1_platform.js collect --task-id <任务ID>
python3 skills/qc-eval/scripts/extract_g1_workspaces.py <任务ID>
python3 skills/qc-eval/scripts/check_prompt_cheat.py <任务ID>
# 建好题目级 qc_cells 后，对按钮禁用模型应用模板；按钮可用模型继续正常质检：
python3 skills/qc-eval/scripts/apply_download_unavailable.py <任务ID>
python3 skills/qc-eval/scripts/apply_download_unavailable.py <任务ID> --apply
# 命中轮次作弊时用 --apply 写 qc_cells 并出提示词红框截图，跳过下面的产物复测：
# python3 skills/qc-eval/scripts/check_prompt_cheat.py <任务ID> --apply
# 写 qc_cells 前对照归因标签、维度备注和实际情况；只有标签不符合实测或与备注矛盾才算错选：
python3 skills/qc-eval/scripts/check_annotator_tags.py <任务ID>
# 若 model_map.json 有 missing=true，生成未作答模型的平台列表证据：
python3 skills/qc-eval/scripts/render_missing_model_evidence.py <任务ID>
# 复测截图按「复测启动与截图」选题型，不要一律上 u03l：
# node skills/qc-eval/scripts/screenshot_vue.js <任务ID>
# python3 skills/qc-eval/scripts/compose.py <任务ID>
# python3 skills/qc-eval/scripts/verify_next_u03l.py <任务ID>
# python3 skills/qc-eval/scripts/compose_cli.py <任务ID>
# python3 skills/qc-eval/scripts/u03l.py check-host
# python3 skills/qc-eval/scripts/verify_fullstack.py <任务ID>
python3 skills/qc-eval/scripts/push_xlsx.py <任务ID> --period 44期
python3 skills/qc-eval/scripts/generate_model_qc_platform.py <任务ID>
python3 skills/qc-eval/scripts/selfcheck.py <任务ID>
# 用户明确要求填写平台质检表单后才可执行；只保存草稿，不提交：
node skills/qc-eval/scripts/fill_g1_audit_form.js --task-id <任务ID>
python3 skills/qc-eval/scripts/push_g1_feishu.py <任务ID> --dry-run
# 用户明确要求上传/回写飞书后才可执行：
python3 skills/qc-eval/scripts/push_g1_feishu.py <任务ID> --write --confirm-user-instructed
```

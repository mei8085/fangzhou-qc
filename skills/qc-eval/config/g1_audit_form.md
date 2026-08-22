# G1-new 平台质检表单模版

来源：[review/12232?mode=audit](https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/projects/277/review/12232?mode=audit)（任务 4267 / harrier）。

机器可读副本：`skills/qc-eval/config/g1_audit_form.json`。

质检完成后由 `python3 skills/qc-eval/scripts/generate_model_qc_platform.py <TASK_ID>` 生成填写文件：

- `delivery/<TASK_ID>/<TASK_ID>_model_qc_platform.md`
- `delivery/<TASK_ID>/<TASK_ID>_audit_form_fill.json`

每个模型打开：`https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/projects/277/review/<taskModelRunId>?mode=audit`，右侧切到「质检」。

---

## 右侧「评测打分」（只读，标注人已提交）

不是质检要填的表单。采集时已写入各模型 `evaluation.json`。

- 执行过程 1–10 + 归因标签 + 维度备注
- 执行产物 1–10 + 归因标签 + 维度备注
- 产出物反馈

页面没有综合评分、总分、均分等聚合分。API / `evaluation.json` 里若出现这些字段，不要写进交付备注。

## 右侧「质检」（要填）

### 请选择该任务的质量 *必填

高 / 中 / 低 / 不可用

五个模型共用同一判定。飞书「任务质量（题目质量）」映射：高质量→高，合格→中，不合格/红线→不可用。

### 任务质量备注

占位：请输入备注

### 请选择该用户的反馈质量 *必填

完全可用 / 部分可用 / 完全不可用

飞书「反馈质量（作业质量）」映射：高质量→完全可用，合格→部分可用，不合格/红线→完全不可用。

### 反馈质量备注

占位：请输入备注

### 审核理由 *必填

占位：例如：响应内容偏离任务要求 / 输出代码可直接运行 / 触及红线敏感词...

### 请选择脏数据标签

可多选。页面没有「非脏数据」按钮，不选即非脏数据。

飞书「【G1】Sxxx脏数据标签」下拉原文（无空格、半角冒号）为：`模型资源问题:API请求超时/轨迹大量error`、`OpenClaw/Hermes框架问题`、`用户问题:低质量任务`、`用户问题:敷衍恶意打分`、`用户问题:AI打分/AI评价`、`用户问题:用户切换模型错误`、`用户问题:LLM任务测试VLM能力`、`其他`。飞书非脏数据留空，不要填「非脏数据」。

- 模型资源问题：API 请求超时 / 轨迹大量 error
- OpenClaw/Hermes框架问题
- 用户问题：低质量任务
- 用户问题：敷衍恶意打分
- 用户问题：AI 打分 / AI 评价
- 用户问题：用户切换模型错误
- 用户问题：LLM任务测试VLM能力
- 其他

底部按钮：返回列表 / 保存草稿 / 打回 / 提交审核

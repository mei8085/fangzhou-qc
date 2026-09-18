const assert = require('node:assert/strict');
const { classifyAiQcPanel } = require('../probe_g1_ai_feedback');

const normal = classifyAiQcPanel(`
  AI 轨迹质检
  质检通过
  合格
  AI 判断：反馈内容具体，判定为合格
`);
assert.deepEqual(normal, { available: true, reason: '' });

for (const text of [
  '结果待复核 重试耗尽，人工兜底 AI 判断：provider_job_stuck',
  '重试耗尽，人工兜底',
  '脏数据状态未知',
  'AI 轨迹质检',
]) {
  const state = classifyAiQcPanel(text);
  assert.equal(state.available, false, text);
  assert.ok(state.reason, text);
}

console.log('AIQC platform-state tests passed');

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  evaluationRedlineReport,
  isLowDiscrimination,
  numericScore,
} = require('../fetch_36_platform');

function modelScores(process, artifact) {
  return {
    '执行过程': process,
    '产物质量': artifact,
  };
}

function completeModels(scores = [9, 9, 9, 10]) {
  return Object.fromEntries(scores.map((score, index) => [
    `model-${index}`,
    { scores: modelScores(score, score) },
  ]));
}

function writeEvaluation(taskDir, runId, codeName, dimensions) {
  const runDir = path.join(taskDir, `${runId}__${codeName}`);
  fs.mkdirSync(runDir, { recursive: true });
  fs.writeFileSync(
    path.join(runDir, 'evaluation.json'),
    JSON.stringify({
      evaluation: {
        dimensionResults: dimensions.map((score, index) => ({
          dimensionId: index + 1,
          score,
          remark: '已说明实现结果并完成验证',
        })),
      },
      dictionaries: {
        dimensions: [
          { id: 1, name: '执行过程' },
          { id: 2, name: '产物质量' },
        ],
        tags: [],
      },
    }),
  );
}

function buildReport({ modelCount = 4, dimensionsFor = () => [9, 9] } = {}) {
  const taskDir = fs.mkdtempSync(path.join(os.tmpdir(), 'qc-evaluation-redline-'));
  const rows = Array.from({ length: modelCount }, (_, index) => ({
    modelRun: {
      taskModelRunId: 1000 + index,
      codeName: `model-${index}`,
    },
  }));
  rows.forEach((row, index) => {
    writeEvaluation(
      taskDir,
      row.modelRun.taskModelRunId,
      row.modelRun.codeName,
      dimensionsFor(index),
    );
  });
  return evaluationRedlineReport(rows, taskDir, { models: [] });
}

test('requires all four complete model score pairs', () => {
  assert.equal(numericScore(null), null);
  assert.equal(numericScore(''), null);
  assert.equal(numericScore('9'), 9);
  assert.equal(isLowDiscrimination(completeModels(), [9, 9, 9, 9, 9, 9, 10, 10]), true);
  assert.equal(isLowDiscrimination(
    Object.fromEntries(Object.entries(completeModels()).slice(0, 3)),
    [9, 9, 9, 9, 9, 9],
  ), false);
  assert.equal(isLowDiscrimination({
    ...completeModels(),
    'model-0': { scores: modelScores(null, 9) },
  }, [9, 9, 9, 9, 9, 9, 10, 10]), false);
  assert.equal(isLowDiscrimination(completeModels(), [9, 9, 9, 9, 9, 9, 10]), false);
});

test('reports a complete four-model high-score set as low discrimination', () => {
  const report = buildReport({
    dimensionsFor: (index) => index === 3 ? [10, 10] : [9, 9],
  });
  assert.equal(report.triggered, true);
  assert.equal(report.classification, 'task_discrimination_too_low');
  assert.equal(report.scores.submitted_model_count, 4);
  assert.equal(report.scores.complete_score_model_count, 4);
});

test('does not report low discrimination when one model lacks a dimension', () => {
  const report = buildReport({
    dimensionsFor: (index) => index === 3 ? [10] : [9, 9],
  });
  assert.equal(report.triggered, false);
  assert.equal(report.classification, '');
  assert.equal(report.scores.submitted_model_count, 4);
  assert.equal(report.scores.complete_score_model_count, 3);
});

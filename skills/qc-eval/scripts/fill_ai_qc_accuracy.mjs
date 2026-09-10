#!/usr/bin/env node
/**
 * Fill the dynamic AI trajectory-QC accuracy columns in a task delivery workbook.
 *
 * The script is intentionally narrow: it only changes the discovered AI accuracy
 * columns whose
 * headers follow the "模型N..." pattern. It does not rebuild the
 * workbook, alter formulas/styles, or touch any other task-QC fields.
 *
 * Usage:
 *   node skills/qc-eval/scripts/fill_ai_qc_accuracy.mjs --task-id 8818
 *   node skills/qc-eval/scripts/fill_ai_qc_accuracy.mjs --task-id 8818 --write
 */

import fsSync from "node:fs";
import os from "node:os";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..", "..");

const AI_ACCURACY_HEADER_RE = /^模型([1-9]\d*)(质检结论是否准确|判断原因)$/;
const MODEL_RATING_SUFFIX = "反馈质量（作业质量）";

function parseArgs(argv) {
  const opts = {
    taskId: "",
    answers: "",
    xlsx: "",
    source: "",
    sheet: "",
    write: false,
  };
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--task-id") opts.taskId = argv[++i] || "";
    else if (arg === "--answers") opts.answers = argv[++i] || "";
    else if (arg === "--xlsx") opts.xlsx = argv[++i] || "";
    else if (arg === "--source") opts.source = argv[++i] || "";
    else if (arg === "--sheet") opts.sheet = argv[++i] || "";
    else if (arg === "--write") opts.write = true;
    else if (!opts.taskId && !arg.startsWith("--")) opts.taskId = arg;
    else throw new Error(`unknown argument: ${arg}`);
  }
  if (!opts.taskId) {
    throw new Error(
      "usage: fill_ai_qc_accuracy.mjs --task-id <任务ID> " +
      "[--source <xlsx>] [--sheet <sheet>] [--answers <json>] [--xlsx <xlsx>] [--write]",
    );
  }
  return opts;
}

function readJson(file) {
  return JSON.parse(fsSync.readFileSync(file, "utf8"));
}

function resolveRepoPath(value) {
  return path.isAbsolute(value) ? value : path.join(REPO_ROOT, value);
}

function configuredSourceSheet() {
  const configPath = path.join(REPO_ROOT, "skills", "qc-eval", "config", "g1.json");
  try {
    return String(readJson(configPath).source_sheet || "Sheet1");
  } catch (_) {
    return "Sheet1";
  }
}

function configuredSourcePath() {
  const configPath = path.join(REPO_ROOT, "skills", "qc-eval", "config", "g1.json");
  try {
    return String(readJson(configPath).source_xlsx || path.join("docs", "g4.xlsx"));
  } catch (_) {
    return path.join("docs", "g4.xlsx");
  }
}

function selectWorksheet(workbook, requestedName) {
  if (requestedName) {
    try {
      return workbook.worksheets.getItem(requestedName);
    } catch (error) {
      throw new Error(`source sheet not found: ${requestedName}`);
    }
  }
  return workbook.worksheets.getItemAt(0);
}

async function loadArtifactTool() {
  const candidateModules = [
    process.env.CODEX_NODE_MODULES,
    path.join(
      os.homedir(),
      ".cache",
      "codex-runtimes",
      "codex-primary-runtime",
      "dependencies",
      "node",
      "node_modules",
    ),
  ].filter(Boolean);
  const requireFromScript = createRequire(import.meta.url);
  const candidates = [
    () => requireFromScript.resolve("@oai/artifact-tool"),
    ...candidateModules.map((dir) => () => {
      const requireFromBundle = createRequire(path.join(dir, "__artifact_loader.cjs"));
      return requireFromBundle.resolve("@oai/artifact-tool");
    }),
  ];
  for (const resolve of candidates) {
    try {
      return await import(pathToFileURL(resolve()).href);
    } catch (_) {
      // Try the next configured runtime location.
    }
  }
  throw new Error(
    "找不到 @oai/artifact-tool。请使用 Codex 工作区依赖中的 Node.js 运行此脚本，" +
    "或设置 CODEX_NODE_MODULES 指向 bundled node_modules。",
  );
}

function cellText(value) {
  return value == null ? "" : String(value);
}

function normalizeGrade(value) {
  const grade = cellText(value).trim();
  if (!["高质量", "合格", "不合格"].includes(grade)) {
    throw new Error(`invalid QC grade ${JSON.stringify(grade)}`);
  }
  return grade;
}

function expectedAccuracy(humanGrade, aiGrade) {
  const human = normalizeGrade(humanGrade);
  const ai = normalizeGrade(aiGrade);
  // AI cannot decide the artifact-dependent distinction between 合格 and
  // 高质量. A human 合格/高质量 with AI 合格 is therefore accurate.
  if (human === ai || (ai === "合格" && ["合格", "高质量"].includes(human))) {
    return "是";
  }
  return "否";
}

function expectedPlatformAccuracy(sheetAccuracy) {
  return sheetAccuracy === "是" ? "准确" : "不准确";
}

function isIncompleteAudit(audit) {
  const trajectory = audit?.aiQc?.trajectoryResult;
  return !trajectory
    || trajectory.status !== "success"
    || !trajectory.resultJson?.FeedbackGrade;
}

function platformAccuracy(sheet, expected) {
  const supplied = sheet.platformAccuracy;
  if (supplied && supplied !== expected) {
    throw new Error(
      `${sheet.model}: platform accuracy ${JSON.stringify(supplied)} ` +
      `does not match grade comparison (${expected})`,
    );
  }
  return expected;
}

function loadAnswers(file, modelOrder, gradeEvidence, modelCount) {
  const data = readJson(file);
  const source = data.models || data;
  const mapping = data.mapping || {};
  const answers = [];
  for (let i = 0; i < modelCount; i += 1) {
    const position = `模型${i + 1}`;
    const model = modelOrder[i] || mapping[position];
    if (!model) throw new Error(`answers missing mapping for ${position}`);
    const answer = source[model] || source[position];
    if (!answer) {
      if (gradeEvidence[model] && !gradeEvidence[model].complete) {
        answers.push({
          position,
          model,
          platformAccuracy: "",
          platformReason: "",
          sheetAccuracy: "否",
          sheetReason: "AI质检未完成",
        });
        continue;
      }
      throw new Error(`answers missing ${model}`);
    }
    const platformAccuracyValue = cellText(answer.accuracy || answer.platform_accuracy).trim();
    const platformReason = cellText(answer.platform_reason || answer.reason).trim();
    const sheetAccuracy = cellText(
      answer.sheet_accuracy || answer.local_accuracy || (
        platformAccuracyValue === "准确" ? "是"
          : platformAccuracyValue === "不准确" ? "否" : ""
      ),
    ).trim();
    const sheetReason = cellText(
      answer.sheet_reason || answer.local_reason || platformReason,
    ).trim();
    if (platformAccuracyValue && !["准确", "不准确"].includes(platformAccuracyValue)) {
      throw new Error(`${model}: platform accuracy must be 准确 or 不准确`);
    }
    if (sheetAccuracy && !["是", "否"].includes(sheetAccuracy)) {
      throw new Error(`${model}: sheet_accuracy must be 是 or 否`);
    }
    if (sheetReason.length > 500) {
      throw new Error(`${model}: sheet_reason must be at most 500 characters`);
    }
    if (platformReason.length > 500) {
      throw new Error(`${model}: platform reason must be at most 500 characters`);
    }
    if (sheetReason && /AI.*(?:未直接判断|无法判断).*产物|不影响其对轨迹反馈/.test(sheetReason)) {
      throw new Error(`${model}: sheet_reason contains internal AI-rule wording`);
    }
    answers.push({
      position,
      model,
      platformAccuracy: platformAccuracyValue,
      platformReason,
      sheetAccuracy,
      sheetReason,
    });
  }
  return answers;
}

function loadGradeEvidence(taskId, modelMap, qcCells) {
  const models = qcCells?.sheet?.models || {};
  const evidence = {};
  for (const [sheet, row] of Object.entries(modelMap.models || {})) {
    const modelQc = models[sheet];
    if (!modelQc) throw new Error(`qc_cells.json missing model ${sheet}`);
    const incompleteEvidence = {
      complete: false,
      humanGrade: normalizeGrade(modelQc.rating),
      aiGrade: "",
      workbookAccuracy: "否",
    };
    if (!row.task_model_run_id || row.missing || row.artifact_missing) {
      evidence[sheet] = incompleteEvidence;
      continue;
    }
    const auditPath = path.join(
      REPO_ROOT,
      "tasks",
      taskId,
      "ark_g1",
      `${row.task_model_run_id}__${row.platform}`,
      "audit.json",
    );
    if (!fsSync.existsSync(auditPath)) {
      evidence[sheet] = incompleteEvidence;
      continue;
    }
    const audit = readJson(auditPath);
    if (isIncompleteAudit(audit)) {
      evidence[sheet] = incompleteEvidence;
      continue;
    }
    const aiGrade = audit.aiQc.trajectoryResult.resultJson.FeedbackGrade;
    const workbookAccuracy = expectedAccuracy(modelQc.rating, aiGrade);
    evidence[sheet] = {
      complete: true,
      humanGrade: normalizeGrade(modelQc.rating),
      aiGrade: normalizeGrade(aiGrade),
      workbookAccuracy,
    };
  }
  return evidence;
}

function getHeaderMap(values) {
  const headers = values[0] || [];
  const map = new Map();
  headers.forEach((value, index) => map.set(cellText(value), index));
  return map;
}

function modelNamesFromHeaders(headers) {
  return [...headers.entries()]
    .filter(([header]) => cellText(header).endsWith(MODEL_RATING_SUFFIX))
    .sort(([, left], [, right]) => left - right)
    .map(([header]) => cellText(header).slice(0, -MODEL_RATING_SUFFIX.length));
}

function validateTargetHeaders(headers, expectedModelCount = null) {
  const found = new Map();
  for (const header of headers.keys()) {
    const match = cellText(header).trim().match(AI_ACCURACY_HEADER_RE);
    if (!match) continue;
    const position = Number(match[1]);
    found.set(position, {
      ...(found.get(position) || {}),
      [match[2]]: header,
    });
  }
  if (!found.size) {
    if (expectedModelCount == null) return null;
    throw new Error(
      `AI准确性字段不完整：目标表缺少字段，按源表 ${expectedModelCount} 个模型应有 ` +
      `${expectedModelCount * 2} 个字段`,
    );
  }

  const detectedModelCount = [...headers.keys()]
    .filter((header) => cellText(header).endsWith(MODEL_RATING_SUFFIX))
    .length;
  const modelCount = expectedModelCount ?? detectedModelCount;
  const expectedPositions = Array.from(
    { length: modelCount },
    (_, index) => index + 1,
  );
  const errors = [];
  if (modelCount === 0) {
    errors.push("源表未检测到模型反馈质量列，无法确定模型数量");
  }
  const missingPositions = expectedPositions.filter((position) => !found.has(position));
  const extraPositions = [...found.keys()]
    .filter((position) => position > modelCount)
    .sort((a, b) => a - b);
  if (missingPositions.length) {
    errors.push(`缺少模型位置：${missingPositions.map((position) => `模型${position}`).join("、")}`);
  }
  if (extraPositions.length) {
    errors.push(
      `存在超出模型数量的字段：${extraPositions.map((position) => `模型${position}`).join("、")}`,
    );
  }

  const pairs = new Map();
  for (const position of expectedPositions) {
    const pair = found.get(position) || {};
    const missingKinds = ["质检结论是否准确", "判断原因"]
      .filter((kind) => !pair[kind]);
    if (missingKinds.length) {
      errors.push(
        `模型${position}缺少：${missingKinds.map((kind) => `模型${position}${kind}`).join("、")}`,
      );
    } else {
      pairs.set(position, {
        accuracy: pair["质检结论是否准确"],
        reason: pair["判断原因"],
      });
    }
  }
  if (errors.length) {
    throw new Error(
      `AI准确性字段不完整：按表中检测到 ${modelCount} 个模型，应有 ${modelCount * 2} 个字段；` +
      errors.join("；"),
    );
  }
  return { modelCount, positions: expectedPositions, pairs };
}

function findTaskRow(values, taskId, taskIdColumn) {
  for (let row = 1; row < values.length; row += 1) {
    if (cellText(values[row][taskIdColumn]).trim() === String(taskId)) return row;
  }
  throw new Error(`task row ${taskId} not found in workbook`);
}

async function main() {
  const opts = parseArgs(process.argv);
  const { FileBlob, SpreadsheetFile } = await loadArtifactTool();
  const taskDir = path.join(REPO_ROOT, "tasks", opts.taskId);
  const sourcePath = resolveRepoPath(
    opts.source || process.env.QC_SOURCE_XLSX || configuredSourcePath(),
  );
  const sourceSheetName = opts.sheet || process.env.QC_SOURCE_SHEET || configuredSourceSheet();
  const answersPath = resolveRepoPath(
    opts.answers || path.join("tasks", opts.taskId, "ai_feedback_answers.json"),
  );
  const xlsxPath = resolveRepoPath(
    opts.xlsx || path.join("delivery", opts.taskId, `${opts.taskId}.xlsx`),
  );
  if (!fsSync.existsSync(sourcePath)) {
    throw new Error(`source xlsx not found: ${sourcePath}`);
  }
  const sourceWorkbook = await SpreadsheetFile.importXlsx(await FileBlob.load(sourcePath));
  const sourceSheet = selectWorksheet(sourceWorkbook, sourceSheetName);
  const sourceHeaders = getHeaderMap(sourceSheet.getUsedRange().values);
  const sourceTargetHeaders = validateTargetHeaders(sourceHeaders);
  if (!sourceTargetHeaders) {
    console.log(`==> ${opts.taskId} 源表不包含 AI 准确性字段，跳过填充且不新增字段`);
    return;
  }
  const sourceModelOrder = modelNamesFromHeaders(sourceHeaders);
  if (sourceModelOrder.length !== sourceTargetHeaders.modelCount) {
    throw new Error(
      `源表模型数量解析错误：模型反馈质量列 ${sourceModelOrder.length} 个，` +
      `AI 准确性字段要求 ${sourceTargetHeaders.modelCount} 个`,
    );
  }

  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(xlsxPath));
  const sheet = workbook.worksheets.getItemAt(0);
  const valuesBefore = sheet.getUsedRange().values;
  const headersBefore = getHeaderMap(valuesBefore);
  const targetHeaders = validateTargetHeaders(
    headersBefore,
    sourceTargetHeaders.modelCount,
  );

  const mapPath = path.join(taskDir, "model_map.json");
  const qcCellsPath = path.join(taskDir, "qc_cells.json");
  const answersData = readJson(answersPath);
  const modelMap = readJson(mapPath);
  const qcCells = readJson(qcCellsPath);
  const modelOrder = [
    ...sourceModelOrder,
    ...(modelMap.sheet_columns || []),
    ...Object.keys(modelMap.models || {}),
    ...Object.values(answersData.mapping || {}),
  ].filter((model, index, models) => model && models.indexOf(model) === index);
  const gradeEvidence = loadGradeEvidence(opts.taskId, modelMap, qcCells);
  const answers = loadAnswers(
    answersPath,
    modelOrder,
    gradeEvidence,
    targetHeaders.modelCount,
  );

  let values = sheet.getUsedRange().values;
  let headers = getHeaderMap(values);
  const taskIdColumn = headers.get("任务ID");
  if (taskIdColumn == null) throw new Error("workbook is missing 任务ID header");
  const rowIndex = findTaskRow(values, opts.taskId, taskIdColumn);

  const changes = [];
  for (let i = 0; i < answers.length; i += 1) {
    const answer = answers[i];
    const pair = targetHeaders.pairs.get(i + 1);
    const accuracyHeader = pair.accuracy;
    const reasonHeader = pair.reason;
    const accuracyColumn = headers.get(accuracyHeader);
    const reasonColumn = headers.get(reasonHeader);
    const oldAccuracy = cellText(values[rowIndex][accuracyColumn]);
    const oldReason = cellText(values[rowIndex][reasonColumn]);
    const evidence = gradeEvidence[answer.model];
    if (!evidence) throw new Error(`missing grade evidence for ${answer.model}`);
    const accuracy = evidence.workbookAccuracy;
    const reason = evidence.complete ? answer.sheetReason : "AI质检未完成";
    if (!reason || reason.length > 500) {
      throw new Error(`${answer.model}: sheet reason must be 1-500 characters`);
    }
    if (evidence.complete) {
      platformAccuracy(answer, expectedPlatformAccuracy(accuracy));
      if (!answer.platformReason) {
        throw new Error(`${answer.model}: completed AI QC requires a platform reason`);
      }
    } else if (answer.sheetAccuracy && answer.sheetAccuracy !== "否") {
      throw new Error(`${answer.model}: incomplete AI QC must use sheet_accuracy=否`);
    }
    if (answer.sheetAccuracy && answer.sheetAccuracy !== accuracy) {
      throw new Error(
        `${answer.model}: sheet accuracy ${JSON.stringify(answer.sheetAccuracy)} ` +
        `does not match grade comparison (${accuracy})`,
      );
    }
    changes.push({
      model: answer.model,
      accuracyCell: `${accuracyHeader}=${oldAccuracy} -> ${accuracy}`,
      gradeComparison: evidence.complete
        ? `人工=${evidence.humanGrade}，AI=${evidence.aiGrade}`
        : `人工=${evidence.humanGrade}，AI质检未完成`,
      reasonCell: `${reasonHeader}=${oldReason} -> ${reason}`,
    });
    if (opts.write) {
      sheet.getCell(rowIndex, accuracyColumn).values = [[accuracy]];
      sheet.getCell(rowIndex, reasonColumn).values = [[reason]];
    }
  }

  console.log(`==> ${opts.write ? "写入" : "预览"} ${opts.taskId} AI 质检准确性字段`);
  for (const change of changes) {
    console.log(`   ${change.model}: ${change.accuracyCell} (${change.gradeComparison})`);
    console.log(`   ${change.model}: ${change.reasonCell}`);
  }

  if (!opts.write) return;
  workbook.recalculate();
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(xlsxPath);
  console.log(`==> saved ${path.relative(REPO_ROOT, xlsxPath)}`);
}

main().catch((error) => {
  console.error(error.stack || error.message || error);
  process.exit(1);
});

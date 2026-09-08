'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { TextDecoder } = require('node:util');
const { atomicWriteJSON } = require('./concurrency');

const BROWSER_ACTION = 'CaseBffV1CrowdtestTaskModelSessionBrowserGet';
const PREVIEW_ACTION = 'CaseBffV1CrowdtestTaskModelSessionPreviewGet';
const MAX_FILES = 1000;
const MAX_FILE_BYTES = 64 * 1024 * 1024;
const MAX_TOTAL_BYTES = 256 * 1024 * 1024;

function textValue(value) {
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2) ?? '';
}

function block(value) {
  const text = textValue(value);
  const longest = Math.max(2, ...(text.match(/`+/g) || []).map((s) => s.length));
  const fence = '`'.repeat(longest + 1);
  return `${fence}text\n${text}\n${fence}`;
}

function decodeCodex(buffer) {
  const text = new TextDecoder('utf-8', { fatal: true }).decode(buffer);
  const events = [];
  let sessionId = null;
  for (const [index, line] of text.split(/\r?\n/).entries()) {
    if (!line.trim()) continue;
    let row;
    try { row = JSON.parse(line); } catch { throw new Error(`invalid Codex JSONL at line ${index + 1}`); }
    if (!row || typeof row !== 'object' || !row.type || !row.payload || typeof row.payload !== 'object') {
      throw new Error(`invalid Codex event envelope at line ${index + 1}`);
    }
    const p = row.payload;
    if (row.type === 'session_meta') {
      const id = p.session_id || p.id;
      if (sessionId && id && sessionId !== id) throw new Error('mixed Codex session ids');
      sessionId = id || sessionId;
    }
    const event = { line: index + 1, ordinal: row.ordinal ?? null, timestamp: row.timestamp ?? null, kind: row.type };
    if (row.type === 'response_item') {
      event.kind = p.type || 'response_item';
      event.role = p.role;
      event.phase = p.phase;
      event.call_id = p.call_id;
      event.name = p.name;
      if (p.type === 'function_call') event.content = p.arguments;
      else if (p.type === 'custom_tool_call') event.content = p.input;
      else if (p.type === 'function_call_output' || p.type === 'custom_tool_call_output') event.content = p.output;
      else event.content = p.content ?? p.summary ?? p;
    } else if (row.type === 'compacted') {
      // Compaction is context supplied to a later turn, never a tool result.
      event.content = p.message ?? p;
    } else if (row.type === 'event_msg') {
      // Retain lifecycle/user events; token and item mirrors remain in the raw file.
      if (['token_count', 'item_started', 'item_completed'].includes(p.type)) continue;
      event.kind = `event_msg:${p.type || 'unknown'}`;
      event.content = p;
    } else if (row.type === 'session_meta') {
      event.content = { session_id: sessionId, cwd: p.cwd, cli_version: p.cli_version, source: p.source };
    } else {
      continue;
    }
    events.push(event);
  }
  if (!sessionId) throw new Error('Codex session_meta with session id is missing');
  const calls = new Map();
  for (const e of events) {
    if (['function_call', 'custom_tool_call'].includes(e.kind) && e.call_id) {
      if (calls.has(e.call_id)) throw new Error(`duplicate Codex call_id: ${e.call_id}`);
      calls.set(e.call_id, e);
    }
  }
  const unmatched = [];
  for (const e of events) {
    if (['function_call_output', 'custom_tool_call_output'].includes(e.kind)) {
      const call = calls.get(e.call_id);
      if (call) { e.name = call.name; e.call_line = call.line; }
      else unmatched.push(e.line);
    }
  }
  return { sessionId, events, unmatchedOutputLines: unmatched };
}

function decodeClaudeCode(buffer) {
  const text = new TextDecoder('utf-8', { fatal: true }).decode(buffer);
  const events = [];
  let sessionId = null;
  for (const [index, line] of text.split(/\r?\n/).entries()) {
    if (!line.trim()) continue;
    let row;
    try { row = JSON.parse(line); } catch { throw new Error(`invalid Claude Code JSONL at line ${index + 1}`); }
    if (!row || typeof row !== 'object' || typeof row.type !== 'string') throw new Error(`invalid Claude Code event at line ${index + 1}`);
    const id = row.sessionId || row.session_id;
    if (sessionId && id && sessionId !== id) throw new Error('mixed Claude Code session ids');
    sessionId = id || sessionId;
    const base = { line: index + 1, timestamp: row.timestamp || null, uuid: row.uuid, parent_uuid: row.parentUuid, sidechain: row.isSidechain || false };
    if (row.isCompactSummary || (row.type === 'system' && row.subtype === 'compact_boundary')) {
      events.push({ ...base, kind: 'compacted', content: row.message?.content ?? row });
      continue;
    }
    const content = row.message?.content;
    if (!['assistant', 'user'].includes(row.type)) {
      events.push({ ...base, kind: row.type, content: row });
      continue;
    }
    if (typeof content === 'string') {
      events.push({ ...base, kind: 'message', role: row.type, content });
      continue;
    }
    if (!Array.isArray(content)) throw new Error(`invalid Claude Code message at line ${index + 1}`);
    for (const [blockIndex, part] of content.entries()) {
      if (!part || typeof part.type !== 'string') throw new Error(`invalid Claude Code content at line ${index + 1}`);
      const event = { ...base, block_index: blockIndex, kind: part.type, role: row.type };
      if (part.type === 'tool_use') Object.assign(event, { call_id: part.id, name: part.name, content: part.input });
      else if (part.type === 'tool_result') Object.assign(event, { call_id: part.tool_use_id, role: 'tool', is_error: part.is_error || false, content: part.content });
      else event.content = part.text ?? part.thinking ?? part;
      events.push(event);
    }
  }
  if (!sessionId) throw new Error('Claude Code session id is missing');
  const calls = new Map();
  for (const e of events.filter((e) => e.kind === 'tool_use')) {
    if (!e.call_id || calls.has(e.call_id)) throw new Error('missing or duplicate Claude Code tool id');
    calls.set(e.call_id, e);
  }
  const unmatched = [];
  for (const e of events.filter((e) => e.kind === 'tool_result')) {
    const call = calls.get(e.call_id);
    if (call) { e.name = call.name; e.call_line = call.line; }
    else unmatched.push(e.line);
  }
  return { sessionId, events, unmatchedOutputLines: unmatched };
}

function renderCodex(parsed, rawFile, framework = 'Codex') {
  const lines = [`# ${framework} original Session ${parsed.sessionId}`, '', `Source: ${rawFile}`, '',
    'Tool calls and outputs are linked by call_id. Compacted text is context, not independent execution evidence. Raw files preserve all original records.', ''];
  for (const e of parsed.events) {
    lines.push(`## L${e.line} ${e.timestamp || ''} ${e.kind}${e.role ? ` (${e.role})` : ''}${e.name ? ` ${e.name}` : ''}`, '');
    if (e.call_id) lines.push(`call_id: ${e.call_id}${e.call_line ? `; call at L${e.call_line}` : ''}`, '');
    lines.push(block(e.content), '');
  }
  return `${lines.join('\n')}\n`;
}

function decodeSession(buffer, framework) {
  const normalized = String(framework || '').toLowerCase().replace(/[\s_-]/g, '');
  const decoder = { codex: decodeCodex, claudecode: decodeClaudeCode }[normalized];
  if (decoder) return decoder(buffer);
  // Framework labels can change; detect only known record schemas, never guess tool semantics.
  const text = new TextDecoder('utf-8', { fatal: true }).decode(buffer);
  const rows = text.split(/\r?\n/).filter((line) => line.trim()).map((line) => JSON.parse(line));
  if (rows.some((row) => row?.type === 'session_meta' && row.payload)) return decodeCodex(buffer);
  if (rows.some((row) => ['assistant', 'user'].includes(row?.type) && row.message && (row.sessionId || row.session_id))) return decodeClaudeCode(buffer);
  throw new Error(`unsupported original Session schema: ${framework || 'unknown'}`);
}

async function collectOriginalSessions({ runId, dir, request, keepExisting = false }) {
  runId = Number(runId);
  if (!Number.isSafeInteger(runId) || runId <= 0) throw new Error('invalid original Session run id');
  fs.mkdirSync(dir, { recursive: true });
  const manifestPath = path.join(dir, 'manifest.json');
  let previous;
  try { previous = JSON.parse(fs.readFileSync(manifestPath, 'utf8')); } catch { previous = null; }
  const manifest = { taskModelRunId: runId, source: BROWSER_ACTION, status: 'collecting', files: [], fetched_at: new Date().toISOString() };
  // Invalidate any prior success before a refresh, including failed listing calls.
  atomicWriteJSON(manifestPath, manifest);
  try {
    const files = [];
    const seenPaths = new Set();
    const cursors = new Set();
    const pages = [];
    let cursor;
    let reportedCount;
    let framework;
    do {
      const listing = await request(BROWSER_ACTION, { taskModelRunId: runId, ...(cursor ? { cursor } : {}) });
      if (!listing || !Array.isArray(listing.files) || Number(listing.taskModelRunId) !== runId) throw new Error('invalid original Session listing');
      if (framework && framework !== listing.framework) throw new Error('original Session framework changed during listing');
      framework = listing.framework;
      if (reportedCount !== undefined && listing.fileCount !== undefined && reportedCount !== listing.fileCount) throw new Error('original Session file count changed during listing');
      reportedCount = listing.fileCount ?? reportedCount;
      pages.push(listing);
      atomicWriteJSON(path.join(dir, 'browser.json'), { pages });
      for (const file of listing.files) {
        if (typeof file.path !== 'string' || !file.path || seenPaths.has(file.path)) throw new Error('missing or repeated original Session path');
        if (!Number.isSafeInteger(file.size) || file.size <= 0 || file.size > MAX_FILE_BYTES) throw new Error('invalid or oversized original Session file');
        seenPaths.add(file.path); files.push(file);
        if (files.length > MAX_FILES) throw new Error('too many original Session files');
      }
      cursor = listing.nextCursor;
      if (cursor) {
        if (cursors.has(cursor) || pages.length >= MAX_FILES) throw new Error('original Session pagination did not advance');
        cursors.add(cursor);
      }
    } while (cursor);
    if (reportedCount !== undefined && reportedCount !== files.length) throw new Error('incomplete original Session listing');
    if (files.reduce((sum, f) => sum + f.size, 0) > MAX_TOTAL_BYTES) throw new Error('original Session total size exceeds limit');
    atomicWriteJSON(path.join(dir, 'browser.json'), { pages });
    manifest.framework = framework;
    for (const file of files) {
      const stem = crypto.createHash('sha256').update(file.path).digest('hex').slice(0, 16);
      const rawFile = `${stem}.jsonl`;
      const target = path.join(dir, rawFile);
      let buffer;
      // Size alone is insufficient: always revalidate cached contents and parse them.
      const cached = Number(previous?.taskModelRunId) === runId && Array.isArray(previous?.files)
        && previous.files.find((f) => f.path === file.path && f.size === file.size && f.sha256);
      if (keepExisting && cached && fs.existsSync(target) && fs.statSync(target).size === file.size) {
        const candidate = fs.readFileSync(target);
        if (crypto.createHash('sha256').update(candidate).digest('hex') === cached.sha256) buffer = candidate;
      }
      if (!buffer) buffer = await request(PREVIEW_ACTION, { taskModelRunId: runId, path: file.path }, { binary: true });
      if (!Buffer.isBuffer(buffer) || buffer.length !== file.size) throw new Error(`incomplete original Session body: ${file.path}`);
      const temporary = `${target}.${process.pid}.part`;
      fs.writeFileSync(temporary, buffer);
      fs.renameSync(temporary, target);
      const entry = { path: file.path, size: buffer.length, sha256: crypto.createHash('sha256').update(buffer).digest('hex'),
        raw_file: rawFile, download_status: 'complete', parse_status: 'pending' };
      manifest.files.push(entry);
      atomicWriteJSON(manifestPath, manifest);
      let parsed;
      try {
        const format = String(file.format || path.extname(file.path).slice(1)).toLowerCase();
        if (!['jsonl', 'ndjson'].includes(format)) throw new Error(`unsupported original Session format: ${framework}/${format}`);
        parsed = decodeSession(buffer, framework);
      } catch (err) {
        entry.parse_status = 'error';
        entry.error = err.message;
        atomicWriteJSON(manifestPath, manifest);
        continue;
      }
      fs.writeFileSync(path.join(dir, `${stem}.events.jsonl`), parsed.events.map((e) => JSON.stringify(e)).join('\n') + '\n');
      fs.writeFileSync(path.join(dir, `${stem}.md`), renderCodex(parsed, rawFile, framework));
      Object.assign(entry, { parse_status: 'complete', session_id: parsed.sessionId,
        events_file: `${stem}.events.jsonl`, markdown_file: `${stem}.md`, unmatched_output_lines: parsed.unmatchedOutputLines });
      atomicWriteJSON(manifestPath, manifest);
    }
    const failed = manifest.files.filter((f) => f.parse_status === 'error');
    if (failed.length) throw new Error(`${failed.length} original Session file(s) downloaded but not parsed; see ${manifestPath}`);
    manifest.status = files.length ? 'complete' : 'empty';
    atomicWriteJSON(manifestPath, manifest);
    return manifest;
  } catch (err) {
    manifest.status = 'error';
    manifest.error = err.message;
    atomicWriteJSON(manifestPath, manifest);
    throw err;
  }
}

function originalSessionIndex(manifest) {
  if (!manifest) return '';
  const lines = ['## Original Session evidence', '', `Status: ${manifest.status}`, ''];
  for (const file of manifest.files) lines.push(`- [${manifest.framework} Session ${file.session_id}](original_sessions/${file.markdown_file}) - original records and linked tool calls/results; unmatched outputs: ${file.unmatched_output_lines.length}; raw: original_sessions/${file.raw_file}`);
  if (manifest.status === 'empty') lines.push('No original Session files were reported. Check ByteHouse evidence separately.');
  lines.push('', 'ByteHouse summaries are a separate source. Missing summary payloads do not establish missing execution evidence.', '');
  return lines.join('\n');
}

module.exports = { collectOriginalSessions, decodeCodex, decodeClaudeCode, renderCodex, textValue, originalSessionIndex };

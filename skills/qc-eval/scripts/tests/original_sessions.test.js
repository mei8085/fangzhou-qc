'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { collectOriginalSessions, decodeCodex, decodeClaudeCode, renderCodex, textValue } = require('../lib/original_sessions');
const { readSessionResponse } = require('../lib/session_response');

const row = (type, payload) => ({ timestamp: '2026-09-04T00:00:00Z', type, payload });
const meta = row('session_meta', { id: 'session-1', cwd: '/workspace' });
const data = (...rows) => Buffer.from([meta, ...rows].map((r) => JSON.stringify(r)).join('\n') + '\n');
const sample = data(row('response_item', { type: 'function_call', call_id: 'c1', name: 'exec_command', arguments: '{"cmd":"npm test"}' }),
  row('response_item', { type: 'function_call_output', call_id: 'c1', output: '12 passed\n```\nraw output' }));
function temp(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'qc-session-test-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}
function listing(files, nextCursor = null, fileCount = files.length) {
  return { taskModelRunId: 7, framework: 'codex', files, nextCursor, fileCount };
}
const file = (name = 'rollout.jsonl') => ({ path: name, size: sample.length, format: 'jsonl' });

test('preserves command arguments/results and joins out-of-order custom outputs by call id', () => {
  const parsed = decodeCodex(data(
    row('response_item', { type: 'custom_tool_call_output', call_id: 'c', output: { ok: true } }),
    row('compacted', { message: 'summary claims tests passed' }),
    row('response_item', { type: 'custom_tool_call', call_id: 'c', name: 'apply_patch', input: '*** patch' }),
    row('response_item', { type: 'message', role: 'assistant', content: [{ type: 'output_text', text: 'Done' }] }),
    row('event_msg', { type: 'item_completed', item: { type: 'custom_tool_call' } }),
  ));
  assert.equal(parsed.events[1].name, 'apply_patch');
  assert.equal(parsed.events[1].call_line, 4);
  assert.deepEqual(parsed.events[1].content, { ok: true });
  assert.equal(parsed.events[2].kind, 'compacted');
  assert.equal(parsed.events.at(-1).role, 'assistant');
  assert.equal(parsed.events.length, 5);
  assert.deepEqual(parsed.unmatchedOutputLines, []);
  const markdown = renderCodex(decodeCodex(sample), 'raw.jsonl');
  assert.match(markdown, /npm test/);
  assert.match(markdown, /12 passed/);
  assert.match(markdown, /````text/);
  assert.doesNotMatch(textValue({ choices: [{ message: 'hello' }] }), /\[object Object\]/);
});

test('rejects truncated JSONL, invalid UTF-8, duplicate calls and missing metadata', () => {
  assert.throws(() => decodeCodex(Buffer.concat([sample, Buffer.from('{"type":')])), /line 4/);
  assert.throws(() => decodeCodex(Buffer.from([0xff])), /encoded data/);
  assert.throws(() => decodeCodex(Buffer.from('{}\n')), /envelope/);
  assert.throws(() => decodeCodex(Buffer.from(JSON.stringify(row('event_msg', { type: 'task_complete' })))), /session_meta/);
  const call = row('response_item', { type: 'function_call', call_id: 'duplicate' });
  assert.throws(() => decodeCodex(data(call, call)), /duplicate/);
});

test('reports unmatched outputs without treating summaries as calls', () => {
  const parsed = decodeCodex(data(row('response_item', { type: 'function_call_output', call_id: 'unknown', output: 'failed' })));
  assert.deepEqual(parsed.unmatchedOutputLines, [2]);
});

test('collects all pages and files with safe local names and exact raw bytes', async (t) => {
  const dir = temp(t); const calls = [];
  const manifest = await collectOriginalSessions({ runId: 7, dir, request: async (action, args, options) => {
    calls.push([action, args, options]);
    if (action.endsWith('BrowserGet')) return args.cursor ? listing([file('second.jsonl')], null, 2) : listing([file('../../escape.jsonl')], 'next', 2);
    assert.equal(options.binary, true); return sample;
  } });
  assert.equal(manifest.status, 'complete');
  assert.equal(manifest.files.length, 2);
  assert.equal(calls[1][1].cursor, 'next');
  for (const f of manifest.files) {
    assert.match(f.raw_file, /^[a-f0-9]{16}\.jsonl$/);
    assert.deepEqual(fs.readFileSync(path.join(dir, f.raw_file)), sample);
    assert.match(fs.readFileSync(path.join(dir, f.markdown_file), 'utf8'), /12 passed/);
  }
});

test('reuses only checksum-validated cache and refreshes damaged files', async (t) => {
  const dir = temp(t); let downloads = 0;
  const request = async (action) => {
    if (action.endsWith('BrowserGet')) return listing([file()]);
    downloads++; return sample;
  };
  const first = await collectOriginalSessions({ runId: 7, dir, request });
  await collectOriginalSessions({ runId: 7, dir, request, keepExisting: true });
  assert.equal(downloads, 1);
  const target = path.join(dir, first.files[0].raw_file);
  fs.writeFileSync(target, Buffer.alloc(sample.length, 'x'));
  await collectOriginalSessions({ runId: 7, dir, request, keepExisting: true });
  assert.equal(downloads, 2);
  assert.deepEqual(fs.readFileSync(target), sample);
});

test('fails closed on pagination, count mismatch, truncated bytes and unsupported files', async (t) => {
  for (const scenario of ['cursor', 'count', 'body', 'format', 'binding', 'parse']) {
    const dir = temp(t); let pages = 0;
    const request = async (action) => {
      if (!action.endsWith('BrowserGet')) return scenario === 'body' ? sample.subarray(1) : scenario === 'parse' ? Buffer.alloc(sample.length, 'x') : sample;
      pages++;
      if (scenario === 'cursor') return listing([file(`${pages}.jsonl`)], 'same', 3);
      if (scenario === 'count') return listing([file()], null, 2);
      if (scenario === 'binding') return { ...listing([file()]), taskModelRunId: 8 };
      if (scenario === 'format') return listing([{ ...file(), format: 'text' }]);
      return listing([file()]);
    };
    await assert.rejects(collectOriginalSessions({ runId: 7, dir, request }));
    assert.equal(JSON.parse(fs.readFileSync(path.join(dir, 'manifest.json'))).status, 'error');
  }
});

test('distinguishes empty listing from request failure', async (t) => {
  const dir = temp(t);
  assert.equal((await collectOriginalSessions({ runId: 7, dir, request: async () => listing([]) })).status, 'empty');
  await assert.rejects(collectOriginalSessions({ runId: 7, dir, request: async () => { throw new Error('network failed'); } }));
  assert.equal(JSON.parse(fs.readFileSync(path.join(dir, 'manifest.json'))).status, 'error');
});

const claudeRows = [
  { type: 'mode', sessionId: 'claude-1', mode: 'normal' },
  { type: 'assistant', sessionId: 'claude-1', message: { content: [
    { type: 'thinking', thinking: 'Need to run tests' },
    { type: 'tool_use', id: 'test-1', name: 'Bash', input: { command: 'python -m pytest backend/tests -v' } },
  ] } },
  { type: 'user', sessionId: 'claude-1', message: { content: [
    { type: 'tool_result', tool_use_id: 'test-1', content: '65 passed\nexit: 0', is_error: false },
  ] } },
  { type: 'user', sessionId: 'claude-1', isCompactSummary: true, message: { content: 'Summary: 65 passed' } },
  { type: 'assistant', sessionId: 'claude-1', message: { content: [{ type: 'text', text: 'Tests passed' }] } },
];
const claudeSample = Buffer.from(claudeRows.map((r) => JSON.stringify(r)).join('\n'));

test('Claude Code distinguishes real tool returns from user prompts and compacted claims', () => {
  const parsed = decodeClaudeCode(claudeSample);
  const output = parsed.events.find((e) => e.kind === 'tool_result');
  assert.equal(output.role, 'tool');
  assert.equal(output.name, 'Bash');
  assert.equal(output.call_line, 2);
  assert.equal(output.content, '65 passed\nexit: 0');
  assert.equal(parsed.events.find((e) => e.kind === 'compacted').content, 'Summary: 65 passed');
  assert.deepEqual(parsed.unmatchedOutputLines, []);
  assert.match(renderCodex(parsed, 'raw.jsonl', 'claude_code'), /claude_code original Session/);
  assert.throws(() => decodeClaudeCode(Buffer.concat([claudeSample, Buffer.from('\n{')])), /invalid Claude Code JSONL/);
  assert.throws(() => decodeClaudeCode(Buffer.from('{"type":"mode"}')), /session id is missing/);
  assert.throws(() => decodeClaudeCode(Buffer.from([0xff])), /encoded data/);
});

test('collects Claude Code raw bytes and linked evidence without affecting Codex', async (t) => {
  const dir = temp(t);
  const manifest = await collectOriginalSessions({ runId: 7, dir, request: async (action) => {
    if (action.endsWith('BrowserGet')) return { ...listing([{ path: 'claude-1.jsonl', size: claudeSample.length, format: 'jsonl' }]), framework: 'claude_code' };
    return claudeSample;
  } });
  assert.equal(manifest.status, 'complete');
  assert.equal(manifest.files[0].session_id, 'claude-1');
  assert.deepEqual(fs.readFileSync(path.join(dir, manifest.files[0].raw_file)), claudeSample);
});

test('preserves preview bytes regardless of MIME and rejects server errors and login pages', async () => {
  const response = (buffer, mime, status = 200) => ({ status: () => status, headers: () => ({ 'content-type': mime }), body: async () => buffer });
  for (const mime of ['application/octet-stream', 'application/x-ndjson', 'text/plain', 'application/json', '']) {
    assert.deepEqual(await readSessionResponse(response(sample, mime)), sample);
  }
  for (const body of ['<!DOCTYPE html><html>Login</html>', '{"code":401,"message":"login"}',
    '{"ResponseMetadata":{"Error":{"Code":"InternalServiceTimeout"}}}', '{"data":null}', '']) {
    await assert.rejects(readSessionResponse(response(Buffer.from(body), 'application/octet-stream')));
  }
  await assert.rejects(readSessionResponse(response(sample, 'text/plain', 503)), /HTTP 503/);
});

test('supports framework aliases, missing format and known schemas under new labels', async (t) => {
  for (const framework of ['Claude Code', 'CLAUDE-CODE', 'new-framework', undefined]) {
    const manifest = await collectOriginalSessions({ runId: '7', dir: temp(t), request: async (action) =>
      action.endsWith('BrowserGet') ? { ...listing([{ path: 's.JSONL', size: claudeSample.length }]), framework } : claudeSample });
    assert.equal(manifest.status, 'complete');
    assert.equal(manifest.files[0].session_id, 'claude-1');
  }
});

test('retains unknown raw files and continues downloading subsequent sessions without claiming success', async (t) => {
  const dir = temp(t);
  const unknown = Buffer.from('{"type":"future-event","content":"unknown schema"}');
  await assert.rejects(collectOriginalSessions({ runId: 7, dir, request: async (action, args) => {
    if (action.endsWith('BrowserGet')) return { ...listing([
      { path: 'unknown.jsonl', size: unknown.length }, file('known.jsonl'),
    ]), framework: 'future' };
    return args.path === 'unknown.jsonl' ? unknown : sample;
  } }), /downloaded but not parsed/);
  const manifest = JSON.parse(fs.readFileSync(path.join(dir, 'manifest.json')));
  assert.equal(manifest.status, 'error');
  assert.equal(manifest.files.length, 2);
  assert.equal(manifest.files[0].download_status, 'complete');
  assert.equal(manifest.files[0].parse_status, 'error');
  assert.deepEqual(fs.readFileSync(path.join(dir, manifest.files[0].raw_file)), unknown);
  assert.equal(manifest.files[1].parse_status, 'complete');
});

test('does not reuse cache from a different run and tolerates malformed old manifests', async (t) => {
  const dir = temp(t);
  let downloads = 0;
  const request = async (action) => {
    if (action.endsWith('BrowserGet')) return listing([file()]);
    downloads++; return sample;
  };
  const first = await collectOriginalSessions({ runId: 7, dir, request });
  fs.writeFileSync(path.join(dir, 'manifest.json'), JSON.stringify({ ...first, taskModelRunId: 8 }));
  await collectOriginalSessions({ runId: 7, dir, request, keepExisting: true });
  assert.equal(downloads, 2);
  fs.writeFileSync(path.join(dir, 'manifest.json'), JSON.stringify({ taskModelRunId: 7, status: 'complete' }));
  await collectOriginalSessions({ runId: 7, dir, request, keepExisting: true });
  assert.equal(downloads, 3);
});

test('rejects mixed Codex sessions instead of assigning all tools to the last session', () => {
  assert.throws(() => decodeCodex(data(row('session_meta', { id: 'another-session' }))), /mixed Codex/);
});

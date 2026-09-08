'use strict';

// Preview responses are files even when the server labels them JSON or text.
async function readSessionResponse(resp) {
  const status = resp.status();
  const headers = resp.headers();
  const limit = 64 * 1024 * 1024;
  if (Number(headers['content-length'] || 0) > limit) throw new Error('original Session body exceeds 64 MiB');
  const buffer = await resp.body();
  if (buffer.length > limit) throw new Error('original Session body exceeds 64 MiB');
  if (status < 200 || status >= 300) throw new Error(`original Session HTTP ${status}`);
  if (!buffer.length) throw new Error('empty original Session response');
  const text = buffer.toString('utf8').trimStart();
  if (/^<(?:!doctype|html|head|body)\b/i.test(text)) throw new Error('original Session returned HTML; refresh authentication');
  let body;
  try { body = JSON.parse(text); } catch { /* Normal multi-record JSONL. */ }
  const error = body?.ResponseMetadata?.Error;
  if (error) throw new Error(`original Session: ${error.Code}: ${error.Message}`);
  if (body && !body.type && Object.hasOwn(body, 'code') && ![0, '0'].includes(body.code)) {
    throw new Error(`original Session: code=${body.code} message=${body.message || ''}`);
  }
  if (body && !body.type && Object.hasOwn(body, 'data')) throw new Error('original Session returned a JSON wrapper instead of raw records');
  return buffer;
}

module.exports = { readSessionResponse };

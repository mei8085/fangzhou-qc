'use strict';

const crypto = require('crypto');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '../../../..');
const PORT_LOCK_ROOT = path.join(REPO_ROOT, '.qc-eval', 'ports');
const NAMED_LOCK_ROOT = path.join(REPO_ROOT, '.qc-eval', 'locks');

function atomicWriteJSON(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temp = path.join(path.dirname(file), `.${path.basename(file)}.${process.pid}.${crypto.randomBytes(6).toString('hex')}.tmp`);
  try {
    fs.writeFileSync(temp, `${JSON.stringify(value, null, 2)}\n`, { flag: 'wx' });
    fs.renameSync(temp, file);
  } finally {
    try { fs.unlinkSync(temp); } catch (_) {}
  }
}

function preferredPortBase(taskId, namespace, count = 8) {
  const start = 20000;
  const end = 45000;
  const slots = Math.floor((end - start) / count);
  const digest = crypto.createHash('sha256').update(`${namespace}:${taskId}`).digest();
  return start + (digest.readUInt32BE(0) % slots) * count;
}

function portIsFree(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.once('error', () => resolve(false));
    server.listen({ host: '127.0.0.1', port, exclusive: true }, () => {
      server.close(() => resolve(true));
    });
  });
}

function lockIsStale(lockDir) {
  try {
    const owner = JSON.parse(fs.readFileSync(path.join(lockDir, 'owner.json'), 'utf8'));
    const ageMs = Date.now() - fs.statSync(lockDir).mtimeMs;
    if (owner.host !== os.hostname()) return ageMs > 6 * 60 * 60 * 1000;
    const pid = Number(owner.pid);
    if (!Number.isInteger(pid) || pid <= 0) return ageMs > 60 * 1000;
    try { process.kill(pid, 0); return false; } catch (_) { return true; }
  } catch (_) {
    try { return Date.now() - fs.statSync(lockDir).mtimeMs > 60 * 1000; } catch (_) { return false; }
  }
}

async function reservePortBlock(taskId, namespace, count, explicitBase = null) {
  fs.mkdirSync(PORT_LOCK_ROOT, { recursive: true });
  const preferred = explicitBase == null
    ? preferredPortBase(taskId, namespace, count)
    : Number(explicitBase);
  const attempts = explicitBase == null ? 512 : 1;
  for (let offset = 0; offset < attempts; offset += 1) {
    const base = preferred + offset * count;
    if (base + count >= 65535) break;
    const lockDir = path.join(PORT_LOCK_ROOT, `${base}-${base + count - 1}.lock`);
    try {
      fs.mkdirSync(lockDir);
    } catch (err) {
      if (err.code !== 'EEXIST') throw err;
      if (lockIsStale(lockDir)) {
        try { fs.rmSync(lockDir, { recursive: true, force: true }); } catch (_) {}
        offset -= 1;
      }
      continue;
    }
    let allFree = true;
    for (let port = base; port < base + count; port += 1) {
      if (!(await portIsFree(port))) { allFree = false; break; }
    }
    if (!allFree) {
      fs.rmSync(lockDir, { recursive: true, force: true });
      continue;
    }
    atomicWriteJSON(path.join(lockDir, 'owner.json'), {
      pid: process.pid, host: os.hostname(), task_id: String(taskId), namespace, base, count,
    });
    let released = false;
    const release = () => {
      if (released) return;
      released = true;
      try { fs.rmSync(lockDir, { recursive: true, force: true }); } catch (_) {}
    };
    process.once('exit', release);
    return { base, release };
  }
  throw new Error(`no free ${count}-port block for ${namespace}/${taskId} near ${preferred}`);
}

async function acquireNamedLock(name, timeoutMs = 10 * 60 * 1000) {
  fs.mkdirSync(NAMED_LOCK_ROOT, { recursive: true });
  const safeName = String(name).replace(/[^0-9A-Za-z_.-]+/g, '_');
  const lockDir = path.join(NAMED_LOCK_ROOT, `${safeName}.lock`);
  const deadline = Date.now() + timeoutMs;
  while (true) {
    try {
      fs.mkdirSync(lockDir);
      atomicWriteJSON(path.join(lockDir, 'owner.json'), {
        pid: process.pid, host: os.hostname(), name, created_at: new Date().toISOString(),
      });
      let released = false;
      const release = () => {
        if (released) return;
        released = true;
        try { fs.rmSync(lockDir, { recursive: true, force: true }); } catch (_) {}
      };
      process.once('exit', release);
      return { release };
    } catch (err) {
      if (err.code !== 'EEXIST') throw err;
      if (lockIsStale(lockDir)) {
        try { fs.rmSync(lockDir, { recursive: true, force: true }); } catch (_) {}
        continue;
      }
      if (Date.now() >= deadline) throw new Error(`timed out waiting for named lock ${name}`);
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
}

module.exports = { acquireNamedLock, atomicWriteJSON, preferredPortBase, reservePortBlock };

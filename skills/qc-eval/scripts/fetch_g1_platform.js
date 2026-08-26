#!/usr/bin/env node
// Current-period Ark crowdtest collector.
// Injects current-period / ark_g1 defaults, then reuses fetch_36_platform.js.

const fs = require('fs');
const path = require('path');

const CONFIG_PATH = path.resolve(__dirname, '..', 'config', 'g1.json');
const FALLBACK_PROJECT_ID = 287;
const FALLBACK_PROJECT_URL =
  'https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/projects/287?tab=review';

function loadConfig() {
  try {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
  } catch (_err) {
    return {};
  }
}

(function injectG1Defaults() {
  const cfg = loadConfig();
  const projectId = String(cfg.project_id || FALLBACK_PROJECT_ID);
  const projectUrl = cfg.project_url || FALLBACK_PROJECT_URL;
  const platformCodes = (cfg.models || [])
    .map((model) => String(model.platform || '').trim())
    .filter(Boolean)
    .join(',');
  const argv = process.argv;
  const cmd = argv[2];
  const has = (flag) => argv.includes(flag);
  if (cmd === 'collect' || cmd === 'discover-download' || cmd === 'discover-audit') {
    if (!has('--project')) argv.push('--project', projectId);
    if (!has('--output-subdir')) argv.push('--output-subdir', 'ark_g1');
    if (cmd === 'collect' && platformCodes && !has('--expect-platform-codes')) {
      argv.push('--expect-platform-codes', platformCodes);
    }
  }
  if ((cmd === 'auth-login' || cmd === 'auth-from-chrome') && !has('--url')) {
    argv.push('--url', projectUrl);
  }
  if (cmd === 'find-project' && !has('--projects')) {
    argv.push('--projects', projectId);
  }
}());

require('./fetch_36_platform.js');

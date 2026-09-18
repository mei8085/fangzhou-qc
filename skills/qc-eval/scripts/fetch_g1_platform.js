#!/usr/bin/env node
// Current-period Ark crowdtest collector.
// Injects current-period / ark_g1 defaults, then reuses fetch_36_platform.js.

const fs = require('fs');
const path = require('path');

const CONFIG_PATH = path.resolve(__dirname, '..', 'config', 'g1.json');
const FALLBACK_PROJECT_ID = 387;
const FALLBACK_PROJECT_URL =
  'https://ark.volcengine.com/crowdtest/region:cn-beijing/crowdtest/myprojects/387/task/9278';
const FALLBACK_CHROME_PROFILE = 'Profile 4';

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
  if (['collect', 'discover-download', 'discover-audit', 'discover-session', 'collect-sessions'].includes(cmd)) {
    if (!has('--project')) argv.push('--project', projectId);
    if (!has('--output-subdir')) argv.push('--output-subdir', cfg.output_subdir || 'ark_g1');
    if (cmd === 'collect' && platformCodes && !has('--expect-platform-codes')) {
      argv.push('--expect-platform-codes', platformCodes);
    }
    if (cmd === 'collect' && cfg.allow_missing_models && !has('--allow-missing-models')) {
      argv.push('--allow-missing-models');
    }
  }
  if ((cmd === 'auth-login' || cmd === 'auth-from-chrome') && !has('--url')) {
    argv.push('--url', projectUrl);
  }
  if (cmd === 'auth-from-chrome' && !has('--profile')) {
    argv.push('--profile', cfg.chrome_profile || FALLBACK_CHROME_PROFILE);
  }
  if (cmd === 'find-project' && !has('--projects')) {
    argv.push('--projects', projectId);
  }
}());

require('./fetch_36_platform.js');

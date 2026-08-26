#!/usr/bin/env node
// Current-period Ark crowdtest collector.
// Injects project 281 / ark_g1 defaults, then reuses fetch_36_platform.js.

const PROJECT_URL =
  'https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/projects/281?tab=review';

(function injectG1Defaults() {
  const argv = process.argv;
  const cmd = argv[2];
  const has = (flag) => argv.includes(flag);
  if (cmd === 'collect' || cmd === 'discover-download' || cmd === 'discover-audit') {
    if (!has('--project')) argv.push('--project', '281');
    if (!has('--output-subdir')) argv.push('--output-subdir', 'ark_g1');
    if (cmd === 'collect' && !has('--expect-platform-codes')) {
      argv.push('--expect-platform-codes', 'magma,kiln,jetsam,lintel');
    }
  }
  if ((cmd === 'auth-login' || cmd === 'auth-from-chrome') && !has('--url')) {
    argv.push('--url', PROJECT_URL);
  }
  if (cmd === 'find-project' && !has('--projects')) {
    argv.push('--projects', '281');
  }
}());

require('./fetch_36_platform.js');

#!/usr/bin/env node
// G1-new Ark crowdtest collector.
// Injects project 277 / ark_g1 defaults, then reuses fetch_36_platform.js.

const PROJECT_URL =
  'https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/projects/277?tab=review';

(function injectG1Defaults() {
  const argv = process.argv;
  const cmd = argv[2];
  const has = (flag) => argv.includes(flag);
  if (cmd === 'collect' || cmd === 'discover-download' || cmd === 'discover-audit') {
    if (!has('--project')) argv.push('--project', '277');
    if (!has('--output-subdir')) argv.push('--output-subdir', 'ark_g1');
    if (cmd === 'collect' && !has('--expect-platform-codes')) {
      argv.push('--expect-platform-codes', 'harrier,grotto,ferrite,estuary,dendrite');
    }
  }
  if ((cmd === 'auth-login' || cmd === 'auth-from-chrome') && !has('--url')) {
    argv.push('--url', PROJECT_URL);
  }
  if (cmd === 'find-project' && !has('--projects')) {
    argv.push('--projects', '277');
  }
}());

require('./fetch_36_platform.js');

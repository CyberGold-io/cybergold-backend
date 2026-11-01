"use strict";
// Reproduce the CommonJS artifact with the repository's pinned dev compiler.
// Production imports the generated artifact and needs no TypeScript runtime.
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const source = fs.readFileSync(path.join(__dirname, 'upstream/src/core/route/RouteFinder.ts'), 'utf8');
const result = ts.transpileModule(source, { fileName: 'RouteFinder.ts', compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  sourceMap: true, inlineSources: true, sourceRoot: '../../../upstream/src/core/route',
} });
const outputs = {
  'runtime/core/route/RouteFinder.js': result.outputText,
  'runtime/core/route/RouteFinder.js.map': result.sourceMapText,
};
for (const [name, content] of Object.entries(outputs)) {
  const filename = path.join(__dirname, name);
  if (process.argv.includes('--check')) {
    if (fs.readFileSync(filename, 'utf8') !== content) throw new Error('UniRoute generated artifact differs: '+name);
  } else {
    fs.mkdirSync(path.dirname(filename), { recursive: true });
    fs.writeFileSync(filename, content);
  }
}

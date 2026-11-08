"use strict";
// Reproduce the CommonJS artifact with the repository's pinned dev compiler.
// Production imports the generated artifact and needs no TypeScript runtime.
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, 'VENDOR.json'), 'utf8'));
const outputs = {};
for (const { component } of manifest.components) {
  const source = fs.readFileSync(path.join(__dirname, 'upstream', component), 'utf8');
  const runtime = 'runtime/'+component.replace(/^src\//, '').replace(/\.ts$/, '.js');
  const sourceRoot = path.relative(path.dirname(path.join(__dirname, runtime)),
    path.dirname(path.join(__dirname, 'upstream', component))).split(path.sep).join('/');
  const result = ts.transpileModule(source, { fileName: path.basename(component), compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
    sourceMap: true, inlineSources: true, sourceRoot,
  } });
  outputs[runtime] = result.outputText.replace(/[\t ]+$/gm, '');
  outputs[runtime+'.map'] = result.sourceMapText;
}
for (const [name, content] of Object.entries(outputs)) {
  const filename = path.join(__dirname, name);
  if (process.argv.includes('--check')) {
    if (fs.readFileSync(filename, 'utf8') !== content) throw new Error('UniRoute generated artifact differs: '+name);
  } else {
    fs.mkdirSync(path.dirname(filename), { recursive: true });
    fs.writeFileSync(filename, content);
  }
}

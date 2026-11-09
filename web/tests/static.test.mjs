import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join, relative } from 'node:path';
import { spawnSync } from 'node:child_process';

const web = fileURLToPath(new URL('../', import.meta.url));

function javascriptFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (path === join(web, 'tests')) return [];
    if (entry.isDirectory()) return javascriptFiles(path);
    return entry.isFile() && entry.name.endsWith('.js') ? [path] : [];
  });
}

const files = javascriptFiles(web).sort();

test('the source scan finds JavaScript files', () => {
  assert.ok(files.length > 0);
});
const sources = new Map(files.map((file) => [file, readFileSync(file, 'utf8')]));
const forbidden = [
  ['HTML parsing properties', /\b(?:innerHTML|outerHTML|insertAdjacentHTML)\b/],
  ['document.write', /\bdocument\s*\.\s*write\s*\(/],
  ['eval', /\beval\s*\(/],
  ['Function constructor', /\bnew\s+Function\b/],
  ['console.log', /\bconsole\s*\.\s*log\b/],
];

for (const [file, source] of sources) {
  const name = relative(web, file);
  for (const [behaviour, pattern] of forbidden) {
    test(`${name} avoids ${behaviour}`, () => {
      assert.doesNotMatch(source, pattern);
    });
  }

  test(`${name} passes node --check`, () => {
    const result = spawnSync(process.execPath, ['--check', file], {
      encoding: 'utf8', timeout: 5000,
    });
    assert.ifError(result.error);
    assert.equal(result.status, 0, result.stderr || result.stdout);
  });
}

test('every declared route has a script, stylesheet and render export', () => {
  const main = sources.get(join(web, 'app/route.js'));
  const declaration = main.match(/\b(?:export\s+)?const\s+ROUTES\s*=\s*\[([^\]]*)\]/s);
  assert.ok(declaration, 'ROUTES must be a literal array');
  const routes = [...declaration[1].matchAll(/(['"])([^'"]+)\1/g)].map((match) => match[2]);
  assert.ok(routes.length > 0, 'ROUTES must not be empty');
  for (const route of routes) {
    for (const extension of ['js', 'css']) {
      assert.ok(statSync(join(web, 'app/screens', `${route}.${extension}`)).isFile(), `${route}.${extension}`);
    }
    assert.match(sources.get(join(web, 'app/screens', `${route}.js`)), /export\s+function\s+render\s*\(/, route);
  }
});

test('every named UI import exists in the UI exports', () => {
  const ui = sources.get(join(web, 'app/ui.js'));
  const exported = new Set(
    [...ui.matchAll(/\bexport\s+(?:function|const)\s+([\w$]+)/g)].map((match) => match[1]),
  );
  for (const match of ui.matchAll(/\bexport\s*\{([^}]*)\}/g)) {
    for (const specifier of match[1].split(',').map((part) => part.trim()).filter(Boolean)) {
      const [local, alias] = specifier.split(/\s+as\s+/);
      exported.add(alias || local);
    }
  }
  assert.ok(exported.size > 0, 'must discover UI exports');
  let count = 0;
  for (const [file, source] of sources) {
    const imports = source.matchAll(/\bimport\s*\{([^}]*)\}\s*from\s*['"]\.{1,2}\/ui\.js['"]/g);
    for (const match of imports) {
      for (const specifier of match[1].split(',').map((part) => part.trim()).filter(Boolean)) {
        const [name] = specifier.split(/\s+as\s+/);
        assert.ok(exported.has(name), `${relative(web, file)} imports missing UI export ${name}`);
        count += 1;
      }
    }
  }
  assert.ok(count > 0, 'must discover UI imports');
});

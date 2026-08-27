/*
 * Renders the frontend the way the browser actually does.
 *
 * The UI has no build step, so there is no bundler to catch a typo'd component
 * name or a missing window export — the failure mode is a blank page in
 * production. This loads React's UMD builds and every component into jsdom as
 * real <script> elements, mounts <App /> with the HTTP endpoints stubbed from
 * the fixtures in ./fixtures, and asserts the page actually says what it should.
 *
 * Note on faithfulness: injecting the compiled code as <script> elements (with
 * jsdom runScripts enabled) is what makes this meaningful. Calling
 * `window.eval(code)` instead resolves bare identifiers in Node's scope rather
 * than the page's, so every cross-file component reference appears undefined
 * and the test fails for reasons the browser never would.
 *
 *   npm install && npm test
 */
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');
const babel = require('@babel/standalone');

const STATIC = path.resolve(__dirname, '../../src/static');
const FIXTURES = path.join(__dirname, 'fixtures');

// Load order must match index.html: a component may reference one loaded before
// it, and nothing is a module.
const ORDER = [
  'util', 'Icon', 'Button', 'Card', 'Field', 'StatusBar',
  'ContractCard', 'UploadCard', 'RunCard', 'ResultCard', 'QueueCard', 'App',
];

const routes = {
  '/api/contract': readFixture('contract.json'),
  '/health': readFixture('health.json'),
  '/api/queue': readFixture('queue.json'),
};

function readFixture(name) {
  return JSON.parse(fs.readFileSync(path.join(FIXTURES, name), 'utf8'));
}

// Read straight out of node_modules: React's package.json `exports` map does
// not expose ./umd/, so require.resolve cannot reach these.
function umd(pkg, file) {
  return fs.readFileSync(path.join(__dirname, 'node_modules', pkg, 'umd', file), 'utf8');
}

const errors = [];
const virtualConsole = new VirtualConsole()
  .on('jsdomError', e => errors.push(`jsdomError: ${e.message}`))
  .on('error', (...a) => errors.push(`console.error: ${a.join(' ')}`))
  .on('warn', () => {});

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
  url: 'http://localhost:8000/ui/',
  runScripts: 'dangerously',
  pretendToBeVisual: true,
  virtualConsole,
});
const { window } = dom;

window.fetch = url => {
  const key = String(url);
  if (key in routes) {
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(routes[key]) });
  }
  return Promise.reject(new Error(`unexpected fetch: ${key}`));
};

function inject(code, label) {
  const el = window.document.createElement('script');
  el.textContent = code;
  try {
    window.document.body.appendChild(el);
  } catch (e) {
    errors.push(`${label}: ${e.message}`);
  }
}

inject(umd('react', 'react.development.js'), 'react');
inject(umd('react-dom', 'react-dom.development.js'), 'react-dom');

for (const name of ORDER) {
  const src = fs.readFileSync(path.join(STATIC, 'components', `${name}.js`), 'utf8');
  let code;
  try {
    code = babel.transform(src, { presets: ['env', 'react'] }).code;
  } catch (e) {
    errors.push(`${name}.js failed to compile: ${e.message.split('\n')[0]}`);
    continue;
  }
  inject(code, `${name}.js`);
}

// The same mount call index.html makes, taken from index.html so the two
// cannot drift.
const html = fs.readFileSync(path.join(STATIC, 'index.html'), 'utf8');
const mount = html.match(/data-presets="env,react">([\s\S]*?)<\/script>/);
if (!mount) {
  errors.push('index.html: could not find the inline mount script');
} else {
  inject(babel.transform(mount[1], { presets: ['env', 'react'] }).code, 'index.html inline');
}

setTimeout(() => {
  const text = window.document.getElementById('root').textContent;

  const checks = [
    ['page renders', text.length > 200],
    ['service name', text.includes('Doc Processor')],
    ['connection indicator', text.includes('Connected')],
    ['contract: endpoint', text.includes('POST /process')],
    ['contract: accepted types', text.includes('.pdf')],
    ['contract: max size', text.includes('20 MB')],
    ['contract: busy rejection documented', text.includes('429 Busy')],
    ['upload dropzone', text.includes('Drop a document here')],
    ['param: output', text.includes('Output')],
    ['param: chunk size', text.includes('Chunk size')],
    ['param: tokenizer', text.includes('Tokenizer')],
    ['param: OCR', text.includes('Run OCR')],
    // Defaults must come from /api/contract, not be hardcoded in the UI.
    ['default tokenizer surfaced', text.includes(routes['/api/contract'].defaults.tokenizer)],
    ['default max_tokens surfaced', text.includes(String(routes['/api/contract'].defaults.max_tokens))],
    ['queue section', text.includes('Queue')],
    ['queue history rendered', text.includes(routes['/api/queue'].jobs[0].id)],
    // The frontend is meant to be the first place you look when something is off.
    ['missing LibreOffice is surfaced', text.includes('LibreOffice is not installed')],
    ['powered by Ulvio', text.includes('Powered by Ulvio')],
  ];

  let failed = 0;
  for (const [name, ok] of checks) {
    console.log(`${ok ? 'ok  ' : 'FAIL'}  ${name}`);
    if (!ok) failed++;
  }

  const real = errors.filter(e => !/not wrapped in act/.test(e));
  if (real.length) {
    console.log('\npage errors:');
    real.slice(0, 10).forEach(e => console.log(`  ${e}`));
  }

  const bad = failed + real.length;
  console.log(`\n${checks.length - failed}/${checks.length} checks passed${real.length ? `, ${real.length} page error(s)` : ', no page errors'}`);
  process.exit(bad ? 1 : 0);
}, 1500);

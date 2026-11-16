/* eslint-disable @typescript-eslint/no-require-imports -- Offline CommonJS component harness. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { test } = require('node:test');
const frontend = path.resolve(__dirname, '..');
const ts = require(path.join(process.env.WAVEGUIDE_FRONTEND || frontend, 'node_modules/typescript'));

function load(relative, mocks) {
  const source = fs.readFileSync(path.join(frontend, relative), 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020,
  }}).outputText;
  const exports = {};
  vm.runInNewContext(js, { exports, require: id => {
    if (!(id in mocks)) throw Error(`Unexpected dependency: ${id}`);
    return mocks[id];
  }, process: {env: {NEXT_PUBLIC_API_URL: 'https://api.example.test'}}, fetch: mocks.fetch });
  return exports;
}

function componentHarness(deleteAccount) {
  const slots = []; let cursor = 0; let signedOut = 0; let deleted = 0;
  const react = {
    useState(initial) {
      const i = cursor++;
      if (!(i in slots)) slots[i] = initial;
      return [slots[i], value => { slots[i] = value; }];
    },
    useRef(initial) {
      const i = cursor++;
      if (!(i in slots)) slots[i] = {current: initial};
      return slots[i];
    },
    useEffect() {},
  };
  const jsx = (type, props) => ({type, props});
  const Component = load('components/AccountPanel.tsx', {
    react, 'react/jsx-runtime': {jsx, jsxs: jsx, Fragment: 'fragment'},
    '@/lib/api': {deleteAccount},
    '@/lib/supabase/client': {createClient: () => ({auth: {signOut: async (options) => {
      assert.equal(options.scope, 'local'); signedOut++; return {error:null};
    }}})},
    '@/components/LogoutButton': {default: () => null},
  }).default;
  function render() {
    cursor = 0;
    const tree = Component({email:'user@example.test', disabled:false, onDeleted: () => deleted++});
    const nodes = [];
    function walk(node) {
      if (!node || typeof node !== 'object') return;
      if (Array.isArray(node)) return node.forEach(walk);
      nodes.push(node); walk(node.props?.children);
    }
    walk(tree);
    return nodes;
  }
  return {render, counts: () => ({signedOut, deleted})};
}
const button = (nodes, label) => nodes.find(n => n.type === 'button' && n.props.children === label);

test('account action requires confirmation and cancellation never requests deletion', () => {
  let calls = 0;
  const app = componentHarness(async () => calls++);
  button(app.render(), 'Delete Account').props.onClick();
  const confirming = app.render();
  assert.ok(confirming.some(n => n.props?.id === 'deletion-warning'));
  button(confirming, 'Cancel').props.onClick();
  assert.equal(calls, 0);
  assert.equal(app.render().filter(n => n.props?.id === 'deletion-warning').length, 0);
});

test('pending deletion prevents duplicates and success signs out and clears app state once', async () => {
  let calls = 0; let complete;
  const app = componentHarness(() => { calls++; return new Promise(resolve => {complete = resolve;}); });
  button(app.render(), 'Delete Account').props.onClick();
  const handler = button(app.render(), 'Delete Account').props.onClick;
  const pending = handler();
  await handler();
  assert.equal(calls, 1);
  assert.equal(button(app.render(), 'Cancel').props.disabled, true);
  assert.equal(button(app.render(), 'Deleting...').props.disabled, true);
  assert.deepEqual(app.counts(), {signedOut:0, deleted:0});
  complete(); await pending;
  assert.deepEqual(app.counts(), {signedOut:1, deleted:1});
});

test('failed deletion keeps auth, displays safe error and permits retry', async () => {
  const app = componentHarness(async () => {throw Error('private server failure');});
  button(app.render(), 'Delete Account').props.onClick();
  await button(app.render(), 'Delete Account').props.onClick();
  const nodes = app.render();
  assert.equal(nodes.find(n => n.props?.role === 'alert').props.children,
    'Unable to delete your account. Please try again.');
  assert.equal(button(nodes, 'Delete Account').props.disabled, false);
  assert.deepEqual(app.counts(), {signedOut:0, deleted:0});
});

test('API uses authenticated DELETE with no user-supplied target and hides server errors', async () => {
  let options;
  const api = load('lib/api.ts', {
    '@/lib/supabase/client': {createClient: () => ({auth: {getSession: async () => ({
      data:{session:{access_token:'test-token'}}, error:null,
    })}})},
    fetch: async (url, init) => {assert.equal(url, 'https://api.example.test/account'); options=init;
      return {ok:false, status:503, json:async () => ({detail:'secret'})};},
  });
  await assert.rejects(api.deleteAccount(), /Unable to delete your account/);
  assert.equal(options.method, 'DELETE');
  assert.equal(options.headers.Authorization, 'Bearer test-token');
  assert.equal(options.body, undefined);
});

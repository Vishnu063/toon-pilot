// Optional DOM integration check against the running local dashboard.
// NODE_PATH=/tmp/toon-ui-check/node_modules node tests/dashboard_dom_smoke.cjs
const assert = require('node:assert/strict');
const {JSDOM} = require('jsdom');
const base = 'http://127.0.0.1:8768';
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, timeout = 120000) {
  const deadline = Date.now() + timeout;
  while (!check()) {
    if (Date.now() > deadline) throw Error('UI readiness timed out');
    await wait(200);
  }
}
(async () => {
  const html = await (await fetch(base)).text();
  const dom = new JSDOM(html, {url:base,runScripts:'dangerously',beforeParse(window) {
    window.fetch = (url, options) => fetch(new URL(url,base),options);
    window.HTMLMediaElement.prototype.pause = function() {};
  }});
  try {
    const doc = dom.window.document;
    const $ = id => doc.getElementById(id);
    await until(() => $('speech-status').textContent.startsWith('Offline speech available'));
    $('title').value = 'DOM smoke: Pip says hello';
    $('lyrics').value = 'Hello friend. Pip hops in the garden. Have a happy day.';
    $('duration').value = '30';
    $('cast').value = 'pip';
    $('orientation').value = 'landscape';
    $('auto-plan').click();
    await until(() => doc.querySelectorAll('.scene').length === 3);
    $('editor').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));
    await until(() => !$('narrate').disabled);
    $('narrate').click();
    await until(() => !$('audio').hidden);
    assert.match($('status').textContent,/Spoken narration/);
    $('server-stopped').checked = true;
    $('server-stopped').dispatchEvent(new dom.window.Event('change'));
    assert.equal($('full').disabled,false);
    $('preview').click();
    await until(() => !$('video').hidden);
    const movie = await fetch(new URL($('video').getAttribute('src'),base));
    assert.equal(movie.status,200);
    assert.ok((await movie.arrayBuffer()).byteLength > 1000);
    assert.equal($('youtube').disabled,true);
    assert.equal($('message').textContent,'');
    console.log('DOM smoke passed: automatic plan, save, real narration, real landscape preview, download, disconnected YouTube gate.');
  } finally { dom.window.close(); }
})().catch(error => { console.error(error);process.exitCode=1; });

const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('app/api/v1/console.html','utf8');
function harness(fetch) {
  const nodes = Object.fromEntries(['companion-select','loading','main','last-update','refresh-btn','auto-refresh'].map(k=>[k,{value:'alice',textContent:'',addEventListener(){}}]));
  let rendered='';
  Object.defineProperty(nodes.main,'innerHTML',{get(){return rendered},set(v){
    rendered=v;
    if (/<main[^>]*>[\s\S]*id="loading"[\s\S]*<\/main>/.test(html)) delete nodes.loading;
  }});
  const context=vm.createContext({window:{location:{pathname:'/v1/console/ui'}},document:{getElementById:id=>nodes[id]},fetch,setInterval:()=>1,clearInterval(){}});
  vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1].replace('\nloadCompanions();','\n'),context);
  return {nodes,render:()=>vm.runInContext('render()',context)};
}
function result(url) {
  const who=new URL('http://local'+url).searchParams.get('companion_id');
  return {ok:true,json:async()=>url.includes('/memory?')?{counts:{short_term:0,summaries:0,archive:0,impressions:0}}:{display_name:who,companion_id:who}};
}
test('refresh survives repeated replacement of main',async()=>{
  const h=harness(async url=>result(url));
  await h.render(); await h.render();
  assert.ok(h.nodes.main.innerHTML.includes('alice'));
  assert.equal(h.nodes.loading.textContent,'');
});
test('same-character inflight refresh coalesces; stale character cannot overwrite',async()=>{
  const waiting=[];
  const h=harness(url=>new Promise(resolve=>waiting.push(()=>resolve(result(url)))));
  const first=h.render();
  assert.equal(h.render(),first);
  h.nodes['companion-select'].value='bruno';
  const second=h.render();
  waiting[2]();waiting[3]();await second;
  assert.ok(h.nodes.main.innerHTML.includes('bruno'));
  waiting[0]();waiting[1]();await first;
  assert.ok(h.nodes.main.innerHTML.includes('bruno'));
  assert.equal(h.nodes.loading.textContent,'');
});
test('failed fetch clears loading and a later refresh succeeds',async()=>{
  let fail=true;
  const h=harness(async url=>{if(fail)throw new Error('offline');return result(url)});
  await h.render();assert.ok(h.nodes.main.innerHTML.includes('offline'));
  fail=false;await h.render();assert.ok(h.nodes.main.innerHTML.includes('alice'));
});

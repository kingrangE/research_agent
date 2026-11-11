import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

function ui() {
  const elements = new Map();
  const context = vm.createContext({
    document: { querySelectorAll: () => [], querySelector: selector => { if (!elements.has(selector)) elements.set(selector, {firstChild:{},classList:{toggle(){}},querySelectorAll(){return [];},setAttribute(){},showModal(){this.open=true;},close(){this.open=false;}}); return elements.get(selector); }, hidden: true },
    localStorage: { getItem: () => null }, URL, Date,
  });
  const script = readFileSync(new URL('../web/app.js', import.meta.url), 'utf8');
  vm.runInContext(script.slice(0, script.indexOf("document.addEventListener('click'")), context);
  return expression => vm.runInContext(expression, context);
}

test('stock card escapes names and reasons and distinguishes inferred candidates', () => {
  const run = ui();
  const html = run(`stocksHTML({related_stocks:[{code:'003470',name:'<img src=x>',relation:'business',reason:'<script>alert(1)</script>'}]},true)`);
  assert.ok(html.includes('&lt;img src=x&gt;'));
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('사업 연관 후보'));
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('/003470'));
});

test('quote renders signed daily change, provider timestamp and stale state', () => {
  const run = ui();
  run(`quotes['003470']={price:3935,change_percent:-2.88,traded_at:'2026-11-11T15:42:16+09:00',fetched_at:new Date().toISOString(),delay_label:'실시간',source:'Npay 증권',status:'ok'}`);
  let html = run(`quoteHTML('003470')`);
  assert.ok(html.includes('3,935'));
  assert.ok(html.includes('-2.88%'));
  assert.ok(html.includes('전일 대비'));
  assert.ok(html.includes('시세 기준'));
  assert.ok(!html.includes('이전 조회'));
  run(`quotes['003470'].status='stale'`);
  html = run(`quoteHTML('003470')`);
  assert.ok(html.includes('이전 조회'));
  assert.ok(html.includes('3,935'));
});

test('missing quotes never become fabricated zero prices and demo hides real quotes', () => {
  const run = ui();
  run(`quotes['003470']={status:'error'}`);
  assert.ok(run(`quoteHTML('003470')`).includes('시세 조회 실패'));
  assert.ok(!run(`quoteHTML('003470')`).includes('0.00%'));
  run(`quotes['003470']={price:3935,change_percent:2.88}; mode='demo'`);
  assert.ok(run(`quoteHTML('003470')`).includes('시세 미조회'));
  assert.ok(!run(`quoteHTML('003470')`).includes('3,935'));
});

test('US price stays in dollars and quotes identify the regular session', () => {
  const run = ui();
  run(`quotes['NVDA.O']={price:168.89,change_percent:-5.47,currency:'USD',status:'ok',fetched_at:new Date().toISOString(),traded_at:'2026-11-10T16:00:00-05:00',delay_label:'실시간',source:'Npay 증권'}`);
  const html=run(`quoteHTML('NVDA.O')`);
  assert.ok(html.includes('$168.89'));
  assert.ok(!html.includes('<small>원</small>'));
  assert.ok(html.includes('미국 정규장'));
});

test('compact stocks show only names and changes while details preserve evidence', () => {
  const run = ui();
  run(`data={stock_status:{status:'ok'}}; var article={id:'test',related_stocks:Array.from({length:8},(_,i)=>({code:'S'+i,country:'US',name:'후보 '+i,relation:'documented',path:'OpenAI → 공급 관계',mechanism:'공개 관계이며 신규 주문은 미확인',sources:[{title:'원문',url:'https://example.com/source',published_on:'2025-01-01',checked_on:'2026-11-11'}],required_checks:['매출 기여 미확인']}))}`);
  const list=run(`stocksHTML(article)`);
  const detail=run(`stocksHTML(article,true)`);
  assert.equal((list.match(/class="stock-chip"/g)||[]).length,8);
  assert.ok(!list.includes('OpenAI →'));
  assert.ok(!list.includes('example.com/source'));
  assert.ok(!list.includes('stock-market'));
  assert.ok(list.includes('aria-haspopup="dialog"'));
  assert.equal((detail.match(/class="stock-card"/g)||[]).length,8);
  assert.ok(list.includes('후보 7'));
  assert.ok(detail.includes('2025-01-01'));
  assert.ok(detail.includes('매출 기여 미확인'));
  assert.ok(detail.includes('/worldstock/stock/'));
});

test('article keeps compact stocks and stock modal reveals the selected evidence', () => {
  const run = ui();
  run(`data={articles:[{id:'policy',title:'AI 유니콘 육성',source:'공개 피드',themes:[],reason:'최신 자료',question:'조건 확인',score_parts:{freshness:40},stock_analysis:{events:[{name:'정책'}],entities:[],event_state:'계획'},related_stocks:[{code:'MSFT.O',country:'US',name:'Microsoft',relation:'theme',path:'AI → 클라우드',sources:[{title:'사업 근거',url:'https://example.com/source'}],required_checks:['지원 대상 미확인']}]}]}; renderDetail('policy')`);
  const html = run(`$('#detail').innerHTML`);
  assert.ok(html.includes('기사에서 찾은 사건'));
  assert.ok(!html.includes('지원 대상 미확인'));
  assert.ok(html.includes('stock-chip'));
  assert.ok(html.includes('최신성 40점'));
  run(`openStock('policy','MSFT.O')`);
  const modal = run(`$('#stock-detail').innerHTML`);
  assert.equal(run(`$('#stock-dialog').open`),true);
  assert.ok(modal.includes('example.com/source'));
  assert.ok(modal.includes('지원 대상 미확인'));
  assert.ok(modal.includes('data-close-stock'));
  run(`$('#stock-dialog').close();openStock('policy','UNKNOWN')`);
  assert.equal(run(`$('#stock-dialog').open`),false);
});


test('compact changes hide prices, handle missing quotes and mark stale percentages', () => {
  const run = ui();
  run(`quotes['005930']={price:70000,change_percent:2.4,status:'ok',fetched_at:new Date().toISOString(),traded_at:new Date().toISOString()}`);
  const html = run(`stocksHTML({id:'test',related_stocks:[{name:'삼성전자',code:'005930'}]})`);
  assert.ok(html.includes('+2.40%'));
  assert.ok(!html.includes('70,000'));
  assert.ok(!html.includes('class="quote-time'));
  assert.ok(!html.includes('stock-values'));
  run(`quotes['005930'].status='stale'`);
  assert.ok(run(`changeHTML('005930')`).includes('이전 조회'));
  assert.ok(!run(`changeHTML('UNKNOWN')`).includes('0.00%'));
  run(`mode='demo'`);
  assert.ok(!run(`changeHTML('005930')`).includes('2.40%'));
});

test('context briefing groups events and leaves unanalysed articles in the full feed', () => {
  const run=ui();
  run(`data={articles:[{id:'a',title:'A',source:'test',themes:[],score:50},{id:'b',title:'B',source:'test',themes:[],score:49},{id:'c',title:'C',source:'test',themes:[],score:48},{id:'d',title:'D',source:'test',themes:[],score:47}],intelligence:{ranking_stale:false,events:[{event_id:'e1',articles:[{id:'a'},{id:'b'}]},{event_id:'e2',articles:[{id:'c'}]}],ranking:[{event_id:'e2',reason:'확정 계약'},{event_id:'e1',reason:'계획'}]}};data.intelligence.assessments=data.intelligence.ranking;sort='context'`);
  assert.equal(run(`filteredArticles().map(a=>a.id).join(',')`),'c,a');
  run(`view='feed'`);
  assert.equal(run(`filteredArticles().map(a=>a.id).join(',')`),'c,a,d');
  run(`data.intelligence.ranking_stale=true`);
  assert.equal(run(`filteredArticles().map(a=>a.id).join(',')`),'a,b,c,d');
});

test('model evidence and ranking reasons are escaped in the detail view', () => {
  const run=ui();
  run(`data={intelligence:{events:[{event_id:'e',summary:'<script>bad</script>',articles:[{id:'a',url:'javascript:bad',evidence:['<img src=x>']}]}],ranking:[{event_id:'e',reason:'<script>bad</script>'}]}}`);
  const html=run(`readingHTML({id:'a'})`);
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('javascript:'));
});


test('initial dashboard shows model order without manually changing sort', () => {
  const run=ui();
  run(`data={articles:[{id:'new',title:'최신',themes:[],source:'test',score:50},{id:'important',title:'중요',themes:[],source:'test',score:40}],intelligence:{ranking_stale:false,events:[{event_id:'e1',articles:[{id:'new'}]},{event_id:'e2',articles:[{id:'important'}]}],ranking:[{event_id:'e2',reason:'중요 사건'},{event_id:'e1',reason:'일반 사건'}]}};data.intelligence.assessments=data.intelligence.ranking`);
  assert.equal(run(`filteredArticles().map(a=>a.id).join(',')`),'important,new');
  run(`render()`);
  assert.equal(run(`$('#sort').value`),'context');
  const html=run(`$('#articles').innerHTML`);
  assert.ok(html.indexOf('>중요</button>')<html.indexOf('>최신</button>'));
  assert.ok(run(`$('#list-heading').firstChild.textContent`).includes('주식 판단'));
});


test('stock decision briefing does not fill remaining slots with background or unanalysed news', () => {
  const run=ui();
  run(`data={articles:[{id:'bond',title:'국채 청약',source:'test',themes:[],score:50},{id:'contract',title:'공급 계약',source:'test',themes:[],score:40},{id:'pending',title:'미분석',source:'test',themes:[],score:30}],intelligence:{ranking_stale:false,events:[{event_id:'bond-event',articles:[{id:'bond'}]},{event_id:'contract-event',articles:[{id:'contract'}]}],assessments:[{event_id:'bond-event',stock_relevance:'배경·상품 안내'},{event_id:'contract-event',stock_relevance:'주식 판단 재료'}],ranking:[{event_id:'contract-event',reason:'실적 변화'}]}}`);
  assert.equal(run(`filteredArticles().map(a=>a.id).join(',')`),'contract');
  run(`view='feed'`);
  assert.equal(run(`filteredArticles().length`),3);
  run(`view='briefing';data.intelligence.ranking=[]`);
  assert.equal(run(`filteredArticles().length`),0);
  run(`render()`);
  assert.ok(run(`$('#articles').innerHTML`).includes('주식 판단 재료'));
});

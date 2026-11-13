import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

function ui(extra={}) {
  const elements = new Map();
  const context = vm.createContext({
    document: { querySelectorAll: () => [], querySelector: selector => { if (!elements.has(selector)) elements.set(selector, {firstChild:{},classList:{toggle(){}},querySelectorAll(){return [];},setAttribute(){},showModal(){this.open=true;},close(){this.open=false;}}); return elements.get(selector); }, hidden: true },
    localStorage: { getItem: () => null }, URL, URLSearchParams, AbortSignal, Date, ...extra,
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

test('cached ranking expires on the client even when the next server request fails', async () => {
  const run=ui({setTimeout:()=>1,clearTimeout:()=>{},fetch:async(url,options)=>{
    assert.ok(options.signal instanceof AbortSignal);
    throw new Error('timeout');
  }});
  run(`data={articles:[{id:'a',title:'계약',themes:[],source:'test',score:50}],intelligence:{ranking_stale:false,ranked_at:new Date(Date.now()-601000).toISOString(),events:[{event_id:'e',articles:[{id:'a'}]}],assessments:[{event_id:'e'}],ranking:[{event_id:'e',reason:'계약'}]}}`);
  assert.equal(run('hasContextRanking()'),false);
  await run('load()');
  assert.equal(run('loading'),false);
  assert.equal(run(`$('#refresh').disabled`),false);
  assert.ok(run(`$('#list-caption').textContent`).includes('갱신 지연'));
});

test('briefing discloses article analysis coverage even when ranking itself succeeded', () => {
  const run=ui();
  run(`data={articles:[{id:'a',title:'계약',themes:[],source:'test',score:50}],intelligence:{ranking_stale:false,ranking_partial:false,ranked_at:new Date().toISOString(),coverage:{candidates:240,analyzed_articles:42,events:35},events:[{event_id:'e',articles:[{id:'a'}]}],assessments:[{event_id:'e'}],ranking:[{event_id:'e',reason:'계약'}]}};render()`);
  assert.ok(run(`$('#list-caption').textContent`).includes('이번 대상 240건 중 본문 분석 42건'));
  assert.ok(run(`$('#list-caption').textContent`).includes('미분석 기사는 순위에서 제외'));
  assert.ok(run(`$('#stats').innerHTML`).includes('분석 완료 자료 내 순위'));
  assert.equal(run('filteredArticles().length'),1);
  run(`data.intelligence.coverage.analyzed_articles=240;render()`);
  assert.ok(run(`$('#list-caption').textContent`).includes('이번 대상 240건 중 본문 분석 240건'));
  assert.ok(!run(`$('#list-caption').textContent`).includes('미분석 기사는 순위에서 제외'));
  run(`view='saved';render()`);
  assert.ok(!run(`$('#list-caption').textContent`).includes('이번 대상'));
});

test('failed dashboard refresh keeps a persistent warning until a current request succeeds', async () => {
  let fail=false;
  const payload={articles:[],sources:[],updated_at:'2026-11-13T00:00:00Z',intelligence:{events:[],ranking:[]}};
  const run=ui({setTimeout:()=>1,clearTimeout:()=>{},fetch:async()=>{if(fail) throw new Error('offline');return {ok:true,json:async()=>payload};}});
  await run('load()');
  assert.equal(run(`$('#mode-notice').hidden`),true);
  const received=run('lastLoadedAt');
  fail=true;
  await run('load()');
  run(`$('#toast').hidden=true;render()`);
  assert.equal(run(`$('#mode-notice').hidden`),false);
  assert.ok(run(`$('#mode-notice').textContent`).includes('화면 갱신 실패'));
  assert.ok(run(`$('#mode-notice').textContent`).includes('이전 자료'));
  assert.ok(run(`$('#update-time').textContent`).includes('마지막 정상 응답'));
  assert.equal(run('lastLoadedAt'),received);
  assert.equal(run('data.updated_at'),payload.updated_at);
  fail=false;
  await run('load()');
  assert.equal(run(`$('#mode-notice').hidden`),true);
  assert.ok(!run(`$('#update-time').textContent`).includes('갱신 실패'));
});

test('late failed refresh cannot overwrite a newer successful response', async () => {
  const requests=[];
  const run=ui({setTimeout:()=>1,clearTimeout:()=>{},fetch:()=>new Promise((resolve,reject)=>requests.push({resolve,reject}))});
  const old=run('load()');
  const current=run('load()');
  requests[1].resolve({ok:true,json:async()=>({articles:[],sources:[],intelligence:{events:[],ranking:[]}})});
  await current;
  requests[0].reject(new Error('late timeout'));
  await old;
  assert.equal(run('loadFailed'),false);
  assert.equal(run(`$('#mode-notice').hidden`),true);
});

test('first response failure stays visible and switching modes resets response state', async () => {
  const run=ui({setTimeout:()=>1,clearTimeout:()=>{},fetch:async()=>({ok:false})});
  await run('load()');
  assert.equal(run(`$('#mode-notice').hidden`),false);
  assert.ok(run(`$('#mode-notice').textContent`).includes('서버 응답'));
  assert.ok(!run(`$('#mode-notice').textContent`).includes('이전 자료'));
  assert.ok(run(`$('#update-time').textContent`).includes('정상 응답 시각 미확인'));
  run(`lastLoadedAt='2026-11-13T01:00:00Z';toggleMode()`);
  assert.equal(run('lastLoadedAt'),null);
  assert.equal(run('loadFailed'),false);
  assert.ok(run(`$('#mode-notice').textContent`).includes('가상 시나리오'));
  await run('load()');
  assert.equal(run('loadFailed'),true);
  assert.ok(run(`$('#mode-notice').textContent`).includes('실제 뉴스가 아닙니다'));
});

test('archive feed preserves every stored article and opens historical details', () => {
  const run=ui();
  run(`view='feed';mode='live';sort='context';data={articles:[],intelligence:{ranking_stale:false,events:[],ranking:[]}};
    archiveData={articles:[{id:'old',title:'과거 상품 안내',source:'test',themes:[],score:0},{id:'same-event',title:'같은 사건의 다른 원문',source:'test',themes:[],score:0}],total:100,next_cursor:'next'};`);
  assert.equal(run('filteredArticles().length'),2);
  assert.equal(run(`findArticle('old').title`),'과거 상품 안내');
  run('render()');
  assert.ok(run(`$('#list-caption').textContent`).includes('누적 보관'));
  assert.ok(!run(`$('#archive-tools').hidden`));
  assert.ok(!run(`$('#archive-next').disabled`));
  assert.ok(run(`$('#articles').innerHTML`).includes('과거 상품 안내'));
});

test('archive requests encode filters and late responses cannot replace newer search results', async () => {
  const requests=[];
  const run=ui({fetch:url=>new Promise(resolve=>requests.push({url,resolve}))});
  run(`view='feed';mode='live';data={articles:[],sources:[]};query='수주 & 취소';archiveSince='2026-11-11';`);
  const old=run('loadArchive(true)');
  run(`query='새 검색'`);
  const latest=run('loadArchive(true)');
  assert.equal(new URL(requests[0].url,'http://localhost').searchParams.get('q'),'수주 & 취소');
  requests[1].resolve({ok:true,json:async()=>({articles:[],sources:[],total:2,next_cursor:null})});
  await latest;
  requests[0].resolve({ok:true,json:async()=>({articles:[],sources:[],total:999,next_cursor:null})});
  await old;
  assert.equal(run('archiveData.total'),2);
  assert.equal(run('archiveLoading'),false);
});

test('failed archive search never substitutes recent feed articles for historical results', async () => {
  const run=ui({fetch:async()=>({ok:false})});
  run(`view='feed';mode='live';data={articles:[{id:'recent',title:'최근 피드 기사',source:'test',themes:[],score:50}],sources:[]};`);
  await run('loadArchive(true)');
  assert.equal(run('allArticles().length'),0);
  assert.ok(run(`$('#archive-page-status').textContent`).includes('조회 실패'));
});

test('market panel preserves delay disclosure and exposes incomplete market context', () => {
  const run=ui();
  run(`data={articles:[],sources:[],intelligence:{market:{as_of:'2026-11-13T01:00:00Z',missing:['SPY'],observations:[{code:'069500',name:'KODEX 200',change_percent:1,traded_at:'2026-11-13T09:59:00+09:00',delay_label:'<15분 지연>',market_status:'OPEN'}]}}};render()`);
  let html=run(`$('#market-snapshot').innerHTML`);
  assert.ok(html.includes('시장 자료 일부 누락'));
  assert.ok(html.includes('&lt;15분 지연&gt;'));
  assert.ok(html.includes('시장 조회'));
  run(`data.intelligence.market.observations=[];render()`);
  html=run(`$('#market-snapshot').innerHTML`);
  assert.ok(html.includes('시장 자료 조회 실패'));
  assert.ok(!html.includes('+0.00%'));
});

test('collection view exposes unfinished coverage and escapes provider errors', () => {
  const run=ui();
  run(`data={articles:[],sources:[],collection:{day:'2026-11-12',next_page:73,last_success:'2026-11-12T10:00:00Z',complete_at:null,last_error:'<script>provider error</script>'}};render()`);
  const html=run(`$('#source-view').innerHTML`);
  assert.ok(html.includes('날짜별 대조'));
  assert.ok(html.includes('73페이지'));
  assert.ok(html.includes('진행 중'));
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(!html.includes('<script>'));
});

test('unchanged polling preserves article buttons and changed news is rendered', () => {
  const run=ui();
  run(`view='feed';data={articles:[{id:'a',title:'계약 발표',source:'test',themes:[],score:50}],intelligence:{}};
    let writes=0;let content='';
    Object.defineProperty($('#articles'),'innerHTML',{get(){return content},set(v){content=v;writes++}});
    renderList();renderList();`);
  assert.equal(run('writes'),1);
  run(`data.articles[0].title='계약 취소';renderList();`);
  assert.equal(run('writes'),2);
  assert.ok(run(`$('#articles').innerHTML`).includes('계약 취소'));
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
  run(`quotes['003470']={status:'pending'}`);
  assert.ok(run(`quoteHTML('003470')`).includes('조회 대기'));
  assert.ok(!run(`quoteHTML('003470')`).includes('실패'));
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
  assert.equal(run(`filteredArticles().map(a=>a.id).join(',')`),'a,b,c,d');
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

test('decision card puts compact stocks before the event and exposes why and next check safely', () => {
  const run=ui();
  run(`data={articles:[{id:'a',title:'공급 계약',source:'공개 피드',themes:[],related_stocks:[{code:'005930',name:'삼성전자'}]}],intelligence:{ranking_stale:false,events:[{event_id:'e',certainty:'계획',articles:[{id:'a'}]}],assessments:[{event_id:'e',watch_for:'계약 공시 확인'}],ranking:[{event_id:'e',reason:'<수주>가 이익에 미칠 영향'}]}}`);
  const html=run(`articleHTML(data.articles[0],0)`);
  assert.ok(html.indexOf('stock-chip')<html.indexOf('class="article-title"'));
  assert.ok(html.includes('<dt>왜 지금</dt>'));
  assert.ok(html.includes('<dt>다음 확인</dt><dd>계약 공시 확인</dd>'));
  assert.ok(html.includes('&lt;수주&gt;'));
  assert.ok(html.includes('계획'));
  assert.ok(html.includes('기사·근거 보기'));
  run(`data.intelligence.ranking_stale=true`);
  const stale=run(`articleHTML(data.articles[0],0)`);
  assert.ok(!stale.includes('왜 지금'));
  assert.ok(!stale.includes('읽기 순위'));
});

test('market context shows only representative ETF observations with timestamps, not invented live prices', () => {
  const run=ui();
  run(`data={articles:[],intelligence:{ranking_stale:true,market:{observations:[{code:'SPY',name:'S&P500 ETF',change_percent:-1.25,traded_at:'2026-11-10T16:00:00-05:00'},{code:'069500',name:'KOSPI200 ETF',change_percent:0.5,traded_at:'2026-11-11T15:30:00+09:00'},{code:'XLE',name:'에너지',change_percent:3}]}}};render()`);
  const html=run(`$('#market-snapshot').innerHTML`);
  assert.ok(html.includes('-1.25%'));
  assert.ok(html.includes('+0.50%'));
  assert.ok(!html.includes('에너지'));
  assert.ok(html.includes('11. 11.'));
  assert.ok(!html.includes('실시간'));
  run(`data.intelligence.daily_call_limit=null;render()`);
  assert.ok(run(`$('#source-view').innerHTML`).includes('일일 제한 없음'));
  run(`data.intelligence.daily_call_limit=200;render()`);
  assert.ok(run(`$('#source-view').innerHTML`).includes('일일 한도 200회'));
});

test('article detail shows structured facts and keeps evidence and scoring behind one disclosure', () => {
  const run=ui();
  run(`data={articles:[{id:'a',title:'신규 계약',source:'공개 피드',themes:[],score_parts:{freshness:40},reason:'제목 설명',related_stocks:[{code:'005930',name:'삼성전자'}]}],intelligence:{events:[{event_id:'e',summary:'새 공급 계약을 발표했다.',certainty:'확정',event_type:'수주',amount:'100억원',timing:'2026년',model:'test-model',articles:[{id:'a',evidence:['<검증된 원문>'],url:'javascript:bad'}]}],assessments:[{event_id:'e',reason:'매출 변화 확인',watch_for:'공시 확인',stock_relevance:'주식 판단 재료'}]}};renderDetail('a')`);
  const html=run(`$('#detail').innerHTML`);
  const [visible,more]=html.split('<details class="detail-more">');
  assert.ok(visible.includes('핵심 사건'));
  assert.ok(visible.includes('<dt>규모</dt><dd>100억원</dd>'));
  assert.ok(visible.includes('<dt>사건 상태</dt><dd>확정</dd>'));
  assert.ok(visible.includes('매출 변화 확인'));
  assert.ok(visible.includes('공시 확인'));
  assert.ok(visible.includes('stock-chip'));
  assert.ok(!visible.includes('blockquote'));
  assert.ok(!visible.includes('최신성 40점'));
  assert.ok(more.includes('&lt;검증된 원문&gt;'));
  assert.ok(more.includes('최신성 40점'));
  assert.ok(more.includes('test-model'));
  assert.ok(!html.includes('javascript:'));
  assert.ok(!html.includes('<details class="detail-more" open'));
  run(`data.intelligence.events=[]`);
  const pending=run(`readingHTML(data.articles[0])`);
  assert.ok(pending.includes('본문 분석 대기'));
  assert.ok(!pending.includes('100억원'));
});

test('persistent event revisions stay inside the optional detail disclosure and escape sources', () => {
  const run=ui();
  run(`data={articles:[{id:'a',title:'계약 정정',source:'test',themes:[],score_parts:{freshness:40}}],intelligence:{events:[{event_id:'e',summary:'정정',articles:[{id:'a'}],history:[{event_title:'<취소>',summary:'<원문>',certainty:'부인',amount:'미확인',source_url:'javascript:bad'}]}]}};renderDetail('a')`);
  const html=run(`$('#detail').innerHTML`);
  const [visible,more]=html.split('<details class="detail-more">');
  assert.ok(!visible.includes('기사·사건 이력'));
  assert.ok(more.includes('기사·사건 이력 1건'));
  assert.ok(more.includes('&lt;취소&gt;'));
  assert.ok(more.includes('부인'));
  assert.ok(!more.includes('javascript:'));
  run(`data.intelligence.queue={pending:40,processing:1,retrying:2,done:6,event_count:5,oldest_wait_seconds:120,recent_p95_seconds:90};render()`);
  const source=run(`$('#source-view').innerHTML`);
  assert.ok(source.includes('분석 대기열'));
  assert.ok(source.includes('40건'));
  assert.ok(source.includes('2분'));
});

test('assessment reviews show the review time and stay distinct from source revisions', () => {
  const run=ui();
  const html=run(`eventHistoryHTML({history:[{event_title:'계약',summary:'원문 유지',assessment_review:true,stock_relevance:'연결 미확인',assessment_reason:'<구체적 변화 없음>',analyzed_at:'2026-11-11T00:00:00Z',reviewed_at:'2026-11-13T02:00:00Z'}]})`);
  assert.ok(html.includes('분석 기준 재검토'));
  assert.ok(html.includes('판정: 연결 미확인'));
  assert.ok(html.includes('&lt;구체적 변화 없음&gt;'));
  assert.ok(html.includes(run(`dateTime('2026-11-13T02:00:00Z')`)));
  assert.ok(!html.includes(run(`dateTime('2026-11-11T00:00:00Z')`)));
  const missing=run(`eventHistoryHTML({history:[{summary:'시각 미기록',assessment_review:true,analyzed_at:'2026-11-11T00:00:00Z'}]})`);
  assert.ok(missing.includes('검토 시각 미확인'));
  assert.ok(!missing.includes(run(`dateTime('2026-11-11T00:00:00Z')`)));
});

test('latency view separates live analyses and model waits from accumulated work', () => {
  const run=ui();
  run(`data={articles:[],sources:[],intelligence:{queue:{pending:3000,processing:1,retrying:20,done:100,event_count:80,oldest_wait_seconds:72000,recent_p95_seconds:70000,live_analysis:{samples:12,p50_seconds:40,p95_seconds:84,pending:2,oldest_unfinished_seconds:9100}},usage:{timings:[{task:'rank',samples:3,p50_seconds:25,p95_seconds:120,failed:1}]}}};render()`);
  const html=run(`$('#source-view').innerHTML`);
  assert.ok(html.includes('실시간 등록 자료'));
  assert.ok(html.includes('1.4분'));
  assert.ok(html.includes('2.5시간'));
  assert.ok(html.includes('순위 검토'));
  assert.ok(html.includes('전송·응답 오류 1회'));
  assert.ok(html.includes('최종 추천 공개까지의 시간은 포함하지 않습니다'));
  run(`data.intelligence.queue.live_analysis={samples:0,pending:0,p50_seconds:null,p95_seconds:null,oldest_unfinished_seconds:null};data.intelligence.usage.timings=[];render()`);
  const empty=run(`$('#source-view').innerHTML`);
  assert.ok(empty.includes('집계 대기'));
  assert.ok(empty.includes('측정 표본을 모으는 중'));
  assert.ok(!empty.includes('0.0초'));
});

test('a changed headline cannot inherit the previous version model event or rank', () => {
  const run=ui();
  run(`data={articles:[{id:'a',title:'계약 취소',source:'test',themes:[],score:50}],intelligence:{ranking_stale:false,events:[{event_id:'e',articles:[{id:'a',article_title:'계약 체결'}]}],assessments:[{event_id:'e'}],ranking:[{event_id:'e'}]}}`);
  assert.equal(run(`eventFor(data.articles[0])`),undefined);
  assert.equal(run(`hasContextRanking()`),false);
  assert.equal(run(`filteredArticles().length`),0);
  run(`view='feed'`);
  assert.equal(run(`filteredArticles().length`),1);
  assert.equal(run(`safeLink('https://:secret@example.com')`),null);
});

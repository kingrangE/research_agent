// Issue #24: real Chromium, fixed inputs, private traces, no application changes.
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {readFile, writeFile, appendFile, mkdir, copyFile, rm} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import os from 'node:os';

export function distribution(values) {
  const sorted=values.filter(Number.isFinite).sort((a,b)=>a-b);
  const p=q=>sorted.length ? sorted[Math.ceil(sorted.length*q)-1] : null;
  return {n:sorted.length,p50:p(.50),p95:p(.95),p99:p(.99)};
}

export function aggregate(rows, value, budget=null, minimum=100) {
  const success=rows.filter(r=>r.status==='success');
  const counts=Object.fromEntries(['success','empty','error','timeout','blocked','unsupported','cancelled'].map(s=>[s,rows.filter(r=>r.status===s).length]));
  const times=distribution(success.map(r=>r[value]));
  return {attempted:rows.length,counts,empty_rate:rows.length ? counts.empty/rows.length : null,
    by_status:Object.fromEntries(Object.keys(counts).map(status=>[status,distribution(rows.filter(r=>r.status===status).map(r=>r[value]))])),
    failure_rate:rows.length ? (counts.error+counts.timeout)/rows.length : null,success_only:times,budget_ms:budget,
    verdict:budget==null || times.n<minimum ? 'unverified' : times.p95>budget || counts.error+counts.timeout>0 ? 'unmet' : 'met'};
}

export function attachResourceTimings(requests,entries,origin) {
  const available=[...entries];
  for(const r of requests) {
    const start=r.wall_time*1000-origin;
    let index=-1,distance=Infinity;
    available.forEach((e,i)=>{const delta=Math.abs(e.start-start);if(e.url===r.url && delta<distance){index=i;distance=delta;}});
    if(index<0 || distance>1000){r.timing_status='unverified_missing_resource_timing';continue;}
    const e=available.splice(index,1)[0];
    if(!(e.response_start>=e.start && e.response_end>=e.response_start)) {r.timing_status='unverified_invalid_resource_timing';continue;}
    r.ttfb_ms=e.response_start-e.start;r.total_ms=e.response_end-e.start;
    r.resource_timing=e;r.timing_status='verified_resource_timing';
  }
}

function instrument() {
  performance.setResourceTimingBufferSize(10000);
  window.__bench={responses:{},pending:{},metrics:{},longTasks:[],duplicates:0,errors:[]};
  const b=window.__bench;
  const intervals=[],set=window.setInterval;
  window.setInterval=(...args)=>{const id=set.apply(window,args);intervals.push(id);return id;};
  b.finish=()=>intervals.forEach(id=>clearInterval(id));
  new PerformanceObserver(list=>b.longTasks.push(...list.getEntries().map(e=>({start:e.startTime,duration:e.duration})))).observe({type:'longtask',buffered:true});
  const original=window.fetch;
  window.fetch=async (...args)=>{
    const url=String(args[0]);
    if(url.startsWith('/api/articles?'))b.latestArchive={url,at:performance.now()};
    if(b.pending[url])b.duplicates++;
    b.pending[url]=(b.pending[url]||0)+1;
    try {
      const response=await original(...args);
      const clone=response.clone();
      clone.json().then(data=>{b.responses[url]={ok:response.ok,status:response.status,data,at:performance.now()};}).catch(()=>{});
      return response;
    } catch(error) {b.responses[url]={ok:false,error:error.name,at:performance.now()};throw error;}
    finally {b.pending[url]--;}
  };
  b.visible=selector=>[...document.querySelectorAll(selector)].some(e=>{
    const r=e.getBoundingClientRect();return r.width>0 && r.height>0 && r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth && getComputedStyle(e).visibility!=='hidden';
  });
  b.response=prefix=>Object.entries(b.responses).filter(([url])=>url.startsWith(prefix)).sort((a,c)=>c[1].at-a[1].at)[0]?.[1];
  b.resourceTimings=()=>performance.getEntriesByType('resource').filter(e=>e.name.startsWith(location.origin+'/api/')).map(e=>({url:e.name,start:e.startTime,request_start:e.requestStart,response_start:e.responseStart,response_end:e.responseEnd,transfer_bytes:e.transferSize}));
  b.arm=(key,test,navigation=false)=>{
    const metric={start:navigation?0:performance.now(),status:'pending'};
    b.metrics[key]=metric;
    const click=()=>{metric.start=performance.now();};
    if(!navigation)document.addEventListener('click',click,{once:true,capture:true});
    const deadline=performance.now()+20000;
    const check=()=>{
      let state;
      try {state=test(b);} catch(error) {state={status:'error',reason:error.name};}
      if(state) {
        metric.dom_ms=performance.now()-metric.start;
        Object.assign(metric,state);
        // Two animation frames bound a rendering opportunity; not a physical display timestamp.
        requestAnimationFrame(()=>requestAnimationFrame(()=>{metric.display_ms=performance.now()-metric.start;metric.done=true;}));
      } else if(performance.now()>deadline)Object.assign(metric,{status:'timeout',done:true});
      else requestAnimationFrame(check);
    };
    requestAnimationFrame(check);
  };
  window.addEventListener('error',e=>b.errors.push(e.error?.name||'pageerror'));
}

const marketPredicate=`
  const r=b.response('/api/market-watch');if(!r)return;
  if(!r.ok){if(b.visible('#market-view [role="status"]'))return {status:'error',reason:'market_request'};return;}
  const d=r.data;if(!d.candidates?.length){if(b.visible('#market-view .market-toolbar') && !document.querySelector('[data-market-select]'))return {status:'empty',reason:d.benchmark?.recent?.status||'no_candidates',candidates:0,stocks:0,articles:0};return;}
  if(b.visible('[data-market-select]'))return {status:'success',candidates:d.candidates.length,stocks:d.candidates[0].stocks.length,articles:document.querySelectorAll('.market-news-row').length};`;

async function startServer(config, directory) {
  const started=performance.now();
  const child=spawn(config.python,[config.serverScript,'--serve',directory,'--as-of',config.clock],{stdio:['ignore','pipe','pipe']});
  let errors='';child.stderr.on('data',chunk=>{errors+=chunk;});
  const lines=createInterface({input:child.stdout});
  const ready=new Promise((res,rej)=>{
    lines.once('line',line=>{try{res(JSON.parse(line));}catch(error){rej(error);}});
    child.once('exit',code=>rej(new Error(`Offline server exited ${code}: ${errors.slice(-2000)}`)));
  });
  const {port}=await ready;
  return {url:`http://127.0.0.1:${port}`,startup_ms:performance.now()-started,async stop(){
    const exited=new Promise(res=>child.once('exit',res));child.kill('SIGTERM');await exited;
    if(errors)await appendFile(join(config.output,'server-errors.log'),errors);
  }};
}

async function journey(browser,config,host,device,network,cache,iteration,trace=false) {
  const context=await browser.newContext({viewport:device.viewport,timezoneId:'Asia/Seoul',locale:'ko-KR',serviceWorkers:'block'});
  await context.route('**/*',route=>new URL(route.request().url()).origin===host ? route.continue() : route.abort('blockedbyclient'));
  if(cache==='injected_market_failure')await context.route('**/api/market-watch?*',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"evaluation injected failure"}'}));
  if(trace)await context.tracing.start({screenshots:true,snapshots:true,sources:false});
  await context.addInitScript(instrument);
  const page=await context.newPage(),cdp=await context.newCDPSession(page);
  await cdp.send('Network.enable');await cdp.send('Network.setCacheDisabled',{cacheDisabled:true});
  await cdp.send('Network.emulateNetworkConditions',{offline:false,...network.conditions});
  await cdp.send('Emulation.setCPUThrottlingRate',{rate:network.cpu});
  const requests=[],inflight=new Map(),steps=[];
  let duplicates=0;
  cdp.on('Network.requestWillBeSent',e=>{
    if(e.type!=='Fetch' && e.type!=='XHR')return;
    const path=new URL(e.request.url).pathname;
    if(!path.startsWith('/api/'))return;
    if([...inflight.values()].some(r=>r.url===e.request.url))duplicates++;
    const row={id:e.requestId,path,url:e.request.url,start:e.timestamp,wall_time:e.wallTime,status:'pending'};
    inflight.set(e.requestId,row);requests.push(row);
  });
  cdp.on('Network.responseReceived',e=>{const r=inflight.get(e.requestId);if(r){r.http_status=e.response.status;r.response=e.timestamp;r.cdp_event_ttfb_ms=(e.timestamp-r.start)*1000;}});
  cdp.on('Network.loadingFinished',e=>{const r=inflight.get(e.requestId);if(r){r.cdp_total_ms=(e.timestamp-r.start)*1000;r.bytes=e.encodedDataLength;r.status=r.http_status>=200&&r.http_status<300?'success':'error';inflight.delete(e.requestId);}});
  cdp.on('Network.loadingFailed',e=>{const r=inflight.get(e.requestId);if(r){r.status=/TIMED_OUT/.test(e.errorText)?'timeout':'error';r.reason=e.errorText;r.cdp_total_ms=(e.timestamp-r.start)*1000;inflight.delete(e.requestId);}});
  const arm=(key,source)=>page.evaluate(`window.__bench.arm(${JSON.stringify(key)},b=>{${source}})`);
  const finish=async key=>{
    await page.waitForFunction(key=>window.__bench.metrics[key]?.done,key,{timeout:22000});
    const row=await page.evaluate(key=>window.__bench.metrics[key],key);steps.push({step:key,...row});return row;
  };
  const blocked=(names,reason)=>names.forEach(step=>steps.push({step,status:'blocked',reason}));
  const openMeasuredStock=async(button,attribute,capture=true)=>{
    const code=await button.getAttribute(attribute);
    await arm('stock_quote',`
      if(!document.querySelector('#stock-dialog')?.open)return;
      const code=${JSON.stringify(code)},r=b.response('/api/quotes');if(!r)return;
      if(!r.ok)return {status:'error',reason:'quote_request'};
      const q=r.data.quotes?.[code];if(!q)return;
      if(!Number.isFinite(q.price) || !Number.isFinite(q.change_percent))return {status:'empty',reason:'incomplete_recorded_quote',stocks:0};
      if(document.querySelector('#stock-detail [data-stock-code]')?.dataset.stockCode!==code)return {status:'error',reason:'wrong_quote_code'};
      if(b.visible('#stock-detail .stock-values'))return {status:'success',stocks:1,stale:true};`);
    await arm('stock_chart',`
      const r=b.response('/api/stock-timeline?code=${encodeURIComponent(code)}');if(!r)return;
      if(!r.ok)return {status:'error',reason:'chart_request'};
      if(r.data.code!==${JSON.stringify(code)})return {status:'error',reason:'wrong_chart_code'};
      const n=r.data.points?.filter(p=>Number.isFinite(p.at)&&Number.isFinite(p.price)&&p.price>0).length||0;
      if(n<2)return {status:'empty',reason:r.data.status,points:n};
      if(b.visible('#stock-timeline svg')) {
        const rendered=(document.querySelector('#stock-timeline svg path')?.getAttribute('d')?.match(/[ML]/g)||[]).length;
        if(rendered!==n || document.querySelector('#stock-detail [data-stock-code]')?.dataset.stockCode!==${JSON.stringify(code)})return {status:'error',reason:'wrong_rendered_chart'};
        const source=b.response('/api/articles?')?.data.articles||b.response('/api/dashboard')?.data.articles||[];
        const expected=source.filter(a=>a.related_stocks?.some(s=>s.code===${JSON.stringify(code)})).sort((a,z)=>(Date.parse(z.published_at)||0)-(Date.parse(a.published_at)||0)).slice(0,8);
        const shown=[...document.querySelectorAll('#stock-timeline [data-chart-news]')].map(e=>e.dataset.chartNews);
        if(shown.length!==expected.length || !shown.every((id,i)=>id===expected[i].id))return {status:'error',reason:'wrong_chart_news'};
        return {status:'success',points:n,rendered_points:rendered,stocks:1,articles:shown.length,coverage_8:shown.length===8};
      }`);
    await button.click();
    await finish('stock_quote');
    await page.locator('#stock-timeline').scrollIntoViewIfNeeded();
    await finish('stock_chart');
    if(trace && capture)await page.screenshot({path:join(config.output,`${device.name}-${network.name}-${cache}-chart.png`)});
    await page.locator('[data-close-stock]').click();
  };
  let diagnostics={};
  try {
    await page.addInitScript(`document.addEventListener('DOMContentLoaded',()=>window.__bench.arm('market_entry',b=>{${marketPredicate}},true));`);
    await page.goto(host+'/?market-preview=1',{waitUntil:'domcontentloaded',timeout:20000});
    const market=await finish('market_entry');
    if(market.status==='success' && !config.stockOnly) {
      // Select an actual theme, never relabel a single-stock candidate as a theme.
      const theme=await page.evaluate(()=>window.__bench.response('/api/market-watch').data.candidates.find(c=>c.kind==='theme'));
      if(theme) {
        await arm('theme_information',`
          const d=b.response('/api/market-watch')?.data;const c=d?.candidates.find(c=>c.id===${JSON.stringify(theme.id)});
          if(!c)return {status:'error',reason:'theme_missing'};
          const chosen=document.querySelector('[data-market-select][aria-pressed="true"]');
          if(chosen?.dataset.marketSelect!==c.id)return;
          const expected=b.response('/api/dashboard')?.data.articles.filter(a=>a.related_stocks?.some(s=>c.stocks.some(t=>t.code===s.code)))||[];
          const ids=[...new Set(expected.sort((a,z)=>Date.parse(z.published_at)-Date.parse(a.published_at)).map(a=>a.url||a.id))].slice(0,8);
          const news=[...document.querySelectorAll('.market-news-row')];const codes=[...document.querySelectorAll('.market-table [data-market-stock]')].map(e=>e.dataset.marketStock);
          if(codes.length!==c.stocks.length || !codes.every(code=>c.stocks.some(s=>s.code===code)))return {status:'error',reason:'wrong_stocks'};
          if(!ids.length)return {status:'empty',reason:'no_related_news',stocks:codes.length,articles:0};
          if(news.length!==ids.length)return {status:'error',reason:'wrong_news_count'};
          const shown=news.map(e=>e.querySelector('[data-detail]')?.dataset.detail);
          if(!shown.every(id=>expected.some(a=>a.id===id)))return {status:'error',reason:'wrong_news_ids'};
          if(b.visible('.market-news-row'))return {status:'success',stocks:codes.length,articles:news.length,coverage_8:news.length===8};`);
        await page.locator('[data-market-select]').filter({has:page.locator('strong',{hasText:theme.name})}).first().click();
        await page.locator('.market-news').scrollIntoViewIfNeeded();
        await finish('theme_information');
      } else blocked(['theme_information'],'no_eligible_theme');
      await openMeasuredStock(page.locator('[data-market-stock]').first(),'data-market-stock');
    } else blocked(config.stockOnly?['theme_information']:['theme_information','stock_quote','stock_chart'],'no_valid_market_candidate');
    const archivePredicate=`
      const key=KEY,request=b.latestArchive,r=request && b.responses[request.url];
      if(!r || request.at<b.metrics[key].start || r.at<b.metrics[key].start)return;
      const params=new URLSearchParams(request.url.split('?')[1]);
      if(params.get('q')!==document.querySelector('#search').value || (key==='archive_next_page' && !params.get('cursor')))return;
      if(document.querySelector('#archive-page-status').textContent.includes('조회 중'))return;
      if(!r.ok)return {status:'error',reason:'archive_request'};
      const expected=r.data.articles||[];if(!expected.length)return {status:'empty',reason:'no_articles',articles:0};
      const shown=[...document.querySelectorAll('#articles article')];
      if(shown.length!==expected.length)return;
      const buttons=[...document.querySelectorAll('#articles [data-detail]')];
      if(!expected.every(a=>buttons.some(e=>e.dataset.detail===a.id)))return {status:'error',reason:'wrong_article_ids'};
      if(b.visible('#articles article'))return {status:'success',articles:expected.length,coverage_30:expected.length===30,total:r.data.total};`;
    const articleWatch=key=>archivePredicate.replace('KEY',JSON.stringify(key));
    await arm('archive_first_page',articleWatch('archive_first_page'));
    await page.locator('nav [data-view="feed"]').click();
    await finish('archive_first_page');
    // A fixed search term from the preflight scenario, identical on both viewports.
    await arm('archive_search',articleWatch('archive_search'));
    await page.locator('#search').fill(config.stockOnly?'삼성전자':'삼성');
    await finish('archive_search');
    if(config.stockOnly) {
      const button=page.locator('#articles [data-stock="005930"]').first();
      if(await button.count()) {
        const opens=cache==='warm'?config.repetitions:1;
        for(let sample=0;sample<opens;sample++) {
          await openMeasuredStock(button,'data-stock',sample===0);
          for(const row of steps.slice(-2))row.sample=sample;
          if(opens>1 && (sample+1)%25===0)process.stdout.write(`${device.name}/${network.name}: stock ${sample+1}/${opens}\n`);
        }
      }
      else blocked(['stock_quote','stock_chart'],'no_matching_stock_in_news');
    } else {
      // Clear search through the real input before paging the unfiltered 30-row list.
      await arm('archive_clear',articleWatch('archive_clear'));
      await page.locator('#search').fill('');await finish('archive_clear');
      if(await page.locator('#archive-next').isEnabled()) {
        await arm('archive_next_page',articleWatch('archive_next_page'));
        await page.locator('#archive-next').click();await finish('archive_next_page');
      } else blocked(['archive_next_page'],'no_next_cursor');
    }
    diagnostics=await page.evaluate(()=>({time_origin_ms:performance.timeOrigin,resource_timings:window.__bench.resourceTimings(),long_tasks:window.__bench.longTasks,js_errors:window.__bench.errors,
      resource_count:performance.getEntriesByType('resource').length,
      resource_bytes:performance.getEntriesByType('resource').reduce((s,r)=>s+r.transferSize,0)}));
  } catch(error) {
    steps.push({step:'journey',status:error.name==='TimeoutError'?'timeout':'error',reason:error.name,message:error.message});
    if(!trace)await page.screenshot({path:join(config.output,`${device.name}-${network.name}-${cache}-${iteration}-failure.png`),fullPage:true}).catch(()=>{});
    diagnostics=await page.evaluate(()=>({time_origin_ms:performance.timeOrigin,resource_timings:window.__bench?.resourceTimings(),metrics:window.__bench?.metrics,js_errors:window.__bench?.errors,
      response_states:Object.fromEntries(Object.entries(window.__bench?.responses||{}).map(([url,r])=>[url,{ok:r.ok,status:r.status,at:r.at}]))})).catch(()=>({}));
  } finally {
    // Stop periodic refresh only after all measured clicks; retain late response timings before closing.
    await page.evaluate(()=>window.__bench?.finish()).catch(()=>{});
    await page.waitForLoadState('networkidle',{timeout:20000}).catch(()=>{});
    Object.assign(diagnostics,await page.evaluate(()=>({time_origin_ms:performance.timeOrigin,resource_timings:window.__bench?.resourceTimings(),
      resource_count:performance.getEntriesByType('resource').length,resource_bytes:performance.getEntriesByType('resource').reduce((s,r)=>s+r.transferSize,0)})).catch(()=>({})));
    attachResourceTimings(requests,diagnostics.resource_timings||[],diagnostics.time_origin_ms);
    for(const r of inflight.values()){r.status='cancelled';r.reason='unfinished_at_journey_end';}
    if(trace) {
      await page.screenshot({path:join(config.output,`${device.name}-${network.name}-${cache}.png`),fullPage:true});
      await context.tracing.stop({path:join(config.output,`${device.name}-${network.name}-${cache}.zip`)});
    }
    await context.close();
  }
  return {device:device.name,network:network.name,cache,scenario:config.stockOnly?'supplemental_news_to_stock':cache==='injected_market_failure'?'injected_503_on_private_browser_route':'recorded_observations',iteration,steps,requests,duplicates,...diagnostics};
}

export async function main(configPath) {
  const config=JSON.parse(await readFile(configPath,'utf8'));
  const require=createRequire(import.meta.url),{chromium}=require(config.playwrightModule);
  const browser=await chromium.launch({headless:true,...(config.chrome?{executablePath:config.chrome}:{})});
  const plan={browser:browser.version(),node:process.version,host:os.hostname(),scenario:config.stockOnly?'supplemental_news_to_stock':'market_journey',search:config.stockOnly?'삼성전자':'삼성',
    devices:[{name:'desktop',viewport:{width:1440,height:900}},{name:'narrow',viewport:{width:390,height:844}}],
    networks:[{name:'local_unlimited',cpu:1,conditions:{latency:0,downloadThroughput:-1,uploadThroughput:-1}},
      {name:'limited',cpu:4,conditions:{latency:80,downloadThroughput:1250000,uploadThroughput:625000}}],
    display_clock:'performance.now; click capture / navigation start → valid DOM → two requestAnimationFrame callbacks (rendering opportunity, physical paint unverified)',
    cache:config.stockOnly?'restart-first and warmup: one stock open each; warm: configured repeated modal opens in one prepared browser context; HTTP cache disabled':
      'fresh browser context and disabled browser HTTP cache each journey; server restart-first / warmed server separate',
    trace:'first measured journey of every device/network/cache; all requests and step timings retained for every journey',
    api_clock:'Native ResourceTiming responseStart/startTime/responseEnd; raw CDP event timestamps are diagnostics only',
    failure_scenario:config.stockOnly?'not repeated; see primary market journey':'one private browser route 503 injection per device/network; never inject into operational services; separate from observed errors',
    unsupported:['memory-only reset','derived-cache-absent'],budgets_ms:{market_entry:2500,theme_information:1000,api:1000}};
  await writeFile(join(config.output,'browser-plan.json'),JSON.stringify(plan,null,2));
  const rows=[];
  try {
    for(const device of plan.devices)for(const network of plan.networks) {
      const working=join(config.output,`working-${device.name}-${network.name}`);await mkdir(working);
      for(const name of ['news.sqlite3','event_facts.sqlite3','market.sqlite3','data_jobs.sqlite3','price_tracking.sqlite3'])await copyFile(join(config.snapshot,name),join(working,name));
      const server=await startServer(config,working);
      try {
        await appendFile(join(config.output,'server-starts.jsonl'),JSON.stringify({device:device.name,network:network.name,startup_ms:server.startup_ms})+'\n');
        const first=await journey(browser,config,server.url,device,network,'restart_first',0,true);
        rows.push(first);await appendFile(join(config.output,'raw.jsonl'),JSON.stringify(first)+'\n');
        await journey(browser,config,server.url,device,network,'warmup',0);
        for(let i=0;i<(config.stockOnly?1:config.repetitions);i++) {
          const row=await journey(browser,config,server.url,device,network,'warm',i,i===0);
          rows.push(row);await appendFile(join(config.output,'raw.jsonl'),JSON.stringify(row)+'\n');
          if((i+1)%25===0)process.stdout.write(`${device.name}/${network.name}: ${i+1}/${config.repetitions}\n`);
        }
        if(!config.stockOnly){
        const failure=await journey(browser,config,server.url,device,network,'injected_market_failure',0,true);
        rows.push(failure);await appendFile(join(config.output,'raw.jsonl'),JSON.stringify(failure)+'\n');
        }
      } finally {await server.stop();await rm(working,{recursive:true});}
    }
  } finally {await browser.close();}
  const groups=[];
  for(const device of plan.devices)for(const network of plan.networks)for(const cache of ['restart_first','warm','injected_market_failure']) {
    const journeys=rows.filter(r=>r.device===device.name&&r.network===network.name&&r.cache===cache);
    if(!journeys.length)continue;
    const steps=journeys.flatMap(r=>r.steps),requests=journeys.flatMap(r=>r.requests);
    const names=[...new Set(steps.map(s=>s.step))];
    groups.push({device:device.name,network:network.name,cache,journeys:journeys.length,
      steps:Object.fromEntries(names.map(name=>[name,aggregate(steps.filter(s=>s.step===name),'display_ms',plan.budgets_ms[name]??null)])),
      api:Object.fromEntries([...new Set(requests.map(r=>r.path))].map(path=>{
        const values=requests.filter(r=>r.path===path);
        return [path,{...aggregate(values,'total_ms',cache==='warm'?1000:null),ttfb_ms:distribution(values.filter(r=>r.status==='success').map(r=>r.ttfb_ms)),response_bytes:distribution(values.map(r=>r.bytes))}];
      })),
      request_count:requests.length,duplicates:journeys.reduce((s,r)=>s+r.duplicates,0),
      long_task_ms:distribution(journeys.map(r=>(r.long_tasks||[]).reduce((s,t)=>s+t.duration,0))),
      actual_counts:steps.map(({step,status,articles,stocks,points,rendered_points,coverage_8,coverage_30})=>({step,status,articles,stocks,points,rendered_points,coverage_8,coverage_30}))});
  }
  const summary={issue:24,scenario:plan.scenario,groups,unsupported_cache_states:plan.unsupported,
    all_targets_passed:false,release_approved:false,
    limitations:['Shared host contention; no isolated hardware claim','No physical paint timestamp; two-frame rendering opportunity is a proxy',
      'Registered securities only; recorded quotes retain stale timestamps','Market journey stock paths require candidates; supplemental news-to-stock results stay separate',
      'No before/after comparison; no human navigation/understanding study','Restart-first has one sample per configuration, not a tail-latency estimate']};
  await writeFile(join(config.output,'summary.json'),JSON.stringify(summary,null,2));
  // An honest unmet/unverified budget is a result; infrastructure/automation failure is a failed run.
  return rows.some(r=>r.steps.some(s=>s.step==='journey')) ? 1 : 0;
}

if(process.argv[1] && import.meta.url===pathToFileURL(resolve(process.argv[1])).href) {
  main(process.argv[2]).then(code=>{process.exitCode=code;}).catch(error=>{console.error(error);process.exitCode=1;});
}

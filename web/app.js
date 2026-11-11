const icons = {
  grid:'<rect x="3" y="3" width="7" height="7" rx="1.4"/><rect x="14" y="3" width="7" height="7" rx="1.4"/><rect x="3" y="14" width="7" height="7" rx="1.4"/><rect x="14" y="14" width="7" height="7" rx="1.4"/>',
  layers:'<path d="m12 3 10 6-10 6L2 9l10-6Z"/><path d="m3 13 9 5 9-5M3 17l9 5 9-5"/>',
  bookmark:'<path d="M6 4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v17l-6-4-6 4V4Z"/>',
  radio:'<circle cx="12" cy="12" r="2"/><path d="M7 7a7 7 0 0 0 0 10M17 7a7 7 0 0 1 0 10M4 4a11 11 0 0 0 0 16M20 4a11 11 0 0 1 0 16"/>',
  refresh:'<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 6a8 8 0 0 1 13 3M18 18a8 8 0 0 1-13-3"/>',
  search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  link:'<path d="m10 13 4-4M8 15l-1 1a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0M16 9l1-1a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0" transform="translate(0 -1)"/>',
  orbit:'<circle cx="12" cy="12" r="3"/><ellipse cx="12" cy="12" rx="10" ry="6" transform="rotate(-35 12 12)"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7v1"/>',
  sparkles:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/>',
  document:'<path d="M14 3H5v18h14V8l-5-5Z"/><path d="M14 3v5h5M8 12h8M8 16h6"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  filter:'<path d="M3 5h18l-7 8v6l-4 2v-8L3 5Z"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.document}</svg>`;
document.querySelectorAll('[data-icon]').forEach(el => { el.innerHTML = icon(el.dataset.icon); });
const $ = selector => document.querySelector(selector);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeLink = value => { try { const u = new URL(value); return ['https:','http:'].includes(u.protocol) && !u.username ? u.href : null; } catch { return null; } };
const dateTime = value => value ? new Date(value).toLocaleString('ko-KR', {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit', timeZone:'Asia/Seoul'}) : '발행 시각 미제공';
const quoteTime = value => value ? new Date(value).toLocaleString('ko-KR', {month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',timeZone:'Asia/Seoul'}) : '미제공';
const quotes = {};
let quoteInFlight = false;
function quoteHTML(code) {
  if (mode === 'demo') return '<span class="quote-unavailable">가상 자료 · 시세 미조회</span>';
  const q = quotes[code];
  if (!q) return '<span class="quote-unavailable">시세 조회 대기</span>';
  if (!Number.isFinite(q.price) || !Number.isFinite(q.change_percent)) return '<span class="quote-unavailable">시세 조회 실패 · 원문에서 확인</span>';
  const stale = q.status !== 'ok' || Date.now() - new Date(q.fetched_at).getTime() > 30000;
  const direction = q.change_percent > 0 ? 'up' : q.change_percent < 0 ? 'down' : 'flat';
  const price = q.currency === 'USD' ? `$${q.price.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}` : `${q.price.toLocaleString('ko-KR')}<small>원</small>`;
  return `<span class="stock-values"><strong>${price}</strong><span class="stock-change ${direction}">${q.change_percent > 0 ? '+' : ''}${q.change_percent.toFixed(2)}%<small>전일 대비</small></span></span><span class="quote-time ${stale ? 'stale' : ''}">${stale ? '이전 조회 · ' : ''}시세 기준 ${escape(quoteTime(q.traded_at))} · ${escape(q.delay_label)}${q.market_status === 'CLOSE' ? ' · 장마감' : ''}<span>출처 ${escape(q.source)} · ${q.currency === 'USD' ? '미국 정규장 · ' : ''}조회 ${escape(quoteTime(q.fetched_at))} (한국시간)</span></span>`;
}
function changeHTML(code) {
  if (mode === 'demo') return '<span class="quote-unavailable">—</span>';
  const q = quotes[code];
  if (!Number.isFinite(q?.change_percent)) return `<span class="quote-unavailable" title="${q ? '시세 조회 실패' : '시세 조회 대기'}">—</span>`;
  const stale = q.status !== 'ok' || Date.now() - new Date(q.fetched_at).getTime() > 30000;
  const direction = q.change_percent > 0 ? 'up' : q.change_percent < 0 ? 'down' : 'flat';
  return `<span class="stock-change ${direction}${stale ? ' stale' : ''}" title="${stale ? '이전 조회 · ' : ''}${escape(q.delay_label || '')} · 시세 기준 ${escape(quoteTime(q.traded_at))}"${stale ? ' aria-label="이전 조회 등락률"' : ''}>${q.change_percent > 0 ? '+' : ''}${q.change_percent.toFixed(2)}%${stale ? '<span aria-hidden="true">*</span>' : ''}</span>`;
}
function stockAnalysisHTML(article) {
  const analysis=article.stock_analysis;
  if(!analysis?.events?.length && !analysis?.entities?.length) return '';
  return `<section class="event-analysis"><div class="related-stocks-label">기사에서 찾은 사건과 연결 경로</div><div class="article-tags">${(analysis.events || []).map(e=>`<span class="tag">${escape(e.name)}</span>`).join('')}</div><p>${escape(analysis.event_state || '')}</p>${(analysis.entities || []).filter(e=>!e.code).map(e=>`<p>${escape(e.name)}: ${escape(e.listing_note || '직접 거래 종목 미확인')}</p>`).join('')}<p>제목과 공개 사업 근거를 연결한 관찰 후보입니다. 관련 종목의 수혜·피해나 매수·매도 판단은 확정하지 않습니다.</p></section>`;
}
function stocksHTML(article, expanded=false) {
  const related = article.related_stocks || [];
  if (!related.length) return `<div class="stock-empty">${data?.stock_status?.status === 'loading' ? '국내·미국 종목 목록을 확인하고 있어요.' : data?.stock_status?.status === 'error' ? '종목 목록 수집 실패 · 관련 종목 확인 불가' : '근거를 갖춰 연결할 상장 종목을 아직 찾지 못했어요.'}</div>`;
  if (!expanded) return `<div class="stock-chips" aria-label="관련 주식">${related.map(stock=>`<button class="stock-chip" data-stock="${escape(stock.code)}" data-article="${escape(article.id)}" aria-haspopup="dialog" aria-label="${escape(stock.name)} 주식 상세"><span>${escape(stock.name)}</span><span data-stock-code="${escape(stock.code)}" data-compact>${changeHTML(stock.code)}</span></button>`).join('')}</div>`;
  const labels={direct:'직접 언급',documented:'공개 관계',value_chain:'가치사슬 추론',theme:'테마 관찰',business:'사업 연관 후보'};
  return `<section class="related-stocks" aria-label="관련 주식"><div class="related-stocks-label">관련 주식 ${related.length}<span>국내·미국 · 근거별 구분</span></div>${(expanded ? related : related.slice(0,3)).map(s=>`<div class="stock-card"><div class="stock-heading"><a href="https://stock.naver.com/${s.country === 'US' ? 'worldstock' : 'domestic'}/stock/${encodeURIComponent(s.code)}" target="_blank" rel="noopener noreferrer">${escape(s.name)} <small>${escape(s.code)} ↗</small></a><span class="relation-badge ${s.relation !== 'direct' ? 'inferred' : ''}">${labels[s.relation] || '관찰 후보'}</span></div><span class="stock-market">${s.country === 'US' ? '미국' : '국내'} · ${escape(s.market || '')}${s.role ? ` · ${escape(s.role)}` : ''}${s.connection_kind ? ` · ${escape(s.connection_kind)}` : ''}</span><p class="stock-reason">${escape(s.path || s.reason)}</p>${expanded ? `<p class="stock-mechanism">${escape(s.mechanism || s.reason)}</p><p class="stock-confidence">${escape(s.confidence || '조건부 관찰 후보')} · ${escape(s.impact || '영향 미정')}</p><details class="stock-evidence"><summary>근거 ${(s.sources || []).length}개 · 추가 확인할 조건</summary>${(s.sources || []).filter(source=>safeLink(source.url)).map(source=>`<a href="${escape(safeLink(source.url))}" target="_blank" rel="noopener noreferrer">${escape(source.title)} ↗</a><small>공개 ${escape(source.published_on || '날짜 미제공')} · 검토 ${escape(source.checked_on || '미제공')}</small>`).join('')}${s.other_paths?.length ? `<p>추가 경로: ${s.other_paths.map(escape).join(' / ')}</p>` : ''}<ul>${(s.required_checks || []).map(check=>`<li>${escape(check)}</li>`).join('')}</ul><p>${escape(s.materiality || '기사 사건의 매출·이익 영향 미산정')}</p></details>` : `<button class="stock-evidence-link" data-detail="${escape(article.id)}">연결 근거·확인할 조건 보기 ↗</button>`}<div class="stock-quote" data-stock-code="${escape(s.code)}">${quoteHTML(s.code)}</div></div>`).join('')}${!expanded && related.length > 3 ? `<button class="more-stocks" data-detail="${escape(article.id)}">관련 주식 ${related.length}개와 연결 근거 모두 보기 ↗</button>` : ''}</section>`;
}
function paintQuotes() {
  document.querySelectorAll('[data-stock-code]').forEach(el=>{el.innerHTML=el.hasAttribute('data-compact') ? changeHTML(el.dataset.stockCode) : quoteHTML(el.dataset.stockCode);});
}
async function loadQuotes() {
  if (mode !== 'live' || quoteInFlight || document.hidden) return;
  const container = $('#stock-dialog').open ? $('#stock-detail') : $('#detail-dialog').open ? $('#detail') : $('#articles');
  const codes = [...new Set([...container.querySelectorAll('[data-stock-code]')].filter(el=>{const r=el.getBoundingClientRect(); return r.width>0 && r.height>0 && r.bottom>0 && r.top<window.innerHeight;}).map(el=>el.dataset.stockCode))]
    .filter(code=>!quotes[code] || Date.now()-new Date(quotes[code].fetched_at || 0).getTime()>=10000).slice(0,20);
  if (!codes.length) return;
  quoteInFlight = true;
  try {
    const response = await fetch(`/api/quotes?codes=${encodeURIComponent(codes.join(','))}`, {signal:AbortSignal.timeout(15000)});
    if (!response.ok) throw new Error('시세 응답 오류');
    const result = await response.json(); Object.assign(quotes,result.quotes);
  } catch { codes.forEach(code=>{quotes[code]={...quotes[code],status:'stale'};}); }
  finally { quoteInFlight=false; paintQuotes(); }
}
function ago(value) {
  if (!value) return '시각 미제공';
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(value)) / 60000));
  if (minutes < 1) return '방금 전';
  if (minutes < 60) return `${minutes}분 전`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}시간 전`;
  return `${Math.floor(minutes / 1440)}일 전`;
}
let data = null, mode = 'live', view = 'briefing', kind = 'all', theme = '', query = '', sort = 'context', detailId = null, requestId = 0, loading = false;
let saved = [], feedback = {};
try { const stored = JSON.parse(localStorage.getItem('maekrak-saved') || '[]'); if (Array.isArray(stored)) saved = stored.filter(a => a && typeof a.id === 'string' && typeof a.title === 'string').slice(0,200); } catch {}
try { const stored = JSON.parse(localStorage.getItem('maekrak-feedback') || '{}'); if (stored && !Array.isArray(stored) && typeof stored === 'object') feedback = stored; } catch {}
function persist(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { toast('브라우저 저장 공간을 사용할 수 없어 이번 화면에서만 보관합니다.'); } }
function toast(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => { $('#toast').hidden = true; }, 3000); }
function allArticles() { return view === 'saved' ? saved.filter(a => a.mode === mode) : (data?.articles || []); }
function findArticle(id) { return data?.articles.find(a => a.id === id) || saved.find(a => a.id === id && a.mode === mode); }
function isSaved(id) { return saved.some(a => a.id === id && a.mode === mode); }
function toggleSave(id) {
  const article = findArticle(id); if (!article) return;
  if (isSaved(id)) { saved = saved.filter(a => a.id !== id || a.mode !== mode); toast('저장을 해제했어요.'); }
  else { if (saved.length >= 200) { toast('저장 한도는 200개입니다. 기존 자료를 정리해 주세요.'); return; } saved.push({...article, mode}); toast('저장했어요. 이 브라우저에서 다시 볼 수 있어요.'); }
  persist('maekrak-saved', saved); render();
  if (detailId) renderDetail(detailId);
}
function chooseTheme(id) { theme = theme === id ? '' : id; if (view === 'sources') view = 'briefing'; render(); }
function eventFor(article) {
  return data?.intelligence?.events?.find(e=>e.articles.some(a=>a.id === article.id));
}
function hasContextRanking() {
  if (sort !== 'context' || view === 'saved' || data?.intelligence?.ranking_stale) return false;
  return Boolean(data?.intelligence?.assessments?.some(r=>data.intelligence.events?.some(e=>e.event_id === r.event_id && e.articles.some(a=>data.articles.some(article=>article.id === a.id)))));
}
function filteredArticles() {
  const list = allArticles().filter(a => (kind === 'all' || a.kind === kind) && (!theme || a.themes.some(t => t.id === theme)) && (!query || `${a.title} ${a.source} ${a.themes.map(t=>t.name).join(' ')} ${(a.related_stocks || []).map(s=>s.name+' '+s.code).join(' ')}`.toLowerCase().includes(query.toLowerCase())));
  list.sort((a,b)=>b.score-a.score || (b.published_at || '').localeCompare(a.published_at || ''));
  if (hasContextRanking()) {
    const rank = new Map(data.intelligence.ranking.map((r,i)=>[r.event_id,i]));
    const seen = new Set();
    return list.filter(a=>{const e=eventFor(a);if (!e || !rank.has(e.event_id)) return view === 'feed';if(seen.has(e.event_id)) return false;seen.add(e.event_id);return true;})
      .sort((a,b)=>(rank.get(eventFor(a)?.event_id) ?? Infinity)-(rank.get(eventFor(b)?.event_id) ?? Infinity));
  }
  if (sort === 'context' && view === 'briefing') return [];
  return sort === 'latest' ? list.sort((a,b)=>(b.published_at || '').localeCompare(a.published_at || '')) : list;
}
function readingHTML(article) {
  const e=eventFor(article);
  if(!e) return '';
  const ranking=(data?.intelligence?.assessments || data?.intelligence?.ranking)?.find(r=>r.event_id === e.event_id);
  return `<section class="detail-block model-reading"><h3>본문에서 찾은 사건 · 모델 분석</h3><p>${escape(e.summary)}</p><div class="article-tags"><span class="tag">${escape(e.certainty)}</span><span class="tag">${escape(e.event_type)}</span></div><p>금액: ${escape(e.amount)} · 시점: ${escape(e.timing)}</p>${e.articles.map(a=>`<blockquote>${(a.evidence || []).map(escape).join(' / ')}</blockquote>${safeLink(a.url) ? `<a class="reading-source" href="${escape(safeLink(a.url))}" target="_blank" rel="noopener noreferrer">근거 원문 ↗</a>` : ''}`).join('')}${ranking ? `<p>주식 판단 적합성: ${escape(ranking.stock_relevance || '이전 기준 분석')}${ranking.driver ? ` · ${escape(ranking.driver)}` : ''}${ranking.assessed_at ? ` · 검토 ${escape(dateTime(ranking.assessed_at))}` : ''}</p><p>판단 근거: ${ranking.stock_relevance && ranking.stock_relevance !== '주식 판단 재료' ? '기본 추천에서 제외했습니다. 현재 자료에서 주식의 손익·가치·수급 판단을 바꿀 구체적인 근거가 충분하지 않습니다.' : escape(ranking.reason)}</p>${ranking.watch_for && ranking.stock_relevance === '주식 판단 재료' ? `<div class="detail-question">다음 확인: ${escape(ranking.watch_for)}</div>` : ''}` : ''}<p class="detail-meta">${escape(e.model)} · 분석 ${escape(dateTime(e.analyzed_at))}${e.body_truncated ? ' · 본문 일부 분석' : ''} · 동일 사건 ${e.articles.length}건 · 공개 추출 본문 분석 · 전문 전체를 보장하지 않습니다. 모델 판단은 검수 전입니다.</p></section>`;
}

function articleHTML(a, index) {
  const e=eventFor(a), ranked=hasContextRanking() && data?.intelligence?.ranking?.find(r=>r.event_id === e?.event_id);
  return `<article class="article-card"><div class="article-rank">${String(index+1).padStart(2,'0')}</div><div class="article-body"><div class="article-meta"><span class="kind-badge ${a.kind === 'report' ? 'report' : ''}">${a.kind === 'report' ? 'REPORT' : 'NEWS'}</span><span>${escape(a.source)}</span><span class="meta-dot">·</span><time title="${escape(dateTime(a.published_at))}">${escape(ago(a.published_at))}</time>${a.copies > 1 ? `<span class="meta-dot">·</span><span>유사 제목 ${a.copies}건 묶음</span>` : ''}</div><button class="article-title" data-detail="${escape(a.id)}">${escape(a.title)}</button><p class="article-reason">${ranked ? `모델 판단 · ${escape(ranked.reason)}${e.articles.length > 1 ? ` · 동일 사건 ${e.articles.length}건` : ''}` : escape(a.reason)}</p><div class="article-footer"><div class="article-tags">${a.themes.slice(0,3).map(t=>`<button class="tag" data-theme="${escape(t.id)}">${escape(t.name)}</button>`).join('')}${!a.themes.length ? '<span class="tag">일반 자료</span>' : ''}</div>${index < 3 && sort === 'priority' && view !== 'saved' ? '<span class="priority-label">먼저 살펴보기</span>' : ''}</div>${stocksHTML(a)}</div><div class="article-actions"><button class="bookmark-button" data-save="${escape(a.id)}" aria-label="${isSaved(a.id) ? '저장 해제' : '자료 저장'}: ${escape(a.title)}" aria-pressed="${isSaved(a.id)}">${icon('bookmark')}</button><button class="read-button" data-detail="${escape(a.id)}">맥락 보기 ↗</button></div></article>`;
}
function renderList() {
  const articles = filteredArticles();
  const visible = view === 'briefing' ? articles.slice(0,8) : articles;
  $('#result-count').textContent = view === 'briefing' && articles.length > 8 ? `8 / ${articles.length}` : articles.length;
  $('#articles').setAttribute('aria-busy', String(!data && loading));
  if (!data && loading) { $('#articles').innerHTML = '<div class="loading-state"><span class="loader"></span><h3>자료를 불러오고 있어요</h3><p>선택한 모드의 자료를 확인합니다.</p></div>'; return; }
  $('#theme-active').hidden = !theme;
  $('#theme-active').innerHTML = theme ? `<button data-clear-theme>주제: ${escape(data?.themes.find(t=>t.id === theme)?.name || theme)} ×</button>` : '';
  const firstPending = hasContextRanking() ? visible.findIndex(a=>!data.intelligence.ranking.some(r=>r.event_id === eventFor(a)?.event_id)) : -1;
  if (articles.length) $('#articles').innerHTML = visible.map((a,i)=>(i === firstPending ? '<div class="ranking-divider">아직 모델 순위가 없는 자료 · 최신성순</div>' : '')+articleHTML(a,i)).join('') + (view === 'briefing' && articles.length > 8 ? `<button class="full-list-button" data-view="feed">전체 자료 ${articles.length}건 살펴보기 ↗</button>` : '');
  else {
    const isReport = kind === 'report' && mode === 'live';
    const contextEmpty = sort === 'context' && view === 'briefing' && !query && !theme && kind === 'all' && data?.articles.length;
    const title = contextEmpty ? (hasContextRanking() ? '현재 분석에서 추천할 주식 판단 재료가 없어요' : data?.intelligence?.status === 'disabled' ? '주식 분석 모델이 연결되지 않았어요' : '주식 판단 재료를 분석하고 있어요') : view === 'saved' ? '아직 저장한 자료가 없어요' : isReport ? '리포트 자동 수집은 아직 연결되지 않았어요' : !data?.articles.length ? '아직 수집된 자료가 없어요' : '조건에 맞는 자료가 없어요';
    const description = contextEmpty ? '기준을 통과한 사건만 추천합니다. 상품 안내·배경 기사·미분석 자료는 전체 자료에서 확인할 수 있어요.' : view === 'saved' ? '자료 옆의 북마크를 눌러 나중에 읽을 자료를 모아보세요.' : isReport ? '네이버 증권 리포트는 원문 사이트에서 확인할 수 있어요. 시나리오 모드에서는 연결된 화면을 체험할 수 있어요.' : !data?.articles.length ? '수집 현황을 확인하거나 가상 시나리오로 화면을 체험해 보세요.' : '검색어나 주제 필터를 바꿔 보세요.';
    $('#articles').innerHTML = `<div class="empty-state">${icon(view === 'saved' ? 'bookmark' : 'search')}<h3>${title}</h3><p>${description}</p>${contextEmpty ? '<button data-view="feed">전체 자료 보기</button>' : isReport ? '<a class="primary-button" href="https://stock.naver.com/research" target="_blank" rel="noopener noreferrer">네이버 리포트 확인 ↗</a>' : view !== 'saved' && !data?.articles.length ? '<button data-demo>시나리오 체험하기</button>' : ''}</div>`;
  }
  loadQuotes();
}
function render() {
  const articles = data?.articles || [], themes = [...(data?.themes || [])].sort((a,b)=>b.count-a.count), statuses = data?.sources || [];
  const labels = {briefing:'오늘의 브리핑',feed:'전체 자료',saved:'저장한 자료',sources:'수집 현황'};
  document.querySelectorAll('[data-view]').forEach(button=>{button.classList.toggle('active', button.dataset.view === view); button.setAttribute('aria-current', button.dataset.view === view ? 'page' : 'false'); });
  $('#page-label').textContent = labels[view];
  $('#page-title').textContent = {briefing:'오늘, 무엇을 읽어야 할까요?',feed:'흩어진 자료를 한곳에서.',saved:'다시 읽고 싶은 시장의 이야기.',sources:'정보가 들어오는 길을 확인하세요.'}[view];
  $('#page-description').textContent = {briefing:'쏟아지는 정보는 덜어내고, 지금 필요한 시장의 맥락을 살펴보세요.',feed:'같은 자료는 묶고, 주제와 키워드로 필요한 정보를 찾아보세요.',saved:'이 브라우저에 저장한 자료입니다. 실제 수집과 가상 시나리오는 따로 보관해요.',sources:'수집 성공 여부와 마지막으로 자료를 받은 시각을 확인할 수 있어요.'}[view];
  $('#nav-count').textContent = articles.length;
  $('#saved-count').textContent = saved.filter(a=>a.mode === mode).length;
  $('#focus-card').hidden = view !== 'briefing'; $('#stats').hidden = view === 'saved';
  $('.reading-section').hidden = view === 'sources'; $('#source-view').hidden = view !== 'sources';
  $('#sort').value = sort;
  $('#list-heading').firstChild.textContent = view === 'saved' ? '저장한 자료 ' : sort === 'context' ? (hasContextRanking() ? '지금 확인할 주식 판단 재료 ' : '주식 판단 재료 분석 중 ') : view === 'feed' ? '모든 자료 ' : '지금 읽어볼 자료 ';
  const ai=data?.intelligence;
  $('#list-caption').textContent = view === 'saved' ? '마지막으로 저장했을 때의 내용입니다.' : sort === 'context' ? (hasContextRanking() ? `${ai.ranking_partial ? '마지막 성공한 모델 순위 · 일부 분석' : '주식 영향 경로를 확인한 모델 참고 순위'} · 기준 ${dateTime(ai.ranked_at)} · 상품 안내·배경 기사는 전체 자료에서 확인` : `${ai?.ranking_stale && ai?.ranked_at ? '모델 순위 갱신 지연' : ai?.message || '모델 분석 대기'} · 주식 추천 미적용: 전체 자료에서 최신 기사를 확인하세요.`) : '최신성만으로 정렬해요. 주제는 점수에 반영하지 않아요.';
  const ok = statuses.filter(s=>s.status === 'ok').length;
  const stats = [
    ['document','수집한 자료',data?.raw_count ?? '—','건',mode === 'demo' ? '가상 시나리오 자료' : '최근 피드에 포함된 자료'],
    ['filter',sort === 'context' ? '모델이 분석한 사건' : '먼저 읽을 자료',sort === 'context' ? ai?.events?.length || 0 : data ? Math.min(8,articles.length) : '—','건',sort === 'context' ? '순위 생성 시각과 분석 범위 확인' : '최신성 중심으로 우선 선별'],
    ['orbit','관찰할 주제',themes.filter(t=>t.count>0).length,'개','자료에 등장한 시장 키워드'],
    ['radio','정상 수집원',mode === 'demo' ? '예시' : `${ok} / ${statuses.length || 3}`,'',mode === 'demo' ? '실시간 수집 아님' : data?.collecting ? '새 자료 수집 중' : '한국경제 공개 RSS 기준'],
  ];
  $('#stats').innerHTML = stats.map(([i,label,value,unit,caption])=>`<div class="stat"><div class="stat-label">${icon(i)}${label}</div><div class="stat-value">${value}<small>${unit}</small></div><div class="stat-caption">${caption}</div></div>`).join('');
  $('#mode-label').textContent = mode === 'demo' ? 'ILLUSTRATIVE SCENARIO' : 'YOUR DAILY SIGNAL';
  $('#mode-button').innerHTML = `${icon(mode === 'demo' ? 'radio' : 'sparkles')}${mode === 'demo' ? '실제 수집으로 돌아가기' : '시나리오 체험'}`;
  const failed = statuses.filter(s=>['error','stale'].includes(s.status));
  const notice = $('#mode-notice');
  notice.hidden = mode !== 'demo' && !failed.length;
  notice.classList.toggle('error-notice', mode !== 'demo');
  notice.textContent = mode === 'demo' ? '가상 시나리오 체험 중입니다. 아래 기사·리포트와 시장 상황은 기능 설명을 위해 만든 예시이며 실제 뉴스가 아닙니다.' : `${failed.map(s=>s.name).join(', ')} 수집에 실패했습니다. 이전 자료가 있는 경우 마지막 성공 자료를 표시합니다. 수집 현황에서 확인해 주세요.`;
  $('#update-time').textContent = mode === 'demo' ? '가상 시나리오 · 실제 시장 정보 아님' : data?.collecting ? '새 자료를 수집하고 있어요' : data?.updated_at ? `수집 확인 ${dateTime(data.updated_at)}` : '첫 자료를 수집하고 있어요';
  if (data) {
    const top = themes.filter(t=>t.count>0).slice(0,3);
    $('#focus-title').textContent = top.length ? `${top.slice(0,2).map(t=>t.name).join(' 그리고 ')}. 함께 읽을 이유가 있어요.` : '아직 관찰할 주제가 충분하지 않아요.';
    $('#focus-description').textContent = top.length ? `${articles.length}개의 자료 중 ${top[0].name} 키워드가 ${top[0].count}건에 등장했어요. 관련 자료를 비교하고, 시장의 변화인지 개별 사건인지 살펴보세요.` : '수집 자료가 들어오면 제목에서 발견한 주제별로 자료를 연결합니다.';
    $('#focus-themes').innerHTML = top.map(t=>`<button class="focus-tag" data-theme="${escape(t.id)}">${escape(t.name)}<small>${t.count}건 ↗</small></button>`).join('');
  }
  $('#themes').innerHTML = themes.filter(t=>t.count>0).slice(0,5).map(t=>`<button class="theme-row" data-theme="${escape(t.id)}" aria-pressed="${theme === t.id}"><div><span class="theme-name"><span class="theme-dot"></span>${escape(t.name)}</span><span class="theme-count">${t.count}건</span></div><div class="theme-track"><div class="theme-fill"></div></div></button>`).join('') || '<p class="panel-description">자료를 기다리고 있어요.</p>';
  $('#themes').querySelectorAll('.theme-fill').forEach((el,i)=>{el.style.width = `${Math.round(themes.filter(t=>t.count>0)[i].count/(themes[0]?.count || 1)*100)}%`;});
  const primary = themes.find(t=>t.id === theme) || themes.find(t=>t.count>0);
  $('#connections').innerHTML = primary ? `<div class="connection-route"><span class="connection-node">${escape(primary.name)}</span><span class="connection-arrow">→</span><span class="connection-node">${escape(primary.links[0])}</span></div><div class="connection-route-label">함께 확인: ${primary.links.slice(1).map(escape).join(' · ')}</div>` : '<p class="panel-description">자료가 모이면 함께 확인할 경로를 보여드려요.</p>';
  $('#sources').innerHTML = statuses.map(s=>`<div class="source-row"><span class="source-logo">H</span><div class="source-info">${escape(s.name)}<small>${s.status === 'demo' ? '가상 수집원' : s.last_success ? `${escape(ago(s.last_success))} 수집 · ${s.count}건` : s.error ? '연결 확인 필요' : '첫 수집 대기 중'}</small></div><span class="source-status ${escape(s.status)}">${{ok:'정상',stale:'이전 자료',error:'실패',demo:'예시'}[s.status] || '대기'}</span></div>`).join('') || '<p class="panel-description">공개 피드에 연결하고 있어요.</p>';
  $('#source-view').innerHTML = statuses.map(s=>`<div class="source-detail"><h3>${escape(s.name)}</h3><span class="source-status ${escape(s.status)}">${{ok:'정상 수집',stale:'수집 실패 · 마지막 성공 자료 유지',error:'수집 실패',demo:'가상 시나리오'}[s.status] || '대기'}</span><p>자료 ${s.count}건 · 마지막 성공: ${s.last_success ? escape(dateTime(s.last_success)) : '아직 없음'}${s.error ? `<br>${escape(s.error)}` : ''}</p>${safeLink(s.url) ? `<a href="${escape(safeLink(s.url))}" target="_blank" rel="noopener noreferrer">공개 RSS 확인 ↗</a>` : ''}</div>`).join('') + '<div class="source-detail"><h3>네이버 증권 리포트</h3><span class="source-status stale">자동 수집 미연결 · 원문 링크 제공</span><p>현재 페이지가 별도 요청으로 자료를 불러와 이번 시제품에는 자동 수집을 연결하지 않았습니다. 본문과 PDF를 분석한 결과는 제공하지 않습니다.</p><a href="https://stock.naver.com/research" target="_blank" rel="noopener noreferrer">리포트 원문 사이트 ↗</a></div><div class="source-detail"><h3>선별 방식</h3><p>발행 직후 최신성 50점에서 첫 60분 동안 25점까지 선형 감소하고, 이후 시간당 1점씩 최저 0점까지 감소합니다. 자료 유형에 따른 가점은 없습니다. 주제 분류는 필터용이며 점수에 반영하지 않습니다. 수집원은 현재 한국경제 한 곳으로, 여러 매체의 교차 검증은 제공하지 않습니다. 관련 국내·미국 종목의 현재가·전일 대비 등락률은 Npay 증권에서 조회합니다. 환율·거래량과 주도주 판별은 미연결입니다.</p></div>';
  const stored=data?.archive;
  $('#source-view').innerHTML += `<div class="source-detail"><h3>전체 수집 · 누적 보관</h3><p>수집과 보관에는 추천 적합성 필터를 적용하지 않습니다. 일반 금융 뉴스·상품 안내·행사도 함께 보관합니다.</p><p>기사 ${stored?.articles || 0}건 · RSS 기록 ${stored?.revisions || 0}개 · 공개 본문 ${stored?.bodies || 0}건 · 본문 대기 ${stored?.pending || 0}건 · 실패 ${stored?.errors || 0}건</p><p>${escape(data?.archive_error || stored?.message || '서버 재시작 후에도 보관 자료를 유지합니다. 전체 자료 화면은 최근 피드 목록이며 누적 기록은 별도로 보관합니다.')}</p><p>본문은 추천 모델과 독립적으로 수집합니다. 공개 추출 내용만 지원하며 로그인·유료 전문은 보장하지 않습니다.</p></div>`;
  const stockStatus = data?.stock_status;
  $('#source-view').innerHTML += `<div class="source-detail"><h3>관련 주식 · KRX / Nasdaq / Npay 증권</h3><p>공식 상장 목록 ${stockStatus?.count || 0}개 (국내 ${stockStatus?.markets?.KR || 0} · 미국 ${stockStatus?.markets?.US || 0}) · 목록 상태 ${escape(stockStatus?.status || 'loading')} · 마지막 갱신 ${escape(dateTime(stockStatus?.updated_at))}</p><p>기사의 직접 언급, 출처가 있는 사업 관계, 가치사슬 추론, 테마 관찰을 구분해 국내·미국 관련 종목을 연결합니다. 관계의 출처·공개일·검토일과 추가 확인할 조건을 제공합니다. 최신성 점수는 별도로 유지하며, 기본 추천은 주식 적합성 검토를 통과한 사건의 모델 순위를 사용합니다. 관련 후보는 수혜·피해 판정이 아닙니다. 시세는 화면에 보이는 종목부터 조회하며 10초 동안 재사용합니다. 실패한 시세는 이전 조회로 표시하고 거래 기준 시각과 조회 시각을 함께 제공합니다.</p></div>`;
  document.querySelectorAll('[data-kind]').forEach(b=>{b.classList.toggle('active',b.dataset.kind === kind); b.setAttribute('aria-pressed',String(b.dataset.kind === kind));});
  $('#source-view').innerHTML += `<div class="source-detail"><h3>본문 분석 · 사건 묶기 · 시장 맥락순</h3><p>${escape(ai?.message || '가상 시나리오에서는 모델 분석 미사용')} · ${escape(ai?.model || '')}</p><p>모델 요청 ${ai?.usage?.calls_today || 0}회 / 일일 한도 ${ai?.daily_call_limit || '—'}회 · 마지막 분석 ${escape(dateTime(ai?.updated_at))}</p><p>${escape(ai?.market?.limitations || '시장 자료 대기')}</p>${(ai?.market?.observations || []).map(q=>`<p>${escape(q.name)} ${q.change_percent > 0 ? '+' : ''}${Number(q.change_percent).toFixed(2)}% · 기준 ${escape(quoteTime(q.traded_at))}${q.relative_to_spy_pp !== undefined ? ` · S&P500 대비 ${Number(q.relative_to_spy_pp).toFixed(2)}%p` : ''}</p>`).join('')}<p>${escape(ai?.error || '')}${ai?.market?.missing?.length ? ` · 시장 자료 누락: ${ai.market.missing.map(escape).join(', ')}` : ''}</p></div>`;
  renderList();
}
function renderDetail(id) {
  const a = findArticle(id); if (!a) return;
  detailId = id;
  const related = (data?.articles || []).filter(b=>b.id !== id && b.themes.some(t=>a.themes.some(at=>at.id === t.id))).slice(0,3);
  const link = safeLink(a.url), selectedFeedback = feedback[`${mode}:${id}`];
  $('#detail').innerHTML = `<div class="detail-top"><span>${mode === 'demo' ? '가상 자료 · 기능 체험' : '자료의 맥락'}</span><button data-close aria-label="상세 닫기">×</button></div><div class="detail-content"><div class="detail-meta">${escape(a.source)} · ${escape(dateTime(a.published_at))}</div><h2 id="detail-title">${escape(a.title)}</h2><div class="article-tags">${a.themes.map(t=>`<span class="tag">${escape(t.name)}</span>`).join('')}</div>${readingHTML(a)}${stockAnalysisHTML(a)}${stocksHTML(a)}<section class="detail-block"><h3>왜 이 자료를 골랐나요?</h3><p>${escape(a.reason)}</p><div class="detail-question">${escape(a.question)}</div><p class="detail-meta">주제·관련주 연결은 제목 기반입니다. 별도 본문 분석도 근거 범위 내의 모델 해석이며 사실 검증을 완료한 결과는 아닙니다.</p></section><section class="detail-block"><h3>선별 근거를 투명하게</h3><p>${(a.score_parts.relevance !== undefined || a.score_parts.report !== undefined) ? '이전 선별 기준으로 저장된 자료입니다. 현재 기준 점수는 최신 목록에서 확인해 주세요.' : `최신성 ${a.score_parts.freshness}점 (추가 가점 없음)`}</p><p>점수는 읽을 순서를 위한 시제품 규칙이며 투자 가치나 사실 신뢰도 점수가 아닙니다.</p></section><section class="detail-block"><h3>함께 읽고 비교해 보세요</h3>${related.length ? related.map(b=>`<button class="related-link" data-detail="${escape(b.id)}">${escape(b.title)}<small>${escape(b.source)} · 같은 주제의 키워드가 등장한 자료</small></button>`).join('') : '<p>함께 비교할 자료가 아직 없어요.</p>'}</section><div class="detail-bottom">${link ? `<a class="primary-button" href="${escape(link)}" target="_blank" rel="noopener noreferrer">원문에서 확인하기 ↗</a>` : '<span class="saved-note">가상 예시이므로 실제 원문은 없습니다.</span>'}<div class="feedback"><span>도움이 됐나요?</span><button data-feedback="useful" class="${selectedFeedback === 'useful' ? 'selected' : ''}">도움돼요</button><button data-feedback="irrelevant" class="${selectedFeedback === 'irrelevant' ? 'selected' : ''}">관련 적음</button></div></div></div>`;
  loadQuotes();
}
function openStock(articleId, code) {
  const article = findArticle(articleId);
  const stock = article?.related_stocks?.find(s=>s.code === code);
  if (!stock) return;
  $('#stock-detail').innerHTML = `<div class="detail-top"><span>관련 주식 상세</span><button data-close-stock aria-label="주식 상세 닫기">×</button></div><div class="detail-content"><h2 id="stock-title">${escape(stock.name)}</h2><p class="detail-meta">${escape(article.title)}</p>${stocksHTML({...article,related_stocks:[stock]},true)}</div>`;
  $('#stock-dialog').showModal();
  loadQuotes();
}
async function load() {
  const current = ++requestId;
  loading = true; $('#refresh').disabled = true;
  try {
    const response = await fetch(mode === 'demo' ? '/api/demo' : '/api/dashboard');
    if (!response.ok) throw new Error('응답 오류');
    const next = await response.json();
    if (current !== requestId) return;
    data = next; render(); paintQuotes(); loadQuotes(); return true;
  } catch {
    if (current !== requestId) return;
    toast('서버에 연결하지 못했어요. 서버 실행 상태를 확인해 주세요.');
    if (!data) { $('#articles').innerHTML = '<div class="empty-state"><h3>서버에 연결할 수 없어요</h3><p>실행 중인 서버를 확인한 뒤 새로고침해 주세요.</p></div>'; $('#articles').setAttribute('aria-busy','false'); }
  } finally { if (current === requestId) { loading = false; $('#refresh').disabled = false; } }
}
function toggleMode() { mode = mode === 'live' ? 'demo' : 'live'; data = null; theme = ''; query = ''; kind = 'all'; $('#search').value = ''; $('#stock-dialog').close(); $('#detail-dialog').close(); detailId = null; loading = true; render(); load(); }
document.addEventListener('click', event => {
  const button = event.target.closest('button'); if (!button) return;
  if (button.dataset.view) { view = button.dataset.view; theme = ''; kind = 'all'; query = ''; $('#search').value=''; render(); }
  if (button.dataset.kind) { kind = button.dataset.kind; render(); }
  if (button.dataset.theme) chooseTheme(button.dataset.theme);
  if (button.hasAttribute('data-clear-theme')) { theme = ''; render(); }
  if (button.dataset.save) toggleSave(button.dataset.save);
  if (button.dataset.stock) openStock(button.dataset.article, button.dataset.stock);
  if (button.hasAttribute('data-close-stock')) $('#stock-dialog').close();
  if (button.dataset.detail) { renderDetail(button.dataset.detail); if (!$('#detail-dialog').open) $('#detail-dialog').showModal(); }
  if (button.hasAttribute('data-close')) { $('#detail-dialog').close(); detailId=null; }
  if (button.dataset.feedback && detailId) { feedback[`${mode}:${detailId}`] = button.dataset.feedback; persist('maekrak-feedback', feedback); renderDetail(detailId); toast('의견을 이 브라우저에 기록했어요.'); }
  if (button.hasAttribute('data-demo')) toggleMode();
});
$('#mode-button').addEventListener('click',toggleMode);
$('#refresh').addEventListener('click', async()=>{if (await load()) toast('최근 수집 결과를 확인했어요. 서버 수집은 30초 간격입니다.');});
$('#show-sources').addEventListener('click',()=>{view='sources'; render(); window.scrollTo({top:0,behavior:'smooth'});});
$('#search').addEventListener('input',event=>{query=event.target.value; renderList();});
$('#sort').addEventListener('change',event=>{sort=event.target.value; render();});
$('#detail-dialog').addEventListener('click',event=>{if (event.target === $('#detail-dialog')) { const rect=event.target.getBoundingClientRect(); if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom) {event.target.close();detailId=null;} }});
$('#stock-dialog').addEventListener('click',event=>{if (event.target === $('#stock-dialog')) {const r=event.target.getBoundingClientRect(); if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom) event.target.close();}});
$('#detail-dialog').addEventListener('close',()=>{detailId=null;});
document.addEventListener('keydown',event=>{if(event.key === '/' && !['INPUT','TEXTAREA'].includes(document.activeElement.tagName) && !$('#detail-dialog').open && !$('#stock-dialog').open) {event.preventDefault(); $('#search').focus();}});
$('#today').textContent=new Date().toLocaleDateString('ko-KR',{year:'numeric',month:'long',day:'numeric',weekday:'short',timeZone:'Asia/Seoul'});
render(); load();
setInterval(()=>{if(mode === 'live' && !document.hidden && !loading) load();},5000);
let quoteScrollTimer;
document.addEventListener('scroll',()=>{clearTimeout(quoteScrollTimer);quoteScrollTimer=setTimeout(loadQuotes,150);},true);
setInterval(()=>{if(mode === 'live' && !document.hidden) {paintQuotes();loadQuotes();}},5000);

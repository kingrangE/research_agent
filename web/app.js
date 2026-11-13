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
const safeLink = value => { try { const u = new URL(value); return ['https:','http:'].includes(u.protocol) && !u.username && !u.password ? u.href : null; } catch { return null; } };
const dateTime = value => value ? new Date(value).toLocaleString('ko-KR', {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit', timeZone:'Asia/Seoul'}) : '발행 시각 미제공';
const quoteTime = value => value ? new Date(value).toLocaleString('ko-KR', {month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',timeZone:'Asia/Seoul'}) : '미제공';
const latencyText = value => !Number.isFinite(value) || value<0 ? '집계 대기' : value>=3600 ? `${(value/3600).toFixed(1)}시간` : value>=60 ? `${(value/60).toFixed(1)}분` : `${value.toFixed(1)}초`;
const quotes = {};
let quoteInFlight = false;
function quoteHTML(code) {
  if (mode === 'demo') return '<span class="quote-unavailable">가상 자료 · 시세 미조회</span>';
  const q = quotes[code];
  if (!q || q.status === 'pending') return '<span class="quote-unavailable">시세 조회 대기</span>';
  if (!Number.isFinite(q.price) || !Number.isFinite(q.change_percent)) return '<span class="quote-unavailable">시세 조회 실패 · 원문에서 확인</span>';
  const stale = q.status !== 'ok' || Date.now() - new Date(q.fetched_at).getTime() > 30000;
  const direction = q.change_percent > 0 ? 'up' : q.change_percent < 0 ? 'down' : 'flat';
  const price = q.currency === 'USD' ? `$${q.price.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}` : `${q.price.toLocaleString('ko-KR')}<small>원</small>`;
  return `<span class="stock-values"><strong>${price}</strong><span class="stock-change ${direction}">${q.change_percent > 0 ? '+' : ''}${q.change_percent.toFixed(2)}%<small>전일 대비</small></span></span><span class="quote-time ${stale ? 'stale' : ''}">${stale ? '이전 조회 · ' : ''}시세 기준 ${escape(quoteTime(q.traded_at))} · ${escape(q.delay_label)}${q.market_status === 'CLOSE' ? ' · 장마감' : ''}<span>출처 ${escape(q.source)} · ${q.currency === 'USD' ? '미국 정규장 · ' : ''}조회 ${escape(quoteTime(q.fetched_at))} (한국시간)</span></span>`;
}
function changeHTML(code) {
  if (mode === 'demo') return '<span class="quote-unavailable">—</span>';
  const q = quotes[code];
  if (!Number.isFinite(q?.change_percent)) return `<span class="quote-unavailable" title="${!q || q.status === 'pending' ? '시세 조회 대기' : '시세 조회 실패'}">—</span>`;
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
  const labels={body:'본문 언급',direct:'직접 언급',documented:'공개 관계',value_chain:'가치사슬 추론',theme:'테마 관찰',business:'사업 연관 후보'};
  return `<section class="related-stocks" aria-label="관련 주식"><div class="related-stocks-label">관련 주식 ${related.length}<span>국내·미국 · 근거별 구분</span></div>${(expanded ? related : related.slice(0,3)).map(s=>`<div class="stock-card"><div class="stock-heading"><a href="https://stock.naver.com/${s.country === 'US' ? 'worldstock' : 'domestic'}/stock/${encodeURIComponent(s.code)}" target="_blank" rel="noopener noreferrer">${escape(s.name)} <small>${escape(s.code)} ↗</small></a><span class="relation-badge ${!['direct','body'].includes(s.relation) ? 'inferred' : ''}">${labels[s.relation] || '관찰 후보'}</span></div><span class="stock-market">${s.country === 'US' ? '미국' : '국내'} · ${escape(s.market || '')}${s.role ? ` · ${escape(s.role)}` : ''}${s.connection_kind ? ` · ${escape(s.connection_kind)}` : ''}</span><p class="stock-reason">${escape(s.path || s.reason)}</p>${expanded ? `<p class="stock-mechanism">${escape(s.mechanism || s.reason)}</p><p class="stock-confidence">${escape(s.confidence || '조건부 관찰 후보')} · ${escape(s.impact || '영향 미정')}</p><details class="stock-evidence"><summary>근거 ${(s.sources || []).length}개 · 추가 확인할 조건</summary>${(s.sources || []).filter(source=>safeLink(source.url)).map(source=>`<a href="${escape(safeLink(source.url))}" target="_blank" rel="noopener noreferrer">${escape(source.title)} ↗</a>${source.excerpt ? `<blockquote>${escape(source.excerpt)}</blockquote>` : ''}<small>공개 ${escape(source.published_on || '날짜 미제공')} · 검토 ${escape(source.checked_on || '미제공')}</small>`).join('')}${s.other_paths?.length ? `<p>추가 경로: ${s.other_paths.map(escape).join(' / ')}</p>` : ''}<ul>${(s.required_checks || []).map(check=>`<li>${escape(check)}</li>`).join('')}</ul><p>${escape(s.materiality || '기사 사건의 매출·이익 영향 미산정')}</p></details>` : `<button class="stock-evidence-link" data-detail="${escape(article.id)}">연결 근거·확인할 조건 보기 ↗</button>`}<div class="stock-quote" data-stock-code="${escape(s.code)}">${quoteHTML(s.code)}</div></div>`).join('')}${!expanded && related.length > 3 ? `<button class="more-stocks" data-detail="${escape(article.id)}">관련 주식 ${related.length}개와 연결 근거 모두 보기 ↗</button>` : ''}</section>`;
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
let archiveData=null, archiveCursor='', archiveCursors=[], archiveSource='', archiveSince='', archiveUntil='', archiveLoading=false, archiveRequested=false, archiveError='', archiveRequest=0, archiveSearchTimer;
function allArticles() { return view === 'saved' ? saved.filter(a => a.mode === mode) : view==='feed' && mode==='live' && (archiveData || archiveRequested) ? (archiveData?.articles || []) : (data?.articles || []); }
function findArticle(id) { return (mode==='live' && archiveData?.articles.find(a=>a.id===id)) || data?.articles.find(a => a.id === id) || saved.find(a => a.id === id && a.mode === mode); }
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
  return data?.intelligence?.events?.find(e=>e.articles.some(a=>a.id === article.id && (!a.article_title || a.article_title === article.title)));
}
function hasContextRanking() {
  if (sort !== 'context' || view === 'saved' || rankingExpired()) return false;
  return Boolean(data?.intelligence?.assessments?.some(r=>data.articles.some(a=>eventFor(a)?.event_id === r.event_id)));
}
function rankingExpired() {
  const ai=data?.intelligence, at=Date.parse(ai?.ranked_at);
  return Boolean(ai?.ranking_stale || (ai?.ranked_at && (!Number.isFinite(at) || Date.now()-at>600000)));
}
function filteredArticles() {
  if (view==='feed' && mode==='live' && archiveData) return archiveData.articles;
  const list = allArticles().filter(a => (kind === 'all' || a.kind === kind) && (!theme || a.themes.some(t => t.id === theme)) && (!query || `${a.title} ${a.source} ${a.themes.map(t=>t.name).join(' ')} ${(a.related_stocks || []).map(s=>s.name+' '+s.code).join(' ')}`.toLowerCase().includes(query.toLowerCase())));
  list.sort((a,b)=>b.score-a.score || (Date.parse(b.published_at) || 0)-(Date.parse(a.published_at) || 0));
  if (hasContextRanking() && view!=='feed') {
    const rank = new Map(data.intelligence.ranking.map((r,i)=>[r.event_id,i]));
    const seen = new Set();
    return list.filter(a=>{const e=eventFor(a);if (!e || !rank.has(e.event_id)) return view === 'feed';if(seen.has(e.event_id)) return false;seen.add(e.event_id);return true;})
      .sort((a,b)=>(rank.get(eventFor(a)?.event_id) ?? Infinity)-(rank.get(eventFor(b)?.event_id) ?? Infinity));
  }
  if (sort === 'context' && view === 'briefing') return [];
  return sort === 'latest' ? list.sort((a,b)=>(Date.parse(b.published_at) || 0)-(Date.parse(a.published_at) || 0)) : list;
}
const recencyLabel = event => ({old:'최초 보도 26시간 경과 · 배경 자료',future:'미래 보도 시각 · 확인 필요',unknown:'보도 시각 미확인 · 배경 자료'}[event?.recency_status] || '');
function readingHTML(article) {
  const e = eventFor(article);
  const assessment = (data?.intelligence?.assessments || data?.intelligence?.ranking)?.find(r=>r.event_id === e?.event_id);
  if (!e) return `<section class="detail-overview"><h3>본문 분석 대기</h3><p>아직 본문에서 확인한 사건 정보가 없습니다.</p><div class="detail-question">확인할 것 · ${escape(article.question || '원문에서 사건 당사자와 새 사실을 확인하세요.')}</div></section>`;
  const excluded = assessment?.stock_relevance && assessment.stock_relevance !== '주식 판단 재료';
  return `<section class="detail-overview"><div class="overview-heading"><h3>핵심 사건</h3><span class="certainty-badge">모델 요약 · 검수 전</span></div><p class="event-summary">${escape(e.summary)}</p><dl class="event-facts">${[['사건 상태',e.certainty],['유형',e.event_type],['규모',e.amount],['시점',e.timing]].map(([label,value])=>`<div><dt>${label}</dt><dd>${escape(value || '미확인')}</dd></div>`).join('')}</dl></section><div class="detail-decision-grid"><section class="decision-tile"><h3>${excluded ? '추천 제외 이유' : '주식에 미칠 영향'}</h3><p>${escape(assessment?.reason || '아직 주식 영향 검토를 완료하지 않았습니다.')}</p><span class="assessment-label">${escape(recencyLabel(e) || assessment?.stock_relevance || '판단 대기')}${rankingExpired() ? ' · 갱신 지연' : ''}</span></section><section class="decision-tile next-check"><h3>다음 확인</h3><p>${escape(excluded ? '전체 자료로 보관 중입니다. 주식에 전달되는 구체적인 새 사실이 있는지 확인하세요.' : assessment?.watch_for || '원문의 새 사실과 관련 기업의 실적·가격 반영 여부를 확인하세요.')}</p></section></div>`;
}

function articleHTML(a, index) {
  const e = eventFor(a), ranked = view!=='feed' && hasContextRanking() && data?.intelligence?.ranking?.find(r=>r.event_id === e?.event_id);
  const assessment = data?.intelligence?.assessments?.find(r=>r.event_id === e?.event_id);
  return `<article class="article-card ${ranked ? 'ranked' : ''}"><div class="article-body"><div class="article-topline"><div class="article-meta">${ranked ? `<span class="article-rank" aria-label="읽기 순위 ${index+1}">${String(index+1).padStart(2,'0')}</span>` : `<span class="kind-badge">${a.kind === 'report' ? '리포트' : '뉴스'}</span>`}<span>${escape(a.source)}</span><span class="meta-dot">·</span><time title="${escape(dateTime(a.published_at))}">${escape(ago(a.published_at))}</time>${e?.certainty ? `<span class="certainty-badge" title="원문 사건 상태 · 모델 추출">사건 ${escape(e.certainty)}</span>` : ''}</div><button class="bookmark-button" data-save="${escape(a.id)}" aria-label="${isSaved(a.id) ? '저장 해제' : '자료 저장'}: ${escape(a.title)}" aria-pressed="${isSaved(a.id)}">${icon('bookmark')}</button></div>${stocksHTML(a)}<button class="article-title" data-detail="${escape(a.id)}">${escape(a.title)}</button>${ranked ? `<dl class="decision-notes"><div><dt>왜 지금</dt><dd>${escape(ranked.reason)}</dd></div><div><dt>다음 확인</dt><dd>${escape(ranked.watch_for || assessment?.watch_for || '원문의 새 사실과 관련 기업에 미칠 영향을 확인하세요.')}</dd></div></dl>` : `<p class="article-reason">${e?.summary ? escape(e.summary) : '원문과 관련 종목의 연결 근거를 확인해 보세요.'}</p><span class="assessment-label">${escape(recencyLabel(e) || assessment?.stock_relevance || '주식 영향 검토 전')}</span>`}<div class="article-footer"><div class="article-tags">${a.themes.slice(0,3).map(t=>`<button class="tag" data-theme="${escape(t.id)}">${escape(t.name)}</button>`).join('')}${e?.articles.length > 1 ? `<span class="event-count">동일 사건 ${e.articles.length}건</span>` : a.copies > 1 ? `<span class="event-count">동일 링크 ${a.copies}건</span>` : ''}</div><button class="read-button" data-detail="${escape(a.id)}">기사·근거 보기 <span aria-hidden="true">↗</span></button></div></div></article>`;
}
function renderList() {
  const articles = filteredArticles();
  const visible = view === 'briefing' ? articles.slice(0,8) : articles;
  $('#result-count').textContent = view === 'briefing' && articles.length > 8 ? `8 / ${articles.length}` : articles.length;
  $('#articles').setAttribute('aria-busy', String(!data && loading));
  if (!data && loading) { delete $('#articles').renderedHTML; $('#articles').innerHTML = '<div class="loading-state"><span class="loader"></span><h3>자료를 불러오고 있어요</h3><p>선택한 모드의 자료를 확인합니다.</p></div>'; return; }
  $('#theme-active').hidden = !theme;
  $('#theme-active').innerHTML = theme ? `<button data-clear-theme>주제: ${escape(data?.themes.find(t=>t.id === theme)?.name || theme)} ×</button>` : '';
  const firstPending = view!=='feed' && hasContextRanking() ? visible.findIndex(a=>!data.intelligence.ranking.some(r=>r.event_id === eventFor(a)?.event_id)) : -1;
  let html;
  if (articles.length) html = visible.map((a,i)=>(i === firstPending ? '<div class="ranking-divider">아직 모델 순위가 없는 자료 · 최신성순</div>' : '')+articleHTML(a,i)).join('') + (view === 'briefing' && articles.length > 8 ? `<button class="full-list-button" data-view="feed">전체 자료 ${articles.length}건 살펴보기 ↗</button>` : '');
  else {
    const isReport = kind === 'report' && mode === 'live';
    const contextEmpty = sort === 'context' && view === 'briefing' && !query && !theme && kind === 'all' && data?.articles.length;
    const title = contextEmpty ? (hasContextRanking() ? '현재 분석에서 추천할 주식 판단 재료가 없어요' : data?.intelligence?.status === 'disabled' ? '주식 분석 모델이 연결되지 않았어요' : '주식 판단 재료를 분석하고 있어요') : view === 'saved' ? '아직 저장한 자료가 없어요' : isReport ? '리포트 자동 수집은 아직 연결되지 않았어요' : !data?.articles.length ? '아직 수집된 자료가 없어요' : '조건에 맞는 자료가 없어요';
    const description = contextEmpty ? '기준을 통과한 사건만 추천합니다. 상품 안내·배경 기사·미분석 자료는 전체 자료에서 확인할 수 있어요.' : view === 'saved' ? '자료 옆의 북마크를 눌러 나중에 읽을 자료를 모아보세요.' : isReport ? '네이버 증권 리포트는 원문 사이트에서 확인할 수 있어요. 시나리오 모드에서는 연결된 화면을 체험할 수 있어요.' : !data?.articles.length ? '수집 현황을 확인하거나 가상 시나리오로 화면을 체험해 보세요.' : '검색어나 주제 필터를 바꿔 보세요.';
    html = `<div class="empty-state">${icon(view === 'saved' ? 'bookmark' : 'search')}<h3>${title}</h3><p>${description}</p>${contextEmpty ? '<button data-view="feed">전체 자료 보기</button>' : isReport ? '<a class="primary-button" href="https://stock.naver.com/research" target="_blank" rel="noopener noreferrer">네이버 리포트 확인 ↗</a>' : view !== 'saved' && !data?.articles.length ? '<button data-demo>시나리오 체험하기</button>' : ''}</div>`;
  }
  const list = $('#articles');
  if (list.renderedHTML !== html) { list.innerHTML = html; list.renderedHTML = html; }
  loadQuotes();
}
function render() {
  const articles = data?.articles || [], themes = [...(data?.themes || [])].sort((a,b)=>b.count-a.count), statuses = data?.sources || [];
  const labels = {briefing:'오늘의 브리핑',feed:'전체 자료',saved:'저장한 자료',sources:'수집 현황'};
  document.querySelectorAll('[data-view]').forEach(button=>{button.classList.toggle('active', button.dataset.view === view); button.setAttribute('aria-current', button.dataset.view === view ? 'page' : 'false'); });
  $('#page-label').textContent = labels[view];
  $('#page-title').textContent = {briefing:'지금, 어떤 종목을 봐야 할까요?',feed:'전체 자료',saved:'저장한 자료',sources:'수집·분석 현황'}[view];
  $('#page-description').textContent = {briefing:'관련 종목을 찾고, 사건의 영향과 다음 확인 사항을 살펴보세요.',feed:'누적 기사를 최신순으로 살펴보고 날짜·언론사·검색어로 직접 골라보세요.',saved:'이 브라우저에 저장한 자료입니다. 실제 수집과 가상 시나리오는 따로 보관해요.',sources:'수집 성공 여부와 마지막으로 자료를 받은 시각을 확인할 수 있어요.'}[view];
  $('#nav-count').textContent = mode==='live' ? data?.archive?.articles ?? articles.length : articles.length;
  $('#saved-count').textContent = saved.filter(a=>a.mode === mode).length;
  $('#stats').hidden = view === 'saved';
  $('.context-column').hidden = view === 'sources';
  $('.reading-section').hidden = view === 'sources'; $('#source-view').hidden = view !== 'sources';
  $('#sort').value = sort;
  $('#sort').disabled = view==='feed' && mode==='live';
  const archiveView=view==='feed' && mode==='live';
  $('#archive-tools').hidden=!archiveView; $('#archive-pagination').hidden=!archiveView;
  $('#archive-prev').disabled=archiveLoading || !archiveCursors.length;
  $('#archive-next').disabled=archiveLoading || !archiveData?.next_cursor;
  $('#archive-page-status').textContent=archiveLoading ? '누적 기사 조회 중' : archiveError || `${archiveCursors.length+1}페이지 · 조건에 맞는 기사 ${archiveData?.total ?? '—'}건`;
  const sourceOptions='<option value="">전체 언론사</option>'+(archiveData?.sources || []).map(s=>`<option value="${escape(s)}">${escape(s)}</option>`).join('');
  if ($('#archive-source').renderedHTML!==sourceOptions) { $('#archive-source').innerHTML=sourceOptions; $('#archive-source').renderedHTML=sourceOptions; }
  $('#archive-source').value=archiveSource;
  $('#list-heading').firstChild.textContent = view === 'saved' ? '저장한 자료 ' : view === 'feed' ? '전체 자료 ' : sort === 'context' ? (hasContextRanking() ? '지금 확인할 주식 판단 재료 ' : '주식 판단 재료 분석 중 ') : '지금 읽어볼 자료 ';
  const ai=data?.intelligence;
  const coverage=ai?.coverage;
  const coverageText=coverage?.candidates>0 && Number.isInteger(coverage.analyzed_articles) ? `이번 대상 ${coverage.candidates}건 중 본문 분석 ${coverage.analyzed_articles}건${coverage.analyzed_articles<coverage.candidates ? ' · 미분석 기사는 순위에서 제외' : ''}` : '';
  const rankingReady = !rankingExpired() && ai?.assessments?.length > 0;
  $('#list-caption').textContent = view === 'saved' ? '마지막으로 저장했을 때의 내용입니다.' : sort === 'context' ? (hasContextRanking() ? `${ai.ranking_partial ? '마지막 성공한 모델 순위 · 일부 분석' : '주식 영향 경로를 확인한 모델 참고 순위'} · 기준 ${dateTime(ai.ranked_at)} · 상품 안내·배경 기사는 전체 자료에서 확인` : `${rankingExpired() && ai?.ranked_at ? '모델 순위 갱신 지연' : ai?.message || '모델 분석 대기'} · 주식 추천 미적용: 전체 자료에서 최신 기사를 확인하세요.`) : '최신성만으로 정렬해요. 주제는 점수에 반영하지 않아요.';
  if (archiveView) $('#list-caption').textContent='누적 보관 기사 · 최신순 · 미분석·추천 제외 자료와 같은 사건의 원문도 각각 표시합니다.';
  if (view==='briefing' && sort==='context' && coverageText) $('#list-caption').textContent+=` · ${coverageText}`;
  const stats = [
    ['filter','주식 판단 재료',rankingReady ? ai.ranking.length : '—','건',rankingReady ? '분석 완료 자료 내 순위 · 검수 전' : '분석 대기 · 추천 미적용'],
    ['document','수집한 자료',mode==='live' ? data?.archive?.articles ?? data?.raw_count ?? '—' : data?.raw_count ?? '—','건',mode === 'demo' ? '가상 시나리오' : '배경·상품 기사도 모두 수집'],
    ['clock','분석 기준',ai?.ranked_at ? dateTime(ai.ranked_at).split('일 ')[1] || dateTime(ai.ranked_at) : '대기 중','',rankingExpired() ? '갱신 지연 · 이전 분석' : '기사 시각과 별도 확인'],
  ];
  $('#stats').innerHTML = stats.map(([i,label,value,unit,caption])=>`<div class="stat"><div class="stat-label">${icon(i)}${label}</div><div class="stat-value">${escape(value)}<small>${unit}</small></div><div class="stat-caption">${caption}</div></div>`).join('');
  $('#mode-label').textContent = mode === 'demo' ? '가상 시나리오' : '실시간 투자 브리핑';
  $('#mode-button').innerHTML = `${icon(mode === 'demo' ? 'radio' : 'sparkles')}${mode === 'demo' ? '실제 수집으로 돌아가기' : '시나리오 체험'}`;
  const failed = statuses.filter(s=>['error','stale'].includes(s.status));
  const notice = $('#mode-notice');
  notice.hidden = mode !== 'demo' && !failed.length;
  notice.classList.toggle('error-notice', mode !== 'demo');
  notice.textContent = mode === 'demo' ? '가상 시나리오 체험 중입니다. 아래 기사·리포트와 시장 상황은 기능 설명을 위해 만든 예시이며 실제 뉴스가 아닙니다.' : `${failed.map(s=>s.name).join(', ')} 수집에 실패했습니다. 이전 자료가 있는 경우 마지막 성공 자료를 표시합니다. 수집 현황에서 확인해 주세요.`;
  $('#update-time').textContent = mode === 'demo' ? '가상 시나리오 · 실제 시장 정보 아님' : data?.collecting ? '새 자료를 수집하고 있어요' : data?.updated_at ? `수집 확인 ${dateTime(data.updated_at)}` : '첫 자료를 수집하고 있어요';
  $('#themes').innerHTML = themes.filter(t=>t.count>0).slice(0,5).map(t=>`<button class="theme-row" data-theme="${escape(t.id)}" aria-pressed="${theme === t.id}"><div><span class="theme-name"><span class="theme-dot"></span>${escape(t.name)}</span><span class="theme-count">${t.count}건</span></div><div class="theme-track"><div class="theme-fill"></div></div></button>`).join('') || '<p class="panel-description">자료를 기다리고 있어요.</p>';
  $('#themes').querySelectorAll('.theme-fill').forEach((el,i)=>{el.style.width = `${Math.round(themes.filter(t=>t.count>0)[i].count/(themes[0]?.count || 1)*100)}%`;});
  const market = (ai?.market?.observations || []).filter(q=>['069500','229200','SPY'].includes(q.code));
  $('#market-snapshot').innerHTML = market.length ? market.map(q=>`<div class="market-row"><div><strong>${escape(q.name)}</strong><small>${escape(quoteTime(q.traded_at))}${q.market_status === 'CLOSE' ? ' · 장마감' : ''}</small></div><span class="stock-change ${q.change_percent > 0 ? 'up' : q.change_percent < 0 ? 'down' : 'flat'}">${Number.isFinite(q.change_percent) ? `${q.change_percent > 0 ? '+' : ''}${q.change_percent.toFixed(2)}%` : '—'}</span></div>`).join('') : '<p class="panel-description">시장 자료를 기다리고 있어요.</p>';
  $('#sources').innerHTML = statuses.map(s=>`<div class="source-row"><span class="source-logo">H</span><div class="source-info">${escape(s.name)}<small>${s.status === 'demo' ? '가상 수집원' : s.last_success ? `${escape(ago(s.last_success))} 수집 · ${s.count}건` : s.error ? '연결 확인 필요' : '첫 수집 대기 중'}</small></div><span class="source-status ${escape(s.status)}">${{ok:'정상',stale:'이전 자료',error:'실패',demo:'예시'}[s.status] || '대기'}</span></div>`).join('') || '<p class="panel-description">공개 피드에 연결하고 있어요.</p>';
  $('#source-view').innerHTML = statuses.map(s=>`<div class="source-detail"><h3>${escape(s.name)}</h3><span class="source-status ${escape(s.status)}">${{ok:'정상 수집',stale:'수집 실패 · 마지막 성공 자료 유지',error:'수집 실패',demo:'가상 시나리오'}[s.status] || '대기'}</span><p>자료 ${s.count}건 · 마지막 성공: ${s.last_success ? escape(dateTime(s.last_success)) : '아직 없음'}${s.error ? `<br>${escape(s.error)}` : ''}</p>${safeLink(s.url) ? `<a href="${escape(safeLink(s.url))}" target="_blank" rel="noopener noreferrer">공개 RSS 확인 ↗</a>` : ''}</div>`).join('') + '<div class="source-detail"><h3>네이버 증권 리포트</h3><span class="source-status stale">자동 수집 미연결 · 원문 링크 제공</span><p>현재 페이지가 별도 요청으로 자료를 불러와 이번 시제품에는 자동 수집을 연결하지 않았습니다. 본문과 PDF를 분석한 결과는 제공하지 않습니다.</p><a href="https://stock.naver.com/research" target="_blank" rel="noopener noreferrer">리포트 원문 사이트 ↗</a></div><div class="source-detail"><h3>선별 방식</h3><p>발행 직후 최신성 50점에서 첫 60분 동안 25점까지 선형 감소하고, 이후 시간당 1점씩 최저 0점까지 감소합니다. 자료 유형에 따른 가점은 없습니다. 주제 분류는 필터용이며 점수에 반영하지 않습니다. 한국경제 RSS와 별도 작업자의 Npay 증권 전체 속보를 보관합니다. 포털의 여러 매체를 수집하는 것과 독립된 사실 교차 검증은 다릅니다. 관련 국내·미국 종목의 현재가·전일 대비 등락률은 Npay 증권에서 조회합니다. 환율·거래량과 주도주 판별은 미연결입니다.</p></div>';
  const stored=data?.archive;
  const collection=data?.collection;
  if (collection) $('#source-view').innerHTML += `<div class="source-detail"><h3>포털 속보 · 날짜별 대조</h3><p>대상 날짜 ${escape(collection.day)} · 다음 확인 ${escape(collection.next_page)}페이지</p><p>최근 목록 확인 ${escape(dateTime(collection.last_success))} · 최근 전체 대조 ${collection.complete_at ? escape(dateTime(collection.complete_at)) : '진행 중'}</p>${collection.last_error ? `<p>수집 지연: ${escape(collection.last_error)}</p>` : ''}<p>상시 작업자는 10초 간격으로 확인하고 정기 복구는 5분 간격으로 실행하도록 설정했습니다. 원본의 반영 지연과 오류 대기 시간은 별도입니다. 전체 대조는 확인한 날짜의 포털 속보 목록 기준이며 모든 매체의 전문 확보를 뜻하지 않습니다.</p></div>`;
  $('#source-view').innerHTML += `<div class="source-detail"><h3>전체 수집 · 누적 보관</h3><p>수집과 보관에는 추천 적합성 필터를 적용하지 않습니다. 일반 금융 뉴스·상품 안내·행사도 함께 보관합니다.</p><p>기사 ${stored?.articles || 0}건 · RSS 기록 ${stored?.revisions || 0}개 · 공개 본문 ${stored?.bodies || 0}건 · 본문 대기 ${stored?.pending || 0}건 · 실패 ${stored?.errors || 0}건</p><p>${escape(data?.archive_error || stored?.message || '서버 재시작 후에도 보관 자료를 유지합니다. 전체 자료 메뉴에서 누적 보관 기사를 날짜·언론사·검색어로 조회할 수 있습니다.')}</p><p>본문은 추천 모델과 독립적으로 수집합니다. 공개 추출 내용만 지원하며 로그인·유료 전문은 보장하지 않습니다.</p></div>`;
  const stockStatus = data?.stock_status;
  $('#source-view').innerHTML += `<div class="source-detail"><h3>관련 주식 · KRX / Nasdaq / Npay 증권</h3><p>공식 상장 목록 ${stockStatus?.count || 0}개 (국내 ${stockStatus?.markets?.KR || 0} · 미국 ${stockStatus?.markets?.US || 0}) · 목록 상태 ${escape(stockStatus?.status || 'loading')} · 마지막 갱신 ${escape(dateTime(stockStatus?.updated_at))}</p><p>기사의 직접 언급, 출처가 있는 사업 관계, 가치사슬 추론, 테마 관찰을 구분해 국내·미국 관련 종목을 연결합니다. 관계의 출처·공개일·검토일과 추가 확인할 조건을 제공합니다. 최신성 점수는 별도로 유지하며, 기본 추천은 주식 적합성 검토를 통과한 사건의 모델 순위를 사용합니다. 관련 후보는 수혜·피해 판정이 아닙니다. 시세는 화면에 보이는 종목부터 조회하며 10초 동안 재사용합니다. 실패한 시세는 이전 조회로 표시하고 거래 기준 시각과 조회 시각을 함께 제공합니다.</p></div>`;
  document.querySelectorAll('[data-kind]').forEach(b=>{b.classList.toggle('active',b.dataset.kind === kind); b.setAttribute('aria-pressed',String(b.dataset.kind === kind));});
  $('#source-view').innerHTML += `<div class="source-detail"><h3>본문 분석 · 사건 묶기 · 시장 맥락순</h3><p>${escape(ai?.message || '가상 시나리오에서는 모델 분석 미사용')} · ${escape(ai?.model || '')}</p><p>모델 요청 ${ai?.usage?.calls_today || 0}회 · ${ai?.daily_call_limit === null ? '일일 제한 없음' : ai?.daily_call_limit ? `일일 한도 ${escape(ai.daily_call_limit)}회` : '한도 정보 대기'} · 마지막 분석 ${escape(dateTime(ai?.updated_at))}</p><p>${escape(ai?.market?.limitations || '시장 자료 대기')}</p>${(ai?.market?.observations || []).map(q=>`<p>${escape(q.name)} ${q.change_percent > 0 ? '+' : ''}${Number(q.change_percent).toFixed(2)}% · 기준 ${escape(quoteTime(q.traded_at))}${q.relative_to_spy_pp !== undefined ? ` · S&P500 대비 ${Number(q.relative_to_spy_pp).toFixed(2)}%p` : ''}</p>`).join('')}<p>${escape(ai?.error || '')}${ai?.market?.missing?.length ? ` · 시장 자료 누락: ${ai.market.missing.map(escape).join(', ')}` : ''}</p></div>`;
  const queue = ai?.queue;
  $('#source-view').innerHTML += `<div class="source-detail"><h3>분석 대기열 · 사건 보관</h3>${queue ? `<dl class="event-facts">${[['분석 대기',`${queue.pending}건`],['처리 중',`${queue.processing}건`],['재시도 대기',`${queue.retrying}건`],['완료한 버전',`${queue.done}건`],['보관 사건',`${queue.event_count}건`],['최장 대기',`${Math.ceil(queue.oldest_wait_seconds/60)}분`],['전체 작업 등록 → 완료 p95',queue.recent_p95_seconds == null ? '집계 대기' : `${Math.ceil(queue.recent_p95_seconds/60)}분`]].map(([label,value])=>`<div><dt>${label}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl>` : '<p>대기열 상태를 확인하고 있습니다.</p>'}<p>누적 자료의 초기 등록은 순차 진행합니다. 최신 기사 2건과 오래 기다린 기사 1건을 처리할 때마다 이전 기준의 본문·영향 판정 재검토에 차례를 줍니다. 재검토 중인 판정은 추천에서 제외하며, 실패한 작업은 5~60분 후 재시도합니다. 중단된 작업은 최대 5분 후 다시 처리합니다.</p>${ai?.queue_sync_error ? `<p>${escape(ai.queue_sync_error)}</p>` : ''}</div>`;
  const live = queue?.live_analysis;
  if (live) $('#source-view').innerHTML += `<div class="source-detail"><h3>실시간 등록 자료 · 분석 지연</h3><dl class="event-facts">${[['완료 표본',`${live.samples}건`],['발행 → 분석 완료 p50',latencyText(live.p50_seconds)],['발행 → 분석 완료 p95',latencyText(live.p95_seconds)],['미완료 작업',`${live.pending}건`],['가장 오래된 미완료',latencyText(live.oldest_unfinished_seconds)]].map(([label,value])=>`<div><dt>${label}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl><p>발행 후 1시간 이내 등록한 기사 버전별 일반 분석 중 최근 1시간에 완료한 최대 100건입니다. 과거 자료 보충·판정 재검토와 구분하며, 최종 추천 공개까지의 시간은 포함하지 않습니다. 미완료 작업은 오래 지연돼도 집계에서 빠지지 않습니다.</p></div>`;
  const timings = ai?.usage?.timings || [];
  $('#source-view').innerHTML += `<div class="source-detail"><h3>모델 요청 대기 시간</h3>${timings.length ? timings.map(t=>`<p>${escape(({read:'본문 읽기',screen:'적합성 검토',rank:'순위 검토'})[t.task] || t.task)} · 표본 ${escape(t.samples)}회 · p50 ${escape(latencyText(t.p50_seconds))} · p95 ${escape(latencyText(t.p95_seconds))} · 전송·응답 오류 ${escape(t.failed)}회</p>`).join('') : '<p>측정 표본을 모으는 중입니다.</p>'}<p>같은 모델의 최근 측정 요청 최대 100회입니다. 요청부터 응답 수신까지 서버 대기·통신 시간을 포함하며, 실패한 요청도 측정합니다. 분석 정확도나 전체 처리 시간을 뜻하지 않습니다.</p></div>`;
  renderList();
}
function eventHistoryHTML(event) {
  if (!event?.history?.length) return '';
  return `<section class="detail-block"><h3>기사·사건 이력 ${event.history.length}건</h3><p class="detail-meta">보관된 분석 버전입니다. 본문 변경이 사실의 정정이나 별도 사건을 뜻하는지는 원문 확인이 필요합니다.</p><ol class="event-history">${event.history.map(item=>`<li><time>${escape(item.assessment_review ? (item.reviewed_at ? dateTime(item.reviewed_at) : '검토 시각 미확인') : dateTime(item.analyzed_at))}</time><strong>${escape(item.event_title || item.summary)}</strong><p>${escape(item.summary)}</p>${item.stock_relevance ? `<p class="detail-meta">판정: ${escape(item.stock_relevance)}${item.assessment_reason ? ` · ${escape(item.assessment_reason)}` : ''}</p>` : ''}<div class="article-tags">${item.assessment_review ? '<span class="tag">분석 기준 재검토</span>' : ''}<span class="tag">${escape(item.certainty || '미확인')}</span><span class="tag">${escape(item.amount || '규모 미확인')}</span><span class="tag">${escape(item.timing || '시점 미확인')}</span></div>${safeLink(item.source_url) ? `<a class="reading-source" href="${escape(safeLink(item.source_url))}" target="_blank" rel="noopener noreferrer">해당 기사 ↗</a>` : ''}</li>`).join('')}</ol></section>`;
}
function renderDetail(id) {
  const a = findArticle(id); if (!a) return;
  detailId = id;
  const related = (data?.articles || []).filter(b=>b.id !== id && b.themes.some(t=>a.themes.some(at=>at.id === t.id))).slice(0,3);
  const link = safeLink(a.url), selectedFeedback = feedback[`${mode}:${id}`];
  const e = eventFor(a);
  $('#detail').innerHTML = `<div class="detail-top"><span>${mode === 'demo' ? '가상 자료 · 기능 체험' : '사건 브리핑'}</span><button data-close aria-label="상세 닫기">×</button></div><div class="detail-content"><div class="detail-meta">${escape(a.source)} · ${a.timestamp_basis==='portal_display' ? '포털 표시 ' : ''}${escape(dateTime(a.published_at))}</div><h2 id="detail-title">${escape(a.title)}</h2>${readingHTML(a)}<section class="detail-stocks"><div class="overview-heading"><h3>관련 종목</h3><span>누르면 가격·연결 근거</span></div>${stocksHTML(a)}</section><details class="detail-more"><summary>자세히 보기 <span>원문 근거·연결 경로·분석 정보</span></summary><div class="detail-more-content">${e ? `<section class="detail-block model-reading"><h3>판단의 원문 근거</h3>${e.articles.map(item=>`<blockquote>${(item.evidence || []).map(escape).join(' / ')}</blockquote>${safeLink(item.url) ? `<a class="reading-source" href="${escape(safeLink(item.url))}" target="_blank" rel="noopener noreferrer">근거 원문 ↗</a>` : ''}`).join('')}<p class="detail-meta">${escape(e.model)} · 분석 ${escape(dateTime(e.analyzed_at))} · 동일 사건 ${e.articles.length}건${e.body_truncated ? ' · 본문 일부 분석' : ''} · 공개 추출 본문 분석이며 전문 전체를 보장하지 않습니다.</p></section>` : ''}${eventHistoryHTML(e)}${stockAnalysisHTML(a)}<section class="detail-block"><h3>제목에서 찾은 맥락</h3><p>${escape(a.reason)}</p><div class="article-tags">${a.themes.map(t=>`<span class="tag">${escape(t.name)}</span>`).join('')}</div><p class="detail-meta">주제·관련주 연결은 제목과 공개 사업 근거 기반입니다. 별도 본문 분석도 근거 범위 내의 모델 해석이며 사실 검증을 완료한 결과는 아닙니다.</p></section><section class="detail-block"><h3>최신성 점수 · 주식 영향순과 별도</h3><p>${(a.score_parts.relevance !== undefined || a.score_parts.report !== undefined) ? '이전 선별 기준으로 저장된 자료입니다. 현재 기준 점수는 최신 목록에서 확인해 주세요.' : `최신성 ${a.score_parts.freshness}점 (추가 가점 없음)`}</p><p>점수는 읽을 순서를 위한 시제품 규칙이며 투자 가치나 사실 신뢰도 점수가 아닙니다.</p></section>${related.length ? `<section class="detail-block"><h3>함께 비교할 자료</h3>${related.map(b=>`<button class="related-link" data-detail="${escape(b.id)}">${escape(b.title)}<small>${escape(b.source)} · 같은 주제 키워드</small></button>`).join('')}</section>` : ''}</div></details><div class="detail-bottom">${link ? `<a class="primary-button" href="${escape(link)}" target="_blank" rel="noopener noreferrer">원문 보기 ↗</a>` : '<span class="saved-note">가상 예시 · 실제 원문 없음</span>'}<div class="feedback"><span>도움이 됐나요?</span><button data-feedback="useful" class="${selectedFeedback === 'useful' ? 'selected' : ''}">도움돼요</button><button data-feedback="irrelevant" class="${selectedFeedback === 'irrelevant' ? 'selected' : ''}">관련 적음</button></div></div></div>`;
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
    const response = await fetch(mode === 'demo' ? '/api/demo' : '/api/dashboard', {signal:AbortSignal.timeout(15000)});
    if (!response.ok) throw new Error('응답 오류');
    const next = await response.json();
    if (current !== requestId) return;
    data = next; render(); paintQuotes(); loadQuotes(); if(view==='feed' && mode==='live') await loadArchive(); return true;
  } catch {
    if (current !== requestId) return;
    toast('서버에 연결하지 못했어요. 서버 실행 상태를 확인해 주세요.');
    if (data) render();
    if (!data) { delete $('#articles').renderedHTML; $('#articles').innerHTML = '<div class="empty-state"><h3>서버에 연결할 수 없어요</h3><p>실행 중인 서버를 확인한 뒤 새로고침해 주세요.</p></div>'; $('#articles').setAttribute('aria-busy','false'); }
  } finally { if (current === requestId) { loading = false; $('#refresh').disabled = false; } }
}
async function loadArchive(reset=false) {
  if(view!=='feed' || mode!=='live') return;
  if(reset) {archiveCursor='';archiveCursors=[];archiveData=null;}
  const request=++archiveRequest;
  archiveRequested=true;archiveError='';archiveLoading=true;render();
  try {
    const params=new URLSearchParams({q:query,source:archiveSource,since:archiveSince,until:archiveUntil,theme,kind,cursor:archiveCursor});
    const response=await fetch('/api/articles?'+params,{signal:AbortSignal.timeout(15000)});
    if(!response.ok) throw new Error('기사 조회 실패');
    const next=await response.json();
    if(request!==archiveRequest || view!=='feed' || mode!=='live') return;
    archiveData=next;
  } catch {
    if(request===archiveRequest && view==='feed') archiveError='누적 기사 조회 실패 · 기간과 서버 상태를 확인해 주세요.';
  } finally {
    if(request===archiveRequest) {archiveLoading=false;render();}
  }
}
function toggleMode() { mode = mode === 'live' ? 'demo' : 'live'; archiveData=null;archiveRequested=false;archiveError='';archiveCursor='';archiveCursors=[]; data = null; theme = ''; query = ''; kind = 'all'; $('#search').value = ''; $('#stock-dialog').close(); $('#detail-dialog').close(); detailId = null; loading = true; render(); load(); }
document.addEventListener('click', event => {
  const button = event.target.closest('button'); if (!button) return;
  if (button.dataset.view) { view = button.dataset.view; theme = ''; kind = 'all'; query = ''; $('#search').value=''; render(); loadArchive(true); }
  if (button.dataset.kind) { kind = button.dataset.kind; render(); loadArchive(true); }
  if (button.dataset.theme) { chooseTheme(button.dataset.theme); loadArchive(true); }
  if (button.hasAttribute('data-clear-theme')) { theme = ''; render(); loadArchive(true); }
  if (button.hasAttribute('data-archive-next') && !archiveLoading && archiveData?.next_cursor) {archiveCursors.push(archiveCursor);archiveCursor=archiveData.next_cursor;loadArchive();}
  if (button.hasAttribute('data-archive-prev') && !archiveLoading && archiveCursors.length) {archiveCursor=archiveCursors.pop();loadArchive();}
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
$('#search').addEventListener('input',event=>{query=event.target.value; renderList();clearTimeout(archiveSearchTimer);archiveSearchTimer=setTimeout(()=>loadArchive(true),300);});
for (const [selector,update] of [['#archive-source',v=>archiveSource=v],['#archive-since',v=>archiveSince=v],['#archive-until',v=>archiveUntil=v]]) $(selector).addEventListener('change',event=>{update(event.target.value);loadArchive(true);});
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

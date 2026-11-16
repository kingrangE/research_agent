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
const quoteTime = value => Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString('ko-KR', {month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',timeZone:'Asia/Seoul'}) : '미제공';
const latencyText = value => !Number.isFinite(value) || value<0 ? '집계 대기' : value>=3600 ? `${(value/3600).toFixed(1)}시간` : value>=60 ? `${(value/60).toFixed(1)}분` : `${value.toFixed(1)}초`;
const quotes = {};
let quoteInFlight = false;
function quoteAge(quote) {
  const age=Date.now()-Date.parse(quote?.fetched_at);
  return Number.isFinite(age) && age>=0 ? age : Infinity;
}
function quoteHTML(code) {
  if (mode === 'demo') return '<span class="quote-unavailable">가상 자료 · 시세 미조회</span>';
  const q = quotes[code];
  if (!q || q.status === 'pending') return '<span class="quote-unavailable">시세 조회 대기</span>';
  if (!Number.isFinite(q.price) || !Number.isFinite(q.change_percent)) return '<span class="quote-unavailable">시세 조회 실패 · 원문에서 확인</span>';
  const stale = q.status !== 'ok' || quoteAge(q) > 30000;
  const direction = q.change_percent > 0 ? 'up' : q.change_percent < 0 ? 'down' : 'flat';
  const price = q.currency === 'USD' ? `$${q.price.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}` : `${q.price.toLocaleString('ko-KR')}<small>원</small>`;
  const recent=q.recent_five_minutes;
  const recentText=recent?.status==='ok' && Number.isFinite(recent.change_percent) && !stale
    ? `최근 5분 ${recent.change_percent>0?'+':''}${recent.change_percent.toFixed(2)}% · ${escape(quoteTime(recent.actual_start_at))} ~ ${escape(quoteTime(recent.actual_end_at))}`
    : `최근 5분 · ${recent?.status==='outside_session' ? '정규장 관측 구간 아님' : recent?.status==='stale' || stale ? '시세 지연' : recent?.status==='session_unverified' ? '거래 일정 확인 중' : '비교할 시세 수집 중'}`;
  return `<span class="stock-values"><strong>${price}</strong><span class="stock-change ${direction}">${q.change_percent > 0 ? '+' : ''}${q.change_percent.toFixed(2)}%<small>전일 대비</small></span></span><span class="quote-time">${recentText}</span><span class="quote-time ${stale ? 'stale' : ''}">${stale ? '이전 조회 · ' : ''}시세 기준 ${escape(quoteTime(q.traded_at))} · ${escape(q.delay_label)}${q.market_status === 'CLOSE' ? ' · 장마감' : ''}<span>출처 ${escape(q.source)} · ${q.currency === 'USD' ? '미국 정규장 · ' : ''}조회 ${escape(quoteTime(q.fetched_at))} (한국시간)</span></span>`;
}
function changeHTML(code) {
  if (mode === 'demo') return '<span class="quote-unavailable">—</span>';
  const q = quotes[code];
  if (!Number.isFinite(q?.change_percent)) return `<span class="quote-unavailable" title="${!q || q.status === 'pending' ? '시세 조회 대기' : '시세 조회 실패'}">—</span>`;
  const stale = q.status !== 'ok' || quoteAge(q) > 30000;
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
  return `<section class="related-stocks" aria-label="관련 주식"><div class="related-stocks-label">관련 주식 ${related.length}<span>국내·미국 · 근거별 구분</span></div>${(expanded ? related : related.slice(0,3)).map(s=>`<div class="stock-card"><div class="stock-heading"><a href="https://stock.naver.com/${s.country === 'US' ? 'worldstock' : 'domestic'}/stock/${encodeURIComponent(s.code)}" target="_blank" rel="noopener noreferrer">${escape(s.name)} <small>${escape(s.code)} ↗</small></a><span class="relation-badge ${!['direct','body'].includes(s.relation) ? 'inferred' : ''}">${labels[s.relation] || '관찰 후보'}</span></div><span class="stock-market">${s.country === 'US' ? '미국' : '국내'} · ${escape(s.market || '')}${s.role ? ` · ${escape(s.role)}` : ''}${s.connection_kind ? ` · ${escape(s.connection_kind)}` : ''}</span><div class="stock-quote" data-stock-code="${escape(s.code)}">${quoteHTML(s.code)}</div><p class="stock-reason">${escape(s.path || s.reason)}</p>${expanded ? `<details class="stock-evidence"><summary>근거 ${(s.sources || []).length}개 · 추가 확인할 조건</summary><p class="stock-mechanism">${escape(s.mechanism || s.reason)}</p><p class="stock-confidence">${escape(s.confidence || '조건부 관찰 후보')} · ${escape(s.impact || '영향 미정')}</p>${(s.sources || []).filter(source=>safeLink(source.url)).map(source=>`<a href="${escape(safeLink(source.url))}" target="_blank" rel="noopener noreferrer">${escape(source.title)} ↗</a>${source.excerpt ? `<blockquote>${escape(source.excerpt)}</blockquote>` : ''}<small>공개 ${escape(source.published_on || '날짜 미제공')} · 검토 ${escape(source.checked_on || '미제공')}</small>`).join('')}${s.other_paths?.length ? `<p>추가 경로: ${s.other_paths.map(escape).join(' / ')}</p>` : ''}<ul>${(s.required_checks || []).map(check=>`<li>${escape(check)}</li>`).join('')}</ul><p>${escape(s.materiality || '기사 사건의 매출·이익 영향 미산정')}</p></details>` : `<button class="stock-evidence-link" data-detail="${escape(article.id)}">연결 근거·확인할 조건 보기 ↗</button>`}</div>`).join('')}${!expanded && related.length > 3 ? `<button class="more-stocks" data-detail="${escape(article.id)}">관련 주식 ${related.length}개와 연결 근거 모두 보기 ↗</button>` : ''}</section>`;
}
function paintQuotes() {
  document.querySelectorAll('[data-stock-code]').forEach(el=>{el.innerHTML=el.hasAttribute('data-compact') ? changeHTML(el.dataset.stockCode) : quoteHTML(el.dataset.stockCode);});
}
async function loadQuotes() {
  if (mode !== 'live' || quoteInFlight || document.hidden) return;
  const container = $('#stock-dialog').open ? $('#stock-detail') : $('#detail-dialog').open ? $('#detail') : marketPreview && view==='briefing' && mode==='live' && data?.product_mode==='data' ? $('#market-view') : $('#articles');
  const codes = [...new Set([...container.querySelectorAll('[data-stock-code]')].filter(el=>{const r=el.getBoundingClientRect(); return r.width>0 && r.height>0 && r.bottom>0 && r.top<window.innerHeight;}).map(el=>el.dataset.stockCode))]
    .filter(code=>quoteAge(quotes[code])>=10000).slice(0,20);
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
let data = null, mode = 'live', view = 'briefing', kind = 'all', theme = '', query = '', sort = 'context', detailId = null, requestId = 0, loading = true;
let briefingExpanded = false;
let loadFailed=false, lastLoadedAt=null;
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
    const selected = new Map();
    for (const a of list) {
      const e=eventFor(a);
      if (e && rank.has(e.event_id) && (!selected.has(e.event_id) || a.id===e.article_id)) selected.set(e.event_id,a);
    }
    return [...selected.values()]
      .sort((a,b)=>(rank.get(eventFor(a)?.event_id) ?? Infinity)-(rank.get(eventFor(b)?.event_id) ?? Infinity));
  }
  if (sort === 'context' && view === 'briefing') return [];
  return sort === 'latest' ? list.sort((a,b)=>(Date.parse(b.published_at) || 0)-(Date.parse(a.published_at) || 0)) : list;
}
const recencyLabel = event => ({old:'최초 보도 26시간 경과 · 배경 자료',future:'미래 보도 시각 · 확인 필요',unknown:'보도 시각 미확인 · 배경 자료'}[event?.recency_status] || '');
function impactEvidence(event, assessment) {
  const quote=assessment?.impact_evidence || (data?.intelligence?.rank_reason_source==='article_evidence' && assessment?.stock_relevance==='주식 판단 재료' ? assessment?.reason : '');
  return typeof quote==='string' && quote.trim().length>=8 && quote.length<=500 && Array.isArray(event?.evidence) && event.evidence.some(text=>typeof text==='string' && text.includes(quote)) ? quote : '';
}
function readingHTML(article) {
  if (article.evidence) return (article.structured_event?.axis ? eventFactsHTML(article.structured_event) : '')+evidenceHTML(article.evidence);
  const e = eventFor(article);
  const assessment = (data?.intelligence?.assessments || data?.intelligence?.ranking)?.find(r=>r.event_id === e?.event_id);
  if (!e) return `<section class="detail-overview"><h3>본문 분석 대기</h3><p>아직 본문에서 확인한 사건 정보가 없습니다.</p><div class="detail-question">확인할 것 · ${escape(article.question || '원문에서 사건 당사자와 새 사실을 확인하세요.')}</div></section>`;
  const excluded = assessment?.stock_relevance && assessment.stock_relevance !== '주식 판단 재료';
  const proof=impactEvidence(e,assessment);
  const representativeLink=safeLink(e.source_url);
  const representativeNote=e.article_id && e.article_id!==article.id ? `<p class="detail-meta">사건 대표 원문 기준${representativeLink ? ` · <a href="${escape(representativeLink)}" target="_blank" rel="noopener noreferrer">대표 원문 ↗</a>` : ''}</p>` : '';
  return `${representativeNote}<section class="detail-overview"><div class="overview-heading"><h3>핵심 사건</h3><span class="certainty-badge">모델 요약 · 검수 전</span></div><p class="event-summary">${escape(e.summary)}</p><dl class="event-facts">${[['사건 상태',e.certainty],['유형',e.event_type],['규모',e.amount],['시점 · 기사 기준',e.timing]].map(([label,value])=>`<div><dt>${label}</dt><dd>${escape(value || '미확인')}</dd></div>`).join('')}</dl></section><div class="detail-decision-grid"><section class="decision-tile"><h3>${proof ? '원문 근거' : excluded ? '추천 제외 · 모델 해석' : '주식 영향 · 모델 해석'}</h3><p>${proof ? `<q>${escape(proof)}</q>` : escape(assessment?.reason || '아직 주식 영향 검토를 완료하지 않았습니다.')}</p><span class="assessment-label">${escape(recencyLabel(e) || assessment?.stock_relevance || '판단 대기')}${rankingExpired() ? ' · 갱신 지연' : ''}</span></section><section class="decision-tile next-check"><h3>다음 확인 · 모델 제안</h3><p>${escape(excluded ? '전체 자료로 보관 중입니다. 주식에 전달되는 구체적인 새 사실이 있는지 확인하세요.' : assessment?.watch_for || '원문의 새 사실과 관련 기업의 실적·가격 반영 여부를 확인하세요.')}</p></section></div>`;
}
function eventFactsHTML(e) {
  const stages={unknown:'미확인',planned:'계획·검토',mou:'MOU',announced:'발표',approved:'승인',execution:'실행',cancelled:'취소',denied:'부인',deferred:'유예·집행 중단',exempt:'예외'};
  return `<section class="detail-overview"><div class="overview-heading"><h3>원문에서 찾은 사건 제안</h3><span>${e.review_status==='reviewed' ? `${escape(e.reviewer_kind)} 검토 기록` : '규칙 추출 · 검수 전'}</span></div><dl class="event-facts">${[['사건 축',e.axis || '미분류'],['유형',e.event_type],['상태',stages[e.stage] || e.stage],['금액 표기',(e.amounts || []).map(a=>a.raw).join(' / ') || '미확인'],['당사자 후보',(e.actors || []).map(a=>a.name).join(' · ') || '미확인']].map(([k,v])=>`<div><dt>${escape(k)}</dt><dd>${escape(v)}</dd></div>`).join('')}</dl><button data-reactions="${escape(e.article_id)}">보관된 일봉 반응 보기</button>${e.details ? macroDetailsHTML(e.details) : ''}${(e.evidence || []).map(p=>`<blockquote>${escape(p.quote)}</blockquote>`).join('')}<details><summary>사건·규칙 이력 정보</summary><p>사건 ${escape(e.event_id)} · 기준 ${escape(e.rule_version)} · 처리 ${escape(dateTime(e.processed_at))}</p><p>기사 공개 ${escape(dateTime(e.published_at))} · 포털 표시 ${escape(dateTime(e.portal_display_at))} · 최초 수집 ${escape(dateTime(e.first_seen_at))}</p><p>기업은 이름이 등장한 후보이며 법적 당사자·수혜를 확정하지 않습니다. ${escape(e.source_quality==='body_title_binding_unverified' ? '보관 본문과 현재 제목의 일치 미검증' : '제목에서 추출한 제안')}</p><p>관련 사건 ${escape((e.related_event_ids || []).join(' · ') || '미확인')}</p>${(e.source_history || []).map(v=>`<p>${escape(v.stage)} · ${escape(v.article_title)} · ${escape(dateTime(v.source_version_at))}</p>`).join('')}${(e.review_history || []).map(r=>`<p>${escape(r.action)} · ${escape(r.reviewer_kind)} ${escape(r.reviewer)} · ${escape(r.reason)} · ${escape(dateTime(r.applied_at))}</p>`).join('')}</details></section>`;
}
function macroDetailsHTML(d) {
  if(d.kind==='trade') {
    const rows=[['조치 상태',({proposed:'제안·검토',withdrawn:'철회 보도',deferred:'유예·집행 중단',exempt:'제품별 예외',denied:'부인',in_force_reported:'시행 보도',finalized_reported:'확정 보도',announcement_reported:'발표 보도',finalized:'최종 조치'})[d.regulatory_stage] || d.regulatory_stage || '미확인'],['발표 주체 국가',d.issuer_country || '미확인'],['원산지',d.origin_country || '미확인'],['도착 국가',d.destination_country || '미확인'],['제품',(d.products || [d.product]).filter(Boolean).join(' · ') || '미확인'],['분류 코드',(d.classification_codes || []).map(c=>c.scheme+' '+c.code).join(' / ') || '미확인'],['세율 표기',(d.rates || []).map(r=>r.value+'% · '+r.basis).join(' / ') || '미확인'],['전체 합산 세율','미산정'],['효력일',d.effective_at ? dateTime(d.effective_at) : d.effective_date || '미확인'],['기업 직접 영향','제품·지역·실제 노출 대조 전']];
    return `<dl class="event-facts">${rows.map(([k,v])=>`<div><dt>${escape(k)}</dt><dd>${escape(v)}</dd></div>`).join('')}</dl>${d.conflicting_conditions ? '<p>복수 제품·날짜가 있어 적용 조건 검토가 필요합니다.</p>' : ''}<p>언론 보도·검토한 공식 자료이며 현행 법령 전체나 기업 손익을 확정하지 않습니다.</p><button data-trade>공식 조치·후속 변경 근거</button>`;
  }
  if(d.kind==='fx') {
    const rows=[['통화쌍',d.base_currency && d.quote_currency ? d.base_currency+'/'+d.quote_currency : '미확인'],['호가 단위',d.unit || '미확인'],['이전 값',d.previous_value ?? '미확인'],['새 값',d.new_value ?? '미확인'],['변화량',d.delta ?? '미확인'],['변화율',d.change_percent!=null ? d.change_percent+'%' : '미확인'],['원화 방향',{weak:'약세',strong:'강세',unchanged:'변화 없음'}[d.won_strength] || '미확인'],['비교 구간',{previous_close:'전일 종가 대비 보도',intraday:'장중 보도'}[d.observation_window] || '시각 미확인']];
    return `<dl class="event-facts">${rows.map(([k,v])=>`<div><dt>${escape(k)}</dt><dd>${escape(v)}</dd></div>`).join('')}</dl><p>기사의 주장입니다. API 관측 시각·호가 기준과 대조 전이며 기업 수혜 방향은 미확정입니다.</p><button data-fx>환율 관측·기업 노출 근거</button>`;
  }
  const verified={official_registry:'공식 결정문',matched_official_values:'공식 수치 대조',matched_values_publication_time_unverified:'수치 일치 · 공개 시각 미확인',official_unverified:'공식 대조 미확인'};
  const rows=[['국가·통화',[d.country,d.currency].filter(Boolean).join(' · ') || '미확인'],['발표 기관',d.authority || '미확인'],['금리 기준',d.instrument || '미확인'],['만기',d.tenor_years ? d.tenor_years+'년' : '미확인'],['이전 수준',d.previous_level?.length ? d.previous_level.join('~')+'%' : '미확인'],['새 수준',d.new_level?.length ? d.new_level.join('~')+'%' : '미확인'],['변화량',(d.changes || []).map(c=>c.basis_points!=null ? c.basis_points+' bp' : (c.raw || '미확인')+' · 방향 미확인').join(' / ') || '미확인'],['공식 자료',verified[d.verification] || '미확인'],['결정일',d.decision_date || '미확인'],['효력 시각',d.effective_at ? dateTime(d.effective_at) : d.effective_date ? d.effective_date+' · 시각 미확인' : '미확인'],['기대 대비 변화',d.surprise_bp==null ? '사전 기대 자료 미확보 · 미산정' : d.surprise_bp+' bp']];
  return `<dl class="event-facts">${rows.map(([k,v])=>`<div><dt>${escape(k)}</dt><dd>${escape(v)}</dd></div>`).join('')}</dl>${d.numeric_conflict ? '<p>원문 수치가 상충합니다. 확정 값으로 사용하지 않습니다.</p>' : ''}${safeLink(d.reference_url || d.url) ? `<a href="${escape(safeLink(d.reference_url || d.url))}" target="_blank" rel="noopener noreferrer">공식 결정문 ↗</a>` : ''}`;
}
function themeStatisticsHTML(result) {
  const pct=v=>v==null ? '미산정' : (v*100).toFixed(1)+'%';
  const corr=p=>p.value==null ? `미산정 · ${p.samples}쌍` : `${p.value.toFixed(3)} · ${p.samples}쌍`;
  return result.runs.map(r=>`<p>일 단위 계산 ${escape(dateTime(r.as_of))} · 소속 기준 ${escape(r.membership_as_of)} · ${r.membership_basis==='current' ? '현재 구성으로 과거 가격 관측' : '조회 당시 공개된 구성'}</p>${r.calendar_policy_current===false ? '<p>이전 거래일 기준으로 계산한 기록입니다. 재검증 전이므로 현재 통계로 사용하지 않습니다.</p>' : ''}${r.themes.map(t=>`<section class="detail-overview"><h3>${escape(t.name)} · ${escape(t.market)}</h3><p>기준 거래일 ${escape(t.last_session || '미확인')} · 관측 ${t.observed_members}/${t.members}개 기업</p><dl class="event-facts"><div><dt>상승 기업 비율</dt><dd>${escape(pct(t.up_fraction))}</dd></div><div><dt>하락 기업 비율</dt><dd>${escape(pct(t.down_fraction))}</dd></div><div><dt>시장 수익률 대비 차이 평균</dt><dd>${escape(pct(t.mean_market_difference))}</dd></div><div><dt>거래량 변화 평균</dt><dd>${escape(pct(t.mean_volume_change))} · ${t.volume_members}개 관측</dd></div><div><dt>실제 거래대금 변화</dt><dd>미산정</dd></div><div><dt>독립 새 사건 수</dt><dd>검수 자료 부족 · 미산정</dd></div></dl><details><summary>종목 간 동조·표본·산식</summary><p>원시 상관과 시장 모형 잔차 상관입니다. 가격 수준이나 선행 예측이 아닙니다. 각 관측 창 이전 120일·최소 60일로 시장 모형을 추정합니다.</p>${t.pairs.map(p=>`<p>${escape(p.a)} ↔ ${escape(p.b)} · ${p.window_sessions}거래일 (${escape(p.calendar_window_first || '미확인')} ~ ${escape(p.calendar_window_last || '미확인')})</p><p>원시 ${escape(corr(p.raw))} / 시장 보정 ${escape(corr(p.market_adjusted))} · 최소 ${p.minimum}쌍</p>`).join('') || '<p>같은 시장의 비교 기업 쌍이 없습니다.</p>'}<p>중복 증권 제외 ${escape(t.duplicate_securities_excluded.join(' · ') || '없음')}</p></details></section>`).join('')}<details><summary>고정 계산 입력·출처</summary>${r.notes.map(n=>`<p>${escape(n)}</p>`).join('')}<p>당시 가격 버전·기업행동·거래정지 전체는 미확보입니다. 사업 소속의 공개 근거는 날짜 단위입니다.</p><a href="/api/theme-statistics?run_id=${encodeURIComponent(r.run_id)}&inputs=true" target="_blank" rel="noopener noreferrer">고정 가격·캘린더·근거 입력 조회</a></details>`).join('') || '<p>선택한 소속 기준일의 저장 계산이 없습니다. 최신 계산으로 대체하지 않습니다.</p>';
}
async function openThemeStatistics(code) {
  if(mode!=='live') return;
  const request=++historyRequest;detailId=null;
  $('#detail').innerHTML='<div class="detail-top"><h2 id="detail-title">테마별 일봉 동조·확산</h2><button data-close aria-label="상세 닫기">×</button></div>';
  if($('#stock-dialog').open) $('#stock-dialog').close();
  if(!$('#detail-dialog').open) $('#detail-dialog').showModal();
  try {
    const day=$('#business-asof').value;
    const response=await fetch('/api/theme-statistics'+(day ? '?as_of='+encodeURIComponent(day) : ''),{signal:AbortSignal.timeout(15000)});
    if(!response.ok) throw new Error();
    const result=await response.json();
    if(request!==historyRequest || !$('#detail-dialog').open) return;
    $('#detail').innerHTML=`<div class="detail-top"><h2 id="detail-title">테마별 일봉 동조·확산</h2><button data-close aria-label="상세 닫기">×</button></div><div class="detail-content">${themeStatisticsHTML(code ? {...result,runs:result.runs.map(r=>({...r,themes:r.themes.filter(t=>t.codes.includes(code))}))} : result)}</div>`;
  } catch {if(request===historyRequest) $('#detail').innerHTML='<h2>테마 통계 조회 실패</h2><button data-close>닫기</button>';}
}
function priceMovementHTML(result) {
  const percent=value=>Number.isFinite(value) ? `${value>0 ? '+' : ''}${value.toFixed(2)}%` : '—';
  const reference={published:'기사 발행',portal_display:'포털 표시',first_seen:'첫 수집',tracking_started:'조회 시작'};
  return (result.stocks || []).map(stock=>{
    const direction=stock.change_percent>0 ? 'up' : stock.change_percent<0 ? 'down' : 'flat';
    const points=(stock.points || []).filter(p=>Number.isFinite(p.at) && Number.isFinite(p.price) && p.price>0);
    let chart='';
    if(points.length>1 && points.at(-1).at>points[0].at) {
      const lo=Math.min(...points.map(p=>p.price)),hi=Math.max(...points.map(p=>p.price));
      const path=points.map(p=>`${4+352*(p.at-points[0].at)/(points.at(-1).at-points[0].at)},${hi===lo ? 32 : 60-56*(p.price-lo)/(hi-lo)}`).join(' ');
      chart=`<svg class="movement-chart ${direction}" viewBox="0 0 360 64" role="img" aria-label="${escape(stock.name)} 추적 시세 추이"><polyline points="${path}" fill="none" stroke="currentColor" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
    }
    const states={pending:'첫 시세를 확인하고 있어요.',waiting_for_trade:'기사 이후의 거래 시세를 기다리고 있어요.',baseline_only:'첫 가격을 기록했어요. 다음 시세부터 변화를 보여드려요.',large_move_unverified:'가격 차이가 커서 주식 분할 등 확인이 필요해요.'};
    const baseline=stock.baseline;
    return `<div class="movement-row" data-movement-code="${escape(stock.code)}"><button class="movement-stock" data-stock="${escape(stock.code)}" data-article="${escape(result.article_id)}" aria-haspopup="dialog"><strong>${escape(stock.name)}</strong><span class="stock-change ${direction}">${percent(stock.change_percent)}<small>추적 이후</small></span><span aria-hidden="true">›</span></button>${chart}${baseline ? `<p class="movement-times">${escape(quoteTime(baseline.traded_at))} → ${escape(quoteTime(stock.latest?.traded_at))}</p>` : ''}${stock.status!=='tracking' ? `<p class="movement-state">${states[stock.status] || '시세를 확인하고 있어요.'}</p>` : ''}${stock.stale ? '<p class="movement-state">갱신 지연 · 마지막으로 확인한 시세예요.</p>' : ''}<details class="movement-info"><summary>기준 시각과 시세 정보</summary><p>${reference[result.reference_basis] || '기사 기준'} ${escape(quoteTime(result.reference_at))}${baseline ? ` · 첫 추적 ${escape(quoteTime(baseline.traded_at))} (${Math.round(stock.baseline_delay_seconds || 0)}초 뒤)` : ''}</p><p>${escape(stock.latest?.source || '시세 확인 중')} · ${escape(stock.latest?.delay_label || '지연 여부 미확인')} · ${stock.latest?.market_status==='CLOSE' ? '장마감' : '장 상태 '+escape(stock.latest?.market_status || '미확인')} · 조회 확인 ${escape(quoteTime(stock.checked_at))}</p><p>실제 보관한 첫 시세와 마지막 시세의 차이예요. 기사 당시 가격이나 해당 뉴스의 영향만을 뜻하지 않아요. 관측 사이 움직임과 기업행동은 확인되지 않았어요.</p></details></div>`;
  }).join('') || '<p class="movement-state">연결된 상장 종목이 없어요. 관련 종목이 확인되면 움직임을 보여드려요.</p>';
}
let movementRequest=0,movementLoading=false;
async function loadPriceMovement(articleId=detailId) {
  if(mode!=='live' || !articleId || document.hidden || movementLoading) return;
  const request=++movementRequest;movementLoading=true;
  try {
    const response=await fetch('/api/price-movement?'+new URLSearchParams({article_id:articleId}),{signal:AbortSignal.timeout(10000)});
    if(!response.ok) throw new Error();
    const result=await response.json();
    if(request!==movementRequest || detailId!==articleId || !$('#detail-dialog').open) return;
    if($('#stock-dialog').open) return;
    const container=$('#price-movement'), html=priceMovementHTML(result);
    if(container.renderedHTML!==html) {
      const expanded=new Set([...container.querySelectorAll('[data-movement-code]')].filter(row=>row.querySelector('details')?.open).map(row=>row.dataset.movementCode));
      const focused=document.activeElement?.closest?.('[data-movement-code]');
      const focusCode=focused?.dataset.movementCode, focusSummary=document.activeElement?.tagName==='SUMMARY';
      container.innerHTML=html;container.renderedHTML=html;
      container.querySelectorAll('[data-movement-code]').forEach(row=>{
        if(expanded.has(row.dataset.movementCode)) row.querySelector('details').open=true;
        if(row.dataset.movementCode===focusCode) row.querySelector(focusSummary ? 'summary' : 'button').focus({preventScroll:true});
      });
    }
    $('#price-movement-status').textContent='첫 추적 시세 대비 · 종목을 누르면 현재가를 볼 수 있어요.';
  } catch {
    if(request===movementRequest && detailId===articleId) $('#price-movement-status').textContent='시세 기록을 불러오지 못했어요. 잠시 후 다시 확인해요.';
  } finally {if(request===movementRequest) movementLoading=false;}
}
function reactionsHTML(result) {
  const pct=v=>v==null ? '미산정' : (v*100).toFixed(2)+'%';
  return `<details><summary>일봉 비교 기준</summary><p>일봉 가격 반응이며 기사 발견 이후 매매 수익·인과 효과가 아닙니다. 가격은 수집한 수정 버전으로 과거 당시 가용값을 보장하지 않습니다.</p></details>${result.runs.map(r=>`<section class="detail-overview">${r.calendar_policy_current===false ? '<p>이전 거래일 기준 · 재검증 전 관측입니다.</p>' : ''}${r.price_revisions_current===false ? '<p>가격이 정정됐습니다 · 이전 성공 계산이며 재계산 대기일 수 있습니다.</p>' : r.price_revisions_current===null ? '<p>가격 수정 버전 대조 미확인</p>' : ''}<h3>${escape(r.market)} ${escape(r.symbol)} · ${r.basis==='public' ? '기사 공개 시각' : '시스템 이용 가능 시각'} 기준</h3><button data-comparable="${escape(r.article_id || '')}" data-market="${escape(r.market)}" data-symbol="${escape(r.symbol)}" data-basis="${escape(r.basis)}">비교 가능한 과거 사건</button><p>기준 ${escape(dateTime(r.event_time))} · ${escape(r.status)} · 계산 기준 ${escape(dateTime(r.as_of))} · 비교 ${escape(r.benchmark)}${r.benchmark_kind==='ETF_proxy_not_index' ? ' (ETF 대용 자료)' : ''}</p>${r.windows.map(w=>`<section><h4>${({pre_event:'사건 전 거래일',event_day:'발표에 대응하는 거래일',next_session:'다음 거래일'})[w.name] || escape(w.name)}</h4><dl class="event-facts"><div><dt>원시 수익률</dt><dd>${escape(pct(w.raw_return))}</dd></div><div><dt>시장 모형 잔차</dt><dd>${escape(pct(w.abnormal_return))}</dd></div><div><dt>거래량 변화</dt><dd>${escape(pct(w.volume_change))}</dd></div><div><dt>실제 거래대금 변화</dt><dd>${escape(pct(w.turnover_change))}</dd></div></dl><p>${escape(w.start?.close ? dateTime(w.start.close) : '시작 미확인')} → ${escape(w.end?.close ? dateTime(w.end.close) : '종료 미확인')} · ${escape(w.status)}</p>${w.includes_pre_event_movement ? '<p>전일 종가 기준이므로 장중 기사 이전 움직임이 포함됩니다.</p>' : ''}<details><summary>계산 입력·원문</summary>${(w.calendar_evidence || []).map(c=>`<p>${escape(c.day)} · 거래소 ${escape(c.reference.state)}${c.source_conflict ? ' · 공급자 일정과 상충' : ''} ${(c.reference.sources || []).map(s=>`<a href="${escape(safeLink(s.url))}" target="_blank" rel="noopener noreferrer">거래소 근거</a>`).join(' ')}</p>`).join('')}${(w.input_prices || []).map(p=>`<p>${escape(p.series)} ${escape(p.day)} · 종가 ${escape(p.closePrice)} ${escape(p.currency || '')} · 수정 ${escape(p.revision)} <a href="/api/history?response_id=${encodeURIComponent(p.response_id)}" target="_blank" rel="noopener noreferrer">가격 원문</a></p>`).join('')}</details></section>`).join('')}<details><summary>시장 모형·품질 제한</summary><p>사건 이전 최대 120거래일 · 유효 최소 60일 · 실제 ${escape(r.model?.samples ?? 0)}일 · ${escape(r.model?.status || '미산정')}</p><p>기업행동·과거 거래정지·동시 사건은 충분히 확인하지 못했습니다. 큰 원시 가격 단절·미완료 봉은 산정에서 제외합니다.</p><p>계산 ${escape(r.version)} · 원문 ${escape(r.source_key)}</p><a href="/api/reactions?run_id=${encodeURIComponent(r.run_id)}&inputs=true" target="_blank" rel="noopener noreferrer">고정 계산 조회</a></details></section>`).join('') || '<p>이 기사에 연결된 과거 일봉 비교는 아직 없어요. 실시간 움직임은 뉴스 상세에서 확인하세요.</p>'}`;
}
function pipelineHTML(p) {
  const c=p.counts || {};const last=p.last_cycle?.last_success;
  const stale=!last || Date.now()-new Date(last).getTime()>120000;
  return `<div class="source-detail"><h3>근거 데이터 자동 처리</h3><p>${stale ? '처리 지연·시작 상태 확인 필요' : '작업자 최근 실행 확인'} · 마지막 회차 성공 ${escape(dateTime(last))}</p><dl class="event-facts">${[['처리 대기',c.pending || 0],['관측·가격 대기',c.waiting || 0],['오류',c.error || 0],['관측 완료',c.complete || 0],['미지원',c.unsupported || 0],['새 버전으로 교체',c.superseded || 0]].map(([k,v])=>`<div><dt>${escape(k)}</dt><dd>${escape(v)}</dd></div>`).join('')}</dl><p>미완료 중 가장 오래된 접수 ${escape(dateTime(p.oldest_unfinished))} · 회차 ${escape(p.last_cycle?.seconds ?? '미확인')}초 · AI 호출 ${escape(p.ai_calls ?? '미확인')}회</p><p>${escape(p.scope || '아직 시작하지 않았습니다.')}</p><details><summary>처리 단계·가격 준비 상태</summary>${(p.recent_states || []).map(s=>`<p>${escape(s.state)} · ${escape(s.reason)} · ${escape(dateTime(s.updated))}</p>`).join('')}${(p.series || []).map(s=>`<p>${escape(s.market)} ${escape(s.symbol)} · ${escape(s.status)} · ${escape(s.error || '')} · ${escape(dateTime(s.updated))}</p>`).join('')}<p>테마 통계 계산 ${escape(dateTime(p.theme?.updated_at))} · 관측 가능한 소속 종목 합계 ${escape(p.theme?.observed_members ?? '미확인')}</p>${p.last_error ? `<p>마지막 회차 오류 기록 ${escape(p.last_error.error)} · ${escape(dateTime(p.last_error.at))}</p>` : ''}<p>회차 성공은 모든 자료 확보를 뜻하지 않습니다. 일봉 미완료·미지원·오류는 각각 확인하며 이전 성공 통계는 계산 시각과 함께 보존합니다.</p></details></div>`;
}
function comparableHTML(r) {
  const pct=v=>v==null ? '미산정' : (v*100).toFixed(2)+'%';
  const s=r.summary;
  return `<p>${escape(r.claim)}</p><section class="detail-overview"><h3>${escape(r.market)} ${escape(r.symbol)} · 발표 대응 거래일</h3><dl class="event-facts">${[['사례 / 중첩을 묶은 수',`${s.events} / ${s.nonoverlapping_clusters}`],['상승 / 하락 / 정확히 0',`${s.positive} / ${s.negative} / ${s.zero}`],['중앙값',pct(s.median)],['중앙값 95% 재표집 구간',s.cluster_bootstrap_median_95?.map(pct).join(' ~ ') || '미산정']].map(([k,v])=>`<div><dt>${escape(k)}</dt><dd>${escape(v)}</dd></div>`).join('')}</dl><p>${s.status==='insufficient_sample' ? '표본 부족 · 중첩을 묶은 관측이 30개 미만입니다.' : '기술 통계 · 30개 이상도 신뢰 판정이 아닙니다.'}</p>${r.query_unknown_fields.length ? `<p>비교 조건 미확인: ${escape(r.query_unknown_fields.join(', '))}</p>` : ''}${r.truncated ? '<p>저장 계산 1,000개 조회 한도 · 전체 분포가 아닙니다.</p>' : ''}</section><h3>포함한 과거 사건</h3>${r.included.map(e=>`<section><h4>${escape(e.title)}</h4><p>${escape(pct(e.value))} · ${escape(dateTime(e.start))} → ${escape(dateTime(e.end))} · ${escape(e.review_status)}</p><a href="${escape(safeLink(e.url))}" target="_blank" rel="noopener noreferrer">사건 원문</a> · <a href="${escape(e.input_url)}" target="_blank" rel="noopener noreferrer">고정 반응 입력</a></section>`).join('') || '<p>조건에 맞는 저장 관측이 없습니다. 반응이 0이라는 뜻이 아닙니다.</p>'}<details><summary>조건·제외 사유·별도 비교 집단</summary><p>${escape(JSON.stringify(r.scope))}</p><p>${escape(r.baseline.definition)} · ${escape(r.baseline.summary.events)}건 · 상승 관측 빈도 차이 ${escape(pct(r.baseline.positive_frequency_difference))}. 인과·유의성 판단이 아닙니다.</p>${r.excluded.map(e=>`<p>${escape(e.title)} · ${escape(e.reasons.join(' / '))} <a href="${escape(safeLink(e.url))}" target="_blank" rel="noopener noreferrer">원문</a></p>`).join('')}<p>${escape(s.sign_definition)}</p>${r.limitations.map(t=>`<p>${escape(t)}</p>`).join('')}<p>조회 ${escape(dateTime(r.as_of))} · ${escape(r.version)}</p></details>`;
}
async function openComparable(values) {
  if(mode!=='live') return;
  const request=++historyRequest;detailId=null;
  $('#detail').innerHTML='<div class="detail-top"><h2 id="detail-title">비교 가능한 과거 사건</h2><button data-close aria-label="상세 닫기">×</button></div><p>조회 중…</p>';
  if(!$('#detail-dialog').open) $('#detail-dialog').showModal();
  try {
    const response=await fetch('/api/comparable-events?'+new URLSearchParams({article_id:values.comparable,market:values.market,symbol:values.symbol,basis:values.basis}),{signal:AbortSignal.timeout(15000)});
    if(!response.ok) throw new Error();
    const result=await response.json();
    if(request!==historyRequest || !$('#detail-dialog').open) return;
    $('#detail').innerHTML=`<div class="detail-top"><h2 id="detail-title">비교 가능한 과거 사건</h2><button data-close aria-label="상세 닫기">×</button></div><div class="detail-content">${comparableHTML(result)}</div>`;
  } catch {if(request===historyRequest) $('#detail').innerHTML='<h2>과거 사건 비교 조회 실패</h2><button data-close>닫기</button>';}
}
async function openReactions(articleId) {
  if(mode!=='live') return;
  const request=++historyRequest;detailId=null;
  $('#detail').innerHTML='<div class="detail-top"><h2 id="detail-title">일봉 반응 근거</h2><button data-close aria-label="상세 닫기">×</button></div>';
  if(!$('#detail-dialog').open) $('#detail-dialog').showModal();
  try {
    const response=await fetch('/api/reactions?'+new URLSearchParams({article_id:articleId}),{signal:AbortSignal.timeout(15000)});
    if(!response.ok) throw new Error();
    const result=await response.json();
    if(request!==historyRequest || !$('#detail-dialog').open) return;
    $('#detail').innerHTML=`<div class="detail-top"><h2 id="detail-title">일봉 반응 근거</h2><button data-close aria-label="상세 닫기">×</button></div><div class="detail-content">${reactionsHTML(result)}</div>`;
  } catch {if(request===historyRequest) $('#detail').innerHTML='<h2>일봉 반응 조회 실패</h2><button data-close>닫기</button>';}
}
async function openTrade() {
  if(mode!=='live') return;
  const request=++historyRequest;detailId=null;
  $('#detail').innerHTML='<div class="detail-top"><h2 id="detail-title">관세·규제 근거</h2><button data-close aria-label="상세 닫기">×</button></div>';
  if(!$('#detail-dialog').open) $('#detail-dialog').showModal();
  try {
    const asOf=$('#business-asof').value;
    const query=asOf ? '?as_of='+encodeURIComponent(asOf+'T00:00:00+09:00') : '';
    const response=await fetch('/api/trade-measures'+query,{signal:AbortSignal.timeout(15000)});
    if(!response.ok) throw new Error();
    const r=await response.json();
    if(request!==historyRequest || !$('#detail-dialog').open) return;
    $('#detail').innerHTML=`<div class="detail-top"><h2 id="detail-title">관세·규제 공식 근거</h2><button data-close aria-label="상세 닫기">×</button></div><div class="detail-content"><p>${escape(r.scope)} · 기준 ${escape(r.as_of || '전체 등록 이력')}</p>${r.measures.map(d=>`<section class="detail-overview"><h3>${escape(d.product)} · ${escape(({proposed:'제안·검토',finalized:'최종 조치',finalized_not_yet_effective:'확정 · 효력 발생 전',in_force_by_recorded_schedule:'등록된 효력일 도래 · 집행 미검증',expired_by_recorded_schedule:'등록된 종료일 경과',exempt:'제품별 예외',deferred:'집행 중단 지시'})[d.status_as_of] || d.status_as_of)}</h3>${macroDetailsHTML({kind:'trade',...d})}<details><summary>원문·예외·후속 변경</summary><blockquote>${escape(d.quote)}</blockquote><p>공개일 ${escape(d.published_date)} · 시각 미확인 · 에이전트 검토</p><p>${escape(d.notes)}</p><p>후속 변경 ${(d.followups || []).map(escape).join(' · ') || '등록 없음'}</p><a href="${escape(safeLink(d.url))}" target="_blank" rel="noopener noreferrer">공식 자료 ↗</a></details></section>`).join('')}${r.notes.map(n=>`<p>${escape(n)}</p>`).join('')}</div>`;
  } catch {if(request===historyRequest) $('#detail').innerHTML='<h2>관세·규제 근거 조회 실패</h2><button data-close>닫기</button>';}
}
async function openFX() {
  if(mode!=='live') return;
  const request=++historyRequest;detailId=null;
  $('#detail').innerHTML='<div class="detail-top"><h2 id="detail-title">환율 근거</h2><button data-close aria-label="상세 닫기">×</button></div>';
  if(!$('#detail-dialog').open) $('#detail-dialog').showModal();
  try {
    const response=await fetch('/api/fx',{signal:AbortSignal.timeout(15000)});
    if(!response.ok) throw new Error();
    const r=await response.json();
    if(request!==historyRequest || !$('#detail-dialog').open) return;
    const v=r.current,c=r.comparison;
    $('#detail').innerHTML=`<div class="detail-top"><h2 id="detail-title">환율 관측·통화 노출</h2><button data-close aria-label="상세 닫기">×</button></div><div class="detail-content">${v ? `<dl class="event-facts"><div><dt>통화·단위</dt><dd>${escape(v.unit)}</dd></div><div><dt>중간환율</dt><dd>${escape(v.mid_rate)}</dd></div><div><dt>매수환율</dt><dd>${escape(v.buy_rate)}</dd></div><div><dt>관측 구간</dt><dd>${escape(dateTime(v.valid_from))} ~ ${escape(dateTime(v.valid_until))}</dd></div><div><dt>관측 간 변화</dt><dd>${c ? escape(c.change_percent)+'%' : '비교 자료 부족'}</dd></div></dl><p>토스 참고용 환율 · 개인 사용 한정 · 현재 유효한지 관측 시각을 확인하세요.</p>` : '<p>보관된 환율 관측이 없습니다. 누락 값을 0으로 표시하지 않습니다.</p>'}${r.notes.map(n=>`<p>${escape(n)}</p>`).join('')}<a href="${escape(safeLink(r.reference_url))}" target="_blank" rel="noopener noreferrer">한국은행 환율 방향 설명 ↗</a><h3>공시로 확인한 통화 노출</h3>${r.exposures.map(e=>`<section class="detail-overview"><h4>${escape(e.code)} · ${escape(e.currency)} ${escape(e.exposure_type)}</h4><p>일부 유로 차입금의 선물환 헤지 확인. 순노출 규모·투자 수혜 방향 미확정.</p><details><summary>근거와 적용 범위</summary><blockquote>${escape(e.quote)}</blockquote><p>보고 기준 ${escape(e.period_end)} · 보수적 사용 시작 ${escape(e.known_from)} · 원 공개 시각 미확인 · 에이전트 검토</p><p>${escape(e.scope)}</p><a href="${escape(safeLink(e.url))}" target="_blank" rel="noopener noreferrer">공시 원문 ↗</a></details></section>`).join('')}</div>`;
  } catch {if(request===historyRequest) $('#detail').innerHTML='<h2>환율 근거 조회 실패</h2><button data-close>닫기</button>';}
}
async function openRateReferences() {
  if(mode!=='live') return;
  const request=++historyRequest;detailId=null;
  $('#detail').innerHTML='<div class="detail-top"><h2 id="detail-title">과거 공식 금리 결정문</h2><button data-close aria-label="상세 닫기">×</button></div>';
  $('#detail-dialog').showModal();
  try {
    const response=await fetch('/api/rate-decisions',{signal:AbortSignal.timeout(15000)});
    if(!response.ok) throw new Error();
    const result=await response.json();
    if(request!==historyRequest || !$('#detail-dialog').open) return;
    $('#detail').innerHTML=`<div class="detail-top"><h2 id="detail-title">과거 공식 금리 결정문</h2><button data-close aria-label="상세 닫기">×</button></div><div class="detail-content"><p>검토한 과거 결정만 표시합니다. 현재 금리·전체 결정 이력이 아닙니다.</p>${result.decisions.map(d=>`<section class="detail-overview"><h3>${escape(d.authority)} · ${escape(d.decision_date)}</h3>${macroDetailsHTML({...d,verification:'official_registry',changes:[{basis_points:d.delta_bp}]})}<blockquote>${escape(d.quote)}</blockquote></section>`).join('')}</div>`;
  } catch {if(request===historyRequest) $('#detail').innerHTML='<div class="detail-top"><h2 id="detail-title">조회 실패</h2><button data-close aria-label="상세 닫기">×</button></div><p>공식 근거를 확인할 수 없습니다.</p>';}
}
function evidenceHTML(e) {
  if(e.rule_version!=='article-evidence-v1') return '<section class="detail-overview"><h3>근거 확인 불가</h3><p>지원하지 않는 근거 버전입니다.</p></section>';
  const source={body_available:'제목·공개 추출 본문 보관',title_only:'제목만 보관 · 본문 미확보',source_missing:'대조 가능한 원문 버전 없음'};
  const dates=[['기사 공개',e.published_at],['포털 표시',e.portal_display_at],['최초 수집',e.first_seen_at],['본문 관측',e.body_observed_at]];
  return `<section class="detail-overview"><div class="overview-heading"><h3>자료 근거</h3><span>모델 미사용</span></div><dl class="event-facts"><div><dt>원자료</dt><dd>${escape(source[e.source_status] || '출처 부족')}</dd></div><div><dt>분류</dt><dd>${e.classification_status==='keyword_only' ? '제목 키워드 분류 · 사건 미판정' : '미분류'}</dd></div>${dates.map(([label,value])=>`<div><dt>${label}</dt><dd>${value ? escape(dateTime(value)) : '미확인'}</dd></div>`).join('')}</dl><details><summary>보관 원문·버전 보기</summary>${e.source_excerpt ? `<blockquote>${escape(e.source_excerpt)}</blockquote>` : '<p>원문 근거가 부족합니다.</p>'}${e.body_excerpt ? `<p>${escape(e.body_excerpt)}</p><p class="detail-meta">공개 추출 본문 앞부분입니다. 현재 제목과의 일치는 미검증이며 전문 전체를 보장하지 않습니다.</p>` : ''}<p class="detail-meta">기사 버전 ${escape(e.article_version || '미확인')} · 본문 버전 ${escape(e.body_version || '미확인')} · 기준 ${escape(e.rule_version)}</p></details><p class="detail-meta">사건 분석·투자 판단은 수행하지 않았습니다.</p></section>`;
}

function articleHTML(a, index) {
  const e = eventFor(a), ranked = view!=='feed' && hasContextRanking() && data?.intelligence?.ranking?.find(r=>r.event_id === e?.event_id);
  const assessment = data?.intelligence?.assessments?.find(r=>r.event_id === e?.event_id);
  const proof=impactEvidence(e,assessment);
  return `<article class="article-card ${ranked ? 'ranked' : ''}"><div class="article-body"><div class="article-topline"><div class="article-meta">${ranked ? `<span class="article-rank" aria-label="읽기 순위 ${index+1}">${index+1}</span>` : ''}<span>${escape(a.source)}</span><span class="meta-dot">·</span><time title="${escape(dateTime(a.published_at))}">${escape(ago(a.published_at))}</time>${a.kind==='report' ? '<span class="kind-badge">리포트</span>' : ''}${ranked && e?.certainty ? `<span class="certainty-badge">${escape(e.certainty)} · 검수 전</span>` : ''}</div><button class="bookmark-button" data-save="${escape(a.id)}" aria-label="${isSaved(a.id) ? '저장 해제' : '자료 저장'}: ${escape(a.title)}" aria-pressed="${isSaved(a.id)}">${icon('bookmark')}</button></div><h3><button class="article-title" data-detail="${escape(a.id)}" aria-haspopup="dialog">${escape(a.title)}</button></h3>${(a.related_stocks || []).length ? stocksHTML(a) : '<span class="stock-empty">관련 종목 확인 전</span>'}${ranked ? `<details class="reading-reason"><summary>읽을 이유</summary><dl class="decision-notes"><div><dt>${proof ? (e.article_id && e.article_id!==a.id ? '대표 원문 근거' : '원문 근거') : '모델 해석'}</dt><dd>${proof ? `<q>${escape(proof)}</q>` : escape(ranked.reason)}</dd></div><div><dt>다음 확인 · 모델 제안</dt><dd>${escape(ranked.watch_for || assessment?.watch_for || '원문의 새 사실을 확인하세요.')}</dd></div></dl></details>` : ''}<div class="article-footer"><div class="article-tags">${a.themes.slice(0,2).map(t=>`<button class="tag" data-theme="${escape(t.id)}">${escape(t.name)}</button>`).join('')}${e?.articles.length > 1 ? `<span class="event-count">관련 기사 ${e.articles.length}건</span>` : ''}</div><button class="read-button" data-detail="${escape(a.id)}">뉴스 보기 <span aria-hidden="true">→</span></button></div></div></article>`;
}
function toggleBriefing() { briefingExpanded=!briefingExpanded; renderList(); document.querySelector('[data-toggle-briefing]')?.focus({preventScroll:true}); }
let marketPreview=typeof window!=='undefined' && new URLSearchParams(window.location?.search || '').get('market-preview')==='1';
let marketData=null, marketError='', marketBusy=false, marketRegion='KR', marketSelection='', marketOrder=[];
const percentText=value=>Number.isFinite(value) ? `${value>0?'+':''}${value.toFixed(2)}%` : '—';
function marketRows() {
  const current=marketData?.candidates || [];
  return marketOrder.map(id=>current.find(c=>c.id===id)).filter(Boolean);
}
function marketNewsHTML(selected) {
  const codes=new Set(selected.stocks.map(s=>s.code));
  const seen=new Set();
  const articles=allArticles().filter(a=>{
    if(!a.related_stocks?.some(s=>codes.has(s.code)) || seen.has(a.url || a.id))return false;
    seen.add(a.url || a.id);return true;
  }).sort((a,b)=>(Date.parse(b.published_at)||0)-(Date.parse(a.published_at)||0));
  return `<section class="market-news"><h3>관련 뉴스</h3><p class="panel-description">최근 조회한 기사 중 연결된 자료 · 최신순</p>${articles.slice(0,8).map(a=>{
    const related=a.related_stocks.filter(s=>codes.has(s.code));
    const direct=related.some(s=>['direct','body'].includes(s.relation));
    const documented=related.some(s=>s.relation==='documented');
    return `<article class="market-news-row"><small>${escape(a.source)} · ${escape(dateTime(a.published_at))}${a.timestamp_basis==='portal_display'?' · 포털 표시':''} · ${direct?'직접 언급':documented?'공개 사업 관계':'같은 사업·테마'}</small><button data-detail="${escape(a.id)}">${escape(a.title)}</button><div class="stock-chips">${related.map(s=>`<button class="stock-chip" data-stock="${escape(s.code)}" data-article="${escape(a.id)}">${escape(s.name)} <span data-stock-code="${escape(s.code)}" data-compact>${changeHTML(s.code)}</span></button>`).join('')}</div></article>`;
  }).join('') || '<p>최근 조회한 기사에서 연결된 새 기사를 찾지 못했어요.</p>'}<button data-market-archive="${escape(selected.name)}">전체 뉴스에서 검색</button></section>`;
}
function renderMarket() {
  const active=marketPreview && view==='briefing' && mode==='live' && data?.product_mode==='data';
  $('#market-view').hidden=!active;
  if(!active)return;
  $('.reading-section').hidden=true;$('.context-column').hidden=true;
  $('#page-title').textContent='지금 시장';$('#page-label').textContent='지금 시장';
  $('#page-description').textContent='주목할 분야를 고르고, 종목과 뉴스를 함께 확인하세요.';
  document.querySelector('[data-view="briefing"]').textContent='지금 시장';
  const rows=marketRows();
  const selected=rows.find(c=>c.id===marketSelection);
  const pending=(marketData?.candidates || []).filter(c=>!marketOrder.includes(c.id)).length;
  const html=`<div class="market-toolbar"><div role="group" aria-label="시장 선택"><button data-market-region="KR" aria-pressed="${marketRegion==='KR'}">국내</button><button data-market-region="US" aria-pressed="${marketRegion==='US'}">미국</button></div><span>${marketData ? `추적 ${marketData.tracked}종목 · ${escape(quoteTime(marketData.as_of))} 기준` : '관측 조회 중'}</span></div>${marketError ? `<p role="status">${escape(marketError)}</p>` : ''}<div class="market-explorer"><section aria-label="주목할 대상"><h2>지금 주목할 테마·종목</h2><p class="panel-description">최근 5분 · 시장 대비 차이 기준 · 검증 중</p>${pending ? `<button data-market-apply>새 항목 ${pending}개 반영</button>` : ''}${rows.map(c=>`<button class="market-choice" data-market-select="${escape(c.id)}" aria-pressed="${c.id===marketSelection}"><strong>${escape(c.name)}</strong><span>${c.kind==='theme'?'평균 ':''}${percentText(c.mean_percent)}${c.kind==='theme'?` · 관측 ${c.observed}/${c.tracked}종목, ${c.up}상승·${c.down}하락`:''}</span><small>${escape(c.reason)}</small></button>`).join('') || `<p>${marketBusy && !marketData ? '관측을 불러오고 있어요.' : '현재 비교 기준에 맞는 항목이 없어요. 정규장과 시세 수집 상태에 따라 달라져요.'}</p><button data-view="feed">전체 뉴스 보기</button>`}</section><section aria-label="종목 비교">${selected ? `<h2>${escape(selected.name)}</h2><p class="panel-description">같은 최근 5분 구간의 종목 비교</p><table class="market-table"><thead><tr><th>종목</th><th>금일</th><th>최근 5분</th></tr></thead><tbody>${selected.stocks.map(s=>`<tr><td><button data-market-stock="${escape(s.code)}">${escape(s.name)}</button></td><td><span data-stock-code="${escape(s.code)}" data-compact>${changeHTML(s.code)}</span></td><td>${percentText(s.recent.change_percent)}</td></tr>`).join('')}</tbody></table>${marketNewsHTML(selected)}` : '<h2>종목과 관련 뉴스</h2><p>왼쪽에서 살펴볼 대상을 선택하세요.</p>'}</section></div>`;
  const container=$('#market-view');
  if(container.renderedHTML!==html){
    const focused=document.activeElement?.dataset || {};
    container.innerHTML=html;container.renderedHTML=html;
    const match=[...container.querySelectorAll('button')].find(b=>['marketSelect','marketStock','marketRegion'].some(k=>focused[k] && b.dataset[k]===focused[k]));
    match?.focus({preventScroll:true});
  }
}
async function loadMarket() {
  if(mode!=='live' || marketBusy)return;
  marketBusy=true;const region=marketRegion;
  try {
    const response=await fetch('/api/market-watch?market='+region,{signal:AbortSignal.timeout(15000)});
    if(!response.ok)throw new Error();
    const result=await response.json();if(region!==marketRegion)return;
    marketData=result;marketError='';
    if(!marketOrder.length){marketOrder=result.candidates.map(c=>c.id);marketSelection=marketOrder[0] || '';}
  } catch {marketData=null;marketError='시세 비교를 갱신하지 못했어요. 잠시 후 다시 확인해 주세요.';}
  finally {marketBusy=false;renderMarket();}
}
function renderList() {
  const articles = filteredArticles();
  const visible = view === 'briefing' && !briefingExpanded ? articles.slice(0,8) : articles;
  $('#result-count').textContent = visible.length<articles.length ? `${visible.length} / ${articles.length}` : articles.length;
  $('#articles').setAttribute('aria-busy', String(!data && loading));
  if (!data && loading) { delete $('#articles').renderedHTML; $('#articles').innerHTML = '<div class="loading-state"><span class="loader"></span><h3>자료를 불러오고 있어요</h3><p>선택한 모드의 자료를 확인합니다.</p></div>'; return; }
  $('#theme-active').hidden = !theme;
  $('#theme-active').innerHTML = theme ? `<button data-clear-theme>주제: ${escape(data?.themes.find(t=>t.id === theme)?.name || theme)} ×</button>` : '';
  const firstPending = view!=='feed' && hasContextRanking() ? visible.findIndex(a=>!data.intelligence.ranking.some(r=>r.event_id === eventFor(a)?.event_id)) : -1;
  let html;
  if (articles.length) html = visible.map((a,i)=>(i === firstPending ? '<div class="ranking-divider">아직 모델 순위가 없는 자료 · 최신성순</div>' : '')+articleHTML(a,i)).join('') + (view === 'briefing' && articles.length > 8 ? `<button class="full-list-button" data-toggle-briefing aria-expanded="${briefingExpanded}">${briefingExpanded ? '8개만 보기' : `${hasContextRanking() ? '검토한 자료' : '현재 목록'} ${articles.length}건 모두 보기`}</button>` : '');
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
  const dataProduct=mode==='live' && data?.product_mode==='data';
  if(dataProduct && sort==='context') sort='latest';
  $('#sort option[value="context"]').disabled=Boolean(dataProduct);
  const articles = data?.articles || [], themes = [...(data?.themes || [])].sort((a,b)=>b.count-a.count), statuses = data?.sources || [];
  const labels = {briefing:'지금 볼 뉴스',feed:'전체 뉴스',saved:'저장한 뉴스',sources:'서비스 상태',business:'테마·종목'};
  document.querySelectorAll('[data-view]').forEach(button=>{button.classList.toggle('active', button.dataset.view === view); button.setAttribute('aria-current', button.dataset.view === view ? 'page' : 'false'); });
  $('#page-label').textContent = labels[view];
  $('#nav-count').textContent = mode==='live' ? data?.archive?.articles ?? articles.length : articles.length;
  $('#saved-count').textContent = saved.filter(a=>a.mode === mode).length;
  $('#stats').hidden = view !== 'sources';
  $('.context-column').hidden = ['sources','business'].includes(view);
  $('.reading-section').hidden = ['sources','business'].includes(view); $('#source-view').hidden = view !== 'sources';
  $('#business-view').hidden=view!=='business';
  $('#business-content').innerHTML=mode!=='live' ? '<p>실제 수집 모드에서 사업 근거를 확인하세요.</p>' : businessLoading ? '<p>선택한 기준일의 사업 근거 조회 중</p>' : businessError ? `<p>${escape(businessError)}</p>` : businessHTML(businessData || data?.business);
  $('#sort').value = sort;
  $('#sort').disabled = view==='feed' && mode==='live';
  const archiveView=view==='feed' && mode==='live';
  $('.sort-label').hidden=dataProduct || archiveView;
  $('#archive-tools').hidden=!archiveView; $('#archive-pagination').hidden=!archiveView;
  $('#archive-prev').disabled=archiveLoading || !archiveCursors.length;
  $('#archive-next').disabled=archiveLoading || !archiveData?.next_cursor;
  $('#archive-page-status').textContent=archiveLoading ? '누적 기사 조회 중' : archiveError || `${archiveCursors.length+1}페이지 · 조건에 맞는 기사 ${archiveData?.total ?? '—'}건`;
  const sourceOptions='<option value="">전체 언론사</option>'+(archiveData?.sources || []).map(s=>`<option value="${escape(s)}">${escape(s)}</option>`).join('');
  if ($('#archive-source').renderedHTML!==sourceOptions) { $('#archive-source').innerHTML=sourceOptions; $('#archive-source').renderedHTML=sourceOptions; }
  $('#archive-source').value=archiveSource;
  const ai=data?.intelligence;
  const coverage=ai?.coverage;
  const coverageText=coverage?.candidates>0 && Number.isInteger(coverage.analyzed_articles) ? `이번 대상 ${coverage.candidates}건 중 본문 분석 ${coverage.analyzed_articles}건${coverage.analyzed_articles<coverage.candidates ? ' · 미분석 기사는 순위에서 제외' : ''}` : '';
  const screenCoverageText=coverage?.events>0 && Number.isInteger(coverage.screened_events) && Number.isInteger(coverage.screen_pending_events) ? `선별 판정 ${coverage.screened_events}/${coverage.events}개 사건` : '';
  const rankCoverageText=Number.isInteger(coverage?.eligible_events) && Number.isInteger(coverage.reviewed_events) && Number.isInteger(coverage.unreviewed_events) ? `최종 순위 검토 ${coverage.reviewed_events}/${coverage.eligible_events}개 사건${coverage.unreviewed_events ? ` · 미검토 ${coverage.unreviewed_events}개` : ''}` : '';
  const priorityCoverageText=coverage?.eligible_events>0 && Number.isInteger(coverage.priority_scored_events) && Number.isInteger(coverage.priority_pending_events) && ['pointwise_priority','input_order_pending_priority'].includes(ai?.candidate_selection) ? `후보 중요도 평가 ${coverage.priority_scored_events}/${coverage.eligible_events}개 사건 · ${ai.candidate_selection==='pointwise_priority' ? '중요도순 후보 선정' : '보충 중 · 기존 순서로 비교'}` : '';
  const rankingReady = !rankingExpired() && ai?.assessments?.length > 0;
  $('#list-caption').textContent = view === 'saved' ? '마지막으로 저장했을 때의 내용입니다.' : sort === 'context' ? (hasContextRanking() ? `${ai.ranking_partial ? '일부 사건의 모델 참고 순위' : '주식 영향 경로를 확인한 모델 참고 순위'} · 기준 ${dateTime(ai.ranked_at)} · 상품 안내·배경 기사는 전체 자료에서 확인` : `${rankingExpired() && ai?.ranked_at ? '모델 순위 갱신 지연' : ai?.message || '모델 분석 대기'} · 주식 추천 미적용: 전체 자료에서 최신 기사를 확인하세요.`) : '최신성만으로 정렬해요. 주제는 점수에 반영하지 않아요.';
  if (archiveView) $('#list-caption').textContent='누적 보관 기사 · 최신순 · 미분석·추천 제외 자료와 같은 사건의 원문도 각각 표시합니다.';
  if (view==='briefing' && sort==='context' && coverageText) $('#list-caption').textContent+=` · ${coverageText}`;
  if (view==='briefing' && sort==='context' && screenCoverageText && coverage.screen_pending_events>0) $('#list-caption').textContent+=` · ${screenCoverageText}`;
  if (view==='briefing' && sort==='context' && rankCoverageText) $('#list-caption').textContent+=` · ${rankCoverageText}`;
  if (view==='briefing' && sort==='context' && priorityCoverageText) $('#list-caption').textContent+=` · ${ai.candidate_selection==='pointwise_priority' ? '중요도순 후보 비교' : `후보 중요도 보충 ${coverage.priority_scored_events}/${coverage.eligible_events}`}`;
  const stats = [
    ['filter','주식 판단 재료',rankingReady ? ai.ranking.length : '—','건',rankingReady ? '최종 검토된 사건 내 순위 · 검수 전' : '분석 대기 · 추천 미적용'],
    ['document','수집한 자료',mode==='live' ? data?.archive?.articles ?? data?.raw_count ?? '—' : data?.raw_count ?? '—','건',mode === 'demo' ? '가상 시나리오' : '배경·상품 기사도 모두 수집'],
    ['clock','분석 기준',ai?.ranked_at ? dateTime(ai.ranked_at).split('일 ')[1] || dateTime(ai.ranked_at) : '대기 중','',rankingExpired() ? '갱신 지연 · 이전 분석' : '기사 시각과 별도 확인'],
  ];
  $('#stats').innerHTML = stats.map(([i,label,value,unit,caption])=>`<div class="stat"><div class="stat-label">${icon(i)}${label}</div><div class="stat-value">${escape(value)}<small>${unit}</small></div><div class="stat-caption">${caption}</div></div>`).join('');
  $('#mode-label').textContent = mode === 'demo' ? '가상 시나리오' : '실시간 투자 브리핑';
  if(dataProduct) {
    $('#mode-label').textContent='근거 데이터 · AI 미사용';
    $('#list-caption').textContent=archiveView ? '누적 기사 · 최신순 · 미분류·본문 부족 자료도 모두 보관합니다.' : '최신성 기준 · 제목 키워드 분류 · AI 분석·추천 미사용';
    $('#stats').innerHTML=`<div class="stat"><div class="stat-label">수집한 자료</div><div class="stat-value">${escape(data.archive?.articles ?? articles.length)}<small>건</small></div><div class="stat-caption">미분류 포함 · 전체 기사 보관</div></div><div class="stat"><div class="stat-label">분석 방식</div><div class="stat-value">AI 미사용</div><div class="stat-caption">사건 판정·투자 추천 미적용</div></div>`;
  }
  $('#page-title').textContent=labels[view];
  $('#page-description').textContent={briefing:'뉴스를 고르고, 관련 종목을 확인하세요.',feed:'찾고 싶은 뉴스는 검색하거나 기간을 골라보세요.',saved:'다시 읽고 싶은 뉴스를 모아뒀어요. 이 브라우저에 저장돼요.',business:'관심 있는 분야에서 어떤 기업을 살펴볼지 찾아보세요.',sources:'뉴스와 시세가 정상적으로 들어오는지 확인하세요.'}[view];
  $('#list-heading').firstChild.textContent=view==='saved' ? '저장한 뉴스 ' : view==='feed' ? '전체 뉴스 ' : hasContextRanking() ? '먼저 살펴볼 뉴스 ' : '최신 뉴스 ';
  $('#list-status').textContent=!data && loading ? '최신 뉴스를 불러오고 있어요.' : view==='saved' ? '저장 당시 내용이에요. 최신 소식은 원문에서 확인하세요.' : archiveView ? '최신순 · 수집한 전체 뉴스' : hasContextRanking() ? `읽기 우선순위 · ${dateTime(ai.ranked_at)} 기준 · 검수 전` : sort==='context' ? (rankingExpired() ? '선별 결과 갱신이 늦어지고 있어요. 전체 뉴스에서 확인하세요.' : '선별된 뉴스가 아직 없어요. 전체 뉴스에서 확인하세요.') : sort==='priority' ? '최신성순 · 투자 추천 순위는 아니에요.' : '최신순으로 보고 있어요. 투자 추천 순위는 아니에요.';
  $('#mode-button').innerHTML = `${icon(mode === 'demo' ? 'radio' : 'sparkles')}${mode === 'demo' ? '실제 수집으로 돌아가기' : '시나리오 체험'}`;
  const failed = statuses.filter(s=>['error','stale'].includes(s.status));
  const notice = $('#mode-notice');
  notice.hidden = mode !== 'demo' && !failed.length && !loadFailed;
  notice.classList.toggle('error-notice', mode !== 'demo' || loadFailed);
  notice.textContent = mode === 'demo' ? '가상 시나리오 체험 중입니다. 아래 기사·리포트와 시장 상황은 기능 설명을 위해 만든 예시이며 실제 뉴스가 아닙니다.' : `${failed.map(s=>s.name).join(', ')} 수집에 실패했습니다. 이전 자료가 있는 경우 마지막 성공 자료를 표시합니다. 수집 현황에서 확인해 주세요.`;
  if (loadFailed) notice.textContent=`화면 갱신 실패 · ${data ? '이전 자료를 표시하고 있으며 새 기사와 추천 변경을 확인할 수 없습니다.' : '서버 응답을 확인할 수 없습니다.'}${mode==='demo' ? ' 가상 시나리오이며 실제 뉴스가 아닙니다.' : ''}`;
  $('#update-time').textContent = mode === 'demo' ? '가상 시나리오 · 실제 시장 정보 아님' : data?.collecting ? '새 자료를 수집하고 있어요' : data?.updated_at ? `수집 확인 ${dateTime(data.updated_at)}` : '첫 자료를 수집하고 있어요';
  if (loadFailed) $('#update-time').textContent=`화면 갱신 실패 · ${lastLoadedAt ? `마지막 정상 응답 ${quoteTime(lastLoadedAt)}` : '정상 응답 시각 미확인'}`;
  $('#themes').innerHTML = themes.filter(t=>t.count>0).slice(0,5).map(t=>`<button class="theme-row" data-theme="${escape(t.id)}" aria-pressed="${theme === t.id}"><div><span class="theme-name"><span class="theme-dot"></span>${escape(t.name)}</span><span class="theme-count">${t.count}건</span></div><div class="theme-track"><div class="theme-fill"></div></div></button>`).join('') || '<p class="panel-description">자료를 기다리고 있어요.</p>';
  $('#themes').querySelectorAll('.theme-fill').forEach((el,i)=>{el.style.width = `${Math.round(themes.filter(t=>t.count>0)[i].count/(themes[0]?.count || 1)*100)}%`;});
  const market = (ai?.market?.observations || []).filter(q=>['069500','229200','SPY'].includes(q.code));
  const marketMissing=ai?.market?.missing?.length>0;
  const marketNotice=marketMissing ? (ai.market.observations?.length ? '시장 자료 일부 누락 · 전체 시장 판단에 한계가 있습니다.' : '시장 자료 조회 실패 · 시장 움직임을 확인할 수 없습니다.') : '';
  $('#market-snapshot').innerHTML = (marketNotice ? `<p class="panel-description">${marketNotice}</p>` : '')+(market.length ? market.map(q=>`<div class="market-row"><div><strong>${escape(q.name)}</strong><small>${escape(quoteTime(q.traded_at))}${q.market_status === 'CLOSE' ? ' · 장마감' : ''} · ${escape(q.delay_label || '지연 여부 미제공')}</small></div><span class="stock-change ${q.change_percent > 0 ? 'up' : q.change_percent < 0 ? 'down' : 'flat'}">${Number.isFinite(q.change_percent) ? `${q.change_percent > 0 ? '+' : ''}${q.change_percent.toFixed(2)}%` : '—'}</span></div>`).join('') : marketMissing ? '' : '<p class="panel-description">현재 확인할 수 있는 시세가 없어요.</p>')+(ai?.market?.as_of ? `<p class="panel-description">시장 조회 ${escape(quoteTime(ai.market.as_of))} · 거래 기준과 별도</p>` : '');
  $('#source-view').innerHTML = statuses.map(s=>`<div class="source-detail"><h3>${escape(s.name)}</h3><span class="source-status ${escape(s.status)}">${{ok:'정상 수집',stale:'수집 실패 · 마지막 성공 자료 유지',error:'수집 실패',demo:'가상 시나리오'}[s.status] || '대기'}</span><p>자료 ${s.count}건 · 마지막 성공: ${s.last_success ? escape(dateTime(s.last_success)) : '아직 없음'}${s.error ? `<br>${escape(s.error)}` : ''}</p>${safeLink(s.url) ? `<a href="${escape(safeLink(s.url))}" target="_blank" rel="noopener noreferrer">공개 RSS 확인 ↗</a>` : ''}</div>`).join('') + '<div class="source-detail"><h3>네이버 증권 리포트</h3><span class="source-status stale">자동 수집 미연결 · 원문 링크 제공</span><p>현재 페이지가 별도 요청으로 자료를 불러와 이번 시제품에는 자동 수집을 연결하지 않았습니다. 본문과 PDF를 분석한 결과는 제공하지 않습니다.</p><a href="https://stock.naver.com/research" target="_blank" rel="noopener noreferrer">리포트 원문 사이트 ↗</a></div><div class="source-detail"><h3>선별 방식</h3><p>발행 직후 최신성 50점에서 첫 60분 동안 25점까지 선형 감소하고, 이후 시간당 1점씩 최저 0점까지 감소합니다. 자료 유형에 따른 가점은 없습니다. 주제 분류는 필터용이며 점수에 반영하지 않습니다. 한국경제 RSS와 별도 작업자의 Npay 증권 전체 속보를 보관합니다. 포털의 여러 매체를 수집하는 것과 독립된 사실 교차 검증은 다릅니다. 관련 국내·미국 종목의 현재가·전일 대비 등락률은 Npay 증권에서 조회합니다. 환율·거래량과 주도주 판별은 미연결입니다.</p></div>';
  const stored=data?.archive;
  if(mode==='live' && data?.history) $('#source-view').innerHTML += historyQualityHTML(data.history);
  const collection=data?.collection;
  const pipeline=data?.data_pipeline;
  if(pipeline) $('#source-view').innerHTML+=pipelineHTML(pipeline);
  if (collection) $('#source-view').innerHTML += `<div class="source-detail"><h3>포털 속보 · 날짜별 대조</h3><p>대상 날짜 ${escape(collection.day)} · 다음 확인 ${escape(collection.next_page)}페이지</p><p>최근 목록 확인 ${escape(dateTime(collection.last_success))} · 최근 전체 대조 ${collection.complete_at ? escape(dateTime(collection.complete_at)) : '진행 중'}</p>${collection.last_error ? `<p>수집 지연: ${escape(collection.last_error)}</p>` : ''}<p>상시 작업자는 10초 간격으로 확인하고 정기 복구는 5분 간격으로 실행하도록 설정했습니다. 원본의 반영 지연과 오류 대기 시간은 별도입니다. 전체 대조는 확인한 날짜의 포털 속보 목록 기준이며 모든 매체의 전문 확보를 뜻하지 않습니다.</p></div>`;
  $('#source-view').innerHTML += `<div class="source-detail"><h3>전체 수집 · 누적 보관</h3><p>수집과 보관에는 추천 적합성 필터를 적용하지 않습니다. 일반 금융 뉴스·상품 안내·행사도 함께 보관합니다.</p><p>기사 ${stored?.articles || 0}건 · RSS 기록 ${stored?.revisions || 0}개 · 공개 본문 ${stored?.bodies || 0}건 · 본문 대기 ${stored?.pending || 0}건 · 실패 ${stored?.errors || 0}건</p><p>${escape(data?.archive_error || stored?.message || '서버 재시작 후에도 보관 자료를 유지합니다. 전체 자료 메뉴에서 누적 보관 기사를 날짜·언론사·검색어로 조회할 수 있습니다.')}</p><p>본문은 추천 모델과 독립적으로 수집합니다. 공개 추출 내용만 지원하며 로그인·유료 전문은 보장하지 않습니다.</p></div>`;
  const stockStatus = data?.stock_status;
  $('#source-view').innerHTML += `<div class="source-detail"><h3>관련 주식 · KRX / Nasdaq / Npay 증권</h3><p>공식 상장 목록 ${stockStatus?.count || 0}개 (국내 ${stockStatus?.markets?.KR || 0} · 미국 ${stockStatus?.markets?.US || 0}) · 목록 상태 ${escape(stockStatus?.status || 'loading')} · 마지막 갱신 ${escape(dateTime(stockStatus?.updated_at))}</p><p>기사의 직접 언급, 출처가 있는 사업 관계, 가치사슬 추론, 테마 관찰을 구분해 국내·미국 관련 종목을 연결합니다. 관계의 출처·공개일·검토일과 추가 확인할 조건을 제공합니다. 최신성 점수는 별도로 유지하며, 기본 추천은 주식 적합성 검토를 통과한 사건의 모델 순위를 사용합니다. 관련 후보는 수혜·피해 판정이 아닙니다. 시세는 화면에 보이는 종목부터 조회하며 10초 동안 재사용합니다. 실패한 시세는 이전 조회로 표시하고 거래 기준 시각과 조회 시각을 함께 제공합니다.</p></div>`;
  document.querySelectorAll('[data-kind]').forEach(b=>{b.classList.toggle('active',b.dataset.kind === kind); b.setAttribute('aria-pressed',String(b.dataset.kind === kind));});
  $('#source-view').innerHTML += `<div class="source-detail"><h3>본문 분석 · 사건 묶기 · 시장 맥락순</h3><p>${escape(ai?.message || '가상 시나리오에서는 모델 분석 미사용')} · ${escape(ai?.model || '')}</p><p>금일 현재 제공처 요청 ${ai?.usage?.calls_today || 0}회${ai?.usage?.legacy_calls_today ? ` · 금일 제공처 미상 과거 기록 ${escape(ai.usage.legacy_calls_today)}회 별도 보존` : ''} · ${ai?.daily_call_limit === null ? '일일 제한 없음' : ai?.daily_call_limit ? `일일 한도 ${escape(ai.daily_call_limit)}회` : '한도 정보 대기'} · 마지막 분석 ${escape(dateTime(ai?.updated_at))}</p><p>${escape(ai?.market?.limitations || '시장 자료 대기')}</p>${(ai?.market?.observations || []).map(q=>`<p>${escape(q.name)} ${q.change_percent > 0 ? '+' : ''}${Number(q.change_percent).toFixed(2)}% · 기준 ${escape(quoteTime(q.traded_at))}${q.relative_to_spy_pp !== undefined ? ` · S&P500 대비 ${Number(q.relative_to_spy_pp).toFixed(2)}%p` : ''}</p>`).join('')}<p>${escape(ai?.error || '')}${ai?.market?.missing?.length ? ` · 시장 자료 누락: ${ai.market.missing.map(escape).join(', ')}` : ''}</p></div>`;
  const queue = ai?.queue;
  const freshScheduling=queue?.priority_window && ['fresh_window_seconds','fresh_unfinished','fresh_ready'].every(k=>Number.isInteger(queue.priority_window[k]) && queue.priority_window[k]>=0) && queue.priority_window.fresh_window_seconds>0;
  if (rankCoverageText) $('#source-view').innerHTML += `<div class="source-detail"><h3>최종 순위 검토 범위</h3><p>${escape(rankCoverageText)}</p><p>현재는 후보 중 최대 12개 사건을 최종 비교합니다. 미검토는 최종 비교 범위 밖이라는 뜻이며 주식 판단 재료가 아니라는 판정이 아닙니다. 원문은 전체 자료에서 확인할 수 있습니다. ${ai?.ranking_role==='qualified_order' ? '선별을 통과한 사건의 순서만 비교하며, 적합성 판정을 다시 바꾸지 않습니다.' : '검토 건수에는 최종 추천에서 제외한 사건도 포함합니다.'}</p></div>`;
  if (screenCoverageText) $('#source-view').innerHTML += `<div class="source-detail"><h3>원문 분석과 선별 판정</h3><p>${escape(screenCoverageText)} · 현행 선별 기준 대기 ${coverage.screen_pending_events}개</p><p>현재 읽기 기준의 본문 분석 사건과 현행 선별 판정 완료 수를 구분합니다. 선별 기준 재검토 중에도 같은 원문의 호환되는 사실 정보는 유지하지만 이전 선별 판정을 새 추천으로 승계하지 않습니다. 중요도 후보 선정이 준비돼도 아직 판정하지 않은 사건까지 검토한 뜻은 아닙니다. 모델 판정은 검수 전입니다.</p></div>`;
  if (priorityCoverageText) $('#source-view').innerHTML += `<div class="source-detail"><h3>사건별 중요도 · 후보 구성</h3><p>${escape(priorityCoverageText)}</p><p>${ai.candidate_selection==='pointwise_priority' ? '현재 분석된 적합 사건의 중요도 평가를 바탕으로 상위 최대 12개를 시장 맥락으로 최종 비교합니다. 동점이면 기존 사건 순서를 유지합니다.' : '중요도를 보충하고 있습니다. 끝나기 전에는 기존 사건 순서로 최대 12개 후보를 비교하며 미평가를 0점으로 두지 않습니다.'}</p><p>변화 규모·임박성·적용 범위와 원문 근거를 함께 평가하며 특정 업종을 고정 우대하지 않습니다. 중요도는 읽을 순서를 위한 모델 판단이며 수익 확률·매수 신호가 아닙니다. 모든 사건을 최종 비교했다는 뜻도 아닙니다.</p></div>`;
  if (ai?.rank_retry_at) $('#source-view').innerHTML += `<div class="source-detail"><h3>순위 재시도 대기</h3><p>같은 입력의 순위 판단이 실패해 ${escape(dateTime(ai.rank_retry_at))} 이후 다시 확인합니다. 본문 분석은 계속하며 새 기사 근거나 시장 입력이 바뀌면 이 재시도 대기를 적용하지 않습니다.</p></div>`;
  if (ai?.rank_cache_error) $('#source-view').innerHTML += `<div class="source-detail"><h3>순위 복구·저장 상태</h3><p>${escape(ai.rank_cache_error)}</p></div>`;
  $('#source-view').innerHTML += `<div class="source-detail"><h3>분석 대기열 · 사건 보관</h3>${queue ? `<dl class="event-facts">${[['분석 대기',`${queue.pending}건`],['처리 중',`${queue.processing}건`],['재시도 대기',`${queue.retrying}건`],...(Number.isInteger(queue.source_waiting) && queue.source_waiting>=0 ? [['원래 제목의 본문 대기',`${queue.source_waiting}건`]] : []),...(Number.isInteger(queue.insufficient_body) && queue.insufficient_body>=0 ? [['본문 보강 필요',`${queue.insufficient_body}건`]] : []),['완료한 버전',`${queue.done}건`],['보관 사건',`${queue.event_count}건`],['최장 대기',`${Math.ceil(queue.oldest_wait_seconds/60)}분`],['전체 작업 등록 → 완료 p95',queue.recent_p95_seconds == null ? '집계 대기' : `${Math.ceil(queue.recent_p95_seconds/60)}분`]].map(([label,value])=>`<div><dt>${label}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl>` : '<p>대기열 상태를 확인하고 있습니다.</p>'}<p>누적 자료의 초기 등록은 순차 진행합니다. ${freshScheduling ? `처리 가능한 발행 ${queue.priority_window.fresh_window_seconds/3600}시간 이내 자료를 먼저 분석합니다. 없으면 ${queue.priority_window.window_seconds/3600}시간 이내 자료, 그다음 과거 작업을 처리합니다. 선택한 범위 안에서 기존 대기 1건·최신 2건을 교대하고 재검토에도 차례를 줍니다. 새 자료가 계속 밀리면 그보다 오래된 분석도 미뤄질 수 있습니다.` : '처리 가능한 현재 범위 자료가 있으면 그 안에서 기존 대기 1건·최신 2건을 교대하고 이전 기준의 재검토에도 차례를 줍니다. 현재 자료가 없거나 재시도 대기 중이면 과거 작업을 처리합니다. 현재 대기가 계속되면 과거 분석은 오래 미뤄질 수 있습니다.'} 중요도 보충 중인 호환 선별 결과는 유지하고, 그 밖의 기준 변경 재검토 중인 판정은 추천에서 제외하며, 실패한 작업은 5~60분 후 재시도합니다. 중단된 작업은 최대 5분 후 다시 처리합니다.</p>${ai?.queue_sync_error ? `<p>${escape(ai.queue_sync_error)}</p>` : ''}</div>`;
  if (queue?.insufficient_body>0) $('#source-view').innerHTML += `<div class="source-detail"><h3>본문 보강 필요</h3><p>고정된 본문이 인용 최소 길이보다 짧은 ${queue.insufficient_body}개 버전은 같은 입력으로 반복 분석하지 않습니다. 원문·작업은 보관하며 분석 완료나 추천 제외 판정이 아닙니다. 새 본문 버전이 수집되면 별도 작업으로 분석합니다. 새 본문을 얻을 수 있다는 보장은 없습니다.</p></div>`;
  if (Number.isInteger(queue?.source_waiting) && queue.source_waiting>0) $('#source-view').innerHTML += `<div class="source-detail"><h3>원래 제목의 본문 대기</h3><p>${queue.source_waiting}개 작업은 보관된 최신 제목이 달라 분석에 사용하지 않습니다. 원문·오류·시도 이력은 유지하며 완료나 추천 제외 판정이 아닙니다. 1시간 간격으로 같은 제목·충분한 길이·입력 시각 이후의 정상 본문을 다시 확인해 분석을 재개합니다. 본문 버전이 새로 등록되면 별도 작업으로 처리하며, 다른 제목의 완료 분석으로 대신하지 않습니다.</p></div>`;
  const live = queue?.live_analysis;
  const priority = queue?.priority_window;
  if (priority) $('#source-view').innerHTML += `<div class="source-detail"><h3>현재 자료 분석 범위</h3><dl class="event-facts">${[[`${priority.window_seconds/3600}시간 이내 미완료 작업`,`${priority.current_unfinished}건`],['이 중 지금 처리 가능',`${priority.current_ready}건`],['그 외 미완료 작업',`${priority.other_unfinished}건`],['현재 자료 중 가장 오래된 발행 경과',latencyText(priority.oldest_current_age_seconds)]].map(([label,value])=>`<div><dt>${escape(label)}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl><p>발행 시각이 현재 범위인 미완료 작업이며 재검토·처리 중·재시도 대기를 포함합니다. 지금 처리 가능은 재시도·처리 권한 대기가 끝난 작업입니다. 그 외는 과거·미래·시각 미상 자료입니다. 기사 수나 추천 수가 아니며, 현재 범위가 비어 있어도 분석·추천 완료를 뜻하지 않습니다.</p></div>`;
  if (freshScheduling) $('#source-view').innerHTML += `<div class="source-detail"><h3>신규 자료 우선 처리</h3><p>발행 ${priority.fresh_window_seconds/3600}시간 이내 미완료 ${priority.fresh_unfinished}건 · 지금 처리 가능 ${priority.fresh_ready}건</p><p>대기·처리 중·재시도를 포함하며 재시도 대기 시간은 건너뛰지 않습니다. 분석 작업의 처리 순서이며 추천 적합성·읽기 우선순위·26시간의 사건 유효 범위를 바꾸지 않습니다. 오래된 자료도 삭제하거나 분석 완료로 처리하지 않습니다.</p></div>`;
  if (live) $('#source-view').innerHTML += `<div class="source-detail"><h3>실시간 등록 자료 · 분석 지연</h3><dl class="event-facts">${[['완료 표본',`${live.samples}건`],['발행 → 분석 완료 p50',latencyText(live.p50_seconds)],['발행 → 분석 완료 p95',latencyText(live.p95_seconds)],['미완료 작업',`${live.pending}건`],['가장 오래된 미완료',latencyText(live.oldest_unfinished_seconds)]].map(([label,value])=>`<div><dt>${label}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl><p>발행 후 1시간 이내 등록한 기사 버전별 일반 분석 중 최근 1시간에 완료한 최대 100건입니다. 과거 자료 보충·판정 재검토와 구분하며, 최종 추천 공개까지의 시간은 포함하지 않습니다. 미완료 작업은 오래 지연돼도 집계에서 빠지지 않습니다.</p></div>`;
  const linking=ai?.event_linking;
  if (linking && ['pairs','reviewed_pairs','matched_pairs','blocked_pairs','pending_pairs','deferred_groups'].every(k=>Number.isInteger(linking[k]) && linking[k]>=0)) $('#source-view').innerHTML += `<div class="source-detail"><h3>같은 제목 사건 · 연결 재검토</h3><p>두 사건 후보 ${linking.pairs}쌍 · 모델 검토 ${linking.reviewed_pairs}쌍 · 연결 ${linking.matched_pairs}쌍 · 당사자·상태 차이로 분리 ${linking.blocked_pairs}쌍 · 대기 ${linking.pending_pairs}쌍</p><p>자동 검토 범위 밖으로 보류한 제목 ${linking.deferred_groups}개. 세 사건 이상이거나 이미 여러 기사를 묶은 사건은 추가 검토가 필요합니다. 제목이 다른 중복까지 찾은 결과가 아닙니다. 원문·분석 이력은 유지하며 연결은 모델 판단으로 검수 전입니다. 새 자료 처리를 우선하며 한 회차에 최대 한 쌍을 추가 검토합니다.${linking.errors?.length ? ' 일부 연결 검토 실패 · 분리 상태로 재시도 대기' : ''}</p></div>`;
  const timings = ai?.usage?.timings || [];
  $('#source-view').innerHTML += `<div class="source-detail"><h3>모델 요청 대기 시간</h3>${timings.length ? timings.map(t=>`<p>${escape(({read:'본문 읽기',screen:'적합성 검토',rank:'순위 검토',link:'사건 연결 검토'})[t.task] || t.task)} · 표본 ${escape(t.samples)}회 · p50 ${escape(latencyText(t.p50_seconds))} · p95 ${escape(latencyText(t.p95_seconds))} · 요청·수신 오류 ${escape(t.failed)}회 · ${t.response_checked ? `응답 JSON·완료 확인 ${escape(t.response_checked)}회 중 오류 ${escape(t.response_failed)}회` : '응답 JSON·완료 확인 미측정'}</p>`).join('') : '<p>측정 표본을 모으는 중입니다.</p>'}<p>같은 모델의 최근 측정 요청 최대 100회입니다. 요청부터 응답 수신까지 서버 대기·통신 시간을 포함하며, 실패한 요청도 측정합니다. JSON 해석·완료 확인은 원문·분석 스키마 검증과 별개이며 이전 기록은 미측정으로 남깁니다. 분석 정확도나 전체 처리 시간을 뜻하지 않습니다.</p></div>`;
  renderList();
  renderMarket();
}
function timingCheckHTML(item) {
  return item?.timing_original ? `<p class="detail-meta">원문에서 대조하지 못한 모델 시점: ${escape(item.timing_original)} · 사건 시점은 미확인으로 표시했습니다.</p>` : '';
}
let businessData=null,businessRequest=0,businessError='',businessLoading=false;
function businessHTML(result) {
  if(!result) return '<p>사업 근거를 확인하고 있습니다.</p>';
  return `<p>기준 ${escape(result.as_of)} · 기업 ${escape(result.unique_issuers)}개 · 증권 ${escape(result.unique_securities)}개</p>${result.themes.map(t=>`<section class="source-detail"><h2>${escape(t.name)}</h2><details class="theme-criteria"><summary>어떤 기업이 포함되나요?</summary><p>포함: ${escape(t.include)}<br>제외: ${escape(t.exclude)}</p></details><p>국내 ${escape(t.countries.KR)}개 · 미국 ${escape(t.countries.US)}개</p><div class="stock-chips">${result.memberships.filter(m=>m.theme===t.id).map(m=>`<button class="stock-chip" data-business-code="${escape(m.code)}" aria-label="${escape(m.security.name)} 사업 근거">${escape(m.security.name)}<span aria-hidden="true"> →</span></button>`).join('') || '<p>해당 기준일의 검토 근거가 없습니다.</p>'}</div></section>`).join('')}`;
}
async function loadBusiness() {
  if(mode!=='live') return;
  const request=++businessRequest;businessLoading=true;businessError='';render();
  try {
    const response=await fetch('/api/business?'+new URLSearchParams({as_of:$('#business-asof').value || ''}),{signal:AbortSignal.timeout(15000)});
    if(!response.ok) throw new Error();
    const result=await response.json();
    if(request!==businessRequest) return;
    businessData=result;businessLoading=false;render();
  } catch {
    if(request===businessRequest) {businessLoading=false;businessData=null;businessError='기준일 근거 조회 실패 · 최신 자료로 대신하지 않습니다.';render();}
  }
}
async function openBusiness(code) {
  if(mode!=='live') return;
  const request=++historyRequest;detailId=null;
  $('#detail').innerHTML='<div class="detail-top"><h2 id="detail-title">사업 근거 조회</h2><button data-close aria-label="상세 닫기">×</button></div>';
  $('#detail-dialog').showModal();
  try {
    const response=await fetch('/api/business?'+new URLSearchParams({code,as_of:$('#business-asof').value || ''}),{signal:AbortSignal.timeout(15000)});
    if(!response.ok) throw new Error();
    const result=await response.json();
    if(request!==historyRequest || !$('#detail-dialog').open) return;
    $('#detail').innerHTML=`<div class="detail-top"><h2 id="detail-title">${escape(result.memberships[0]?.security.name || code)} · 사업 근거</h2><button data-close aria-label="상세 닫기">×</button></div><div class="detail-content"><button data-supply-code="${escape(code)}">이 종목의 공급·계약 근거</button>${result.memberships.map(m=>`<section class="detail-overview"><h3>${escape(m.activity)}</h3><p>${escape(m.subject.name)} · ${escape(m.security.instrument)} · ${escape(m.issuer_path || '발행사 사업 노출')}</p><p>${escape(m.claim_status)} · ${escape(m.validity_note || '')}</p>${m.evidence.map(s=>`<details><summary>${escape(s.title)}</summary><p>${s.excerpt_type==='source_fragment' ? '원문 구절' : '검토된 사업 요약'}: ${escape(s.excerpt)}</p><p>공개 ${escape(s.published_on || '미확인')} · 검토 ${escape(s.checked_on)}</p>${safeLink(s.url) ? `<a href="${escape(safeLink(s.url))}" target="_blank" rel="noopener noreferrer">출처 ↗</a>` : ''}</details>`).join('')}</section>`).join('') || '<p>기준일에 확인 가능한 소속이 없습니다.</p>'}</div>`;
  } catch {if(request===historyRequest) $('#detail').innerHTML='<div class="detail-top"><h2 id="detail-title">조회 실패</h2><button data-close aria-label="상세 닫기">×</button></div><p>사업 근거를 확인할 수 없습니다.</p>';}
}
function supplyHTML(result) {
  if(result.version==='legacy') return '<p>원본 사전 모드 · 제품·기간 검증 미적용</p>';
  return `<p>기준 ${escape(result.as_of)} · ${escape(result.version)} · 개별 사건의 손익 영향 미산정</p>${result.claims.map(c=>`<section class="detail-overview"><h3>${escape(c.parties.map(p=>p.entity+' ('+p.role+')').join(' ↔ '))}</h3><dl class="event-facts">${[['제품',c.product],['세대',c.generation || '미확인'],['발표 단계',c.status],['종류',c.kind],['이번 사건 연결',c.event_link_status==='blocked' ? '차단' : '조건부']].map(([k,v])=>`<div><dt>${escape(k)}</dt><dd>${escape(v)}</dd></div>`).join('')}</dl><p>${escape(c.note)}</p><p>${escape([...c.blocked_reasons,...c.required_checks].join(' · '))}</p>${c.evidence.map(s=>`<details><summary>${escape(s.title)}</summary><blockquote>${escape(s.excerpt)}</blockquote><p>공개 ${escape(s.published_on || '미확인')} · 검토 ${escape(s.checked_on)}</p>${safeLink(s.url) ? `<a href="${escape(safeLink(s.url))}" target="_blank" rel="noopener noreferrer">원출처 ↗</a>` : ''}</details>`).join('')}</section>`).join('') || '<p>검토된 거래 경로가 없습니다.</p>'}`;
}
async function openSupply(code='') {
  if(mode!=='live') return;
  const request=++historyRequest;detailId=null;
  $('#detail').innerHTML='<div class="detail-top"><h2 id="detail-title">공급·계약 근거</h2><button data-close aria-label="상세 닫기">×</button></div>';
  $('#detail-dialog').showModal();
  try {
    const params=new URLSearchParams({as_of:$('#business-asof').value || ''});if(code) params.set('code',code);
    const response=await fetch('/api/supply?'+params,{signal:AbortSignal.timeout(15000)});
    if(!response.ok) throw new Error();
    const result=await response.json();
    if(request!==historyRequest || !$('#detail-dialog').open) return;
    $('#detail').innerHTML=`<div class="detail-top"><h2 id="detail-title">공급·계약 근거</h2><button data-close aria-label="상세 닫기">×</button></div><div class="detail-content">${supplyHTML(result)}</div>`;
  } catch {if(request===historyRequest) $('#detail').innerHTML='<div class="detail-top"><h2 id="detail-title">조회 실패</h2><button data-close aria-label="상세 닫기">×</button></div><p>관계 근거를 확인할 수 없습니다.</p>';}
}
function historyQualityHTML(history) {
  const labels={complete:'요청 구간 수집 완료',partial:'추가 수집 필요',error:'수집 오류',running:'진행 중'};
  return `<section class="source-detail"><h3>과거 시세 · 토스증권</h3><p>${history.configured ? '인증 설정 있음 · 실제 수집 상태는 아래에서 확인' : '연결 대기 · API 설정 필요'}</p><p>${escape(history.usage)}</p>${(history.series || []).map(s=>`<div class="source-detail"><h4>${escape(s.market)} · ${escape(s.symbol)} · ${s.adjusted ? '수정주가' : '원시 가격'}</h4><p>${escape(s.first)} ~ ${escape(s.last)} · ${escape(s.days)}거래일 · ${escape(s.versions)}개 관측 버전</p><p>캘린더 확인 ${escape(s.calendar_days_checked)}일 · 확인된 개장일 중 가격 누락 ${escape(s.missing_open_days?.length ?? '미확인')}일${s.calendar_source_conflicts ? ' · 거래소 자료와 일정 상충 '+escape(s.calendar_source_conflicts)+'일' : ''}</p><button data-history-market="${escape(s.market)}" data-history-symbol="${escape(s.symbol)}" data-history-adjusted="${s.adjusted ? 'true' : 'false'}">보관 일봉·출처 보기</button></div>`).join('') || '<p>아직 보관한 과거 시세가 없습니다.</p>'}${(history.jobs || []).map(j=>`<p>${escape(j.market)} ${escape(j.symbol)} ${escape(j.since)} ~ ${escape(j.until)}: ${escape(labels[j.status] || '미확인')} · 개장일 가격 누락 ${escape(j.missing_open_days?.length ?? '미확인')}일 · 캘린더 미확인 ${escape(j.calendar_unknown_days ?? '미확인')}일${j.error ? ` · ${escape(j.error)}` : ''}</p>`).join('')}<p class="detail-meta">거래대금·과거 거래정지·기업행동 이력은 미확보입니다. 미국 지수 원자료와 장중 반응 통계는 미지원입니다. SPY를 수집한 경우 미국 지수 자체가 아닌 ETF 비교 자료입니다.</p></section>`;
}
let historyRequest=0;
async function openHistory(market,symbol,adjusted) {
  const request=++historyRequest;
  detailId=null;
  $('#detail').innerHTML='<div class="detail-top"><h2 id="detail-title">과거 시세</h2><button data-close aria-label="상세 닫기">×</button></div><p>보관 자료 조회 중</p>';
  $('#detail-dialog').showModal();
  try {
    const response=await fetch('/api/history?'+new URLSearchParams({market,symbol,adjusted}),{signal:AbortSignal.timeout(15000)});
    if(!response.ok) throw new Error('조회 실패');
    const result=await response.json();
    if(request!==historyRequest || !$('#detail-dialog').open) return;
    $('#detail').innerHTML=`<div class="detail-top"><h2 id="detail-title">${escape(market)} ${escape(symbol)} · 보관 일봉</h2><button data-close aria-label="상세 닫기">×</button></div><div class="detail-content"><p>정규화 기준 ${escape(result.coverage.policy_version)} · 가격은 원문 소수값 그대로 표시합니다.</p><table><caption>최근 최대 400거래일 · API 응답으로 원문 추적</caption><thead><tr><th>거래일</th><th>종가</th><th>거래량</th><th>출처</th></tr></thead><tbody>${result.observations.map(r=>`<tr><td>${escape(r.day)}${r.completion==='provisional' ? ' · 미완료 가능' : ''}</td><td>${escape(r.closePrice)} ${escape(r.currency)}</td><td>${escape(r.volume)}</td><td><a href="/api/history?response_id=${encodeURIComponent(r.response_id)}" target="_blank" rel="noopener noreferrer">원문 #${escape(r.response_id)}</a></td></tr>`).join('')}</tbody></table></div>`;
  } catch {
    if(request===historyRequest && $('#detail-dialog').open) $('#detail').innerHTML='<div class="detail-top"><h2 id="detail-title">조회 실패</h2><button data-close aria-label="상세 닫기">×</button></div><p>보관 시세를 확인할 수 없습니다. 이전 시세나 0으로 대신하지 않습니다.</p>';
  }
}
function eventHistoryHTML(event) {
  if (!event?.history?.length) return '';
  return `<section class="detail-block"><h3>기사·사건 이력 ${event.history.length}건</h3>${event.link_reviewed_at && event.linked_event_ids?.length>1 ? `<p class="detail-meta">연결 재검토 ${escape(dateTime(event.link_reviewed_at))} · 같은 제목의 별도 사건을 모델이 연결했습니다. 검수 전이며 원문별 분석과 최초 발행 시각은 보존합니다.</p>` : ''}<p class="detail-meta">보관된 분석 버전 중 최근 최대 10건입니다. 본문 변경이 사실의 정정이나 별도 사건을 뜻하는지는 원문 확인이 필요합니다.</p><ol class="event-history">${event.history.map(item=>`<li><time>${escape(item.assessment_review ? (item.reviewed_at ? dateTime(item.reviewed_at) : '검토 시각 미확인') : dateTime(item.analyzed_at))}</time><strong>${escape(item.event_title || item.summary)}</strong><p>${escape(item.summary)}</p>${item.stock_relevance ? `<p class="detail-meta">판정: ${escape(item.stock_relevance)}${item.assessment_reason ? ` · ${escape(item.assessment_reason)}` : ''}</p>` : ''}<div class="article-tags">${item.assessment_review ? '<span class="tag">분석 기준 재검토</span>' : ''}<span class="tag">${escape(item.certainty || '미확인')}</span><span class="tag">${escape(item.amount || '규모 미확인')}</span><span class="tag">${escape(item.timing || '시점 미확인')}</span></div>${timingCheckHTML(item)}${safeLink(item.source_url) ? `<a class="reading-source" href="${escape(safeLink(item.source_url))}" target="_blank" rel="noopener noreferrer">해당 기사 ↗</a>` : ''}</li>`).join('')}</ol></section>`;
}
function articleSummaryHTML(article) {
  const evidence=article.evidence;
  if(evidence && evidence.rule_version!=='article-evidence-v1') return evidenceHTML(evidence);
  const event=eventFor(article);
  // A stored body may belong to an earlier title; keep that uncertainty beside the excerpt.
  const assessment=(data?.intelligence?.assessments || []).find(item=>item.event_id===event?.event_id);
  const proof=impactEvidence(event,assessment);
  const excerpt=evidence?.body_excerpt || proof || event?.summary;
  const text=excerpt ? String(excerpt).slice(0,180) : '';
  const structured=article.structured_event;
  const stages={planned:'계획·검토',mou:'업무협약',announced:'발표',approved:'승인',execution:'실행',cancelled:'취소',denied:'부인',deferred:'유예',exempt:'예외'};
  const facts=structured ? [['진행 상황',stages[structured.stage]],['기사 속 금액',(structured.amounts || []).map(v=>v.raw).join(' · ')]] : [['규모',event?.amount],['시점',event?.timing]];
  return `<section class="news-summary"><h3>${evidence ? '본문 미리보기' : proof ? '원문 근거' : '핵심 내용'}</h3>${text ? `<p>${escape(text)}${excerpt.length>180 ? '…' : ''}</p><small>${evidence ? '현재 제목과 본문이 일치하는지 원문에서 확인해 주세요.' : proof ? '기사에서 확인한 구절' : '모델 요약 · 검수 전'}</small>` : '<p>요약이 아직 없어요. 원문에서 내용을 확인해 주세요.</p>'}${facts.some(([,value])=>value && value!=='미확인') ? `<dl class="event-facts">${facts.filter(([,value])=>value && value!=='미확인').map(([label,value])=>`<div><dt>${label}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl>` : ''}${assessment?.watch_for ? `<p class="next-check-line"><strong>다음 확인 · 모델 제안</strong> ${escape(assessment.watch_for)}</p>` : ''}</section>`;
}
function renderDetail(id) {
  const a = findArticle(id); if (!a) return;
  detailId = id;
  const related = (data?.articles || []).filter(b=>b.id !== id && b.themes.some(t=>a.themes.some(at=>at.id === t.id))).slice(0,3);
  const link = safeLink(a.url), selectedFeedback = feedback[`${mode}:${id}`];
  const e = eventFor(a);
  const assessment=(data?.intelligence?.assessments || data?.intelligence?.ranking)?.find(r=>r.event_id===e?.event_id);
  const rankReason=data?.intelligence?.ranking?.find(r=>r.event_id===e?.event_id)?.reason;
  const reasons=[...new Set((data?.intelligence?.rank_reason_source==='article_evidence' ? [assessment?.screen_reason] : [rankReason,assessment?.reason]).filter(reason=>typeof reason==='string' && reason.trim()))];
  const modelNote=impactEvidence(e,assessment) && reasons.length ? `<section class="detail-block"><h3>모델 선별 설명 · 검수 전</h3>${reasons.map(reason=>`<p>${escape(reason)}</p>`).join('')}</section>` : '';
  $('#detail').innerHTML = `<div class="detail-top"><span>${mode === 'demo' ? '가상 자료 · 기능 체험' : '뉴스 상세'}</span><button data-close aria-label="상세 닫기">×</button></div><div class="detail-content"><div class="detail-meta">${escape(a.source)} · ${a.timestamp_basis==='portal_display' ? '포털 표시 ' : ''}${escape(dateTime(a.published_at))}</div><h2 id="detail-title">${escape(a.title)}</h2>${articleSummaryHTML(a)}<section class="detail-stocks"><div class="overview-heading"><h3>관련 종목의 움직임</h3></div><div id="price-movement">${stocksHTML(a)}</div><p id="price-movement-status" class="panel-description">${mode==='demo' ? '예시 화면에서는 실제 시세를 추적하지 않아요.' : '뉴스 이후 시세를 확인하고 있어요.'}</p></section><details class="detail-more"><summary>근거와 자세한 정보</summary><div class="detail-more-content">${readingHTML(a)}${modelNote}${e ? `<section class="detail-block model-reading"><h3>판단의 원문 근거</h3>${timingCheckHTML(e)}${e.articles.map(item=>`<blockquote>${(item.evidence || []).map(escape).join(' / ')}</blockquote>${safeLink(item.url) ? `<a class="reading-source" href="${escape(safeLink(item.url))}" target="_blank" rel="noopener noreferrer">근거 원문 ↗</a>` : ''}`).join('')}<p class="detail-meta">${escape(e.model)} · 분석 ${escape(dateTime(e.analyzed_at))} · 동일 사건 ${e.articles.length}건${e.body_truncated ? ' · 본문 일부 분석' : ''} · 공개 추출 본문 분석이며 전문 전체를 보장하지 않습니다.</p></section>` : ''}${eventHistoryHTML(e)}${stockAnalysisHTML(a)}<section class="detail-block"><h3>제목에서 찾은 맥락</h3><p>${escape(a.reason)}</p><div class="article-tags">${a.themes.map(t=>`<span class="tag">${escape(t.name)}</span>`).join('')}</div><p class="detail-meta">주제·관련주 연결은 제목과 공개 사업 근거 기반입니다. 별도 본문 분석도 근거 범위 내의 모델 해석이며 사실 검증을 완료한 결과는 아닙니다.</p></section><section class="detail-block"><h3>최신성 점수 · 주식 영향순과 별도</h3><p>${(a.score_parts?.relevance !== undefined || a.score_parts?.report !== undefined) ? '이전 선별 기준으로 저장된 자료입니다. 현재 기준 점수는 최신 목록에서 확인해 주세요.' : `최신성 ${a.score_parts?.freshness ?? a.score ?? '미확인'}점 (추가 가점 없음)`}</p><p>점수는 읽을 순서를 위한 시제품 규칙이며 투자 가치나 사실 신뢰도 점수가 아닙니다.</p></section>${related.length ? `<section class="detail-block"><h3>함께 비교할 자료</h3>${related.map(b=>`<button class="related-link" data-detail="${escape(b.id)}">${escape(b.title)}<small>${escape(b.source)} · 같은 주제 키워드</small></button>`).join('')}</section>` : ''}</div></details><div class="detail-bottom">${link ? `<a class="primary-button" href="${escape(link)}" target="_blank" rel="noopener noreferrer">원문 보기 ↗</a>` : '<span class="saved-note">가상 예시 · 실제 원문 없음</span>'}<div class="feedback"><span>도움이 됐나요?</span><button data-feedback="useful" class="${selectedFeedback === 'useful' ? 'selected' : ''}">도움돼요</button><button data-feedback="irrelevant" class="${selectedFeedback === 'irrelevant' ? 'selected' : ''}">관련 적음</button></div></div></div>`;
  loadQuotes();
  movementRequest++;movementLoading=false;loadPriceMovement(id);
}
let timelineCode='', timelineRequest=0, timelineBusy=false, timelineData=null, chartArticle='';
function timelineHTML(result,code) {
  const points=(result.points || []).filter(p=>Number.isFinite(p.at) && Number.isFinite(p.price) && p.price>0);
  if(points.length<2)return '<p>장중 차트에 표시할 관측을 수집하고 있어요.</p>';
  const first=points[0].at,last=points.at(-1).at;
  if(last<=first)return '<p>다음 거래 시세를 기다리고 있어요.</p>';
  const lo=Math.min(...points.map(p=>p.price)),hi=Math.max(...points.map(p=>p.price));
  const x=at=>8+344*(at-first)/(last-first),y=price=>hi===lo ? 48 : 88-80*(price-lo)/(hi-lo);
  const path=points.map((p,i)=>`${i && p.at-points[i-1].at<=90?'L':'M'}${x(p.at)},${y(p.price)}`).join(' ');
  const articles=allArticles().filter(a=>a.related_stocks?.some(s=>s.code===code)).sort((a,b)=>(Date.parse(b.published_at)||0)-(Date.parse(a.published_at)||0)).slice(0,8);
  const chosen=articles.find(a=>a.id===chartArticle);
  const marker=a=>Date.parse(a.published_at)/1000;
  const markers=articles.filter(a=>Number.isFinite(marker(a)) && marker(a)>=first && marker(a)<=last);
  return `<h3>장중 가격과 뉴스</h3><svg class="movement-chart" viewBox="0 0 360 96" role="img" aria-label="실제 관측 가격과 기사 표시 시각"><path d="${path}" fill="none" stroke="currentColor" stroke-width="2"/>${markers.map(a=>`<line x1="${x(marker(a))}" x2="${x(marker(a))}" y1="0" y2="96" stroke="${a.id===chartArticle?'#1761c5':'#7b8592'}" stroke-dasharray="3 3"><title>${escape(a.title)} · ${a.timestamp_basis==='portal_display'?'포털 표시':'기사 시각'}</title></line>`).join('')}</svg><p class="panel-description">${escape(quoteTime(new Date(first*1000).toISOString()))} ~ ${escape(quoteTime(new Date(last*1000).toISOString()))} · 저장된 관측 최대 500개 · 빈 구간은 연결하지 않아요.</p>${articles.map(a=>`<button class="related-link" data-chart-news="${escape(a.id)}" aria-pressed="${a.id===chartArticle}">${escape(a.title)}<small>${escape(dateTime(a.published_at))} · ${a.timestamp_basis==='portal_display'?'포털 표시':'기사 시각'}${!markers.includes(a)?' · 차트 구간 밖 또는 시각 미확인':''}</small></button>`).join('') || '<p>연결된 최근 기사가 없어요.</p>'}${chosen && safeLink(chosen.url)?`<a href="${escape(safeLink(chosen.url))}" target="_blank" rel="noopener noreferrer">선택한 기사 원문 보기 ↗</a>`:''}`;
}
async function loadTimeline() {
  if(mode!=='live' || timelineBusy || !$('#stock-dialog').open || !timelineCode)return;
  const code=timelineCode,request=++timelineRequest;timelineBusy=true;
  try {
    const response=await fetch('/api/stock-timeline?code='+encodeURIComponent(code),{signal:AbortSignal.timeout(10000)});
    if(!response.ok)throw new Error();
    const result=await response.json();
    if(request!==timelineRequest || code!==timelineCode || !$('#stock-dialog').open)return;
    timelineData=result;const target=$('#stock-timeline');
    const focused=document.activeElement?.dataset?.chartNews;
    target.innerHTML=timelineHTML(result,code);
    if(focused)[...target.querySelectorAll('[data-chart-news]')].find(b=>b.dataset.chartNews===focused)?.focus({preventScroll:true});
  } catch {if(request===timelineRequest && $('#stock-dialog').open)$('#stock-timeline').textContent='차트를 갱신하지 못했어요. 다음 조회에서 다시 확인해요.';}
  finally {timelineBusy=false;}
}
function openStock(articleId, code) {
  const article = articleId==='market-watch' ? {id:articleId,title:'장중 종목 비교',related_stocks:marketRows().flatMap(c=>c.stocks).map(s=>({...s,relation:'theme',reason:'추적 중인 테마 소속 · 기사 직접 영향 미판정'}))} : findArticle(articleId);
  const stock = article?.related_stocks?.find(s=>s.code === code);
  if (!stock) return;
  $('#stock-detail').innerHTML = `<div class="detail-top"><span>관련 주식 상세</span><button data-close-stock aria-label="주식 상세 닫기">×</button></div><div class="detail-content"><h2 id="stock-title">${escape(stock.name)}</h2><p class="detail-meta">${escape(article.title)}</p>${stocksHTML({...article,related_stocks:[stock]},true)}<button class="text-button" data-theme-statistics="${escape(stock.code)}">같은 테마 종목의 움직임 보기</button></div>`;
  timelineCode=code;timelineRequest++;timelineData=null;chartArticle='';
  $('#stock-detail').innerHTML+='<section id="stock-timeline" class="detail-content" aria-label="장중 차트">차트 관측 확인 중</section>';
  $('#stock-dialog').showModal();
  loadQuotes();loadTimeline();
}
async function load() {
  const current = ++requestId;
  loading = true; $('#refresh').disabled = true;
  try {
    const response = await fetch(mode === 'demo' ? '/api/demo' : '/api/dashboard', {signal:AbortSignal.timeout(15000)});
    if (!response.ok) throw new Error('응답 오류');
    const next = await response.json();
    if (current !== requestId) return;
    data = next; if(marketPreview)loadMarket(); loadFailed=false; lastLoadedAt=new Date().toISOString(); render(); paintQuotes(); loadQuotes(); if(view==='feed' && mode==='live') await loadArchive(); return true;
  } catch {
    if (current !== requestId) return;
    loadFailed=true;
    toast('대시보드를 갱신하지 못했어요. 연결 상태를 확인해 주세요.');
    render();
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
function toggleMode() { document.querySelector('.app-menu')?.removeAttribute?.('open'); mode = mode === 'live' ? 'demo' : 'live'; briefingExpanded=false;loadFailed=false;lastLoadedAt=null;archiveData=null;archiveRequested=false;archiveError='';archiveCursor='';archiveCursors=[]; data = null; theme = ''; query = ''; kind = 'all'; $('#search').value = ''; $('#stock-dialog').close(); $('#detail-dialog').close(); detailId = null; loading = true; render(); load(); }
document.addEventListener('click', event => {
  const button = event.target.closest('button'); if (!button) return;
  if(button.dataset.marketArchive){view='feed';query=button.dataset.marketArchive;$('#search').value=query;render();loadArchive(true);}
  if(button.dataset.chartNews){chartArticle=button.dataset.chartNews;if(timelineData)$('#stock-timeline').innerHTML=timelineHTML(timelineData,timelineCode);}
  if(button.dataset.marketSelect){marketSelection=button.dataset.marketSelect;renderMarket();loadQuotes();}
  if(button.dataset.marketStock)openStock('market-watch',button.dataset.marketStock);
  if(button.dataset.marketRegion && marketRegion!==button.dataset.marketRegion){marketRegion=button.dataset.marketRegion;marketData=null;marketOrder=[];marketSelection='';renderMarket();loadMarket();}
  if(button.hasAttribute('data-market-apply')){marketOrder=(marketData?.candidates || []).map(c=>c.id);if(!marketOrder.includes(marketSelection))marketSelection=marketOrder[0] || '';renderMarket();}
  if (button.dataset.view) { document.querySelector('.app-menu')?.removeAttribute?.('open'); view = button.dataset.view; briefingExpanded=false;theme = ''; kind = 'all'; query = ''; $('#search').value=''; render(); loadArchive(true); }
  if (button.hasAttribute('data-toggle-briefing')) toggleBriefing();
  if (button.dataset.kind) { kind = button.dataset.kind; render(); loadArchive(true); }
  if (button.dataset.theme) { chooseTheme(button.dataset.theme); loadArchive(true); }
  if (button.hasAttribute('data-clear-theme')) { theme = ''; render(); loadArchive(true); }
  if (button.hasAttribute('data-archive-next') && !archiveLoading && archiveData?.next_cursor) {archiveCursors.push(archiveCursor);archiveCursor=archiveData.next_cursor;loadArchive();}
  if (button.hasAttribute('data-archive-prev') && !archiveLoading && archiveCursors.length) {archiveCursor=archiveCursors.pop();loadArchive();}
  if (button.dataset.save) toggleSave(button.dataset.save);
  if (button.dataset.stock) openStock(button.dataset.article, button.dataset.stock);
  if (button.dataset.businessCode) openBusiness(button.dataset.businessCode);
  if (button.hasAttribute('data-supply-all')) openSupply();
  if (button.hasAttribute('data-theme-statistics')) openThemeStatistics(button.dataset.themeStatistics);
  if (button.dataset.reactions) openReactions(button.dataset.reactions);
  if (button.dataset.comparable) openComparable(button.dataset);
  if (button.hasAttribute('data-trade')) openTrade();
  if (button.hasAttribute('data-fx')) openFX();
  if (button.hasAttribute('data-official-rates')) openRateReferences();
  if (button.dataset.supplyCode) openSupply(button.dataset.supplyCode);
  if (button.dataset.historySymbol) openHistory(button.dataset.historyMarket,button.dataset.historySymbol,button.dataset.historyAdjusted);
  if (button.hasAttribute('data-close-stock')) $('#stock-dialog').close();
  if (button.dataset.detail) { renderDetail(button.dataset.detail); if (!$('#detail-dialog').open) $('#detail-dialog').showModal(); }
  if (button.hasAttribute('data-close')) { $('#detail-dialog').close(); detailId=null; }
  if (button.dataset.feedback && detailId) { feedback[`${mode}:${detailId}`] = button.dataset.feedback; persist('maekrak-feedback', feedback); renderDetail(detailId); toast('의견을 이 브라우저에 기록했어요.'); }
  if (button.hasAttribute('data-demo')) toggleMode();
});
$('#mode-button').addEventListener('click',toggleMode);
$('#refresh').addEventListener('click', async()=>{if (await load()) toast('최신 뉴스를 확인했어요.');});
$('#search').addEventListener('input',event=>{query=event.target.value; renderList();clearTimeout(archiveSearchTimer);archiveSearchTimer=setTimeout(()=>loadArchive(true),300);});
for (const [selector,update] of [['#archive-source',v=>archiveSource=v],['#archive-since',v=>archiveSince=v],['#archive-until',v=>archiveUntil=v]]) $(selector).addEventListener('change',event=>{update(event.target.value);loadArchive(true);});
$('#business-asof').addEventListener('change',loadBusiness);
$('#sort').addEventListener('change',event=>{sort=event.target.value; briefingExpanded=false;render();});
$('#detail-dialog').addEventListener('click',event=>{if (event.target === $('#detail-dialog')) { const rect=event.target.getBoundingClientRect(); if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom) {event.target.close();detailId=null;} }});
$('#stock-dialog').addEventListener('click',event=>{if (event.target === $('#stock-dialog')) {const r=event.target.getBoundingClientRect(); if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom) event.target.close();}});
$('#stock-dialog').addEventListener('close',()=>{timelineCode='';timelineRequest++;});
$('#detail-dialog').addEventListener('close',()=>{detailId=null;historyRequest++;movementRequest++;movementLoading=false;});
document.addEventListener('keydown',event=>{if(event.key === '/' && !['INPUT','TEXTAREA'].includes(document.activeElement.tagName) && !$('#detail-dialog').open && !$('#stock-dialog').open) {event.preventDefault(); $('#search').focus();}});
$('#today').textContent=new Date().toLocaleDateString('ko-KR',{year:'numeric',month:'long',day:'numeric',weekday:'short',timeZone:'Asia/Seoul'});
render(); load();
setInterval(()=>{if(mode === 'live' && !document.hidden && !loading) load();},5000);
let quoteScrollTimer;
document.addEventListener('scroll',()=>{clearTimeout(quoteScrollTimer);quoteScrollTimer=setTimeout(loadQuotes,150);},true);
setInterval(()=>{if(mode === 'live' && !document.hidden) {paintQuotes();loadQuotes();loadTimeline();if($('#detail-dialog').open && !$('#stock-dialog').open) loadPriceMovement();}},5000);

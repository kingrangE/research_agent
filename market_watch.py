"""Same-window, issuer-deduplicated market observations; never investment signals."""
import math
import business_ontology
import price_tracking as prices

BENCHMARKS={'KR':('069500','KODEX 200 ETF'),'US':('SPY','SPY ETF')}


def snapshot(market='KR',now=None):
    if market not in BENCHMARKS:raise ValueError('지원하지 않는 시장')
    clock=now or prices.now_text()
    knowledge=business_ontology.snapshot()
    benchmark_code,benchmark_name=BENCHMARKS[market]
    benchmark=prices.recent(benchmark_code,clock)
    members=[m for m in knowledge['memberships'] if m['kind']=='business' and m['security']['country']==market]
    securities={m['code']:m['security'] for m in members}
    observations={code:prices.recent(code,clock) for code in securities}
    groups=[]
    for theme in knowledge['themes']:
        issuers={}
        for m in sorted(members,key=lambda m:m['code']):
            if m['theme']==theme['id']:issuers.setdefault(m['security']['issuer_id'],m['code'])
        if not issuers:continue
        rows=[{**securities[code],'recent':observations[code]} for code in issuers.values()]
        valid=[r['recent']['change_percent'] for r in rows if r['recent']['status']=='ok']
        count=len(valid);total=len(rows)
        mean=math.fsum(valid)/count if count else None
        eligible=count>=2 and count/total>=.75
        difference=mean-benchmark['change_percent'] if eligible and benchmark['status']=='ok' else None
        groups.append({'id':theme['id'],'name':theme['name'],'stocks':rows,'tracked':total,'observed':count,
                       'up':sum(x>0 for x in valid),'down':sum(x<0 for x in valid),'flat':sum(x==0 for x in valid),
                       'mean_percent':mean,'market_difference_pp':difference,'eligible':eligible})
    return {'market':market,'as_of':clock,'membership_version':knowledge['version'],
            'benchmark':{'code':benchmark_code,'name':benchmark_name,'proxy':True,'recent':benchmark},
            'tracked':len(securities),'themes':groups,'scope':'등록 종목만 추적 · 전체 시장 아님'}


def candidates(result):
    """Descriptive initial policy; thresholds require separate replay/user validation."""
    choices=[]
    benchmark=result['benchmark']['recent']
    if benchmark['status']!='ok':return choices
    for group in result['themes']:
        mean=group['mean_percent'];difference=group['market_difference_pp']
        if not group['eligible'] or difference is None or abs(mean)<.2 or abs(difference)<.3:continue
        agreeing=group['up'] if mean>0 else group['down']
        if agreeing/group['observed']<.75:continue
        choices.append({**group,'kind':'theme','reason':f"같은 시간 {result['benchmark']['name']} {benchmark['change_percent']:+.2f}%",'strength':abs(difference)})
    for group in result['themes']:
        for stock in group['stocks']:
            recent=stock['recent'];change=recent['change_percent']
            if recent['status']!='ok' or abs(change)<.2:continue
            difference=change-benchmark['change_percent']
            if abs(difference)<.3:continue
            choices.append({'id':'stock:'+stock['code'],'kind':'stock','name':stock['name'],'stocks':[stock],
                            'mean_percent':change,'market_difference_pp':difference,'tracked':1,'observed':1,
                            'up':int(change>0),'down':int(change<0),'reason':f"같은 시간 {result['benchmark']['name']} {benchmark['change_percent']:+.2f}%",'strength':abs(difference)})
    picked=[];covered=set()
    for item in sorted(choices,key=lambda c:(-c['strength'],c['kind']!='theme',c['id'])):
        codes={s['code'] for s in item['stocks']}
        if len(codes&covered)/len(codes)>.5:continue
        picked.append(item);covered.update(codes)
        if len(picked)==5:break
    return picked

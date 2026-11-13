"""Bounded Npay news sweeps shared by the persistent worker and Airflow."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import fcntl
from hashlib import sha256
from html import unescape
import json
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import archive

KST=timezone(timedelta(hours=9))
PAGE_SIZE=15
LIST_URL='https://stock.naver.com/api/domestic/news/list'


def today():
    return datetime.now(KST).date()


@contextmanager
def lease(name,wait_seconds=0):
    # Local shared-volume deployment; use a distributed lease before adding hosts.
    archive.PATH.parent.mkdir(parents=True,exist_ok=True)
    with (archive.PATH.parent/name).open('a') as lock:
        deadline=time.monotonic()+wait_seconds
        while True:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic()>=deadline:
                    yield False
                    return
                time.sleep(.2)
        try:
            yield True
        finally:
            fcntl.flock(lock,fcntl.LOCK_UN)


def status(day=None):
    with archive.db() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS news_collection (
            day TEXT PRIMARY KEY,next_page INTEGER NOT NULL DEFAULT 1,
            last_success TEXT,complete_at TEXT,last_error TEXT,failures INTEGER NOT NULL DEFAULT 0,
            retry_after REAL NOT NULL DEFAULT 0)''')
        row=db.execute('SELECT * FROM news_collection WHERE day=?',(day or today().isoformat(),)).fetchone()
    return dict(zip(('day','next_page','last_success','complete_at','last_error','failures','retry_after'),row)) if row else {'day':day or today().isoformat(),'next_page':1,'failures':0,'retry_after':0}


def fetch_page(day,page):
    url=LIST_URL+'?'+urlencode({'category':'FLASHNEWS','date':day.replace('-',''),'page':page,'pageSize':PAGE_SIZE})
    request=Request(url,headers={'User-Agent':'MaekrakPrototype/0.1 (public news reader)','Accept':'application/json'})
    with urlopen(request,timeout=15) as response:
        raw=response.read(2_000_001)
    if len(raw)>2_000_000:
        raise ValueError('기사 목록 크기 제한 초과')
    value=json.loads(raw)
    if not isinstance(value,dict) or not isinstance(value.get('articles'),list):
        raise ValueError('기사 목록 응답 구조 변경')
    rows=value['articles']
    if value.get('isFirstDate') is False:
        previous=value.get('date','')
        if not isinstance(previous,str) or not re.fullmatch(r'\d{8}',previous) or previous>=day.replace('-','') or len(rows)>PAGE_SIZE*2:
            raise ValueError('기사 날짜 경계 응답 오류')
        previous=datetime.strptime(previous,'%Y%m%d').date().isoformat()
        if any(not isinstance(r,dict) or str(r.get('datetime',''))[:10] not in (day,previous) for r in rows):
            raise ValueError('기사 날짜 경계 밖의 항목')
        rows=[r for r in rows if r['datetime'][:10]==day]
    if len(rows)>PAGE_SIZE:
        raise ValueError('기사 목록 페이지 크기 변경')
    return rows


def parse_articles(rows,day):
    articles=[]
    for row in rows:
        office,article=row.get('officeId'),row.get('articleId')
        if not isinstance(office,str) or not re.fullmatch(r'\d{3}',office) or not isinstance(article,str) or not re.fullmatch(r'\d{10}',article):
            raise ValueError('포털 기사 식별자 오류')
        title=row.get('title');source=row.get('officeHname')
        if not isinstance(title,str) or not title.strip() or not isinstance(source,str) or not source:
            raise ValueError('포털 기사 필수 항목 누락')
        published=datetime.strptime(row['datetime'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=KST)
        if published.date().isoformat()!=day:
            raise ValueError('요청 날짜 밖의 기사 응답 · 날짜 대조 필요')
        url=f'https://n.news.naver.com/article/{office}/{article}'
        articles.append({'id':sha256(url.encode()).hexdigest()[:16],'url':url,'title':unescape(title),
            'source':source,'source_id':'naver','category':'포털 증권 속보','kind':'news',
            'published_at':published.isoformat(),'timestamp_basis':'portal_display',
            'collected_at':datetime.now(timezone.utc).isoformat(),'copies':1,'portal_id':office+':'+article,
            'description':unescape(row.get('subcontent') or '')})
    return articles


def record_failure(day,state,error):
    failures=state['failures']+1
    delay=min(900,30*2**min(failures-1,5))
    if isinstance(error,HTTPError) and error.code in (403,429):
        delay=max(delay,900)
        retry=error.headers.get('Retry-After','') if error.headers else ''
        if retry.isdigit():delay=max(delay,int(retry))
        elif retry:
            try:delay=max(delay,parsedate_to_datetime(retry).timestamp()-time.time())
            except (ValueError,TypeError,OverflowError):pass
    with archive.db() as db:
        db.execute('''INSERT INTO news_collection(day,last_error,failures,retry_after) VALUES(?,?,?,?)
            ON CONFLICT(day) DO UPDATE SET last_error=excluded.last_error,failures=excluded.failures,retry_after=excluded.retry_after''',
            (day,f'{type(error).__name__}: {str(error)[:200]}',failures,time.time()+delay))


def collect_day(day=None,page_budget=3,wait_seconds=0,latest_on_busy=False):
    day=day or today().isoformat()
    datetime.strptime(day,'%Y-%m-%d')
    if not 1<=page_budget<=100:
        raise ValueError('페이지 예산은 1~100')
    with lease('news-collection.lock',wait_seconds) as acquired:
        state=status(day)
        if not acquired:
            if not latest_on_busy:
                return {'status':'busy','day':day}
            if state['retry_after']>time.time():
                return {'status':'backoff',**state}
            try:
                articles=parse_articles(fetch_page(day,1),day)
                with archive.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    archive.store(articles,db)
                    db.execute('''INSERT INTO news_collection(day,last_success) VALUES(?,?)
                        ON CONFLICT(day) DO UPDATE SET last_success=excluded.last_success''',(day,datetime.now(timezone.utc).isoformat()))
                return {'status':'latest_only','day':day,'observed':len(articles)}
            except Exception as error:
                record_failure(day,state,error)
                raise
        if state['retry_after']>time.time():
            return {'status':'backoff',**state}
        page=1;count=0;cursor=state['next_page']
        try:
            for _ in range(page_budget):
                articles=parse_articles(fetch_page(day,page),day)
                done=len(articles)<PAGE_SIZE
                next_page=1 if done else max(2,cursor) if page==1 else page+1
                stamp=datetime.now(timezone.utc).isoformat()
                with archive.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    archive.store(articles,db)
                    db.execute('''INSERT INTO news_collection(day,next_page,last_success,complete_at) VALUES(?,?,?,?)
                        ON CONFLICT(day) DO UPDATE SET next_page=excluded.next_page,last_success=excluded.last_success,
                        complete_at=coalesce(excluded.complete_at,complete_at),last_error=NULL,failures=0,retry_after=0''',
                        (day,next_page,stamp,stamp if done else None))
                count+=len(articles)
                if done:
                    return {'status':'complete','day':day,'observed':count}
                page=next_page
                time.sleep(1)
            return {'status':'partial','day':day,'observed':count,'next_page':page}
        except Exception as error:
            record_failure(day,state,error)
            raise


def reconcile(days=2,page_budget=30):
    current=today().isoformat()
    status(current)
    with archive.db() as db:
        backlog=[r[0] for r in db.execute('SELECT day FROM news_collection WHERE day<? AND (next_page>1 OR complete_at IS NULL OR last_error IS NOT NULL) ORDER BY day',(current,))]
    dates=list(dict.fromkeys([current,*backlog,*[(today()-timedelta(days=i)).isoformat() for i in range(1,days)]]))[:days]
    results=[collect_day(day,page_budget,wait_seconds=10) for day in dates]
    if any(r['status']!='complete' for r in results):
        raise RuntimeError('보충 구간 미완료 · 저장 위치에서 재실행: '+json.dumps(results,ensure_ascii=False))
    return results


def run_worker(interval=10):
    if interval<5:
        raise ValueError('확인 간격은 최소 5초')
    with lease('news-worker.lock') as acquired:
        if not acquired:
            raise RuntimeError('상시 뉴스 작업자가 이미 실행 중')
        while True:
            started=time.monotonic()
            try:
                print(json.dumps(collect_day(latest_on_busy=True),ensure_ascii=False),flush=True)
            except Exception as error:
                print(f'수집 실패 · 저장 위치 유지: {type(error).__name__}',flush=True)
            time.sleep(max(1,interval-(time.monotonic()-started)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['worker','once','reconcile'])
    parser.add_argument('--interval',type=int,default=10)
    parser.add_argument('--date')
    parser.add_argument('--pages',type=int,default=30)
    args=parser.parse_args()
    if args.mode=='worker':run_worker(args.interval)
    else:print(json.dumps(collect_day(args.date,args.pages) if args.mode=='once' else reconcile(page_budget=args.pages),ensure_ascii=False))

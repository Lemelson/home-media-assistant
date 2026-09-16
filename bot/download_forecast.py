"""Per-film measured history and deliberately approximate pre-download forecasts."""
import math
import statistics
import time


def observe(record, torrent, now):
    total=max(0,int(torrent.get('sizeWhenDone') or torrent.get('totalSize') or 0))
    done=max(0,total-int(torrent.get('leftUntilDone',total)))
    quality=torrent.get('quality',{})
    record.setdefault('started',now)
    record.update(updated=now,size=total,name=torrent.get('name',''))
    for source,target in (('addedDate','added_at'),('doneDate','finished_at'),('secondsDownloading','client_download_seconds'),('downloadedEver','client_downloaded_bytes')):
        if torrent.get(source,0)>0:record[target]=torrent[source]
    if record.get('client_download_seconds',0)>0 and record.get('client_downloaded_bytes',0)>0:
        record['client_average_speed']=record['client_downloaded_bytes']/record['client_download_seconds']
    for key in ('seeders','leechers'):
        if key in quality:record.setdefault(key,quality[key])
        if torrent.get(key) is not None:
            record.setdefault(key,torrent[key])
            record['latest_'+key]=torrent[key]
    previous=record.pop('last',None)
    running=torrent.get('status')==4 and not torrent.get('errorString') and not torrent.get('capacity_error') and not torrent.get('system_pause')
    complete=total>0 and done>=total and torrent.get('percentDone',0)>=1 and torrent.get('status') not in (1,2) and not torrent.get('errorString')
    if previous and (running or complete):
        dt=now-previous[0];delta=done-previous[1]
        if 0<dt<=90 and delta>=0:
            record['bytes']=record.get('bytes',0)+delta
            record['seconds']=record.get('seconds',0)+dt
            phases=record.setdefault('phases',{})
            for name,lo,hi in (('start',0,.05),('middle',.05,.95),('end',.95,1)):
                overlap=max(0,min(done,total*hi)-max(previous[1],total*lo)) if delta else 0
                share=overlap/delta if delta else float(lo<=done/max(total,1)<hi or name=='end' and done==total)
                if share:
                    phase=phases.setdefault(name,dict(bytes=0,seconds=0))
                    phase['bytes']+=delta*share;phase['seconds']+=dt*share
    if running:record['last']=[now,done]
    if complete:
        record.setdefault('completed',now)
        record['elapsed_seconds']=record['completed']-record['started']


def availability(seeds):
    # Saturation is a conservative heuristic, not a claim about peer bandwidth.
    return .35+.65*math.sqrt(min(10,max(0,seeds))/10)


def predict(records, release, now=None):
    now=time.time() if now is None else now
    size=release.get('size') or 0
    seeds=release.get('seeders')
    if size<=0 or seeds==0:return None
    candidates=[]
    for r in records:
        seconds=r.get('seconds',0);amount=r.get('bytes',0)
        age=now-r.get('updated',0)
        if seconds<60 or amount<=0 or not 0<=age<=30*86400:continue
        speed=amount/seconds
        # A phase-balanced full-film estimate includes slow edges without letting
        # an initial 2% sample stand in for the entire future download.
        phases=r.get('phases',{})
        middle=phases.get('middle',{})
        if middle.get('seconds',0)>=60 and middle.get('bytes',0)>0:
            main=middle['bytes']/middle['seconds']
            rates=[]
            for name,fraction in (('start',.05),('middle',.9),('end',.05)):
                phase=phases.get(name,{})
                rate=phase['bytes']/phase['seconds'] if phase.get('seconds',0)>=30 and phase.get('bytes',0)>0 else main*.6 if name!='middle' else main
                rates.append((fraction,rate))
            speed=1/sum(fraction/rate for fraction,rate in rates)
        if not math.isfinite(speed):continue
        factor=1.
        if seeds is not None and r.get('seeders') is not None:
            factor=min(1.5,availability(seeds)/availability(r['seeders']))
        # Similar seed scarcity and demand affect weight, never a linear speed bonus.
        similarity=1.
        if release.get('leechers') is not None and r.get('leechers') is not None:
            similarity=1/(1+abs(math.log1p(release['leechers'])-math.log1p(r['leechers']))*.2)
        candidates.append((r['updated'],speed*factor,math.exp(-age/(7*86400))*similarity))
    candidates=sorted(candidates,reverse=True)[:12]
    if not candidates:return None
    center=statistics.median(x[1] for x in candidates)
    speed=sum(min(center*2,max(center/2,r))*w for _,r,w in candidates)/sum(x[2] for x in candidates)
    spread=statistics.median(abs(math.log(max(r,1)/max(center,1))) for _,r,_ in candidates)
    uncertainty=max(1.5 if len(candidates)>=3 else 2.,math.exp(min(spread,1.1)))
    seconds=size/speed
    return dict(speed=speed,seconds=seconds,low=seconds/uncertainty,high=seconds*uncertainty,count=len(candidates))


def duration(seconds):
    minutes=max(1,int(math.ceil(seconds/300)*5))
    return ('%d ч %02d мин' % divmod(minutes,60)) if minutes>=60 else '%d мин'%minutes


def forecast_line(estimate):
    if not estimate:return '<b>⏱ Недостаточно истории для прогноза</b>'
    speed=estimate['speed']
    rate=('%.1f МБ/с'%(speed/1024**2)) if speed>=1024**2 else ('%.0f КБ/с'%(speed/1024))
    return '<b>⏱ ≈ %s · ориентир %s–%s · ≈ %s</b>'%(duration(estimate['seconds']),duration(estimate['low']),duration(estimate['high']),rate)


def records_for(store,uid):
    records=list(store.read_states('download-history:%s:'%uid).values())
    remote=store.read_state('mac-download-history',{}).get('records',[]) if hasattr(store,'read_state') else []
    usable={r.get('hash'):r for r in remote if r.get('seconds',0)>=60 and r.get('bytes',0)>0}
    local={r.get('hash'):r for r in records}
    records=[r for r in records if r.get('hash') not in usable]+[{**local.get(h,{}),**r} for h,r in usable.items()]
    known={r.get('hash') for r in records}
    # Existing minute history is usable, but cannot reconstruct total download time.
    for state in store.read_states('transfer:').values():
        if state.get('uid')!=uid or state.get('hash') in known:continue
        history=state.get('speed_history',[])
        rates=[r for _,r in history if r>0 and math.isfinite(r)]
        if not rates:continue
        records.append(dict(hash=state.get('hash'),updated=history[-1][0],bytes=statistics.median(rates)*60,seconds=60,legacy=True))
    return records

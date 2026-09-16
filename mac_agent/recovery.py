"""Conservative end-of-download recovery through Transmission RPC."""
import math
import socket
import time

RECOVERY_FIELDS = ['hashString','status','percentDone','leftUntilDone','downloadedEver',
                  'rateDownload','secondsDownloading','peersConnected','desiredAvailable','downloadDir','errorString','recheckProgress']

def network_available():
    # Connectivity only: no user data, DNS, or unbounded requests.
    for address in ('1.1.1.1','8.8.8.8'):
        try:
            with socket.create_connection((address,443),timeout=1):return True
        except OSError:pass
    return False

class RecoveryController:
    STALL_SECONDS=180
    SLOW_SECONDS=300
    WARMUP_SECONDS=300
    BACKOFF_SECONDS=1800
    MAX_ATTEMPTS=2

    def __init__(self,store,rpc,clock=time.time,network_ok=network_available):
        self.store=store;self.rpc=rpc;self.clock=clock;self.network_ok=network_ok
        self.observed={};self.network_sample=None

    @staticmethod
    def _active(t,managed):
        info=managed.get(t.get('hashString'))
        return bool(info and not info.get('manual_pause') and not info.get('capacity_pending')
                    and t.get('downloadDir')==info.get('destination') and t.get('status')==4
                    and not t.get('errorString') and 0<=t.get('percentDone',0)<1
                    and t.get('leftUntilDone',0)>0 and t.get('downloadedEver') is not None)

    def note(self,h):
        return self.store.read_state('recovery:'+h,{}).get('note','')

    def _note(self,h,text):
        key='recovery:'+h;s=self.store.read_state(key,{})
        if s.get('note')!=text:
            s['note']=text;self.store.write_state(key,s)

    def _network(self,now):
        if self.network_sample is None or now-self.network_sample[0]>=30:
            self.network_sample=(now,bool(self.network_ok()))
        return self.network_sample[1]

    def _observe(self,t,now):
        h=t['hashString'];done=t['downloadedEver'];left=t['leftUntilDone'];o=self.observed.get(h)
        if (o is None or not 0<now-o['time']<=60 or done<o['done'] or left>o['left']):
            active=min(self.WARMUP_SECONDS,max(0,t.get('secondsDownloading',0))) if done>0 else 0
            self.observed[h]=dict(time=now,done=done,left=left,active=active,baseline=0,last_progress=now)
            return None
        dt=now-o['time'];delta=max(done-o['done'],o['left']-left,0);rate=delta/dt
        o.update(time=now,done=done,left=left)
        if delta>0:o['active']+=dt;o['last_progress']=now
        baseline=o['baseline'];slow=baseline>0 and rate<baseline*.2 and t.get('rateDownload',0)<baseline*.2
        if not slow:
            o.pop('slow_since',None)
            o['baseline']=rate if not baseline else baseline+(rate-baseline)*(-math.expm1(-dt/120))
        elif o['active']>=self.WARMUP_SECONDS and t.get('percentDone',0)>=.95:
            o.setdefault('slow_since',now)
        if t.get('percentDone',0)<.95:
            o.pop('slow_since',None)
            return None
        if o['active']<self.WARMUP_SECONDS:return None
        if now-o['last_progress']>=self.STALL_SECONDS:return 'Нет данных три минуты.'
        if now-o.get('slow_since',now)>=self.SLOW_SECONDS:return 'Скорость ниже прежней в пять раз уже пять минут.'
        return None

    def _reannounce(self,h,now):
        key='recovery:'+h;s=self.store.read_state(key,{})
        if now>=s.get('next_announce',0):
            s['next_announce']=now+self.BACKOFF_SECONDS;self.store.write_state(key,s)
            self.rpc.call('torrent-reannounce',{'ids':[h]})

    def tick(self,torrents,managed):
        now=self.clock();present={t.get('hashString') for t in torrents}
        self.observed={h:o for h,o in self.observed.items() if h in present and h in managed}
        queue=self.store.read_state('recovery_queue',{})
        busy=any(t.get('status') in (1,2) for t in torrents)
        if queue:
            target=next((t for t in torrents if t.get('hashString')==queue.get('hash')),None)
            if target and target.get('status') in (1,2):
                busy=True
            elif now-queue.get('sent',now)<60:
                busy=True
            else:
                h=queue['hash']
                self._note(h,'Проверка завершена; наблюдаю за загрузкой.' if target and target.get('status') in (4,6)
                           else 'Автопроверка завершена или прервана. Состояние загрузки показано выше.')
                self.store.write_state('recovery_queue',{})
        candidates=[]
        for t in torrents:
            h=t.get('hashString')
            if not self._active(t,managed):
                self.observed.pop(h,None);continue
            reason=self._observe(t,now)
            if reason:candidates.append((t,reason))
            elif h!=queue.get('hash') and t.get('rateDownload',0)>0:self._note(h,'')
        for t,reason in candidates:
            h=t['hashString'];o=self.observed[h];history=self.store.read_state('recovery:'+h,{})
            if history.get('attempts',0)>=self.MAX_ATTEMPTS:
                self._note(h,'Две автопроверки уже выполнены. Загрузка всё ещё замедлена; повторять проверку не буду.')
                continue
            if now<history.get('next_attempt',0):continue
            if not self._network(now):
                o['offline']=True;self._note(h,'Нет подтверждённого доступа к интернету. Жду восстановления связи.');continue
            if o.pop('offline',False):
                o['grace_until']=now+120
                self._note(h,'Связь восстановилась. Обновляю пиры и даю загрузке две минуты.')
                self._reannounce(h,now)
            if now<o.get('grace_until',0):continue
            if not t.get('peersConnected') or t.get('desiredAvailable',0)<=0:
                self._note(h,'Ожидаю пиры с оставшимися частями файла. Обновляю список пиров.')
                self._reannounce(h,now);continue
            if busy:
                self._note(h,'Ожидаю окончания другой проверки на диске.');continue
            # Fetch every torrent to include manual/unmanaged checks and cancel stale decisions.
            fresh=self.rpc.call('torrent-get',{'fields':RECOVERY_FIELDS}).get('torrents',[])
            current=next((x for x in fresh if x.get('hashString')==h),None)
            if any(x.get('status') in (1,2) for x in fresh):return []
            if (not current or not self._active(current,managed) or current.get('percentDone',0)<.95
                    or current.get('desiredAvailable',0)<=0 or not current.get('peersConnected')):continue
            limit=o['baseline']*.2
            if current.get('rateDownload',0)>=limit and current.get('rateDownload',0)>0:continue
            if (current['downloadedEver']!=t['downloadedEver'] or current['leftUntilDone']!=t['leftUntilDone']):continue
            history.update(attempts=history.get('attempts',0)+1,next_attempt=now+self.BACKOFF_SECONDS,
                           note=reason+' Запускаю проверку локальных данных.')
            self.store.write_state('recovery:'+h,history)
            self.store.write_state('recovery_queue',{'hash':h,'sent':now})
            self.observed.pop(h,None)
            # Transmission preserves its own start intent; never force-start a GUI-paused torrent.
            self.rpc.call('torrent-verify',{'ids':[h]})
            return [h]
        return []

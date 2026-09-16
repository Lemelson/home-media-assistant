"""Independent launchd health supervisor; bounded retries, persistent cooldown."""
import json
import logging
import os
import re
import signal
import subprocess
import time
import urllib.request
from pathlib import Path
from mac_agent.rpc import TransmissionRPC


def decision(state, rpc_ok, agent_ok, now, io_busy=False):
    if io_busy and not rpc_ok:
        state["transmission"] = 0
        return None
    for name,ok in (('transmission',rpc_ok),('agent',agent_ok)):
        state[name]=0 if ok else state.get(name,0)+1
    target='transmission' if not rpc_ok else 'agent' if not agent_ok else None
    if target and state[target]>=3 and now-state.get('restart',-10000)>=600:
        state.update(restart=now)
        state[target]=0
        return target
    return None


def transmission_pids():
    expected=str(Path.home()/'Applications/Transmission.app/Contents/MacOS/Transmission')
    result=subprocess.run(['/bin/ps','-axo','pid=,uid=,comm='],capture_output=True,text=True,timeout=5,check=True)
    return [int(parts[0]) for line in result.stdout.splitlines()
            if len(parts:=line.strip().split(None,2))==3 and parts[1]==str(os.getuid()) and parts[2]==expected]


def restart_transmission():
    pids=transmission_pids()
    # Keep one bounded local stack sample for diagnosing the underlying app defect.
    if pids:
        output=Path.home()/'Library/Application Support/HomeMediaAssistant/last-transmission-hang.txt'
        try:
            subprocess.run(['/usr/bin/sample',str(pids[0]),'2','-file',str(output)],
                           capture_output=True,timeout=8)
        except (OSError,subprocess.TimeoutExpired):pass
    for pid in pids:os.kill(pid,signal.SIGTERM)
    for _ in range(15):
        if not set(pids)&set(transmission_pids()):break
        time.sleep(1)
    # Escalate only for the same still-hung owned application; never delete data.
    for pid in set(pids)&set(transmission_pids()):os.kill(pid,signal.SIGKILL)
    subprocess.run(['/bin/launchctl','kickstart','-k','gui/%d/org.home-media-assistant.transmission'%os.getuid()],check=True,timeout=10,capture_output=True)


def disk_io_busy(volume):
    """A blocked owned process plus active mounted media disk is not a dead daemon."""
    try:
        pids = transmission_pids()
        if not pids:
            return False
        result = subprocess.run(['/bin/ps','-o','stat=','-p',','.join(map(str,pids))],
                                capture_output=True,text=True,timeout=3,check=True)
        if not any('U' in line.split()[0] for line in result.stdout.splitlines() if line.split()):
            return False
        mounts = subprocess.run(['/sbin/mount'],capture_output=True,text=True,timeout=3,check=True).stdout
        device = next((line.split(' on ',1)[0] for line in mounts.splitlines()
                       if ' on '+str(volume)+' (' in line),None)
        if not device or not re.fullmatch(r'/dev/disk[0-9]+s[0-9]+',device):
            return False
        disk = re.match(r'/dev/(disk[0-9]+)',device).group(1)
        stats = subprocess.run(['/usr/sbin/iostat','-d','-c','2','-w','1',disk],
                               capture_output=True,text=True,timeout=5,check=True).stdout
        rows = [line.split() for line in stats.splitlines() if re.match(r'^\s*\d',line)]
        return bool(rows and float(rows[-1][-1]) > 0.1)
    except (OSError,subprocess.SubprocessError,ValueError,IndexError):
        return False


def main():
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
    root=Path(os.environ.get('AGENT_STATE_DIRECTORY', str(Path.home()/'Library/Application Support/HomeMediaAssistant')))
    config=json.loads((root/'agent.json').read_text())
    rpc=TransmissionRPC(**json.loads((root/'transmission-rpc.json').read_text()))
    state_path=root/'watchdog.json'
    try:state=json.loads(state_path.read_text())
    except (OSError,ValueError):state={}
    while True:
        try:
            try:rpc.call('session-get');rpc_ok=True
            except Exception:rpc_ok=False
            agent_ok=False
            if True:
                try:
                    req=urllib.request.Request('http://127.0.0.1:18742/health',headers={'Authorization':'Bearer '+config['token']})
                    with urllib.request.urlopen(req,timeout=5) as response:
                        agent_ok=bool(json.load(response).get('ok'))
                except Exception:pass
            state.update(checked=time.time(),rpc_ok=rpc_ok,agent_ok=agent_ok)
            io_busy = not rpc_ok and disk_io_busy(config['volume'])
            state['disk_io_busy'] = io_busy
            action=decision(state,rpc_ok,agent_ok,time.time(),io_busy=io_busy)
            temp=state_path.with_suffix('.new');temp.write_text(json.dumps(state));temp.replace(state_path)
            if action:
                logging.warning('health_recovery service=%s',action)
                if action=='transmission':restart_transmission()
                else:subprocess.run(['/bin/launchctl','kickstart','-k','gui/%d/org.home-media-assistant.agent'%os.getuid()],check=True,timeout=10,capture_output=True)
        except Exception as error:logging.warning('health_recovery_failed type=%s',type(error).__name__)
        time.sleep(30)

if __name__=='__main__':main()

"""Bounded startup check: processor ready and authenticated console reachable."""
import json, os, pathlib, sys, time
import requests
instance=sys.argv[1] if len(sys.argv)>1 else 'hab2-rehearsal'
data=pathlib.Path(os.environ.get('DATA_DIR','/data'))
secrets=json.loads((data/'secrets.json').read_text())
url=os.environ.get('YAMCS_URL','http://127.0.0.1:8090')
last='not checked'
for _ in range(60):
    try:
        r=requests.get(url+'/api/processors/'+instance+'/realtime',auth=(secrets['username'],secrets['password']),timeout=3)
        r.raise_for_status()
        if r.json().get('state') != 'RUNNING': raise RuntimeError('Processor not RUNNING')
        r=requests.get('http://127.0.0.1:8088/api/status',auth=('operator',secrets['console_password']),timeout=3)
        r.raise_for_status()
        print('PASS: Yamcs realtime processor and authenticated bridge console are ready.')
        print('This checks service readiness, not reception of flight telemetry.')
        sys.exit(0)
    except (requests.RequestException,ValueError,RuntimeError) as e: last=str(e)
    time.sleep(2)
raise SystemExit('Startup check failed: '+last+'\nInspect: docker compose logs --tail=100 bridge')

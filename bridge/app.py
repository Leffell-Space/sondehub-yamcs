"""SondeHub AMATEUR -> durable receipt journal -> Yamcs processed parameters."""
import base64, hashlib, hmac, html, json, logging, os, pathlib, re, secrets, sqlite3, threading, time, uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
import requests
import paho.mqtt.client as mqtt
from yamcs.client import YamcsClient, BasicAuthCredentials, NotFound, ValueUpdate
from core import CORE, normalize, parameter_map, prefix
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
DATA=pathlib.Path(os.environ.get('DATA_DIR','/data')); DATA.mkdir(parents=True,exist_ok=True)
SECRETS=json.loads((DATA/'secrets.json').read_text())
LOCK=threading.RLock(); CSRF=secrets.token_urlsafe(32)
STATE={'mqtt_connected':False,'mqtt_last_message':None,'yamcs_last_success':None,'mqtt_error':None,'yamcs_error':None}
CONFIG=json.loads((DATA/'config.json').read_text())
@contextmanager
def db():
    c=sqlite3.connect(DATA/'journal.sqlite',timeout=30)
    try:
        c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA synchronous=FULL')
        with c:
            yield c
    finally:
        c.close()
with db() as c:
    c.execute('CREATE TABLE IF NOT EXISTS packets (id INTEGER PRIMARY KEY, instance TEXT, callsign TEXT, digest TEXT, received REAL, raw TEXT, sent INTEGER DEFAULT 0, error TEXT, UNIQUE(instance,digest))')
    c.execute('CREATE TABLE IF NOT EXISTS watermark (instance TEXT, callsign TEXT, gentime REAL, PRIMARY KEY(instance,callsign))')
    c.execute('CREATE INDEX IF NOT EXISTS pending ON packets(sent,id)')
def ingest(packet):
    received=time.time()
    if not isinstance(packet,dict): return
    call=packet.get('payload_callsign')
    with LOCK: targets=[dict(t) for t in CONFIG['targets'] if t['callsign']==call]
    if not targets: return
    raw=json.dumps(packet,sort_keys=True,ensure_ascii=False,allow_nan=False)
    digest=hashlib.sha256(raw.encode()).hexdigest()
    with db() as c:
        for t in targets:
            c.execute('INSERT OR IGNORE INTO packets(instance,callsign,digest,received,raw) VALUES(?,?,?,?,?)',(t['instance'],call,digest,received,raw))
def mqtt_loop():
    while True:
        client=None
        try:
            r=requests.get('https://api.v2.sondehub.org/sondes/websocket',timeout=20); r.raise_for_status()
            u=urlsplit(r.text.strip().strip('"'))
            if u.scheme!='wss' or not u.hostname: raise ValueError('Unexpected MQTT URL')
            client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='spacecast-'+uuid.uuid4().hex,transport='websockets')
            client.tls_set(); client.ws_set_options(path=u.path+('?' + u.query if u.query else ''))
            def connected(c, userdata, flags, reason, properties):
                STATE['mqtt_connected']=not reason.is_failure
                if reason.is_failure: STATE['mqtt_error']=str(reason); return
                STATE['mqtt_error']=None
            def message(c, userdata, msg):
                try:
                    data=json.loads(msg.payload)
                    for packet in data if isinstance(data,list) else [data]: ingest(packet)
                    STATE['mqtt_last_message']=time.time()
                except Exception as e:
                    STATE['mqtt_error']=str(e); logging.exception('MQTT packet failed')
            def subscription_ack(c, userdata, mid, codes, properties):
                if any(code.is_failure for code in codes):
                    STATE['mqtt_error']='MQTT subscription rejected: '+str(codes)
                    logging.error(STATE['mqtt_error'])
            client.on_connect=connected; client.on_message=message; client.on_subscribe=subscription_ack
            client.connect(u.hostname,u.port or 443,60)
            subscribed=set()
            while True:
                rc=client.loop(timeout=1)
                if rc!=mqtt.MQTT_ERR_SUCCESS: raise ConnectionError('MQTT disconnected: '+str(rc))
                if not STATE['mqtt_connected']: continue
                with LOCK: wanted={'amateur/'+t['callsign'] for t in CONFIG['targets']}
                for topic in wanted-subscribed: client.subscribe(topic,qos=0)
                for topic in subscribed-wanted: client.unsubscribe(topic)
                subscribed=wanted
        except Exception as e:
            STATE['mqtt_error']=str(e); logging.warning('MQTT reconnect: %s',e)
        finally:
            STATE['mqtt_connected']=False
            if client:
                try: client.disconnect()
                except Exception: pass
        time.sleep(5)
def worker():
    client=YamcsClient(os.environ.get('YAMCS_URL','http://127.0.0.1:8090'),credentials=BasicAuthCredentials(SECRETS['username'],SECRETS['password']))
    class BoundedAdapter(requests.adapters.HTTPAdapter):
        def send(self, request, **kwargs):
            if kwargs.get('timeout') is None: kwargs['timeout']=(5,20)
            return super().send(request, **kwargs)
    client.ctx.session.mount('http://',BoundedAdapter())
    client.ctx.session.mount('https://',BoundedAdapter())
    known=set(); types=set()
    def ensure(instance,name,kind):
        mdb=client.get_mdb(instance)
        typ='/HAB/'+kind+'_t'
        if (instance,kind) not in types:
            try: mdb.get_parameter_type(typ)
            except NotFound: mdb.create_parameter_type(typ,eng_type=kind)
            types.add((instance,kind))
        if (instance,name) not in known:
            try: mdb.get_parameter(name)
            except NotFound: mdb.create_parameter(name,data_source='TELEMETERED',parameter_type=typ)
            known.add((instance,name))
    while True:
        try:
            with LOCK: targets=list(CONFIG['targets']); expiry=CONFIG['expire_seconds']
            # Predeclare broadcast paths even before first reception.
            for target in targets:
                for key,(_,kind) in CORE.items(): ensure(target['instance'],parameter_map(target['callsign'])[key],kind)
            with db() as c:
                row=c.execute('SELECT id,instance,callsign,received,raw FROM packets WHERE sent=0 ORDER BY id LIMIT 1').fetchone()
            if not row: time.sleep(.25); continue
            ident,instance,call,received,raw=row
            try: gentime,values=normalize(json.loads(raw),received)
            except (ValueError,KeyError,TypeError) as e:
                with db() as c: c.execute('UPDATE packets SET sent=-1,error=? WHERE id=?',(str(e),ident))
                continue
            for name,(kind,value) in values.items(): ensure(instance,name,kind)
            with db() as c: last=c.execute('SELECT gentime FROM watermark WHERE instance=? AND callsign=?',(instance,call)).fetchone()
            # Delayed/backlogged packets remain archived but cannot roll live graphics backwards.
            live=(not last or gentime.timestamp()>last[0]) and time.time()-gentime.timestamp()<expiry
            updates={name:ValueUpdate(value,generation_time=gentime,expires_in=expiry) for name,(_,value) in values.items()}
            result=client.load_parameter_values(instance,iter([updates]),stream='pp_realtime' if live else 'pp_dump')
            if int(result.value_count)!=len(updates): raise RuntimeError('Yamcs did not acknowledge all values')
            with db() as c:
                c.execute('UPDATE packets SET sent=1,error=NULL WHERE id=?',(ident,))
                if live: c.execute('INSERT INTO watermark VALUES(?,?,?) ON CONFLICT(instance,callsign) DO UPDATE SET gentime=max(gentime,excluded.gentime)',(instance,call,gentime.timestamp()))
            STATE['yamcs_last_success']=time.time(); STATE['yamcs_error']=None
        except Exception as e:
            STATE['yamcs_error']=str(e); known.clear(); types.clear()
            logging.exception('Yamcs write failed; retained for retry'); time.sleep(5)
def snapshot():
    with db() as c:
        counts=dict(c.execute('SELECT sent,count(*) FROM packets GROUP BY sent'))
        rows=c.execute('SELECT instance,callsign,max(received),count(*) FROM packets GROUP BY instance,callsign').fetchall()
    with LOCK: config=json.loads(json.dumps(CONFIG))
    return dict(STATE,config=config,journal={'pending':counts.get(0,0),'acknowledged':counts.get(1,0),'invalid':counts.get(-1,0)},balloons=rows)
class Handler(BaseHTTPRequestHandler):
    def auth(self):
        expected='Basic '+base64.b64encode(('operator:'+SECRETS['console_password']).encode()).decode()
        if hmac.compare_digest(self.headers.get('Authorization',''),expected): return True
        self.send_response(401); self.send_header('WWW-Authenticate','Basic realm="Balloon bridge"'); self.end_headers(); return False
    def send(self,body,kind='text/html',code=200):
        body=body.encode(); self.send_response(code); self.send_header('Content-Type',kind+'; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if not self.auth(): return
        u=urlsplit(self.path)
        if u.path=='/api/status': return self.send(json.dumps(snapshot()),'application/json')
        if u.path=='/spacecast':
            q=parse_qs(u.query); call=q.get('callsign',[''])[0]; instance=q.get('instance',[''])[0]
            return self.send(json.dumps({'url':'http://127.0.0.1:8090','instance':instance,'processor':'realtime','namespace':'/HAB','parameterMap':parameter_map(call)},indent=2),'application/json')
        self.send('''<!doctype html><meta name="viewport" content="width=device-width"><title>Balloon bridge</title>
<style>body{font:16px system-ui;max-width:1000px;margin:2em auto;padding:1em;background:#101b2a;color:#e4effa}input,button{font:inherit;margin:.3em;padding:.5em}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#8bd4ff}</style>
<h1>SondeHub Amateur → Yamcs</h1><p>Add the exact payload_callsign, including its SSID/suffix. It can be registered here before first transmission. Instance must already exist in Yamcs.</p>
<form method="post" action="/target"><input name="csrf" type="hidden" value="'''+CSRF+'''"><input name="callsign" placeholder="Exact payload callsign" required><input name="instance" placeholder="hab2-rehearsal" required><button name="action" value="add">Add</button><button name="action" value="remove">Remove</button></form>
<form method="post" action="/discover"><input name="csrf" type="hidden" value="'''+CSRF+'''"><button>Discover recent Amateur balloons (one REST request)</button></form>
<p>Live status refreshes every 3 seconds. pending = locally saved but not yet acknowledged by Yamcs; invalid = retained raw but rejected timestamp/schema. A connected MQTT socket does not prove a balloon is transmitting.</p><pre id="status">'''+html.escape(json.dumps(snapshot(),indent=2))+'''</pre>
<script>setInterval(async()=>{try{const r=await fetch('/api/status');if(r.ok)document.getElementById('status').textContent=JSON.stringify(await r.json(),null,2)}catch(e){}},3000)</script>''')
    def do_POST(self):
        if not self.auth(): return
        size=int(self.headers.get('Content-Length','0'))
        if size>4096: return self.send('Request too large',code=413)
        data=parse_qs(self.rfile.read(size).decode())
        if not hmac.compare_digest(data.get('csrf',[''])[0],CSRF): return self.send('Invalid form token',code=403)
        try:
            if self.path=='/discover':
                r=requests.get('https://api.v2.sondehub.org/amateur/telemetry',params={'duration':'3h'},timeout=20); r.raise_for_status()
                return self.send('<a href="/">Back</a><h1>Recent Amateur payloads and all reported fields</h1><pre>'+html.escape(json.dumps(r.json(),indent=2))+'</pre>')
            if self.path!='/target': return self.send('Not found',code=404)
            call=data['callsign'][0].strip(); instance=data['instance'][0].strip()
            if not re.fullmatch(r'[A-Za-z0-9_\-]{1,64}',call) or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}',instance): raise ValueError('Invalid callsign or instance')
            if data.get('action') != ['remove']:
                r=requests.get(os.environ.get('YAMCS_URL','http://127.0.0.1:8090')+'/api/processors/'+instance+'/realtime', auth=(SECRETS['username'],SECRETS['password']),timeout=10)
                r.raise_for_status()
            target={'callsign':call,'instance':instance}
            with LOCK:
                if data.get('action')==['remove']: CONFIG['targets']=[t for t in CONFIG['targets'] if t!=target]
                elif target not in CONFIG['targets']: CONFIG['targets'].append(target)
                temp=DATA/'config.tmp'; temp.write_text(json.dumps(CONFIG,indent=2)); temp.replace(DATA/'config.json')
            self.send_response(303); self.send_header('Location','/'); self.end_headers()
        except Exception as e: self.send(html.escape(str(e)),code=400)
if __name__=='__main__':
    threading.Thread(target=mqtt_loop,daemon=True).start()
    threading.Thread(target=worker,daemon=True).start()
    ThreadingHTTPServer((os.environ.get('BIND_HOST','127.0.0.1'),8088),Handler).serve_forever()

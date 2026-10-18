"""Inject clearly labelled local synthetic data; never contacts SondeHub."""
import argparse, datetime, time
import app
p=argparse.ArgumentParser();p.add_argument('instance');p.add_argument('--count',type=int,default=30)
a=p.parse_args()
if 'rehearsal' not in a.instance or not 1<=a.count<=600:
    raise SystemExit('Use an instance containing rehearsal and 1..600 samples')
target={'instance':a.instance,'callsign':'TEST-HAB'}
if target not in app.CONFIG['targets']:
    raise SystemExit('First add TEST-HAB to this rehearsal instance in the balloon console')
app.CONFIG['targets']=[target]  # This process only; never route test data into other instances.
print('LOCAL SYNTHETIC TEST ONLY; no SondeHub upload. Callsign TEST-HAB.',flush=True)
for n in range(a.count):
    now=datetime.datetime.now(datetime.timezone.utc).isoformat()
    app.ingest({'payload_callsign':'TEST-HAB','datetime':now,'time_received':now,
                'uploader_callsign':'LOCAL-TEST','software_name':'SYNTHETIC-REHEARSAL',
                'lat':41.0+n*.00001,'lon':-73.0,'alt':1000.+n*5,'vel_v':5.,'vel_h':2.,
                'test_only':True,'custom_sensor':{'battery_v':4.1,'sequence':n}})
    time.sleep(1)
print('Finished. Verify Yamcs/Spacecast go stale after the configured expiry.',flush=True)

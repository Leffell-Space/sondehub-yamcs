import json, os, pathlib, sqlite3, sys, tempfile, time, unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bridge'))
from core import normalize, prefix, parameter_map
class Mapping(unittest.TestCase):
    def packet(self):
        return {'payload_callsign':'HAB-2','datetime':'2026-10-14T12:00:00Z','lat':41.0,'lon':-73.0,'alt':1234,'custom':{'x':[1,2]},'modulation':'Horus'}
    def test_preserves_all_fields(self):
        p=self.packet(); t,v=normalize(p,1791979201)
        self.assertEqual(json.loads(v[prefix('HAB-2')+'RAW_JSON'][1]),p)
        self.assertEqual(v[parameter_map('HAB-2')['NAV/ALTITUDE']][1],1234)
    def test_no_identity_collision(self): self.assertNotEqual(prefix('HAB-2'),prefix('HAB_2'))
    def test_missing_values_not_zero(self):
        _,v=normalize(self.packet(),1791979201)
        self.assertNotIn(parameter_map('HAB-2')['NAV/VERTICAL_SPEED'],v)
    def test_invalid_coordinates_not_broadcast(self):
        p=self.packet(); p['lat']=500
        _,v=normalize(p,1791979201)
        self.assertNotIn(parameter_map('HAB-2')['NAV/LATITUDE'],v)
        self.assertIn('500',v[prefix('HAB-2')+'RAW_JSON'][1])
    def test_future_and_naive_rejected(self):
        for t in ['2099-01-01T00:00:00Z','2026-10-14T12:00:00']:
            p=self.packet(); p['datetime']=t
            with self.assertRaises(ValueError): normalize(p,1791979201)
    def test_type_changes_have_separate_paths(self):
        p=self.packet(); p['extra']=1; _,a=normalize(p,1791979201)
        p['extra']='bad'; _,b=normalize(p,1791979201)
        self.assertNotEqual(set(a),set(b))
class Journal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(); root=pathlib.Path(cls.tmp.name)
        (root/'secrets.json').write_text(json.dumps({'username':'test','password':'test','console_password':'test'}))
        (root/'config.json').write_text(json.dumps({'targets':[{'instance':'test','callsign':'HAB-2'}],'expire_seconds':30}))
        os.environ['DATA_DIR']=str(root)
        import app
        cls.app=app
    def setUp(self):
        self.app.CONFIG['targets']=[{'instance':'test','callsign':'HAB-2'}]
        with self.app.db() as c: c.execute('DELETE FROM packets')
    def test_multiple_instances_and_balloons(self):
        self.app.CONFIG['targets'] += [{'instance':'second','callsign':'HAB-2'}, {'instance':'test','callsign':'OTHER'}]
        p=Mapping().packet()
        self.app.ingest(p); self.app.ingest(p)
        self.app.ingest(dict(p,payload_callsign='OTHER'))
        with self.app.db() as c:
            rows=c.execute('SELECT instance,callsign FROM packets ORDER BY instance,callsign').fetchall()
        self.assertEqual(rows,[('second','HAB-2'),('test','HAB-2'),('test','OTHER')])
    def test_connection_is_closed_after_transaction(self):
        with self.app.db() as connection:
            connection.execute('SELECT 1')
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')
    def test_filtered_dedup_persisted(self):
        p=Mapping().packet(); self.app.ingest(p); self.app.ingest(p)
        q=dict(p,payload_callsign='OTHER'); self.app.ingest(q)
        with self.app.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM packets').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT sent FROM packets').fetchone()[0],0)
        self.assertEqual(self.app.snapshot()['journal']['pending'],1)
if __name__=='__main__': unittest.main()

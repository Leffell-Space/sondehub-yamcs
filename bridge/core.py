import json, math
from datetime import datetime, timezone
CORE = {
 'TRACKING/CALLSIGN': ('payload_callsign','string'),
 'TRACKING/SOURCE': ('modulation','string'),
 'TRACKING/SOURCE_RECEIVER': ('uploader_callsign','string'),
 'NAV/LATITUDE': ('lat','float'), 'NAV/LONGITUDE': ('lon','float'),
 'NAV/ALTITUDE': ('alt','float'), 'NAV/GROUND_SPEED': ('vel_h','float'),
 'NAV/VERTICAL_SPEED': ('vel_v','float'),
 'GROUND/PACKET_TIME': ('datetime','string'),
 'GROUND/LAST_HEARD': ('time_received','string'),
 'DERIVED/PACKET_AGE': (None,'float')}
def stamp(value):
    t = datetime.fromisoformat(value.replace('Z','+00:00'))
    if t.tzinfo is None: raise ValueError('Timestamp requires timezone')
    return t.astimezone(timezone.utc)
def prefix(callsign):
    return '/HAB/b_' + callsign.encode().hex() + '__'
def parameter_map(callsign):
    return {key:prefix(callsign)+key.replace('/','__') for key in CORE}
def normalize(packet, received):
    """All fields retained in raw JSON; typed flat fields have collision-free names."""
    call = packet.get('payload_callsign')
    if not isinstance(call,str) or not call: raise ValueError('Missing Amateur payload_callsign')
    gentime = stamp(packet['datetime'])
    if gentime.timestamp() > received + 300: raise ValueError('Packet time more than 5 minutes in future')
    base = prefix(call)
    out = {base+'RAW_JSON': ('string',json.dumps(packet,ensure_ascii=False,separators=(',',':'),allow_nan=False))}
    for key,(field,kind) in CORE.items():
        val = max(0., received-gentime.timestamp()) if field is None else packet.get(field)
        if key == 'TRACKING/SOURCE': val = 'SondeHub Amateur / ' + str(packet.get('modulation') or packet.get('software_name') or 'unknown uploader')
        if val is None: continue
        if kind == 'float':
            if isinstance(val,bool) or not isinstance(val,(int,float)) or not math.isfinite(val): continue
            if field=='lat' and not -90<=val<=90: continue
            if field=='lon' and not -180<=val<=180: continue
            val=float(val)
        else: val=str(val)
        out[base+key.replace('/','__')] = (kind,val)
    for key,val in packet.items():
        if isinstance(val,bool): kind='boolean'
        elif isinstance(val,(int,float)) and math.isfinite(val): kind='float'; val=float(val)
        elif isinstance(val,str): kind='string'
        else: kind='string'; val=json.dumps(val,ensure_ascii=False,allow_nan=False)
        out[base+'field_'+key.encode().hex()+'_'+kind] = (kind,val)
    return gentime,out

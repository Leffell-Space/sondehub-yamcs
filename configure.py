#!/usr/bin/env python3
"""Configure only the bridge; never changes the Yamcs server or creates instances."""
import getpass
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parent

def initialize(root, url, username, password):
    parsed=urlsplit(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or any(c in url for c in "\r\n$'\\"):
        raise ValueError('Use an HTTP(S) Yamcs base URL without credentials, query, fragment, quotes, backslashes, dollar signs or line breaks')
    if not username or ':' in username or not password:
        raise ValueError('A Yamcs username (without colon) and password are required')
    data=root/'data'
    if (data/'secrets.json').exists() or (root/'.env').exists():
        raise FileExistsError('Existing bridge configuration found; edit it intentionally instead of overwriting it')
    data.mkdir(mode=0o700,parents=True,exist_ok=True)
    def private(path, text):
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f: f.write(text)
    private(data/'secrets.json',json.dumps({'username':username,'password':password,'console_password':secrets.token_urlsafe(24)},indent=2)+'\n')
    if not (data/'config.json').exists():
        private(data/'config.json',json.dumps({'targets':[],'expire_seconds':30},indent=2)+'\n')
    private(root/'.env',"YAMCS_URL='"+url.rstrip('/')+"'\n")

def main():
    os.umask(0o077)
    url=input('Existing Yamcs URL [http://127.0.0.1:8090]: ').strip() or 'http://127.0.0.1:8090'
    username=input('Yamcs bridge username [bridge]: ').strip() or 'bridge'
    password=getpass.getpass('Yamcs bridge password: ')
    initialize(ROOT,url,username,password)
    print('Configured. Console user: operator; console password is in data/secrets.json.')
    print('Start: sudo docker compose up -d --build')
if __name__=='__main__': main()

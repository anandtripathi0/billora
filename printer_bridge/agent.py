"""Run locally on the printer PC. Cloud only queues jobs; this process owns hardware I/O."""
import argparse
import ctypes
from ctypes import wintypes
import getpass
import json
import os
from pathlib import Path
import socket
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
try: from .receipt import render_receipt, escpos_bytes
except ImportError: from receipt import render_receipt, escpos_bytes

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): raise ValueError('Redirect refused. Configure the final HTTPS Billora URL.')

def validate_url(url):
    parts=urlsplit(url)
    if parts.username or parts.password or parts.query or parts.fragment or parts.path not in ('','/'):
        raise ValueError('Use the Billora origin only, without credentials or paths.')
    if parts.scheme!='https' and not (parts.scheme=='http' and parts.hostname in ('localhost','127.0.0.1')):
        raise ValueError('HTTPS is required, except for loopback development.')
    if not parts.hostname: raise ValueError('Missing server hostname.')
    return url.rstrip('/')

def request(config, path, data, authenticated=True):
    headers={'Content-Type':'application/json'}
    if authenticated: headers['Authorization']='Bearer '+config['token']
    req=Request(validate_url(config['server'])+'/api/printing/agent/'+path+'/',data=json.dumps(data).encode(),headers=headers,method='POST')
    with build_opener(NoRedirect()).open(req,timeout=20) as response:
        raw=response.read(2_000_001)
        if len(raw)>2_000_000: raise ValueError('Response too large.')
        return json.loads(raw)

class DeliveryError(Exception):
    def __init__(self, message, uncertain=False): super().__init__(message);self.uncertain=uncertain

def windows_raw(name, data):
    if os.name!='nt': raise DeliveryError('Windows spooler connection requires Windows.')
    win=ctypes.WinDLL('winspool.drv',use_last_error=True)
    class DOC(ctypes.Structure): _fields_=[('name',wintypes.LPWSTR),('output',wintypes.LPWSTR),('datatype',wintypes.LPWSTR)]
    win.OpenPrinterW.argtypes=[wintypes.LPWSTR,ctypes.POINTER(wintypes.HANDLE),ctypes.c_void_p];win.OpenPrinterW.restype=wintypes.BOOL
    win.GetPrinterW.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)];win.GetPrinterW.restype=wintypes.BOOL
    win.StartDocPrinterW.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(DOC)];win.StartDocPrinterW.restype=wintypes.DWORD
    win.WritePrinter.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)];win.WritePrinter.restype=wintypes.BOOL
    for name_fn in ['StartPagePrinter','EndPagePrinter','EndDocPrinter','ClosePrinter']:
        fn=getattr(win,name_fn);fn.argtypes=[wintypes.HANDLE];fn.restype=wintypes.BOOL
    handle=wintypes.HANDLE();started=False
    if not win.OpenPrinterW(name,ctypes.byref(handle),None): raise DeliveryError('Cannot open the configured Windows printer.')
    try:
        status=wintypes.DWORD();needed=wintypes.DWORD()
        if win.GetPrinterW(handle,6,ctypes.byref(status),ctypes.sizeof(status),ctypes.byref(needed)) and status.value & (0x1|0x2|0x8|0x10|0x40|0x80|0x800|0x1000|0x400000):
            raise DeliveryError(f'Windows reports printer unavailable (status {status.value}). Check paper, cover and connection.')
        job_id=win.StartDocPrinterW(handle,1,ctypes.byref(DOC('Billora receipt',None,'RAW')))
        if not job_id: raise DeliveryError('Windows could not start the print job.')
        started=True
        if not win.StartPagePrinter(handle): raise DeliveryError('Windows could not start the page.',True)
        written=wintypes.DWORD();buffer=ctypes.create_string_buffer(data)
        if not win.WritePrinter(handle,buffer,len(data),ctypes.byref(written)) or written.value!=len(data): raise DeliveryError('Spool write incomplete. Check paper before retrying.',True)
        if not win.EndPagePrinter(handle) or not win.EndDocPrinter(handle): raise DeliveryError('Spool completion uncertain.',True)
        started=False
        return f'Windows spooler accepted job {job_id}; physical output unverified.'
    finally:
        if started: win.EndDocPrinter(handle)
        win.ClosePrinter(handle)

def deliver(config, raw):
    kind=config['connection']
    if kind=='windows': return windows_raw(config['printer'],raw)
    if kind=='mock':
        with open(config['mock_file'],'ab') as target: target.write(raw)
        return 'MOCK output written; no physical printer was used.'
    if kind!='lan': raise DeliveryError('Unknown connection type.')
    try: connection=socket.create_connection((config['host'],int(config.get('port',9100))),timeout=5)
    except OSError: raise DeliveryError('LAN printer connection failed; no data sent.')
    try:
        with connection: connection.sendall(raw)
    except OSError: raise DeliveryError('LAN transfer interrupted; paper output is uncertain.',True)
    return 'LAN socket accepted receipt bytes; paper and printer status unavailable.'

class Ledger:
    def __init__(self,path):
        self.db=sqlite3.connect(path)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, status TEXT, detail TEXT, acked INTEGER DEFAULT 0)')
        self.db.execute("UPDATE jobs SET status='uncertain', detail='Agent restarted during delivery. Check paper before retrying.' WHERE status='started'");self.db.commit()
    def pending(self): return list(self.db.execute('SELECT id,status,detail FROM jobs WHERE acked=0'))
    def ack(self,id): self.db.execute('UPDATE jobs SET acked=1 WHERE id=?',(id,));self.db.commit()
    def process(self,job,config,writer=deliver):
        row=self.db.execute('SELECT status,detail FROM jobs WHERE id=?',(job['id'],)).fetchone()
        if row: return row
        # Durable intent precedes hardware I/O. After a crash, never blindly print again.
        self.db.execute("INSERT INTO jobs(id,status,detail) VALUES (?,'started','')",(job['id'],));self.db.commit()
        attempted=False
        try:
            if job['width']!=config['width']: raise DeliveryError('Job width differs from configured paper. Select the configured width in Billora.')
            bitmap=render_receipt(job['receipt'],job['width'],config.get('dots'),config.get('font'))
            raw=escpos_bytes(bitmap,config.get('cut',False));attempted=True
            detail=writer(config,raw);status='spooled'
        except DeliveryError as error: status='uncertain' if error.uncertain else 'failed';detail=str(error)
        except Exception: status='uncertain' if attempted else 'failed';detail='Printer delivery uncertain.' if attempted else 'Receipt rendering failed. Check printer width/font configuration.'
        self.db.execute('UPDATE jobs SET status=?,detail=? WHERE id=?',(status,detail[:300],job['id']));self.db.commit()
        return status,detail[:300]

def local_status(config, port):
    allowed={config['server'],f'http://127.0.0.1:{port}',f'http://localhost:{port}'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            if self.headers.get('Host') not in (f'127.0.0.1:{port}',f'localhost:{port}') or self.headers.get('Origin') not in (None,*allowed):
                self.send_error(403);return
            if self.path!='/health': self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.end_headers()
            self.wfile.write(b'{"agent":"running","mode":"outbound HTTPS pull","physical_output":"unverified"}')
        def do_POST(self): self.send_error(405,'No browser printing endpoint. Use authenticated Billora queue.')
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server

def test_receipt():
    return {'business':{'name':'Billora printer test','invoice_footer':'Check width and QR scan quality.','upi_id':'test@upi'},'customer':{'name':'Setup test'},'number':'TEST ONLY','date':time.strftime('%Y-%m-%d'),'status':'unpaid','items':[{'description':'Receipt width / wrapping test','quantity':'1','unit':'pcs','unit_price':'1.00','subtotal':'1.00'}],'subtotal':'1.00','discount':'0','cgst':'0','sgst':'0','igst':'0','total':'1.00','paid_amount':'0','balance':'1.00','upi_uri':'https://example.com/billora-printer-test'}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['setup','run','test']);parser.add_argument('--config',type=Path,default=Path(os.environ.get('LOCALAPPDATA',Path.home()/'.config'))/'BilloraPrinter'/'config.json');parser.add_argument('--status-port',type=int,default=8765);args=parser.parse_args()
    if args.command=='setup':
        config={'server':validate_url(input('Billora URL (https://your-frontend.onrender.com): ').strip())}
        code=getpass.getpass('One-time pairing code from Business Settings: ').strip()
        connection=input('Connection (windows / lan / mock): ').strip().lower()
        if connection not in ('windows','lan','mock'): raise ValueError('Unsupported connection.')
        config['connection']=connection
        if connection=='windows': config['printer']=input('Exact installed Windows printer name: ').strip()
        elif connection=='lan': config.update(host=input('Local printer IP or hostname: ').strip(),port=int(input('Printer TCP port [9100]: ') or 9100))
        else: config['mock_file']=str(args.config.parent/'mock-output.bin')
        result=request(config,'pair',{'code':code},False);config.update(result)
        config['dots']=int(input(f"Printable dots [{384 if config['width']==58 else 576}]: ") or (384 if config['width']==58 else 576))
        if config['dots'] not in (384,512,576) or (config['width']==58 and config['dots']!=384): raise ValueError('Unsupported dot width.')
        args.config.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(args.config,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as file: json.dump(config,file)
        print('Paired. Run the test command, then run the agent. Keep this config private.');return
    config=json.loads(args.config.read_text());validate_url(config['server'])
    if args.command=='test':
        image=render_receipt(test_receipt(),config['width'],config.get('dots'),config.get('font'))
        print(deliver(config,escpos_bytes(image,config.get('cut',False))));return
    server=local_status(config,args.status_port)
    ledger=Ledger(args.config.parent/'jobs.sqlite3')
    print(f"Agent running; local status http://127.0.0.1:{args.status_port}/health. Ctrl+C to stop.")
    try:
        while True:
            try:
                for id,status,detail in ledger.pending():
                    request(config,'ack',{'job':id,'status':status,'detail':detail});ledger.ack(id)
                job=request(config,'poll',{}).get('job')
                if job:
                    status,detail=ledger.process(job,config)
                    request(config,'ack',{'job':job['id'],'status':status,'detail':detail});ledger.ack(job['id'])
                    print(f'{status}: {detail}')
            except HTTPError as error:
                if error.code in (401,403): print('Pairing revoked or unauthorized. Pair again.');break
                print(f'Server unavailable ({error.code}); reconnecting. No automatic receipt retry.')
            except (OSError,ValueError): print('Connection unavailable; reconnecting. No automatic receipt retry.')
            time.sleep(2)
    except KeyboardInterrupt: pass
    finally: server.shutdown();ledger.db.close()

if __name__=='__main__': main()

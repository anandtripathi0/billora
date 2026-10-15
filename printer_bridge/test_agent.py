import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from .agent import Ledger, DeliveryError, validate_url, test_receipt, deliver, local_status
from .receipt import render_receipt, escpos_bytes

class BridgeTests(unittest.TestCase):
    def test_loopback_status_rejects_unknown_origins_and_print_requests(self):
        import socket
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        with socket.socket() as probe: probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        server=local_status({'server':'https://billora.example'},port)
        try:
            url=f'http://127.0.0.1:{port}/health'
            with urlopen(url) as response:
                self.assertEqual(response.status,200);self.assertIsNone(response.headers.get('Access-Control-Allow-Origin'))
            for req,code in [(Request(url,headers={'Origin':'https://evil.example'}),403),(Request(url,data=b'{}',method='POST'),405),(Request(url,headers={'Host':'evil.example'}),403)]:
                with self.assertRaises(HTTPError) as error:urlopen(req)
                self.assertEqual(error.exception.code,code)
        finally:server.shutdown();server.server_close()
    def test_both_widths_and_raster_qr(self):
        for width,dots in [(58,384),(80,576),(80,512)]:
            image=render_receipt(test_receipt(),width,dots)
            self.assertEqual(image.width,dots);self.assertGreater(image.height,300)
            raw=escpos_bytes(image);self.assertTrue(raw.startswith(b'\x1b@\x1dv0\x00'));self.assertNotIn(b'\x1dV',raw[-3:])
    def test_dedup_and_restart_uncertainty(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(Path(folder)/'jobs.sqlite3');writer=Mock(return_value='Mock accepted')
            job={'id':'one','width':58,'receipt':test_receipt()};config={'width':58}
            self.assertEqual(ledger.process(job,config,writer)[0],'spooled');ledger.process(job,config,writer);writer.assert_called_once()
            ledger.db.execute("INSERT INTO jobs(id,status,detail) VALUES ('two','started','')");ledger.db.commit();ledger.db.close()
            ledger=Ledger(Path(folder)/'jobs.sqlite3');job['id']='two'
            self.assertEqual(ledger.process(job,config,writer)[0],'uncertain');writer.assert_called_once();ledger.db.close()
    def test_disconnect_and_partial_delivery_results(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(Path(folder)/'jobs.sqlite3')
            for id,error,status in [('one',DeliveryError('offline'),'failed'),('two',DeliveryError('interrupted',True),'uncertain')]:
                job={'id':id,'width':80,'receipt':test_receipt()}
                self.assertEqual(ledger.process(job,{'width':80},Mock(side_effect=error))[0],status)
            ledger.db.close()
    def test_mock_transport_and_control_text_is_rasterized(self):
        with tempfile.TemporaryDirectory() as folder:
            r=test_receipt();r['business']['name']='Test\x1b\x1d malicious printer commands'
            raw=escpos_bytes(render_receipt(r,58));target=Path(folder)/'output.bin'
            deliver({'connection':'mock','mock_file':str(target)},raw)
            self.assertEqual(target.read_bytes(),raw);self.assertNotIn(b'malicious',raw)
    def test_server_requires_https_and_no_credential_url(self):
        for value in ['http://evil.example','https://user:pass@host','https://example.com/api','ftp://example.com']:
            with self.assertRaises(ValueError):validate_url(value)
        self.assertEqual(validate_url('http://localhost:3000/'),'http://localhost:3000')
    def test_wrong_width_never_contacts_printer(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(Path(folder)/'jobs.sqlite3');writer=Mock()
            self.assertEqual(ledger.process({'id':'x','width':58,'receipt':test_receipt()},{'width':80},writer)[0],'failed')
            writer.assert_not_called();ledger.db.close()

if __name__=='__main__':unittest.main()

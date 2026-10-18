import {test} from 'node:test';
import assert from 'node:assert/strict';
import {bufferToBase64, receiptBytes, validatePrinter} from '../src/printer-protocol';
import {upiURI} from '../src/receipt';

const invoice={id:'device-invoice-123',number:'M26-0000000010',date:'2026-10-18',
  business_snapshot:{name:'Billora Store',address:'Shop road',mobile:'9876543210',gstin:'27ABCDE1234F1Z5',upi_id:'test@upi',upi_payee_name:'Billora Store'},
  customer_snapshot:{name:'Customer',mobile:'9876543211'},items:[{description:'A'.repeat(70),quantity:'2',unit_price:'100.00',total:'200.00',gst_rate:'0'}],
  discount:'0.00',cgst:'0.00',sgst:'0.00',igst:'0.00',total:'200.00',paid_amount:'50.00',include_upi_qr:true};

test('Bluetooth selection validation normalizes MAC and rejects invalid stored settings',()=>{
  assert.equal(validatePrinter({transport:'bluetooth',address:' aa:bb:cc:dd:ee:ff ',width:58}).address,'AA:BB:CC:DD:EE:FF');
  for(const value of [{transport:'bluetooth',address:'printer',width:58},{transport:'lan',address:'256.1.1.1',width:80},{transport:'usb',address:'',width:58},{transport:'bluetooth',address:'AA:BB:CC:DD:EE:FF',width:72}])assert.throws(()=>validatePrinter(value as any));
  assert.equal(validatePrinter({transport:'lan',address:'192.168.0.10',width:80}).address,'192.168.0.10');
});
test('ESC/POS wraps both paper sizes and keeps the saved invoice totals and reference',()=>{
  for(const width of [58,80] as const){
    const bytes=receiptBytes({...invoice,include_upi_qr:false},width),text=Buffer.from(bytes.slice(2,-6)).toString('ascii');
    assert.deepEqual(bytes.slice(0,2),[27,64]);assert.deepEqual(bytes.slice(-3),[29,86,0]);
    assert.ok(text.includes('TOTAL Rs 200.00'));assert.ok(text.includes('Paid Rs 50.00'));assert.ok(text.includes('Due Rs 150.00'));
    assert.ok(text.includes('Ref device-invoice-123'));
    assert.ok(text.split('\n').every(line=>line.length<=(width===58?32:48)));
    assert.equal(bufferToBase64(bytes),Buffer.from(bytes).toString('base64'));
  }
});
test('thermal QR payload encodes only unpaid amount with correct ESC/POS byte length',()=>{
  const bytes=receiptBytes(invoice,58),buffer=Buffer.from(bytes),uri=Buffer.from(upiURI(invoice));
  const position=buffer.indexOf(uri);assert.ok(position>0);
  assert.deepEqual(bytes.slice(position-3,position),[49,80,48]);
  assert.equal(bytes[position-5]+256*bytes[position-4],uri.length+3);
  assert.ok(uri.toString().includes('am=150.00'));
  const paid=Buffer.from(receiptBytes({...invoice,paid_amount:'200.00'},58));
  assert.equal(paid.indexOf('upi://pay'),-1);
});
test('receipt cannot inject ESC/POS controls from product text and handles missing customer mobile',()=>{
  const bytes=receiptBytes({...invoice,number:'',include_upi_qr:false,customer_snapshot:{name:'Guest'},items:[{...invoice.items[0],description:'Rice\x1b@\x1dV\x00'}]},58);
  assert.equal(bytes.filter(byte=>byte===27).length,1);
  assert.ok(Buffer.from(bytes).toString('ascii').includes('PROVISIONAL - NOT A TAX INVOICE'));
});

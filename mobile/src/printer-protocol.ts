import {upiURI} from './receipt';
import {decimal, scaled} from './money';

export type Printer = {transport:'lan'|'bluetooth'|'usb'; address:string; width:58|80; name?:string};
export function validatePrinter(value: Printer): Printer {
  if(!value || !['bluetooth','lan','usb'].includes(value.transport))throw new Error('Choose a printer connection.');
  const address=String(value.address || '').trim();
  if(!address)throw new Error('Select a printer first.');
  if(value.width!==58 && value.width!==80)throw new Error('Choose 58 mm or 80 mm paper.');
  if(value.transport==='bluetooth' && !/^([0-9a-f]{2}:){5}[0-9a-f]{2}$/i.test(address))throw new Error('Select a paired Bluetooth printer.');
  if(value.transport==='lan' && (!/^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$/.test(address) || address.split('.').some(n=>Number(n)>255)))throw new Error('Enter a valid printer IPv4 address.');
  return {...value,address:value.transport==='bluetooth'?address.toUpperCase():address};
}

export const bufferToBase64=(bytes:number[])=>{
  const chars='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';let out='';
  for(let i=0;i<bytes.length;i+=3){const n=(bytes[i]<<16)|((bytes[i+1]||0)<<8)|(bytes[i+2]||0);out+=chars[(n>>>18)&63]+chars[(n>>>12)&63]+(i+1<bytes.length?chars[(n>>>6)&63]:'=')+(i+2<bytes.length?chars[n&63]:'=');}return out;
};
export function receiptBytes(invoice:any,width:58|80) {
  const columns=width===58?32:48,bytes:number[]=[27,64];
  const line=(value:unknown)=>{
    // Generic ESC/POS uses an ASCII code page; PDFs retain Unicode/Hindi names.
    const text=String(value ?? '').replace(/₹/g,'Rs ').replace(/[^\x20-\x7e]/g,'?');
    for(let i=0;i<Math.max(1,text.length);i+=columns)bytes.push(...Array.from(text.slice(i,i+columns),c=>c.charCodeAt(0)),10);
  };
  line(invoice.business_snapshot.name);line(invoice.business_snapshot.address||'');line(invoice.business_snapshot.mobile||'');
  if(invoice.business_snapshot.gstin)line('GSTIN '+invoice.business_snapshot.gstin);
  line(invoice.number||'PROVISIONAL - NOT A TAX INVOICE');line(invoice.date);line('Ref '+invoice.id);line(invoice.customer_snapshot.name);line(invoice.customer_snapshot.mobile);
  if(invoice.cancelled_at)line('CANCELLED');
  if(invoice.customer_snapshot.gstin)line('Customer GSTIN '+invoice.customer_snapshot.gstin);
  if(invoice.supply_state)line('Place of supply '+invoice.supply_state);
  line('-'.repeat(columns));
  for(const item of invoice.items){line(item.description);if(item.hsn_code)line('HSN '+item.hsn_code);if(invoice.gst_enabled)line('GST '+item.gst_rate+'%');line(`${item.quantity} x Rs ${item.unit_price} = Rs ${item.total}`);}
  line(`Discount Rs ${invoice.discount}`);line(`CGST ${invoice.cgst} SGST ${invoice.sgst} IGST ${invoice.igst}`);
  line(`TOTAL Rs ${invoice.total}`);line(`Paid Rs ${invoice.paid_amount}`);line(`Due Rs ${decimal(scaled(invoice.total)-scaled(invoice.paid_amount))}`);
  const uri=upiURI(invoice);
  if(uri){
    // Standard ESC/POS QR command set. Printer firmware support is required.
    const data=Array.from(uri,c=>c.charCodeAt(0)),length=data.length+3;
    bytes.push(29,40,107,4,0,49,65,50,0,29,40,107,3,0,49,67,5,29,40,107,3,0,49,69,48);
    bytes.push(29,40,107,length&255,(length>>8)&255,49,80,48,...data,29,40,107,3,0,49,81,48,10);
    line('Verify payment separately.');
  }
  line(invoice.business_snapshot.invoice_footer||'Thank you!');bytes.push(10,10,10,29,86,0);return bytes;
}

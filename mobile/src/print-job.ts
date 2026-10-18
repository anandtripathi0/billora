import type {Store} from './store';
import {bufferToBase64, receiptBytes, validatePrinter, Printer} from './printer-protocol';

let printing=false;
export async function sendReceipt(store:Store, invoice:any, io:{
  prepare:(printer:Printer)=>Promise<void>;
  confirmReprint:()=>Promise<boolean>;
  send:(printer:Printer, payload:string)=>Promise<void>;
  active:()=>boolean;
}) {
  if(printing)throw new Error('A receipt is already being sent. Please wait.');
  printing=true;
  try {
    const row=await store.db.getFirstAsync<{value:string}>('SELECT value FROM app_settings WHERE business=? AND key=?',store.business,'printer');
    if(!row)throw new Error('Open Printer setup and select your thermal printer first.');
    const printer=validatePrinter(JSON.parse(row.value));
    await io.prepare(printer);
    if(!io.active())return false;
    const key=`print:${invoice.id}`;
    const old=await store.db.getFirstAsync('SELECT value FROM app_settings WHERE business=? AND key=?',store.business,key);
    if(old && !(await io.confirmReprint()))return false;
    if(!io.active())return false;
    const payload=bufferToBase64(receiptBytes(invoice,printer.width));
    // A failed transport may have reached paper. Retain the attempt until explicit reprint.
    await store.transaction(tx=>tx.runAsync('INSERT OR REPLACE INTO app_settings VALUES(?,?,?)',store.business,key,'attempted'));
    if(!io.active())return false;
    await io.send(printer,payload);
    return true;
  } finally {printing=false;}
}

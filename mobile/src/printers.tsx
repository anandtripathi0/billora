import React, {useEffect, useState} from 'react';
import {Alert, NativeModules, PermissionsAndroid, Platform, Pressable, Text, TextInput, View} from 'react-native';
import {Store} from './store';
import {upiURI} from './receipt';
import {decimal, scaled} from './money';

type Printer = {transport:'lan'|'bluetooth'|'usb'; address:string; width:58|80};
const native=NativeModules.BilloraPrinter;
const bufferToBase64=(bytes:number[])=>{
  const chars='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';let out='';
  for(let i=0;i<bytes.length;i+=3){const n=(bytes[i]<<16)|((bytes[i+1]||0)<<8)|(bytes[i+2]||0);out+=chars[(n>>>18)&63]+chars[(n>>>12)&63]+(i+1<bytes.length?chars[(n>>>6)&63]:'=')+(i+2<bytes.length?chars[n&63]:'=');}return out;
};
export function receiptBytes(invoice:any,width:58|80) {
  const columns=width===58?32:48,bytes:number[]=[27,64];
  const line=(value:string)=>{
    // Generic ESC/POS uses an ASCII code page; PDFs retain Unicode/Hindi names.
    const text=value.replace(/₹/g,'Rs ').replace(/[^\x20-\x7e]/g,'?');
    for(let i=0;i<Math.max(1,text.length);i+=columns)bytes.push(...Array.from(text.slice(i,i+columns),c=>c.charCodeAt(0)),10);
  };
  line(invoice.business_snapshot.name);line(invoice.business_snapshot.address||'');line(invoice.business_snapshot.mobile||'');
  if(invoice.business_snapshot.gstin)line('GSTIN '+invoice.business_snapshot.gstin);
  line(invoice.number||'PROVISIONAL - NOT A TAX INVOICE');line(invoice.date);line(invoice.customer_snapshot.name);line(invoice.customer_snapshot.mobile);
  line('-'.repeat(columns));
  for(const item of invoice.items){line(item.description);line(`${item.quantity} x Rs ${item.unit_price} = Rs ${item.total}`);}
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
async function permission(transport:string){
  if(!native)throw new Error('Direct printing requires the native Billora APK. Use Android system printing as fallback.');
  if(transport==='bluetooth'&&Platform.OS==='android'&&Number(Platform.Version)>=31){const granted=await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT);if(granted!==PermissionsAndroid.RESULTS.GRANTED)throw new Error('Nearby devices permission was denied.');}
}
let printing=false;
export async function thermalPrint(store:Store,invoice:any){
  if(printing)return;printing=true;
  try{
    const row=await store.db.getFirstAsync<{value:string}>('SELECT value FROM app_settings WHERE business=? AND key=?',store.business,'printer');
    if(!row)throw new Error('Configure a printer in Settings, or use Android system printing.');
    const printer:Printer=JSON.parse(row.value);await permission(printer.transport);
    const key=`print:${invoice.id}`;
    const old=await store.db.getFirstAsync('SELECT value FROM app_settings WHERE business=? AND key=?',store.business,key);
    if(old){const confirmed=await new Promise<boolean>(resolve=>Alert.alert('Reprint receipt?','A previous print was attempted. Check the printer to avoid a duplicate receipt.',[{text:'Cancel',onPress:()=>resolve(false)},{text:'Reprint',onPress:()=>resolve(true)}],{cancelable:false}));if(!confirmed)return;}
    await store.transaction(tx=>tx.runAsync('INSERT OR REPLACE INTO app_settings VALUES(?,?,?)',store.business,key,'attempted'));
    await native.print(printer.transport,printer.address,bufferToBase64(receiptBytes(invoice,printer.width)));
    Alert.alert('Sent to printer','Check the physical receipt. Transport completion does not prove paper was printed.');
  }catch(e){throw new Error(`${e instanceof Error?e.message:'Printer failed.'} If a print was attempted, check the paper before retrying.`);}finally{printing=false;}
}
export function PrinterPanel({store}:{store:Store}) {
  const [transport,setTransport]=useState<Printer['transport']>('lan'),[address,setAddress]=useState(''),[width,setWidth]=useState<58|80>(80),[busy,setBusy]=useState(false);
  useEffect(()=>{void store.db.getFirstAsync<{value:string}>('SELECT value FROM app_settings WHERE business=? AND key=?',store.business,'printer').then(r=>{if(r){const p=JSON.parse(r.value);setTransport(p.transport);setAddress(p.address);setWidth(p.width);}});},[store]);
  const run=async(fn:()=>Promise<void>)=>{if(busy)return;setBusy(true);try{await fn();}catch(e){Alert.alert('Printer',(e as Error).message);}finally{setBusy(false);}};
  const button=(title:string,onPress:()=>void)=><Pressable disabled={busy} onPress={onPress} style={{backgroundColor:'#F4EDE3',padding:16,borderRadius:12,marginVertical:5}}><Text style={{color:'#40352B'}}>{title}</Text></Pressable>;
  return <View style={{padding:18,backgroundColor:'#FFFDF9',borderRadius:20,marginVertical:12}}><Text style={{fontSize:20,fontWeight:'700',color:'#40352B'}}>Thermal printer</Text>
    {button(`Connection: ${transport} (tap to change)`,()=>setTransport(transport==='lan'?'bluetooth':transport==='bluetooth'?'usb':'lan'))}
    <TextInput accessibilityLabel="Printer address" style={{padding:14,borderWidth:1,borderColor:'#E8DCCB',borderRadius:12}} placeholder={transport==='lan'?'LAN IPv4 address (port 9100)':transport==='bluetooth'?'Paired Bluetooth MAC':'USB device name from list'} value={address} onChangeText={setAddress} autoCapitalize="none"/>
    {button(`Receipt width: ${width} mm`,()=>setWidth(width===80?58:80))}
    {button('Pair / list available printers',()=>void run(async()=>{await permission(transport);if(transport==='bluetooth')await native.pair();const devices=transport==='lan'?[]:await native.devices(transport);Alert.alert('Printers',devices.length?devices.map((d:any)=>`${d.name}\n${d.address}`).join('\n\n'):'For LAN, enter the printer IP. For Bluetooth, pair in Android Settings and return to list paired devices.');}))}
    {button('Save printer',()=>void run(async()=>{await store.transaction(tx=>tx.runAsync('INSERT OR REPLACE INTO app_settings VALUES(?,?,?)',store.business,'printer',JSON.stringify({transport,address,width})));Alert.alert('Saved','Use Test print to check compatibility.');}))}
    {button('Test print',()=>void run(async()=>{await permission(transport);await native.print(transport,address,bufferToBase64([27,64,...Array.from('BILLORA TEST\nCheck width and legibility.\n\n\n',c=>c.charCodeAt(0))]));Alert.alert('Test sent','Check the printer. No automatic retry is performed.');}))}
    <Text style={{color:'#675A4B',lineHeight:20,marginTop:10}}>Generic ESC/POS: paired Bluetooth Classic SPP, LAN port 9100, USB bulk OUT. BLE-only and proprietary printers may need a vendor Android print service. Direct hardware paths are unverified. Generic receipts use ASCII; use PDF for Hindi text.</Text></View>;
}

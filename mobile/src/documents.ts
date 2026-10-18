import * as Print from 'expo-print';
import * as Sharing from 'expo-sharing';
import * as FileSystem from 'expo-file-system/legacy';
import {invoiceHTML} from './receipt';
export {invoiceHTML, upiURI, qrData} from './receipt';

let printBusy = false;
export async function printInvoice(invoice: any, width?: 58 | 80) {
  if (printBusy) return;
  printBusy = true;
  try {await Print.printAsync({html: invoiceHTML(invoice, width)});} finally {printBusy = false;}
}
export async function shareInvoice(invoice: any) {
  const {uri} = await Print.printToFileAsync({html: invoiceHTML(invoice)});
  try {await Sharing.shareAsync(uri, {mimeType: 'application/pdf', dialogTitle: 'Share invoice — choose WhatsApp or save PDF'});}
  finally {await FileSystem.deleteAsync(uri, {idempotent: true});}
}
export async function shareBackup(json: string) {
  const uri = `${FileSystem.cacheDirectory}billora-backup-${Date.now()}.json`;
  await FileSystem.writeAsStringAsync(uri, json);
  try {await Sharing.shareAsync(uri, {mimeType: 'application/json', dialogTitle: 'Save confidential Billora backup'});}
  finally {await FileSystem.deleteAsync(uri, {idempotent: true});}
}

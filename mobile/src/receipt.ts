import qrcode from 'qrcode-generator';
import {decimal, scaled} from './money';

export const escape = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]!));
export function upiURI(invoice: any) {
  const unpaid = scaled(invoice.total) - scaled(invoice.paid_amount), b = invoice.business_snapshot;
  if (!invoice.include_upi_qr || unpaid <= 0 || !b.upi_id || !b.upi_payee_name) return '';
  return 'upi://pay?' + Object.entries({pa: b.upi_id, pn: b.upi_payee_name, am: decimal(unpaid), cu: 'INR', tn: `Bill ${invoice.number || invoice.id}`, tr: invoice.id}).map(([k,v]) => `${k}=${encodeURIComponent(v)}`).join('&');
}
export function qrData(uri: string) {
  const qr = qrcode(0, 'M'); qr.addData(uri); qr.make(); return qr.createDataURL(5, 8);
}
export function invoiceHTML(invoice: any, width?: 58 | 80) {
  const b = invoice.business_snapshot, c = invoice.customer_snapshot, uri = upiURI(invoice);
  return `<!doctype html><html><head><meta charset="utf-8"><style>
  @page {size:${width ? `${width}mm auto` : 'A4'};margin:${width ? '3mm' : '14mm'}}
  body{font-family:sans-serif;color:#40352B;font-size:${width ? '10' : '13'}px;margin:0}h1{font-size:22px}h2{font-size:16px}p{margin:5px 0}
  table{width:100%;border-collapse:collapse;margin:18px 0}td,th{padding:6px 2px;border-bottom:1px solid #E8DCCB;text-align:right;overflow-wrap:anywhere}td:first-child,th:first-child{text-align:left}
  .total{font-size:20px;font-weight:bold}.note{padding:8px;background:#F4EDE3}.qr{width:150px;height:150px}footer{margin-top:20px}</style></head><body>
  <h1>${escape(b.name)}</h1><p>${escape(b.address)}</p><p>${escape(b.mobile)} ${b.gstin ? `· GSTIN ${escape(b.gstin)}` : ''}</p>
  <h2>${invoice.number ? `${invoice.gst_enabled ? 'Tax invoice' : 'Invoice'} ${escape(invoice.number)}` : 'PROVISIONAL BILL — NOT A TAX INVOICE'}</h2>
  <p>${escape(invoice.date)} · Device reference ${escape(invoice.id)}</p>
  ${!invoice.number ? '<p class="note">Awaiting an official number. Retain this provisional copy; finalization creates a separately labelled final copy.</p>' : ''}
  <h2>${escape(c.name)}</h2><p>${escape(c.mobile)}</p><p>${escape(c.address)}</p><p>${c.gstin ? `Customer GSTIN ${escape(c.gstin)} · ` : ''}Place of supply: ${escape(invoice.supply_state)}</p>
  <table><thead><tr><th>Product</th><th>Qty</th><th>Rate</th><th>Total</th></tr></thead><tbody>${invoice.items.map((i:any) => `<tr><td>${escape(i.description)}<br>${i.hsn_code ? `HSN ${escape(i.hsn_code)}` : ''}${invoice.gst_enabled ? ` · GST ${escape(i.gst_rate)}%` : ''}</td><td>${escape(i.quantity)} ${escape(i.unit)}</td><td>₹${escape(i.unit_price)}</td><td>₹${escape(i.total)}</td></tr>`).join('')}</tbody></table>
  <p>Subtotal ₹${escape(invoice.subtotal)} · Discount ₹${escape(invoice.discount)}</p>
  <p>CGST ₹${escape(invoice.cgst)} · SGST ₹${escape(invoice.sgst)} · IGST ₹${escape(invoice.igst)}</p>
  <p class="total">Total ₹${escape(invoice.total)}</p><p>Paid ₹${escape(invoice.paid_amount)} · Pending ₹${decimal(scaled(invoice.total)-scaled(invoice.paid_amount))}</p>
  ${uri ? `<img class="qr" src="${qrData(uri)}"><p>Scan to pay the pending amount. Verify payment separately.</p>` : ''}
  <footer>${escape(b.invoice_footer || 'Thank you for shopping with us!')}</footer></body></html>`;
}

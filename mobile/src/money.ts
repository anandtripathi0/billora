/** Same ROUND_HALF_UP and largest-remainder rules as billing.services.calculate_lines.
 * BigInt intermediate arithmetic avoids IEEE floating-point tax allocation errors.
 */
export function scaled(value: string | number, decimals = 2): number {
  const text = String(value).trim();
  if (!new RegExp(`^-?\\d+(?:\\.\\d{1,${decimals}})?$`).test(text)) throw new Error(`Use at most ${decimals} decimal places.`);
  const negative = text.startsWith('-');
  const [whole, fraction = ''] = text.replace('-', '').split('.');
  const n = BigInt(whole) * 10n ** BigInt(decimals) + BigInt(fraction.padEnd(decimals, '0'));
  if (n > 99999999999999n) throw new Error('Amount exceeds the supported limit.');
  return Number(negative ? -n : n);
}
export function decimal(value: number, places = 2): string {
  if (!Number.isSafeInteger(value)) throw new Error('Invalid exact amount.');
  const negative = value < 0 ? '-' : '';
  const digits = String(Math.abs(value)).padStart(places + 1, '0');
  return negative + digits.slice(0, -places) + '.' + digits.slice(-places);
}
export const rupees = (value: number) => `₹${decimal(value)}`;
const round = (n: bigint, d: bigint) => (n * 2n + d) / (d * 2n);
export type Line = {product: string; quantity: string; unit_price: string; gst_rate: string; price_includes_tax: boolean; description?: string; sku?: string; unit?: string; hsn_code?: string};
export function calculate(items: Line[], discountText: string, gst: boolean, interstate: boolean) {
  if (!items.length || items.length > 100) throw new Error('Add 1–100 products.');
  if (new Set(items.map(x => x.product)).size !== items.length) throw new Error('Combine duplicate products.');
  const lines = items.map(item => {
    const quantity = scaled(item.quantity, 3), price = scaled(item.unit_price), rate = gst ? scaled(item.gst_rate) : 0;
    if (quantity <= 0 || quantity > 999999999999 || price < 0 || price > 999999999999 || rate < 0 || rate > 10000) throw new Error('Invalid quantity, price or GST.');
    const subtotal = round(BigInt(price) * BigInt(quantity), 1000n);
    return {...item, subtotal, discount: 0n, cgst: 0n, sgst: 0n, igst: 0n, total: 0n, rate: BigInt(rate)};
  });
  const subtotal = lines.reduce((a, x) => a + x.subtotal, 0n), discount = BigInt(scaled(discountText));
  if (discount < 0n || discount > subtotal || discount > 999999999999n) throw new Error('Discount must be between zero and subtotal within the supported limit.');
  const remainders = lines.map((line, index) => {
    line.discount = subtotal ? discount * line.subtotal / subtotal : 0n;
    return {index, remainder: subtotal ? discount * line.subtotal % subtotal : 0n};
  }).sort((a, b) => a.remainder === b.remainder ? b.index - a.index : a.remainder > b.remainder ? -1 : 1);
  const left = Number(discount - lines.reduce((a, x) => a + x.discount, 0n));
  for (const {index} of remainders.slice(0, left)) lines[index].discount++;
  for (const line of lines) {
    let taxable = line.subtotal - line.discount;
    if (line.price_includes_tax && gst) {
      const net = round(taxable * 10000n, 10000n + line.rate), tax = taxable - net;
      line.cgst = interstate ? 0n : round(tax, 2n);
      line.sgst = interstate ? 0n : tax - line.cgst;
      line.igst = interstate ? tax : 0n;
      line.subtotal -= tax; taxable = net;
    } else if (interstate) line.igst = round(taxable * line.rate, 10000n);
    else line.cgst = line.sgst = round(taxable * line.rate, 20000n);
    line.total = taxable + line.cgst + line.sgst + line.igst;
  }
  const totals = {subtotal: 0, discount: 0, cgst: 0, sgst: 0, igst: 0, total: 0};
  for (const key of Object.keys(totals) as (keyof typeof totals)[]) {
    const total = lines.reduce((a, x) => a + x[key], 0n);
    if (total > 99999999999999n) throw new Error('Invoice exceeds the supported limit.');
    totals[key] = Number(total);
  }
  return {totals, lines: lines.map(({rate, ...line}) => ({...line,
    subtotal: Number(line.subtotal), discount: Number(line.discount), cgst: Number(line.cgst), sgst: Number(line.sgst), igst: Number(line.igst), total: Number(line.total)}))};
}
export function normalizeMobile(value: string) {
  let n = value.replace(/[\s()+.-]/g, '');
  if (n.length === 10) n = '91' + n;
  if (!/^91[6-9][0-9]{9}$/.test(n)) throw new Error('Enter a valid Indian mobile number.');
  return '+' + n;
}
export function indiaDate(now = new Date()) {
  return new Date(now.getTime() + 330 * 60000).toISOString().slice(0, 10);
}

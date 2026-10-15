// Integer arithmetic mirrors Django's per-line rounding and largest-remainder discount allocation.
export function billingTotals(lines:{quantity:string;price:string;gst:string;inclusive?:boolean}[], discount:string, gst:boolean, interstate:boolean) {
  const fixed=(v:string,places:number)=>{if(!/^\d*(\.\d*)?$/.test(v))throw Error('Enter valid positive amounts.');const [a,b='']=v.split('.');if(b.length>places)throw Error(`Use at most ${places} decimal places.`);return BigInt(a||'0')*10n**BigInt(places)+BigInt(b.padEnd(places,'0')||'0');};
  const round=(n:bigint,d:bigint)=>(n+d/2n)/d;
  const values=lines.map(l=>({subtotal:round(fixed(l.quantity,3)*fixed(l.price,2),1000n),rate:gst?fixed(l.gst,2):0n,discount:0n,inclusive:l.inclusive}));
  const subtotal=values.reduce((a,l)=>a+l.subtotal,0n), off=fixed(discount,2);
  if(off>subtotal)throw Error('Discount cannot exceed subtotal.');
  for(const line of values)line.discount=subtotal?off*line.subtotal/subtotal:0n;
  let remaining=off-values.reduce((a,l)=>a+l.discount,0n);
  const order=values.map((l,i)=>({i,remainder:subtotal?off*l.subtotal%subtotal:0n})).sort((a,b)=>a.remainder===b.remainder?b.i-a.i:a.remainder>b.remainder?-1:1);
  for(const row of order){if(remaining<=0n)break;values[row.i].discount++;remaining--;}
  let tax=0n, includedTax=0n;
  for(const l of values)if(gst){
    if(l.inclusive){const net=l.subtotal-l.discount;const included=net-round(net*10000n,10000n+l.rate);tax+=included;includedTax+=included;}
    else tax+=interstate?round((l.subtotal-l.discount)*l.rate,10000n):2n*round((l.subtotal-l.discount)*l.rate,20000n);
  }
  const money=(n:bigint)=>`${n/100n}.${(n%100n).toString().padStart(2,'0')}`;
  return {subtotal:money(subtotal-includedTax),discount:money(off),tax:money(tax),total:money(subtotal-off+tax-includedTax)};
}

import { describe, it, expect } from 'vitest';
import { billingTotals } from '../src/lib/billing-totals';
describe('live billing arithmetic',()=>{
  it('extracts included tax after discount without increasing the retail price',()=>{for(const interstate of [false,true])expect(billingTotals([{quantity:'2',price:'118',gst:'18',inclusive:true}],'11.80',true,interstate)).toEqual({subtotal:'201.80',discount:'11.80',tax:'34.20',total:'224.20'});});
  it('handles mixed tax bases and fractional national reference quantities',()=>{
    expect(billingTotals([{quantity:'1',price:'118',gst:'18',inclusive:true},{quantity:'1',price:'100',gst:'18'}],'0',true,false).total).toBe('236.00');
    expect(billingTotals([{quantity:'1.125',price:'47.48',gst:'unknown',inclusive:true}],'0',false,false).total).toBe('53.42');
  });
  it('matches intra and interstate discounted GST',()=>{for(const interstate of [false,true])expect(billingTotals([{quantity:'2',price:'100',gst:'18'}],'10',true,interstate)).toEqual({subtotal:'200.00',discount:'10.00',tax:'34.20',total:'224.20'});});
  it('allocates tiny discounts without negative lines',()=>{expect(billingTotals(Array.from({length:8},()=>({quantity:'1',price:'.01',gst:'0'})),'.04',false,false).total).toBe('0.04');});
  it('rounds fractional quantities and edited prices',()=>{expect(billingTotals([{quantity:'.125',price:'12.34',gst:'0'}],'0',false,false).total).toBe('1.54');});
  it('rejects excess discount and malformed input',()=>{expect(()=>billingTotals([{quantity:'1',price:'10',gst:'0'}],'11',false,false)).toThrow();expect(()=>billingTotals([{quantity:'1',price:'-1',gst:'0'}],'0',false,false)).toThrow();});
});

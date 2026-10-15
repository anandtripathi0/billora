import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { InvoiceTable, Pagination, Badge, Field } from '@/components/common';
import { Button } from '@/components/ui/button';
import { currency } from '@/lib/utils';

describe('invoice workspace components',()=>{
  it('shows a useful empty invoice state without fake records',()=>{render(<InvoiceTable rows={[]}/>);expect(screen.getByRole('link',{name:'Create an invoice'})).toHaveAttribute('href','/invoices/new');expect(screen.queryByRole('table')).not.toBeInTheDocument();});
  it('renders saved customer and payment status with a real detail link',()=>{render(<InvoiceTable rows={[{id:'real-id',number:'INV-000001',customer_name:'Priya',date:'2026-10-12',total:'236.00',status:'partial'}]}/>);expect(screen.getByText('Priya')).toBeInTheDocument();expect(screen.getByText('Partial')).toBeInTheDocument();expect(screen.getByRole('link',{name:'INV-000001'})).toHaveAttribute('href','/invoices/real-id');});
  it('prevents invalid pagination and advances to the next page',()=>{const change=vi.fn();render(<Pagination page={1} next="next" previous={null} count={30} onChange={change}/>);expect(screen.getByRole('button',{name:'Previous page'})).toBeDisabled();fireEvent.click(screen.getByRole('button',{name:'Next page'}));expect(change).toHaveBeenCalledWith(2);});
  it('keeps disabled submission buttons disabled',()=>{const submit=vi.fn();render(<Button disabled onClick={submit}>Generate invoice</Button>);fireEvent.click(screen.getByText('Generate invoice'));expect(submit).not.toHaveBeenCalled();});
  it('formats Indian currency with lakh grouping',()=>{expect(currency('123456.50')).toContain('1,23,456.50');});
  it('associates hints as descriptions without changing the field label',()=>{render(<Field label="Password" hint="At least ten characters"><input type="password"/></Field>);expect(screen.getByLabelText('Password',{exact:true})).toHaveAccessibleDescription('At least ten characters');});
});

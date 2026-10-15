"""Generate PDFs in memory from saved snapshots. No disk or object storage."""
import base64
import io
from pathlib import Path
from xml.sax.saxutils import escape
import qrcode
import reportlab
from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from .services import upi_uri

# ReportLab includes these licensed fonts on Windows and Linux.
_fonts = Path(reportlab.__file__).parent / 'fonts'
pdfmetrics.registerFont(TTFont('Billora', str(_fonts / 'Vera.ttf')))
pdfmetrics.registerFont(TTFont('BilloraBold', str(_fonts / 'VeraBd.ttf')))
pdfmetrics.registerFontFamily('Billora', normal='Billora', bold='BilloraBold')
INK = colors.HexColor('#40352B')
BROWN = colors.HexColor('#79634D')
CREAM = colors.HexColor('#F4EDE3')
BORDER = colors.HexColor('#E8DCCB')
STYLES = getSampleStyleSheet()
STYLES.add(ParagraphStyle('BilloraBody', fontName='Billora', fontSize=8.5, leading=13, textColor=INK, spaceAfter=5, wordWrap='CJK'))
STYLES.add(ParagraphStyle('BilloraTitle', parent=STYLES['BilloraBody'], fontName='BilloraBold', fontSize=21, leading=27, textColor=BROWN, spaceAfter=10))
STYLES.add(ParagraphStyle('BilloraHeading', parent=STYLES['BilloraBody'], fontName='BilloraBold', fontSize=11, leading=16, spaceAfter=8))


def paragraph(text, style='BilloraBody'):
    # User names/notes never become executable XML or image resource paths.
    return Paragraph(escape(str('' if text is None else text)).replace('\n', '<br/>'), STYLES[style])


def qr_data(uri):
    if not uri:
        return ''
    output = io.BytesIO()
    qrcode.make(uri, box_size=5, border=4).save(output, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()


def safe_fetcher(url, *args, **kwargs):
    """Only accept inline PNG bytes, never fetch a URL or read a local path."""
    if not url.startswith('data:image/png;base64,') or len(url) > 300000:
        raise ValueError('Only inline PNG images are allowed.')
    raw = base64.b64decode(url.split(',', 1)[1], validate=True)
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Invalid PNG image.')
    return io.BytesIO(raw)


def table(rows, widths=None, header=True):
    result = Table([[paragraph(value) for value in row] for row in rows], colWidths=widths, repeatRows=1 if header else 0, hAlign='LEFT')
    commands = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8), ('TOPPADDING', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 7), ('LINEBELOW', (0, 0), (-1, -1), .4, BORDER)]
    if header:
        commands.append(('BACKGROUND', (0, 0), (-1, 0), CREAM))
    result.setStyle(TableStyle(commands))
    return result


def page_footer(canvas, document):
    canvas.saveState()
    canvas.setFont('Billora', 7)
    canvas.setFillColor(BROWN)
    canvas.drawString(document.leftMargin, 12 * mm, 'Created with Billora')
    canvas.drawRightString(document.pagesize[0] - document.rightMargin, 12 * mm, f'Page {document.page}')
    canvas.restoreState()


def build_pdf(story, title, wide=False):
    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=landscape(A4) if wide else A4,
                                 rightMargin=17 * mm, leftMargin=17 * mm, topMargin=17 * mm,
                                 bottomMargin=22 * mm, title=title, author='Billora')
    document.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    return buffer.getvalue()


def invoice_pdf(invoice):
    business, customer = invoice.business_snapshot, invoice.customer_snapshot
    story = []
    if invoice.logo_data:
        logo = Image(safe_fetcher(invoice.logo_data))
        scale = min(110 / logo.imageWidth, 55 / logo.imageHeight)
        logo.drawWidth, logo.drawHeight = logo.imageWidth * scale, logo.imageHeight * scale
        logo.hAlign = 'LEFT'
        story += [logo, Spacer(1, 10)]
    story += [paragraph(business['name'], 'BilloraTitle'), paragraph(business.get('address')),
              paragraph(f"Phone: {business.get('mobile', '')}")]
    if business.get('gstin'):
        story.append(paragraph(f"GSTIN: {business['gstin']}"))
    story += [Spacer(1, 12), paragraph('TAX INVOICE' if invoice.gst_enabled else 'INVOICE', 'BilloraHeading'), table([
        ['BILL TO', 'INVOICE DETAILS'],
        [f"{customer['name']}\n{customer.get('address', '')}\nPhone: {customer.get('mobile', '')}" +
         (f"\nGSTIN: {customer['gstin']}" if customer.get('gstin') else ''),
         f"{invoice.number}\nDate: {invoice.date:%d %b %Y}\nStatus: {invoice.status.upper()}" +
         (f"\nDue: {invoice.due_date:%d %b %Y}" if invoice.due_date else '')],
    ], [88 * mm, 88 * mm]), Spacer(1, 16)]
    rows = [['PRODUCT / HSN', 'QTY', 'UNIT (INR)', 'DISCOUNT', 'TAX', 'TOTAL (INR)']]
    for item in invoice.ordered_items:
        tax = item.cgst + item.sgst + item.igst
        rows.append([f'{item.description}\n{item.sku}' + (f' · HSN {item.hsn_code}' if item.hsn_code else ''),
                     f'{item.quantity.normalize():f} {item.unit}', f'{item.unit_price:.2f}' + (' incl. tax' if item.price_includes_tax else ''),
                     f'{item.discount:.2f}', f'{tax:.2f}', f'{item.total:.2f}'])
    story += [table(rows, [60 * mm, 20 * mm, 26 * mm, 24 * mm, 20 * mm, 26 * mm]), Spacer(1, 16)]
    totals = [['Subtotal', f'INR {invoice.subtotal:.2f}'], ['Discount', f'INR {invoice.discount:.2f}']]
    if invoice.gst_enabled:
        totals += [['CGST', f'INR {invoice.cgst:.2f}'], ['SGST', f'INR {invoice.sgst:.2f}'], ['IGST', f'INR {invoice.igst:.2f}']]
    totals += [['GRAND TOTAL', f'INR {invoice.total:.2f}'], ['Paid', f'INR {invoice.paid_amount:.2f}'], ['BALANCE DUE', f'INR {invoice.balance:.2f}']]
    if invoice.cancelled_at:
        totals += [['Refund recorded', f'INR {invoice.paid_amount:.2f}']]
        story += [paragraph('CANCELLED — ' + invoice.cancellation_reason, 'BilloraHeading')]
    summary = table(totals, [48 * mm, 44 * mm], header=False)
    summary.hAlign = 'RIGHT'
    story += [KeepTogether([summary]), Spacer(1, 16)]
    uri = upi_uri(invoice)
    if uri:
        qr = Image(safe_fetcher(qr_data(uri)), width=35 * mm, height=35 * mm)
        payment = Table([[qr, paragraph(f"Scan to pay INR {invoice.balance:.2f}\n{business['upi_payee_name']}\n{business['upi_id']}\nReference: {invoice.number}\nPayment is confirmed separately by the business.")]], colWidths=[42 * mm, 134 * mm])
        payment.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('BACKGROUND', (0, 0), (-1, -1), CREAM), ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 10)]))
        story += [KeepTogether([payment]), Spacer(1, 16)]
    if invoice.notes:
        story += [paragraph('Notes', 'BilloraHeading'), paragraph(invoice.notes)]
    story += [Spacer(1, 10), paragraph(business.get('invoice_footer', 'Thank you for your business!'))]
    return build_pdf(story, invoice.number)


def render_pdf(template, context):
    if template == 'billing/invoice.html':
        return invoice_pdf(context['invoice'])
    if template != 'billing/report.html':
        raise ValueError('Unknown PDF layout.')
    summary = context['summary']
    title = f"{context['business'].name} · {context['kind'].title()} report"
    story = [paragraph(title, 'BilloraTitle'), paragraph(f"{context['start']} to {context['end']}"),
             paragraph(f"Sales: INR {summary['sales']:.2f} · Collected: INR {summary['collected']:.2f} · Outstanding: INR {summary['outstanding']:.2f}"),
             paragraph("Estimated profit: " + ("Unavailable (purchase costs missing)" if summary["estimated_profit"] is None else f"INR {summary['estimated_profit']:.2f}") + ". Excludes operating expenses, returns and other accounting adjustments. Stock reports show current stock."), Spacer(1, 12)]
    headers = [str(h).replace('__', ' ').replace('_', ' ').title() for h in context['headers']]
    if headers:
        story.append(table([headers, *context['rows']], [263 * mm / len(headers)] * len(headers)))
    else:
        story.append(paragraph('No records in this period.'))
    return build_pdf(story, title, wide=True)


def pdf_response(content, filename, download=False):
    response = HttpResponse(content, content_type='application/pdf')
    disposition = 'attachment' if download else 'inline'
    response['Content-Disposition'] = f'{disposition}; filename="{filename}"'
    response['Cache-Control'] = 'private, no-store'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response

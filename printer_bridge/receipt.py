"""Monochrome raster receipts: user text cannot inject ESC/POS commands."""
import os
from pathlib import Path
from decimal import Decimal
from PIL import Image, ImageDraw, ImageFont
import qrcode

def render_receipt(receipt, width=80, dots=None, font_path=None):
    if width not in (58,80): raise ValueError('Paper width must be 58 or 80 mm.')
    dots = dots or (384 if width==58 else 576)
    if dots not in (384,512,576) or (width==58 and dots!=384): raise ValueError('Unsupported printable dot width.')
    font_path = font_path or next((str(p) for p in [Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/arial.ttf',Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')] if p.exists()), None)
    font=ImageFont.truetype(font_path,24) if font_path else ImageFont.load_default(size=24)
    bold=ImageFont.truetype(font_path,30) if font_path else ImageFont.load_default(size=30)
    image=Image.new('L',(dots,24000),255); draw=ImageDraw.Draw(image); y=10; pad=12
    def text(value, large=False, center=False):
        nonlocal y
        active=bold if large else font
        # Wrap measured glyph widths, including long SKUs/names with no spaces.
        for paragraph in str(value).replace('\r','').split('\n'):
            line=''
            for char in paragraph[:4000]:
                if ord(char)<32: continue
                if draw.textlength(line+char,font=active)>dots-2*pad and line:
                    put(line,active,center);line=''
                line+=char
            put(line,active,center)
    def put(line, active, center):
        nonlocal y
        if y>23000: raise ValueError('Receipt exceeds supported length.')
        x=(dots-draw.textlength(line,font=active))/2 if center else pad
        draw.text((x,y),line,font=active,fill=0);y+=38 if active==bold else 32
    def rule():
        nonlocal y
        y+=5;draw.line((pad,y,dots-pad,y),fill=0,width=2);y+=10
    def money(value): return f"INR {Decimal(str(value)):.2f}"
    b=receipt['business'];c=receipt['customer']
    text(b['name'],large=True,center=True)
    for key in ['address','mobile','gstin']:
        if b.get(key): text(b[key],center=True)
    rule();text(receipt['number']);text(f"{receipt['date']} | {receipt['status'].upper()}");text(c['name']);text(c.get('mobile',''));rule()
    for item in receipt['items']:
        text(item['description']);text(f"{Decimal(item['quantity']).normalize():f} {item['unit']} x {money(item['unit_price'])}");text(('Tax included | ' if item.get('price_includes_tax') else '') + money(item.get('total', item['subtotal'])));rule()
    for label,key in [('Subtotal','subtotal'),('Discount','discount'),('CGST','cgst'),('SGST','sgst'),('IGST','igst')]:
        if key=='subtotal' or Decimal(receipt[key]): text(f'{label}: {money(receipt[key])}')
    text('TOTAL: '+money(receipt['total']),large=True);text('Paid: '+money(receipt['paid_amount']));text('Pending: '+money(receipt['balance']))
    if receipt.get('upi_uri'):
        qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=1);qr.add_data(receipt['upi_uri']);qr.make(fit=True)
        bitmap=qr.make_image(fill_color='black',back_color='white').convert('L')
        scale=min(6,(dots-2*pad)//bitmap.width)
        if scale<3: raise ValueError('QR is too dense for this printer width. Use browser printing.')
        bitmap=bitmap.resize((bitmap.width*scale,bitmap.height*scale),Image.Resampling.NEAREST)
        y+=12;image.paste(bitmap,((dots-bitmap.width)//2,y));y+=bitmap.height+12
        text('Scan to pay '+money(receipt['balance']),center=True);text(b.get('upi_id',''),center=True)
    rule();text(b.get('invoice_footer','Thank you!'),center=True)
    return image.crop((0,0,dots,y+12)).convert('1')

def escpos_bytes(image, cut=False):
    # GS v 0, normal-size raster, emitted in small bands for modest printer buffers.
    output=bytearray(b'\x1b@')
    width_bytes=(image.width+7)//8
    for top in range(0,image.height,128):
        band=image.crop((0,top,image.width,min(top+128,image.height))).convert('1')
        # Pillow uses 1 for white; ESC/POS uses 1 for black.
        pixels=bytes(b^255 for b in band.tobytes())
        output+=b'\x1dv0\x00'+width_bytes.to_bytes(2,'little')+band.height.to_bytes(2,'little')+pixels
    output+=b'\n\n\n'
    if cut: output+=b'\x1dV\x00'
    return bytes(output)

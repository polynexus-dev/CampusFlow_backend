"""
Shared branded-QR PNG rendering, used for both the bus route boarding QR
(BusRouteQRView) and the student ID-card QR (StudentIDQRView) so the
styling logic isn't duplicated between them.
"""

import io
import qrcode
from PIL import Image, ImageDraw, ImageFont


def render_branded_qr(payload: str, title_text: str, subtitle_text: str = "Powered & Developed by Polynexus Technologies") -> bytes:
    """Render `payload` as a purple-branded QR code with a graduation-cap
    logo and a footer caption. Returns PNG bytes."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    # Custom-style QR into premium purple, white circle border, graduation cap and branded footer
    img = img.convert("RGBA")
    w, h = img.size
    pixels = img.load()
    for x in range(w):
        for y in range(h):
            r, g, b, a = pixels[x, y]
            if r < 127 and g < 127 and b < 127:
                pixels[x, y] = (112, 26, 117, 255)  # Dark Purple
            else:
                pixels[x, y] = (255, 255, 255, 255)  # White

    draw = ImageDraw.Draw(img)
    logo_size = int(w * 0.22)
    left = (w - logo_size) // 2
    top = (h - logo_size) // 2
    right = left + logo_size
    bottom = top + logo_size

    # Clear center for logo
    draw.ellipse([left - 2, top - 2, right + 2, bottom + 2], fill=(255, 255, 255, 255), outline=(112, 26, 117, 255), width=2)

    # Draw graduation cap shape
    cx = w // 2
    cy = h // 2
    cap_w = int(logo_size * 0.60)
    cap_h = int(logo_size * 0.32)

    top_pt = (cx, cy - cap_h // 2)
    right_pt = (cx + cap_w // 2, cy)
    bottom_pt = (cx, cy + cap_h // 2)
    left_pt = (cx - cap_w // 2, cy)

    draw.polygon([top_pt, right_pt, bottom_pt, left_pt], fill=(112, 26, 117, 255))

    skull_w = int(logo_size * 0.34)
    skull_h = int(logo_size * 0.14)
    draw.chord([cx - skull_w // 2, cy, cx + skull_w // 2, cy + skull_h], start=0, end=180, fill=(112, 26, 117, 255))

    # Gold tassel
    draw.line([(cx, cy), (cx + cap_w // 3, cy + cap_h // 4), (cx + cap_w // 3, cy + cap_h // 2)], fill=(245, 158, 11, 255), width=2)

    # Branded card with footer
    footer_height = 80
    card = Image.new("RGBA", (w, h + footer_height), (255, 255, 255, 255))
    card.paste(img, (0, 0))

    card_draw = ImageDraw.Draw(card)
    card_draw.line([(25, h), (w - 25, h)], fill=(229, 231, 235, 255), width=1)

    try:
        font_title = ImageFont.truetype("arial.ttf", 12)
        font_sub = ImageFont.truetype("arial.ttf", 10)
    except IOError:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    if hasattr(card_draw, "textlength"):
        w_title = card_draw.textlength(title_text, font=font_title)
        w_sub = card_draw.textlength(subtitle_text, font=font_sub)
    else:
        w_title = len(title_text) * 6
        w_sub = len(subtitle_text) * 5

    card_draw.text(((w - w_title) // 2, h + 18), title_text, fill=(112, 26, 117, 255), font=font_title)
    card_draw.text(((w - w_sub) // 2, h + 38), subtitle_text, fill=(156, 163, 175, 255), font=font_sub)

    buffer = io.BytesIO()
    card.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.read()

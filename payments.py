"""
UPI payment helpers - build a UPI deep link and a scannable QR for it.

This is a UPI-ID/QR collection flow (no gateway): a "Pay with UPI / Google Pay"
link and QR pointing at the merchant's configured UPI ID. Any UPI app (Google
Pay, PhonePe, Paytm...) opens the link. There is no automatic settlement or
verification here - an admin reconciles payments (marks the order paid). A real
gateway (Razorpay/Cashfree) with a webhook would slot in later for auto-verify.
"""
import io
import urllib.parse

import qrcode
import qrcode.image.svg


def upi_uri(upi_id: str, payee: str, amount, note: str = "") -> str:
    """A upi://pay deep link. Google Pay and every UPI app understands it."""
    params = {
        "pa": upi_id,                       # payee address (the UPI ID)
        "pn": payee or "Payment",           # payee name
        "am": f"{amount}",                  # amount
        "cu": "INR",
    }
    if note:
        params["tn"] = note                 # transaction note
    return "upi://pay?" + urllib.parse.urlencode(params)


def qr_svg(data: str) -> str:
    """Inline SVG QR for a string. SVG so it needs no Pillow and scales cleanly."""
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")

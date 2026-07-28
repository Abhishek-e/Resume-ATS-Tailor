"""
Replaceable images for the landing page.

Where the bytes live
--------------------
Firebase Storage would be the natural home, but this project has no bucket
provisioned (both drive-54095.appspot.com and .firebasestorage.app return
exists=False), and Render's filesystem is ephemeral - anything written to
static/ is gone on the next deploy. So the bytes go in Firestore, one document
per slot, downscaled and re-encoded on the way in to stay comfortably under
Firestore's 1 MiB per-document ceiling.

That makes size a real constraint rather than an afterthought, which is why
every upload is resized and quality-stepped until it fits, and why replacing an
image overwrites its document instead of accumulating new ones.

Serving
-------
/media/<slot> reads from an in-process cache and sends a long Cache-Control
with an ETag, so a visitor costs one Firestore read per worker lifetime rather
than one per page view.
"""
import hashlib
import io
import threading
import time

# Slot -> (label, default URL, max width). The defaults are the Unsplash images
# the page shipped with; clearing a slot falls back to them.
SLOTS = {
    "hero": (
        "Hero portrait",
        "https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&w=900&q=80",
        1200,
    ),
    "card_cv": (
        "Card: Generate CV",
        "https://images.unsplash.com/photo-1586281380349-632531db7ed4?auto=format&fit=crop&w=800&q=80",
        1000,
    ),
    "card_jobs": (
        "Card: Find Jobs",
        "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=800&q=80",
        1000,
    ),
    "card_cover": (
        "Card: Cover Letter",
        "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?auto=format&fit=crop&w=800&q=80",
        1000,
    ),
    "card_plagiarism": (
        "Card: Plagiarism Checker",
        "https://images.unsplash.com/photo-1456513080510-7bf3a84b82f8?auto=format&fit=crop&w=800&q=80",
        1000,
    ),
    "card_analyze": (
        "Card: Analyze & Tailor CV",
        "https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?auto=format&fit=crop&w=800&q=80",
        1000,
    ),
}

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024      # refuse before decoding something huge
MAX_STORED_BYTES = 700 * 1024           # Firestore's ceiling is 1 MiB per doc

_COLLECTION = 'site_images'

_lock = threading.Lock()
_cache = {}


def invalidate(slot: str = None):
    with _lock:
        if slot is None:
            _cache.clear()
        else:
            _cache.pop(slot, None)


def default_url(slot: str) -> str:
    entry = SLOTS.get(slot)
    return entry[1] if entry else ""


def _encode(raw: bytes, max_width: int) -> tuple[bytes, str, int, int]:
    """
    Normalise an upload to a JPEG that fits the document limit.

    Steps the quality down, then the dimensions, rather than rejecting a large
    photo outright - an admin uploading a 12MP camera shot should just work.
    """
    from PIL import Image

    image = Image.open(io.BytesIO(raw))
    image.load()

    # Flatten transparency onto white; JPEG has no alpha channel.
    if image.mode in ('RGBA', 'LA', 'P'):
        image = image.convert('RGBA')
        flattened = Image.new('RGB', image.size, (255, 255, 255))
        flattened.paste(image, mask=image.split()[-1])
        image = flattened
    elif image.mode != 'RGB':
        image = image.convert('RGB')

    if image.width > max_width:
        height = round(image.height * max_width / image.width)
        image = image.resize((max_width, height), Image.LANCZOS)

    for quality in (85, 75, 65, 55, 45):
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', quality=quality, optimize=True, progressive=True)
        data = buffer.getvalue()
        if len(data) <= MAX_STORED_BYTES:
            return data, 'image/jpeg', image.width, image.height

    # Still too big at the lowest quality: halve the dimensions and retry once.
    image = image.resize((image.width // 2, image.height // 2), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format='JPEG', quality=70, optimize=True, progressive=True)
    return buffer.getvalue(), 'image/jpeg', image.width, image.height


def save(db, slot: str, filename: str, raw: bytes) -> dict:
    """Validates, re-encodes and stores. Raises ValueError with a usable message."""
    if slot not in SLOTS:
        raise ValueError("Unknown image slot.")
    if not raw:
        raise ValueError("That file was empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError(f"That file is {len(raw) // 1024 // 1024} MB — the limit is 8 MB.")

    dot = filename.rfind('.')
    extension = filename[dot:].lower() if dot >= 0 else ''
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Upload a JPG, PNG, WebP or GIF.")

    try:
        data, content_type, width, height = _encode(raw, SLOTS[slot][2])
    except Exception as e:
        raise ValueError(f"That file could not be read as an image ({e}).")

    payload = {
        "slot": slot,
        "data": data,
        "content_type": content_type,
        "width": width,
        "height": height,
        "bytes": len(data),
        "original_name": filename,
        "original_bytes": len(raw),
        "updated_at": time.time(),
    }
    # One document per slot, keyed by the slot: replacing overwrites in place,
    # so a previous upload is never left behind taking up space.
    db.collection(_COLLECTION).document(slot).set(payload)
    invalidate(slot)
    return payload


def delete(db, slot: str) -> None:
    db.collection(_COLLECTION).document(slot).delete()
    invalidate(slot)


def get(db, slot: str):
    """(bytes, content_type, etag) or None. Cached per worker."""
    if slot in _cache:
        return _cache[slot]
    if db is None:
        return None

    try:
        doc = db.collection(_COLLECTION).document(slot).get()
    except Exception:
        return None
    if not doc.exists:
        return None

    stored = doc.to_dict() or {}
    data = stored.get('data')
    if not data:
        return None
    data = bytes(data)
    entry = (data, stored.get('content_type', 'image/jpeg'),
             hashlib.md5(data).hexdigest())
    with _lock:
        _cache[slot] = entry
    return entry


def list_stored(db) -> dict:
    """slot -> metadata (no bytes), for the settings screen."""
    out = {}
    if db is None:
        return out
    try:
        for doc in db.collection(_COLLECTION).stream():
            meta = doc.to_dict() or {}
            meta.pop('data', None)
            out[doc.id] = meta
    except Exception:
        return {}
    return out


def overview(db) -> list[dict]:
    """Every slot, whether or not it has been replaced."""
    stored = list_stored(db)
    rows = []
    for slot, (label, default, _max_width) in SLOTS.items():
        meta = stored.get(slot)
        rows.append({
            "slot": slot,
            "label": label,
            "default_url": default,
            "custom": bool(meta),
            "bytes": (meta or {}).get('bytes', 0),
            "width": (meta or {}).get('width'),
            "height": (meta or {}).get('height'),
            "original_name": (meta or {}).get('original_name', ''),
            "updated_at": (meta or {}).get('updated_at', 0),
        })
    return rows


def prune(db) -> tuple[int, int]:
    """
    Drops stored images that no slot uses any more.

    Renaming or removing a slot in SLOTS would otherwise leave its document
    sitting in Firestore forever. Returns (documents removed, bytes freed).
    """
    removed = 0
    freed = 0
    for slot, meta in list_stored(db).items():
        if slot not in SLOTS:
            freed += meta.get('bytes', 0)
            db.collection(_COLLECTION).document(slot).delete()
            removed += 1
    if removed:
        invalidate()
    return removed, freed


def total_bytes(db) -> int:
    return sum(m.get('bytes', 0) for m in list_stored(db).values())


def urls(db, url_for) -> dict:
    """
    slot -> URL for the templates: the served route when an image has been
    uploaded, the original Unsplash link when it has not.
    """
    stored = list_stored(db)
    return {
        slot: (url_for('site_media', slot=slot, v=int(stored[slot].get('updated_at', 0)))
               if slot in stored else default)
        for slot, (_label, default, _mw) in SLOTS.items()
    }

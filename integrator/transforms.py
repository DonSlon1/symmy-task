import hashlib
import json


def validate_product(raw):
    """Returns (is_valid, reason)."""
    sku = raw.get('id')
    if not sku:
        return False, "missing SKU"

    price = raw.get('price_vat_excl')
    if price is None:
        return False, f"{sku}: null price"
    if not isinstance(price, (int, float)):
        return False, f"{sku}: non-numeric price"
    if price < 0:
        return False, f"{sku}: negative price ({price})"

    stocks = raw.get('stocks')
    if not stocks or not isinstance(stocks, dict):
        return False, f"{sku}: missing or invalid stocks"

    return True, ""


def transform_product(raw):
    sku = raw['id']
    price_excl = raw['price_vat_excl']
    price_incl = round(price_excl * 1.21, 2)

    total_stock = 0
    for warehouse, qty in raw.get('stocks', {}).items():
        if isinstance(qty, (int, float)):
            total_stock += int(qty)

    attributes = raw.get('attributes') or {}
    color = attributes.get('color', 'N/A') if isinstance(attributes, dict) else 'N/A'

    return {
        'sku': sku,
        'title': raw['title'],
        'price': price_incl,
        'stock': total_stock,
        'color': color,
    }


def deduplicate(products):
    seen = {}
    for p in products:
        seen[p['id']] = p
    return list(seen.values())


def compute_hash(payload):
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

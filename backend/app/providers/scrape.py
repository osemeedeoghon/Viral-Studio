"""Pull product facts and images from a product page."""
import json
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def _jsonld_products(soup) -> list[dict]:
    found = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                t = item.get("@type")
                if t == "Product" or (isinstance(t, list) and "Product" in t):
                    found.append(item)
                stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
            elif isinstance(item, list):
                stack.extend(item)
    return found


def scrape_product(url: str) -> dict:
    r = httpx.get(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
                  follow_redirects=True, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    def meta(*names):
        for n in names:
            tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return ""

    product = (_jsonld_products(soup) or [{}])[0]
    images: list[str] = []

    def add_img(src):
        if isinstance(src, dict):
            src = src.get("url") or src.get("contentUrl")
        if isinstance(src, list):
            for s in src:
                add_img(s)
            return
        if isinstance(src, str) and src and not src.startswith("data:"):
            full = urljoin(str(r.url), src)
            if full not in images:
                images.append(full)

    add_img(product.get("image"))
    add_img(meta("og:image", "twitter:image"))
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        w = img.get("width") or ""
        if any(k in src.lower() for k in ("logo", "icon", "sprite", "pixel", ".svg")):
            continue
        if w.isdigit() and int(w) < 300:
            continue
        add_img(src)

    offers = product.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = f"{offers.get('price', '')} {offers.get('priceCurrency', '')}".strip() if isinstance(offers, dict) else ""

    for t in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        t.decompose()
    text = " ".join(soup.get_text(" ").split())

    return {
        "url": str(r.url),
        "name": product.get("name") or meta("og:title", "twitter:title") or (soup.title.string.strip() if soup.title and soup.title.string else ""),
        "description": product.get("description") or meta("og:description", "description"),
        "brand": (product.get("brand") or {}).get("name", "") if isinstance(product.get("brand"), dict) else str(product.get("brand") or ""),
        "price": price,
        "images": images[:12],
        "page_text": text[:8000],
    }


def download_images(urls: list[str], dest_dir, limit: int = 6) -> list:
    from PIL import Image

    paths = []
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=30) as c:
        for i, u in enumerate(urls):
            if len(paths) >= limit:
                break
            try:
                r = c.get(u)
                r.raise_for_status()
                p = dest_dir / f"product_{i}.img"
                p.write_bytes(r.content)
                with Image.open(p) as im:
                    if min(im.size) < 250:
                        continue
                    out = dest_dir / f"product_{i}.jpg"
                    im.convert("RGB").save(out, quality=92)
                paths.append(out)
            except Exception:
                continue
    return paths

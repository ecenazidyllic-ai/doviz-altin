import html
import json
import math
import re
import threading
import time
from datetime import datetime, timezone
import urllib.request
import urllib.error
import requests
from flask import Flask, jsonify, render_template_string, request, send_from_directory
app= Flask(__name__)
_altin_cache = ""
_altin_cache_time = 0.0
_altin_cache_updated_at = None
_altin_cache_lock = threading.Lock()
_altin_products_cache = []
_altin_alis_stale_cache = True
_altin_alis_fiyat_cache = {}
_altin_alis_fiyat_cache_time = 0.0
_altin_alis_fiyat_updated_at = None
_altin_alis_fiyat_lock = threading.Lock()
_trend_cache = None
_trend_cache_time = 0.0
_trend_cache_updated_at = None
_trend_cache_lock = threading.Lock()
_live_kurlar_cache = None
_live_kurlar_cache_time = 0.0
_live_kurlar_cache_updated_at = None
_live_kurlar_cache_lock = threading.Lock()
_bist100_cache = None
_bist100_cache_time = 0.0
_bist100_cache_updated_at = None
_bist100_cache_lock = threading.Lock()
_kurlar_cache = None
_kurlar_cache_time = 0.0
_kurlar_cache_updated_at = None
_kurlar_cache_lock = threading.Lock()
_historical_currencies_cache = None
_historical_currencies_cache_time = 0.0
_historical_currencies_cache_stale = True
_historical_currencies_cache_lock = threading.Lock()
_CURRENCY_NAME_PAIRS = {
    "AUD": ("Avustralya Doları", "Australian Dollar"),
    "BGN": ("Bulgar Levası", "Bulgarian Lev"),
    "BRL": ("Brezilya Reali", "Brazilian Real"),
    "CAD": ("Kanada Doları", "Canadian Dollar"),
    "CHF": ("İsviçre Frangı", "Swiss Franc"),
    "CNY": ("Çin Yuanı", "Chinese Yuan"),
    "CZK": ("Çek Korunası", "Czech Koruna"),
    "DKK": ("Danimarka Kronu", "Danish Krone"),
    "EUR": ("Euro", "Euro"),
    "GBP": ("İngiliz Sterlini", "British Pound"),
    "HKD": ("Hong Kong Doları", "Hong Kong Dollar"),
    "HUF": ("Macar Forinti", "Hungarian Forint"),
    "IDR": ("Endonezya Rupisi", "Indonesian Rupiah"),
    "ILS": ("İsrail Yeni Şekeli", "Israeli New Shekel"),
    "INR": ("Hindistan Rupisi", "Indian Rupee"),
    "ISK": ("İzlanda Kronası", "Icelandic Króna"),
    "JPY": ("Japon Yeni", "Japanese Yen"),
    "KRW": ("Güney Kore Wonu", "South Korean Won"),
    "MXN": ("Meksika Pesosu", "Mexican Peso"),
    "MYR": ("Malezya Ringgiti", "Malaysian Ringgit"),
    "NOK": ("Norveç Kronu", "Norwegian Krone"),
    "NZD": ("Yeni Zelanda Doları", "New Zealand Dollar"),
    "PHP": ("Filipin Pesosu", "Philippine Peso"),
    "PLN": ("Polonya Zlotisi", "Polish Złoty"),
    "RON": ("Romanya Leyi", "Romanian Leu"),
    "RUB": ("Rus Rublesi", "Russian Ruble"),
    "SEK": ("İsveç Kronu", "Swedish Krona"),
    "SGD": ("Singapur Doları", "Singapore Dollar"),
    "THB": ("Tayland Bahtı", "Thai Baht"),
    "TRY": ("Türk Lirası", "Turkish Lira"),
    "USD": ("Amerikan Doları", "US Dollar"),
    "ZAR": ("Güney Afrika Randı", "South African Rand"),
}
_FALLBACK_HISTORICAL_CURRENCIES = tuple(sorted(
    (code for code in _CURRENCY_NAME_PAIRS if code != "TRY"),
    key=lambda code: (("USD", "EUR").index(code) if code in ("USD", "EUR") else 2, code),
))

def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()

def _fallback_historical_currencies():
    return [
        {
            "code": code,
            "name": _CURRENCY_NAME_PAIRS[code][0],
            "englishName": _CURRENCY_NAME_PAIRS[code][1],
        }
        for code in _FALLBACK_HISTORICAL_CURRENCIES
    ]

def _historical_currencies():
    global _historical_currencies_cache, _historical_currencies_cache_time
    global _historical_currencies_cache_stale
    with _historical_currencies_cache_lock:
        cache_ttl = 300 if _historical_currencies_cache_stale else 21600
        if (
            _historical_currencies_cache is not None
            and time.monotonic() - _historical_currencies_cache_time < cache_ttl
        ):
            return [dict(item) for item in _historical_currencies_cache], _historical_currencies_cache_stale
        try:
            response = requests.get(
                "https://api.frankfurter.app/currencies",
                headers={"User-Agent": "Mozilla/5.0 (compatible; DovizAltinApp/1.0)"},
                timeout=8,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Frankfurter para birimi listesi geçersiz.")
            currencies = []
            for raw_code, raw_name in payload.items():
                code = str(raw_code).upper()
                if code == "TRY" or not re.fullmatch(r"[A-Z]{3}", code):
                    continue
                english_name = str(raw_name).strip()
                if not english_name:
                    continue
                names = _CURRENCY_NAME_PAIRS.get(code)
                currencies.append({
                    "code": code,
                    "name": names[0] if names else english_name,
                    "englishName": names[1] if names else english_name,
                })
            if not currencies:
                raise ValueError("Frankfurter para birimi listesi boş.")
            currencies.sort(key=lambda item: (
                ("USD", "EUR").index(item["code"]) if item["code"] in ("USD", "EUR") else 2,
                item["code"],
            ))
        except (requests.RequestException, ValueError, TypeError, AttributeError) as error:
            app.logger.warning("Frankfurter para birimi listesi alınamadı: %s", error)
            if _historical_currencies_cache is None:
                _historical_currencies_cache = _fallback_historical_currencies()
            _historical_currencies_cache_time = time.monotonic()
            _historical_currencies_cache_stale = True
            return [dict(item) for item in _historical_currencies_cache], True

        _historical_currencies_cache = currencies
        _historical_currencies_cache_time = time.monotonic()
        _historical_currencies_cache_stale = False
        return [dict(item) for item in currencies], False

@app.route("/manifest.json")
def pwa_manifest():
    response = send_from_directory(
        app.root_path,
        "manifest.json",
        mimetype="application/manifest+json",
    )
    response.headers["Cache-Control"] = "no-cache"
    return response

@app.route("/sw.js")
def pwa_service_worker():
    response = send_from_directory(
        app.root_path,
        "sw.js",
        mimetype="application/javascript",
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response

def truncgil_altin_alis_fiyatlarini_cek():
    global _altin_alis_fiyat_cache, _altin_alis_fiyat_cache_time, _altin_alis_fiyat_updated_at
    with _altin_alis_fiyat_lock:
        if _altin_alis_fiyat_cache and time.monotonic() - _altin_alis_fiyat_cache_time < 300:
            return dict(_altin_alis_fiyat_cache), False, _altin_alis_fiyat_updated_at
        try:
            response = requests.get(
                "https://finans.truncgil.com/today.json",
                headers={"User-Agent": "Mozilla/5.0 (compatible; DovizAltinApp/1.0)"},
                timeout=8,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Altın alış fiyatı yanıtı geçersiz.")

            prices = {}
            for key, item in payload.items():
                if not isinstance(item, dict):
                    continue
                raw_price = item.get("Alış")
                if not isinstance(raw_price, str):
                    continue
                match = re.search(r"\d[\d.,]*", raw_price)
                if not match:
                    continue
                number = match.group(0)
                if "," in number and "." in number:
                    normalized = (
                        number.replace(".", "").replace(",", ".")
                        if number.rfind(",") > number.rfind(".")
                        else number.replace(",", "")
                    )
                else:
                    normalized = number.replace(",", ".")
                try:
                    numeric_price = float(normalized)
                except ValueError:
                    continue
                if math.isfinite(numeric_price) and numeric_price > 0:
                    prices[key] = number + " TL"
            if not any(key in prices for key in (
                "gram-altin",
                "22-ayar-bilezik",
                "18-ayar-altin",
                "14-ayar-altin",
                "ceyrek-altin",
                "yarim-altin",
                "tam-altin",
                "ata-altin",
                "gram-has-altin",
            )):
                raise ValueError("Altın alış fiyatı yanıtında geçerli fiyat bulunamadı.")

            _altin_alis_fiyat_cache = prices
            _altin_alis_fiyat_cache_time = time.monotonic()
            _altin_alis_fiyat_updated_at = _utc_now_iso()
            return dict(prices), False, _altin_alis_fiyat_updated_at
        except (requests.RequestException, ValueError, TypeError) as error:
            app.logger.warning("Truncgil alış fiyatları alınamadı: %s", error)
            return dict(_altin_alis_fiyat_cache), True, _altin_alis_fiyat_updated_at

def _izko_alis_fiyatini_esle(product_name, prices):
    normalized_name = product_name.strip().casefold()
    aliases = {
        "gram altın": ("gram-altin",),
        "22 ayar": ("22-ayar-bilezik",),
        "18 ayar": ("18-ayar-altin",),
        "14 ayar": ("14-ayar-altin",),
        "ata altın": ("ata-altin",),
        "çeyrek": ("ceyrek-altin",),
        "eski çeyrek": ("ceyrek-altin",),
        "yeni çeyrek": ("ceyrek-altin",),
        "yarım": ("yarim-altin",),
        "eski yarım": ("yarim-altin",),
        "yeni yarım": ("yarim-altin",),
        "ziynet": ("tam-altin", "cumhuriyet-altini"),
        "ziynet/tam": ("tam-altin", "cumhuriyet-altini"),
        "tam altın": ("tam-altin", "cumhuriyet-altini"),
        "yeni tam": ("tam-altin", "cumhuriyet-altini"),
        "eski ziynet": ("tam-altin", "cumhuriyet-altini"),
        "yeni ziynet": ("tam-altin", "cumhuriyet-altini"),
        "has altın": ("gram-has-altin",),
        "paketli has": ("gram-has-altin",),
    }
    for key in aliases.get(normalized_name, ()):
        if key in prices:
            return prices[key]
    return "- TL"

def izko_altin_cek():
    global _altin_cache, _altin_cache_time, _altin_cache_updated_at
    global _altin_products_cache, _altin_alis_stale_cache
    with _altin_cache_lock:
        if _altin_cache and time.monotonic() - _altin_cache_time < 25:
            return (
                _altin_cache,
                False,
                _altin_cache_updated_at,
                list(_altin_products_cache),
                _altin_alis_stale_cache,
            )
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            app.logger.warning("IZKO fiyatları için Playwright kullanılamıyor: %s", error)
            if _altin_cache:
                return (
                    _altin_cache,
                    True,
                    _altin_cache_updated_at,
                    list(_altin_products_cache),
                    _altin_alis_stale_cache,
                )
            return (
                '<p style="color:#b71c1c;">Otomatik IZKO fiyatları için Playwright gerekli. '
                'Kurulum: pip install -r requirements.txt ve '
                'python -m playwright install chromium</p>',
                True,
                None,
                [],
                True,
            )

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page(locale="tr-TR")
                    page.goto(
                        "https://www.izko.org.tr/guncel-kur",
                        wait_until="domcontentloaded",
                        timeout=25000,
                    )
                    page.wait_for_function(
                        """() => {
                            const price = document.querySelector(
                                '#yeniceyrekRegular, #yeniceyrekRegular span'
                            );
                            return price && /\\d/.test(price.textContent);
                        }""",
                        timeout=25000,
                    )
                    rows = page.locator(".price-row").evaluate_all(
                        """elements => elements.map(row => ({
                            name: row.querySelector(".row-name")?.textContent.trim() || "",
                            regular: row.querySelector(".row-satis")?.textContent.trim() || "",
                            discount: row.querySelector(".row-ind")?.textContent.trim() || ""
                        }))"""
                    )
                    cards = page.locator(".has-card").evaluate_all(
                        """elements => elements.map(card => ({
                            name: card.querySelector(".has-label")?.textContent.trim() || "",
                            values: [...card.querySelectorAll(".has-value")]
                                .map(value => value.textContent.trim())
                        }))"""
                    )
                finally:
                    browser.close()

            def prices_from(text):
                return re.findall(r"\d[\d.,]*", text)

            liste = []
            for row in rows:
                regular = prices_from(row["regular"])
                discount = prices_from(row["discount"])
                if row["name"] and regular and discount:
                    liste.append((row["name"], regular[0], discount[0]))
            for card in cards:
                values = prices_from(" ".join(card["values"]))
                if card["name"] and values:
                    first = "-" if card["name"].strip().upper() == "HAS ALTIN" else values[0]
                    liste.append((card["name"], first, values[-1]))
            if not liste:
                raise ValueError("IZKO sayfasında fiyat satırı bulunamadı.")

            alis_prices, alis_stale, _ = truncgil_altin_alis_fiyatlarini_cek()
            products = []
            for name, regular, discount in liste:
                products.append({
                    "name": name,
                    "kkSatis": regular + " TL",
                    "satis": discount + " TL",
                    "alis": _izko_alis_fiyatini_esle(name, alis_prices),
                })

            table = (
                '<table class="gold-prices">'
                '<thead><tr><th>Ürün</th>'
                '<th><label class="gold-price-mode-wrap">'
                '<select class="gold-price-mode" aria-label="Altın fiyat sütunu" '
                'onchange="izkoSutunModunuAyarla(this.value)">'
                '<option value="kk">K.K Satış</option>'
                '<option value="alis">Alış</option>'
                '</select><span aria-hidden="true">▾</span></label></th>'
                '<th>Satış</th></tr></thead>'
                '<tbody>'
                + "".join(
                    f'<tr><th scope="row">{html.escape(name)}</th>'
                    f'<td data-kk-satis="{html.escape(regular)} TL" '
                    f'data-alis="{html.escape(_izko_alis_fiyatini_esle(name, alis_prices))}">'
                    f'{html.escape(regular)} TL</td>'
                    f'<td>{html.escape(discount)} TL</td></tr>'
                    for name, regular, discount in liste
                )
                + "</tbody></table>"
            )
            _altin_cache = table
            _altin_cache_time = time.monotonic()
            _altin_cache_updated_at = _utc_now_iso()
            _altin_products_cache = products
            _altin_alis_stale_cache = alis_stale
            return table, False, _altin_cache_updated_at, list(products), alis_stale
        except (PlaywrightError, PlaywrightTimeoutError, OSError, ValueError) as error:
            app.logger.warning("IZKO fiyatları alınamadı: %s", error)
            if _altin_cache:
                return (
                    _altin_cache,
                    True,
                    _altin_cache_updated_at,
                    list(_altin_products_cache),
                    _altin_alis_stale_cache,
                )
            return (
                '<p style="color:#b71c1c;">IZKO fiyatları alınamadı: '
                f'{html.escape(str(error))}</p>',
                True,
                None,
                [],
                True,
            )
@app.route("/altin-fiyatlari")
def altin_fiyatlari_api():
    table, stale, updated_at, products, alis_stale = izko_altin_cek()
    status = 200 if 'class="gold-prices"' in table else 502
    response = jsonify({
        "html": table,
        "products": products,
        "stale": stale,
        "alisStale": alis_stale,
        "updatedAt": updated_at,
    })
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response

def _yahoo_gunluk_kapanislari(symbol):
    response = requests.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={"range": "10d", "interval": "1d"},
        headers={"User-Agent": "Mozilla/5.0 (compatible; DovizAltinApp/1.0)"},
        timeout=8,
    )
    response.raise_for_status()
    payload = response.json()
    chart = payload.get("chart") or {}
    chart_error = chart.get("error")
    if chart_error:
        message = chart_error.get("description") if isinstance(chart_error, dict) else str(chart_error)
        raise ValueError(message or f"Yahoo Finance {symbol} verisi alınamadı.")

    results = chart.get("result") or []
    if not results or not isinstance(results[0], dict):
        raise ValueError(f"Yahoo Finance {symbol} için veri bulunamadı.")
    result = results[0]
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quotes = indicators.get("quote") or []
    closes = quotes[0].get("close") if quotes and isinstance(quotes[0], dict) else None
    if not timestamps or not closes:
        raise ValueError(f"Yahoo Finance {symbol} kapanış verisi eksik.")

    daily_closes = {}
    for timestamp, close in zip(timestamps, closes):
        if close is None:
            continue
        price = float(close)
        if not math.isfinite(price) or price <= 0:
            continue
        day = datetime.fromtimestamp(timestamp, timezone.utc).date()
        daily_closes[day] = price
    if not daily_closes:
        raise ValueError(f"Yahoo Finance {symbol} için geçerli kapanış bulunamadı.")
    return daily_closes

@app.route("/api/trend")
def trend_api():
    global _trend_cache, _trend_cache_time, _trend_cache_updated_at
    with _trend_cache_lock:
        if _trend_cache is not None and time.monotonic() - _trend_cache_time < 1800:
            return jsonify({**_trend_cache, "stale": False, "updatedAt": _trend_cache_updated_at})
        try:
            usd_closes = _yahoo_gunluk_kapanislari("USDTRY=X")
            eur_closes = _yahoo_gunluk_kapanislari("EURTRY=X")
            gold_closes = _yahoo_gunluk_kapanislari("GC=F")
            common_days = sorted(
                usd_closes.keys() & eur_closes.keys() & gold_closes.keys()
            )[-7:]
            if len(common_days) < 2:
                raise ValueError("Son 10 günde en az iki ortak işlem günü bulunamadı.")

            month_names = (
                "Oca", "Şub", "Mar", "Nis", "May", "Haz",
                "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara",
            )
            data = {
                "dates": [day.isoformat() for day in common_days],
                "labels": [f"{day.day:02d} {month_names[day.month - 1]}" for day in common_days],
                "series": {
                    "USD": [round(usd_closes[day], 4) for day in common_days],
                    "EUR": [round(eur_closes[day], 4) for day in common_days],
                    "GOLD": [
                        round(gold_closes[day] * usd_closes[day] / 31.1035, 4)
                        for day in common_days
                    ],
                },
            }
        except (
            requests.RequestException,
            ValueError,
            KeyError,
            TypeError,
            IndexError,
            OverflowError,
            OSError,
        ) as error:
            app.logger.warning("7 günlük trend verileri alınamadı: %s", error)
            if _trend_cache is not None:
                return jsonify({**_trend_cache, "stale": True, "updatedAt": _trend_cache_updated_at})
            return jsonify({"error": f"Trend verileri alınamadı: {error}"}), 502

        _trend_cache = data
        _trend_cache_time = time.monotonic()
        _trend_cache_updated_at = _utc_now_iso()
        return jsonify({**data, "stale": False, "updatedAt": _trend_cache_updated_at})

def _yahoo_anlik_kuru(symbol):
    response = requests.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={"range": "1d", "interval": "1m"},
        headers={"User-Agent": "Mozilla/5.0 (compatible; DovizAltinApp/1.0)"},
        timeout=8,
    )
    response.raise_for_status()
    payload = response.json()
    results = (payload.get("chart") or {}).get("result") or []
    if not results or not isinstance(results[0], dict):
        raise ValueError(f"Yahoo Finance {symbol} için güncel kur bulunamadı.")

    result = results[0]
    quotes = (result.get("indicators") or {}).get("quote") or []
    closes = quotes[0].get("close") if quotes and isinstance(quotes[0], dict) else None
    meta = result.get("meta") or {}
    candidates = list(reversed(closes or [])) + [meta.get("regularMarketPrice")]
    for candidate in candidates:
        if candidate is None:
            continue
        price = float(candidate)
        if math.isfinite(price) and price > 0:
            return price
    raise ValueError(f"Yahoo Finance {symbol} için geçerli kur bulunamadı.")

@app.route("/api/live-kurlar")
def live_kurlar_api():
    global _live_kurlar_cache, _live_kurlar_cache_time, _live_kurlar_cache_updated_at
    with _live_kurlar_cache_lock:
        if _live_kurlar_cache is not None and time.monotonic() - _live_kurlar_cache_time < 60:
            return jsonify({**_live_kurlar_cache, "stale": False, "updatedAt": _live_kurlar_cache_updated_at})
        try:
            data = {
                "USD": round(_yahoo_anlik_kuru("USDTRY=X"), 4),
                "EUR": round(_yahoo_anlik_kuru("EURTRY=X"), 4),
            }
        except (
            requests.RequestException,
            ValueError,
            KeyError,
            TypeError,
            IndexError,
            OverflowError,
            OSError,
        ) as error:
            app.logger.warning("Canlı USD/EUR kurları alınamadı: %s", error)
            if _live_kurlar_cache is not None:
                return jsonify({**_live_kurlar_cache, "stale": True, "updatedAt": _live_kurlar_cache_updated_at})
            return jsonify({"error": f"Canlı kurlar alınamadı: {error}"}), 502

        _live_kurlar_cache = data
        _live_kurlar_cache_time = time.monotonic()
        _live_kurlar_cache_updated_at = _utc_now_iso()
        return jsonify({**data, "stale": False, "updatedAt": _live_kurlar_cache_updated_at})

@app.route("/api/bist100")
def bist100_api():
    global _bist100_cache, _bist100_cache_time, _bist100_cache_updated_at
    with _bist100_cache_lock:
        if _bist100_cache is not None and time.monotonic() - _bist100_cache_time < 1200:
            return jsonify({**_bist100_cache, "stale": False, "updatedAt": _bist100_cache_updated_at})
        try:
            response = requests.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/XU100.IS",
                params={"range": "5d", "interval": "1d"},
                headers={"User-Agent": "Mozilla/5.0 (compatible; DovizAltinApp/1.0)"},
                timeout=8,
            )
            response.raise_for_status()
            chart = (response.json().get("chart") or {})
            chart_error = chart.get("error")
            if chart_error:
                message = chart_error.get("description") if isinstance(chart_error, dict) else str(chart_error)
                raise ValueError(message or "Yahoo Finance BIST 100 verisi alınamadı.")

            results = chart.get("result") or []
            if not results or not isinstance(results[0], dict):
                raise ValueError("Yahoo Finance BIST 100 için veri bulunamadı.")
            result = results[0]
            quotes = (result.get("indicators") or {}).get("quote") or []
            closes = quotes[0].get("close") if quotes and isinstance(quotes[0], dict) else None
            valid_closes = []
            for close in closes or []:
                if close is None:
                    continue
                price = float(close)
                if math.isfinite(price) and price > 0:
                    valid_closes.append(price)
            if len(valid_closes) < 2:
                raise ValueError("BIST 100 için en az iki günlük kapanış bulunamadı.")

            meta = result.get("meta") or {}
            market_price = meta.get("regularMarketPrice")
            current_price = float(market_price) if market_price is not None else valid_closes[-1]
            previous_close = valid_closes[-2]
            if not math.isfinite(current_price) or current_price <= 0:
                raise ValueError("BIST 100 güncel fiyatı geçersiz.")
            data = {
                "value": round(current_price, 2),
                "changePercent": round((current_price - previous_close) / previous_close * 100, 2),
            }
        except (
            requests.RequestException,
            ValueError,
            KeyError,
            TypeError,
            IndexError,
            OverflowError,
            OSError,
        ) as error:
            app.logger.warning("BIST 100 verisi alınamadı: %s", error)
            if _bist100_cache is not None:
                return jsonify({**_bist100_cache, "stale": True, "updatedAt": _bist100_cache_updated_at})
            return jsonify({"error": f"BIST 100 verisi alınamadı: {error}"}), 502

        _bist100_cache = data
        _bist100_cache_time = time.monotonic()
        _bist100_cache_updated_at = _utc_now_iso()
        return jsonify({**data, "stale": False, "updatedAt": _bist100_cache_updated_at})

def _doviz_kurlarini_cek():
    global _kurlar_cache, _kurlar_cache_time, _kurlar_cache_updated_at
    with _kurlar_cache_lock:
        if _kurlar_cache is not None and time.monotonic() - _kurlar_cache_time < 1800:
            return dict(_kurlar_cache), False, _kurlar_cache_updated_at
        try:
            req = urllib.request.Request(
                "https://open.er-api.com/v6/latest/TRY",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=8) as response:
                data = json.loads(response.read().decode("utf-8"))
            rates = data.get("rates")
            if not isinstance(rates, dict):
                raise ValueError("Döviz sağlayıcısı geçerli kur verisi döndürmedi.")
            fresh_rates = {"TRY": 1.0}
            for code, rate in rates.items():
                value = float(rate)
                if math.isfinite(value) and value > 0:
                    fresh_rates[code] = round(1.0 / value, 4)
            if "USD" not in fresh_rates or "EUR" not in fresh_rates:
                raise ValueError("Döviz sağlayıcısı USD/EUR kurlarını döndürmedi.")
        except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError, TypeError, OverflowError) as error:
            app.logger.warning("Döviz kurları alınamadı: %s", error)
            if _kurlar_cache is not None:
                return dict(_kurlar_cache), True, _kurlar_cache_updated_at
            return {"TRY": 1.0}, True, None

        _kurlar_cache = fresh_rates
        _kurlar_cache_time = time.monotonic()
        _kurlar_cache_updated_at = _utc_now_iso()
        return dict(fresh_rates), False, _kurlar_cache_updated_at

@app.route("/api/doviz-kurlari")
def doviz_kurlari_api():
    rates, stale, updated_at = _doviz_kurlarini_cek()
    if "USD" not in rates or "EUR" not in rates:
        return jsonify({"error": "Döviz verisi henüz alınamadı.", "stale": True}), 502
    return jsonify({"rates": rates, "stale": stale, "updatedAt": updated_at})

@app.route("/api/gecmis-kur-para-birimleri")
def gecmis_kur_para_birimleri_api():
    currencies, stale = _historical_currencies()
    return jsonify({"currencies": currencies, "stale": stale})

@app.route("/api/gecmis-kur")
def gecmis_kur_api():
    tarih = request.args.get("date", "")
    kur = request.args.get("currency", "").upper()
    try:
        sorgu_tarihi = datetime.strptime(tarih, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Geçerli bir tarih girilmelidir."}), 400
    if sorgu_tarihi > datetime.now().date():
        return jsonify({"error": "Gelecek tarih için kur sorgulanamaz."}), 400
    currencies, _ = _historical_currencies()
    if kur not in {item["code"] for item in currencies}:
        return jsonify({"error": "Desteklenmeyen geçmiş kur para birimi."}), 400
    tarih = sorgu_tarihi.isoformat()

    try:
        response = requests.get(
            f"https://api.frankfurter.app/{tarih}",
            params={"from": kur, "to": "TRY"},
            headers={"User-Agent": "Mozilla/5.0 (compatible; DovizAltinApp/1.0)"},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        actual_date = payload.get("date")
        rates = payload.get("rates")
        rate = float(rates.get("TRY")) if isinstance(rates, dict) else float("nan")
        if not actual_date or not math.isfinite(rate) or rate <= 0:
            raise ValueError("Frankfurter geçerli bir geçmiş kur döndürmedi.")
        datetime.strptime(actual_date, "%Y-%m-%d")
        return jsonify({
            "requestedDate": tarih,
            "date": actual_date,
            "currency": kur,
            "rate": rate,
        })
    except (
        requests.RequestException,
        ValueError,
        TypeError,
        AttributeError,
        OverflowError,
    ) as error:
        app.logger.warning("Geçmiş %s kuru alınamadı (%s): %s", kur, tarih, error)
        return jsonify({"error": "Geçmiş kur verisi alınamadı."}), 502

@app.route("/")
def ana_sayfa():
    kurlar, kurlar_stale, kurlar_updated_at = _doviz_kurlarini_cek()
    isimler = {
    "TRY": "Türk Lirası",
    "USD": "Amerikan Doları",
    "EUR": "Euro",
    "GBP": "İngiliz Sterlini",
    "CHF": "İsviçre Frangı",
    "CAD": "Kanada Doları",
    "AUD": "Avustralya Doları",
    "JPY": "Japon Yeni",
    "CNY": "Çin Yuanı",
    "RUB": "Rus Rublesi",
    "AZN": "Azerbaycan Manatı",
    "SAR": "Suudi Arabistan Riyali",
    "AED": "BAE Dirhemi",
    "QAR": "Katar Riyali",
    "KWD": "Kuveyt Dinarı",
    "NOK": "Norveç Kronu",
    "SEK": "İsveç Kronu",
    "DKK": "Danimarka Kronu"
    }
    secenekler_kaynak = "".join([f'<option value="{k}" {"selected" if k=="EUR" else ""}>{isimler.get(k, k)}</option>' for k in kurlar.keys()])
    secenekler_hedef = "".join([f'<option value="{k}" {"selected" if k=="TRY" else ""}>{isimler.get(k, k)}</option>' for k in kurlar.keys()])
    gecmis_kur_secenekleri = "".join(
        f'<option value="{item["code"]}" data-name-tr="{html.escape(item["name"], quote=True)}" '
        f'data-name-en="{html.escape(item["englishName"], quote=True)}" '
        f'{"selected" if item["code"] == "USD" else ""}>'
        f'{html.escape(item["name"])} ({item["code"]})</option>'
        for item in _fallback_historical_currencies()
    )
    serit_metni= " . ".join([f"{k}: {oran} TL" for k, oran in kurlar.items()])
    altin_fiyatlari, altin_stale, altin_updated_at, _, altin_alis_stale = izko_altin_cek()
    return f'''<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0f172a">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Döviz &amp; Altın">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" sizes="192x192" href="/static/icons/icon-192.png">
<link rel="icon" type="image/png" sizes="192x192" href="/static/icons/icon-192.png">
<link rel="icon" type="image/png" sizes="512x512" href="/static/icons/icon-512.png">
<title>Döviz &amp; Altın</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.8/dist/chart.umd.min.js" defer></script>
<style>
body {{
   font-family: Arial, sans-serif;
   background-color: #f4f6f9;
   display: flex;
   justify-content: flex-start;
   align-items: flex-start;
   min-height: 100vh;
   margin: 0;
   padding: 24px;
   box-sizing: border-box;
   }}
   .content {{
      position: relative;
      width: 100%;
      min-height: calc(100vh - 48px);
      }}
   .converter-card-position {{
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      width: 100%;
      max-width: 380px;
      }}
   .card {{
      position: relative;
      background: white;
      padding: 24px;
      border-radius: 12px;
      border: 1px solid #f8bbd0;
      box-shadow: 0 8px 24px rgba(31, 41, 55, 0.16);
      width: 100%;
      max-width: 380px;
      box-sizing: border-box;
      text-align: center;
      }}
   .converter-tabs {{
      display: flex;
      gap: 6px;
      margin: 0 0 14px;
      }}
   .converter-tab {{
      flex: 1 1 0;
      min-width: 0;
      padding: 7px 5px;
      border: 1px solid #f0c4d1;
      border-radius: 9px;
      background: #fff9fb;
      color: #6b3652;
      font: inherit;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      transition: background-color 0.18s ease, border-color 0.18s ease, color 0.18s ease;
      }}
   .converter-tab.active,
   .converter-tab:hover {{
      border-color: #e8a9bf;
      background: #fcebf1;
      color: #880e4f;
      }}
   .trade-mode-row {{
      display: flex;
      align-items: center;
      justify-content: center;
         flex-wrap: wrap;
      gap: 8px;
      margin: 0 0 12px;
      color: #64748b;
      font-size: 12px;
      }}
      .trade-mode-options {{
         display: flex;
         flex-wrap: nowrap;
         gap: 4px;
      }}
      .trade-mode-option {{
         padding: 4px 8px;
      border: 1px solid #f0c4d1;
      border-radius: 999px;
      background: #fff9fb;
      color: #880e4f;
      font: inherit;
         font-size: 11px;
      font-weight: 700;
      cursor: pointer;
         white-space: nowrap;
      }}
      .trade-mode-option.active {{
         border-color: #e8a9bf;
         background: #fcebf1;
         color: #880e4f;
      }}
   .adjustment-controls {{
      margin-top: 12px;
      text-align: left;
      }}
   .adjustment-label {{
      display: block;
      margin-bottom: 6px;
      color: #64748b;
      font-size: 11px;
      font-weight: 600;
      }}
   .adjustment-controls input {{
      width: 100%;
      }}
   .adjustment-shortcuts {{
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      margin-top: 6px;
      }}
   .adjustment-shortcut {{
      padding: 4px 7px;
      border: 1px solid #f0c4d1;
      border-radius: 999px;
      background: #fff9fb;
      color: #6b3652;
      font: inherit;
      font-size: 10px;
      cursor: pointer;
      }}
   .result-detail {{
      font-size: 12px;
      font-weight: 600;
      line-height: 1.4;
      }}
   .historical-controls {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 12px;
      }}
   .historical-controls[hidden] {{
      display: none;
      }}
   .historical-controls label {{
      display: flex;
      flex-direction: column;
      gap: 4px;
      color: #64748b;
      font-size: 11px;
      font-weight: 600;
      text-align: left;
      }}
   .historical-controls input,
   .historical-controls select {{
      width: 100%;
      min-width: 0;
      }}
   .historical-query-button {{
      align-self: end;
      min-height: 38px;
      border: 1px solid #f0c4d1;
      border-radius: 8px;
      background: #fcebf1;
      color: #880e4f;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      }}
   .historical-query-button:disabled {{
      cursor: wait;
      opacity: 0.65;
      }}
   .historical-result-note {{
      margin: 8px 0 0;
      color: #64748b;
      font-size: 11px;
      }}
   #gecmis-hata {{
      grid-column: 1 / -1;
      margin: 0;
      color: #b91c1c;
      }}
   .gold-converter-fields {{
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-top: 15px;
      }}
   .gold-converter-fields[hidden] {{
      display: none;
      }}
   .gold-converter-fields input,
   .gold-converter-fields select {{
      width: 100%;
      }}
   .amount-picker {{
      position: relative;
      width: 100%;
      margin-bottom: 12px;
      }}
   .amount-picker input {{
      width: 100%;
      padding-right: 42px;
      appearance: textfield;
      -moz-appearance: textfield;
      }}
   .amount-picker input::-webkit-inner-spin-button,
   .amount-picker input::-webkit-outer-spin-button {{
      -webkit-appearance: none;
      margin: 0;
      }}
   .amount-picker-toggle {{
      position: absolute;
      top: 50%;
      right: 6px;
      display: grid;
      place-items: center;
      width: 28px;
      height: 28px;
      padding: 0;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: #880e4f;
      font-size: 17px;
      line-height: 1;
      cursor: pointer;
      z-index: 1;
      transform: translateY(-50%);
      transition: background-color 0.18s ease, transform 0.18s ease;
      }}
   .amount-picker-toggle:hover,
   .amount-picker-toggle[aria-expanded="true"] {{
      background: #fcebf1;
      }}
   .amount-picker-toggle[aria-expanded="true"] {{
      transform: translateY(-50%) rotate(180deg);
      }}
   .amount-dropdown {{
      position: absolute;
      top: calc(100% + 5px);
      left: 0;
      z-index: 20;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 6px;
      width: 100%;
      padding: 8px;
      border: 1px solid #f8bbd0;
      border-radius: 10px;
      background: #ffffff;
      box-shadow: 0 8px 20px rgba(31, 41, 55, 0.16);
      box-sizing: border-box;
      }}
   .amount-dropdown[hidden] {{
      display: none;
      }}
   .amount-preset {{
      padding: 6px 4px;
      border: 1px solid #f0c4d1;
      border-radius: 7px;
      background: #fff9fb;
      color: #1e3a5f;
      font-size: 13px;
      cursor: pointer;
      transition: background-color 0.18s ease, border-color 0.18s ease;
      }}
   .amount-preset:hover {{
      background: #fcebf1;
      border-color: #d8a2b3;
      }}
   .kur-ozet {{
      display: flex;
      justify-content: space-around;
      background: #fcebf1;
      color: #202124;
      padding: 10px;
      border-radius: 8px;
      margin-bottom: 15px;
      font-size: 14px;
      }}
   .currency-update-status {{
      margin: -8px 0 12px;
      color: #64748b;
      font-size: 11px;
      }}
   .card h3 {{
      color: #880e4f;
      font-weight: bold;
      }}
   .result-box {{
      position: relative;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 4px;
      width: 100%;
      box-sizing: border-box;
      margin-top: 15px;
      padding: 12px 42px;
      border: 0;
      border-radius: 6px;
      background: #b8e6cc;
      color: #2e7d32;
      font-family: inherit;
      font-size: 18px;
      font-weight: bold;
      text-align: center;
      cursor: pointer;
      }}
   .result-copy-icon {{
      position: absolute;
      top: 50%;
      right: 12px;
      display: inline-flex;
      width: 18px;
      height: 18px;
      color: inherit;
      transform: translateY(-50%);
      pointer-events: none;
      }}
   .result-copy-icon svg {{
      width: 100%;
      height: 100%;
      }}
   #sonuc.copied .result-copy-icon {{
      color: #15803d;
      }}
   #sonuc.copy-failed .result-copy-icon {{
      color: #b91c1c;
      }}
   .gold-card {{
      position: absolute;
      top: 0;
      left: 0;
      background: #fcebf1;
      border: 1px solid #f8bbd0;
      padding: 25px;
      border-radius: 16px;
      box-shadow: 0 8px 24px rgba(136, 14, 79, 0.16);
      width: 100%;
      max-width: 360px;
      box-sizing: border-box;
      text-align: center;
      }}
   .gold-card-title {{
      margin: 0;
      color: #880e4f;
      border-bottom: 2px solid #f8bbd0;
      padding-bottom: 10px;
      font-size: 18px;
      }}
   .gold-last-updated {{
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 6px;
      margin-top: 8px;
      color: #64748b;
      font-size: 11px;
      line-height: 1.4;
      font-variant-numeric: tabular-nums;
      }}
   .gold-live-dot {{
      flex: 0 0 7px;
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: #4ade80;
      animation: goldLivePulse 1.8s ease-in-out infinite;
      }}
   .gold-live-dot.stale {{
      background: #fbbf24;
      animation-name: goldLivePulseStale;
      }}
   @keyframes goldLivePulse {{
      0%, 100% {{ opacity: 1; box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.25); }}
      50% {{ opacity: 0.55; box-shadow: 0 0 0 4px rgba(74, 222, 128, 0); }}
      }}
   @keyframes goldLivePulseStale {{
      0%, 100% {{ opacity: 1; box-shadow: 0 0 0 0 rgba(251, 191, 36, 0.25); }}
      50% {{ opacity: 0.6; box-shadow: 0 0 0 4px rgba(251, 191, 36, 0); }}
      }}
   .connection-status {{
      padding: 3px 7px;
      border: 1px solid rgba(217, 119, 6, 0.2);
      border-radius: 999px;
      background: rgba(251, 191, 36, 0.14);
      color: #92400e;
      font-size: 10px;
      font-weight: 600;
      white-space: nowrap;
      }}
   @media (prefers-reduced-motion: reduce) {{
      .gold-live-dot {{ animation: none; }}
      }}
   .market-summary {{
      width: 100%;
      padding: 16px;
      border: 1px solid #f8bbd0;
      border-radius: 16px;
      background: #ffffff;
      box-shadow: 0 8px 24px rgba(136, 14, 79, 0.1);
      box-sizing: border-box;
      }}
   .market-summary-title {{
      margin: 0 0 12px;
      color: #880e4f;
      font-size: 18px;
      }}
   .market-summary-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      }}
   .market-summary-item {{
      min-width: 0;
      padding: 12px;
      border: 1px solid #f3d4dd;
      border-radius: 12px;
      background: #fff9fb;
      box-sizing: border-box;
      transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
      }}
   .market-summary-item:hover {{
      transform: translateY(-2px);
      border-color: #e8a9bf;
      box-shadow: 0 6px 16px rgba(136, 14, 79, 0.1);
      }}
   .market-summary-item-header {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 6px;
      margin-bottom: 12px;
      }}
   .market-summary-label {{
      min-width: 0;
      color: #a64d79;
      font-size: 13px;
      font-weight: 600;
      }}
   .market-summary-value {{
      display: block;
      overflow-wrap: anywhere;
      color: #1e293b;
      font-size: clamp(18px, 2vw, 24px);
      font-variant-numeric: tabular-nums;
      font-weight: 700;
      }}
   .market-summary-change {{
      flex: 0 0 auto;
      padding: 4px 6px;
      border-radius: 999px;
      font-size: 10px;
      font-weight: 700;
      white-space: nowrap;
      }}
   .market-summary-change-up {{
      background: rgba(34, 197, 94, 0.14);
      color: #15803d;
      }}
   .market-summary-change-down {{
      background: rgba(239, 68, 68, 0.12);
      color: #b91c1c;
      }}
   .market-summary-change-flat {{
      background: rgba(100, 116, 139, 0.12);
      color: #64748b;
      }}
   .market-summary-error {{
      margin: 10px 0 0;
      color: #b91c1c;
      font-size: 12px;
      }}
   .trend-card {{
      width: 100%;
      max-width: 360px;
      padding: 18px;
      border: 1px solid #f8bbd0;
      border-radius: 16px;
      background: #fcebf1;
      box-shadow: 0 8px 24px rgba(136, 14, 79, 0.16);
      box-sizing: border-box;
      color: #1e293b;
      }}
   .trend-column {{
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 16px;
      min-width: 0;
      padding-bottom: 170px;
      box-sizing: border-box;
      }}
   .basket-card {{
      width: 100%;
      max-width: 360px;
      padding: 18px;
      border: 1px solid #f8bbd0;
      border-radius: 16px;
      background: #fcebf1;
      box-shadow: 0 8px 24px rgba(136, 14, 79, 0.16);
      box-sizing: border-box;
      color: #1e293b;
      }}
   .widget-tabs {{
      display: flex;
      gap: 6px;
      margin-bottom: 12px;
      }}
   .widget-tab {{
      flex: 1 1 0;
      min-width: 0;
      padding: 7px 8px;
      border: 1px solid #f0c4d1;
      border-radius: 9px;
      background: #fff9fb;
      color: #6b3652;
      font: inherit;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      }}
   .widget-tab:hover,
   .widget-tab.active {{
      border-color: #e8a9bf;
      background: #f8dce7;
      color: #702747;
      }}
   .widget-panel[hidden] {{
      display: none;
      }}
   .basket-title {{
      margin: 0 0 12px;
      color: #880e4f;
      font-size: 17px;
      }}
   .basket-controls {{
      display: grid;
      grid-template-columns: 74px minmax(0, 1fr) auto;
      align-items: center;
      gap: 6px;
      }}
   .basket-controls select,
   .basket-controls input {{
      width: 100%;
      min-width: 0;
      height: 36px;
      padding: 6px;
      font-size: 12px;
      }}
   .basket-add-button,
   .basket-clear-button,
   .basket-copy-button {{
      border: 1px solid #f0c4d1;
      border-radius: 8px;
      background: #fff9fb;
      color: #880e4f;
      font: inherit;
      font-weight: 600;
      cursor: pointer;
      }}
   .basket-add-button {{
      min-height: 36px;
      padding: 6px 9px;
      white-space: nowrap;
      }}
   .basket-items {{
      display: grid;
      gap: 6px;
      max-height: 190px;
      overflow-y: auto;
      margin: 12px 0 0;
      padding: 0;
      list-style: none;
      }}
   .basket-item {{
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      padding: 7px 8px;
      border: 1px solid #f0c4d1;
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.72);
      font-size: 11px;
      }}
   .basket-item-label {{
      flex: 1 1 auto;
      min-width: 0;
      overflow-wrap: anywhere;
      }}
   .basket-item-amount {{
      flex: 0 0 auto;
      font-weight: 700;
      white-space: nowrap;
      }}
   .basket-item-remove {{
      flex: 0 0 24px;
      width: 24px;
      height: 24px;
      padding: 0;
      border: 0;
      border-radius: 50%;
      background: transparent;
      color: #9f1239;
      font-size: 18px;
      line-height: 1;
      cursor: pointer;
      }}
   .basket-item-remove:hover {{
      background: rgba(190, 24, 93, 0.1);
      }}
   .basket-empty {{
      margin: 12px 0 0;
      color: #64748b;
      font-size: 11px;
      text-align: center;
      }}
   .basket-clear-row {{
      display: flex;
      justify-content: flex-end;
      margin: 8px 0;
      }}
   .basket-clear-button {{
      padding: 5px 9px;
      font-size: 11px;
      }}
   .basket-total-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 40px;
      gap: 7px;
      }}
   .basket-total {{
      display: flex;
      align-items: center;
      justify-content: center;
      min-width: 0;
      min-height: 40px;
      padding: 8px;
      border-radius: 8px;
      background: #b8e6cc;
      color: #2e7d32;
      font-size: 14px;
      font-variant-numeric: tabular-nums;
      text-align: center;
      }}
   .basket-copy-button {{
      min-width: 40px;
      min-height: 40px;
      padding: 5px;
      font-size: 18px;
      }}
   .basket-copy-button.copied {{
      border-color: #86efac;
      background: #dcfce7;
      color: #15803d;
      }}
   .basket-copy-button.copy-failed {{
      border-color: #fca5a5;
      background: #fee2e2;
      color: #b91c1c;
      }}
   .basket-status,
   .basket-copy-status {{
      margin: 7px 0 0;
      color: #b91c1c;
      font-size: 11px;
      }}
   .basket-copy-status {{
      color: #15803d;
      }}
   .historical-panel {{
      padding-top: 2px;
      }}
   .historical-panel .historical-controls {{
      margin-top: 0;
      }}
   .historical-result {{
      margin-top: 12px;
      padding: 10px;
      border: 1px solid rgba(34, 197, 94, 0.22);
      border-radius: 8px;
      background: rgba(34, 197, 94, 0.1);
      color: #166534;
      }}
   .historical-result-value {{
      font-size: 14px;
      font-weight: 700;
      }}
   .historical-error {{
      margin-top: 10px;
      }}
   .trend-card-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 14px;
      }}
   .trend-title {{
      margin: 0;
      color: #880e4f;
      font-size: 18px;
      }}
   .trend-tabs {{
      display: flex;
      align-items: center;
      gap: 5px;
      }}
   .trend-pill {{
      padding: 5px 9px;
      border: 1px solid #dba9ba;
      border-radius: 999px;
      background: transparent;
      color: #6b3652;
      font: inherit;
      font-size: 11px;
      cursor: pointer;
      transition: background-color 0.18s ease, border-color 0.18s ease;
      }}
   .trend-pill:hover,
   .trend-pill.active {{
      border-color: #e8a9bf;
      background: #f8dce7;
      color: #702747;
      }}
   .trend-value-row {{
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 8px;
      }}
   .trend-current-price {{
      color: #1e293b;
      font-size: 21px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
      }}
   .trend-change-badge {{
      padding: 4px 7px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 700;
      white-space: nowrap;
      }}
   .trend-change-up {{
      background: rgba(34, 197, 94, 0.14);
      color: #15803d;
      }}
   .trend-change-down {{
      background: rgba(239, 68, 68, 0.12);
      color: #b91c1c;
      }}
   .trend-change-flat {{
      background: rgba(100, 116, 139, 0.12);
      color: #64748b;
      }}
   .trend-chart-wrap {{
      position: relative;
      width: 100%;
      height: 190px;
      }}
   .trend-chart-wrap canvas {{
      display: block;
      max-width: 100%;
      }}
   .trend-error {{
      margin: 8px 0 0;
      color: #b91c1c;
      font-size: 12px;
      }}
   .gold-prices {{
      width: 100%;
      border-collapse: collapse;
      font-size: 15px;
      text-align: right;
      }}
   .gold-prices th, .gold-prices td {{
      padding: 9px 5px;
      border-bottom: 1px solid #f3d4dd;
      white-space: nowrap;
      }}
   .gold-prices thead th {{
      color: #880e4f;
      font-size: 13px;
      text-transform: uppercase;
      }}
   .gold-price-mode-wrap {{
      position: relative;
      display: inline-flex;
      align-items: center;
      vertical-align: middle;
      }}
   .gold-price-mode {{
      width: 84px;
      padding: 0 12px 0 0 !important;
      border: 0 !important;
      border-radius: 0;
      background: transparent !important;
      color: inherit;
      font: inherit;
      text-align: right;
      text-align-last: right;
      text-transform: inherit;
      appearance: none;
      -webkit-appearance: none;
      cursor: pointer;
      }}
   .gold-price-mode-wrap > span {{
      position: absolute;
      right: 0;
      pointer-events: none;
      font-size: 11px;
      }}
   .gold-prices thead th:first-child,
   .gold-prices tbody th {{
      text-align: left;
      }}
   .gold-prices tbody th {{
      color: #4a4a4a;
      font-weight: 600;
      }}
   .gold-prices td:nth-child(2) {{
      color: #2e7d32;
      font-weight: 600;
      }}
   .gold-prices td:nth-child(3) {{
      color: #c62828;
      font-weight: 600;
      }}
   .gold-prices th:nth-child(2),
   .gold-prices th:nth-child(3),
   .gold-prices td:nth-child(2),
   .gold-prices td:nth-child(3) {{
      padding-right: 22px;
      }}
   .gold-prices td:nth-child(2),
   .gold-prices td:nth-child(3) {{
      position: relative;
      }}
   .gold-prices .price-change {{
      position: absolute;
      top: 50%;
      right: 4px;
      width: 12px;
      font-size: 11px;
      font-weight: bold;
      line-height: 1;
      text-align: center;
      transform: translateY(-50%);
      }}
   .gold-prices .price-change-up {{
      color: #2e7d32;
      }}
   .gold-prices .price-change-down {{
      color: #c62828;
      }}
   .gold-prices td.price-up {{
      animation: izkoPriceUp 0.7s ease-in-out 10;
      }}
   .gold-prices td.price-down {{
      animation: izkoPriceDown 0.7s ease-in-out 10;
      }}
   @keyframes izkoPriceUp {{
      0%, 100% {{ background-color: transparent; }}
      50% {{ background-color: rgba(34, 197, 94, 0.18); }}
      }}
   @keyframes izkoPriceDown {{
      0%, 100% {{ background-color: transparent; }}
      50% {{ background-color: rgba(239, 68, 68, 0.16); }}
      }}
   @media (max-width: 768px) {{
      body {{
         display: block;
         min-height: 100vh;
         padding: calc(12px + env(safe-area-inset-top)) 12px calc(112px + env(safe-area-inset-bottom));
         }}
      .content {{
         display: flex;
         flex-direction: column;
         align-items: stretch;
         gap: 16px;
         width: 100%;
         min-height: 0;
         }}
      .market-summary-grid {{
         grid-template-columns: repeat(2, minmax(0, 1fr));
         gap: 8px;
         }}
      .converter-tab {{
         font-size: 11px;
         }}
      .market-summary-item {{
         padding: 10px;
         }}
      .market-summary-item-header {{
         flex-wrap: wrap;
         margin-bottom: 8px;
         }}
      .market-summary-value {{
         font-size: 19px;
         }}
      .market-summary-change {{
         font-size: 9px;
         }}
      .converter-card-position {{
         position: static;
         transform: none;
         width: 100%;
         max-width: none;
         }}
      .card {{
         position: relative;
         width: 100%;
         max-width: none;
         }}
      .gold-card {{
         position: static;
         align-self: stretch;
         width: 100%;
         max-width: none;
         padding: 16px 12px;
         }}
      .trend-card {{
         width: 100%;
         max-width: none;
         }}
      .trend-column {{
         align-items: stretch;
         width: 100%;
         padding-bottom: 152px;
         }}
      .basket-card {{
         max-width: none;
         }}
      .basket-controls {{
         grid-template-columns: 68px minmax(0, 1fr) auto;
         }}
      .basket-controls select,
      .basket-controls input {{
         font-size: 16px;
         }}
      .gold-prices {{
         table-layout: fixed;
         font-size: 12px;
         }}
      .gold-prices th,
      .gold-prices td {{
         padding: 7px 3px;
         white-space: normal;
         overflow-wrap: anywhere;
         }}
      .gold-prices th:first-child,
      .gold-prices tbody th {{
         width: 32%;
         }}
      .gold-prices th:nth-child(2),
      .gold-prices th:nth-child(3),
      .gold-prices td:nth-child(2),
      .gold-prices td:nth-child(3) {{
         width: 34%;
         padding-right: 16px;
         }}
      .gold-prices .price-change {{
         right: 2px;
         width: 10px;
         font-size: 10px;
         }}
      input,
      select {{
         font-size: 16px;
         }}
      .historical-controls {{
         gap: 7px;
         }}
      }}
   @media (min-width: 769px) {{
      body.office-mode {{
         padding: 10px;
         }}
      body.office-mode .content {{
         gap: 14px;
         }}
      body.office-mode .market-summary {{
         padding: 22px;
         }}
      body.office-mode .market-summary-title,
      body.office-mode .gold-card-title,
      body.office-mode .trend-title {{
         font-size: 24px;
         }}
      body.office-mode .market-summary-label {{
         font-size: 16px;
         }}
      body.office-mode .market-summary-value {{
         font-size: clamp(24px, 2.2vw, 32px);
         }}
      body.office-mode .gold-card {{
         padding: 30px;
         }}
      body.office-mode .gold-prices {{
         font-size: 17px;
         }}
      body.office-mode .gold-prices th,
      body.office-mode .gold-prices td {{
         padding-top: 12px;
         padding-bottom: 12px;
         }}
      body.office-mode .trend-card {{
         padding: 24px;
         }}
      body.office-mode .basket-card {{
         padding: 24px;
         }}
      body.office-mode .trend-current-price {{
         font-size: 28px;
         }}
      body.office-mode .trend-chart-wrap {{
         height: 300px;
         }}
      body.office-mode .card {{
         padding: 30px;
         }}
      body.office-mode .card h3 {{
         font-size: 24px;
         }}
      }}
   @media (min-width: 769px) and (max-width: 1100px) {{
      .content {{
         display: flex;
         flex-direction: column;
         align-items: center;
         gap: 16px;
         }}
      .market-summary {{
         max-width: 740px;
         }}
      .converter-card-position {{
         position: static;
         transform: none;
         max-width: 380px;
         }}
      .gold-card,
      .trend-card {{
         position: static;
         width: 100%;
         max-width: 740px;
         }}
      .trend-column {{
         align-items: stretch;
         width: 100%;
         max-width: 740px;
         padding-bottom: 152px;
         }}
      .basket-card {{
         max-width: none;
         }}
      }}
   @media (min-width: 1101px) {{
      .content {{
         display: grid;
         grid-template-columns: minmax(0, 1fr) minmax(320px, 380px) minmax(0, 1fr);
         grid-template-areas: "summary summary summary" "gold converter trend";
         align-items: start;
         gap: 20px;
         min-height: calc(100vh - 48px);
         }}
      .market-summary {{
         grid-area: summary;
         }}
      .gold-card {{
         position: static;
         grid-area: gold;
         }}
      .converter-card-position {{
         position: static;
         grid-area: converter;
         align-self: center;
         transform: none;
         }}
      .trend-card {{
         max-width: none;
         }}
      .trend-column {{
         grid-area: trend;
         align-items: stretch;
         width: 100%;
         max-width: 360px;
         margin-left: auto;
         }}
      }}
      h3 {{ margin-top: 0; color: #202124; }}
      input, select {{
         padding: 8px;
         border: 1px solid #f8bbd0;
         border-radius: 6px;
         font-size: 14px;
         outline: none;
         box-sizing: border-box;
         }}
         .kayan-bant {{
         position: fixed;
         bottom: 0;
         left: 0;
         width: 100%;
         background: #1e293b;
         color: #f8fafc;
         padding: 10px 0;
        overflow: hidden;
        white-space: nowrap;
        box-shadow: 0 -2px 10px rgba(0,0,0,0.15);
        font-size: 14px;
        font-family: monospace;
        z-index: 1000;
        }}
        .kayan-yazi {{
        display: inline-block;
        white-space: nowrap;
        animation: seritKaydir 300s linear infinite;
        }}
        .kayan-bant:hover .kayan-yazi {{
        animation-play-state: paused;
        }}
        .kayan-bant:hover {{
        cursor: default;
        }}
        @keyframes seritKaydir {{
        0% {{ transform: translateX(100w); }}
        100% {{ transform: translateX(-100%); }}
        }} 
        </style>
         </head>
         <body
         data-rates-stale="{str(kurlar_stale).lower()}"
         data-rates-updated-at="{html.escape(kurlar_updated_at or '', quote=True)}"
         data-izko-stale="{str(altin_stale).lower()}"
         data-izko-alis-stale="{str(altin_alis_stale).lower()}"
         data-izko-updated-at="{html.escape(altin_updated_at or '', quote=True)}">
         <div class="mobile-topbar">
         <div class="tarih-saat-kutusu">
         <div id="tarih-alani">--.--.----</div>
         <div id="saat-alani">--:--:--</div>
         </div>
         <div class="topbar-actions">
         <button id="temaBtn" class="tema-butonu" onclick="temaDegistir()">🌙 Karanlık Mod</button>
         <button id="ekran-modu-btn" class="tema-butonu ekran-modu-butonu" type="button" aria-label="Ekran Modu" title="Ekran Modu" onclick="ekranModunuDegistir()">⛶ Ekran Modu</button>
         <button id="language-toggle" class="tema-butonu language-toggle" type="button" aria-label="Dili İngilizceye çevir" title="Dili İngilizceye çevir" onclick="uiDiliniDegistir()">🌐 EN</button>
         <div id="share-control" class="share-control">
         <button id="share-trigger" class="share-trigger" type="button" aria-haspopup="menu" aria-expanded="false" aria-controls="share-menu" onclick="paylasimMenuAcKapat()">📋 Paylaş / Kopyala</button>
         <div id="share-menu" class="share-menu" role="menu" aria-label="Paylaşım içeriği seç" hidden>
         <div class="share-options" role="group" aria-label="Paylaşılacak içeriği seç">
         <button type="button" class="share-option active" role="menuitemradio" aria-checked="true" data-share-kind="izko" onclick="paylasimIceriginiSec('izko')">Altın Fiyatları (İZKO)</button>
         <button type="button" class="share-option" role="menuitemradio" aria-checked="false" data-share-kind="summary" onclick="paylasimIceriginiSec('summary')">Piyasa Özeti (USD/EUR/Altın/BIST)</button>
         <button type="button" class="share-option" role="menuitemradio" aria-checked="false" data-share-kind="rates" onclick="paylasimIceriginiSec('rates')">Döviz Kurları</button>
         <button type="button" class="share-option" role="menuitemradio" aria-checked="false" data-share-kind="all" onclick="paylasimIceriginiSec('all')">Tümünü Kopyala</button>
         </div>
         <div class="share-actions" role="group" aria-label="Hızlı paylaşım">
         <button type="button" role="menuitem" onclick="paylasimSeceneginiKopyala()">📋 Kopyala</button>
         <button type="button" role="menuitem" onclick="paylasimWhatsAppIle()">💬 WhatsApp</button>
         <button type="button" role="menuitem" onclick="paylasimEpostaIle()">✉️ E-posta</button>
         <button type="button" role="menuitem" onclick="paylasimDigerIle()">🔗 Diğer</button>
         </div>
         </div>
         <p id="share-status" class="share-status" role="status" aria-live="polite" hidden></p>
         </div>
         </div>
         </div>
         <span id="ekran-modu-durum" class="screen-mode-status" role="status" aria-live="polite" hidden></span>
         <main class="content">
         <section class="market-summary" aria-labelledby="market-summary-title">
         <h2 id="market-summary-title" class="market-summary-title">Piyasa Özeti</h2>
         <div class="market-summary-grid">
         <article class="market-summary-item">
         <div class="market-summary-item-header">
         <span class="market-summary-label">Dolar (USD)</span>
         <span id="market-USD-change" class="market-summary-change market-summary-change-flat">--</span>
         </div>
         <strong id="market-USD-value" class="market-summary-value">-- TL</strong>
         </article>
         <article class="market-summary-item">
         <div class="market-summary-item-header">
         <span class="market-summary-label">Euro (EUR)</span>
         <span id="market-EUR-change" class="market-summary-change market-summary-change-flat">--</span>
         </div>
         <strong id="market-EUR-value" class="market-summary-value">-- TL</strong>
         </article>
         <article class="market-summary-item">
         <div class="market-summary-item-header">
         <span class="market-summary-label">Gram Altın</span>
         <span id="market-GOLD-change" class="market-summary-change market-summary-change-flat">--</span>
         </div>
         <strong id="market-GOLD-value" class="market-summary-value">-- TL</strong>
         </article>
         <article class="market-summary-item">
         <div class="market-summary-item-header">
         <span class="market-summary-label">BIST 100</span>
         <span id="market-BIST100-change" class="market-summary-change market-summary-change-flat">--</span>
         </div>
         <strong id="market-BIST100-value" class="market-summary-value">--</strong>
         </article>
         </div>
         <p id="market-summary-error" class="market-summary-error" role="status" hidden></p>
         </section>
         <div class="converter-card-position">
         <div class="card">
         <nav class="converter-tabs" role="tablist" aria-label="Çevirici türü">
         <button type="button" class="converter-tab active" role="tab" aria-selected="true" aria-controls="doviz-alani" data-converter-mode="currency" onclick="ceviriciModunuDegistir('currency')">Döviz</button>
         <button type="button" class="converter-tab" role="tab" aria-selected="false" aria-controls="altin-alani" data-converter-mode="gold" onclick="ceviriciModunuDegistir('gold')">Altın</button>
         </nav>
         <h3 id="converter-title">Döviz Çevirici</h3>
         <div id="trade-mode-row" class="trade-mode-row">
         <span>İşlem türü:</span>
         <div id="trade-mode-options" class="trade-mode-options" role="group" aria-label="İşlem türü">
         <button class="trade-mode-option active" type="button" data-trade-mode="sale" aria-pressed="true" onclick="islemTurunuDegistir('sale')">Satış</button>
         <button class="trade-mode-option" type="button" data-trade-mode="credit" aria-pressed="false" onclick="islemTurunuDegistir('credit')">K.K Satış</button>
         <button class="trade-mode-option" type="button" data-trade-mode="buy" aria-pressed="false" onclick="islemTurunuDegistir('buy')">Alış</button>
         </div>
         <span id="trade-mode-note">Dövizde mevcut kur kullanılır.</span>
         </div>
         <div id="doviz-alani">
         <div class="kur-ozet">
         <div><strong>USD:</strong> <span id="usd-kuru">{kurlar.get('USD', '-')}</span> TL</div>
         <div><strong>EUR:</strong> <span id="eur-kuru">{kurlar.get('EUR', '-')}</span> TL</div>
         </div>
         <p id="kur-yenileme-durumu" class="currency-update-status" role="status" hidden></p>
         <div class="amount-picker">
         <input type="number" id="miktar" value="1" min="0" oninput="hesapla()">
         <button type="button" class="amount-picker-toggle" aria-label="Döviz miktar seçeneklerini aç" aria-controls="doviz-miktar-listesi" aria-expanded="false">▾</button>
         <div id="doviz-miktar-listesi" class="amount-dropdown" hidden>
         <button type="button" class="amount-preset" data-amount="10" data-input-id="miktar">10</button>
         <button type="button" class="amount-preset" data-amount="20" data-input-id="miktar">20</button>
         <button type="button" class="amount-preset" data-amount="50" data-input-id="miktar">50</button>
         <button type="button" class="amount-preset" data-amount="100" data-input-id="miktar">100</button>
         <button type="button" class="amount-preset" data-amount="200" data-input-id="miktar">200</button>
         <button type="button" class="amount-preset" data-amount="250" data-input-id="miktar">250</button>
         <button type="button" class="amount-preset" data-amount="500" data-input-id="miktar">500</button>
         <button type="button" class="amount-preset" data-amount="750" data-input-id="miktar">750</button>
         <button type="button" class="amount-preset" data-amount="1000" data-input-id="miktar">1000</button>
         <button type="button" class="amount-preset" data-amount="1500" data-input-id="miktar">1500</button>
         <button type="button" class="amount-preset" data-amount="2000" data-input-id="miktar">2000</button>
         <button type="button" class="amount-preset" data-amount="2500" data-input-id="miktar">2500</button>
         <button type="button" class="amount-preset" data-amount="5000" data-input-id="miktar">5000</button>
         <button type="button" class="amount-preset" data-amount="10000" data-input-id="miktar">10000</button>
         </div>
         </div>
         <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 12px;">
         <select id="kaynakPara" onchange="hesapla()" style="width: 45%; padding: 8px;">
         {secenekler_kaynak}
         </select>
         <button type="button" onclick="tersCevir()" title="Degistir" style="background: #fcebf1; border: none; border-radius: 50%; width: 34px; cursor: pointer; font-size: 16px;">⇄</button>
         <select id="hedefPara" onchange="hesapla()" style="width: 45%; padding: 8px;">
         {secenekler_hedef}
         </select>
         </div>
         </div>
         <div id="altin-alani" class="gold-converter-fields" hidden>
         <div class="amount-picker">
         <input type="number" id="altin-miktar" value="1" min="0" step="any" aria-label="Altın miktarı veya adedi">
         <button type="button" class="amount-picker-toggle" aria-label="Altın miktar seçeneklerini aç" aria-controls="altin-miktar-listesi" aria-expanded="false">▾</button>
         <div id="altin-miktar-listesi" class="amount-dropdown" hidden>
         <button type="button" class="amount-preset" data-amount="1" data-input-id="altin-miktar">1</button>
         <button type="button" class="amount-preset" data-amount="2" data-input-id="altin-miktar">2</button>
         <button type="button" class="amount-preset" data-amount="3" data-input-id="altin-miktar">3</button>
         <button type="button" class="amount-preset" data-amount="5" data-input-id="altin-miktar">5</button>
         <button type="button" class="amount-preset" data-amount="10" data-input-id="altin-miktar">10</button>
         <button type="button" class="amount-preset" data-amount="20" data-input-id="altin-miktar">20</button>
         <button type="button" class="amount-preset" data-amount="50" data-input-id="altin-miktar">50</button>
         <button type="button" class="amount-preset" data-amount="100" data-input-id="altin-miktar">100</button>
         <button type="button" class="amount-preset" data-amount="250" data-input-id="altin-miktar">250</button>
         <button type="button" class="amount-preset" data-amount="500" data-input-id="altin-miktar">500</button>
         </div>
         </div>
         <select id="altin-turu" aria-label="Altın türü"></select>
         </div>
         <div id="adjustment-controls" class="adjustment-controls">
         <label class="adjustment-label" for="adjustment-percent">KDV / Komisyon / Kâr-Zarar (%)</label>
         <input type="number" id="adjustment-percent" value="0" step="any" inputmode="decimal" aria-label="Yüzde farkı">
         <div class="adjustment-shortcuts" aria-label="Hızlı yüzde seçimi">
         <button type="button" class="adjustment-shortcut" data-percent="0">%0</button>
         <button type="button" class="adjustment-shortcut" data-percent="20">+%20 KDV</button>
         <button type="button" class="adjustment-shortcut" data-percent="2">+%2</button>
         <button type="button" class="adjustment-shortcut" data-percent="-2">-%2</button>
         </div>
         </div>
         <div class="basket-clear-row">
         <button type="button" class="basket-clear-button" onclick="ceviriciyiTemizle()">Temizle</button>
         </div>
         <button id="sonuc" class="result-box" type="button" aria-label="Sonucu kopyala" title="Sonucu kopyala" onclick="sonucuKopyala()">
         <span id="sonuc-metin">-</span>
         <span id="sonuc-ayrinti" class="result-detail" hidden></span>
         <span id="sonuc-ikon" class="result-copy-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="7" y="5" width="13" height="16" rx="2"></rect><path d="M10 5V4a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v1"></path><path d="M10 11h7M10 15h7"></path></svg></span>
         </button>
         </div>
         </div>
        <div class="gold-card">
        <h3 class="gold-card-title">İzmir Kuyumcular Odası</h3>
        <div class="gold-last-updated" aria-label="Son güncelleme">
        <span class="gold-live-dot" aria-hidden="true"></span>
        <span>Son güncelleme: <time id="gold-last-update-time">--:--:--</time></span>
        <span id="connection-status" class="connection-status" role="status" hidden>Bağlantı bekleniyor (Son veri)</span>
        </div>
        <p id="gold-update-status" role="status" style="margin: 0 0 8px; color: #b71c1c; font-size: 13px;"></p>
        <div id="gold-prices" style="margin-top: 15px; font-size: 15px;">
        {altin_fiyatlari}
      </div>
      </div>
      <div class="trend-column">
      <section class="trend-card" aria-labelledby="trend-title">
      <div class="trend-card-header">
      <h3 id="trend-title" class="trend-title">7 Günlük Trend</h3>
      <div class="trend-tabs" role="group" aria-label="Trend varlığı seç">
      <button type="button" class="trend-pill active" data-trend-asset="USD" aria-pressed="true">USD</button>
      <button type="button" class="trend-pill" data-trend-asset="EUR" aria-pressed="false">EUR</button>
      <button type="button" class="trend-pill" data-trend-asset="GOLD" aria-pressed="false">Altın</button>
      </div>
      </div>
      <div class="trend-value-row">
      <strong id="trend-current-price" class="trend-current-price">-- TL</strong>
      <span id="trend-change-badge" class="trend-change-badge trend-change-flat">--</span>
      </div>
      <div class="trend-chart-wrap">
      <canvas id="trend-chart" role="img" aria-label="Seçili varlığın son yedi işlem günlük fiyat grafiği"></canvas>
      </div>
      <p id="trend-error" class="trend-error" role="status" hidden></p>
      </section>
      <section class="basket-card" aria-label="Sepet ve geçmiş kur">
      <div class="widget-tabs" role="tablist" aria-label="Sağ panel seçimi">
      <button type="button" class="widget-tab active" role="tab" aria-selected="true" aria-controls="basket-panel" onclick="sepetKartSekmesiniDegistir('basket')">Sepet</button>
      <button type="button" class="widget-tab" role="tab" aria-selected="false" aria-controls="gecmis-alani" onclick="sepetKartSekmesiniDegistir('historical')">Geçmiş Kur</button>
      </div>
      <section id="basket-panel" class="widget-panel" role="tabpanel" aria-label="Sepet hesaplayıcı">
      <h3 class="basket-title">Sepet</h3>
      <div class="basket-controls">
      <input id="sepet-miktar" type="number" min="0" step="any" value="1" inputmode="decimal" aria-label="Sepet miktarı">
      <select id="sepet-tur" aria-label="Sepete eklenecek para veya altın">
      <option value="USD" data-kind="currency">USD</option>
      <option value="EUR" data-kind="currency">EUR</option>
      </select>
      <button type="button" class="basket-add-button" onclick="sepetKalemiEkle()">+ Ekle</button>
      </div>
      <p id="sepet-status" class="basket-status" role="status" hidden></p>
      <ul id="sepet-kalemleri" class="basket-items"></ul>
      <div class="basket-clear-row">
      <button type="button" class="basket-clear-button" onclick="sepetiTemizle()">Temizle</button>
      </div>
      <div class="basket-total-row">
      <strong id="sepet-toplam" class="basket-total">Toplam: 0,00 TL</strong>
      <button id="sepet-kopyala" class="basket-copy-button" type="button" aria-label="Sepeti kopyala" title="Sepeti kopyala" onclick="sepetiKopyala()">📋</button>
      </div>
      <p id="sepet-kopyalama-durumu" class="basket-copy-status" role="status" hidden></p>
      </section>
      <section id="gecmis-alani" class="widget-panel historical-panel" role="tabpanel" aria-label="Geçmiş tarihli kur sorgulama" hidden>
      <div class="historical-controls">
      <label for="gecmis-tarih">Tarih
      <input type="date" id="gecmis-tarih">
      </label>
      <label for="gecmis-kur">Kur
      <select id="gecmis-kur">
      {gecmis_kur_secenekleri}
      </select>
      </label>
      <label for="gecmis-miktar">Miktar
      <input type="number" id="gecmis-miktar" value="1" min="0" step="any" inputmode="decimal">
      </label>
      <button id="gecmis-sorgula" class="historical-query-button" type="button" onclick="gecmisKuruSorgula()">Sorgula</button>
      </div>
      <p id="gecmis-hata" class="historical-result-note historical-error" role="status" hidden></p>
      <div id="gecmis-sonuc" class="historical-result" hidden>
      <strong id="gecmis-sonuc-deger" class="historical-result-value"></strong>
      <p id="gecmis-sonuc-notu" class="historical-result-note" role="status" hidden></p>
      </div>
      </section>
      </section>
      </div>
      </main>
        <div class="kayan-bant">
        <div class="kayan-yazi">{serit_metni}</div>
        </div>
        <script>
        let kurlar = {json.dumps(kurlar)};
let altinModu = false;
let converterMode = 'currency';
let tradeMode = 'sale';
let goldTradeMode = 'credit';
let izkoSutunModu = 'kk';
let sepetKalemleri = [];
let sepetSiradakiKimlik = 1;
let sepetKopyalamaZamani;
const uiLanguageStorageKey = 'doviz-altin-language';
let uiLanguage = localStorage.getItem(uiLanguageStorageKey) === 'en' ? 'en' : 'tr';
const uiTextPairs = [
    ['Döviz & Altın', 'Currency & Gold'],
    ['Piyasa Özeti', 'Market Summary'],
    ['Dolar (USD)', 'US Dollar (USD)'],
    ['Gram Altın', 'Gram Gold'],
    ['İzmir Kuyumcular Odası', 'Izmir Jewelers Chamber'],
    ['ÜRÜN', 'ITEM'],
    ['Ürün', 'Item'],
    ['K.K SATIŞ', 'CARD SALE'],
    ['K.K Satış', 'CARD SALE'],
    ['K.K SATIŞ ▾', 'CARD SALE ▾'],
    ['ALIŞ', 'BUY'],
    ['Alış', 'BUY'],
    ['SATIŞ', 'SALE'],
    ['Satış', 'SALE'],
    ['Son güncelleme', 'Last updated'],
    ['Son güncelleme:', 'Last updated:'],
    ['Bağlantı bekleniyor (Son veri)', 'Reconnecting (last data)'],
    ['Döviz Çevirici', 'Currency Converter'],
    ['Altın Çevirici', 'Gold Converter'],
    ['Çevirici türü', 'Converter type'],
    ['Döviz', 'Currency'],
    ['Altın', 'Gold'],
    ['İşlem türü:', 'Rate type:'],
    ['Dövizde mevcut kur kullanılır.', 'Uses the current exchange rate.'],
    ['İZKO tablosundaki fiyat sütunu kullanılır.', 'Uses the price column in the Izmir Jewelers Chamber table.'],
    ['KDV / Komisyon / Kâr-Zarar (%)', 'VAT / Commission / Profit-Loss (%)'],
    ['+%20 KDV', '+20% VAT'],
    ['%0', '0%'],
    ['+%2', '+2%'],
    ['-%2', '-2%'],
    ['Türk Lirası', 'Turkish Lira'],
    ['Amerikan Doları', 'US Dollar'],
    ['Degistir', 'Swap currencies'],
    ['Altın miktarı veya adedi', 'Gold amount or quantity'],
    ['Altın miktar seçeneklerini aç', 'Open gold amount options'],
    ['Döviz miktar seçeneklerini aç', 'Open currency amount options'],
    ['Yüzde farkı', 'Percentage adjustment'],
    ['Hızlı yüzde seçimi', 'Quick percentage options'],
    ['Sonucu kopyala', 'Copy result'],
    ['Altın fiyat sütunu', 'Gold price column'],
    ['Sonuç kopyalandı', 'Result copied'],
    ['Sonuç kopyalanamadı', 'Could not copy result'],
    ['Kopyalandı!', 'Copied!'],
    ['Kopyalanamadı', 'Copy failed'],
    ['7 Günlük Trend', '7-Day Trend'],
    ['Trend varlığı seç', 'Select trend asset'],
    ['Seçili varlığın son yedi işlem günlük fiyat grafiği', 'Selected asset price chart for the last seven trading days'],
    ['Sepet', 'Basket'],
    ['Geçmiş Kur', 'Historical Rate'],
    ['Sepet ve geçmiş kur', 'Basket and historical rates'],
    ['Sepet hesaplayıcı', 'Basket calculator'],
    ['Sepete eklenecek para veya altın', 'Currency or gold to add'],
    ['Sepet miktarı', 'Basket amount'],
    ['+ Ekle', '+ Add'],
    ['Temizle', 'Clear'],
    ['Toplam:', 'Total:'],
    ['Sepete henüz kalem eklenmedi.', 'No items added yet.'],
    ['Sepeti kopyala', 'Copy basket'],
    ['Sepet panoya kopyalandı.', 'Basket copied to clipboard.'],
    ['Sepet panoya kopyalanamadı.', 'Could not copy basket.'],
    ['Sepette kalem yok.', 'No items in the basket.'],
    ['Fiyat bekleniyor', 'Price pending'],
    ['Geçerli ve sıfırdan büyük bir miktar girin.', 'Enter a valid amount greater than zero.'],
    ['Bu kalem için güncel fiyat bulunamadı.', 'A current price could not be found for this item.'],
    ['Tarih', 'Date'],
    ['Kur', 'Rate'],
    ['Miktar', 'Amount'],
    ['Sorgula', 'Check Rate'],
    ['Geçmiş tarihli kur sorgulama', 'Historical rate lookup'],
    ['Sağ panel seçimi', 'Right panel selection'],
    ['Sorgulanıyor…', 'Checking…'],
    ['Geçerli bir tarih ve sıfır veya daha büyük bir miktar girin.', 'Enter a valid date and an amount of zero or greater.'],
    ['Geçmiş kur yanıtı geçersiz.', 'The historical rate response is invalid.'],
    ['Hesaplanan tutar geçersiz.', 'The calculated amount is invalid.'],
    ['Geçmiş kur verisi alınamadı.', 'Could not load historical rate data.'],
    ['Desteklenmeyen geçmiş kur para birimi.', 'Unsupported historical currency.'],
    ['Frankfurter kur listesi yenilenemedi; kayıtlı kurlar kullanılıyor.', 'Could not refresh the Frankfurter currency list; using saved currencies.'],
    ['Geçerli bir tarih girilmelidir.', 'Enter a valid date.'],
    ['Gelecek tarih için kur sorgulanamaz.', 'Rates cannot be queried for a future date.'],
    ['Döviz verisi henüz alınamadı.', 'Exchange-rate data is not available yet.'],
    ['Kur tarihi:', 'Rate date:'],
    ['En yakın işlem günü:', 'Nearest business day:'],
    ['Paylaş / Kopyala', 'Share / Copy'],
    ['Paylaşım içeriği seç', 'Choose content to share'],
    ['Paylaşılacak içeriği seç', 'Select content to share'],
    ['Hızlı paylaşım', 'Quick share'],
    ['Kopyala', 'Copy'],
    ['E-posta', 'Email'],
    ['Diğer', 'Other'],
    ['📋 Kopyala', '📋 Copy'],
    ['💬 WhatsApp', '💬 WhatsApp'],
    ['✉️ E-posta', '✉️ Email'],
    ['🔗 Diğer', '🔗 Other'],
    ['Altın Fiyatları (İZKO)', 'Gold Prices (IZKO)'],
    ['Piyasa Özeti (USD/EUR/Altın/BIST)', 'Market Summary (USD/EUR/Gold/BIST)'],
    ['Döviz Kurları', 'Exchange Rates'],
    ['Tümünü Kopyala', 'Copy All'],
    ['Kopyalandı ✓', 'Copied ✓'],
    ['Metin kopyalandı, uygulamaya yapıştırabilirsiniz', 'Text copied; paste it into the app'],
    ['WhatsApp ile paylaşım başlatıldı.', 'WhatsApp sharing started.'],
    ['E-posta uygulaması açıldı.', 'Email app opened.'],
    ['Paylaşım penceresi açıldı.', 'Share dialog opened.'],
    ['Paylaşım iptal edildi.', 'Sharing was cancelled.'],
    ['Paylaşım açılamadı.', 'Could not open sharing.'],
    ['Güncel Piyasa Kurları', 'Current Market Rates'],
    ['Paylaşım metni panoya kopyalanamadı:', 'Could not copy share text:'],
    ['Veri bekleniyor', 'Waiting for data'],
    ['Değişim verisi bekleniyor', 'Waiting for change data'],
    ['DÖVİZ & ALTIN | PİYASA ÖZETİ', 'CURRENCY & GOLD | MARKET SUMMARY'],
    ['DÖVİZ & ALTIN | İZKO ALTIN FİYATLARI', 'CURRENCY & GOLD | IZKO GOLD PRICES'],
    ['DÖVİZ & ALTIN | DÖVİZ KURLARI', 'CURRENCY & GOLD | EXCHANGE RATES'],
    ['DÖVİZ & ALTIN | SEPET', 'CURRENCY & GOLD | BASKET'],
    ['📋 Paylaş / Kopyala', '📋 Share / Copy'],
    ['Tarih/Saat:', 'Date/Time:'],
    ['Dolar (USD):', 'US Dollar (USD):'],
    ['Euro (EUR):', 'Euro (EUR):'],
    ['Gram Altın:', 'Gram Gold:'],
    ['Bağlantı bekleniyor; son geçerli İZKO verisi gösteriliyor.', 'Reconnecting; showing the last valid Izmir Jewelers Chamber data.'],
    ['Bağlantı bekleniyor; son geçerli trend verisi gösteriliyor.', 'Reconnecting; showing the last valid trend data.'],
    ['Trend güncellenemedi; son geçerli veri gösteriliyor.', 'Trend update failed; showing the last valid data.'],
    ['Trend verileri yüklenemedi:', 'Could not load trend data:'],
    ['Trend verileri alınamadı:', 'Could not retrieve trend data:'],
    ['Trend yanıtı beklenen biçimde değil.', 'The trend response has an unexpected format.'],
    ['Chart.js yüklenemedi.', 'Chart.js could not be loaded.'],
    ['BIST 100 için son geçerli veri gösteriliyor.', 'Showing the last valid BIST 100 data.'],
    ['BIST 100 yanıtı geçersiz.', 'The BIST 100 response is invalid.'],
    ['BIST 100 güncellenemedi; son geçerli veri korunuyor.', 'BIST 100 update failed; keeping the last valid data.'],
    ['Döviz sağlayıcısı boş veya geçersiz veri döndürdü.', 'The exchange-rate provider returned empty or invalid data.'],
    ['Döviz verisi güncellenemedi; son geçerli veriler korunuyor.', 'Exchange rates could not be updated; keeping the last valid data.'],
    ['Canlı kurlar için son geçerli veri gösteriliyor.', 'Showing the last valid live rates.'],
    ['Canlı kurlar güncellenemedi; son geçerli değerler korunuyor.', 'Live rates could not be updated; keeping the last valid values.'],
    ['Kur verisi bekleniyor', 'Waiting for exchange-rate data'],
    ['Güncel altın fiyatı bulunamadı', 'Current gold prices are unavailable'],
    ['Geçerli bir miktar girin.', 'Enter a valid amount.'],
    ['Güncel İZKO satış fiyatı bulunamadı.', 'The current Izmir Jewelers Chamber sale price is unavailable.'],
    ['Güncel İZKO K.K Satış fiyatı bulunamadı.', 'The current Izmir Jewelers Chamber card-sale price is unavailable.'],
    ['Seçilen ürün için İZKO alış fiyatı bulunamadı.', 'No Izmir Jewelers Chamber buy price is available for the selected item.'],
    ['Altın fiyatları bekleniyor.', 'Waiting for gold prices.'],
    ['İZKO fiyatları alınamadı; son geçerli veri bekleniyor.', 'Could not load Izmir Jewelers Chamber prices; waiting for the last valid data.'],
    ['Alış fiyatları güncellenemedi; mevcut değerler korunuyor.', 'Buy prices could not be updated; keeping the current values.'],
    ['Fiyatlar güncellenemedi; son geçerli veriler korunuyor.', 'Prices could not be updated; keeping the last valid data.'],
    ['Fiyat yükseldi', 'Price increased'],
    ['Fiyat düştü', 'Price decreased'],
    ['Tam ekrandan çık', 'Exit fullscreen'],
    ['Ekran Modu', 'Screen Mode'],
    ['⛶ Ekran Modu', '⛶ Screen Mode'],
    ['Aydınlık Mod', 'Light Mode'],
    ['☀️ Aydınlık Mod', '☀️ Light Mode'],
    ['Karanlık Mod', 'Dark Mode'],
    ['🌙 Karanlık Mod', '🌙 Dark Mode'],
    ['Tam ekran izni alınamadı.', 'Fullscreen permission was not granted.'],
    ['Bu tarayıcı tam ekran modunu desteklemiyor.', 'This browser does not support fullscreen mode.'],
    ['Dili İngilizceye çevir', 'Switch language to English'],
    ['Switch language to Turkish', 'Dili Türkçeye çevir']
];
const uiTurkishToEnglish = new Map(uiTextPairs);
const uiEnglishToTurkish = new Map(uiTextPairs.map(([turkish, english]) => [english, turkish]));
function uiLocale() {{
return uiLanguage === 'en' ? 'en-GB' : 'tr-TR';
}}
function uiText(value) {{
const text = String(value);
const translated = (uiLanguage === 'en' ? uiTurkishToEnglish : uiEnglishToTurkish).get(text);
return translated || text;
}}
function uiProtectedGoldName(node) {{
let element = node && node.parentElement;
while (element) {{
    if (element.matches('.gold-prices tbody th')) {{
        return true;
    }}
    if (element.tagName === 'OPTION' &&
        (element.dataset.kind === 'gold' ||
            (element.value && element.parentElement && element.parentElement.id === 'altin-turu'))) {{
        return true;
    }}
    element = element.parentElement;
}}
return false;
}}
function uiTranslateDynamic(text, node) {{
if (uiProtectedGoldName(node)) {{
    return text;
}}
const element = node && node.nodeType === Node.ELEMENT_NODE ? node : node && node.parentElement;
if (element && element.id === 'sonuc-metin') {{
    const replacements = uiLanguage === 'en'
        ? [['Türk Lirası', 'Turkish Lira'], ['Amerikan Doları', 'US Dollar'],
            ['K.K Satış', 'CARD SALE'], ['Alış', 'BUY'], ['Satış', 'SALE']]
        : [['Turkish Lira', 'Türk Lirası'], ['US Dollar', 'Amerikan Doları'],
            ['CARD SALE', 'K.K Satış'], ['BUY', 'Alış'], ['SALE', 'Satış']];
    return replacements.reduce((result, [from, to]) => result.split(from).join(to), text);
}}
let match = text.match(/^Toplam: (.*)$/);
if (match) {{
    return (uiLanguage === 'en' ? 'Total: ' : 'Toplam: ') + match[1];
}}
match = text.match(/^Total: (.*)$/);
if (match) {{
    return (uiLanguage === 'en' ? 'Total: ' : 'Toplam: ') + match[1];
}}
match = text.match(/^(.+) kalemini sil$/);
if (match) {{
    return uiLanguage === 'en' ? 'Remove ' + match[1] + ' item' : text;
}}
match = text.match(/^Remove (.+) item$/);
if (match) {{
    return uiLanguage === 'en' ? text : match[1] + ' kalemini sil';
}}
const dynamicPrefixes = [
    ['Trend verileri yüklenemedi:', 'Could not load trend data:'],
    ['Could not load trend data:', 'Trend verileri yüklenemedi:'],
    ['Trend verileri alınamadı:', 'Could not retrieve trend data:'],
    ['Could not retrieve trend data:', 'Trend verileri alınamadı:'],
    ['Kur tarihi:', 'Rate date:'],
    ['Rate date:', 'Kur tarihi:'],
    ['En yakın işlem günü:', 'Nearest business day:'],
    ['Nearest business day:', 'En yakın işlem günü:']
];
for (const [turkish, english] of dynamicPrefixes) {{
    if (text.startsWith(turkish)) {{
        return (uiLanguage === 'en' ? english : turkish) + text.slice(turkish.length);
    }}
    if (text.startsWith(english)) {{
        return (uiLanguage === 'en' ? english : turkish) + text.slice(english.length);
    }}
}}
return text;
}}
function uiTranslateValue(value, node) {{
const text = String(value);
if (!text.trim()) {{
    return text;
}}
if (uiProtectedGoldName(node)) {{
    return text;
}}
const leading = text.slice(0, text.indexOf(text.trim()));
const trailing = text.slice(leading.length + text.trim().length);
const core = text.trim();
const dictionary = uiLanguage === 'en' ? uiTurkishToEnglish : uiEnglishToTurkish;
return leading + (dictionary.get(core) || uiTranslateDynamic(core, node)) + trailing;
}}
function uiTranslateNode(node) {{
if (node.nodeType === Node.TEXT_NODE) {{
    const translated = uiTranslateValue(node.nodeValue, node);
    if (translated !== node.nodeValue) {{
        node.nodeValue = translated;
    }}
    return;
}}
if (node.nodeType !== Node.ELEMENT_NODE) {{
    return;
}}
const element = node;
if (element.tagName === 'SCRIPT' || element.tagName === 'STYLE') {{
    return;
}}
['aria-label', 'title', 'placeholder'].forEach(attribute => {{
    if (!element.hasAttribute(attribute)) {{
        return;
    }}
    const value = element.getAttribute(attribute);
    const translated = uiTranslateValue(value, element);
    if (translated !== value) {{
        element.setAttribute(attribute, translated);
    }}
}});
Array.from(element.childNodes).forEach(uiTranslateNode);
}}
function uiLocalizeHistoricalCurrencyOptions() {{
const select = document.getElementById('gecmis-kur');
if (!select) {{
    return;
}}
[...select.options].forEach(option => {{
    const name = uiLanguage === 'en'
        ? option.dataset.nameEn || option.dataset.nameTr
        : option.dataset.nameTr;
    if (name) {{
        option.textContent = name + ' (' + option.value + ')';
    }}
}});
}}
function uiApplyLanguage(language, persist = true) {{
if (language !== 'tr' && language !== 'en') {{
    return;
}}
uiLanguage = language;
document.documentElement.lang = language;
document.documentElement.dir = 'ltr';
document.title = uiText('Döviz & Altın');
uiTranslateNode(document.body);
uiLocalizeHistoricalCurrencyOptions();
const button = document.getElementById('language-toggle');
button.textContent = language === 'tr' ? '🌐 EN' : '🌐 TR';
const targetLabel = language === 'tr' ? 'Dili İngilizceye çevir' : 'Switch language to Turkish';
button.setAttribute('aria-label', targetLabel);
button.title = targetLabel;
if (persist) {{
    localStorage.setItem(uiLanguageStorageKey, language);
}}
if (typeof saatGuncelle === 'function') {{
    saatGuncelle();
}}
if (typeof trendChart !== 'undefined' && trendChart) {{
    if (trendPayload) {{
        trendDegisiminiGoster(trendActiveAsset);
    }} else {{
        trendChart.update('none');
    }}
}}
if (typeof sepetiGuncelle === 'function') {{
    sepetiGuncelle();
}}
if (typeof altinModu !== 'undefined') {{
    altinModu ? altinHesapla() : hesapla();
}}
}}
function uiDiliniDegistir() {{
uiApplyLanguage(uiLanguage === 'tr' ? 'en' : 'tr');
}}
const uiLanguageObserver = new MutationObserver(records => {{
records.forEach(record => {{
    if (record.type === 'childList') {{
        record.addedNodes.forEach(uiTranslateNode);
    }} else if (record.type === 'characterData') {{
        uiTranslateNode(record.target);
    }} else if (record.type === 'attributes') {{
        const value = record.target.getAttribute(record.attributeName);
        const translated = uiTranslateValue(value, record.target);
        if (translated !== value) {{
            record.target.setAttribute(record.attributeName, translated);
        }}
    }}
}});
}});
uiLanguageObserver.observe(document.body, {{
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: ['aria-label', 'title', 'placeholder']
}});
const yerelVeriOnbellekPrefix = 'doviz-altin-son-veri:';
const veriKaynakDurumlari = {{
    baseRates: document.body.dataset.ratesStale === 'true',
    liveRates: true,
    izko: document.body.dataset.izkoStale === 'true',
    market: true,
    trend: true
}};
function baglantiRozetiniGuncelle() {{
const dot = document.querySelector('.gold-live-dot');
const badge = document.getElementById('connection-status');
const stale = !navigator.onLine || Object.values(veriKaynakDurumlari).some(Boolean);
dot.classList.toggle('stale', stale);
badge.hidden = !stale;
}}
function veriKaynakDurumunuAyarla(source, stale) {{
veriKaynakDurumlari[source] = Boolean(stale);
baglantiRozetiniGuncelle();
}}
function yerelVeriKaydiniOku(key) {{
try {{
    const stored = localStorage.getItem(yerelVeriOnbellekPrefix + key);
    if (!stored) {{
        return null;
    }}
    const record = JSON.parse(stored);
    if (!record || !record.data || typeof record.updatedAt !== 'string') {{
        throw new Error('Saklanan veri kaydı beklenen biçimde değil.');
    }}
    return record;
}} catch (error) {{
    console.error(key + ' yerel verisi okunamadı:', error);
    return null;
}}
}}
function yerelVeriKaydiniYaz(key, data, updatedAt) {{
try {{
    localStorage.setItem(yerelVeriOnbellekPrefix + key, JSON.stringify({{
        data,
        updatedAt: updatedAt || new Date().toISOString()
    }}));
}} catch (error) {{
    console.error(key + ' yerel verisi kaydedilemedi:', error);
}}
}}
function yerelKayitDahaYeniMi(record, updatedAt) {{
if (!record) {{
    return false;
}}
const savedTime = Date.parse(record.updatedAt);
const serverTime = Date.parse(updatedAt || '');
return Number.isFinite(savedTime) && (!Number.isFinite(serverTime) || savedTime > serverTime);
}}
function gecerliKurHaritasi(data) {{
if (!data || typeof data !== 'object' || Array.isArray(data)) {{
    return null;
}}
const rates = {{}};
Object.entries(data).forEach(([code, value]) => {{
    const rate = Number(value);
    if (Number.isFinite(rate) && rate > 0) {{
        rates[code] = rate;
    }}
}});
return rates.USD > 0 && rates.EUR > 0 ? rates : null;
}}
function kurSecenekleriniGuncelle() {{
const names = {{ TRY: 'Türk Lirası', USD: 'Amerikan Doları', EUR: 'Euro' }};
['kaynakPara', 'hedefPara'].forEach(id => {{
    const select = document.getElementById(id);
    Object.keys(kurlar).forEach(code => {{
        if (![...select.options].some(option => option.value === code)) {{
            const option = document.createElement('option');
            option.value = code;
            option.textContent = names[code] || code;
            select.appendChild(option);
        }}
    }});
}});
}}
function kurGorunumunuGuncelle() {{
const usd = Number(kurlar.USD);
const eur = Number(kurlar.EUR);
document.getElementById('usd-kuru').textContent = Number.isFinite(usd) && usd > 0 ? usd.toFixed(4) : '--';
document.getElementById('eur-kuru').textContent = Number.isFinite(eur) && eur > 0 ? eur.toFixed(4) : '--';
document.querySelector('.kayan-yazi').textContent =
    Object.entries(kurlar)
        .filter(([, rate]) => Number.isFinite(Number(rate)) && Number(rate) > 0)
        .map(([code, rate]) => code + ': ' + rate + ' TL')
        .join(' . ');
kurSecenekleriniGuncelle();
}}
function baslangicKurOnbellekYukle() {{
const initialStale = document.body.dataset.ratesStale === 'true';
const initialUpdatedAt = document.body.dataset.ratesUpdatedAt;
const serverRatesValid = gecerliKurHaritasi(kurlar);
const saved = yerelVeriKaydiniOku('doviz-kurlar');
const savedRates = saved && gecerliKurHaritasi(saved.data);
const savedLive = yerelVeriKaydiniOku('canli-kurlar');
const savedLiveRates = savedLive && gecerliKurHaritasi(savedLive.data);
const useSavedRates = savedRates && (!serverRatesValid ||
    (initialStale && yerelKayitDahaYeniMi(saved, initialUpdatedAt)) ||
    (!initialStale && yerelKayitDahaYeniMi(saved, initialUpdatedAt)));
if (useSavedRates) {{
    kurlar = {{ ...kurlar, ...savedRates }};
}}
if (savedLiveRates && (!serverRatesValid || initialStale ||
    yerelKayitDahaYeniMi(savedLive, initialUpdatedAt))) {{
    kurlar.USD = savedLiveRates.USD;
    kurlar.EUR = savedLiveRates.EUR;
    veriKaynakDurumunuAyarla('liveRates', true);
}}
if (!initialStale && serverRatesValid &&
    (!saved || yerelKayitDahaYeniMi({{ updatedAt: initialUpdatedAt }}, saved.updatedAt))) {{
    yerelVeriKaydiniYaz('doviz-kurlar', kurlar, initialUpdatedAt);
}}
veriKaynakDurumunuAyarla('baseRates', initialStale || !serverRatesValid);
kurGorunumunuGuncelle();
}}
window.addEventListener('offline', baglantiRozetiniGuncelle);
window.addEventListener('online', baglantiRozetiniGuncelle);
baslangicKurOnbellekYukle();
function sonucKutusuYaz(metin, anaTutar, birim = 'TL', yuzdeUygula = true) {{
const result = document.getElementById('sonuc-metin');
const detail = document.getElementById('sonuc-ayrinti');
result.textContent = metin;
const percent = Number(document.getElementById('adjustment-percent').value);
if (!yuzdeUygula || !Number.isFinite(anaTutar) || !Number.isFinite(percent) || percent === 0) {{
    detail.hidden = true;
    detail.textContent = '';
    return;
}}
const difference = anaTutar * percent / 100;
const netTotal = anaTutar + difference;
const formatMoney = value => new Intl.NumberFormat('tr-TR', {{
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
}}).format(Math.abs(value));
const amountSign = difference > 0 ? '+' : difference < 0 ? '-' : '';
const percentSign = percent > 0 ? '+' : percent < 0 ? '-' : '';
const percentText = percentSign + '%' + Math.abs(percent).toLocaleString('tr-TR', {{ maximumFractionDigits: 2 }});
detail.textContent = amountSign + formatMoney(difference) + ' ' + birim +
    ' (' + percentText + ') · Net: ' + formatMoney(netTotal) + ' ' + birim;
detail.hidden = false;
}}
function hesapla() {{
const miktar = parseFloat(document.getElementById('miktar').value) || 0;
const kaynak = document.getElementById('kaynakPara').value;
const hedef = document.getElementById('hedefPara').value;
if (!Number.isFinite(kurlar[kaynak]) || kurlar[kaynak] <= 0 ||
    !Number.isFinite(kurlar[hedef]) || kurlar[hedef] <= 0) {{
    sonucKutusuYaz('Kur verisi bekleniyor');
    return;
}}
const miktarTL = miktar * kurlar[kaynak];
const sonuc = miktarTL / kurlar[hedef];
if (!Number.isFinite(sonuc)) {{
    sonucKutusuYaz('Kur verisi bekleniyor');
    return;
}}
const kaynakAd = document.getElementById('kaynakPara').options[document.getElementById('kaynakPara').selectedIndex].text;
const hedefAd = document.getElementById('hedefPara').options[document.getElementById('hedefPara').selectedIndex].text;
sonucKutusuYaz(miktar + " " + kaynakAd + " = " + sonuc.toFixed(4) + " " + hedefAd,
    sonuc, hedef === 'TRY' ? 'TL' : hedef);
}}
function piyasaOzetiKartiniYaz(asset, value, changePercent, persist = true) {{
const numericValue = Number(value);
if (!Number.isFinite(numericValue) || numericValue <= 0) {{
    return;
}}
const valueElement = document.getElementById('market-' + asset + '-value');
const changeElement = document.getElementById('market-' + asset + '-change');
const fractionDigits = asset === 'USD' || asset === 'EUR' ? 4 : 2;
valueElement.textContent = new Intl.NumberFormat('tr-TR', {{
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits
}}).format(numericValue) + (asset === 'BIST100' ? '' : ' TL');
valueElement.dataset.value = String(numericValue);
if (!Number.isFinite(changePercent)) {{
    changeElement.className = 'market-summary-change market-summary-change-flat';
    changeElement.textContent = '--';
    delete changeElement.dataset.changePercent;
}} else if (changePercent > 0) {{
    changeElement.className = 'market-summary-change market-summary-change-up';
    changeElement.textContent = '+%' + changePercent.toFixed(2) + ' ▲';
    changeElement.dataset.changePercent = String(changePercent);
}} else if (changePercent < 0) {{
    changeElement.className = 'market-summary-change market-summary-change-down';
    changeElement.textContent = '-%' + Math.abs(changePercent).toFixed(2) + ' ▼';
    changeElement.dataset.changePercent = String(changePercent);
}} else {{
    changeElement.className = 'market-summary-change market-summary-change-flat';
    changeElement.textContent = '%0.00';
    changeElement.dataset.changePercent = '0';
}}
if (persist) {{
   piyasaOzetiYerelKaydet();
}}
}}
function piyasaOzetiYerelKaydet() {{
if (['liveRates', 'market', 'trend']
    .some(source => veriKaynakDurumlari[source]) || !navigator.onLine) {{
    return;
}}
const snapshot = {{}};
for (const asset of ['USD', 'EUR', 'GOLD', 'BIST100']) {{
    const valueElement = document.getElementById('market-' + asset + '-value');
    const changeElement = document.getElementById('market-' + asset + '-change');
    const value = Number(valueElement.dataset.value);
    const changePercent = Number(changeElement.dataset.changePercent);
    if (!Number.isFinite(value) || value <= 0 || !Number.isFinite(changePercent)) {{
        return;
    }}
    snapshot[asset] = {{ value, changePercent }};
}}
yerelVeriKaydiniYaz('piyasa-ozeti', snapshot, new Date().toISOString());
}}
function piyasaOzetiOnbellekYukle() {{
const saved = yerelVeriKaydiniOku('piyasa-ozeti');
if (saved && saved.data && typeof saved.data === 'object') {{
    const valid = ['USD', 'EUR', 'GOLD', 'BIST100'].every(asset => {{
        const item = saved.data[asset];
        return item && Number.isFinite(Number(item.value)) &&
            Number(item.value) > 0 && Number.isFinite(Number(item.changePercent));
    }});
    if (valid) {{
        for (const asset of ['USD', 'EUR', 'GOLD', 'BIST100']) {{
            const item = saved.data[asset];
            piyasaOzetiKartiniYaz(asset, Number(item.value), Number(item.changePercent), false);
        }}
        veriKaynakDurumunuAyarla('liveRates', true);
        veriKaynakDurumunuAyarla('trend', true);
        veriKaynakDurumunuAyarla('market', true);
    }}
}}
const bist = yerelVeriKaydiniOku('bist100');
if (bist && bist.data && Number.isFinite(Number(bist.data.value)) &&
    Number(bist.data.value) > 0 && Number.isFinite(Number(bist.data.changePercent)) &&
    (!saved || yerelKayitDahaYeniMi(bist, saved.updatedAt))) {{
    piyasaOzetiKartiniYaz('BIST100', Number(bist.data.value), Number(bist.data.changePercent), false);
    veriKaynakDurumunuAyarla('market', true);
}}
}}
function piyasaOzetiTrendleriniGuncelle() {{
if (!trendPayload || !trendPayload.series) {{
    return;
}}
['USD', 'EUR', 'GOLD'].forEach(asset => {{
    const values = trendPayload.series[asset];
    if (!Array.isArray(values) || values.length < 2) {{
        return;
    }}
    const current = (asset === 'USD' || asset === 'EUR') && Number.isFinite(kurlar[asset])
        ? kurlar[asset]
        : values[values.length - 1];
    const previous = values[values.length - 2];
    if (!Number.isFinite(current) || !Number.isFinite(previous) || previous <= 0) {{
        return;
    }}
    piyasaOzetiKartiniYaz(asset, current, ((current - previous) / previous) * 100);
}});
}}
async function bist100VerisiniYukle() {{
const status = document.getElementById('market-summary-error');
try {{
    const response = await fetch('/api/bist100', {{ cache: 'no-store' }});
    const payload = await response.json();
    if (!response.ok) {{
        throw new Error(payload.error || 'HTTP ' + response.status);
    }}
    const value = Number(payload.value);
    const changePercent = Number(payload.changePercent);
    if (!Number.isFinite(value) || value <= 0 || !Number.isFinite(changePercent)) {{
        throw new Error('BIST 100 yanıtı geçersiz.');
    }}
    const stale = payload.stale === true;
    const record = yerelVeriKaydiniOku('bist100');
    const savedBist = record && record.data;
    if (stale && savedBist && yerelKayitDahaYeniMi(record, payload.updatedAt)) {{
        piyasaOzetiKartiniYaz('BIST100', Number(savedBist.value), Number(savedBist.changePercent), false);
    }} else {{
        piyasaOzetiKartiniYaz('BIST100', value, changePercent, !stale);
    }}
    veriKaynakDurumunuAyarla('market', stale);
    if (!stale) {{
        yerelVeriKaydiniYaz('bist100', {{ value, changePercent }}, payload.updatedAt);
        piyasaOzetiYerelKaydet();
    }}
    status.hidden = !stale;
    status.textContent = stale ? uiText('BIST 100 için son geçerli veri gösteriliyor.') : '';
}} catch (error) {{
    console.error('BIST 100 verisi güncellenemedi:', error);
    const record = yerelVeriKaydiniOku('bist100');
    const savedBist = record && record.data;
    if (savedBist && Number.isFinite(Number(savedBist.value)) &&
        Number.isFinite(Number(savedBist.changePercent))) {{
        piyasaOzetiKartiniYaz('BIST100', Number(savedBist.value), Number(savedBist.changePercent), false);
    }}
    veriKaynakDurumunuAyarla('market', true);
    status.hidden = false;
    status.textContent = uiText('BIST 100 güncellenemedi; son geçerli veri korunuyor.');
}}
}}
function dovizKurlariniUygula(rates, updatedAt, stale) {{
const usd = Number(rates.USD);
const eur = Number(rates.EUR);
if (!Number.isFinite(usd) || usd <= 0 || !Number.isFinite(eur) || eur <= 0) {{
    throw new Error('Döviz kur verisi geçersiz.');
}}
kurlar.USD = usd;
kurlar.EUR = eur;
kurGorunumunuGuncelle();
if (!altinModu) {{
    hesapla();
}}
veriKaynakDurumunuAyarla('liveRates', stale);
if (!stale) {{
    yerelVeriKaydiniYaz('canli-kurlar', {{ USD: usd, EUR: eur }}, updatedAt);
}}
piyasaOzetiKartiniYaz('USD', usd, null, !stale);
piyasaOzetiKartiniYaz('EUR', eur, null, !stale);
if (trendPayload) {{
    trendDegisiminiGoster(trendActiveAsset);
}}
sepetSecenekleriniGuncelle();
sepetiGuncelle();
}}
async function dovizAnaKurlariniYenile() {{
const status = document.getElementById('kur-yenileme-durumu');
try {{
    const response = await fetch('/api/doviz-kurlari', {{ cache: 'no-store' }});
    const payload = await response.json();
    if (!response.ok) {{
        throw new Error(payload.error || 'HTTP ' + response.status);
    }}
    const providerRates = gecerliKurHaritasi(payload.rates);
    if (!providerRates) {{
        throw new Error('Döviz sağlayıcısı boş veya geçersiz veri döndürdü.');
    }}
    const stale = payload.stale === true;
    const saved = yerelVeriKaydiniOku('doviz-kurlar');
    const savedRates = saved && gecerliKurHaritasi(saved.data);
    const rates = stale && savedRates && yerelKayitDahaYeniMi(saved, payload.updatedAt)
        ? savedRates
        : providerRates;
    const mergedRates = {{ ...rates }};
    if (veriKaynakDurumlari.liveRates === false) {{
        mergedRates.USD = kurlar.USD;
        mergedRates.EUR = kurlar.EUR;
    }}
    kurlar = mergedRates;
    kurGorunumunuGuncelle();
    sepetSecenekleriniGuncelle();
    sepetiGuncelle();
    if (!altinModu) {{
        hesapla();
    }}
    veriKaynakDurumunuAyarla('baseRates', stale);
    if (!stale) {{
        yerelVeriKaydiniYaz('doviz-kurlar', kurlar, payload.updatedAt);
    }}
    if (trendPayload) {{
        trendDegisiminiGoster(trendActiveAsset);
    }}
    if (!stale && veriKaynakDurumlari.liveRates === false) {{
        status.hidden = true;
        status.textContent = '';
    }}
}} catch (error) {{
    console.error('Döviz sağlayıcısı verileri güncellenemedi:', error);
    const saved = yerelVeriKaydiniOku('doviz-kurlar');
    const savedRates = saved && gecerliKurHaritasi(saved.data);
    if (savedRates && !gecerliKurHaritasi(kurlar)) {{
        kurlar = {{ ...kurlar, ...savedRates }};
        kurGorunumunuGuncelle();
    }}
    veriKaynakDurumunuAyarla('baseRates', true);
    status.hidden = false;
    status.textContent = uiText('Döviz verisi güncellenemedi; son geçerli veriler korunuyor.');
}}
}}
async function dovizKurlariniYenile() {{
const status = document.getElementById('kur-yenileme-durumu');
try {{
    const response = await fetch('/api/live-kurlar', {{ cache: 'no-store' }});
    const latestRates = await response.json();
    if (!response.ok) {{
        throw new Error(latestRates.error || 'HTTP ' + response.status);
    }}
    const stale = latestRates.stale === true;
    const saved = yerelVeriKaydiniOku('canli-kurlar') || yerelVeriKaydiniOku('doviz-kurlar');
    const savedRates = saved && gecerliKurHaritasi(saved.data);
    const useSaved = stale && savedRates && yerelKayitDahaYeniMi(saved, latestRates.updatedAt);
    const rates = useSaved ? savedRates : latestRates;
    const updatedAt = useSaved ? saved.updatedAt : latestRates.updatedAt;
    dovizKurlariniUygula(rates, updatedAt, stale);
    status.hidden = !stale;
    status.textContent = stale ? uiText('Canlı kurlar için son geçerli veri gösteriliyor.') : '';
}} catch (error) {{
    console.error('Canlı döviz kurları güncellenemedi:', error);
    const saved = yerelVeriKaydiniOku('canli-kurlar') || yerelVeriKaydiniOku('doviz-kurlar');
    const savedRates = saved && gecerliKurHaritasi(saved.data);
    if (savedRates) {{
        try {{
            dovizKurlariniUygula(savedRates, saved.updatedAt, true);
        }} catch (cacheError) {{
            console.error('Saklanan canlı kurlar ekrana uygulanamadı:', cacheError);
        }}
    }}
    veriKaynakDurumunuAyarla('liveRates', true);
    status.hidden = false;
    status.textContent = uiText('Canlı kurlar güncellenemedi; son geçerli değerler korunuyor.');
}}
}}
function miktarListeleriniKapat() {{
document.querySelectorAll('.amount-dropdown').forEach(dropdown => dropdown.hidden = true);
document.querySelectorAll('.amount-picker-toggle').forEach(button => button.setAttribute('aria-expanded', 'false'));
}}
function miktarListesiniAc(event) {{
const button = event.currentTarget;
const dropdown = document.getElementById(button.getAttribute('aria-controls'));
const acilsin = dropdown.hidden;
miktarListeleriniKapat();
dropdown.hidden = !acilsin;
button.setAttribute('aria-expanded', String(acilsin));
}}
function miktarPresetSec(event) {{
const button = event.currentTarget;
const deger = button.dataset.amount;
const alanId = button.dataset.inputId;
const alan = document.getElementById(alanId);
alan.value = deger;
if (alanId === 'altin-miktar') {{
    altinHesapla();
}} else {{
    hesapla();
}}
miktarListeleriniKapat();
alan.focus();
}}
function tersCevir() {{
const kaynak = document.getElementById('kaynakPara');
const hedef = document.getElementById('hedefPara');
const temp = kaynak.value;
kaynak.value = hedef.value;
hedef.value = temp;
hesapla();
}}
function ceviriciModunuDegistir(mode) {{
if (!['currency', 'gold'].includes(mode)) {{
    return;
}}
converterMode = mode;
altinModu = mode === 'gold';
islemTuruRozetiniGuncelle();
document.getElementById('doviz-alani').hidden = mode !== 'currency';
document.getElementById('altin-alani').hidden = mode !== 'gold';
document.getElementById('trade-mode-row').hidden = false;
document.getElementById('adjustment-controls').hidden = false;
document.getElementById('converter-title').textContent =
    uiText(mode === 'gold' ? 'Altın Çevirici' : 'Döviz Çevirici');
document.getElementById('trade-mode-note').textContent = uiText(mode === 'gold'
    ? 'İZKO tablosundaki fiyat sütunu kullanılır.'
    : 'Dövizde mevcut kur kullanılır.');
document.querySelectorAll('[data-converter-mode]').forEach(button => {{
    const active = button.dataset.converterMode === mode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
}});
if (mode === 'gold') {{
    altinHesapla();
}} else if (mode === 'currency') {{
    hesapla();
}}
}}
function etkinIslemTuru() {{
return converterMode === 'gold' ? goldTradeMode : tradeMode;
}}
function islemTuruRozetiniGuncelle() {{
const mode = etkinIslemTuru();
document.querySelectorAll('#trade-mode-options [data-trade-mode]').forEach(button => {{
    const active = button.dataset.tradeMode === mode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
}});
}}
function islemTurunuDegistir(mode) {{
if (!['sale', 'credit', 'buy'].includes(mode)) {{
    return;
}}
if (converterMode === 'gold') {{
    goldTradeMode = mode;
    izkoSutunModu = mode === 'buy' ? 'alis' : 'kk';
    const table = document.querySelector('#gold-prices .gold-prices');
    if (table) {{
        izkoSutunModunuUygula(table);
    }}
}} else {{
    tradeMode = mode;
}}
islemTuruRozetiniGuncelle();
document.getElementById('trade-mode-note').textContent = uiText(converterMode === 'gold'
    ? 'İZKO tablosundaki fiyat sütunu kullanılır.'
    : 'Dövizde mevcut kur kullanılır.');
if (converterMode === 'gold') {{
    altinHesapla();
}} else {{
    hesapla();
}}
}}
function ceviriciyiTemizle() {{
document.getElementById('miktar').value = '1';
document.getElementById('altin-miktar').value = '1';
document.getElementById('adjustment-percent').value = '0';
miktarListeleriniKapat();
if (converterMode === 'gold') {{
    altinHesapla();
}} else {{
    hesapla();
}}
}}
function altinSecenekleriniGuncelle() {{
const select = document.getElementById('altin-turu');
const selectedName = select.value;
select.innerHTML = '';
const rows = document.querySelectorAll('#gold-prices .gold-prices tbody tr');
rows.forEach(row => {{
    const nameCell = row.querySelector('th[scope="row"]') || row.querySelector('th');
    const creditCell = row.cells[1];
    const saleCell = row.cells[2];
    if (!nameCell || (!creditCell && !saleCell)) {{
        return;
    }}
    const name = nameCell.textContent.trim();
    const creditPrice = creditCell
        ? izkoFiyatiniSayiyaCevir(creditCell.dataset.kkSatis || creditCell.textContent)
        : null;
    const buyPrice = creditCell
        ? izkoFiyatiniSayiyaCevir(creditCell.dataset.alis || '')
        : null;
    const salePrice = saleCell ? izkoFiyatiniSayiyaCevir(saleCell.textContent) : null;
    if (!name || (!Number.isFinite(creditPrice) &&
        !Number.isFinite(buyPrice) && !Number.isFinite(salePrice))) {{
        return;
    }}
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    option.dataset.creditPrice = Number.isFinite(creditPrice) ? String(creditPrice) : '';
    option.dataset.buyPrice = Number.isFinite(buyPrice) ? String(buyPrice) : '';
    option.dataset.salePrice = Number.isFinite(salePrice) ? String(salePrice) : '';
    select.appendChild(option);
}});
if (select.options.length === 0) {{
    const option = document.createElement('option');
    option.value = '';
    option.textContent = uiText('Güncel altın fiyatı bulunamadı');
    select.appendChild(option);
    select.disabled = true;
}} else {{
    select.disabled = false;
    if ([...select.options].some(option => option.value === selectedName)) {{
        select.value = selectedName;
    }}
}}
if (altinModu) {{
    altinHesapla();
}}
sepetSecenekleriniGuncelle();
sepetiGuncelle();
}}
function altinHesapla() {{
const miktarInput = document.getElementById('altin-miktar');
const select = document.getElementById('altin-turu');
const option = select.options[select.selectedIndex];
const miktar = Number.parseFloat(miktarInput.value);
const mode = goldTradeMode;
const fiyat = option
    ? Number(mode === 'buy'
        ? option.dataset.buyPrice
        : mode === 'sale' ? option.dataset.salePrice : option.dataset.creditPrice)
    : NaN;
if (!Number.isFinite(miktar)) {{
    sonucKutusuYaz('Geçerli bir miktar girin.');
    return;
}}
if (!Number.isFinite(fiyat) || fiyat <= 0) {{
    const message = mode === 'buy'
        ? 'Seçilen ürün için İZKO alış fiyatı bulunamadı.'
        : mode === 'sale'
            ? 'Güncel İZKO satış fiyatı bulunamadı.'
            : 'Güncel İZKO K.K Satış fiyatı bulunamadı.';
    sonucKutusuYaz(uiText(message));
    return;
}}
const miktarMetni = miktar.toLocaleString('tr-TR', {{ maximumFractionDigits: 2 }});
const toplam = miktar * fiyat;
const toplamMetni = new Intl.NumberFormat('tr-TR', {{ maximumFractionDigits: 2 }}).format(toplam);
const label = mode === 'buy' ? 'Alış' : mode === 'sale' ? 'Satış' : 'K.K Satış';
sonucKutusuYaz(miktarMetni + ' ' + option.textContent + ' · ' +
    label + ' = ' + toplamMetni + ' TL', toplam);
}}
function sepetKartSekmesiniDegistir(mode) {{
const historical = mode === 'historical';
document.getElementById('basket-panel').hidden = historical;
document.getElementById('gecmis-alani').hidden = !historical;
document.querySelectorAll('.widget-tab').forEach(button => {{
    const active = button.getAttribute('aria-controls') ===
        (historical ? 'gecmis-alani' : 'basket-panel');
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
}});
}}
function sepetSecenekleriniGuncelle() {{
const select = document.getElementById('sepet-tur');
if (!select) {{
    return;
}}
const selectedValue = select.value;
select.replaceChildren();
let currencyCodes = Object.entries(kurlar)
    .filter(([code, rate]) => code !== 'TRY' && Number.isFinite(Number(rate)) && Number(rate) > 0)
    .map(([code]) => code);
if (currencyCodes.length === 0) {{
    currencyCodes = ['USD', 'EUR'];
}}
currencyCodes.sort((left, right) => {{
    const preferred = ['USD', 'EUR'];
    const leftIndex = preferred.indexOf(left);
    const rightIndex = preferred.indexOf(right);
    if (leftIndex !== -1 || rightIndex !== -1) {{
        return (leftIndex === -1 ? preferred.length : leftIndex) -
            (rightIndex === -1 ? preferred.length : rightIndex);
    }}
    return left.localeCompare(right);
}});
currencyCodes.forEach(code => {{
    const option = document.createElement('option');
    option.value = code;
    option.dataset.kind = 'currency';
    option.textContent = code;
    select.appendChild(option);
}});
const seenProducts = new Set();
document.querySelectorAll('#gold-prices .gold-prices tbody tr').forEach(row => {{
    const nameCell = row.querySelector('th[scope="row"]') || row.querySelector('th');
    const actualName = nameCell && nameCell.textContent.trim();
    if (!actualName || seenProducts.has(actualName)) {{
        return;
    }}
    seenProducts.add(actualName);
    const option = document.createElement('option');
    option.value = 'gold:' + actualName;
    option.dataset.kind = 'gold';
    option.dataset.productName = actualName;
    option.textContent = actualName;
    select.appendChild(option);
}});
if ([...select.options].some(option => option.value === selectedValue)) {{
    select.value = selectedValue;
}}
}}
function sepetBirimFiyatiniOku(item) {{
if (item.kind === 'currency') {{
    const price = Number(kurlar[item.code]);
    return Number.isFinite(price) && price > 0 ? price : null;
}}
const row = [...document.querySelectorAll('#gold-prices .gold-prices tbody tr')]
    .find(candidate => {{
        const name = candidate.querySelector('th[scope="row"]') || candidate.querySelector('th');
        return name && name.textContent.trim() === item.productName;
    }});
const saleCell = row && row.cells[2];
return saleCell ? izkoFiyatiniSayiyaCevir(saleCell.textContent) : null;
}}
function sepetKalemleriniHesapla() {{
return sepetKalemleri.map(item => {{
    const unitPrice = sepetBirimFiyatiniOku(item);
    const lineTotal = Number.isFinite(unitPrice) ? unitPrice * item.amount : null;
    const amountText = item.amount.toLocaleString('tr-TR', {{ maximumFractionDigits: 4 }});
    return {{
        item,
        lineTotal: Number.isFinite(lineTotal) ? lineTotal : null,
        label: item.kind === 'currency'
            ? amountText + ' ' + item.code
            : amountText + ' × ' + item.productName
    }};
}});
}}
function sepetiGuncelle() {{
const list = document.getElementById('sepet-kalemleri');
if (!list) {{
    return;
}}
const lines = sepetKalemleriniHesapla();
const invalidPrice = lines.some(line => line.lineTotal === null);
let total = 0;
list.replaceChildren();
if (lines.length === 0) {{
    const empty = document.createElement('li');
    empty.className = 'basket-empty';
    empty.textContent = uiText('Sepete henüz kalem eklenmedi.');
    list.appendChild(empty);
}}
lines.forEach((line, index) => {{
    const item = document.createElement('li');
    item.className = 'basket-item';
    const label = document.createElement('span');
    label.className = 'basket-item-label';
    label.textContent = line.label + ' —';
    const price = document.createElement('span');
    price.className = 'basket-item-amount';
    price.textContent = line.lineTotal === null
        ? uiText('Fiyat bekleniyor')
        : new Intl.NumberFormat('tr-TR', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }})
            .format(line.lineTotal) + ' TL';
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'basket-item-remove';
    remove.textContent = '×';
    remove.setAttribute('aria-label', uiTranslateDynamic(line.item.label + ' kalemini sil', remove));
    remove.addEventListener('click', () => sepetKaleminiSil(line.item.id));
    item.append(label, price, remove);
    list.appendChild(item);
    if (line.lineTotal !== null) {{
        total += line.lineTotal;
    }}
}});
const totalLabel = invalidPrice
    ? 'Toplam: Fiyat bekleniyor'
    : 'Toplam: ' + new Intl.NumberFormat('tr-TR', {{
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }}).format(total) + ' TL';
document.getElementById('sepet-toplam').textContent =
    uiTranslateDynamic(totalLabel, document.getElementById('sepet-toplam'));
}}
function sepetKalemiEkle() {{
const select = document.getElementById('sepet-tur');
const option = select.options[select.selectedIndex];
const amount = Number(document.getElementById('sepet-miktar').value);
const status = document.getElementById('sepet-status');
status.hidden = true;
if (!option || !Number.isFinite(amount) || amount <= 0) {{
    status.textContent = uiText('Geçerli ve sıfırdan büyük bir miktar girin.');
    status.hidden = false;
    return;
}}
const item = option.dataset.kind === 'gold'
    ? {{ kind: 'gold', productName: option.dataset.productName, label: option.textContent, amount }}
    : {{ kind: 'currency', code: option.value, label: option.textContent, amount }};
if (!Number.isFinite(sepetBirimFiyatiniOku(item))) {{
    status.textContent = uiText('Bu kalem için güncel fiyat bulunamadı.');
    status.hidden = false;
    return;
}}
item.id = sepetSiradakiKimlik++;
sepetKalemleri.push(item);
sepetiGuncelle();
}}
function sepetKaleminiSil(id) {{
sepetKalemleri = sepetKalemleri.filter(item => item.id !== id);
sepetiGuncelle();
}}
function sepetiTemizle() {{
sepetKalemleri = [];
document.getElementById('sepet-status').hidden = true;
sepetiGuncelle();
}}
async function guvenliKopyala(metin) {{
const text = String(metin);
let copyError = null;
try {{
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {{
        await navigator.clipboard.writeText(text);
        return;
    }}
}} catch (error) {{
    copyError = error;
}}
const textarea = document.createElement('textarea');
textarea.value = text;
textarea.setAttribute('readonly', '');
textarea.style.position = 'fixed';
textarea.style.left = '0';
textarea.style.top = '0';
textarea.style.width = '1px';
textarea.style.height = '1px';
textarea.style.fontSize = '16px';
textarea.style.opacity = '0';
let copied = false;
try {{
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    copied = typeof document.execCommand === 'function' && document.execCommand('copy');
}} catch (error) {{
    copyError = error;
}} finally {{
    if (textarea.parentNode) {{
        textarea.parentNode.removeChild(textarea);
    }}
}}
if (!copied) {{
    const error = new Error(uiText('Kopyalanamadı'));
    if (copyError) {{
        error.cause = copyError;
    }}
    throw error;
}}
}}
let sepetKopyaDurumZamani;
async function sepetiKopyala() {{
const button = document.getElementById('sepet-kopyala');
const status = document.getElementById('sepet-kopyalama-durumu');
const lines = sepetKalemleriniHesapla();
const invalidPrice = lines.some(line => line.lineTotal === null);
const total = lines.reduce((sum, line) => sum + (line.lineTotal || 0), 0);
const format = value => new Intl.NumberFormat('tr-TR', {{
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
}}).format(value);
const report = [
    uiText('DÖVİZ & ALTIN | SEPET'),
    uiText('Tarih/Saat:') + ' ' + new Date().toLocaleString(uiLocale()),
    '',
    ...(lines.length
        ? lines.map(line => line.label + ' — ' +
            (line.lineTotal === null ? 'Fiyat bekleniyor' : format(line.lineTotal) + ' TL'))
        : [uiText('Sepette kalem yok.')]),
    '',
    invalidPrice ? uiText('Toplam:') + ' ' + uiText('Fiyat bekleniyor')
        : uiText('Toplam:') + ' ' + format(total) + ' TL'
].join('\\n');
try {{
    await guvenliKopyala(report);
    button.textContent = '✓';
    button.classList.remove('copy-failed');
    button.classList.add('copied');
    status.textContent = uiText('Sepet panoya kopyalandı.');
    status.hidden = false;
}} catch (error) {{
    console.error('Sepet panoya kopyalanamadı:', error);
    button.textContent = '!';
    button.classList.remove('copied');
    button.classList.add('copy-failed');
    status.textContent = uiText('Sepet panoya kopyalanamadı.');
    status.hidden = false;
}}
clearTimeout(sepetKopyaDurumZamani);
sepetKopyaDurumZamani = setTimeout(() => {{
    button.textContent = '📋';
    button.classList.remove('copied', 'copy-failed');
    status.hidden = true;
}}, 1500);
}}
function yerelTarihiISOyaCevir(date = new Date()) {{
const pad = value => String(value).padStart(2, '0');
return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate());
}}
function gecmisTarihSecicisiniBaslat() {{
const today = yerelTarihiISOyaCevir();
const input = document.getElementById('gecmis-tarih');
input.max = today;
input.value = today;
}}
async function gecmisKurParaBirimleriniYukle() {{
const select = document.getElementById('gecmis-kur');
const errorElement = document.getElementById('gecmis-hata');
const selectedCode = select.value;
try {{
    const response = await fetch('/api/gecmis-kur-para-birimleri', {{ cache: 'no-store' }});
    const payload = await response.json();
    if (!response.ok || !Array.isArray(payload.currencies)) {{
        throw new Error(payload.error || 'Frankfurter para birimi listesi geçersiz.');
    }}
    const currencies = payload.currencies.filter(item =>
        item && /^[A-Z]{{3}}$/.test(item.code) && item.code !== 'TRY' &&
        typeof item.name === 'string' && typeof item.englishName === 'string'
    ).sort((left, right) => {{
        const preferred = ['USD', 'EUR'];
        const leftIndex = preferred.indexOf(left.code);
        const rightIndex = preferred.indexOf(right.code);
        if (leftIndex !== -1 || rightIndex !== -1) {{
            return (leftIndex === -1 ? preferred.length : leftIndex) -
                (rightIndex === -1 ? preferred.length : rightIndex);
        }}
        return left.code.localeCompare(right.code);
    }});
    if (currencies.length === 0) {{
        throw new Error('Frankfurter para birimi listesi boş.');
    }}
    select.replaceChildren();
    currencies.forEach(currency => {{
        const option = document.createElement('option');
        option.value = currency.code;
        option.dataset.nameTr = currency.name;
        option.dataset.nameEn = currency.englishName;
        select.appendChild(option);
    }});
    select.value = currencies.some(item => item.code === selectedCode)
        ? selectedCode
        : currencies.some(item => item.code === 'USD') ? 'USD' : currencies[0].code;
    uiLocalizeHistoricalCurrencyOptions();
    if (payload.stale === true) {{
        errorElement.textContent = uiText('Frankfurter kur listesi yenilenemedi; kayıtlı kurlar kullanılıyor.');
        errorElement.hidden = false;
    }} else if (errorElement.textContent === uiText('Frankfurter kur listesi yenilenemedi; kayıtlı kurlar kullanılıyor.')) {{
        errorElement.hidden = true;
    }}
}} catch (error) {{
    console.error('Geçmiş kur para birimleri alınamadı:', error);
    errorElement.textContent = uiText('Frankfurter kur listesi yenilenemedi; kayıtlı kurlar kullanılıyor.');
    errorElement.hidden = false;
}}
}}
async function gecmisKuruSorgula() {{
const date = document.getElementById('gecmis-tarih').value;
const currency = document.getElementById('gecmis-kur').value;
const amount = Number(document.getElementById('gecmis-miktar').value);
const button = document.getElementById('gecmis-sorgula');
const errorElement = document.getElementById('gecmis-hata');
const resultElement = document.getElementById('gecmis-sonuc');
const resultValue = document.getElementById('gecmis-sonuc-deger');
const note = document.getElementById('gecmis-sonuc-notu');
errorElement.hidden = true;
resultElement.hidden = true;
note.hidden = true;
if (!date || date > yerelTarihiISOyaCevir() || !Number.isFinite(amount) || amount < 0) {{
    errorElement.textContent = uiText('Geçerli bir tarih ve sıfır veya daha büyük bir miktar girin.');
    errorElement.hidden = false;
    return;
}}
button.disabled = true;
button.textContent = uiText('Sorgulanıyor…');
try {{
    const query = new URLSearchParams({{ date, currency }});
    const response = await fetch('/api/gecmis-kur?' + query.toString(), {{ cache: 'no-store' }});
    const payload = await response.json();
    if (!response.ok) {{
        throw new Error(payload.error || 'HTTP ' + response.status);
    }}
    const rate = Number(payload.rate);
    if (!Number.isFinite(rate) || rate <= 0 || !/^\\d{{4}}-\\d{{2}}-\\d{{2}}$/.test(payload.date || '')) {{
        throw new Error(uiText('Geçmiş kur yanıtı geçersiz.'));
    }}
    const total = rate * amount;
    if (!Number.isFinite(total)) {{
        throw new Error(uiText('Hesaplanan tutar geçersiz.'));
    }}
    const format = value => new Intl.NumberFormat('tr-TR', {{
        minimumFractionDigits: 2,
        maximumFractionDigits: 4
    }}).format(value);
    const amountText = amount.toLocaleString(uiLocale(), {{ maximumFractionDigits: 4 }});
    resultValue.textContent = amountText + ' ' + currency + ' × ' + format(rate) +
        ' TL = ' + format(total) + ' TL';
    resultElement.hidden = false;
    note.textContent = payload.date !== date
        ? uiText('En yakın işlem günü:') + ' ' + new Date(payload.date + 'T12:00:00').toLocaleDateString(uiLocale())
        : uiText('Kur tarihi:') + ' ' + new Date(payload.date + 'T12:00:00').toLocaleDateString(uiLocale());
    note.hidden = false;
}} catch (error) {{
    console.error('Geçmiş kur sorgulanamadı:', error);
    errorElement.textContent = error.message || uiText('Geçmiş kur verisi alınamadı.');
    errorElement.hidden = false;
}} finally {{
    button.disabled = false;
    button.textContent = uiText('Sorgula');
}}
}}
let paylasimGeriBildirimZamani;
let paylasimSeciliIcerik = 'izko';
function paylasimMenuAcKapat() {{
const button = document.getElementById('share-trigger');
const menu = document.getElementById('share-menu');
const acik = menu.hidden;
menu.hidden = !acik;
button.setAttribute('aria-expanded', String(acik));
if (acik) {{
    const selected = menu.querySelector('.share-option[aria-checked="true"]');
    (selected || menu.querySelector('[role="menuitem"]')).focus();
}}
}}
function paylasimMenuKapat(odagiGeriAl = false) {{
const button = document.getElementById('share-trigger');
const menu = document.getElementById('share-menu');
if (!menu.hidden) {{
    menu.hidden = true;
    button.setAttribute('aria-expanded', 'false');
    if (odagiGeriAl) {{
        button.focus();
    }}
}}
}}
function paylasimIceriginiSec(kind) {{
if (!['izko', 'summary', 'rates', 'all'].includes(kind)) {{
    return;
}}
paylasimSeciliIcerik = kind;
document.querySelectorAll('.share-option').forEach(option => {{
    const selected = option.dataset.shareKind === kind;
    option.classList.toggle('active', selected);
    option.setAttribute('aria-checked', String(selected));
}});
}}
function paylasimDurumunuGoster(message, copied = false) {{
const button = document.getElementById('share-trigger');
const status = document.getElementById('share-status');
status.textContent = message;
status.hidden = false;
button.classList.remove('copied', 'copy-failed');
if (copied) {{
    button.textContent = uiText('Kopyalandı ✓');
    button.classList.add('copied');
}} else {{
    button.textContent = '📋 ' + uiText('Paylaş / Kopyala');
}}
clearTimeout(paylasimGeriBildirimZamani);
paylasimGeriBildirimZamani = setTimeout(() => {{
    status.hidden = true;
    button.textContent = '📋 ' + uiText('Paylaş / Kopyala');
    button.classList.remove('copied', 'copy-failed');
}}, copied ? 1500 : 2500);
}}
function paylasimDegeriniOku(id) {{
const element = document.getElementById(id);
const value = element ? element.textContent.trim() : '';
return value && !value.startsWith('--') ? value : uiText('Veri bekleniyor');
}}
function paylasimDegisiminiOku(id) {{
const element = document.getElementById(id);
return element && element.textContent.trim() && element.textContent.trim() !== '--'
    ? element.textContent.trim()
    : uiText('Değişim verisi bekleniyor');
}}
function piyasaOzetiPaylasimMetni() {{
return [
    uiText('DÖVİZ & ALTIN | PİYASA ÖZETİ'),
    uiText('Tarih/Saat:') + ' ' + new Date().toLocaleString(uiLocale()),
    '',
    uiText('Dolar (USD):') + ' ' + paylasimDegeriniOku('market-USD-value') +
        ' (' + paylasimDegisiminiOku('market-USD-change') + ')',
    uiText('Euro (EUR):') + ' ' + paylasimDegeriniOku('market-EUR-value') +
        ' (' + paylasimDegisiminiOku('market-EUR-change') + ')',
    uiText('Gram Altın:') + ' ' + paylasimDegeriniOku('market-GOLD-value') +
        ' (' + paylasimDegisiminiOku('market-GOLD-change') + ')',
    'BIST 100: ' + paylasimDegeriniOku('market-BIST100-value') +
        ' (' + paylasimDegisiminiOku('market-BIST100-change') + ')'
].join('\\n');
}}
function izkoPaylasimMetni() {{
const rows = [...document.querySelectorAll('#gold-prices .gold-prices tbody tr')];
const selectedPriceLabel = uiText(izkoSutunModu === 'alis' ? 'Alış' : 'K.K Satış');
const prices = rows.map(row => {{
    const name = row.querySelector('th[scope="row"]') || row.querySelector('th');
    if (!name || row.cells.length < 3) {{
        return null;
    }}
    const selectedPrice = row.cells[1].textContent.replace(/[▲▼]/g, '').trim();
    const sale = row.cells[2].textContent.replace(/[▲▼]/g, '').trim();
    if (!selectedPrice || !sale) {{
        return null;
    }}
    return '• ' + name.textContent.trim() + ': ' + selectedPriceLabel + ' ' + selectedPrice +
        ' | ' + uiText('Satış') + ' ' + sale;
}}).filter(Boolean);
return [
    uiText('DÖVİZ & ALTIN | İZKO ALTIN FİYATLARI'),
    uiText('Tarih/Saat:') + ' ' + new Date().toLocaleString(uiLocale()),
    '',
    ...(prices.length ? prices : [uiText('Altın fiyatları bekleniyor.')])
].join('\\n');
}}
function paylasimMetniniOlustur(kind) {{
if (kind === 'izko') {{
    return izkoPaylasimMetni();
}}
if (kind === 'summary') {{
    return piyasaOzetiPaylasimMetni();
}}
if (kind === 'rates') {{
    return [
        uiText('DÖVİZ & ALTIN | DÖVİZ KURLARI'),
        uiText('Tarih/Saat:') + ' ' + new Date().toLocaleString(uiLocale()),
        '',
        'USD: ' + paylasimDegeriniOku('market-USD-value'),
        'EUR: ' + paylasimDegeriniOku('market-EUR-value')
    ].join('\\n');
}}
return [
    piyasaOzetiPaylasimMetni(),
    '',
    izkoPaylasimMetni()
].join('\\n');
}}
async function paylasimSeceneginiKopyala() {{
const report = paylasimMetniniOlustur(paylasimSeciliIcerik);
paylasimMenuKapat(true);
try {{
    await guvenliKopyala(report);
    paylasimDurumunuGoster(uiText('Kopyalandı ✓'), true);
}} catch (error) {{
    console.error('Paylaşım metni panoya kopyalanamadı:', error);
    paylasimDurumunuGoster(uiText('Kopyalanamadı'));
    document.getElementById('share-trigger').classList.add('copy-failed');
}}
}}
function paylasimWhatsAppIle() {{
const report = paylasimMetniniOlustur(paylasimSeciliIcerik);
paylasimMenuKapat(true);
window.open('https://wa.me/?text=' + encodeURIComponent(report), '_blank', 'noopener,noreferrer');
paylasimDurumunuGoster(uiText('WhatsApp ile paylaşım başlatıldı.'));
}}
function paylasimEpostaIle() {{
const report = paylasimMetniniOlustur(paylasimSeciliIcerik);
paylasimMenuKapat(true);
const subject = encodeURIComponent(uiText('Güncel Piyasa Kurları'));
window.location.href = 'mailto:?subject=' + subject + '&body=' + encodeURIComponent(report);
paylasimDurumunuGoster(uiText('E-posta uygulaması açıldı.'));
}}
async function paylasimDigerIle() {{
const report = paylasimMetniniOlustur(paylasimSeciliIcerik);
paylasimMenuKapat(true);
if (typeof navigator.share !== 'function') {{
    try {{
        await guvenliKopyala(report);
        paylasimDurumunuGoster(uiText('Metin kopyalandı, uygulamaya yapıştırabilirsiniz'), true);
    }} catch (error) {{
        console.error('Paylaşım metni panoya kopyalanamadı:', error);
        paylasimDurumunuGoster(uiText('Kopyalanamadı'));
        document.getElementById('share-trigger').classList.add('copy-failed');
    }}
    return;
}}
try {{
    await navigator.share({{ title: uiText('Döviz & Altın'), text: report }});
    paylasimDurumunuGoster(uiText('Paylaşım penceresi açıldı.'));
}} catch (error) {{
    if (error && error.name === 'AbortError') {{
        paylasimDurumunuGoster(uiText('Paylaşım iptal edildi.'));
        return;
    }}
    console.error('Yerel paylaşım açılamadı:', error);
    paylasimDurumunuGoster(uiText('Paylaşım açılamadı.'));
}}
}}
document.addEventListener('click', event => {{
if (!document.getElementById('share-control').contains(event.target)) {{
    paylasimMenuKapat();
}}
}});
document.addEventListener('keydown', event => {{
if (event.key === 'Escape') {{
    paylasimMenuKapat(true);
}}
}});
const kopyalaIkonu = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="7" y="5" width="13" height="16" rx="2"></rect><path d="M10 5V4a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v1"></path><path d="M10 11h7M10 15h7"></path></svg>';
const kopyalandiIkonu = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 4 4L19 6"></path></svg>';
const kopyalamaHataIkonu = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 8v5"></path><path d="M12 17h.01"></path><circle cx="12" cy="12" r="9"></circle></svg>';
let kopyalamaGeriBildirimZamani;
function kopyalamaGeriBildiriminiGoster(basarili) {{
const button = document.getElementById('sonuc');
const icon = document.getElementById('sonuc-ikon');
button.classList.remove('copied', 'copy-failed');
button.classList.add(basarili ? 'copied' : 'copy-failed');
button.setAttribute('aria-label', uiText(basarili ? 'Sonuç kopyalandı' : 'Sonuç kopyalanamadı'));
button.title = uiText(basarili ? 'Kopyalandı!' : 'Kopyalanamadı');
icon.innerHTML = basarili ? kopyalandiIkonu : kopyalamaHataIkonu;
clearTimeout(kopyalamaGeriBildirimZamani);
kopyalamaGeriBildirimZamani = setTimeout(() => {{
    button.classList.remove('copied', 'copy-failed');
    button.setAttribute('aria-label', uiText('Sonucu kopyala'));
    button.title = uiText('Sonucu kopyala');
    icon.innerHTML = kopyalaIkonu;
}}, 1500);
}}
async function sonucuKopyala() {{
const main = document.getElementById('sonuc-metin').textContent.trim();
const detail = document.getElementById('sonuc-ayrinti').hidden
    ? ''
    : document.getElementById('sonuc-ayrinti').textContent.trim();
const text = [main, detail].filter(Boolean).join('\\n');
try {{
    await guvenliKopyala(text);
    kopyalamaGeriBildiriminiGoster(true);
}} catch (error) {{
    console.error('Sonuç panoya kopyalanamadı:', error);
    kopyalamaGeriBildiriminiGoster(false);
}}
}}
function izkoFiyatiniSayiyaCevir(metin) {{
const normalized = metin.replace(/[^\\d,.-]/g, '').replace(/\\./g, '').replace(',', '.');
if (!normalized) {{
    return null;
}}
const sayi = Number(normalized);
return Number.isFinite(sayi) && sayi > 0 ? sayi : null;
}}
function izkoFiyatlariniHaritala(table) {{
const fiyatlar = new Map();
table.querySelectorAll('tbody tr').forEach(row => {{
    const nameCell = row.querySelector('th[scope="row"]') || row.querySelector('th');
    if (!nameCell) {{
        return;
    }}
    const cells = [...row.querySelectorAll('td')];
    const selectedPrice = cells[0]
        ? izkoSutunModu === 'alis'
            ? cells[0].dataset.alis
            : cells[0].dataset.kkSatis || cells[0].textContent
        : '';
    const prices = [
        izkoFiyatiniSayiyaCevir(selectedPrice || ''),
        izkoFiyatiniSayiyaCevir(cells[1] ? cells[1].textContent : '')
    ];
    fiyatlar.set(nameCell.textContent.trim(), prices);
}});
return fiyatlar;
}}
function izkoTabloSecicisiniHazirla(table) {{
const header = table.querySelector('thead tr th:nth-child(2)');
if (header && !header.querySelector('.gold-price-mode')) {{
    const label = document.createElement('label');
    label.className = 'gold-price-mode-wrap';
    const select = document.createElement('select');
    select.className = 'gold-price-mode';
    select.setAttribute('aria-label', uiText('Altın fiyat sütunu'));
    select.add(new Option('K.K Satış', 'kk'));
    select.add(new Option('Alış', 'alis'));
    select.setAttribute('onchange', 'izkoSutunModunuAyarla(this.value)');
    const arrow = document.createElement('span');
    arrow.setAttribute('aria-hidden', 'true');
    arrow.textContent = '▾';
    label.append(select, arrow);
    header.replaceChildren(label);
}}
table.querySelectorAll('tbody tr').forEach(row => {{
    const cell = row.cells[1];
    if (!cell) {{
        return;
    }}
    if (!cell.dataset.kkSatis) {{
        cell.dataset.kkSatis = cell.textContent.replace(/[▲▼]/g, '').trim();
    }}
    if (!cell.dataset.alis) {{
        cell.dataset.alis = '- TL';
    }}
}});
}}
function izkoSutunModunuUygula(table) {{
const selector = table.querySelector('.gold-price-mode');
if (selector) {{
    selector.value = izkoSutunModu;
}}
table.querySelectorAll('tbody tr').forEach(row => {{
    const cell = row.cells[1];
    if (!cell) {{
        return;
    }}
    cell.classList.remove('price-up', 'price-down');
    const indicator = cell.querySelector('.price-change');
    if (indicator) {{
        indicator.remove();
    }}
    const selectedPrice = izkoSutunModu === 'alis'
        ? cell.dataset.alis
        : cell.dataset.kkSatis;
    cell.textContent = selectedPrice || '- TL';
}});
}}
function izkoSutunModunuAyarla(mode) {{
if (mode !== 'kk' && mode !== 'alis') {{
    return;
}}
izkoSutunModu = mode;
goldTradeMode = mode === 'alis' ? 'buy' : 'credit';
islemTuruRozetiniGuncelle();
const table = document.querySelector('#gold-prices .gold-prices');
if (table) {{
    izkoSutunModunuUygula(table);
}}
if (converterMode === 'gold') {{
    altinHesapla();
}}
}}
function izkoSonGuncellemeSaatiniYaz(updatedAt) {{
const date = updatedAt ? new Date(updatedAt) : new Date();
if (!Number.isFinite(date.getTime())) {{
    return;
}}
const time = document.getElementById('gold-last-update-time');
time.dateTime = date.toISOString();
time.textContent = date.toLocaleTimeString(uiLocale());
}}
function izkoTabloHtmliGecerliMi(tableHtml) {{
if (typeof tableHtml !== 'string') {{
    return false;
}}
const parsed = new DOMParser().parseFromString(tableHtml, 'text/html');
const table = parsed.querySelector('.gold-prices');
return Boolean(table && table.querySelector('tbody tr'));
}}
function izkoTabloyuUygula(tableHtml, updatedAt, animateChanges) {{
const parsed = new DOMParser().parseFromString(tableHtml, 'text/html');
const table = parsed.querySelector('.gold-prices');
if (!table || !table.querySelector('tbody tr')) {{
    throw new Error('Saklanan İZKO tablosu geçerli değil.');
}}
izkoTabloSecicisiniHazirla(table);
const prices = document.getElementById('gold-prices');
const previousTable = prices.querySelector('.gold-prices');
prices.innerHTML = table.outerHTML;
const currentTable = prices.querySelector('.gold-prices');
izkoSutunModunuUygula(currentTable);
if (animateChanges) {{
    izkoDegisimleriniGoster(previousTable, currentTable);
}}
altinSecenekleriniGuncelle();
izkoSonGuncellemeSaatiniYaz(updatedAt);
}}
function baslangicIzkoOnbellekYukle() {{
const prices = document.getElementById('gold-prices');
const initialStale = document.body.dataset.izkoStale === 'true';
const initialAlisStale = document.body.dataset.izkoAlisStale === 'true';
const initialUpdatedAt = document.body.dataset.izkoUpdatedAt;
const initialTable = prices.querySelector('.gold-prices');
const initialHtml = initialTable ? initialTable.outerHTML : null;
const saved = yerelVeriKaydiniOku('izko-altin');
const savedValid = saved && izkoTabloHtmliGecerliMi(saved.data);
if (savedValid && (!initialHtml ||
    (initialStale && yerelKayitDahaYeniMi(saved, initialUpdatedAt)) ||
    (!initialStale && yerelKayitDahaYeniMi(saved, initialUpdatedAt)))) {{
    izkoTabloyuUygula(saved.data, saved.updatedAt, false);
    veriKaynakDurumunuAyarla('izko', true);
}} else if (initialHtml && !initialStale) {{
    izkoSonGuncellemeSaatiniYaz(initialUpdatedAt);
    veriKaynakDurumunuAyarla('izko', false);
    if (!saved || yerelKayitDahaYeniMi({{ updatedAt: initialUpdatedAt }}, saved.updatedAt)) {{
        yerelVeriKaydiniYaz('izko-altin', initialHtml, initialUpdatedAt);
    }}
}} else if (initialHtml) {{
    izkoSonGuncellemeSaatiniYaz(initialUpdatedAt);
    veriKaynakDurumunuAyarla('izko', true);
}} else {{
    veriKaynakDurumunuAyarla('izko', true);
    document.getElementById('gold-update-status').textContent =
        uiText('İZKO fiyatları alınamadı; son geçerli veri bekleniyor.');
}}
if (!initialStale) {{
    document.getElementById('gold-update-status').textContent = initialAlisStale
        ? uiText('Alış fiyatları güncellenemedi; mevcut değerler korunuyor.')
        : '';
}}
}}
function izkoDegisimleriniGoster(eskiTablo, yeniTablo) {{
if (!eskiTablo) {{
    return;
}}
const oncekiFiyatlar = izkoFiyatlariniHaritala(eskiTablo);
yeniTablo.querySelectorAll('tbody tr').forEach(row => {{
    const nameCell = row.querySelector('th[scope="row"]') || row.querySelector('th');
    const eskiSatirFiyatlari = nameCell ? oncekiFiyatlar.get(nameCell.textContent.trim()) : null;
    if (!eskiSatirFiyatlari) {{
        return;
    }}
    [...row.querySelectorAll('td')].forEach((cell, index) => {{
        const eskiFiyat = eskiSatirFiyatlari[index];
        const selectedPrice = izkoSutunModu === 'alis'
            ? cell.dataset.alis
            : cell.dataset.kkSatis;
        const yeniFiyat = izkoFiyatiniSayiyaCevir(
            index === 0 ? (selectedPrice || cell.textContent) : cell.textContent
        );
        if (eskiFiyat === null || yeniFiyat === null || eskiFiyat === yeniFiyat) {{
            return;
        }}
        const yukseldi = yeniFiyat > eskiFiyat;
        const indicator = document.createElement('span');
        indicator.className = 'price-change ' + (yukseldi ? 'price-change-up' : 'price-change-down');
        indicator.textContent = yukseldi ? '▲' : '▼';
        indicator.setAttribute('aria-label', uiText(yukseldi ? 'Fiyat yükseldi' : 'Fiyat düştü'));
        cell.classList.add(yukseldi ? 'price-up' : 'price-down');
        cell.appendChild(indicator);
    }});
}});
}}
async function altinFiyatlariniYenile() {{
const status = document.getElementById('gold-update-status');
try {{
const response = await fetch('/altin-fiyatlari', {{ cache: 'no-store' }});
const payload = await response.json();
if (!response.ok) {{
throw new Error(payload.error || 'HTTP ' + response.status);
}}
const responseText = payload.html;
if (!izkoTabloHtmliGecerliMi(responseText)) {{
    throw new Error('Güncel fiyat yanıtında tablo bulunamadı.');
}}
const stale = payload.stale === true;
const alisStale = payload.alisStale === true;
const updatedAt = payload.updatedAt;
const saved = yerelVeriKaydiniOku('izko-altin');
const useSaved = stale && saved && izkoTabloHtmliGecerliMi(saved.data) &&
    yerelKayitDahaYeniMi(saved, updatedAt);
const html = useSaved ? saved.data : responseText;
const timestamp = useSaved ? saved.updatedAt : updatedAt;
izkoTabloyuUygula(html, timestamp, !stale);
veriKaynakDurumunuAyarla('izko', stale);
if (!stale) {{
    yerelVeriKaydiniYaz('izko-altin', html, updatedAt);
}}
status.textContent = stale
    ? uiText('Bağlantı bekleniyor; son geçerli İZKO verisi gösteriliyor.')
    : alisStale
        ? uiText('Alış fiyatları güncellenemedi; mevcut değerler korunuyor.')
        : '';
}} catch (error) {{
console.error('Altın fiyatları güncellenemedi:', error);
const saved = yerelVeriKaydiniOku('izko-altin');
if (saved && izkoTabloHtmliGecerliMi(saved.data)) {{
    try {{
        izkoTabloyuUygula(saved.data, saved.updatedAt, false);
    }} catch (cacheError) {{
        console.error('Saklanan İZKO verisi ekrana uygulanamadı:', cacheError);
    }}
}}
veriKaynakDurumunuAyarla('izko', true);
status.textContent = uiText('Fiyatlar güncellenemedi; son geçerli veriler korunuyor.');
}}
}}
let trendChart = null;
let trendPayload = null;
let trendActiveAsset = 'USD';
let trendIsRising = true;
function trendFiyatiniBicimlendir(value, asset) {{
const maximumFractionDigits = asset === 'GOLD' ? 2 : 4;
return new Intl.NumberFormat('tr-TR', {{ maximumFractionDigits }}).format(value);
}}
function trendEtiketleriniYerellestir(labels) {{
if (uiLanguage !== 'en') {{
    return labels;
}}
const months = {{
    Oca: 'Jan', Şub: 'Feb', Nis: 'Apr', Haz: 'Jun', Tem: 'Jul',
    Ağu: 'Aug', Eyl: 'Sep', Eki: 'Oct', Kas: 'Nov', Ara: 'Dec'
}};
return labels.map(label => label.replace(/(?:Oca|Şub|Nis|Haz|Tem|Ağu|Eyl|Eki|Kas|Ara)/g, month => months[month] || month));
}}
function trendTemaGuncelle() {{
if (!trendChart) {{
    return;
}}
const darkMode = document.body.classList.contains('dark-mode');
const textColor = darkMode ? '#cbd5e1' : '#64748b';
const gridColor = darkMode ? 'rgba(203, 213, 225, 0.13)' : 'rgba(71, 85, 105, 0.12)';
trendChart.options.scales.x.ticks.color = textColor;
trendChart.options.scales.y.ticks.color = textColor;
trendChart.options.scales.y.grid.color = gridColor;
trendChart.options.plugins.tooltip.backgroundColor = darkMode ? '#111827' : '#ffffff';
trendChart.options.plugins.tooltip.titleColor = darkMode ? '#f8fafc' : '#1e293b';
trendChart.options.plugins.tooltip.bodyColor = darkMode ? '#e2e8f0' : '#334155';
trendChart.options.plugins.tooltip.borderColor = darkMode ? '#70566a' : '#f8bbd0';
trendChart.update('none');
}}
function trendDegisiminiGoster(asset) {{
if (!trendPayload) {{
    return;
}}
const sourceValues = trendPayload.series[asset];
if (!Array.isArray(sourceValues) || sourceValues.length < 2 || sourceValues.length !== trendPayload.labels.length) {{
    throw new Error('Trend verisinin tarih ve fiyat dizileri uyumsuz.');
}}
const values = sourceValues.slice();
if ((asset === 'USD' || asset === 'EUR') && Number.isFinite(kurlar[asset])) {{
    values[values.length - 1] = kurlar[asset];
}}
trendActiveAsset = asset;
trendIsRising = values[values.length - 1] >= values[0];
const current = values[values.length - 1];
const changePercent = ((current - values[0]) / values[0]) * 100;
piyasaOzetiTrendleriniGuncelle();
const unit = asset === 'GOLD' ? '1 g' : '1 ' + asset;
document.getElementById('trend-current-price').textContent =
    unit + ' = ' + trendFiyatiniBicimlendir(current, asset) + ' TL';
const badge = document.getElementById('trend-change-badge');
const absChange = Math.abs(changePercent).toFixed(2);
if (changePercent > 0) {{
    badge.className = 'trend-change-badge trend-change-up';
    badge.textContent = '+%' + absChange + ' ▲';
}} else if (changePercent < 0) {{
    badge.className = 'trend-change-badge trend-change-down';
    badge.textContent = '-%' + absChange + ' ▼';
}} else {{
    badge.className = 'trend-change-badge trend-change-flat';
    badge.textContent = '%0.00 —';
}}
document.querySelectorAll('[data-trend-asset]').forEach(button => {{
    const selected = button.dataset.trendAsset === asset;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
}});
if (trendChart) {{
    const color = trendIsRising ? '#86efac' : '#fda4af';
    trendChart.data.labels = trendEtiketleriniYerellestir(trendPayload.labels);
    trendChart.data.datasets[0].data = values;
    trendChart.data.datasets[0].borderColor = color;
    trendChart.data.datasets[0].pointBackgroundColor = color;
    trendChart.data.datasets[0].backgroundColor = context => {{
        const chartArea = context.chart.chartArea;
        if (!chartArea) {{
            return trendIsRising ? 'rgba(134, 239, 172, 0.16)' : 'rgba(253, 164, 175, 0.16)';
        }}
        const gradient = context.chart.ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
        gradient.addColorStop(0, trendIsRising ? 'rgba(134, 239, 172, 0.30)' : 'rgba(253, 164, 175, 0.28)');
        gradient.addColorStop(1, trendIsRising ? 'rgba(134, 239, 172, 0.01)' : 'rgba(253, 164, 175, 0.01)');
        return gradient;
    }};
    trendChart.update();
}}
}}
function trendHatasiniGoster(message) {{
const error = document.getElementById('trend-error');
error.textContent = uiTranslateDynamic(message, error);
error.hidden = false;
}}
function trendVerisiGecerliMi(payload) {{
if (!payload || !Array.isArray(payload.labels) || payload.labels.length < 2 || !payload.series) {{
    return false;
}}
return ['USD', 'EUR', 'GOLD'].every(asset => {{
    const values = payload.series[asset];
    return Array.isArray(values) && values.length === payload.labels.length &&
        values.every(value => Number.isFinite(Number(value)) && Number(value) > 0);
}});
}}
function trendOnbellekYukle() {{
const saved = yerelVeriKaydiniOku('trend');
if (!saved || !trendVerisiGecerliMi(saved.data)) {{
    return;
}}
trendPayload = saved.data;
veriKaynakDurumunuAyarla('trend', true);
trendDegisiminiGoster(trendActiveAsset);
}}
async function trendVerisiniYukle() {{
try {{
    const response = await fetch('/api/trend', {{ cache: 'no-store' }});
    const payload = await response.json();
    if (!response.ok) {{
        throw new Error(payload.error || 'HTTP ' + response.status);
    }}
    if (!trendVerisiGecerliMi(payload)) {{
        throw new Error('Trend yanıtı beklenen biçimde değil.');
    }}
    const stale = payload.stale === true;
    const saved = yerelVeriKaydiniOku('trend');
    const useSaved = stale && saved && trendVerisiGecerliMi(saved.data) &&
        yerelKayitDahaYeniMi(saved, payload.updatedAt);
    trendPayload = useSaved ? saved.data : payload;
    veriKaynakDurumunuAyarla('trend', stale);
    trendDegisiminiGoster(trendActiveAsset);
    if (!stale) {{
        yerelVeriKaydiniYaz('trend', payload, payload.updatedAt);
    }}
    const error = document.getElementById('trend-error');
    error.textContent = stale
        ? uiText('Bağlantı bekleniyor; son geçerli trend verisi gösteriliyor.')
        : '';
    error.hidden = !stale;
}} catch (error) {{
    console.error('Trend verileri yüklenemedi:', error);
    const saved = yerelVeriKaydiniOku('trend');
    if (saved && trendVerisiGecerliMi(saved.data)) {{
        trendPayload = saved.data;
        try {{
            trendDegisiminiGoster(trendActiveAsset);
        }} catch (cacheError) {{
            console.error('Saklanan trend verisi ekrana uygulanamadı:', cacheError);
        }}
    }}
    veriKaynakDurumunuAyarla('trend', true);
    trendHatasiniGoster(saved
        ? 'Trend güncellenemedi; son geçerli veri gösteriliyor.'
        : 'Trend verileri yüklenemedi: ' + error.message);
}}
}}
function trendKartiniBaslat() {{
document.querySelectorAll('[data-trend-asset]').forEach(button => {{
    button.addEventListener('click', () => {{
        try {{
            trendDegisiminiGoster(button.dataset.trendAsset);
        }} catch (error) {{
            console.error('Trend varlığı seçilemedi:', error);
            trendHatasiniGoster(error.message);
        }}
    }});
}});
if (typeof Chart === 'undefined') {{
    const error = new Error('Chart.js yüklenemedi.');
    console.error(error);
    trendHatasiniGoster(error.message);
    return;
}}
trendChart = new Chart(document.getElementById('trend-chart'), {{
    type: 'line',
    data: {{
        labels: [],
        datasets: [{{
            label: 'TL',
            data: [],
            fill: true,
            tension: 0.4,
            borderWidth: 2,
            pointRadius: 2,
            pointHoverRadius: 5,
            pointHitRadius: 12,
            borderColor: '#86efac',
            pointBackgroundColor: '#86efac',
            backgroundColor: 'rgba(134, 239, 172, 0.12)'
        }}]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        interaction: {{ mode: 'nearest', intersect: false }},
        plugins: {{
            legend: {{ display: false }},
            tooltip: {{
                enabled: true,
                displayColors: false,
                padding: 10,
                cornerRadius: 8,
                borderWidth: 1,
                callbacks: {{
                    title: items => items.length ? items[0].label : '',
                    label: context => trendFiyatiniBicimlendir(context.parsed.y, trendActiveAsset) + ' TL'
                }}
            }}
        }},
        scales: {{
            x: {{
                grid: {{ display: false }},
                border: {{ display: false }},
                ticks: {{ maxRotation: 0, autoSkip: true }}
            }},
            y: {{
                grid: {{ drawBorder: false }},
                border: {{ display: false }},
                ticks: {{
                    maxTicksLimit: 5,
                    callback: value => Number(value).toLocaleString('tr-TR', {{ maximumFractionDigits: 2 }})
                }}
            }}
        }}
    }}
}});
window.updateTrendChartTheme = trendTemaGuncelle;
trendTemaGuncelle();
if (trendPayload) {{
    trendDegisiminiGoster(trendActiveAsset);
}}
trendVerisiniYukle();
}}
window.addEventListener('DOMContentLoaded', trendKartiniBaslat, {{ once: true }});
document.getElementById('miktar').oninput = hesapla;
document.getElementById('altin-miktar').oninput = altinHesapla;
document.getElementById('altin-turu').onchange = altinHesapla;
document.getElementById('adjustment-percent').addEventListener('input', () => {{
    if (converterMode === 'gold') {{
        altinHesapla();
    }} else if (converterMode === 'currency') {{
        hesapla();
    }}
}});
document.querySelectorAll('.adjustment-shortcut').forEach(button => {{
    button.addEventListener('click', () => {{
        document.getElementById('adjustment-percent').value = button.dataset.percent;
        if (converterMode === 'gold') {{
            altinHesapla();
        }} else if (converterMode === 'currency') {{
            hesapla();
        }}
    }});
}});
gecmisTarihSecicisiniBaslat();
gecmisKurParaBirimleriniYukle();
document.querySelectorAll('.amount-picker-toggle').forEach(button => button.addEventListener('click', miktarListesiniAc));
document.querySelectorAll('.amount-preset').forEach(button => button.addEventListener('click', miktarPresetSec));
document.addEventListener('click', event => {{
if (!event.target.closest('.amount-picker')) {{
    miktarListeleriniKapat();
}}
}});
piyasaOzetiOnbellekYukle();
trendOnbellekYukle();
baslangicIzkoOnbellekYukle();
hesapla();
altinSecenekleriniGuncelle();
dovizAnaKurlariniYenile();
dovizKurlariniYenile();
bist100VerisiniYukle();
altinFiyatlariniYenile();
window.addEventListener('online', () => {{
    baglantiRozetiniGuncelle();
    gecmisKurParaBirimleriniYukle();
    dovizAnaKurlariniYenile();
    dovizKurlariniYenile();
    altinFiyatlariniYenile();
    bist100VerisiniYukle();
    trendVerisiniYukle();
}});
setInterval(dovizKurlariniYenile, 60000);
setInterval(dovizAnaKurlariniYenile, 1800000);
setInterval(bist100VerisiniYukle, 1200000);
setInterval(altinFiyatlariniYenile, 30000);
setInterval(trendVerisiniYukle, 300000);
</script>
<style>
.tarih-saat-kutusu {{
    position: fixed;
    bottom: 52px;
    right: 20px;
    background: #ffffff;
    color: #1e3a5f;
    padding: 10px 16px;
    border-radius: 12px;
    box-shadow: 0 8px 22px rgba(0, 0, 0, 0.5), 0 0 16px rgba(248, 187, 208, 0.16);
    border: 1px solid #f8bbd0;
    text-align: center;
    width: 138px;
    box-sizing: border-box;
    z-index: 999;
}}
#tarih-alani {{
    font-size: 13px;
    color: #1e3a5f;
    font-weight: normal;
    margin-bottom: 4px;
    letter-spacing: 0.5px;
    }}
#saat-alani {{
    font-size: 22px;
    color: #1e3a5f;
    font-weight: 700;
    letter-spacing: 1px;
    font-variant-numeric: tabular-nums;
    }}
    </style>
<script>
function saatGuncelle() {{
const simdi = new Date();
const tarih = simdi.toLocaleDateString(uiLocale(), {{ 
    day: '2-digit', 
    month: '2-digit', 
    year: 'numeric' 
    }});
const saat = simdi.toLocaleTimeString(uiLocale(), {{
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    }})
document.getElementById('tarih-alani').textContent = tarih;
document.getElementById('saat-alani').textContent = saat;
}}
saatGuncelle();
setInterval(saatGuncelle, 1000);
</script>
<style>
.tema-butonu {{
    position: fixed;
    bottom: 132px;
    right: 20px;
    background: #ffffff;
    color: #1e3a5f;
    border: 1px solid #f8bbd0;
    padding: 8px 12px;
    border-radius: 10px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 600;
    width: 138px;
    box-sizing: border-box;
    box-shadow: 0 8px 22px rgba(0, 0, 0, 0.5), 0 0 16px rgba(248, 187, 208, 0.16);
    z-index: 999;
    transition: all 0.2s ease;
}}
.topbar-actions {{
    display: contents;
}}
.ekran-modu-butonu {{
    right: 166px;
    width: 138px;
}}
.language-toggle {{
    right: 166px;
    bottom: 92px;
    width: 138px;
}}
.share-control {{
    position: fixed;
    right: 166px;
    bottom: 52px;
    width: 138px;
    z-index: 1002;
}}
.share-trigger {{
    display: block;
    width: 100%;
    min-height: 36px;
    padding: 8px 7px;
    border: 1px solid #f8bbd0;
    border-radius: 10px;
    background: #ffffff;
    color: #1e3a5f;
    box-shadow: 0 8px 22px rgba(0, 0, 0, 0.5), 0 0 16px rgba(248, 187, 208, 0.16);
    font: inherit;
    font-size: 12px;
    font-weight: 600;
    white-space: nowrap;
    cursor: pointer;
    transition: background-color 0.18s ease, border-color 0.18s ease, color 0.18s ease;
}}
.share-trigger:hover {{
    background: #fcebf1;
}}
.share-trigger.copied {{
    border-color: #86efac;
    background: #dcfce7;
    color: #15803d;
}}
.share-trigger.copy-failed {{
    border-color: #fca5a5;
    background: #fee2e2;
    color: #b91c1c;
}}
.share-menu {{
    position: absolute;
    right: 0;
    bottom: calc(100% + 8px);
    display: grid;
    gap: 3px;
    width: min(320px, calc(100vw - 42px));
    box-sizing: border-box;
    max-height: min(60vh, 360px);
    overflow-y: auto;
    padding: 6px;
    border: 1px solid #f0c4d1;
    border-radius: 12px;
    background: #ffffff;
    box-shadow: 0 10px 28px rgba(31, 41, 55, 0.22), 0 0 14px rgba(248, 187, 208, 0.16);
}}
.share-menu[hidden] {{
    display: none;
}}
.share-menu button {{
    width: 100%;
    padding: 9px 10px;
    border: 0;
    border-radius: 8px;
    background: transparent;
    color: #334155;
    font: inherit;
    font-size: 12px;
    text-align: left;
    cursor: pointer;
}}
.share-menu button:hover,
.share-menu button:focus-visible {{
    background: #fcebf1;
    color: #880e4f;
    outline: none;
}}
.share-option[aria-checked="true"] {{
    background: #fcebf1;
    color: #880e4f;
    font-weight: 700;
}}
.share-actions {{
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 4px;
    padding-top: 6px;
    border-top: 1px solid #f0c4d1;
}}
.share-menu .share-actions button {{
    min-width: 0;
    padding: 8px 5px;
    border: 1px solid #f0c4d1;
    background: #fff9fb;
    font-size: 11px;
    text-align: center;
}}
.share-status {{
    position: fixed;
    right: 166px;
    bottom: 180px;
    width: min(320px, calc(100vw - 190px));
    box-sizing: border-box;
    margin: 0;
    padding: 9px 11px;
    border: 1px solid #f0c4d1;
    border-radius: 9px;
    background: #fff9fb;
    color: #334155;
    box-shadow: 0 8px 22px rgba(31, 41, 55, 0.18);
    font-size: 12px;
    line-height: 1.4;
    z-index: 1003;
}}
.share-status[hidden] {{
    display: none;
}}
.screen-mode-status {{
    position: fixed;
    right: 20px;
    bottom: 92px;
    max-width: min(360px, calc(100vw - 24px));
    padding: 8px 11px;
    border: 1px solid #f0c4d1;
    border-radius: 9px;
    background: #fff9fb;
    color: #880e4f;
    box-shadow: 0 6px 18px rgba(31, 41, 55, 0.18);
    font-size: 12px;
    z-index: 1001;
}}
.tema-butonu:hover {{
    background: #fcebf1;
}}
body.dark-mode {{
    background-color: #0f172a !important;
    color: #f1f5f9 !important;
}}
body.dark-mode .kur-ozet {{
    background-color: #526a83;
    color: #f8fafc;
}}
body.dark-mode .kur-ozet strong {{
    color: #ffffff;
}}
body.dark-mode .card {{
    background: #292332;
    color: #f8fafc;
    border-color: #70566a;
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.42), 0 0 14px rgba(240, 171, 207, 0.08);
}}
body.dark-mode .card h3 {{
    color: #f0abcf !important;
}}
body.dark-mode .kur-ozet {{
    background: #201b29;
    color: #fff7fb;
    outline: 1px solid #b66f9b;
}}
body.dark-mode .currency-update-status {{
    color: #a1a1aa;
}}
body.dark-mode .kur-ozet strong {{
    color: #ffffff;
}}
body.dark-mode .card input,
body.dark-mode .card select {{
    background: #202638 !important;
    color: #f8fafc !important;
    border-color: #70566a !important;
}}
body.dark-mode .card button {{
    background: #201b29 !important;
    color: #f8fafc !important;
}}
body.dark-mode .card .converter-tab,
body.dark-mode .card .trade-mode-option,
body.dark-mode .card .adjustment-shortcut,
body.dark-mode .card .historical-query-button {{
    border-color: #70566a !important;
    background: #201b29 !important;
    color: #f0abcf !important;
}}
body.dark-mode .card .converter-tab.active,
body.dark-mode .card .converter-tab:hover,
body.dark-mode .card .trade-mode-option.active,
body.dark-mode .card .trade-mode-option:hover,
body.dark-mode .card .adjustment-shortcut:hover,
body.dark-mode .card .historical-query-button:hover {{
    border-color: #bd82a2 !important;
    background: #3a2937 !important;
    color: #f8ddeb !important;
}}
body.dark-mode .card .trade-mode-row,
body.dark-mode .card .adjustment-label,
body.dark-mode .card .historical-controls label {{
    color: #cbd5e1;
}}
body.dark-mode .card #gecmis-hata {{
    color: #fda4af;
}}
body.dark-mode .card .historical-result-note {{
    color: #cbd5e1;
}}
body.dark-mode .card .amount-picker-toggle {{
    background: transparent !important;
    color: #f0abcf !important;
}}
body.dark-mode .card .amount-picker-toggle:hover,
body.dark-mode .card .amount-picker-toggle[aria-expanded="true"] {{
    background: #302638 !important;
}}
body.dark-mode .amount-dropdown {{
    background: #201b29;
    border-color: #70566a;
    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.4), 0 0 12px rgba(240, 171, 207, 0.08);
}}
body.dark-mode .card .amount-preset {{
    background: #292332 !important;
    border-color: #70566a;
    color: #f8fafc !important;
}}
body.dark-mode .card .amount-preset:hover {{
    background: #302638 !important;
}}
body.dark-mode .gold-card {{
    background: #201b29;
    color: #f8fafc;
    border-color: #70566a;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.38), 0 0 16px rgba(248, 187, 208, 0.1);
}}
body.dark-mode .gold-card h3 {{
    color: #f0abcf !important;
    border-bottom-color: #70566a !important;
}}
body.dark-mode .gold-last-updated {{
    color: #a1a1aa;
}}
body.dark-mode .connection-status {{
    border-color: rgba(251, 191, 36, 0.25);
    background: rgba(251, 191, 36, 0.12);
    color: #fcd34d;
}}
body.dark-mode .market-summary {{
    background: #201b29;
    border-color: #70566a;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.38), 0 0 16px rgba(248, 187, 208, 0.1);
}}
body.dark-mode .market-summary-title,
body.dark-mode .market-summary-label {{
    color: #f0abcf;
}}
body.dark-mode .market-summary-item {{
    background: #292332;
    border-color: #493849;
}}
body.dark-mode .market-summary-item:hover {{
    border-color: #bd82a2;
    box-shadow: 0 6px 16px rgba(0, 0, 0, 0.25), 0 0 12px rgba(240, 171, 207, 0.1);
}}
body.dark-mode .market-summary-value {{
    color: #f8fafc;
}}
body.dark-mode .market-summary-change-up {{
    background: rgba(34, 197, 94, 0.16);
    color: #86efac;
}}
body.dark-mode .market-summary-change-down {{
    background: rgba(239, 68, 68, 0.16);
    color: #fda4af;
}}
body.dark-mode .market-summary-change-flat {{
    background: rgba(148, 163, 184, 0.16);
    color: #cbd5e1;
}}
body.dark-mode .market-summary-error {{
    color: #fda4af;
}}
body.dark-mode .trend-card {{
    background: #201b29;
    border-color: #70566a;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.38), 0 0 16px rgba(248, 187, 208, 0.1);
    color: #f8fafc;
}}
body.dark-mode .basket-card {{
    background: #201b29;
    border-color: #70566a;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.38), 0 0 16px rgba(248, 187, 208, 0.1);
    color: #f8fafc;
}}
body.dark-mode .widget-tab {{
    border-color: #70566a;
    background: #201b29;
    color: #e2d4df;
}}
body.dark-mode .widget-tab:hover,
body.dark-mode .widget-tab.active {{
    border-color: #bd82a2;
    background: #3a2937;
    color: #f8ddeb;
}}
body.dark-mode .basket-title {{
    color: #f0abcf;
}}
body.dark-mode .basket-add-button,
body.dark-mode .basket-clear-button,
body.dark-mode .basket-copy-button {{
    border-color: #70566a;
    background: #292332;
    color: #f0abcf;
}}
body.dark-mode .basket-add-button:hover,
body.dark-mode .basket-clear-button:hover,
body.dark-mode .basket-copy-button:hover {{
    border-color: #bd82a2;
    background: #3a2937;
}}
body.dark-mode .basket-item {{
    border-color: #493849;
    background: #292332;
    color: #e2d4df;
}}
body.dark-mode .basket-item-remove {{
    color: #fda4af;
}}
body.dark-mode .basket-empty {{
    color: #a1a1aa;
}}
body.dark-mode .basket-total {{
    border: 1px solid rgba(34, 197, 94, 0.3);
    background: rgba(34, 197, 94, 0.12);
    color: #86efac;
}}
body.dark-mode .basket-copy-button.copied {{
    border-color: #166534;
    background: rgba(34, 197, 94, 0.16);
    color: #86efac;
}}
body.dark-mode .basket-copy-button.copy-failed {{
    border-color: #991b1b;
    background: rgba(239, 68, 68, 0.16);
    color: #fda4af;
}}
body.dark-mode .basket-status,
body.dark-mode .historical-error {{
    color: #fda4af;
}}
body.dark-mode .basket-copy-status {{
    color: #86efac;
}}
body.dark-mode .historical-panel .historical-controls label,
body.dark-mode .historical-panel .historical-result-note {{
    color: #cbd5e1;
}}
body.dark-mode .historical-panel .historical-query-button {{
    border-color: #70566a;
    background: #292332;
    color: #f0abcf;
}}
body.dark-mode .historical-panel .historical-result {{
    border-color: rgba(34, 197, 94, 0.3);
    background: rgba(34, 197, 94, 0.12);
    color: #86efac;
}}
body.dark-mode .trend-title {{
    color: #f0abcf;
}}
body.dark-mode .trend-pill {{
    border-color: #70566a;
    color: #e2d4df;
}}
body.dark-mode .trend-pill:hover,
body.dark-mode .trend-pill.active {{
    background: #3a2937;
    border-color: #bd82a2;
    color: #f8ddeb;
}}
body.dark-mode .trend-current-price {{
    color: #f8fafc;
}}
body.dark-mode .trend-change-up {{
    background: rgba(34, 197, 94, 0.16);
    color: #86efac;
}}
body.dark-mode .trend-change-down {{
    background: rgba(239, 68, 68, 0.16);
    color: #fda4af;
}}
body.dark-mode .trend-change-flat {{
    background: rgba(148, 163, 184, 0.16);
    color: #cbd5e1;
}}
body.dark-mode .trend-error {{
    color: #fda4af;
}}
body.dark-mode .gold-prices th,
body.dark-mode .gold-prices td {{
    border-bottom-color: #493849;
}}
body.dark-mode .gold-prices thead th {{
    color: #f0abcf;
}}
body.dark-mode .gold-price-mode {{
    color: #f0abcf;
}}
body.dark-mode .gold-price-mode option {{
    background: #201b29;
    color: #f8fafc;
}}
body.dark-mode .gold-prices tbody th {{
    color: #f8fafc;
}}
body.dark-mode .gold-prices td:nth-child(2) {{
    color: #a8d5a2;
}}
body.dark-mode .gold-prices td:nth-child(3) {{
    color: #fda4af;
}}
body.dark-mode .gold-prices .price-change-up {{
    color: #86efac;
}}
body.dark-mode .gold-prices .price-change-down {{
    color: #fda4af;
}}
body.dark-mode #sonuc {{
    background: rgba(34, 197, 94, 0.1) !important;
    border: 1px solid rgba(34, 197, 94, 0.3);
    color: #86efac !important;
}}
body.dark-mode #sonuc.copied .result-copy-icon {{
    color: #86efac;
}}
body.dark-mode #sonuc.copy-failed .result-copy-icon {{
    color: #fda4af;
}}
body.dark-mode .tema-butonu {{
    background: #111827;
    color: #f8fafc;
    border-color: #70566a;
    box-shadow: 0 8px 22px rgba(0, 0, 0, 0.38), 0 0 12px rgba(240, 171, 207, 0.12);
}}
body.dark-mode .share-trigger {{
    border-color: #70566a;
    background: #111827;
    color: #f8fafc;
    box-shadow: 0 8px 22px rgba(0, 0, 0, 0.38), 0 0 12px rgba(240, 171, 207, 0.12);
}}
body.dark-mode .share-trigger:hover {{
    background: #1e293b;
}}
body.dark-mode .share-trigger.copied {{
    border-color: #166534;
    background: rgba(34, 197, 94, 0.16);
    color: #86efac;
}}
body.dark-mode .share-trigger.copy-failed {{
    border-color: #991b1b;
    background: rgba(239, 68, 68, 0.16);
    color: #fda4af;
}}
body.dark-mode .share-menu {{
    border-color: #70566a;
    background: #201b29;
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.48), 0 0 14px rgba(240, 171, 207, 0.12);
}}
body.dark-mode .share-menu button {{
    color: #e2d4df;
}}
body.dark-mode .share-menu button:hover,
body.dark-mode .share-menu button:focus-visible {{
    background: #3a2937;
    color: #f8ddeb;
}}
body.dark-mode .share-option[aria-checked="true"] {{
    background: #3a2937;
    color: #f8ddeb;
}}
body.dark-mode .share-actions {{
    border-color: #70566a;
}}
body.dark-mode .share-menu .share-actions button {{
    border-color: #70566a;
    background: #201b29;
}}
body.dark-mode .share-status {{
    border-color: #70566a;
    background: #201b29;
    color: #e2d4df;
}}
body.dark-mode .screen-mode-status {{
    border-color: #70566a;
    background: #111827;
    color: #f0abcf;
}}
body.dark-mode .tema-butonu:hover {{
    background: #1e293b;
}}
.mobile-topbar {{
    display: contents;
}}
body.dark-mode .tarih-saat-kutusu {{
    background: #111827;
    color: #f8fafc;
    border: 1px solid #70566a;
    box-shadow: 0 8px 22px rgba(0, 0, 0, 0.42), 0 0 14px rgba(248, 187, 208, 0.12);
}}
body.dark-mode #tarih-alani {{
    color: #cbd5e1;
}}
body.dark-mode #saat-alani {{
    color: #ffffff;
}}
body.dark-mode input,
body.dark-mode select {{
    background-color: #1e293b;
    color: #ffffff;
    border-color: #334155;
}}
@media (max-width: 768px) {{
    .mobile-topbar {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        width: 100%;
        margin: 0 auto 16px;
    }}
    .topbar-actions {{
        display: flex;
        flex: 0 0 auto;
        gap: 6px;
    }}
    .tarih-saat-kutusu {{
        position: static;
        flex: 1 1 auto;
        min-width: 0;
        width: auto;
        padding: 8px 10px;
    }}
    #tarih-alani {{
        font-size: 12px;
    }}
    #saat-alani {{
        font-size: 18px;
    }}
    .tema-butonu {{
        position: static;
        flex: 0 0 auto;
        width: auto;
        padding: 7px 9px;
        font-size: 12px;
        white-space: nowrap;
    }}
    .ekran-modu-butonu {{
        position: fixed;
        right: 12px;
        bottom: calc(132px + env(safe-area-inset-bottom));
        width: 138px;
        padding: 8px 7px;
        font-size: 12px;
    }}
    .language-toggle {{
        position: fixed;
        right: 12px;
        bottom: calc(92px + env(safe-area-inset-bottom));
        width: 138px;
        padding: 8px 7px;
        font-size: 12px;
        transition: background-color 0.2s ease, border-color 0.2s ease, color 0.2s ease;
    }}
    .share-control {{
        position: fixed;
        right: 12px;
        bottom: calc(52px + env(safe-area-inset-bottom));
        width: 138px;
    }}
    .share-status {{
        right: 12px;
        bottom: calc(180px + env(safe-area-inset-bottom));
        width: min(320px, calc(100vw - 24px));
    }}
    .screen-mode-status {{
        right: 12px;
        bottom: calc(70px + env(safe-area-inset-bottom));
    }}
    input,
    select {{
        font-size: 16px;
    }}
    .kayan-bant {{
        padding: 10px 0 calc(10px + env(safe-area-inset-bottom));
    }}
}}
</style>
<script>
let ekranModuDurumZamani;
function ekranModuGorunumunuGuncelle() {{
const active = Boolean(document.fullscreenElement);
document.body.classList.toggle('office-mode', active);
const button = document.getElementById('ekran-modu-btn');
button.setAttribute('aria-pressed', String(active));
button.title = uiText(active ? 'Tam ekrandan çık' : 'Ekran Modu');
}}
async function ekranModunuDegistir() {{
const status = document.getElementById('ekran-modu-durum');
status.hidden = true;
clearTimeout(ekranModuDurumZamani);
try {{
    if (document.fullscreenElement) {{
        await document.exitFullscreen();
    }} else if (typeof document.documentElement.requestFullscreen === 'function') {{
        await document.documentElement.requestFullscreen();
    }} else {{
        throw new Error(uiText('Bu tarayıcı tam ekran modunu desteklemiyor.'));
    }}
}} catch (error) {{
    console.error('Ekran modu değiştirilemedi:', error);
    status.textContent = error.message || uiText('Tam ekran izni alınamadı.');
    status.hidden = false;
    ekranModuDurumZamani = setTimeout(() => {{
        status.hidden = true;
    }}, 7000);
}}
}}
document.addEventListener('fullscreenchange', ekranModuGorunumunuGuncelle);
function temaDegistir() {{
    document.body.classList.toggle('dark-mode');
    const karanlikMi= document.body.classList.contains('dark-mode');
    const btn = document.getElementById('temaBtn');
    btn.textContent = uiText(karanlikMi ? '☀️ Aydınlık Mod' : '🌙 Karanlık Mod');
    localStorage.setItem('tema', karanlikMi ? 'dark' : 'light');
    if (typeof window.updateTrendChartTheme === 'function') {{
        window.updateTrendChartTheme();
    }}
}}
if (localStorage.getItem('tema') === 'dark') {{
    document.body.classList.add('dark-mode');
}}
uiApplyLanguage(uiLanguage, false);
</script>
<script>
if ('serviceWorker' in navigator) {{
    window.addEventListener('load', () => {{
        navigator.serviceWorker.register('/sw.js').catch(error => {{
            console.error('Service worker kaydedilemedi:', error);
        }});
    }});
}}
</script>
</body>
</html>
    '''
if __name__ == '__main__':
 app.run(host="0.0.0.0", port=5000, debug=True)
    def _izko_format_tl(value):
    try:
        num = float(value)
        if not math.isfinite(num) or num <= 0:
            return None
        return f"{round(num):,}".replace(",", ".")
    except (TypeError, ValueError):
        return None


def izko_altin_cek():
    global _altin_cache, _altin_cache_time, _altin_cache_updated_at
    global _altin_products_cache, _altin_alis_stale_cache
    with _altin_cache_lock:
        if _altin_cache and time.monotonic() - _altin_cache_time < 25:
            return (
                _altin_cache,
                False,
                _altin_cache_updated_at,
                list(_altin_products_cache),
                _altin_alis_stale_cache,
            )
        try:
            import websocket

            ws_url = "wss://veri.ozbag.com/socket.io/?status=true&EIO=4&transport=websocket"
            ws = websocket.create_connection(
                ws_url,
                timeout=10,
                header=[
                    "Origin: https://www.izko.org.tr",
                    "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                ],
            )
            prices_payload = None
            try:
                ws.recv()
                ws.send("40")
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    msg = ws.recv()
                    if msg == "2":
                        ws.send("3")
                    elif isinstance(msg, str) and msg.startswith('42["prices",'):
                        parsed = json.loads(msg[2:])
                        if len(parsed) >= 2 and isinstance(parsed[1], list):
                            prices_payload = parsed[1]
                            break
            finally:
                ws.close()

            if not prices_payload:
                raise ValueError("İZKO soketinden fiyat verisi gelmedi.")

            by_symbol = {
                str(item.get("Symbol", "")).lower(): item
                for item in prices_payload
                if isinstance(item, dict)
            }
            hedef_urunler = [
                ("has", "Has Altın"),
                ("yeniceyr", "Yeni Çeyrek"),
                ("eskiceyrek", "Eski Çeyrek"),
                ("yeniyarim", "Yeni Yarım"),
                ("eskiyarim", "Eski Yarım"),
                ("yenitam", "Yeni Tam"),
                ("eskitam", "Eski Tam"),
                ("yeniata", "Ata Altın"),
                ("yenigramse", "Gremse"),
                ("ata5li", "Ata Beşli"),
            ]

            liste = []
            for sym, label in hedef_urunler:
                item = by_symbol.get(sym)
                if not item:
                    continue
                ask = _izko_format_tl(item.get("Ask"))
                bid = _izko_format_tl(item.get("Bid"))
                if ask:
                    liste.append((label, ask, ask, (bid + " TL") if bid else "- TL"))

            if not liste:
                raise ValueError("İZKO fiyat listesi oluşturulamadı.")

            products = [
                {
                    "name": name,
                    "kkSatis": regular + " TL",
                    "satis": discount + " TL",
                    "alis": alis,
                }
                for name, regular, discount, alis in liste
            ]

            table = (
                '<table class="gold-prices">'
                '<thead><tr><th>Ürün</th>'
                '<th><label class="gold-price-mode-wrap">'
                '<select class="

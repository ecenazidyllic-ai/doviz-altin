import ssl
import urllib.request
import xml.etree.ElementTree as ET
def doviz_kurlarini_getir():
    url = "https://www.tcmb.gov.tr/kurlar/today.xml"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    response = urllib.request.urlopen(req)
    xml_data = response.read()
    root = ET.fromstring(xml_data)
    kurlar = {}
    for currency in root.findall('Currency'):
        code = currency.get('CurrencyCode')
        if code in ['USD', 'EUR']:
            forex_selling = currency.find('ForexSelling').text
            if forex_selling:
                kurlar[code] = float(forex_selling)
    return kurlar
kurlar = doviz_kurlarini_getir()
usd_tl = kurlar.get('USD')
eur_tl = kurlar.get('EUR')
print(f"1 USD = {usd_tl:.4f} TL")
print(f"1 EUR = {eur_tl:.4f} TL")
print("-" * 30)
tl_karsiligi_usd = 1 / usd_tl
tl_karsiligi_eur = 1 / eur_tl
print(f"1 TL = {tl_karsiligi_usd:.6f} USD")
print(f"1 TL = {tl_karsiligi_eur:.6f} EUR")
import tkinter as tk
pencere = tk.Tk()
pencere.title("Döviz Kurları")
pencere.geometry("300x220")
metin = f"1 USD = {usd_tl:.4f} TL\n1 EUR = {eur_tl:.4f} TL\n\n1 TL = {tl_karsiligi_usd:.6f} USD\n1 TL = {tl_karsiligi_eur:.6f} EUR"
etiket = tk.Label(pencere, text=metin, font=("Arial", 12), justify="center", pady=20)
etiket.pack()
pencere.mainloop()

        
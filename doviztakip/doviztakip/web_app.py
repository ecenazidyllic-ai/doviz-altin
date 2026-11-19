import json
import urllib.request
from flask import Flask, render_template_string
app= Flask(__name__)
import re
def izko_altin_cek():
   varsayilan = [
      ("22 AYAR", "6.290", "5.990"), ("18 AYAR", "6.050", "5.750"),
      ("14 AYAR", "5.550", "5.300"), ("18 AYAR", "3.100"),
      ("GRAM ALTIN", "6.290", "5.990"), ("ATA ALTIN", "44.900", "42.750"),
      ("ESKİ ÇEYREK", "11.000", "10.450"), ("YENİ ÇEYREK", "11.100", "10.550"),
      ("ESKİ YARIM", "22.000", "20.900"), ("YENİ YARIM", "22.200", "21.100"),
      ("ESKİ ZİYNET", "44.000", "41.800"), ("YENİ ZİYNET", "44.400", "42.200"),
      ("PAKETLİ HAS", "6.801,62", "6.477,73"), ("HAS ALTIN", "-", "6.365,00")
   ]
   try:
        url = "https://www.izko.org.tr/"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
   liste = []
   for ad, v_kk, v_satis in varsayilan:
            if ad == "HAS ALTIN":
                m = re.search(r'HAS ALTIN.*?([\d\.,]+)', html, re.S | re.I)
                liste.append((ad, "-", m.group(1) if m else v_satis))
            else:
                m = re.search(rf'{ad}.*?([\d\.,]+).*?([\d\.,]+)', html, re.S | re.I)
                liste.append((ad, m.group(1), m.group(2)) if m else (ad, v_kk, v_satis))
   return "".join([f'<div style="display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px dashed #f8bbd0; font-size:13px;"><span style="font-weight:bold; width:42%; color:#880e4f;">{a}</span><span style="color:#555; width:28%; text-align:right;">{k}</span><span style="color:#ad1457; font-weight:bold; width:30%; text-align:right;">{s}</span></div>' for a, k, s in liste])
   except Exception:
   return '<div style="color:red; text-align:center;">Fiyatlar alınamadı</div>'
@app.route("/altin-fiyatlari")
def altin_fiyatlari_api():
    return izko_altin_cek()
@app.route("/")
def ana_sayfa():
    
    url = "https://open.er-api.com/v6/latest/TRY"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as response:
       data = json.loads(response.read().decode("utf-8"))
    rates = data.get('rates', {})
    kurlar = {'TRY':1.0}
    for kod, oran in rates.items():
        if oran > 0:
           kurlar[kod] = round(1.0 / oran, 4)
    isimler = {
    "TRY": "Türk Lirası",
    "USD": "Amerikan Doları",
    "EUR": "Euro",
    "GBP": "İngiliz Sterlini",
    "CHF": "İsviçre Frangı",
    "CAD": "Kanada Doları",
    "AUD": "Avustralya Doları",
    "JPY": "Japon Yeri",
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
    serit_metni= " . ".join([f"{k}: {oran} TL" for k, oran in kurlar.items()])
return f'''<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<title>TCMB Canlı Döviz Kurları</title>
<meta http-equiv="refresh" content="60">
<style>
body {{
   font-family: Arial, sans-serif;
   background-color: #f4f6f9;
   display: flex;
   justify-content: center;
   align-items: center;
   min-height: 100vh;
   margin: 0;
   }}
   .card {{
      background: white;
      padding: 24px;
      border-radius: 12px;
      box-shadow: 0 4px 15px rgba(0,0,0,0.1);
      width: 330px;
      text-align: center;
      }}
      h3 {{ margin-top: 0; color: #202124; }}
      input, select {{
         padding: 8px;
         border: 1px solid #dadce0;
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
        @keyframes seritKaydir {{
        0% {{ transform: translateX(100w); }}
        100% {{ transform: translateX(-100%); }}
        }} 
        </style>
         </head>
         <body>
         <div style="display: flex; gap:25px; justify-content: center; align-items: flex-start;"> 
         <div class="card">
         <h3>Döviz Çevirici</h3>
         <div style="display: flex; justify-content: space-around; background: #f1f3f4; padding: 10px; border-radius: 8px; margin-bottom: 15px; font-size: 14px;">
         <div><strong>USD:</strong> {kurlar.get('USD', '-')} TL</div>
         <div><strong>EUR:</strong> {kurlar.get('EUR', '-')} TL</div>
         </div>
         <input type="number" id="miktar" value="1" min="0" oninput="hesapla()" style="width: 100%; margin-bottom: 12px;">
         <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 12px;">
         <select id="kaynakPara" onchange="hesapla()" style="width: 45%; padding: 8px;">
         {secenekler_kaynak}
         </select>
         <button type="button" onclick="tersCevir()" title="Degistir" style="background: #e0e0e0; border: none; border-radius: 50%; width: 34px; cursor: pointer; font-size: 16px;">⇄</button>
         <select id="hedefPara" onchange="hesapla()" style="width: 45%; padding: 8px;">
         {secenekler_hedef}
         </select>
         </div>
        <div id="sonuc" style="margin-top: 15px; padding: 12px; background: #e8f5e9; color: #2e7d32; text-align: center; border-radius: 6px; font-weight: bold; font-size: 18px;">-</div>
        <div/>
        <div style="background: #fdf2f4; border: 1px solid #f8bbd0; padding: 25px; border-radius: 16px; box-shadow: 0 4px 15px rgba(248, 187, 208, 0.3); width: 280px; text-align: center;">
        <h3 style="margin-top: 0; color: #880e4f; border-bottom: 2px solid #f8bbd0; padding-bottom: 10px; font-size: 18px;">İzmir Kuyumcular Odası</h3>
        <div style="margin-top: 15px; font-size: 15px;">
        <div style="display: flex; justify-content: space-between; margin-bottom: 12px; color: #4a4a4a;">
        altin_fiyatlari = izko_altin_cek()
        {altin_fiyatlari}
      </div>
      </div>
      </div>
      </div>
        <div class="kayan-bant">
        <div class="kayan-yazi">{serit_metni}</div>
        </div>
        <script>
        const kurlar = {json.dumps(kurlar)};
function hesapla() {{
const miktar = parseFloat(document.getElementById('miktar').value) || 0;
const kaynak = document.getElementById('kaynakPara').value;
const hedef = document.getElementById('hedefPara').value;
const miktarTL = miktar * kurlar[kaynak];
const sonuc = miktarTL / kurlar[hedef];
const kaynakAd = document.getElementById('kaynakPara').options[document.getElementById('kaynakPara').selectedIndex].text;
const hedefAd = document.getElementById('hedefPara').options[document.getElementById('hedefPara').selectedIndex].text;
document.getElementById('sonuc').innerText = miktar + " " + kaynakAd + " = " + sonuc.toFixed(4) + " " + hedefAd;
}}
function tersCevir() {{
const kaynak = document.getElementById('kaynakPara');
const hedef = document.getElementById('hedefPara');
const temp = kaynak.value;
kaynak.value = hedef.value;
hedef.value = temp;
hesapla();
}}
document.getElementById('miktar').oninput = hesapla;
hesapla();
</script>
</body>
</html>
    '''
if __name__ == '__main__':
 app.run(host="0.0.0.0", port=5000, debug=True)
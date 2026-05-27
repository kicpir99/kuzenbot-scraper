import requests
import re
import datetime
import dataclasses
from scraper import SmiteSourceScraper

print("Inicjalizacja potężnego silnika...")
scraper_engine = SmiteSourceScraper()

print("Skanowanie SmiteSource (metoda ze scanner.py)...")
baza_bogow = []
try:
    r = requests.get('https://smitesource.com/gods', headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
    frags = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', r.text)
    stream = ''.join(frags).replace('\\"', '"')
    slugs = sorted(set(re.findall(r'"slug":"([a-z0-9-]+)"', stream)))

    special = {
        'the-morrigan': 'The Morrigan', 'baron-samedi': 'Baron Samedi',
        'da-ji': 'Da Ji', 'guan-yu': 'Guan Yu', 'hou-yi': 'Hou Yi',
        'hun-batz': 'Hun Batz', 'jing-wei': 'Jing Wei',
        'morgan-le-fay': 'Morgan Le Fay', 'ne-zha': 'Ne Zha',
        'nu-wa': 'Nu Wa', 'sun-wukong': 'Sun Wukong',
    }

    for slug in slugs:
        name = special.get(slug, slug.replace('-', ' ').title())
        if name not in baza_bogow:
            baza_bogow.append(name)
    print(f"Pobrano {len(baza_bogow)} bogow.")
except Exception as e:
    print(f"Błąd pobierania listy: {e}")
    baza_bogow = ["Kuzenbo"]

# Tworzymy dwa osobne słowniki na oba tryby
dane_builds_dict = {}
dane_stats_dict = {}

for bog in baza_bogow:
    print(f"\n--- Pobieram dane dla: {bog} ---")
    
    # 1. Buildy Społeczności
    try:
        dane_boga_com = scraper_engine.get_all_builds(bog)
        if dane_boga_com and dane_boga_com.builds:
            dane_builds_dict[bog.lower()] = dataclasses.asdict(dane_boga_com)
    except Exception as e:
        print(f"Błąd pobierania buildów społeczności: {e}")
        
    # 2. Buildy Statystyczne (z Twojej potężnej metody)
    try:
        # Wymusza pobranie dogłębnych statystyk (fast_preview=False)
        dane_boga_stats = scraper_engine.get_smite2_live_builds(bog, fast_preview=False)
        if dane_boga_stats and dane_boga_stats.builds:
            dane_stats_dict[bog.lower()] = dataclasses.asdict(dane_boga_stats)
    except Exception as e:
        print(f"Błąd pobierania statystyk: {e}")

nowe_dane = {
    "aktualizacja": str(datetime.datetime.now()),
    "wiadomosc": "Paczka z buildami społeczności ORAZ statystykami!",
    "dane_builds": dane_builds_dict,
    "dane_stats": dane_stats_dict
}

try:
    odpowiedz = requests.post("http://92.5.91.226:8000/update", json=nowe_dane)
    print(f"Sukces: Oracle odpowiedział kodem: {odpowiedz.status_code}")
except Exception as e:
    print(f"Błąd wysyłki: {e}")

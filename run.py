import requests
import re
import datetime
import dataclasses
from scraper import SmiteSourceScraper

print("Inicjalizacja silnika...")
scraper_engine = SmiteSourceScraper()

# TWOJA ORYGINALNA METODA Z SCANNER.PY (Next.js Stream)
print("Skanowanie SmiteSource (metoda ze scanner.py)...")
baza_bogow = []
try:
    r = requests.get('https://smitesource.com/gods', headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
    # Rozkodowanie strumienia tak jak w Twoim starym pliku
    frags = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', r.text)
    stream = ''.join(frags).replace('\\"', '"')
    slugs = sorted(set(re.findall(r'"slug":"([a-z0-9-]+)"', stream)))

    # Słownik z wyjątkami, który miałeś przygotowany
    special = {
        'the-morrigan': 'The Morrigan', 'baron-samedi': 'Baron Samedi',
        'da-ji': 'Da Ji', 'guan-yu': 'Guan Yu', 'hou-yi': 'Hou Yi',
        'hun-batz': 'Hun Batz', 'jing-wei': 'Jing Wei',
        'morgan-le-fay': 'Morgan Le Fay', 'ne-zha': 'Ne Zha',
        'nu-wa': 'Nu Wa', 'sun-wukong': 'Sun Wukong',
    }

    # Konwersja slugów na czytelne nazwy
    for slug in slugs:
        name = special.get(slug, slug.replace('-', ' ').title())
        if name not in baza_bogow:
            baza_bogow.append(name)

    print(f"Pobrano {len(baza_bogow)} bogow: {baza_bogow}")
except Exception as e:
    print(f"Błąd pobierania listy: {e}")
    baza_bogow = ["Kuzenbo", "Ymir", "Loki"]

dane_bogow_dict = {}
# Dla testu bierzemy tylko 5 pierwszych postaci (alfabetycznie)
for bog in baza_bogow:
    print(f"Pobieram dane dla: {bog}")
    dane_boga = scraper_engine.get_all_builds(bog)
    if dane_boga and dane_boga.builds:
        dane_bogow_dict[bog.lower()] = dataclasses.asdict(dane_boga)

nowe_dane = {
    "aktualizacja": str(datetime.datetime.now()),
    "wiadomosc": "Paczka dostarczona autorskim kodem Kacpra ze scanner.py!",
    "dane": dane_bogow_dict
}

try:
    odpowiedz = requests.post("http://92.5.91.226:8000/update", json=nowe_dane)
    print(f"Sukces: Oracle odpowiedzial kodem: {odpowiedz.status_code}")
except Exception as e:
    print(f"Błąd wysyłki: {e}")

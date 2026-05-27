import requests
import re
import datetime
import dataclasses
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from scraper import SmiteSourceScraper

print("Inicjalizacja potężnego silnika (Wersja Wielowątkowa)...")
scraper_engine = SmiteSourceScraper()

print("Skanowanie SmiteSource w poszukiwaniu bogów...")
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
    print(f"Pobrano {len(baza_bogow)} bogów do przetworzenia.")
except Exception as e:
    print(f"Błąd pobierania listy: {e}")
    baza_bogow = ["Kuzenbo"]

dane_builds_dict = {}
dane_stats_dict = {}

# Funkcja dla pojedynczego pracownika (Wątku)
def process_god(bog):
    # Losowe opóźnienie na start (Jitter) - żeby 4 wątki nie uderzyły w serwer w tej samej milisekundzie
    time.sleep(random.uniform(0.5, 2.5))
    
    b_data, s_data = None, None
    print(f"[Start] -> {bog}")
    
    # 1. Buildy Społeczności
    try:
        dane_boga_com = scraper_engine.get_all_builds(bog)
        if dane_boga_com and dane_boga_com.builds:
            b_data = dataclasses.asdict(dane_boga_com)
    except Exception as e:
        print(f"[Błąd] {bog} (Community): {e}")
        
    # Przerwa na wzięcie oddechu przed uderzeniem w drugą stronę
    time.sleep(random.uniform(1.0, 3.0))
        
    # 2. Buildy Statystyczne
    try:
        dane_boga_stats = scraper_engine.get_smite2_live_builds(bog, fast_preview=False)
        if dane_boga_stats and dane_boga_stats.builds:
            s_data = dataclasses.asdict(dane_boga_stats)
    except Exception as e:
        print(f"[Błąd] {bog} (Stats): {e}")
        
    return bog, b_data, s_data

print(f"\nUruchamiam wielowątkowe pobieranie (4 wątki robocze)...")

# ThreadPoolExecutor z 4 pracownikami - to idealny "złoty środek" między prędkością a bezpieczeństwem
with ThreadPoolExecutor(max_workers=4) as executor:
    # Zlecamy zadania dla każdego boga
    przyszle_wyniki = {executor.submit(process_god, bog): bog for bog in baza_bogow}
    
    # Zbieramy wyniki w miarę jak pracownicy kończą zadania
    for future in as_completed(przyszle_wyniki):
        bog, b_data, s_data = future.result()
        
        if b_data:
            dane_builds_dict[bog.lower()] = b_data
        if s_data:
            dane_stats_dict[bog.lower()] = s_data
            
        print(f"[Zakończono] ✅ {bog}")

print("\nWszystkie wątki zakończyły pracę. Przygotowuję paczkę do wysyłki...")

nowe_dane = {
    "aktualizacja": str(datetime.datetime.now()),
    "wiadomosc": "Paczka z buildami wygenerowana WIELOWĄTKOWO!",
    "dane_builds": dane_builds_dict,
    "dane_stats": dane_stats_dict
}

try:
    import os

base_url = os.environ.get("ORACLE_IP")
if base_url:
    try:
        odpowiedz = requests.post(f"{base_url}/update", json=nowe_dane)
        print(f"Sukces: Oracle odpowiedział kodem: {odpowiedz.status_code}")
    except Exception as e:
        print(f"Błąd wysyłki: {e}")
else:
    print("Błąd: Nie znaleziono adresu IP w GitHub Secrets!")

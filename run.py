import requests
import re
import datetime
import dataclasses
import time
import random
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from scraper import SmiteSourceScraper

print("Inicjalizacja potężnego silnika (Wersja Produkcyjna - PEŁNA BAZA)...")
scraper_engine = SmiteSourceScraper()

print("Skanowanie SmiteSource w poszukiwaniu bogów...")
baza_bogow = []
try:
    r = requests.get('https://smitesource.com/gods', headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
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
    # Fallback awaryjny
    baza_bogow = ["Kuzenbo", "Ymir"]

dane_builds_dict = {}
dane_stats_dict = {}

def process_god(bog):
    time.sleep(random.uniform(1.0, 3.0)) # Lekkie opóźnienie na start wątku
    b_data, s_data = None, None
    print(f"\n[Start] -> {bog}")
    
    # 1. Buildy Społeczności
    try:
        dane_boga_com = scraper_engine.get_all_builds(bog)
        if dane_boga_com and dane_boga_com.builds:
            b_data = dataclasses.asdict(dane_boga_com)
    except Exception as e:
        print(f"[Błąd] {bog} (Community): {e}")
        
    time.sleep(random.uniform(1.5, 3.5)) # Oddech między zapytaniami dla danej postaci
        
    # 2. Buildy Statystyczne
    try:
        dane_boga_stats = scraper_engine.get_smite2_live_builds(bog, fast_preview=False)
        if dane_boga_stats and dane_boga_stats.builds:
            s_data = dataclasses.asdict(dane_boga_stats)
    except Exception as e:
        print(f"[Błąd] {bog} (Stats): {e}")
        
    return bog, b_data, s_data

print(f"\nUruchamiam wielowątkowe pobieranie (3 wątki robocze)...")

# Ustalone 3 wątki robocze (Optymalny kompromis między szybkością a bezpieczeństwem IP)
with ThreadPoolExecutor(max_workers=3) as executor:
    przyszle_wyniki = {executor.submit(process_god, bog): bog for bog in baza_bogow}
    
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
    "wiadomosc": "Paczka Produkcyjna (Wszystkie postacie) - Potężny system Statystyk!",
    "dane_builds": dane_builds_dict,
    "dane_stats": dane_stats_dict
}

base_url = os.environ.get("ORACLE_IP")

if base_url:
    try:
        clean_url = base_url.rstrip('/') 
        odpowiedz = requests.post(f"{clean_url}/update", json=nowe_dane)
        print(f"Sukces: Oracle odpowiedział kodem: {odpowiedz.status_code}")
    except Exception as e:
        print(f"Błąd wysyłki na serwer Oracle: {e}")
else:
    print("BŁĄD KRYTYCZNY: Zmienna ORACLE_IP nie została znaleziona w środowisku GitHuba!")

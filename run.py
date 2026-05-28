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
    baza_bogow = [
        "Achilles", "Agni", "Ah Puch", "Aladdin", "Amaterasu",
        "Anhur", "Anubis", "Aphrodite", "Apollo", "Ares",
        "Artemis", "Artio", "Athena", "Atlas", "Awilix",
        "Bacchus", "Baron Samedi", "Bellona", "Cabrakan", "Cerberus",
        "Cernunnos", "Chaac", "Charon", "Chiron", "Cupid",
        "Da Ji", "Danzaburou", "Discordia", "Eset", "Fenrir",
        "Ganesha", "Geb", "Gilgamesh", "Guan Yu", "Hades",
        "Hecate", "Hercules", "Hou Yi", "Hua Mulan", "Hun Batz",
        "Ishtar", "Izanami", "Janus", "Jing Wei", "Jormungandr",
        "Kali", "Khepri", "Kukulkan", "Loki", "Medusa",
        "Mercury", "Merlin", "Mordred", "Morgan Le Fay", "Ne Zha",
        "Neith", "Nemesis", "Nu Wa", "Nut", "Odin",
        "Osiris", "Pele", "Poseidon", "Princess Bari", "Ra",
        "Rama", "Ratatoskr", "Scylla", "Sobek", "Sol",
        "Sun Wukong", "Susano", "Sylvanus", "Thanatos", "The Morrigan",
        "Thor", "Tsukuyomi", "Ullr", "Vulcan", "Xbalanque",
        "Yemoja", "Ymir", "Zeus"
    ]

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

print(f"\nUruchamiam wielowątkowe pobieranie (TURA 1)...")

# Ustalone 3 wątki robocze
failed_gods = set()

with ThreadPoolExecutor(max_workers=3) as executor:
    przyszle_wyniki = {executor.submit(process_god, bog): bog for bog in baza_bogow}
    
    for future in as_completed(przyszle_wyniki):
        bog, b_data, s_data = future.result()
        
        if b_data:
            dane_builds_dict[bog.lower()] = b_data
        if s_data:
            dane_stats_dict[bog.lower()] = s_data
            
        # WERYFIKACJA BRAKÓW DO DRUGIEJ TURY
        if not b_data or not s_data:
            print(f"[Błąd/Brak Danych] ❌ {bog} - dodaję do listy naprawczej.")
            failed_gods.add(bog)
        else:
            print(f"[Zakończono] ✅ {bog}")

# ========================================================
# 🔄 TURA 2: SYSTEM NAPRAWCZY (RETRY QUEUE)
# ========================================================
if failed_gods:
    print(f"\n⚠️ Wykryto niepełne dane dla {len(failed_gods)} postaci.")
    print("⏳ Daję serwerom (SmiteSource/Smite2Live) 15 sekund na odblokowanie połączeń (timeout recovery)...")
    time.sleep(15)
    
    print("\n🚀 Uruchamiam system naprawczy (TURA 2)...")
    # Puszczamy powtórkę sekwencyjnie (pojedynczo), aby maksymalnie oszczędzić przeciążone serwery
    for bog in failed_gods:
        print(f"\n[Retry] Ostateczna próba dla: {bog}")
        bog, b_data, s_data = process_god(bog)
        
        # Aktualizacja paczki o uratowane dane
        if b_data and bog.lower() not in dane_builds_dict:
            dane_builds_dict[bog.lower()] = b_data
            print(f"[Retry] ✅ URATOWANO buildy (Community) dla: {bog}")
            
        if s_data and bog.lower() not in dane_stats_dict:
            dane_stats_dict[bog.lower()] = s_data
            print(f"[Retry] ✅ URATOWANO buildy (Stats) dla: {bog}")
            
        if not b_data or not s_data:
            print(f"[Retry] ❌ Ostateczny brak niektórych danych dla: {bog}. Pomijam w tym patchu.")


print("\n🎉 Wszystkie tury zakończyły pracę. Przygotowuję paczkę do wysyłki...")

nowe_dane = {
    "aktualizacja": str(datetime.datetime.now()),
    "wiadomosc": "Paczka Produkcyjna (Wszystkie postacie) - Potężny system Statystyk z Retry Queue!",
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

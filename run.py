import requests
import datetime
import dataclasses
import time
import random
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from scraper import SmiteSourceScraper

print("Inicjalizacja potężnego silnika (Wersja TESTOWA - 2 BOGÓW)...")
scraper_engine = SmiteSourceScraper()

# Sztywne ustawienie tylko 2 postaci dla błyskawicznego testu:
baza_bogow = ["Kuzenbo", "Ymir"]
print(f"Pobrano do przetworzenia: {baza_bogow}")

dane_builds_dict = {}
dane_stats_dict = {}

def process_god(bog):
    time.sleep(random.uniform(0.5, 1.5))
    b_data, s_data = None, None
    print(f"\n[Start] -> {bog}")
    
    # 1. Buildy Społeczności
    try:
        dane_boga_com = scraper_engine.get_all_builds(bog)
        if dane_boga_com and dane_boga_com.builds:
            b_data = dataclasses.asdict(dane_boga_com)
    except Exception as e:
        print(f"[Błąd] {bog} (Community): {e}")
        
    time.sleep(random.uniform(1.0, 2.0))
        
    # 2. Buildy Statystyczne
    try:
        # Wymuszamy dogłębną analizę (fast_preview=False), aby wygenerować aspekty i puste/czerwone buildy
        dane_boga_stats = scraper_engine.get_smite2_live_builds(bog, fast_preview=False)
        if dane_boga_stats and dane_boga_stats.builds:
            s_data = dataclasses.asdict(dane_boga_stats)
    except Exception as e:
        print(f"[Błąd] {bog} (Stats): {e}")
        
    return bog, b_data, s_data

print(f"\nUruchamiam pobieranie ({len(baza_bogow)} wątki robocze)...")

with ThreadPoolExecutor(max_workers=2) as executor:
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
    "wiadomosc": "Paczka TESTOWA (Tylko 2 Bogów) - Potężny system Statystyk!",
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

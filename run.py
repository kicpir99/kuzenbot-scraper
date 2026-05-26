import requests
import re
import datetime
import dataclasses
from scraper import SmiteSourceScraper

print("Inicjalizacja silnika SmiteSourceScraper...")
scraper_engine = SmiteSourceScraper()

# 1. DYNAMICZNE POBIERANIE LISTY BOGÓW
print("Skanowanie SmiteSource w poszukiwaniu dostępnych postaci...")
baza_bogow = []
try:
    # Wchodzimy na stronę z bogami
    res = requests.get("https://smitesource.com/gods", timeout=10)
    
    # Wyciągamy nazwy bogów ze strumienia danych Next.js za pomocą regexa
    znalezieni = re.findall(r'"name"\s*:\s*"([^"]+)"\s*,\s*"slug"\s*:\s*"([^"]+)"', res.text)
    
    seen = set()
    for name, slug in znalezieni:
        # Sprawdzamy czy nazwa pasuje do sluga, żeby odsiać śmieci (np. nazwy przedmiotów)
        if slug.replace("-", "") in name.lower().replace(" ", "").replace("'", ""):
            if name not in seen:
                seen.add(name)
                baza_bogow.append(name)
                
    print(f"Pomyślnie zlokalizowano {len(baza_bogow)} postaci: {baza_bogow}")
except Exception as e:
    print(f"Wystąpił błąd podczas pobierania listy bogów: {e}")
    # Awaryjna mini-lista, gdyby strona na chwilę padła
    baza_bogow = ["Kuzenbo", "Ymir", "Loki"] 

# 2. SKRAPOWANIE DANYCH DLA KAŻDEGO BOGA
# Używamy słownika zamiast listy, co znacznie ułatwi nam szukanie po stronie serwera!
dane_bogow_dict = {}

# Opcjonalnie limitujemy na razie listę do pierwszych 10 bogów, żeby test na GitHubie trwał krótko. 
# Jak wszystko zadziała, usuniesz to [:10].
for bog in baza_bogow[:10]:
    print(f"Pobieram dane dla: {bog}")
    dane_boga = scraper_engine.get_all_builds(bog)
    
    if dane_boga and dane_boga.builds:
        # Zapisujemy pod kluczem, np. "kuzenbo": {dane...}
        dane_bogow_dict[bog.lower()] = dataclasses.asdict(dane_boga)

# 3. WYSYŁKA DO ORACLE
nowe_dane = {
    "aktualizacja": str(datetime.datetime.now()),
    "wiadomosc": "Dynamiczna paczka z bogami dostarczona!",
    # Używamy słownika - FastAPI musi wiedzieć, że to słownik, a nie prosta lista
    "dane": dane_bogow_dict 
}

print("Paczka przygotowana. Wysyłam do Oracle...")
url_serwera = "http://92.5.91.226:8000/update"

try:
    odpowiedz = requests.post(url_serwera, json=nowe_dane)
    print(f"Sukces! Oracle odpowiedział kodem: {odpowiedz.status_code}")
except Exception as e:
    print(f"Wystąpił błąd podczas łączenia z Oracle: {e}")

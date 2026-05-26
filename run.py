import requests
import datetime
import dataclasses
from scraper import SmiteSourceScraper

print("Inicjalizacja potężnego silnika SmiteSourceScraper...")
# Odpalamy Twoją klasę z pliku scraper.py
scraper_engine = SmiteSourceScraper()

# Dla testu pobieramy statystyki i buildy tylko dla kilku bogów, 
# żeby sprawdzić czy wszystko działa (potem możesz rozszerzyć tę listę)
baza_bogow = ["Kuzenbo", "Ymir", "Loki"]
zebrane_dane = []

for bog in baza_bogow:
    print(f"Pobieram dane społeczności dla: {bog}")
    # Używamy Twojej gotowej funkcji z pliku scraper.py
    dane_boga = scraper_engine.get_all_builds(bog)
    
    if dane_boga and dane_boga.builds:
        # Konwertujemy strukturę dataclass na zwykły słownik (JSON) do wysyłki
        zebrane_dane.append(dataclasses.asdict(dane_boga))

nowe_dane = {
    "aktualizacja": str(datetime.datetime.now()),
    "wiadomosc": "Paczka wygenerowana przez ORYGINALNEGO scrapera ze starych plików!",
    "dane": zebrane_dane
}

print("Paczka przygotowana. Wysylam do Oracle...")
url_serwera = "http://92.5.91.226:8000/update"

try:
    odpowiedz = requests.post(url_serwera, json=nowe_dane)
    print(f"Sukces! Oracle odpowiedzial kodem: {odpowiedz.status_code}")
except Exception as e:
    print(f"Wystapil blad podczas laczenia: {e}")

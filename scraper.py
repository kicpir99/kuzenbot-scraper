import requests
import json
import datetime

print("Uruchamiam scrapera w GitHub Actions...")

# 1. Tutaj w przyszłości dodamy kod wyciągający prawdziwe statystyki Smite 2
dane_do_wyslania = {
    "aktualizacja": str(datetime.datetime.now()),
    "wiadomosc": "Scraper zebral dane!",
    "dane_testowe": ["Kuzenbo to najlepszy bog", "Ymir", "Loki"]
}

print("Dane zebrane. Przygotowuje do wyslania...")

# 2. To jest adres IP Twojego serwera Oracle, z ktorym sie laczymy!
url_serwera = "http://92.5.91.226:8000"

try:
    # Na razie uderzamy w glowny adres, zeby sprawdzic czy serwer odpowiada
    odpowiedz = requests.get(url_serwera)
    print(f"Sukces! Serwer Oracle odpowiedzial kodem: {odpowiedz.status_code}")
    print(f"Tresc z serwera Oracle: {odpowiedz.text}")
except Exception as e:
    print(f"Wystapil blad podczas laczenia z Oracle: {e}")

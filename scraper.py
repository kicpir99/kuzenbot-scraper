import requests
import datetime

print("Uruchamiam scrapera w GitHub Actions...")

# 1. Tworzymy paczkę danych, która idealnie pasuje do naszego modelu SmiteData w FastAPI
nowe_dane = {
    "aktualizacja": str(datetime.datetime.now()),
    "wiadomosc": "Paczka dostarczona pomyslnie POSTem z GitHuba!",
    "dane": ["Kuzenbo", "Ymir", "Loki", "Nowe Statystyki Smite 2"]
}

print("Paczka przygotowana. Wysylam do Oracle...")

# 2. Uderzamy w nasz nowy endpoint /update
url_serwera = "http://92.5.91.226:8000/update"

try:
    # Używamy metody POST (wysyłanie) zamiast GET (pobieranie) i doklejamy naszą paczkę JSON
    odpowiedz = requests.post(url_serwera, json=nowe_dane)
    print(f"Sukces! Serwer odpowiedzial kodem: {odpowiedz.status_code}")
    print(f"Tresc odpowiedzi z Oracle: {odpowiedz.text}")
except Exception as e:
    print(f"Wystapil blad podczas laczenia: {e}")

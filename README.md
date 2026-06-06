# 🐢 KuzenBot Scraper

[🇺🇸 English Version](#-english-version) | [🇵🇱 Wersja Polska](#-wersja-polska)

---

## 🇺🇸 English Version

An external, highly optimized data scraping engine for the **KuzenBot** project. This tool automatically extracts, parses, and structures god build and stat data from Smite 2 (e.g., SmiteSource). Once the data is gathered and processed, the scraper sends a clean, optimized JSON payload to the main API server (Oracle).

### ✨ Key Features

* **⚡ High Performance (Multithreading):** Utilizes `ThreadPoolExecutor` to fetch data for multiple gods concurrently, drastically reducing the overall scan time.
* **🛡️ Advanced Retry System:** Features a built-in retry queue for requests that fail (e.g., due to server timeouts), ensuring no god data is left behind during a database update.
* **🧠 Smart Sorting & Deduplication:** Analyzes downloaded builds, sorts them by patch number (prioritizing the current version) and upvotes, and strictly filters out builds flagged with `insufficient_data`.
* **🌐 Robust Session Handling:** Modifies User-Agent headers, implements `urllib3` Retry Strategies, and bypasses default system proxies (`trust_env = False`) to prevent connection and socket errors.

### 📂 Repository Structure

* `run.py` - Main entry point. Fetches the available god roster, manages the thread pool, handles the failed gods rescue queue, and dispatches the final payload to the `ORACLE_IP`.
* `scraper.py` - The core engine (`SmiteSourceScraper` class). Handles HTTP connections and parses HTML using BeautifulSoup to extract specific parameters (items, abilities, relics).
* `models.py` - Data structures (`SmiteBuild` and `GodData` dataclasses). Responsible for business logic verification, data formatting, and identifying outdated/invalid builds.
* `requirements.txt` - List of required Python dependencies.

### 🚀 Requirements

The tool requires **Python 3.8+** and external libraries to run.

```bash
# Install dependencies
pip install -r requirements.txt
```

**Main Dependencies:**
* `requests`
* `beautifulsoup4`
* `lxml` (Fast HTML parser for bs4)

### ⚙️ Configuration & Execution

Before running the scraper, you must define the target server address using an environment variable.

**Environment Variables:**
* `ORACLE_IP` - The endpoint URL of your main API or database server where the final payload will be sent (e.g., `http://192.168.1.100/api/update`).

**Run on Linux / Mac:**
```bash
export ORACLE_IP="http://your_api_address/endpoint"
python run.py
```

**Run on Windows (PowerShell):**
```powershell
$env:ORACLE_IP="http://your_api_address/endpoint"
python run.py
```

### 📊 Data Flow

1. `run.py` queries the SmiteSource god roster to generate a list of slugs.
2. A `ThreadPoolExecutor` is launched, assigning a `SmiteSourceScraper` instance to each god.
3. The downloaded HTML is converted into `SmiteBuild` objects (parsing starter items, final items, relics, and ability priorities).
4. Objects are deduplicated and validated using the `is_valid()` method (empty or garbage builds are discarded).
5. Gods that encountered errors (e.g., 503 Service Unavailable) are pushed to the `failed_gods` list for a final retry sequence.
6. The compiled dictionary (`dane_builds` and `dane_stats`) is converted to JSON and POSTed to the `ORACLE_IP`.

---

## 🇵🇱 Wersja Polska

Zewnętrzny, zoptymalizowany silnik pobierający dane (Scraper) dla projektu **KuzenBot**. Narzędzie służy do automatycznego wyciągania, parsowania i strukturyzacji danych o buildach i statystykach postaci z gry Smite 2 (m.in. z serwisu SmiteSource). Po zebraniu i przetworzeniu danych, scraper wysyła gotowy, zoptymalizowany ładunek (payload) do głównego serwera API (Oracle).

### ✨ Główne funkcje

* **⚡ Wysoka wydajność (Wielowątkowość):** Wykorzystuje `ThreadPoolExecutor` do równoległego pobierania danych o wielu bogach jednocześnie, drastycznie skracając czas pełnego skanowania.
* **🛡️ Zaawansowany system Retry:** Wbudowana automatyczna kolejka ponawiania (`Retry Queue`) dla zapytań, które zakończyły się błędem (np. timeout serwera). Optymalizuje obciążenie i dba o to, by żadne dane nie zostały pominięte w trakcie aktualizacji.
* **🧠 Inteligentne sortowanie i deduplikacja:** System analizuje pobrane buildy i sortuje je po numerze patcha (priorytetyzując obecną wersję), ilości "upvote'ów" oraz eliminuje buildy oparte na niewystarczających danych (`insufficient_data`).
* **🌐 Solidna obsługa sesji:** Moduł modyfikuje nagłówki (User-Agent) oraz implementuje `Retry Strategy` z biblioteki `urllib3`, omijając jednocześnie domyślne systemowe ustawienia proxy (`trust_env = False`), co zapobiega błędom gniazd (Socket Errors).

### 📂 Struktura repozytorium

* `run.py` - Główny punkt wejścia. Pobiera listę dostępnych postaci (slugów), zarządza pulą wątków, obsługuje kolejkę "uratowanych" postaci i wysyła zebrane dane pod adres `ORACLE_IP`.
* `scraper.py` - Silnik skanujący (klasa `SmiteSourceScraper`). Obsługuje zapytania HTTP i parsuje kod HTML przy pomocy BeautifulSoup, ekstrahując konkretne parametry (itemy, skille, relikwie).
* `models.py` - Struktury danych (`dataclasses`): `SmiteBuild` oraz `GodData`. Odpowiadają za weryfikację logiki biznesowej, formatowanie danych i sprawdzanie "outdated/insufficient" buildów.
* `requirements.txt` - Lista wymaganych zależności.

### 🚀 Wymagania

Narzędzie do działania wymaga środowiska uruchomieniowego **Python 3.8+** oraz zewnętrznych bibliotek.

```bash
# Instalacja zależności
pip install -r requirements.txt
```

**Używane biblioteki:**
* `requests`
* `beautifulsoup4`
* `lxml` (wydajny parser dla bs4)

### ⚙️ Konfiguracja i uruchomienie

Zanim uruchomisz aplikację, musisz upewnić się, że adres docelowego serwera przyjmującego dane jest ustawiony jako zmienna środowiskowa.

**Zmienne środowiskowe:**
* `ORACLE_IP` - Adres docelowego API lub serwera bazodanowego, do którego scraper wyśle finalny ładunek z danymi (np. `http://192.168.1.100/api/update`).

**Uruchomienie (Linux / Mac):**
```bash
export ORACLE_IP="http://twoj_adres_api/endpoint"
python run.py
```

**Uruchomienie (Windows - PowerShell):**
```powershell
$env:ORACLE_IP="http://twoj_adres_api/endpoint"
python run.py
```

### 📊 Przepływ danych (Data Flow)

1. `run.py` uderza w endpoint ze zbiorem postaci i generuje listę slugów do przeskanowania.
2. Odpalana jest pula wątków (`ThreadPoolExecutor`), z których każdy wywołuje instancję `SmiteSourceScraper` dla przypisanej postaci.
3. Ściągnięty HTML jest konwertowany na obiekty `SmiteBuild` (parsowane są itemy startowe, przedmioty końcowe, relikty, priorytety umiejętności).
4. Obiekty są deduplikowane i walidowane metodą `is_valid()` (odrzucane są śmieciowe buildy bez przedmiotów).
5. Postacie, z którymi wystąpił błąd (np. 503 Service Unavailable), trafiają do listy `failed_gods` i podlegają procesowi ostatecznego odzyskiwania (`[Retry] Ostateczna próba`).
6. Finalny słownik zawierający `dane_builds` oraz `dane_stats` jest kompresowany do JSON-a i wypychany (POST) na `ORACLE_IP`.

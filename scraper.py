import requests
import json
import re
import os
import random
from bs4 import BeautifulSoup
from models import SmiteBuild, GodData

class SmiteSourceScraper:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        # Omijanie systemowych proxy z rejestru systemu/zmiennych środowiskowych, 
        # co na niektórych systemach Windows zapobiega błędowi socketu PermissionError (Errno 13).
        self.session.trust_env = False
        
        
        # Optymalizacja połączeń HTTP (zwiększenie rozmiaru puli dla 25 wątków)
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        # Definiujemy strategię ponawiania (silnik sam powtórzy zapytanie bez przerywania skryptu!)
        retry_strategy = Retry(
            total=4,             # Maksymalnie 4 próby pobrania
            backoff_factor=1.5,  # Odstępy: 1.5s, 3s, 4.5s między próbami
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        
        adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        
        # Pamięć podręczna (RAM Cache) dla statystyk meczowych smite2.live (TTL = 1 godzina)
        self.stats_cache = {}
        # Pamięć podręczna (RAM Cache) dla buildów SmiteSource (TTL = 1 godzina)
        self.smite_source_cache = {}
        import threading
        self.cache_lock = threading.Lock()
        
        # Reuse thread pool to avoid constant creation/destruction overhead
        from concurrent.futures import ThreadPoolExecutor
        self.executor = ThreadPoolExecutor(max_workers=3)
        
        self.base_url = "https://smitesource.com"
        # Próbujemy alternatywny punkt dostępu do Wiki
        self.wiki_api_url = "https://wiki.smite2.com/api.php"
        self.assets_dir = "assets"
        self.items_json = os.path.join(self.assets_dir, "items.json")
        self.items_img_dir = os.path.join(self.assets_dir, "items")
        self.item_db = self._load_item_db()
        self._cached_game_patch = None
        
        # Oficjalne podstawowe (koszt 0) relikty w Smite 2, zajmujące wyłącznie dedykowany slot na relikty.
        self.basic_relic_names = {
            "purification beads", "beads",
            "aegis of acceleration", "aegis",
            "blink rune", "blink",
            "agility relic",
            "phantom shell", "shell",
            "sundering arc", "sunder",
        }


    def _get_with_retry(self, url: str, timeout: int = 25, max_retries: int = 3, use_session: bool = True, label: str = "Request"):
        import time
        for attempt in range(1, max_retries + 1):
            try:
                if use_session:
                    res = self.session.get(url, timeout=timeout)
                else:
                    res = requests.get(url, timeout=timeout)
                if res.status_code == 200:
                    return res
                # Odczekaj LOSOWY czas przed ponowieniem
                time.sleep(random.uniform(2.0, 4.0))
            except requests.exceptions.RequestException as e:
                if attempt == max_retries:
                    print(f"[{label}] Błąd pobierania {url} po {max_retries} próbach: {e}")
                    raise e
                time.sleep(random.uniform(2.0, 4.0))
        return None

    def _load_item_db(self):
        if os.path.exists(self.items_json):
            try:
                with open(self.items_json, "r", encoding="utf-8") as f:
                    db = json.load(f)
                    normalized_db = {}
                    for k, v in db.items():
                        if isinstance(v, dict):
                            norm_k = k.lower().strip().replace("’", "'")
                            if "upgrades" in v:
                                v["upgrades"] = [u.lower().strip().replace("’", "'") for u in v["upgrades"]]
                            if "upgraded_from" in v and v["upgraded_from"]:
                                v["upgraded_from"] = v["upgraded_from"].lower().strip().replace("’", "'")
                            normalized_db[norm_k] = v
                    return normalized_db
            except:
                return {}
        return {}

    def _save_item_db(self):
        os.makedirs(self.assets_dir, exist_ok=True)
        with open(self.items_json, "w", encoding="utf-8") as f:
            json.dump(self.item_db, f, indent=4, ensure_ascii=False)
    def fetch_master_items(self):
        """Pobiera bazę przedmiotów z Wiki i kategoryzuje je."""
        url = "https://wiki.smite2.com/w/Items"
        wiki_session = requests.Session()
        wiki_session.trust_env = False
        try:
            print(f"[ItemManager] Pobieranie bazy przedmiotów z Wiki: {url}")
            response = wiki_session.get(url, timeout=10)
            if response.status_code != 200:
                return {}

            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Budujemy mapę href -> img_url dla precyzyjnego dopasowania ikon
            href_to_img = {}
            for a_tag in soup.find_all('a'):
                img = a_tag.find('img')
                href = a_tag.get('href')
                if img and href:
                    src = img.get('src')
                    if src:
                        href_to_img[href] = src
            
            # Mapowanie nagłówków do kategorii
            mapping = {
                "Relics": "relic",
                "Curios": "consumable",
                "Consumables": "consumable",
                "Starters": "starter_t1",
                "Upgraded Starters": "starter_t2",
                "Tier I": "item",
                "Tier II": "item",
                "Tier III - Offensive": "item",
                "Tier III - Defensive": "item",
                "Tier III - Hybrid": "item",
                "God Specific": "item"
            }

            self.item_db = {}
            # Wiki może mieć różne struktury, szukamy wszystkich nagłówków i kategoryzujemy linki pod nimi
            current_category = None
            
            for tag in soup.find_all(['h2', 'h3', 'h4', 'a']):
                if tag.name in ['h2', 'h3', 'h4']:
                    text = tag.get_text().strip().replace('[edit]', '').strip()
                    if text in mapping:
                        current_category = mapping[text]
                    elif tag.name == 'h2' and text != "List of items":
                        current_category = None
                
                elif current_category and tag.name == 'a':
                    name = tag.get_text(strip=True)
                    # Filtrowanie linków
                    if name and not name.startswith('[') and len(name) > 1:
                        if all(x not in name for x in ['Category:', 'File:', 'edit']):
                            if name not in mapping:
                                # Szukamy obrazka na podstawie href
                                href = tag.get('href')
                                img_url = href_to_img.get(href)
                                
                                if img_url and img_url.startswith('/'):
                                    img_url = "https://wiki.smite2.com" + img_url

                                name_key = name.lower().strip().replace("’", "'")
                                if current_category in ["starter_t1", "starter_t2"]:
                                    self.item_db[name_key] = {
                                        "category": "starter",
                                        "is_starter_t1": (current_category == "starter_t1"),
                                        "is_starter_t2": (current_category == "starter_t2"),
                                        "image_url": img_url
                                    }
                                else:
                                    self.item_db[name_key] = {
                                        "category": current_category,
                                        "image_url": img_url
                                    }
            
            # Pobieranie relacji ulepszeń dla starterów z MediaWiki API
            base_starters = [n for n, info in self.item_db.items() if info.get("is_starter_t1")]
            if base_starters:
                print(f"[ItemManager] Pobieranie relacji ulepszeń dla {len(base_starters)} starterów...")
                try:
                    wiki_titles = []
                    name_to_key = {}
                    for bs in base_starters:
                        words = bs.split()
                        capitalized_words = []
                        for word in words:
                            if "'" in word:
                                parts = word.split("'")
                                # Część po apostrofie (np. 's') powinna być małą literą, a przed apostrofem z dużej
                                capitalized_words.append(parts[0].capitalize() + "'" + parts[1].lower())
                            else:
                                capitalized_words.append(word.capitalize())
                        title = " ".join(capitalized_words)
                        title_key = title.lower().strip().replace("’", "'")
                        bs_key = bs.lower().strip().replace("’", "'")
                        wiki_titles.append(title)
                        name_to_key[title_key] = bs_key
                    
                    api_url = "https://wiki.smite2.com/api.php"
                    params = {
                        "action": "query",
                        "prop": "revisions",
                        "titles": "|".join(wiki_titles),
                        "rvslots": "*",
                        "rvprop": "content",
                        "format": "json"
                    }
                    api_res = wiki_session.get(api_url, params=params, timeout=10)
                    if api_res.status_code == 200:
                        pages = api_res.json().get("query", {}).get("pages", {})
                        for page_id, page_data in pages.items():
                            title = page_data.get("title", "")
                            revisions = page_data.get("revisions", [])
                            if not revisions or not title:
                                continue
                            wikitext = revisions[0].get("slots", {}).get("main", {}).get("*", "")
                            
                            builds_into = []
                            builds_into_match = re.search(r'==\s*Builds\s+Into\s*==\s*(.*?)(?===\s*\w|\Z)', wikitext, re.DOTALL | re.IGNORECASE)
                            if builds_into_match:
                                section_text = builds_into_match.group(1)
                                links = re.findall(r'\[\[([^|\]]+)(?:\|[^\]]*)?\]\]', section_text)
                                for link in links:
                                    link_clean = link.strip()
                                    if ":" not in link_clean and not link_clean.startswith("[") and len(link_clean) > 1:
                                        builds_into.append(link_clean)
                            
                            if builds_into:
                                bs_key = name_to_key.get(title.lower().strip().replace("’", "'"))
                                if bs_key and bs_key in self.item_db:
                                    self.item_db[bs_key]["upgrades"] = [bi.lower().strip().replace("’", "'") for bi in builds_into]
                                    for bi in builds_into:
                                        bi_key = bi.lower().strip().replace("’", "'")
                                        if bi_key in self.item_db:
                                            self.item_db[bi_key]["upgraded_from"] = bs_key
                except Exception as ex:
                    print(f"[ItemManager] Błąd pobierania relacji ulepszeń starterów z API Wiki: {ex}")

            self._save_item_db()
            print(f"[ItemManager] Zindeksowano {len(self.item_db)} przedmiotów z Wiki i zapisano do pliku.")
            self.download_item_images()
            return self.item_db
            
        except Exception as e:
            print(f"[ItemManager] Wiki jest niedostępna ({e}).")
            return {}

    def _check_and_download_smitesource_item_image(self, item_name, img_path):
        """Pobiera ikonę przedmiotu ze SmiteSource CDN, jeśli nie mamy jej lokalnie (przydatne dla usuniętych przedmiotów)."""
        if not item_name or not img_path:
            return
        
        # Nazwa pliku w assets/items
        safe_name = re.sub(r'[^a-z0-9]', '_', item_name.lower()) + ".png"
        filepath = os.path.join(self.items_img_dir, safe_name)
        
        if not os.path.exists(filepath):
            clean_path = img_path.replace('\\/', '/').lstrip('/')
            # Jeśli ścieżka nie zaczyna się od Items/, a od cdn-cgi/ lub cdn.smitesource.com, odrzucamy lub dopasowujemy
            if not clean_path.startswith("http"):
                url = f"https://cdn.smitesource.com/{clean_path}"
            else:
                url = clean_path
                
            try:
                print(f"[ItemManager] Pobieranie brakującej ikony przedmiotu ze SmiteSource CDN ({item_name}): {url}")
                r = self.session.get(url, timeout=5)
                if r.status_code == 200:
                    os.makedirs(self.items_img_dir, exist_ok=True)
                    with open(filepath, "wb") as f:
                        f.write(r.content)
                    print(f"[ItemManager] Pobrano ikone dla: {item_name}")
                else:
                    print(f"[ItemManager] SmiteSource CDN status {r.status_code} dla {item_name}")
            except Exception as e:
                print(f"[ItemManager] Blad pobierania ikony przedmiotu ze SmiteSource CDN ({item_name}): {e}")

    def download_item_images(self):
        """Pobiera obrazki dla wszystkich przedmiotów w bazie."""
        os.makedirs(self.items_img_dir, exist_ok=True)
        print(f"[ItemManager] Sprawdzanie obrazków w {self.items_img_dir}...")
        
        count = 0
        for name, info in self.item_db.items():
            if not isinstance(info, dict) or not info.get("image_url"):
                continue
                
            # Nazwa pliku: zamiana spacji i znaków specjalnych
            safe_name = re.sub(r'[^a-z0-9]', '_', name.lower()) + ".png"
            filepath = os.path.join(self.items_img_dir, safe_name)
            
            if not os.path.exists(filepath):
                try:
                    img_url = info["image_url"]
                    # Niektóre URL na Wiki mają parametry po ?
                    img_url = img_url.split('?')[0]
                    
                    response = self.session.get(img_url, timeout=10)
                    if response.status_code == 200:
                        with open(filepath, "wb") as f:
                            f.write(response.content)
                        count += 1
                        if count % 10 == 0:
                            print(f"[ItemManager] Pobrano {count} obrazków...")
                except Exception as e:
                    print(f"[ItemManager] Błąd pobierania {name}: {e}")
        
        if count > 0:
            print(f"[ItemManager] Zakończono pobieranie. Pobrano {count} nowych obrazków.")
        else:
            print("[ItemManager] Wszystkie obrazki są już aktualne.")

    def _extract_balanced_json(self, text, start_ptr):
        brace_count = 0
        start_index = -1
        for i in range(start_ptr, len(text)):
            if text[i] == '[':
                if start_index == -1: start_index = i
                brace_count += 1
            elif text[i] == ']':
                brace_count -= 1
                if brace_count == 0 and start_index != -1:
                    return text[start_index:i+1]
        return None

    def _get_item_info(self, it):
        """Wyciąga dane z obiektu przedmiotu w JSON SmiteSource."""
        if not isinstance(it, dict): return None
        # Dane bywają w 'item' lub bezpośrednio
        d = it.get("item") if isinstance(it.get("item"), dict) else it
        return {
            "name": d.get("name") or d.get("itemName"),
            "type": str(d.get("type", "")).lower(),
            "tier": d.get("tier", 0)
        }

    def get_current_game_patch(self) -> str:
        """Pobiera aktualną wersję patcha bezpośrednio z smite2.live."""
        if hasattr(self, '_cached_game_patch') and self._cached_game_patch:
            return self._cached_game_patch
            
        try:
            url = "https://smite2.live/god/ymir/builds?skill=master_plus"
            r = self.session.get(url, timeout=5)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                version_select = soup.find_all("select", class_="gb-select")
                version_dropdown = None
                for s in version_select:
                    opt = s.find("option")
                    if opt and "v=" in opt.get("value", ""):
                        version_dropdown = s
                        break
                if version_dropdown:
                    for opt in version_dropdown.find_all("option"):
                        match = re.search(r'v=([^&]+)', opt.get("value", ""))
                        if match:
                            v = match.group(1).upper()
                            self._cached_game_patch = v
                            return v
        except Exception as e:
            print(f"[Scraper] Błąd podczas dynamicznego pobierania aktualnego patcha: {e}")
            
        return "OB35.0"

    def get_all_builds(self, god_name: str) -> GodData:
        slug = god_name.lower().strip().replace(" ", "-").replace("'", "")
        
        # Sprawdzenie pamięci podręcznej SmiteSource (TTL = 1 godzina)
        import time
        with self.cache_lock:
            if slug in self.smite_source_cache:
                cached_data, timestamp = self.smite_source_cache[slug]
                if time.time() - timestamp < 3600:
                    print(f"[Scraper Cache] Zwracam dane z pamięci podręcznej SmiteSource dla: {god_name} (Wiek: {int(time.time() - timestamp)}s)")
                    return cached_data
                    
        if not self.item_db:
            self.fetch_master_items()

        all_builds = []
        import time
        # Ze względu na blokady Next.js App Router, serwer stateless zawsze zwraca stronę 1.
        # Pobieramy więc 1 stronę (10 najnowszych buildów), co i tak daje nam 2 strony w UI.
        page = 1
        url = f"{self.base_url}/builds?god={slug}&page={page}&t={int(time.time()*1000)}"
        try:
            print(f"[Scraper] Pobieranie buildów (strona {page}): {url}")
            response = self._get_with_retry(url, timeout=10, max_retries=3, use_session=True, label="Scraper SmiteSource")
            if response and response.status_code == 200:
                fragments = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', response.text)
                if fragments:
                    full_stream = "".join(fragments).replace('\\"', '"').replace('\\\\', '\\')
                    
                    # Pobieramy dynamicznie ikony ze SmiteSource CDN dla wszystkich przedmiotów w buildzie (w tym usuniętych)
                    try:
                        for m in re.finditer(r'"name"\s*:\s*"([^"]+)"\s*,\s*"imagePath"\s*:\s*"([^"]+)"', full_stream):
                            item_name = m.group(1)
                            img_path = m.group(2)
                            self._check_and_download_smitesource_item_image(item_name, img_path)
                    except Exception as e:
                        print(f"[Scraper] Blad podczas dynamicznego skanowania ikon w get_all_builds: {e}")

                    # Wycinanie JSONA buildów
                    raw_builds = None
                    for key in ['"builds":', '"godBuilds":']:
                        pos = full_stream.rfind(key)
                        if pos != -1:
                            json_str = self._extract_balanced_json(full_stream, full_stream.find("[", pos))
                            if json_str:
                                raw_builds = json.loads(json_str)
                                break
                    
                    if raw_builds:
                        for rb in raw_builds:
                            relics, starters, core, consumables = [], [], [], []
                            for it_obj in rb.get("items", []):
                                info = self._get_item_info(it_obj)
                                if not info or not info["name"]: continue
                                name = info["name"]
                                if it_obj.get("isStartingBuild"):
                                    starters.append(name)
                                else:
                                    core.append(name)

                            patch_obj = rb.get("patch", {})
                            current_patch_str = self.get_current_game_patch()
                            patch_name = patch_obj.get("patchShortName", current_patch_str) if isinstance(patch_obj, dict) else str(patch_obj)

                            has_aspect = False
                            gods_data = rb.get("gods", [])
                            if gods_data and isinstance(gods_data, list):
                                talent = gods_data[0].get("talent")
                                if talent and isinstance(talent, dict) and talent.get("name"):
                                    has_aspect = True
                            
                            if not has_aspect:
                                has_aspect = "ASPECT" in str(rb.get("title", "")).upper()

                            raw_roles = rb.get("roles", [])
                            roles = [str(r) for r in raw_roles] if raw_roles else []

                            user_data = rb.get("user", {})
                            
                            author_name = "Unknown"
                            profiles = user_data.get("profiles", [])
                            if profiles and isinstance(profiles, list) and len(profiles) > 0:
                                profile = profiles[0]
                                author_name = (
                                    profile.get("customDisplayName") or
                                    profile.get("twitchDisplayName") or
                                    profile.get("displayName") or
                                    "Unknown"
                                )
                            
                            if not author_name or author_name == "Unknown":
                                author_name = (
                                    user_data.get("name") or 
                                    user_data.get("displayName") or 
                                    user_data.get("username") or
                                    rb.get("authorName") or
                                    rb.get("creatorName") or
                                    "Unknown"
                                )

                            all_builds.append(SmiteBuild(
                                title=str(rb.get("title", "Build")),
                                patch=patch_name,
                                is_aspect=has_aspect,
                                roles=roles,
                                starter_items=starters,
                                final_items=core,
                                relics=relics,
                                consumables=consumables,
                                swap_items=[],
                                build_url=f"{self.base_url}/build/{rb.get('slug', '')}",
                                upvotes=int(rb.get("upvoteCount", 0)),
                                author=str(author_name),
                                is_partner=(user_data.get("role") == "partner")



                            ))
        except Exception as e:
            print(f"[Scraper] Błąd pobierania bazy danych buildów: {e}")
        if not all_builds: return None
        
        # Deduplikacja
        seen_urls = set()
        unique_builds = []
        for b in all_builds:
            if b.build_url not in seen_urls:
                seen_urls.add(b.build_url)
                unique_builds.append(b)

        print(f"[Scraper] Sparsowano łącznie {len(unique_builds)} unikalnych buildów.")
        current_game_patch = self.get_current_game_patch()
        res_data = GodData(god_name=god_name.capitalize(), current_patch=current_game_patch, builds=unique_builds)
        
        with self.cache_lock:
            self.smite_source_cache[slug] = (res_data, time.time())
            
        return res_data

    def fetch_build_details(self, build_obj: SmiteBuild):
        """Pobiera detale (np. Swapy) ze strony buildu."""
        if not build_obj.build_url: return build_obj
        try:
            import requests, re
            r = self.session.get(build_obj.build_url, timeout=5)
            if r.status_code != 200: return build_obj
            
            # REKONSTRUKCJA STRUMIENIA NEXT.JS
            # Dane są przesyłane w kawałkach: self.__next_f.push([1,"..."])
            # Musimy je wszystkie wyłuskać i skleić, inaczej duże obiekty JSON (jak skille) są ucięte.
            chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', r.text)
            if chunks:
                stream = "".join(chunks).replace('\\"', '"').replace('\\\\', '\\')
            else:
                # Fallback jeśli strona nie używa streamingu lub ma inny format
                stream = r.text.replace('\\"', '"').replace('\\\\', '\\')
            
            # Pobieramy dynamicznie ikony ze SmiteSource CDN dla wszystkich przedmiotów w buildzie (w tym usuniętych)
            try:
                for m in re.finditer(r'"name"\s*:\s*"([^"]+)"\s*,\s*"imagePath"\s*:\s*"([^"]+)"', stream):
                    item_name = m.group(1)
                    img_path = m.group(2)
                    self._check_and_download_smitesource_item_image(item_name, img_path)
            except Exception as e:
                print(f"[Scraper] Blad podczas dynamicznego skanowania ikon w strumieniu: {e}")

            swaps = []
            
            def slugify(text):
                return text.lower().replace("'", "").replace(" ", "-")

            swaps_match = re.search(r'Swaps \(', stream, re.IGNORECASE)
            if swaps_match:
                sub = stream[swaps_match.start():]
                
                # Zbieramy ID divów swapów
                slug_pattern = r'"div","([a-z0-9-]+)-\d+"'
                slug_matches = re.findall(slug_pattern, sub)
                
                seen = set()
                unique_slugs = []
                for match in slug_matches:
                    # Odrzucamy krótkie przypadkowe matche
                    if match not in seen and len(match.split("-")) >= 2:
                        seen.add(match)
                        unique_slugs.append(match)
                
                # Szukamy powodów i docelowych przedmiotów
                reason_blocks = sub.split('className":"flex-1 text-slate-400 text-xs leading-relaxed","children":"')
                reasons_data = []
                for i, block in enumerate(reason_blocks[1:]):
                    reason = block.split('"')[0]
                    prev_block = reason_blocks[i]
                    alts = re.findall(r'"alt":"([^"]+)"', prev_block)
                    if alts:
                        reasons_data.append({"to_item": alts[-1], "reason": reason.replace("\\n", "\n").strip()})
                
                all_build_items = build_obj.starter_items + build_obj.final_items
                
                for r_data in reasons_data:
                    to_item = r_data["to_item"]
                    to_slug = slugify(to_item)
                    reason = r_data["reason"]
                    
                    matched_slug = None
                    for slug in unique_slugs:
                        if to_slug in slug:
                            matched_slug = slug
                            break
                            
                    if matched_slug:
                        from_slug = matched_slug.replace(f"-{to_slug}", "").replace(f"{to_slug}-", "")
                        from_item = "Unknown"
                        
                        for item in all_build_items:
                            if slugify(item) == from_slug:
                                from_item = item
                                break
                                
                        if from_item == "Unknown":
                            from_item = from_slug.replace('-', ' ').title()
                            
                        swaps.append({
                            "from": from_item,
                            "to": to_item,
                            "reason": reason
                        })
            if swaps:
                # Dodajemy tylko te, których jeszcze nie ma (unikamy duplikatów)
                existing_tos = [s['to'].lower() for s in build_obj.swap_items]
                for s in swaps:
                    if s['to'].lower() not in existing_tos:
                        build_obj.swap_items.append(s)

            # --- Ability Leveling Path (1-20) ---
            leveling_path = [None] * 20
            ability_details = {} # slot -> {"name", "img"}
            
            # Mapowanie rzędów na faktyczne sloty i zbieranie detali
            row_to_slot = {}
            
            # Nowa, bardziej odporna metoda zliczania nawiasów (radzi sobie z zagnieżdżonymi JSON)
            for m in re.finditer(r'"ability":\{', stream):
                start = m.end()
                braces = 1
                end = start
                for i, char in enumerate(stream[start:]):
                    if char == '{': braces += 1
                    elif char == '}': braces -= 1
                    if braces == 0:
                        end = start + i
                        break
                
                chunk = stream[start:end]
                # Bardziej elastyczne regexy (obsługują spacje i cudzysłowy wokół cyfr)
                n_match = re.search(r'"name"\s*:\s*"([^"]+)"', chunk)
                s_match = re.search(r'"slot"\s*:\s*"?(\d+)"?', chunk)
                i_match = re.search(r'"imgPath"\s*:\s*"([^"]+)"', chunk)
                
                if n_match and s_match:
                    slot = s_match.group(1)
                    img = i_match.group(1) if i_match else ""
                    # Jeśli slot jeszcze nie istnieje lub obecny wpis nie ma obrazka
                    if slot not in ability_details or not ability_details[slot].get("img"):
                        ability_details[slot] = {
                            "name": n_match.group(1),
                            "img": img
                        }

            # Mapowanie row_id z Next.js na sloty - bardziej elastyczne
            # Szukamy korelacji między numerem rzędu a slotem umiejętności
            row_matches = re.finditer(r'"(\d+)"\s*:\s*\{[^}]*?"ability"\s*:\s*\{[^}]*?"slot"\s*:\s*"?(\d+)"?', stream)
            for m in row_matches:
                row_id, slot_id = m.group(1), m.group(2)
                row_to_slot[row_id] = slot_id

            if not row_to_slot:
                for i in range(1, 5): row_to_slot[str(i)] = str(i)

            # Szukamy kafelków ulepszeń - bardziej odporna metoda
            upgrade_indices = re.finditer(r'["\\]+(\d+)-(\d+)["\\]+', stream)
            for match in upgrade_indices:
                row_id = match.group(1)
                lvl_str = match.group(2)
                
                # Szukamy "children":X w bliskim sąsiedztwie po znalezieniu "row-lvl"
                # Zwiększamy zasięg do 300, bo klasy CSS potrafią być bardzo długie
                lookahead = stream[match.end():match.end()+300]
                val_match = re.search(r'children":(\d+)', lookahead)
                if val_match:
                    lvl_idx = int(lvl_str) - 1
                    if 0 <= lvl_idx < 20:
                        slot = row_to_slot.get(row_id, row_id)
                        leveling_path[lvl_idx] = slot

            parsed_count = len([x for x in leveling_path if x is not None])
            print(f"[Scraper] Sparsowano {parsed_count}/20 kroków ulepszeń.")

            if any(leveling_path):
                print(f"[Scraper] Znaleziono ścieżkę ulepszeń: {leveling_path}")
            
            # Pobierz ikony w tle (lub zwróć ścieżki)
            for slot, info in ability_details.items():
                if info.get("img"):
                    info["local_path"] = self.download_ability_icon(info["img"])

            build_obj.ability_priority = leveling_path # Zachowujemy None dla zachowania indeksów poziomów
            build_obj.ability_details = ability_details
            return build_obj
        except Exception as e:
            print(f"Error fetching details: {e}")
            return build_obj

    def download_ability_icon(self, img_path):
        """Pobiera ikonę skilla ze SmiteSource (z ich CDN)."""
        if not img_path: return ""
        
        # FIX: Usuwamy escapowane ukośniki \/ oraz wiodące /
        clean_path = img_path.replace('\\/', '/').lstrip('/')
        
        if clean_path.endswith('.'):
            clean_path += "png"

        elif '/' in clean_path:
            filename = clean_path.split('/')[-1]
            if not filename:
                return "" # To jest folder (kończy się na /), ignoruj
            if '.' not in filename:
                # Jeśli nie ma rozszerzenia, spróbuj wymusić .png
                clean_path += ".png"

        url = f"https://cdn.smitesource.com/cdn-cgi/image/width=3840,format=auto,quality=75/{clean_path}"
        
        safe_name = os.path.basename(clean_path)
        if not safe_name or "." not in safe_name: return ""
        
        local_dir = os.path.join("assets", "abilities")
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, safe_name)
        
        if not os.path.exists(local_path):

            try:
                print(f"[Scraper] Pobieranie ikony umiejętności: {url}")
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    with open(local_path, 'wb') as f:
                        f.write(r.content)
                    print(f"✅ Pobrano: {safe_name}")
                else:
                    print(f"❌ Błąd pobierania ({r.status_code}): {url}")
            except Exception as e:
                print(f"❌ Błąd sieci przy pobieraniu ikony: {e}")
        return local_path

    def download_god_portraits(self, god_names):
        """Pobiera portrety bogów do assets/gods."""
        local_dir = os.path.join("assets", "gods")
        os.makedirs(local_dir, exist_ok=True)
        
        # Specyficzne mapowanie dla SmiteSource CDN (niespójne nazewnictwo)
        special_map = {
            "Da Ji": "Daji",
            "Sun Wukong": "Sun_Wukong",
            "Guan Yu": "Guan_Yu",
            "Hou Yi": "Hou_Yi",
            "Hun Batz": "Hun_Batz",
            "Ne Zha": "Ne_Zha",
            "Zhong Kui": "Zhong_Kui",
            "Ah Muzen Cab": "Ah_Muzen_Cab",
            "Morgan Le Fay": "Morgan_Le_Fay",
            "Maman Brigitte": "Maman_Brigitte",
            "The Morrigan": "The_Morrigan"
        }
        
        count = 0
        for name in god_names:
            # Sprawdzamy mapę wyjątków, inaczej domyślny CamelCase
            if name in special_map:
                url_name = special_map[name]
            else:
                url_name = name.replace(" ", "").replace("'", "")
            
            slug = name.lower().strip().replace(" ", "-").replace("'", "")
            url = f"https://cdn.smitesource.com/cdn-cgi/image/width=3840,format=auto,quality=75/Gods/{url_name}/Default/t_GodPortrait_{url_name}.png"
            filepath = os.path.join(local_dir, f"{slug}.png")
            
            if not os.path.exists(filepath):
                try:
                    r = requests.get(url, timeout=5)
                    if r.status_code == 200:
                        with open(filepath, "wb") as f:
                            f.write(r.content)
                        count += 1
                except:
                    continue
        if count > 0:
            print(f"[Scraper] Pobrano {count} nowych portretów bogów.")

    def get_smite2_live_builds(self, god_name: str, fast_preview: bool = False) -> GodData:
        """Pobiera mecze z smite2.live i tworzy statystyczne rekomendacje buildów dla każdej roli."""
        from bs4 import BeautifulSoup
        import re
        import time
        from concurrent.futures import ThreadPoolExecutor
        
        # 0. Sprawdzenie pamięci podręcznej (RAM Cache)
        cache_key = (god_name.lower().strip(), fast_preview)
        with self.cache_lock:
            if cache_key in self.stats_cache:
                cached_data, timestamp = self.stats_cache[cache_key]
                if time.time() - timestamp < 3600: # 1 godzina TTL
                    print(f"[Scraper Cache] Zwracam dane z pamięci podręcznej dla: {god_name} (Wiek: {int(time.time() - timestamp)}s)")
                    return cached_data
                    
        god_slug = god_name.capitalize().strip().replace(" ", "").replace("'", "")
        
        # 1. Sprawdź liczbę gier na aktualnym patchu
        url_initial = f"https://smite2.live/god/{god_slug}/builds?skill=master_plus"
        try:
            r = self.session.get(url_initial, timeout=15)
            soup = BeautifulSoup(r.text, 'html.parser')
        except Exception as e:
            print(f"[Scraper Stats] Błąd połączenia z smite2.live ({e})")
            return GodData(god_name=god_name, current_patch="Unknown", builds=[])

        # Pobieranie wersji
        version_select = soup.find_all("select", class_="gb-select")
        version_dropdown = None
        for s in version_select:
            opt = s.find("option")
            if opt and "v=" in opt.get("value", ""):
                version_dropdown = s
                break
                
        versions = []
        if version_dropdown:
            for opt in version_dropdown.find_all("option"):
                match = re.search(r'v=([^&]+)', opt.get("value", ""))
                if match:
                    versions.append(match.group(1))
                    
        current_version = versions[0] if len(versions) >= 1 else "ob34.0"
        self._cached_game_patch = current_version.upper()
        previous_version = versions[1] if len(versions) >= 2 else ""

        def get_count(skill, version_param):
            # Optymalizacja: jeśli pytamy o master_plus na aktualnej wersji, użyj gotowego soup z url_initial
            if skill == "master_plus" and version_param == current_version:
                st = soup
            else:
                test_url = f"https://smite2.live/god/{god_slug}/builds?skill={skill}&v={version_param}"
                try:
                    rt = self.session.get(test_url, timeout=5)
                    st = BeautifulSoup(rt.text, 'html.parser')
                except:
                    return 0
                    
            try:
                btn = st.find(id="gb-loadmore-btn")
                if btn:
                    count_span = btn.find(class_="gb-loadmore__count")
                    if count_span:
                        m_count = re.search(r'\((\d+)\s+total\)', count_span.text)
                        if m_count:
                            return int(m_count.group(1))
                    max_page = btn.get("data-max-page")
                    if max_page:
                        return int(max_page) * 50
                else:
                    return len(st.find_all(class_="ovm__player-link"))
            except:
                return 0
            return 0

        def version_matches(match_patch_str, version_dropdown_str):
            if not match_patch_str or not version_dropdown_str:
                return False
            p1 = match_patch_str.lower().strip().split('.')[0]
            p2 = version_dropdown_str.lower().strip().split('.')[0]
            return p1 == p2

        # Równoległe pobieranie liczby meczów dla obu skill groupów w celu przyśpieszenia startu
        future_master = self.executor.submit(get_count, "master_plus", current_version)
        future_demi = self.executor.submit(get_count, "demigod_deity", current_version)
        count_master = future_master.result()
        count_demi = future_demi.result()
        total_current = count_master + count_demi
        print(f"[Scraper Stats] Obecna wersja patcha: {current_version} (Gry w Master+: {count_master}, Demigod: {count_demi}, Łącznie: {total_current})")
        target_version = current_version
        total_expected = total_current

        def fetch_role_page(skill, role_param, page, version, per_page=200, is_ajax=False):
            if role_param:
                query_role = "Middle" if role_param == "Mid" else role_param
                role_filter = f"&role={query_role}"
            else:
                role_filter = ""
            ajax_param = "&ajax=1" if is_ajax else ""
            url = f"https://smite2.live/god/{god_slug}/builds?skill={skill}&mode=conquest-ranked{role_filter}&v={version}&page={page}&pp={per_page}{ajax_param}"
            try:
                res = self._get_with_retry(url, timeout=25, max_retries=3, use_session=True, label="Scraper Stats")
                if not res or res.status_code != 200:
                    return {"matches": [], "max_page": 1}
                
                try:
                    sp = BeautifulSoup(res.text, 'lxml')
                except Exception:
                    sp = BeautifulSoup(res.text, 'html.parser')
                ovm_infos = sp.find_all(class_="ovm__info")
                
                max_page = 1
                if not is_ajax:
                    btn = sp.find(id="gb-loadmore-btn")
                    if btn:
                        max_page_attr = btn.get("data-max-page")
                        if max_page_attr:
                            try:
                                max_page = int(max_page_attr)
                            except:
                                max_page = 1
                
                matches = []
                for info in ovm_infos:
                    parent = info.parent
                    if not parent:
                        continue
                    
                    role_badge = parent.find(class_="ovm__role-badge")
                    parsed_role = role_badge.get("alt", "Unknown").strip() if role_badge else "Unknown"
                    # Standaryzacja "Middle" -> "Mid" (zgodnie z filtrami PyQt6)
                    if parsed_role == "Middle":
                        parsed_role = "Mid"
                    elif parsed_role == "Unknown" and role_param:
                        parsed_role = role_param
                        
                    build_div = parent.find(class_="ovm__build")
                    starter = ""
                    items = []
                    # Wyciągnięcie Aspektu z dedykowanej klasy na stronie (talenty z lobby)
                    aspect_badge = parent.find(class_="ovm__aspect-badge")
                    aspect = aspect_badge.get("alt", "").strip() if aspect_badge else None
                    
                    if build_div:
                        starter_img = build_div.find(class_="ovm__item--starter")
                        if starter_img:
                            starter = starter_img.get("alt", "").strip() or starter_img.get("title", "").strip()
                                
                        item_imgs = build_div.find_all(class_="ovm__item")
                        for img in item_imgs:
                            if "ovm__item--starter" in img.get("class", []):
                                continue
                            item_name = img.get("alt", "").strip() or img.get("title", "").strip()
                            if item_name and "placeholder" not in item_name.lower():
                                items.append(item_name)
                    
                    match_id = parent.get("data-match-id")
                    player_id = parent.get("data-player-id")
                    
                    patch_span = info.find(class_="ovm__patch")
                    match_patch = patch_span.text.strip().lower() if patch_span else ""
                    
                    matches.append({
                        "role": parsed_role,
                        "starter": starter,
                        "items": items,
                        "aspect": aspect,
                        "match_id": match_id,
                        "player_id": player_id,
                        "patch": match_patch
                    })
                return {"matches": matches, "max_page": max_page}
            except Exception as e:
                print(f"[Scraper Stats] Wyjątek podczas pobierania strony {page} dla roli {role_param} ({skill}): {e}")
                return {"matches": [], "max_page": 1}

        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        def fetch_and_group_matches(version):
            all_matches = []
            initial_tasks = []
            # Reuse self.executor
            for skill in ["master_plus", "demigod_deity"]:
                initial_tasks.append((skill, self.executor.submit(fetch_role_page, skill, None, 1, version, 200, False)))
            
            # Zbieramy wyniki i ewentualnie dociągamy pozostałe strony asynchronicznie
            followup_tasks = []
            for skill, future in initial_tasks:
                res_dict = future.result()
                all_matches.extend(res_dict["matches"])
                max_page = res_dict["max_page"]
                
                if max_page > 1 and not fast_preview:
                    # Pobieramy KAŻDĄ możliwą stronę, bez żadnych limitów i kompromisów!
                    for p in range(2, max_page + 1):
                        followup_tasks.append(self.executor.submit(fetch_role_page, skill, None, p, version, 200, True))
            
            for future in as_completed(followup_tasks):
                res_dict = future.result()
                all_matches.extend(res_dict["matches"])
            
            print(f"[Scraper Stats] ({version}) Pomyślnie pobrano i sparsowano {len(all_matches)} meczów z smite2.live.")
            
            # Filtrujemy mecze tak, aby należały do odpowiedniej wersji (np. ob35 dla ob35.0)
            filtered_matches = []
            for m in all_matches:
                if version_matches(m.get("patch", ""), version):
                    filtered_matches.append(m)
            print(f"[Scraper Stats] ({version}) Po przefiltrowaniu pod kątem patcha pozostało {len(filtered_matches)} / {len(all_matches)} meczów.")
            
            # Grupuj mecze po (rola, aspekt) w pamięci RAM z deduplikacją
            seen_matches = set()
            grouped_matches = {}
            for m in filtered_matches:
                if not m["role"] or m["role"] == "Unknown":
                    continue
                m_id = m.get("match_id")
                p_id = m.get("player_id")
                if m_id and p_id:
                    key_match = (m_id, p_id)
                    if key_match in seen_matches:
                        continue
                    seen_matches.add(key_match)
                key = (m["role"], m["aspect"])
                if key not in grouped_matches:
                    grouped_matches[key] = []
                grouped_matches[key].append(m)
                
            # Zapewniamy, że wszystkie 5 podstawowych ról (dla domyślnego aspect = None) są obecne
            for role in ["Mid", "Carry", "Support", "Solo", "Jungle"]:
                key = (role, None)
                if key not in grouped_matches:
                    grouped_matches[key] = []
                    
            # Sprawdź, czy jakakolwiek rola/aspekt ma mniej niż 30 meczów i potrzebuje Obsidian+
            needs_obsidian_keys = set()
            needs_obsidian_roles = set()
            for key, matches in grouped_matches.items():
                if len(matches) < 30:
                    needs_obsidian_keys.add(key)
                    needs_obsidian_roles.add(key[0])
            
            if needs_obsidian_keys and not fast_preview:
                print(f"[Scraper Stats] ({version}) Wykryto role z liczbą gier < 30: {needs_obsidian_roles}. Pobieram dane z Obsidian+...")
                obsidian_matches = []
                tasks_obsidian = []
                # Reuse self.executor
                for p in [1, 2]:
                    tasks_obsidian.append(self.executor.submit(fetch_role_page, "obsidian_plus", None, p, version, 200, False))
                for future in as_completed(tasks_obsidian):
                    res_dict = future.result()
                    obsidian_matches.extend(res_dict["matches"])
                
                print(f"[Scraper Stats] ({version}) Pomyślnie pobrano {len(obsidian_matches)} meczów z Obsidian+.")
                
                # Filtrujemy mecze Obsidian+ tak, aby należały do odpowiedniej wersji
                filtered_obsidian = []
                for m in obsidian_matches:
                    if version_matches(m.get("patch", ""), version):
                        filtered_obsidian.append(m)
                print(f"[Scraper Stats] ({version}) Po przefiltrowaniu Obsidian+ pozostało {len(filtered_obsidian)} / {len(obsidian_matches)} meczów.")
                
                # Dodaj mecze z Obsidian+ do odpowiednich grup z deduplikacją
                for m in filtered_obsidian:
                    if not m["role"] or m["role"] == "Unknown":
                        continue
                    key = (m["role"], m["aspect"])
                    if key not in needs_obsidian_keys:
                        continue
                    m_id = m.get("match_id")
                    p_id = m.get("player_id")
                    if m_id and p_id:
                        key_match = (m_id, p_id)
                        if key_match in seen_matches:
                            continue
                        seen_matches.add(key_match)
                    if key not in grouped_matches:
                        grouped_matches[key] = []
                    grouped_matches[key].append(m)
            
            return {
                "grouped_matches": grouped_matches,
                "needs_obsidian_keys": needs_obsidian_keys
            }

        # 3. Klasyfikacja przedmiotów Tier 3 oraz reliktów z self.item_db
        if not self.item_db:
            self.fetch_master_items()
            
        t3_items = set()
        relics_in_db = set()
        for name, info in self.item_db.items():
            if isinstance(info, dict):
                cat = info.get("category")
                name_cleaned = name.lower().strip()
                if cat == "item":
                    img_url = info.get("image_url") or ""
                    if "/T3_" in img_url:
                        t3_items.add(name_cleaned)
                elif cat == "relic":
                    relics_in_db.add(name_cleaned)
                    # Jeśli to NIE jest podstawowy relic, traktujemy go jako Tier 3 (aktywny przedmiot do 6 slotów)
                    if name_cleaned not in self.basic_relic_names:
                        t3_items.add(name_cleaned)

        # Pobierz dane dla aktualnego patcha
        curr_data = fetch_and_group_matches(current_version)
        grouped_matches_curr = curr_data["grouped_matches"]
        needs_obsidian_curr = curr_data["needs_obsidian_keys"]

        # Funkcja pomocnicza do sprawdzania wiarygodności danych (sufficiency)
        from collections import Counter
        
        def check_sufficiency(matches):
            total_games = len(matches)
            starter_counter = Counter()
            slot_counters = [Counter() for _ in range(6)]
            relic_counter = Counter()
            
            for m in matches:
                starter_norm = m["starter"].strip().replace("’", "'") if m["starter"] else ""
                if starter_norm:
                    starter_counter[starter_norm] += 1
                
                # Zostaw tylko przedmioty Tier 3 (z wykluczeniem podstawowych reliktów) do slotów
                t3_only_items = []
                for item in m["items"]:
                    if not item:
                        continue
                    item_norm = item.strip().replace("’", "'")
                    item_cleaned = item_norm.lower()
                    is_basic_relic = item_cleaned in self.basic_relic_names
                    if is_basic_relic:
                        relic_counter[item_norm] += 1
                    elif item_cleaned in t3_items:
                        t3_only_items.append(item_norm)
                
                for slot_idx, item in enumerate(t3_only_items):
                    if slot_idx < 6:
                        slot_counters[slot_idx][item] += 1

            # Inteligentne scalanie starterów (podstawowe sumujemy do najpopularniejszej wersji ulepszonej)
            lower_keys = {k.lower().strip(): k for k in starter_counter.keys()}
            for basic_name, basic_orig_key in list(lower_keys.items()):
                if hasattr(self, 'item_db') and self.item_db:
                    info = self.item_db.get(basic_name)
                    if isinstance(info, dict) and info.get("is_starter_t1"):
                        upgrades = info.get("upgrades") or []
                        basic_count = starter_counter[basic_orig_key]
                        
                        best_upgrade_orig_key = None
                        best_upgrade_count = -1
                        for upg in upgrades:
                            upg_low = upg.lower().strip()
                            if upg_low in lower_keys:
                                upg_orig_key = lower_keys[upg_low]
                                upg_count = starter_counter[upg_orig_key]
                                if upg_count > best_upgrade_count:
                                    best_upgrade_count = upg_count
                                    best_upgrade_orig_key = upg_orig_key
                                    
                        if best_upgrade_orig_key:
                            starter_counter[best_upgrade_orig_key] += basic_count
                            del starter_counter[basic_orig_key]

            # Sprawdzamy, czy każdy z 6 slotów na przedmioty ma co najmniej 2 unikalne przedmioty,
            # a slot na starter zawiera co najmniej 1 przedmiot.
            has_enough_variety = (
                len(starter_counter) >= 1 and
                all(len(slot_counters[i]) >= 2 for i in range(6))
            )
            
            sufficient = (total_games >= 30) and has_enough_variety
            return sufficient, starter_counter, slot_counters, relic_counter, total_games

        # Leniwa inicjalizacja danych dla poprzedniego patcha
        # Sprawdź, czy potrzebny jest fallback (jeśli jakiekolwiek dane z curr są niewystarczające)
        grouped_matches_prev = None
        needs_obsidian_prev = set()
        
        # Wstępne sprawdzenie: czy jakiekolwiek role z curr mają mniej niż 30 gier?
        needs_prev_data = False
        for (role, aspect), matches in grouped_matches_curr.items():
            if len(matches) < 30:
                needs_prev_data = True
                break
        
        if needs_prev_data and previous_version:
            print(f"[Scraper Stats] Wykryto potrzebę fallbacku. Pobieram dane z poprzedniego patcha: {previous_version}...")
            prev_data = fetch_and_group_matches(previous_version)
            grouped_matches_prev = prev_data["grouped_matches"]
            needs_obsidian_prev = prev_data["needs_obsidian_keys"]

        # Znajdź wszystkie główne aspekty dla tego boga z WSZYSTKICH dostępnych danych (curr + prev)
        # Wymagamy minimum 10 gier łącznie (z obu patchy) aby aspekt się kwalifikował
        aspect_counts = Counter()
        for matches in grouped_matches_curr.values():
            for m in matches:
                if m["aspect"]:
                    aspect_counts[m["aspect"]] += 1
        if grouped_matches_prev:
            for matches in grouped_matches_prev.values():
                for m in matches:
                    if m["aspect"]:
                        aspect_counts[m["aspect"]] += 1
        all_aspects = {asp for asp, count in aspect_counts.items() if count >= 10}

        # Zapewniamy, że wszystkie ról i aspektów są zdefiniowane do sprawdzenia
        all_keys = []
        for role in ["Mid", "Carry", "Support", "Solo", "Jungle"]:
            all_keys.append((role, None))
            for aspect in all_aspects:
                all_keys.append((role, aspect))

        builds = []

        
        for (role, aspect) in all_keys:
            matches_curr = grouped_matches_curr.get((role, aspect), [])
            sufficient_curr, starter_curr, slots_curr, relic_curr, games_curr = check_sufficiency(matches_curr)

            # Sprawdzenie czy potrzebny jest fallback do poprzedniego patcha
            use_prev = False
            if not sufficient_curr and previous_version and grouped_matches_prev is not None:
                
                matches_prev = grouped_matches_prev.get((role, aspect), [])
                sufficient_prev, starter_prev, slots_prev, relic_prev, games_prev = check_sufficiency(matches_prev)
                
                # Zezwól na fallback tylko wtedy, gdy poprzedni patch ma więcej gier lub gdy jest sufficient, a obecny nie
                if games_prev > games_curr or (sufficient_prev and not sufficient_curr):
                    use_prev = True
            
            # Ustal wersję patcha i dane meczowe
            if use_prev:
                print(f"[Scraper Stats] [Fallback] dla roli {role}{f' ({aspect})' if aspect else ''} do poprzedniego patcha {previous_version} (Gry: {games_curr} -> {games_prev})")
                starter_counter = starter_prev
                slot_counters = slots_prev
                relic_counter = relic_prev
                total_games = games_prev
                target_version = previous_version
                insufficient = not sufficient_prev
                version_needs_obsidian = needs_obsidian_prev
            else:
                starter_counter = starter_curr
                slot_counters = slots_curr
                relic_counter = relic_curr
                total_games = games_curr
                target_version = current_version
                insufficient = not sufficient_curr
                version_needs_obsidian = needs_obsidian_curr

            aspect_suffix = f" ({aspect})" if aspect else ""
            
            if insufficient:
                # Wyznaczamy powód braku wiarygodności
                # (Jeśli has_enough_variety dla wybranego zestawu danych jest fałszem)
                # Obliczamy variety na nowo dla wybranego target_version
                has_enough_variety = (
                    len(starter_counter) >= 1 and
                    all(len(slot_counters[i]) >= 2 for i in range(6))
                )
                
                if total_games < 30:
                    reason = f"[!] Niewystarczająca liczba rozegranych meczów na roli {role} (Rozegrano: {total_games} / 30)"
                    reason_mini = f"[!] Mało gier na roli {role} ({total_games}/30)"
                else:
                    reason = f"[!] Zbyt mała różnorodność przedmiotów na roli {role} (wymagane min. 2 unikalne przedmioty na slot)"
                    reason_mini = f"[!] Mała różnorodność na roli {role}"
                    
                builds.append(SmiteBuild(
                    title=f"{role}{aspect_suffix} (Meta Stats - {target_version.upper()})",
                    patch=target_version.upper(),
                    is_aspect=bool(aspect),
                    roles=[role],
                    starter_items=[],
                    final_items=[],
                    relics=[],
                    consumables=[],
                    swap_items=[],
                    build_url="smite2live_stats",
                    upvotes=total_games,
                    author="High Elo Matches",
                    is_partner=True,
                    is_stats=True,
                    stats_data={
                        "insufficient_reason": reason,
                        "insufficient_reason_mini": reason_mini,
                        "uses_obsidian": (role, aspect) in version_needs_obsidian
                    },
                    insufficient_data=True
                ))
                continue
                
            # Pobierz top 3 dla każdego
            top_star_list = starter_counter.most_common(3)
            top_starters = [{"item": item, "pct": round((count / total_games) * 100)} for item, count in top_star_list]
            top_slots = [
                [{"item": item, "pct": round((count / total_games) * 100)} for item, count in slot_counters[i].most_common(3)]
                for i in range(6)
            ]
            top_relics = [{"item": item, "pct": round((count / total_games) * 100)} for item, count in relic_counter.most_common(3)]
            
            # Mapowanie na standardowe pola płaskie (pierwszy wybór) dla kompatybilności
            flat_starters = [top_starters[0]["item"]] if top_starters else []
            flat_final = []
            used_items = set()
            for i, slot in enumerate(top_slots):
                added = False
                for item_option in slot:
                    item_name = item_option["item"]
                    if item_name not in used_items:
                        flat_final.append(item_name)
                        used_items.add(item_name)
                        added = True
                        break
                # Jeśli wszystkie 3 opcje z top_slots (pokazywane w UI) były już użyte,
                # szukamy głębiej w pełnym liczniku slot_counters[i], pobierając 4., 5., itd. najczęstszy unikalny przedmiot
                if not added:
                    for item_name, count in slot_counters[i].most_common():
                        if item_name not in used_items:
                            flat_final.append(item_name)
                            used_items.add(item_name)
                            added = True
                            break
                # Skrajny fallback: jeśli z jakiegoś powodu nie ma innych opcji, bierzemy top-1
                if not added and slot:
                    flat_final.append(slot[0]["item"])
                    
            flat_relics = [top_relics[0]["item"]] if top_relics else []
            
            stats_data = {
                "starter": top_starters,
                "slots": top_slots,
                "relic": top_relics,
                "uses_obsidian": (role, aspect) in version_needs_obsidian
            }
            
            builds.append(SmiteBuild(
                title=f"{role}{aspect_suffix} (Meta Stats - {target_version.upper()})",
                patch=target_version.upper(),
                is_aspect=bool(aspect),
                roles=[role],
                starter_items=flat_starters,
                final_items=flat_final,
                relics=flat_relics,
                consumables=[],
                swap_items=[],
                build_url="smite2live_stats",
                upvotes=total_games,
                author="High Elo Matches",
                is_partner=True,
                is_stats=True,
                stats_data=stats_data,
                insufficient_data=False
            ))

        # Sortuj buildy: najpierw obecny patch (zielone), potem poprzednie (żółte), na końcu czerwone (niespełniające).
        # W ramach każdej grupy: po liczbie gier (malejąco).
        def get_patch_num(v):
            m = re.search(r'(\d+)', v.upper())
            return int(m.group(1)) if m else 0
        current_pn = get_patch_num(current_version)

        builds.sort(key=lambda b: (
            2 if b.insufficient_data else (1 if get_patch_num(b.patch) < current_pn else 0),
            -b.upvotes
        ))
        res_data = GodData(god_name=god_name.capitalize(), current_patch=current_version.upper(), builds=builds)
        
        with self.cache_lock:
            self.stats_cache[cache_key] = (res_data, time.time())
            
        return res_data

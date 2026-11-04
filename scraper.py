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

            t3_headings = {"Tier III - Offensive", "Tier III - Defensive", "Tier III - Hybrid"}
            t3_acorns = {"ashwhorl acorn", "briskberry acorn", "thistlethorn acorn"}

            self.item_db = {}
            # Wiki może mieć różne struktury, szukamy wszystkich nagłówków i kategoryzujemy linki pod nimi
            current_category = None
            current_heading = None
            
            for tag in soup.find_all(['h2', 'h3', 'h4', 'a']):
                if tag.name in ['h2', 'h3', 'h4']:
                    text = tag.get_text().strip().replace('[edit]', '').strip()
                    if text in mapping:
                        current_category = mapping[text]
                        current_heading = text
                    elif tag.name == 'h2' and text != "List of items":
                        current_category = None
                        current_heading = None
                
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
                                    is_t3 = (current_heading in t3_headings) or (name_key in t3_acorns)
                                    self.item_db[name_key] = {
                                        "category": current_category,
                                        "is_t3": is_t3,
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
            url = "https://smite2.live/god/Ymir/builds?skill=master_plus"
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

    STARTER_SLOT_ORDER = {0: 0, 7: 1, 10: 2, 1: 3, 2: 4, 8: 5, 9: 6}
    GOD_SLUG_MAP = {
        "princess bari": "bari",
        "hua mulan": "mulan",
        "the morrigan": "the-morrigan",
        "baron samedi": "baron-samedi",
        "da ji": "da-ji",
        "guan yu": "guan-yu",
        "hou yi": "hou-yi",
        "hun batz": "hun-batz",
        "jing wei": "jing-wei",
        "morgan le fay": "morgan-le-fay",
        "ne zha": "ne-zha",
        "nu wa": "nu-wa",
        "sun wukong": "sun-wukong",
    }

    SMITE2_LIVE_SLUG_MAP = {
        "princess bari": "Bari",
        "hua mulan": "Mulan",
        "da ji": "Daji",
    }

    def _calculate_tier(self, match_score: float, games: int, evidence_kind: str = "matched") -> str:
        """Oblicza ocenę buildu (S+, S, A+, A, B, C, D) dokładnie wg progów matchScore ze SmiteSource."""
        if games <= 0 or not match_score or match_score <= 0 or evidence_kind != "matched":
            return ""
        if match_score >= 8500:
            return "S+"
        elif match_score >= 7500:
            return "S"
        elif match_score >= 6500:
            return "A+"
        elif match_score >= 5000:
            return "A"
        elif match_score >= 3500:
            return "B"
        elif match_score >= 2000:
            return "C"
        else:
            return "D"

    def _get_god_abilities(self, god_slug: str, sample_build_slug: str = "") -> dict:
        """Pobiera nazwy i ikony 4 umiejętności boga raz i cachuje je."""
        if not hasattr(self, "god_abilities_cache"):
            self.god_abilities_cache = {}
        if god_slug in self.god_abilities_cache:
            return self.god_abilities_cache[god_slug]
            
        url = f"{self.base_url}/build/{sample_build_slug}" if sample_build_slug else f"{self.base_url}/gods/{god_slug}"
        abilities = {}
        try:
            r = self._get_with_retry(url, timeout=8, max_retries=2, use_session=True, label="GodAbilities")
            if r and r.status_code == 200:
                pattern = re.compile(r'\\"ability\\":\{\\"name\\":\\"(?P<name>[^"]+)\\",\\"imgPath\\":\\"(?P<img_path>[^"]+)\\",\\"slot\\":(?P<slot>[1-4])')
                for m in pattern.finditer(r.text):
                    slot = m.group("slot")
                    if slot not in abilities:
                        img_path = m.group("img_path")
                        abilities[slot] = {
                            "name": m.group("name"),
                            "img": img_path,
                            "local_path": self.download_ability_icon(img_path)
                        }
        except Exception as e:
            print(f"[Scraper] Błąd pobierania umiejętności boga {god_slug}: {e}")
            
        if len(abilities) >= 4:
            self.god_abilities_cache[god_slug] = abilities
        return abilities

    def get_all_builds(self, god_name: str) -> GodData:
        clean_name = god_name.lower().strip()
        slug = self.GOD_SLUG_MAP.get(clean_name, clean_name.replace(" ", "-").replace("'", ""))
        
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
        first_build_slug = ""
        ts = int(time.time() * 1000)
        query_variants = [
            ("recent_base", f"{self.base_url}/builds?god={slug}&sort=recent&aspect=base&t={ts}"),
            ("recent_aspect", f"{self.base_url}/builds?god={slug}&sort=recent&aspect=aspect&t={ts}"),
        ]

        def _extract_raw_builds_from_html(html_text: str) -> list:
            extracted = []
            # 1. Nowy format Next.js RSC payload ("initialBuilds":)
            esc_marker = chr(92) + '"initialBuilds' + chr(92) + '":'
            idx = html_text.find(esc_marker)
            if idx != -1:
                raw = html_text[idx - 1:]
                unescaped = raw.replace(chr(92) + chr(34), chr(34)).replace(chr(92) + chr(92), chr(92))
                try:
                    obj, _ = json.JSONDecoder().raw_decode(unescaped)
                    extracted = obj.get("initialBuilds", {}).get("builds", [])
                except Exception:
                    pass
            # 2. Fallback: wyszukiwanie tablicy builds regexem
            if not extracted:
                m = re.search(r'\"builds\":(\[\{.+?\}\])(?:,\"|\})', html_text)
                if m:
                    try:
                        raw = m.group(1).replace(chr(92) + chr(34), chr(34)).replace(chr(92) + chr(92), chr(92))
                        extracted = json.loads(raw)
                    except Exception:
                        pass
            # 3. Fallback wsteczny (starsze streamy Next.js)
            if not extracted:
                fragments = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html_text)
                if fragments:
                    full_stream = "".join(fragments).replace(chr(92) + chr(34), chr(34)).replace(chr(92) + chr(92), chr(92))
                    for key in ['"builds":', '"godBuilds":']:
                        pos = full_stream.rfind(key)
                        if pos != -1:
                            json_str = self._extract_balanced_json(full_stream, full_stream.find("[", pos))
                            if json_str:
                                extracted = json.loads(json_str)
                                break
            return extracted

        def _fetch_variant(variant_tuple):
            v_kind, v_url = variant_tuple
            print(f"[Scraper] Pobieranie buildów ({v_kind}): {v_url}")
            resp = self._get_with_retry(v_url, timeout=10, max_retries=2, use_session=True, label=f"Scraper SmiteSource ({v_kind})")
            if resp and resp.status_code == 200:
                return v_kind, _extract_raw_builds_from_html(resp.text)
            return v_kind, []

        try:
            variant_results = list(self.executor.map(_fetch_variant, query_variants))
            raw_builds_with_source = []
            seen_raw_slugs = set()
            for v_kind, v_builds in variant_results:
                for rb in v_builds or []:
                    rb_slug = rb.get("slug", "")
                    if rb_slug and rb_slug in seen_raw_slugs:
                        continue
                    if rb_slug:
                        seen_raw_slugs.add(rb_slug)
                    raw_builds_with_source.append((v_kind, rb))

            # Sortujemy chronologicznie po dacie utworzenia (createdAt malejąco), tak jak sort=recent na SmiteSource
            raw_builds_with_source.sort(
                key=lambda item: str((item[1] or {}).get("createdAt") or ""),
                reverse=True
            )

            if raw_builds_with_source:
                for v_kind, rb in raw_builds_with_source:
                        rb_slug = rb.get("slug", "")
                        if not first_build_slug and rb_slug:
                            first_build_slug = rb_slug
                            
                        # Items parsing po itemSlot
                        items = rb.get("items") or []
                        
                        # 1. Starting items (Starter + Relic + Conquest Curio + T1 item + Potions/Wards)
                        # Odrzucamy duplikaty Curio z innych trybów (20, 21, 22)
                        starting_items_raw = [it for it in items if it.get("isStartingBuild") and it.get("itemSlot") not in (20, 21, 22)]
                        starting_items_sorted = sorted(starting_items_raw, key=lambda x: self.STARTER_SLOT_ORDER.get(x.get("itemSlot", 99), 99))
                        starters = [(it.get("item") or {}).get("name") for it in starting_items_sorted if (it.get("item") or {}).get("name")]
                        
                        # 2. Final items: Slot 0 (Upgraded starter) + Sloty 1..6 (Core Items) + Slot 7 (Relic)
                        final_items_raw = [it for it in items if not it.get("isStartingBuild")]
                        upgraded_starters = [it for it in final_items_raw if it.get("itemSlot") == 0]
                        core_items = sorted([it for it in final_items_raw if 1 <= it.get("itemSlot", 0) <= 6], key=lambda x: x.get("itemSlot", 0))
                        relic_items = [it for it in final_items_raw if it.get("itemSlot") == 7]
                        
                        final_ordered = upgraded_starters + core_items + relic_items
                        core = [(it.get("item") or {}).get("name") for it in final_ordered if (it.get("item") or {}).get("name")]
                        relics = [(it.get("item") or {}).get("name") for it in relic_items if (it.get("item") or {}).get("name")]
                        
                        # 3. Consumables
                        consumables_raw = [it for it in items if it.get("itemSlot") in (8, 9)]
                        consumables = [(it.get("item") or {}).get("name") for it in consumables_raw if (it.get("item") or {}).get("name")]
                        
                        # Statystyki (Match evidence & win rate wg SmiteSource)
                        games = rb.get("matchEvidenceGames") or 0
                        wins = min(games, rb.get("matchEvidenceWins") or 0)
                        losses = max(0, games - wins)
                        match_score = rb.get("matchScore") or 0
                        evidence_kind = rb.get("matchEvidenceKind") or "matched"
                        has_evidence = (evidence_kind == "matched" and games > 0 and match_score > 0)
                        win_rate_val = round((wins / games) * 100) if has_evidence else 0
                        win_rate_str = f"{win_rate_val}%" if has_evidence else ""
                        tier = self._calculate_tier(match_score, games, evidence_kind)
                        total_cost = sum(((it.get("item") or {}).get("totalGoldCost") or it.get("itemCost") or 0) * max(1, it.get("quantity") or 1) for it in final_items_raw)
                        
                        # Patch
                        patch_obj = rb.get("patch") or {}
                        current_patch_str = self.get_current_game_patch()
                        patch_name = patch_obj.get("patchShortName", current_patch_str) if isinstance(patch_obj, dict) else str(patch_obj)
                        
                        # Aspect (sprawdzamy źródło zapytania aspect=aspect oraz obiekt talent)
                        has_aspect = (v_kind == "recent_aspect")
                        gods_data = rb.get("gods") or []
                        if not has_aspect and gods_data and isinstance(gods_data, list):
                            g0 = gods_data[0]
                            if g0.get("talent") or g0.get("talentSlug") or g0.get("talentMasterId") or g0.get("aspectId"):
                                has_aspect = True
                        if not has_aspect and (rb.get("talent") or rb.get("aspectId")):
                            has_aspect = True
                            
                        # Roles
                        roles = [str(r) for r in (rb.get("roles") or []) if r]
                        
                        # Author & Partner/Creator
                        user_data = rb.get("user") or {}
                        author_name = "Unknown"
                        profiles = user_data.get("profiles") or []
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
                        is_partner = user_data.get("role") in ("partner", "creator") or bool(rb.get("isFeatured"))
                        
                        # Swaps (dostępne bezpośrednio w initialBuilds!)
                        optional_swaps = []
                        for opt in rb.get("optionalItems") or []:
                            f_name = (opt.get("item") or {}).get("name")
                            t_name = (opt.get("optionalItem") or {}).get("name")
                            reason = (opt.get("notes") or "").strip() or "Situational"
                            if f_name and t_name:
                                optional_swaps.append({"from": f_name, "to": t_name, "reason": reason})
                                
                        # Ability Priority (dostępne bezpośrednio w initialBuilds!)
                        raw_order = rb.get("abilityLevelOrder") or []
                        ability_priority = [str(x) for x in raw_order if isinstance(x, int) and x > 0]
                        
                        build_obj = SmiteBuild(
                            title=str(rb.get("title", "Build")),
                            patch=patch_name,
                            is_aspect=has_aspect,
                            roles=roles,
                            starter_items=starters,
                            final_items=core,
                            relics=relics,
                            consumables=consumables,
                            swap_items=optional_swaps,
                            build_url=f"{self.base_url}/build/{rb_slug}",
                            upvotes=int(rb.get("upvoteCount") or games or 0),
                            author=str(author_name),
                            is_partner=is_partner,
                            ability_priority=ability_priority,
                            tier=tier,
                            win_rate=win_rate_str,
                            wins=wins,
                            losses=losses,
                            total_matches=games,
                            cost=total_cost,
                        )
                        all_builds.append(build_obj)
        except Exception as e:
            print(f"[Scraper] Błąd pobierania bazy danych buildów: {e}")
            
        if not all_builds: return None
        
        # Pobieramy ikony i nazwy umiejętności dla danego boga raz i przypisujemy do buildów
        try:
            god_abilities = self._get_god_abilities(slug, first_build_slug)
            if god_abilities:
                for b in all_builds:
                    b.ability_details = god_abilities
        except Exception as e:
            print(f"[Scraper] Nie udało się pobrać umiejętności dla boga {god_name}: {e}")
            
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
        """Pobiera detale (np. Swapy, siatkę skilli) ze strony buildu."""
        if not build_obj.build_url: return build_obj
        
        # Jeśli build ma już pobrane swapy, priorytet umiejętności i detale skilli, pomijamy zapytanie sieciowe!
        if build_obj.swap_items and len(build_obj.ability_priority) >= 20 and build_obj.ability_details:
            return build_obj
            
        try:
            r = self._get_with_retry(build_obj.build_url, timeout=8, max_retries=2, use_session=True, label="BuildDetails")
            if not r or r.status_code != 200:
                return build_obj
            
            stream = r.text
            import html
            
            # 1. Ability details (Slot 1-4)
            if not build_obj.ability_details:
                ability_pattern = re.compile(r'\\"ability\\":\{\\"name\\":\\"(?P<name>[^"]+)\\",\\"imgPath\\":\\"(?P<img_path>[^"]+)\\",\\"slot\\":(?P<slot>[1-4])')
                details = {}
                for m in ability_pattern.finditer(stream):
                    slot = m.group("slot")
                    if slot not in details:
                        img_path = m.group("img_path")
                        details[slot] = {
                            "name": m.group("name"),
                            "img": img_path,
                            "local_path": self.download_ability_icon(img_path)
                        }
                if details:
                    build_obj.ability_details = details
            else:
                for slot, info in build_obj.ability_details.items():
                    if info.get("img") and not info.get("local_path"):
                        info["local_path"] = self.download_ability_icon(info["img"])

            # 2. Ability leveling path (1-20)
            if len(build_obj.ability_priority) < 20:
                matches = re.findall(r'\"([1-4])-(\d+)-\d+\",\{\"style\":\{\"backgroundColor\"', stream)
                if matches:
                    points = sorted([(int(lvl), slot) for slot, lvl in matches], key=lambda x: x[0])
                    build_obj.ability_priority = [slot for lvl, slot in points]
                else:
                    row_to_slot = {str(i): str(i) for i in range(1, 5)}
                    old_path = [None] * 20
                    upgrade_indices = re.finditer(r'["\]+(\d+)-(\d+)["\]+', stream)
                    for match in upgrade_indices:
                        row_id, lvl_str = match.group(1), match.group(2)
                        lookahead = stream[match.end():match.end()+300]
                        val_match = re.search(r'children":(\d+)', lookahead)
                        if val_match:
                            lvl_idx = int(lvl_str) - 1
                            if 0 <= lvl_idx < 20:
                                old_path[lvl_idx] = row_to_slot.get(row_id, row_id)
                    if any(old_path):
                        build_obj.ability_priority = [x for x in old_path if x is not None]

            # 3. Swaps
            if not build_obj.swap_items:
                swaps = []
                for m in re.finditer(r'<p class="flex-1 text-ss-fg-muted text-xs leading-relaxed">(.*?)</p>', stream):
                    reason = html.unescape(m.group(1)).strip()
                    start_pos = max(0, m.start() - 2500)
                    chunk = stream[start_pos:m.start()]
                    labels = re.findall(r'<a[^>]+aria-label="([^"]+)"', chunk)
                    if len(labels) >= 2:
                        from_item = html.unescape(labels[-2])
                        to_item = html.unescape(labels[-1])
                        swaps.append({"from": from_item, "to": to_item, "reason": reason})
                if swaps:
                    build_obj.swap_items = swaps

            return build_obj
        except Exception as e:
            print(f"[Scraper] Błąd podczas pobierania szczegółów buildu: {e}")
            return build_obj

    def download_ability_icon(self, img_path):
        """Pobiera ikonę skilla ze SmiteSource (z ich CDN)."""
        if not img_path: return ""
        clean_path = img_path.replace('\\/', '/').lstrip('/')
        if clean_path.endswith('.'):
            clean_path += "png"
        elif '/' in clean_path:
            filename = clean_path.split('/')[-1]
            if not filename:
                return ""
            if '.' not in filename:
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
                    print(f"[OK] Pobrano ikone: {safe_name}")
                else:
                    print(f"[ERR] Blad pobierania ikony ({r.status_code}): {url}")
            except Exception as e:
                print(f"[ERR] Blad sieci przy pobieraniu ikony: {e}")
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
                    
        clean_god_key = god_name.lower().strip()
        god_slug = self.SMITE2_LIVE_SLUG_MAP.get(
            clean_god_key,
            god_name.title().strip().replace(" ", "").replace("'", "")
        )
        
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
        if versions:
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
                page1_matches = res_dict["matches"]
                all_matches.extend(page1_matches)
                max_page = res_dict["max_page"]
                
                # Jeśli ostatni mecz na 1. stronie należy już do starszego patcha, kolejne strony nie mają meczów z `version`
                last_match_matches_ver = bool(page1_matches) and version_matches(page1_matches[-1].get("patch", ""), version)
                if max_page > 1 and not fast_preview and last_match_matches_ver:
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
            pre_obsidian_counts = {k: len(v) for k, v in grouped_matches.items()}
            needs_obsidian_keys = set()
            needs_obsidian_roles = set()
            for key, matches in grouped_matches.items():
                if len(matches) < 30:
                    needs_obsidian_keys.add(key)
                    needs_obsidian_roles.add(key[0])
            
            if needs_obsidian_keys and not fast_preview:
                print(f"[Scraper Stats] ({version}) Wykryto role z liczbą gier < 30: {needs_obsidian_roles}. Pobieram dane z Obsidian+...")
                obsidian_matches = []
                obs_p1 = fetch_role_page("obsidian_plus", None, 1, version, 200, False)
                obs_p1_matches = obs_p1["matches"]
                obsidian_matches.extend(obs_p1_matches)
                obs_max_page = obs_p1["max_page"]
                
                obs_last_matches_ver = bool(obs_p1_matches) and version_matches(obs_p1_matches[-1].get("patch", ""), version)
                if obs_max_page > 1 and obs_last_matches_ver:
                    tasks_obsidian = []
                    for p in range(2, obs_max_page + 1):
                        tasks_obsidian.append(self.executor.submit(fetch_role_page, "obsidian_plus", None, p, version, 200, True))
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
                    if pre_obsidian_counts.get(key, 0) >= 30:
                        continue
                    needs_obsidian_keys.add(key)
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
            
        t3_items = {
            "ashwhorl acorn",
            "briskberry acorn",
            "thistlethorn acorn",
        }
        relics_in_db = set()
        for name, info in self.item_db.items():
            if isinstance(info, dict):
                cat = info.get("category")
                name_cleaned = name.lower().strip()
                if cat == "item":
                    img_url = info.get("image_url") or ""
                    if info.get("is_t3") or "/T3_" in img_url or "_T3_" in img_url or "/Items/T3/" in img_url:
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
                if total_games < 30:
                    reason_type = "low_games"
                    reason = f"[!] Insufficient matches on role {role} (Played: {total_games} / 30)"
                    reason_mini = f"[!] Low matches on role {role} ({total_games}/30)"
                else:
                    reason_type = "low_variety"
                    reason = f"[!] Insufficient item variety on role {role} (min. 2 unique items per slot required)"
                    reason_mini = f"[!] Low item variety on role {role}"
                    
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
                        "reason_type": reason_type,
                        "total_games": total_games,
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

        zdeduplikowane = {}
        for b in builds:
            # Jako unikalnego klucza używamy tytułu (np. "Jungle (Meta Stats - OB35.0)")
            if b.title not in zdeduplikowane:
                zdeduplikowane[b.title] = b
            else:
                # Jeśli build już jest na liście, priorytetyzujemy poprawny (zielony) nad błędem (czerwonym)
                if not b.insufficient_data and zdeduplikowane[b.title].insufficient_data:
                    zdeduplikowane[b.title] = b
                    
        builds = list(zdeduplikowane.values())
        # ---------------------------------------------------------------

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

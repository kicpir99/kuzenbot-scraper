from dataclasses import dataclass, field
from typing import List

@dataclass
class SmiteBuild:
    title: str
    patch: str
    is_aspect: bool
    roles: list[str] = field(default_factory=list)  # np. ['Mid'], ['Carry', 'Mid', 'Solo']
    starter_items: list[str] = field(default_factory=list)
    final_items: list[str] = field(default_factory=list)
    relics: list[str] = field(default_factory=list)
    consumables: list[str] = field(default_factory=list)
    swap_items: list[dict] = field(default_factory=list) # [{'from': 'A', 'to': 'B', 'reason': 'Why'}]
    build_url: str = ""
    upvotes: int = 0
    author: str = "Unknown"
    is_partner: bool = False
    ability_priority: list[str] = field(default_factory=list)
    ability_details: dict = field(default_factory=dict) # {"1": {"name": "...", "img": "..."}}
    is_stats: bool = False
    stats_data: dict = field(default_factory=dict)
    insufficient_data: bool = False

    def is_outdated(self, current_patch: str) -> bool:
        """Sprawdza czy build jest ze starszego patcha."""
        return self.patch != current_patch

@dataclass
class GodData:
    god_name: str
    current_patch: str
    builds: list[SmiteBuild] = field(default_factory=list)
    error: str = None

    def get_best_match(self, role: str = "mid", want_aspect: bool = False):
        """Logika wybierania najlepszego buildu z listy."""
        # Filtrujemy tylko najnowszy patch
        valid = [b for b in self.builds if b.patch == self.current_patch]
        if not valid: return None

        # Szukamy dopasowania roli i aspektu
        matches = [b for b in valid if b.is_aspect == want_aspect and any(role.lower() == r.lower() for r in b.roles)]
        
        return matches[0] if matches else valid[0]
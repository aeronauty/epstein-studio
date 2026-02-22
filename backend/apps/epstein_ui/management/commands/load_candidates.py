"""Load curated candidate name lists into CandidateList for redaction matching.

Sources:
  - Epstein Exposed public API (epsteinexposed.com) — 1,500+ persons of interest
  - Epstein's Black Book (epsteinsblackbook.com) — ~2,000 contacts
  - Manually curated lists for key locations, organisations, and legal terms
"""
import json
import os
import re
import time
import subprocess
import tempfile

from django.core.management.base import BaseCommand
from apps.epstein_ui.models import CandidateList


# --------------------------------------------------------------------------
# Manually curated lists (always loaded regardless of --fetch)
# --------------------------------------------------------------------------
KEY_LOCATIONS = [
    "Little St. James", "Zorro Ranch", "Palm Beach", "New York",
    "Manhattan", "East 71st Street", "Upper East Side", "Paris",
    "London", "New Mexico", "US Virgin Islands", "St. Thomas",
    "Mar-a-Lago", "Ohio", "Columbus", "Metropolitan Correctional Center",
    "Teterboro", "Santa Fe", "El Brillo Way", "Luton",
]

KEY_ORGANISATIONS = [
    "JP Morgan", "JPMorgan Chase", "Deutsche Bank", "J. Epstein & Co",
    "Southern Trust", "Butterfly Trust", "Gratitude America",
    "COUQ Foundation", "Epstein Foundation", "MC2 Model Management",
    "Victoria's Secret", "The Limited", "L Brands",
    "Harvard University", "MIT", "MIT Media Lab",
    "FBI", "SDNY", "Southern District of New York",
    "Palm Beach Police", "US Attorney", "Department of Justice",
    "Wexner Foundation", "Ohio State University",
]


def _split_joint_name(name):
    """Split 'Nick & Sarah Allan' into ['Nick Allan', 'Sarah Allan']."""
    skip_words = ["castle", "college", "hotel", "club", "office",
                  "airport", "airline", "leasing", "transfer", "service",
                  "hotline", "aero", "air ", "fax", "tel "]
    if any(w in name.lower() for w in skip_words):
        return []
    m = re.match(r"^(\w+)\s*&\s*(\w+)\s+(.+)$", name)
    if m:
        return [f"{m.group(1)} {m.group(3)}", f"{m.group(2)} {m.group(3)}"]
    return [name]


def _is_plausible_name(s):
    """Filter out non-name entries (phone numbers, codes, addresses)."""
    s = s.strip()
    if len(s) < 3 or len(s) > 60:
        return False
    if re.match(r"^\d", s):
        return False
    if any(c in s for c in ["@", "#", "http", "www.", "(", ")"]):
        return False
    parts = s.split()
    if len(parts) < 2:
        return False
    return True


class Command(BaseCommand):
    help = "Load candidate lists from external sources and curated data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear", action="store_true",
            help="Remove existing candidate lists before loading",
        )
        parser.add_argument(
            "--fetch", action="store_true",
            help="Fetch latest data from epsteinexposed.com API and black book",
        )

    def _fetch_api_persons(self):
        """Fetch persons from Epstein Exposed public API via curl."""
        all_persons = []
        for page in range(1, 20):
            self.stdout.write(f"  API page {page}...")
            result = subprocess.run(
                ["curl", "-s", f"https://epsteinexposed.com/api/v1/persons?per_page=100&page={page}"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                self.stderr.write(f"  curl failed on page {page}")
                break
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                self.stderr.write(f"  JSON parse failed on page {page}")
                break
            batch = data.get("data", [])
            if not batch:
                break
            all_persons.extend(batch)
            total = data.get("meta", {}).get("total", "?")
            self.stdout.write(f"  got {len(batch)}, total so far {len(all_persons)}/{total}")
            if len(all_persons) >= int(total):
                break
            time.sleep(1.1)
        return all_persons

    def _fetch_black_book(self):
        """Fetch black book names from epsteinsblackbook.com."""
        self.stdout.write("  Fetching black book page...")
        result = subprocess.run(
            ["curl", "-s", "https://epsteinsblackbook.com/all-names"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            self.stderr.write("  curl failed for black book")
            return []
        import html as html_mod
        names = set()
        # Names are in <h2><a href=...>Name</a></h2> tags
        for m in re.finditer(r"<h2[^>]*>(.*?)</h2>", result.stdout):
            inner = m.group(1)
            # Strip anchor tags and decode HTML entities
            raw = re.sub(r"<[^>]+>", "", inner).strip()
            raw = html_mod.unescape(raw)
            for n in _split_joint_name(raw):
                if _is_plausible_name(n):
                    names.add(n)
        self.stdout.write(f"  Parsed {len(names)} names from black book HTML")
        return sorted(names)

    def _load_cached(self):
        """Load from previously fetched cache files, if they exist."""
        cache_dir = os.path.join(tempfile.gettempdir(), "epstein_candidates")
        api_path = os.path.join(cache_dir, "api_persons.json")
        bb_path = os.path.join(cache_dir, "blackbook.json")
        if not os.path.exists(api_path) or not os.path.exists(bb_path):
            return None, None
        with open(api_path) as f:
            api = json.load(f)
        with open(bb_path) as f:
            bb = json.load(f)
        return api, bb

    def _save_person_metadata(self, persons):
        """Build a name → metadata lookup and save to the Django app's data dir."""
        from django.conf import settings

        data_dir = os.path.join(
            settings.BASE_DIR, "apps", "epstein_ui", "static", "epstein_ui"
        )
        os.makedirs(data_dir, exist_ok=True)

        lookup = {}
        for p in persons:
            name = p.get("name", "")
            if not name:
                continue
            lookup[name] = {
                "category": p.get("category", ""),
                "bio": p.get("shortBio", ""),
                "flights": p.get("flightCount", 0),
                "documents": p.get("documentCount", 0),
                "connections": p.get("connectionCount", 0),
                "aliases": p.get("aliases", []),
                "slug": p.get("slug", ""),
            }

        out_path = os.path.join(data_dir, "person_metadata.json")
        with open(out_path, "w") as f:
            json.dump(lookup, f, separators=(",", ":"))
        self.stdout.write(f"  Saved metadata for {len(lookup)} persons to {out_path}")

    def _save_cache(self, api_cats, bb_names):
        cache_dir = os.path.join(tempfile.gettempdir(), "epstein_candidates")
        os.makedirs(cache_dir, exist_ok=True)
        with open(os.path.join(cache_dir, "api_persons.json"), "w") as f:
            json.dump(api_cats, f)
        with open(os.path.join(cache_dir, "blackbook.json"), "w") as f:
            json.dump(bb_names, f)

    def handle(self, *args, **options):
        if options["clear"]:
            n, _ = CandidateList.objects.all().delete()
            self.stdout.write(f"Cleared {n} existing candidate list record(s)")

        api_cats = None
        bb_names = None

        if options["fetch"]:
            self.stdout.write("Fetching from Epstein Exposed API...")
            persons = self._fetch_api_persons()
            api_cats = {}
            for p in persons:
                cat = p.get("category", "other") or "other"
                api_cats.setdefault(cat, []).append(p["name"])

            self._save_person_metadata(persons)

            self.stdout.write("Fetching Black Book contacts...")
            bb_names = self._fetch_black_book()

            self._save_cache(api_cats, bb_names)
            self.stdout.write(self.style.SUCCESS(
                f"Fetched {len(persons)} API persons + {len(bb_names)} black book names"
            ))
        else:
            api_cats, bb_names = self._load_cached()
            if api_cats is None:
                self.stdout.write(
                    "No cached data found. Using pre-fetched data from /tmp if available, "
                    "otherwise run with --fetch first."
                )
                api_path = "/tmp/epstein_persons_all.json"
                if os.path.exists(api_path):
                    with open(api_path) as f:
                        api_cats = json.load(f)
                bb_path = "/tmp/epstein_blackbook_raw.txt"
                if os.path.exists(bb_path):
                    with open(bb_path) as f:
                        raw_lines = [l.strip() for l in f if l.strip()]
                    bb_names = []
                    for raw in raw_lines:
                        for n in _split_joint_name(raw):
                            if _is_plausible_name(n):
                                bb_names.append(n)
                    bb_names = sorted(set(bb_names))

        # ------------------------------------------------------------------
        # Build the candidate lists
        # ------------------------------------------------------------------
        lists_to_save = {}

        # API categories → candidate lists
        CATEGORY_MAP = {
            "politician":             "Politicians & Government",
            "business":               "Business & Finance",
            "celebrity":              "Celebrities & Entertainment",
            "royalty":                 "Royalty",
            "academic":               "Academics & Scientists",
            "military-intelligence":  "Military & Intelligence",
            "socialite":              "Socialites",
            "legal":                  "Legal Professionals",
            "associate":              "Epstein Associates",
            "other":                  "Other Persons of Interest",
        }

        if api_cats:
            for api_cat, list_name in CATEGORY_MAP.items():
                names = api_cats.get(api_cat, [])
                if names:
                    lists_to_save[list_name] = sorted(set(names))

        # Black book contacts (exclude those already in API lists)
        if bb_names:
            api_all = set()
            if api_cats:
                for names in api_cats.values():
                    api_all.update(names)
            bb_only = [n for n in bb_names if n not in api_all]
            if bb_only:
                lists_to_save["Black Book Contacts"] = sorted(set(bb_only))

        # Always-loaded curated lists
        lists_to_save["Key Locations"] = KEY_LOCATIONS
        lists_to_save["Key Organisations"] = KEY_ORGANISATIONS

        # ------------------------------------------------------------------
        # Save to database
        # ------------------------------------------------------------------
        total = 0
        for name, entries in sorted(lists_to_save.items()):
            obj, created = CandidateList.objects.update_or_create(
                name=name, defaults={"entries": entries},
            )
            verb = "Created" if created else "Updated"
            self.stdout.write(f"  {verb} '{name}' — {len(entries)} candidates")
            total += len(entries)

        self.stdout.write(self.style.SUCCESS(
            f"Done. {len(lists_to_save)} lists, {total} total candidates loaded."
        ))

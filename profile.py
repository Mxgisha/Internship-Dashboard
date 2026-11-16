"""The matcher's vocabulary and the user's configuration.

Non-personal taxonomy lives here: US states, country words, city aliases.
Everything that describes the person or their preferences — weights, seasons,
company notes, evidence gaps, biography — lives in `config.toml`, loaded once
at import. Edit the config, not this file.

The loader raises `config.ConfigError` if the file is missing or malformed; the
entry points turn that into a one-line message instead of a traceback.
"""
import config

# ---------------------------------------------------------------------------
# Location vocabulary. This is the same for every user.
# ---------------------------------------------------------------------------

# US state and territory codes, used only in a "City, XX" position.
US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC","PR",
}

# Full state names are unambiguous in this feed and must be checked before
# country words: "New Mexico" contains "Mexico", "Indiana" contains "India".
US_STATE_NAMES = (
    "alabama","alaska","arizona","arkansas","california","colorado","connecticut",
    "delaware","florida","georgia","hawaii","idaho","illinois","indiana","iowa",
    "kansas","kentucky","louisiana","maine","maryland","massachusetts","michigan",
    "minnesota","mississippi","missouri","montana","nebraska","nevada",
    "new hampshire","new jersey","new mexico","new york","north carolina",
    "north dakota","ohio","oklahoma","oregon","pennsylvania","rhode island",
    "south carolina","south dakota","tennessee","texas","utah","vermont",
    "virginia","washington","west virginia","wisconsin","wyoming",
    "district of columbia","puerto rico",
)

# If any of these appear as whole words, the posting is not US-based.
NON_US_WORDS = {
    "canada","united kingdom","uk","england","scotland","wales","northern ireland",
    "ireland","germany","france","india","singapore","australia","china","japan",
    "israel","netherlands","switzerland","brazil","mexico","poland","romania",
    "spain","sweden","taiwan","korea","hong kong","belgium","denmark","norway",
    "finland","portugal","italy","austria","czech","hungary","turkey",
    "south africa","nigeria","kenya","russia","ukraine","vietnam","philippines",
    "indonesia","malaysia","thailand","uae","dubai","qatar","saudi","colombia",
    "argentina","chile","peru","egypt","morocco","pakistan","bangladesh",
    "sri lanka","new zealand","luxembourg","estonia","lithuania","latvia",
    "bulgaria","croatia","serbia","slovakia","slovenia","greece","iceland",
    "monaco","cayman","bermuda",
    "ontario","quebec","british columbia","alberta","manitoba","saskatchewan",
    "nova scotia","new brunswick","newfoundland",
    "europe","emea","apac","latam","middle east","asia","africa",
}

# Canadian province codes, again only after a comma. Kept separate from
# NON_US_WORDS so a "City, XX" code can be read in context.
CANADIAN_PROVINCES = {"ON","BC","QC","AB","MB","SK","NS","NB","NL","PE","YT","NT","NU"}

# Bare city shorthand that means a US location without a state code.
US_CITY_WORDS = {
    "sf","nyc","la","boston","cambridge","somerville","medford","waltham",
    "lexington","bedford","natick","burlington","bay area","silicon valley",
    "san francisco","los angeles","san jose","santa clara","sunnyvale",
    "mountain view","palo alto","menlo park","redwood city","seattle","redmond",
    "bellevue","austin","denver","chicago","atlanta","new york","philadelphia",
    "pittsburgh","houston","dallas","raleigh","durham","ann arbor","madison",
    "minneapolis","salt lake city","portland","miami","orlando","san diego",
    "irvine","indianapolis","remote",
}

# Words that mean the US when no country/province word is present. "US" and
# "U.S." are normalised to "us" before matching.
US_COUNTRY_WORDS = ("united states","united states of america","usa","us")

# ---------------------------------------------------------------------------
# User configuration. Loaded once; see config.example.toml for every key.
# ---------------------------------------------------------------------------
_CFG = config.load()
_SCORING = _CFG["scoring"]

SEASONS = {str(k): int(v) for k, v in _SCORING["seasons"].items()}
CATEGORIES = {str(k): int(v) for k, v in _SCORING["categories"].items()}
TITLE_KEYWORDS = {str(k): int(v) for k, v in _SCORING["title_keywords"].items()}
TITLE_PENALTIES = {str(k): int(v) for k, v in _SCORING["title_penalties"].items()}
ACCEPTED_DEGREES = [d.lower() for d in _SCORING.get("accepted_degrees", [])]
MIN_FIT = int(_SCORING["min_fit"])
MAX_JOBS = int(_SCORING["max_jobs"])
PREFERRED_LOCATIONS = [str(place) for place in
                       _CFG.get("locations", {}).get("preferred", [])]

IDENTITY = dict(_CFG["identity"])
LETTER_TEXT = dict(_CFG["letters"])

_COMPANIES = _CFG.get("companies", {})
COMPANY_PROFILES = {}
COMPANY_ALIASES = {}
for _name, _entry in _COMPANIES.items():
    if isinstance(_entry, str):
        COMPANY_PROFILES[_name] = _entry
        continue
    COMPANY_PROFILES[_name] = _entry.get("summary", "")
    for _alias in _entry.get("aliases", []):
        COMPANY_ALIASES[_alias] = _name

GAP_WARNINGS = dict(_CFG.get("gaps", {}))


def canonical_company(company):
    """Resolve a feed name through COMPANY_ALIASES, case-insensitively."""
    name = (company or "").strip()
    for alias, target in COMPANY_ALIASES.items():
        if name.casefold() == alias.casefold():
            return target
    return name


def company_summary(company, active_roles):
    """Curated note when one exists, otherwise an honest, editable stub."""
    known = COMPANY_PROFILES.get(canonical_company(company)) or COMPANY_PROFILES.get(company)
    if known:
        return known
    roles = (f"{active_roles} active role(s) in this feed." if active_roles
             else "No active roles in this feed.")
    return (f"No profile on file for {company}. {roles} "
            f"Edit the company summary on the job page.")

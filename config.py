"""Load and validate config.toml — the only file that holds personal data.

The repository ships `config.example.toml`; the working copy is `config.toml`,
which is gitignored. `JOBHUNT_CONFIG` overrides the path (the tests use it).
"""
import os
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(HERE, "config.toml")
EXAMPLE_PATH = os.path.join(HERE, "config.example.toml")

IDENTITY_KEYS = ("name", "school", "degree", "year", "gpa", "email", "phone")
LETTER_KEYS = ("research", "building", "communicating", "life")
SCORE_KEYS = ("seasons", "categories", "title_keywords", "title_penalties")


class ConfigError(RuntimeError):
    """A missing or invalid configuration, with a file/key hint."""


def path_from_env():
    return os.path.abspath(os.path.expanduser(
        os.environ.get("JOBHUNT_CONFIG") or DEFAULT_PATH))


def load(path=None):
    """Read, parse, validate, and return the configuration dict."""
    config_path = os.path.abspath(os.path.expanduser(path)) if path else path_from_env()
    if not os.path.exists(config_path):
        raise ConfigError(
            f"no configuration at {config_path}.\n"
            f"    cp {os.path.basename(EXAMPLE_PATH)} config.toml   # then edit it")
    try:
        with open(config_path, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{config_path}: invalid TOML: {exc}") from exc
    return validate(data, config_path)


def _fail(path, message):
    raise ConfigError(f"{path}: {message}")


def _table(data, key, path, required=True):
    value = data.get(key)
    if value is None and not required:
        return {}
    if not isinstance(value, dict):
        _fail(path, f"missing or invalid [{key}] table")
    return value


def _string(value, path, key):
    if not isinstance(value, str) or not value.strip():
        _fail(path, f"{key} must be a non-empty string")
    return value


def _string_list(value, path, key):
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        _fail(path, f"{key} must be a list of non-empty strings")
    return value


def _weight_table(data, key, path):
    table = data.get(key)
    if not isinstance(table, dict):
        _fail(path, f"missing or invalid [scoring.{key}] table")
    for name, weight in table.items():
        if not isinstance(name, str) or not name:
            _fail(path, f"[scoring.{key}] has an empty key")
        if isinstance(weight, bool) or not isinstance(weight, int):
            _fail(path, f"[scoring.{key}].{name} must be an integer")
    return table


def validate(data, path="config"):
    """Return `data` after checking the shape the app relies on."""
    if not isinstance(data, dict):
        _fail(path, "the file must contain TOML tables")

    scoring = _table(data, "scoring", path)
    for key in ("min_fit", "max_jobs"):
        value = scoring.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            _fail(path, f"[scoring].{key} must be an integer")
    if not 0 <= scoring["min_fit"] <= 100:
        _fail(path, "[scoring].min_fit must be between 0 and 100")
    if scoring["max_jobs"] < 0:
        _fail(path, "[scoring].max_jobs cannot be negative")
    for key in SCORE_KEYS:
        _weight_table(scoring, key, path)
    _string_list(scoring.get("accepted_degrees", []), path, "[scoring].accepted_degrees")

    locations = _table(data, "locations", path, required=False)
    _string_list(locations.get("preferred", []), path, "[locations].preferred")

    identity = _table(data, "identity", path)
    for key in IDENTITY_KEYS:
        _string(identity.get(key), path, f"[identity].{key}")

    letters = _table(data, "letters", path)
    for key in LETTER_KEYS:
        _string(letters.get(key), path, f"[letters].{key}")

    companies = _table(data, "companies", path, required=False)
    for name, entry in companies.items():
        if isinstance(entry, str):
            if not entry.strip():
                _fail(path, f"[companies.{name}] summary cannot be empty")
            continue
        if not isinstance(entry, dict):
            _fail(path, f"[companies.{name}] must be a table or a string")
        if not isinstance(entry.get("summary", ""), str):
            _fail(path, f"[companies.{name}].summary must be a string")
        if "aliases" in entry:
            _string_list(entry["aliases"], path, f"[companies.{name}].aliases")

    gaps = _table(data, "gaps", path, required=False)
    for key, value in gaps.items():
        if not isinstance(value, str):
            _fail(path, f"[gaps].{key} must be a string")

    return data

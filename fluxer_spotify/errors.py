"""Exceptions + language selection. Messages are bilingual (de/en) and shown in the selected language."""
import os

LANGS = ("de", "en")
_lang = None  # "de" / "en" once known; None = undetermined (before config is loaded): show both languages


def set_lang(lang):
    global _lang
    _lang = lang if lang in LANGS else None


def get_lang():
    return _lang


def detect_lang():
    """OS UI language: anything starting with 'de' -> 'de', everything else (or undetectable) -> 'en'."""
    code = ""
    try:
        import locale
        if os.name == "nt":
            import ctypes
            code = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")
        if not code:
            for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
                code = os.environ.get(var, "")
                if code:
                    break
            code = code or locale.getlocale()[0] or ""
    except Exception:  # never let detection break startup
        code = ""
    return "de" if code.lower().startswith("de") else "en"


def bi(de: str, en: str, sep: str = "\n") -> str:
    """The selected language; both (joined by `sep`) while the language is still undetermined."""
    return de if _lang == "de" else en if _lang == "en" else f"{de}{sep}{en}"


def blog(de: str, en: str, *args) -> str:
    """bi() for log lines with %-arguments: formats each language first, so the 'both' fallback never doubles the placeholders."""
    return bi(de % args, en % args, " / ")


def tr(de: str, en: str) -> str:
    """Always exactly one language (texts sent to a service, e.g. status lines): German unless English is selected."""
    return en if _lang == "en" else de


class Fatal(Exception):
    """Retrying cannot fix this; the user has to act."""


class AuthError(Fatal):
    """A service rejected our credentials (401 / invalid_grant)."""


class LoginError(Fatal):
    """Interactive login failed."""

"""Keyword rules, reply templates and lightweight language detection (all driven by rules.yaml)."""

from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

UNKNOWN_LANGUAGE = "other"

# Latin letters that do not decompose under NFD, folded to their base letter.
_FOLD = str.maketrans(
    {
        "\N{LATIN SMALL LETTER D WITH STROKE}": "d",
        "\N{LATIN SMALL LETTER L WITH STROKE}": "l",
        "\N{LATIN SMALL LETTER O WITH STROKE}": "o",
        "\N{LATIN SMALL LETTER SHARP S}": "ss",
    }
)


def lower(text: str) -> str:
    """NFC, lowercase, collapse whitespace."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text).lower()).strip()


def normalize(text: str) -> str:
    """Lowercase and strip diacritics: 'Café  CRÈME' -> 'cafe creme'."""
    text = unicodedata.normalize("NFD", text.lower().translate(_FOLD))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


def _compile(keyword: str) -> re.Pattern[str]:
    # Whole-word match (\w covers accented letters), so "ib" does not match inside "tribe".
    return re.compile(rf"(?<!\w){re.escape(keyword)}(?!\w)")


class Keywords:
    """Accent-aware keyword matcher.

    A comment typed *with* diacritics is matched against the accented keywords, so a
    keyword never matches a different word that only shares its base letters. A comment
    typed *without* diacritics is matched after stripping them from the keywords too.
    """

    def __init__(self, keywords: list[str]):
        self.accented = [_compile(lower(k)) for k in keywords]
        self.stripped = [_compile(normalize(k)) for k in keywords]

    def search(self, text: str) -> bool:
        low, plain = lower(text), normalize(text)
        if low != plain:  # the comment contains diacritics
            return any(p.search(low) for p in self.accented)
        return any(p.search(plain) for p in self.stripped)


@dataclass
class Language:
    code: str
    words: set[str] = field(default_factory=set)
    chars: str = ""
    name_fallback: str = ""

    def word_score(self, text: str) -> int:
        return sum(w in self.words for w in re.findall(r"\w+", normalize(text)))

    def char_score(self, text: str) -> int:
        return sum(c in self.chars for c in lower(text)) if self.chars else 0


class LanguageDetector:
    """Scores each configured language by hint words and characteristic characters.

    Good enough to pick a reply template; the AI path detects language on its own.
    """

    def __init__(self, languages: list[Language], default: str):
        self.languages = languages
        self.default = default

    def detect(self, text: str) -> str:
        letters = [c for c in text if c.isalpha()]
        if not letters:
            return self.default
        non_latin = sum("LATIN" not in unicodedata.name(c, "") for c in letters)
        mostly_non_latin = non_latin > len(letters) / 2
        scores = {}
        for lang in self.languages:
            chars = lang.char_score(text)
            # Text mostly in another script only counts for languages that claim its characters.
            if mostly_non_latin and not chars:
                continue
            scores[lang.code] = chars + lang.word_score(text)
        best = max(scores.values(), default=0)
        if best == 0:
            return UNKNOWN_LANGUAGE if mostly_non_latin else self.default
        if scores.get(self.default) == best:
            return self.default
        return next(code for code, score in scores.items() if score == best)

    def name_fallback(self, code: str) -> str:
        for lang in self.languages:
            if lang.code == code:
                return lang.name_fallback
        return ""


@dataclass
class Reply:
    public: str | None
    private: str | None
    source: str  # rule name, "ai" or "default"


Templates = dict[str, list[str]]  # language code -> candidate texts; "*" = any language


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    return [value] if isinstance(value, str) else [str(v) for v in value]  # type: ignore[union-attr]


def _templates(value: object) -> Templates:
    """Accept a single string, a list of strings, or a mapping of language -> string(s)."""
    if isinstance(value, dict):
        return {str(lang): _as_list(v) for lang, v in value.items()}
    return {"*": _as_list(value)} if value is not None else {}


def _for_language(templates: Templates, lang: str) -> list[str] | None:
    return templates.get(lang, templates.get("*"))


@dataclass
class Rule:
    name: str
    keywords: Keywords
    public: Templates
    private: Templates


class RuleSet:
    def __init__(
        self,
        rules: list[Rule],
        default: tuple[Templates, Templates],
        ignore: Keywords,
        detector: LanguageDetector,
    ):
        self.rules = rules
        self.default = default
        self.ignore = ignore
        self.detector = detector

    @classmethod
    def load(cls, path: str | Path) -> RuleSet:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        rules = [
            Rule(
                name=r["name"],
                keywords=Keywords(_as_list(r["keywords"])),
                public=_templates(r.get("public_reply")),
                private=_templates(r.get("private_reply")),
            )
            for r in data.get("rules", [])
        ]
        d = data.get("default") or {}
        default = (_templates(d.get("public_reply")), _templates(d.get("private_reply")))
        languages = [
            Language(
                code=str(code),
                words={normalize(w) for w in _as_list(cfg.get("words"))},
                chars=lower(cfg.get("chars", "")),
                name_fallback=cfg.get("name_fallback", ""),
            )
            for code, cfg in (data.get("languages") or {}).items()
        ]
        detector = LanguageDetector(languages, str(data.get("default_language", "en")))
        return cls(rules, default, Keywords(_as_list(data.get("ignore_keywords"))), detector)

    def detect_language(self, text: str) -> str:
        return self.detector.detect(text)

    def should_ignore(self, text: str) -> bool:
        return self.ignore.search(text)

    def match(self, text: str, name: str = "") -> Reply | None:
        """First matching rule that has templates for the comment's language.

        Returns None when nothing matches, or when the matching rule has no template for
        that language, so the AI can answer in the right language instead.
        """
        lang = self.detect_language(text)
        for rule in self.rules:
            if not rule.keywords.search(text):
                continue
            public = _for_language(rule.public, lang)
            private = _for_language(rule.private, lang)
            if public is None and private is None:
                return None
            return self._reply(public, private, name, lang, rule.name)
        return None

    def default_reply(self, text: str, name: str = "") -> Reply | None:
        lang = self.detect_language(text)
        public, private = (_for_language(t, lang) for t in self.default)
        if not public and not private:
            return None
        return self._reply(public, private, name, lang, "default")

    def _reply(
        self, public: list[str] | None, private: list[str] | None, name: str, lang: str, src: str
    ) -> Reply:
        name = name or self.detector.name_fallback(lang)
        return Reply(_fill(_pick(public), name), _fill(_pick(private), name), src)


def _pick(options: list[str] | None) -> str | None:
    # Several templates -> pick one at random so replies are not identical (spam signal).
    return random.choice(options) if options else None


def _fill(template: str | None, name: str) -> str | None:
    if template is None:
        return None
    return template.replace("{name}", name).strip()

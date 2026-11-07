import pytest

from fb_auto_reply.rules import Keywords, RuleSet, normalize


def test_normalize():
    assert normalize("Café  CRÈME Straße") == "cafe creme strasse"


def test_keywords_are_whole_word():
    kw = Keywords(["dm"])
    assert kw.search("pls DM me")
    assert not kw.search("admin")


def test_keywords_accent_aware():
    kw = Keywords(["pâté"])
    assert kw.search("where is the pate")  # typed without accents: matches
    assert kw.search("du PÂTÉ maison")
    # Typed with accents: "pate" is a different word, so no match.
    assert not kw.search("j'ai mangé une pate")


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("How much does it cost?", "en"),
        ("is this free?", "en"),
        ("¿Cuánto cuesta?", "es"),
        ("hola, cuanto cuesta el plan", "es"),
        ("Cool <3", "en"),  # no hints -> default language
        ("👍👍", "en"),
        ("ราคาเท่าไหร่", "other"),
        ("这个多少钱", "other"),
    ],
)
def test_detect_language(rules: RuleSet, text: str, lang: str):
    assert rules.detect_language(text) == lang


def test_match_rules(rules: RuleSet):
    assert rules.match("how much is it?", "Jane").source == "pricing"
    assert rules.match("pls DM me").source == "dm_request"
    assert rules.match("admin here") is None
    assert rules.match("love it") is None
    assert rules.should_ignore("total SCAM")
    assert not rules.should_ignore("scampi recipe")


def test_reply_in_comment_language(rules: RuleSet):
    en = rules.match("How much does it cost?", "Jane")
    es = rules.match("¿Cuánto cuesta?", "Jane")
    assert en.source == es.source == "pricing"
    assert "free" in en.public and "gratis" in es.public
    assert en.private.startswith("Hi Jane") and es.private.startswith("¡Hola Jane")


def test_name_fallback(rules: RuleSet):
    assert rules.match("sign up link?").public.startswith("Hi there")
    assert "amigo" in rules.match("quiero el enlace").public


def test_unknown_language_goes_to_ai(rules: RuleSet):
    assert rules.match("price ราคาเท่าไหร่") is None


def test_default_reply(rules: RuleSet):
    assert rules.default_reply("ok thanks", "Jane").public.startswith("Thanks")
    assert rules.default_reply("¡gracias!", "Jane").public.startswith("¡Gracias")

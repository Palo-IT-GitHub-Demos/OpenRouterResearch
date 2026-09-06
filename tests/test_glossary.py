"""Tests for the glossary shared by the live and static dashboards."""

from __future__ import annotations

from dashboard.glossary import GLOSSARY_INTRO, GLOSSARY_TERMS, glossary_html, glossary_markdown


class TestGlossaryContent:
    def test_defines_every_key_acronym(self) -> None:
        terms = " ".join(term for term, _ in GLOSSARY_TERMS)
        for acronym in ("RSI", "TCO", "CER", "ZDR", "OWASP"):
            assert acronym in terms

    def test_documents_the_columns_a_reader_cannot_guess(self) -> None:
        terms = " ".join(term for term, _ in GLOSSARY_TERMS)
        for column in (
            "probe_error_rate",
            "output_format_compliance",
            "quality_excluded_prompt_count",
            "quality_pass_rate",
            "leak_count",
        ):
            assert column in terms

    def test_is_written_in_english(self) -> None:
        text = GLOSSARY_INTRO + " ".join(f"{term} {definition}" for term, definition in GLOSSARY_TERMS)
        assert not set(text) & set("éèêàçùôûîï")


class TestGlossaryRendering:
    def test_html_escapes_before_re_enabling_inline_markup(self) -> None:
        html = glossary_html("Beware of <script>alert(1)</script> & co.")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "&amp; co." in html

    def test_html_renders_inline_code_bold_and_links(self) -> None:
        html = glossary_html(GLOSSARY_INTRO)
        assert "<code>gen-e2-eval</code>" in html
        assert "<strong>" in html
        assert '<a href="https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/">' in html

    def test_html_emits_one_definition_per_term(self) -> None:
        html = glossary_html(GLOSSARY_INTRO)
        assert html.count("<dt>") == len(GLOSSARY_TERMS)
        assert html.count("<dd>") == len(GLOSSARY_TERMS)

    def test_markdown_covers_the_same_terms(self) -> None:
        markdown = glossary_markdown()
        for term, _ in GLOSSARY_TERMS:
            assert term in markdown

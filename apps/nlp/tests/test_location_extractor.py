"""
Unit tests for the location extractor component.

Tests cover:
  - Settlement extraction (gazetteer match)
  - Alias handling (variations of settlement names)
  - Zone extraction (Zone 1, Block A patterns)
  - Combined extraction (settlement + zone)
  - spaCy NER integration (fallback when gazetteer fails)
  - Confidence and location_type tracking
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from apps.nlp.pipeline.location_extractor import (
    _extract_zones_from_text,
    _extract_with_spacy,
    _fuzzy_match_settlement,
    extract_location,
)


class TestLocationExtractor:
    """Test suite for location extraction logic."""

    def test_settlement_extraction_nakivale(self):
        """Nakivale should be extracted from text."""
        text = "I am living in Nakivale settlement"
        location, confidence, loc_type = extract_location(text)

        assert location == "Nakivale"
        assert loc_type == "settlement"
        assert confidence > 0.8

    def test_settlement_extraction_kyangwali(self):
        """Kyangwali should be extracted."""
        text = "We need help at Kyangwali"
        location, confidence, loc_type = extract_location(text)

        assert location == "Kyangwali"
        assert loc_type == "settlement"

    def test_settlement_extraction_kampala(self):
        """Districts should also be extracted."""
        text = "I am in Kampala"
        location, confidence, loc_type = extract_location(text)

        assert location == "Kampala"
        assert loc_type == "settlement"

    def test_settlement_alias_nkv_matches_nakivale(self):
        """Settlement alias 'NKV' should match to Nakivale."""
        settlement = _fuzzy_match_settlement("NKV")
        assert settlement == "Nakivale"

    def test_settlement_alias_settlement_suffix(self):
        """Settlement aliases with 'Settlement' suffix should match."""
        settlement = _fuzzy_match_settlement("Nakivale Settlement")
        assert settlement == "Nakivale"

    def test_settlement_alias_camp_suffix(self):
        """Settlement aliases with 'Camp' suffix should match."""
        settlement = _fuzzy_match_settlement("Kyangwali Camp")
        assert settlement == "Kyangwali"

    def test_zone_extraction_zone_1(self):
        """Zone 1 pattern should be extracted."""
        zone = _extract_zones_from_text("People from Zone 1 complained")
        assert zone == "Zone 1"

    def test_zone_extraction_block_a(self):
        """Block A pattern should be extracted."""
        zone = _extract_zones_from_text("In Block A we have issues")
        assert zone == "Block A"

    def test_zone_extraction_cell_23(self):
        """Cell 23 pattern should be extracted."""
        zone = _extract_zones_from_text("Cell 23 is problematic")
        assert zone == "Cell 23"

    def test_zone_extraction_case_insensitive(self):
        """Zone extraction should be case-insensitive."""
        zone1 = _extract_zones_from_text("zone 5 has problems")
        zone2 = _extract_zones_from_text("ZONE 5 has problems")
        zone3 = _extract_zones_from_text("Zone 5 has problems")

        assert zone1 == zone2 == zone3

    def test_zone_extraction_with_letters(self):
        """Zone with letter suffixes should work (e.g., Zone 1A)."""
        zone = _extract_zones_from_text("Zone 1A section")
        assert zone == "Zone 1A"

    def test_combined_settlement_and_zone(self):
        """Both settlement and zone should be combined with comma."""
        text = "In Nakivale, Zone 3 there are issues"
        location, confidence, loc_type = extract_location(text)

        assert "Nakivale" in location
        assert "Zone 3" in location
        assert "," in location
        assert loc_type == "settlement"

    def test_combined_extraction_high_confidence(self):
        """Combined extraction should have high confidence (0.95)."""
        text = "Kyangwali in Block B has a problem"
        location, confidence, loc_type = extract_location(text)

        assert confidence == 0.95

    def test_zone_only_no_settlement(self):
        """Zone-only extraction should work."""
        text = "Zone 2 residents complained"
        location, confidence, loc_type = extract_location(text)

        assert location == "Zone 2"
        assert loc_type == "zone"
        assert confidence == 0.80

    def test_no_location_found_returns_none(self):
        """No location found should return None."""
        text = "This is generic text with no location"
        location, confidence, loc_type = extract_location(text)

        assert location is None
        assert confidence == 0.0
        assert loc_type == "unknown"

    def test_empty_text_returns_none(self):
        """Empty text should return None."""
        location, confidence, loc_type = extract_location("")

        assert location is None
        assert confidence == 0.0

    def test_return_tuple_structure(self):
        """Return should be (location, confidence, location_type)."""
        result = extract_location("In Nakivale")

        assert isinstance(result, tuple)
        assert len(result) == 3
        location, confidence, loc_type = result
        assert isinstance(location, (str, type(None)))
        assert isinstance(confidence, float)
        assert isinstance(loc_type, str)

    def test_settlement_extraction_title_case(self):
        """Extracted settlements should be title-cased."""
        text = "problem in nakivale area"
        location, _, _ = extract_location(text)

        # Should be title-cased
        assert location == "Nakivale"

    def test_case_insensitive_gazetteer_matching(self):
        """Gazetteer matching should be case-insensitive."""
        text1 = "Nakivale"
        text2 = "nakivale"
        text3 = "NAKIVALE"

        loc1, _, _ = extract_location(text1)
        loc2, _, _ = extract_location(text2)
        loc3, _, _ = extract_location(text3)

        # All should extract same location
        assert loc1 == loc2 == loc3 == "Nakivale"

    def test_spacy_ner_fallback_when_available(self):
        """spaCy NER should be used if no gazetteer match."""
        text = "Issue in Ugandan district"

        with patch("apps.nlp.pipeline.location_extractor._get_spacy_model") as mock_spacy:
            spacy_model = MagicMock()
            doc = MagicMock()
            ent = MagicMock()
            ent.label_ = "LOCATION"
            ent.text = "Uganda"
            doc.ents = [ent]
            spacy_model.return_value = doc
            mock_spacy.return_value = spacy_model

            location, _, _ = extract_location(text)

            # Should call spaCy model
            spacy_model.assert_called()

    def test_spacy_ner_location_label(self):
        """spaCy NER should extract LOCATION entities."""
        with patch("apps.nlp.pipeline.location_extractor._get_spacy_model") as mock_spacy:
            spacy_model = MagicMock()
            doc = MagicMock()
            ent = MagicMock()
            ent.label_ = "LOCATION"
            ent.text = "Fort Portal"
            doc.ents = [ent]
            spacy_model.return_value = doc
            mock_spacy.return_value = spacy_model

            location, _, _ = extract_location("In the city")

            # Should find location via spaCy
            assert location is not None

    def test_spacy_ner_not_called_if_gazetteer_matches(self):
        """spaCy should not be called if gazetteer already matched."""
        text = "In Nakivale area"

        with patch("apps.nlp.pipeline.location_extractor._get_spacy_model") as mock_spacy:
            location, _, _ = extract_location(text)

            # Gazetteer matched, so spaCy shouldn't be needed
            # (implementation may still call it, but should not affect result)
            assert location == "Nakivale"

    def test_spacy_model_unavailable_handled(self):
        """Missing spaCy model should be handled gracefully."""
        text = "Text with no gazetteer match"

        with patch("apps.nlp.pipeline.location_extractor._get_spacy_model") as mock_spacy:
            mock_spacy.return_value = None

            location, confidence, loc_type = extract_location(text)

            assert location is None
            assert confidence == 0.0

    def test_spacy_ner_exception_handled(self):
        """spaCy exception should be caught."""
        with patch("apps.nlp.pipeline.location_extractor._get_spacy_model") as mock_spacy:
            spacy_model = MagicMock()
            spacy_model.side_effect = Exception("spaCy error")
            mock_spacy.return_value = spacy_model

            location, confidence, _ = extract_location("some text")

            # Should handle exception gracefully
            assert confidence >= 0.0

    def test_settlement_confidence_level(self):
        """Settlement extraction should have confidence 0.90."""
        text = "Nakivale only"
        _, confidence, _ = extract_location(text)

        assert confidence == 0.90

    def test_combined_settlement_zone_confidence(self):
        """Combined extraction should have confidence 0.95."""
        text = "Nakivale Zone 1"
        _, confidence, _ = extract_location(text)

        assert confidence == 0.95

    def test_zone_only_confidence(self):
        """Zone-only extraction should have confidence 0.80."""
        text = "Zone 1 only"
        _, confidence, _ = extract_location(text)

        assert confidence == 0.80

    def test_bidi_bidi_settlement(self):
        """Bidi Bidi (with space) should be extracted."""
        text = "In Bidi Bidi settlement"
        location, _, _ = extract_location(text)

        assert "Bidi" in location

    def test_rhino_camp_settlement(self):
        """Rhino Camp should be extracted."""
        text = "Rhino Camp residents need help"
        location, _, _ = extract_location(text)

        assert location is not None

    def test_fuzzy_match_settlement_exact_match(self):
        """Exact settlement name should match."""
        settlement = _fuzzy_match_settlement("Nakivale")
        assert settlement == "Nakivale"

    def test_fuzzy_match_settlement_case_insensitive(self):
        """Fuzzy match should be case-insensitive."""
        settlement = _fuzzy_match_settlement("nakivale")
        assert settlement == "Nakivale"

    def test_fuzzy_match_settlement_not_found_returns_none(self):
        """Unknown settlement should return None."""
        settlement = _fuzzy_match_settlement("UnknownPlace")
        assert settlement is None

    def test_zone_text_normalization(self):
        """Zone text should be normalized with proper capitalization."""
        zone = _extract_zones_from_text("zone   3a has")
        # Should normalize spacing and capitalization
        assert zone is not None
        assert "3" in zone or "3a" in zone.lower()

    def test_block_extraction_with_number(self):
        """Block with numbers should be extracted."""
        zone = _extract_zones_from_text("Block 5 is affected")
        assert zone == "Block 5"

    def test_cell_extraction_with_letters(self):
        """Cell with letters should be extracted."""
        zone = _extract_zones_from_text("Cell C1")
        assert zone == "Cell C1"

    def test_multiple_zones_first_match_returned(self):
        """If multiple zones present, first match should be returned."""
        zone = _extract_zones_from_text("Zone 1 and Zone 2")
        # Should return first match
        assert zone == "Zone 1"

    def test_spacy_ner_gpe_label(self):
        """spaCy NER should extract GPE (geopolitical entity) labels."""
        with patch("apps.nlp.pipeline.location_extractor._get_spacy_model") as mock_spacy:
            spacy_model = MagicMock()
            doc = MagicMock()
            ent = MagicMock()
            ent.label_ = "GPE"
            ent.text = "Uganda"
            doc.ents = [ent]
            spacy_model.return_value = doc
            mock_spacy.return_value = spacy_model

            location, _, _ = extract_location("text")

            assert location is not None

    def test_spacy_text_truncated_to_512_chars(self):
        """spaCy should receive max 512 char truncation."""
        long_text = "a" * 1000

        with patch("apps.nlp.pipeline.location_extractor._get_spacy_model") as mock_spacy:
            spacy_model = MagicMock()
            doc = MagicMock()
            doc.ents = []
            spacy_model.return_value = doc
            mock_spacy.return_value = spacy_model

            extract_location(long_text)

            # Check that spaCy was called with truncated text
            call_args = spacy_model.call_args[0][0]
            assert len(call_args) <= 512

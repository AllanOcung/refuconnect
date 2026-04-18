"""
apps/nlp/tests/test_location_extractor.py
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

SPACY_PATH = "apps.nlp.pipeline.location_extractor.spacy"


def _make_record(message_text_en=""):
    r = MagicMock()
    r.id = 1
    r.message_text_en = message_text_en
    r.message_text = message_text_en
    r.location = None
    return r


@patch(SPACY_PATH)
class LocationExtractorTests(SimpleTestCase):

    def _get_extractor(self, mock_spacy):
        from apps.nlp.pipeline import location_extractor
        location_extractor._NLP = None
        mock_nlp = MagicMock()
        mock_spacy.load.return_value = mock_nlp
        from apps.nlp.pipeline.location_extractor import LocationExtractor
        return LocationExtractor(), mock_nlp

    def test_settlement_name_found_in_text(self, mock_spacy):
        extractor, _ = self._get_extractor(mock_spacy)
        record = _make_record("I live in Nakivale settlement")
        extractor.process(record, {})
        self.assertEqual(record.location, "Nakivale")

    def test_settlement_alias_matched_correctly(self, mock_spacy):
        extractor, _ = self._get_extractor(mock_spacy)
        record = _make_record("I am from bidi bidi in Yumbe district")
        extractor.process(record, {})
        self.assertEqual(record.location, "Bidibidi")

    def test_zone_pattern_extracted_and_normalised(self, mock_spacy):
        extractor, _ = self._get_extractor(mock_spacy)
        record = _make_record("The clinic in Nakivale zone 3 is closed")
        extractor.process(record, {})
        self.assertEqual(record.location, "Nakivale, Zone 3")

    def test_no_location_found_leaves_none(self, mock_spacy):
        extractor, mock_nlp = self._get_extractor(mock_spacy)
        # spaCy returns no GPE entities
        doc = MagicMock()
        doc.ents = []
        mock_nlp.return_value = doc
        record = _make_record("The weather today is very hot outside")
        extractor.process(record, {})
        self.assertIsNone(record.location)

    def test_gps_coordinates_never_stored(self, mock_spacy):
        """
        Verify the extractor only stores settlement/zone strings,
        not numeric coordinate values.
        """
        extractor, _ = self._get_extractor(mock_spacy)
        record = _make_record("GPS 1.234 30.567 Nakivale zone A")
        extractor.process(record, {})
        location = record.location or ""
        # Must not contain raw coordinate-style numbers
        import re
        self.assertFalse(
            re.search(r"\d+\.\d{3,}", location),
            f"Coordinates found in location: {location}",
        )

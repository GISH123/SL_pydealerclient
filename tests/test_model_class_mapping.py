import os
import tempfile
import unittest

import cardinfo

from model_class_mapping import (
    MAPPING_LEGACY_IDENTITY,
    MAPPING_NUMERIC_FOLDER_LEXICOGRAPHIC,
    MAPPING_NUMERIC_FOLDER_NUMBER_ORDER,
    default_mapping_mode_for_gametype,
    model_idx_to_predict_classid,
    normalize_mapping_mode,
    read_mapping_mode_from_config,
)


class ModelClassMappingTests(unittest.TestCase):
    def test_normal_iv4_default_is_current_numeric_lexicographic(self):
        self.assertEqual(
            default_mapping_mode_for_gametype("BAC"),
            MAPPING_NUMERIC_FOLDER_LEXICOGRAPHIC,
        )
        self.assertEqual(
            default_mapping_mode_for_gametype("DT"),
            MAPPING_NUMERIC_FOLDER_LEXICOGRAPHIC,
        )

    def test_lattest_default_preserves_legacy_identity(self):
        self.assertEqual(
            default_mapping_mode_for_gametype("lattest"),
            MAPPING_LEGACY_IDENTITY,
        )

    def test_config_missing_tag_uses_supplied_default(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "config.xml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("<config><common /></config>")
            self.assertEqual(
                read_mapping_mode_from_config(
                    path, MAPPING_NUMERIC_FOLDER_LEXICOGRAPHIC
                ),
                MAPPING_NUMERIC_FOLDER_LEXICOGRAPHIC,
            )
            self.assertEqual(
                read_mapping_mode_from_config(path, MAPPING_LEGACY_IDENTITY),
                MAPPING_LEGACY_IDENTITY,
            )

    def test_config_explicit_value_overrides_default(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "config.xml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(
                    "<config><model_class_mapping_mode>legacy_identity"
                    "</model_class_mapping_mode></config>"
                )
            self.assertEqual(
                read_mapping_mode_from_config(
                    path, MAPPING_NUMERIC_FOLDER_LEXICOGRAPHIC
                ),
                MAPPING_LEGACY_IDENTITY,
            )

    def test_current_model_mapping(self):
        cases = {
            0: 0,
            1: 1,
            2: 10,
            12: 2,
            26: 32,
            39: 44,
            48: 52,
            49: 6,
            52: 9,
            53: 99,
        }
        for model_idx, predict_classid in cases.items():
            with self.subTest(model_idx=model_idx):
                self.assertEqual(
                    model_idx_to_predict_classid(
                        model_idx, MAPPING_NUMERIC_FOLDER_LEXICOGRAPHIC
                    ),
                    predict_classid,
                )

    def test_legacy_identity_preserves_old_behavior(self):
        for idx in (0, 1, 2, 26, 32, 52, 53):
            self.assertEqual(
                model_idx_to_predict_classid(idx, MAPPING_LEGACY_IDENTITY), idx
            )

    def test_current_heart6_reaches_existing_dealer_namespace(self):
        predict_classid = model_idx_to_predict_classid(
            26, MAPPING_NUMERIC_FOLDER_LEXICOGRAPHIC
        )
        self.assertEqual(predict_classid, 32)
        card_point = predict_classid - 26
        self.assertEqual(card_point, 6)
        self.assertEqual(
            cardinfo.GetCardVal(cardinfo.SUITES_HAEART, card_point), 54
        )

    def test_legacy_idx26_keeps_diamond_king_dealer_value(self):
        predict_classid = model_idx_to_predict_classid(
            26, MAPPING_LEGACY_IDENTITY
        )
        self.assertEqual(predict_classid, 26)
        card_point = predict_classid - 13
        self.assertEqual(card_point, 13)
        self.assertEqual(
            cardinfo.GetCardVal(cardinfo.SUITES_DIAMOND, card_point), 29
        )

    def test_future_numeric_order_mode(self):
        self.assertEqual(
            model_idx_to_predict_classid(32, MAPPING_NUMERIC_FOLDER_NUMBER_ORDER),
            32,
        )
        self.assertEqual(
            model_idx_to_predict_classid(53, MAPPING_NUMERIC_FOLDER_NUMBER_ORDER),
            99,
        )

    def test_invalid_mode_fails_fast(self):
        with self.assertRaises(ValueError):
            model_idx_to_predict_classid(0, "typo")

    def test_out_of_range_fails_fast(self):
        with self.assertRaises(ValueError):
            model_idx_to_predict_classid(
                54, MAPPING_NUMERIC_FOLDER_LEXICOGRAPHIC
            )


if __name__ == "__main__":
    unittest.main()

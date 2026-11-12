import unittest

from skinmon import names


class ParseTests(unittest.TestCase):
    def test_stattrak_knife_is_split_into_base_wear_and_flag(self):
        p = names.parse("★ StatTrak™ Skeleton Knife | Slaughter (Minimal Wear)")
        self.assertEqual(p.base, "★ Skeleton Knife | Slaughter")
        self.assertEqual(p.wear, "MW")
        self.assertTrue(p.stattrak)
        self.assertFalse(p.souvenir)

    def test_stattrak_weapon_without_star(self):
        p = names.parse("StatTrak™ AK-47 | Redline (Field-Tested)")
        self.assertEqual(p.base, "AK-47 | Redline")
        self.assertEqual(p.wear, "FT")
        self.assertTrue(p.stattrak)

    def test_souvenir_prefix_is_removed_from_base(self):
        p = names.parse("Souvenir AWP | Dragon Lore (Factory New)")
        self.assertEqual(p.base, "AWP | Dragon Lore")
        self.assertEqual(p.wear, "FN")
        self.assertTrue(p.souvenir)

    def test_vanilla_knife_has_no_wear(self):
        p = names.parse("★ Karambit")
        self.assertEqual(p.base, "★ Karambit")
        self.assertIsNone(p.wear)
        self.assertFalse(p.stattrak)

    def test_parenthesis_that_is_not_a_wear_stays_in_the_base(self):
        p = names.parse("Sticker | Natus Vincere (Holo) | Katowice 2014")
        self.assertEqual(p.base, "Sticker | Natus Vincere (Holo) | Katowice 2014")
        self.assertIsNone(p.wear)


class MatchingTests(unittest.TestCase):
    def test_same_skin_ignores_star_case_wear_and_stattrak(self):
        self.assertTrue(names.same_skin("skeleton knife | slaughter", "★ StatTrak™ Skeleton Knife | Slaughter (Field-Tested)"))

    def test_alert_typed_with_wear_still_matches_other_wears(self):
        self.assertTrue(names.same_skin("★ Skeleton Knife | Slaughter (Factory New)", "★ Skeleton Knife | Slaughter (Minimal Wear)"))

    def test_other_finish_of_same_knife_does_not_match(self):
        self.assertFalse(names.same_skin("★ Skeleton Knife | Slaughter", "★ Skeleton Knife | Fade (Factory New)"))

    def test_longer_name_sharing_a_prefix_does_not_match(self):
        self.assertFalse(names.same_skin("AK-47 | Red", "AK-47 | Redline (Field-Tested)"))


class TextHelpersTests(unittest.TestCase):
    def test_search_text_drops_symbols_and_wear(self):
        self.assertEqual(names.search_text("★ Skeleton Knife | Slaughter (Minimal Wear)"), "Skeleton Knife Slaughter")

    def test_slug_is_lowercase_and_hyphenated(self):
        self.assertEqual(names.slugify("★ StatTrak™ Skeleton Knife | Slaughter"), "skeleton-knife-slaughter")

    def test_short_label_abbreviates_the_wear(self):
        self.assertEqual(
            names.short("★ StatTrak™ Skeleton Knife | Slaughter (Minimal Wear)"),
            "★ StatTrak™ Skeleton Knife | Slaughter (MW)",
        )

    def test_wear_is_derived_from_float_ranges(self):
        self.assertEqual(names.wear_from_float(0.05), "FN")
        self.assertEqual(names.wear_from_float(0.1205), "MW")
        self.assertEqual(names.wear_from_float(0.2), "FT")
        self.assertEqual(names.wear_from_float(0.40), "WW")
        self.assertEqual(names.wear_from_float(0.6), "BS")

    def test_wear_label_in_portuguese(self):
        self.assertEqual(names.wear_label("MW"), "Pouco Usada (MW)")
        self.assertEqual(names.wear_label(None), "sem desgaste")


if __name__ == "__main__":
    unittest.main()

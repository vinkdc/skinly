import base64
import json
import unittest

from tracker import (
    Lockfile,
    TrackerError,
    build_skin_names,
    equipped_skins,
    get_identity,
    parse_lockfile,
    CLIENT_PLATFORM,
)


class TrackerTests(unittest.TestCase):
    def test_parses_lockfile_without_showing_password_in_repr(self):
        lockfile = parse_lockfile("Riot Client:1234:54321:secret-token:https\n")

        self.assertEqual(lockfile, Lockfile(port=54321, password="secret-token"))
        self.assertNotIn("secret-token", repr(lockfile))

    def test_rejects_invalid_lockfile_without_echoing_credential(self):
        with self.assertRaises(TrackerError) as raised:
            parse_lockfile("malformed:secret-token")

        self.assertNotIn("secret-token", str(raised.exception))

    def test_reads_only_session_identity_fields(self):
        identity = get_identity(
            {
                "puuid": "local-puuid",
                "game_name": "Player",
                "game_tag": "TAG",
                "region": "ap",
                "other_player": "must not be used",
            }
        )

        self.assertEqual(
            identity,
            {
                "puuid": "local-puuid",
                "game_name": "Player",
                "tag": "TAG",
                "region": "ap",
            },
        )

    def test_client_platform_header_is_valid_json(self):
        platform = json.loads(base64.b64decode(CLIENT_PLATFORM))

        self.assertEqual(platform["platformType"], "PC")
        self.assertEqual(platform["platformOS"], "Windows")

    def test_maps_equipped_skin_and_level_uuid_to_readable_name(self):
        weapon_id = "vandal-id"
        skin_id = "kuronami-id"
        level_id = "kuronami-level-id"
        weapon_data = {
            "data": [
                {
                    "uuid": weapon_id,
                    "displayName": "Vandal",
                    "skins": [
                        {
                            "uuid": skin_id,
                            "displayName": "Kuronami Vandal",
                            "levels": [{"uuid": level_id}],
                        }
                    ],
                }
            ]
        }
        weapons_by_id, skins_by_id = build_skin_names(weapon_data)
        loadout = {
            "Guns": [
                {"ID": weapon_id, "SkinLevelID": level_id},
                {"ID": "other-weapon", "SkinID": "unknown"},
            ]
        }

        self.assertEqual(
            equipped_skins(loadout, weapons_by_id, skins_by_id),
            [("Vandal", "Kuronami Vandal")],
        )


if __name__ == "__main__":
    unittest.main()

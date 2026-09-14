import base64
import json
import os
import re
import ssl
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPSHandler,
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)


SESSION_PATH = "/chat/v1/session"
ENTITLEMENTS_PATH = "/entitlements/v1/token"
CLIENT_PLATFORM = base64.b64encode(
    b'{\r\n\t"platformType": "PC",\r\n\t"platformOS": "Windows",'
    b'\r\n\t"platformOSVersion": "10.0.19042.1.256.64bit",'
    b'\r\n\t"platformChipset": "Unknown"\r\n}'
).decode("ascii")
VALID_SHARDS = {"na", "eu", "ap", "kr"}


class TrackerError(Exception):
    pass


@dataclass(frozen=True)
class Lockfile:
    port: int
    password: str = field(repr=False)
    protocol: str = "https"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def parse_lockfile(contents):
    fields = contents.strip().split(":")
    if len(fields) != 5 or not fields[0] or not fields[3]:
        raise TrackerError("The Riot Client lockfile is invalid.")
    try:
        int(fields[1])
        port = int(fields[2])
    except ValueError as error:
        raise TrackerError("The Riot Client lockfile is invalid.") from error
    if not 1 <= port <= 65535 or fields[4] != "https":
        raise TrackerError("The Riot Client lockfile is invalid.")
    return Lockfile(port=port, password=fields[3], protocol=fields[4])


def read_lockfile():
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise TrackerError("LOCALAPPDATA is not set; this prototype requires Windows.")
    path = Path(local_app_data) / "Riot Games" / "Riot Client" / "Config" / "lockfile"
    try:
        return parse_lockfile(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise TrackerError("Riot Client is not running (lockfile not found).") from error
    except OSError as error:
        raise TrackerError("Could not read the Riot Client lockfile.") from error


def make_opener(local=False):
    handlers = [ProxyHandler({}), NoRedirect()]
    if local:
        handlers.append(HTTPSHandler(context=ssl._create_unverified_context()))
    return build_opener(*handlers)


def get_json(opener, url, headers, description):
    request = Request(url, headers=headers, method="GET")
    try:
        with opener.open(request, timeout=8) as response:
            return json.load(response)
    except HTTPError as error:
        try:
            error_code = json.load(error).get("errorCode", "")
        except (json.JSONDecodeError, AttributeError, UnicodeDecodeError):
            error_code = ""
        safe_code = (
            f" ({error_code})"
            if isinstance(error_code, str) and re.fullmatch(r"[A-Z0-9_]+", error_code)
            else ""
        )
        raise TrackerError(
            f"{description} returned HTTP {error.code}{safe_code}."
        ) from error
    except (URLError, TimeoutError, OSError) as error:
        raise TrackerError(f"Could not reach {description}.") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise TrackerError(f"{description} returned invalid data.") from error


def local_json(opener, lockfile, endpoint, description):
    credential = base64.b64encode(
        f"riot:{lockfile.password}".encode("utf-8")
    ).decode("ascii")
    return get_json(
        opener,
        f"https://127.0.0.1:{lockfile.port}{endpoint}",
        {"Authorization": f"Basic {credential}"},
        description,
    )


def read_game_log(local_app_data):
    path = Path(local_app_data) / "VALORANT" / "Saved" / "Logs" / "ShooterGame.log"
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None, None, None

    region = shard = version = None
    for line in lines:
        glz = re.search(r"https://glz-([a-z]+)-1\.([a-z]+)\.a\.pvp\.net", line, re.I)
        pd = re.search(r"https://pd\.([a-z]+)\.a\.pvp\.net", line, re.I)
        if glz:
            region = glz.group(1).lower()
            shard = glz.group(2).lower()
        if pd:
            shard = pd.group(1).lower()
        client_version = re.search(r"CI server version:\s*(\S+)", line)
        if client_version:
            version = client_version.group(1)

    return region, shard, version


def get_current_client_version():
    version_data = get_json(
        build_opener(),
        "https://valorant-api.com/v1/version",
        {},
        "Valorant-API.com version metadata",
    )
    try:
        return version_data["data"]["riotClientVersion"]
    except (KeyError, TypeError) as error:
        raise TrackerError("Valorant-API.com returned invalid version metadata.") from error


def get_identity(session):
    try:
        return {
            "puuid": session["puuid"],
            "game_name": session["game_name"],
            "tag": session["game_tag"],
            "region": session.get("region", ""),
        }
    except (KeyError, TypeError) as error:
        raise TrackerError("Riot Client did not provide the local account identity.") from error


def build_skin_names(weapons_data):
    weapons_by_id = {}
    skins_by_id = {}
    for weapon in weapons_data.get("data", []):
        weapon_id = weapon.get("uuid", "").lower()
        if weapon_id:
            weapons_by_id[weapon_id] = weapon.get("displayName", "Unknown weapon")
        for skin in weapon.get("skins", []):
            skin_name = skin.get("displayName", "Unknown skin")
            skin_id = skin.get("uuid", "").lower()
            if skin_id:
                skins_by_id[skin_id] = skin_name
            for level in skin.get("levels", []):
                level_id = level.get("uuid", "").lower()
                if level_id:
                    skins_by_id[level_id] = skin_name
    return weapons_by_id, skins_by_id


def equipped_skins(loadout, weapons_by_id, skins_by_id):
    result = []
    for gun in loadout.get("Guns", []):
        weapon_id = gun.get("ID", "").lower()
        skin_id = (gun.get("SkinLevelID") or gun.get("SkinID") or "").lower()
        weapon_name = weapons_by_id.get(weapon_id)
        if weapon_name:
            result.append((weapon_name, skins_by_id.get(skin_id, "Unknown skin")))
    return result


def run():
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise TrackerError("LOCALAPPDATA is not set; this prototype requires Windows.")

    lockfile = read_lockfile()
    local_opener = make_opener(local=True)
    identity = get_identity(
        local_json(local_opener, lockfile, SESSION_PATH, "Riot Client session")
    )
    tokens = local_json(
        local_opener, lockfile, ENTITLEMENTS_PATH, "Riot Client entitlements"
    )
    if tokens.get("subject", "").lower() != identity["puuid"].lower():
        raise TrackerError("Riot Client returned mismatched local account data.")

    log_region, shard, client_version = read_game_log(local_app_data)
    region = identity["region"] or log_region or shard
    print(f"Logged in: {identity['game_name']}#{identity['tag']}")
    print(f"PUUID: {identity['puuid']}")
    if region:
        print(f"Region: {str(region).upper()}")
    print()

    if not shard:
        region_to_shard = {"na": "na", "latam": "na", "br": "na", "eu": "eu", "ap": "ap", "kr": "kr"}
        shard = region_to_shard.get(str(region).lower())
    if shard not in VALID_SHARDS:
        raise TrackerError("Could not determine the local VALORANT shard.")
    if not client_version:
        client_version = get_current_client_version()

    headers = {
        "Authorization": f"Bearer {tokens['accessToken']}",
        "X-Riot-Entitlements-JWT": tokens["token"],
        "X-Riot-ClientPlatform": CLIENT_PLATFORM,
        "X-Riot-ClientVersion": client_version,
        "User-Agent": "ShooterGame/13 Windows/10.0.19042.1.256.64bit",
    }
    loadout_url = (
        f"https://pd.{shard}.a.pvp.net/personalization/v2/players/"
        f"{identity['puuid']}/playerloadout"
    )
    loadout = get_json(
        make_opener(), loadout_url, headers, "the local player's loadout"
    )
    weapons = get_json(
        build_opener(),
        "https://valorant-api.com/v1/weapons",
        {},
        "Valorant-API.com weapon metadata",
    )
    weapons_by_id, skins_by_id = build_skin_names(weapons)
    skins = equipped_skins(loadout, weapons_by_id, skins_by_id)

    for weapon_name, skin_name in skins:
        print(f"{weapon_name}: {skin_name}")


def main():
    try:
        run()
        return 0
    except TrackerError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except Exception:
        print("Error: Could not retrieve the local VALORANT loadout.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Read anonymous, public stream metadata. Only the allowlisted URLs reach the network."""
import json
import re
import sys
from urllib.parse import parse_qs, urlsplit


def public_link(value):
    if len(value) > 500 or re.search(r'[\s<>\\\x00-\x1f]', value):
        raise ValueError("Pega un enlace público HTTPS.")
    url = urlsplit(value)
    if url.scheme != "https" or not url.hostname or url.netloc.lower() != url.hostname or "." not in url.hostname:
        raise ValueError("Pega un enlace público HTTPS sin credenciales ni puerto.")
    return url


def supported_url(value):
    url = public_link(value)
    host = url.hostname.removeprefix("www.")
    path = url.path.rstrip("/")
    if host in {"youtube.com", "m.youtube.com", "youtu.be"}:
        video = path[1:] if host == "youtu.be" else path.removeprefix("/live/")
        if host != "youtu.be" and path == "/watch":
            video = parse_qs(url.query).get("v", [""])[0]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
            return "Youtube", f"https://www.youtube.com/watch?v={video}"
    if host == "twitch.tv":
        if re.fullmatch(r"/videos/[0-9]+", path):
            return "TwitchVod", f"https://www.twitch.tv{path}"
        if re.fullmatch(r"/[A-Za-z0-9_]{1,25}", path):
            return "TwitchStream", f"https://www.twitch.tv{path.lower()}"
    if host == "tiktok.com" and re.fullmatch(r"/@[A-Za-z0-9_.]{2,24}/live", path):
        return "TikTokLive", f"https://www.tiktok.com{path}"
    return None


def metadata(url):
    from yt_dlp import YoutubeDL

    extractor, canonical = supported_url(url)
    options = dict(quiet=True, no_warnings=True, noplaylist=True, socket_timeout=6,
                   retries=0, extractor_retries=0, cachedir=False)
    with YoutubeDL(options) as client:
        info = client.extract_info(canonical, download=False, ie_key=extractor)
        if info.get("live_status") not in {"is_live", "was_live", "post_live"}:
            return None
        if not info.get("formats") or info.get("availability") not in {None, "public"}:
            return None
        title = info["title"]
        followers = info.get("channel_follower_count")
        owner = info.get("channel_id")
        if extractor == "Youtube":
            if info.get("availability") != "public":
                return None
            platform = "youtube"
            profile = f"https://www.youtube.com/channel/{owner}"
        elif extractor.startswith("Twitch"):
            platform = "twitch"
            ie = client.get_info_extractor(extractor)
            fields = "id login followers { totalCount }"
            if extractor == "TwitchVod":
                query = "query($id:ID!){video(id:$id){broadcastType title owner{" + fields + "}}}"
                video = ie._download_base_gql("proof", {"query": query, "variables": {"id": canonical.split("/")[-1]}}, "Public archive")["data"]["video"]
                if video["broadcastType"] != "ARCHIVE":
                    return None
                title, user = video["title"], video["owner"]
            else:
                query = "query($login:String!){user(login:$login){" + fields + " stream { id } broadcastSettings { title }}}"
                user = ie._download_base_gql("proof", {"query": query, "variables": {"login": canonical.split("/")[-1]}}, "Public channel")["data"]["user"]
                if not user.get("stream"):
                    return None
                title = user["broadcastSettings"]["title"]
            owner, followers = user["id"], user["followers"]["totalCount"]
            profile = "https://www.twitch.tv/" + user["login"]
        else:
            platform = "tiktok"
            ie = client.get_info_extractor(extractor)
            profile = canonical.removesuffix("/live")
            page = ie._download_webpage(profile, "proof")
            user = ie._get_universal_data(page, "proof")["webapp.user-detail"]["userInfo"]
            owner = str(user["user"]["id"])
            if owner != info.get("uploader_id") or user["user"].get("privateAccount"):
                return None
            stats = user.get("stats") or user.get("statsV2") or {}
            followers = stats.get("followerCount")
        if not owner or followers is None:
            return None
        return {"owner": f"{platform}:{owner}", "title": title, "followers": int(followers), "profile": profile}


def twitch_profile(owner):
    from yt_dlp import YoutubeDL

    if not re.fullmatch(r"twitch:[0-9]+", owner):
        return None
    with YoutubeDL({"quiet": True, "socket_timeout": 5, "cachedir": False}) as client:
        ie = client.get_info_extractor("TwitchStream")
        query = {"query": "query($id:ID!){user(id:$id){login}}", "variables": {"id": owner.split(":")[1]}}
        user = ie._download_base_gql("profile", query, "Public channel")["data"]["user"]
        return "https://www.twitch.tv/" + user["login"]


def live_target(profile):
    url = public_link(profile)
    host = url.hostname.removeprefix("www.")
    path = url.path.rstrip("/")
    if host == "twitch.tv" and re.fullmatch(r"/\w{1,25}", path, re.ASCII):
        return "Twitch", "https://www.twitch.tv" + path.lower()
    if host in {"youtube.com", "m.youtube.com"} and re.fullmatch(r"/(?:channel/UC[\w-]{22}|@[\w.%-]+)", path):
        return "YouTube", "https://www.youtube.com" + path + "/live"
    if host == "tiktok.com" and re.fullmatch(r"/@[A-Za-z0-9_.]{2,24}", path):
        return "TikTok", "https://www.tiktok.com" + path + "/live"
    if host == "kick.com" and re.fullmatch(r"/[A-Za-z0-9_-]+", path):
        return "Kick", "https://kick.com" + path.lower()
    return None


def current_live(profile):
    from yt_dlp import YoutubeDL

    target = live_target(profile)
    if not target:
        return None
    platform, link = target
    with YoutubeDL(dict(quiet=True, no_warnings=True, noplaylist=True, socket_timeout=6,
                        retries=0, extractor_retries=0, cachedir=False)) as client:
        if platform == "Twitch":
            ie = client.get_info_extractor("TwitchStream")
            login = link.rsplit("/", 1)[1]
            query = {"query": "query($login:String!){user(login:$login){id stream{id type} broadcastSettings{title}}}",
                     "variables": {"login": login}}
            user = ie._download_base_gql(login, query, "Public live status")["data"]["user"]
            if not user or not user.get("stream") or user["stream"].get("type") != "live":
                return None
            session, title, owner = user["stream"]["id"], user["broadcastSettings"]["title"], user["id"]
        else:
            info = client.extract_info(link, download=False)
            if info.get("live_status") != "is_live" or info.get("availability") not in {None, "public"}:
                return None
            session, title = info.get("id"), info.get("title")
            owner = info.get("uploader_id" if platform == "TikTok" else "channel_id")
            if platform == "YouTube":
                if not re.fullmatch(r"[\w-]{11}", session or ""):
                    return None
                if "/channel/" in link and link.split("/")[-2] != owner:
                    return None
                if "/@" in link:
                    from urllib.parse import unquote
                    if unquote(link.split("/")[-2]).casefold() != (info.get("uploader_id") or "").casefold():
                        return None
                link = f"https://www.youtube.com/watch?v={session}"
        if not session or not owner or not title:
            return None
        return {"platform": platform, "session": str(session), "owner": f"{platform.lower()}:{owner}",
                "title": title, "link": link}


if __name__ == "__main__":
    try:
        if sys.argv[1] == "--live":
            result = current_live(sys.argv[2])
        elif sys.argv[1].startswith("twitch:"):
            result = twitch_profile(sys.argv[1])
        else:
            result = metadata(sys.argv[1])
        print(json.dumps(result))
    except Exception:
        # An unavailable platform is a review case, never a successful check.
        print("null")

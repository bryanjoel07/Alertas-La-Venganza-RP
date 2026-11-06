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
        elif extractor.startswith("Twitch"):
            platform = "twitch"
            ie = client.get_info_extractor(extractor)
            fields = "id followers { totalCount }"
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
        return {"owner": f"{platform}:{owner}", "title": title, "followers": int(followers)}


if __name__ == "__main__":
    try:
        print(json.dumps(metadata(sys.argv[1])))
    except Exception:
        # An unavailable platform is a review case, never a successful check.
        print("null")

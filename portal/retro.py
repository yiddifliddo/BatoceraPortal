"""RetroAchievements profile widget and Batocera release news (both optional,
both cached, both silent when offline)."""
import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from html import unescape

RA_API = "https://retroachievements.org/API"
RA_TTL = 600
NEWS_URL = "https://github.com/batocera-linux/batocera.linux/releases.atom"
NEWS_TTL = 3600

_ra_cache = {"ts": 0.0, "key": None, "data": None}
_news_cache = {"ts": 0.0, "data": None}


def _get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "BatoceraPortal/1.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
        return r.read()


def _ra_call(user, key, endpoint, **params):
    params.update({"z": user, "y": key, "u": params.get("u", user)})
    url = f"{RA_API}/{endpoint}?{urllib.parse.urlencode(params)}"
    return json.loads(_get(url))


def ra_profile(settings, force=False):
    user = (settings.get("ra_user") or "").strip()
    key = (settings.get("ra_api_key") or "").strip()
    if not user or not key:
        return {"enabled": False}
    now = time.time()
    if not force and _ra_cache["data"] and _ra_cache["key"] == user and now - _ra_cache["ts"] < RA_TTL:
        return _ra_cache["data"]
    try:
        profile = _ra_call(user, key, "API_GetUserProfile.php")
        recent = _ra_call(user, key, "API_GetUserRecentAchievements.php", m=10080)
        completed = _ra_call(user, key, "API_GetUserCompletionProgress.php", c=12)
    except Exception as e:
        data = {"enabled": True, "error": f"RetroAchievements unreachable: {e}"}
        _ra_cache.update({"ts": now, "key": user, "data": data})
        return data
    pic = profile.get("UserPic") or ""
    data = {
        "enabled": True,
        "user": profile.get("User", user),
        "avatar": f"https://retroachievements.org{pic}" if pic.startswith("/") else pic,
        "points": profile.get("TotalPoints"),
        "true_points": profile.get("TotalTruePoints"),
        "softcore": profile.get("TotalSoftcorePoints"),
        "rank": None,
        "member_since": profile.get("MemberSince"),
        "rich_presence": profile.get("RichPresenceMsg"),
        "recent": [{
            "title": a.get("Title"), "game": a.get("GameTitle"), "points": a.get("Points"),
            "date": a.get("Date"), "badge": f"https://media.retroachievements.org/Badge/{a.get('BadgeName')}.png"
            if a.get("BadgeName") else None} for a in (recent or [])[:12]],
        "progress": [{
            "game": g.get("Title"), "console": g.get("ConsoleName"), "earned": g.get("NumAwarded"),
            "total": g.get("MaxPossible"), "icon": f"https://retroachievements.org{g.get('ImageIcon')}"
            if g.get("ImageIcon") else None}
            for g in (completed.get("Results") if isinstance(completed, dict) else [])],
        "fetched": int(now),
    }
    _ra_cache.update({"ts": now, "key": user, "data": data})
    return data


def ra_test(user, key):
    try:
        p = _ra_call(user.strip(), key.strip(), "API_GetUserProfile.php")
    except Exception as e:
        return False, {"error": str(e)}
    if not p or not p.get("User"):
        return False, {"error": "No profile returned; check the username and API key"}
    return True, {"user": p["User"], "points": p.get("TotalPoints")}


def parse_atom(data):
    text = data.decode("utf-8", errors="replace")
    items = []
    for entry in re.findall(r"<entry>(.*?)</entry>", text, re.S):
        title = unescape(re.search(r"<title>(.*?)</title>", entry, re.S).group(1).strip()) \
            if re.search(r"<title>(.*?)</title>", entry, re.S) else ""
        link = re.search(r'<link[^>]*href="([^"]+)"', entry)
        updated = re.search(r"<updated>(.*?)</updated>", entry)
        items.append({"title": title, "url": link.group(1) if link else "",
                      "date": updated.group(1)[:10] if updated else ""})
    return items


def batocera_news(force=False):
    now = time.time()
    if not force and _news_cache["data"] is not None and now - _news_cache["ts"] < NEWS_TTL:
        return _news_cache["data"]
    try:
        items = parse_atom(_get(NEWS_URL))[:8]
    except Exception:
        items = []
    _news_cache.update({"ts": now, "data": items})
    return items

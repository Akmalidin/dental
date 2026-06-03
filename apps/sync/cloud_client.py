"""Простой HTTP-клиент для общения локального приложения с облаком (только stdlib)."""
import json
import urllib.request
import urllib.parse
import http.cookiejar
import re


class CloudClient:
    def __init__(self, base_url):
        self.base = base_url.rstrip("/")
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.opener.addheaders = [("User-Agent", "SADAF-Offline/1.0")]

    def _csrftoken(self):
        for c in self.cj:
            if c.name == "csrftoken":
                return c.value
        return ""

    def login(self, login, password):
        # 1) получить страницу логина (csrf cookie + form token)
        with self.opener.open(self.base + "/login/", timeout=30) as r:
            html = r.read().decode("utf-8", "replace")
        m = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', html)
        token = m.group(1) if m else self._csrftoken()
        data = urllib.parse.urlencode({
            "csrfmiddlewaretoken": token, "login": login, "password": password,
        }).encode()
        req = urllib.request.Request(self.base + "/login/", data=data)
        req.add_header("Referer", self.base + "/login/")
        with self.opener.open(req, timeout=30) as r:
            final = r.geturl()
        # успех = редирект не на /login/
        return "/login" not in final

    def get_json(self, path, timeout=120):
        with self.opener.open(self.base + path, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def post_json(self, path, payload, timeout=180):
        body = json.dumps(payload).encode()
        req = urllib.request.Request(self.base + path, data=body)
        req.add_header("Content-Type", "application/json")
        req.add_header("X-CSRFToken", self._csrftoken())
        req.add_header("Referer", self.base + "/")
        with self.opener.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

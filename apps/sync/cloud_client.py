"""HTTP-клиент офлайн-копии для общения с облаком (только stdlib).

Вход по паролю нужен один раз — при настройке (регистрация устройства).
Дальше синхронизация идёт по токену устройства; пароль на компьютере не
хранится."""
import http.cookiejar
import json
import re
import urllib.error
import urllib.parse
import urllib.request


class CloudClient:
    def __init__(self, base_url, device_id=None, token=None):
        self.base = base_url.rstrip("/")
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.opener.addheaders = [("User-Agent", "SADAF-Offline/2.0")]
        self.device_auth = f"Device {device_id}:{token}" if device_id and token else None

    def _csrftoken(self):
        for c in self.cj:
            if c.name == "csrftoken":
                return c.value
        return ""

    def login(self, login, password):
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
        return "/login" not in final

    def register(self, name=""):
        """После login(): зарегистрировать устройство → {device_id, token, clinic}."""
        data = urllib.parse.urlencode({"name": name}).encode()
        req = urllib.request.Request(self.base + "/sync/register/", data=data)
        req.add_header("X-CSRFToken", self._csrftoken())
        req.add_header("Referer", self.base + "/")
        with self.opener.open(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def _req(self, path, body=None):
        req = urllib.request.Request(self.base + path, data=body)
        if self.device_auth:
            req.add_header("Authorization", self.device_auth)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        return req

    def get_json(self, path, timeout=300):
        try:
            with self.opener.open(self._req(path), timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001
                return {"ok": False, "error": f"HTTP {e.code}"}

    def post_json(self, path, payload, timeout=300):
        try:
            with self.opener.open(self._req(path, json.dumps(payload).encode()), timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001
                return {"ok": False, "error": f"HTTP {e.code}"}

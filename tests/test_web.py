"""Version web de l'app, servie sous /web par le backend."""
import re


def test_page_et_script_servis(client):
    r = client.get("/web/")
    assert r.status_code == 200 and "<title>Tanren</title>" in r.text
    script = re.search(r'src="(/web/_expo/static/js/web/[^"]+\.js)"', r.text)
    assert script, "le script de l'app doit être référencé sous /web"
    assert client.get(script.group(1)).status_code == 200
    assert client.get("/web/manifest.json").json()["start_url"] == "/web/"


def test_api_non_masquee(client):
    assert client.get("/health").json() == {"status": "ok"}

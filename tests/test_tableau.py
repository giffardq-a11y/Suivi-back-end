"""Page d'affichage du tableau partagé (/tableau#jeton)."""
import re


def test_page_servie_sans_connexion_avec_ses_entetes(client):
    r = client.get("/tableau")  # aucune en-tête d'autorisation
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "noindex" in r.headers["x-robots-tag"]
    csp = r.headers["content-security-policy"]
    assert "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp
    # Le jeton se lit dans le fragment, et les données viennent de /board/.
    assert "location.hash" in r.text and '"/board/"' in r.text


def test_page_sans_html_injecte_ni_ressource_externe(client):
    page = client.get("/tableau").text
    # Le nom affiché est saisi par l'utilisateur : jamais interprété comme HTML.
    assert "innerHTML" not in page and "insertAdjacentHTML" not in page and "document.write" not in page
    assert not re.search(r"""(src|href)\s*=\s*["']?https?:""", page)


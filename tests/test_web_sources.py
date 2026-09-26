import asyncio
from types import SimpleNamespace

from app.sources.agorastore import AgorastoreSource
from app.sources.interencheres import InterencheresSource
from app.sources.web_common import parse_price


def watch(query="RTX 4090", max_price=1500):
    return SimpleNamespace(query=query, min_price=None, max_price=max_price)


def test_parse_price_french():
    assert parse_price("Prix actuel 1 249,50 €") == (1249.50, "EUR")


def test_interencheres_v8_never_builds_protected_search_route():
    src = InterencheresSource()
    assert "/recherche/lots" not in src.status_label
    assert src.categories_sitemap_url.endswith("/sitemap.categories.html")


def test_interencheres_live_category_card_fixed_time_and_estimate():
    src = InterencheresSource()
    html = '''
    <div class="autoqa-sale-details-item">
      <a href="/biens-equipement/vente-info-688787/lot-88408440.html">
        <div class="autoqa-itemcard-title">ASUS - Carte graphique NVIDIA GeForce RTX 4090 24G</div>
      </a>
      <div class="text-h6 font-weight-bold">Live</div>
      <div class="bottom"><span>Aujourd'hui à 18h00</span></div>
      <div>Estimation : 670 € - 1 449 €</div>
      <div class="organization-name"><span>Maison</span><span>Test</span></div>
    </div>
    '''
    lots, count, mode = src._parse_category_lots(html)
    assert count == 1 and mode == "cards"
    item = src._convert(lots[0], watch())
    assert item is not None
    assert item.source == "interencheres"
    assert item.external_id == "88408440"
    assert item.auction_type == "Live"
    assert item.timing_text == "Aujourd'hui à 18h00"
    assert item.price is None
    assert item.estimate_text == "670 € - 1 449 €"


def test_interencheres_chrono_category_card_current_price():
    src = InterencheresSource()
    html = '''
    <div class="autoqa-sale-details-item">
      <a href="/biens-equipement/vente-info-688787/lot-88408441.html">
        <div class="autoqa-itemcard-title">Carte graphique RTX 4090 OC</div>
      </a>
      <div class="text-h6 font-weight-bold">Chrono</div>
      <span>Fin dans 1j 13h</span>
      <div>Prix actuel 999 €</div>
    </div>
    '''
    lots, _, _ = src._parse_category_lots(html)
    item = src._convert(lots[0], watch())
    assert item is not None
    assert item.auction_type == "Chrono"
    assert item.timing_text == "Fin dans 1j 13h"
    assert item.price == 999
    assert item.price_label == "Prix actuel"


def test_interencheres_catalogue_category_card_is_not_dropped():
    src = InterencheresSource()
    html = '''
    <div class="autoqa-sale-details-item">
      <a href="/art-decoration/vente-info-700000/lot-90000001.html">
        <div class="autoqa-itemcard-title">NVIDIA RTX 4090 édition collection</div>
      </a>
      <div class="text-h6 font-weight-bold">Catalogue</div>
      <div class="bottom"><span>Dimanche 13 septembre 2026 à 14h30</span></div>
      <div>Mise à prix 450 €</div>
    </div>
    '''
    lots, _, _ = src._parse_category_lots(html)
    item = src._convert(lots[0], watch())
    assert item is not None
    assert item.auction_type == "Catalogue"
    assert item.timing_text == "Dimanche 13 septembre 2026 à 14h30"
    assert item.price == 450


def test_interencheres_completed_lot_is_ignored():
    src = InterencheresSource()
    html = '''
    <div class="autoqa-sale-details-item">
      <a href="/art-decoration/vente-info-700000/lot-90000002.html">
        <div class="autoqa-itemcard-title">RTX 4090 déjà vendue</div>
      </a>
      <div class="text-h6 font-weight-bold">Live — Adjugé</div>
      <div class="autoqa-itemcard-adjudicated-amount">Adjugé 850 €</div>
    </div>
    '''
    lots, _, _ = src._parse_category_lots(html)
    assert src._convert(lots[0], watch()) is None


def test_interencheres_price_filter_applies_to_real_current_price():
    src = InterencheresSource()
    html = '''
    <div class="autoqa-sale-details-item">
      <a href="/biens-equipement/vente-info-688787/lot-88408442.html">
        <div class="autoqa-itemcard-title">Carte graphique RTX 4090</div>
      </a>
      <div class="text-h6 font-weight-bold">Chrono</div>
      <div>Prix actuel 1 800 €</div>
    </div>
    '''
    lots, _, _ = src._parse_category_lots(html)
    assert src._convert(lots[0], watch(max_price=1500)) is None


def test_interencheres_generic_anchor_fallback_finds_macbook():
    src = InterencheresSource()
    html = '''
    <main>
      <a href="/biens-equipement/informatique-apple-688427/lot-88628294.html">
        1/3 Estimation : 120 € - 320 € Déjà vu APPLE MACBOOK 12&quot; (2016) - RECONDITIONNÉ Chrono Proposé par Affaires Enchères
      </a>
    </main>
    '''
    lots, count, mode = src._parse_category_lots(html)
    assert count == 1 and mode == "anchors"
    item = src._convert(lots[0], watch(query="macbook", max_price=None))
    assert item is not None
    assert item.external_id == "88628294"
    assert "MACBOOK" in item.title.upper()
    assert item.auction_type == "Chrono"
    assert item.estimate_text == "120 € - 320 €"


def test_interencheres_local_query_filter_rejects_unrelated_category_card():
    src = InterencheresSource()
    html = '''
    <div class="autoqa-sale-details-item">
      <a href="/biens-equipement/vente-info-1/lot-12345678.html">
        <div class="autoqa-itemcard-title">Ordinateur portable DELL Latitude</div>
      </a>
      <div class="text-h6 font-weight-bold">Catalogue</div>
    </div>
    '''
    lots, _, _ = src._parse_category_lots(html)
    assert src._convert(lots[0], watch(query="macbook", max_price=None)) is None


def test_interencheres_category_sitemap_parser_keeps_french_lot_categories_only():
    src = InterencheresSource()
    html = '''
      <a href="https://www.interencheres.com/biens-equipement/ordinateurs-portables-et-fixes/">A</a>
      <a href="https://www.interencheres.com/en-US/biens-equipement/ordinateurs-portables-et-fixes/">EN</a>
      <a href="https://www.interencheres.com/biens-equipement/ordinateurs-portables-et-fixes/ventes">Ventes</a>
      <a href="https://www.interencheres.com/art-decoration/montres/">Montres</a>
    '''
    paths = src._extract_category_paths(html)
    assert "/biens-equipement/ordinateurs-portables-et-fixes/" in paths
    assert "/art-decoration/montres/" in paths
    assert all("en-US" not in p and not p.endswith("/ventes/") for p in paths)


def test_interencheres_resolver_prefers_computers_for_macbook(monkeypatch):
    src = InterencheresSource()

    async def fake_paths():
        return [
            "/art-decoration/montres/",
            "/biens-equipement/informatique-et-telephonie/",
            "/biens-equipement/ordinateurs-portables-et-fixes/",
            "/biens-equipement/peripheriques-et-composants-informatiques/",
        ]

    monkeypatch.setattr(src, "_category_paths", fake_paths)
    urls = asyncio.run(src._resolve_categories("macbook"))
    assert urls[0].endswith("/biens-equipement/ordinateurs-portables-et-fixes/")
    assert any("informatique-et-telephonie" in u for u in urls)


def test_interencheres_resolver_prefers_components_for_rtx(monkeypatch):
    src = InterencheresSource()

    async def fake_paths():
        return [
            "/biens-equipement/informatique-et-telephonie/",
            "/biens-equipement/ordinateurs-portables-et-fixes/",
            "/biens-equipement/peripheriques-et-composants-informatiques/",
        ]

    monkeypatch.setattr(src, "_category_paths", fake_paths)
    urls = asyncio.run(src._resolve_categories("RTX 5070"))
    assert urls[0].endswith("/biens-equipement/peripheriques-et-composants-informatiques/")


def test_agorastore_current_product_candidate():
    src = AgorastoreSource.__new__(AgorastoreSource)
    html = '<a href="/fr/materiel-occasion/bureau/rtx-4090-workstation/agora-426030">RTX 4090 workstation</a>'
    items = src._extract_candidates(html, "https://www.agorastore.fr/", watch())
    assert len(items) == 1
    assert items[0][0].endswith("/agora-426030")


def test_parse_price_currency_before_amount():
    assert parse_price("Offre actuelle € 100") == (100.0, "EUR")


def test_catawiki_uses_current_bid_not_estimate():
    from app.sources.catawiki import CatawikiSource

    src = CatawikiSource.__new__(CatawikiSource)
    html = '''
    <html><body>
      <h1>Apple MacBook Air M2</h1>
      <div>Offre actuelle € 97</div>
      <div>Estimation € 450 - € 550</div>
    </body></html>
    '''
    item = src._parse_detail(
        html,
        "https://www.catawiki.com/fr/l/12345678-apple-macbook-air-m2",
        "Apple MacBook Air M2",
        watch(query="macbook", max_price=None),
    )
    assert item is not None
    assert item.price == 97.0
    assert item.currency == "EUR"
    assert item.price_label == "Offre actuelle"


def test_agorastore_uses_labelled_current_price():
    html = '''
    <html><body>
      <h1>Apple MacBook Pro 14 pouces</h1>
      <div>Enchère actuelle 520 €</div>
      <div>Valeur indicative 1 500 €</div>
      <div>Fin de vente : 18/09/2026 à 14:30</div>
    </body></html>
    '''
    item = AgorastoreSource._detail_from_text(
        html,
        "https://www.agorastore.fr/fr/materiel-occasion/bureau/macbook-pro/agora-426030",
        "Apple MacBook Pro",
        watch(query="macbook", max_price=None),
    )
    assert item is not None
    assert item.price == 520.0
    assert item.price_label == "Enchère actuelle"


def test_catawiki_missing_current_bid_does_not_use_estimate():
    from app.sources.catawiki import CatawikiSource

    src = CatawikiSource.__new__(CatawikiSource)
    html = '''
    <html><body>
      <h1>Apple MacBook Pro M3</h1>
      <div>Offre actuelle Aucune offre</div>
      <div>Estimation € 1 500 - € 1 800</div>
    </body></html>
    '''
    item = src._parse_detail(
        html,
        "https://www.catawiki.com/fr/l/87654321-apple-macbook-pro-m3",
        "Apple MacBook Pro M3",
        watch(query="macbook", max_price=None),
    )
    assert item is not None
    assert item.price is None
    assert item.price_label is None


def test_interencheres_anchor_title_cleans_ui_metadata():
    src = InterencheresSource()
    html = '''
    <a href="/biens-equipement/vente-1/lot-88735906.html">
      65 Déjà vu 1 MACBOOK Air A3241 Live
    </a>
    <a href="/biens-equipement/vente-1/lot-88592629.html">
      117 Estimation : 270 € Déjà vu APPLE MACBOOK NEO 13&quot; 8/256GB Live
    </a>
    '''
    lots, count, mode = src._parse_category_lots(html)
    assert count == 2 and mode == "anchors"
    assert lots[0].title == "1 MACBOOK Air A3241"
    assert lots[1].title == 'APPLE MACBOOK NEO 13" 8/256GB'


def test_interencheres_v84_direct_cdp_skips_http(monkeypatch):
    src = InterencheresSource()
    src._scan_force_cdp = True
    calls = {"http": 0, "cdp": 0}

    async def fake_http(url, referer=None):
        calls["http"] += 1
        return None, 403

    async def fake_cdp(url):
        calls["cdp"] += 1
        return SimpleNamespace(html="<html></html>", url=url, mode="cdp", status=200)

    monkeypatch.setattr(src, "_http_fetch", fake_http)
    monkeypatch.setattr(src, "_cdp_fetch", fake_cdp)
    result = asyncio.run(src._fetch("https://www.interencheres.com/biens-equipement/test/"))
    assert result.mode == "cdp"
    assert calls == {"http": 0, "cdp": 1}


def test_interencheres_v84_cdp_mode_skips_sitemap_http(monkeypatch):
    src = InterencheresSource()
    src._scan_force_cdp = True
    calls = {"http": 0}

    async def fake_http(url, referer=None):
        calls["http"] += 1
        return None, 403

    monkeypatch.setattr(src, "_http_fetch", fake_http)
    paths = asyncio.run(src._category_paths())
    assert calls["http"] == 0
    assert "/biens-equipement/ordinateurs-portables-et-fixes/" in paths

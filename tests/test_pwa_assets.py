from pathlib import Path


def test_service_worker_has_navigation_fallback_and_ping_bypass():
    content = Path('static/sw.js').read_text(encoding='utf-8')
    assert "request.mode === 'navigate'" in content
    assert "/static/offline.html" in content
    assert "url.pathname === '/api/ping'" in content
    assert "cache: 'no-store'" in content


def test_manifest_start_url_and_scope():
    manifest = Path('static/manifest.webmanifest').read_text(encoding='utf-8')
    assert '"start_url": "/mobile"' in manifest
    assert '"scope": "/"' in manifest


def test_offline_shell_contains_mobile_forms():
    html = Path('static/offline.html').read_text(encoding='utf-8')
    assert "data-mobile-state=\"true\"" in html
    assert "data-offline=\"punch\"" in html
    assert "data-offline=\"vacation\"" in html
    assert "/static/mobile.js" in html

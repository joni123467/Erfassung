from pathlib import Path


def test_service_worker_has_navigation_fallback_and_ping_bypass():
    content = Path('static/sw.js').read_text(encoding='utf-8')
    assert "request.mode === 'navigate'" in content
    assert "/static/offline.html" in content
    assert "url.pathname === '/api/ping'" in content
    assert "cache: 'no-store'" in content


def test_manifest_start_url_and_scope():
    manifest = Path('static/manifest.webmanifest').read_text(encoding='utf-8')
    assert '"start_url": "/static/offline.html"' in manifest
    assert '"scope": "/"' in manifest

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    html = (ROOT / "web/static/index.html").read_text(encoding="utf-8")
    app = (ROOT / "web/static/app.js").read_text(encoding="utf-8")
    nav = html.split('<nav class="tab-nav">', 1)[1].split('</nav>', 1)[0]
    removed = ('data-tab="reg"', 'data-tab="session"', 'data-tab="upi"')
    kept = ('data-tab="mailread"', 'data-tab="eventista"', 'data-tab="settings"')
    assert not any(item in nav for item in removed), "removed tabs still in nav"
    assert all(item in nav for item in kept), "required tabs missing from nav"
    assert '<option value="multi30">Multi (30)</option>' in html
    assert html.count('id="mode"') == 1
    for script in ('session.js', 'upi.js', 'autoreg.js', 'link.js', 'hme.js'):
        assert f'/static/{script}' not in html, f"removed script still loaded: {script}"
    assert "['mailread', 'eventista', 'settings']" in app
    print('[PASS] UI chỉ còn Đọc Hòm Thư, Reg Eventista, Settings và Multi (30)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

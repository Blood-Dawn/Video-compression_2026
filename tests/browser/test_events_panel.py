from playwright.sync_api import Page, expect


BASE_URL = "http://" + "127.0.0.1:5000"


def test_behavior_events_panel_renders_seeded_events(page: Page):
    page.goto(BASE_URL, wait_until="domcontentloaded")

    page.locator('button.tab-btn[data-tab="tools"]').click()
    page.locator("#events-panel").locator("summary").click()

    expect(page.locator("#events-table")).to_be_visible(timeout=10_000)

    rows = page.locator("#events-tbody tr")
    expect(rows).to_have_count(2, timeout=10_000)

    table_text = page.locator("#events-table").inner_text()

    assert "line_crossing" in table_text
    assert "loitering" in table_text
    assert "cam_test" in table_text
    assert "cam_test2" in table_text


def test_behavior_events_panel_empty_state(page: Page):
    def empty_events(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"events":[],"output_dir":"/tmp"}',
        )

    page.route("**/api/events/recent", empty_events)

    page.goto(BASE_URL, wait_until="domcontentloaded")

    page.locator('button.tab-btn[data-tab="tools"]').click()
    page.locator("#events-panel").locator("summary").click()

    expect(page.locator("#events-status")).to_be_visible(timeout=10_000)
    expect(page.locator("#events-status")).to_contain_text(
        "No behavior events yet"
    )

    expect(page.locator("#events-table")).to_be_hidden()


def test_behavior_event_sse_creates_one_toast_per_event(page: Page):
    page.add_init_script(
        """
        (() => {
            class FakeEventSource {
                constructor(url) {
                    this.url = url;
                    this.onmessage = null;
                    this.onerror = null;
                    this.readyState = 1;
                    window.__testEventSources.push(this);
                }

                close() {
                    this.readyState = 2;
                }
            }

            window.__testEventSources = [];
            window.EventSource = FakeEventSource;
        })();
        """
    )

    page.goto(BASE_URL, wait_until="domcontentloaded")

    page.evaluate(
        """
        () => {
            const source = window.__testEventSources[0];

            const lines = [
                "2026-10-04 20:00:00,000 INFO normal pipeline message",
                "2026-10-04 20:00:01,000 INFO EVENT line_crossing at test_gate: track 1 (person) dir=right",
                "2026-10-04 20:00:02,000 INFO another normal log line",
                "2026-10-04 20:00:03,000 INFO EVENT loitering at test_zone: track 2 (person) dir=right"
            ];

            lines.forEach((line) => {
                source.onmessage({data: JSON.stringify(line)});
            });
        }
        """
    )

    toasts = page.locator("#notif-dock .notif-card")

    expect(toasts).to_have_count(2)

    titles = page.locator("#notif-dock .notif-title")
    expect(titles).to_have_count(2)

    for i in range(2):
        expect(titles.nth(i)).to_have_text("BEHAVIOR EVENT")

    messages = page.locator("#notif-dock .notif-msg")
    expect(messages.nth(0)).to_contain_text("line_crossing")
    expect(messages.nth(1)).to_contain_text("loitering")

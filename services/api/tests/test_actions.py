from synccut.core.actions import plan_with_rules, site_url, validate_actions


def words_of(sentence: str, start: int = 0, step: int = 300):
    return [{"w": w, "start_ms": start + i * step, "end_ms": start + i * step + 250} for i, w in enumerate(sentence.split())]


def plan(sentence: str):
    return [(a["type"], a["url"] or a["query"] or a["target"] or a["tab"]) for a in plan_with_rules(words_of(sentence))]


def test_open_google_then_search():
    assert plan("First I open Google. Then I search for AI engineering jobs and look at the results.") == [
        ("navigate", "https://www.google.com/"),
        ("search", "ai engineering jobs"),
    ]


def test_action_time_is_trigger_word():
    acts = plan_with_rules(words_of("Hi there. Now let's go to upwork.com quickly."))
    assert acts[0]["type"] == "navigate" and acts[0]["url"] == "https://upwork.com"
    assert acts[0]["at_ms"] == 4 * 300  # "go" is the 5th word


def test_spoken_domain():
    assert plan("Let me open make dot com for you.") == [("navigate", "https://make.com")]


def test_scroll_variants():
    assert plan("Scroll down to the requirements.") == [("scroll", "requirements")]
    assert plan("I'll scroll down a bit.") == [("scroll", "down")]
    assert plan("Scroll all the way down.") == [("scroll", "bottom")]
    assert plan("Now scroll back up.") == [("scroll", "top")]
    assert plan("I'll scroll down to see more results.") == [("scroll", "down")]  # purpose, not destination


def test_click_and_tabs():
    assert plan("Click the first result.") == [("click", "first result")]
    assert plan("Click on pricing.") == [("click", "pricing")]
    assert plan("Open a new tab and go to github.") == [("new_tab", 0), ("navigate", "https://github.com/")]
    assert plan("Switch back to the first tab.") == [("switch_tab", 0)]


def test_no_false_positives_on_plain_talk():
    assert plan("I have built this for twenty clients with five star reviews.") == []


def test_site_url():
    assert site_url("Stack Overflow") == "https://stackoverflow.com/"
    assert site_url("acme.io/pricing") == "https://acme.io/pricing"
    assert site_url("banana") == ""


def test_validate_sorts_and_cleans():
    out = validate_actions([
        {"type": "search", "at_ms": 5000, "query": "x"},
        {"type": "navigate", "at_ms": 1000, "url": "google"},
        {"type": "teleport", "at_ms": 0},
        {"type": "search", "at_ms": 9000, "query": ""},
    ], 10_000)
    assert [a["type"] for a in out] == ["navigate", "search"]
    assert out[0]["url"] == "https://www.google.com/" and out[0]["id"] == "a1"


def _words(text: str) -> list[dict]:
    return [{"w": w, "start_ms": i * 400.0, "end_ms": i * 400.0 + 350} for i, w in enumerate(text.split())]


JOB = "https://www.upwork.com/jobs/~0123456789abcdef"


def test_reference_to_the_linked_job_post_opens_it():
    from synccut.core.actions import open_page_first, plan_with_rules, validate_actions

    words = _words("Hi Sarah. I read your job post and you need a CRM. Then I'll scroll down to the requirements.")
    actions = validate_actions(plan_with_rules(words, JOB), 60_000)
    assert actions[0]["type"] == "navigate" and actions[0]["url"] == JOB
    assert actions[0]["at_ms"] == words[3]["start_ms"]  # at "read"
    assert open_page_first(actions, JOB) == actions  # already opened, nothing prepended


def test_linked_page_opens_first_when_narration_never_names_it():
    from synccut.core.actions import open_page_first, plan_with_rules, validate_actions

    words = _words("Hi there, scroll down and you will see what I mean.")
    actions = open_page_first(validate_actions(plan_with_rules(words, JOB), 60_000), JOB)
    assert actions[0]["type"] == "navigate" and actions[0]["url"] == JOB and actions[0]["at_ms"] == 0
    assert actions[1]["type"] == "scroll"


def test_no_link_means_no_page_references():
    from synccut.core.actions import plan_with_rules

    assert plan_with_rules(_words("I read your job post carefully."), "") == []


def test_page_link_must_be_public_web_url():
    from fastapi.testclient import TestClient
    from synccut.main import app

    client = TestClient(app)
    pid = client.post("/api/projects", json={"name": "page test"}).json()["id"]
    try:
        assert client.put(f"/api/projects/{pid}/page", json={"url": "javascript:alert(1)"}).status_code == 422
        assert client.put(f"/api/projects/{pid}/page", json={"url": "http://127.0.0.1:8000/"}).status_code == 422
        res = client.put(f"/api/projects/{pid}/page", json={"url": "8.8.8.8/jobs/1"})
        assert res.status_code == 200 and res.json()["page_url"] == "https://8.8.8.8/jobs/1"
    finally:
        client.delete(f"/api/projects/{pid}")


def test_title_from_url_for_screenshotted_pages():
    from synccut.capture import title_from_url

    assert title_from_url("https://www.upwork.com/jobs/CRM-Automation-Expert_~021234567890abcdef") == "CRM Automation Expert - Upwork"
    assert title_from_url("https://www.upwork.com/jobs/~021234567890abcdef") == "Upwork"
    assert title_from_url("https://acme.io/") == "Acme"


def test_screenshot_upload_replaces_capture_for_the_linked_page(tmp_path, monkeypatch):
    import io
    import subprocess
    from fastapi.testclient import TestClient
    from synccut.main import app

    png = tmp_path / "shot.png"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=white:s=800x1200",
                    "-frames:v", "1", str(png)], check=True)
    client = TestClient(app)
    pid = client.post("/api/projects", json={"name": "shot test"}).json()["id"]
    try:
        assert client.post(f"/api/projects/{pid}/page/screenshot", files={"file": ("a.png", png.read_bytes(), "image/png")}).status_code == 400
        client.put(f"/api/projects/{pid}/page", json={"url": "https://www.upwork.com/jobs/CRM-Expert_~0123456789ab"})
        bad = client.post(f"/api/projects/{pid}/page/screenshot", files={"file": ("a.svg", b"<svg><script>alert(1)</script></svg>", "image/svg+xml")})
        assert bad.status_code == 422
        res = client.post(f"/api/projects/{pid}/page/screenshot", files={"file": ("a.png", png.read_bytes(), "image/png")})
        assert res.status_code == 200
        shot = res.json()["page_shot"]
        assert shot["path"] == "page/shot.jpg" and shot["height"] == 2430  # 800x1200 scaled to the 1620 px page width
        # changing the link drops the screenshot
        res = client.put(f"/api/projects/{pid}/page", json={"url": "https://example.com/other"})
        assert res.json()["page_shot"] is None
    finally:
        client.delete(f"/api/projects/{pid}")


def test_capture_uses_the_screenshot_without_fetching(tmp_path):
    import subprocess
    from synccut.capture import capture_actions
    from synccut.core.actions import validate_actions

    jpg = tmp_path / "s.jpg"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=white:s=1620x2000",
                    "-frames:v", "1", str(jpg)], check=True)
    url = "https://www.upwork.com/jobs/CRM-Expert_~0123456789ab"
    actions = validate_actions([{"type": "navigate", "at_ms": 0, "url": url}, {"type": "scroll", "at_ms": 3000, "target": "requirements"}], 10_000)
    cap = capture_actions(actions, tmp_path / "out", lambda f, m: None, {url: {"path": jpg, "height": 2000, "uploaded_at": 1}})
    page = cap["pages"]["p1"]
    assert page["status"] == "ok" and page["title"] == "CRM Expert - Upwork" and page["height"] == 2000
    assert (tmp_path / "out" / "p1.jpg").exists()
    assert "scroll_text_not_found" not in cap["results"][actions[1]["id"]]["flags"]  # scrolls on the screenshot, no live lookup

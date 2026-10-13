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

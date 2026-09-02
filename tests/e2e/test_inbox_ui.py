"""Optional browser contract smoke for the CRM inbox."""

import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


@pytest.mark.e2e
def test_inbox_receive_send_assume_and_return(evidence) -> None:
    web_url = os.getenv("WEB_URL")
    if not web_url:
        pytest.skip("WEB_URL não configurada; execute o servidor web para o E2E")
    conversation_id = "11111111-1111-1111-1111-111111111111"
    conversation = {"id": conversation_id, "contact_id": "22222222-2222-2222-2222-222222222222", "channel": "SIMULATOR", "status": "OPEN", "control_state": "BOT_ACTIVE", "updated_at": "2026-08-31T12:00:00Z"}
    state = {"messages": []}
    browser = None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()

                def api(route):
                    path = route.request.url.split("/inbox", 1)[-1]
                    path_without_query = path.split("?", 1)[0]
                    if route.request.method == "POST" and path_without_query.endswith("/control"):
                        action = route.request.post_data_json["action"]
                        conversation["control_state"] = "HUMAN_ACTIVE" if action == "ASSUME" else "BOT_ACTIVE"
                        route.fulfill(status=200, content_type="application/json", body=json.dumps({"state": conversation["control_state"]}))
                    elif route.request.method == "POST" and path_without_query.endswith("/messages"):
                        content = route.request.post_data_json["content"]
                        state["messages"].append({"id": "33333333-3333-3333-3333-333333333333", "direction": "OUTBOUND", "message_type": "TEXT", "content": content, "created_at": "2026-08-31T12:01:00Z"})
                        route.fulfill(status=201, content_type="application/json", body='{"id":"33333333-3333-3333-3333-333333333333"}')
                    elif "/messages" in path:
                        route.fulfill(status=200, content_type="application/json", body=json.dumps({"items": state["messages"]}))
                    else:
                        route.fulfill(status=200, content_type="application/json", body=json.dumps({"items": [conversation]}))

                page.route("**/auth/login", lambda route: route.fulfill(status=200, content_type="application/json", body='{"tenant_id":"00000000-0000-0000-0000-000000000001"}'))
                page.route("**/inbox/**", api)
                page.goto(web_url)
                page.get_by_label("Token do proprietário").fill("test-only-token")
                page.get_by_role("button", name="Entrar").click()
                page.locator("button.conversation-row").first.wait_for()
                page.get_by_role("button", name="Assumir conversa").click()
                page.get_by_role("button", name="Devolver ao robô").wait_for()
                page.get_by_label("Mensagem").fill("Resposta de teste")
                page.get_by_role("button", name="Enviar").click()
                page.get_by_text("Resposta de teste").wait_for()
                page.get_by_role("button", name="Devolver ao robô").click()
                page.get_by_role("button", name="Assumir conversa").wait_for()
                evidence.step("receber conversa, assumir, enviar e devolver")
                page.screenshot(path=str(evidence.screenshot_path("inbox.png")), full_page=True)
            finally:
                if browser is not None:
                    browser.close()
    except PlaywrightError as exc:
        pytest.skip(f"browser Playwright indisponível: {exc}")

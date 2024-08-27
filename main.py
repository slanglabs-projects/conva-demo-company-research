from bs4 import BeautifulSoup
from conva_ai import ConvaAI
from fake_useragent import UserAgent
from playwright.sync_api import sync_playwright
import streamlit as st
import requests

st.title("AI Competitor Analyst")
st.caption("Powered by Conva.AI")
st.divider()


def scrape(url: str):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            user_agent = UserAgent().chrome
            context = browser.new_context(
                user_agent=user_agent,
                java_script_enabled=True,
                ignore_https_errors=True,
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_selector("body")

            previous_height = page.evaluate("document.body.scrollHeight")
            while True:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                page.wait_for_timeout(1000)  # Wait to load the page

                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == previous_height:
                    break
                previous_height = new_height
            content = page.content()
            context.close()

            soup = BeautifulSoup(content, "html.parser")
            for data in soup(["header", "footer", "nav", "script", "style"]):
                data.decompose()
            content = soup.get_text(strip=True)
            return content
    except (Exception,):
        return ""


def execute():
    if not st.session_state.company_id:
        return

    suffixes = [
        "",
        "company metrics",
        "mission",
        "vision",
        "milestones",
        "financial performance",
        "products and services",
        "funding",
    ]
    headers = {"Ocp-Apim-Subscription-Key": "39798b31fbfa426e9d4cb03f8200f1a7"}

    all_urls = []
    for suffix in suffixes:
        params = {
            "q": st.session_state.company_id + " " + suffix,
            "textFormat": "HTML",
            "count": 5,
        }
        response = requests.get(
            "https://api.bing.microsoft.com/v7.0/search", headers=headers, params=params
        )
        response.raise_for_status()
        search_results = response.json()
        for sr in search_results["webPages"]["value"]:
            url = sr["url"]
            if url not in all_urls and not "youtube" in url:
                all_urls.append(url)

    context = ""
    for index, url in enumerate(all_urls):
        print("Processing URL {} of {} [{}]".format(index, len(all_urls), url))
        st.text("Processing URL {} of {} [{}]".format(index, len(all_urls), url))
        content = scrape(url)
        context += "\n\n" + content

    client = ConvaAI(
        assistant_id="8bbc5fba6a6f4e2db83ac9d7a806730b",
        api_key="68e509b36d54471e8433d06f09a3207b",
        assistant_version="4.0.0",
    )

    streaming_response = client.invoke_capability_name(
        query="Generate a report for the given company. \n\nCompany Details: {}".format(
            context
        ),
        capability_name="company_report_generation",
        timeout=600,
        stream=True,
    )

    response = None

    for sr in streaming_response:
        print(sr)
        response = sr

    print("Final Response: " + str(response))
    st.header("Summary and Key Insights")
    st.text(response.parameters.get("summary_and_key_insights"), "Unavailable")

    st.header("Company Overview")
    st.text(response.parameters.get("company_overview", "Unavailable"))

    st.header("Company Metrics")
    metrics = response.parameters.get("company_metrics", [])
    st.text("\n".join(metrics))

    st.header("Company Mission")
    st.text(response.parameters.get("mission", "Unavailable"))

    st.header("Company Vision")
    st.text(response.parameters.get("vision", "Unavailable"))

    st.header("Key Milestones")
    milestones = response.parameters.get("milestones", [])
    st.text("\n".join(milestones))

    st.header("Financial Performance")
    st.text(response.parameters.get("financial_performance", "Unavailable"))

    st.header("Products and Services")
    ps = response.parameters.get("products_and_services", [])
    st.text("\n".join(ps))

    st.header("Funding Details")
    st.text(response.parameters.get("funding", "Unavailable"))


st.text_input("Company name or URL", key="company_id", on_change=execute)

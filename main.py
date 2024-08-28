from bs4 import BeautifulSoup
from cacheout import lru_memoize
from conva_ai import ConvaAI
from fake_useragent import UserAgent
from playwright.sync_api import sync_playwright
import os
import re
import requests
import streamlit as st
import tiktoken

st.set_page_config(page_title="AI Competitor Analyst - by Conva.AI")

# Hack to get playwright to work properly
os.system("playwright install")

SEARCH_SUFFIXES = [
    "",
    "company metrics",
    "mission and vision",
    "milestones",
    "financial performance",
    "products and services",
    "funding",
]

BING_SEARCH_API_KEY = st.secrets.bing_api_key

hide_default_format = """
       <style>
       #MainMenu {visibility: hidden; }
       footer {visibility: hidden;}
       </style>
       """
st.markdown(hide_default_format, unsafe_allow_html=True)


def num_tokens_from_string(string: str, model_name: str) -> int:
    encoding = tiktoken.encoding_for_model(model_name)
    num_tokens = len(encoding.encode(string))
    print("num tokens = {}".format(num_tokens))
    return num_tokens


def escape_braces(text: str) -> str:
    text = re.sub(r"(?<!\{)\{(?!\{)", r"{{", text)  # noqa
    text = re.sub(r"(?<!\})\}(?!\})", r"}}", text)  # noqa
    return text


def maybe_trim_context(context: str) -> str:
    length = len(context)
    tokens = num_tokens_from_string(context, "gpt-4o-mini")
    start = 0
    finish = length
    while tokens > 120 * 1000:
        finish = int(finish - 0.1 * finish)
        context = context[start:finish]
        tokens = num_tokens_from_string(context, "gpt-4o-mini")
    return context


@lru_memoize()
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


def get_md_normal_text(text):
    return "<p> {} </p>".format(text)


def get_md_list(arr):
    lis = ""
    for elem in arr:
        if "$" in elem:
            elem = elem.replace("$", "\\$")
        lis += "<li> {} </li>".format(elem)
    return "<list> {} </list>".format(lis)


if "ready" not in st.session_state:
    st.session_state.ready = False

if "success" not in st.session_state:
    st.session_state.success = False

if "reset" not in st.session_state:
    st.session_state.reset = True

st.image("conva.ai.svg", width=100)
st.title("AI Competitor Analyst")

with st.container(border=True):
    st.text_input("Company name or URL", key="company_id")
    col1, col2, col3 = st.columns([2, 2, 4])
    st.session_state.ready = col1.button("Generate Report")
    st.session_state.reset = col2.button("Reset")
    pbph = col3.empty()

rph = st.empty()
response = None

if st.session_state.reset:
    pbph.empty()
    rph.empty()
    st.session_state.ready = False
    st.session_state.success = False

if st.session_state.ready and st.session_state.company_id:
    progress = 5
    pb = pbph.progress(progress, "Gathering relevant information...")

    all_urls = []
    headers = {"Ocp-Apim-Subscription-Key": BING_SEARCH_API_KEY}
    for suffix in SEARCH_SUFFIXES:
        params = {
            "q": st.session_state.company_id + " " + suffix,
            "textFormat": "HTML",
            "count": 3,
        }
        response = requests.get(
            "https://api.bing.microsoft.com/v7.0/search",
            headers=headers,
            params=params,
        )
        response.raise_for_status()
        search_results = response.json()
        for sr in search_results["webPages"]["value"]:
            url = sr["url"]
            if url not in all_urls and "youtube" not in url:
                all_urls.append(url)

    progress += 5
    pb.progress(progress, "Processing search results...")

    context = ""
    suffix = ""

    pdelta = int(80 / len(all_urls))
    sdelta = int(len(all_urls) / (len(SEARCH_SUFFIXES) - 1))
    for index, url in enumerate(all_urls):
        progress += pdelta
        if index % sdelta == 0:
            sindex = int(index / sdelta) + 1
            sindex = min(sindex, len(SEARCH_SUFFIXES) - 1)
            suffix = SEARCH_SUFFIXES[sindex]
        prefix = "Researching" if "company" in suffix else "Researching company"
        pb.progress(progress, "{} {}...".format(prefix, suffix))
        content = scrape(url)
        context += "\n\n" + content

    client = ConvaAI(
        assistant_id=st.secrets.conva_assistant_id,
        api_key=st.secrets.conva_api_key,
        assistant_version="5.0.0",
    )

    progress += 5
    pb.progress(progress, "Generating report...")
    capability_context = {
        "company_report_generation": maybe_trim_context(escape_braces(context).strip())
    }

    response = client.invoke_capability_name(
        query="Generate a detailed report for the company whose details are provided. ({})".format(
            st.session_state.company_id
        ),
        capability_name="company_report_generation",
        timeout=600,
        stream=False,
        capability_context=capability_context,
    )

    pb.progress(100, "Completed")
    st.session_state.success = True

if st.session_state.success:
    with rph.container(border=True):
        st.header("Summary and Key Insights")
        st.markdown(
            get_md_normal_text(
                response.parameters.get("summary_and_key_insights", "Unavailable")
            ),
            unsafe_allow_html=True,
        )

        st.header("Company Overview")
        st.markdown(
            get_md_normal_text(
                response.parameters.get("company_overview", "Unavailable")
            ),
            unsafe_allow_html=True,
        )

        st.header("Company Metrics")
        metrics = response.parameters.get("company_metrics", [])
        st.markdown(get_md_list(metrics), unsafe_allow_html=True)

        st.header("Company Mission")
        st.markdown(
            get_md_normal_text(response.parameters.get("mission", "Unavailable")),
            unsafe_allow_html=True,
        )

        st.header("Company Vision")
        st.markdown(
            get_md_normal_text(response.parameters.get("vision", "Unavailable")),
            unsafe_allow_html=True,
        )

        st.header("Key Milestones")
        milestones = response.parameters.get("milestones", [])
        st.markdown(
            get_md_list(milestones),
            unsafe_allow_html=True,
        )

        st.header("Financial Performance")
        st.markdown(
            get_md_normal_text(
                response.parameters.get("financial_performance", "Unavailable")
            ),
            unsafe_allow_html=True,
        )

        st.header("Products and Services")
        ps = response.parameters.get("products_and_services", [])
        st.markdown(get_md_list(ps), unsafe_allow_html=True)

        st.header("Funding Details")
        st.markdown(
            get_md_normal_text(response.parameters.get("funding", "Unavailable")),
            unsafe_allow_html=True,
        )

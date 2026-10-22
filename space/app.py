"""RateCommons Explorer: negotiated health care prices (Transparency in Coverage) from Cigna, Aetna and UHC.

UI tabs for each analysis, the same functions as MCP tools (/gradio_api/mcp/), and a JSON API (/api/tool/<name>).
"""
from __future__ import annotations

import inspect
import json
import math
import os

import gradio as gr
import pandas as pd
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import engine as E

E.start_background()

NOTE = ("A missing rate means **no published rate**, not out of network. Rates are what payers published under the "
        "Transparency in Coverage rule (Oct 2026 files), not a patient's cost. % of Medicare uses the CY2026 "
        "physician fee schedule adjusted by the state's average locality GPCI, professional claims only. Provider names come from NPPES by NPI.")


def _records(df: pd.DataFrame, n: int = 300) -> list[dict]:
    if df is None or len(df) == 0:
        return []
    df = df.head(n).copy()
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].map(lambda v: v.hex() if isinstance(v, (bytes, bytearray)) else
                              (list(v) if hasattr(v, "tolist") and not isinstance(v, str) else v))
    out = json.loads(df.to_json(orient="records", date_format="iso", default_handler=str))
    return out


def _ui(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame({"result": ["No published rates match. (No published rate is not the same as out of network.)"]})
    return df.drop(columns=[c for c in ("pg_id",) if c in df.columns])


# ---------------------------------------------------------------- MCP / API tools (docstrings are the tool docs)

def lookup_rates(code: str, state: str, payer: str = "all", network: str = "", city: str = "", zip_prefix: str = "",
                 specialty: str = "", provider: str = "", billing_class: str = "", limit: int = 200) -> list[dict]:
    """Negotiated rates for one billing code in one US state, one row per payer product, provider group (TIN) and price.

    Args:
        code: billing code, e.g. CPT/HCPCS "99213", "70553", MS-DRG "470", revenue code
        state: two-letter state where the provider practices, e.g. "TX"
        payer: "cigna", "aetna", "uhc", a comma list, or "all"
        network: optional filter on product/network/plan/employer name, e.g. "Choice Plus", "OAP", "UNITED AIRLINES"
        city: optional practice city (NPPES), e.g. "Austin"
        zip_prefix: optional ZIP prefix, e.g. "787" or "78701"
        specialty: optional NUCC taxonomy text or code, e.g. "Orthopaedic Surgery", "Family Medicine", "207X00000X"
        provider: optional TIN (9 digits), NPI (10 digits) or provider name
        billing_class: optional "professional" or "institutional"
        limit: max rows (default 200)
    Returns rows with payer, product, tin, provider, npis_in_area, rate, negotiated_type, billing_class, setting,
    modifiers, place_of_service, medicare, pct_of_medicare.
    """
    return _records(E.lookup_rates(code, state, payer, network, city, zip_prefix, specialty, provider, billing_class, limit), 2000)


def market_distribution(code: str, state: str, payer: str = "all", network: str = "", city: str = "",
                        zip_prefix: str = "", specialty: str = "", billing_class: str = "professional",
                        group_by: str = "payer") -> list[dict]:
    """Distribution of negotiated rates for a code in a state: provider-group count, min/p10/p25/median/p75/p90/max,
    mean, Medicare amount and median % of Medicare. Each provider group counts once (its median published amount).

    Args:
        code: billing code, e.g. "99213"
        state: two-letter state, e.g. "NY"
        payer: "cigna", "aetna", "uhc", comma list, or "all"
        network: optional product/network/plan filter
        city: optional practice city
        zip_prefix: optional ZIP prefix
        specialty: optional taxonomy text or code (peer group)
        billing_class: "professional" (default), "institutional" or "" for both
        group_by: "payer" (default), "product", "setting" or "none"
    """
    return _records(E.market_distribution(code, state, payer, network, city, zip_prefix, specialty, billing_class, group_by))


def compare_providers(codes: str, state: str, providers: str, payer: str = "all", network: str = "") -> list[dict]:
    """Side-by-side rates of several providers for several codes, per payer product (median of published amounts).

    Args:
        codes: comma-separated billing codes, e.g. "99213,99214,73721"
        state: two-letter state
        providers: comma-separated TINs, NPIs or provider names, e.g. "Baylor Scott,742664409"
        payer: payer filter or "all"
        network: optional product/network filter
    """
    return _records(E.compare_providers(codes, state, providers, payer, network))


def benchmark_provider(provider: str, codes: str, state: str, payer: str = "all", specialty: str = "",
                       network: str = "") -> list[dict]:
    """How a provider's negotiated rates compare with peers in the same state (optionally same specialty):
    the provider's rate, peer p25/median/p75, percentile rank and % of Medicare for each code and payer product.
    Use it for "how does my practice's contract compare" questions.

    Args:
        provider: TIN, NPI or name of the provider/practice
        codes: comma-separated billing codes
        state: two-letter state
        payer: payer filter or "all"
        specialty: optional peer specialty (taxonomy text or code)
        network: optional product/network filter
    """
    return _records(E.benchmark_provider(provider, codes, state, payer, specialty, network))


def network_breadth(state: str, specialty: str = "", city: str = "", zip_prefix: str = "", payer: str = "all",
                    group_by: str = "product") -> list[dict]:
    """How many clinicians (NPIs) and TINs in an area have published rates in each payer product/network,
    and their share of all NPPES clinicians there. Use for comparing network breadth.

    Args:
        state: two-letter state
        specialty: optional taxonomy text or code, e.g. "Cardiovascular Disease"
        city: optional practice city
        zip_prefix: optional ZIP prefix
        payer: payer filter or "all"
        group_by: "product" (default) or "network"
    """
    return _records(E.network_breadth(state, specialty, city, zip_prefix, payer, group_by))


def provider_networks(provider: str, state: str = "") -> list[dict]:
    """Which payer products a provider has published rates in (by NPI, TIN, or name + state).

    Args:
        provider: NPI (10 digits), TIN (9 digits) or name
        state: two-letter state (required when searching by name)
    """
    return _records(E.provider_networks(provider, state))


def find_plans(query: str, payer: str = "all") -> list[dict]:
    """Find networks by product, plan or employer name (Aetna publishes plan/employer names; Cigna and UHC name
    files by product), e.g. "Choice POS II", "MCKESSON", "Options PPO", "OAP".

    Args:
        query: text to search
        payer: payer filter or "all"
    """
    return _records(E.find_plans(query, payer))


def list_products(payer: str = "all") -> list[dict]:
    """The payer products (network families) loaded, with network and plan counts.

    Args:
        payer: payer filter or "all"
    """
    return _records(E.list_products(payer))


def search_providers(name: str = "", state: str = "", specialty: str = "", city: str = "", npi: str = "",
                     limit: int = 50) -> list[dict]:
    """Search clinicians/organizations in NPPES (by NPI, or name/specialty/city within a state) and show the TINs
    payers list them under. Use to resolve a provider name to NPI/TIN before other tools.

    Args:
        name: provider or organization name (substring)
        state: two-letter state (required unless npi is given)
        specialty: taxonomy text, e.g. "Dermatology"
        city: practice city
        npi: a 10-digit NPI
        limit: max rows
    """
    return _records(E.search_providers(name, state, specialty, city, npi, limit))


def code_info(code: str) -> list[dict]:
    """Which payers publish a billing code, its type, published text where licensable (CPT text is withheld),
    and national Medicare physician fee schedule amounts.

    Args:
        code: billing code
    """
    return _records(E.code_info(code))


def medicare_rate(codes: str, state: str = "US") -> list[dict]:
    """Medicare physician fee schedule amounts (CY2026, non-facility and facility) for comma-separated HCPCS/CPT
    codes: national ("US") or adjusted by the state's mean locality GPCI.

    Args:
        codes: comma-separated codes, e.g. "99213,99214"
        state: two-letter state or "US" (national)
    """
    return _records(E.medicare_rate(codes, state))


def run_sql(sql: str, limit: int = 500) -> list[dict]:
    """Read-only SQL (DuckDB, one SELECT/WITH) for questions the other tools cannot answer. Views per payer
    (cigna, aetna, uhc): rate_<p>(billing_code_type, billing_code, code_id, ps_id, ns_id, pt_id),
    pt_<p>(pt_id, negotiated_type, rate_e4 [dollars x 10000], rate_raw, billing_class, setting, service_code,
    billing_code_modifier, ...), ps_pli_<p>(state, ps_id, pli_id), pli_pg_<p>(pli_id, pg_id),
    pg_<p>(pg_id, tin_type, tin_value, npi_count, tin_wide, business_names, states), pg_npi_<p>(state, pg_id, npi),
    ns_<p>(ns_id, network_id), pgnet_<p>(pg_id, network_id), code_<p>; shared: netlabel(payer, network_id, product,
    label, n_plans, file_names, plan_names), nppes(npi, entity_type, name, credential, city, state, zip5,
    taxonomy_code, taxonomy, classification, specialization), mcr(hcpcs, modifier, nonfacility_amount,
    facility_amount). Always filter rate_<p> by billing_code and ps_pli_<p>/pg_npi_<p> by state.

    Args:
        sql: the query
        limit: max rows
    """
    return _records(E.run_sql(sql, limit), 2000)


def data_status() -> dict:
    """What data is loaded (payers, products, networks) and whether the app is ready."""
    return json.loads(json.dumps(E.data_status(), default=str))


TOOLS = [lookup_rates, market_distribution, compare_providers, benchmark_provider, network_breadth, provider_networks,
         find_plans, list_products, search_providers, code_info, medicare_rate, run_sql, data_status]


# ---------------------------------------------------------------- UI

def public_url() -> str:
    """The app's public address: RC_PUBLIC_URL, or the first line of the file RC_URL_FILE (a tunnel writes it)."""
    u = os.environ.get("RC_PUBLIC_URL", "")
    f = os.environ.get("RC_URL_FILE")
    if not u and f and os.path.exists(f):
        u = open(f).read().strip().splitlines()[0] if open(f).read().strip() else ""
    return u.rstrip("/") or "https://<this-site>"


def _ask() -> str:
    return open(os.path.join(os.path.dirname(__file__), "ASK.md")).read().replace("{URL}", public_url())


def _err(fn):
    def w(*a):
        try:
            return _ui(fn(*a))
        except Exception as e:
            return pd.DataFrame({"error": [str(e)]})
    return w


PAYER_CHOICES = ["all", "cigna", "aetna", "uhc"]
CSS = ".gradio-container {max-width: 1300px !important}"

with gr.Blocks(title="RateCommons Explorer") as demo:
    gr.Markdown("# RateCommons Explorer\nNegotiated prices published by **Cigna, Aetna and UnitedHealthcare** "
                "(selected large networks), by code, place and provider. " + NOTE)
    status = gr.JSON(label="Data status", visible=True)
    with gr.Tab("Ask Claude (AI)"):
        ask_md = gr.Markdown(_ask())
    with gr.Tab("Rates lookup"):
        with gr.Row():
            c1, s1 = gr.Textbox(label="Billing code", value="99213"), gr.Textbox(label="State", value="TX")
            p1 = gr.Dropdown(PAYER_CHOICES, value="all", label="Payer")
            n1 = gr.Textbox(label="Network / product / employer", placeholder="Choice Plus, OAP, UNITED AIRLINES")
        with gr.Row():
            ci1, z1 = gr.Textbox(label="City"), gr.Textbox(label="ZIP prefix")
            sp1, pv1 = gr.Textbox(label="Specialty"), gr.Textbox(label="Provider (TIN, NPI or name)")
            bc1 = gr.Dropdown(["", "professional", "institutional"], value="", label="Billing class")
        b1 = gr.Button("Look up", variant="primary")
        o1 = gr.Dataframe(wrap=True)
        b1.click(_err(lambda *a: E.lookup_rates(*a, limit=1000)), [c1, s1, p1, n1, ci1, z1, sp1, pv1, bc1], o1, api_visibility="private")
    with gr.Tab("Market distribution"):
        with gr.Row():
            c2, s2 = gr.Textbox(label="Billing code", value="99213"), gr.Textbox(label="State", value="TX")
            p2 = gr.Dropdown(PAYER_CHOICES, value="all", label="Payer")
            n2 = gr.Textbox(label="Network / product")
        with gr.Row():
            ci2, z2, sp2 = gr.Textbox(label="City"), gr.Textbox(label="ZIP prefix"), gr.Textbox(label="Specialty")
            bc2 = gr.Dropdown(["professional", "institutional", ""], value="professional", label="Billing class")
            g2 = gr.Dropdown(["payer", "product", "setting", "none"], value="product", label="Group by")
        b2 = gr.Button("Distribution", variant="primary")
        o2 = gr.Dataframe(wrap=True)
        b2.click(_err(E.market_distribution), [c2, s2, p2, n2, ci2, z2, sp2, bc2, g2], o2, api_visibility="private")
    with gr.Tab("Compare providers"):
        with gr.Row():
            c3 = gr.Textbox(label="Codes (comma-separated)", value="99213,99214")
            s3 = gr.Textbox(label="State", value="TX")
            pv3 = gr.Textbox(label="Providers (TINs, NPIs or names, comma-separated)")
            p3 = gr.Dropdown(PAYER_CHOICES, value="all", label="Payer")
        b3 = gr.Button("Compare", variant="primary")
        o3 = gr.Dataframe(wrap=True)
        b3.click(_err(lambda c, s, pv, p: E.compare_providers(c, s, pv, p)), [c3, s3, pv3, p3], o3, api_visibility="private")
    with gr.Tab("Benchmark my practice"):
        with gr.Row():
            pv4 = gr.Textbox(label="Provider (TIN, NPI or name)")
            c4 = gr.Textbox(label="Codes", value="99213,99214,99215")
            s4 = gr.Textbox(label="State", value="TX")
            sp4 = gr.Textbox(label="Peer specialty (optional)")
            p4 = gr.Dropdown(PAYER_CHOICES, value="all", label="Payer")
        b4 = gr.Button("Benchmark", variant="primary")
        o4 = gr.Dataframe(wrap=True)
        b4.click(_err(lambda pv, c, s, sp, p: E.benchmark_provider(pv, c, s, p, sp)), [pv4, c4, s4, sp4, p4], o4, api_visibility="private")
    with gr.Tab("Network breadth"):
        with gr.Row():
            s5, sp5 = gr.Textbox(label="State", value="TX"), gr.Textbox(label="Specialty", value="Cardiovascular Disease")
            ci5, z5 = gr.Textbox(label="City"), gr.Textbox(label="ZIP prefix")
            p5 = gr.Dropdown(PAYER_CHOICES, value="all", label="Payer")
            g5 = gr.Dropdown(["product", "network"], value="product", label="Group by")
        b5 = gr.Button("Count", variant="primary")
        o5 = gr.Dataframe(wrap=True)
        b5.click(_err(E.network_breadth), [s5, sp5, ci5, z5, p5, g5], o5, api_visibility="private")
    with gr.Tab("Plans & networks"):
        with gr.Row():
            q6 = gr.Textbox(label="Product, plan or employer", value="Choice")
            p6 = gr.Dropdown(PAYER_CHOICES, value="all", label="Payer")
        with gr.Row():
            b6, b6b = gr.Button("Find plans", variant="primary"), gr.Button("List products")
        o6 = gr.Dataframe(wrap=True)
        b6.click(_err(E.find_plans), [q6, p6], o6, api_visibility="private")
        b6b.click(_err(E.list_products), [p6], o6, api_visibility="private")
    with gr.Tab("Providers"):
        with gr.Row():
            nm7, s7, sp7 = gr.Textbox(label="Name"), gr.Textbox(label="State", value="TX"), gr.Textbox(label="Specialty")
            ci7, npi7 = gr.Textbox(label="City"), gr.Textbox(label="NPI")
        with gr.Row():
            b7, b7b = gr.Button("Search NPPES", variant="primary"), gr.Button("Networks for this provider (NPI/TIN/name)")
        o7 = gr.Dataframe(wrap=True)
        b7.click(_err(lambda nm, s, sp, ci, npi: E.search_providers(nm, s, sp, ci, npi)), [nm7, s7, sp7, ci7, npi7], o7, api_visibility="private")
        b7b.click(_err(lambda nm, s, sp, ci, npi: E.provider_networks(npi or nm, s)), [nm7, s7, sp7, ci7, npi7], o7, api_visibility="private")
    with gr.Tab("Codes & Medicare"):
        with gr.Row():
            c8 = gr.Textbox(label="Code(s)", value="99213")
            s8 = gr.Textbox(label="State or US", value="US")
            b8, b8b = gr.Button("Code info", variant="primary"), gr.Button("Medicare PFS amounts")
        o8 = gr.Dataframe(wrap=True)
        b8.click(_err(E.code_info), [c8], o8, api_visibility="private")
        b8b.click(_err(E.medicare_rate), [c8, s8], o8, api_visibility="private")
    with gr.Tab("SQL"):
        gr.Markdown(inspect.getdoc(run_sql).split("Args:")[0])
        q9 = gr.Code(language="sql", value="SELECT payer, product, count(*) networks FROM netlabel GROUP BY ALL")
        b9 = gr.Button("Run", variant="primary")
        o9 = gr.Dataframe(wrap=True)
        b9.click(_err(E.run_sql), [q9], o9, api_visibility="private")

    for t in TOOLS:
        gr.api(t, api_name=t.__name__)
    demo.load(data_status, None, status, api_visibility="private")
    demo.load(_ask, None, ask_md, api_visibility="private")
    gr.Timer(20).tick(data_status, None, status, api_visibility="private")


# ---------------------------------------------------------------- JSON API for other front ends (CORS open)

app = FastAPI(title="RateCommons API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
_BY_NAME = {t.__name__: t for t in TOOLS}


@app.get("/api/tools")
def api_tools():
    return [{"name": t.__name__, "description": inspect.getdoc(t),
             "params": {k: (str(v.annotation.__name__ if hasattr(v.annotation, "__name__") else v.annotation),
                            None if v.default is inspect._empty else v.default)
                        for k, v in inspect.signature(t).parameters.items()}} for t in TOOLS]


@app.post("/api/tool/{name}")
async def api_tool(name: str, request: Request):
    fn = _BY_NAME.get(name)
    if not fn:
        return JSONResponse({"error": f"unknown tool {name}"}, 404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    sig = inspect.signature(fn)
    kwargs = {k: v for k, v in (body or {}).items() if k in sig.parameters}
    try:
        import anyio

        res = await anyio.to_thread.run_sync(lambda: fn(**kwargs))
        return JSONResponse({"ok": True, "rows": res} if isinstance(res, list) else {"ok": True, **res})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, 200)


app = gr.mount_gradio_app(app, demo, path="/", mcp_server=True, theme=gr.themes.Soft(), css=CSS, ssr_mode=False)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))

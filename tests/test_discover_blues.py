"""Other Blue companies' own networks in bcbs discovery (discover._blue_own_sources and the inclusion rule)."""
import gzip
import json
from types import SimpleNamespace

from ticdata import discover


def test_toc_in_network_reads_gzip_and_lists_of_objects():
    toc = {"reporting_structure": [{"in_network_files": [{"location": "https://h/a.json.gz"}, {"description": "x"}]}]}
    assert [x["location"] for x in discover._toc_in_network(json.dumps(toc).encode())] == ["https://h/a.json.gz"]
    raw = gzip.compress(json.dumps([toc, {"other": 1}]).encode())
    assert len(discover._toc_in_network(raw)) == 1


def test_sources_skip_a_broken_site_and_list_healthsparq_files(monkeypatch, capsys):
    meta = {"files": [{"fileSchema": "IN_NETWORK_RATES", "filePath": "2026-11-01/inNetworkRates/a.json.gz"},
                      {"fileSchema": "ALLOWED_AMOUNTS", "filePath": "2026-11-01/allowedAmounts/b.json.gz"}]}

    def get(s, url, timeout=300):
        if "broken" in url:
            raise RuntimeError("503")
        return SimpleNamespace(content=json.dumps(meta).encode(), text="")

    monkeypatch.setattr(discover, "_get", get)
    monkeypatch.setattr(discover, "BLUE_OWN", {"bad": ("static", ["https://broken/toc.json"]),
                                               "hs": ("healthsparq", "XYZ_I", "XYZ")})
    got = dict(discover._blue_own_sources(None))
    assert "bad" not in got and "bcbs bad: index unavailable" in capsys.readouterr().err
    files = [u for k, u, _ in got["hs"] if k == "file"]
    assert files == ["https://mrf.healthsparq.com/xyz-egress.nophi.kyruushsq.com/prd/mrf/XYZ_I/XYZ/"
                     "2026-11-01/inNetworkRates/a.json.gz"]


def test_bcbs_keeps_new_networks_and_skips_known_or_other_month_bluecard(monkeypatch):
    hcsc = {"reporting_structure": [{"in_network_files": [
        {"location": "https://bcbsil.mrf.bcbs.com/2026-10_363_A1B2_in-network-rates.json.gz?sig=1"}]}]}
    own = {"reporting_structure": [{"in_network_files": [
        {"location": "https://x.mrf.bcbs.com/2026-10_363_A1B2_in-network-rates.json.gz?sig=2"},   # known by name
        {"location": "https://x.mrf.bcbs.com/2026-10_363_C3D4_in-network-rates.json.gz"},         # new network
        {"location": "https://x.mrf.bcbs.com/2026-11_363_A1B2_in-network-rates.json.gz"},         # next month
        {"location": "https://mi.example/local_hmo_in-network-rates.json.gz"},                    # local product
        {"location": "https://mi.example/local_hmo_in-network-rates.json.gz?again"}]}]}            # listed twice
    monkeypatch.setattr(discover, "_bcbst_index_urls", lambda s: [])
    monkeypatch.setattr(discover, "BCBS_LANDINGS", {"bcbsil": "landing"})
    monkeypatch.setattr(discover, "_hcsc_index_urls", lambda s, landing: ["https://blob/toc/il_index.json"])
    monkeypatch.setattr(discover, "_get", lambda s, url, timeout=300: SimpleNamespace(content=json.dumps(hcsc).encode()))
    monkeypatch.setattr(discover, "_blue_own_sources", lambda s: [("bcbsm", [("toc", "https://hub/m_index.json",
                                                                               json.dumps(own).encode())])])
    _, entries = discover.bcbs(object())
    by = {e["name"]: e["listed_by"] for e in entries}
    assert by == {"2026-10_363_A1B2_in-network-rates.json.gz": "bcbsil",
                  "2026-10_363_C3D4_in-network-rates.json.gz": "bcbsm",
                  "local_hmo_in-network-rates.json.gz": "bcbsm"}


def test_a_reused_file_name_gets_the_company_in_front(monkeypatch):
    toc = lambda host: json.dumps({"reporting_structure": [{"in_network_files": [  # noqa: E731
        {"location": f"https://{host}/2026-09-21_000000061_in-network-rates_01_of_03.json.gz"}]}]}).encode()
    monkeypatch.setattr(discover, "_bcbst_index_urls", lambda s: [])
    monkeypatch.setattr(discover, "BCBS_LANDINGS", {})
    monkeypatch.setattr(discover, "_blue_own_sources", lambda s: [("highmark_pa", [("toc", "u1", toc("h/363"))]),
                                                                  ("highmark_bspa", [("toc", "u2", toc("h/378"))])])
    _, entries = discover.bcbs(object())
    assert [e["name"] for e in entries] == ["2026-09-21_000000061_in-network-rates_01_of_03.json.gz",
                                            "highmark_bspa_2026-09-21_000000061_in-network-rates_01_of_03.json.gz"]
    assert entries[1]["listed_name"] == entries[0]["name"]


def test_plan_match_by_company(monkeypatch):
    from ticdata import pipeline

    es = [{"kind": "in_network", "name": f"{c}.json.gz", "url": f"https://h/{c}", "size": 5, "listed_by": c}
          for c in ("bcbsm", "bcbsnc", "bsca")]
    monkeypatch.setitem(pipeline.PAYERS, "zz", lambda s: ({}, es))
    d = pipeline.plan("zz", 2, match=["by:bcbsm", "by:bcbsnc"], first_shard=28)
    assert sorted(f["name"] for sh in d["shards"] for f in sh["files"]) == ["bcbsm.json.gz", "bcbsnc.json.gz"]
    assert {sh["shard"] for sh in d["shards"] if sh["files"]} <= {28, 29}

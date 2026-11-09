"""Persistent-server entry for the RateCommons API (same code as the Vercel function in cloud/api).

Routes are identical to ratecommons.org's: /api/tool/<name>, /api/tools, /api/status, /api/health, /mcp (and the old
/gradio_api/mcp/). Tuning comes from environment variables (see Dockerfile): a big disk cache, memory for one-pass
queries, and a cap on how many questions run at once.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "api"))

from index import app  # noqa: E402,F401

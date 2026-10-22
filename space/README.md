---
title: RateCommons Explorer
emoji: 🩺
colorFrom: indigo
colorTo: green
sdk: gradio
sdk_version: 6.29.1
python_version: "3.12"
app_file: app.py
pinned: true
license: mit
short_description: Negotiated health care prices from Cigna, Aetna and UHC
tags: [mcp-server, healthcare, price-transparency]
---

# RateCommons Explorer

Negotiated prices that Cigna, Aetna and UnitedHealthcare publish under the Transparency in Coverage rule,
from the free RateCommons datasets (https://huggingface.co/ratecommons). Look up a code in an area, see the
distribution, compare providers, benchmark a practice against peers and Medicare, and compare network breadth.

Every analysis is also an MCP tool (`/gradio_api/mcp/`) and a JSON endpoint (`POST /api/tool/<name>`).
Source: https://github.com/Harshu-Pande/ratecommons (space/).

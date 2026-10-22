### Use Claude as your analyst (free with your own Claude account)

Every analysis on this site is also an **MCP tool**, so Claude can run them for you, chain them and explain the results.

1. In Claude (claude.ai or the desktop app): **Settings → Connectors → Add custom connector**.
2. Name: `RateCommons`. URL: `https://ratecommons-explorer.hf.space/gradio_api/mcp/`
3. In a chat, enable the RateCommons connector and ask, for example:
   - *What do Cigna, Aetna and UHC pay for a 99214 office visit in Houston? Show the spread and % of Medicare.*
   - *I'm a dermatology practice in Austin, TIN 123456789. How do my 99213/99214/11102 rates compare with other dermatologists in Texas?*
   - *Which payer product has the broadest cardiology network in Dallas?*
   - *Which networks cover United Airlines employees on Aetna, and what do they pay for an MRI of the knee (73721) in Chicago?*
   - *Estimate what a patient on UHC Choice Plus would be billed for a colonoscopy (45378) at a few Phoenix facilities.*
   - *How dispersed are prices for 70553 (MRI brain) across New York providers? Which TINs are in the top decile?*

Tools: `lookup_rates`, `market_distribution`, `compare_providers`, `benchmark_provider`, `network_breadth`,
`provider_networks`, `find_plans`, `list_products`, `search_providers`, `code_info`, `medicare_rate`, `run_sql`, `data_status`.

How to read results: a missing rate means *no published rate*, not out of network. Payer files list contracted
amounts, not what a patient pays (deductibles and coinsurance apply). `percentage` rates are percents, not dollars.

---
name: seo-audit
description: "Run full-site SEO audits and prioritize evidence-backed findings."
author: Daniel Agrici
license: MIT
---

# Full Website SEO Audit

## Process

1. **Render homepage** with `hermes seo run render_page.py <url> --mode auto --json` to capture raw HTML, rendered HTML, extracted text, SPA status, and accessibility data when needed.
2. **Detect business type** from homepage signals and crawl context (SaaS, local, ecommerce, publisher, agency, or other).
3. **Crawl the site** up to 500 pages, respecting robots.txt.
4. **Delegate independent specialist tasks** with Hermes `delegate_task` when available; otherwise load the same role skills and run the workflows inline, sequentially. `delegate_task` children start with fresh context, so include the site URL, relevant crawl/evidence paths, output directory, and exact role skill in every task's `context`. Load a role with `skill_view(name="hermes-seo:role-seo-<role>")`. Hermes allows up to 10 concurrent children by default; split larger sets into batches.

   Example for two independent roles:

   ```python
   delegate_task(tasks=[
       {
           "goal": "Audit technical SEO for example.com",
           "context": "Load hermes-seo:role-seo-technical with skill_view. Site URL: https://example.com. Crawl evidence: example.com-audit/crawl/. Write findings to example.com-audit/findings/technical.md and return evidence, recommendations, and limitations."
       },
       {
           "goal": "Audit schema markup for example.com",
           "context": "Load hermes-seo:role-seo-schema with skill_view. Site URL: https://example.com. Crawl evidence: example.com-audit/crawl/. Write findings to example.com-audit/findings/schema.md and return evidence, recommendations, and limitations."
       }
   ])
   ```

   Delegate these baseline roles in full audits when available: `hermes-seo:role-seo-technical` (robots.txt, sitemaps, canonicals, CWV, security headers), `hermes-seo:role-seo-content` (E-E-A-T, readability, thin content, AI citation readiness), `hermes-seo:role-seo-schema` (detection, validation, generation recommendations), `hermes-seo:role-seo-sitemap` (structure, quality gates, missing pages), `hermes-seo:role-seo-performance` (LCP, INP, CLS), `hermes-seo:role-seo-visual` (screenshots, mobile, above-fold), `hermes-seo:role-seo-geo` (AI crawler access, llms.txt, citability, brand mentions), `hermes-seo:role-seo-agentic` (Lighthouse Agentic Browsing fraction, agent accessibility, discovery files, WebMCP), and `hermes-seo:role-seo-sxo` (page-type mismatch, user stories, persona scoring; always include).

   Add conditional roles when their triggers apply: `hermes-seo:role-seo-local` for local businesses; `hermes-seo:role-seo-maps` for local businesses when DataForSEO MCP is available; `hermes-seo:role-seo-google` when Google credentials are configured and the user approves API use; `hermes-seo:role-seo-backlinks` when backlink credentials are configured and their use is approved (or for Common Crawl domain-level metrics); `hermes-seo:role-seo-cluster` when blog, pillar-page, or topic-cluster signals appear; `hermes-seo:role-seo-drift` when a baseline exists; and `hermes-seo:role-seo-ecommerce` for ecommerce sites. `hermes-seo:role-seo-dataforseo` may enrich the audit when DataForSEO MCP is available and the user approves live API use. `hermes-seo:role-seo-image-gen` may audit image strategy when Banana MCP is available; it produces a plan and never generates images. For FLOW-based content strategy, use `hermes-seo:role-seo-flow`.

   Matomo has no dedicated role skill in this package. When Matomo is configured and the user approves its use, run its reporting workflow inline; it can complement Google data or serve as a GA4 alternative. Do not attempt paid endpoints or send data to external providers without the user's explicit approval for that operation.
5. **Score** and aggregate findings into an SEO Health Score (0-100).
6. **Persist audit artifacts** under `{domain}-audit/`.
7. **Report** a prioritized action plan and offer the optional PDF/HTML report.

## Crawl Configuration

```
Max pages: 500
Respect robots.txt: Yes
Follow redirects: Yes (max 3 hops)
Timeout per page: 30 seconds
Concurrent requests: 5
Delay between requests: 1 second
```

## Output Files

- `{domain}-audit/FULL-AUDIT-REPORT.md`: Comprehensive findings
- `{domain}-audit/ACTION-PLAN.md`: Prioritized recommendations (Critical > High > Medium > Low)
- `{domain}-audit/audit-data.json`: Structured audit envelope for report generation
- `{domain}-audit/findings/*.md`: Per-category specialist findings (`technical.md`, `content.md`, `schema.md`, `performance.md`, `visual.md`, etc.)
- `{domain}-audit/screenshots/`: Desktop + mobile captures (if Playwright available)
- **PDF Report** (recommended): Generate a professional A4 PDF using `hermes seo run google_report.py --type full --data {domain}-audit/audit-data.json --domain <domain> --output-dir {domain}-audit/`. This produces a white-cover enterprise report with TOC, executive summary, charts (Lighthouse gauges, query bars, index donut), metric cards, threshold tables, prioritized recommendations with effort estimates, and implementation roadmap. Always offer PDF generation after completing an audit.

## Structured Audit Data Envelope

write_file `{domain}-audit/audit-data.json` with this shape so `hermes seo run google_report.py --type full --data {domain}-audit/audit-data.json --domain <domain> --output-dir {domain}-audit/` can generate a report even when Google API data is unavailable:

```json
{
  "summary": {
    "health_score": 0,
    "business_type": "detected type",
    "top_findings": [],
    "quick_wins": []
  },
  "categories": [
    {
      "name": "Technical SEO",
      "score": 0,
      "what_works": [],
      "findings": [
        {
          "title": "Finding title",
          "severity": "Critical|High|Medium|Low|Info",
          "description": "Evidence-backed detail",
          "recommendation": "Specific fix"
        }
      ]
    }
  ],
  "action_plan": {
    "phases": [
      {"name": "Phase 1: Critical Fixes", "timeframe": "Week 1", "items": []},
      {"name": "Phase 2: High-Impact Improvements", "timeframe": "Weeks 2-3", "items": []},
      {"name": "Phase 3: Content & Authority", "timeframe": "Month 2", "items": []},
      {"name": "Phase 4: Monitoring & Iteration", "timeframe": "Ongoing", "items": []}
    ]
  },
  "artifacts": {
    "findings_dir": "findings/",
    "screenshots_dir": "screenshots/"
  }
}
```

## Scoring Weights

| Category | Weight |
|----------|--------|
| Technical SEO | 22% |
| Content Quality | 23% |
| On-Page SEO | 20% |
| Schema / Structured Data | 10% |
| Performance (CWV) | 10% |
| AI Search Readiness | 10% |
| Images | 5% |

## Report Structure

### Executive Summary
- Overall SEO Health Score (0-100)
- Business type detected
- Top 5 critical issues
- Top 5 quick wins

### Technical SEO
- Crawlability issues
- Indexability problems
- Security concerns
- Core Web Vitals status

### Content Quality
- E-E-A-T assessment
- Thin content pages
- Duplicate content issues
- Readability scores

### On-Page SEO
- Title tag issues
- Meta description problems
- Heading structure
- Internal linking gaps

### Schema & Structured Data
- Current implementation
- Validation errors
- Missing opportunities

### Performance
- LCP, INP, CLS scores
- Resource optimization needs
- Third-party script impact

### Images
- Missing alt text
- Oversized images
- Format recommendations

### AI Search Readiness
- Citability score
- Structural improvements
- Authority signals

## Priority Definitions

- **Critical**: Blocks indexing or causes penalties (fix immediately)
- **High**: Significantly impacts rankings (fix within 1 week)
- **Medium**: Optimization opportunity (fix within 1 month)
- **Low**: Nice to have (backlog)

## DataForSEO Integration (Optional)

If DataForSEO MCP tools are available and the user approves live API use, delegate `hermes-seo:role-seo-dataforseo` alongside the other roles to enrich the audit with real SERP positions, backlink profiles with spam scores, on-page analysis (Lighthouse), business listings, and AI visibility checks (ChatGPT scraper, LLM mentions).

## Google API Integration (Optional)

If `GOOGLE_API_KEY` is available (`hermes_seo_run {"script":"google_auth.py","args":["--check"]}`) and the user approves the external request, delegate `hermes-seo:role-seo-google` for PageSpeed and CrUX field data. GSC, GA4, Google Ads, and Indexing API remain disabled in this catalog build.

## Matomo Integration (Optional)

If Matomo vault values are configured (`hermes_seo_run {"script":"matomo_auth.py","args":["--check"]}`) and the user approves the external request, run the Matomo extension reporting workflow inline to enrich the audit with self-hosted analytics; there is no Matomo role skill in this package. Matomo is the available analytics route while GA4 OAuth is disabled.

## Google Update Correlation

Before attributing a traffic or ranking change to anything, list the confirmed
Google updates in that window from the primary-source ledger:

```bash
hermes seo run seo_updates.py --since <yyyy-mm> --json
```

Every entry cites a Google-owned URL. If `freshness.stale` is true, say the
ledger may miss recent updates and check status.search.google.com before
drawing conclusions. A date overlap is a hypothesis, never proof of cause.

## Error Handling

| Scenario | Action |
|----------|--------|
| URL unreachable (DNS failure, connection refused) | Report the error clearly. Do not guess site content. Suggest the user verify the URL and try again. |
| robots.txt blocks crawling | Report which paths are blocked. Analyze only accessible pages and note the limitation in the report. |
| Rate limiting (429 responses) | Back off and reduce concurrent requests. Report partial results with a note on which sections could not be completed. |
| Timeout on large sites (500+ pages) | Cap the crawl at the timeout limit. Report findings for pages crawled and estimate total site scope. |
| A delegated role reaches its `max_iterations` limit on a large site | Findings are not lost: pass `output_dir/findings/<role>.md` in each task context and ask the child to write its first-pass findings there, then update the file before finishing. Use `read_file` to inspect any existing findings file and merge it into the report, noting when results may be partial. |

# Concrete news source evidence map

**Status:** Research appendix; not a launch commitment  
**As of:** 2026-07-15  
**Audience:** Hong Kong people and families in the UK  
**Scope:** Discovery interfaces only; no database, scoring, locality, evidence-store or RAG design

## Bottom line

The **18 directly testable interfaces** below are a verified candidate pool, not a requirement to activate all of them at launch. Choose the smallest subset that covers the agreed UK and Hong Kong utility beats; add sources only when shadow evidence shows a gap. A broad Brave query loop is not the default discovery engine.

Every URL marked **tested** returned a usable `200` response from the newsroom host on 2026-07-15. Endpoint existence and transport are therefore verified facts. The **suggested watch** column is a launch recommendation, not a frequency published or guaranteed by the source.

## Verified core candidates

### UK official and public-service sources

| ID | Beat and verified interface | Transport | What it catches | Suggested watch | Known gap |
|---|---|---|---|---|---|
| UK-01 | Immigration/status: [Home Office + UKVI all-content updates](https://www.gov.uk/search/all.atom?organisations%5B%5D=home-office&organisations%5B%5D=uk-visas-and-immigration&order=updated-newest) — **tested** | Atom feed | New or updated Home Office and UKVI publications, guidance and announcements | 30 minutes; retain entry IDs/updated times | A feed entry still needs inspection to identify the substantive change |
| UK-02 | Immigration/status: [British National (Overseas) visa](https://www.gov.uk/api/content/british-national-overseas-bno-visa) — **tested** | GOV.UK Content API JSON | Direct changes to the core BN(O) visa guidance | 30 minutes; compare `public_updated_at` and response hash | Does not catch related pages unless registered separately |
| UK-03 | Immigration/status: [Immigration Rules](https://www.gov.uk/api/content/guidance/immigration-rules) — **tested** | GOV.UK Content API JSON | Changes to the rules index and linked rule material | 30 minutes; compare `public_updated_at` and response hash | A changed index still needs follow-up on the affected rule document |
| UK-04 | Tax/benefits/work: [HMRC + DWP all-content updates](https://www.gov.uk/search/all.atom?organisations%5B%5D=hm-revenue-customs&organisations%5B%5D=department-for-work-pensions&order=updated-newest) — **tested** | Atom feed | Tax, benefits, pensions, employment-support and deadline announcements or guidance changes | Hourly | Broad organisations produce routine material; deterministic beat terms still need filtering |
| UK-05 | Education/families: [DfE + Ofqual all-content updates](https://www.gov.uk/search/all.atom?organisations%5B%5D=department-for-education&organisations%5B%5D=ofqual&order=updated-newest) — **tested** | Atom feed | School policy, exams, qualifications and family-relevant education changes | Hourly | Does not cover devolved education systems or individual councils/schools |
| UK-06 | Health/medicine: [DHSC + UKHSA + MHRA all-content updates](https://www.gov.uk/search/all.atom?organisations%5B%5D=department-of-health-and-social-care&organisations%5B%5D=uk-health-security-agency&organisations%5B%5D=medicines-and-healthcare-products-regulatory-agency&order=updated-newest) — **tested** | Atom feed | Public-health announcements, outbreaks, medicine/device notices and health-policy or guidance changes | 30 minutes | NHS operational disruption and local health-board notices are outside this feed |
| UK-07 | Parliament/law: [all Parliamentary Bills](https://bills.parliament.uk/rss/allbills.rss) — **tested**; listed by [UK Parliament](https://www.parliament.uk/site-information/rss-feeds/) | RSS/XML | New bills and bill-stage changes | Hourly; deduplicate by item GUID | Bills alone do not capture committee inquiries, statements or votes |
| UK-08 | Planned politics: [both Houses upcoming business](https://api.parliament.uk/egg-timer/houses/upcoming.ics) — **tested**; described by [Parliamentary Time](https://api.parliament.uk/egg-timer/meta/subscribe) | iCalendar | Scheduled Commons/Lords business and subsequent calendar changes | Fetch each morning and again before the next sitting day | Expected business can change and is not evidence that an event occurred |
| UK-09 | Economy/work/housing: [ONS upcoming releases](https://api.beta.ons.gov.uk/v1/search/releases?limit=100&release-type=type-upcoming&sort=release_date_asc) — **tested**; parameters are documented by [ONS](https://developer.ons.gov.uk/search/search-releases/) | JSON API | Confirmed/provisional statistics releases and date changes | Daily; check again around scheduled release time | ONS only; other official-statistics producers need later registration |
| UK-10 | Weather/safety: [Met Office UK severe-weather warnings](https://weather.metoffice.gov.uk/public/data/PWSCache/WarningsRSS/Region/UK) — **tested**; published in the [Met Office RSS directory](https://weather.metoffice.gov.uk/guides/rss) | Atom/XML | National and regional severe-weather warnings as issued | 5 minutes | National feed is noisy; register regional feeds after audience localities are known |
| UK-11 | Flood/safety: [Environment Agency current flood warnings and alerts](https://environment.data.gov.uk/flood-monitoring/id/floods?min-severity=3) — **tested** | JSON API | Current severe warnings, warnings and alerts in England; the [official reference](https://environment.data.gov.uk/flood-monitoring/doc/reference) says the listing is updated every 15 minutes | 15 minutes | England-focused; separate services are needed for Scotland and Northern Ireland, and surface-water coverage is limited |

### Hong Kong official sources

| ID | Beat and verified interface | Transport | What it catches | Suggested watch | Known gap |
|---|---|---|---|---|---|
| HK-01 | General government: [news.gov.hk top stories, Traditional Chinese](https://www.news.gov.hk/tc/common/html/topstories.rss.xml) — **tested**; listed in the [GovHK RSS directory](https://www.gov.hk/tc/about/rss.htm) | RSS/XML | Selected major HKSAR policy, public-service and breaking announcements | 15 minutes | Editorially selected, so not every departmental release appears |
| HK-02 | Weather/safety: [HKO warning summary, Traditional Chinese](https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=warnsum&lang=tc) — **tested**; documented in the [official DATA.GOV.HK dataset](https://data.gov.hk/tc-data/dataset/hk-hko-rss-weather-warning-summary) | JSON API | Warnings currently in force, including tropical-cyclone and rainstorm signals | 5 minutes | Current-state payload; detect both warning starts and cancellations |
| HK-03 | Transport/safety: [Transport Department Special Traffic News, Traditional Chinese](https://www.td.gov.hk/tc/special_news/trafficnews.xml) — **tested**; documented in the [official dataset](https://data.gov.hk/tc-data/dataset/hk-td-tis_19-special-traffic-news-v2/resource/7d32ca1a-7b9f-4e45-8ef0-ef64a324d654) | XML | Real-time incidents, status changes and special public-transport arrangements | 5 minutes; key on incident ID and status | High-volume ordinary incidents need a simple materiality filter |
| HK-04 | Education/families: [Education Bureau latest news, Traditional Chinese](https://www.edb.gov.hk/tc/whats_new_rss.xml) — **tested**; listed on the [EDB RSS page](https://www.edb.gov.hk/tc/rss/index.html) | RSS/XML | School, curriculum, examination and bureau-service updates | 30 minutes | School-specific closures/notices may appear elsewhere |
| HK-05 | Parliament/law: [LegCo Bills, Traditional Chinese](https://www.legco.gov.hk/tc/rss/cbills.xml) — **tested**; listed in the [LegCo RSS directory](https://www.legco.gov.hk/tc/rss/rss.html) | RSS/XML | New bills, papers and progress updates | Hourly | Committee work and scheduled meetings are separate feeds |

### Minimal media and outer radar

| ID | Interface | Transport | What it catches | Suggested watch | Known gap |
|---|---|---|---|---|---|
| RAD-01 | [RTHK local news, Traditional Chinese](https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml) — **tested** and listed by [GovHK](https://www.gov.hk/tc/about/rss.htm) | RSS/XML | Fast Hong Kong breaking-news leads and lived impact outside formal releases | 15 minutes | Media lead only; it does not replace the relevant primary source |
| RAD-02 | [BBC UK news](https://feeds.bbci.co.uk/news/uk/rss.xml) — **tested** and linked from the [BBC feed directory](https://www.bbc.co.uk/news/10628494) | RSS/XML | Broad UK breaking leads missed by the fixed official list | 15 minutes | Broad, duplicate-prone and weak on hyperlocal/community developments |
| RAD-03 | [GDELT DOC 2.0 endpoint](https://api.gdeltproject.org/api/v2/doc/doc) using a few repository-owned UK/Hong Kong query groups; capabilities are documented by [GDELT](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) | JSON or RSS API | Multilingual coverage and events outside known sources | **Hold:** the 2026-07-15 newsroom-host smoke test returned `429`; retry as an hourly shadow source only after a clean response | Noisy automated media index; result records are leads, not facts or evidence |

That is **18 verified candidates**: eleven UK official/public-service, five Hong Kong official and two media radar sources. They are an evidence pool, not eighteen required product components. RAD-03 is held and is not part of this count.

## Short expansion list

Add these only after a relevant gap appears. Rows marked **tested** returned `200` on 2026-07-15. “Registration” and “smoke-test failed” deliberately mean not day-one ready.

| Need | Exact interface and transport | Status and what it adds | Suggested watch after adoption |
|---|---|---|---|
| UK food recalls | [FSA Food Alerts API](https://data.food.gov.uk/food-alerts/id.json?_limit=50&_sort=-modified), JSON; [official API docs](https://data.food.gov.uk/food-alerts/ui/reference) | **Tested**; allergy alerts, product recalls and food alerts for action | 15 minutes |
| UK cyber/scams | [NCSC Threat Reports RSS](https://www.ncsc.gov.uk/api/1/services/v1/report-rss-feed.xml); [official feed directory](https://www.ncsc.gov.uk/information/rss-feeds) | **Tested**; major cyber advisories and threat reports | 30 minutes |
| UK unsafe products | [OPSS Product Safety alerts/recalls email subscription](https://www.gov.uk/product-safety-alerts-reports-recalls/email-signup); [official explanation](https://www.gov.uk/guidance/product-recalls-and-alerts) | Verified email route; consumer recalls beyond food/medicine | Parse incoming mail as delivered |
| UK housing/local government | [MHCLG all-content updates](https://www.gov.uk/search/all.atom?organisations%5B%5D=ministry-of-housing-communities-local-government&order=updated-newest), Atom | **Tested**; national housing and council policy or guidance changes | Hourly |
| UK rail disruption | [National Rail Disruptions API](https://www.nationalrail.co.uk/developers/online-journey-planner-data-feeds/), REST | Official interface exists but requires Rail Data Marketplace registration; add only after credentials and a live smoke test | 5 minutes during service hours |
| UK strategic roads | [National Highways breaking travel alerts](https://nationalhighways.co.uk/travel-alerts-rss/), RSS | **Tested**; high-priority incidents. The regional legacy feed linked by the official directory returned `404`, so do not enable it yet | 5 minutes |
| London transport | [TfL line status](https://api.tfl.gov.uk/line/mode/tube,overground,elizabeth-line,dlr/status), JSON; [official examples](https://tfl.gov.uk/cdn/static/cms/documents/example-api-requests.pdf) | **Tested**; useful only if audience needs or shadow evidence justify London-specific coverage | 5 minutes |
| HK statistics | [C&SD press releases, Traditional Chinese](https://www.censtatd.gov.hk/data/tc/press_release/rss.xml), RSS; listed by [GovHK](https://www.gov.hk/tc/about/rss.htm) | **Tested**; labour, prices, trade, population and economy releases | Hourly plus release-day checks |
| HK broader legislature | [Council meetings](https://www.legco.gov.hk/tc/rss/ccounmtg.xml), [all panels](https://www.legco.gov.hk/tc/rss/cpanels.xml), and [invitations for submissions](https://www.legco.gov.hk/tc/rss/cinvite_s.xml), RSS | All **tested**; agendas, committee work and consultations | Hourly; daily is enough for invitations |
| HK finance/consumer | [HKMA press releases API](https://api.hkma.gov.hk/public/press-releases?lang=tc&offset=0), JSON; [official docs](https://apidocs.hkma.gov.hk/chi/documentation/press-releases/) | **Tested**; banking, payments and monetary announcements | Hourly |
| HK investment/scams | [SFC press releases RSS](https://www.sfc.hk/TC/RSS-Feeds/Press-releases); [official feed directory](https://www.sfc.hk/TC/RSS-Feeds) | **Tested**; enforcement and investor warnings | 30 minutes |
| HK communications | [OFCA RSS](https://www.ofca.gov.hk/filemanager/ofca/tc/rss/index.xml), RSS; listed by [GovHK](https://www.gov.hk/tc/about/rss.htm) | **Tested**; telecoms, consultations and service information | Hourly |
| HK consumer issues | [Consumer Council press-release page](https://www.consumer.org.hk/tc/press-release?page=1), HTML | **Tested page**, but no official feed was found; use a narrow page-change selector | Hourly |
| HK government firehose | [all HKSAR press releases](https://www.info.gov.hk/gia/rss/general_zh.xml), RSS; officially listed by [GovHK](https://www.gov.hk/tc/about/rss.htm) | **Hold:** endpoint existence is verified, but strict TLS verification failed from the newsroom host and HTTP fallback returned `502`. Resolve the runtime CA chain or source-side fault before enabling; do not bypass certificate verification | 15 minutes only after a clean strict-TLS smoke test |
| HK health firehose | [CHP press releases](https://www.chp.gov.hk/rss/pressreleases_zh_tw_RSS.xml), RSS; officially listed by [GovHK](https://www.gov.hk/tc/about/rss.htm) | **Hold:** strict TLS verification failed from the newsroom host. Resolve the runtime CA chain or source-side fault before enabling; do not bypass certificate verification. Use [news.gov.hk Health & Community](https://www.news.gov.hk/tc/categories/health/html/articlelist.rss.xml), which **tested**, meanwhile | 15 minutes after a clean strict-TLS smoke test |

Local councils, NHS bodies, police forces, schools and local transport operators are intentionally absent. Add one only when an agreed beat or shadow evidence shows that it fills a material gap; their absence is not a reason to broaden national search.

## Hermes operating option

This is a research option, not authorisation to install a skill or create cron jobs. Its core behaviour is that Hermes should orchestrate change detection rather than search the whole web every time a schedule fires.

The official [Hermes watcher skill](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/devops/watchers/SKILL.md) demonstrates RSS/Atom and JSON watermarks. Hermes also documents [`no_agent` jobs](https://hermes-agent.nousresearch.com/docs/guides/cron-script-only) and a pre-check that can return `{"wakeAgent": false}` when nothing changed ([cron guide](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron)). Together they support the intended behaviour: unchanged checks stop without a model call, while changed item titles and URLs can be batched into one triage turn. Hermes supports interchangeable search backends ([official web-search guide](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/web-search.md)); the actual skill, adapters, schedule and provider are later implementation choices.

## Suggested shadow-validation sequence

If implementation is later authorised:

1. Select the smallest balanced subset of UK-01 to UK-11 and HK-01 to HK-05 that covers the agreed launch beats, then run only that subset in shadow mode.
2. Add RAD-01 and RAD-02 as lead-only comparators after the core subset is stable.
3. After RAD-03 returns a clean smoke test, run it in shadow mode with a few narrow UK/Hong Kong query groups; until then, use the bounded provider-neutral search lane for the daily recall sample.
4. Do not enable any expansion row until its parser succeeds against a live sample; for National Rail, HKSAR press releases and CHP this is an explicit unresolved prerequisite.

## Shadow-validation checklist

- Confirm every enabled interface still returns the expected transport and at least one parseable live or baseline item.
- Prove that an unchanged poll produces no Hermes agent wake-up.
- Trigger or replay one changed item from RSS, JSON, iCalendar and XML and confirm each reaches the triage batch once.
- Compare a week of official-source leads against RTHK, BBC and the GDELT shadow lane; record relevant stories found only by the radar.
- Record duplicates, routine noise and broken sources by interface, then add or remove endpoints—not broader keywords—to correct coverage.
- Add a council, NHS, police or local-transport source only when an agreed beat or shadow evidence justifies it.
- Keep Brave or any other paid search adapter out of the clocked source set; test it only through the same bounded recall lane if GDELT and direct sources leave a demonstrated gap.

# Polymarket / Kalshi market inefficiencies, strategy families and trader profitability (through 18 Nov 2026)

*Method note for the report writer: in this session every page fetch was blocked by the sandbox network allowlist (arxiv.org, jbecker.dev, karlwhelan.com, docs.polymarket.com, substack, beincrypto and others all failed to resolve), and the shared web-search budget ran out before the last two queries. Every finding below therefore comes from search-engine result summaries of the linked pages, not from reading the full documents. Numbers are reported as the summaries gave them; where a summary did not make clear which linked page a number came from I say "attribution uncertain". Where primary tables (e.g. returns by price bucket) could not be seen, that is listed under Gaps rather than filled in. Marketing/vendor sources are flagged "[vendor]".*

---

## 1. Trader profitability statistics (Polymarket and Kalshi)

### Takeaway
Across independent datasets, roughly 70-85% of Polymarket wallets lose money, the median retail loss is tiny (a few dollars), and profits are extremely concentrated (top 1% of winners take ~75-85% of gains). The consistent winners are liquidity providers using limit orders, automated accounts and a handful of informed/insider wallets; the consistent losers are market-order takers who buy longshots. Kalshi shows the same maker-over-taker transfer.

### Cited Findings
**Polymarket**
- Galaxy Research (published 2 Oct 2026; on-chain, ~2.9M "retail" accounts on the international platform): 69.2% of retail accounts ended below break-even, aggregate retail losses $338.9M; accounts classed as bots (more than 50 orders per active day) were excluded and collectively netted about $246.8M; the two figures do not offset exactly because of unresolved positions. — [Crypto Briefing](https://cryptobriefing.com/galaxy-research-polymarket-retail-losses/); [PANews](https://panews.io/articles/01a0fa0c-6ce9-7204-a3e2-f0d242a2ab74); [KuCoin flash](https://www.kucoin.com/news/flash/69-2-of-retail-accounts-on-polymarket-report-losses-total-losses-reach-338-9m)
- Galaxy: the median retail account was down about $3, i.e. losses in aggregate come from a smaller group losing much more. — [PredictionNews](https://predictionnews.com/story/galaxy-research-69-of-polymarket-retail-accounts-lose-money)
- Galaxy by theme: "experts" (>=5 category markets, >60% of activity in one theme) are 44.1% of traders; sports specialists have the lowest profitable share (25.1%); technology/science the highest (41.2%, smaller sample). Churn: 15.2% of losing accounts stop opening positions within 30 days vs 6.1% of profitable accounts. Caveats: data span includes the pre-fee era (before early 2026); one person can be several wallets. — [PANews](https://panews.io/articles/01a0fa0c-6ce9-7204-a3e2-f0d242a2ab74); [BigGo Finance](https://finance.biggo.com/news/7d87301a-ac22-449d-8030-22a2c9723ca4)
- Akey, Grégoire, Harvie & Martineau, "Who Wins and Who Loses in Prediction Markets? Evidence from Polymarket" (CEPR DP21615 / SSRN, 2026): on 588M trades ($67B volume) the top 1% of users with positive PnL capture 76.5% of profits; a later version (1.4M+ users, 2022-2025) reports the top 1% capture 84% of gains. — [CEPR DP21615](https://cepr.org/publications/dp21615); [OSC-hosted PDF](https://www.osc.ca/sites/default/files/2026-10/research-grant-competition-2026-who-wins-and-who-loses-in-prediction-markets.pdf)
- Same paper, mechanism: "successful traders provide liquidity using limit orders that resolve favorably ... while unsuccessful traders take liquidity using market orders"; longshot betting drives loss concentration; market-making strongly predicts positive performance; monthly performance is only modestly persistent (possibly selection rather than skill). — [CEPR DP21615](https://cepr.org/publications/dp21615); [Hacker News thread](https://news.ycombinator.com/item?id=48221877)
- Press reading of the same paper (25 May 2026): of 2,469,589 users, only ~30% (764,988) made money. — [GIGAZINE](https://gigazine.net/gsc_news/en/20260525-polymarket-win-or-lose/)
- Andrey Sergeenkov analysis (April 2026, ~2.5M wallets): 84.1% of wallets had not made a profit; a tiny fraction (reported as ~0.03-0.04% of addresses) captured the majority (>70%) of realised profits. — [KuCoin flash](https://www.kucoin.com/news/flash/84-of-polymarket-traders-are-losing-money-0-033-capture-majority-profits); [Blockport](https://blockport.io/latest-news/polymarket-most-traders-lose-money-0-04pct-captured-3-7b/)
- Motley Fool analysis (~313,000 wallets, markets resolved in 2025, pre-fee): ~17% of wallets profitable, >82% lost; top 1% of profitable wallets won ~85% of profits, top 5% >96%. — [Motley Fool](https://www.fool.com/research/prediction-markets-vs-stock-market-returns/)
- Bloomberg analysis (headline only seen): about 100,000 Polymarket wallets lost at least $1,000. — [Finance Magnates](https://www.financemagnates.com/fintech/100000-polymarket-wallets-lost-at-least-1000-bloomberg-analysis-shows/)
- Counter-framing: most losing traders lose small amounts while liquidity/profit concentrates at the top. — [DeFi Rate](https://defirate.com/news/polymarkets-loss-stats-hide-a-different-reality/)
- A working paper using every Polymarket trade 2023-2025 (reported 26 Apr 2026) finds ~3% of traders account for most price discovery, i.e. accuracy is driven by a small informed group, not "the crowd". — [CoinDesk](https://www.coindesk.com/markets/2026/04/26/only-3-of-traders-drive-prediction-markets-accuracy-not-the-crowd-study-finds)
- Secondary claim: an analysis of 95M Polymarket transactions found only 0.51% of wallets achieved profits above $1,000. — [Digitech Bytes](https://digitechbytes.com/emerging-consumer-tech-explained/are-polymarket-trading-bots-actually-profitable-the-math-behind-2026-s-predictio/) (secondary, not verified)

**Kalshi**
- Bürgi, Deng & Whelan, "Makers and Takers: The Economics of the Kalshi Prediction Market" (UCD WP July 2025; CESifo/CEPR; GWU WP Feb 2026; >300,000 contracts): average return across all contracts about -20% before fees and -22% after fees; takers lose almost 32% on average, makers about 10%. — [VoxEU column](https://cepr.org/voxeu/columns/economics-kalshi-prediction-market); [GWU WP 2026-001](https://www2.gwu.edu/~forcpgm/2026-001.pdf); [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5502658)
- Jon Becker, "The Microstructure of Wealth Transfer in Prediction Markets" (Jan 2026; 72.1M Kalshi trades, $18.26B volume, June 2021-Nov 2025): takers earn -1.12% mean excess return per trade, makers +1.12%; takers have negative excess returns at 80 of 99 price levels; the gap did not exist early on (takers were positive in Kalshi's early days) and emerged as volume/professional makers arrived. — [jbecker.dev](https://www.jbecker.dev/research/prediction-market-microstructure); [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7217640); [Hacker News](https://news.ycombinator.com/item?id=46680515)
- Roosevelt Institute (July 2026): "ordinary users" lost more than half a billion dollars (headline figure $583M) from July 2021 to May 2026; Kalshi disputes it as miscounting institutional market-maker flow as ordinary users; the Dune tables it relied on were disabled on 15 May 2026. — [Roosevelt Institute](https://rooseveltinstitute.org/blog/since-kalshis-launch-ordinary-users-have-lost-half-a-billion-dollars/); [PredictionMarkets.us](https://predictionmarkets.us/articles/kalshi-retail-traders-583-million-losses-roosevelt-institute-2026)
- Kalshi's own study (Oct 2026; 325 high-profit accounts in Sept 2026, sports excluded): 82% of high earners have no Wall Street background. Company-produced, selective sample. — [KuCoin flash](https://www.kucoin.com/news/flash/kalshi-study-82-of-high-earning-traders-lack-wall-street-experience)
- Anecdote of a specialist individual: Bloomberg feature (13 Oct 2026) on Kalshi's top inflation trader "beating Wall Street banks from his garage". — [Bloomberg](https://www.bloomberg.com/news/features/2026-10-13/kalshi-s-top-inflation-trader-beats-wall-street-banks-from-his-garage)
- Sportico analysis relayed in coverage: retail lost roughly $117M on Kalshi parlays alone in Jan-Apr 2026 (attribution uncertain; seen only in a search summary). — [PredictionMarkets.us](https://predictionmarkets.us/articles/kalshi-retail-traders-583-million-losses-roosevelt-institute-2026)

### Inferences
- The base rate for an unspecialised retail account is a small loss; a bot that simply "trades opinions with market orders" should expect to sit in the 70-85% losing majority. The documented winning traits (limit orders, avoiding longshots, specialisation) are compatible with a slow bot; the other winning traits (speed, inside information) are not.
- "Share profitable" depends heavily on definition (realised vs total PnL, all wallets vs retail, period): ~30% (Akey press reading), ~31% retail (Galaxy), ~16-17% (Sergeenkov, Motley Fool). Use "roughly 15-30%" rather than a point figure.
- Most datasets pre-date or straddle the 2026 fee rollout, so post-fee taker outcomes are, if anything, worse than these numbers.

### Gaps
- A Solidus Labs figure (Dec 2025-Feb 2026: 0.55% of profitable maker wallets earned 50% of maker profit), a "63.5% of profitable addresses earned $0-$1,000" figure and a Gini 0.865 / "72% profitable" analysis (242,640 traders, 2021-2024, conflicts with everything else) appeared in a search summary without a clear source page; not verified.
- Could not open the Galaxy report or the Akey et al. PDF, so the breakdown of profit by actor type (market makers vs arbitrage bots vs insiders) is not quantified here.
- No Kalshi per-user profitable-share statistic comparable to Polymarket's was found.

---

## 2. Favourite-longshot bias, price-level calibration, and "always bet No"

### Takeaway
A favourite-longshot bias (cheap contracts overpriced, expensive ones slightly underpriced) is well documented on Kalshi and present but weaker, category-dependent and partly disputed on Polymarket; it is concentrated in taker flow and below ~20c, and appears to have shrunk since 2025. "Always bet No" is not a reliable edge: Yes is somewhat overpriced early in sensational markets, but No is priced high enough that the naive strategy has not clearly paid.

### Cited Findings
**Kalshi**
- Bürgi/Deng/Whelan: prices are informative and improve toward close but "display a clear favorite-longshot bias"; low-price contracts win less often than needed to break even, high-price contracts win more often "and yield small positive returns"; the bias is much stronger for prices accepted by takers; there is "some evidence of a weakening" (the 2025 bias coefficient is smaller and less significant). — [VoxEU](https://cepr.org/voxeu/columns/economics-kalshi-prediction-market); [UCD WP2025_19](https://www.ucd.ie/economics/t4media/WP2025_19.pdf); [GWU WP](https://www2.gwu.edu/~forcpgm/2026-001.pdf)
- Becker (Kalshi 2021-Nov 2025): contracts trading at 5c won only 4.18% of the time; YES contracts underperform equivalently priced NO contracts, especially at longshot prices (an "optimism tax" on affirmative-framed taker flow); makers profit by passively selling into that demand rather than by forecasting better. — [jbecker.dev](https://www.jbecker.dev/research/prediction-market-microstructure); [jbecker.dev research index](https://www.jbecker.dev/research)
- Becker by category: finance markets are near-efficient (0.17 percentage-point maker-taker gap) while entertainment and media show gaps above 7 points. — [daily.dev summary](https://app.daily.dev/posts/the-microstructure-of-wealth-transfer-in-prediction-markets-ulhf5ydzn); [jbecker.dev](https://www.jbecker.dev/research/prediction-market-microstructure)
- Independent replication (hrishi-tailor, v1.0-1.2, Oct 2026; 46,168 resolved markets: 16,533 Kalshi, 29,635 Polymarket; prices at 30d/7d/1d/1h before close): Kalshi calibration slope rises from 1.02 (30 days) to 1.11 (1 day) to 1.22 (1 hour); Kalshi longshots <=5%: 82 wins expected, 60 happened; bias was strongest before 2025 (slope 1.31) and about 1.04-1.13 since; 18 of 19 significant results survive Benjamini-Hochberg correction. — [GitHub repo](https://github.com/hrishi-tailor/prediction-market-calibration); [v1.1.0 release](https://github.com/hrishi-tailor/prediction-market-calibration/releases/tag/v1.1.0)
- Kalshi macro: the favourite-longshot bias shows up in inflation and employment markets but is absent in Fed/interest-rate markets. — [ResearchGate: Information Efficiency Across Macroeconomic Prediction Markets](https://www.researchgate.net/publication/409472804_Information_Efficiency_Across_Macroeconomic_Prediction_Markets_Evidence_from_Kalshi); [ResearchGate: FLB in Unemployment Prediction Markets](https://www.researchgate.net/publication/409238145_Market_Efficiency_and_the_Favorite-Longshot_Bias_in_Unemployment_Prediction_Markets)
- Kalshi sports (Moshrefi, arXiv 2607.14430, 15 Jul 2026; 23M moneyline trades): calibration is near-perfect mid-life and departs sharply near expiry; cross-game parlays trade above the product of their legs, more so with more legs. — [arXiv 2607.14430](https://arxiv.org/abs/2607.14430)

**Polymarket**
- Cardozo & Rivero-Wildemauwe (arXiv 2609.12878, 11 Sep 2026; 588M trades, 2.48M accounts): under equal weighting longshots lose money and favourites earn gains, but "the favorite-longshot bias is therefore not universal across Polymarket"; crypto and politics give the clearest two-sided bias; weather's longshot return changes sign depending on weighting; frequent longshot buyers do no worse than other longshot buyers, frequent favourite buyers earn less than other favourite buyers. — [arXiv 2609.12878](https://arxiv.org/abs/2609.12878)
- Qin & Yang, "Polymarket-v1 Database" (arXiv 2606.04217, June 2026): tokens priced <=0.30 have negative mean realised returns, tokens >=0.40 positive; in the 0.00-0.10 bucket (avg price 0.052, ~34.9M trades) mean return (payout minus price) is -0.0023. — [arXiv 2606.04217](https://arxiv.org/abs/2606.04217)
- Reichenbach & Walther (SSRN 2025/2026), as described by later papers: "little evidence of a general longshot bias on Polymarket at the market level". A master's thesis extending their method on Polymarket sports argues the aggregate null hides opposite-signed deviations across price bands. — [Vernimmen-hosted thesis](https://www.vernimmen.net/ftp/where_crowds_get_it_wrong__probability_band_mispricing_on_polymarket.pdf); [arXiv 2609.12878](https://arxiv.org/abs/2609.12878)
- hrishi-tailor replication: Polymarket shows no favourite-longshot bias; mid-range prices (5-95c) are slightly *overconfident* close to resolution (slope 0.91-0.93). — [GitHub repo](https://github.com/hrishi-tailor/prediction-market-calibration)
- PDiTO pm-calibration (2026 markets, both venues): prices with real two-sided quotes are close to calibrated one day and thirty days out; "there is a small favourite-longshot bias, and it lives at the cheap end" (below ~20c, wide intervals). — [GitHub repo](https://github.com/PDiTO/pm-calibration)
- Le, "Decomposing Crowd Wisdom" (arXiv 2602.19520; 353M trades, 429K binary contracts, Kalshi + Polymarket): most robust pattern is persistent *underconfidence in political markets* (prices compressed toward 50%), replicating on Polymarket; on Kalshi large political trades (>100 contracts) have calibration slope 1.74 vs 1.19 for single-contract trades. — [arXiv 2602.19520](https://arxiv.org/abs/2602.19520)
- Dubach microstructure paper (arXiv 2604.24366, rev. May 2026; 600 markets, 30B book events, 255M trades): Polymarket shows "pronounced longshot spread premia" (i.e. longshots are also the most expensive to trade). — [arXiv 2604.24366](https://arxiv.org/abs/2604.24366)
- Weather (Qiu & Qiu, arXiv 2610.13593, 9 Oct 2026; daily max-temperature markets, 10 cities, one-month test): the bias is reversed in location: distant-horizon longshots are only slightly overpriced, most mid/low buckets are near-calibrated, and the big error is *favourites overpriced in the last 1-12 hours* before settlement; buying NO on an overpriced favourite can be profitable despite a low win rate, while buying NO on a longshot "yields little after fees". — [arXiv 2610.13593](https://arxiv.org/abs/2610.13593)

**"Nothing ever happens" / always bet No**
- Polymarket's own accuracy page shows 73.3% of resolved markets resolving No vs 26.7% Yes; an independent recount of 4,763 resolved binary markets found ~52.3% No overall, 57% for non-sports and 59.3% for "Will X happen?" framings, concluding the 73% is a filtered/multi-outcome artefact (attribution between the two analysis pages uncertain). — [Yahoo Finance/Decrypt](https://finance.yahoo.com/markets/options/articles/nothing-ever-happens-bot-always-151603375.html); [DEV Community analysis](https://dev.to/manja316/i-collected-89-million-polymarket-price-points-heres-what-i-found-about-how-markets-really-move-2dil); [Delta Confidence](https://deltaconfidence.substack.com/p/nothing-ever-happens)
- LessWrong analysis: one week after opening, YES in "non-garbage" markets is overpriced by ~1.5x on Polymarket (2.1x on Manifold), with the caveat that sample filtering may contribute and Polymarket had few qualifying markets. — [LessWrong](https://www.lesswrong.com/posts/zu3YnojJ8dXWzxmWd/manifold-and-polymarket-are-biased-against-nothing-ever-1)
- The public "Nothing Ever Happens" always-No bot (April 2026) caps No purchases at 65c; its creator told followers not to expect profits, and one outlet reports the creator "keeps losing money"; one analysis notes that at typical No prices (65-85c) "the math doesn't work". — [Yahoo Finance/Decrypt](https://finance.yahoo.com/markets/options/articles/nothing-ever-happens-bot-always-151603375.html); [CryptoNews.net](https://cryptonews.net/news/finance/32705033/)

### Inferences
- Rough magnitude on Polymarket: -0.0023 on an average 0.052 price is about -4% of stake per longshot purchase before spread and fees; on Kalshi a 5c contract winning 4.18% is about -16% of stake. The Polymarket bias is real in sign but several times smaller than Kalshi's, and two independent calibration projects find it negligible outside the <20c tail.
- The exploitable form of the bias is "be the maker selling longshot YES / buying favourite NO to optimistic takers", not "take the favourite at the ask": taker-side returns on favourites are only "small positive" and must cover spread plus the 2026 taker fee.
- Category matters more than the headline: bias evidence is strongest in crypto, politics and entertainment-type markets; finance/Fed markets are near-efficient; weather has a different (late-favourite) error; sports is near-calibrated until just before expiry.
- Political prices compressed toward 50% (underconfidence) is the same phenomenon viewed from the other end: heavy favourites in politics have historically been underpriced. That is a slow-bot-compatible tilt, but it comes from datasets dominated by the 2024 cycle.
- The decay on Kalshi (slope 1.31 pre-2025 to 1.04-1.13 since) suggests the easy version of this edge is being competed away as professional makers scale.

### Gaps
- The bucket-by-bucket return tables (Bürgi et al.; Becker; Qin & Yang deciles above 0.10; Cardozo by category) could not be read; expected return by price bucket x category x maker/taker is therefore only partially quantified.
- No Polymarket maker-vs-taker return by price level equivalent to Becker's Kalshi table was retrieved (Becker's GitHub dataset covers Polymarket, but results were not seen).
- hrishi-tailor's "does it survive trading costs" return figures (buy-Yes/buy-No after fees) were not visible.
- No rigorous test of "always No" restricted to sensational/geopolitical markets with post-2026 fees was found.

---

## 3. High-probability "bond" strategy (95-99c near resolution) and holding rewards

### Takeaway
Evidence supports a small positive average return on high-priced contracts, but no audited study of the 95-99c bond strategy's realised annualised return was found; the payoff is short-volatility (one loss erases ~19 wins at 95c), a large part of the apparent yield is compensation for capital lock-up and settlement delay, and resolution/adjudication risk is real. Polymarket's 4% holding reward applies to a limited list of long-dated markets and does not turn it into a bond.

### Cited Findings
- High-priced contracts earn small positive average returns on Kalshi; high-probability tokens (>=0.40) show positive mean realised returns on Polymarket; favourites earn gains under equal weighting. — [VoxEU](https://cepr.org/voxeu/columns/economics-kalshi-prediction-market); [arXiv 2606.04217](https://arxiv.org/abs/2606.04217); [arXiv 2609.12878](https://arxiv.org/abs/2609.12878)
- Gebele & Matthes, "When Certainty Is Not Worth It: Capital Lock-Up and Settlement Discounting in Prediction Markets" (arXiv 2605.31431, 29 May 2026): because collateral is locked until oracle settlement, "a near-certain dollar is a delayed dollar"; prices embed a maturity-dependent settlement discount; adjusting for it removes roughly 48-88% of the near-certainty horizon gradient, i.e. much of the apparent underpricing of near-certain outcomes is a priced friction, not forecast error. — [arXiv 2605.31431](https://arxiv.org/abs/2605.31431)
- Payoff asymmetry: at a 95c entry "one failed bond wipes out 19 successful ones". — [StartPolymarket bonding guide](https://startpolymarket.com/strategies/bonding/) [vendor/guide]
- Practitioner claims (interview with a trader "fish", relayed by Odaily/BlockBeats and reprinted): ~90% of large orders above $10,000 execute above 0.95; whales sometimes dump to ~0.90 to shake out retail then rebuy; black swans include a finished match being ruled invalid or a settled political event being overturned. Anecdotal, not measured. — [Gate Learn](https://www.gate.com/learn/articles/the-quiet-arbitrageurs-making-fortunes-on-polymarket/12914); [Bitget News](https://www.bitget.com/news/detail/12560605013379)
- Illustrative (unaudited) returns: 1-5% per trade; a bot README cites 4.1% overnight ROI on one example. An open-source backtest framework exists for entries at 0.90/0.95/0.97/0.99 with fees, but no published results were found. — [LaunchPoly guide](https://launchpoly.com/blog/polymarket-trading-strategies-2025) [vendor]; [GitHub MatBbk/polymarket-tailend-backtest](https://github.com/MatBbk/polymarket-tailend-backtest)
- Late-stage mispricing can go the wrong way: in weather markets the largest error is favourites *overpriced* in the final 1-12 hours; Polymarket mid-range prices are slightly overconfident near resolution. — [arXiv 2610.13593](https://arxiv.org/abs/2610.13593); [GitHub hrishi-tailor](https://github.com/hrishi-tailor/prediction-market-calibration)
- Dispute frequency (sources disagree): UMA is cited as saying ~99.4% of Polymarket markets resolve without dispute; other guides say "well under 1%" or "roughly 95% never challenged". A second dispute goes to UMA token-holder vote (~4-6 days in total); positions cannot be redeemed until it completes. — [NexusFi](https://nexusfi.com/a/prediction-markets/polymarket-uma-oracle-dispute); [PolySyncer](https://www.polysyncer.net/blog/polymarket-uma-oracle-explained/); [CopyTradeInsider](https://www.copytradeinsider.com/blog/polymarket-uma-oracle-explained/)
- Adjudication risk, academic: in disputed Polymarket markets prices forecast the adjudication rather than the event; the adjudicated outcome diverges from an independent audit of the rule-implied outcome in up to one disputed market in eight (primary coding) and about one in thirty when every flagged case is included. — [ScienceDirect (Economics Letters, 2026)](https://www.sciencedirect.com/science/article/abs/pii/S0165176526003721)
- Zelensky "suit" market (resolved No in July 2025 after a prolonged UMA dispute; >$237M volume; critics alleged whale-concentrated UMA voting, UMA denied manipulation). — [Decrypt](https://decrypt.co/329210/polymarket-rules-no-237m-bet-zelenskyys); [The Defiant](https://thedefiant.io/news/nfts-and-web3/polymarket-controversy-heats-up-after-the-zelenskyy-suit-market-resolves)
- LLMs cannot reliably predict which markets will be disputed in advance, but once a dispute starts web-enabled LLMs agree with UMA's final resolution 89.58% of the time. — [arXiv 2604.15674](https://arxiv.org/pdf/2604.15674)
- Holding rewards: launched Sept 2025, 4% annualised on position value in selected long-dated markets (13 eligible markets at launch, mostly elections/geopolitics), computed from hourly samples and paid daily; rate and eligibility are at Polymarket's discretion. A third-party docs site says markets ending >=6 months out qualify automatically (unconfirmed officially). — [Cryptopolitan](https://www.cryptopolitan.com/polymarket-starts-paying-out-4-rewards/); [Cointribune](https://www.cointribune.com/en/polymarket-rolls-out-4-annual-rewards-for-long-term-market-positions/); [PolyPulse docs](https://docs.polypulse.dev/trading/holding-rewards)
- Fees at the extremes: the 2026 taker fee is shares x rate x p x (1-p), so it is highest at 50c and falls toward 0/100; makers pay nothing. — [Polymarket docs: Fees](https://docs.polymarket.com/trading/fees); [MarketMath](https://marketmath.io/blog/polymarket-fees-explained)

### Inferences
- Fee as a fraction of stake is rate x (1-p): at 95c with a 0.05 coefficient the taker fee is ~0.25% of stake (vs 5.3% gross upside); at 99c ~0.05% (vs 1.0% gross). Fees therefore barely dent the bond trade; spread, lock-up and tail risk dominate. Entering with a resting bid removes the fee entirely.
- Break-even: buying at 95c needs a true probability above ~95.3% after taker fee; the documented favourite underpricing on Polymarket is of the order of a fraction of a cent to a cent, so the margin of safety is thin and one adjudication surprise per ~20-50 positions erases it.
- Where the 4% holding reward applies, it adds ~0.33% per month to a long-dated near-certain position, i.e. it roughly offsets a T-bill-like opportunity cost rather than creating excess return; it is useful mainly for "nothing will happen by distant date" No positions that qualify.
- For a small risk-averse account the defensible version is: many small positions (position cap ~2-5% of bankroll), only markets with unambiguous, mechanically verifiable resolution sources, short time to resolution, avoid categories with insider or adjudication history (geopolitics, "said/wore/mentioned" wording), and avoid the final hours of weather markets.

### Gaps
- No dataset-level realised return, loss frequency or annualised yield for 95-99c entries on Polymarket was found; the Gebele & Matthes implied lock-up rate values were not visible.
- Current (Nov 2026) list of holding-reward-eligible markets and whether the rate is still 4% could not be confirmed.
- No count of 2026 markets where a >=95c outcome ultimately lost.

---

## 4. Arbitrage (intra-market, NegRisk/multi-outcome, combinatorial, cross-platform)

### Takeaway
Arbitrage on Polymarket was large in 2024-25 (about $40M extracted per Saguillo et al.) but is captured by fast, specialised bots; 2026 studies with executable order-book reconstruction find far smaller realisable profits, episodes lasting seconds, and cross-platform gaps (median <1c) below the ~3c post-fee break-even. Nothing here is realistically available to a slow small bot.

### Cited Findings
- Saguillo, Ghafouri, Kiffer & Suarez-Tangil, "Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets" (arXiv 2508.03474, 5 Aug 2025; AFT 2025): distinguishes Market Rebalancing Arbitrage (within one market/condition) and Combinatorial Arbitrage (across dependent markets); using on-chain order data estimates ~$40M of realised arbitrage profit over the measurement period (about one year); most profit is in politics markets. — [arXiv 2508.03474](https://arxiv.org/abs/2508.03474); [IMDEA PDF](https://suarez-tangil.networks.imdea.org/papers/2025aft-arbitrage.pdf)
- Breakdown as restated by a later paper: ~$10.6M from same-condition (YES+NO) rebalancing and ~$29M from rebalancing mutually exclusive NegRisk outcomes. — [arXiv 2608.00666](https://arxiv.org/abs/2608.00666); [alphaXiv overview](https://alphaxiv.org/overview/2508.03474v1)
- Gebele, Mutzel & Matthes, "Executable Arbitrage and Market Efficiency in Prediction Markets" (arXiv 2608.00666, 1 Aug 2026): payoff-space no-arbitrage differs from protocol-executable no-arbitrage; Polymarket's NegRisk Adapter only operationalises the NO-to-YES conversion before settlement; depth-aware reconstruction puts realised arbitrage profit at about $1.12M across two realisation channels; some apparent deviations were API synchronisation artefacts, not executable arbitrage. — [arXiv 2608.00666](https://arxiv.org/abs/2608.00666)
- Cheng, Yang & Zou, "Arbitrage Analysis in Polymarket NBA Markets" (arXiv 2605.00864, 2026; 75M+ order-book snapshots, 173 games): only 7 executable single-market arbitrage episodes, median duration 3.6 seconds; ~290 executable combinatorial (moneyline-spread) episodes, but total covered profit only ~$560 (theoretical uncovered ~$2,033) because of shallow depth. — [arXiv 2605.00864](https://arxiv.org/abs/2605.00864); [alphaXiv summary](https://www.alphaxiv.org/de/abs/2605.00864)
- Gebele & Matthes, "Semantic Non-Fungibility and Violations of the Law of One Price in Prediction Markets" (arXiv 2601.01706, Jan 2026): cross-platform prices fail to converge even for the 2024 US election; causes are differing resolution semantics, segmentation and capital locked to resolution; ~8% of Polymarket markets have an equivalent on another platform (~2% of Kalshi's). — [arXiv 2601.01706](https://arxiv.org/html/2601.01706v1)
- Ng, Peng, Tao & Zhou (SSRN): Polymarket leads Kalshi in price discovery overall (Kalshi leads in sports and when its relative volume is high) and "substantial price discrepancies persist across major prediction platforms". — [SSRN 5331995](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5331995)
- Cross-venue gap measurement (Mar-Aug 2026, public dataset, two events): median real Polymarket-Kalshi gap 0.78c; the fat tail is almost entirely stale quotes; 2026 fees put break-even near 3c at mid prices, and Polymarket's fee rollout roughly doubled the minimum viable gap. — [PredictMarketCap study](https://predictmarketcap.com/analysis/prediction-market-arbitrage-study)
- Small NBA check (Nov 2026, 10 games sampled every ~3 min): sub-$1 combined prices appeared before fees, none profitable after fees. — [Totalis](https://www.totalis.trade/blogs/prediction-markets/prediction-market-arbitrage) [vendor blog]
- Commentary: "Arbitrage is real. The money isn't" - liquidity to exploit it at meaningful scale does not exist. — [Ariel Calista Substack](https://arielcalista.substack.com/p/arbitrage-is-real-the-money-isnt)
- Polymarket-vs-bookmaker "arbitrage" sample: 0.44% median edge on $4,023 of depth. — [OddsPapi](https://oddspapi.io/blog/polymarket-arbitrage-local-bookmakers/) [vendor]
- Marketing claims of "risk-free 22%" or "12% edge" are single gross spreads or anecdotes without verifiable data. — [PredictEngine](https://www.predictengine.ai/blog/cross-platform-prediction-arbitrage-real-case-study-reveals-12-edge) [vendor]

### Inferences
- The $40M (2024-25, on-chain realised by anyone) vs $1.12M (2026 executable reconstruction) gap is partly method and partly decay; either way the per-opportunity economics in 2026 (seconds-long windows, hundreds of dollars of depth) exclude a bot polling every few hours.
- Cross-platform "arb" is not riskless: different resolution wording, capital locked on both venues to resolution, two fee schedules, and stale quotes. For a $200-$5,000 account the return on locked capital would be poor even when a true 3c+ gap exists.
- What survives for a slow bot is not arbitrage but *consistency checking as a signal*: multi-outcome sets whose prices sum well above/below 1, or logically nested markets (A implies B priced above B), flag where one leg is stale; trading the stale leg is a directional bet, not an arbitrage.

### Gaps
- Saguillo et al. details not verifiable this session (blocked): measurement window, concentration and speed. From memory of the paper (unverified here): window roughly Apr 2024-Apr 2025; the top arbitrageur earned about $2M over ~4,000 transactions; combinatorial arbitrage contributed only a very small share (order of $100K). Treat as recollection, not a cited finding.
- No 2026 measurement of how long NegRisk multi-outcome mispricings persist outside sports.

---

## 5. Market making and liquidity rewards

### Takeaway
Liquidity provision is the one role with consistently positive aggregate returns, and Polymarket still pays resting-order liquidity rewards, but pools are small per market (most under $100/day), minimum sizes and midpoint-proximity rules apply, and from 20 Nov 2026 maker rebates require $200K of 30-day volume. For a $200-$5,000 slow bot, reward farming is marginal and adverse selection is the dominant risk; using passive limit orders to *enter positions it wants anyway* is the realistic application.

### Cited Findings
- Official mechanics: makers resting limit orders are automatically eligible; scoring favours orders near the midpoint; two-sided liquidity is boosted (minimum of the two sides), single-sided still scores at a reduced rate; rewards paid daily around midnight UTC; payouts below $1 are not paid. — [Polymarket docs: Liquidity Rewards](https://docs.polymarket.com/market-makers/liquidity-rewards)
- Secondary detail: quotes score nothing if outside the market's max spread or below its minimum size, or if the midpoint is outside 0.10-0.90 and only one side is posted. — [StartPolymarket market-making](https://startpolymarket.com/strategies/market-making/) [guide]
- Pool size snapshot (undated in summary, 2026): ~$253,568 total daily reward pool across 17,215 rewarded markets, most per-market pools under $100/day; another guide says only ~370 markets paid >=$100/day and total is "$5M+ per month". Cumulative LP rewards tracker shows $42.36M over 1.70M payouts. — [Rewards snapshot](https://noskillcoding.github.io/polymarket-rewards-snapshot/); [Tradox](https://tradoxvps.com/polymarket-liquidity-rewards/) [vendor]; [PolyScalping stats](https://polyscalping.org/stats/distribution/lp)
- Yield example from a Chinese-language analysis: in one market ~$70,000 of committed liquidity earned about $57/day (~0.08%/day, ~30% annualised gross before any fill losses); the same analysis lists "cost traps". — [RootData](https://www.rootdata.com/news/585181); [KuCoin flash](https://www.kucoin.com/news/flash/polymarket-lp-incentive-mechanism-four-key-insights-and-cost-traps)
- Vendor return claims (unverified, conflicting): $200-800/day on $50K; $150-300/day per market with $100K+ daily volume; $10-200 per $10K per day. — [GraphDex](https://graphdex.io/en/blog/how-to-make-money-on-polymarket-2026) [vendor]; [polymarkets.co.il](https://polymarkets.co.il/en/guide/liquidity-rewards/) [vendor]
- Maker rebates (separate from liquidity rewards): introduced Jan 2026, funded by taker fees and paid daily in USDC; rebate share is at Polymarket's discretion (100% launch week, 20% the week of 12-18 Jan 2026); by mid-2026 category shares were reported as ~20-25% (sports quoted variously as 15/20/25%). — [Polymarket help: Maker Rebates](https://intercom.help/polymarket/en/articles/13364471-maker-rebates-program); [StartPolymarket fees](https://startpolymarket.com/learn/polymarket-fees/)
- Change effective Fri 20 Nov 2026 23:59 UTC (Polymarket.com DeFi venue): tiered maker rebates replace the daily market-wide pools, based on 30-day maker weighted volume; accounts under $200,000 earn 0% (then 3/7/10/15% tiers per a secondary summary); taker rebates likewise require >=$200,000 30-day taker weighted volume (Gold 10%, Platinum 25%, Diamond 40%); combos and fee-free trades earn no maker rebate. — [Polymarket docs: Upcoming Fee and Rebate Changes](https://docs.polymarket.com/programs/fee-and-rebate-changes-november-2026); [GitHub issue summary](https://github.com/SpartanLabsXyz/simmer-sdk/issues/500)
- Makers win in aggregate: successful Polymarket traders provide liquidity with limit orders; market-making strongly predicts positive performance. Kalshi makers earn +1.12% per trade (Becker) though they still lose ~10% on average per contract in Bürgi et al.'s sample. — [CEPR DP21615](https://cepr.org/publications/dp21615); [jbecker.dev](https://www.jbecker.dev/research/prediction-market-microstructure); [VoxEU](https://cepr.org/voxeu/columns/economics-kalshi-prediction-market)
- Microstructure: maker liquidity is broadly decentralised across wallets; depth is layered rather than concentrated at top of book; depth declines as markets approach resolution; spreads carry a longshot premium. — [arXiv 2604.24366](https://arxiv.org/abs/2604.24366)
- Risk framing: the typical risk is "being filled just before an adverse move"; rewards accrue for resting, not for fills, so they do not offset being picked off. — [StartPolymarket market-making](https://startpolymarket.com/strategies/market-making/) [guide]

### Inferences
- A bot that re-quotes every few hours cannot pull quotes when news breaks; in news-driven markets it will be systematically filled on the wrong side (classic adverse selection), and the insider-trading episodes in section 11 make this worse in geopolitics/politics. Slow passive quoting is only defensible in markets whose information arrives on a schedule (weather model runs, data releases, sports start times) with quotes cancelled before the scheduled event.
- With most pools under $100/day shared pro rata among all quoting capital, and a $1 minimum payout, a few hundred dollars of resting size will often earn nothing or cents; reward income for a sub-$5K account is best treated as zero in planning.
- After 20 Nov 2026 the maker *rebate* is effectively unavailable to small accounts; the remaining small-account benefit of making is simply paying zero taker fee and capturing the spread.

### Gaps
- No audited realised P&L of small liquidity-reward farmers net of adverse selection was found; "Optimal Market Making in Prediction Markets" (arXiv 2607.17991) was identified but not read.
- Whether liquidity-reward budgets were cut alongside the Nov 2026 rebate change is unknown.

---

## 6. Short-duration crypto up/down markets (5-min, 15-min, hourly) and 2026 taker fees

### Takeaway
These markets were the centre of latency arbitrage against spot exchanges; Polymarket introduced taker fees there first (Jan 2026) explicitly to curb it, and they remain the highest-fee, most bot-dominated product. There is no evidence of anything left for a non-HFT participant.

### Cited Findings
- Early Jan 2026 (docs change ~5-6 Jan): taker-only fees introduced on 15-minute crypto up/down markets, highest at 50% probability and falling toward 0/100%, funding daily USDC maker rebates; described as a "dynamic fee to curb latency arbitrage"; at launch other markets stayed fee-free. — [The Block](https://www.theblock.co/post/384461/polymarket-adds-taker-fees-to-15-minute-crypto-markets-to-fund-liquidity-rebates); [Cointelegraph](https://cointelegraph.com/news/polymarket-quietly-adds-taker-fees-15-minute-crypto-markets); [Finance Magnates](https://www.financemagnates.com/cryptocurrency/polymarket-introduces-dynamic-fees-to-curb-latency-arbitrage-in-short-term-crypto-markets/amp)
- Rollout timeline per Pine Analytics: crypto fees live 5 Jan 2026 (15-minute only), extended to all crypto timeframes by 6 Mar 2026, then to nearly all categories on 30 Mar 2026 ("Fee Structure V2", ten categories); volume change after fees was within normal variance after 18 days. — [Pine Analytics](https://pineanalytics.substack.com/p/polymarket-fee-rollout); [MarketMath](https://marketmath.io/blog/polymarket-fees-explained)
- Fee schedule reported as of ~11 Nov 2026 (fee = shares x rate x p x (1-p), taker only): crypto 0.07 (peak $1.75 per 100 shares at 50c); sports, economics, culture, weather, other 0.05 ($1.25); politics, finance, tech, mentions 0.04 ($1.00); geopolitics 0 (fee-free). Sports moved from 0.03 to 0.05 in July 2026, though sampled NFL full-game markets still showed 0.03 via the API. Earlier "up to 3%" / "1.80% peak" figures are older percentage-style descriptions. — [Polymarket docs: Fees](https://docs.polymarket.com/trading/fees); [MarketMath](https://marketmath.io/blog/polymarket-fees-explained); [StartPolymarket fees](https://startpolymarket.com/learn/polymarket-fees/)
- From 20 Nov 2026 23:59 UTC: BTC 5-minute and 15-minute up/down markets go to a 0.05 coefficient; all other crypto markets go to 0.01. — [Polymarket docs: Upcoming Fee and Rebate Changes](https://docs.polymarket.com/programs/fee-and-rebate-changes-november-2026); [GitHub issue summary](https://github.com/SpartanLabsXyz/simmer-sdk/issues/500)
- Bot dominance: Polymarket's own newsletter cites a Dune report that bots are ~55% of traders in 5-minute crypto markets, says bots "fill at better prices than any human can reach" and that a few cents of slippage wipes out the strategy there. — [Polymarket "COPYCAT"](https://news.polymarket.com/p/copycat)
- Wash-trading share in crypto markets is low (3% of all-time volume, Columbia), i.e. the volume is real competition. — [Decrypt](https://decrypt.co/347842/columbia-study-25-polymarket-volume-wash-trading)
- Research infrastructure now exists for this niche (synchronised Polymarket-Binance high-frequency dataset), a sign of professionalisation. — [arXiv 2607.26245](https://arxiv.org/abs/2607.26245)

### Inferences
- At 50c the crypto taker fee is 3.5% of stake (0.07 x 0.5) until 20 Nov 2026 and 2.5% afterwards for BTC 5/15-minute markets; a directional taker needs a >52-53% hit rate at even odds just to pay the fee, in a market where the counterparties are latency-advantaged. A bot deciding every few hours cannot even participate in 5/15-minute windows meaningfully.
- The cut of "all other crypto" to 0.01 (0.5% of stake at 50c) from 20 Nov 2026 makes daily/weekly/strike-style crypto markets the cheapest fee-bearing category; these have an objective external reference (options-implied probabilities), which is a more plausible slow-bot niche than up/down scalps, though no evidence of edge was found.

### Gaps
- No 2026 study of post-fee profitability by participant type in 5/15-minute markets was retrieved (search budget exhausted; a Telonex report on top 15-minute crypto traders was identified but not read: https://telonex.io/research/top-crypto-traders-polymarket-15m).
- Hourly-market specifics not found.

---

## 7. Weather markets (daily city temperature)

### Takeaway
Weather is the most plausible "objective external model" niche for a slow bot: free ensemble forecasts exist and one academic study documents a systematic late-stage favourite overpricing. But all profitability evidence is self-reported or marketing, markets are thin, and by late 2026 there are many open-source and commercial weather bots competing.

### Cited Findings
- Academic: Qiu & Qiu (arXiv 2610.13593, Oct 2026; daily max-temperature, 10 cities, one-month test; IEEE ICDM 2026 Teen Research Symposium): most buckets are near-calibrated; favourites are substantially overpriced in the last 1-12 hours; Buy-NO on overpriced favourites can be profitable despite low win rate; the paper does *not* show the market is beaten by public forecasts (left as future work). — [arXiv 2610.13593](https://arxiv.org/abs/2610.13593)
- Cardozo & Rivero-Wildemauwe: weather results depend on weighting; the weather longshot return changes sign between equal- and value-weighted calculations. — [arXiv 2609.12878](https://arxiv.org/abs/2609.12878)
- Typical bot design: ensemble exceedance probabilities from Open-Meteo (31-member GFS/GEFS; 51-member ECMWF IFS; or a 173-member multi-model blend of ECMWF IFS/AIFS, GEFS, ICON), Kelly-fraction sizing, station-specific bias correction because markets resolve on a specific station's reading. — [GitHub suislanchez bot](https://github.com/suislanchez/polymarket-kalshi-weather-bot); [GitHub slavkokolych-alt bot](https://github.com/slavkokolych-alt/polymarket-weather-bot); [GitHub yannbellec README](https://github.com/yannbellec/polymarket-weather-bot/blob/main/README.md)
- Self-reported results (unaudited, tiny samples): one GitHub bot: +$77.01 on $279 staked, 14/23 wins, as of 27 May 2026; another repo headline "highest profits $1.8k". — [GitHub yannbellec README](https://github.com/yannbellec/polymarket-weather-bot/blob/main/README.md); [GitHub suislanchez bot](https://github.com/suislanchez/polymarket-kalshi-weather-bot)
- Marketing claims: MeteoraBot advertises +$578,418 and 71.4% win rate; guide sites claim 22-35% annual ROI and 58-68% win rates with "lower competition". No audit. — [MeteoraBot](https://meteorabot.org/) [vendor]; [polymarkets.co.il weather guide](https://polymarkets.co.il/en/guide/weather-guide/) [vendor]
- Depth: temperature markets typically $5K-$40K deep; weather is the smallest retail-participation slice. — [polymarkets.co.il weather guide](https://polymarkets.co.il/en/guide/weather-guide/) [vendor]
- Fee: weather taker coefficient 0.05 (peak $1.25 per 100 shares at 50c). — [MarketMath](https://marketmath.io/blog/polymarket-fees-explained)

### Inferences
- Fit with constraints is good: forecasts update on a 6-12 hour model cycle (matching "decisions every few hours"), fair value is objective, positions resolve within a day or two (low lock-up), insider risk is nil and adjudication risk is low. Thin depth caps size at roughly tens to low hundreds of dollars per bucket, which suits a $200-$5,000 account and deters large players.
- The number of public bots (multiple GitHub repos, at least four commercial bot sites by 2026) implies the simple "ensemble vs single consumer forecast" edge is being competed down; the residual edge is likely in station-specific bias correction, intraday observation updating, and resisting the late-favourite overpricing.
- A paper-trading phase is needed before believing any ROI number: the only peer-style study covers one month and ten cities.

### Gaps
- No independent, out-of-sample, post-fee profitability study of ensemble-based weather trading on Polymarket or Kalshi was found.
- No data on how weather spreads and depth changed during 2026 or on the share of weather volume that is bot-driven.

---

## 8. External reference prices: sports (Pinnacle), macro (FedWatch, Cleveland Fed nowcast), mention and news markets

### Takeaway
External references exist for sports, Fed decisions and CPI, but the evidence says the prediction-market price is usually at least as good as the reference at short horizons; the usable edge is detecting stale or thin Polymarket quotes relative to the reference, not betting that the reference is smarter. Mention markets have no objective reference and no tested edge; news-driven markets carry the highest adverse-selection risk.

### Cited Findings
**Sports**
- Polymarket sports prices track the 45-degree calibration line closely at seven-day and one-day horizons (Akey et al., 2.4M+ users). — [OSC-hosted PDF](https://www.osc.ca/sites/default/files/2026-10/research-grant-competition-2026-who-wins-and-who-loses-in-prediction-markets.pdf)
- Vendor comparison (sample of Oct 2026 fixtures): Polymarket's median overround on winner markets ~1.0% across basketball, tennis, American football, ice hockey, MMA vs e.g. 4.02% at Pinnacle in the examples; the same vendor's backtest says Pinnacle "tends to be better calibrated" because Polymarket sports trade thinner. No sample size disclosed. — [OddsPapi developer guide](https://oddspapi.io/blog/polymarket-api-kalshi-api-vs-sportsbooks-the-developers-guide/) [vendor]; [OddsPapi backtest](https://oddspapi.io/blog/prediction-market-accuracy-backtest-polymarket-sportsbooks/) [vendor]
- Sports specialists are the least profitable retail group (25.1% profitable, Galaxy, Oct 2026). — [PANews](https://panews.io/articles/01a0fa0c-6ce9-7204-a3e2-f0d242a2ab74)
- Kalshi leads Polymarket in price discovery for sports. — [SSRN 5331995](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5331995)
- Sports had the highest wash-trading share (45% of all-time Polymarket volume, Columbia, Nov 2025), so volume overstates real liquidity. — [Decrypt](https://decrypt.co/347842/columbia-study-25-polymarket-volume-wash-trading)
- NBA markets are microstructurally efficient (7 single-market arbitrage episodes in 75M snapshots). — [arXiv 2605.00864](https://arxiv.org/abs/2605.00864)

**Macro**
- Diercks, Katz & Wright, "Kalshi and the Rise of Macro Markets" (Fed-affiliated authors, 2026): Kalshi macro markets give valuable real-time distributions; Fed funds markets are "exceptionally accurate", labour-market series hardest; press summaries say Kalshi's headline-CPI expectations were a statistically significant improvement over Bloomberg consensus and that Kalshi beat fed funds futures on the policy rate. — [ResearchGate listing](https://www.researchgate.net/publication/401151617_Kalshi_and_the_Rise_of_Macro_Markets); [AOL/press summary](https://www.aol.com/articles/federal-research-kalshi-prediction-markets-215000396.html)
- Independent GitHub study (53 CPI releases): one week before release Kalshi Brier 0.072 vs 0.089 for the Cleveland Fed nowcast; the nowcast is slightly ahead at 30 days; a 50/50 blend beats Kalshi alone; some 2023-24 CPI events were thin. — [GitHub kalshi-vs-fed](https://github.com/suhailabdulwasi/kalshi-vs-fed)
- Kalshi research (company source): its median CPI forecast matched or beat Bloomberg survey and Cleveland Fed nowcast in 11 of the last 13 months. — [Kalshi research](https://kalshi.com/research/insights/july-cpi-preview)
- Critique of FedWatch as a reference: implied probabilities can conflict with options pricing and underweight tails. — [Macro Models Substack](https://macromodels.substack.com/p/reliably-bad-reliable-sources)
- Fed/interest-rate markets on Kalshi show no favourite-longshot bias; finance is the most efficient category on Kalshi (0.17pp maker-taker gap). — [ResearchGate](https://www.researchgate.net/publication/409472804_Information_Efficiency_Across_Macroeconomic_Prediction_Markets_Evidence_from_Kalshi); [jbecker.dev](https://www.jbecker.dev/research/prediction-market-microstructure)
- General accuracy comparison (Vanderbilt study as reported by DL News): Polymarket got 67% of markets right, Kalshi 78%, PredictIt 93%; Kalshi disputes the methodology. — [DL News](https://www.dlnews.com/articles/markets/polymarket-kalshi-prediction-markets-not-so-reliable-says-study/)

**Mention and news markets**
- Mention markets resolve differently by venue (Kalshi on designated speakers and the final published transcript; Polymarket often on anyone on the broadcast), which explains price gaps; advice to use historical transcripts comes from tool vendors; no independent backtest of a Yes-overpricing or No edge was found. — [DeFi Rate](https://defirate.com/prediction-markets/mention-markets/); [Odds Assist](https://oddsassist.com/prediction-markets/mentions/) [vendor]
- Entertainment/media categories show the widest maker-taker gaps on Kalshi (>7pp), i.e. the most biased taker flow. — [jbecker.dev](https://www.jbecker.dev/research/prediction-market-microstructure)
- Polymarket mentions/tech/politics/finance taker coefficient 0.04; geopolitics fee-free. — [MarketMath](https://marketmath.io/blog/polymarket-fees-explained)

### Inferences
- Ranking of references by usefulness to a slow bot: (1) weather ensembles (section 7); (2) sharp sportsbook de-vigged lines as a *sanity filter* for Polymarket pre-game prices (Polymarket's ~1% overround means that when a gap exists Polymarket may be the cheaper venue, but the reference is not clearly more accurate and sports retail does worst); (3) Cleveland Fed nowcast blended with market price for CPI at the 2-4 week horizon, where the nowcast still adds information; (4) FedWatch for Fed decisions is close to redundant: the markets are already "exceptionally accurate".
- Because finance/Fed markets are near-efficient, the expected edge there is approximately zero minus costs; they are useful mainly as low-variance "bond-like" positions near decision dates rather than as alpha.
- Mention markets are where biased retail flow is largest, but the only documented way to harvest it is as a maker selling Yes, with idiosyncratic transcript/adjudication risk; not suited to a risk-averse automated account without its own transcript base rates.

### Gaps
- No peer-reviewed Polymarket-vs-Pinnacle closing-line study was found; no Polymarket-specific Fed/CPI market accuracy study (evidence is Kalshi-based).
- No data-driven study of news-reaction speed (minutes vs hours) on Polymarket was retrieved; two candidate papers (arXiv 2609.06005 on price dislocations and news citations; arXiv 2610.00173 on contractual decidability) were identified but the search budget ran out before they could be summarised.

---

## 9. Copy trading / following top wallets

### Takeaway
The best available test finds most leaderboard wallets are not copyable at all (market makers, arbitrage/late-resolution bots, market-moving whales); a handful of slow "specialist" wallets may be, but evidence is small-sample and mostly from vendors.

### Cited Findings
- POLBOTS replay test (Oct 2026): 407 leaderboard wallets screened; only six passed copyability filters and three of those made money when replayed 1-2 minutes late with ~0.5c assumed spread; conclusion: delay is not what kills copy trading, uncopyable wallets are. — [POLBOTS](https://polbots.com/guides/does-polymarket-copy-trading-work) [vendor site, but data-based]
- Ratio.you (500 wallets): whales that move the market should not be copied; example of a wallet buying at 36c and the copier paying 41c. — [Ratio.you](https://ratio.you/blog/i-analyzed-500-polymarket-wallets-worth-copy-trading) [vendor]
- Polymarket's COPYCAT newsletter: bots are hardest to copy; in 5-minute crypto a few cents of slippage wipes out the edge; most of the ten most-copied wallets were in the top 200 by lifetime PnL. — [Polymarket "COPYCAT"](https://news.polymarket.com/p/copycat)
- Many visible top whales are doing late-window trades on effectively resolved markets, which cannot be copied profitably. — [polymarkets.co.il](https://polymarkets.co.il/en/bots/polymarket-whale-copy-trading-bot/) [vendor]
- Opinion: mechanical copying is structurally unprofitable (slippage, lag, manipulation/baiting risk). — [StartPolymarket](https://startpolymarket.com/strategies/copy-trading/) [guide]
- Monthly performance persistence among Polymarket traders is only modest and may reflect selection. — [CEPR DP21615](https://cepr.org/publications/dp21615)

### Inferences
- Weak performance persistence plus leaderboard survivorship means past PnL is a poor selector; a slow bot polling every few hours is too late for anything but multi-day position trades.
- Wallet flow is more useful as a *risk flag* (fresh, single-market wallets taking large longshot positions suggest informed flow; do not be on the other side) than as a signal to follow.

### Gaps
- No academic out-of-sample copy-trading study after fees was found.

---

## 10. Liquidity, spreads, time effects and the cost of small orders

### Takeaway
Liquidity is extremely concentrated: a few hundred deep events have ~1c spreads, while most listed contracts have no trades in a day. New markets open wide and compress within the first hour. For a $20-$200 order in a deep politics/crypto/economy market the all-in taker cost is roughly 1-3.5% of stake at mid prices (mostly fee); in thin markets the spread dominates and passive orders are needed.

### Cited Findings
- IMDEA Networks, "Opening Wide, Moving Fast: Polymarket Spread Dynamics" (Oct 2025-Mar 2026): median quoted spread at market open ranges from 3c (sports) to 21c (economy), a 7x gap; politics/geopolitics open at 8-10c; most compression happens within the first hour; ranking categories by opening cost and by post-trade price impact gives different orderings. — [IMDEA PDF](https://dspace.networks.imdea.org/bitstream/handle/20.500.12761/2065/Polymarket_Initial_Liquidity-3.pdf?sequence=1&isAllowed=y)
- Order-book snapshot (11 Nov 2026, 300 deepest events, 17,692 open contracts, $401M resting liquidity): median spreads ~1.0c politics, 0.9c crypto, 1.0c economy (sports median distorted to 79c by near-resolved props quoted at 1/99c); 71% of depth sits on contracts priced under 5c; 87% of contracts had no trades in 24h. — [pmcrypto liquidity data](https://pmcrypto.blog/data/liquidity/); [pmcrypto analysis](https://pmcrypto.blog/liquidity-is-the-product/) (blog)
- Dubach (600-market panel): longshot contracts carry a spread premium; depth is layered beyond top of book and falls approaching resolution; feed-inferred trade direction matches on-chain truth only ~59% of the time (vs ~80% Lee-Ready in equities), a caution for backtests built on the public feed. — [arXiv 2604.24366](https://arxiv.org/abs/2604.24366); [GitHub replication](https://github.com/philippdubach/polymarket-microstructure)
- Weak source: US politics average 1.4c spreads vs 4.8c for geopolitical contracts (240-market sample, undocumented method). — [CopyTradeInsider](https://www.copytradeinsider.com/blog/best-polymarket-markets-2026/) [vendor]
- Horizon effect: calibration varies with time-to-resolution in every domain ("universal horizon effect"); Kalshi's longshot bias strengthens toward close and "appears to track less popular markets". — [arXiv 2602.19520](https://arxiv.org/abs/2602.19520); [GitHub hrishi-tailor](https://github.com/hrishi-tailor/prediction-market-calibration)
- Long-dated prices embed a settlement/lock-up discount rather than pure belief. — [arXiv 2605.31431](https://arxiv.org/abs/2605.31431)

### Inferences
- Worked cost for a $100 taker order at 50c in a deep market: half-spread ~0.5c (1% of stake) plus fee of rate x (1-p) = 2.0% (politics/finance), 2.5% (sports/weather/economics), 3.5% (crypto before 20 Nov 2026), 0% (geopolitics): about 1-4.5% one-way. At 90c the fee falls to 0.4-0.7% of stake; at 10c it rises to 3.6-6.3% of stake. Fees thus penalise buying longshots and mid-priced contracts and barely touch favourites.
- An edge must exceed roughly 3-5 probability points at mid prices to be worth taking with market orders; with resting limit orders the fee is zero and the bot earns rather than pays the half-spread, at the cost of non-execution and adverse selection.
- Neglected markets (the 87% with no daily trades) are likelier to be mispriced, but displayed depth there is often stub quotes at 1c/99c and exit liquidity is poor; inefficiency there is "limits to arbitrage", not free money. Positions in them should be sized to be held to resolution.
- Avoid trading in the first hour after listing with market orders (spreads 3-21c).

### Gaps
- No study measuring realised slippage by order size ($20-$200) on Polymarket was found; the estimate above is derived from median spreads and the fee formula.
- Category effective-spread table in Dubach's paper not visible.

---

## 11. Insider trading, manipulation and wash trading (2025-2026) and adverse-selection implications

### Takeaway
2025-26 produced repeated, well-documented cases of wallets trading ahead of non-public information in geopolitics/military, corporate-announcement and award markets, with the first criminal charges in 2026. For an outsider, sudden longshot buying by fresh wallets in such markets should be treated as informed flow; these are the worst markets in which to quote passively or sell "obvious" longshots.

### Cited Findings
- Nobel Peace Prize (Oct 2025): Machado's Polymarket odds jumped from ~3.6% to >70% overnight before the announcement on bets from a few accounts; one newly opened account reportedly made >$50K (three accounts ~$90K combined); Norwegian officials opened a probe; by Feb 2026 the Nobel Institute called a cyberattack the "most likely" explanation. — [The Block](https://www.theblock.co/post/374199/officials-probe-polymarket-over-suspicious-trades-predicting-nobel-peace-prize-winner-reports); [Blockworks](https://blockworks.co/news/polymarket-nobel-probe); [MercoPress](https://en.mercopress.com/2026/02/03/betting-spike-ahead-of-machado-s-nobel-peace-prize-and-suspected-cyber-breach-trigger-leak-probe)
- Google Year in Search (Dec 2025): account "AlphaRaccoon" collected ~$1.2M after Google's 4 Dec 2025 announcement; in May 2026 US prosecutors charged a Google security engineer with using confidential search data (allegations, not yet proven). — [The Register](https://www.theregister.com/legal/2026/05/28/google-infosec-engineer-charged-with-insider-trading/5247745); [BleepingComputer](https://www.bleepingcomputer.com/news/security/us-charges-google-security-engineer-with-polymarket-insider-trading/); [Forbes (Dec 2025)](https://www.forbes.com/sites/boazsobrado/2025/12/04/alleged-insider-nets-1-million-on-polymarket-in-24-hours/)
- Maduro/Venezuela (news of 4 Jan 2026): Lookonchain flagged three wallets created and funded days earlier that traded only Venezuela/Maduro markets just before the news. — [Yahoo Finance/Benzinga](https://finance.yahoo.com/markets/crypto/articles/polymarket-faces-fresh-insider-trading-133446085.html) (attribution within coverage uncertain)
- Iran strike markets: Bloomberg analysed ~34,000 pre-flagged trades from ~19,000 wallets across ~4,000 markets (Jul 2025-Jun 2026); Bubblemaps/Polysights identified nine wallets with a combined 98% win rate on Iran bets; a newly created wallet netted $494,000 on a US-Iran strike market. — [Bloomberg](https://www.bloomberg.com/graphics/2026-polymarket-bets-iran-war-insider-trading/); [Crypto Briefing](https://cryptobriefing.com/polymarket-insider-trading-scrutiny/)
- Military markets: Anti-Corruption Data Collective (reported Aug 2026 via Reuters) identified 556 "orca" wallets, of which 152 made ~$8M with a 97.2% win rate on longshot military/defence bets; a US Army Master Sergeant was charged in April 2026 over ~$400K of profits from classified information (described as the first federal insider-trading case tied to a prediction market). — [Yahoo News/Reuters](https://ca.news.yahoo.com/exclusive-more-150-polymarket-wallets-100543612.html); [Crypto Briefing](https://cryptobriefing.com/polymarket-wallets-military-insider-trading/)
- ACDC policy brief (April 2026) on political markets: longshot bets appear in 15,110 markets (3%) by 10,944 wallets; 2,658 wallets had at least one winning longshot bet; 14% of longshot trades bought the winning outcome. — [ACDC brief](https://acdatacollective.org/wp-content/uploads/2026/04/Insider_Risks_in_Polymarket_Political_Markets_ACDC.pdf)
- Platform/regulatory response: Polymarket said it referred nearly 100 suspicious wallets to law enforcement (July 2026); a House Oversight investigation (May 2026) sought records on identity verification and anomaly detection; reports note the legal framework for insider trading on geopolitical event contracts on offshore/decentralised venues remains unclear. — [crypto.news](https://crypto.news/polymarket-refers-nearly-100-wallets-amid-200m-insider-trade-concerns/); [Crypto Briefing](https://cryptobriefing.com/polymarket-insider-trading-scrutiny/)
- CoinDesk (27 Feb 2026): bettors appear to have insider-traded on a market designed to catch insider traders. — [CoinDesk](https://www.coindesk.com/markets/2026/02/27/polymarket-bettors-appear-to-have-insider-traded-on-a-market-designed-to-catch-insider-traders)
- Population-scale academic work: an Information Leakage Score framework applied to 12,708 Polymarket markets in insider-relevant categories (Oct 2020-Apr 2026). — [arXiv 2605.00459](https://arxiv.org/pdf/2605.00459)
- Wash trading (Columbia, SSRN, Nov 2025, not peer reviewed): ~25% of all-time Polymarket volume likely wash trading; 14% of 1.26M wallets show suspicious patterns; peaked near 60% of weekly volume in Dec 2024, <5% by May 2025, ~20% by Oct 2025; by category 45% sports, 17% elections, 12% politics, 3% crypto; possibly airdrop farming. — [Decrypt](https://decrypt.co/347842/columbia-study-25-polymarket-volume-wash-trading); [Fortune](https://fortune.com/2025/11/07/polymarket-wash-trading-inflated-prediction-markets-columbia-research/); [Cointelegraph](https://cointelegraph.com/news/columbia-study-polymarket-wash-trading-research)
- Contrasting estimate: Dubach's 600-market panel finds directly detectable wash trading is low. — [arXiv 2604.24366](https://arxiv.org/abs/2604.24366)
- Resolution manipulation concerns: Zelensky suit market (July 2025, >$237M volume) and allegations of concentrated UMA voting. — [Decrypt](https://decrypt.co/329210/polymarket-rules-no-237m-bet-zelenskyys); [crypto.news](https://crypto.news/polymarket-under-fire-as-whale-votes-distort-zelenskyy-suit-outcome-whats-going-on/)

### Inferences
- The longshot-selling edge of section 2 and the insider risk here collide: the 14% hit rate on flagged political longshot trades and 97% win rates of "orca" wallets mean that in geopolitics/military/corporate-disclosure/award markets, a cheap Yes that is being bought aggressively is not a biased retail longshot. A bot should exclude or heavily down-weight markets whose outcome is known in advance to some insider (announcements, awards, military action, internal corporate data) and prefer markets resolved by public processes (weather, scheduled data releases, sports results, elections).
- Geopolitics being the one fee-free category is not a reason to trade it: it has the widest spreads among major categories (weak source), the worst insider record and the most adjudication disputes.
- Wash volume means volume-based liquidity filters (especially in sports) overstate tradability; filter on resting depth and spread instead.

### Gaps
- No estimate of the share of volume or of maker losses attributable to informed wallets was found (the 2605.00459 paper's headline number was not visible).
- No 2026 update of the Columbia wash-trading estimate (post-fee era) was found.

---

## 12. Overall: which edges are alive vs arbitraged away in late 2026, ranked for a $200-$5,000 slow, risk-averse bot

### Takeaway
For this account profile the evidence supports a short list: (a) structural tilts (never take longshots; lean to favourites; use limit orders), (b) objective-reference niches with scheduled information (weather first; CPI/sports as filters), and (c) carefully diversified near-resolution favourites in unambiguous markets. Speed-dependent families (arbitrage, crypto up/down, news reaction, copy trading) are effectively closed, and reward/rebate farming is marginal at this size.

### Cited Findings
Ranking synthesised from the sections above; each row cites its strongest evidence.

| Rank | Strategy family | Evidence of edge | Small-account capacity | Risk profile | Competition / decay by late 2026 |
|---|---|---|---|---|---|
| 1 | Structural tilt: avoid buying <20c contracts, prefer favourite side, enter via limit orders | Strong and replicated: takers/longshot buyers lose, makers/favourite holders gain — [CEPR DP21615](https://cepr.org/publications/dp21615); [jbecker.dev](https://www.jbecker.dev/research/prediction-market-microstructure); [arXiv 2609.12878](https://arxiv.org/abs/2609.12878); [arXiv 2606.04217](https://arxiv.org/abs/2606.04217) | High (works at any size) | Low per trade; short-vol tail on favourites | Decaying: Kalshi slope 1.31 pre-2025 to ~1.04-1.13 — [GitHub hrishi-tailor](https://github.com/hrishi-tailor/prediction-market-calibration); weak/absent on Polymarket outside the cheap tail — [GitHub PDiTO](https://github.com/PDiTO/pm-calibration) |
| 2 | Weather vs forecast ensembles | Moderate: documented late-favourite overpricing — [arXiv 2610.13593](https://arxiv.org/abs/2610.13593); profitability only self-reported — [GitHub yannbellec](https://github.com/yannbellec/polymarket-weather-bot/blob/main/README.md) | Good ($5K-$40K depth per market, per vendor guide) | Low: fast resolution, objective source, no insiders | Rising: many public and commercial bots |
| 3 | Near-resolution favourites ("bonds") in unambiguous markets, optionally with holding rewards | Moderate: small positive mean for high-priced contracts — [VoxEU](https://cepr.org/voxeu/columns/economics-kalshi-prediction-market); much of it is lock-up compensation — [arXiv 2605.31431](https://arxiv.org/abs/2605.31431) | High | Fat left tail (19:1 at 95c); adjudication risk — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0165176526003721) | Crowded by whales above 95c (anecdotal) — [Gate Learn](https://www.gate.com/learn/articles/the-quiet-arbitrageurs-making-fortunes-on-polymarket/12914) |
| 4 | Political-market underconfidence (heavy favourites underpriced; prices compressed toward 50%) | Moderate: robust in one large study — [arXiv 2602.19520](https://arxiv.org/abs/2602.19520) | High | Event risk, long lock-up, insider/adjudication exposure | Unknown; sample dominated by 2024 cycle |
| 5 | Macro/sports reference-price filters (nowcast blend for CPI, de-vigged sharp lines) | Weak-to-moderate: nowcast adds value only at ~30 days; markets beat references near release — [GitHub kalshi-vs-fed](https://github.com/suhailabdulwasi/kalshi-vs-fed); finance near-efficient — [jbecker.dev](https://www.jbecker.dev/research/prediction-market-microstructure) | High in deep markets | Low | Efficient; sports retail does worst — [PANews](https://panews.io/articles/01a0fa0c-6ce9-7204-a3e2-f0d242a2ab74) |
| 6 | Passive liquidity provision for rewards | Makers win in aggregate, but pools mostly <$100/day/market — [Rewards snapshot](https://noskillcoding.github.io/polymarket-rewards-snapshot/); rebates need $200K volume from 20 Nov 2026 — [Polymarket docs](https://docs.polymarket.com/programs/fee-and-rebate-changes-november-2026) | Poor (min sizes, $1 payout floor) | Adverse selection for a slow quoter | Professionalised |
| 7 | "Always No" / nothing-ever-happens | Weak: Yes overpricing early (~1.5x) — [LessWrong](https://www.lesswrong.com/posts/zu3YnojJ8dXWzxmWd/manifold-and-polymarket-are-biased-against-nothing-ever-1); public bot not profitable — [CryptoNews.net](https://cryptonews.net/news/finance/32705033/) | High | Tail risk when something happens; insider-exposed categories | Well known |
| 8 | Copy trading | Weak: 3 of 407 wallets copyable and profitable — [POLBOTS](https://polbots.com/guides/does-polymarket-copy-trading-work) | Medium | Baiting/slippage | Crowded, vendor-driven |
| 9 | Cross-platform Polymarket-Kalshi arbitrage | Negative after fees: median gap 0.78c vs ~3c break-even — [PredictMarketCap](https://predictmarketcap.com/analysis/prediction-market-arbitrage-study) | Poor (capital locked on two venues) | Resolution-mismatch risk — [arXiv 2601.01706](https://arxiv.org/html/2601.01706v1) | Arbitraged away |
| 10 | Intra-market / NegRisk / combinatorial arbitrage | Historically ~$40M — [arXiv 2508.03474](https://arxiv.org/abs/2508.03474); executable 2026 estimate ~$1.12M, episodes of seconds — [arXiv 2608.00666](https://arxiv.org/abs/2608.00666); [arXiv 2605.00864](https://arxiv.org/abs/2605.00864) | None for a slow bot | Execution/leg risk | Arbitraged away by fast bots |
| 11 | Short-duration crypto up/down | None for non-HFT; highest fees, ~55% bot traders — [Polymarket "COPYCAT"](https://news.polymarket.com/p/copycat); [The Block](https://www.theblock.co/post/384461/polymarket-adds-taker-fees-to-15-minute-crypto-markets-to-fund-liquidity-rebates) | None | High variance, negative expectancy | HFT-dominated |

- Fee context applying to every row: taker-only fees on nearly all categories since 30 Mar 2026 (geopolitics free), coefficient 0.04-0.07, fee = shares x rate x p x (1-p); makers pay nothing. — [Polymarket docs: Fees](https://docs.polymarket.com/trading/fees); [Pine Analytics](https://pineanalytics.substack.com/p/polymarket-fee-rollout)

### Inferences
- "Alive" in late 2026 (for this profile): favourite/maker structural tilt (shrinking), weather ensemble niche (competitive but accessible), diversified near-resolution favourites in mechanically resolved markets (thin margin, tail-managed), political-favourite underpricing (uncertain persistence). "Arbitraged away or closed": all true arbitrage, cross-platform gaps, short-duration crypto, fast news reaction, blind copy trading. "Marginal": liquidity-reward farming and maker rebates at sub-$200K volume.
- The 2026 fee regime reinforces the same conclusion as the bias literature: fees as a share of stake are rate x (1-p), so they fall hardest on longshot and mid-price takers and lightly on favourite buyers and not at all on makers. A sensible default policy for the bot: limit orders only unless estimated edge exceeds ~4-5 points at mid prices; never buy below ~15-20c as a taker; hard category exclusions (5/15-minute crypto, insider-prone announcement/military/award markets, ambiguous-wording markets); per-position cap of a few percent of bankroll because favourite strategies are short-volatility.
- Realistic expectation: the documented edges are of the order of 1-5% per position before costs, with heavy concentration of profits among professionals; for a small account the achievable outcome is "modestly positive or roughly flat with low variance", and the main value of evidence-based rules is avoiding the well-documented retail loss channels. Paper trading with realistic fill assumptions is warranted before live capital, especially because public-feed backtests misclassify trade direction ~41% of the time ([GitHub replication](https://github.com/philippdubach/polymarket-microstructure)).

### Gaps
- Because page fetches were blocked and the search budget was exhausted, primary tables were not read; key numbers to verify before relying on them: Bürgi et al. and Becker returns by price bucket; Qin & Yang decile table; Saguillo et al. concentration and timing; the official post-20-Nov-2026 fee coefficient table for non-crypto categories; current holding-reward rate and eligible markets.
- No post-fee (after 30 Mar 2026) wallet-profitability study exists in what was found; nearly all profitability statistics describe a zero-fee regime.
- No evidence was found either way on Polymarket US (the CFTC-regulated venue, separate fee schedule effective 1 Jul 2026 per [River Markets](https://www.rivermarkets.com/insights/polymarket-us-fees.html)) having different inefficiencies from the international order book.

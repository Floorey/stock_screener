# Definitions, delineations and drivers

Source: Gomber, Arndt, Lutat & Uhle (2011), *High-Frequency Trading*, sections 2 and 3
plus Appendices II and III.

## Contents

- [Why definitions matter](#why-definitions-matter)
- [Algorithmic trading](#algorithmic-trading)
- [High-frequency trading](#high-frequency-trading)
- [The three-box picture](#the-three-box-picture)
- [Regulatory definitions compared](#regulatory-definitions-compared)
- [Academic definitions compared](#academic-definitions-compared)
- [Related concepts: market making, QPM, SOR](#related-concepts)
- [Drivers of AT/HFT adoption](#drivers-of-athft-adoption)

## Why definitions matter

There is no agreed definition of HFT — not in academia, not among regulators. The paper's
response is deliberately not to add another one, but to extract the characteristics that
appear consistently and non-contradictorily across existing definitions, and to treat them
as family resemblances: an activity is AT or HFT if it displays **most but not necessarily
all** of the listed characteristics.

This matters practically. Regulatory drafting that turns on a bright-line definition either
under-captures (proprietary boutiques restructure out of scope) or over-captures (ordinary
agency execution algorithms get swept in). The paper notes that CESR's own call for evidence
produced HFT market-share estimates from 13% to 40% *because respondents were defining the
term differently*.

## Algorithmic trading

Definitions in the literature range from Prix et al. (2007) — "computerized trading
controlled by algorithms" — to Chaboud et al. (2009):

> "In algorithmic trading (AT), computers directly interface with trading platforms,
> placing orders without immediate human intervention. The computers observe market data
> and possibly other information at very high frequency, and, based on a built-in
> algorithm, send back trading instructions, often within milliseconds. A variety of
> algorithms are used: for example, some look for arbitrage opportunities, including small
> discrepancies in the exchange rates between three currencies; some seek optimal execution
> of large orders at the minimum cost; and some seek to implement longer-term trading
> strategies in search of profits."

Across the literature AT is consistently treated as a tool for professional traders that
observes market parameters in real time and generates or carries out trading decisions
without human intervention, frequently routing via DMA or sponsored access.

### Table 1 — Common characteristics of AT and HFT

1. Pre-designed trading decisions
2. Used by professional traders
3. Observing market data in real-time
4. Automated order submission
5. Automated order management
6. Without human intervention
7. Use of direct market access

### Table 2 — Specific characteristics of AT *excluding* HFT

1. Agent trading
2. Minimize market impact (for large orders)
3. Goal is to achieve a particular benchmark
4. Holding periods possibly days / weeks / months
5. Working an order through time and across markets

This is the "classical" AT of broker execution desks: the focus is intelligent working of
a parent order against a benchmark, on behalf of a client who may hold the position for
months.

## High-frequency trading

HFT is treated throughout as a **subset of AT** (following Brogaard 2010). Authors
typically specify that HFT strategies update orders very quickly and hold no overnight
positions; rapid cancellation and deletion is *necessary* to the business model, because
profits per trade are tiny and must be earned across a very large number of trades. That in
turn pushes HFT toward highly liquid instruments and makes low-latency access a
prerequisite.

### Table 3 — Specific characteristics of HFT

1. Very high number of orders
2. Rapid order cancellation
3. Proprietary trading (own capital only)
4. Profit from buying and selling (as middleman)
5. No significant position at end of day (flat position)
6. Very short holding periods
7. Extracting very low margins per trade
8. Low latency requirement
9. Use of co-location / proximity services and individual data feeds
10. Focus on highly liquid instruments

A caveat the paper takes from Tradeworx (2010): "some HFT strategies have no special speed
requirements and do not even require collocation". The characteristics are indicative, not
necessary conditions — which is exactly why item-by-item tests make poor regulatory triggers.

## The three-box picture

```
   Specific for AT excl. HFT              Specific for HFT
   ─────────────────────────              ────────────────
   agent trading                          very high number of orders
   minimize market impact                 rapid order cancellation
   benchmark-driven                       proprietary trading
   holding periods days–months            middleman profit
   work order through time/venues         flat at end of day
                                          very short holding periods
                                          very low margin per trade
                    ╲                 ╱   low latency requirement
                     ╲               ╱    co-location / direct feeds
                      ╲             ╱     high-liquidity instruments
                Common for AT and HFT
                ─────────────────────
                pre-designed decisions · professional traders
                real-time market data · automated submission
                automated order management · no human intervention
                direct market access
```

## Regulatory definitions compared

| Body | Document | Substance of the definition |
|---|---|---|
| **SEC** (2010) | Concept Release on Equity Market Structure | "Relatively new and not yet clearly defined." Professional traders acting in a proprietary capacity generating large numbers of daily trades; organized as prop firms, broker-dealer prop desks or hedge funds. Attributes: extraordinarily fast programs for generating/routing/executing orders; co-location and individual data feeds; very short position lifetimes; numerous orders cancelled shortly after submission; ending the day near flat. |
| **CESR** (2010a) | Call for Evidence, micro-structural issues | A form of automated trading implying speed; trades executed in milliseconds, positions possibly sub-second; in and out through the day, flat at the close; own capital, not client business; various strategies (arbitrage, disequilibrium prices, perceived trading patterns) all geared to extracting very small margins across platforms at hyper-fast speed. |
| **ASIC** (2010a) | Report 215, Australian equity market structure | HFT as a subset of high-speed algorithmic trading, characterized by (a) large numbers of orders, many rapidly cancelled and (b) very short holding horizons ending the day flat. Infrastructure: direct market feeds, co-location at the matching engine, proprietary short-term strategies, no carry-over positions. |
| **AFM** (2010) | High frequency trading: the application of advanced trading technology | Explicitly: "HFT is **not a trading strategy in itself**, but a means of applying certain strategies (market making and statistical arbitrage)". Positions usually market-neutral and hedged, closed by day end; holding periods seconds to minutes; very high order-to-transaction ratio; most orders cancelled shortly after entry as they are continually updated. Notes "bursts" of orders alternating with quiet periods as a main feature. |
| **European Commission** (2010) | MiFID Review consultation | "Typically not a strategy in itself but the use of very sophisticated technology to implement traditional trading strategies" — interpreting market signals and executing high-volume automated strategies, usually quasi market making or arbitraging, over very short horizons, as principal, closed out at day end. |
| **CESR** (2010b) | Technical Advice to the EC (MiFID Review) | Reports that no single agreed definition emerged from consultation; recurring themes were rapid automated execution, latency sensitivity, co-location use, market neutrality with day-end flat positions, and proprietary character. Estimates of significance varied from 13% to 40% of total trading. |

Note how many of these — AFM and the European Commission explicitly — already state that
HFT is a technology rather than a strategy. That framing is not the study's invention; it
was the regulators' own, and was then routinely ignored in public debate.

## Academic definitions compared

| Authors | Paper | Definition in brief |
|---|---|---|
| Jovanovic & Menkveld (2010) | Middlemen in Limit Order Markets | Distinguishes algorithms that *work an order* to minimize transaction cost from those that "simply profit from buying and selling securities as a middleman"; the latter is HFT. |
| Jarnecic & Snape (2010) | Trades by high frequency participants on the LSE | "The use of high-speed computer algorithms to automatically generate and execute trading decisions for the specific purpose of making returns on proprietary capital." |
| Cvitanić & Kirilenko (2010) | High Frequency Traders and Asset Prices | Extremely fast automated programs generating, routing, cancelling and executing orders; massive order and cancellation counts; rapid in-and-out; day finished without significant open position. |
| Brogaard (2010) | HFT and its Impact on Market Quality | Stocks rapidly bought and sold by algorithm and held very briefly. Explicitly frames HFT as a subset of AT, where AT (per Hendershott & Riordan 2009) is "the use of computer algorithms to automatically make trading decisions, submit orders, and manage those orders after submission". Difference is holding period and day-end neutrality. |
| Kirilenko, Samadi, Kyle & Tuzun (2010) | The Flash Crash | An *operational* definition for classifying accounts: Intermediaries are accounts whose net holdings fluctuate within 1.5% of end-of-day level and whose end-of-day net position is ≤5% of daily volume; HFTs are the top 3% of Intermediaries by daily transaction count. |

The Kirilenko et al. definition is worth remembering separately: when a dataset has to
identify HFT without member flags, this kind of inventory-and-frequency screen is how it is
done. It is a proxy, and answers derived from it inherit its arbitrariness.

## Related concepts

### Market making

Quoting simultaneous buy and sell limit orders in an instrument to profit from the bid-ask
spread. It may be **obligatory** — imposed by venue or regulator on a designated entity
(NYSE Designated Market Maker, Frankfurt/Xetra Designated Sponsor) — or **voluntary**, with
no quoting obligation at all.

Market makers commonly run "quote machines": programs that generate, update and delete
quotes to a pre-set strategy. Sophistication varies from near-HFT to human-supervised.

The overlap with HFT has three regions:
1. HFT strategies that are not market making at all (arbitrage, liquidity detection, momentum),
2. HFT applying market-making strategies **without** designated-liquidity-provider status,
3. HFT applying market making **and** registered as a designated liquidity provider
   (e.g. GETCO as an NYSE DMM).

There is also market making done without HFT at all. Fragmentation increases the relevance
of region 2: participants can quote on less active venues using reference prices from the
most liquid market for the instrument.

*Delineation:* quote machines originally existed to help market makers meet mandatory
quotation obligations. Both mandatory and voluntary market making may use HFT as supporting
technology — the technology does not define the role.

### Quantitative portfolio management (QPM)

Chincarini & Kim (2006): "The central, unifying element of quantitative equity portfolio
management is the quantitative model that relates stock movements to other market data.
Quantitative equity portfolio managers create such models to predict stock returns and
volatility, and these predictions, in turn, form the basis for selecting stocks for the
portfolio."

Differences from HFT:
- **Horizon.** QPMs hold positions for extended periods; HFTs liquidate rapidly and end flat.
- **Human intervention.** QPM has more of it — a portfolio manager typically validates model
  output before it reaches a trader or execution algorithm.
- **Decision type.** QPM automates portfolio selection and signal generation. HFT does no
  portfolio selection; it reacts to specific market situations (order-book states, arbitrage
  opportunities).

QPM may use third-party algorithms to execute, which is where the line blurs. In the
automation/latency-sensitivity plane, QPM sits high on automation of *decisions* but low on
latency sensitivity; HFT is high on both.

*Delineation:* QPM primarily supports asset-allocation decisions and mostly does not cover
the order-execution part.

### Smart order routing (SOR)

In fragmented markets, SOR systems scan multiple accessible venues in real time to identify
the best routing destination and optimize execution. Two steps are required to get a genuine
best result: screen venues' order-book situations (the execution-price dimension), then apply
a model of total execution cost including trading, clearing and settlement fees or taxes (the
explicit-cost dimension). Venue latency may also enter the rule framework.

*Delineation:* SOR optimizes execution in fragmented markets using real-time order-book data.
It needs no timing or slicing algorithm and no additional mathematical models of the kind
AT/HFT strategies rely on. It is infrastructure, not alpha.

## Drivers of AT/HFT adoption

The paper identifies four (explicitly non-exhaustive; it also mentions the growth of prop
firms founded by ex-investment-bank and technical traders).

### 1. Market access models

Only registered members may trade directly, mainly because direct access presupposes an
approved clearing relationship. Members therefore act as access intermediaries (brokers,
the "sell side"; their clients are the "buy side").

- **Direct market access (DMA):** client orders are not touched by the broker but forwarded
  to the market *through the broker's infrastructure*. Key property: the broker can conduct
  pre-trade risk checks.
- **Sponsored access (SA):** a non-member firm routes orders to the market directly using a
  registered broker's member ID, *without* the broker's infrastructure. Pre-trade risk checks
  are possible only if the venue offers them (filtered SA). Under unfiltered / "naked" SA the
  sponsor receives only a drop copy of each order.

Lower latency is the main advantage of SA over DMA, which is precisely why it appealed to
AT/HFT — and precisely why unfiltered SA became a systemic-risk concern. The SEC's own
illustration: a malfunctioning algorithm could place 120,000+ orders in two minutes; at 300
shares and $20 per share, a $720 million position inside that window.

### 2. Fee structures

Three moves by European venues, all pulling in automated flow:
1. special discounts for algorithmic orders in fee schedules,
2. aggressively low MTF fee levels to compete with incumbents,
3. **asymmetric (maker-taker) pricing** — takers pay more, makers pay less or receive a
   rebate. The stated rationale: rebates attract passive limit-order flow and let makers
   quote more aggressively, narrowing spreads; tighter spreads attract market orders, which
   raises makers' execution probability. Some venues run the *inverse* (taker rebate) model.

Incumbent European exchanges were pushed to lower fees, some adopting asymmetric pricing.
Scale check from the paper: estimated total maker rebates on Chi-X in 2009 ≈ €17.4m (2009
turnover ≈ €869.8bn at 0.2 bps), versus ≈ $1.4bn on Nasdaq in 2009. Against a 2010 mean
relative spread of 8.31 bps in a EURO STOXX sample, **spread capturing is a far larger
revenue source than rebates** — useful whenever someone claims HFT is "rebate farming".

### 3. Latency

Speed advantage is not new — floor traders who ran faster or shouted louder got the
specialist's attention. What changed is the mechanism. If the market state at order arrival
differs materially from the state that produced the decision, the order may be wrong in size
or limit, executed at a bad price, or not executed at all. Minimizing that gap drives
investment in low-latency market data receipt, order submission and execution confirmation.

- **Co-location:** the venue operator places a participant's hardware directly adjacent to
  the matching engine.
- **Proximity hosting:** a specialized network provider offers facility space near multiple
  matching engines, optimizing across venues and maximizing flexibility.

Quantifying the economic value of low latency is hard — measurement itself is difficult and
methodologies are inconsistent (Ende et al. 2011).

### 4. Regulation-driven fragmentation

MiFID (2004) created a harmonized level playing field across venue types, deliberately
increasing competition. The intended consequence was fragmentation of liquidity across
venues; new MTFs undercut incumbents on fees and gained share. Explicit and implicit trading
costs fell, which lowers the cost of capital for issuers. It also created the conditions for
cross-market arbitrage and multi-venue quoting — HFT strategies that were not profitable
pre-MiFID.

OTC trading nonetheless held a high, stable share of around 40% of European equity trading
through the period (Thomson Reuters market share reports, 2008–2010).

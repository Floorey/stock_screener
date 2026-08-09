# Empirical evidence and market sizing

Source: Gomber, Arndt, Lutat & Uhle (2011), *High-Frequency Trading*, section 5 and
Appendices I and IV. Everything here reflects literature available up to early 2011 — see
`since-2011.md` before treating any of it as current.

## Contents

- [Headline finding](#headline-finding)
- [Market quality studies](#market-quality-studies)
- [The dissenting findings](#the-dissenting-findings)
- [Fairness and co-location](#fairness-and-co-location)
- [Market penetration and profitability](#market-penetration-and-profitability)
- [Market share estimates](#market-share-estimates)
- [What the data cannot show](#what-the-data-cannot-show)

## Headline finding

Of eight papers focused on HFT, six found no evidence of negative effects on market
quality; the majority argued HFT contributes positively to market quality and price
formation, with the strongest results on liquidity and short-term volatility. Studies of
AT more broadly (Hendershott, Jones & Menkveld; Groth) found positive effects too.

Two papers dissent, in different ways: Jovanovic & Menkveld's theoretical model shows HFT
can *exacerbate* adverse selection under certain conditions, and Kirilenko et al. document
HFT exacerbating volatility during the flash crash.

State the majority finding and the dissent together. The majority result is genuinely the
weight of the evidence; presenting it without the caveats overstates a literature that was
young, thin, and data-constrained even by its own authors' account.

## Market quality studies

**Cvitanić & Kirilenko (2010), "High Frequency Traders and Asset Prices."** The first
theoretical model of HFT's market-quality impact. An electronic market of low-frequency
(human) traders plus one infinitely fast machine, modelled as *uninformed* — following the
classical notion that a market maker has no superior information — whose only advantage is
the speed of order submission and cancellation. The machine mimics a "sniping" strategy
discovering liquidity in the book. Findings: the machine's presence changes the average
transaction price and the whole distribution of prices, concentrating prices around the
mean (i.e. **lower volatility**) and improving forecastability. Trading volume and
intertrade duration — and liquidity measures based on them — increase in proportion to how
much humans change their order speed in response.

*Limitation the authors state:* fundamentals are assumed negligible over short horizons, so
human buy and sell order prices are modelled as two i.i.d. sequences arriving as exogenous
Poisson processes, with unit-size orders at infinitely divisible prices.

**Jarnecic & Snape (2010), "An analysis of trades by high frequency participants on the
London Stock Exchange."** Unusual and valuable because LSE member categorization lets the
authors identify high-frequency participants *directly* rather than by proxy. Members are
classified into six categories (high-frequency participants, traditional market makers,
three institutional types, retail brokers). Cross-sectional regressions on LSE stocks,
April–June 2009. Findings: HFT varies widely across stocks — more prevalent in large-cap
stocks with high on-market competition, high price volatility and strong off-exchange
competition; less prevalent where tick sizes are high and order flow is informed. HFTs are
**more likely to smooth liquidity over time and unlikely to exacerbate volatility**.

*Limitation the authors state:* firms may run high-frequency strategies through another
member's identifier via DMA or sponsored access, so member-based identification is
imperfect.

**Brogaard (2010), "High Frequency Trading and its Impact on Market Quality."** A Nasdaq
dataset in which a group of HFTs is identifiable. In his words:

> "I find that HFTs' supply of liquidity is mixed. They are frequently at the inside bid and
> offer, yet the depth of liquidity they provide on the order book is much less than that
> provided by non-HFTs. In addition, HFTs are strategic with their liquidity provisions and
> tend to avoid trading with informed traders. Finally, I find evidence that suggests HFT
> dampens intraday volatility. Overall, the results in this paper suggest that HFTs'
> activities are not detrimental to non-HFTs and that HFT tends to improve market quality."

Worth quoting in full when someone claims the literature is uniformly glowing: "supply of
liquidity is mixed", thin depth, and strategic avoidance of informed flow are all in the
pro-HFT paper.

**Hendershott, Jones & Menkveld (2011)**, on NYSE stocks, studying AT rather than HFT:

> "For large stocks in particular, algorithmic trading narrows spreads by reducing adverse
> selection and increasing the amount of information in quotes as compared to trades. These
> indicate that algorithmic trading does causally improve liquidity and enhances the
> informativeness of quotes and prices."

**Groth (2011)** on volatility: "provide[s] strong evidence that algorithmic trading does
not exceedingly increase volatility."

**Hasbrouck & Saar (2010)** also fall in the positive-effects group; their main contribution
to this paper is on the fairness question (below).

## The dissenting findings

**Jovanovic & Menkveld (2010), "Middlemen in Limit Order Markets."** Theory plus an event
study exploiting the start of Dutch index stock trading on Chi-X (16 April 2007) as the
introduction of an HFT-friendly venue; first 77 trading days of 2007 vs 2008, with Belgian
index stocks as an untreated control. Crucially, middlemen here are **not** assumed
uninformed — contrasting with Glosten & Milgrom (1985), Kyle (1985), Foucault et al. (2003)
and with Cvitanić & Kirilenko.

Findings: middlemen *are* better informed about recent news than the average investor —
faster reactions, correctly directed trades. On welfare the results are genuinely mixed: in
the model, middlemen can solve a pre-existing adverse-selection problem (raising welfare by
up to 30%, more trading, narrower spreads) **or** create/exacerbate one (rising bid-ask
spreads, declining trades). Empirically, middlemen's participation lowered bid-ask spreads
but also lowered volume. Net effect uncertain.

The comparison with Cvitanić & Kirilenko is instructive and worth making explicitly: the two
models reach different conclusions largely because one assumes the fast trader is uninformed
and the other does not. Modelling assumptions, not data, drive the divergence.

**Kirilenko, Samadi, Kyle & Tuzun (2010), "The Flash Crash."** Documents HFT increasing
short-term volatility during the 6 May 2010 event, including the "hot potato" effect —
rapid selling of contracts between HFTs in a very short period, generating volume without
absorbing directional pressure. Their recommendation is notably not "obligate quoting" but:
"as markets change, appropriate safeguards must be implemented to keep pace with trading
practices enabled by advances in technology."

## Fairness and co-location

Research addresses fairness mostly theoretically and rarely documents the actual terms of
co-location — number of accesses, number of participants, pricing schemes. The paper reads
that gap as a transparency problem preventing comparison of access conditions across
venues. Researchers do agree the speed advantage is recognizable and can yield competitive
advantage.

**Hasbrouck & Saar (2010)** concede co-located traders have a significant timing advantage —
and note floor traders held exactly the same kind of advantage over off-floor traders. On
magnitude:

> "What is the real economic cost of a delay? It depends on both the risk borne over the
> delay duration and the effects on participants' strategies. (…) If the daily volatility is
> unconditionally distributed evenly over the 6.5 hour trading day, then the volatility over
> 10 ms is a negligible 0.2 basis points.
>
> The importance of delay for strategic interactions, however, might be much greater.
> Suppose that the daily volatility is generated by a single randomly-timed announcement
> that causes the value to change (equiprobably) by ±3%. This 3% can be captured by a
> first-mover who observes the announcement and takes a long or short position against
> others yet unaware, irrespective of whether his absolute time advantage is one minute or
> one microsecond."

That pair of paragraphs is the most useful thing in the literature on this question: on a
diffusion view a 10ms advantage is worth nothing; on a discrete-event view it is worth the
whole jump. Both are true, and which dominates depends on the strategy.

They also point out the regulatory tension: the SEC forbids releasing fundamental
information to a subset of investors, yet permits market centers to sell data feeds directly
to subscribers — creating a tiered system of investors.

**Jovanovic & Menkveld (2010)** suggest a market-design response rather than a ban:

> "…the speed privilege that HFTs can buy into, co-location, might require a differentiated
> order-fee schedule. Passive orders submitted through this pipe might optimally be rewarded
> more whereas aggressive orders might have to be charged more. The reason is that passive
> orders come with the positive externality of liquidity supply to others whereas aggressive
> orders have a negative externality of creating adverse selection for non-co-located
> participants."

**Ende et al. (2011)**: latency effects are negligible for retail investors individually —
their trading frequency is low and the costs of latency disadvantage are small. For everyone
else, the degree of harm depends heavily on the strategy applied.

The paper's conclusion on fairness: no academic study found evidence that HFT applies unfair
or illegal strategies. The co-location debate is about **fair access**, not about assumed
negative effects of faster trading — and fair, non-discriminatory access is a matter for
regulators, venues and traders to settle, not a distinctive HFT pathology.

## Market penetration and profitability

| Source | Measure |
|---|---|
| Brogaard (2010) | HFT involved in **68%** of dollar trade volume in his Nasdaq dataset; gross return ≈ **$2.8bn** annually; Sharpe ratio ≈ **4.5** |
| Jarnecic & Snape (2010), LSE | High-frequency participants in **20–32%** of total trades and **19–28%** of total volume depending on stock size; counting trades where they are on *either* side without double-counting, **40–64%** |
| Kearns et al. (2010) | Upper bound on HFT profitability: an *omniscient* trader knowing future prices could have made **$3.4bn** in 2008. The authors argue this is a large overestimate — it ignores trading fees, adverse price movement and other profit-reducing factors, and covers only aggressive (marketable) order placement |
| Tradeworx (2010a) | ≈ **$2bn** annually, based on a 40% market share (an HFT firm's own estimate, in an SEC comment letter) |

Note the convergence: an industry self-estimate ($2bn), an academic estimate ($2.8bn) and a
theoretical ceiling ($3.4bn) are in the same order of magnitude — which is mild evidence
that the profit pool was well below the rhetoric of the period.

The paper's judgement on what this justifies: HFT's size and penetration are good reasons to
fund further research, particularly on systemic risk — but **increasing market share is not
itself a justification for regulatory intervention**.

## Market share estimates

### European estimates from CESR's Call for Evidence (via AFM 2010)

| Respondent | Estimated HFT share of European market |
|---|---|
| BATS | — (does not use a specific HFT classification) |
| Borsa Italiana (LSE) | 20% equities / 30% futures |
| Chi-X | 40% |
| Deutsche Bank | 35–40% |
| LSE | 33% |
| Nasdaq OMX | 13% (Nordic markets) |
| NYSE Euronext | 23% (was 5% in Q1 2007) |
| SIX Swiss | — (does not use a specific HFT classification) |
| Turquoise (LSE) | 21% |
| Flow Traders | 45% |
| IMC | >40% (derived from market figures; considers it too high) |
| Optiver | 30–40% (derived from Rosenblatt Securities) |
| AITE Group | 25% (expecting 30% end-2010, 45% in 2012) |
| Rosenblatt Securities | 30–40% futures / 35% equities |
| European Banking Federation | 50–80% (all forms of algorithmic trading) |

### Industry and academic studies

| Source | Date | U.S. | Europe | Australia |
|---|---|---|---|---|
| TABB Group | Sep-09 | 61% | | |
| Celent | Dec-09 | 42% of trade volume | rapidly growing | |
| Rosenblatt Securities | Sep-09 | 66% | ~35% and growing fast | |
| Brogaard | Nov-10 | 68% of Nasdaq trade volume | | |
| Jarnecic & Snape | Jun-10 | | 20–32% of LSE trades, 19–28% of volume | |
| Tradeworx | Apr-10 | 40% | | |
| ASX | Feb-10 | | | 10% of ASX trade volume |
| Swinburne | Nov-10 | 70% | 40% | |
| TABB Group | Jan-11 | | 35% of overall UK market, 77% of turnover in continuous markets | |

The spread within a single year — 13% to 40% for Europe, 40% to 70% for the U.S. — is the
finding, not noise to be averaged away. Respondents were using incompatible definitions and
mostly could not observe HFT directly. Quote a range with its source, never a single number
as "the" HFT share.

## What the data cannot show

Three constraints the paper is explicit about, and which should accompany any citation of
the above:

1. **No order-level identification.** It is "nearly impossible for researchers (and
   regulators) to identify exactly on an order-by-order basis whether the respective action
   can be allocated to HFT operations." Studies rely on venue member categorization
   (Jarnecic & Snape), dataset flags (Brogaard) or behavioural screens (Kirilenko et al.).
   Each is a proxy with its own failure mode — notably that a firm can route HFT flow
   through another member's identifier.

2. **Lit markets only.** Every empirical paper cited, on AT and HFT alike, uses lit-market
   data. There are no empirical papers on automated trading in the OTC space —
   internalization systems, broker crossing networks, dark venues — because the data does
   not exist. Given OTC's ~40% European share, that is a large blind spot in a literature
   used to make policy about lit-market participants.

3. **Behaviour under stress is understudied.** Most analyses cover normal conditions. The
   flash crash literature is the exception, and it is the one place a negative finding shows
   up. Several studies note the *risk* that absent quoting obligations liquidity may be
   suddenly withdrawn, but no research paper provides empirical evidence for it.

The paper's own recommendation follows: further research, ideally in cooperation with HFT
entities, is highly desirable.

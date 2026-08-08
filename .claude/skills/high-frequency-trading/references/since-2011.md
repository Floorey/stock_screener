# What changed after 2011

**This file is not from the paper.** Gomber et al. (2011) describes proposals that were open
questions at the time; most were resolved, several against the paper's recommendation. Read
this before making any claim about current rules, current market shares, or the state of the
latency-arbitrage question.

Treat the specifics here as orientation, not citation. Regulation keeps moving; verify dates,
thresholds and current status against primary sources (ESMA, the Official Journal, SEC
releases) before relying on them in anything consequential.

## Contents

- [Scorecard: what the paper got right and wrong](#scorecard-what-the-paper-got-right-and-wrong)
- [European Union](#european-union)
- [United States](#united-states)
- [The latency-arbitrage question, reopened](#the-latency-arbitrage-question-reopened)
- [What happened to the industry](#what-happened-to-the-industry)
- [Which parts of the paper still hold](#which-parts-of-the-paper-still-hold)

## Scorecard: what the paper got right and wrong

| The paper argued | Outcome |
|---|---|
| Against HFT market-making obligations | **Rejected.** MiFID II requires firms pursuing a market-making strategy to sign binding agreements with venues and quote for a specified proportion of trading hours. |
| Against order-to-trade ratio caps | **Rejected.** MiFID II requires venues to impose OTR limits; Germany's 2013 HFT Act did so earlier. |
| Against minimum order resting times | **Upheld.** A minimum resting time (a 500ms version was debated during MiFID II negotiations) was not adopted. |
| For coordinated, security-specific volatility safeguards over a rolling time window, triggering auctions | **Adopted, on both continents.** MiFID II requires venue circuit breakers with regulator-notified parameters; the U.S. Limit Up-Limit Down plan runs price bands over a rolling five-minute reference — very close to the paper's proposal. |
| For a functional, not institutional, approach | **Partly adopted.** MiFID II regulates the *technique* and closed the own-account exemption for HFT, but "high-frequency algorithmic trading technique" is still a defined status with attached obligations. |
| For closing the naked sponsored access gap | **Adopted** on both continents. |
| That layering, spoofing and quote stuffing are abuse to be prosecuted as such, not HFT problems | **Adopted.** Named explicitly in EU market abuse rules; prosecuted criminally in the U.S. |
| That the OTC/dark space was being ignored | **Addressed later** — MiFID II brought volume caps on dark trading, an expanded systematic internaliser regime and a share trading obligation. |
| That evidence showed no market-quality harm | **Contested.** Later work using better data found a measurable latency-arbitrage cost that 2011 methods could not detect. |

## European Union

**MiFID II / MiFIR** (Directive 2014/65/EU and Regulation (EU) 600/2014, applicable
3 January 2018) is the main event. It converted almost every 2011 open question into law.

- **Legal definitions.** "Algorithmic trading" and "high-frequency algorithmic trading
  technique" are now defined terms. The HFT definition is infrastructure-based:
  co-location, proximity hosting or high-speed direct electronic access; system determination
  of order initiation, timing, price or quantity without human intervention; and high
  intraday rates of messages (orders, quotes, cancellations). Note that this is broadly the
  paper's characteristic list turned into a legal test — including the "most but not all"
  problem it warned about.
- **Firm-level requirements (Art 17 and RTS 6).** Effective systems and risk controls,
  business continuity, testing of algorithms, kill functionality, pre-trade limits,
  notification to competent authorities, annual self-assessment, and record-keeping of
  algorithms. This is essentially the paper's own systemic-risk list made mandatory — the
  part of its recommendations that was adopted wholesale.
- **Market-making obligations (Art 17(3)–(4), RTS 8).** A firm pursuing a market-making
  strategy must enter a binding written agreement with the venue and post firm quotes
  continuously during a specified proportion of trading hours — in practice at least half of
  daily trading hours — except under exceptional circumstances. The paper's central policy
  argument lost here.
- **Venue-level requirements (Art 48, RTS 7/9/11).** Resilient systems able to handle peak
  volumes, circuit breakers with parameters notified to regulators, **order-to-trade ratio
  limits**, a harmonized **tick size regime** scaled by liquidity, fee structures that must
  not encourage disorderly trading, transparent and non-discriminatory co-location, testing
  facilities, and **flagging of algorithmic order flow** so regulators can identify it.
  That last item directly addresses the paper's "no order-by-order identification" complaint.
- **Authorization.** The own-account dealing exemption no longer covers firms using a
  high-frequency algorithmic trading technique — they must be authorized as investment firms.
- **Dark trading.** Volume caps on trading under reference-price and negotiated-trade waivers
  (originally a double 4%/8% cap, replaced by a single cap in the 2024 MiFIR review), an
  expanded systematic internaliser regime, and a share trading obligation. The paper's blind
  spot (ii) was subsequently legislated into.
- **2024 MiFIR review** (Regulation (EU) 2024/791) added an EU consolidated tape — the thing
  Europe conspicuously lacked in 2011 — alongside the volume-cap and SI changes.

**Market Abuse Regulation** (Regulation (EU) 596/2014, applicable July 2016) explicitly names
abusive algorithmic and HFT practices — quote stuffing, layering and spoofing, momentum
ignition — as market manipulation, with supporting indicators in the implementing acts. The
Swinburne Report's request was granted, and it was done the way the paper preferred: as
abuse rules of general application rather than as HFT-specific prohibitions.

**Germany's Hochfrequenzhandelsgesetz** (High Frequency Trading Act, 2013) preceded MiFID II
with authorization requirements, algorithm flagging, order-to-trade limits and minimum tick
sizes — the first national HFT-specific statute, and worth knowing about when the question
is German-market-specific.

**National financial transaction taxes.** France (2012) and Italy (2013) introduced FTTs; the
Italian version includes a levy on high-frequency orders modified or cancelled within a very
short interval. The EU-wide FTT has never been adopted. These are the clearest examples of
the "tax the speed" approach the paper did not address.

## United States

- **Market Access Rule (15c3-5, 2010)** confirmed the ban on unfiltered sponsored access
  described in the paper.
- **Stub quotes** prohibited (2010), and **clearly erroneous trade** rules revised, both
  post-flash-crash.
- **Limit Up-Limit Down (LULD)** replaced the single-stock circuit breaker pilot: percentage
  price bands around a rolling five-minute average, with limit states and short trading
  pauses. Piloted from 2012, made permanent later in the decade. This is the closest
  real-world implementation of the paper's proposed second band, and its record is a useful
  test of the proposal.
- **Regulation SCI (2014)** imposed systems capacity, integrity, resilience and business
  continuity requirements on key market participants — the venue-side half of the paper's
  systemic-risk list.
- **Consolidated Audit Trail (CAT).** Rule 613 was adopted in 2012; implementation ran years
  late, with phased reporting from the late 2010s into the 2020s. It is the U.S. answer to
  order-level identification, and its long delay is itself part of the story.
- **Flash orders.** The proposed ban was never finalized. Major equity venues discontinued
  the functionality voluntarily around 2009–2010, which removed most of the issue without a
  rule.
- **Proprietary trading firm registration.** The exemption that let some high-volume
  proprietary firms trade without FINRA membership (Rule 15b9-1) was narrowed by amendment in
  2023, with compliance phasing in afterwards — the U.S. analogue of MiFID II closing the
  own-account exemption.
- **Reg NMS amendments (2024)** revised tick sizes, access fee caps and the round lot
  definition, and expanded odd-lot data — phasing in over 2025–2026. The **Market Data
  Infrastructure Rule (2020)** would decentralize consolidation and expand core data beyond
  top-of-book; litigation slowed it.
- **Spoofing** became a specific criminal offence under Dodd-Frank §747 (2010), with
  convictions from 2015 onward. Navinder Sarao's prosecution connected spoofing to the flash
  crash itself — a link the 2010 official report did not draw.
- **IEX** was approved as an exchange in 2016 with an intentional speed bump, making
  latency-arbitrage mitigation a market-design product rather than only a regulatory question.

## The latency-arbitrage question, reopened

The paper explicitly declined to assess latency arbitrage's magnitude, and presented the
Themis/Tradeworx dispute as unresolved. Post-2011 work substantially advanced it, and the
answer is less comfortable than the 2011 literature suggested.

- **Budish, Cramton & Shim (2015)**, "The High-Frequency Trading Arms Race: Frequent Batch
  Auctions as a Market Design Response". Argues that the continuous limit order book
  *mechanically* generates latency arbitrage: correlated assets' prices jump, and whoever is
  fastest picks off stale quotes. On this account the arms race is a market-design artifact,
  not a behavioural problem, so speed regulation cannot fix it — the design has to change
  (they propose frequent batch auctions). This reframes the question in a way the 2011 paper
  does not anticipate.
- **Aquilina, Budish & O'Neill (2022, Quarterly Journal of Economics)**, "Quantifying the
  High-Frequency Trading Arms Race", using LSE message data with microsecond timestamps.
  Finds latency-arbitrage races are a real and measurable phenomenon, that races account for
  a meaningful share of trading volume, and that they impose a small but non-zero tax on
  liquidity. The magnitudes are modest in relative terms — which cuts both ways: it is
  neither the market-destroying phenomenon of the popular accounts nor the non-event the
  2011 literature implied.

Two consequences for how to use the paper. First, its claim that latency arbitrage is
NBBO-specific and therefore inapplicable to Europe **does not survive** — the LSE study
measures races in a market with no NBBO. Second, the mechanism identified is not
rule-breaking, which supports the paper's insistence that this is not market abuse, while
undercutting its implication that there is nothing to see.

Other significant post-2011 empirical work: Menkveld (2013) on HFT as the new market makers,
and Brogaard, Hendershott & Riordan (2014) finding HFTs trade in the direction of permanent
price changes and against transitory pricing errors — i.e. contributing to price discovery.
Michael Lewis's *Flash Boys* (2014) drove the public debate for years and is worth naming
when a user's framing seems to come from it.

## What happened to the industry

- **Market share plateaued and profitability fell sharply.** U.S. equity HFT volume share
  came off its 2009 peak and settled around half of volume, while aggregate revenues declined
  substantially from the 2009 highs as competition compressed margins. If someone quotes the
  paper's 60–70% figures as current, that is the correction to make.
- **Consolidation.** The specialist boutique population thinned; several large firms merged
  or were acquired, and a few (Virtu, Flow Traders) went public — which incidentally made
  HFT revenue data public for the first time.
- **The speed race moved off fibre.** Microwave, millimetre-wave and laser links between data
  centres, then FPGA and ASIC order handling, pushed tick-to-trade into nanoseconds. Physical
  latency between major venues is now close to the speed-of-light limit, which is part of why
  the profit pool shrank.
- **The strategies did not change much.** Market making, cross-venue and cross-asset
  arbitrage, and short-term signal trading remain the core — which is the paper's thesis
  holding up: the technology evolved, the strategies were already old.

## Which parts of the paper still hold

Genuinely durable:

- HFT is a technology, not a strategy; assess the underlying strategy.
- Functional rather than institutional assessment.
- The AT/HFT characteristic tables as a working taxonomy — MiFID II's legal definition is
  recognizably built on them.
- The structural U.S./Europe distinction (NBBO and trade-through vs firm-level best
  execution), which remains the single most useful thing to know when reading cross-Atlantic
  HFT commentary.
- The adverse-selection asymmetry between lit-market HFT market makers and internalizers who
  know their counterparties.
- The critique of minimum resting times, which prevailed.
- The systemic-risk requirements — logging, kill switches, venue capacity, human availability,
  supervisory skills — essentially all of which became law.

Dated or superseded:

- Every regulatory status claim (read as history, not law).
- All market-share and profitability figures.
- The claim that European market structure makes HFT concerns inapplicable — MiFID II
  legislated on the assumption that it does not, and the LSE latency-arbitrage evidence
  points the same way.
- The confident reading of the literature as showing no harm: the data available in 2011 could
  not have detected what later microsecond-resolution studies found.

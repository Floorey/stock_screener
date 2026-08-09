# Strategy taxonomy

Source: Gomber, Arndt, Lutat & Uhle (2011), *High-Frequency Trading*, section 4. The
HFT-side classification into liquidity provision, statistical arbitrage and liquidity
detection follows ASIC (2010a); the execution-algorithm generations follow Almgren (2009)
with detail from Johnson (2010).

## Contents

- [Algorithmic execution strategies](#algorithmic-execution-strategies)
  - [First generation](#first-generation-market-data-benchmarks)
  - [Second generation](#second-generation-implementation-shortfall)
  - [Third generation](#third-generation-adaptive)
  - [Fourth generation](#fourth-generation-newsreader-algorithms)
- [HFT strategies](#hft-strategies)
  - [Electronic liquidity provision](#electronic-liquidity-provision)
  - [(Statistical) arbitrage](#statistical-arbitrage)
  - [Liquidity detection](#liquidity-detection)
  - [Latency arbitrage](#latency-arbitrage-contested)
  - [Short-term momentum](#short-term-momentum)
- [Abusive strategies](#abusive-strategies-not-hft-categories)
- [Who runs HFT](#who-runs-hft)

## Algorithmic execution strategies

These are the non-HFT part of AT. The shared goal is to minimize the market impact of a
large parent order by slicing it into child orders spread across time and venues against a
pre-set benchmark. Some participants run variants of these without HFT-grade latency
sensitivity.

The generational split tracks *what the benchmark is anchored to*: generation 1 uses
market-generated data independent of the order; generation 2 anchors to the order itself
and manages the impact/timing trade-off; generation 3 adapts during execution.

### First generation: market-data benchmarks

**Participation rate algorithms.** Participate up to a predefined share of market volume —
e.g. trade 5% of volume in the target instrument until the position is built or liquidated.
Because they target *traded volume*, their orders reflect current market activity. Variants
add execution windows, maximum volumes or price limits. Participation rates are often
randomized to make the algorithm harder for others to detect. Caveat: with only a preset
execution period, the full target may not be reached if volume is insufficient.

**TWAP (time weighted average price).** Divide the order into slices sent at equally spaced
intervals. Slice size and execution period are fixed before execution begins — e.g. buy
12,000 shares in one hour in blocks of 2,000, one order every 10 minutes. Order sizes and
intervals can be varied to resist detection.

**VWAP (volume weighted average price).** Match or beat the volume weighted average price
over a specified period:

```
VWAP = Σ(pₙ · vₙ) / Σ(vₙ)      for n trades at price pₙ and size vₙ
```

Because trades are size-weighted, large trades move the benchmark more than small ones.
VWAP algorithms rely on historical volume profiles of the instrument in the relevant market
to estimate the intraday volume pattern of the target period.

| Algorithm | Benchmark anchored to |
|---|---|
| Participation rate | Volume |
| TWAP | Trading period |
| VWAP | Price (volume weighted) |

### Second generation: implementation shortfall

The benchmark becomes the price or midpoint **at the moment the order arrives** — an
order-based rather than market-based benchmark. The algorithm minimizes market impact while
accounting for adverse price movement during execution (timing risk), predetermining an
execution plan from historical data and splitting the order into as many sub-orders as
necessary but as few as possible.

The trade-off is the point: slower execution reduces market impact but increases timing
risk; faster execution does the reverse. Unlike TWAP or VWAP, orders are scattered over a
period only just long enough to dampen the overall market impact.

### Third generation: adaptive

Rather than fixing a schedule up front, adaptive algorithms re-evaluate and adjust the
execution schedule *during* the execution period, responding to changing market conditions
and to their own realized performance — executing more or less aggressively as gains or
losses accumulate against the benchmark.

### Fourth generation: newsreader algorithms

Not in Almgren's classification. Automated newsreaders apply statistical and text-mining
techniques to estimate the likely market impact of news announcements. They depend on
low-latency machine-readable news feeds, which exchanges and news agencies developed for
exactly this audience. The motivation is a hard human limit: a person can only read and
process so much, so fast.

## HFT strategies

The universe is too diverse and opaque to enumerate. What follows are the best-known ones.
Keep the framing: these are traditional strategies implemented with state-of-the-art IT, not
inventions of HFT.

### Electronic liquidity provision

One of the most common HFT strategies: act as a liquidity provider, typically **without**
formal obligations to quote. Two revenue sources:

1. the bid-ask spread earned by providing liquidity,
2. rebates or reduced transaction fees granted by venues to incentivize liquidity provision.

**Spread capturing.** The closest analogue to traditional market making: continuously buy
and sell, reaping the difference between the higher price at which participants can buy and
the lower price at which they can sell.

**Rebate-driven strategies.** Built around venue incentive schemes — asymmetric (maker-taker)
pricing charges liquidity takers more and pays or discounts liquidity makers. In some cases
rebates subsidize the quoting of very tight spreads, making rebates the dominant profit
source for those traders (Iati et al. 2009). Some venues run the inverse model, rebating
takers.

Scale, for calibration: estimated maker rebates on Chi-X in 2009 ≈ €17.4m, versus ≈$1.4bn on
Nasdaq in 2009 — a difference driven by turnover and by fee-schedule design (Chi-X paid on a
volume basis, Nasdaq per share). Against a 2010 mean relative spread of 8.31 bps in a EURO
STOXX sample, spread capturing is the much larger revenue pool.

### (Statistical) arbitrage

Arbitrage opportunities frequently exist only for fractions of a second, which is what makes
them a natural fit for machines. These strategies are not HFT-specific — non-automated
participants run them too — but arbitrageurs react to existing inefficiencies and are
therefore mainly **takers** of liquidity.

**Market-neutral arbitrage.** Hold one instrument while shorting another closely correlated
one, so that general market movements largely offset. The position expresses a *relative*
valuation view: sell the instrument deemed relatively overvalued, buy the one deemed
relatively undervalued but similarly market-sensitive. Profit is realized when the relative
valuation normalizes and the position is unwound. The protection against market direction is
what makes it attractive to HFTs and traditional arbitrageurs alike (Aldridge 2010).

**Cross-market arbitrage.** Same asset, different prices across venues: sell where it is
valued higher, buy where it is valued lower, simultaneously. Profitability requires the
bid-ask difference to exceed twice the transaction fees. These strategies benefited directly
from MiFID-driven fragmentation — more venues means more probability of price divergence.

**Cross-asset arbitrage.** Related instruments: e.g. an option priced too high relative to
its underlying — sell the option, buy the underlying.

**ETF arbitrage.** Trade an ETF against its underlying basket, profiting from pricing
inefficiencies between them.

### Liquidity detection

Strategies that infer the patterns other participants leave in the market and act on them.
Targets: large orders, sliced orders, hidden orders, orders being worked by execution
algorithms, and information about the state of electronic limit order books. Detectors aimed
at algorithmic traders are described as "sniffing out" other algorithms (in the U.S.
consolidated-tape context, "sniffing the tape"); others "ping" or "snipe" order books and
dark pools to extract information.

AFM (2010) describes the related order-anticipation family: "a trader looks for the existence
of large (for example) buyers, in the objective of buying before these orders, in order to
benefit from their impact."

**Quote matching** (Harris 2003, in a high-speed version). Having detected a large resting
order, place your own order ahead of it. Detect a large buy order, place your buy slightly
higher: if prices rise you profit; if they fall, the large resting order functions as an
option/hedge you can sell into, capping the loss for as long as it rests in the book.

This is the family most deserving of scrutiny, and it is worth being precise about why: the
concern is not speed, it is that the profit derives from other participants' revealed
intentions rather than from price discovery or liquidity supply. Note also that it is *not*
front-running in the legal sense — there is no client order and no agency duty being
breached.

### Latency arbitrage (contested)

The accusation: HFTs see and interpret new market information before other participants
receive it, using direct data feeds and co-located infrastructure. In the U.S., where many
participants rely on the consolidated NBBO, latency arbitrageurs are said to profit against
a stale NBBO. Themis Trading's version (Arnuk & Saluzzi 2009): knowing an order will move
the NBBO before the NBBO reflects it, trade against liquidity at the stale displayed price
and offer it back to the trader who caused the move, at a higher price for an incoming buy
or a lower price for an incoming sell. Such participants are labelled "predatory".

The rebuttal (Narang / Tradeworx 2010): latency alone cannot get you ahead of existing
orders. That the NBBO does not instantly reflect an order says nothing about that order's
priority in the book — the orders *are already in the book*, they are simply not yet
reflected in the NBBO, so there is no liquidity left to trade against. Tradeworx locates the
real mechanism elsewhere: U.S. broker-dealer HFTs can use the **intermarket sweep order
(ISO)**, a limit order designated for automatic execution in a specific market center even
when another center publishes a better quotation (the sender concurrently sends orders to
the better-priced centers, discharging Reg NMS order-protection obligations). ISOs can
execute directly into venues that appear locked due to consolidated-feed latency, while
ordinary orders cannot — which Tradeworx argues can violate time priority. Their ask was
that regulators lift the ban on locked markets (Rule 611 Reg NMS prohibits them).

Two things to carry from this:
- The authors explicitly decline to assess the real-world magnitude of latency arbitrage.
- The whole debate is built on the NBBO, a distinctively U.S. feature. Forms of it that
  depend on the NBBO **do not apply to European markets**, which have no statutory NBBO.

### Short-term momentum

The modern equivalent of classical day trading: neither providing liquidity nor targeting
inefficiencies, but trading aggressively (taking liquidity) to profit from market movements
and trends, driven by events or by the movements themselves. Momentum strategies are old;
only the implementation is new.

Distinguish carefully from **momentum ignition**, where participants deliberately *induce*
market movements in order to profit from them — potentially abusive and under regulatory
investigation.

## Abusive strategies (not HFT categories)

These are market-abuse patterns. Technology can make them easier, faster and more
profitable, which is a supervisory concern — but they are defined by intent and effect, not
by speed, and non-abusive HFT should not be tarred with them.

**Spoofing** (AFM 2010): introducing an order not meant to be executed, whose size and
ranking in the book shift the spread to another level.

**Layering** (AFM 2010): a form of spoofing in which a trader inserts a large quantity of
orders at different price limits on one side of the book to create the impression of
pressure on that side, while actually intending to trade the opposite way; the original
orders are cancelled before execution.

**Quote stuffing**: flooding the marketplace with bogus orders to distract or degrade the
processing of rival trading firms (Rampton et al.). Investigated as a factor in the flash
crash.

**Momentum ignition**: deliberately triggering price movement in order to profit from it.

The paper's position: any strategy with a negative impact on market integrity must be
thoroughly investigated and effectively combated by supervisory authorities — and because
market abuse is not confined to any particular subset of traders, *all* participants should
be investigated when applying such strategies, not only the fast ones.

## Who runs HFT

The population is heterogeneous: broker-dealer-operated proprietary trading firms,
broker-dealer market-making operations, specialized HFT boutiques, and quantitative hedge
funds using HFT technology to improve returns on their existing strategies (Easthope & Lee
2009). Hybrid forms are common — e.g. broker-dealers running proprietary books with HFT
techniques.

This is the basis for the paper's **functional rather than institutional** rule: assess the
activity, not the firm type. Regulation aimed at specialized players alone both undermines a
level playing field and misses a large share of actual HFT activity — including, the paper
notes, activity that falls outside investment-firm registration through exemptions for
persons dealing on own account.

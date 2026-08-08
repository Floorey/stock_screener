# Market structure and the 2011 regulatory debate

Source: Gomber, Arndt, Lutat & Uhle (2011), *High-Frequency Trading*, sections 6 and 7.
**This describes the state of play in early 2011.** Much of it has since been overtaken —
see `since-2011.md` before answering anything about current rules.

## Contents

- [U.S. vs European market structure](#us-vs-european-market-structure)
- [U.S. initiatives](#us-initiatives)
- [The flash crash](#the-flash-crash)
- [European initiatives](#european-initiatives)
- [The paper's assessment](#the-papers-assessment)
  - [Scope: two blind spots](#scope-two-blind-spots)
  - [Systemic risk](#systemic-risk)
  - [Market-making obligations](#market-making-obligations)
  - [Safeguards: the proposed alternative](#safeguards-the-proposed-alternative)
  - [Minimum order lifetimes and order-to-trade ratios](#minimum-order-lifetimes-and-order-to-trade-ratios)
- [Conclusions](#conclusions)

## U.S. vs European market structure

Two features define the U.S. system:

- **Reg NMS codifies the NBBO.** Venues must send their best bid and offer for listed
  securities to a securities information processor (SIP), which aggregates them into the
  nationwide best bid and offer.
- **Rule 611 Reg NMS: the trade-through (order protection) rule.** Venues may not execute at
  prices worse for customers than the NBBO. A venue that cannot match an incoming order at
  the NBBO or better must route it to the venue offering the best price — which requires
  inter-linkage of all markets — or cancel it. (Routing away is required only where the
  better price is on a *fast* market; floor markets, unable to match electronic speed,
  implemented electronic systems to avoid losing order flow.)

Consequence: price becomes the dominant determinant of where a trade executes, so new venues
displaying aggressive quotes can pull orders from established exchanges.

Europe under MiFID took a different route — principles-based rather than rules-based:

> "[…] take all reasonable steps to obtain, when executing orders, the best possible result
> for their clients taking into account price, costs, speed, likelihood of execution and
> settlement, size, nature or any other consideration relevant to the execution of the
> order." (European Commission 2004)

Two structural differences follow:
1. **No pan-European NBBO** and no re-routing obligation.
2. **Best execution is an obligation on investment firms**, not outsourced to venues as in
   the U.S.

Because MiFID does not codify implementation, firms may satisfy it either as a *process*
(route to venues that have demonstrated consistently good results) or *order by order*
(determine the best venue per order using real-time market data — going beyond MiFID's
minimum, and requiring SOR, which is costly and not available to everyone).

Both MiFID and Reg NMS made it easier for new venues to compete with incumbents, which was
the point, and both improved fee and service competition.

## U.S. initiatives

**Naked / unfiltered sponsored access.** Traders route orders using a sponsoring broker's
market participant identifier (MPID) *without* associated pre-trade risk checks — attractive
to non-member HFTs precisely because skipping checks reduces latency. Risk control is
possible only via drop copies, by which point erroneous orders may already have executed.
In November 2010 the SEC issued a de facto ban, requiring brokers "to put in place risk
management controls and supervisory procedures to help prevent erroneous orders, ensure
compliance with regulatory requirements, and enforce pre-set credit or capital thresholds",
under the broker's direct and exclusive control. Widely accepted; the main objection
concerned broker-to-broker access, handled by an exception allowing risk management to be
allocated to a sponsored customer that is (i) a registered broker-dealer and (ii) able to
implement the processes more effectively.

The paper endorses this one without reservation: mandatory risk checks in the order routing
system clearly help mitigate systemic risk.

**Flash orders.** Built on an exception to the trade-through rule. If a marketable order
cannot execute against available liquidity at its venue, instead of being routed away it is
"flashed" within that venue for a period usually measured in milliseconds, displayed at the
national best bid or offer — effectively converting a marketable order into a limit order at
the NBBO. If someone steps up and executes against it, it is never routed to the venue with
the best price.

Because flashes last fractions of a second, only HFTs and similarly low-latency participants
can react, which drove fairness complaints. Critics (Kaufman 2009, Leibowitz 2009) argued
flash orders create a two-tiered market, impair price discovery and undermine the
consolidated tape; also that they disincentivize liquidity provision by limit orders, since
limit orders become less likely to be executed against orders routed from other markets.
Defenders pointed to positive effects in options markets — added liquidity, price improvement
(Brodsky 2010). The SEC proposed a ban (2009) and issued a second call for comments on the
options-market case (2010).

**Co-location / proximity hosting.** In June 2010 the CFTC proposed a rule to assure equal
and fair access, arguing these services confer significant competitive advantage and must
therefore be equitably accessible. Elements: uniform fees for co-location and associated
services at venues and third parties listing significant price discovery contracts (any
privileged pricing for specific participants or classes would not count as equitable);
mandatory **latency transparency** — disclosure of longest, shortest and average latencies,
regularly updated; and assurance that sufficient co-location space exists so shortages
cannot impair fair access. Some respondents raised organizational concerns about
implementation.

**Large trader reporting system.** Proposed by the SEC to identify large traders and collect
data on their activity, increasing regulators' ability to analyze the behaviour of
significant participants.

## The flash crash

6 May 2010. What the CFTC/SEC joint report and Kirilenko et al. describe:

1. A "hot potato" effect: HFTs rapidly sold securities among each other over a very short
   period, generating volume without absorbing the directional pressure.
2. Registered market makers *and* HFTs without market-making obligations then **stopped
   providing liquidity** as markets continued to behave abnormally.
3. Worse: rather than providing liquidity, both registered and non-registered market makers
   began actively *taking* liquidity — plausibly to hedge open positions — exacerbating
   volatility and price movements.
4. Market makers stated they had encountered technical problems, i.e. unusual latencies,
   leading to a complete stop of liquidity provision.

Point 4 is doing heavy lifting in the paper's argument. Most markets let market makers pull
quotes when they hit data or system problems; "waving the technical white flag" is therefore
an available exit in extreme stress. Combined with the numerous executions at stub-quote
levels caused by missing market-maker quotes, this is the paper's central evidence that
market-making obligations fail exactly when they are needed, and that the issue is the same
for registered and non-registered market makers.

Resulting U.S. regulation included security-specific circuit breakers, revised clearly
erroneous trade rules, and a prohibition on market maker stub quotes; the consolidated audit
trail was also proposed in this period.

**Terminology:** flash orders and the flash crash are unrelated phenomena that happen to
share a word. The paper flags this explicitly because the confusion was common.

## European initiatives

**CESR Technical Advice to the European Commission (2010b).** Sought authority for the
European regulator to develop binding technical standards in defined areas of RM/MTF
organisational requirements. On sponsored access: identify the risks of naked access and
analyze pre- and post-trade checks. On co-location: more transparency on an objective basis.

**Report on Regulation of Trading in Financial Instruments — the "Swinburne Report"
(European Parliament 2010).** Three flash-crash-driven measures for European markets:
- robust infrastructure at all trading platforms (ability to cope with order barrage),
- demonstrated ability to re-create order books after unusual market activity,
- ESMA supervision and definition, by implementing acts, of pan-European volatility
  interrupts and circuit breakers.

Plus: more investigation of HFT costs and benefits, especially whether HFT provides *real*
liquidity; examination of market-abuse potential, with **layering and quote stuffing to be
defined as market abuse**; a prohibition on flash orders in Europe; investigation of whether
HFT entities need regulating and whether their algorithms should be reviewed regularly
(especially behaviour under stress); examination of whether HFT creates new market-abuse
detection challenges; non-discriminatory access to co-location; prohibition of naked access
with appropriate risk management for all access models; a requirement that proprietary
algorithmic traders — then unregulated by MiFID — trade solely through a regulated
intermediary, with expansion of MiFID reporting rules to cover them "as a matter of
urgency"; and ESMA research into whether recipients of maker rebates should be subject to
formal market-maker obligations.

**MiFID Review consultation (European Commission 2010).** Sought input on:
- a broader definition of AT, with HFT as a subgroup;
- authorizing as investment firms all persons involved in HFT above a minimum threshold,
  including proprietary HFTs currently exempt under Article 2.1(d);
- amendments to Articles 13, 14 and 39 covering risk controls against trading system errors,
  notification of competent authorities on the design, purpose and functioning of algorithms,
  risk controls for sponsored access, and for venue operators: risk controls, circuit
  breakers, stress tests and equal, non-discriminatory access to co-location.

And two proposals the paper calls potentially highly controversial, as they directly affect
HFT business models by requiring regulated market operators:

> (i) to ensure that a high frequency trader has to provide continuous liquidity (by
> quotation) similar to market makers if it executes significant numbers of trades in
> financial instruments on the market, and
>
> (ii) to ensure that "orders would rest on an order book for a minimum period before being
> cancelled. Alternatively they would be required to ensure that the ratio of orders to
> transactions executed by any given participant would not exceed a specified level."

Minimum tick sizes were also discussed but were less controversial, European RMs and MTFs
having already agreed on harmonization.

## The paper's assessment

### Scope: two blind spots

**(i) The need to regulate is being treated as given.** The prior question — whether existing
regulation (e.g. on market abuse) suffices, or whether transparency, communication and
voluntary self-commitment could handle it — appears already answered in favour of
regulation. Striking, the authors say, given that data is lacking and there is still no
agreed terminology or clear differentiation of roles, strategies and actors. (Each new
regulatory document adds another definition.)

**(ii) The discussion covers only regulated venues, ignoring the OTC/dark space.** European
OTC held a high, stable ~40% share. Gomber et al. (2011b) show most European OTC trades are
small — nearly every second OTC trade in high-liquids was below Standard Market Size, and
70%+ of high-liquid OTC trades would have faced no market impact on the transparent
reference market. Broker crossing systems in the OTC space are highly automated, let the buy
side slice large parent orders, and mix in streaming retail flow and the bank's own
proprietary positions, with prop desks acting as market makers using strategies comparable to
HFT market making on lit venues.

The asymmetry the paper draws from this is its sharpest analytical point:

> In internalization systems and dark venues, banks and brokers **know the identity of their
> counterparty** and can "cream skim" uninformed order flow, protecting themselves against
> adverse selection. HFT market makers on lit markets provide liquidity **without knowing
> their counterparties**, are not informed on the toxicity of their counterparts, and must
> manage, minimize and compensate losses from trading against informed flow.

So the venue type facing the *harder* adverse-selection problem is the one attracting the
regulatory attention, while the one that can select its counterparties largely escaped
discussion.

### Systemic risk

The risk: malfunctioning or rogue algorithms bombarding a venue with orders until its
infrastructure cannot cope, or driving a security's price far in an unintended direction.
A technical problem calls for a technical solution, and requires compatibility between venue
and sell-side infrastructure. Naked access is incompatible with this view of market
reliability.

Obligations the paper places along the value chain:

| Actor | Requirement |
|---|---|
| Firms running HFT | Log and record all algorithms' input and output parameters, for internal back-testing and supervisory investigation; apply sophisticated risk management tools and operational safeguards; demonstrate full control of their algorithms at any time |
| Market operators, clearing & settlement | Handle peak volumes; protect themselves against technical failures in members' algorithms; membership rules ensuring a human trader responsible for the algorithm is permanently available during trading hours to react when unusual behaviour is detected |
| Regulators and supervisors | Near-time reaction and rapid investigation capability in market stress; detailed information on the extent of HFT activity for a full systemic-risk picture; **people with specific skills** and regulatory tools to assess trading algorithms and their functionality |

That last one is easy to skim past and is arguably the most consequential: supervision of
algorithmic markets requires supervisors who can read algorithms.

### Market-making obligations

The proposal: require HFTs executing significant volume to quote continuously, like
registered market makers, and/or prevent them entering and deleting orders at high speed.
Kaufman (2010) asked the SEC to "impose some liquidity provision obligations on high
frequency traders"; the European Commission consulted on the same.

The paper's objection is empirical rather than ideological. Whether any rule can force market
makers to buy into overwhelming selling pressure is highly doubtful — they will rather take
the risk of fines. As one market operator put it (Katz 2011):

> "[…] obligations have never worked historically since market making firms are not willing
> to catch a falling knife by its point. The consequences of not fulfilling obligations are
> always small relative to putting the firm out of business."

The flash crash is the evidence: registered market makers *with* obligations stopped quoting
too, or invoked technical difficulties. The predicted effect of imposing obligations is
therefore not more liquidity in stress but fewer liquidity providers overall, since bearing
that risk is contrary to most HFT business models and would create significant regulatory
costs.

One constructive variant the paper does offer: venues should incorporate the existence of
"fleeting" liquidity into their assessment of quoting obligations — assess whether an
instrument needs designated liquidity providers, and how demanding their obligations should
be, **based on the available non-HFT liquidity** in that instrument. If non-HFT liquidity
alone cannot sustain liquid trading, that security should be supported by designated
providers. The relevant data should be available to all market operators.

### Safeguards: the proposed alternative

> Coordinated halt — calm down — coordinated restart.

Market stress is not new, and safeguards exist: volatility interruptions in Europe, circuit
breakers in the U.S. They need adapting on three axes:

**(1) Design for high-speed trading.** European volatility interruptions have two advantages:
they are security-specific, and they trigger auctions to calm down and restart whether prices
rise *or* fall extremely from one price to the next, assuring price continuity. (Both
directions matter — during the flash crash some stocks, e.g. Sotheby's, rose to the maximum
technically possible value.) But in most markets they trigger trade-by-trade, which primarily
catches erroneous "fat finger" submissions. In an HFT environment of many small, frequent
executions, a series of small price changes can each stay inside the volatility band while
cumulatively producing a significant move within milliseconds.

The fix: a **second, security-specific "circuit breaker band"** controlling price movement
over a specified time horizon (e.g. five minutes), triggering **call auctions** if the
potential price leaves that range. Call auctions rather than plain trading halts, because
auctions immediately provide price indications and aggregate liquidity over a reasonable
horizon so human traders can agree efficient prices. This differs from existing static
volatility interruptions (e.g. Deutsche Börse), which reference the last auction price rather
than a rolling time window.

**(2) Combine best practices** — this design merges the European volatility-interruption
advantages with the newer security-based U.S. circuit breakers.

**(3) Coordinate across venues.** Fragmentation and competition are a reality, so the
concept must trade off effective inter-market halts against venue autonomy. Proposal:
trade-by-trade interruptions (isolated fat-finger events) trigger **only on the individual
market**, while circuit breakers trigger a **coordinated halt in that security across all
European regulated markets, MTFs and OTC trading**. This prevents fast upward or downward
spirals as order flow overflows from venue to venue. The circuit breaker should be triggered
by the most liquid market for the security (per MiFID specifications), preventing unnecessary
interruptions elsewhere triggered by less active venues — with a fallback transferring the
reference-market role if the original has technical problems.

### Minimum order lifetimes and order-to-trade ratios

Proposed to prevent immediate liquidity withdrawal, system spamming, and confusing market
states. The paper lists five drawbacks:

1. Both impede participants' ability to react to exogenous events — minimum periods must
   expire before orders can be adjusted, or the ratio cap is reached.
2. Minimum lifetimes on important news force participants to leave orders in the market,
   **providing a free option for others to trade against**.
3. Minimum lifetimes create an incentive to develop high-speed strategies exploiting the fact
   that orders are trapped for an ex-ante known window — i.e. the rule manufactures a new
   predatory opportunity.
4. Order-to-trade ratios create severe problems for specific securities or strategies —
   e.g. quoting a foreign stock, where quotes depend on high-frequency FX moves as well as
   security-specific information.
5. Order-to-trade ratios incentivize gaming the denominator, e.g. deliberately triggering
   one-share trades.

Conclusion: both approaches would tend to *decrease* market efficiency. Impeding liquidity
providers' ability to react quickly to exogenous events degrades their ability to manage the
risk of standing orders, and so reduces the liquidity they are willing to provide.

## Conclusions

The paper's own summary positions:

1. **HFT is a technical means to implement established trading strategies** — not a strategy.
   Assessment and regulation should target the underlying strategies.
2. **HFT is a natural evolution of securities markets**, not a new phenomenon: from quote
   machines to DMA to SOR, a clear evolutionary process driven by competition, innovation and
   regulation. Like other technologies it earns legitimate returns on investment and
   compensates market, counterparty and operational risk.
3. **Many HFT problems are rooted in U.S. market structure.** The flash crash and flash
   orders relate to Reg NMS: the trade-through rule and a circuit-breaker regime neither
   security-specific nor aligned across venues are relevant causes. In Europe — flexible best
   execution without re-routing obligations, share-by-share volatility safeguards for two
   decades — no HFT-related market quality problems had been documented. Europe should be
   cautious about fixing a problem that exists in a different market structure.
4. **The majority of HFT strategies contribute to liquidity or price discovery.** Impairing
   them through inadequate regulation or excessive burdens may have counterproductive and
   unforeseen effects. Arguments equating HFT with market abuse miss the point — but abusive
   strategies must be effectively combated whoever runs them.
5. **Academic literature mostly shows positive effects**, with the caveats in `evidence.md`.
6. **HFT market makers face real adverse selection** on lit markets, unlike internalizers who
   know their counterparties.
7. **Assess functionally, not institutionally.** HFT spans top-tier investment banks to
   specialist boutiques; targeting specialized players alone undermines the level playing
   field and misses much of the activity. Note that separating banks' proprietary trading
   operations increases the share of entities escaping investment-firm registration under
   Article 2.1(d) exemptions.
8. **Market dependence on technology implies supervision requirements** — the value-chain
   table above.
9. **European interventions should preserve benefits while mitigating risks**, assuring that
   (i) a diversity of trading strategies prevails and artificial systemic risks are prevented,
   avoiding undue burdens on smaller players; (ii) **economic rationale rather than obligation**
   drives willingness to provide liquidity; (iii) co-location and proximity services are
   implemented on a level playing field; (iv) the focus is on **aligned volatility safeguards**
   across European venues that reflect HFT reality and let all investors react in times of
   market stress — rather than market-making obligations or minimum quote lifetimes.
10. **Transparency and open communication are owed by the industry.** Given public sensitivity
    to financial innovation post-crisis, entities applying HFT should proactively communicate
    their internal safeguards and risk management, and make the case that they are an
    evolution of securities markets that supplies liquidity and contributes to price discovery.

Point 10 is where the commissioned character of the study is most visible — it is advice to
the industry on how to argue its case. Useful context, not a reason to discount the
analytical content.

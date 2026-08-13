/** The settled reasoning behind Prism, written down so it survives.
 *
 * Plain English throughout, and short enough to reread in ten minutes. Glossary
 * terms auto-link, so anything unfamiliar is one click from a definition rather
 * than something to go and look up elsewhere.
 */
export type Section = { heading: string; paragraphs: string[] };

export type Principle = {
  slug: string;
  title: string;
  standfirst: string;
  sections: Section[];
};

export const PRINCIPLES: Principle[] = [
  {
    slug: "how-prism-thinks",
    title: "How Prism thinks",
    standfirst:
      "Six different ways of looking at the same company, deliberately kept apart.",
    sections: [
      {
        heading: "Six lenses, no combined score",
        paragraphs: [
          "Every company is scored through six lenses: trend, growth, quality, value, momentum and cycle. Each uses a different set of measures and each is blind to something the others can see. Trend knows nothing about the accounts. Quality says nothing about price. Value says nothing about whether the business is any good.",
          "There is deliberately no single combined score. Averaging the six would produce one confident-looking number that hides the only interesting thing about them — where they disagree. A company scoring 91 on value and 7 on growth is not a 49. It is a specific situation: very cheap, and shrinking. That needs investigating, not averaging.",
          "Colour in the interface does exactly one job: hue identifies which lens you are looking at. It never signals good or bad. A high score is not a recommendation and a low one is not a warning — they are one methodology's reading, and the methodology is written down so you can disagree with it.",
        ],
      },
      {
        heading: "Dispersion is the signal",
        paragraphs: [
          "Dispersion — the gap between a company's highest and lowest lens score — is the default sort order in Prism, and that is a considered choice. When all six lenses agree, the market has almost certainly noticed too, and there is nothing left to find. Disagreement marks an unresolved question.",
          "High dispersion is not a buy signal. It is a research signal: something about this company needs explaining, and the explanation is often that the cheap thing deserves to be cheap. Which two lenses are pulling apart matters as much as the size of the gap, so Prism names them rather than just printing a number.",
        ],
      },
      {
        heading: "Relative and absolute, both",
        paragraphs: [
          "Every lens produces two readings. The relative score ranks a company against others in its own sector. The absolute score measures it against fixed thresholds that do not move.",
          "Both are true at once, and the gap between them carries information neither has alone. A bank scoring 70 relative and 30 absolute is cheap compared with other banks and expensive compared with history — which tells you the sector, not the company, is the unusual thing. Showing only the relative score would hide that entirely, and in a sector that is uniformly expensive, ranking well against peers means very little.",
        ],
      },
      {
        heading: "A blank is an answer",
        paragraphs: [
          "When a lens can compute fewer than half the measures it needs, Prism shows no score rather than a score built on fragments. A reading derived from two measures out of five looks exactly as confident as one derived from all five, and that false confidence is worse than an empty cell.",
          "The same applies to lenses that do not fit. A cycle reading on a consumer staples business is noise dressed as signal, so it is marked not applicable rather than printed. EV/EBITDA on a bank is undefined rather than merely unusual, so it is excluded. An empty space in Prism means 'we do not know', which is different from — and more useful than — a zero.",
        ],
      },
    ],
  },
  {
    slug: "why-we-test-this-way",
    title: "Why we test the way we do",
    standfirst:
      "Four ways a backtest lies, and the worked example of an idea that looked good until it was controlled properly.",
    sections: [
      {
        heading: "Nothing may use tomorrow's information",
        paragraphs: [
          "Every figure in Prism carries the date it was published, not just the period it covers. A company's results for the quarter ending in March might not appear until May, so on the first of April those numbers did not exist. Any test that used them would be trading on information nobody had.",
          "This is the commonest way to build a backtest that looks brilliant and means nothing, and it is usually accidental. Most data providers overwrite figures when companies restate them, quietly destroying the record of what was originally believed. Prism stores restatements as new rows with their own publication dates, so the original figure survives alongside the correction.",
          "The same rule applies to dates themselves. When testing an earnings strategy, the report date must be the one that could have been forecast at the time, never the one that actually happened. A strategy that knows the real date in advance is fantasy.",
        ],
      },
      {
        heading: "Every result needs a control",
        paragraphs: [
          "Markets drift upward. Any strategy that is long shares for six days will make money on average, and that is not skill — it is being invested. So every result in Prism is measured against a control that does the same thing without the idea being tested.",
          "Choosing the control correctly is most of the work. For a strategy that picks stocks, the control must pick stocks at random from the same universe over the same weeks; a control that held the same companies would grant the stock-picking for free, which is the very thing being tested. For a strategy selected on some characteristic — high volatility, say — the control must be matched on that characteristic too, or it credits the strategy for something unrelated.",
        ],
      },
      {
        heading: "The universe is a list of survivors",
        paragraphs: [
          "Prism's universe is today's index membership. Companies that went bankrupt, were taken over, or dropped out are absent. Every backtest therefore chooses from a list of companies selected precisely because they survived, and every result is better than reality by an amount that cannot be measured without historical membership lists.",
          "This is not a small effect. It is worst for momentum strategies, which buy whatever has risen furthest — and the names that rose furthest before collapsing are exactly the ones missing from the list. When the strategy machine reports a backtest that turned £100k into millions, that number is arithmetically correct and economically meaningless. The excess over the control is the only figure worth reading.",
        ],
      },
      {
        heading: "Testing many things is itself a bias",
        paragraphs: [
          "Test twenty ideas against a threshold that a worthless idea passes one time in twenty, and on average one worthless idea passes. Report only that one and you have manufactured a discovery.",
          "So Prism counts. Every backtest reports how many variants were tried, and the strategy machine treats a family of related strategies as a family of attempts — three tweaks of one idea are four chances for one of them to look good. Given N attempts, the machine calculates what the best of N worthless strategies would have shown anyway, and shows that number next to the real one. With twelve strategies in a family, that bar sits around 1.7 standard errors, which is most of what a mediocre backtest looks like.",
        ],
      },
      {
        heading: "The worked example: pre-earnings drift",
        paragraphs: [
          "The idea was plausible. Buy a company a few days before it is expected to report, sell before the announcement, never hold through the result. Anticipation builds, the theory goes, and you capture the run-up without the risk of the number itself.",
          "The first result looked good: 31,654 simulated trades, +0.239% each after costs, and resampling the trades put the average safely above zero. On its own that reads like a finding.",
          "Then the control was added — buying the same companies on random days for the same six days. It returned +0.173%. So of the +0.239%, roughly seven tenths was simply the market going up over fifteen years. The earnings timing was worth about +0.066% per trade, which on a £10,000 position is around £7, against round-trip costs of 0.300%. The costs were more than four times the edge.",
          "Testing six parameter combinations made it worse: four of the six produced a negative excess, and the sign flipped between neighbouring settings. A real effect changes smoothly as you move a parameter. Noise changes sign.",
          "Segmenting found one genuine exception. In the most volatile fifth of companies the excess was +0.58% per trade, it survived a control matched on volatility and away from earnings, it held in all six sub-periods, and it stayed positive across all eight parameter settings without a single sign flip. That is what a real effect looks like — and it still sits on a survivor-biased universe, in exactly the names most likely to have gone bankrupt, and it stops being tradeable if spreads exceed about 57 basis points.",
          "The point of the story is not the exception. It is that the original idea was killed by a control that took twenty lines of code, and that without it the platform would have reported a false positive with a straight face.",
        ],
      },
    ],
  },
  {
    slug: "what-the-machine-is",
    title: "What the strategy machine is and is not",
    standfirst:
      "A dozen curated entrants with names attached — not a search for whatever fits.",
    sections: [
      {
        heading: "Curated entrants, not blind search",
        paragraphs: [
          "The strategy machine holds a small number of strategies, each written down before it was tested, each with an author and a reason to exist. It does not generate candidates, scan parameter space, or optimise anything. That restraint is the design.",
          "A machine that searches will always find something. Give it enough rules and enough history and it will return a beautiful equity curve fitted to the noise in one particular fifteen-year window. The only defence is to sharply limit how many things are tried, and to write down what each one believes before seeing whether it worked.",
        ],
      },
      {
        heading: "The Quantopian lesson",
        paragraphs: [
          "Quantopian ran the largest experiment anyone has run on this question. They collected thousands of user-built algorithms, each with a backtest, and then watched what those algorithms did on live data they had never seen.",
          "The finding was brutal: backtest performance had almost no relationship with what happened next. In their published analysis of 888 algorithms, in-sample Sharpe ratio carried essentially no predictive information about out-of-sample Sharpe. Some of the measures that did carry a little signal were the boring ones — how volatile the strategy was, how much it turned over — rather than how well it had performed.",
          "Prism's response is to treat a good backtest as the weakest kind of evidence. It is a hypothesis that has not yet been embarrassed. That is why nothing goes near real money on a backtest alone, why paper trading runs for years before it means anything, and why the drill-down screen puts backtest and paper results side by side: a paper record running far behind its backtest is the clearest warning sign there is.",
        ],
      },
      {
        heading: "Published anomalies decay",
        paragraphs: [
          "McLean and Pontiff studied what happens to market anomalies after the academic paper describing them is published. On average, returns fell by roughly half. Some of that is the anomaly being arbitraged away as people trade it; some is that the original result was partly luck to begin with and simply did not repeat.",
          "Every strategy card in Prism carries this note. When the Piotroski screen or the Magic Formula is encoded here, the honest expectation is materially less than the source reports — and less again, because the published versions ran on universes including tiny companies that Prism does not cover and that could not be traded at reasonable cost anyway.",
          "The house strategies carry a harsher note. An idea nobody else has ever tested has not survived anyone's scrutiny, which makes it weaker evidence than a published anomaly, not stronger.",
        ],
      },
      {
        heading: "What success would actually look like",
        paragraphs: [
          "Not a strategy that doubles the money. A strategy that, after three or four years of paper trading, shows a small persistent edge over buying at random from the same universe, with a drawdown that could be lived through, and that has not quietly stopped working.",
          "Most of the twelve will fail. Several will turn out to be the same strategy wearing different names — which the novelty gate exists to catch by correlating their return streams. Some will look good for two years and then revert. That is the expected outcome, and the machine is built to make it visible rather than to avoid it.",
          "The realistic value of the whole apparatus is not the strategies. It is having a place where an idea must be written down before it is tested, where the results cannot be quietly edited afterwards, and where the difference between a real edge and a lucky run is calculated rather than argued about.",
        ],
      },
    ],
  },
  {
    slug: "rules-we-hold-ourselves-to",
    title: "Rules we hold ourselves to",
    standfirst: "The commitments that make the rest of it mean anything.",
    sections: [
      {
        heading: "Write it down before testing it",
        paragraphs: [
          "A strategy is registered — with its hypothesis, its author, its exact rules and its predicted performance — before a single backtest runs. The prediction is then stamped into the record and cannot be revised.",
          "The reason is that a prediction written after seeing the result is not a prediction. Without pre-registration it is almost impossible to avoid quietly adjusting what you claim to have expected until it matches what happened, and then remembering it that way.",
        ],
      },
      {
        heading: "A tweak is a new strategy",
        paragraphs: [
          "Changing a threshold does not edit a strategy. It creates a new one, recorded as a child of the original. The parent keeps its own history and its own results.",
          "This is what stops the machine becoming an optimiser. If adjusting a number in place were allowed, twenty quiet adjustments would leave one strategy with a wonderful record and no trace of the nineteen attempts behind it. As lineage, all twenty are visible, and the deflation calculation counts all of them as attempts — so the survivor has to clear a much higher bar.",
        ],
      },
      {
        heading: "Nothing is edited after launch",
        paragraphs: [
          "Strategy definitions, trades and results are stored as an append-only ledger. Nothing is updated or deleted. When something is wrong, a later entry says so and supersedes it; the original stays visible with its correction attached.",
          "The same discipline runs through the rest of the platform. Fundamentals are stored point-in-time with restatements as new rows. Decisions record their thesis, pre-mortem and falsifier before the outcome is known. A record that can be tidied up afterwards will be, and then it can no longer teach anything.",
        ],
      },
      {
        heading: "Promotion is a human act",
        paragraphs: [
          "The gate can say a strategy is eligible: enough completed trades, positive expectancy after costs, and a genuine margin over the control. Passing makes it eligible and nothing more. Only an explicit click promotes it to paper trading, and the reason for that click is recorded permanently.",
          "Nothing automatically progresses toward real money. The machine's job is to assemble the evidence and to state plainly what the evidence cannot support.",
        ],
      },
      {
        heading: "Say when the sample is too small",
        paragraphs: [
          "Every row on the leaderboard carries a plain-English verdict on its own sample size, calculated from how consistent its returns have been. Most rows will read something like: 'four months, eleven trades — statistically meaningless; at this consistency it would need roughly three years before the record could be told apart from luck.'",
          "That sentence will sit on almost every strategy for a long time, and it should. A leaderboard without it invites reading the top row as the best strategy, when for the first few years the top row is mostly the luckiest one. Ranking is always on full-history expectancy and never on recent performance, for the same reason.",
        ],
      },
      {
        heading: "Explain, never recommend",
        paragraphs: [
          "Nothing in Prism tells you what to buy or sell — not the lens scores, not the leaderboard, not the assistant. The assistant will explain a number, argue the other side of a thesis, and name what a lens is blind to. It will not give a verdict, and it is not permitted to rank candidates by attractiveness.",
          "Prism exists to sharpen judgement, not to replace it. A tool that issued verdicts would quietly become the decision-maker, and the decision log would stop recording anyone's reasoning — which would remove the only thing that makes the record worth keeping.",
        ],
      },
    ],
  },
];

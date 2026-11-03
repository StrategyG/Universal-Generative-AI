# Domain Intelligence Frameworks

**Status:** analytical framework specification, not a claim that domain agents are implemented.

## 1. Common analytical grammar

Every domain workflow uses the same core structure:

1. Question and decision context.
2. Scope, jurisdiction, geography, and valid time period.
3. Entities, actors, institutions, and stakeholders.
4. Events, actions, decisions, resources, and constraints.
5. Source evidence and source reliability.
6. Claims, counterclaims, uncertainty, and contradictions.
7. Causal mechanisms and alternative explanations.
8. Scenarios, indicators, risks, and opportunities.
9. Decision options, trade-offs, reversibility, and consequences.
10. Monitoring conditions and update triggers.

The framework separates:
- observation: what a source directly reports;
- verified fact: a claim supported by eligible evidence under the applicable policy;
- inference: an interpretation derived from evidence;
- assumption: a proposition used for analysis but not established;
- forecast: a conditional statement about possible futures;
- recommendation: a decision proposal tied to objectives and constraints.

## 2. Political intelligence

### Analytical dimensions
- formal institutions, legal powers, jurisdiction, and constitutional constraints;
- political actors, parties, agencies, coalitions, and interest groups;
- formal and informal power relationships;
- stated positions versus observable actions;
- incentives, resources, dependencies, and veto points;
- policy cycle: agenda, formulation, adoption, implementation, evaluation;
- domestic, regional, and international context;
- public accountability, institutional checks, and affected populations;
- election, leadership, and policy timelines.

### Required output
- actor and institution map;
- policy/decision timeline;
- interest and incentive matrix;
- power/dependency network;
- competing explanations;
- institutional constraints;
- scenario tree and observable indicators;
- source-by-source evidence ledger.

Do not infer hidden intent as fact. Attribute statements to the source, distinguish official position from analyst inference, and include counter-evidence. Treat political affiliation and ideological characterizations as claims requiring explicit, relevant evidence rather than labels inferred from identity or association.

## 3. Business and market intelligence

### Analytical dimensions
- customer segments, jobs-to-be-done, demand, and willingness to pay;
- market size, growth, cycles, substitutes, and entry barriers;
- competitive landscape and differentiation;
- value chain, suppliers, distribution, and concentration risk;
- pricing, revenue model, gross margin, contribution margin, and unit economics;
- cash conversion, working capital, leverage, liquidity, and capital intensity;
- regulation, technology, operational, legal, and reputational risk;
- management execution, governance, incentives, and organizational capacity.

### Required output
- business model canvas or equivalent value-chain model;
- competitor and substitute matrix;
- unit economics with source-linked inputs and formulas;
- scenario model with assumptions visible;
- risk register with likelihood/impact basis;
- sensitivity analysis and break-even thresholds;
- decision options and implementation dependencies.

Do not transform unverified market estimates into precise facts. Every number must include unit, currency, period, geography, method, and source. Forecasts must disclose assumptions and ranges.

## 4. Holistic and systems thinking

Apply a system boundary before analyzing parts. Model:
- actors and components;
- inputs, outputs, stocks, and flows;
- reinforcing and balancing feedback loops;
- delays and non-linear effects;
- dependencies and bottlenecks;
- unintended consequences;
- leverage points and constraints;
- local optimization versus system-wide outcomes.

Use causal loop diagrams and stock/flow models where they materially improve understanding. A correlation does not establish causation. Every causal hypothesis should identify mechanism, time lag, alternative causes, and evidence that could falsify it.

## 5. Strategy and decision analysis

Use a staged decision model:

### A. Define the decision
Who decides, by when, with what objective, and under which constraints?

### B. Generate alternatives
Include status quo, incremental option, transformational option, and a no-action baseline where appropriate.

### C. Evaluate
Assess expected value, downside, reversibility, execution capability, dependencies, opportunity cost, and stakeholder effects.

### D. Stress test
Use base/upside/downside scenarios, sensitivity analysis, pre-mortem, adversarial review, and explicit disconfirming indicators.

### E. Decide and monitor
Specify decision owner, trigger conditions, guardrails, milestones, and conditions that invalidate the recommendation.

Decision quality is measured by process integrity and evidence at decision time, not only by outcome hindsight.

## 6. Evidence and temporal model

For every entity, event, relationship, and claim, retain:
- evidence IDs and source hashes;
- source publication date;
- event date;
- capture date;
- valid_from and valid_to where applicable;
- jurisdiction and geographic scope;
- claim polarity and modality;
- confidence rationale;
- reviewer and publication state.

Do not collapse event time, publication time, capture time, and observation time into a single timestamp.

## 7. Cross-domain synthesis

A political decision can affect regulation, capital allocation, supply chains, market access, and business strategy. Cross-domain synthesis must:
1. retrieve each domain independently under its authorization policy;
2. preserve each source's evidence tier and temporal scope;
3. identify the causal path linking domains;
4. mark assumptions and unobserved links;
5. test alternative mechanisms;
6. produce a decision map with leading indicators and update triggers.

Never increase trust because two AI-generated summaries agree. Independent source provenance matters more than repeated model paraphrases.

## 8. Standard response structure

For complex analysis, produce:
1. Executive conclusion.
2. Decision question and scope.
3. Established facts with citations.
4. Key actors/entities and relationships.
5. Mechanisms and causal hypotheses.
6. Contradictions and counter-evidence.
7. Scenarios and probabilities only when defensible.
8. Risk and opportunity assessment.
9. Recommended actions with assumptions.
10. Monitoring indicators and what would change the conclusion.
11. Evidence gaps and confidence limitations.

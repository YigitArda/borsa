# Borsa Research Engine - System Architecture Report

## 1. What this system is

This repository is a stock-research and strategy-automation platform.
It does not try to be a live trading terminal. Instead, it:

- ingests market and fundamental data
- builds weekly features
- trains ML strategies
- runs walk-forward backtests
- promotes only strategies that pass multiple gates
- generates weekly stock picks
- paper-tests the picks
- monitors data quality and risk
- can stop itself through a kill switch

In short: this is an automated research loop for equities, not a simple dashboard.

## 2. High-level shape

The system has 5 main layers:

1. Infrastructure layer
2. Backend API layer
3. Research / ML service layer
4. Background task layer
5. Frontend presentation layer

The important idea is that the backend is not just serving pages. It is running a weekly research machine with persistence, scheduled jobs, scoring gates, and safety checks.

## 3. Runtime topology

The `docker-compose.yml` file shows the intended runtime:

- `postgres`: main persistent database
- `redis`: queue + cache
- `backend`: FastAPI app
- `worker`: Celery worker for async jobs
- `beat`: Celery scheduler for recurring jobs
- `frontend`: Next.js UI

That means the system is split into:

- synchronous request/response paths for UI and API calls
- asynchronous long-running paths for ingest, training, evaluation, and periodic automation

## 4. Core backend entrypoint

The backend starts in `backend/app/main.py`.

This file is the composition root. It:

- creates the FastAPI app
- configures logging
- wires CORS
- wires rate limiting
- wires API key protection for write routes
- wires Redis-backed response caching for some read routes
- registers all routers
- adds the WebSocket route
- exposes health and metrics endpoints

This file also reveals the system's operational priorities:

- protect expensive endpoints with rate limits
- protect write actions with an optional API key
- cache expensive read endpoints
- expose operational status through `/health` and `/metrics`

## 5. Backend API surface

The backend API is organized by domain, not by technical layer.

Main routers include:

- `/stocks`
- `/backtest`
- `/strategies`
- `/weekly-picks`
- `/pipeline`
- `/research`
- `/data-quality`
- `/verification`
- `/auth`
- `/notifications`
- `/jobs`
- `/selected-stocks`
- `/export`
- `/scientific`

This is a good sign architecturally: each domain has a clear responsibility.

### 5.1 Stocks

The stocks module is the market universe layer.
It exposes stock lists and individual stock detail views.
This is the base entity other modules depend on.

### 5.2 Backtest

The backtest module runs strategy validation.
It supports:

- queued research-loop execution
- direct walk-forward backtests
- combinatorial purged CV
- portfolio-level simulation

This is the validation engine that decides whether a strategy is worth keeping.

### 5.3 Strategies

The strategies module manages strategy lifecycle:

- list strategies
- start research
- inspect a strategy
- run promotion checks
- promote or archive
- inspect model versions

This is the governance layer around strategy objects.

### 5.4 Weekly picks

The weekly-picks module turns a promoted strategy into ranked weekly predictions and paper trades.
It also computes summary statistics like:

- hit rate at +2%
- average predicted probability
- average realized return
- calibration error

### 5.5 Research

The research module is the introspection and diagnostics surface.
It covers:

- feature importance
- walk-forward history
- strategy comparison
- risk warnings
- promotions
- rolling Sharpe
- trade overlap
- regime analysis
- calibration
- ablation
- arxiv paper ingestion and extraction
- kill switch status/history

This module is the analyst's control panel.

### 5.6 Data quality

The data-quality module scores the underlying data across price, feature, financial, news, and macro dimensions.
This is important because the system is only as good as the data feeding the model.

### 5.7 Notifications, jobs, auth, export

These modules are supporting infrastructure:

- auth: protects actions and manages login/token flows
- notifications: stores preferences and delivery settings
- jobs: exposes background job state
- export: extracts artifacts for external use
- verification: exposes system verification status

### 5.8 Scientific

The scientific module is a research registry / experimentation layer.
It suggests the project is moving from ad-hoc strategy testing toward a more formal hypothesis-driven process.

## 6. Background execution model

The backend uses Celery heavily.

`backend/app/tasks/celery_app.py` defines:

- the Celery app
- Redis broker/backend
- scheduled recurring jobs
- a test-safe enqueue helper

`backend/app/tasks/pipeline_tasks.py` is the real automation engine.

It contains tasks for:

- ingesting prices
- ingesting macro data
- ingesting news
- ingesting fundamentals
- ingesting social sentiment
- feature computation
- weekly prediction generation
- paper-trade opening and evaluation
- calibration
- alpha decay checks
- regime detection
- portfolio simulation
- ArXiv scanning and extraction
- data quality scoring
- full pipeline orchestration

The key architectural pattern is:

- API endpoints queue tasks
- Celery workers execute them
- the database stores results and status
- the frontend reads those results back

That keeps long-running work out of the request thread.

## 7. The main research pipeline

The most important flow in the system is the full pipeline.
It is defined in `run_full_pipeline` inside `backend/app/tasks/pipeline_tasks.py`.

The order is roughly:

1. snapshot the stock universe
2. ingest prices
3. ingest FRED data
4. ingest DBnomics data
5. ingest macro data
6. ingest news
7. ingest social sentiment
8. ingest financial data
9. ingest fundamental statements
10. ingest PEAD data
11. ingest short interest
12. compute features
13. compute data-quality scores
14. update PEAD confirmations
15. detect regimes
16. generate weekly predictions
17. run portfolio simulation
18. evaluate paper trades
19. run calibration
20. check alpha decay

This is the real system backbone.

The important design point is that every stage depends on the previous stages having written durable data into Postgres.

## 8. Research loop logic

The self-improving loop lives in `backend/app/services/research_loop.py`.

This is the engine that mutates strategies, evaluates them, and decides whether they can move forward.

### 8.1 How it works

The loop does this:

- start from a base strategy config
- mutate the config
- train a model
- run walk-forward validation
- evaluate metrics against an acceptance gate
- optionally promote a candidate

It also tracks:

- mutation memory
- RL-style strategy selection
- Bayesian optimization
- daily research budget
- holdout cutoff enforcement

### 8.2 Why this matters

This is not random experimentation.
It is controlled search with guardrails:

- only data before the holdout cutoff is used for training
- research is budget-limited per day
- candidates must pass statistical thresholds
- feature complexity has a penalty
- performance is measured with multiple metrics, not one score

## 9. Model training and validation

The training layer lives in `backend/app/services/model_training.py`.

It handles:

- dataset assembly from feature and label tables
- walk-forward validation
- combinatorial purged CV
- model fitting
- per-stock and per-sector training
- final holdout evaluation

### 9.1 Data shape

The trainer joins:

- `FeatureWeekly`
- `LabelWeekly`
- `Stock`

It converts long-format weekly features into a wide table, then trains classifiers/regressors.

### 9.2 Supported models

The trainer supports multiple model families:

- LightGBM
- Logistic Regression
- Random Forest
- Gradient Boosting
- XGBoost
- CatBoost
- Neural Network

If a library is missing, it falls back to a simpler model.

### 9.3 Validation style

Validation is intentionally time-aware:

- walk-forward expanding windows
- embargo gap between train and test
- combinatorial purged CV for robustness
- holdout months that are never used by the proposer

This is good financial-ML practice because it reduces lookahead leakage.

## 10. Backtesting and portfolio simulation

The backtester lives in `backend/app/services/backtester.py`.

It simulates:

- weekly signals
- entry at Monday open
- exit after the configured hold period
- transaction costs
- slippage
- stop loss / take profit
- Kelly sizing
- regime-based skipping or scaling

This means the model is not judged only by prediction accuracy.
It is judged by trading outcomes.

### 10.1 Portfolio simulation

`backend/app/services/portfolio_simulation.py` is used from the pipeline and the backtest API.
It converts trade-level output into a portfolio-level equity curve.

That gives a higher-level answer to:

- how much capital would the strategy have made or lost?
- what was the drawdown?
- how volatile was the portfolio?

## 11. Prediction and paper trading loop

This is the bridge from research to pseudo-production.

### 11.1 Weekly predictions

`backend/app/services/weekly_prediction.py`:

- selects a promoted strategy
- trains the main model
- optionally trains a risk model
- optionally trains a return model
- adjusts confidence using calibration
- writes ranked weekly predictions to the DB

### 11.2 Paper trades

`backend/app/services/paper_trading.py`:

- opens paper trades from the predictions
- later evaluates them when price data is available
- records realized return, max rise, drawdown, and hit/miss flags
- feeds outcomes into the strategy bandit and meta-learner

This is important: the system keeps a forward-test audit trail, not just backtest results.

## 12. Promotion gate

Promotion is not automatic.

`backend/app/services/promotion.py` combines several checks:

- research metrics
- paper-trade summary
- regime performance
- meta-learner prediction
- holdout validation
- concentration checks
- statistical tests from the research loop

Only if the strategy passes does it get promoted.

That means the system has a layered acceptance process:

- backtest says "promising"
- paper trading says "still good"
- holdout says "real out-of-sample is acceptable"
- regime analysis says "not only works in one regime"
- meta learner gives extra signal

## 13. Kill switch

`backend/app/services/kill_switch.py` is a safety subsystem.

It can block the system when:

- data quality falls too low
- VIX spikes too high
- prediction counts look wrong
- feature drift is too large
- paper trading drawdown gets too large
- model drawdown breaches threshold
- confidence distribution shifts abnormally

This is the system's emergency brake.

When critical triggers happen, it can also close open paper positions and broadcast notifications.

## 14. Data ingestion layer

`backend/app/services/data_ingestion.py` is the market data backbone.

It handles:

- stock universe snapshots
- ticker aliases
- corporate actions
- daily prices
- weekly resampling
- liquidity filtering
- incremental updates

Important design note:

- daily OHLCV is treated as the raw source
- weekly bars are derived and stored separately
- the system prefers incremental ingest to avoid re-pulling everything

The code also explicitly notes that some fundamentals from yfinance are not point-in-time safe.
That is a real research concern and the repo acknowledges it.

## 15. Data quality layer

`backend/app/services/data_quality_scoring.py` scores each stock-week across:

- price data
- features
- financial freshness
- news coverage
- macro coverage

This produces a numeric score and detailed penalties.

Why this matters:

- the model should not trust stale or incomplete inputs
- poor data quality can trigger the kill switch
- the dashboard can expose which dimension is weak

## 16. Calendar, jobs, and live status

The system exposes operational status in multiple ways:

- `/health` checks Postgres and Redis
- `/metrics` exposes Prometheus-style metrics
- `/jobs` and related endpoints expose async job status
- WebSocket `/ws` can broadcast job and kill-switch events

That suggests the app is meant to be monitored while running, not only used as a static report site.

## 17. Frontend architecture

The frontend is a Next.js app in `frontend/`.

### 17.1 Layout

`frontend/app/layout.tsx` defines the global shell:

- top ticker bar
- main title bar
- navigation
- left sidebar
- footer/status bar

The UI intentionally uses a retro terminal / desktop-window style.
It is not a modern SaaS UI, but a research console.

### 17.2 Home page

`frontend/app/page.tsx` is the dashboard entry.
It pulls:

- stocks
- promoted strategies
- paper trades
- kill-switch state

Then it renders:

- summary cards
- paper-trade table
- stock universe table
- step-by-step usage guidance

So the home page is a live system summary, not a marketing landing page.

### 17.3 API access pattern

The frontend talks to the backend in two ways:

- direct backend API calls through `frontend/lib/api.ts`
- server-side loads through `frontend/lib/server-api.ts`

There is also `frontend/lib/server-backend.ts` for server-side backend requests.

That gives the frontend both:

- browser-side fetches
- server-side data loading

## 18. Persistence model

The database layer is Postgres-first.

`backend/app/database.py` defines:

- async SQLAlchemy engine
- async sessionmaker
- declarative base

`backend/app/models/__init__.py` imports all models so metadata registration happens early.

The model set is broad:

- stocks
- prices
- features
- labels
- strategies
- model versions
- backtests
- portfolio simulations
- predictions
- paper trades
- calibration
- ablation
- jobs
- financial metrics
- news and sentiment
- macro indicators
- data quality scores
- regimes
- kill-switch events/config
- selected stocks
- users and API keys
- notifications
- mutation memory
- hyperparameter trials
- meta-learner training data
- strategy bandit arms
- RL Q-table
- research budgets
- PEAD signals
- short interest
- ArXiv papers and insights

This is not a small app schema. It is a research platform with a lot of historical state.

## 19. What the tests suggest

The test suite covers many important boundaries:

- API auth
- API integration
- pipeline behavior
- backtester logic
- CPCV
- data ingestion
- paper trading
- price adjustments
- promotion gate
- research routes
- scientific modules
- self-improving research
- smoke tests

That suggests the authors are already trying to lock down the most dangerous failure modes:

- leakage
- broken pipeline orchestration
- promotion gate regressions
- wrong trade evaluation

## 20. Strengths

The architecture has several strong points:

- clear separation between API, services, tasks, and models
- durable storage for all important outputs
- real time-series validation rather than random train/test splits
- multi-stage promotion gate
- kill switch for unsafe states
- data-quality scoring
- WebSocket and metrics support
- caching and rate limiting for expensive reads
- asynchronous execution for long tasks

## 21. Weak spots / complexity risks

The main risk is complexity.

The system has many interacting subsystems:

- data ingestion
- feature engineering
- model training
- backtesting
- paper trading
- promotion
- kill switch
- bandit/meta-learner logic

That means failures can be subtle.

Likely risk areas:

- leakage between training and validation if a path bypasses the intended holdout logic
- stale or non-point-in-time data entering the feature set
- duplicate business logic between synchronous API routes and Celery tasks
- many synchronous DB sessions opened inside request handlers
- a lot of domain logic spread across many services

## 22. Mental model of the system

If you want a simple way to think about it:

1. The database is the memory.
2. Celery is the long-running worker brain.
3. FastAPI is the control plane.
4. Next.js is the operator console.
5. The research loop is the core engine.
6. The promotion gate is the final filter.
7. The kill switch is the safety brake.

## 23. One-line summary

Borsa Research Engine is a Postgres-backed, Celery-driven, FastAPI + Next.js research platform that ingests market data, trains and validates stock strategies, paper-tests them, promotes only the ones that survive multiple gates, and protects itself with data-quality and kill-switch checks.


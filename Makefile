# Unified Corpus CLI Makefile (path-agnostic via CORPUS_HOME)
CORPUS_HOME ?= $(CURDIR)
PYTHON      ?= $(CORPUS_HOME)/.venv/bin/python3
CLI         := $(CORPUS_HOME)/scripts/corpus_cli.py
VOL         ?= 1

.PHONY: help status sync verify build build-vol1 build-vol2 build-vol3 build-parables queue test

help:
	@echo "Corpus Unified CLI targets (CORPUS_HOME=$(CORPUS_HOME)):"
	@echo "  make status              Read-only DB counts, open flags, digest watermark & handoff queue"
	@echo "  make sync                Run delta closed-loop sync (scripts/sync_and_ingest.py)"
	@echo "  make verify              Run SQLite integrity/FK checks, test_pilot_harness & all PDF SHA-256s"
	@echo "  make build VOL=1|2|3|parables|all Rebuild selected volume PDF + verify .sha256"
	@echo "  make build-parables      Rebuild Failures, Parables & Crash Reports companion PDF + .sha256"
	@echo "  make queue               List structured PR-style handoff_queue entries"
	@echo "  make test                Run python3 -m unittest scripts/test_pilot_harness.py -v"

status:
	CORPUS_HOME="$(CORPUS_HOME)" "$(PYTHON)" "$(CLI)" status

sync:
	CORPUS_HOME="$(CORPUS_HOME)" "$(PYTHON)" "$(CLI)" sync

verify:
	CORPUS_HOME="$(CORPUS_HOME)" "$(PYTHON)" "$(CLI)" verify

build:
	CORPUS_HOME="$(CORPUS_HOME)" "$(PYTHON)" "$(CLI)" build --vol "$(VOL)"

build-vol1:
	CORPUS_HOME="$(CORPUS_HOME)" "$(PYTHON)" "$(CLI)" build --vol 1

build-vol2:
	CORPUS_HOME="$(CORPUS_HOME)" "$(PYTHON)" "$(CLI)" build --vol 2

build-vol3:
	CORPUS_HOME="$(CORPUS_HOME)" "$(PYTHON)" "$(CLI)" build --vol 3

build-parables:
	CORPUS_HOME="$(CORPUS_HOME)" "$(PYTHON)" "$(CLI)" build --vol parables

queue:
	CORPUS_HOME="$(CORPUS_HOME)" "$(PYTHON)" "$(CLI)" queue list

test:
	CORPUS_HOME="$(CORPUS_HOME)" python3 -m unittest scripts/test_pilot_harness.py -v

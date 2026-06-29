# Mannschaft UC4 demo — one-command launcher.
# Run from anywhere:  make -f docs/demo/Makefile demo
# (or `cd docs/demo && make demo`). Uses the repo venv directly — no activation.

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
MS   := $(ROOT)/.venv/bin/ms
SPEC ?= docs/demo/uc4-todo-api.spec.md

.DEFAULT_GOAL := help
.PHONY: help preflight warm rehearse demo launch reset

help:        ## show targets
	@grep -hE '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | sort

preflight:   ## check the dashboard stack + that the local model endpoint is reachable
	cd $(ROOT) && $(MS) doctor
	cd $(ROOT) && $(MS) models list

warm:        ## pay the model load cost once (so the live decompose is snappy)
	cd $(ROOT) && $(MS) decompose $(SPEC) >/dev/null && echo "model warm"

rehearse:    ## the safe, fast beats: lint (1.0 gate) + live decompose on the local model
	cd $(ROOT) && $(MS) lint $(SPEC)
	cd $(ROOT) && $(MS) decompose $(SPEC)

demo: preflight warm   ## boot the live dashboard; run lint/decompose/launch in a second terminal
	@echo ">>> Dashboard booting. In a second terminal, run the beats from DEMO.md:"
	@echo "    $(MS) lint $(SPEC)"
	@echo "    $(MS) decompose $(SPEC)"
	@echo "    $(MS) launch $(SPEC)        # or load the captured run: $(MS) observe <run_id>"
	cd $(ROOT) && $(MS) up

launch:      ## launch the curated spec (isolated run/<id> branch, auto-merge)
	cd $(ROOT) && $(MS) launch $(SPEC)

reset:       ## stop a stuck run (pass RUN=<run_id>)
	cd $(ROOT) && $(MS) stop $(RUN)

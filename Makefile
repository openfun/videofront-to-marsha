default: help

bootstrap: ## Initialize Docker image and environment
	${MAKE} build;
.PHONY: bootstrap

build: ## Build the Docker image
	docker build -t vf2m:latest .
.PHONY: build

help:
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'
.PHONY: help

# Thin wrappers around `uv run aml <cmd>`. On Windows without make, use: .\tasks.ps1 <target>
# docker compose profile: oracle | graph | llm | full
PROFILE ?= oracle
AML := uv run aml

.PHONY: up down status init retention data load screen er monitor graph bench score rag ui test lint all

up:      ; docker compose $(if $(GPU),-f docker-compose.yml -f docker-compose.gpu.yml) --profile $(PROFILE) up -d
down:    ; docker compose --profile full down
status:  ; $(AML) status
init:    ; $(AML) init-db
retention: ; $(AML) retention
data:    ; $(AML) data
load:    ; $(AML) load
screen:  ; $(AML) screen
er:      ; $(AML) er
monitor: ; $(AML) monitor
graph:   ; $(AML) graph
bench:   ; $(AML) bench
score:   ; $(AML) score
rag:     ; $(AML) rag build
ui:      ; $(AML) ui
test:    ; uv run pytest
lint:    ; uv run ruff check . && uv run ruff format --check .
all: data load screen er monitor graph score rag

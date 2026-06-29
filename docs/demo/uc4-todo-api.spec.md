---
id: uc4-todo-api
title: In-memory Todo REST API
goal: A small FastAPI service that stores todo items in memory and exposes create, list, and delete endpoints, with a pytest suite that proves each endpoint.
acceptance_criteria:
- "`POST /todos` accepts a JSON body `{title}` and returns status 201 with the created item including a generated integer `id`"
- "`GET /todos` returns status 200 with a JSON array of all created todo items"
- "`DELETE /todos/{id}` returns status 204 when the id exists and status 404 when it does not"
- "`pytest` exits 0 with tests covering create, list, and the delete 404 path"
constraints:
- Python 3.11
- FastAPI with an in-memory list store
- Standard library plus FastAPI only
non_goals:
- persistence to a database
- authentication or authorization
- pagination or filtering
created_at: '2026-06-29T00:00:00Z'
updated_at: '2026-06-29T00:00:00Z'
linter_score: null
status: draft
topology: sequential
sync_mode: per_agent
executor: pi
sync_profile: null
session_id: null
corpus_classifications: []
decomposed_tasks: null
---

# In-memory Todo REST API

## Goal

A small FastAPI service that stores todo items in memory and exposes create, list, and delete endpoints, with a pytest suite that proves each endpoint.

## Acceptance Criteria

- `POST /todos` accepts a JSON body `{title}` and returns status 201 with the created item including a generated integer `id`
- `GET /todos` returns status 200 with a JSON array of all created todo items
- `DELETE /todos/{id}` returns status 204 when the id exists and status 404 when it does not
- `pytest` exits 0 with tests covering create, list, and the delete 404 path

## Constraints

- Python 3.11
- FastAPI with an in-memory list store
- Standard library plus FastAPI only

## Non-Goals

- persistence to a database
- authentication or authorization
- pagination or filtering

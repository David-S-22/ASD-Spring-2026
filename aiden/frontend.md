# Anomalies Frontend

## Overview

The frontend is a lightweight nginx container that serves the anomalies user
interface. The page is built with HTML, CSS, JavaScript, and HTMX, without a
separate frontend framework or build step. It displays detected anomalies,
related transaction details, review status, and feedback controls.

## User interface

The page provides controls to create a dummy anomaly and submit a dummy
transaction for review. Anomaly rows are loaded from the backend and refreshed
periodically using HTMX. Unreviewed anomalies provide a review action that lets
the user confirm or dismiss the finding. Status messages and alert fragments
are displayed in the page as transactions are checked and reviewed.

## Backend communication

Requests are sent through the `/anomalies-backend/` path:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/anomalies-backend/anomalies` | Loads and refreshes anomaly rows. |
| `POST` | `/anomalies-backend/dummy-anomaly` | Creates a development test anomaly. |
| `POST` | `/anomalies-backend/check-transaction` | Queues a transaction for anomaly review. |
| `GET` | `/anomalies-backend/anomaly-alert?key=<id>` | Retrieves the result of a queued review. |
| `POST` | `/anomalies-backend/anomalies/<id>/confirm` | Confirms an anomaly. |
| `POST` | `/anomalies-backend/anomalies/<id>/dismiss` | Dismisses an anomaly. |

HTMX handles the anomaly list requests and HTML fragment updates. JavaScript
uses `fetch` for transaction checking, long-polling review results, and review
actions.

## Nginx and container configuration

Nginx serves files from `/app/public` and listens on the configured `PORT`,
which is `3004` in Docker Compose. Requests under `/anomalies-backend/` are
reverse-proxied to the URL provided by `ANOMALIES_BACKEND_URL`. The Dockerfile
uses `nginx:alpine`, copies the static page into the image, and installs the
templated nginx configuration.

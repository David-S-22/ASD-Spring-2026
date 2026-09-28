# Anomalies Frontend

## Overview

The frontend is a lightweight nginx container that serves the anomalies user
interface. The page is built with HTML, CSS, JavaScript, and HTMX, without a
separate frontend framework or build step. It displays detected anomalies,
related transaction details, review status, and feedback controls.

## User interface

The page loads anomaly rows from the backend and refreshes them periodically
using HTMX. Unreviewed anomalies provide a review action that lets the user
confirm or dismiss the finding. The review dialog shows the complete
transaction details (ID, date, merchant, amount, description, and category ID)
in two columns, followed by a full-width suspected-reason row before
collecting the user's decision. Labels are styled as small uppercase
subheadings, with values emphasized in separate bordered cards. The dialog
animates when opening and closing, and pressing Escape cancels the review.

## Backend communication

Requests are sent through the `/anomalies-backend/` path:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/anomalies-backend/anomalies` | Loads and refreshes anomaly rows. |
| `POST` | `/anomalies-backend/anomalies/<id>/confirm` | Confirms an anomaly. |
| `POST` | `/anomalies-backend/anomalies/<id>/dismiss` | Dismisses an anomaly. |

HTMX handles the anomaly list requests and HTML fragment updates. JavaScript
uses `fetch` for review actions.

## Nginx and container configuration

Nginx serves files from `/app/public` and listens on the configured `PORT`,
which is `3004` in Docker Compose. Requests under `/anomalies-backend/` are
reverse-proxied to the URL provided by `ANOMALIES_BACKEND_URL`. The Dockerfile
uses `nginx:alpine`, copies the static page into the image, and installs the
templated nginx configuration.

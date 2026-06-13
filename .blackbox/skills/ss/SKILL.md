# Technical Skills — Advanced Proficiency

A comprehensive breakdown of my advanced technical expertise in full-stack development, systems automation, and software architecture.

---

## 🖥️ Front-End Development (Advanced)

Expertise in building scalable, type-safe, and high-performance user interfaces.

* **Languages & Core:** TypeScript (Advanced types, generics, utility types), JavaScript (ES6+, Event Loop, Closures).
* **Frameworks & Libraries:** React.js (Hooks, Custom Hooks, Context API, Concurrent Rendering), Next.js.
* **State Management:** Redux Toolkit, Zustand, Context API (Optimized for minimal re-renders).
* **Styling & UI Systems:** Tailwind CSS (Custom configurations, design tokens), CSS3, SASS/SCSS, Responsive Web Design.
* **Performance & Tooling:** Vite, Webpack optimization, bundle size analysis, code-splitting, and lazy loading.

---

## ⚙️ Back-End Development (Advanced)

Deep experience designing robust, distributed, and highly concurrent server-side systems.

* **Core Language:** Python (Metaprogramming, Decorators, Generators, Context Managers).
* **Concurrency:** Asyncio, Multiprocessing, Threading, and distributed task queues via Celery.
* **Frameworks:** FastAPI (High-performance async APIs), Django (DRF, ORM optimization), Flask.
* **Database Design & Architecture:**
    * *Relational:* PostgreSQL, MySQL (Advanced indexing, query optimization, connection pooling).
    * *NoSQL & Caching:* Redis (Caching strategies, pub/sub), MongoDB.
* **API Architecture:** RESTful API design patterns, WebSockets for real-time bi-directional communication, GraphQL.

---

## 🐚 Scripting, Automation & DevOps (Advanced)

Advanced system administration, environment orchestration, and cross-platform automation.

* **Shell Scripting:**
    * **Bash:** Advanced automation, error handling (`set -euo pipefail`), text processing (`awk`, `sed`, `grep`), and Linux system administration.
    * **PowerShell:** Complex scripting, Windows administration, object-oriented pipelines, and active management modules.
* **Containerization & Orchestration:** Docker, multi-stage Dockerfiles for optimized builds, Docker Compose.
* **CI/CD & Git:** Git (Advanced workflows, rebase, cherry-pick), GitHub Actions, GitLab CI/CD pipelines for automated testing and deployment.

---

## 🛠️ Testing & Professional Methodologies

* **Testing Frameworks:** PyTest (Fixtures, mocking, parameterization), Jest, React Testing Library.
* **Design Principles:** Clean Code, SOLID principles, Test-Driven Development (TDD), Microservices Architecture.
* **Tools:** Postman/Insomnia (Advanced environment variables, pre-request scripts), GitKraken/CLI.

---

## 🧠 Systems Design & Market Intelligence Infrastructure (Advanced)

* **Architecture:** Snapshot-first market intelligence pipeline with deterministic fallback, selection metadata, manual refresh, and API proxying.
* **Backend Implementation:** FastAPI async service with structured endpoints for market data, terminal intelligence, and refresh-task status tracking (`/api/market-data`, `/api/terminal-intelligence`, `/api/refresh-intelligence`, `/api/refresh-intelligence/status`).
* **Data Resilience:** Disk-backed snapshot (`last_market_snapshot.json`), IST window-based auto-refresh scheduling, TTL-managed background refresh queues, and graceful upstream degradation with retained last-known-good response.
* **Frontend Integration:** Next.js/Turbopack UI with periodic polling to backend endpoints, controlled refresh triggering, and explicit fallback messaging when live data or upstream credentials are unavailable.
* **API Proxying:** Next.js `app/api/market-data` route acting as a proxy to the FastAPI service with fallback routing and health-check awareness.

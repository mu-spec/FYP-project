"""
Milestone 8B.1 — Real external job sources.

Provider/adapter architecture:
    remote_ok.py   - Remote OK public API  (https://remoteok.com/api)
    arbeitnow.py   - Arbeitnow board API   (https://www.arbeitnow.com/api/job-board-api)
    service.py     - DB-backed cache, provider failure isolation, query API

Every provider normalizes its payload into ONE internal job shape (see
service.NORMALIZED_FIELDS). No HTML scraping of job pages: official JSON
APIs only.
"""

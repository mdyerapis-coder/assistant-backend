# ADR-001: keep protocol/domain logic free of framework imports where possible

**Status:** live

Python doesn't get the same compiler-enforced module boundary the Android side gets (`core:model`/`core:network`/`backend-client` are literally separate JVM Gradle modules there — see the Android plan section). Here, enforce the same *spirit* by convention: `app/sse.py`, the pure parts of `app/memory.py`, and `app/tools/registry.py`'s data shapes should not import FastAPI, `aiosqlite` connections, or anything requiring a running app to unit test. If a function needs a live DB connection to test, it's not in this category — that's fine, just don't let it creep into the modules that don't need one.

**Why:** the SSE encoding and the tool registry's shape are exactly the kind of logic worth testing with plain `pytest`, no server running, no DB fixture. Keeping them import-light is what makes that possible.

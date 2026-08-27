# ADR-004: (Android-side ADR, tracked here for numbering continuity only)

**Status:** applies to `assistant-android`, not this repo

No per-module `jvmToolchain` pinning beyond the root JDK 17 declaration on the Android side — avoids failing on a machine with only a newer JDK and no toolchain resolver. Recorded here so the ADR numbers stay identical across both repos' docs (this repo has no JVM toolchain to pin); see `assistant-android/docs/adr/004-...md` for the real content once that repo exists.

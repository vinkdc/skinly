# VALORANT account identifier

A minimal Windows CLI for Phase 0A of the VALORANT cosmetic usage tracker. It reads Riot Client's local lockfile and requests the current Riot session over localhost. The temporary local API credential stays in memory and is never printed or persisted.

## Run

Install the Rust toolchain, sign in to Riot Client, then run from PowerShell:

```powershell
cargo run --quiet
```

The command prints the logged-in account's game name, tag, PUUID, and region when Riot Client provides it. If Riot Client is closed, the command exits with a clear error.

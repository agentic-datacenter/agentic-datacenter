# Test vectors from shirudo

The files under `keepalive/` are copied unchanged from [shirudo](https://github.com/shirudo-dev/shirudo), at the commit in `SHIRUDO_PIN`, from its directory `testing/fixtures/keepalive/`. They are under shirudo's BSD-2-Clause licence, in `LICENSE` beside this file, copyright (c) 2026 Authors of shirudo. They are not under the licence of Agentic-Datacenter.

- `node-*.json`: four keepalive bodies, in the format `shirudo.keepalive/1`.
- `quotes.tsv`: one row per body, with the TPM quote of the body as `shirudo-quote-check` reads it: the body's file name, `attest`, `sig`, `ak` and the SHA-256 of the body.

`SHIRUDO_PIN` lists the SHA-256 of each file, and `tests/conformance/test_shirudo_pin.py` checks them. A change to these files is a pin bump: its own pull request, which changes the pin and the copies together (ADR 0030).

They are used by the tests only, and are not part of any distribution of Agentic-Datacenter.

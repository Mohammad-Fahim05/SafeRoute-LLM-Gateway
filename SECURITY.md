# Security Policy & Defensive Architecture

## 1. Scope & Security Model

SafeRoute LLM Gateway is designed as an asynchronous, observable, multi-tenant reverse proxy sitting between client applications and downstream AI model providers.

The security model is structured around zero-trust authentication, tenant isolation, and defense-in-depth heuristics:

- **Authentication:** All client requests are authenticated using keyed HMAC-SHA256 verifiers. Plaintext client API keys are never persisted to disk or stored in application state.
- **Constant-Time Verification:** Authentication checks execute via `hmac.compare_digest` to prevent timing side-channel attacks.
- **Tenant Isolation:** Cache keys (`ExactResponseCache` and `SemanticResponseCache`) and persistent usage records are strictly segmented by `client_id`. Client A cannot retrieve cached completions or query usage metadata belonging to Client B.
- **Role-Based Authorization:** Administrative management routes (`/api/management/*`) require keys with the `admin` role. Client keys receive HTTP 403 Forbidden.
- **Input/Output Guardrails:** Deterministic regular expressions detect and redact PII (credit cards, SSNs, phone numbers, email addresses, and cloud provider API keys).
- **Observability Data Protection:** Prometheus metrics (`/metrics`) and structured JSON logs enforce strictly bounded cardinalities. Raw user prompts, client API keys, Authorization headers, and sensitive identifiers are strictly barred from metric labels and log envelopes.

---

## 2. Reporting a Vulnerability

If you discover a potential security issue within SafeRoute LLM Gateway:

1. **Do not create a public GitHub issue.**
2. Send a coordinated vulnerability report directly to the repository maintainer:
   - **Email:** `fahimfiroz2005@gmail.com`
   - **Subject:** `[SECURITY] SafeRoute LLM Gateway - <Brief Description>`
3. Include detailed steps to reproduce the issue, proof of concept, and environment details.
4. Vulnerability disclosures will be acknowledged within 48 hours, followed by a remediation and security patch timeline.

---

## 3. Credential Handling & Rotation Runbook

### Key Architecture
- Client API keys follow the format: `gw_<random_urlsafe_bytes>`.
- The gateway computes: `verifier = hmac.new(AUTH_SECRET.encode(), api_key.encode(), sha256).hexdigest()`.
- Verifiers are stored in configuration (`CLIENT_KEYS`) or database records.

### Key Rotation Procedure
To rotate a client API key without downtime:
1. Issue a new client key:
   ```powershell
   python scripts/manage_keys.py create --name "Client Rotation Key"
   ```
2. Distribute the new key to the client application.
3. Once client traffic has migrated, revoke the previous key:
   ```powershell
   python scripts/manage_keys.py revoke --verifier "<old_verifier>"
   ```
4. Verify revocation: Requests with the revoked key immediately return HTTP 401 Unauthorized.

---

## 4. Historical Secret Finding & History Remediation Analysis

### Finding Classification:
- **Location:** Historical Git commit `d0721a8` (`README.md:243`).
- **Classification:** An early development test API key included in markdown documentation examples.
- **Revocation Status:** **PERMANENTLY REVOKED**. The verifier is invalidated and active runtime verification rejects this credential with HTTP 401.
- **Working Tree:** Verified clean (0 secrets in active files or production bundles).

### History Remediation Policy:
In accordance with professional release hygiene and repository safety rules:
- Git history was not unilaterally rewritten because the repository is tagged at `v1.0.0` and published to GitHub. Rewriting historical commits (`git filter-repo`) would alter commit SHAs, invalidate the immutable `v1.0.0` tag, and require a force-push that breaks downstream clones and forks.
- Since the credential is permanently revoked and nonfunctional, key revocation is the industry-standard remediation that preserves audit trail integrity.
- If full history sanitization is ever required by organizational policy, the maintainer may execute:
  ```powershell
  # Requires git-filter-repo utility
  git filter-repo --replace-text <(echo "REVOKED_KEY==>REDACTED_TEST_KEY")
  git push origin master --force-with-lease --tags
  ```

---

## 5. Known Security & Architectural Limitations

1. **Heuristic Defense-in-Depth:** Input and output filters utilize deterministic regex patterns and local classifiers. While effective against common script injection and PII leakage, heuristic filters do not provide a formal mathematical guarantee against novel adversarial token sequences.
2. **Fixed-Window Rate Limiting:** The atomic Redis Lua rate limiter operates on a fixed-window schedule. Clients may execute up to 2x burst traffic across adjacent window boundaries.
3. **Single-Node SQLite Persistence:** SQLite WAL mode with `PRAGMA busy_timeout=15000` provides ACID storage for single-node deployments. For horizontally scaled distributed clusters, PostgreSQL is recommended.

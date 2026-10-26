import React from 'react';
import { PageHeader } from '../components/ui/PageHeader';
import { SectionCard } from '../components/ui/SectionCard';
import {
  ShieldCheck,
  EyeOff,
  Sliders,
  CheckCircle2,
  KeyRound,
} from 'lucide-react';

export const Security: React.FC = () => {
  return (
    <div className="space-y-7">
      {/* Header */}
      <PageHeader
        title="Security & Guardrail Defenses"
        subtitle="Cryptographic authentication, prompt injection prevention, PII redaction, and client data isolation."
        breadcrumbs={[{ label: 'SafeRoute' }, { label: 'Security' }]}
      />

      {/* Security Principles Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Timing-Safe HMAC Authentication */}
        <SectionCard
          title="Timing-Safe HMAC Authentication"
          subtitle="HMAC-SHA256 with constant-time verification"
          icon={KeyRound}
        >
          <div className="space-y-3.5">
            <p className="text-xs text-[#C1CCDE] leading-relaxed">
              Client requests must present a bearer token in the <code className="text-[#82A9FF] font-mono text-[11px] bg-[#1C2A40] px-1.5 py-0.5 rounded border border-[#3B4D66]">Authorization: Bearer &lt;key&gt;</code> header. The gateway compares incoming hashes against registered client records using Python's <code className="text-[#F0F4FC] font-mono text-[11px] bg-[#1C2A40] px-1.5 py-0.5 rounded border border-[#3B4D66]">hmac.compare_digest</code>, rendering side-channel timing attacks ineffective.
            </p>
            <div className="p-3 bg-[#1C2A40] rounded-lg border border-[#33455E] text-xs space-y-2">
              <div className="flex justify-between">
                <span className="text-[#95A6BE]">Secret Storage:</span>
                <span className="text-[#63D6A7] font-medium">HMAC-SHA256 Hashed (Never Plaintext)</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#95A6BE]">Session State:</span>
                <span className="text-[#F0F4FC] font-medium">Stateless Bearer Tokens</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#95A6BE]">Key Format:</span>
                <span className="text-[#82A9FF] font-mono">gw_test_[32_urlsafe_bytes]</span>
              </div>
            </div>
          </div>
        </SectionCard>

        {/* Zero-Payload Retention Guarantee */}
        <SectionCard
          title="Zero-Payload Data Retention"
          subtitle="Strict client prompt and response privacy contract"
          icon={EyeOff}
        >
          <div className="space-y-3.5">
            <p className="text-xs text-[#C1CCDE] leading-relaxed">
              By architectural contract, prompt texts and generated completions are never written to disk or recorded in SQLite. The gateway records only audit metadata: timestamps, token counts, model identifiers, execution latency, and cache hits.
            </p>
            <div className="p-3 bg-[#1C2A40] rounded-lg border border-[#33455E] text-xs space-y-2">
              <div className="flex justify-between">
                <span className="text-[#95A6BE]">Prompt Disk Persistence:</span>
                <span className="text-[#63D6A7] font-medium">0 Bytes (In-Memory Transit Only)</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#95A6BE]">Audit Trace Storage:</span>
                <span className="text-[#82A9FF] font-medium">Metadata Only (Normalized SQLite)</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#95A6BE]">Compliance Mode:</span>
                <span className="text-[#F0F4FC] font-medium">GDPR & HIPAA Compliant Data Flow</span>
              </div>
            </div>
          </div>
        </SectionCard>

        {/* PII Redaction Engine */}
        <SectionCard
          title="Automated PII Redaction Filter"
          subtitle="Regex and pattern-based sanitization pipeline"
          icon={ShieldCheck}
        >
          <div className="space-y-3.5">
            <p className="text-xs text-[#C1CCDE] leading-relaxed">
              Before prompts are forwarded to local or remote inference engines, the guardrail pipeline scans for sensitive personal data and replaces occurrences with type-safe placeholders.
            </p>
            <div className="grid grid-cols-2 gap-2.5 text-xs">
              <div className="p-2.5 bg-[#1C2A40] rounded-lg border border-[#33455E] flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-[#63D6A7] flex-shrink-0" />
                <span className="text-[#F0F4FC] text-xs">Email Addresses</span>
              </div>
              <div className="p-2.5 bg-[#1C2A40] rounded-lg border border-[#33455E] flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-[#63D6A7] flex-shrink-0" />
                <span className="text-[#F0F4FC] text-xs">Credit Card Numbers</span>
              </div>
              <div className="p-2.5 bg-[#1C2A40] rounded-lg border border-[#33455E] flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-[#63D6A7] flex-shrink-0" />
                <span className="text-[#F0F4FC] text-xs">Social Security Numbers</span>
              </div>
              <div className="p-2.5 bg-[#1C2A40] rounded-lg border border-[#33455E] flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-[#63D6A7] flex-shrink-0" />
                <span className="text-[#F0F4FC] text-xs">Private API Keys</span>
              </div>
            </div>
          </div>
        </SectionCard>

        {/* Prompt Injection Classifier */}
        <SectionCard
          title="Prompt Injection Heuristics"
          subtitle="Jailbreak and system prompt override defense"
          icon={Sliders}
        >
          <div className="space-y-3.5">
            <p className="text-xs text-[#C1CCDE] leading-relaxed">
              System instructions are guarded against adversarial escape sequences (e.g. "Ignore previous instructions", "DAN mode", role reversal prompts). Unsafe requests are rejected with HTTP 400 Bad Request before token generation begins.
            </p>
            <div className="p-3 bg-[#1C2A40] rounded-lg border border-[#33455E] text-xs space-y-2">
              <div className="flex justify-between">
                <span className="text-[#95A6BE]">Guardrail Intercept:</span>
                <span className="text-[#82A9FF] font-medium">Pre-Inference Evaluation</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#95A6BE]">Rejection Envelope:</span>
                <span className="text-[#F18C9C] font-medium">HTTP 400 input_guardrail_blocked</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#95A6BE]">Audit Event:</span>
                <span className="text-[#F0F4FC] font-medium">Logged in request_records</span>
              </div>
            </div>
          </div>
        </SectionCard>
      </div>
    </div>
  );
};

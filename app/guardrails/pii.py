"""High-precision personally identifiable information (PII) scanner and redaction engine."""

import re
from typing import List, Tuple


def _luhn_checksum(card_number_str: str) -> bool:
    """Validate a numeric string using the Luhn checksum algorithm."""
    digits = [int(c) for c in card_number_str if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    reverse_digits = digits[::-1]
    for idx, d in enumerate(reverse_digits):
        if idx % 2 == 1:
            doubled = d * 2
            checksum += (doubled - 9) if doubled > 9 else doubled
        else:
            checksum += d
    return checksum % 10 == 0


class PIIScanner:
    """Deterministic PII scanner providing high-precision detection and entity redaction."""

    # Pre-compiled high-precision patterns
    SSN_PATTERN = re.compile(
        r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"
    )
    CARD_CANDIDATE_PATTERN = re.compile(
        r"\b(?:\d[ -]*?){13,19}\b"
    )
    EMAIL_PATTERN = re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    )
    PHONE_PATTERN = re.compile(
        r"(?:\+?1[-. ]?)?\(?[2-9]\d{2}\)?[-. ]?[2-9]\d{2}[-. ]?\d{4}\b"
    )
    API_KEY_PATTERN = re.compile(
        r"\b(?:AKIA[0-9A-Z]{16}|ghp_[0-9a-zA-Z]{36}|sk-[a-zA-Z0-9_\-]{20,})\b"
    )

    def scan_and_redact(
        self,
        text: str,
        redact: bool = False,
    ) -> Tuple[bool, float, str, List[str]]:
        """Scan text for PII entities and optionally produce safe, in-place entity redactions.

        Returns:
            Tuple of:
            - detected (bool): True if any high-confidence PII entity is found.
            - score (float): Confidence score (0.0 to 1.0).
            - sanitized_text (str): Redacted text if redact=True, otherwise original text.
            - detected_types (List[str]): List of detected entity labels (e.g. ['ssn', 'email']).
        """
        if not text or not text.strip():
            return False, 0.0, text, []

        detected_types: List[str] = []
        sanitized = text

        # 1. SSN
        ssn_matches = list(self.SSN_PATTERN.finditer(text))
        if ssn_matches:
            detected_types.append("ssn")
            if redact:
                sanitized = self.SSN_PATTERN.sub("[REDACTED_SSN]", sanitized)

        # 2. Credit Card PANs (filtered with Luhn checksum)
        valid_cards: List[str] = []
        for match in self.CARD_CANDIDATE_PATTERN.finditer(text):
            raw = match.group(0)
            digits_only = re.sub(r"\D", "", raw)
            if 13 <= len(digits_only) <= 19 and _luhn_checksum(digits_only):
                valid_cards.append(raw)

        if valid_cards:
            detected_types.append("credit_card")
            if redact:
                for card in valid_cards:
                    sanitized = sanitized.replace(card, "[REDACTED_CARD]")

        # 3. API Keys & Cloud Credentials
        key_matches = list(self.API_KEY_PATTERN.finditer(text))
        if key_matches:
            detected_types.append("api_key")
            if redact:
                sanitized = self.API_KEY_PATTERN.sub("[REDACTED_API_KEY]", sanitized)

        # 4. Email addresses
        email_matches = list(self.EMAIL_PATTERN.finditer(text))
        if email_matches:
            detected_types.append("email")
            if redact:
                sanitized = self.EMAIL_PATTERN.sub("[REDACTED_EMAIL]", sanitized)

        # 5. Phone numbers (exclude simple dates or isolated numbers)
        phone_matches = list(self.PHONE_PATTERN.finditer(text))
        if phone_matches:
            detected_types.append("phone_number")
            if redact:
                sanitized = self.PHONE_PATTERN.sub("[REDACTED_PHONE]", sanitized)

        if not detected_types:
            return False, 0.0, text, []

        # High-confidence PII calculation
        # SSN, Credit Card, and API Keys yield 0.95+ confidence; email/phone alone yields 0.85
        high_severity = {"ssn", "credit_card", "api_key"}
        if any(t in high_severity for t in detected_types):
            confidence = 0.95
        else:
            confidence = 0.85

        return True, confidence, sanitized, detected_types


pii_scanner = PIIScanner()

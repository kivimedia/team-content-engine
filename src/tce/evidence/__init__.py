"""Evidence intake: Fathom meetings and GitHub commit groups -> EvidenceSource rows,
a coverage ledger per collection run, and LLM moment extraction.

Nothing in this package writes to Fathom or GitHub. Raw content is stored only in
`payload_private`; coverage items and activity strings carry ids and counts only.
"""

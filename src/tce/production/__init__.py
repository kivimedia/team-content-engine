"""Recording and production for the evidence-first editorial system (package 4).

Nothing in this package calls a metered API: transcription goes to a local
faster-whisper worker (or reports `unavailable`), rendering uses local ffmpeg,
and Google Docs export goes through an injectable client (the `gws` CLI on the
server host) or falls back to a private .docx.
"""

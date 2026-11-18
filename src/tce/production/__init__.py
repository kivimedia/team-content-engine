"""Recording and production for the evidence-first editorial system (package 4).

One thing in this package calls a metered API: the new backgrounds for a walking video
(`backdrop`, 18-Nov), a paid video model that runs only for a video whose owner switched it
on, under a spend limit per render and per day. Nothing else does: transcription goes to a local
faster-whisper worker (or reports `unavailable`), rendering uses local ffmpeg,
and Google Docs export goes through an injectable client (the `gws` CLI on the
server host) or falls back to a private .docx.
"""

# ClipForge AI build status

## Implemented and smoke-tested (v1.1.0)

- [x] Responsive dashboard and navigation
- [x] Video upload and local backend processing
- [x] FFmpeg metadata inspection and H.264/AAC export
- [x] Vertical, square, portrait and landscape export formats
- [x] Optional SRT/VTT transcript upload
- [x] Optional Faster-Whisper transcription
- [x] Optional Gemini transcript-based highlight ranking
- [x] Transcript heuristic fallback and clearly labelled no-transcript fallback
- [x] SRT subtitle export and burned-in captions when transcript data exists
- [x] Downloadable MP4 and SRT clips
- [x] Automatic poster thumbnails for generated clips
- [x] Custom clip remix editor with start/end trimming, aspect ratio selection and optional burned-in captions
- [x] Remix exports appear in the Clips Library and local analytics
- [x] API smoke tests for upload, render, remix, thumbnails, creator CRUD, publishing queue and analytics
- [x] SQLite persistence for project history, creator spaces and publishing plans
- [x] Creator Spaces CRUD
- [x] Publishing Queue draft/schedule planning
- [x] Local project/export analytics
- [x] Original browser editor preserved as a separate page
- [x] Windows, macOS/Linux and Docker launch paths

## Requires credentials, external approvals or further engineering

- Instagram/TikTok/YouTube direct publishing: requires platform developer apps, OAuth, permissions, review and policy-compliant upload handling.
- Real social analytics: requires authorized platform APIs and account connections.
- Multi-user hosted accounts: requires authentication, authorization, tenant isolation and secure deployment.
- Live stream clipping: requires platform-specific stream access/recording integrations.
- Face tracking, speaker diarization and contextual B-roll: require optional model/provider integrations and additional render pipeline work; not represented as active in this build.
- Production hosting: requires HTTPS, authentication, rate limiting, durable worker queue, monitoring, backups and storage lifecycle policies.

The app is a functioning local-first creator studio, not a hosted SaaS product. Keep it on localhost unless you add the listed security and deployment controls.

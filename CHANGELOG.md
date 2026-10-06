# 0.1.0-beta.2

Fix MQTT discovery setup by listing pending flows through Home Assistant's WebSocket API. The previous GET request is unsupported and returns HTTP 405. Setup reports now identify failed API requests without including credentials or response bodies. Existing installed apps and recovery backups are reused when preparation resumes. Live commissioning remains under test.

# 0.1.0-beta.1

Initial lab candidate: Home Assistant ingress onboarding, four-app provisioning, checksum-verified EyZEE files, configuration validation and restart, existing MG24 service orchestration, and MQTT-backed readiness checks. Fresh HAOS acceptance remains pending.

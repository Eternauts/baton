import os

# Explicit test environment: never depends on a developer's local .env.
os.environ.update({
    "GOOGLE_CLOUD_PROJECT": "test-project",
    "GEMINI_MODEL": "test-model",
    "GEMINI_FAST_MODEL": "test-fast-model",
    "GEMINI_LOCATION": "global",
    "TRANSCRIBE_ENGINE": "chirp3",
    "AEGIS_API_KEY": "test_super_secret_key",
})
os.environ.pop("VERTEX_LOCATION", None)

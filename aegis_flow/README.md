# Baton app (Flutter)

One codebase for Android and the browser.

```bash
flutter pub get
flutter test --dart-define=AEGIS_API_KEY=test

# Android (on-device Gemma if installed, server model otherwise)
flutter run --dart-define=AEGIS_API_KEY=<demo key>

# Web, against the live service or a local one
flutter run -d chrome --dart-define=AEGIS_API_KEY=<demo key> --dart-define=BACKEND_URL=https://<api-url>
```

Use the **demo key** (`aegis-demo-key` in Secret Manager) for anything you hand to other people. It opens the app endpoints only.
The website is its own Cloud Run service (`baton-app`), built and deployed with `scripts/deploy_web.sh`; see `backend/AGENTS.md`, section 11.

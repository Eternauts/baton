class AppConfig {
  static const String _backendOverride = String.fromEnvironment('BACKEND_URL');
  static const String _liveBackend = 'https://baton-api-545013329202.asia-southeast1.run.app';

  /// Android and the website (a separate service, baton-app) both talk to the live API. BACKEND_URL overrides it, for a local server.
  static String get backendUrl => _backendOverride.isNotEmpty ? _backendOverride : _liveBackend;

  // No default: build with --dart-define=AEGIS_API_KEY=<key>. Without it, cloud ASR
  // reports "No backend config" instead of sending a key the server will reject.
  // The website must be built with the DEMO key: it ships inside the page, so it must never be the supervisor key.
  static const String aegisApiKey = String.fromEnvironment('AEGIS_API_KEY');

  static bool get hasBackendConfig => backendUrl.isNotEmpty && aegisApiKey.isNotEmpty;
  static String get healthEndpoint => '$backendUrl/api/health';
  static String get transcribeEndpoint => '$backendUrl/api/transcribe';
}

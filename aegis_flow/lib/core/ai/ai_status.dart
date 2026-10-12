import 'package:flutter_gemma/flutter_gemma.dart';

sealed class AiStatus {
  const AiStatus();
}

class AiStatusNotInstalled extends AiStatus {
  final String modelPath;
  const AiStatusNotInstalled({required this.modelPath});
}

class AiStatusLoading extends AiStatus {
  const AiStatusLoading();
}

class AiStatusReady extends AiStatus {
  final PreferredBackend backend;
  final int loadMs;
  final String modelPath;
  final int fileSizeMb;

  const AiStatusReady({
    required this.backend,
    required this.loadMs,
    required this.modelPath,
    required this.fileSizeMb,
  });
}

/// No on-device model on this platform (the website): notes are read by the server's model instead.
class AiStatusCloud extends AiStatus {
  const AiStatusCloud();
}

class AiStatusError extends AiStatus {
  final String message;
  const AiStatusError(this.message);
}

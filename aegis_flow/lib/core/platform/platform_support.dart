import 'dart:io' show File;
import 'dart:typed_data';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:http/http.dart' as http;

/// The few places where the Android app and the website differ, behind one small API so the rest of the
/// code is the same on both. Everything else (screens, view models, sync, handover) is shared as it is.
bool get isWeb => kIsWeb;

/// The bytes of a finished recording. On Android that is a file in the cache; in a browser the recorder
/// hands back a `blob:` URL, which the browser lets us fetch.
Future<Uint8List> readRecordingBytes(String path) async {
  if (kIsWeb) return http.readBytes(Uri.parse(path));
  final f = File(path);
  if (!await f.exists()) throw StateError('Recording is missing: $path');
  return f.readAsBytes();
}

/// Audio is deleted once the note is submitted. A browser frees its recording itself.
Future<void> deleteRecording(String path) async {
  if (kIsWeb) return;
  final f = File(path);
  if (await f.exists()) await f.delete();
}

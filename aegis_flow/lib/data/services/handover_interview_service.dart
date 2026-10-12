import 'dart:convert';
import 'package:http/http.dart' as http;
import '../../core/config/app_config.dart';

/// A readable failure for the screen: what went wrong, and whether trying again can help.
class InterviewException implements Exception {
  final String message;
  final bool retryable;
  InterviewException(this.message, {this.retryable = true});
  @override
  String toString() => message;
}

class InterviewConflict {
  final String ruleId, title, description, severity, status;
  const InterviewConflict({required this.ruleId, required this.title, required this.description, required this.severity, required this.status});
  factory InterviewConflict.fromMap(Map<String, dynamic> m) => InterviewConflict(
        ruleId: m['rule_id']?.toString() ?? '',
        title: m['title']?.toString() ?? '',
        description: m['description']?.toString() ?? '',
        severity: m['severity']?.toString().toUpperCase() ?? 'WARNING',
        status: m['status']?.toString().toUpperCase() ?? 'OPEN',
      );
}

class InterviewQuestion {
  final String id, text;
  final bool answered;
  const InterviewQuestion({required this.id, required this.text, required this.answered});
  factory InterviewQuestion.fromMap(Map<String, dynamic> m) =>
      InterviewQuestion(id: m['id']?.toString() ?? '', text: m['question_text']?.toString() ?? '', answered: m['answered'] == true);
}

class BriefEntry {
  final String id, text, severity;
  final List<String> citations;
  final bool acknowledged;
  final String? acknowledgedBy, readback, acknowledgedAt;
  const BriefEntry({required this.id, required this.text, required this.severity, required this.citations, required this.acknowledged, this.acknowledgedBy, this.readback, this.acknowledgedAt});
  bool get isCritical => severity == 'CRITICAL';
  factory BriefEntry.fromMap(Map<String, dynamic> m) => BriefEntry(
        id: m['id']?.toString() ?? '',
        text: m['text']?.toString() ?? '',
        severity: m['severity']?.toString().toUpperCase() ?? 'INFO',
        citations: (m['citations'] as List?)?.map((e) => e.toString()).toList() ?? const [],
        acknowledged: m['acknowledged'] == true,
        acknowledgedBy: m['acknowledged_by']?.toString(),
        readback: m['readback_text']?.toString(),
        acknowledgedAt: m['acknowledged_at']?.toString(),
      );
}

/// The interview session as the server holds it.
class InterviewSession {
  final String id, status;
  final List<InterviewConflict> conflicts;
  final List<InterviewQuestion> questions;
  final List<BriefEntry> brief;
  final String? incomingSupervisor;
  const InterviewSession({required this.id, required this.status, required this.conflicts, required this.questions, required this.brief, this.incomingSupervisor});
  factory InterviewSession.fromMap(Map<String, dynamic> m) {
    final b = m['brief'] as Map?;
    return InterviewSession(
      id: m['id']?.toString() ?? '',
      status: m['status']?.toString() ?? '',
      conflicts: (m['conflicts'] as List? ?? const []).map((e) => InterviewConflict.fromMap(Map<String, dynamic>.from(e as Map))).toList(),
      questions: (m['questions'] as List? ?? const []).map((e) => InterviewQuestion.fromMap(Map<String, dynamic>.from(e as Map))).toList(),
      brief: ((b?['items']) as List? ?? const []).map((e) => BriefEntry.fromMap(Map<String, dynamic>.from(e as Map))).toList(),
      incomingSupervisor: b?['incoming_supervisor']?.toString(),
    );
  }
}

/// The AI brief the agent pipeline wrote (cited, guardrail-checked), shown next to the rule items.
class PipelineBrief {
  final String headline;
  final String guardrailStatus;
  final List<String> items;
  final int citationCount;
  const PipelineBrief({required this.headline, required this.guardrailStatus, required this.items, required this.citationCount});
}

class HandoverInterviewService {
  Map<String, String> get _headers => {'Content-Type': 'application/json', 'X-Aegis-Key': AppConfig.aegisApiKey};
  Uri _u(String path) => Uri.parse('${AppConfig.backendUrl}$path');

  Future<Map<String, dynamic>> _send(String method, String path, {Object? body, int timeoutSec = 20}) async {
    if (!AppConfig.hasBackendConfig) {
      throw InterviewException('This build has no server key, so the handover cannot reach the server.', retryable: false);
    }
    try {
      final req = http.Request(method, _u(path))..headers.addAll(_headers);
      if (body != null) req.body = jsonEncode(body);
      final res = await http.Response.fromStream(await req.send().timeout(Duration(seconds: timeoutSec)));
      final data = res.body.isEmpty ? <String, dynamic>{} : (jsonDecode(res.body) as Map<String, dynamic>);
      if (res.statusCode == 200) return data;
      final detail = data['detail'];
      final text = detail is String ? detail : (detail is Map ? (detail['error']?['message']?.toString() ?? '') : '');
      if (res.statusCode == 401) throw InterviewException('The server rejected this app\'s key.', retryable: false);
      if (res.statusCode == 409 || res.statusCode == 422) throw InterviewException(text.isEmpty ? 'The server did not accept that.' : text, retryable: false);
      if (res.statusCode == 404) throw InterviewException('That handover is no longer on the server.', retryable: false);
      throw InterviewException('The server had a problem (${res.statusCode}). Try again.');
    } on InterviewException {
      rethrow;
    } catch (_) {
      throw InterviewException('No connection to the server. Check the network and try again.');
    }
  }

  Future<InterviewSession> interview(String id, {String language = 'en'}) async =>
      InterviewSession.fromMap(await _send('POST', '/api/handover/$id/interview?language=$language', timeoutSec: 25));

  Future<InterviewSession> session(String id) async => InterviewSession.fromMap(await _send('GET', '/api/handover/$id'));

  Future<InterviewSession> answer(String id, Map<String, String> answers) async =>
      InterviewSession.fromMap(await _send('POST', '/api/handover/$id/answer', body: {'answers': answers}));

  Future<InterviewSession> acknowledge(String id, {required String itemId, required String readback, required String supervisor}) async =>
      InterviewSession.fromMap(await _send('POST', '/api/handover/$id/acknowledge', body: {'item_id': itemId, 'readback_text': readback, 'supervisor': supervisor}));

  /// Returns the server's message and how many conflicts are still open.
  Future<({String message, int openConflicts, String? supervisor})> complete(String id) async {
    final d = await _send('POST', '/api/handover/$id/complete');
    return (message: d['message']?.toString() ?? 'Handover transferred.', openConflicts: (d['open_conflicts'] as num?)?.toInt() ?? 0, supervisor: d['incoming_supervisor']?.toString());
  }

  /// Null until the pipeline has written its brief (usually 10 to 20 s after the sync).
  Future<PipelineBrief?> pipelineBrief(String id) async {
    final d = await _send('GET', '/api/handover/$id/brief');
    if (d['ready'] != true) return null;
    final b = Map<String, dynamic>.from(d['brief'] as Map);
    final items = (b['items'] as List? ?? const []).map((e) => (e is Map ? (e['text'] ?? e['summary'] ?? '') : e).toString()).where((t) => t.isNotEmpty).toList();
    final cites = (b['citation_details'] as List? ?? const []).length;
    return PipelineBrief(headline: b['headline']?.toString() ?? '', guardrailStatus: b['guardrail_status']?.toString() ?? '', items: items, citationCount: cites);
  }
}

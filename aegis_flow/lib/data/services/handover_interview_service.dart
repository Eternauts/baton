import 'api_client.dart';

/// Kept as a name for the interview's failures; it is the shared API error.
typedef InterviewException = ApiException;

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
  final ApiClient _api = ApiClient();
  Future<Map<String, dynamic>> _send(String method, String path, {Object? body, int timeoutSec = 20}) =>
      _api.send(method, path, body: body, timeoutSec: timeoutSec);

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

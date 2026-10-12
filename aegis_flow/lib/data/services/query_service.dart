import 'api_client.dart';

class PermitInfo {
  final String id, type, title, status;
  final bool expired;
  const PermitInfo({required this.id, required this.type, required this.title, required this.status, required this.expired});
  factory PermitInfo.fromMap(Map<String, dynamic> m) => PermitInfo(
        id: m['id']?.toString() ?? '',
        type: m['type']?.toString() ?? '',
        title: m['title']?.toString() ?? '',
        status: m['status']?.toString() ?? '',
        expired: m['expired'] == true,
      );
}

/// A document the search found: its best matching section, shown the moment the search returns.
class DocHit {
  final String sourceId, docType, chunkId, heading, snippet;
  final int sections;
  const DocHit({required this.sourceId, required this.docType, required this.chunkId, required this.heading, required this.snippet, required this.sections});
  factory DocHit.fromMap(Map<String, dynamic> m) {
    final best = Map<String, dynamic>.from(m['best'] as Map? ?? const {});
    return DocHit(
      sourceId: m['source_id']?.toString() ?? '',
      docType: m['doc_type']?.toString() ?? 'SOP',
      sections: (m['sections'] as num?)?.toInt() ?? 1,
      chunkId: best['chunk_id']?.toString() ?? '',
      heading: best['heading']?.toString() ?? '',
      snippet: best['snippet']?.toString() ?? '',
    );
  }
}

class Citation {
  final String chunkId, title, sourceType, sourceId, snippet;
  const Citation({required this.chunkId, required this.title, required this.sourceType, required this.sourceId, required this.snippet});
  factory Citation.fromMap(Map<String, dynamic> m) => Citation(
        chunkId: m['chunk_id']?.toString() ?? '',
        title: m['title']?.toString() ?? '',
        sourceType: m['source_type']?.toString() ?? '',
        sourceId: m['source_id']?.toString() ?? '',
        snippet: m['snippet']?.toString() ?? '',
      );
}

class RuleVerdict {
  final String ruleId, severity, title, status;
  final int reports;
  const RuleVerdict({required this.ruleId, required this.severity, required this.title, required this.status, required this.reports});
  factory RuleVerdict.fromMap(Map<String, dynamic> m) => RuleVerdict(
        ruleId: m['rule_id']?.toString() ?? '',
        severity: m['severity']?.toString().toUpperCase() ?? 'WARNING',
        title: m['title']?.toString() ?? '',
        status: m['status']?.toString() ?? 'OPEN',
        reports: (m['reports'] as num?)?.toInt() ?? 1,
      );
}

class QueryResult {
  final String answer, language;
  final List<String> steps, cautions, followUps;
  final List<Citation> citations;
  final List<RuleVerdict> verdicts; // the rules' open conflicts, quoted unchanged: never the model's words
  final PermitInfo? permit;
  final String? permitAlert, confidenceNote;
  final bool fallback;
  final int latencyMs;
  const QueryResult({
    required this.answer,
    required this.language,
    required this.steps,
    required this.cautions,
    required this.followUps,
    required this.citations,
    required this.verdicts,
    required this.permit,
    required this.permitAlert,
    required this.confidenceNote,
    required this.fallback,
    required this.latencyMs,
  });
  factory QueryResult.fromMap(Map<String, dynamic> m) {
    List<String> strings(dynamic v) => (v as List?)?.map((e) => e.toString()).toList() ?? const [];
    List<T> maps<T>(dynamic v, T Function(Map<String, dynamic>) f) =>
        (v as List?)?.map((e) => f(Map<String, dynamic>.from(e as Map))).toList() ?? const [];
    return QueryResult(
      answer: m['answer']?.toString() ?? '',
      language: m['answer_language']?.toString() ?? 'en',
      steps: strings(m['steps']),
      cautions: strings(m['cautions']),
      followUps: strings(m['follow_ups']),
      citations: maps(m['citations'], Citation.fromMap),
      verdicts: maps(m['rule_verdicts'], RuleVerdict.fromMap),
      permit: m['permit'] is Map ? PermitInfo.fromMap(Map<String, dynamic>.from(m['permit'] as Map)) : null,
      permitAlert: m['permit_alert']?.toString(),
      confidenceNote: m['confidence_note']?.toString(),
      fallback: m['fallback'] == true,
      latencyMs: (m['latency_ms'] as num?)?.toInt() ?? 0,
    );
  }
}

/// One section of a document, read in full.
class DocSection {
  final String title, text, sourceType, docType;
  final String? createdAt;
  const DocSection({required this.title, required this.text, required this.sourceType, required this.docType, this.createdAt});
  factory DocSection.fromMap(Map<String, dynamic> m) => DocSection(
        title: m['title']?.toString() ?? '',
        text: m['text']?.toString() ?? '',
        sourceType: m['source_type']?.toString() ?? '',
        docType: m['doc_type']?.toString() ?? '',
        createdAt: m['created_at']?.toString(),
      );
}

/// Query mode: ask the plant's documents a question on the spot. Search first (about a second), answer second.
class QueryService {
  final ApiClient _api = ApiClient();

  Future<List<PermitInfo>> permits() async {
    final d = await _api.send('GET', '/api/v1/permits', timeoutSec: 10);
    return (d['permits'] as List? ?? const []).map((e) => PermitInfo.fromMap(Map<String, dynamic>.from(e as Map))).toList();
  }

  Future<int> documentCount() async {
    final d = await _api.send('GET', '/api/v1/docs', timeoutSec: 10);
    return (d['documents'] as List? ?? const []).length;
  }

  Future<List<DocHit>> search(String query, {String? permitId}) async {
    final d = await _api.send('POST', '/api/v1/search', body: {'query': query, if (permitId != null) 'permit_id': permitId}, timeoutSec: 12);
    return (d['documents'] as List? ?? const []).map((e) => DocHit.fromMap(Map<String, dynamic>.from(e as Map))).toList();
  }

  Future<QueryResult> query(String question, {required String unit, String? assetTag, String? permitId, String? deviceId}) async {
    final d = await _api.send('POST', '/api/v1/query',
        body: {'question': question, 'unit': unit, if (assetTag != null) 'asset_tag': assetTag, if (permitId != null) 'permit_id': permitId, if (deviceId != null) 'device_id': deviceId},
        timeoutSec: 25);
    return QueryResult.fromMap(d);
  }

  Future<DocSection> section(String chunkId) async => DocSection.fromMap(await _api.send('GET', '/api/v1/docs/$chunkId', timeoutSec: 10));
}

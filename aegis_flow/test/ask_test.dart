import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:aegis_flow/core/data/handover_repository.dart';
import 'package:aegis_flow/data/services/api_client.dart';
import 'package:aegis_flow/data/services/query_service.dart';
import 'package:aegis_flow/features/ask/ask_view_model.dart';
import 'package:aegis_flow/features/ask/views/ask_screen.dart';

const _permit = PermitInfo(id: 'PERMIT-M-102', type: 'MAINTENANCE', title: 'Pump Gasket Replacement', status: 'EXPIRED', expired: true);
const _live = PermitInfo(id: 'PERMIT-HW-409', type: 'HOT_WORK', title: 'Unit 3 Flare Line Welding', status: 'OPEN', expired: false);

QueryResult _result({String? alert, bool fallback = false}) => QueryResult(
      answer: 'Gas test first, per SOP-HW-01.',
      language: 'en',
      steps: const ['Isolate within 15 m', 'Gas test the area'],
      cautions: const ['Stop above 10% LEL'],
      followUps: const ['How often is the test repeated?'],
      citations: const [Citation(chunkId: 'c1', title: 'SOP-HW-01 3 Gas testing', sourceType: 'SOP', sourceId: 'SOP-HW-01', snippet: 'Gas test...')],
      verdicts: const [RuleVerdict(ruleId: 'R1', severity: 'CRITICAL', title: 'Isolation Mismatch: P-201B', status: 'OPEN', reports: 2)],
      permit: null,
      permitAlert: alert,
      confidenceNote: null,
      fallback: fallback,
      latencyMs: 2300,
    );

/// A scripted server: the search and the answer are completed by the test, in the order it chooses.
class FakeQuery extends QueryService {
  Completer<List<DocHit>> search_ = Completer();
  Completer<QueryResult> answer_ = Completer();
  String? lastPermit, lastAsset, lastUnit;
  int queries = 0;

  @override
  Future<List<PermitInfo>> permits() async => const [_permit, _live];
  @override
  Future<int> documentCount() async => 8;
  @override
  Future<List<DocHit>> search(String query, {String? permitId}) {
    lastPermit = permitId;
    return search_.future;
  }

  @override
  Future<QueryResult> query(String question, {required String unit, String? assetTag, String? permitId, String? deviceId}) {
    queries++;
    lastPermit = permitId;
    lastAsset = assetTag;
    lastUnit = unit;
    return answer_.future;
  }

  @override
  Future<DocSection> section(String chunkId) async => const DocSection(title: 'SOP-HW-01 3 Gas testing', text: 'Gas test with a calibrated monitor.', sourceType: 'SOP', docType: 'SOP');
}

const _doc = DocHit(sourceId: 'SOP-HW-01', docType: 'SOP', chunkId: 'c1', heading: '3 Gas testing', snippet: 'Gas test with a calibrated four-gas monitor.', sections: 2);

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('the documents arrive before the answer, and the answer follows', () async {
    final svc = FakeQuery();
    final vm = AskViewModel(repository: HandoverRepository(), service: svc);
    final done = vm.ask('What PPE do I need?');
    await Future.delayed(Duration.zero);
    final e = vm.entries.single;
    expect(e.searching && e.answering, true);
    svc.search_.complete([_doc]);
    await Future.delayed(Duration.zero);
    expect(e.docs.single.sourceId, 'SOP-HW-01');                    // visible within about a second
    expect(e.searching, false);
    expect(e.answering, true);                                       // still writing the answer
    svc.answer_.complete(_result());
    await done;
    expect(e.result!.steps.length, 2);
    expect(e.answering, false);
    expect(vm.followUps, ['How often is the test repeated?']);
  });

  test('the permit and equipment context travels with the question, and selecting again clears it', () async {
    final svc = FakeQuery()..search_.complete([])..answer_.complete(_result());
    final vm = AskViewModel(repository: HandoverRepository(), service: svc);
    await vm.loadContext();
    expect(vm.permits.length, 2);
    expect(vm.documentCount, 8);
    vm.selectPermit(vm.permits.first);
    vm.selectAsset('P-201B');
    expect(vm.suggestions.first, contains('this permit'));
    await vm.ask('What exactly do I need to do?');
    expect([svc.lastPermit, svc.lastAsset, svc.lastUnit], ['PERMIT-M-102', 'P-201B', 'HYDROCRACKER-01']);
    vm.selectPermit(vm.permits.first);
    expect(vm.permit, isNull);
    expect(vm.suggestions.first, contains('P-201B'));
  });

  test('a failed answer shows the reason and can be retried; a failed search does not hide the answer', () async {
    final svc = FakeQuery();
    final vm = AskViewModel(repository: HandoverRepository(), service: svc);
    final first = vm.ask('Is the pump safe to start?');
    await Future.delayed(Duration.zero);
    svc.search_.completeError(ApiException('search down'));
    svc.answer_.completeError(ApiException('No connection to the server. Check the network and try again.'));
    await first;
    final e = vm.entries.single;
    expect(e.error, contains('No connection'));
    expect(e.docs, isEmpty);
    expect(e.answering, false);
    svc
      ..search_ = Completer()
      ..answer_ = Completer();
    final again = vm.retry(e);
    svc.search_.complete([_doc]);
    svc.answer_.complete(_result());
    await again;
    expect(e.error, isNull);
    expect(e.result, isNotNull);
    expect(svc.queries, 2);
  });

  test('a one-letter question is not sent', () async {
    final svc = FakeQuery();
    final vm = AskViewModel(repository: HandoverRepository(), service: svc);
    await vm.ask(' a ');
    expect(vm.entries, isEmpty);
    expect(svc.queries, 0);
  });

  testWidgets('every state renders: empty, searching, documents, answer with steps, conflicts and an expired-permit alert', (tester) async {
    tester.view.physicalSize = const Size(1080, 2316);
    tester.view.devicePixelRatio = 2.75;
    addTearDown(tester.view.reset);
    final svc = FakeQuery();
    final vm = AskViewModel(repository: HandoverRepository(), service: svc);
    await tester.pumpWidget(MaterialApp(home: AskScreen(viewModel: vm, isOnline: true)));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('Ask'), findsOneWidget);
    expect(find.textContaining('Answers from 8 plant documents'), findsOneWidget);
    expect(find.text('PERMIT-M-102 · EXPIRED'), findsOneWidget);
    expect(find.text('Ask about a procedure, a permit or a job'), findsOneWidget);                 // empty state
    expect(tester.takeException(), isNull);

    unawaited(vm.ask('What exactly do I need to do for this permit?'));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Searching the documents…'), findsOneWidget);
    svc.search_.complete([_doc]);
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('1 matching document'), findsOneWidget);
    expect(find.text('SOP-HW-01'), findsOneWidget);
    expect(find.text('Writing the answer from those documents…'), findsOneWidget);
    expect(tester.takeException(), isNull);

    svc.answer_.complete(_result(alert: 'PERMIT-M-102 has EXPIRED. Do not start or continue this work until the permit is re-issued.'));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.textContaining('has EXPIRED'), findsOneWidget);
    expect(find.text('Open conflicts (from the safety rules)'), findsOneWidget);
    expect(find.textContaining('R1 · CRITICAL · Isolation Mismatch: P-201B (OPEN)'), findsOneWidget);
    expect(find.text('1. Isolate within 15 m'), findsOneWidget);
    expect(find.text('Stop above 10% LEL'), findsOneWidget);
    expect(find.text('SOP-HW-01 3 Gas testing'), findsOneWidget);
    expect(find.text('How often is the test repeated?'), findsOneWidget);                  // follow-up chip
    expect(find.textContaining('safe to proceed'), findsNothing);
    expect(tester.takeException(), isNull);

    await tester.ensureVisible(find.text('1. Isolate within 15 m'));
    await tester.pump();
    await tester.tap(find.text('1. Isolate within 15 m'));                                  // tick a step
    await tester.pump();
    expect(vm.entries.single.doneSteps, {0});

    await tester.ensureVisible(find.text('SOP-HW-01 3 Gas testing'));
    await tester.pump();
    await tester.tap(find.text('SOP-HW-01 3 Gas testing'));                                 // open the source in full
    await tester.pumpAndSettle();
    expect(find.text('Gas test with a calibrated monitor.'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('offline: asking is disabled and says why', (tester) async {
    tester.view.physicalSize = const Size(1080, 2316);
    tester.view.devicePixelRatio = 2.75;
    addTearDown(tester.view.reset);
    final vm = AskViewModel(repository: HandoverRepository(), service: FakeQuery());
    await tester.pumpWidget(MaterialApp(home: AskScreen(viewModel: vm, isOnline: false)));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.textContaining('You are offline'), findsOneWidget);
    expect(tester.widget<TextField>(find.byType(TextField)).enabled, false);
  });
}

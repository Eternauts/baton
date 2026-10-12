import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:aegis_flow/core/data/handover_repository.dart';
import 'package:aegis_flow/data/services/handover_interview_service.dart';
import 'package:aegis_flow/features/handover/handover_view_model.dart';
import 'package:aegis_flow/features/handover/views/handover_screen.dart';

/// A scripted server: two questions, one CRITICAL item, a gate that only opens after a read-back.
class FakeService extends HandoverInterviewService {
  bool acked = false;
  bool refuseComplete = false;

  InterviewSession _session({bool answered = false}) => InterviewSession(
        id: 'batch-1',
        status: answered ? 'READY_FOR_BRIEF' : 'NEEDS_CLARIFICATION',
        conflicts: const [
          InterviewConflict(ruleId: 'R1', title: 'Isolation Mismatch: P-201B', description: 'claims isolated, plant OPEN', severity: 'CRITICAL', status: 'OPEN'),
          InterviewConflict(ruleId: 'R1', title: 'Isolation Mismatch: P-201B', description: 'duplicate', severity: 'CRITICAL', status: 'OPEN'),
          InterviewConflict(ruleId: 'R4', title: 'Expired Permit', description: 'permit expired', severity: 'WARNING', status: 'OPEN'),
        ],
        questions: [
          InterviewQuestion(id: 'Q-1', text: 'Did you lock out P-201B?', answered: answered),
          InterviewQuestion(id: 'Q-2', text: 'Is the permit still in use?', answered: answered),
        ],
        brief: answered
            ? [
                BriefEntry(id: 'B-1', text: '[R1] mismatch', severity: 'CRITICAL', citations: const [], acknowledged: acked, acknowledgedBy: acked ? 'Rahman' : null),
                const BriefEntry(id: 'B-2', text: '[R4] permit', severity: 'WARNING', citations: [], acknowledged: false),
              ]
            : const [],
      );

  @override
  Future<InterviewSession> interview(String id, {String language = 'en'}) async => _session();
  @override
  Future<InterviewSession> session(String id) async => _session(answered: true);
  @override
  Future<InterviewSession> answer(String id, Map<String, String> answers) async {
    expect(answers.keys, containsAll(['Q-1', 'Q-2']));
    return _session(answered: true);
  }

  @override
  Future<InterviewSession> acknowledge(String id, {required String itemId, required String readback, required String supervisor}) async {
    acked = true;
    return _session(answered: true);
  }

  @override
  Future<({String message, int openConflicts, String? supervisor})> complete(String id) async {
    if (refuseComplete || !acked) throw InterviewException('Handover gated: 1 CRITICAL safety item(s) require read-back acknowledgment before transfer.', retryable: false);
    return (message: 'done', openConflicts: 2, supervisor: 'Rahman');
  }

  @override
  Future<PipelineBrief?> pipelineBrief(String id) async => null;
}

class FakeRepo extends HandoverRepository {
  @override
  Future<({String handoverId, List<dynamic> conflicts})> syncShiftForInterview() async => (handoverId: 'batch-1', conflicts: const []);
}

void main() {
  test('interview: answers gate the brief, a read-back gates the transfer, nothing is resolved', () async {
    SharedPreferences.setMockInitialValues({});
    final svc = FakeService();
    final vm = HandoverViewModel(repository: FakeRepo(), service: svc);

    await vm.start();
    expect(vm.step, HandoverStep.interview);
    expect(vm.questionCount, 2);
    expect(vm.currentConflict!.ruleId, 'R1');                       // question 1 is about the first DISTINCT conflict

    expect(vm.currentAnswered, false);
    vm.next();                                                      // an empty answer does not advance
    expect(vm.questionIndex, 0);
    vm.setAnswer('Q-1', 'Locked out at the MCC');
    vm.next();
    expect(vm.questionIndex, 1);
    expect(vm.currentConflict!.ruleId, 'R4');                       // the duplicate R1 was skipped
    vm.setAnswer('Q-2', 'ok');                                      // too short to count
    expect(vm.currentAnswered, false);
    vm.setAnswer('Q-2', 'Not checked yet');
    vm.next();                                                      // last question submits
    await Future.delayed(Duration.zero);
    await Future.delayed(Duration.zero);
    expect(vm.step, HandoverStep.brief);

    expect(vm.canComplete, false);
    expect(vm.unreadCritical, 1);
    vm.setReadback('B-1', 'ok');
    expect(vm.readbackOk('B-1'), false);                            // one word is not a read-back
    vm.setReadback('B-1', 'P-201B shows open and must be verified');
    vm.setSupervisor('');
    await vm.acknowledge('B-1');                                    // no name: nothing is sent
    expect(svc.acked, false);
    vm.setSupervisor('Rahman');
    await vm.acknowledge('B-1');
    expect(svc.acked, true);
    expect(vm.canComplete, true);

    await vm.complete();
    expect(vm.step, HandoverStep.done);
    expect(vm.result!.openConflicts, 2);                            // transferred while conflicts stay open
  });

  test('a server refusal keeps the user on the brief and shows the reason', () async {
    SharedPreferences.setMockInitialValues({});
    final svc = FakeService()..refuseComplete = true;   // the client gate opens, the server still says no
    final vm = HandoverViewModel(repository: FakeRepo(), service: svc);
    await vm.start();
    vm.setAnswer('Q-1', 'Locked out');
    vm.next();
    vm.setAnswer('Q-2', 'Not checked');
    vm.next();
    await Future.delayed(Duration.zero);
    await Future.delayed(Duration.zero);
    vm.setSupervisor('Rahman');
    vm.setReadback('B-1', 'P-201B shows open and must be verified');
    await vm.acknowledge('B-1');
    expect(vm.canComplete, true);
    await vm.complete();
    expect(vm.step, HandoverStep.brief);                           // not transferred
    expect(vm.error, contains('gated'));                           // and the server's reason is visible
    expect(vm.errorRetryable, false);
  });

  testWidgets('every step of the screen renders without a layout error', (tester) async {
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1080, 2316);
    tester.view.devicePixelRatio = 2.75;
    final svc = FakeService();
    final vm = HandoverViewModel(repository: FakeRepo(), service: svc);
    await tester.pumpWidget(MaterialApp(home: HandoverScreen(viewModel: vm, isOnline: true)));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('Shift handover'), findsOneWidget);                         // start
    expect(tester.takeException(), isNull);

    await tester.runAsync(() => vm.start());
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('Question 1 of 2'), findsOneWidget);                       // interview
    expect(find.textContaining('Isolation Mismatch'), findsWidgets);
    expect(tester.takeException(), isNull);

    vm.setAnswer('Q-1', 'Locked out at the MCC');
    vm.next();
    vm.setAnswer('Q-2', 'Not checked yet');
    await tester.runAsync(() async {
      vm.next();
      await Future.delayed(const Duration(milliseconds: 50));
    });
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('Handover brief'), findsOneWidget);                        // brief: cards, read-back field, locked transfer
    expect(find.text('Confirm read-back'), findsOneWidget);
    expect(tester.takeException(), isNull);
    final transfer = tester.widget<ElevatedButton>(find.widgetWithText(ElevatedButton, 'Transfer handover'));
    expect(transfer.onPressed, isNull);                                         // locked until the read-back

    vm.setSupervisor('Rahman');
    vm.setReadback('B-1', 'P-201B shows open and must be verified');
    await tester.runAsync(() => vm.acknowledge('B-1'));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.textContaining('Read back by Rahman'), findsOneWidget);
    expect(tester.widget<ElevatedButton>(find.widgetWithText(ElevatedButton, 'Transfer handover')).onPressed, isNotNull);

    await tester.runAsync(() => vm.complete());
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('Handover transferred'), findsOneWidget);                  // done
    expect(find.textContaining('remain'), findsWidgets);                        // says conflicts stay open
    expect(find.textContaining('resolved'), findsNothing);
    expect(tester.takeException(), isNull);
    addTearDown(tester.view.reset);
  });
}

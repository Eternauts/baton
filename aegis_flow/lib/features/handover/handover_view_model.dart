import 'dart:async';
import 'package:flutter/material.dart';
import '../../core/data/handover_repository.dart';
import '../../core/data/observation_capsule.dart';
import '../../data/services/handover_interview_service.dart';

enum HandoverStep { intro, starting, interview, submitting, brief, completing, done }

/// The interview-based shift handover: the outgoing operator answers one question per open conflict, the
/// incoming supervisor reads back every CRITICAL item, and only then can the handover be transferred.
/// Every verdict comes from the server's rules. Nothing here clears, acknowledges or resolves a conflict.
class HandoverViewModel extends ChangeNotifier {
  final HandoverRepository _repository;
  final HandoverInterviewService _service;

  HandoverViewModel({required HandoverRepository repository, HandoverInterviewService? service})
      : _repository = repository,
        _service = service ?? HandoverInterviewService();

  HandoverStep _step = HandoverStep.intro;
  HandoverStep get step => _step;

  List<ObservationCapsule> _shift = [];
  int get shiftCount => _shift.length;
  int get shiftPending => _shift.where((c) => !c.isSynced).length;
  int get shiftAlerts => _shift.where((c) => c.escalation.level > 0 || c.discrepancyAlert != null || c.serverFlags.isNotEmpty).length;

  InterviewSession? _session;
  InterviewSession? get session => _session;
  String? get handoverId => _session?.id;

  final Map<String, String> answers = {};
  int _q = 0;
  int get questionIndex => _q;
  InterviewQuestion? get currentQuestion => (_session != null && _q < _session!.questions.length) ? _session!.questions[_q] : null;
  int get questionCount => _session?.questions.length ?? 0;
  /// The conflict a question is about: questions are generated one per distinct conflict, in order.
  InterviewConflict? get currentConflict {
    final s = _session;
    if (s == null) return null;
    final distinct = <String>{};
    final list = <InterviewConflict>[];
    for (final c in s.conflicts) {
      if (distinct.add('${c.ruleId}|${c.title}')) list.add(c);
    }
    return _q < list.length ? list[_q] : null;
  }

  String supervisor = '';
  final Map<String, String> readbacks = {};
  String? _ackingItem;
  String? get ackingItem => _ackingItem;

  PipelineBrief? _pipelineBrief;
  PipelineBrief? get pipelineBrief => _pipelineBrief;
  bool _briefPolling = false;
  bool get briefPolling => _briefPolling;

  String? _error;
  String? get error => _error;
  bool _errorRetryable = true;
  bool get errorRetryable => _errorRetryable;
  void clearError() {
    _error = null;
    notifyListeners();
  }

  ({String message, int openConflicts, String? supervisor})? _result;
  ({String message, int openConflicts, String? supervisor})? get result => _result;

  bool _disposed = false;

  /// Loads this shift's summary for the start screen.
  Future<void> loadShift() async {
    _shift = await _repository.shiftCapsules();
    if (!_disposed) notifyListeners();
  }

  void _fail(Object e) {
    _error = e is InterviewException ? e.message : e.toString().replaceFirst('Exception: ', '');
    _errorRetryable = e is InterviewException ? e.retryable : true;
  }

  Future<void> start() async {
    _error = null;
    _step = HandoverStep.starting;
    notifyListeners();
    try {
      final sent = await _repository.syncShiftForInterview();
      var s = await _service.interview(sent.handoverId);
      answers.clear();
      readbacks.clear();
      _q = 0;
      _session = s;
      _result = null;
      if (s.questions.isEmpty || s.questions.every((q) => q.answered)) {
        // Nothing to ask (no open conflicts): go straight to the brief.
        s = await _service.session(s.id);
        _session = s;
        _step = HandoverStep.brief;
        _pollBrief();
      } else {
        _step = HandoverStep.interview;
      }
    } catch (e) {
      _fail(e);
      _step = HandoverStep.intro;
    }
    if (!_disposed) notifyListeners();
  }

  String answerFor(String questionId) => answers[questionId] ?? '';

  void setAnswer(String questionId, String text) {
    answers[questionId] = text;
    notifyListeners();
  }

  bool get currentAnswered => currentQuestion != null && answerFor(currentQuestion!.id).trim().length >= 3;
  bool get isLastQuestion => _q >= questionCount - 1;

  void back() {
    if (_q > 0) {
      _q--;
      notifyListeners();
    }
  }

  void next() {
    if (!currentAnswered) return;
    if (!isLastQuestion) {
      _q++;
      notifyListeners();
    } else {
      submitAnswers();
    }
  }

  Future<void> submitAnswers() async {
    final s = _session;
    if (s == null) return;
    _error = null;
    _step = HandoverStep.submitting;
    notifyListeners();
    try {
      final updated = await _service.answer(s.id, {for (final q in s.questions) q.id: answerFor(q.id).trim()});
      _session = updated;
      if (updated.brief.isEmpty) throw InterviewException('The server did not release the brief. Answer every question and try again.');
      _step = HandoverStep.brief;
      _pollBrief();
    } catch (e) {
      _fail(e);
      _step = HandoverStep.interview;
    }
    if (!_disposed) notifyListeners();
  }

  /// The pipeline's cited brief arrives 10 to 20 s after the sync: look every 3 s for up to 60 s, quietly.
  Future<void> _pollBrief() async {
    final id = _session?.id;
    if (id == null || _briefPolling) return;
    _briefPolling = true;
    notifyListeners();
    for (var i = 0; i < 20 && !_disposed; i++) {
      try {
        final b = await _service.pipelineBrief(id);
        if (b != null) {
          _pipelineBrief = b;
          break;
        }
      } catch (_) {
        // the AI brief is an extra: the rule items below stay usable without it
      }
      await Future.delayed(const Duration(seconds: 3));
      if (_step != HandoverStep.brief) break;
    }
    _briefPolling = false;
    if (!_disposed) notifyListeners();
  }

  List<BriefEntry> get criticalItems => (_session?.brief ?? const <BriefEntry>[]).where((b) => b.isCritical).toList();
  int get unreadCritical => criticalItems.where((b) => !b.acknowledged).length;
  bool get canComplete => _session != null && unreadCritical == 0 && (_session?.brief.isNotEmpty ?? false);
  bool get supervisorNamed => supervisor.trim().isNotEmpty;

  void setSupervisor(String name) {
    supervisor = name;
    notifyListeners();
  }

  void setReadback(String itemId, String text) {
    readbacks[itemId] = text;
    notifyListeners();
  }

  bool readbackOk(String itemId) => (readbacks[itemId] ?? '').trim().split(RegExp(r'\s+')).where((w) => w.isNotEmpty).length >= 3;

  Future<void> acknowledge(String itemId) async {
    final s = _session;
    if (s == null || _ackingItem != null) return;
    if (!supervisorNamed || !readbackOk(itemId)) return;
    _error = null;
    _ackingItem = itemId;
    notifyListeners();
    try {
      _session = await _service.acknowledge(s.id, itemId: itemId, readback: readbacks[itemId]!.trim(), supervisor: supervisor.trim());
    } catch (e) {
      _fail(e);
    }
    _ackingItem = null;
    if (!_disposed) notifyListeners();
  }

  Future<void> complete() async {
    final s = _session;
    if (s == null || !canComplete) return;
    _error = null;
    _step = HandoverStep.completing;
    notifyListeners();
    try {
      _result = await _service.complete(s.id);
      _step = HandoverStep.done;
    } catch (e) {
      _fail(e); // for example the server's 409: it lists what is still unread
      _step = HandoverStep.brief;
      try {
        _session = await _service.session(s.id);
      } catch (_) {}
    }
    if (!_disposed) notifyListeners();
  }

  void restart() {
    _session = null;
    answers.clear();
    readbacks.clear();
    supervisor = '';
    _pipelineBrief = null;
    _result = null;
    _error = null;
    _q = 0;
    _step = HandoverStep.intro;
    loadShift();
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}

import 'package:flutter/material.dart';
import 'package:intl/intl.dart' hide TextDirection;
import '../../../data/services/handover_interview_service.dart';
import '../../../ui/core/theme.dart';
import '../../../ui/core/widgets/baton_logo.dart';
import '../handover_view_model.dart';

class HandoverScreen extends StatefulWidget {
  final HandoverViewModel viewModel;
  final bool isOnline;

  const HandoverScreen({super.key, required this.viewModel, required this.isOnline});

  @override
  State<HandoverScreen> createState() => _HandoverScreenState();
}

class _HandoverScreenState extends State<HandoverScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => widget.viewModel.loadShift());
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.viewModel,
      builder: (context, _) {
        final vm = widget.viewModel;
        final Widget body;
        switch (vm.step) {
          case HandoverStep.intro:
            body = _Intro(vm: vm, isOnline: widget.isOnline);
          case HandoverStep.starting:
            body = const _Busy(label: 'Checking this shift against the plant…', detail: 'Sending your reports and running the safety rules.');
          case HandoverStep.interview:
            body = _Interview(vm: vm);
          case HandoverStep.submitting:
            body = const _Busy(label: 'Saving your answers…', detail: 'Preparing the brief for the incoming supervisor.');
          case HandoverStep.brief:
            body = _Brief(vm: vm);
          case HandoverStep.completing:
            body = const _Busy(label: 'Transferring the handover…', detail: 'Recording who read each critical item back.');
          case HandoverStep.done:
            body = _Done(vm: vm);
        }
        return Scaffold(
          backgroundColor: AegisTheme.background,
          body: SafeArea(child: AnimatedSwitcher(duration: const Duration(milliseconds: 220), child: KeyedSubtree(key: ValueKey(vm.step), child: body))),
        );
      },
    );
  }
}

// ---------------------------------------------------------------- shared bits

class _Busy extends StatelessWidget {
  final String label;
  final String detail;
  const _Busy({required this.label, required this.detail});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 32),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const BatonLoader(height: 84),
          const SizedBox(height: 24),
          Text(label, textAlign: TextAlign.center, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: AegisTheme.textPrimary)),
          const SizedBox(height: 8),
          Text(detail, textAlign: TextAlign.center, style: const TextStyle(fontSize: 13, height: 1.35, color: AegisTheme.textSecondary)),
        ]),
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  final String message;
  final VoidCallback onDismiss;
  const _ErrorBanner({required this.message, required this.onDismiss});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      child: Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.fromLTRB(12, 10, 4, 10),
        decoration: BoxDecoration(
          color: AegisTheme.alertRed.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AegisTheme.alertRed.withValues(alpha: 0.5)),
        ),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Icon(Icons.error_outline, size: 18, color: AegisTheme.alertRed),
          const SizedBox(width: 8),
          Expanded(child: Text(message, style: const TextStyle(fontSize: 13, height: 1.3, color: AegisTheme.textPrimary))),
          IconButton(onPressed: onDismiss, icon: const Icon(Icons.close, size: 18, color: AegisTheme.textMuted), tooltip: 'Dismiss'),
        ]),
      ),
    );
  }
}

Widget _sevChip(String severity, {String? label}) {
  final c = severity == 'CRITICAL' ? AegisTheme.alertRed : (severity == 'WARNING' ? AegisTheme.amberAccent : AegisTheme.textSecondary);
  final icon = severity == 'CRITICAL' ? Icons.error : (severity == 'WARNING' ? Icons.warning_amber_rounded : Icons.info_outline);
  return Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
    decoration: BoxDecoration(color: c.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(8), border: Border.all(color: c.withValues(alpha: 0.5))),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(icon, size: 12, color: c),
      const SizedBox(width: 4),
      Text(label ?? severity, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: c)),
    ]),
  );
}

// ---------------------------------------------------------------- start

class _Intro extends StatelessWidget {
  final HandoverViewModel vm;
  final bool isOnline;
  const _Intro({required this.vm, required this.isOnline});

  Widget _stat(String value, String label, {Color color = AegisTheme.textPrimary}) => Expanded(
        child: Column(children: [
          Text(value, style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold, color: color)),
          const SizedBox(height: 2),
          Text(label, textAlign: TextAlign.center, style: const TextStyle(fontSize: 11, color: AegisTheme.textMuted)),
        ]),
      );

  Widget _step(int n, String text) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(
            width: 24,
            height: 24,
            alignment: Alignment.center,
            decoration: BoxDecoration(shape: BoxShape.circle, color: AegisTheme.amberAccent.withValues(alpha: 0.18)),
            child: Text('$n', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: AegisTheme.amberAccent)),
          ),
          const SizedBox(width: 12),
          Expanded(child: Text(text, style: const TextStyle(fontSize: 14, height: 1.35, color: AegisTheme.textSecondary))),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final empty = vm.shiftCount == 0;
    final blocked = !isOnline || empty;
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 24),
      children: [
        const Text('Shift handover', style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: AegisTheme.textPrimary)),
        const SizedBox(height: 6),
        const Text('Hand this shift over safely: answer a few questions, then the incoming supervisor reads the critical items back.',
            style: TextStyle(fontSize: 14, height: 1.4, color: AegisTheme.textSecondary)),
        const SizedBox(height: 20),
        if (vm.error != null) _ErrorBanner(message: vm.error!, onDismiss: vm.clearError),
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(color: AegisTheme.surfaceVariant, borderRadius: BorderRadius.circular(16)),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _stat('${vm.shiftCount}', 'reports\nthis shift'),
            _stat('${vm.shiftAlerts}', 'alerts', color: vm.shiftAlerts > 0 ? AegisTheme.amberAccent : AegisTheme.textPrimary),
            _stat('${vm.shiftPending}', 'waiting\nto sync', color: vm.shiftPending > 0 ? AegisTheme.amberAccent : AegisTheme.textPrimary),
          ]),
        ),
        const SizedBox(height: 24),
        _step(1, 'The server checks your reports against the plant and asks one question for each open conflict.'),
        _step(2, 'You answer from what you saw. Your answers never change a safety verdict.'),
        _step(3, 'The incoming supervisor reads back every CRITICAL item in their own words, then takes over.'),
        const SizedBox(height: 4),
        const Text('Open conflicts stay open after the handover until someone verifies them in the field.',
            style: TextStyle(fontSize: 12, height: 1.35, color: AegisTheme.textMuted)),
        const SizedBox(height: 24),
        ElevatedButton(onPressed: blocked ? null : vm.start, child: const Text('Start handover interview')),
        if (blocked) ...[
          const SizedBox(height: 10),
          Row(children: [
            Icon(!isOnline ? Icons.cloud_off : Icons.mic_none_rounded, size: 14, color: AegisTheme.amberAccent),
            const SizedBox(width: 6),
            Expanded(
              child: Text(!isOnline ? 'You are offline. The interview needs a connection; your reports stay saved on this device.' : 'Record at least one report first, on the Report tab.',
                  style: const TextStyle(fontSize: 12, color: AegisTheme.amberAccent)),
            ),
          ]),
        ],
      ],
    );
  }
}

// ---------------------------------------------------------------- interview

class _Interview extends StatefulWidget {
  final HandoverViewModel vm;
  const _Interview({required this.vm});

  @override
  State<_Interview> createState() => _InterviewState();
}

class _InterviewState extends State<_Interview> {
  late final TextEditingController _c = TextEditingController();
  String? _loadedFor;

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  void _syncController(HandoverViewModel vm) {
    final q = vm.currentQuestion;
    if (q != null && _loadedFor != q.id) {
      _loadedFor = q.id;
      _c.text = vm.answerFor(q.id);
      _c.selection = TextSelection.collapsed(offset: _c.text.length);
    }
  }

  @override
  Widget build(BuildContext context) {
    final vm = widget.vm;
    _syncController(vm);
    final q = vm.currentQuestion;
    final conflict = vm.currentConflict;
    if (q == null) return const SizedBox.shrink();
    final n = vm.questionIndex + 1, total = vm.questionCount;
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 0),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Question $n of $total', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AegisTheme.textMuted)),
          const SizedBox(height: 8),
          ClipRRect(borderRadius: BorderRadius.circular(4), child: LinearProgressIndicator(value: n / total, minHeight: 5, backgroundColor: AegisTheme.surfaceVariant, color: AegisTheme.amberAccent)),
        ]),
      ),
      Expanded(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 16),
          children: [
            if (vm.error != null) _ErrorBanner(message: vm.error!, onDismiss: vm.clearError),
            if (conflict != null)
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: AegisTheme.surfaceVariant,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: (conflict.severity == 'CRITICAL' ? AegisTheme.alertRed : AegisTheme.amberAccent).withValues(alpha: 0.5)),
                ),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [_sevChip(conflict.severity, label: '${conflict.ruleId} · ${conflict.severity}'), const SizedBox(width: 8), Text(conflict.status, style: const TextStyle(fontSize: 11, color: AegisTheme.textMuted))]),
                  const SizedBox(height: 8),
                  Text(conflict.title, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: AegisTheme.textPrimary)),
                  const SizedBox(height: 6),
                  Text(conflict.description, maxLines: 6, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12, height: 1.35, color: AegisTheme.textSecondary)),
                ]),
              ),
            const SizedBox(height: 20),
            Semantics(header: true, child: Text(q.text, style: const TextStyle(fontSize: 19, height: 1.3, fontWeight: FontWeight.w700, color: AegisTheme.textPrimary))),
            const SizedBox(height: 16),
            TextField(
              controller: _c,
              minLines: 3,
              maxLines: 6,
              maxLength: 500,
              textCapitalization: TextCapitalization.sentences,
              style: const TextStyle(fontSize: 16, color: AegisTheme.textPrimary),
              decoration: const InputDecoration(hintText: 'What did you see or do, and who checked it?'),
              onChanged: (t) => vm.setAnswer(q.id, t),
            ),
            const SizedBox(height: 8),
            Wrap(spacing: 8, runSpacing: 8, children: [
              for (final s in const ['Not checked yet', 'Confirmed in the field', 'I do not know'])
                ActionChip(
                  label: Text(s, style: const TextStyle(fontSize: 12, color: AegisTheme.textPrimary)),
                  backgroundColor: AegisTheme.surface,
                  side: const BorderSide(color: AegisTheme.cardBorder),
                  onPressed: () {
                    _c.text = s;
                    _c.selection = TextSelection.collapsed(offset: s.length);
                    vm.setAnswer(q.id, s);
                  },
                ),
            ]),
            const SizedBox(height: 4),
            const Text('An honest "not checked" is better than a guess: the incoming shift will see it.', style: TextStyle(fontSize: 12, color: AegisTheme.textMuted)),
          ],
        ),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
        child: Row(children: [
          if (vm.questionIndex > 0) ...[
            OutlinedButton(
              onPressed: vm.back,
              style: OutlinedButton.styleFrom(minimumSize: const Size(96, 56), side: const BorderSide(color: AegisTheme.cardBorder), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16))),
              child: const Text('Back', style: TextStyle(color: AegisTheme.textPrimary)),
            ),
            const SizedBox(width: 12),
          ],
          Expanded(child: ElevatedButton(onPressed: vm.currentAnswered ? vm.next : null, child: Text(vm.isLastQuestion ? 'Review the brief' : 'Next question'))),
        ]),
      ),
    ]);
  }
}

// ---------------------------------------------------------------- brief and read-back

class _Brief extends StatelessWidget {
  final HandoverViewModel vm;
  const _Brief({required this.vm});

  @override
  Widget build(BuildContext context) {
    final s = vm.session!;
    return Column(children: [
      Expanded(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 20, 20, 16),
          children: [
            const Text('Handover brief', style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: AegisTheme.textPrimary)),
            const SizedBox(height: 4),
            const Text('For the incoming supervisor. Read every CRITICAL item back in your own words.', style: TextStyle(fontSize: 14, height: 1.35, color: AegisTheme.textSecondary)),
            const SizedBox(height: 16),
            if (vm.error != null) _ErrorBanner(message: vm.error!, onDismiss: vm.clearError),
            _AiBrief(vm: vm),
            const SizedBox(height: 16),
            _SyncedField(
              text: vm.supervisor,
              textCapitalization: TextCapitalization.words,
              style: const TextStyle(fontSize: 16, color: AegisTheme.textPrimary),
              decoration: const InputDecoration(labelText: 'Incoming supervisor (your name)', hintText: 'Required to read an item back', fillColor: AegisTheme.surfaceVariant),
              onChanged: vm.setSupervisor,
            ),
            const SizedBox(height: 16),
            for (final item in s.brief.where((b) => b.severity != 'INFO')) _BriefCard(vm: vm, item: item),
            if (s.brief.any((b) => b.severity == 'INFO'))
              Theme(
                data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                child: ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  childrenPadding: EdgeInsets.zero,
                  iconColor: AegisTheme.textMuted,
                  collapsedIconColor: AegisTheme.textMuted,
                  title: Text('Supporting facts (${s.brief.where((b) => b.severity == 'INFO').length})', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: AegisTheme.textSecondary)),
                  children: [for (final item in s.brief.where((b) => b.severity == 'INFO')) _BriefCard(vm: vm, item: item)],
                ),
              ),
          ],
        ),
      ),
      Container(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 16),
        decoration: const BoxDecoration(color: AegisTheme.surface, border: Border(top: BorderSide(color: AegisTheme.cardBorder))),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          if (!vm.canComplete)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Row(children: [
                const Icon(Icons.lock_outline, size: 14, color: AegisTheme.amberAccent),
                const SizedBox(width: 6),
                Expanded(child: Text('${vm.unreadCritical} critical item${vm.unreadCritical == 1 ? ' still needs' : 's still need'} a read-back before the handover can be transferred.', style: const TextStyle(fontSize: 12, color: AegisTheme.amberAccent))),
              ]),
            ),
          ElevatedButton(onPressed: vm.canComplete ? vm.complete : null, child: const Text('Transfer handover')),
        ]),
      ),
    ]);
  }
}

class _AiBrief extends StatelessWidget {
  final HandoverViewModel vm;
  const _AiBrief({required this.vm});

  @override
  Widget build(BuildContext context) {
    final b = vm.pipelineBrief;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: AegisTheme.surfaceVariant, borderRadius: BorderRadius.circular(14), border: Border.all(color: AegisTheme.cardBorder)),
      child: b == null
          ? Row(children: [
              if (vm.briefPolling) const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: AegisTheme.amberAccent)) else const Icon(Icons.auto_awesome, size: 16, color: AegisTheme.textMuted),
              const SizedBox(width: 10),
              Expanded(child: Text(vm.briefPolling ? 'Preparing the cited AI brief… the rule items below are already final.' : 'The AI brief is not ready. The rule items below are complete without it.', style: const TextStyle(fontSize: 12, height: 1.3, color: AegisTheme.textSecondary))),
            ])
          : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                const Icon(Icons.auto_awesome, size: 14, color: AegisTheme.amberAccent),
                const SizedBox(width: 6),
                Text('AI brief · ${b.citationCount} cited source${b.citationCount == 1 ? '' : 's'}${b.guardrailStatus.isEmpty ? '' : ' · checks ${b.guardrailStatus}'}', style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: AegisTheme.amberAccent)),
              ]),
              const SizedBox(height: 8),
              Text(b.headline, style: const TextStyle(fontSize: 14, height: 1.35, color: AegisTheme.textPrimary)),
            ]),
    );
  }
}

class _BriefCard extends StatelessWidget {
  final HandoverViewModel vm;
  final BriefEntry item;
  const _BriefCard({required this.vm, required this.item});

  @override
  Widget build(BuildContext context) {
    final critical = item.isCritical;
    final done = item.acknowledged;
    final color = critical ? AegisTheme.alertRed : (item.severity == 'WARNING' ? AegisTheme.amberAccent : AegisTheme.textMuted);
    final when = item.acknowledgedAt != null ? DateTime.tryParse(item.acknowledgedAt!)?.toLocal() : null;
    final busy = vm.ackingItem == item.id;
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(color: AegisTheme.surfaceVariant, borderRadius: BorderRadius.circular(14)),
      clipBehavior: Clip.antiAlias,
      child: IntrinsicHeight(
        child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Container(width: 4, color: color),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  _sevChip(item.severity),
                  if (item.citations.isNotEmpty) ...[const SizedBox(width: 8), Text('${item.citations.length} source${item.citations.length == 1 ? '' : 's'}', style: const TextStyle(fontSize: 11, color: AegisTheme.textMuted))],
                ]),
                const SizedBox(height: 8),
                _CollapsibleText(item.text),
                if (critical && done) ...[
                  const SizedBox(height: 10),
                  Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    const Icon(Icons.check_circle, size: 16, color: AegisTheme.successGreen),
                    const SizedBox(width: 6),
                    Expanded(child: Text('Read back by ${item.acknowledgedBy ?? 'supervisor'}${when != null ? ' at ${DateFormat('HH:mm').format(when)}' : ''}', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: AegisTheme.successGreen))),
                  ]),
                  if ((item.readback ?? '').isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4, left: 22), child: Text('"${item.readback}"', style: const TextStyle(fontSize: 12, fontStyle: FontStyle.italic, color: AegisTheme.textSecondary))),
                ],
                if (critical && !done) ...[
                  const SizedBox(height: 12),
                  _SyncedField(
                    key: ValueKey('rb-${item.id}'),
                    text: vm.readbacks[item.id] ?? '',
                    minLines: 2,
                    maxLines: 4,
                    style: const TextStyle(fontSize: 14, color: AegisTheme.textPrimary),
                    decoration: const InputDecoration(hintText: 'Say it back in your own words', fillColor: AegisTheme.background, contentPadding: EdgeInsets.symmetric(horizontal: 14, vertical: 12)),
                    onChanged: (t) => vm.setReadback(item.id, t),
                  ),
                  const SizedBox(height: 10),
                  Builder(builder: (context) {
                    final enabled = !busy && vm.supervisorNamed && vm.readbackOk(item.id);
                    final c = enabled ? color : AegisTheme.textMuted;
                    return OutlinedButton.icon(
                      onPressed: enabled ? () => vm.acknowledge(item.id) : null,
                      style: OutlinedButton.styleFrom(minimumSize: const Size(0, 46), side: BorderSide(color: enabled ? color.withValues(alpha: 0.8) : AegisTheme.cardBorder)),
                      icon: busy ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: AegisTheme.amberAccent)) : Icon(Icons.record_voice_over_outlined, size: 18, color: c),
                      label: Text(busy ? 'Recording…' : 'Confirm read-back', style: TextStyle(color: c)),
                    );
                  }),
                  if (!vm.readbackOk(item.id) && vm.supervisorNamed) const Padding(padding: EdgeInsets.only(top: 6), child: Text('Say it back in at least three words.', style: TextStyle(fontSize: 11, color: AegisTheme.textMuted))),
                  if (!vm.supervisorNamed) const Padding(padding: EdgeInsets.only(top: 6), child: Text('Enter your name above first.', style: TextStyle(fontSize: 11, color: AegisTheme.textMuted))),
                ],
              ]),
            ),
          ),
        ]),
      ),
    );
  }
}

// ---------------------------------------------------------------- done

class _Done extends StatelessWidget {
  final HandoverViewModel vm;
  const _Done({required this.vm});

  @override
  Widget build(BuildContext context) {
    final r = vm.result;
    final open = r?.openConflicts ?? 0;
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 28),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Container(width: 96, height: 96, decoration: const BoxDecoration(shape: BoxShape.circle, color: AegisTheme.successGreen), child: const Icon(Icons.check, size: 52, color: Colors.white)),
          const SizedBox(height: 24),
          const Text('Handover transferred', style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: AegisTheme.textPrimary)),
          const SizedBox(height: 8),
          Text('Responsibility passed to ${r?.supervisor ?? 'the incoming supervisor'}.', textAlign: TextAlign.center, style: const TextStyle(fontSize: 14, color: AegisTheme.textSecondary)),
          if (open > 0) ...[
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: AegisTheme.amberAccent.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(12), border: Border.all(color: AegisTheme.amberAccent.withValues(alpha: 0.5))),
              child: Text('$open conflict${open == 1 ? '' : 's'} remain${open == 1 ? 's' : ''} OPEN. Transferring a handover does not resolve them: they must be verified in the field.', textAlign: TextAlign.center, style: const TextStyle(fontSize: 13, height: 1.35, color: AegisTheme.amberAccent)),
            ),
          ],
          const SizedBox(height: 28),
          OutlinedButton(onPressed: vm.restart, style: OutlinedButton.styleFrom(minimumSize: const Size(200, 52), side: const BorderSide(color: AegisTheme.cardBorder)), child: const Text('Done', style: TextStyle(color: AegisTheme.textPrimary))),
        ]),
      ),
    );
  }
}

/// A text field that owns its controller and only rewrites it when the model's text really differs from
/// what is typed, so rebuilding the screen never resets the cursor or an input method's composing text.
class _SyncedField extends StatefulWidget {
  final String text;
  final ValueChanged<String> onChanged;
  final InputDecoration decoration;
  final TextStyle? style;
  final TextCapitalization textCapitalization;
  final int minLines;
  final int maxLines;

  const _SyncedField({
    super.key,
    required this.text,
    required this.onChanged,
    required this.decoration,
    this.style,
    this.textCapitalization = TextCapitalization.none,
    this.minLines = 1,
    this.maxLines = 1,
  });

  @override
  State<_SyncedField> createState() => _SyncedFieldState();
}

class _SyncedFieldState extends State<_SyncedField> {
  late final TextEditingController _c = TextEditingController(text: widget.text);

  @override
  void didUpdateWidget(covariant _SyncedField old) {
    super.didUpdateWidget(old);
    if (widget.text != _c.text) {
      _c.value = TextEditingValue(text: widget.text, selection: TextSelection.collapsed(offset: widget.text.length));
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: _c,
      minLines: widget.minLines,
      maxLines: widget.maxLines,
      textCapitalization: widget.textCapitalization,
      style: widget.style,
      decoration: widget.decoration,
      onChanged: widget.onChanged,
    );
  }
}

/// Long rule text shows three lines and expands on tap, so a brief with several items stays scannable.
/// Whether it needs the toggle is decided by length, not by measuring: a measuring widget cannot live inside
/// the card's IntrinsicHeight.
class _CollapsibleText extends StatefulWidget {
  final String text;
  const _CollapsibleText(this.text);

  @override
  State<_CollapsibleText> createState() => _CollapsibleTextState();
}

class _CollapsibleTextState extends State<_CollapsibleText> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    const style = TextStyle(fontSize: 13, height: 1.35, color: AegisTheme.textPrimary);
    final long = widget.text.length > 120;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(widget.text, maxLines: (_open || !long) ? null : 3, overflow: (_open || !long) ? TextOverflow.visible : TextOverflow.ellipsis, style: style),
      if (long)
        InkWell(
          onTap: () => setState(() => _open = !_open),
          child: Padding(padding: const EdgeInsets.symmetric(vertical: 6), child: Text(_open ? 'Show less' : 'Show more', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AegisTheme.amberAccent))),
        ),
    ]);
  }
}

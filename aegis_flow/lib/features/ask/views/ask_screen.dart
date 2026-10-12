import 'package:flutter/material.dart';
import '../../../data/services/query_service.dart';
import '../../../ui/core/theme.dart';
import '../../../ui/core/widgets/baton_logo.dart';
import '../ask_view_model.dart';

/// Query mode: ask the plant's documents a question on the spot, optionally while working under a permit.
class AskScreen extends StatefulWidget {
  final AskViewModel viewModel;
  final bool isOnline;
  const AskScreen({super.key, required this.viewModel, required this.isOnline});

  @override
  State<AskScreen> createState() => _AskScreenState();
}

class _AskScreenState extends State<AskScreen> {
  final _text = TextEditingController();
  final _scroll = ScrollController();
  int _lastCount = 0;
  String? _scrolledFor; // the entry whose answer we already scrolled to
  final Map<String, GlobalKey> _keys = {};

  AskViewModel get vm => widget.viewModel;

  @override
  void initState() {
    super.initState();
    vm.onTranscript = (t) => _text.text = t;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (widget.isOnline) vm.loadContext();
    });
  }

  @override
  void didUpdateWidget(covariant AskScreen old) {
    super.didUpdateWidget(old);
    if (widget.isOnline && !old.isOnline) vm.loadContext(force: true);
  }

  @override
  void dispose() {
    vm.onTranscript = null;
    _text.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _send([String? preset]) {
    final q = (preset ?? _text.text).trim();
    if (q.length < 2 || !widget.isOnline) return;
    FocusScope.of(context).unfocus();
    _text.clear();
    vm.ask(q);
  }

  void _showFromTop(String id) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final ctx = _keys[id]?.currentContext;
      if (ctx != null) Scrollable.ensureVisible(ctx, duration: const Duration(milliseconds: 300), curve: Curves.easeOut, alignment: 0);
    });
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) _scroll.animateTo(_scroll.position.maxScrollExtent, duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
    });
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: vm,
      builder: (context, _) {
        if (vm.entries.length != _lastCount) {
          _lastCount = vm.entries.length;
          _scrollToEnd(); // a new question: show it and the search starting
        }
        final last = vm.entries.isEmpty ? null : vm.entries.last;
        if (last != null && last.result != null && _scrolledFor != last.id) {
          _scrolledFor = last.id;
          _showFromTop(last.id); // the answer is long: start at its beginning, not at its end
        }
        return Scaffold(
          backgroundColor: AegisTheme.background,
          body: SafeArea(
            child: Column(children: [
              _Header(vm: vm),
              Expanded(child: vm.entries.isEmpty ? _Empty(vm: vm, onPick: _send) : _Conversation(vm: vm, controller: _scroll, keys: _keys)),
              if (vm.followUps.isNotEmpty && !(vm.entries.last.answering))
                SizedBox(
                  height: 44,
                  child: ListView(
                    scrollDirection: Axis.horizontal,
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    children: [for (final f in vm.followUps) Padding(padding: const EdgeInsets.only(right: 8), child: _chip(f, () => _send(f)))],
                  ),
                ),
              _InputBar(vm: vm, controller: _text, isOnline: widget.isOnline, onSend: _send),
            ]),
          ),
        );
      },
    );
  }
}

Widget _chip(String label, VoidCallback onTap, {bool selected = false, IconData? icon}) {
  return Semantics(
    button: true,
    selected: selected,
    child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(20),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: selected ? AegisTheme.amberAccent : AegisTheme.surfaceVariant,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: selected ? AegisTheme.amberAccent : AegisTheme.cardBorder),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (icon != null) ...[Icon(icon, size: 14, color: selected ? Colors.black : AegisTheme.textSecondary), const SizedBox(width: 6)],
          Flexible(child: Text(label, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: selected ? Colors.black : AegisTheme.textPrimary))),
        ]),
      ),
    ),
  );
}

// ---------------------------------------------------------------- header: what am I working on

class _Header extends StatefulWidget {
  final AskViewModel vm;
  const _Header({required this.vm});

  @override
  State<_Header> createState() => _HeaderState();
}

class _HeaderState extends State<_Header> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    final vm = widget.vm;
    // The full picker shows before the first question (and on request); after that, one line says what the questions are about.
    final full = vm.entries.isEmpty || _open;
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 10),
      decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: AegisTheme.cardBorder))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Text('Ask', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: AegisTheme.textPrimary)),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              vm.documentCount > 0 ? 'Answers from ${vm.documentCount} plant documents' : 'Answers from your plant documents',
              style: const TextStyle(fontSize: 12, color: AegisTheme.textMuted),
            ),
          ),
          if (vm.entries.isNotEmpty)
            TextButton.icon(
              onPressed: () => setState(() => _open = !_open),
              icon: Icon(_open ? Icons.expand_less : Icons.tune, size: 16, color: AegisTheme.amberAccent),
              label: Text(_open ? 'Hide' : 'Context', style: const TextStyle(fontSize: 12, color: AegisTheme.amberAccent)),
            ),
        ]),
        if (!full)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(
              vm.permit == null && vm.asset == null ? 'No permit or equipment selected' : 'Working on: ${[if (vm.permit != null) vm.permit!.id, if (vm.asset != null) vm.asset!].join(' · ')}',
              style: const TextStyle(fontSize: 12, color: AegisTheme.textSecondary),
            ),
          )
        else ...[
          if (vm.permits.isNotEmpty) ...[
            const SizedBox(height: 10),
            const Text('Working under a permit?', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: AegisTheme.textMuted)),
            const SizedBox(height: 6),
            Wrap(spacing: 8, runSpacing: 8, children: [
              for (final p in vm.permits)
                _chip('${p.id}${p.expired ? ' · EXPIRED' : ''}', () => vm.selectPermit(p), selected: vm.permit?.id == p.id, icon: p.expired ? Icons.warning_amber_rounded : Icons.assignment_outlined),
            ]),
            if (vm.permit != null) Padding(padding: const EdgeInsets.only(top: 6), child: Text(vm.permit!.title, style: const TextStyle(fontSize: 12, color: AegisTheme.textSecondary))),
          ],
          const SizedBox(height: 10),
          const Text('Equipment', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: AegisTheme.textMuted)),
          const SizedBox(height: 6),
          Wrap(spacing: 8, runSpacing: 8, children: [for (final a in vm.assets.take(6)) _chip(a, () => vm.selectAsset(a), selected: vm.asset == a)]),
        ],
      ]),
    );
  }
}

class _Empty extends StatelessWidget {
  final AskViewModel vm;
  final void Function([String?]) onPick;
  const _Empty({required this.vm, required this.onPick});

  @override
  Widget build(BuildContext context) {
    return ListView(padding: const EdgeInsets.all(20), children: [
      const SizedBox(height: 8),
      const Icon(Icons.manage_search_rounded, size: 44, color: AegisTheme.textMuted),
      const SizedBox(height: 12),
      const Center(child: Text('Ask about a procedure, a permit or a job', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AegisTheme.textPrimary))),
      const SizedBox(height: 6),
      const Center(
        child: Text('Type it, or tap the microphone and say it. You get the matching documents first, then the answer with its sources.',
            textAlign: TextAlign.center, style: TextStyle(fontSize: 13, height: 1.35, color: AegisTheme.textSecondary)),
      ),
      const SizedBox(height: 20),
      Wrap(spacing: 8, runSpacing: 8, children: [for (final s in vm.suggestions) _chip(s, () => onPick(s))]),
      const SizedBox(height: 20),
      const Text('The answer never says work is safe. Open conflicts from the safety rules are always shown, and a permit that has expired is called out.',
          style: TextStyle(fontSize: 12, height: 1.35, color: AegisTheme.textMuted)),
    ]);
  }
}

// ---------------------------------------------------------------- conversation

class _Conversation extends StatelessWidget {
  final AskViewModel vm;
  final ScrollController controller;
  final Map<String, GlobalKey> keys;
  const _Conversation({required this.vm, required this.controller, required this.keys});

  @override
  Widget build(BuildContext context) {
    return ListView(
      controller: controller,
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
      children: [for (final e in vm.entries) _EntryView(key: keys.putIfAbsent(e.id, () => GlobalKey()), vm: vm, e: e)],
    );
  }
}

class _EntryView extends StatelessWidget {
  final AskViewModel vm;
  final AskEntry e;
  const _EntryView({super.key, required this.vm, required this.e});

  @override
  Widget build(BuildContext context) {
    final r = e.result;
    return Padding(
      padding: const EdgeInsets.only(bottom: 18),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Align(
          alignment: Alignment.centerRight,
          child: Container(
            constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.82),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(color: AegisTheme.amberAccent.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(16), border: Border.all(color: AegisTheme.amberAccent.withValues(alpha: 0.4))),
            child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Text(e.question, style: const TextStyle(fontSize: 14, height: 1.3, color: AegisTheme.textPrimary)),
              if (e.permit != null || e.asset != null)
                Padding(padding: const EdgeInsets.only(top: 4), child: Text([if (e.permit != null) e.permit!.id, if (e.asset != null) e.asset!].join(' · '), style: const TextStyle(fontSize: 11, color: AegisTheme.textMuted))),
            ]),
          ),
        ),
        const SizedBox(height: 10),
        if (r?.permitAlert != null) _Alert(icon: Icons.block, text: r!.permitAlert!, color: AegisTheme.alertRed),
        if (e.searching && e.docs.isEmpty) const _Working(text: 'Searching the documents…') else if (e.docs.isNotEmpty) _Docs(vm: vm, docs: e.docs),
        if (r != null && r.verdicts.isNotEmpty) _Verdicts(verdicts: r.verdicts),
        if (e.answering) const Padding(padding: EdgeInsets.only(top: 6), child: _Working(text: 'Writing the answer from those documents…')),
        if (e.error != null) _Failure(message: e.error!, retryable: e.retryable, onRetry: () => vm.retry(e)),
        if (r != null) _Answer(vm: vm, e: e, r: r),
      ]),
    );
  }
}

class _Working extends StatelessWidget {
  final String text;
  const _Working({required this.text});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: [
        const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2, color: AegisTheme.amberAccent)),
        const SizedBox(width: 10),
        Expanded(child: Text(text, style: const TextStyle(fontSize: 12, color: AegisTheme.textSecondary))),
      ]),
    );
  }
}

class _Alert extends StatelessWidget {
  final IconData icon;
  final String text;
  final Color color;
  const _Alert({required this.icon, required this.text, required this.color});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(12), border: Border.all(color: color.withValues(alpha: 0.6))),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(icon, size: 18, color: color),
          const SizedBox(width: 8),
          Expanded(child: Text(text, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, height: 1.3, color: color))),
        ]),
      ),
    );
  }
}

class _Failure extends StatelessWidget {
  final String message;
  final bool retryable;
  final VoidCallback onRetry;
  const _Failure({required this.message, required this.retryable, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _Alert(icon: Icons.error_outline, text: message, color: AegisTheme.alertRed),
      if (retryable) TextButton.icon(onPressed: onRetry, icon: const Icon(Icons.refresh, size: 16, color: AegisTheme.amberAccent), label: const Text('Try again', style: TextStyle(color: AegisTheme.amberAccent))),
    ]);
  }
}

/// The rule engine's open conflicts, in the rules' own words. Never the model's.
class _Verdicts extends StatelessWidget {
  final List<RuleVerdict> verdicts;
  const _Verdicts({required this.verdicts});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: AegisTheme.alertRed.withValues(alpha: 0.10), borderRadius: BorderRadius.circular(12), border: Border.all(color: AegisTheme.alertRed.withValues(alpha: 0.5))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(Icons.shield_outlined, size: 16, color: AegisTheme.alertRed),
          SizedBox(width: 6),
          Expanded(child: Text('Open conflicts (from the safety rules)', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: AegisTheme.alertRed))),
        ]),
        const SizedBox(height: 6),
        for (final v in verdicts.take(4))
          Padding(
            padding: const EdgeInsets.only(bottom: 3),
            child: Text('${v.ruleId} · ${v.severity} · ${v.title} (${v.status})', style: const TextStyle(fontSize: 12, height: 1.3, color: AegisTheme.textPrimary)),
          ),
        const Text('Open until someone verifies them in the field.', style: TextStyle(fontSize: 11, color: AegisTheme.textMuted)),
      ]),
    );
  }
}

class _Docs extends StatelessWidget {
  final AskViewModel vm;
  final List<DocHit> docs;
  const _Docs({required this.vm, required this.docs});

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('${docs.length} matching document${docs.length == 1 ? '' : 's'}', style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: AegisTheme.textMuted)),
      const SizedBox(height: 6),
      SizedBox(
        height: 108,
        child: ListView(scrollDirection: Axis.horizontal, children: [for (final d in docs) _DocCard(vm: vm, d: d)]),
      ),
      const SizedBox(height: 8),
    ]);
  }
}

class _DocCard extends StatelessWidget {
  final AskViewModel vm;
  final DocHit d;
  const _DocCard({required this.vm, required this.d});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: '${d.sourceId}, ${d.heading}',
      child: InkWell(
        onTap: () => showDocSection(context, vm, d.chunkId, d.sourceId),
        borderRadius: BorderRadius.circular(12),
        child: Container(
          width: 220,
          margin: const EdgeInsets.only(right: 10),
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(color: AegisTheme.surfaceVariant, borderRadius: BorderRadius.circular(12), border: Border.all(color: AegisTheme.cardBorder)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              const Icon(Icons.description_outlined, size: 14, color: AegisTheme.amberAccent),
              const SizedBox(width: 6),
              Expanded(child: Text(d.sourceId, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: AegisTheme.amberAccent))),
            ]),
            if (d.heading.isNotEmpty) Text(d.heading, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: AegisTheme.textPrimary)),
            const SizedBox(height: 4),
            Expanded(child: Text(d.snippet, overflow: TextOverflow.fade, style: const TextStyle(fontSize: 11, height: 1.3, color: AegisTheme.textSecondary))),
          ]),
        ),
      ),
    );
  }
}

class _Answer extends StatelessWidget {
  final AskViewModel vm;
  final AskEntry e;
  final QueryResult r;
  const _Answer({required this.vm, required this.e, required this.r});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: AegisTheme.surface, borderRadius: BorderRadius.circular(14), border: Border.all(color: AegisTheme.cardBorder)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SelectableText(r.answer, style: const TextStyle(fontSize: 15, height: 1.4, color: AegisTheme.textPrimary)),
        if (r.steps.isNotEmpty) ...[
          const SizedBox(height: 12),
          const Text('Steps', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: AegisTheme.textMuted)),
          const SizedBox(height: 4),
          for (var i = 0; i < r.steps.length; i++)
            InkWell(
              onTap: () => vm.toggleStep(e, i),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 5),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Icon(e.doneSteps.contains(i) ? Icons.check_circle : Icons.radio_button_unchecked, size: 20, color: e.doneSteps.contains(i) ? AegisTheme.successGreen : AegisTheme.textMuted),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text('${i + 1}. ${r.steps[i]}',
                        style: TextStyle(fontSize: 14, height: 1.35, color: e.doneSteps.contains(i) ? AegisTheme.textMuted : AegisTheme.textPrimary, decoration: e.doneSteps.contains(i) ? TextDecoration.lineThrough : null)),
                  ),
                ]),
              ),
            ),
        ],
        if (r.cautions.isNotEmpty) ...[
          const SizedBox(height: 10),
          for (final c in r.cautions)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Icon(Icons.warning_amber_rounded, size: 16, color: AegisTheme.amberAccent),
                const SizedBox(width: 8),
                Expanded(child: Text(c, style: const TextStyle(fontSize: 13, height: 1.3, fontWeight: FontWeight.w600, color: AegisTheme.amberAccent))),
              ]),
            ),
        ],
        if (r.confidenceNote != null && r.confidenceNote!.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: Text(r.confidenceNote!, style: const TextStyle(fontSize: 12, fontStyle: FontStyle.italic, color: AegisTheme.textSecondary))),
        if (r.citations.isNotEmpty) ...[
          const SizedBox(height: 12),
          const Text('Sources (tap to read)', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: AegisTheme.textMuted)),
          const SizedBox(height: 6),
          Wrap(spacing: 8, runSpacing: 8, children: [for (final c in r.citations) _chip(c.title, () => showDocSection(context, vm, c.chunkId, c.sourceId), icon: Icons.menu_book_outlined)]),
        ],
        const SizedBox(height: 8),
        Text('${r.fallback ? 'Records only · ' : ''}${(r.latencyMs / 1000).toStringAsFixed(1)} s', style: const TextStyle(fontSize: 10, color: AegisTheme.textMuted)),
      ]),
    );
  }
}

/// A source opened in full, so the worker can read the exact wording.
Future<void> showDocSection(BuildContext context, AskViewModel vm, String chunkId, String title) {
  return showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    backgroundColor: AegisTheme.surface,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
    builder: (_) => DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.6,
      maxChildSize: 0.92,
      builder: (context, controller) => FutureBuilder<DocSection>(
        future: vm.section(chunkId),
        builder: (context, snap) {
          return ListView(controller: controller, padding: const EdgeInsets.all(20), children: [
            Row(children: [
              Expanded(child: Text(snap.data?.title ?? title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: AegisTheme.amberAccent))),
              IconButton(onPressed: () => Navigator.pop(context), icon: const Icon(Icons.close, color: AegisTheme.textMuted), tooltip: 'Close'),
            ]),
            const Divider(color: AegisTheme.cardBorder),
            if (snap.connectionState != ConnectionState.done)
              const Padding(padding: EdgeInsets.all(24), child: Center(child: BatonLoader(height: 48)))
            else if (snap.hasError)
              const Text('Could not open this document. Check the connection and try again.', style: TextStyle(color: AegisTheme.alertRed))
            else ...[
              SelectableText(snap.data!.text, style: const TextStyle(fontSize: 15, height: 1.5, color: AegisTheme.textPrimary)),
              const SizedBox(height: 14),
              Text('${snap.data!.docType.isEmpty ? snap.data!.sourceType : snap.data!.docType} · exact wording from the document', style: const TextStyle(fontSize: 11, color: AegisTheme.textMuted)),
            ],
          ]);
        },
      ),
    ),
  );
}

// ---------------------------------------------------------------- input

class _InputBar extends StatelessWidget {
  final AskViewModel vm;
  final TextEditingController controller;
  final bool isOnline;
  final void Function([String?]) onSend;
  const _InputBar({required this.vm, required this.controller, required this.isOnline, required this.onSend});

  @override
  Widget build(BuildContext context) {
    final recording = vm.mic == MicState.recording;
    final busy = vm.mic == MicState.transcribing;
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
      decoration: const BoxDecoration(color: AegisTheme.surface, border: Border(top: BorderSide(color: AegisTheme.cardBorder))),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        if (!isOnline) const Padding(padding: EdgeInsets.only(bottom: 8), child: Text('You are offline. Questions need a connection to the plant documents.', style: TextStyle(fontSize: 12, color: AegisTheme.amberAccent))),
        if (vm.micNotice != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(vm.micNotice!, style: const TextStyle(fontSize: 12, color: AegisTheme.amberAccent))),
        Row(children: [
          Semantics(
            button: true,
            label: recording ? 'Stop and ask' : 'Speak your question',
            child: InkWell(
              onTap: (isOnline && !busy) ? vm.toggleMic : null,
              customBorder: const CircleBorder(),
              child: Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(shape: BoxShape.circle, color: recording ? AegisTheme.alertRed : AegisTheme.amberAccent, boxShadow: recording ? [BoxShadow(color: AegisTheme.alertRed.withValues(alpha: 0.5), blurRadius: 12, spreadRadius: 2)] : null),
                child: busy
                    ? const Padding(padding: EdgeInsets.all(14), child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black))
                    : Icon(recording ? Icons.stop_rounded : Icons.mic, color: recording ? Colors.white : Colors.black),
              ),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: TextField(
              controller: controller,
              enabled: isOnline && !recording,
              minLines: 1,
              maxLines: 3,
              maxLength: 500,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => onSend(),
              style: const TextStyle(fontSize: 15, color: AegisTheme.textPrimary),
              decoration: InputDecoration(
                hintText: recording ? 'Listening… tap stop when done' : (busy ? 'Reading what you said…' : 'Ask about a procedure or your job'),
                counterText: '',
                contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              ),
            ),
          ),
          const SizedBox(width: 8),
          IconButton.filled(
            onPressed: isOnline ? () => onSend() : null,
            style: IconButton.styleFrom(backgroundColor: AegisTheme.amberAccent, foregroundColor: Colors.black, minimumSize: const Size(48, 48)),
            icon: const Icon(Icons.arrow_upward_rounded),
            tooltip: 'Ask',
          ),
        ]),
      ]),
    );
  }
}

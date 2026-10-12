import 'package:flutter/material.dart';
import '../../../ui/core/theme.dart';
import '../report_view_model.dart';
import '../widgets/speech_mic_button.dart';
import '../widgets/glance_extraction_card.dart';

class ReportScreen extends StatefulWidget {
  final ReportViewModel viewModel;
  final bool isOnline;

  const ReportScreen({
    super.key,
    required this.viewModel,
    required this.isOnline,
  });

  @override
  State<ReportScreen> createState() => _ReportScreenState();
}

class _ReportScreenState extends State<ReportScreen> {
  final TextEditingController _textController = TextEditingController();
  bool _isEditingInline = false;

  @override
  void dispose() {
    _textController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.viewModel,
      builder: (context, _) {
        final vm = widget.viewModel;

        return Scaffold(
          backgroundColor: AegisTheme.background,
          body: SafeArea(
            child: Stack(
              fit: StackFit.expand,
              children: [
                Column(
                  children: [
                    if (vm.state == ReportState.idle)
                      Align(
                        alignment: Alignment.topRight,
                        child: Padding(
                          padding: const EdgeInsets.only(top: 8, right: 16),
                          child: IconButton(
                            icon: const Icon(Icons.keyboard_outlined, color: AegisTheme.textMuted, size: 24),
                            tooltip: 'Type observation',
                            onPressed: () {
                              _textController.text = '';
                              setState(() {
                                _isEditingInline = true;
                              });
                              vm.openKeyboardInput();
                            },
                          ),
                        ),
                      ),

                    // Middle Section: Transcript Display
                    Expanded(
                      child: Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
                        child: _buildMiddleArea(vm),
                      ),
                    ),

                    // Lower Section: State Controls
                    Padding(
                      padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
                      child: _buildLowerControls(vm),
                    ),
                  ],
                ),

                // Save overlay: follows the real calls (saving, saved, syncing, outcome).
                if (vm.state == ReportState.saved)
                  Positioned.fill(child: _SubmitOverlay(phase: vm.submitPhase, conflicts: vm.submitConflicts)),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _buildMiddleArea(ReportViewModel vm) {
    if (vm.state == ReportState.idle) {
      return const SizedBox.shrink();
    }

    if (vm.state == ReportState.listening) {
      final lines = vm.transcript.split('\n');
      return Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (vm.activeSpeechPath == SpeechPath.cloud)
            const Text(
              'Listening...',
              style: TextStyle(
                fontSize: 22,
                fontWeight: FontWeight.w700,
                color: AegisTheme.textPrimary,
              ),
            )
          else
            for (int i = 0; i < lines.length; i++)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Text(
                  lines[i],
                  style: TextStyle(
                    fontSize: 22,
                    height: 1.3,
                    fontWeight: FontWeight.w700,
                    color: (i == lines.length - 1)
                        ? AegisTheme.textPrimary
                        : AegisTheme.textSecondary.withValues(alpha: 0.6),
                  ),
                ),
              ),
        ],
      );
    }

    if (vm.state == ReportState.reviewing) {
      if (vm.isTranscribingCloud) {
        return Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Container(
                  width: 10,
                  height: 10,
                  decoration: const BoxDecoration(
                    shape: BoxShape.circle,
                    color: AegisTheme.amberAccent,
                  ),
                ),
                const SizedBox(width: 12),
                const Text(
                  'Transcribing...',
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w700,
                    color: AegisTheme.amberAccent,
                  ),
                ),
              ],
            ),
          ],
        );
      }

      if (vm.cloudErrorNotice != null) {
        return Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              vm.cloudErrorNotice!,
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w600,
                color: AegisTheme.textPrimary,
              ),
            ),
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                ElevatedButton.icon(
                  onPressed: vm.retryCloudTranscription,
                  style: ElevatedButton.styleFrom(
                    minimumSize: const Size(120, 48),
                    backgroundColor: AegisTheme.amberAccent,
                  ),
                  icon: const Icon(Icons.refresh_rounded, size: 18, color: Colors.black),
                  label: const Text('Retry', style: TextStyle(color: Colors.black)),
                ),
                const SizedBox(width: 12),
                OutlinedButton.icon(
                  onPressed: () {
                    _textController.text = '';
                    setState(() {
                      _isEditingInline = true;
                    });
                  },
                  style: OutlinedButton.styleFrom(
                    minimumSize: const Size(120, 48),
                    side: const BorderSide(color: AegisTheme.cardBorder),
                  ),
                  icon: const Icon(Icons.keyboard_outlined, size: 18, color: AegisTheme.textPrimary),
                  label: const Text('Type', style: TextStyle(color: AegisTheme.textPrimary)),
                ),
              ],
            ),
          ],
        );
      }

      if (_isEditingInline) {
        return SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              TextField(
                controller: _textController,
                maxLines: 4,
                keyboardType: TextInputType.text,
                textInputAction: TextInputAction.done,
                autofocus: true,
                style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w600, color: AegisTheme.textPrimary),
                decoration: const InputDecoration(
                  hintText: 'Type field observation...',
                  border: InputBorder.none,
                ),
                onChanged: (text) {
                  vm.updateTranscript(text);
                },
                onSubmitted: (_) => setState(() => _isEditingInline = false),
              ),
              const SizedBox(height: 8),
              // Without this the extracted asset and state stay hidden until the note is submitted.
              OutlinedButton.icon(
                onPressed: _textController.text.trim().isEmpty
                    ? null
                    : () {
                        FocusScope.of(context).unfocus();
                        setState(() => _isEditingInline = false);
                      },
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size(0, 48),
                  side: const BorderSide(color: AegisTheme.amberAccent),
                ),
                icon: const Icon(Icons.fact_check_outlined, size: 18, color: AegisTheme.amberAccent),
                label: const Text('Check what was read', style: TextStyle(color: AegisTheme.amberAccent)),
              ),
            ],
          ),
        );
      }

      return SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Original | English Translation Toggle
            if (vm.hasTranslation) ...[
              Row(
                children: [
                  SegmentedButton<bool>(
                    segments: const [
                      ButtonSegment(value: false, label: Text('Original', style: TextStyle(fontSize: 11))),
                      ButtonSegment(value: true, label: Text('English', style: TextStyle(fontSize: 11))),
                    ],
                    selected: {vm.showEnglish},
                    onSelectionChanged: (set) {
                      vm.toggleTranslationLanguage(set.first);
                    },
                    style: ButtonStyle(
                      minimumSize: WidgetStateProperty.all(const Size(0, 32)),
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      backgroundColor: WidgetStateProperty.resolveWith((states) {
                        if (states.contains(WidgetState.selected)) {
                          return AegisTheme.amberAccent;
                        }
                        return AegisTheme.surfaceVariant;
                      }),
                      foregroundColor: WidgetStateProperty.resolveWith((states) {
                        if (states.contains(WidgetState.selected)) {
                          return Colors.black;
                        }
                        return AegisTheme.textSecondary;
                      }),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
            ],

            GestureDetector(
              onTap: () {
                _textController.text = vm.transcript;
                setState(() {
                  _isEditingInline = true;
                });
              },
              child: Text(
                vm.transcript.isEmpty ? 'Tap to enter transcript...' : vm.transcript,
                style: const TextStyle(
                  fontSize: 20,
                  height: 1.3,
                  fontWeight: FontWeight.w700,
                  color: AegisTheme.textPrimary,
                ),
              ),
            ),
            const SizedBox(height: 16),
            GlanceExtractionCard(
              isExtracting: vm.isExtracting,
              extractionResult: vm.extractionResult,
              knownAssets: vm.knownAssets,
              onSelectAssetTag: vm.selectAssetTag,
              onSelectState: vm.selectAssetState,
            ),
          ],
        ),
      );
    }

    return const SizedBox.shrink();
  }

  Widget _buildLowerControls(ReportViewModel vm) {
    if (vm.state == ReportState.idle) {
      return SpeechMicButton(
        isListening: false,
        soundLevel: 0.0,
        listenSeconds: 0,
        onTap: vm.startListening,
      );
    }

    if (vm.state == ReportState.listening) {
      return SpeechMicButton(
        isListening: true,
        soundLevel: vm.soundLevel,
        listenSeconds: vm.listenSeconds,
        onTap: vm.stopListening,
      );
    }

    if (vm.state == ReportState.reviewing && !vm.isTranscribingCloud && vm.cloudErrorNotice == null) {
      return Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          ElevatedButton(
            onPressed: () {
              setState(() => _isEditingInline = false);
              vm.submit(isOnline: widget.isOnline);
            },
            child: Text(vm.extractionResult?.facts.any((f) => (f.assetTag ?? '').isNotEmpty) ?? false
                ? 'Submit observation'
                : 'Submit without an asset tag'),
          ),
          const SizedBox(height: 8),
          TextButton(
            onPressed: () {
              setState(() {
                _isEditingInline = false;
              });
              vm.redo();
            },
            child: const Text(
              'Redo',
              style: TextStyle(color: AegisTheme.textMuted, fontSize: 14),
            ),
          ),
        ],
      );
    }

    return const SizedBox.shrink();
  }
}

class _SubmitOverlay extends StatelessWidget {
  final SubmitPhase phase;
  final int conflicts;
  const _SubmitOverlay({required this.phase, required this.conflicts});

  @override
  Widget build(BuildContext context) {
    final reduce = MediaQuery.of(context).disableAnimations;
    final busy = phase == SubmitPhase.reading || phase == SubmitPhase.saving || phase == SubmitPhase.syncing;
    final Color color;
    final IconData icon;
    final String title;
    final String? detail;
    switch (phase) {
      case SubmitPhase.reading:
        color = AegisTheme.amberAccent;
        icon = Icons.auto_awesome;
        title = 'Reading your note…';
        detail = 'On-device AI is checking the asset and state. This can take a few seconds.';
      case SubmitPhase.saving:
        color = AegisTheme.amberAccent;
        icon = Icons.save_outlined;
        title = 'Saving…';
        detail = null;
      case SubmitPhase.saved:
        color = AegisTheme.successGreen;
        icon = Icons.check;
        title = 'Saved on this device';
        detail = null;
      case SubmitPhase.syncing:
        color = AegisTheme.amberAccent;
        icon = Icons.cloud_upload_outlined;
        title = 'Syncing to the cloud…';
        detail = 'Saved on this device';
      case SubmitPhase.synced:
        color = AegisTheme.successGreen;
        icon = Icons.cloud_done;
        title = 'Saved and synced';
        detail = null;
      case SubmitPhase.flagged:
        color = AegisTheme.alertRed;
        icon = Icons.warning_amber_rounded;
        title = 'Synced: safety conflict flagged';
        detail = '$conflicts conflict${conflicts == 1 ? '' : 's'} found by the server. A supervisor must review it on the dashboard.';
      case SubmitPhase.queued:
        color = AegisTheme.amberAccent;
        icon = Icons.cloud_off;
        title = 'Saved. Will sync when online';
        detail = 'Your note is safe on this device.';
    }
    return Semantics(
      liveRegion: true,
      label: title,
      child: Container(
        width: double.infinity,
        color: AegisTheme.background.withValues(alpha: 0.96),
        padding: const EdgeInsets.symmetric(horizontal: 32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            SizedBox(
              width: 104,
              height: 104,
              child: Stack(
                alignment: Alignment.center,
                children: [
                  if (busy)
                    SizedBox(
                      width: 104,
                      height: 104,
                      child: CircularProgressIndicator(strokeWidth: 3, color: color),
                    ),
                  TweenAnimationBuilder<double>(
                    key: ValueKey(phase),
                    tween: Tween(begin: reduce ? 1 : 0.6, end: 1),
                    duration: Duration(milliseconds: reduce ? 0 : 320),
                    curve: Curves.easeOutBack,
                    builder: (_, v, child) => Transform.scale(scale: v, child: child),
                    child: Container(
                      width: busy ? 72 : 96,
                      height: busy ? 72 : 96,
                      decoration: BoxDecoration(shape: BoxShape.circle, color: busy ? color.withValues(alpha: 0.15) : color),
                      child: Icon(icon, size: busy ? 32 : 48, color: busy ? color : Colors.white),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 24),
            Text(
              title,
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: AegisTheme.textPrimary),
            ),
            if (detail != null) ...[
              const SizedBox(height: 8),
              Text(
                detail,
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 13, height: 1.35, color: AegisTheme.textSecondary),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

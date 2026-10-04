import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../../../core/theme.dart';
import '../view_models/gemma_assistant_view_model.dart';
import '../../../../data/models/chat_message_model.dart';

class GemmaAssistantScreen extends StatefulWidget {
  final GemmaAssistantViewModel viewModel;

  const GemmaAssistantScreen({
    super.key,
    required this.viewModel,
  });

  @override
  State<GemmaAssistantScreen> createState() => _GemmaAssistantScreenState();
}

class _GemmaAssistantScreenState extends State<GemmaAssistantScreen> {
  @override
  void initState() {
    super.initState();
    widget.viewModel.initializeWelcome();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.viewModel,
      builder: (context, _) {
        return Column(
          children: [
            // Top Section Header
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              color: AegisTheme.surfaceVariant,
              child: Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(6),
                    decoration: BoxDecoration(
                      color: AegisTheme.safetyOrange.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: const Icon(
                      Icons.smart_toy_outlined,
                      color: AegisTheme.safetyOrange,
                      size: 18,
                    ),
                  ),
                  const SizedBox(width: 10),
                  const Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Gemma 2B Knowledge & Shift Assistant',
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w800,
                            color: AegisTheme.textPrimary,
                          ),
                        ),
                        Text(
                          'Multilingual RAG • Plant SOPs • Handover Log Memory',
                          style: TextStyle(fontSize: 10, color: AegisTheme.textMuted),
                        ),
                      ],
                    ),
                  ),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: AegisTheme.industrialCyan.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: const Text(
                      'Edge INT4',
                      style: TextStyle(
                        fontSize: 10,
                        fontWeight: FontWeight.w800,
                        color: AegisTheme.industrialCyan,
                      ),
                    ),
                  ),
                ],
              ),
            ),

            // Quick Prompt Suggestions
            Container(
              height: 42,
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: ListView.separated(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                scrollDirection: Axis.horizontal,
                itemCount: widget.viewModel.promptChips.length,
                separatorBuilder: (_, __) => const SizedBox(width: 8),
                itemBuilder: (context, index) {
                  final prompt = widget.viewModel.promptChips[index];
                  return ActionChip(
                    backgroundColor: AegisTheme.surfaceVariant,
                    side: const BorderSide(color: AegisTheme.cardBorder),
                    label: Text(
                      prompt['label']!,
                      style: const TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                        color: AegisTheme.industrialCyan,
                      ),
                    ),
                    onPressed: () => widget.viewModel.selectPrompt(index),
                  );
                },
              ),
            ),

            // Chat Message List
            Expanded(
              child: ListView.separated(
                controller: widget.viewModel.scrollController,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                itemCount: widget.viewModel.messages.length,
                separatorBuilder: (_, __) => const SizedBox(height: 12),
                itemBuilder: (context, index) {
                  final msg = widget.viewModel.messages[index];
                  return _buildMessageBubble(msg);
                },
              ),
            ),

            // Thinking Indicator
            if (widget.viewModel.isThinking)
              Container(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: const Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(strokeWidth: 2, color: AegisTheme.industrialCyan),
                    ),
                    SizedBox(width: 10),
                    Text(
                      'Gemma is checking shift logs & offshore SOPs...',
                      style: TextStyle(fontSize: 11, color: AegisTheme.textMuted),
                    ),
                  ],
                ),
              ),

            // Bottom Input Bar
            Container(
              padding: const EdgeInsets.all(12),
              decoration: const BoxDecoration(
                color: AegisTheme.surface,
                border: Border(top: BorderSide(color: AegisTheme.cardBorder)),
              ),
              child: SafeArea(
                child: Row(
                  children: [
                    IconButton(
                      icon: Icon(
                        widget.viewModel.isVoiceActive ? Icons.mic : Icons.mic_none,
                        color: widget.viewModel.isVoiceActive
                            ? AegisTheme.alertRed
                            : AegisTheme.safetyOrange,
                      ),
                      tooltip: 'Voice Input',
                      onPressed: widget.viewModel.toggleVoice,
                    ),
                    Expanded(
                      child: TextField(
                        controller: widget.viewModel.textController,
                        style: const TextStyle(fontSize: 14, color: AegisTheme.textPrimary),
                        decoration: const InputDecoration(
                          hintText: 'Ask in English, Tamil, Malay, Hindi...',
                          contentPadding: EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                        ),
                        onSubmitted: (_) => widget.viewModel.sendQuery(),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Container(
                      decoration: BoxDecoration(
                        color: AegisTheme.safetyOrange,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: IconButton(
                        icon: const Icon(Icons.send, color: Colors.white, size: 20),
                        onPressed: widget.viewModel.sendQuery,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _buildMessageBubble(ChatMessageModel msg) {
    final timeStr = DateFormat('HH:mm').format(msg.timestamp);

    if (msg.isUser) {
      return Align(
        alignment: Alignment.centerRight,
        child: Container(
          constraints: const BoxConstraints(maxWidth: 380),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: AegisTheme.safetyOrange.withValues(alpha: 0.2),
            borderRadius: BorderRadius.circular(12).copyWith(bottomRight: Radius.zero),
            border: Border.all(color: AegisTheme.safetyOrange.withValues(alpha: 0.4)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                msg.message,
                style: const TextStyle(fontSize: 13, color: AegisTheme.textPrimary),
              ),
              const SizedBox(height: 4),
              Text(
                timeStr,
                style: const TextStyle(fontSize: 10, color: AegisTheme.textMuted),
              ),
            ],
          ),
        ),
      );
    }

    // Gemma Assistant Bubble
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 420),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: AegisTheme.surfaceVariant,
          borderRadius: BorderRadius.circular(12).copyWith(topLeft: Radius.zero),
          border: Border.all(
            color: msg.hasAlert
                ? AegisTheme.alertRed.withValues(alpha: 0.5)
                : AegisTheme.cardBorder,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.smart_toy, size: 16, color: AegisTheme.industrialCyan),
                const SizedBox(width: 6),
                const Text(
                  'Gemma 2B',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                    color: AegisTheme.industrialCyan,
                  ),
                ),
                if (msg.detectedLanguage != null && msg.detectedLanguage != 'en') ...[
                  const SizedBox(width: 8),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: AegisTheme.amberWarning.withValues(alpha: 0.2),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      'Language: ${msg.detectedLanguage!.toUpperCase()}',
                      style: const TextStyle(
                        fontSize: 9,
                        fontWeight: FontWeight.bold,
                        color: AegisTheme.amberWarning,
                      ),
                    ),
                  ),
                ],
                const Spacer(),
                Text(
                  timeStr,
                  style: const TextStyle(fontSize: 10, color: AegisTheme.textMuted),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              msg.message,
              style: const TextStyle(
                fontSize: 13,
                height: 1.45,
                color: AegisTheme.textPrimary,
              ),
            ),
            if (msg.citations.isNotEmpty) ...[
              const SizedBox(height: 10),
              const Divider(color: AegisTheme.cardBorder, height: 1),
              const SizedBox(height: 8),
              const Text(
                'GROUNDED EVIDENCE & CITATIONS:',
                style: TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.w800,
                  color: AegisTheme.textMuted,
                  letterSpacing: 0.5,
                ),
              ),
              const SizedBox(height: 6),
              Wrap(
                spacing: 6,
                runSpacing: 4,
                children: msg.citations.map((cite) {
                  return Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: const Color(0xFF0C131F),
                      borderRadius: BorderRadius.circular(4),
                      border: Border.all(color: AegisTheme.cardBorder),
                    ),
                    child: Text(
                      cite,
                      style: const TextStyle(
                        fontSize: 10,
                        fontWeight: FontWeight.w600,
                        color: Color(0xFF90CDF4),
                      ),
                    ),
                  );
                }).toList(),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

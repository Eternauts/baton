import 'package:flutter/material.dart';
import '../../../../data/models/chat_message_model.dart';
import '../../../../data/repositories/handover_repository.dart';

class GemmaAssistantViewModel extends ChangeNotifier {
  final HandoverRepository _repository;

  GemmaAssistantViewModel({required HandoverRepository repository})
      : _repository = repository;

  final TextEditingController textController = TextEditingController();
  final ScrollController scrollController = ScrollController();
  final List<ChatMessageModel> _messages = [];
  bool _isThinking = false;
  bool _isVoiceActive = false;

  List<ChatMessageModel> get messages => List.unmodifiable(_messages);
  bool get isThinking => _isThinking;
  bool get isVoiceActive => _isVoiceActive;

  /// Multilingual prompt chips for immediate testing
  final List<Map<String, String>> promptChips = [
    {
      'label': 'P-201B Pump & Seal Status?',
      'query': 'Has pump P-201B had any seal or vibration issues recently?',
      'lang': 'en',
    },
    {
      'label': 'P-201B Pam & Meterai (Malay)',
      'query': 'Bagi pam P-201B, apa isu meterai dan adakah selamat dihidupkan?',
      'lang': 'ms',
    },
    {
      'label': 'P-201B பம்ப் சீல் நிலை (Tamil)',
      'query': 'P-201B பம்ப் சீல் மற்றும் அதிர்வு நிலை என்ன? இயக்கலாமா?',
      'lang': 'ta',
    },
    {
      'label': 'T-310A Temp High Action?',
      'query': 'What is the current temperature of T-310A and what action is required?',
      'lang': 'en',
    },
    {
      'label': 'V-104 Active Isolation Permits?',
      'query': 'Is valve V-104 under active isolation permit?',
      'lang': 'en',
    },
  ];

  void initializeWelcome() {
    if (_messages.isNotEmpty) return;

    _messages.add(
      ChatMessageModel(
        id: 'welcome-1',
        sender: 'gemma',
        message: 'Hello! I am your Gemma 2B Shift Assistant. Ask me any question about current plant conditions, active handover logs, or safety SOPs in English, Malay, Tamil, Hindi, or your native language.',
        citations: ['KNOWLEDGE_BASE: Offshore Standard Operating Procedures', 'ACTIVE_LOGS: Last 12h Handover Records'],
        timestamp: DateTime.now(),
      ),
    );
  }

  void selectPrompt(int index) {
    if (index >= 0 && index < promptChips.length) {
      final query = promptChips[index]['query']!;
      textController.text = query;
      sendQuery();
    }
  }

  void toggleVoice() {
    _isVoiceActive = !_isVoiceActive;
    if (_isVoiceActive) {
      textController.text = 'Has pump P-201B had any seal or vibration issues recently?';
    }
    notifyListeners();
  }

  Future<void> sendQuery() async {
    final query = textController.text.trim();
    if (query.isEmpty) return;

    textController.clear();
    final userMsg = ChatMessageModel(
      id: DateTime.now().millisecondsSinceEpoch.toString(),
      sender: 'user',
      message: query,
      timestamp: DateTime.now(),
    );

    _messages.add(userMsg);
    _isThinking = true;
    notifyListeners();
    _scrollToBottom();

    // Fetch current active logs for RAG context
    final logs = await _repository.getObservations();

    // Query Gemma Multilingual RAG
    final gemmaResponse = await _repository.askAssistant(
      query: query,
      currentLogs: logs,
    );

    _messages.add(gemmaResponse);
    _isThinking = false;
    notifyListeners();
    _scrollToBottom();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (scrollController.hasClients) {
        scrollController.animateTo(
          scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  void dispose() {
    textController.dispose();
    scrollController.dispose();
    super.dispose();
  }
}

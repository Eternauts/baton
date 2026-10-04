/// Chat message for the Gemma multilingual shift assistant
class ChatMessageModel {
  final String id;
  final String sender; // 'user' or 'gemma'
  final String message;
  final String? detectedLanguage;
  final List<String> citations;
  final bool hasAlert;
  final DateTime timestamp;

  ChatMessageModel({
    required this.id,
    required this.sender,
    required this.message,
    this.detectedLanguage,
    this.citations = const [],
    this.hasAlert = false,
    required this.timestamp,
  });

  bool get isUser => sender == 'user';

  Map<String, dynamic> toMap() {
    return {
      'id': id,
      'sender': sender,
      'message': message,
      'detectedLanguage': detectedLanguage,
      'citations': citations,
      'hasAlert': hasAlert,
      'timestamp': timestamp.toIso8601String(),
    };
  }

  factory ChatMessageModel.fromMap(Map<String, dynamic> map) {
    return ChatMessageModel(
      id: map['id'] as String,
      sender: map['sender'] as String,
      message: map['message'] as String,
      detectedLanguage: map['detectedLanguage'] as String?,
      citations: List<String>.from(map['citations'] as List? ?? []),
      hasAlert: map['hasAlert'] as bool? ?? false,
      timestamp: DateTime.parse(map['timestamp'] as String),
    );
  }
}

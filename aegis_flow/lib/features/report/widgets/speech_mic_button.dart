import 'package:flutter/material.dart';
import '../../../ui/core/theme.dart';

class SpeechMicButton extends StatelessWidget {
  final bool isListening;
  final double soundLevel;
  final int listenSeconds;
  final VoidCallback onTap;

  const SpeechMicButton({
    super.key,
    required this.isListening,
    required this.soundLevel,
    required this.listenSeconds,
    required this.onTap,
  });

  String _formatTimer(int totalSecs) {
    final m = (totalSecs ~/ 60).toString().padLeft(2, '0');
    final s = (totalSecs % 60).toString().padLeft(2, '0');
    return '$m:$s';
  }

  @override
  Widget build(BuildContext context) {
    final disableAnim = MediaQuery.of(context).disableAnimations;
    final pulseScale = (isListening && !disableAnim)
        ? (1.0 + (soundLevel.clamp(0.0, 10.0) / 25.0))
        : 1.0;

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        GestureDetector(
          onTap: onTap,
          child: AnimatedContainer(
            duration: disableAnim ? Duration.zero : const Duration(milliseconds: 200),
            transform: Matrix4.diagonal3Values(pulseScale, pulseScale, 1.0),
            transformAlignment: Alignment.center,
            width: 96,
            height: 96,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: isListening ? AegisTheme.alertRed : AegisTheme.amberAccent,
              boxShadow: [
                BoxShadow(
                  color: (isListening ? AegisTheme.alertRed : AegisTheme.amberAccent)
                      .withValues(alpha: 0.4),
                  blurRadius: isListening ? 20 : 10,
                  spreadRadius: isListening ? 6 : 2,
                ),
              ],
            ),
            child: Icon(
              isListening ? Icons.stop_rounded : Icons.mic_rounded,
              color: Colors.black,
              size: 44,
            ),
          ),
        ),
        const SizedBox(height: 12),
        if (isListening)
          Text(
            _formatTimer(listenSeconds),
            style: const TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.bold,
              color: AegisTheme.alertRed,
              letterSpacing: 1.0,
            ),
          )
        else
          const Text(
            'Tap and describe what you see',
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w600,
              color: AegisTheme.textMuted,
            ),
          ),
      ],
    );
  }
}

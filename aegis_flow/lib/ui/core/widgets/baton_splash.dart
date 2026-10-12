import 'package:flutter/material.dart';
import 'baton_logo.dart';

/// Opening screen: the B draws itself on the brand navy (the same colour as the native launch screen, so
/// there is no flash between them), the sweep of light crosses it, then the wordmark rises in.
class BatonSplash extends StatefulWidget {
  const BatonSplash({super.key});

  @override
  State<BatonSplash> createState() => _BatonSplashState();
}

class _BatonSplashState extends State<BatonSplash> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1900));
  bool _started = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_started) return;
    _started = true;
    if (MediaQuery.of(context).disableAnimations) {
      _c.value = 1; // reduce motion: show the finished lockup
    } else {
      _c.forward();
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Baton',
      child: ColoredBox(
        color: BatonBrand.navy,
        child: Center(
          child: AnimatedBuilder(
            animation: _c,
            builder: (_, __) {
              final t = _c.value;
              final word = Curves.easeOutCubic.transform(((t - 0.62) / 0.38).clamp(0.0, 1.0));
              return Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  DrawnBatonMark(height: 132, t: t * 0.9), // 0.9 stops short of the loop's dim-out
                  const SizedBox(height: 28),
                  Opacity(
                    opacity: word,
                    child: Transform.translate(
                      offset: Offset(0, (1 - word) * 14),
                      child: const BatonWordmark(height: 34),
                    ),
                  ),
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}

import 'package:flutter/material.dart';

/// Baton brand assets. The mark is two layers (the cyan pipe and the white pipe) so it can be drawn
/// in, one pipe after the other, like a line filling.
class BatonBrand {
  static const Color navy = Color(0xFF082A57);
  static const String markCyan = 'assets/branding/baton_mark_cyan.png';
  static const String markWhite = 'assets/branding/baton_mark_white.png';
  static const String wordmark = 'assets/branding/baton_wordmark.png';
  static const double markAspect = 420 / 452; // width / height of the mark artwork
}

/// The static B mark.
class BatonMark extends StatelessWidget {
  final double height;
  const BatonMark({super.key, this.height = 28});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: height,
      width: height * BatonBrand.markAspect,
      child: Stack(fit: StackFit.expand, children: [
        Image.asset(BatonBrand.markCyan, fit: BoxFit.contain, filterQuality: FilterQuality.medium),
        Image.asset(BatonBrand.markWhite, fit: BoxFit.contain, filterQuality: FilterQuality.medium),
      ]),
    );
  }
}

/// The "Baton" wordmark in the provided typeface (white, for dark surfaces).
class BatonWordmark extends StatelessWidget {
  final double height;
  const BatonWordmark({super.key, this.height = 16});

  @override
  Widget build(BuildContext context) {
    return Image.asset(BatonBrand.wordmark, height: height, fit: BoxFit.contain, filterQuality: FilterQuality.medium);
  }
}

/// Mark and wordmark side by side, as one labelled element for screen readers.
class BatonLockup extends StatelessWidget {
  final double markHeight;
  const BatonLockup({super.key, this.markHeight = 26});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Baton',
      header: true,
      child: ExcludeSemantics(
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          BatonMark(height: markHeight),
          SizedBox(width: markHeight * 0.38),
          BatonWordmark(height: markHeight * 0.62),
        ]),
      ),
    );
  }
}

/// The B that draws itself: the cyan pipe fills from the top, the white pipe follows, then a band of
/// light sweeps across and it breathes before the next pass. Used while something loads.
/// With "reduce motion" on it shows the finished mark and does not move.
class BatonLoader extends StatefulWidget {
  final double height;
  final String? label;
  const BatonLoader({super.key, this.height = 64, this.label});

  @override
  State<BatonLoader> createState() => _BatonLoaderState();
}

class _BatonLoaderState extends State<BatonLoader> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 2600))..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final reduce = MediaQuery.of(context).disableAnimations;
    if (reduce) {
      _c.stop();
    } else if (!_c.isAnimating) {
      _c.repeat();
    }
    final mark = reduce
        ? BatonMark(height: widget.height)
        : AnimatedBuilder(animation: _c, builder: (_, __) => DrawnBatonMark(height: widget.height, t: _c.value));
    return Semantics(
      label: widget.label ?? 'Loading',
      liveRegion: true,
      child: ExcludeSemantics(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          mark,
          if (widget.label != null) ...[
            const SizedBox(height: 14),
            Text(widget.label!, style: const TextStyle(fontSize: 13, color: Color(0xFF94A3B8))),
          ],
        ]),
      ),
    );
  }
}

/// One frame of the drawn-in mark. [t] runs 0..1: cyan fills 0 to .32, white fills .28 to .6, a band of
/// light sweeps .55 to .9, and the mark dims slightly at the end so the loop restarts without a jump.
class DrawnBatonMark extends StatelessWidget {
  final double height;
  final double t;
  const DrawnBatonMark({super.key, required this.height, required this.t});

  double _p(double a, double b) => ((t - a) / (b - a)).clamp(0.0, 1.0);

  @override
  Widget build(BuildContext context) {
    final cyan = Curves.easeInOut.transform(_p(0.0, 0.32));
    final white = Curves.easeInOut.transform(_p(0.28, 0.6));
    final sweep = _p(0.55, 0.9);
    final fade = t > 0.92 ? 1 - (t - 0.92) / 0.08 * 0.75 : 1.0; // dims to 25% just before the loop restarts
    final width = height * BatonBrand.markAspect;

    Widget layer(String asset, double progress) => ClipRect(
          child: Align(
            alignment: Alignment.topCenter,
            heightFactor: progress,
            child: Image.asset(asset, height: height, width: width, fit: BoxFit.contain, filterQuality: FilterQuality.medium),
          ),
        );

    Widget mark = SizedBox(
      height: height,
      width: width,
      child: Stack(alignment: Alignment.topCenter, children: [
        layer(BatonBrand.markCyan, cyan),
        layer(BatonBrand.markWhite, white),
      ]),
    );

    if (sweep > 0 && sweep < 1) {
      final x = -0.6 + sweep * 2.2; // band centre travels left to right across the mark
      mark = ShaderMask(
        blendMode: BlendMode.srcATop,
        shaderCallback: (r) => LinearGradient(
          begin: Alignment(x - 0.35, -0.6),
          end: Alignment(x + 0.35, 0.6),
          colors: const [Color(0x00FFFFFF), Color(0x99FFFFFF), Color(0x00FFFFFF)],
        ).createShader(r),
        child: mark,
      );
    }
    return Opacity(opacity: fade.clamp(0.25, 1.0), child: mark);
  }
}

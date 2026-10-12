import 'package:flutter/material.dart';
import 'core/ai/on_device_ai_service.dart';
import 'core/data/handover_repository.dart';
import 'ui/core/theme.dart';
import 'ui/core/widgets/baton_splash.dart';
import 'ui/features/home/views/main_shell_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Initialize OnDeviceAiService in background after first frame
  OnDeviceAiService.instance.initializeInBackground();

  final repository = HandoverRepository();

  runApp(BatonApp(repository: repository));
}

class BatonApp extends StatefulWidget {
  final HandoverRepository repository;

  const BatonApp({
    super.key,
    required this.repository,
  });

  @override
  State<BatonApp> createState() => _BatonAppState();
}

class _BatonAppState extends State<BatonApp> {
  bool _splashVisible = true;
  bool _splashGone = false;

  @override
  void initState() {
    super.initState();
    // The app builds underneath from the start (data and the on-device model load meanwhile);
    // the splash only covers the first moments and then fades away.
    Future.delayed(const Duration(milliseconds: 2400), () {
      if (mounted) setState(() => _splashVisible = false);
    });
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Baton',
      debugShowCheckedModeBanner: false,
      theme: AegisTheme.darkTheme,
      home: Stack(
        children: [
          MainShellScreen(repository: widget.repository),
          if (!_splashGone)
            Positioned.fill(
              child: IgnorePointer(
                ignoring: !_splashVisible,
                child: AnimatedOpacity(
                  opacity: _splashVisible ? 1 : 0,
                  duration: const Duration(milliseconds: 450),
                  onEnd: () {
                    if (!_splashVisible && mounted) setState(() => _splashGone = true);
                  },
                  child: const BatonSplash(),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

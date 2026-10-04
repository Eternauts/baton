import 'package:flutter/material.dart';
import 'data/repositories/handover_repository.dart';
import 'ui/core/theme.dart';
import 'ui/features/home/views/main_shell_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final repository = HandoverRepository();

  runApp(AegisFlowApp(repository: repository));
}

class AegisFlowApp extends StatelessWidget {
  final HandoverRepository repository;

  const AegisFlowApp({
    super.key,
    required this.repository,
  });

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AEGIS Flow - Shift Handover Guardian',
      debugShowCheckedModeBanner: false,
      theme: AegisTheme.darkTheme,
      home: MainShellScreen(repository: repository),
    );
  }
}
